# Instructions for coding agents

atlassian-offline-mcp keeps an offline mirror of Confluence and Jira Cloud content
and serves it to coding agents through a local MCP server. The repository is meant to
become public: never commit an employer's name, a site URL other than the sandbox's,
identifiers or content. Fixtures come only from the sandbox site.

## Workflow

Follow the `workflow:plans` skill with these parameters:

- Plans are `docs/work/plans/NNN-slug.md`, tracked by git.
- Checks, run in full before each review and each merge:
  - `uv run ruff check` and `uv run ruff format --check`;
  - `uv run lint-imports`;
  - `uv run pytest`;
  - `uv run --with-requirements sandbox/seed_corpus.py --with pytest pytest sandbox`,
    which needs pandoc on `PATH`.
- The design and the shared contracts are in `docs/work/README.md` and
  `docs/reference/data-layout.md`; where code goes, in `docs/explanation/code-layout.md`.
  Only the adapter of a representation reads its JSON, and only one module knows the
  site's HTML.
- At most three review rounds.

## Sandbox credentials

`atlassian-test-credientials.sops.json`, at the root of the primary checkout, holds the
sandbox site, account email and API token, encrypted with sops. Use it only as
`sops exec-env <absolute path> '<command>'`, and only against the sandbox. Never
print, decrypt or read its values. Never sign in with a password: browser sign-ins
are the user's.
