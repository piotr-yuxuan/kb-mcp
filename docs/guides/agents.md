# Coding agents

How to give Claude Code and VS Code Copilot the offline mirror: the MCP server for
searching and reading it, and its Markdown files, read-only, for agents that prefer
files.

## Before you start

- The command is installed, so that `atlassian-offline-mcp` is on your `PATH`, for
  instance with `uv tool install <path of this repository>`.
- The mirror is built (`atlassian-offline-mcp mirror`), and so is its index:

  ```bash
  atlassian-offline-mcp index
  ```

  Build the index again after each `mirror`; a running server reads the new index from
  its next call on. `status` tells when the index was built.
- The server is the command with no arguments. It speaks MCP over stdio, reads only
  `<data>/index.sqlite` and the mirror, and writes nothing; its one network connection,
  when it searches by meaning, is to the embedding endpoint on this machine (below). It
  takes its settings, the data directory included, from
  `~/.config/atlassian-offline-mcp/config.toml`; `<data>` is `~/atlassian-offline-mcp`
  unless that file says otherwise.

The server has four tools, all read-only: `search`, `read`, `browse` and `status`. Every
answer marks the text it copies from Confluence and Jira as untrusted reference data,
and the server's instructions tell agents never to follow directions found in it.

Never give an agent `<data>/session/` (your saved sign-in) or `<data>/raw/`: only
`<data>/docs/` is meant for them.

## Search by meaning

`search` ranks by words unless the setting `search_mode` says otherwise: `hybrid`
fuses words and meaning, `semantic` ranks by meaning alone, and `lexical`, the default,
needs nothing more. On plan 002's sandbox questions, hybrid search with the default
model did not beat words significantly and did worse on identifiers, so words stay
the default until your own questions say otherwise (see
[evaluating search](../explanation/search-evaluation.md)). Meaning comes from an
embedding model that this program does not run itself: it asks any OpenAI-compatible
embeddings API, by default [Ollama](https://ollama.com) on this machine. To search by
meaning, install Ollama on the host, not in a container (a container on macOS cannot
use the Mac's GPU), start it (the Ollama app, `brew services start ollama`, or
`ollama serve`), set `search_mode = "hybrid"`, then pull the model, check it and build
the index:

```bash
ollama pull qwen3-embedding:0.6b
```

```bash
atlassian-offline-mcp model check
```

```bash
atlassian-offline-mcp index
```

`model check` connects to the endpoint and says the model's dimensions, its digest and
whether its prefixes are known, or what to run when something is missing; it never
downloads a model. The first `index` with a model embeds every piece of the mirror,
then keeps the vectors in `<data>/vectors.sqlite`, so later builds embed only what
changed. Run `index` again after `ollama pull` of a new version of the model: its
vectors change. Until then a server started after the pull says that the index is
stale and answers by words, while one already running goes on with the new weights
against the old vectors until the index is rebuilt. When the endpoint does not
answer, `index` fails and leaves the index in place; the server answers by words,
saying why, and tries again 30 seconds later. Ollama unloads a model five minutes
after its last use, so the first search after a pause waits for it to load;
`OLLAMA_KEEP_ALIVE` (for instance `1h`) keeps it longer. An index built by an earlier
version names a model of its own, which Ollama does not have: run `index`, rather
than pull that model. A folder `<data>/models/` left by an earlier version can be
deleted.

The default model, `qwen3-embedding:0.6b` (639 MB), retrieves English best among the
small models of Ollama's library compared on the MTEB leaderboard. For French content,
or a faster cold build, set `model = "embeddinggemma:300m"` (622 MB): best on French,
and about a quarter of the compute. Any model the endpoint serves can be named; the
prefixes of `qwen3-embedding`, `embeddinggemma`, `embeddinggemma-2`,
`nomic-embed-text`, `nomic-embed-text-v2-moe` and `snowflake-arctic-embed2` are known,
and texts for any other model are embedded as they are.

Any other OpenAI-compatible server works the same way (LM Studio, llama.cpp's server,
vLLM, a hosted API): set `embedding_url` to its base address, the one that ends before
`/embeddings`, and, if it needs a key, put the key in the environment variable
`ATLASSIAN_OFFLINE_MCP_EMBEDDING_API_KEY` (never in the settings file). Such a server
lists no digest as Ollama does, so the vectors follow the model's name alone: after
changing the weights behind a name, delete `<data>/vectors.sqlite` and run `index`.

```toml
search_mode = "hybrid"
model = "qwen3-embedding:0.6b"
embedding_url = "http://127.0.0.1:11434/v1"
```

The text sent to the endpoint is your company's content, so the endpoint must be on
this machine: a literal loopback address, `127.0.0.1` or `[::1]` (not a name, not even
`localhost`, which resolves as the system says). Any other address is refused unless
the command is given `--allow-remote-embeddings`, on every run, and then only over
https; for the MCP server, that means registering it as `atlassian-offline-mcp serve
--allow-remote-embeddings`. A model that Ollama serves from its cloud (such as a
`:cloud` tag) is refused the same way, since Ollama would forward the text. A tunnel or
a forwarded port to another machine defeats the check: do not point `embedding_url` at
one. By words alone, the default, no endpoint is asked at all.

To check which mode, and which model, fits your own content, write golden questions
and keep them in `<data>/eval/`: a
YAML list where each question has an `id`, the `question`, the `expected` refs that
answer it (page ids, issue keys, or mirror paths, as `read` takes them), and optionally
`partial` refs that help, `groups` to break the measures down, and `evidence`, a phrase
of each expected document's text. Quote page ids, which YAML would read as numbers:

```yaml
- id: q1
  question: How do I roll back a release of the payments service?
  expected: ["196845", PAY-142]
  partial: ["197012"]
  groups: [paraphrase, en]
  evidence: {"196845": "Pause, drain, then roll back."}
```

Then run:

```bash
atlassian-offline-mcp eval ~/atlassian-offline-mcp/eval/golden.yaml
```

It prints Recall@10, MRR@10, nDCG@10, Success@1 and Section@10 per mode and model, with
the paired tests, and keeps the numbers, never the questions, in `<data>/eval/results/`.
It measures the setting's model, or each one named with `--model`, all served by the
endpoint, whatever the setting `search_mode`. [Evaluating
search](../explanation/search-evaluation.md) explains each measure, the tests, and how
the defaults were chosen.

## Claude Code

### Register the server

For every project, at user scope:

```bash
claude mcp add --scope user --transport stdio atlassian-offline-mcp -- atlassian-offline-mcp
```

Or for one project, in its `.mcp.json` (Claude Code asks once before it starts a
project's server):

```json
{
  "mcpServers": {
    "atlassian-offline-mcp": {
      "type": "stdio",
      "command": "atlassian-offline-mcp",
      "args": [],
      "env": {}
    }
  }
}
```

If Claude Code does not find the command, give its absolute path, as `which
atlassian-offline-mcp` prints it.

### Allow the four tools

Claude Code names a server's tools `mcp__<server>__<tool>`. In `~/.claude/settings.json`,
allow each of the four by name, so that no prompt interrupts a search:

```json
{
  "permissions": {
    "allow": [
      "mcp__atlassian-offline-mcp__search",
      "mcp__atlassian-offline-mcp__read",
      "mcp__atlassian-offline-mcp__browse",
      "mcp__atlassian-offline-mcp__status"
    ]
  }
}
```

The wildcard `mcp__atlassian-offline-mcp__*` would also allow any tool a later version
adds; the list keeps to these four. `/permissions` shows each rule and where it comes
from.

### Give read-only access to the files

Add `<data>/docs/` as an additional directory, with an absolute path, and deny edits
there. `Edit` rules cover every built-in tool that changes files; `Write` rules are not
checked, so use `Edit`. A path beginning with `~/` is under your home directory:

```json
{
  "permissions": {
    "additionalDirectories": ["/Users/<you>/atlassian-offline-mcp/docs"],
    "deny": ["Edit(~/atlassian-offline-mcp/docs/**)"]
  }
}
```

Reading inside an additional directory needs no allow rule. Deny rules hold in every
permission mode, but they bind Claude Code's own tools and the file commands it
recognises in Bash, not every program a command may start; for a guarantee from the
operating system, see Claude Code's sandboxing. For one session only, `claude --add-dir
~/atlassian-offline-mcp/docs` does the same as the setting.

## VS Code Copilot

### Register the server

In your user profile's `mcp.json` (the command "MCP: Open User Configuration"), or in a
workspace's `.vscode/mcp.json`:

```json
{
  "servers": {
    "atlassian-offline-mcp": {
      "type": "stdio",
      "command": "atlassian-offline-mcp",
      "args": []
    }
  }
}
```

### Allow the four tools

Run "Chat: Manage Tool Approval" from the Command Palette, open `atlassian-offline-mcp`,
and pre-approve `search`, `read`, `browse` and `status`, or all of the server's tools
with its own box. The first time a tool asks, its dialog also offers to allow it always.
"Chat: Reset Tool Confirmations" withdraws every approval. Leave the global
auto-approval off: it would approve every tool of every server.

The server answers in text, never in structured content, which VS Code would pass on
alone.

### Give read-only access to the files

Add `<data>/docs/` to the workspace (File, Add Folder to Workspace), then make it
read-only in the editor and keep every edit there behind a confirmation, in your user
settings. The globs are absolute: VS Code reads a relative one from each workspace
folder, where `atlassian-offline-mcp/docs` is not part of the files' paths.

```json
{
  "files.readonlyInclude": {"/Users/<you>/atlassian-offline-mcp/docs/**": true},
  "chat.tools.edits.autoApprove": {"/Users/<you>/atlassian-offline-mcp/docs/**": false}
}
```

Neither setting is a guarantee from the operating system: an agent's terminal commands
can still write there. `mirror` rebuilds the folder from the raw store in any case, so
an edit would not last.

## Sources

Checked on 2026-10-21 and 2026-10-22:

- Claude Code: [MCP](https://code.claude.com/docs/en/mcp.md),
  [permissions](https://code.claude.com/docs/en/permissions.md),
  [settings](https://code.claude.com/docs/en/settings-reference.md).
- VS Code: [MCP servers](https://code.visualstudio.com/docs/copilot/customization/mcp-servers),
  [MCP configuration](https://code.visualstudio.com/docs/agents/reference/mcp-configuration),
  [approvals](https://code.visualstudio.com/docs/agents/approvals),
  [read-only files](https://code.visualstudio.com/updates/v1_79).
- Ollama: [OpenAI compatibility](https://docs.ollama.com/api/openai-compatibility),
  [embeddings](https://docs.ollama.com/capabilities/embeddings),
  [list models](https://docs.ollama.com/api/tags),
  [qwen3-embedding](https://ollama.com/library/qwen3-embedding),
  [embeddinggemma](https://ollama.com/library/embeddinggemma); the
  [MTEB leaderboard](https://huggingface.co/spaces/mteb/leaderboard).
