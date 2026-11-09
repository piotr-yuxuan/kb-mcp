# The code's layout

The package `kb_mcp` is grouped by concern: each folder under
`src/kb_mcp/` is a bounded context, holding everything one part of the
program knows, from its pure rules to its effects. So a change to search stays under
`search/`, and a change to how the site answers stays under `sources/atlassian/`. Plan
014 made this layout; Import Linter, run by `uv run lint-imports`, keeps it.

## The contexts, in their order

Each context may use those below it, never those above; `search` and `sources`, side by
side, never use each other:

| Context | Its concern |
|---|---|
| `cli` | The command and its subcommands: where everything is put together |
| `evaluation` | How well search and ask answer golden questions (`eval`), and how agents fare with them (`eval-agents`) |
| `mcp` | The tools agents call (`Library`), and answers within their budgets |
| `search` | The index of the mirror, by words and by meaning, and ranking |
| `sources` | Where documents come from: the registry and the roles' interfaces, beside a package per source, nested by role: `atlassian/`, Confluence and Jira, whose `fetch/` holds the sign-in (the saved session or an API token) and the raw store, and whose `prepare/` writes their documents from that store; `worklog/`, the user's work log, read in place, with `prepare/` alone |
| `mirror` | What every source writes through and search reads: the front matter, which files are documents, the writer of the files that changed, pandoc and its cache of conversions, the instruments of documents built, the rules of text |
| `config` | The settings, their file, and the guard on where data lives |
| `observability` | What a run tells of itself: structured logs, progress on the terminal, traces and metrics |
| `kernel` | What all share: the rules of the names of the mirror's sources, ids, keys and revisions, strict reading of JSON, exit statuses, how a run reports, whether an endpoint is this machine and how each service there is named and started, the bounds of a reranking, the names of the chunkings and of the server's tools, the slug of a title |

The order follows what each needs: `eval` ranks through the `Library` of `mcp`, which
ranks with `search`, which indexes the mirror's front matter; each source writes its
documents through the mirror, which imports none of them, so that search and the sources
sit side by side above it; a source's table and a download read the settings' rules, which
check keys by the kernel's patterns. `observability` sits just above the kernel, so that
every other context, the settings included, may log, trace and report progress through it,
while it takes from the kernel only how a run reports: the command line hands it plain
values, never the settings.

Some choices are not obvious:

- **No `store/`.** Each store belongs to the context whose model it keeps: the raw store
  to `sources/atlassian/fetch/`, the Markdown files to `mirror`, the index and the
  vectors to `search`.
- **`kernel/` is small**, and holds only what contexts that cannot import one another
  share. It has no layers. Its `fields` reads JSON already decoded and does no I/O, so
  pure rules may use it; still, only the adapter of a representation reads a response.
- **`evaluation/` is a context of its own**, above `mcp`, since it measures what agents
  get through `Library.ranked`; inside `search` it would make a cycle.
- **`site_html.py` is in `sources/atlassian/prepare/adapters/`**, in the package it
  serves, beside its only user, the prepare of Confluence and Jira. It is still an
  adapter: a fix for the real site's HTML goes there.
- **`fetch`'s and `prepare`'s rows are `cli/app/sources.py`**, a use case of `cli`: it runs
  each source's role, a row each, by the path that its declaration names. What they choose
  and say is pure, in `cli/domain/sources.py`, so that their declarations stay light, and
  reads the registry that the entry is given, so that it names no source.
- **The index is two interfaces**, declared as protocols in `search/domain/indexes.py`:
  `WordsIndex`, the documents by their words, and `VectorIndex`, their pieces by their
  vectors, each opening one use by `reading()` and changing all or nothing, by `update`
  and `fill`, with `SearchIndex`, the two together, which a search reads in one use.
  They name domain types alone, so contract C holds, and
  `tests/test_index_contract.py` holds every backend to their docstrings. Callers type
  against them: the use cases, `Meaning`, `Library` and the evaluation. The one backend,
  `search.adapters.sqlite_index.SqliteIndex`, is made where the index's path is
  resolved: the use cases of `index` and `embed`, `cli/commands/serve.py`,
  `evaluate.py`, `evaluate_agents.py` and `evaluate_reranking.py`, and
  `evaluation/app/evaluation.py`; a second backend would add a setting there. The handle
  is an argument, never a record's field, as Pydantic cannot build a field typed by a
  protocol: no dataclass joins [the table below](#records) for it.
- **The MCP SDK is known to two modules**: `cli/commands/serve.py`, which registers the
  methods of `mcp.app.tools.Library` as tools, with what `mcp.app.surface` composes, and
  `evaluation/adapters/mcp_client.py`, the client through which `eval-agents` reaches
  the server as an agent does.

## The layers within a context

Each context but the kernel holds the same layers, as sub-packages, from the top:

| Layer | What it holds |
|---|---|
| `main` | The entry point: the parser, built from every declaration (in `cli` only) |
| `commands` | One run per subcommand, with its result as text; `_shared`, the entry of every run but `completion`'s, that loads the settings, refuses what it can before anything is asked, says what it ignores, asks before a run that writes, runs the chosen one and writes its result; `_embedding`, which the runs that build the index share (in `cli` only) |
| `options` | One light declaration per subcommand: its help, its options, the run it names, the settings it reads, whether it writes, and the pure checks that refuse a run before anything is asked (in `cli` only) |
| `app` | Use cases: they combine effects and rules, and know nothing of the command line |
| `adapters` | Effects: the network, the browser, files, SQLite, subprocesses, the terminal |
| `domain` | Pure rules: decisions and conversions with no I/O, time or environment |

A context holds only the layers it needs; `mcp` has only `app`. In `sources/`, each
role of a source holds them, as below.

A subcommand is a pair of modules: `cli/options/<name>.py` declares it, and the module
of `cli/commands/` that its declaration names runs it. `--help`, and shell completion at
every Tab, build the whole parser, so they import every declaration; `main` imports the
entry and the chosen run, by name, only once the arguments are parsed, and for a run
that is not observed, such as `completion`'s, which shells run at each start, the run
alone. So a declaration stays light: contract G keeps the packages that runs need out
of `cli.main` and `cli.options`.

## A source and the registry

A source is a declaration and the code that it names; [sources](sources.md) says why, and
[add a source](../how-to/add-a-source.md) how. Beside the packages, directly under
`sources/`:

| Module | What it holds | Imported by |
|---|---|---|
| `sources/declaration.py` | What a source declares: `Source`, `ResourceType`, `Option`, `Account`, as dataclasses, since `--help` imports them | every declaration |
| `sources/registry.py` | `SOURCES`, one line per source, and `refuse`, the rules of any registry | `cli`, whose entry takes a registry as a parameter |
| `sources/stages.py` | The roles' interfaces, `Fetcher` and `Preparer`, what they take and give, `SourceRun` and `Result`, and what a sign-in and its checks give, `SignedIn` and `Verdict` | each role, each account's sign-in and checks, and `cli`'s `run_each`, `login` and `doctor` |

The first two stay light for `--help`, and all three are pure, by contracts G and C, which
name them. Each source's package holds:

| Module | What it holds | Loaded |
|---|---|---|
| `declared.py` | The declaration: its name, resource types, table, account and roles by module path | at every parse: contract G keeps it light |
| `settings.py` | The Pydantic models of its table and its account | with the settings, by the path that its declaration names |
| `fetch/` | Its fetcher, if any, and all that it uses | by the run that uses it |
| `prepare/` | Its preparers, and all that they use | by the run that uses it |

Each source imports the interfaces, `mirror`, `config`'s rules of a table, `observability`
and the kernel. `cli` reaches its roles by the paths of its declaration, and its sign-in
and checks by those of its account, never by name.

## The roles within a source

Each source's package holds one sub-package per role, and each role holds the layers
above. Plan 029 nested them so:

- **`fetch/`** reaches a system and keeps the store it owns. For Confluence and Jira:
  the sign-in, HTTP, the two APIs' adapters, the browser and the session file, the raw
  store, a download's period, coverage, deletions and files kept; the records that the
  fetch stores and the prepare reads, `content.py`; and the use cases, `fetching.py`,
  `login.py` and `doctor.py`.
- **`prepare/`** writes documents through the mirror, from its source's store or from a
  folder read in place. For Confluence and Jira: the site's HTML, the catalogue, the
  layout of their files, the files they own, and the use case, `prepare.py`. The work log
  has `prepare/` alone, being read in place: org's syntax, its folder's reader, its
  documents and their layout, the files it owns, and its step.

Each role's module in its `app/` is what the declaration names: `fetch/app/fetcher.py` a
`Fetcher`, `prepare/app/preparer.py` a `Preparer`. Preparing may use what fetching keeps,
never the reverse, both may read the tables, and no source imports another: contracts J
and I.

## The contracts

`pyproject.toml` declares eleven contracts, A to K, each with its letter as its id, so
that `uv run lint-imports --contract J` checks one alone; `tests/test_code_layout.py`
checks the ids, in their order, against this table:

| | What it protects |
|---|---|
| A | Contexts use those below them, never those above, and `search` and `sources`, side by side, never use each other. It is exhaustive: a new top-level package breaks it until it is placed in the order |
| B | Within each context, and within each role of a source, the layers' order. It is exhaustive too: a module outside a layer breaks it. A module put directly in a source's package, but `declared` and `settings`, breaks J; one put directly in `sources/` is outside B and J: A still orders it with `sources`, and `declaration`, `registry` and `stages` are named under C, the first two under G too, so a new one joins their lists, or no contract checks its layer or its use of `httpx` |
| C | Pure rules, in any context (and the kernel), with the declarations and the modules beside the sources' packages, use no effect and no use case, nor structlog, OpenTelemetry or Rich: a rule neither logs, traces nor draws |
| D | Effects, in any context, use no use case |
| E | Search, the server and the evaluation, with their commands, `index` and `embed` among them, read the mirror, never a source: the index is built from the mirror alone |
| F | Use cases and commands reach the network through effects only (no `httpx`) |
| G | Declaring the command, `cli.main` and `cli.options`, with the registry and each source's declaration, imports none of the packages that runs need: the MCP SDK, Playwright, httpx, NumPy, lxml, PyYAML, Pydantic, Rich, OpenTelemetry, requests, structlog and platformdirs |
| H | Only `observability` and `cli` use Rich, which draws on the terminal, and requests, which OpenTelemetry's exporters bring: the rest reaches the network by httpx. It counts indirect imports, so what the other contexts import of `observability` reaches neither. It names every other context, so a new one joins its list as it joins A's order, and `observability.adapters.progress`, through which they all report progress, so that it never imports the display that draws it |
| I | No source imports another, `sources.atlassian` and `sources.worklog`: a list that a test holds to the packages of the registry's declarations, so a new source's package joins it |
| J | Within each source, from the top: its declaration, preparing, fetching, its settings: the declaration names the roles by path and imports neither, and preparing may use fetching, never the reverse. It is exhaustive: a source's package holds these alone |
| K | Only `sources.atlassian` uses lxml and Playwright, so that an extra can hold them later: every other context, the modules beside the sources' packages, `sources.worklog` and `sources.atlassian.settings`, which every command loads by its path, import neither, as `cli` loads what uses them by the declarations' paths. It names every other context, so a new one, or a new source, joins its list, as H's does |

A orders the contexts, which B, applied per context, does not; C and D carry the order
of the layers across contexts, which B cannot; I keeps the sources apart, and J the
roles of each in their order, which A, ordering whole contexts, cannot. All but F count
indirect imports too. None sees an import by name, as `main` makes of the entry and the
run, or of the run alone: a test of `tests/test_cli.py` checks, in a fresh interpreter,
that `--help` and a completion import none of G's packages. And a contract forbids only
the root of another package, which OpenTelemetry's API and SDK share: so
`tests/test_code_layout.py` keeps the SDK, its exporters and its instrumentation within
`observability`, while the other contexts use the API alone.

## Records

A record is a value of the program: a document, a setting's layer, a run's outcome. Each
is a `kernel.record.Record`, a Pydantic model built by keyword and checked at
construction, frozen unless it accumulates as a run goes (`model_config =
ConfigDict(frozen=False)`). A record refuses a keyword it does not know, and its errors
never print a value. Plan 028 made the program's dataclasses records. Their rules:

- A record's own checks are a validator, `@model_validator(mode="after")`, which raises
  `kernel.names.RefusedError`; the constructor raises that error as it is, not wrapped
  in Pydantic's, so callers and messages see the field and the rule alone.
- `copy.replace(record, field=value)` gives a record with some fields changed, checked
  again; Pydantic's `model_copy` and `model_construct` skip the checks, so no record
  uses them. `model_dump()` gives a record's values, `model_fields` its fields' names,
  in their order.
- A model copies a list, a dict or a `Counter` that it is given: a field whose object
  the caller keeps using is typed `InstanceOf[...]`, which checks its class and keeps it,
  as `Context.unsupported` is.
- A record has no order: a sort of records takes a `key=`. A frozen record hashes by its
  fields; one that accumulates has no hash, as a dataclass that was not frozen.
- A protocol is never a record's base, as its metaclass and Pydantic's conflict: a
  record that implements one, such as `site_html.Part` a `Construct` or
  `display.TaskBar` a `Bar`, has `Record` for its base and meets the protocol by its
  methods.
- Pydantic reads a record's annotations, so the types they name are imported at run
  time, never under `TYPE_CHECKING`, and so is a `type` alias that they name. Ruff
  knows records by their base, `kb_mcp.kernel.record.Record`, which `ruff.toml` names
  among its runtime-evaluated base classes, and reports an import to move as TC004; it
  does not report an alias. A record base defined in one module and subclassed in
  another joins that list.

Fifteen classes stay dataclasses, each for its reason; `tests/test_code_layout.py` checks
that every dataclass under `src/kb_mcp/` is in this table, and that every class of the
table is one:

| Class | Why it stays a dataclass |
|---|---|
| `cli.domain.command.Command` | G: `--help` imports it |
| `kernel.endpoint.Service` | G: `--help` imports it |
| `kernel.output.Output` | G: `--help` imports it |
| `sources.atlassian.fetch.domain.period.Period` | G: `--help` imports it |
| `sources.declaration.Account` | G: `--help` imports it |
| `sources.declaration.Source` | G: `--help` imports it |
| `sources.declaration.Option` | G: `--help` imports it |
| `sources.declaration.ResourceType` | G: `--help` imports it |
| `evaluation.app.reranked.Arms` | It holds a live client, the reranker's |
| `search.adapters.embedding.ApiEmbedder` | It holds a live client, its `Endpoint` |
| `search.adapters.model_api.Endpoint` | It holds a live client, httpx's |
| `sources.atlassian.fetch.app.fetching.Fetching` | It holds the raw store under its lock and the site's client |
| `evaluation.app.evaluation.Target` | Pydantic cannot build it: a field is typed by the protocol `Embedder` |
| `observability.adapters.progress.Task` | Pydantic cannot build it: a field is typed by the protocol `Bar` |
| `search.app.indexing.Embedding` | Pydantic cannot build it: a field is typed by the protocol `Embedder` |

A new dataclass needs a row here with its reason, of these three kinds: a module that
`--help` or completion imports, which contract G keeps from Pydantic; a live connection,
client, lock or process; or a type that Pydantic cannot build, which `SkipValidation`
would only hide. Any other value is a record.

## Where a new module goes

1. Find the concern it serves, and so its context. A new source of documents is a new
   package under `sources/`, with its declaration, its table and a sub-package per role it
   has, `fetch/` and `prepare/`, each with its own layers; a line of the registry; and a
   place in the lists of contracts I and K, as [add a source](../how-to/add-a-source.md)
   says.
2. Within the context, or the role, put it in the layer of what it does: a rule without
   effects in `domain/`, an effect in `adapters/`, a use case in `app/`.
3. Run `uv run lint-imports`. A broken contract says which import crosses a boundary;
   move the code, or the import, rather than the boundary. A module that fits no
   context needs a split, or a new context placed in contract A's order and H's list.
