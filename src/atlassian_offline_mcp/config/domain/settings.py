"""Settings: the site, where data lives, and what to download when no flag says.

They come in layers, each stronger than the last: the settings file, the environment,
then the flags given. Each layer gives entries, a value at a setting's path;
``settings_of`` merges them, a stronger value replacing a weaker one whole, a list
included, and builds ``Settings``, whose fields hold every rule of a value. Secrets come
from the environment alone. Where data may live is judged by ``unsafe_location``, once
the loader has resolved the data directory.
"""

from __future__ import annotations

import ipaddress
import json
from dataclasses import dataclass, field
from pathlib import Path
from types import NoneType
from typing import TYPE_CHECKING, Annotated, Literal, TypeAliasType, Union, get_args, get_origin
from urllib.parse import urlsplit

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, SecretStr, ValidationError
from pydantic_core import PydanticCustomError

from atlassian_offline_mcp.kernel.content import MODEL_NAME, PROJECT_KEY, SPACE_KEY

if TYPE_CHECKING:
    import re
    from collections.abc import Iterable, Mapping

    from pydantic import ValidationInfo

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
# Each setting's environment variable: the prefix, then its path in capitals, joined.
PREFIX = "ATLASSIAN_OFFLINE_MCP_"
NESTING = "__"
# The layer of a setting that no layer gives.
DEFAULT_LAYER = "default"
# The settings that the file held at its top before plan 015, and their tables now.
MOVED = {"spaces": "[sources.confluence]", "projects": "[sources.jira]"}
# The type of every refusal of a value by the settings' rules.
RULE = "setting"
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


def endpoint_host(value: object) -> str | None:
    """Give the host of an embedding endpoint's address, or None when it is not one.

    An address is http or https, with a host and a valid port if any, and no user,
    query or fragment.
    """
    if not isinstance(value, str):
        return None
    try:
        parts = urlsplit(value)
        usable = (
            parts.scheme in {"http", "https"}
            and bool(parts.hostname)
            and "@" not in parts.netloc
            and not parts.query
            and not parts.fragment
            and parts.port != 0
        )
    except ValueError:  # an unclosed [ in the host, or a port that is not a number
        return None
    return parts.hostname if usable else None


def loopback(url: str) -> bool:
    """Say whether an endpoint's address is a literal address of this machine.

    A name, ``localhost`` included, is not: what it resolves to is the resolver's to say.
    """
    try:
        return ipaddress.ip_address(endpoint_host(url) or "").is_loopback
    except ValueError:
        return False


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


def local_path(path: Path, info: ValidationInfo) -> Path:
    """Accept an absolute path, or one under ``~``, made the home that validation is given.

    The home comes in the validation's context, as ``settings_of`` gives it: without
    one, a path under ``~`` is refused, so that no settings hold a path relative to the
    current directory.
    """
    home = (info.context or {}).get("home")
    if home is not None and path.parts[:1] == ("~",):
        path = home.joinpath(*path.parts[1:])
    if "\0" in str(path) or not path.is_absolute():
        message = "an absolute path, or one under ~"
        raise PydanticCustomError(RULE, message)
    return path


Site = Annotated[str, AfterValidator(site_address)]
# A path on this machine, such as the data directory.
LocalPath = Annotated[Path, AfterValidator(local_path)]
SpaceKey = Annotated[str, matching(SPACE_KEY, "a space key, such as ENG or ~5f1a2b")]
ProjectKey = Annotated[str, matching(PROJECT_KEY, "a project key, such as PLAT")]
ModelName = Annotated[
    str, matching(MODEL_NAME, "the name of an embedding model, such as qwen3-embedding:0.6b")
]
EmbeddingUrl = Annotated[str, AfterValidator(endpoint_address)]
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


class Settings(BaseModel):
    """What every command needs to know: the site, the data directory, the defaults.

    The loader builds it from the layers' merge (``settings_of``), with the home that
    ``~`` stands for: its paths are absolute, its default data directory included. The
    loader then resolves the data directory.
    """

    model_config = TABLE

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


# What a setting is: a table of settings, a list, a secret, or another value.
type Kind = Literal["table", "list", "secret", "value"]
# The types of a setting that is another value, which the environment gives as text.
VALUE_TYPES = (str, bool, int, Path)


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
    if annotation is SecretStr:
        return "secret"
    if origin is Literal or annotation in VALUE_TYPES:
        return "value"
    message = f"a setting of a type that has no kind: {annotation}"
    raise TypeError(message)


def setting_paths(
    model: type[BaseModel], above: tuple[str, ...] = ()
) -> dict[tuple[str, ...], Kind]:
    """Give the path of each setting of a model, at any depth, and its kind.

    A table is a model of its own, whose settings follow it. The environment gives a
    table or a list in JSON, and it alone gives a secret. Raises TypeError for a setting
    of a type that ``kind_of`` knows no kind for.
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


def variable(path: tuple[str, ...]) -> str:
    """Name the environment variable of the setting at a path."""
    return f"{PREFIX}{NESTING.join(path).upper()}"


@dataclass(frozen=True)
class Entry:
    """A value that a layer gives a setting: the setting's path, the value, the layer.

    Its representation leaves the value out, which may be a secret not yet masked.
    """

    path: tuple[str, ...]
    value: object = field(repr=False)
    layer: str


@dataclass(frozen=True)
class Ignored:
    """A value read and not used: the setting it would set, if any, its layer, and why."""

    setting: str | None
    layer: str
    why: str


@dataclass(frozen=True)
class Loaded:
    """The settings, each one's layer by its path joined by dots, and the values ignored."""

    settings: Settings
    layers: Mapping[str, str] = field(default_factory=dict)
    ignored: tuple[Ignored, ...] = ()

    def layer(self, setting: str) -> str:
        """Name the layer that gave a setting, by its path joined by dots, or default.

        Raises KeyError for a path that names no setting, such as a misspelt one.
        """
        if tuple(setting.split(".")) not in SETTING_PATHS:
            raise KeyError(setting)
        return self.layers.get(setting, DEFAULT_LAYER)


def entries_of(value: object, path: tuple[str, ...], layer: str) -> list[Entry]:
    """Give a value that a layer read at a path as entries: a table's, one per value in it.

    An empty table is an entry of its own, so that one naming no setting is refused too.
    """
    if isinstance(value, dict) and value:
        return [
            entry
            for name, inner in value.items()
            for entry in entries_of(inner, (*path, name), layer)
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


def environment_entries(environ: Mapping[str, str]) -> tuple[list[Entry], list[Ignored]]:
    """Give the settings' variables of an environment as entries, and those ignored.

    A variable of the prefix that names no setting, at any depth, or that is empty, is
    ignored, since other tools and versions share the environment. A table or a list is
    written in JSON: else SettingsError names the variable, never its value. Variables
    come in the order of their names, so that a table's own, deeper, come after it.
    """
    named = {variable(path): path for path in SETTING_PATHS}
    entries: list[Entry] = []
    ignored: list[Ignored] = []
    for name in sorted(name for name in environ if name.startswith(PREFIX)):
        path = named.get(name)
        if path is None or not environ[name]:
            setting = None if path is None else ".".join(path)
            ignored.append(Ignored(setting, name, "empty" if setting else "names no setting"))
            continue
        value: object = environ[name]
        if SETTING_PATHS[path] in {"table", "list"}:
            try:
                value = json.loads(environ[name])
            except ValueError:
                message = f"{name}: not JSON, in which a {SETTING_PATHS[path]} is written"
                raise SettingsError(message) from None
        entries.extend(entries_of(value, path, name))
    return entries, ignored


def settings_of(entries: Iterable[Entry], home: Path) -> Loaded:
    """Merge the layers' entries, weakest first, and build the settings from them.

    An entry replaces any earlier one at its path, above it or below it, whole: a list is
    never joined to another. ``~`` in a path, a default's included, is ``home``. Raises
    SettingsError naming each setting refused and the layers that gave it, never its
    value.
    """
    kept: dict[tuple[str, ...], Entry] = {}
    replaced: list[Ignored] = []
    for entry in entries:
        for path in [
            path
            for path in kept
            if path[: len(entry.path)] == entry.path or entry.path[: len(path)] == path
        ]:
            weaker = kept.pop(path)
            replaced.append(Ignored(".".join(path), weaker.layer, f"replaced by {entry.layer}"))
        kept[entry.path] = entry
    values: dict[str, object] = {}
    for path, entry in kept.items():
        table = values
        for name in path[:-1]:
            table = table.setdefault(name, {})
        table[path[-1]] = entry.value
    layers = {".".join(path): entry.layer for path, entry in kept.items()}
    try:
        settings = Settings.model_validate(values, context={"home": home})
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
    return Loaded(settings, layers, tuple(replaced))


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
