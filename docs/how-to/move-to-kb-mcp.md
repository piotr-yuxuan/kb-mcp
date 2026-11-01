# Move to kb-mcp

How to move a machine set up under the program's former name, atlassian-offline-mcp,
to kb-mcp: its command, its settings file, its data, its variables, and what other
programs keep of it. The program moves nothing itself and reads no other program's
configuration: it says what it finds, and you move it.

## 1. Replace the command

Quit the coding agents first: a server started under the former name runs from the tool
that this step removes, and keeps the former data directory open. The former tool gives
the command `atlassian-offline-mcp` alone. From a checkout of the repository at this
version:

```bash
uv tool uninstall atlassian-offline-mcp
uv tool install --force .
```

## 2. Ask what the former name left

Each command that reads the settings stops before acting, exit 2, when it finds what the
former name left in what it would use:

- the former settings file, `~/.config/atlassian-offline-mcp/config.toml`, when the run
  reads the default one, `~/.config/kb-mcp/config.toml`, and that is missing; the
  former file is then judged in its place, and its keys renamed since, `site` and
  `email` at its top, which `[accounts.atlassian]` holds now, are named by their final
  keys;
- the former data directory, `~/atlassian-offline-mcp`, when the data directory is the
  default, `~/kb-mcp`, and that is missing; a folder in a git working tree, such as a
  clone, is never taken for the data;
- a variable named `ATLASSIAN_OFFLINE_MCP_…`, in any case, set and not empty, whose
  final name, `KB_MCP_…`, is not set: the sign-in's are
  `KB_MCP_ACCOUNTS__ATLASSIAN__SITE`, `…__EMAIL` and `…__API_TOKEN`;
- a setting whose path holds a folder or a file whose name begins with the former name,
  such as `data_dir = "~/atlassian-offline-mcp"`, or a `--config` naming a file in such
  a folder, or such a file, whose keys renamed since are named too; a data directory
  given through a link is judged where it leads; a site or an e-mail is never judged.

Where a former place and its new one both exist, the new one is used and nothing stops.
A run given `--config` and `--data-dir` elsewhere uses neither former place. `--help`,
`--version` and `completion` read no settings and never stop. So run `check` first:

```bash
kb-mcp check
```

After the event `settings.refused`, it prints what it found and what to do. For a
machine that holds all four, its settings file holding `site` and `email` at its top,
with `KB_MCP_LOGS__DIR` naming a folder of the former name:

```text
# Move the files:
mkdir -p ~/.config/kb-mcp && mv ~/.config/atlassian-offline-mcp/config.toml ~/.config/kb-mcp/config.toml
mv ~/atlassian-offline-mcp ~/kb-mcp

Rename each key of the settings file:
site to accounts.atlassian.site
email to accounts.atlassian.email

Rename each variable where it is set (a shell's profile, an MCP client, sops):
ATLASSIAN_OFFLINE_MCP_SITE to KB_MCP_ACCOUNTS__ATLASSIAN__SITE

Change each setting whose path names the former name, moving what it names:
logs.dir (KB_MCP_LOGS__DIR)

Then, by hand, as docs/how-to/move-to-kb-mcp.md says:
- uv tool uninstall atlassian-offline-mcp, then uv tool install --force <checkout>
- Claude Code: claude mcp remove --scope user atlassian-offline-mcp, then
  claude mcp add --scope user --transport stdio kb-mcp -- kb-mcp, with the arguments
  it was added with, such as serve --allow-remote-embeddings; in ~/.claude/settings.json
  and each project's .claude/settings.local.json, mcp__atlassian-offline-mcp__*
  renamed mcp__kb-mcp__*, and the data's docs/ path moved in additionalDirectories
  and in the Edit deny rule
- VS Code: in each mcp.json, the server's key and command; then its tools approved again
- every other MCP client that starts the server, such as a project's .mcp.json,
  LM Studio, llama.cpp or Codex: its entry's key and command
- completion: the former script removed, and kb-mcp completion loaded as
  docs/how-to/shell-completions.md says
- eval-agents: each run prepared before, whose files call the former package, prepared
  again
- another search engine over the mirror: each collection on ~/atlassian-offline-mcp/docs/
  added again on ~/kb-mcp/docs/
```

Keys and variables are named, and settings with their layer, never with their values.
The layer of a value that the former settings file holds is that file's path, also when
a setting refuses the value, before anything is said to move. A token left at a file's
top, which no run ever took from there, is named by the variable that alone sets it,
under the heading of the keys:

```text
api_token: delete it, and set KB_MCP_ACCOUNTS__ATLASSIAN__API_TOKEN in the environment
```

## 3. Move the files

Run the block that `check` printed, from `# Move the files:` to the blank line: it holds
only the moves that your machine needs, each to a place that is missing. A `~/kb-mcp`
that is already a link is not missing: the run uses where it leads, and nothing is
moved; remove a link that leads nowhere, then run `check` again. Once the settings file
is moved, its former folder, `~/.config/atlassian-offline-mcp`, may be removed. The data
directory's files hold no path of their own: the index, the vectors, the conversions,
the raw store, the sign-in and the aliases keep working where they are moved, and moving
them makes the next run rebuild nothing.

## 4. Rename the keys, the variables and the settings

In the settings file, once moved, rename each key named: `site` becomes
`accounts.atlassian.site`, which TOML reads as the key `site` of the table
`[accounts.atlassian]`. Rename it where it is, at the file's top, or write it under that
table:

```toml
[accounts.atlassian]
site = "https://<name>.atlassian.net"
email = "<you>@<company>"
```

Rename each variable named, wherever it is set: a shell's profile, an MCP client's entry
for the server, a `sops exec-env` command, whose `KB_MCP_SITE="$ATLASSIAN_SITE"` becomes
`KB_MCP_ACCOUNTS__ATLASSIAN__SITE="$ATLASSIAN_SITE"`, as
[an API token kept by sops](api-token-with-sops.md) shows. The sign-in's variables that
the rename first gave, `KB_MCP_SITE`, `KB_MCP_EMAIL` and `KB_MCP_API_TOKEN`, name no
setting since its settings moved to `[accounts.atlassian]`: each run says it ignored
them, a run refused for want of the site first of all; rename them alike. For each
setting named, move the folder or file that it names, then change it in its layer: the
settings file, a variable, or a flag in a script.

## 5. Coding agents

For Claude Code, register the server again under its new name, with the arguments it
had, such as `serve --allow-remote-embeddings`:

```bash
claude mcp remove --scope user atlassian-offline-mcp
claude mcp add --scope user --transport stdio kb-mcp -- kb-mcp
```

Claude Code names a tool after its server, so rename each rule
`mcp__atlassian-offline-mcp__…` as `mcp__kb-mcp__…`, in `~/.claude/settings.json` and in
each project's `.claude/settings.local.json`, where Claude Code keeps what you allowed
for that project alone. Move the data's `docs/` path in `additionalDirectories` and in
the `Edit` deny rule: else that rule no longer covers the mirror.
[Coding agents](agents.md) gives both.

For VS Code, in each `mcp.json`, change the server's key and its `command` to `kb-mcp`,
then approve its tools again, as [coding agents](agents.md) says.

Every other client that starts the server keeps its own entry: a project's `.mcp.json`
for Claude Code, `~/.lmstudio/mcp.json` for LM Studio, `~/.config/llama.cpp/mcp.json`
for llama.cpp, and `[mcp_servers.…]` in `~/.codex/config.toml` for Codex, as
[a local model](local-model.md) sets them up. Change each entry's key and its command,
an absolute path where the client needs one.

## 6. Shell completion

Remove the former script, `~/.local/share/bash-completion/completions/atlassian-offline-mcp`
for bash or `_atlassian-offline-mcp` in a folder of `$fpath` for zsh, or the line
`eval "$(atlassian-offline-mcp completion)"` in `~/.bashrc` or `~/.zshrc`. Then load
`kb-mcp completion` as [shell completions](shell-completions.md) says: a shell finds a
script by the command's name, so it goes under the new name. In zsh, remove
`~/.zcompdump*`, or those in `$ZDOTDIR`, before opening a new shell: `compinit` keeps
its dump while the number of completion files is the same, which a rename leaves as it
was.

## 7. What else named it

- Runs that `eval-agents` prepared before call the former package: prepare them again,
  as [evaluate `ask` with agents](evaluate-with-agents.md) says.
- Another search engine over the mirror, set up as
  [search the mirror with another engine](other-search-engines.md) says, reads the
  former folder: add each collection again on `~/kb-mcp/docs/`.
- The former log folder, `~/Library/Logs/atlassian-offline-mcp` on macOS, and on Linux
  `$XDG_STATE_HOME/atlassian-offline-mcp`, `~/.local/state/atlassian-offline-mcp`
  without the variable, is no longer pruned: remove it once its logs are no longer
  wanted.

## 8. What runs do differently

The mirror stays the same, byte for byte, but what a run says and keeps has changed since
the former name:

- **The first prepare converts everything once.** The cache of conversions holds its rows
  by source now, so a file of the former columns is replaced, `mirror.cache_replaced`
  saying so; each run after it converts what changed, as before. Nothing is downloaded
  again.
- **A report per source.** A download's report is
  `<data>/runs/<time>-confluence.json` or `<time>-jira.json`, one for each source that it
  fetches, where it was `<time>.json`. Reports already there stay as they are. No code
  reads them; a script of yours may.
- **A row per source and step.** `sync`, `download` and `mirror` write a row for each
  source and step, under `steps` with `--format json`. `sync --include confluence`
  prepares Confluence alone: [bring every source up to
  date](sync.md#3-choose-among-the-sources) says what that leaves.
- **A stray `.md` file under the mirror is read.** The index reports it as a file without
  front matter, and exits 1, where it was ignored: move it out of `docs/`.

## 9. Check again

```bash
kb-mcp check
```

It exits 0 once none of what step 2 lists is left in what it uses.
