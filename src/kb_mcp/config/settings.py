"""The settings' model and rules, composed with each source's table, and their layers merged."""

from __future__ import annotations

import copy
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

from kb_mcp.kernel.names import (
    CHUNKINGS,
    CONNECTOR,
    DEPTHS,
    MODEL_NAME,
    NESTING,
    PREFIX,
    RERANKING,
    RESERVED,
    SOURCE_NAME,
    TELEMETRY,
    Chunking,
    endpoint_host,
    refused_endpoint,
)
from kb_mcp.kernel.records import Record, refused_fields

if TYPE_CHECKING:
    import re
    from collections.abc import Iterable

DEFAULT_DATA_DIR = "~/kb-mcp"
# The embedding model, as the endpoint names it: docs/how-to/embeddings.md says why.
DEFAULT_MODEL = "qwen3-embedding:0.6b"
# The OpenAI-compatible API that embeds: Ollama on this machine, where it listens.
DEFAULT_EMBEDDING_URL = "http://127.0.0.1:11434/v1"
# How search ranks: by words, by meaning, or by both fused.
type SearchMode = Literal["lexical", "semantic", "hybrid"]
# The default search mode: docs/explanation/chunking.md says why.
DEFAULT_SEARCH_MODE: SearchMode = "hybrid"
# How index cuts documents into the chunks it embeds: docs/explanation/chunking.md says why.
DEFAULT_CHUNKING: Chunking = "windows"
# The reranking server: llama.cpp's llama-server on this machine, where the how-to page starts it.
DEFAULT_RERANK_URL = "http://127.0.0.1:9931/v1"
# The reranker, Qwen3-Reranker-0.6B, under the alias that the how-to page gives it:
# docs/explanation/reranking.md says why.
DEFAULT_RERANKER = "qwen3-reranker-0.6b"
# The documents reranked after those named: docs/explanation/reranking.md says why about 30.
DEFAULT_RERANK_DEPTH = 30
# The layer of a setting that no layer gives, as it is named.
DEFAULT_LAYER = "default"
# The type of every refusal of a value by the settings' rules.
RULE = "setting"
# What each source's ``connector`` says, which the model adds to its connector's table.
CONNECTOR_DESCRIPTION = (
    "The connector that reads the source: by default the one of its name, which a source"
    " of the registry always keeps."
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
    """Check a text by a pattern, whole; refuse another as ``expected``."""

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
    """Give the reranking server's address without its trailing slash; refuse another."""
    refusal = refused_endpoint(value, RERANKING, remote_allowed=False)
    if refusal:
        raise PydanticCustomError(RULE, refusal)
    return value.rstrip("/")


def telemetry_address(value: str) -> str:
    """Give telemetry's endpoint as ``http://<address>:<port>``; refuse another, a ValueError."""
    refusal = refused_endpoint(value, TELEMETRY, remote_allowed=False)
    if refusal:
        raise PydanticCustomError(RULE, refusal)
    return f"http://{urlsplit(value).netloc}"


def local_path(path: Path) -> Path:
    """Accept an absolute path, as ``settings_of`` makes one under ``~``; refuse another."""
    if "\0" in str(path) or not path.is_absolute():
        message = "an absolute path, or one under ~"
        raise PydanticCustomError(RULE, message)
    return path


# A path on this machine, such as the data directory: absolute.
LocalPath = Annotated[Path, AfterValidator(local_path)]
# Every table of the settings: frozen, and refusing a key it does not know.
TABLE = ConfigDict(frozen=True, extra="forbid", hide_input_in_errors=True)


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

    endpoint: Annotated[str, AfterValidator(telemetry_address)] | None = Field(
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
            " server: off by default, as it ranked worse on the sandbox."
        ),
    )
    url: Annotated[str, AfterValidator(rerank_address)] = Field(
        default=DEFAULT_RERANK_URL,
        description=(
            "The reranking server's API, up to /rerank, excluded: an address of this"
            " machine, never another."
        ),
    )
    model: Annotated[
        str, matching(MODEL_NAME, "the name of a reranking model, such as qwen3-reranker-0.6b")
    ] = Field(default=DEFAULT_RERANKER, description="The reranking model, as the server names it.")
    depth: int = Field(
        default=DEFAULT_RERANK_DEPTH,
        ge=DEPTHS.start,
        le=DEPTHS[-1],
        description=(
            f"How many documents, after those a query names, are reranked: {DEPTHS.start} to"
            f" {DEPTHS[-1]}."
        ),
    )


class Settings(BaseModel):
    """The core's settings, whose ``sources`` holds no table, and the data directory's places."""

    model_config = TABLE

    data_dir: LocalPath = Field(
        default=Path(DEFAULT_DATA_DIR),
        validate_default=True,
        description=(
            "Where the data lives, ~ being the home directory: never under a synchronised"
            " folder, nor inside a git working tree."
        ),
    )
    model: Annotated[
        str, matching(MODEL_NAME, "the name of an embedding model, such as qwen3-embedding:0.6b")
    ] = Field(
        default=DEFAULT_MODEL,
        description="The embedding model that embed embeds with, as the endpoint names it.",
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
            f"How embed cuts documents into the chunks it embeds: {', '.join(CHUNKINGS)};"
            " search follows the index. By default windows, which ranked best when the"
            " chunkings were compared."
        ),
    )
    embedding_url: Annotated[str, AfterValidator(endpoint_address)] = Field(
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
    rerank: Rerank = Field(
        default_factory=Rerank,
        description="Reranking by a server on this machine, off by default.",
    )

    @property
    def raw(self) -> Path:
        """The raw store: responses as received, and attached files."""
        return self.data_dir / "raw"

    @property
    def copies(self) -> Path:
        """The copy stores of the sources read in place, a folder each."""
        return self.data_dir / "copies"

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
        """Pandoc's conversions so far, by their input, kept across prepares."""
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
        """A folder per recorded run: its configuration, its units' last entries, its lock."""
        return self.data_dir / "runs"

    @property
    def parts(self) -> tuple[Path, ...]:
        """Every place under the data directory where data is written."""
        return (
            self.raw,
            self.copies,
            self.docs,
            self.index,
            self.vectors,
            self.conversions,
            self.evaluations,
            self.session,
            self.runs,
        )


# What a setting is: a table of settings, a list, a secret, a path, or another value.
type SettingKind = Literal["table", "list", "secret", "path", "value"]
# The kind of a setting of each type, other than a table, a list or a choice, that the
# environment gives as text.
TEXT_KINDS: dict[object, SettingKind] = {
    SecretStr: "secret",
    Path: "path",
    str: "value",
    bool: "value",
    int: "value",
}


def bare(annotation: object) -> object:
    """Give a type without its alias and ``Annotated``, which say nothing of its kind."""
    if isinstance(annotation, TypeAliasType):
        return bare(annotation.__value__)
    if get_origin(annotation) is Annotated:
        return bare(get_args(annotation)[0])
    return annotation


def kind_of(annotation: object) -> SettingKind:
    """Give a setting's kind through aliases and ``| None``, a list a tuple of str; or TypeError."""
    annotation = bare(annotation)
    origin, arguments = get_origin(annotation), get_args(annotation)
    others = [argument for argument in arguments if argument is not NoneType]
    if origin is Union and len(others) == 1:
        return kind_of(others[0])
    if origin is tuple and all(
        item is str
        or (get_origin(item) is Literal and all(isinstance(each, str) for each in get_args(item)))
        for item in map(bare, arguments)
        if item is not Ellipsis
    ):
        return "list"
    if origin is Literal:
        return "value"
    if annotation in TEXT_KINDS:
        return TEXT_KINDS[annotation]
    message = f"a setting of a type that has no kind: {annotation}"
    raise TypeError(message)


def setting_paths(
    model: type[BaseModel], above: tuple[str, ...] = ()
) -> dict[tuple[str, ...], SettingKind]:
    """Give the path of each setting of a model, a table's then those inside, and its kind."""
    paths: dict[tuple[str, ...], SettingKind] = {}
    for name, info in model.model_fields.items():
        path = (*above, name)
        annotation = info.annotation
        if isinstance(annotation, type) and issubclass(annotation, BaseModel):
            paths[path] = "table"
            paths.update(setting_paths(annotation, path))
        else:
            paths[path] = kind_of(annotation)
    return paths


def settings_model(sources: Mapping[str, tuple[str, type[BaseModel]]]) -> type[Settings]:
    """Compose the settings' model: the core's, with each source's connector's table, by name.

    Raises SettingsError for a name that the model holds, such as ``json``; TypeError for a
    table holding a setting of no kind, one without a default, or a table.
    """
    tables = {
        name: create_model(
            table.__name__,
            __base__=table,
            __doc__=table.__doc__,
            **{
                CONNECTOR: (
                    Literal[connector],
                    Field(default=connector, description=CONNECTOR_DESCRIPTION),
                )
            },
        )
        for name, (connector, table) in sources.items()
    }
    for name, table in tables.items():
        if hasattr(Sources, name):
            message = f"sources.{name}: a name that the settings' model holds; name it otherwise"
            raise SettingsError(message)
        try:
            kinds = setting_paths(table)
            table()
        except TypeError as error:
            message = f"sources.{name}: {error}"
            raise TypeError(message) from None
        except ValidationError as error:
            without = [".".join(map(str, each["loc"])) for each in error.errors()]
            message = f"sources.{name}: a setting without a default: {', '.join(without)}"
            raise TypeError(message) from None
        inner = [".".join(path) for path, kind in kinds.items() if kind == "table"]
        if inner:
            message = f"sources.{name}: a table inside a table: {', '.join(inner)}"
            raise TypeError(message)
    composed = create_model(
        Sources.__name__,
        __base__=Sources,
        **{
            name: (table, Field(default_factory=table, description=table.__doc__))
            for name, table in sorted(tables.items())
        },
    )
    return create_model(
        "Settings",
        __base__=Settings,
        sources=(
            composed,
            Field(
                default_factory=composed, description=Settings.model_fields["sources"].description
            ),
        ),
    )


def defaults(model: type[Settings]) -> dict[tuple[str, ...], object]:
    """Give each setting's default by its path, a table's aside, before validation."""
    built = model.model_construct()
    return {
        path: reduce(getattr, path, built)
        for path, kind in setting_paths(model).items()
        if kind != "table"
    }


def values_of(settings: Settings) -> dict[str, object]:
    """Give every setting's value by its path joined by dots, a table's aside."""
    return {
        ".".join(path): reduce(getattr, path, settings)
        for path, kind in setting_paths(type(settings)).items()
        if kind != "table"
    }


def variable(path: tuple[str, ...]) -> str:
    """Name the environment variable of the setting at a path."""
    return f"{PREFIX}{NESTING.join(path).upper()}"


class LayerValue(Record):
    """A value that a layer, None for a default, gives a setting; ``implicit``: an empty table's."""

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
    """The settings, each one's layer, the values ignored, and those that a stronger replaced."""

    settings: SerializeAsAny[Settings]
    layers: Mapping[str, str] = Field(default_factory=dict)
    ignored: tuple[Ignored, ...] = ()
    replaced: frozenset[str] = frozenset()

    @property
    def paths(self) -> dict[tuple[str, ...], SettingKind]:
        """Give the path of each setting of the settings' model, and its kind."""
        return setting_paths(type(self.settings))

    def layer(self, setting: str) -> str:
        """Name the layer that gave a setting, or default; KeyError for no setting."""
        if tuple(setting.split(".")) not in self.paths:
            raise KeyError(setting)
        return self.layers.get(setting, DEFAULT_LAYER)


def refuse_not_a_source(path: tuple[str, ...], layer: str, model: type[Settings]) -> None:
    """Raise SettingsError for a path under ``sources`` of a source that the model lacks."""
    sources = model.model_fields["sources"].annotation
    if path[:1] != ("sources",) or len(path) == 1 or path[1] in sources.model_fields:
        return
    tables = (each.annotation for each in sources.model_fields.values())
    connectors = sorted({get_args(each.model_fields[CONNECTOR].annotation)[0] for each in tables})
    message = (
        f"sources.{path[1]} ({layer}): not a source: a source's name matches"
        f" {SOURCE_NAME.pattern}, is none of {', '.join(RESERVED)}, and its connector,"
        f" sources.{path[1]}.{CONNECTOR} or its name, is one of {', '.join(connectors)}"
    )
    raise SettingsError(message)


def entries_of(
    value: object, path: tuple[str, ...], layer: str, model: type[Settings]
) -> list[LayerValue]:
    """Give a value that a layer read at a path as entries: a table's, one per value in it.

    An empty table of the model gives each setting under it its default, ``implicit``.
    """
    if isinstance(value, dict) and value:
        return [
            entry
            for name, inner in value.items()
            for entry in entries_of(inner, (*path, name), layer, model)
        ]
    if value == {} and setting_paths(model).get(path) == "table":
        return [
            LayerValue(path=setting, value=default, layer=layer, implicit=True)
            for setting, default in defaults(model).items()
            if setting[: len(path)] == path
        ]
    return [LayerValue(path=path, value=value, layer=layer)]


def refuse_secrets(
    entries: Iterable[LayerValue], paths: Mapping[tuple[str, ...], SettingKind]
) -> None:
    """Raise SettingsError for a secret that these entries write, naming its own variable."""
    for entry in entries:
        if paths.get(entry.path) == "secret" and not entry.implicit:
            setting = ".".join(entry.path)
            message = f"{setting} ({entry.layer}): a secret, read from {variable(entry.path)} alone"
            raise SettingsError(message)


def file_entries(
    values: Mapping[str, object], layer: str, model: type[Settings]
) -> list[LayerValue]:
    """Give the settings file's values as entries; refuse an unknown one, then a secret."""
    entries = [
        entry
        for name, value in values.items()
        for entry in entries_of(value, (name,), layer, model)
    ]
    paths = setting_paths(model)
    for entry in entries:
        setting = ".".join(entry.path)
        refuse_not_a_source(entry.path, layer, model)
        if entry.path not in paths:
            message = f"{setting} ({layer}): not a setting"
            raise SettingsError(message)
    refuse_secrets(entries, paths)
    return entries


# How the environment writes a table and a list: in JSON, as an object and an array.
JSON_TYPES: dict[SettingKind, type] = {"table": dict, "list": list}


def environment_entries(
    environ: Mapping[str, str], model: type[Settings]
) -> tuple[list[LayerValue], list[Ignored]]:
    """Give the variables of the prefix as entries, without regard to case, and those ignored.

    Ignored: one naming no setting, or empty. Refused: a table or a list not in JSON, two
    variables of one setting, and a secret in JSON.
    """
    paths = setting_paths(model)
    scanned: list[tuple[tuple[str, ...], str]] = []
    decoded: dict[str, object] = {}
    ignored: list[Ignored] = []
    for name in sorted(name for name in environ if name.lower().startswith(PREFIX.lower())):
        path = tuple(name.lower().removeprefix(PREFIX.lower()).split(NESTING))
        kind = paths.get(path)
        if environ[name]:
            refuse_not_a_source(path, name, model)
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
    entries = [
        entry
        for path, name in scanned
        for entry in entries_of(decoded.get(name, environ[name]), path, name, model)
    ]
    refuse_secrets((entry for entry in entries if entry.layer in decoded), paths)
    return entries, ignored


# OpenTelemetry's own variables, which other programs share: its endpoint, a layer of
# telemetry's below the settings file, and the switch that turns it off, above all.
SHARED_ENDPOINT = "OTEL_EXPORTER_OTLP_ENDPOINT"
SDK_DISABLED = "OTEL_SDK_DISABLED"
# Telemetry's endpoint, by its path among the settings.
ENDPOINT = ("telemetry", "endpoint")


def shared_entries(
    environ: Mapping[str, str],
) -> tuple[list[LayerValue], list[LayerValue], list[Ignored]]:
    """Give OpenTelemetry's variables as entries of the endpoint: those below, above, ignored.

    The shared endpoint lies below the file, ignored if refused; ``true`` disables above all.
    """
    below: list[LayerValue] = []
    ignored: list[Ignored] = []
    shared = environ.get(SHARED_ENDPOINT)
    if shared is not None:
        try:
            below.append(
                LayerValue(path=ENDPOINT, value=telemetry_address(shared), layer=SHARED_ENDPOINT)
            )
        except ValueError as error:
            ignored.append(
                Ignored(setting=".".join(ENDPOINT), layer=SHARED_ENDPOINT, why=str(error))
            )
    disabled = environ.get(SDK_DISABLED, "").strip().lower() == "true"
    return (
        below,
        [LayerValue(path=ENDPOINT, value=None, layer=SDK_DISABLED)] if disabled else [],
        ignored,
    )


def settings_of(entries: Iterable[LayerValue], home: Path, model: type[Settings]) -> Loaded:
    """Merge the entries, weakest first, each replacing any at or under its path whole, and build.

    ``~`` is ``home``. Raises SettingsError naming each refusal's setting and layers, never values.
    """
    paths = setting_paths(model)
    at_defaults = [
        LayerValue(path=path, value=value, layer=None)
        for path, value in defaults(model).items()
        if paths[path] == "path"
    ]
    kept: dict[tuple[str, ...], LayerValue] = {}
    replaced: list[tuple[LayerValue, str | None]] = []
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
            value = home.joinpath(*Path(value).parts[1:])
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


def without_secrets(settings: Settings) -> dict[str, object]:
    """Give the settings' values as JSON, each table nested, every secret left out."""
    values = settings.model_dump(mode="json")
    for path, kind in setting_paths(type(settings)).items():
        if kind == "secret":
            reduce(getitem, path[:-1], values).pop(path[-1])
    return values


def with_secrets(values: Mapping[str, object], secrets: Settings) -> Settings:
    """Build settings of the model of ``secrets`` from values without secrets, and its secrets.

    Raises SettingsError naming each setting refused, never its value.
    """
    model = type(secrets)
    tree = copy.deepcopy(dict(values))
    for path, kind in setting_paths(model).items():
        if kind == "secret":
            table = reduce(lambda inner, name: inner.setdefault(name, {}), path[:-1], tree)
            table[path[-1]] = reduce(getattr, path, secrets)
    try:
        return model.model_validate(tree)
    except ValidationError as error:
        raise SettingsError(refused_fields(error)) from None


def unsafe_location(path: Path, home: Path, git_root: Path | None) -> str | None:
    """Say why company data must not live at a resolved path: in a git tree or synced; else None.

    Names compare without regard to case, as on macOS.
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
