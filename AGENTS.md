# Instructions for coding agents

An offline mirror of Confluence, Jira Cloud and a work log, served to coding agents over
MCP. The repository is meant to become public: never commit an employer's name, a site
URL other than the sandbox's, identifiers or content. Fixtures come only from the sandbox
site; `sandbox/corpus/` and `sandbox/jira/` are the fixtures of a fictional company,
never this project's docs.

## Workflow

Follow the `workflow:plans` skill with these parameters:

- Plans are `docs/work/plans/NNN-slug.md`, each beside its `NNN-checks.sh`, untracked:
  `docs/work/` is git-ignored and never committed; parked ones are under
  `docs/work/held/`, done ones under `docs/work/changelog/`. Records under `docs/work/`
  are history, never a contract.
- Checks, run in full before each review and each merge:
  - `uv run ruff check` and `uv run ruff format --check`;
  - `uv run lint-imports`;
  - `uv run pytest -n 4`, on four workers by pytest-xdist, to keep a laptop cool, where
    CI and the tutorial spread over every core;
  - `uv run --with-requirements sandbox/seed_corpus.py --with pytest pytest sandbox`,
    which needs pandoc on `PATH`.
- The design: why each decision was taken and what it costs, in
  [the trade-offs](docs/explanation/trade-offs.md); how the stages work together, in
  [the internals](docs/explanation/internals.md); the formats that the stages share, in
  [the data layout](docs/reference/data-layout.md); where code goes, in
  [the code's layout](docs/explanation/code-layout.md), and in a converged context
  [where the layout is going](docs/explanation/code-layout.md#where-the-layout-is-going);
  the plans, in the roadmap, `docs/work/roadmap.md`, untracked. Only the adapter of a
  representation reads its JSON, and only one module knows the site's HTML.
- The budget: the goal for `src/` is 12,000 lines of code, 70 files and 160 types, with
  no module over 700 lines of code, reached one context at a time. Meanwhile each
  context's ceilings hold it, comment lines included, each falling as it shrinks; once a
  plan has converged a context, or a part of one, its targets hold it too, the contexts'
  targets summing within the goal. `tests/test_code_size.py` holds both. A plan sets
  each ceiling that it changes at its bound; raising one needs the user's word, which the
  approval of a draft whose expected deltas raise it gives.
- What the program offers, its commands, options, settings, MCP tools and prompts, and
  telemetry names, is in the manifest `tests/fixtures/parity.json`, which
  `uv run python -m tests.parity` writes. Nothing leaves it but by a decision that the
  user approves, in the plan that edits it.
- Each plan states in its draft what it expects to change in lines, files, types,
  comment lines and concept entries, per context, and in its record what it changed.
- Each plan under the budget converges one context, or a part of one named in `PARTS`,
  whole, one plan at a time, bottom-up in contract A's order, so that no converged
  context or part is reopened. Its draft defines, with the user, the concepts that it
  adds, before any code. Then three phases, each in commits of its own:
  1. the tests of what it converges are rewritten onto its interface, against the old
     code, with no change under `src/`, pinning every key of the JSON that its commands
     print or serve and every stored format that it writes;
  2. the candidates of the type audit, under `docs/work/research/`, are made as moves of
     `principles:concept-design`, declared in *Concepts* with what each gains and costs,
     changing no assertion; the moves are the request, so the limit of one move made
     beside another request, in `workflow:plans`, does not bound them;
  3. the code is rewritten to the target layout, changing no assertion: its types are
     homed, its contracts rewritten, its ceilings set at their bounds, and it joins
     `CONVERGED`, within its targets or back to the user.

  A dependent plan is revised once its dependency starts; its branch is cut from the
  dependency's tip once the dependency's review starts, and rebased after it merges.
- A new page goes in the folder of `docs/` named by its Diataxis kind, and
  [the map](docs/README.md) links it in the commit that writes it. The reference of
  commands and settings is generated from the code: after changing a command, an option
  or a setting, run `uv run python -m tests.reference_pages` and commit the pages it
  rewrites; else the reference test fails, naming them.
- What runs log, trace and measure: `docs/reference/telemetry/`, changed with the code.
- At most three review rounds.

## The concepts

[The concepts](docs/reference/concepts.md) define the program's words, each once; new
code takes them, and the names of each entry's "In the code" paragraph.

- Each plan has a section *Concepts*, which the review of its draft checks against the
  concepts and against the other plans under `docs/work/plans/` and `docs/work/held/`:

  ```markdown
  ## Concepts

  Adds: <concepts or context words>
  Changes: <and how>
  Retires: <and what replaces them>
  Relies on: <concepts used unchanged>
  ```

- A definition changes only in a plan whose *Concepts* declares the change, and never
  to make a check pass; the pre-merge summary shows the page's diff. An "In the code"
  paragraph follows the code in the commit that changes it.
- The entries under *Core concepts* and *Context vocabulary* stay within the ceiling
  that `tests/test_concepts.py` holds, itself within the budget's 35. A plan raises it
  only by declaring the new concept in its *Concepts*, approved by the user.
- Definitions are timeless. Where the code differs from one goes in
  [the differences](docs/reference/differences.md), classed as that page says.
- A plan that changes a core concept rewrites its line below, and the opening paragraph
  of the concepts, in the same commit.
- Tests take their expectations from the concepts, the trade-offs and the reference
  written by hand, never from the implementation nor from a page generated from it,
  such as the commands and the settings.
- The diagrams, such as [the entity-relationship views](docs/reference/concepts-er.html),
  are derived from the concepts and the trade-offs, drawn with the skill
  `diagram-design:diagram-design` under the profile that `.diagram-design` names; a plan
  that changes what one shows redraws it.

### The core concepts

Each line summarises its entry in [the concepts](docs/reference/concepts.md#core-concepts),
which rules.

```
connector  the code that reads one kind of origin, which it never writes
source     one configured instance of a connector: a name, a location, a sign-in
scope      a part of one source that the user selects, read and tracked as a unit
document   a unit of content that an origin holds and a scope lists: (source, id)
section    one part of a document's body, from one heading to the next
person     what the program takes for one human: the mentions joined as one
ranking    the ordered answer to a query: sections, at most one per document
tool       an operation that the server offers an agent
stage      one of the four steps of the pipeline: fetch, prepare, index, embed
run        what the program does for one command, known by its run id
store      durable data that the program owns and keeps between runs
service    a server, other than an origin, that a run sends text to, under a rule
```

Words to avoid: an origin's own words to define a concept in general, such as
Confluence's node or space tree; identity, for a document's id, since it is kept for
persons; people, for a count of persons. Connector and scope never mean an MCP client's
connector or `--scope`, nor an API token's scopes.

## Layout

The top-level folders; [the code's layout](docs/explanation/code-layout.md) says where
code goes, and [the map](docs/README.md) lists the pages.

```
src/kb_mcp/  the package, one folder per bounded context
tests/       the tests and their fixtures
sandbox/     the fictional company seeded into the sandbox site, and its tests
spikes/      the proof test of reading Atlassian Cloud through a browser session
scripts/     release.py, which CD runs to release the commit that CI checked
deploy/      Grafana's LGTM container, to observe runs on this machine
docs/        the pages, a folder for each Diataxis kind
docs/work/   plans, their checks and notes, and the roadmap; not tracked
.github/     the workflows of CI and CD, the code owners, the security policy
```

## Sandbox credentials

`atlassian-test-credientials.sops.json`, at the root of the primary checkout, holds the
sandbox site, account email and API token, encrypted with sops, under the generic names
`ATLASSIAN_SITE`, `ATLASSIAN_EMAIL` and `ATLASSIAN_API_TOKEN`. It is the user's own test
account, on the free plan, made for this. Agents may decrypt it and use its values
against the sandbox only, by `sops exec-env <absolute path> '<command>'`, the quoted
command mapping the names to the program's variables as
[the how-to](docs/how-to/api-token-with-sops.md) does, such as, from a worktree:

```bash
sops exec-env <primary-checkout>/atlassian-test-credientials.sops.json \
  'KB_MCP_SOURCES__CONFLUENCE__SITE="$ATLASSIAN_SITE" \
  KB_MCP_SOURCES__CONFLUENCE__EMAIL="$ATLASSIAN_EMAIL" \
  KB_MCP_SOURCES__CONFLUENCE__API_TOKEN="$ATLASSIAN_API_TOKEN" \
  KB_MCP_SOURCES__JIRA__SITE="$ATLASSIAN_SITE" \
  KB_MCP_SOURCES__JIRA__EMAIL="$ATLASSIAN_EMAIL" \
  KB_MCP_SOURCES__JIRA__API_TOKEN="$ATLASSIAN_API_TOKEN" \
  uv run kb-mcp fetch --yes --config <scratch>/none.toml \
  --data-dir <scratch>/data --space MFS --project PRB --since 7d'
```

Never commit a value, nor write one into a tracked file, a log or a command line. Never
sign in with a password: browser sign-ins, `login` included, are the user's.
