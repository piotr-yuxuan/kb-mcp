"""Settings: the site, where data lives, and what to download when no flag says.

They come in layers, each stronger than the last: the settings file, the environment,
then the flags given. Each layer gives entries, a value at a setting's path;
``settings_of`` merges them, a stronger value replacing a weaker one whole, a list
included, and builds ``Settings``, whose fields hold every rule of a value. Secrets come
from the environment alone. Where data may live is judged by ``unsafe_location``, once
the loader has resolved the data directory.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import reduce
from operator import getitem
from pathlib import Path
from types import NoneType
from typing import (
    TYPE_CHECKING,
    Annotated,
    Literal,
    TypeAliasType,
    Union,
    get_args,
    get_origin,
    override,
)
from urllib.parse import urlsplit

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, SecretStr, ValidationError
from pydantic_core import PydanticCustomError
from pydantic_settings import BaseSettings, SettingsConfigDict

from atlassian_offline_mcp.kernel.chunking import CHUNKINGS, Chunking
from atlassian_offline_mcp.kernel.content import MODEL_NAME, PROJECT_KEY, SPACE_KEY
from atlassian_offline_mcp.kernel.endpoint import endpoint_host, loopback

if TYPE_CHECKING:
    import re
    from collections.abc import Callable, Iterable, Mapping

    from pydantic_settings import PydanticBaseSettingsSource

DEFAULT_DATA_DIR = "~/atlassian-offline-mcp"
# The embedding model that indexes by meaning, as the endpoint names it. Chosen by plan
# 018 from published retrieval scores: the best in English, French not needed for now.
DEFAULT_MODEL = "qwen3-embedding:0.6b"
# The OpenAI-compatible API that embeds: Ollama on this machine, where it listens.
DEFAULT_EMBEDDING_URL = "http://127.0.0.1:11434/v1"
# How search ranks: by words, by meaning, or by both fused.
type SearchMode = Literal["lexical", "semantic", "hybrid"]
# Plan 011 found hybrid better than lexical with its in-process model; with the model of
# plan 018, hybrid neither beat lexical significantly nor held identifiers, so by the bar
# set before that run, and the user's word, words stay the default.
DEFAULT_SEARCH_MODE: SearchMode = "lexical"
# How index cuts documents into the pieces it embeds: 011's sections, until plan 019's
# evaluation decides by its rule.
DEFAULT_CHUNKING: Chunking = "sections"
# The layer of a setting that no layer gives, as it is named.
DEFAULT_LAYER = "default"
# The settings that the file held at its top before plan 015, and their tables now.
MOVED = {"spaces": "[sources.confluence]", "projects": "[sources.jira]"}
# The type of every refusal of a value by the settings' rules.
RULE = "setting"
# What telemetry's endpoint must be, since what it is sent holds titles and queries.
TELEMETRY_ENDPOINT = (
    "an http address of this machine, with a port and no path, such as"
    " http://127.0.0.1:4318; write 127.0.0.1 for localhost"
)
# Folders that may be synchronised to a cloud, under the home directory or by name.
SYNCED_UNDER_HOME = (
    Path("Library/Mobile Documents"),
    Path("Library/CloudStorage"),
    Path("Desktop"),
    Path("Documents"),
)
SYNCED_NAMES = ("Dropbox", "OneDrive", "Google Drive", "GoogleDrive")


class SettingsError(ValueError):
    """A setting that cannot be used; the message names it and its layer, never its value."""


def matching(pattern: re.Pattern[str], expected: str) -> AfterValidator:
    """Check a text by one of the kernel's patterns, whole; refuse another as ``expected``."""

    def check(value: str) -> str:
        if not pattern.fullmatch(value):
            raise PydanticCustomError(RULE, expected)
        return value

    return AfterValidator(check)


def site_address(value: str) -> str:
    """Give a site's address as ``https://<host>``; refuse one that is not a host alone."""
    try:
        parts = urlsplit(value)
        usable = (
            parts.scheme == "https"
            and bool(parts.hostname)
            and parts.netloc.lower() == parts.hostname
            and parts.path in {"", "/"}
        )
    except ValueError:  # such as an unclosed [ in the host
        usable = False
    if not usable:
        message = "an https address with a host name alone, such as https://x.atlassian.net"
        raise PydanticCustomError(RULE, message)
    return f"https://{parts.hostname}"


def endpoint_address(value: str) -> str:
    """Give an embedding endpoint's address without its trailing slash; refuse another."""
    if endpoint_host(value) is None:
        message = "an http or https address with a host, such as http://127.0.0.1:11434/v1"
        raise PydanticCustomError(RULE, message)
    return value.rstrip("/")


def telemetry_address(value: str) -> str:
    """Give telemetry's endpoint as ``http://<address>:<port>``; refuse another.

    It is an embedding endpoint's address, over http, to a literal address of this
    machine, with a port and no path: OTLP's own paths follow it. Raises
    PydanticCustomError, a ValueError, saying ``TELEMETRY_ENDPOINT``.
    """
    parts = urlsplit(value) if loopback(value) else None
    if parts is None or parts.scheme != "http" or parts.port is None or parts.path not in {"", "/"}:
        raise PydanticCustomError(RULE, TELEMETRY_ENDPOINT)
    return f"http://{parts.netloc}"


def local_path(path: Path) -> Path:
    """Accept an absolute path; refuse another, which would lie below the current directory.

    ``settings_of`` makes ``~`` the home before the model sees a path, a default's
    included, since no validation context reaches pydantic-settings' ``__init__``: built
    without it, the settings refuse a path under ``~``.
    """
    if "\0" in str(path) or not path.is_absolute():
        message = "an absolute path, or one under ~"
        raise PydanticCustomError(RULE, message)
    return path


Site = Annotated[str, AfterValidator(site_address)]
# A path on this machine, such as the data directory: absolute.
LocalPath = Annotated[Path, AfterValidator(local_path)]
SpaceKey = Annotated[str, matching(SPACE_KEY, "a space key, such as ENG or ~5f1a2b")]
ProjectKey = Annotated[str, matching(PROJECT_KEY, "a project key, such as PLAT")]
ModelName = Annotated[
    str, matching(MODEL_NAME, "the name of an embedding model, such as qwen3-embedding:0.6b")
]
EmbeddingUrl = Annotated[str, AfterValidator(endpoint_address)]
TelemetryEndpoint = Annotated[str, AfterValidator(telemetry_address)]
# Every table of the settings: frozen, and refusing a key it does not know.
TABLE = ConfigDict(frozen=True, extra="forbid", hide_input_in_errors=True)


class ConfluenceSource(BaseModel):
    """What to download from Confluence when no flag says."""

    model_config = TABLE

    spaces: tuple[SpaceKey, ...] = Field(
        default=(), description="The spaces to download when no --space is given, by key."
    )


class JiraSource(BaseModel):
    """What to download from Jira when no flag says."""

    model_config = TABLE

    projects: tuple[ProjectKey, ...] = Field(
        default=(), description="The projects to download when no --project is given, by key."
    )


class Sources(BaseModel):
    """The sources of the mirror, each a table of its own."""

    model_config = TABLE

    confluence: ConfluenceSource = Field(
        default_factory=ConfluenceSource, description="Confluence, on the site."
    )
    jira: JiraSource = Field(default_factory=JiraSource, description="Jira, on the site.")


class Logs(BaseModel):
    """Where each run writes its log file."""

    model_config = TABLE

    dir: LocalPath | None = Field(
        default=None,
        description=(
            "The folder of each run's log file, ~ being the home directory: by default the"
            " user's log folder, where the platform keeps them; never under a synchronised"
            " folder, nor inside a git working tree."
        ),
    )


class Telemetry(BaseModel):
    """Where traces, metrics and logs go, if anywhere: nowhere unless an endpoint is set."""

    model_config = TABLE

    endpoint: TelemetryEndpoint | None = Field(
        default=None,
        description=(
            "The OTLP endpoint on this machine that traces, metrics and logs go to, over"
            " http with a port and no path, such as http://127.0.0.1:4318; unset, none is"
            " sent. Else OTEL_EXPORTER_OTLP_ENDPOINT gives it, below the settings file;"
            " OTEL_SDK_DISABLED=true leaves it unset."
        ),
    )


class Settings(BaseSettings):
    """What every command needs to know: the site, the data directory, the defaults.

    The loader builds it from the layers' merge (``settings_of``), with the home that
    ``~`` stands for: its paths are absolute, its default data directory included. It
    reads nothing of its own: the loader reads its variables by pydantic-settings'
    ``EnvSettingsSource``, with the prefix and the nesting of its configuration, an empty
    variable ignored. The loader then resolves the data directory, and the log folder,
    which is the platform's for the user when none is set.
    """

    model_config = SettingsConfigDict(
        **TABLE,
        env_prefix="ATLASSIAN_OFFLINE_MCP_",
        env_nested_delimiter="__",
        env_ignore_empty=True,
    )

    site: Site | None = Field(
        default=None,
        description=(
            "The Atlassian site, for Confluence and Jira alike: https://<name>.atlassian.net."
        ),
    )
    email: str | None = Field(
        default=None, description="The email address of the Atlassian account that signs in."
    )
    api_token: SecretStr | None = Field(
        default=None,
        description="The Atlassian account's API token, a secret: from the environment alone.",
    )
    data_dir: LocalPath = Field(
        default=Path(DEFAULT_DATA_DIR),
        validate_default=True,
        description=(
            "Where the data lives, ~ being the home directory: never under a synchronised"
            " folder, nor inside a git working tree."
        ),
    )
    model: ModelName = Field(
        default=DEFAULT_MODEL,
        description="The embedding model that indexes by meaning, as the endpoint names it.",
    )
    search_mode: SearchMode = Field(
        default=DEFAULT_SEARCH_MODE,
        description="How search ranks: by words (lexical), by meaning (semantic), or both.",
    )
    chunking: Chunking = Field(
        default=DEFAULT_CHUNKING,
        description=(
            f"How index cuts documents into the pieces it embeds: {', '.join(CHUNKINGS)};"
            " search follows the index. The default is plan 019's rule's; windows ranked"
            " best on its sandbox."
        ),
    )
    embedding_url: EmbeddingUrl = Field(
        default=DEFAULT_EMBEDDING_URL,
        description="The OpenAI-compatible API that embeds, up to /embeddings, excluded.",
    )
    embedding_api_key: SecretStr | None = Field(
        default=None,
        description=(
            "The embedding endpoint's API key, if it needs one, a secret: from the environment"
            " alone."
        ),
    )
    sources: Sources = Field(
        default_factory=Sources, description="The sources of the mirror, each a table."
    )
    logs: Logs = Field(default_factory=Logs, description="The log file of each run.")
    telemetry: Telemetry = Field(
        default_factory=Telemetry,
        description="Traces, metrics and logs sent by OpenTelemetry, off by default.",
    )

    @classmethod
    @override
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        """Take the values given alone: the loader reads the layers and merges them."""
        return (init_settings,)

    @property
    def raw(self) -> Path:
        """The raw store: responses as received, and attached files."""
        return self.data_dir / "raw"

    @property
    def docs(self) -> Path:
        """The Markdown mirror that agents read."""
        return self.data_dir / "docs"

    @property
    def index(self) -> Path:
        """The search index, built from the mirror alone."""
        return self.data_dir / "index.sqlite"

    @property
    def vectors(self) -> Path:
        """The vectors embedded so far, kept across index builds."""
        return self.data_dir / "vectors.sqlite"

    @property
    def evaluations(self) -> Path:
        """Golden questions, the indexes of models under evaluation, and their results."""
        return self.data_dir / "eval"

    @property
    def session(self) -> Path:
        """The browser profile and the saved session, never read by agents."""
        return self.data_dir / "session"

    @property
    def runs(self) -> Path:
        """The reports of download runs, which hold counts and paths, never content."""
        return self.data_dir / "runs"

    @property
    def parts(self) -> tuple[Path, ...]:
        """Every place under the data directory where data is written."""
        return (
            self.raw,
            self.docs,
            self.index,
            self.vectors,
            self.evaluations,
            self.session,
            self.runs,
        )


# Each setting's environment variable: the prefix, then its path in capitals, joined.
PREFIX = Settings.model_config["env_prefix"]
NESTING = Settings.model_config["env_nested_delimiter"]
# What a setting is: a table of settings, a list, a secret, a path, or another value.
type Kind = Literal["table", "list", "secret", "path", "value"]
# The kind of a setting of each type, other than a table, a list or a choice, that the
# environment gives as text.
TEXT_KINDS: dict[object, Kind] = {
    SecretStr: "secret",
    Path: "path",
    str: "value",
    bool: "value",
    int: "value",
}


def kind_of(annotation: object) -> Kind:
    """Give the kind of a setting that is no table by its type; refuse a type of no kind.

    An alias, ``Annotated`` and ``| None`` are looked through: ``Site | None`` is a
    value. Another type, such as ``list[str]`` or a table that may be None, raises
    TypeError, so that the environment never reads a setting by the wrong kind.
    """
    if isinstance(annotation, TypeAliasType):
        return kind_of(annotation.__value__)
    origin, arguments = get_origin(annotation), get_args(annotation)
    if origin is Annotated:
        return kind_of(arguments[0])
    others = [argument for argument in arguments if argument is not NoneType]
    if origin is Union and len(others) == 1:
        return kind_of(others[0])
    if origin is tuple:
        return "list"
    if origin is Literal:
        return "value"
    if annotation in TEXT_KINDS:
        return TEXT_KINDS[annotation]
    message = f"a setting of a type that has no kind: {annotation}"
    raise TypeError(message)


def setting_paths(
    model: type[BaseModel], above: tuple[str, ...] = ()
) -> dict[tuple[str, ...], Kind]:
    """Give the path of each setting of a model, at any depth, and its kind.

    A table is a model of its own, whose settings follow it. The environment gives a
    table or a list in JSON, and it alone gives a secret; ``~`` in a path is the home.
    Raises TypeError for a setting of a type that ``kind_of`` knows no kind for.
    """
    paths: dict[tuple[str, ...], Kind] = {}
    for name, info in model.model_fields.items():
        path = (*above, name)
        annotation = info.annotation
        if isinstance(annotation, type) and issubclass(annotation, BaseModel):
            paths[path] = "table"
            paths.update(setting_paths(annotation, path))
        else:
            paths[path] = kind_of(annotation)
    return paths


SETTING_PATHS = setting_paths(Settings)
# Each setting's default by its path, a table's aside, as the model holds it before
# validation: a path keeps its ~.
DEFAULTS = {
    path: reduce(getattr, path, Settings.model_construct())
    for path, kind in SETTING_PATHS.items()
    if kind != "table"
}


def variable(path: tuple[str, ...]) -> str:
    """Name the environment variable of the setting at a path."""
    return f"{PREFIX}{NESTING.join(path).upper()}"


@dataclass(frozen=True)
class Entry:
    """A value that a layer gives a setting: the setting's path, the value, the layer.

    A default's layer is None, so that no layer is taken for the defaults by its name,
    such as a settings file named ``default``. An ``implicit`` entry is a default that
    an empty table of its layer gives: the layer wrote no value, so a stronger one that
    replaces it replaces none. Its representation leaves the value out, which may be a
    secret not yet masked.
    """

    path: tuple[str, ...]
    value: object = field(repr=False)
    layer: str | None
    implicit: bool = False


@dataclass(frozen=True)
class Ignored:
    """A value read and not used: the setting it would set, if any, its layer, and why."""

    setting: str | None
    layer: str
    why: str


@dataclass(frozen=True)
class Loaded:
    """The settings, each one's layer by its path joined by dots, and the values ignored.

    ``replaced`` names each setting, by its path joined by dots, whose value that a layer
    wrote a stronger layer replaced.
    """

    settings: Settings
    layers: Mapping[str, str] = field(default_factory=dict)
    ignored: tuple[Ignored, ...] = ()
    replaced: frozenset[str] = frozenset()

    def layer(self, setting: str) -> str:
        """Name the layer that gave a setting, by its path joined by dots, or default.

        Raises KeyError for a path that names no setting, such as a misspelt one.
        """
        if tuple(setting.split(".")) not in SETTING_PATHS:
            raise KeyError(setting)
        return self.layers.get(setting, DEFAULT_LAYER)


def entries_of(value: object, path: tuple[str, ...], layer: str) -> list[Entry]:
    """Give a value that a layer read at a path as entries: a table's, one per value in it.

    An empty table of the settings gives each setting under it its default, so that the
    layer replaces a weaker one's values there and is said to have given them; each
    entry is implicit, as the layer wrote no value there. Another empty table is an
    entry of its own, so that one naming no setting is refused too.
    """
    if isinstance(value, dict) and value:
        return [
            entry
            for name, inner in value.items()
            for entry in entries_of(inner, (*path, name), layer)
        ]
    if value == {} and SETTING_PATHS.get(path) == "table":
        return [
            Entry(setting, default, layer, implicit=True)
            for setting, default in DEFAULTS.items()
            if setting[: len(path)] == path
        ]
    return [Entry(path, value, layer)]


def file_entries(values: Mapping[str, object], layer: str) -> list[Entry]:
    """Give the settings file's values as entries; refuse a moved or unknown one, a secret."""
    entries = [
        entry for name, value in values.items() for entry in entries_of(value, (name,), layer)
    ]
    for entry in entries:
        setting = ".".join(entry.path)
        if entry.path[0] in MOVED:
            message = f"{setting} ({layer}): moved, as {setting} under {MOVED[entry.path[0]]}"
            raise SettingsError(message)
        if entry.path not in SETTING_PATHS:
            message = f"{setting} ({layer}): not a setting"
            raise SettingsError(message)
        if SETTING_PATHS[entry.path] == "secret":
            message = f"{setting} ({layer}): a secret, read from {variable(entry.path)} alone"
            raise SettingsError(message)
    return entries


# How the environment writes a table and a list: in JSON, as an object and an array.
JSON_TYPES: dict[Kind, type] = {"table": dict, "list": list}


def environment_entries(
    environ: Mapping[str, str], parse: Callable[[], Mapping[str, object]]
) -> tuple[list[Entry], list[Ignored]]:
    """Give the settings' variables of an environment as entries, and those ignored.

    Each variable of the prefix is first scanned by the settings' paths, without regard
    to case, as pydantic-settings reads it. One that names no setting, at any depth, or
    that is empty, is ignored, since other tools and versions share the environment. A
    table is a JSON object, a list a JSON array: else SettingsError names the variable,
    never its value, where pydantic-settings would name none. So it does for two
    variables of one setting, or of a table and of a path inside it: pydantic-settings
    would merge them, below the top by the environment's order, and no value would name
    its variable. Then ``parse``, pydantic-settings' ``EnvSettingsSource(Settings)`` of
    this environment, reads them, and each value read is an entry of its variable; a
    table or a list is the JSON that the scan decoded, its keys as written, since the
    source merges into it the variables below it, those that name no setting included.
    """
    scanned: list[tuple[tuple[str, ...], str]] = []
    decoded: dict[str, object] = {}
    ignored: list[Ignored] = []
    for name in sorted(name for name in environ if name.lower().startswith(PREFIX.lower())):
        path = tuple(name.lower().removeprefix(PREFIX.lower()).split(NESTING))
        kind = SETTING_PATHS.get(path)
        if kind is None or not environ[name]:
            setting = None if kind is None else ".".join(path)
            ignored.append(Ignored(setting, name, "empty" if setting else "names no setting"))
            continue
        if kind in JSON_TYPES:
            try:
                decoded[name] = json.loads(environ[name])
            except ValueError:
                decoded[name] = None
            if not isinstance(decoded[name], JSON_TYPES[kind]):
                message = f"{name}: not a {kind} in JSON"
                raise SettingsError(message)
        scanned.append((path, name))
    for path, name in scanned:
        inner = [
            other for deeper, other in scanned if other != name and deeper[: len(path)] == path
        ]
        if inner:
            setting = ".".join(path)
            message = f"{name}, {inner[0]}: both set {setting}, which one variable alone may set"
            raise SettingsError(message)
    found = parse()
    entries = [
        entry
        for path, name in scanned
        for entry in entries_of(
            decoded[name] if name in decoded else reduce(getitem, path, found), path, name
        )
    ]
    return entries, ignored


# OpenTelemetry's own variables, which other programs share: its endpoint, a layer of
# telemetry's below the settings file, and the switch that turns it off, above all.
SHARED_ENDPOINT = "OTEL_EXPORTER_OTLP_ENDPOINT"
SDK_DISABLED = "OTEL_SDK_DISABLED"
# Telemetry's endpoint, by its path among the settings.
ENDPOINT = ("telemetry", "endpoint")


def shared_entries(environ: Mapping[str, str]) -> tuple[list[Entry], list[Entry], list[Ignored]]:
    """Give OpenTelemetry's own variables of an environment as entries of telemetry's endpoint.

    ``OTEL_EXPORTER_OTLP_ENDPOINT`` gives an entry of the layer below the settings file,
    unless the setting would refuse its value: it is then ignored, with the rule that it
    breaks. ``OTEL_SDK_DISABLED``, when true as the SDK reads it, gives one of the layer
    above all, which leaves the endpoint unset: telemetry off. Give the entries below,
    those above, then what was ignored.
    """
    below: list[Entry] = []
    ignored: list[Ignored] = []
    shared = environ.get(SHARED_ENDPOINT)
    if shared is not None:
        try:
            below.append(Entry(ENDPOINT, telemetry_address(shared), SHARED_ENDPOINT))
        except ValueError as error:
            ignored.append(Ignored(".".join(ENDPOINT), SHARED_ENDPOINT, f"not {error}"))
    disabled = environ.get(SDK_DISABLED, "").strip().lower() == "true"
    return below, [Entry(ENDPOINT, None, SDK_DISABLED)] if disabled else [], ignored


# Each path setting at its default, an entry of no layer, the weakest, so that
# ``settings_of`` makes ``~`` the home in it as in a path given.
PATH_DEFAULTS = [
    Entry(path, DEFAULTS[path], None) for path, kind in SETTING_PATHS.items() if kind == "path"
]


def settings_of(entries: Iterable[Entry], home: Path) -> Loaded:
    """Merge the layers' entries, weakest first, and build the settings from them.

    An entry replaces any earlier one at its path, above it or below it, whole: a list is
    never joined to another. A value replaced that a layer wrote is ignored, and its
    setting is ``replaced``; a default, by no layer or implicit, is neither. ``~`` in a
    path, a default's included, is ``home``. Raises
    SettingsError naming each setting refused and the layers that gave it, never its
    value: first an entry whose path names no setting, which ``BaseSettings`` could take
    as an argument of its own, such as ``_env_file``.
    """
    kept: dict[tuple[str, ...], Entry] = {}
    replaced: list[tuple[Entry, str | None]] = []
    for entry in [*PATH_DEFAULTS, *entries]:
        if entry.path not in SETTING_PATHS:
            message = f"{'.'.join(entry.path)} ({entry.layer}): not a setting"
            raise SettingsError(message)
        overlapping = [
            path
            for path in kept
            if path[: len(entry.path)] == entry.path or entry.path[: len(path)] == path
        ]
        replaced.extend((kept.pop(path), entry.layer) for path in overlapping)
        kept[entry.path] = entry
    values: dict[str, object] = {}
    for path, entry in kept.items():
        table = values
        for name in path[:-1]:
            table = table.setdefault(name, {})
        value = entry.value
        if (
            SETTING_PATHS[path] == "path"
            and isinstance(value, str | Path)
            and Path(value).parts[:1] == ("~",)
        ):
            value = home.joinpath(*Path(value).parts[1:])
        table[path[-1]] = value
    layers = {
        ".".join(path): entry.layer for path, entry in kept.items() if entry.layer is not None
    }
    try:
        settings = Settings.model_validate(values)
    except ValidationError as error:
        problems = []
        for problem in error.errors(include_input=False):
            where = ".".join(str(part) for part in problem["loc"])
            given = {
                layer
                for setting, layer in layers.items()
                if f"{setting}.".startswith(f"{where}.") or f"{where}.".startswith(f"{setting}.")
            }
            named = ", ".join(sorted(given)) or DEFAULT_LAYER
            problems.append(f"{where} ({named}): {problem['msg']}")
        raise SettingsError("; ".join(problems)) from None
    said = [
        (".".join(weaker.path), weaker.layer, stronger)
        for weaker, stronger in replaced
        if weaker.layer is not None and not weaker.implicit
    ]
    return Loaded(
        settings,
        layers,
        tuple(Ignored(setting, layer, f"replaced by {by}") for setting, layer, by in said),
        frozenset(setting for setting, _, _ in said),
    )


def unsafe_location(path: Path, home: Path, git_root: Path | None) -> str | None:
    """Return why company data must not live at this path, or None when it may.

    ``path`` and ``home`` must be resolved, without links or ``..``; names compare
    without regard to case, as on the default file system of macOS. ``git_root`` is the
    working tree that holds the path, if any: data there could be committed. A
    synchronised folder would copy the data off the machine.
    """
    if git_root is not None:
        return f"inside the git working tree {git_root}"
    parts = [part.casefold() for part in path.parts]
    home_parts = [part.casefold() for part in home.parts]
    if parts[: len(home_parts)] == home_parts:
        relative = parts[len(home_parts) :]
        for folder in SYNCED_UNDER_HOME:
            if relative[: len(folder.parts)] == [part.casefold() for part in folder.parts]:
                return f"under ~/{folder}, which may be synchronised"
    for name in SYNCED_NAMES:
        if any(part.startswith(name.casefold()) for part in parts):
            return f"under a {name} folder"
    return None
