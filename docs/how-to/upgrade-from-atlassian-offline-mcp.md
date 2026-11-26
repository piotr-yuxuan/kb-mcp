# Upgrade from atlassian-offline-mcp

How to move a machine that runs atlassian-offline-mcp 0.1.0, the program's former name,
as `atlassian-offline-mcp --version` says, to kb-mcp 0.1.12, without writing the
old program, its settings or its data directory: kb-mcp works on a clone of that
directory. Every step can be undone, by going on with the old program, until the last
one, which removes it. The upgrade was rehearsed on a sandbox: a directory built by
0.1.0 was cloned, brought up to date by 0.1.12, and compared with the original;
the clone kept every document, snapshot, vector and person, downloaded nothing that it
held and embedded nothing again. The costs below are that rehearsal's.

Install 0.1.12 and no other release over a 0.1.0 directory: the releases after it
rewrite the code that reads 0.1.0's formats, and only 0.1.12 was rehearsed. To
move to a later one, upgrade to 0.1.12 first, then from it as any upgrade goes.

## 1. Before you start

Write down the versions that the old directory's caches depend on, and keep both until
the first runs have ended and you have measured what you wanted to: pandoc's version is
part of the key of each conversion that the mirror keeps, and the embedding model's
digest part of the key of each vector, so that changing either converts or embeds the
whole mirror again.

```bash
pandoc --version | head -1
atlassian-offline-mcp model check
```

This page names the old program's default data directory, `~/atlassian-offline-mcp`. If
its settings name another `data_dir`, use that path wherever this page says
`~/atlassian-offline-mcp`.

Then check that the clone can be made safely:

```bash
du -sh ~/atlassian-offline-mcp
df -h ~
test ! -e ~/kb-mcp && echo "~/kb-mcp is free"
find ~/atlassian-offline-mcp -type l
pgrep -fl 'atlassian-offline-mcp (sync|download|mirror|index|eval|login)'
```

- **Free space**: at least the old directory's size. The clone shares its blocks with
  the old directory until it is written, and the first runs rewrite every file of the
  mirror, the index and each evaluated index.
- **`~/kb-mcp` does not exist**: else `cp -R` copies the old directory into it, as
  `~/kb-mcp/atlassian-offline-mcp`, and kb-mcp starts from nothing. Move it aside first.
- **No symbolic link** in the old directory, so `find` prints nothing: else the two
  programs share what it leads to, and kb-mcp's runs write the old program's data.
- **No run of the old program that writes**, so `pgrep` prints nothing: else the copy
  may catch a database half-written. The old MCP server, `atlassian-offline-mcp serve`,
  only reads, and may go on serving agents meanwhile. A pattern of the program's name
  alone also matches any process whose arguments hold a path of that name, such as an
  editor open on a clone of the repository; hence the commands in the pattern.

## 2. Install kb-mcp beside the old program

Install from a fresh clone of 0.1.12: a clone made for 0.1.0 cannot be brought up
to date, since the repository's history was rewritten after it.

```bash
git clone --branch 0.1.12 https://github.com/piotr-yuxuan/kb-mcp.git ~/src/kb-mcp
uv tool install ~/src/kb-mcp
kb-mcp --version
```

uv installs each tool under its own name: the old program, `atlassian-offline-mcp`, stays
installed, with its settings file, `~/.config/atlassian-offline-mcp/config.toml`, its
variables, `ATLASSIAN_OFFLINE_MCP_*`, and its data, `~/atlassian-offline-mcp`. kb-mcp
reads none of them: its settings file is `~/.config/kb-mcp/config.toml`, its variables
`KB_MCP_*`, and its data `~/kb-mcp`.

## 3. Clone the data directory

On macOS, an APFS clone, which takes no time and no space until a file is written:

```bash
cp -c -R -p ~/atlassian-offline-mcp ~/kb-mcp
```

`-p` keeps each file's times and modes, as the rehearsal's copy did.

On Linux, `cp -a --reflink=always` does the same on Btrfs or XFS. Then check each
database of the clone:

```bash
find ~/kb-mcp -name '*.sqlite' -exec sh -c 'printf "%s: " "$1"; sqlite3 "$1" "PRAGMA quick_check;"' _ {} \;
```

Each line ends with `ok`: the index, the vector cache, the conversions, and each
evaluated index under `eval/indexes/`. The rehearsal's clone, of a directory of 181
files, took under a second.

## 4. Write the new settings

Write `~/.config/kb-mcp/config.toml` from the old file, key by key, as this table says;
never copy the old file whole. The settings of each Atlassian source are in its own
table now, and the file refuses a key that names no setting, such as a `site` at its
top.

| atlassian-offline-mcp 0.1.0 | kb-mcp |
|---|---|
| `site` | `sources.confluence.site` and `sources.jira.site` |
| `email` | `sources.confluence.email` and `sources.jira.email` |
| `ATLASSIAN_OFFLINE_MCP_API_TOKEN` | `KB_MCP_SOURCES__CONFLUENCE__API_TOKEN` and `KB_MCP_SOURCES__JIRA__API_TOKEN`, from the environment alone |
| `ATLASSIAN_OFFLINE_MCP_SITE` | `KB_MCP_SOURCES__CONFLUENCE__SITE` and `KB_MCP_SOURCES__JIRA__SITE` |
| `ATLASSIAN_OFFLINE_MCP_EMAIL` | `KB_MCP_SOURCES__CONFLUENCE__EMAIL` and `KB_MCP_SOURCES__JIRA__EMAIL` |
| `data_dir` | none: leave it out, for the default, `~/kb-mcp`, the clone |
| `logs.dir` | none: leave it out, for the default, `~/Library/Logs/kb-mcp` on macOS |
| `sources.confluence.spaces`, `sources.jira.projects`, `sources.worklog.path`, `sources.worklog.archives` | the same keys, under the same names, `confluence`, `jira` and `worklog`: the stores in the clone are under these names |
| `model`, `search_mode`, `chunking`, `embedding_url`, `embedding_api_key`, `rerank.*` | the same keys and values |
| `telemetry.endpoint` | the same key, but only an address of this machine, over http, with a port and no path, such as `http://127.0.0.1:4318`; another is refused |
| any other `ATLASSIAN_OFFLINE_MCP_<KEY>` | `KB_MCP_<KEY>`; a variable of the old prefix is ignored, silently |

For instance:

```toml
[sources.confluence]
site = "https://<name>.atlassian.net"
spaces = ["ENG"]

[sources.jira]
site = "https://<name>.atlassian.net"
projects = ["PLAT"]

[sources.worklog]
path = "~/todo"
```

A variable set in a shell's profile, an MCP client's entry or a `sops exec-env` command
is renamed where it is set, as [an API token kept by sops](api-token-with-sops.md)
shows; [the settings](../reference/settings.md) list every key and variable.

Then check that nothing names the old directory, before any command that writes:

```bash
grep -nE '^[[:space:]]*(data_dir|dir)[[:space:]]*=|atlassian-offline-mcp' ~/.config/kb-mcp/config.toml
env | grep '^KB_MCP_' | grep -iE 'DATA_DIR|LOGS__DIR|atlassian-offline-mcp'
kb-mcp check --detail detailed
```

The two `grep` print nothing, and `check` says `data_dir:` and your home's `kb-mcp`, then
`[default]`, and `logs.dir` `[default]` too; `check` without `--detail detailed` leaves
out the settings that hold their default. Nothing in kb-mcp stops a settings file that
names the old directory: its first run would upgrade that directory in place, which the
old program could no longer read, and leave no way back. A copy of the old file whole is
refused for its `site`, but once `site` is moved into the sources' tables, a `data_dir`
left in it passes `check` silently, as the rehearsal showed. The first `grep` catches
the usual spellings; the test that binds is `check`, whose `data_dir` and `logs.dir`
must both say `[default]`. Look in the same way at each script that sets `KB_MCP_*`
variables; section 7 checks the MCP clients' entries.

## 5. Check the sign-in

```bash
kb-mcp doctor --detail detailed
```

It says that the data directory, your home's `kb-mcp`, is allowed, then for each source
its `sign-in` row and a row named after it, `confluence` or `jira`, signed in. The clone
holds the old program's saved session, `session/cookies.json` and the browser profile
beside it: kb-mcp signs in with it where it is, and its first run that signs in, `fetch`
or `refresh`, moves it into the site's folder, `session/<host>/`, in the clone alone;
`doctor`, a dry run and `serve` move nothing. Run `doctor` again after the first runs:
if a source must sign in again, run `kb-mcp login`, which opens Chrome for you to sign
in, for each site, or `kb-mcp login confluence` for one source. A source that signs in
by an API token reads its variables, as the table above names them, and no session.

## 6. The first runs

Point no agent at kb-mcp before these runs end: `serve` refuses the clone's index, built
by 0.1.0, until `prepare`, `index` and `embed` have run. First move out of
`~/kb-mcp/docs/` any `.md` file that no program wrote there: 0.1.0 ignored it, but
`index` reads it, and fails it as a file without front matter.

```bash
kb-mcp refresh --yes
```

One run, as [bring every source up to date](refresh.md) says, without `--since`: each
space and project takes up from its last fetch by the old program.

- **fetch** reads each space's whole covered period again, as requests: its listing,
  not its pages, of which it fetches only what the store lacks; each project's keys are
  read whole once, then its issues updated since the old program's last fetch. The work
  log's fetch copies each document into its copy store, `copies/worklog/`, carrying the
  dates that the old mirror held. It rewrites the records of what was listed and
  covered, `listed_at.json` and `coverage.json`, and `tombstones.json` once a document is
  gone, in formats that 0.1.0 cannot read: hence the clone.
- **prepare** takes the old cache of conversions as Confluence's and Jira's, converts
  none of their documents again, and rewrites every file of the mirror, its front matter
  in the new form (section 8). The work log's documents go through pandoc once, as 0.1.0
  kept no conversion of theirs.
- **index** rebuilds the index whole, from schema 6, reading every file of the mirror.
- **embed** takes back from `vectors.sqlite` the vector of each chunk whose text is
  unchanged, and embeds what it lacks. Its prune of the vector cache is held back,
  `index.prune_skipped`, while an evaluated index built by 0.1.0 is left.

Then rebuild the evaluated indexes, on your golden file, which kb-mcp reads as 0.1.0
did, but for a bare id that two documents hold, refused: write it `<source>:<id>`.

```bash
kb-mcp eval --yes ~/kb-mcp/eval/golden.yaml
kb-mcp embed --yes
```

`eval` evaluates the setting's model in every chunking, rebuilding each of its indexes
under `eval/indexes/`. An index there of another model is rebuilt by `kb-mcp eval --yes
--model <model> ~/kb-mcp/eval/golden.yaml`, the model as the index's meta row names it,
`sqlite3 <index> "SELECT value FROM meta WHERE name = 'model'"`. The `embed` after it
then prunes, `pruned`, where it said `held back`.

What the rehearsal measured, on a sandbox of 13 pages, 11 issues and 29 documents of a
work log, against an endpoint on the machine:

| Run | Time | Requests | What it did |
|---|---|---|---|
| 0.1.0's `sync --since all`, which built the old directory | 36 s | 90 to the site | fetched every page and issue |
| clone and `quick_check` | under 1 s | none | 181 files |
| `doctor` | 2.4 s | 3 to the site | each source signed in |
| `refresh`: fetch | 2.4 s | 8 to the site | 13 pages listed, none fetched; the project's keys read whole; 29 work-log documents carried |
| `refresh`: prepare | 0.7 s | none | 25 conversions adopted; Confluence and Jira 0 converted, every file rewritten; the work log's 29 converted |
| `refresh`: index | 0.1 s | none | rebuilt whole: 53 documents, 192 sections, 8 persons |
| `refresh`: embed | 0.04 s | 2 to the endpoint | 85 chunks, each vector taken back, none embedded; prune held back |
| `eval`, every chunking | 2.5 s | 188 to the endpoint | four indexes rebuilt, none embedded (0.1.0's had embedded 316 texts) |
| `embed` again | 1 s | not counted | pruned, 401 vectors kept, none deleted |

On a real directory the fetch costs a few requests per space and project, whatever its
size, and the first prepare, index and evaluation take about as long as a full prepare,
index and evaluation always have, but download and embed nothing that the directory
holds. The issues' chunks under the chunkings `section-paths` and `small-to-big` hold
their breadcrumb, and may be embedded again; the rehearsal embedded none.

## 7. Register the agents again

Once the first runs have ended, register kb-mcp where the old server was, with the
arguments it had, such as `serve --allow-remote-embeddings`, save `--data-dir` and
`--config`, which would point kb-mcp at the old program's directory or settings, and
`--site`, which kb-mcp refuses; then remove the old one:

```bash
claude mcp add --scope user --transport stdio kb-mcp -- kb-mcp serve
claude mcp remove --scope user atlassian-offline-mcp
claude mcp list
```

Its line for kb-mcp shows the command `kb-mcp serve`, and none of its arguments is
`--data-dir`, `--config` or `--site`; check each other client's entry below the same
way. The example registers `kb-mcp serve` alone: add after `serve` the arguments that
the old entry had, save those three.

- **Claude Code** names a tool after its server: rename each rule
  `mcp__atlassian-offline-mcp__...` as `mcp__kb-mcp__...`, in `~/.claude/settings.json`
  and in each project's `.claude/settings.local.json`. Move the mirror's path,
  `~/kb-mcp/docs`, into `additionalDirectories` and the `Edit` deny rule: else that rule
  no longer covers the mirror that agents read. [Coding agents](agents.md) gives both.
- **VS Code**: in each `mcp.json`, the server's key and its `command`, then its tools
  approved again.
- **Every other client that starts the server**: a project's `.mcp.json`,
  `~/.lmstudio/mcp.json`, `~/.config/llama.cpp/mcp.json`, and `[mcp_servers.<name>]` in
  `~/.codex/config.toml`, each entry's key and command, as
  [a local model](local-model.md) sets them up.
- **Shell completion**: remove the old script, or the line
  `eval "$(atlassian-offline-mcp completion)"`, and load kb-mcp's as
  [shell completions](shell-completions.md) says; in zsh, remove `~/.zcompdump*` before
  opening a new shell.
- **`eval-agents`**: a run prepared by the old program calls its package, and one
  prepared before the consent to remote embeddings was given per call is refused as
  `outdated`: prepare each again, as [evaluate `ask` with agents](evaluate-with-agents.md)
  says.
- **Another search engine** over the mirror reads the old folder: add each collection
  again on `~/kb-mcp/docs/`, as [search the mirror with another engine](other-search-engines.md)
  says.
- **Grafana**: the dashboards of [observe with Grafana](observe-with-grafana.md) have new
  ids, and the series are named `kb_mcp_` where they were `aom_`; the old series stay,
  shown by no dashboard.

## 8. What changed for agents and scripts

The parser refuses each command and flag that went, exit 2:

| atlassian-offline-mcp 0.1.0 | kb-mcp |
|---|---|
| `sync` | `refresh`, or `fetch && prepare && index && embed` |
| `download` | `fetch` |
| `mirror` | `prepare` |
| `index`, for search by meaning | `index`, which writes the words alone, then `embed`, the vectors |
| `--summary short`, `--summary detailed` | `--detail short`, `--detail detailed` |
| `--site <site>` | refused: the site of each source, `sources.<name>.site` |
| `login`, `login atlassian` | `login`, for each site, or `login <source>`, such as `login jira` |

What agents, scripts and dashboards read changed too:

- **The MCP tools' arguments**: `space` and `project` are `scope`, its type then its key,
  such as `space:ENG` or `project:PLAT`; `issue_type` is `subtype`; `browse` takes
  `scope` and `parent`; a document's ref is `<source>:<id>`, such as `jira:PLAT-12`. An
  old argument is refused as unknown: change the prompts and skills that name them, as
  [the MCP tools](../reference/mcp-tools.md) say.
- **The JSON of each command and the telemetry**: `steps` are `sources`, `pieces` are
  `chunks`, `eval`'s `runs` are `indexes`, `status` and `outcome` are `ending`, `target`
  is `scope`, and the metrics' prefix `aom_` is `kb_mcp_`.
- **The mirror's front matter**: `space` and `project` are `scope`, `issue_type` is
  `subtype`, a person's `account: <id>` is `identity: 'atlassian:<id>'`, a link's `ref`
  is its `document`, `<source>:<id>`, `fetched_at` went, and each document names its
  `parent`; beside each source's documents, `_source.json`. No person's id changes.
- **The work log's meetings and dated transcripts** are dated at midnight UTC of their
  day; their ids stay, but two meetings of one day under one title, one of them with a
  transcript, may swap theirs.
- **A stray `.md` file under the mirror**, which 0.1.0 ignored, is read: `index` reports
  it as a file without front matter and exits 1. Move it out of `docs/`.
- **Runs**: each run is recorded under `runs/<run id>/`; the old reports,
  `runs/<time>.json`, stay, read by nothing. `eval`'s old results, under `runs`, stay too.
- **Logs**: in `~/Library/Logs/kb-mcp` on macOS, `$XDG_STATE_HOME/kb-mcp/log` on Linux;
  the old folder is no longer pruned.

## 9. The way back

Until section 10, go back by going on with `atlassian-offline-mcp`: nothing touched its
program, its settings file, its variables or its data directory. Register its server
again where you removed it, with the arguments it had before section 7, and put back
its rules of section 7 as they were:

```bash
claude mcp add --scope user --transport stdio atlassian-offline-mcp -- atlassian-offline-mcp serve
```

Never point the old program at `~/kb-mcp`: kb-mcp's runs rewrote its records in formats
that 0.1.0 refuses. To try the upgrade again, move `~/kb-mcp` aside and start again from
section 1.

## 10. Remove the old program

Once kb-mcp serves what you need, and you have measured what you wanted to with pandoc
and the model of section 1, remove the old program; from here there is no way back.

```bash
uv tool uninstall atlassian-offline-mcp
```

Then, when you no longer want them, remove its settings folder,
`~/.config/atlassian-offline-mcp`, its data directory, `~/atlassian-offline-mcp`, its
log folder, `~/Library/Logs/atlassian-offline-mcp` on macOS or
`$XDG_STATE_HOME/atlassian-offline-mcp` on Linux, and the clone of the repository made
for it.
