# The code's layout

The package `kb_mcp` is grouped by concern: each folder under
`src/kb_mcp/` is a bounded context, holding everything one part of the
program knows, from its pure rules to its effects. So a change to search stays under
`search/`, and a change to how the site answers stays under `sources/atlassian/`. Plan
014 made this layout; Import Linter, run by `uv run lint-imports`, keeps it.
Under the budget, each context converges to
[where the layout is going](#where-the-layout-is-going); the sections before it describe
the contexts that have not yet, and shrink as each does.

## The contexts, in their order

Each context may use those below it, never those above; `search` and `sources`, side by
side, never use each other:

| Context | Its concern |
|---|---|
| `cli` | The command and its subcommands: where everything is put together |
| `evaluation` | How well search and ask answer golden questions (`eval`), and how agents fare with them (`eval-agents`) |
| `mcp` | The tools agents call (`Library`), and answers within their budgets |
| `search` | The index of the mirror, by words and by meaning, and ranking |
| `sources` | Where documents come from: the registry and the stages' interfaces, beside a package per source, nested by stage: `atlassian/`, Confluence and Jira, whose `fetch/` holds the sign-in (the saved session or an API token) and the raw store, and whose `prepare/` writes their documents from that store; `worklog/`, the user's work log, whose `fetch/` reads its folder in place into a copy store, and whose `prepare/` writes its documents |
| `mirror` | What every source writes through and search reads: the front matter, which files are documents, the writer of the files that changed, pandoc and its cache of conversions, the instruments of documents built, the rules of text |
| `config` | The settings: `settings`, their model, its tables and its layers merged, pure; `load`, which reads the file and the environment and guards where data lives; `file`, the settings file and the sources that it names, for the parser |
| `observability` | What a run tells of itself: `observed`, an invocation's logs, on stderr and in its file, and its display; `progress`, tasks and their bars' protocols, without Rich; `http`, requests observed; `telemetry`, the SDK, traces, metrics and logs exported |
| `kernel` | What all share, pure: `names`, the program's and the mirror's names and rules, the busy store, the chunkings, the tools, the bounds of a reranking, the services and their rule, the endings and exit statuses, how a result is written, the slug of a title, for the parser too; `fields`, strict reading of JSON; `records`, the records, a unit's outcome and an invocation |

The order follows what each needs: `eval` ranks through the `Library` of `mcp`, which
ranks with `search`, which indexes the mirror's front matter; each source writes its
documents through the mirror, which imports none of them, so that search and the sources
sit side by side above it; a source's table and a fetch read the settings' rules, which
check keys by the kernel's patterns. `observability` sits just above the kernel, so that
every other context, the settings included, may log, trace and report progress through it,
while it takes from the kernel the invocation that the command line builds, never the
settings.

Some choices are not obvious:

- **No `store/`.** Each store belongs to the context whose model it keeps: the raw store
  to `sources/atlassian/fetch/`, the Markdown files to `mirror`, the index and the
  vectors to `search`.
- **`kernel/` is small**, and holds only what contexts that cannot import one another
  share, in three pure modules. Its `fields` reads JSON already decoded and does no I/O,
  so pure rules may use it; still, only the adapter of a representation reads a response.
- **`evaluation/` is a context of its own**, above `mcp`, since it measures what agents
  get through `Library.ranked`; inside `search` it would make a cycle.
- **`site_html.py` is in `sources/atlassian/prepare/adapters/`**, in the package it
  serves, beside its only user, the prepare of Confluence and Jira. It is still an
  adapter: a fix for the real site's HTML goes there.
- **A run's units are `cli/app/units.py`**, a use case of `cli`: one runner for every
  stage, each unit's entry written as it ends, through `cli/adapters/run_record.py`, the one
  module that knows the run's record, `runs/<run id>/`. `cli/app/sources.py` makes a
  source's unit of its fetcher or preparers, by the path that its declaration names;
  `cli/commands/_runs.py` the units over the whole, and runs a configuration from its
  record, knowing no source, so that `index` and `embed` hold contract E; `_stages.py`,
  which `fetch`, `prepare` and `refresh` share, both. What they choose and say is pure, in
  `cli/domain/sources.py`, so that their declarations stay light, and reads the registry
  that the entry is given, so that it names no source; a run's configuration, its units
  and what each needs before it runs are pure too, in `cli/domain/runs.py`.
- **The index is two interfaces**, declared as protocols in `search/domain/indexes.py`:
  `WordsIndex`, the documents by their words, and `VectorIndex`, their chunks by their
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

Each context but `kernel`, `observability` and `config`, which hold modules as
[where the layout is going](#where-the-layout-is-going) has it, holds the same layers, as
sub-packages, from the top:

| Layer | What it holds |
|---|---|
| `main` | The entry point: the parser, built from every declaration (in `cli` only) |
| `commands` | One run per subcommand, with its result as text; `_shared`, the entry of every run but `completion`'s, that loads the settings, refuses what it can before anything is asked, says what it ignores, asks before a run that writes, runs the chosen one and writes its result; `_embedding`, which the runs that build the index share (in `cli` only) |
| `options` | One light declaration per subcommand: its help, its options, the run it names, the settings it reads, whether it writes, and the pure checks that refuse a run before anything is asked (in `cli` only) |
| `app` | Use cases: they combine effects and rules, and know nothing of the command line |
| `adapters` | Effects: the network, the browser, files, SQLite, subprocesses, the terminal |
| `domain` | Pure rules: decisions and conversions with no I/O, time or environment |

A context holds only the layers it needs; `mcp` has only `app`. In `sources/`, each
stage of a source holds them, as below.

A subcommand is a pair of modules: `cli/options/<name>.py` declares it, and the module
of `cli/commands/` that its declaration names runs it. `--help`, and shell completion at
every Tab, build the whole parser, so they import every declaration; `main` imports the
entry and the chosen run, by name, only once the arguments are parsed, and for a run
that is not observed, such as `completion`'s, which shells run at each start, the run
alone. So a declaration stays light: contract G keeps the packages that runs need out
of `cli.main` and `cli.options`.

## A source and the registry

A connector is a declaration and the code that it names, and a source one instance of
it; [sources](sources.md) says why, and [add a source](../how-to/add-a-source.md) how.
Beside the packages, directly under `sources/`:

| Module | What it holds | Imported by |
|---|---|---|
| `sources/declaration.py` | What a connector declares: `Connector`, `ScopeType`, `DocumentType`, `Option`; and `Source`, one instance of a connector; as dataclasses, since `--help` imports them | every declaration |
| `sources/registry.py` | `CONNECTORS`, one line per connector, `SOURCES`, a source of each, and `refuse`, the rules of any registry | `cli`, whose entry takes the sources as a parameter |
| `sources/stages.py` | The stages' interfaces, `Fetcher` and `Preparer`, what they take and give, `SourceRun`, and what an account's checks give, `Check` | each fetcher and preparer, each account's checks, and `cli`'s units and `doctor` |

The first two stay light for `--help`, and all three are pure, by contracts G and C, which
name them. Each source's package holds:

| Module | What it holds | Loaded |
|---|---|---|
| `declared.py` | The declaration of each connector: its name, scope types, table, location, fetcher, preparers, login and checks by module path | at every parse: contract G keeps it light |
| `settings.py` | The Pydantic model of its table, its sign-in's settings included | with the settings, by the path that its declaration names |
| `fetch/` | Its fetcher, if any, and all that it uses | by the run that uses it |
| `prepare/` | Its preparers, and all that they use | by the run that uses it |

Each source imports the interfaces, `mirror`, `config`'s rules of a table, `observability`
and the kernel. `cli` reaches its fetcher, preparers, login and checks by the paths of its
declaration, never by name.

## The stages within a source

Each source's package holds one sub-package per stage that it takes part in, and each
holds the layers above. Plan 029 nested them so:

- **`fetch/`** reaches a system and keeps the store it owns. For Confluence and Jira:
  the sign-in, HTTP, the two APIs' adapters, the browser and the session file, the raw
  store, a fetch's period, coverage, deletions and files kept; the records that the
  fetch stores and the prepare reads, `content.py`, and their names, `names.py`; and the
  use cases, `fetching.py`, `login.py` and `doctor.py`. For the work log: org's syntax,
  its folder's reader, its documents, the records of its copy store, `copies.py`, the
  store, and the use case, `fetching.py`.
- **`prepare/`** writes documents through the mirror, from its source's store. For
  Confluence and Jira: the site's HTML, the catalogue, the layout of their files, the
  files they own, and the use case, `prepare.py`. For the work log: the layout of its
  files, the files it owns, and its use case, `prepare.py`.

Each stage's module in its `app/` is what the declaration names: `fetch/app/fetcher.py` a
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
| B | Within each context that holds layers, and within each stage of a source, the layers' order. It is exhaustive too: a module outside a layer breaks it. A module put directly in a source's package, but `declared` and `settings`, breaks J; one put directly in `sources/` is outside B and J: A still orders it with `sources`, and `declaration`, `registry` and `stages` are named under C, the first two under G too, so a new one joins their lists, or no contract checks its layer or its use of `httpx` |
| C | Pure rules, in any context, the pure modules of `kernel` and `config` named, with the declarations and the modules beside the sources' packages, use no effect and no use case, nor any package of T2's list: a rule neither logs, traces nor draws, nor reaches the network, a file, a process or the environment |
| D | Effects, in any context, use no use case |
| E | Search, the server and the evaluation, with their commands, `index` and `embed` among them, read the mirror, never a source: the index is built from the mirror alone |
| F | Use cases and commands reach the network through effects only (no `httpx`), and of `kernel`, `config` and `observability`, `observability.http` alone imports it |
| G | Declaring the command, `cli.main` and `cli.options`, with the registry, each source's declaration, and what they read of `kernel.names`, `kernel.fields` and `config.file`, imports none of the packages that runs need: the MCP SDK, Playwright, httpx, NumPy, lxml, PyYAML, Pydantic, Rich, OpenTelemetry, requests, structlog and platformdirs |
| H | Only `observability` and `cli` use Rich, which draws on the terminal, and requests, which OpenTelemetry's exporters bring: the rest reaches the network by httpx. It counts indirect imports, so what the other contexts import of `observability` reaches neither. It names every other context, so a new one joins its list as it joins A's order, and `observability.progress`, through which they all report progress, so that it never imports the display that draws it |
| I | No source imports another, `sources.atlassian` and `sources.worklog`: a list that a test holds to the packages of the registry's declarations, so a new source's package joins it |
| J | Within each source, from the top: its declaration, preparing, fetching, its settings: the declaration names the fetcher and preparers by path and imports neither, and preparing may use fetching, never the reverse. It is exhaustive: a source's package holds these alone |
| K | Only `sources.atlassian` uses lxml and Playwright, so that an extra can hold them later: every other context, the modules beside the sources' packages, `sources.worklog` and `sources.atlassian.settings`, which every command loads by its path, import neither, as `cli` loads what uses them by the declarations' paths. It names every other context, so a new one, or a new source, joins its list, as H's does |

A orders the contexts, which B, applied per context, does not; C and D carry the order
of the layers across contexts, which B cannot; I keeps the sources apart, and J the
stages of each in their order, which A, ordering whole contexts, cannot. All but F count
indirect imports too. None sees an import by name, as `main` makes of the entry and the
run, or of the run alone: a test of `tests/test_cli.py` checks, in a fresh interpreter,
that `--help` and a completion import none of G's packages. And a contract forbids only
the root of another package, which OpenTelemetry's API and SDK share: so
`tests/test_code_layout.py` keeps the SDK, its exporters and its instrumentation within
`observability`, while the other contexts use the API alone.

## Records

A record is a value of the program: a document, a setting's layer, a run's outcome. Each
is a `kernel.records.Record`, a Pydantic model built by keyword and checked at
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
  as `RenderContext.unsupported` is.
- A record has no order: a sort of records takes a `key=`. A frozen record hashes by its
  fields; one that accumulates has no hash, as a dataclass that was not frozen.
- A protocol is never a record's base, as its metaclass and Pydantic's conflict: a
  record that implements one, such as `site_html.HtmlPart` a `Construct` or
  `observed.TaskBar` a `Bar`, has `Record` for its base and meets the protocol by its
  methods.
- Pydantic reads a record's annotations, so the types they name are imported at run
  time, never under `TYPE_CHECKING`, and so is a `type` alias that they name. Ruff
  knows records by their base, `kb_mcp.kernel.records.Record`, which `ruff.toml` names
  among its runtime-evaluated base classes, and reports an import to move as TC004; it
  does not report an alias. A record base defined in one module and subclassed in
  another joins that list.

Fifteen classes stay dataclasses, each for its reason; `tests/test_code_layout.py` checks
that every dataclass under `src/kb_mcp/` is in this table, and that every class of the
table is one:

| Class | Why it stays a dataclass |
|---|---|
| `cli.domain.command.Command` | G: `--help` imports it |
| `kernel.names.Service` | G: `--help` imports it |
| `sources.atlassian.fetch.domain.period.Period` | G: `--help` imports it |
| `sources.declaration.Connector` | G: `--help` imports it |
| `sources.declaration.DocumentType` | G: `--help` imports it |
| `sources.declaration.Option` | G: `--help` imports it |
| `sources.declaration.ScopeType` | G: `--help` imports it |
| `sources.declaration.Source` | G: `--help` imports it |
| `evaluation.app.reranked.Arms` | It holds a live client, the reranker's |
| `search.adapters.embedding.ApiEmbedder` | It holds a live client, its `Endpoint` |
| `search.adapters.model_api.Endpoint` | It holds a live client, httpx's |
| `sources.atlassian.fetch.app.fetching.Fetching` | It holds the raw store under its lock and the site's client |
| `evaluation.app.evaluation.EvaluatedIndex` | Pydantic cannot build it: a field is typed by the protocol `Embedder` |
| `observability.progress.Task` | Pydantic cannot build it: a field is typed by the protocol `Bar` |
| `search.app.indexing.Embedding` | Pydantic cannot build it: a field is typed by the protocol `Embedder` |

A new dataclass needs a row here with its reason, of these three kinds: a module that
`--help` or completion imports, which contract G keeps from Pydantic; a live connection,
client, lock or process; or a type that Pydantic cannot build, which `SkipValidation`
would only hide. Any other value is a record.

## Where a new module goes

In a context that has converged, a new module follows
[where the layout is going](#where-the-layout-is-going); in any other:

1. Find the concern it serves, and so its context. A new source of documents is a new
   package under `sources/`, with its declaration, its table and a sub-package per stage it
   takes part in, `fetch/` and `prepare/`, each with its own layers; a line of the registry; and a
   place in the lists of contracts I and K, as [add a source](../how-to/add-a-source.md)
   says.
2. Within the context, or the stage, put it in the layer of what it does: a rule without
   effects in `domain/`, an effect in `adapters/`, a use case in `app/`.
3. Run `uv run lint-imports`. A broken contract says which import crosses a boundary;
   move the code, or the import, rather than the boundary. A module that fits no
   context needs a split, or a new context placed in contract A's order and H's list.

## Where the layout is going

The code has a budget to reach, 12,000 lines of code, 70 files and 160 types;
[the trade-offs](trade-offs.md#a-budget-of-twelve-thousand-lines) say why. One plan at a
time converges a context, or a part of one, to the layout below, bottom-up in contract
A's order, so that no converged context is reopened; the sections above then describe
only the contexts that have not converged, and shrink. `tests/test_code_size.py` holds
each context's targets in lines, files and types, and lists those that have converged,
which their targets then hold.

- **T1. The contracts keep their intent.** The plan that converges a context rewrites
  each over its modules: A, the order of the contexts; E, the mirror's readers never
  read a source; G, declaring the command imports none of the packages that runs need;
  H, Rich and requests in `observability` and `cli` alone; I, no source imports another;
  J, within a source, its declaration, preparing, fetching and its settings, over
  modules; K, lxml and Playwright in the Atlassian package alone; and the test that
  keeps OpenTelemetry's SDK within `observability`. F, the network through effects only,
  becomes `httpx` imported only by the modules that its contract names. B, C and D lapse
  with the layers, T2 taking C's purpose.
- **T2. Modules, not layers.** A context holds no `commands`, `options`, `app`,
  `adapters` or `domain` sub-packages: a module per concept or concern, named by it. A
  source keeps its declaration and its settings as modules, and its fetch and its
  prepare each as a module or a flat package, so that J holds. Decisions stay apart from
  effects: each converged context's contract names its pure modules, every other module
  of it being an effect. A pure module imports no effect module of any context, nor
  `httpx`, `sqlite3`, `subprocess`, `socket`, `ssl`, `requests`, `truststore`,
  `certifi`, `anyio`, Playwright, the MCP SDK, structlog, `logging`, OpenTelemetry,
  Rich, `os`, `sys`, `time`, `fcntl`, `tempfile`, `shutil`, `threading`, `secrets`,
  `uuid`, `random`, `importlib` or `platformdirs`. It may build
  paths with `pathlib`; reading or writing through them, `open`, and the clock through
  `datetime.now` are findings of the review.
- **T3. A port only where it pays.** A `Protocol` only where two implementations exist,
  or where a test needs a fake of a server that the program calls, such as a model
  server or a site; elsewhere the concrete class.
- **T4. A record where data crosses a boundary.** A record for data that is served,
  stored or passed between contexts, or that holds an invariant. An internal value stays
  in its caller's variables, or is returned as a tuple only where its elements differ in
  type or are unpacked at the call, else as a record; never a dict standing for a
  record. No type re-spells another: such pairs are retired or unified, as the skill
  `principles:concept-design` names the move. [Records](#records) describes the contexts
  not yet converged, until the last plan rewrites it.
- **T5. A docstring states the contract.** Ruff's docstring rules stay. A docstring
  states, in a line or two, the contract that the name and the signature do not; a
  comment does not stand in for it, comment lines being held by their ceilings. Text
  that the program serves or prints, such as a tool's description or a command's help,
  is product text, and is kept.
- **T6. No module over 700 lines of code.**
- **T7. Parity.** What the manifest, `tests/fixtures/parity.json`, the hand-written
  reference pages ([the MCP tools](../reference/mcp-tools.md),
  [the data layout](../reference/data-layout.md),
  [telemetry](../reference/telemetry/README.md)) and the tests of behaviour hold is
  kept, unless a plan's decision, approved by the user, changes it.
- **T8. Each type has a home.** On [the concepts page](../reference/concepts.md), an
  entry's **Home.**, after its **In the code.** and in the same form, a paragraph in a
  core entry and a `- **Home.**` bullet in a context entry, names its types in plain
  backticks. A type is homed by the concept it carries, an error by the concept it
  refuses, a port by the concept it serves. *Mechanics* is a table,
  `| Role | Home | Why |`, its role bare in the first cell: `wiring`, `adapter`,
  `telemetry` or `utility`. *Not yet modelled* is a table, `| Concept | Meaning | Home |`,
  of the concepts that a later plan defines. *Kept apart* holds one bullet per pair of
  look-alikes, `` `A` and `B`: `` then the purpose of each.
