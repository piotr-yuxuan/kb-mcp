# Instructions for coding agents

An offline mirror of Confluence, Jira Cloud and a work log, served to coding agents over
MCP. The repository is meant to become public: never commit an employer's name, a site
URL other than the sandbox's, identifiers or content. Fixtures come only from the sandbox
site; `sandbox/corpus/` and `sandbox/jira/` are the fixtures of a fictional company,
never this project's docs.

## Workflow

Follow the `workflow:plans` skill with these parameters:

- Plans are `docs/work/plans/NNN-slug.md`, untracked: `docs/work/` is git-ignored and
  never committed; parked ones are under `docs/work/held/`, done ones under
  `docs/work/changelog/`. Records under `docs/work/` are history, never a contract.
- Checks, run in full before each review and each merge:
  - `uv run ruff check` and `uv run ruff format --check`;
  - `uv run lint-imports`;
  - `uv run pytest -n auto`, on every core by pytest-xdist;
  - `uv run --with-requirements sandbox/seed_corpus.py --with pytest pytest sandbox`,
    which needs pandoc on `PATH`.
- The words, each defined once, in [the concepts](docs/reference/concepts.md); until the
  code is conformed to them, new code takes the names of each entry's "In the code"
  paragraph.
- The design: why each decision was taken and what it costs, in
  [the trade-offs](docs/explanation/trade-offs.md); how the stages work together, in
  [the internals](docs/explanation/internals.md); the formats that the stages share, in
  [the data layout](docs/reference/data-layout.md); where code goes, in
  [the code's layout](docs/explanation/code-layout.md); the plans, in the roadmap,
  `docs/work/README.md`, untracked. Only the adapter of a representation reads its
  JSON, and only one module knows the site's HTML.
- A new page goes in the folder of `docs/` named by its Diataxis kind, and
  [the map](docs/README.md) links it in the commit that writes it. The reference of
  commands and settings is generated from the code: after changing a command, an option
  or a setting, run `uv run python -m tests.reference_pages` and commit the pages it
  rewrites; else the reference test fails, naming them.
- What runs log, trace and measure: `docs/reference/telemetry/`, changed with the code.
- At most three review rounds.

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
  'KB_MCP_ACCOUNTS__ATLASSIAN__SITE="$ATLASSIAN_SITE" \
  KB_MCP_ACCOUNTS__ATLASSIAN__EMAIL="$ATLASSIAN_EMAIL" \
  KB_MCP_ACCOUNTS__ATLASSIAN__API_TOKEN="$ATLASSIAN_API_TOKEN" \
  uv run kb-mcp fetch --yes --config <scratch>/none.toml \
  --data-dir <scratch>/data --space MFS --project PRB --since 7d'
```

Never commit a value, nor write one into a tracked file, a log or a command line. Never
sign in with a password: browser sign-ins, `login` included, are the user's.
