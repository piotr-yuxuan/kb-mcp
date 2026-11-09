# Settings

Every setting of the command: how each is named, which layer wins, then a row per
setting; then the variables that a run reads besides. This page is generated from the
settings' model,
[`Settings`](../../src/kb_mcp/config/domain/settings.py),
by `uv run python -m tests.reference_pages`, and `tests/test_reference.py` fails while
it differs: change a setting's `Field` and its description, then run that command;
never edit the page.

## Precedence and naming

A run takes each setting from the strongest layer that gives it. From the weakest: its
default; the settings file; the environment; the flags of the run. A stronger layer's
value replaces a weaker one's whole, a list included, as
[`settings_of`](../../src/kb_mcp/config/domain/settings.py) merges them;
`check --summary detailed` names the layer that gave each setting.

- **The settings file** is TOML: `~/.config/kb-mcp/config.toml`, unless
  `--config` names another; a missing file holds no settings. A key with dots, such as
  `sources.confluence.spaces`, is the key `spaces` of the table `[sources.confluence]`.
  The file may not hold a key that names no setting, nor a secret.
- **The environment** names each setting by a variable: `KB_MCP_`, then
  the setting's key in capitals, each dot written `__`. A list is a JSON array, and
  a table, which a variable of its own may give whole, a JSON object. An empty variable
  is ignored, as is one of the prefix that names no setting; two that set one setting,
  such as a table's and one of its settings', are refused. A secret is read from its
  variable alone.
- **A flag**, such as `--data-dir`, overrides its setting for its run alone;
  [the commands](commands.md) list each command's flags.

A path that starts with `~` starts in the home directory.

## Settings

| Key | Variable | Type | Default | Description |
|---|---|---|---|---|
| `data_dir` | `KB_MCP_DATA_DIR` | path | `"~/kb-mcp"` | Where the data lives, ~ being the home directory: never under a synchronised folder, nor inside a git working tree. |
| `model` | `KB_MCP_MODEL` | text | `"qwen3-embedding:0.6b"` | The embedding model that embed embeds with, as the endpoint names it. |
| `search_mode` | `KB_MCP_SEARCH_MODE` | one of `lexical`, `semantic`, `hybrid` | `"hybrid"` | How search ranks: by words (lexical), by meaning (semantic), or both (hybrid), the default; all but lexical need the embedding endpoint. |
| `chunking` | `KB_MCP_CHUNKING` | one of `sections`, `windows`, `section-paths`, `small-to-big` | `"windows"` | How embed cuts documents into the pieces it embeds: sections, windows, section-paths, small-to-big; search follows the index. By default windows, which ranked best when the chunkings were compared. |
| `embedding_url` | `KB_MCP_EMBEDDING_URL` | text | `"http://127.0.0.1:11434/v1"` | The OpenAI-compatible API that embeds, up to /embeddings, excluded. |
| `embedding_api_key` | `KB_MCP_EMBEDDING_API_KEY` | secret | unset | The embedding endpoint's API key, if it needs one, a secret: from the environment alone. |
| `accounts.atlassian.site` | `KB_MCP_ACCOUNTS__ATLASSIAN__SITE` | text | unset | The Atlassian site, for Confluence and Jira alike: https://\<name>.atlassian.net. |
| `accounts.atlassian.email` | `KB_MCP_ACCOUNTS__ATLASSIAN__EMAIL` | text | unset | The email address of the Atlassian account that signs in. |
| `accounts.atlassian.api_token` | `KB_MCP_ACCOUNTS__ATLASSIAN__API_TOKEN` | secret | unset | The Atlassian account's API token, a secret: from the environment alone. |
| `sources.confluence.spaces` | `KB_MCP_SOURCES__CONFLUENCE__SPACES` | list of text | `[]` | The spaces to fetch when no --space is given, by key. |
| `sources.jira.projects` | `KB_MCP_SOURCES__JIRA__PROJECTS` | list of text | `[]` | The projects to fetch when no --project is given, by key. |
| `sources.worklog.path` | `KB_MCP_SOURCES__WORKLOG__PATH` | path | unset | The work log's folder, absolute or under ~, which holds todo.org, todo.org_archive, transcripts/ and meetings/; read in place, never written. |
| `sources.worklog.archives` | `KB_MCP_SOURCES__WORKLOG__ARCHIVES` | boolean | `true` | Whether todo.org_archive, transcripts/archive/, meetings/archive/ and the subtrees tagged ARCHIVE are prepared too. |
| `logs.dir` | `KB_MCP_LOGS__DIR` | path | unset | The folder of each run's log file, ~ being the home directory: by default the user's log folder, where the platform keeps them; never under a synchronised folder, nor inside a git working tree. |
| `telemetry.endpoint` | `KB_MCP_TELEMETRY__ENDPOINT` | text | unset | The OTLP endpoint on this machine that traces, metrics and logs go to, over http with a port and no path, such as http://127.0.0.1:4318; unset, none is sent. Else OTEL_EXPORTER_OTLP_ENDPOINT gives it, below the settings file; OTEL_SDK_DISABLED=true leaves it unset. |
| `rerank.enabled` | `KB_MCP_RERANK__ENABLED` | boolean | `false` | Whether search and ask rerank their first documents through the reranking server: off by default, as it ranked worse on the sandbox, by the user's choice in plan 022. |
| `rerank.url` | `KB_MCP_RERANK__URL` | text | `"http://127.0.0.1:9931/v1"` | The reranking server's API, up to /rerank, excluded: an address of this machine, never another. |
| `rerank.model` | `KB_MCP_RERANK__MODEL` | text | `"qwen3-reranker-0.6b"` | The reranking model, as the server names it. |
| `rerank.depth` | `KB_MCP_RERANK__DEPTH` | integer | `30` | How many documents, after those a query names, are reranked: 2 to 64. |

## Variables read besides the settings

| Variable | Effect |
|---|---|
| `NO_COLOR` | Set, stderr and `--help` have no colour |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | `telemetry.endpoint`, in a layer below the settings file, shared with other programs; a value that the setting would refuse is ignored, and said to be |
| `OTEL_SDK_DISABLED` | `true` leaves `telemetry.endpoint` unset, above every layer: telemetry off |

A run takes every other `OTEL_` variable out of its environment as it starts, before
OpenTelemetry reads any
([`READ`](../../src/kb_mcp/observability/__init__.py)); the reference of
[telemetry](telemetry/README.md#settings-and-variables) says why.

The libraries that a run uses read variables of their own, which no test finds; these
change what a run does:

- `HTTPS_PROXY`, `HTTP_PROXY` and `ALL_PROXY`, unless `NO_PROXY` names the host, as
  httpx reads them: the site's requests go through that proxy, and so do those to an
  embedding endpoint off this machine; one on it, and telemetry, ignore them. On macOS,
  with none set, Python reads the system's proxy settings instead.
  [Credentials](../explanation/credentials.md#on-the-wire) says what a proxy sees.
- `XDG_STATE_HOME`, on Linux: the log folder is under it, as platformdirs places it.
- `COLUMNS`, `FORCE_COLOR`, `PYTHON_COLORS` and `TERM`, among others: the width and the
  colours of `--help`, as argparse reads them, and of stderr, as Rich does.
