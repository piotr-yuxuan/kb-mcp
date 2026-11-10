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
- scripts, aliases, crontabs and agents' setups: each command that went, sync, download
  and mirror, and index for search by meaning, as that page's section 9 says
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

The mirror stays the same, byte for byte, but for its people, and what a run says and
keeps has changed since the former name:

- **The first prepare rewrites every Confluence and Jira file's `people`.** Each entry's
  `account: <id>` becomes `identity: 'atlassian:<id>'`; until then `index` reads the
  former entries as those identities, and no person's id changes.

- **The first prepare converts everything once.** The cache of conversions holds its rows
  by source now, so a file of the former columns is replaced, `prepare.cache_replaced`
  saying so; each run after it converts what changed, as before. Nothing is downloaded
  again.
- **A report per source.** A download's report is
  `<data>/runs/<time>-confluence.json` or `<time>-jira.json`, one for each source that it
  fetches, where it was `<time>.json`. Reports already there stay as they are. No code
  reads them; a script of yours may.
- **A row per source.** `fetch` and `prepare` write a row for each source, under `sources`
  with `--format json`. `prepare confluence` prepares Confluence alone: [bring every source
  up to date](refresh.md#3-take-some-of-the-sources) says what that leaves.
- **A stray `.md` file under the mirror is read.** The index reports it as a file without
  front matter, and exits 1, where it was ignored: move it out of `docs/`.
- **The first `index` rebuilds the index whole.** An index written before records no
  file's digest, so the first `index` keeps nothing of it, `index.whole` saying why, and
  reads every file; the next `embed` takes the vectors back from `<data>/vectors.sqlite`,
  embedding only what it lacks. `embed` before that `index` stops, exit 1, naming
  `kb-mcp index`, and leaves the index as it was. From then on, `index` reads only the
  files that changed, and writes nothing when none did.
- **An index of schema 6 is rebuilt whole by the first `index`,** at schema 7, whose tables
  are `chunks` and `section_words`. `kb-mcp index`, then `kb-mcp embed`, suffice, as the
  server says of the index of 6: the mirror's files did not change, so no `prepare` is
  needed, and `embed` takes every chunk's vector back from `<data>/vectors.sqlite`, as no
  text embedded changed. Keep that file in place: a deleted one costs a full embedding of
  the mirror. Each evaluated index under `<data>/eval/indexes/` built at schema 6 holds
  every prune of the vector cache back, `index.prune_skipped` saying so, until `eval`
  builds it again. For each `<data>/eval/indexes/<chunking>/<model>.sqlite`, run
  `kb-mcp eval <golden file> --model <model> --chunking <chunking>`, the model's name
  read from the index's meta row, as the file's name writes its `/` and `:` as `_`:

  ```bash
  sqlite3 <data>/eval/indexes/<chunking>/<model>.sqlite \
    "SELECT value FROM meta WHERE name = 'model'"
  ```

  One run may take several `--chunking` for one model's chunkings, but `--model` and
  `--chunking` cross: every model given is evaluated in every chunking given. Only the
  pairs evaluated before take their vectors from the cache; any other chunking is
  embedded anew. Deleting `<data>/eval/indexes/` instead is not free: the next prune
  deletes the vectors that only those indexes read, and the next `eval` embeds them
  again.

## 9. The commands that moved

Scripts, aliases, crontabs and agents' setups may name commands that went. The parser
refuses each, exit 2, and its message lists the commands. What replaces each:

| Was | Now |
|---|---|
| `sync` | the chain that you compose: `fetch && prepare && index && embed`, as [bring every source up to date](refresh.md) says; with the work log alone, from `prepare` on, as `fetch` has nothing to fetch and is refused |
| `sync --since 7d`, and any option of the period | `fetch --since 7d`, then the rest of the chain: `prepare` takes none, and its parser reads a value after an unknown flag as a source's name |
| `sync --include worklog` | `prepare worklog && index`, then `embed` for search by meaning |
| `sync --include` or `--exclude` of a site's source | the sources named: `fetch jira`, `prepare jira` |
| `sync --dry-run` | `fetch --dry-run` and `prepare --dry-run` |
| `download` | `fetch` |
| `mirror` | `prepare confluence jira`, since `prepare` alone takes the work log too |
| `index`, for search by meaning | `index`, then `embed`, which takes `--allow-remote-embeddings`; `index` writes the words alone, asks no endpoint, and refuses that flag |
| `login` | `login atlassian` |

A script that wants search by meaning ends with `index`, then `embed`, never with
`prepare && embed`: `embed` reads the index, not the mirror, so a page that `prepare`
removed, and an edited page's old text, stay served until the next `index`. `embed` warns
of a mirror changed since the index, `embed.mirror_changed`, naming `kb-mcp index`, and
goes on, with the exit status it would have had.

What reads a run's output follows:

- **JSON.** A result's `steps`, each with its `step`, are `sources`, each with its `source`,
  `outcome` and `result`, whose `downloaded` and `mirrored` stay. `index`'s `report` gives
  the documents held by type, their sections and the files skipped, then the documents
  `copied`, `added`, `replaced` and `removed`, `awaiting`, those awaiting vectors, null
  when the index names no model, `unchanged`, whether nothing was written, and `rebuilt`,
  why the index was rebuilt whole, if it was; its `model` and `pruned` are null; its
  `chunks` was `pieces` before schema 7. `embed`'s result by meaning gives `index`,
  `model`, `chunks` (formerly `pieces`) and `documents`, those that the index holds,
  `skipped`, the files that it lacks, `added` and `removed`, the chunks, `embedded`,
  `found` and `refused`, `unchanged`, and `pruned`. `eval`'s result and results file
  give each evaluated index under `indexes`, formerly `runs`, with its `costs.chunks`,
  formerly `costs.pieces`; results files already written keep `runs`.
- **`embed`'s text.** Its lines say `chunks:`, where they said `pieces:`, and "vector
  cache", where they said "vector store".
- **Log files, spans and metrics.** A run's log file and root span take its command's name,
  `fetch` or `prepare`, for instance. Events, spans and instruments named `download.`,
  `kb_mcp.download.`, `mirror.` and `kb_mcp.mirror.` are named `fetch.`, `kb_mcp.fetch.`,
  `prepare.` and `kb_mcp.prepare.`; `sync.` is gone, for each command's `start`, `source`,
  `interrupted`, `end` and `refused`. `fetch.interrupted` names the source that it stopped,
  where `download.interrupted` named the folder of the reports. The index's events, spans
  and instruments are named `index.` and `kb_mcp.index.`, under whichever command writes
  the index; since schema 7, `index.piece_refused` is `index.chunk_refused`, the counter
  `kb_mcp.index.pieces` is `kb_mcp.index.chunks`, of unit `{chunk}`, and the field
  `pieces` of `index.built`, `embed.filled` and `embed.unchanged` is `chunks`. `embed`
  adds its own events, `embed.`, as
  [its telemetry](../reference/telemetry/embed.md) lists them. Log files of the retired
  commands go after their 30 days, as every command's.
- **Persons.** The front matter's `people[].account` is `people[].identity`, valued
  `atlassian:<id>`. `status` counts them on a line `persons:`, where it said `people:`,
  and says "names of several identities". The field `people` of `index.built` and
  `index.person_ambiguous` is `persons`; the field `kind` of `worklog.document` and the
  attribute `kb_mcp.kind` of the prepare's instruments are `type` and `kb_mcp.type`.
- **Dashboards.** Those of [observe with Grafana](observe-with-grafana.md) are `fetch`,
  `prepare`, `index` and `embed`, where they were `download`, `mirror`, `index` and `sync`.
- **`doctor`.** A machine with neither a site nor a Confluence or Jira source gets the
  machine's checks alone, exit 0, where it failed `site: not set`.

## 10. Check again

```bash
kb-mcp check
```

It exits 0 once none of what step 2 lists is left in what it uses.
