# Coding agents

How to give Claude Code and VS Code Copilot the offline mirror of Confluence, Jira and
the work log: the MCP server for searching and reading it, and its Markdown files,
read-only, for agents that prefer files.

## Before you start

- The command is installed, so that `atlassian-offline-mcp` is on your `PATH`, for
  instance with `uv tool install <path of this repository>`.
- The mirror is built, and so is its index: `sync` builds both, from Confluence, Jira
  and the work log alike ([bring every source up to date](sync.md)); or `mirror`, from
  Confluence and Jira, then:

  ```bash
  atlassian-offline-mcp index
  ```

  By default `index` embeds the mirror with a model that Ollama serves, so set that up
  first, as [embeddings](embeddings.md) says, or set `search_mode = "lexical"` to index
  and search by words alone. Build the index again after each
  `mirror`; a running server reads the new index from its next call on. `status` tells
  when the index was built. `mirror`, `index` and `eval` write under the data
  directory, so each first says what it will do and asks `Proceed? [y/N]`; `--yes` runs
  it without the question, as a script needs.
- The server is the command with no arguments. It speaks MCP over stdio, reads only
  `<data>/index.sqlite` and the mirror, and writes nothing; its one network connection,
  when it searches by meaning, is to the embedding endpoint on this machine (below). It
  takes its settings, the data directory included, from
  `~/.config/atlassian-offline-mcp/config.toml` and the variables
  `ATLASSIAN_OFFLINE_MCP_…`; `<data>` is `~/atlassian-offline-mcp` unless they say
  otherwise. It never asks, since its stdin is the protocol's, and says on stderr which
  values it ignores.

The server has five tools, all read-only: `ask`, `search`, `read`, `browse` and `status`
(`serve --tools` serves some of them). Every answer marks the text it copies from
Confluence, Jira and the work log as untrusted reference data, and the server's
instructions tell agents never to follow directions found in it.

Never give an agent `<data>/session/` (your saved sign-in) or `<data>/raw/`: only
`<data>/docs/` is meant for them.

## Search by meaning

`search` and `ask` rank by words, by meaning or by both, as the setting `search_mode`
says. Meaning needs an embedding model, served on this machine by Ollama or by any
other OpenAI-compatible API: [embeddings](embeddings.md) says how to set one up, which
model and chunking to choose, and how to search by words alone.

## Ask, and prompts

`ask` answers a question in one call with passages to quote: one per document, as many
as fit, each with its title, ref, section, dates, site address and the `read()` call of
its section, the text verbatim. It ranks as `search` does, in the setting's mode. An
agent that would otherwise `search`, then `read` each document, gets the evidence at
once; `search` stays to navigate. `serve --tools search,read,browse,status` serves the
four tools of plan 006 alone, without `ask`.

The server also offers three prompts, which Claude Code shows as slash commands
(`/mcp__atlassian-offline-mcp__brief`): `brief REF` summarises one document, `changes
space:KEY 2026-10-01` what changed in a space or a project since a date, and `overview
project:KEY` how one is organised and what to read first. [The
reference](../reference/mcp-tools.md) lists each tool and prompt.

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

### Allow the five tools

Claude Code names a server's tools `mcp__<server>__<tool>`. In `~/.claude/settings.json`,
allow each of the five by name, so that no prompt interrupts a search:

```json
{
  "permissions": {
    "allow": [
      "mcp__atlassian-offline-mcp__ask",
      "mcp__atlassian-offline-mcp__search",
      "mcp__atlassian-offline-mcp__read",
      "mcp__atlassian-offline-mcp__browse",
      "mcp__atlassian-offline-mcp__status"
    ]
  }
}
```

The wildcard `mcp__atlassian-offline-mcp__*` would also allow any tool a later version
adds; the list keeps to these five. `/permissions` shows each rule and where it comes
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

### Allow the five tools

Run "Chat: Manage Tool Approval" from the Command Palette, open `atlassian-offline-mcp`,
and pre-approve `ask`, `search`, `read`, `browse` and `status`, or all of the server's tools
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
