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
  `<data>/index.sqlite` and the model that index names under `<data>/models/`, writes
  nothing and opens no network connection. It takes its
  settings, the data directory included, from `~/.config/atlassian-offline-mcp/config.toml`;
  `<data>` is `~/atlassian-offline-mcp` unless that file says otherwise.

The server has four tools, all read-only: `search`, `read`, `browse` and `status`. Every
answer marks the text it copies from Confluence and Jira as untrusted reference data,
and the server's instructions tell agents never to follow directions found in it.

Never give an agent `<data>/session/` (your saved sign-in) or `<data>/raw/`: only
`<data>/docs/` is meant for them.

## Search by meaning

`search` ranks by words and by meaning together (hybrid) once the index holds vectors;
until then it ranks by words alone, and each answer says so. Vectors come from a small
embedding model that runs on your machine, pulled once:

```bash
atlassian-offline-mcp model pull
```

```bash
atlassian-offline-mcp index
```

`model pull` downloads the model of the setting `model` (by default `bge-small-en-v1.5`,
134 MB) into `<data>/models/`, each file checked against its pinned SHA-256; it is the
only command that downloads a model, and the server never does. `model list` shows the
models known. If the machine cannot reach huggingface.co, copy the model's files from
another one and use `model pull --from <folder>`. The first `index` with a model embeds
every piece of the mirror (a few minutes per 10,000 pieces), then keeps the vectors in
`<data>/vectors.sqlite`, so later builds embed only what changed. If your pages are
not all in English, set `model = "multilingual-e5-small"` (487 MB): it all but tied on
the evaluation, and did better on French questions.

The setting `search_mode` is `hybrid` (the default), `lexical` or `semantic`. To check
which fits your own content, write golden questions and keep them in `<data>/eval/`: a
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

Checked on 2026-10-21:

- Claude Code: [MCP](https://code.claude.com/docs/en/mcp.md),
  [permissions](https://code.claude.com/docs/en/permissions.md),
  [settings](https://code.claude.com/docs/en/settings-reference.md).
- VS Code: [MCP servers](https://code.visualstudio.com/docs/copilot/customization/mcp-servers),
  [MCP configuration](https://code.visualstudio.com/docs/agents/reference/mcp-configuration),
  [approvals](https://code.visualstudio.com/docs/agents/approvals),
  [read-only files](https://code.visualstudio.com/updates/v1_79).
