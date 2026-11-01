"""Settings: where data lives, and each account's and each source's table, composed.

``settings_model`` composes the model of the settings from the core's, ``Settings``, and
the table of each account and of each source that the entry gives it, under ``accounts``
and ``sources``; this module names no source but in ``MOVED``. They come in layers, each
stronger than the last: the settings file, the environment, then the flags given. Each
layer gives entries, a value at a setting's path of that model; ``settings_of`` merges
them, a stronger value replacing a weaker one whole, a list included, and builds the
settings, whose fields hold every rule of a value. Secrets come from the environment
alone. Where data may live is judged by ``unsafe_location``, once the loader has
resolved the data directory.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
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

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    SecretStr,
    SerializeAsAny,
    ValidationError,
    create_model,
)
from pydantic_core import PydanticCustomError
from pydantic_settings import BaseSettings, SettingsConfigDict

from kb_mcp.kernel.chunking import CHUNKINGS, Chunking
from kb_mcp.kernel.endpoint import endpoint_host, loopback
from kb_mcp.kernel.names import MODEL_NAME
from kb_mcp.kernel.record import Record
from kb_mcp.kernel.reranking import DEPTHS

if TYPE_CHECKING:
    import re
    from collections.abc import Callable, Iterable

    from pydantic_settings import PydanticBaseSettingsSource

DEFAULT_DATA_DIR = "~/kb-mcp"
# The embedding model that indexes by meaning, as the endpoint names it. Chosen by plan
# 018 from published retrieval scores: the best in English, French not needed for now.
DEFAULT_MODEL = "qwen3-embedding:0.6b"
# The OpenAI-compatible API that embeds: Ollama on this machine, where it listens.
DEFAULT_EMBEDDING_URL = "http://127.0.0.1:11434/v1"
# How search ranks: by words, by meaning, or by both fused.
type SearchMode = Literal["lexical", "semantic", "hybrid"]
# Plan 018's bar kept words. With plan 019's windows, hybrid met two of its three counts,
# beating words significantly and holding identifiers, but its 95th percentile query
# time missed 200 ms. Plan 025: the user chose hybrid, ranking mattering more than speed.
DEFAULT_SEARCH_MODE: SearchMode = "hybrid"
# How index cuts documents into the pieces it embeds. Plan 019's rule kept sections, as
# no chunking beat them on the evidence quoted; windows ranked significantly better, and
# by plan 025 the user chose them.
DEFAULT_CHUNKING: Chunking = "windows"
# The reranking server: llama.cpp's llama-server on this machine, where the guide starts it.
DEFAULT_RERANK_URL = "http://127.0.0.1:9931/v1"
# The reranker, as the server names it: Qwen3-Reranker-0.6B, chosen by plan 022 from
# published reranking results, under the alias that the guide gives it.
DEFAULT_RERANKER = "qwen3-reranker-0.6b"
# The documents reranked after those named, until plan 022's run on the user's machine decides:
# about 30 fit within its bound of 5 seconds, by estimate.
DEFAULT_RERANK_DEPTH = 30
# The layer of a setting that no layer gives, as it is named.
DEFAULT_LAYER = "default"
# The settings that the file held at its top before plans 015 and 030, and their tables
# now.
MOVED = {
    "spaces": "[sources.confluence]",
    "projects": "[sources.jira]",
    "site": "[accounts.atlassian]",
    "email": "[accounts.atlassian]",
}
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
    """A setting that cannot be used; the message names it and its layer, never its value.

    ``advice``, empty unless a refusal has more to say, is written after it as it is.
    """

    advice = ""


def matching(pattern: re.Pattern[str], expected: str) -> AfterValidator:
    """Check a text by one of the kernel's patterns, whole; refuse another as ``expected``."""

    def check(value: str) -> str:
        if not pattern.fullmatch(value):
            raise PydanticCustomError(RULE, expected)
        return value

    return AfterValidator(check)


def endpoint_address(value: str) -> str:
    """Give an embedding endpoint's address without its trailing slash; refuse another."""
    if endpoint_host(value) is None:
        message = "an http or https address with a host, such as http://127.0.0.1:11434/v1"
        raise PydanticCustomError(RULE, message)
    return value.rstrip("/")


def rerank_address(value: str) -> str:
    """Give the reranking server's address without its trailing slash; refuse another.

    The server is on this machine, by the user's word (plan 022): a literal address of
    it, which no flag can widen.
    """
    if not loopback(value):
        message = (
            "an address of this machine, such as http://127.0.0.1:9931/v1, where the"
            " mirror's text stays; write 127.0.0.1 for localhost"
        )
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


# A path on this machine, such as the data directory: absolute.
LocalPath = Annotated[Path, AfterValidator(local_path)]
ModelName = Annotated[
    str, matching(MODEL_NAME, "the name of an embedding model, such as qwen3-embedding:0.6b")
]
EmbeddingUrl = Annotated[str, AfterValidator(endpoint_address)]
RerankUrl = Annotated[str, AfterValidator(rerank_address)]
RerankerName = Annotated[
    str, matching(MODEL_NAME, "the name of a reranking model, such as qwen3-reranker-0.6b")
]
TelemetryEndpoint = Annotated[str, AfterValidator(telemetry_address)]
# Every table of the settings: frozen, and refusing a key it does not know.
TABLE = ConfigDict(frozen=True, extra="forbid", hide_input_in_errors=True)


class Accounts(BaseModel):
    """The accounts that sources sign in with, each a table, which ``settings_model`` adds."""

    model_config = TABLE


class Sources(BaseModel):
    """The sources of the mirror, each a table of its own, which ``settings_model`` adds."""

    model_config = TABLE


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


class Rerank(BaseModel):
    """Reranking of search's first documents by a server on this machine, off by default."""

    model_config = TABLE

    enabled: bool = Field(
        default=False,
        description=(
            "Whether search and ask rerank their first documents through the reranking"
            " server: off by default, as it ranked worse on the sandbox, by the user's"
            " choice in plan 022."
        ),
    )
    url: RerankUrl = Field(
        default=DEFAULT_RERANK_URL,
        description=(
            "The reranking server's API, up to /rerank, excluded: an address of this"
            " machine, never another."
        ),
    )
    model: RerankerName = Field(
        default=DEFAULT_RERANKER, description="The reranking model, as the server names it."
    )
    depth: int = Field(
        default=DEFAULT_RERANK_DEPTH,
        ge=DEPTHS.start,
        le=DEPTHS[-1],
        description=(
            f"How many documents, after those a query names, are reranked: {DEPTHS.start} to"
            f" {DEPTHS[-1]}."
        ),
    )


class Settings(BaseSettings):
    """What every command needs to know: the data directory, the defaults, the tables.

    The core's settings, whose ``accounts`` and ``sources`` hold no table:
    ``settings_model`` composes from it the model that holds each account's and each
    source's. The loader builds the settings from the
    layers' merge (``settings_of``), with the home that ``~`` stands for: their paths are
    absolute, the default data directory included. The model reads nothing of its own:
    the loader reads its variables by pydantic-settings' ``EnvSettingsSource``, with the
    prefix and the nesting of its configuration, an empty variable ignored. The loader
    then resolves the data directory, and the log folder, which is the platform's for
    the user when none is set.
    """

    model_config = SettingsConfigDict(
        **TABLE,
        env_prefix="KB_MCP_",
        env_nested_delimiter="__",
        env_ignore_empty=True,
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
        description=(
            "How search ranks: by words (lexical), by meaning (semantic), or both (hybrid),"
            " the default; all but lexical need the embedding endpoint."
        ),
    )
    chunking: Chunking = Field(
        default=DEFAULT_CHUNKING,
        description=(
            f"How index cuts documents into the pieces it embeds: {', '.join(CHUNKINGS)};"
            " search follows the index. By default windows, which ranked best on plan"
            " 019's sandbox."
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
    accounts: Accounts = Field(
        default_factory=Accounts,
        description="The accounts that sources sign in with, each a table.",
    )
    sources: Sources = Field(
        default_factory=Sources, description="The sources of the mirror, each a table."
    )
    logs: Logs = Field(default_factory=Logs, description="The log file of each run.")
    telemetry: Telemetry = Field(
        default_factory=Telemetry,
        description="Traces, metrics and logs sent by OpenTelemetry, off by default.",
    )
    rerank: Rerank = Field(
        default_factory=Rerank,
        description="Reranking by a server on this machine, off by default.",
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
    def aliases(self) -> Path:
        """The aliases that the user writes and each index build reads, to join names."""
        return self.data_dir / "aliases.toml"

    @property
    def conversions(self) -> Path:
        """Pandoc's conversions so far, by their input, kept across mirrors."""
        return self.data_dir / "conversions.sqlite"

    @property
    def evaluations(self) -> Path:
        """Golden questions, the indexes of models under evaluation, and their results."""
        return self.data_dir / "eval"

    @property
    def evaluation_indexes(self) -> Path:
        """The indexes that eval builds, one per chunking and model, whose vectors stay."""
        return self.evaluations / "indexes"

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
            self.conversions,
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

    An alias, ``Annotated`` and ``| None`` are looked through: ``LocalPath | None`` is a
    path. Another type, such as ``list[str]`` or a table that may be None, raises
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


def settings_model(
    sources: Mapping[str, type[BaseModel]], accounts: Mapping[str, type[BaseModel]]
) -> type[Settings]:
    """Compose the settings' model: the core's, with each account's and each source's table.

    ``sources`` gives each source's table by its name, which names its table,
    ``[sources.<name>]``, and ``accounts`` each account's alike, ``[accounts.<name>]``;
    the tables of each follow one another in name order, each described by its
    docstring. Raises TypeError, naming the table, for one that holds a setting of a type
    that has no kind, or one without a default, since a source left unset still has its
    table, before any value is read.
    """
    places = {"accounts": (Accounts, accounts), "sources": (Sources, sources)}
    for place, (_, tables) in places.items():
        for name, table in tables.items():
            try:
                setting_paths(table)
                table()
            except TypeError as error:
                message = f"{place}.{name}: {error}"
                raise TypeError(message) from None
            except ValidationError as error:
                without = [".".join(map(str, each["loc"])) for each in error.errors()]
                message = f"{place}.{name}: a setting without a default: {', '.join(without)}"
                raise TypeError(message) from None
    composed = {
        place: create_model(
            base.__name__,
            __base__=base,
            **{
                name: (table, Field(default_factory=table, description=table.__doc__))
                for name, table in sorted(tables.items())
            },
        )
        for place, (base, tables) in places.items()
    }
    return create_model(
        "Settings",
        __base__=Settings,
        **{
            place: (
                model,
                Field(default_factory=model, description=Settings.model_fields[place].description),
            )
            for place, model in composed.items()
        },
    )


def defaults(model: type[Settings]) -> dict[tuple[str, ...], object]:
    """Give each setting's default by its path, a table's aside, as the model holds it.

    That is before validation: a path keeps its ``~``.
    """
    built = model.model_construct()
    return {
        path: reduce(getattr, path, built)
        for path, kind in setting_paths(model).items()
        if kind != "table"
    }


def variable(path: tuple[str, ...]) -> str:
    """Name the environment variable of the setting at a path."""
    return f"{PREFIX}{NESTING.join(path).upper()}"


class Entry(Record):
    """A value that a layer gives a setting: the setting's path, the value, the layer.

    A default's layer is None, so that no layer is taken for the defaults by its name,
    such as a settings file named ``default``. An ``implicit`` entry is a default that
    an empty table of its layer gives: the layer wrote no value, so a stronger one that
    replaces it replaces none. Its representation leaves the value out, which may be a
    secret not yet masked.
    """

    path: tuple[str, ...]
    value: object = Field(repr=False)
    layer: str | None
    implicit: bool = False


class Ignored(Record):
    """A value read and not used: the setting it would set, if any, its layer, and why."""

    setting: str | None
    layer: str
    why: str


class Loaded(Record):
    """The settings, each one's layer by its path joined by dots, and the values ignored.

    ``replaced`` names each setting, by its path joined by dots, whose value that a layer
    wrote a stronger layer replaced. The settings are of the model that ``settings_model``
    composed, whose setting paths are ``paths``; written as JSON, they hold every table.
    """

    settings: SerializeAsAny[Settings]
    layers: Mapping[str, str] = Field(default_factory=dict)
    ignored: tuple[Ignored, ...] = ()
    replaced: frozenset[str] = frozenset()

    @property
    def paths(self) -> dict[tuple[str, ...], Kind]:
        """Give the path of each setting of the settings' model, and its kind."""
        return setting_paths(type(self.settings))

    def layer(self, setting: str) -> str:
        """Name the layer that gave a setting, by its path joined by dots, or default.

        Raises KeyError for a path that names no setting, such as a misspelt one.
        """
        if tuple(setting.split(".")) not in self.paths:
            raise KeyError(setting)
        return self.layers.get(setting, DEFAULT_LAYER)


def entries_of(
    value: object, path: tuple[str, ...], layer: str, model: type[Settings]
) -> list[Entry]:
    """Give a value that a layer read at a path as entries: a table's, one per value in it.

    An empty table of the model's settings gives each setting under it its default, so
    that the layer replaces a weaker one's values there and is said to have given them;
    each entry is implicit, as the layer wrote no value there. Another empty table is an
    entry of its own, so that one naming no setting is refused too.
    """
    if isinstance(value, dict) and value:
        return [
            entry
            for name, inner in value.items()
            for entry in entries_of(inner, (*path, name), layer, model)
        ]
    if value == {} and setting_paths(model).get(path) == "table":
        return [
            Entry(path=setting, value=default, layer=layer, implicit=True)
            for setting, default in defaults(model).items()
            if setting[: len(path)] == path
        ]
    return [Entry(path=path, value=value, layer=layer)]


def file_entries(values: Mapping[str, object], layer: str, model: type[Settings]) -> list[Entry]:
    """Give the settings file's values as entries; refuse a moved or unknown one, a secret.

    An empty table that holds a secret writes no value of it: only one written is refused.
    """
    entries = [
        entry
        for name, value in values.items()
        for entry in entries_of(value, (name,), layer, model)
    ]
    paths = setting_paths(model)
    for entry in entries:
        setting = ".".join(entry.path)
        if entry.path[0] in MOVED:
            message = f"{setting} ({layer}): moved, as {setting} under {MOVED[entry.path[0]]}"
            raise SettingsError(message)
        if entry.path not in paths:
            message = f"{setting} ({layer}): not a setting"
            raise SettingsError(message)
        if paths[entry.path] == "secret" and not entry.implicit:
            message = f"{setting} ({layer}): a secret, read from {variable(entry.path)} alone"
            raise SettingsError(message)
    return entries


# How the environment writes a table and a list: in JSON, as an object and an array.
JSON_TYPES: dict[Kind, type] = {"table": dict, "list": list}


def environment_entries(
    environ: Mapping[str, str], parse: Callable[[], Mapping[str, object]], model: type[Settings]
) -> tuple[list[Entry], list[Ignored]]:
    """Give the settings' variables of an environment as entries, and those ignored.

    Each variable of the prefix is first scanned by the paths of the model's settings,
    without regard to case, as pydantic-settings reads it. One that names no setting, at
    any depth, or that is empty, is ignored, since other tools and versions share the
    environment. A table is a JSON object, a list a JSON array: else SettingsError names
    the variable, never its value, where pydantic-settings would name none. So it does
    for two variables of one setting, or of a table and of a path inside it:
    pydantic-settings would merge them, below the top by the environment's order, and no
    value would name its variable. Then ``parse``, pydantic-settings'
    ``EnvSettingsSource`` of the model and of this environment, reads them, and each
    value read is an entry of its variable; a table or a list is the JSON that the scan
    decoded, its keys as written, since the source merges into it the variables below
    it, those that name no setting included.
    """
    paths = setting_paths(model)
    scanned: list[tuple[tuple[str, ...], str]] = []
    decoded: dict[str, object] = {}
    ignored: list[Ignored] = []
    for name in sorted(name for name in environ if name.lower().startswith(PREFIX.lower())):
        path = tuple(name.lower().removeprefix(PREFIX.lower()).split(NESTING))
        kind = paths.get(path)
        if kind is None or not environ[name]:
            setting = None if kind is None else ".".join(path)
            ignored.append(
                Ignored(setting=setting, layer=name, why="empty" if setting else "names no setting")
            )
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
            decoded[name] if name in decoded else reduce(getitem, path, found), path, name, model
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
            below.append(
                Entry(path=ENDPOINT, value=telemetry_address(shared), layer=SHARED_ENDPOINT)
            )
        except ValueError as error:
            ignored.append(
                Ignored(setting=".".join(ENDPOINT), layer=SHARED_ENDPOINT, why=f"not {error}")
            )
    disabled = environ.get(SDK_DISABLED, "").strip().lower() == "true"
    return (
        below,
        [Entry(path=ENDPOINT, value=None, layer=SDK_DISABLED)] if disabled else [],
        ignored,
    )


def at_home(path: Path, home: Path) -> Path:
    """Give a path that begins with ``~`` with ``home`` in its place."""
    return home.joinpath(*path.parts[1:])


def settings_of(entries: Iterable[Entry], home: Path, model: type[Settings]) -> Loaded:
    """Merge the layers' entries, weakest first, and build the model's settings from them.

    An entry replaces any earlier one at its path, above it or below it, whole: a list is
    never joined to another. A value replaced that a layer wrote is ignored, and its
    setting is ``replaced``; a default, by no layer or implicit, is neither. ``~`` in a
    path, a default's included, is ``home``: each path setting at its default is an
    entry of no layer, the weakest. Raises
    SettingsError naming each setting refused and the layers that gave it, never its
    value: first an entry whose path names no setting, which ``BaseSettings`` could take
    as an argument of its own, such as ``_env_file``.
    """
    paths = setting_paths(model)
    at_defaults = [
        Entry(path=path, value=value, layer=None)
        for path, value in defaults(model).items()
        if paths[path] == "path"
    ]
    kept: dict[tuple[str, ...], Entry] = {}
    replaced: list[tuple[Entry, str | None]] = []
    for entry in [*at_defaults, *entries]:
        if entry.path not in paths:
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
            paths[path] == "path"
            and isinstance(value, str | Path)
            and Path(value).parts[:1] == ("~",)
        ):
            value = at_home(Path(value), home)
        table[path[-1]] = value
    layers = {
        ".".join(path): entry.layer for path, entry in kept.items() if entry.layer is not None
    }
    try:
        settings = model.model_validate(values)
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
        settings=settings,
        layers=layers,
        ignored=tuple(
            Ignored(setting=setting, layer=layer, why=f"replaced by {by}")
            for setting, layer, by in said
        ),
        replaced=frozenset(setting for setting, _, _ in said),
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
