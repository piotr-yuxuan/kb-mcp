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
sandbox site, account email and API token, encrypted with sops, under the generic names
`ATLASSIAN_SITE`, `ATLASSIAN_EMAIL` and `ATLASSIAN_API_TOKEN`. It is the user's own test
account, on the free plan, made for this. Agents may decrypt it and use its values
against the sandbox only, by `sops exec-env <absolute path> '<command>'`, the quoted
command mapping the names to the program's variables as
[the how-to](docs/how-to/api-token-with-sops.md) does, such as, from a worktree:

```bash
sops exec-env <primary-checkout>/atlassian-test-credientials.sops.json 'ATLASSIAN_OFFLINE_MCP_SITE="$ATLASSIAN_SITE" \
  ATLASSIAN_OFFLINE_MCP_EMAIL="$ATLASSIAN_EMAIL" \
  ATLASSIAN_OFFLINE_MCP_API_TOKEN="$ATLASSIAN_API_TOKEN" \
  uv run atlassian-offline-mcp download --yes --config <scratch>/none.toml \
  --data-dir <scratch>/data --space MFS --project PRB --since 7d'
```

Never commit a value, nor write one into a tracked file, a log or a command line. Never
sign in with a password: browser sign-ins, `login` included, are the user's.
