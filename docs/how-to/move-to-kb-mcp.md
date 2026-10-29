# Move to kb-mcp

How to move a machine set up under the program's former name, atlassian-offline-mcp,
to kb-mcp: its command, its settings file, its data, its variables, and what other
programs keep of it. The program moves nothing itself and reads no other program's
configuration: it says what it finds, and you move it.

## 1. Replace the command

The former tool gives the command `atlassian-offline-mcp` alone. From a checkout of the
repository at this version:

```bash
uv tool uninstall atlassian-offline-mcp
uv tool install --force .
```

## 2. Ask what the former name left

Each command that reads the settings stops before acting, exit 2, when it finds what the
former name left in what it would use:

- the former settings file, `~/.config/atlassian-offline-mcp/config.toml`, when the run
  reads the default one, `~/.config/kb-mcp/config.toml`, and that is missing; the
  former file is then judged in its place;
- the former data directory, `~/atlassian-offline-mcp`, when the data directory is the
  default, `~/kb-mcp`, and that is missing; a folder in a git working tree, such as a
  clone, is never taken for the data;
- a variable named `ATLASSIAN_OFFLINE_MCP_…`, in any case, set and not empty, whose new
  name, `KB_MCP_…`, is not set;
- a setting whose path names the former name, such as
  `data_dir = "~/atlassian-offline-mcp"`; a site or an e-mail is never judged.

Where a former place and its new one both exist, the new one is used and nothing stops.
A run given `--config` and `--data-dir` elsewhere uses neither former place. `--help`,
`--version` and `completion` read no settings and never stop. So run `check` first:

```bash
kb-mcp check
```

After the event `settings.refused`, it prints what it found and what to do. For a
machine that holds all four, with `KB_MCP_LOGS__DIR` naming a folder of the former name:

```text
# Move the files:
mkdir -p ~/.config/kb-mcp && mv ~/.config/atlassian-offline-mcp/config.toml ~/.config/kb-mcp/config.toml
mv ~/atlassian-offline-mcp ~/kb-mcp

Rename each variable where it is set (a shell's profile, an MCP client, sops):
ATLASSIAN_OFFLINE_MCP_SITE to KB_MCP_SITE

Change each setting whose path names the former name, moving what it names:
logs.dir (KB_MCP_LOGS__DIR)

Then, by hand, as docs/how-to/move-to-kb-mcp.md says:
- uv tool uninstall atlassian-offline-mcp, then uv tool install --force <checkout>
- Claude Code: claude mcp remove --scope user atlassian-offline-mcp, then
  claude mcp add --scope user --transport stdio kb-mcp -- kb-mcp, with the arguments
  it was added with, such as --allow-remote-embeddings; in ~/.claude/settings.json
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

Variables and settings are named with their layer, never with their values.

## 3. Move the files

Quit the coding agents first: a server started under the former name keeps the former
data directory open. Then run the block that `check` printed, from `# Move the files:`
to the blank line: it holds only the moves that your machine needs, each to a place that
is missing. The data directory's files hold no path of their own: the index, the
vectors, the conversions, the raw store, the sign-in and the aliases keep working where
they are moved, and the next run rebuilds and converts nothing.

## 4. Rename the variables and the settings

Rename each variable named, wherever it is set: a shell's profile, an MCP client's entry
for the server, a `sops exec-env` command. For each setting named, move the folder or
file that it names, then change it in its layer: the settings file, a variable, or a
flag in a script.

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
script by the command's name, so it goes under the new name.

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

## 8. Check again

```bash
kb-mcp check
```

It exits 0 once nothing of the former name is left in what it uses.
