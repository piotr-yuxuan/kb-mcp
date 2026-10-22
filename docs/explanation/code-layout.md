# The code's layout

The package `atlassian_offline_mcp` is grouped by concern: each folder under
`src/atlassian_offline_mcp/` is a bounded context, holding everything one part of the
program knows, from its pure rules to its effects. So a change to search stays under
`search/`, and a change to how the site answers stays under `sources/atlassian/`. Plan
014 made this layout; Import Linter, run by `uv run lint-imports`, keeps it.

## The contexts, in their order

Each context may use those below it, never those above:

| Context | Its concern |
|---|---|
| `cli` | The command and its subcommands: where everything is put together |
| `evaluation` | How well search answers golden questions (`eval`) |
| `mcp` | The tools agents call (`Library`), and answers within their budgets |
| `search` | The index of the mirror, by words and by meaning, and ranking |
| `mirror` | The raw store's newest snapshots as Markdown, with their front matter |
| `sources` | Where documents come from: today `atlassian/`, Confluence and Jira, with the session and the raw store |
| `config` | The settings, their file, and the guard on where data lives |
| `kernel` | What all share: the vocabulary of what the mirror holds, strict reading of JSON, exit statuses, how a run reports |

The order follows what each needs: `eval` ranks through the `Library` of `mcp`, which
ranks with `search`, which indexes the mirror's front matter; the mirror reads the raw
store of `sources`; a download reads the settings, which check keys by the kernel's
patterns.

Some choices are not obvious:

- **No `store/`.** Each store belongs to the context whose model it keeps: the raw store
  to `sources`, the Markdown files to `mirror`, the index and the vectors to `search`.
- **`kernel/` is small**, and holds only what contexts that cannot import one another
  share. It has no layers. Its `fields` reads JSON already decoded and does no I/O, so
  pure rules may use it; still, only the adapter of a representation reads a response.
- **`evaluation/` is a context of its own**, above `mcp`, since it measures what agents
  get through `Library.ranked`; inside `search` it would make a cycle.
- **`site_html.py` is in `mirror/adapters/`**, beside its only user. It is still an
  adapter: a fix for the real site's HTML goes there.
- **The MCP SDK is known to `cli/commands/serve.py` alone**, which registers the methods
  of `mcp.app.tools.Library` as tools.

## The layers within a context

Each context but the kernel holds the same layers, as sub-packages, from the top:

| Layer | What it holds |
|---|---|
| `main` | The entry point: the parser, built from every declaration (in `cli` only) |
| `commands` | One run per subcommand, with its result as text, and `_shared`, the entry that loads the settings, runs the chosen one and writes its result (in `cli` only) |
| `options` | One light declaration per subcommand: its help, its options and the run it names (in `cli` only) |
| `app` | Use cases: they combine effects and rules, and know nothing of the command line |
| `adapters` | Effects: the network, the browser, files, SQLite, subprocesses |
| `domain` | Pure rules: decisions and conversions with no I/O, time or environment |

A context holds only the layers it needs; `mcp` has only `app`.

A subcommand is a pair of modules: `cli/options/<name>.py` declares it, and the module
of `cli/commands/` that its declaration names runs it. `--help`, and shell completion at
every Tab, build the whole parser, so they import every declaration; `main` imports the
entry and the chosen run, by name, only once the arguments are parsed. So a declaration
stays light: contract G keeps the packages that runs need out of `cli.main` and
`cli.options`.

## The contracts

`pyproject.toml` declares seven contracts:

| | What it protects |
|---|---|
| A | Contexts use those below them, never those above. It is exhaustive: a new top-level package breaks it until it is placed in the order |
| B | Within each context, the layers' order. It is exhaustive too: a module outside a layer breaks it. Each source under `sources/` is a context of its own; a module put directly in `sources/` is outside B: A still orders it with `sources`, but no contract checks its layer or its use of `httpx`, so none goes there |
| C | Pure rules, in any context (and the kernel), use no effect and no use case |
| D | Effects, in any context, use no use case |
| E | Search, the server and the evaluation read the mirror, never a source: the index is built from the mirror alone |
| F | Use cases and commands reach the network through effects only (no `httpx`) |
| G | Declaring the command, `cli.main` and `cli.options`, imports none of the packages that runs need: the MCP SDK, Playwright, httpx, NumPy, lxml, PyYAML, Pydantic, Rich, OpenTelemetry, and plan 016's structlog and platformdirs |

A orders the contexts, which B, applied per context, does not; C and D carry the order
of the layers across contexts, which B cannot. All but F count indirect imports too.
None sees an import by name, as `main` makes of the entry and the run: a test of
`tests/test_cli.py` checks, in a fresh interpreter, that `--help` and a completion
import none of G's packages.

## Where a new module goes

1. Find the concern it serves, and so its context. A new source of documents is a new
   package under `sources/`, with its own layers.
2. Within the context, put it in the layer of what it does: a rule without effects in
   `domain/`, an effect in `adapters/`, a use case in `app/`.
3. Run `uv run lint-imports`. A broken contract says which import crosses a boundary;
   move the code, or the import, rather than the boundary. A module that fits no
   context needs a split, or a new context placed in contract A's order.
