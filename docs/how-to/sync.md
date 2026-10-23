# Bring every source up to date

`sync` runs what `download` and `mirror` do for Confluence and Jira, mirrors the work
log, each source as its settings' table names it, then rebuilds the index, as `index`
does. It is the one command to run when the mirror and search should be current;
`download`, `mirror` and `index` stay, for one step at a time.

## 1. Name the sources

Each source is configured by its table in `~/.config/atlassian-offline-mcp/config.toml`:

```toml
site = "https://<your-site>.atlassian.net"

[sources.confluence]
spaces = ["ENG", "OPS"]

[sources.jira]
projects = ["PLAT"]

[sources.worklog]
path = "~/todo"  # absolute or under ~
```

A table that names nothing (no space, no project, no folder) leaves its source out.
`sync` takes its keys from the tables alone: `--space` and `--project` belong to
`download`, for a one-off run. The work log has its own guide: [mirror the work
log](work-log.md).

## 2. Run it

```bash
atlassian-offline-mcp sync
```

Before it acts, it writes on stderr each setting it reads, each source it takes with its
keys or folder, each it leaves out and why, and the command written in full, then asks
`Proceed? [y/N]`, as every command that writes does. `--yes` runs it without the
question.

The steps, in order:

1. **Confluence and Jira**: one download of every space and project named, then the
   mirror of the raw store. Without `--since`, each space and project catches up from
   the start of what earlier runs covered; one never covered needs `--since` the first
   time, and is refused by name before anything runs. `--since`, `--back`, `--until`
   and `--max-file-mb` work as for `download`.
2. **The work log**: read whole, each document converted again only when it changed,
   the files of documents gone removed.
3. **The index**: rebuilt from the whole mirror, whatever sources the run took, by the
   settings `index` reads: `search_mode`, `model`, `chunking` and the embedding
   endpoint. By default, in hybrid mode, it needs the endpoint and its model, Ollama on
   this machine or any other OpenAI-compatible API, as [search by
   meaning](agents.md#search-by-meaning) says: without them, its row fails once the
   other steps have run, and `sync` exits 1. It embeds what `<data>/vectors.sqlite`
   lacks: every piece of the mirror the first time, then only the pieces whose text
   changed. By words alone, `search_mode = "lexical"`, it calls no endpoint. An endpoint
   off this machine needs `--allow-remote-embeddings`, as for `index`, and is refused
   before anything runs without it, unless a dry run.

Each step runs even when an earlier one failed, since the next reads what is on disk:
the work log is mirrored when the site asks to sign in again, and the index is built
from what the mirror holds. Ctrl-C stops the run, and no later step starts.

## 3. Choose among the sources

```bash
atlassian-offline-mcp sync --include worklog
atlassian-offline-mcp sync --exclude worklog --since 7d
```

`--include` takes the sources named alone, `--exclude` all but those, never both in one
run; each repeats, and takes `confluence`, `jira` or `worklog`. The index is rebuilt
whatever the choice: `sync --include worklog` refreshes the work log alone, and search
still finds every page and issue mirrored. A source included without its table, or a
run left with none, is refused, saying why. The work log reads no period: an option of
the period given while it runs is said to be ignored by it (`--since: ignored by
worklog`), and settings that no source taken uses are said not applied, never refused.

## 4. Look before running

```bash
atlassian-offline-mcp sync --dry-run --since 7d
```

`--dry-run` plans the download as `download --dry-run` does, and counts the work log:
its documents, those it would convert, and the files it would remove. The mirror and
the index do not run, so the index's settings are said not applied, and an endpoint off
this machine is not refused. It writes nothing, and does not ask.

## 5. Read the result

A row per step says how it ended: `done`, `failed`, `sign in`, `interrupted` or `not
run`, then that step's counts as its own command gives them; `--summary detailed` gives
all of them. `--format json` writes one document: `exit_status`, and `steps`, each with
its `step`, `outcome` and `result`.

The exit status is 2 when refused before any step, 130 when interrupted, else 3 when a
step needs you to sign in again, else 1 when a step failed or you answered no, else 0.
