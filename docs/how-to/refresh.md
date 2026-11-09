# Bring every source up to date

Four commands, each one stage, which you compose: `fetch` brings each source's changes into
its store, `prepare` turns what each source holds into the Markdown mirror, `index` brings
the index of the mirror's words up to the mirror, and `embed` gives the index's chunks their
vectors, for search by meaning. Nothing runs them for you, and no command runs another.

## 1. Name the sources

Each source is configured by its table in `~/.config/kb-mcp/config.toml`:

```toml
[accounts.atlassian]
site = "https://<your-site>.atlassian.net"

[sources.confluence]
spaces = ["ENG", "OPS"]

[sources.jira]
projects = ["PLAT"]

[sources.worklog]
path = "~/todo"  # absolute or under ~
```

Confluence and Jira sign in with the Atlassian account, on its site. A table that names
nothing (no space, no project, no folder) leaves its source out of `fetch`, and the work log
out of `prepare`. The work log has its own guide: [add the work log](work-log.md).

## 2. Run the chain

```bash
kb-mcp fetch --yes && kb-mcp prepare --yes && kb-mcp index --yes && kb-mcp embed --yes
```

With the work log alone, nothing needs fetching: `fetch` is refused, exit 2, so start the
chain at `prepare`.

Without `--yes`, each command writes on stderr each setting it reads, each source it takes,
each it leaves out and why, and the command written in full, then asks `Proceed? [y/N]`, as
every command that writes does.

1. **`fetch`** brings what changed of each configured source that has a fetcher,
   Confluence's spaces then Jira's projects, a row each. Without `--since`, each space and
   project fetches what changed since its last fetch, and asks again for what failed; one
   never fetched takes its last 7 days, as the echo before the question says. `--since`
   (`12h`, `7d`, `6mo`, an ISO date or time, or `all`) and `--until` set the period, and
   `--max-file-mb` the largest file kept. `--space` and `--project` replace a setting for
   one run. Each source's report goes to `<data>/runs/<time>-<source>.json`.
2. **`prepare`** writes the mirror, a row each: each source that keeps a store, from all
   that its store holds, even a space no longer configured, and the work log, read whole in
   place, each document converted again only when it changed, the files of documents gone
   removed. It reaches no site and signs in nowhere, but it reads the site's address, which
   gives each document its `url` and resolves the links between pages: without a site set, it
   still runs, and says that those documents get no address.

   The mirror keeps pandoc's conversions in `<data>/conversions.sqlite`: the first run
   converts every document, taking as long as a mirror always has, and each run after it
   only what changed; each of their rows says how many were `converted by pandoc` and how
   many `reused from the cache`. Deleting the file starts again, converting everything once and
   downloading nothing: do so after installing a pandoc rebuilt under the same version
   line, the one change that the cache cannot see. A damaged file is replaced by the run
   itself, which converts everything and says so in its log (`prepare.cache_replaced`):
   nothing to do. One that another run holds for more than a minute, or that breaks during
   the run, fails the prepare and stops it there; the next run tries again, on a new file
   if it broke. Deleting the file is also the remedy for a mirror that looks wrong.
3. **`index`** brings the index of the mirror's words up to the mirror, whatever sources
   `prepare` took. It reads only the files whose bytes changed, copies every other
   document from the index in place, with its vectors, leaves out the documents gone, and
   writes nothing when nothing changed; the first run, or `--rebuild`, builds it whole. It
   asks no endpoint, whatever `search_mode` says, and leaves `<data>/vectors.sqlite` as it
   is. Until `embed` runs, the documents added or changed have no vectors, and search
   finds them by words alone; its report says how many await them.
4. **`embed`** gives the index's chunks their vectors. By default it needs Ollama on this
   machine, or any other OpenAI-compatible API, as [embeddings](embeddings.md) says: without
   them, it exits 1, and the index in place stays. It embeds what `<data>/vectors.sqlite`
   lacks: every chunk of the mirror the first time, then only the chunks whose text changed,
   as [building the index](embeddings.md#3-build-the-index) says. An endpoint off this
   machine needs `--allow-remote-embeddings`, and is refused without it. `embed` then prunes
   the vector cache of what no index reads.

`embed` reads the index, not the mirror: `prepare && embed`, leaving out `index`, is a
wrong use. `embed` then fills the index as the last `index` left it, so that a page that
`prepare` removed, and an edited page's old text, stay served until the next `index`.
`embed` compares the mirror's files with the index, and when they differ warns,
`embed.mirror_changed`, naming `kb-mcp index`, then goes on, with the exit status it would
have had: composing the commands is your choice. Run `index` between them.

## 3. Take some of the sources

```bash
kb-mcp fetch confluence --space ENG --since 7d
kb-mcp prepare confluence
```

A command takes the sources named, once each, in the registry's order, however you type
them; together, before or after the options, never split by one. `fetch` takes `confluence`
or `jira`, `prepare` those and `worklog`. Without a name, `fetch` takes every one configured
and `prepare` every one that keeps a store, and the work log when configured. A source named
but not configured is refused, naming its setting, as is a run left with none. A flag of a
source not taken, such as `--project` with `fetch confluence`, is said not applied.

`prepare confluence` prepares Confluence alone, so Jira's files whose links depend on
Confluence's pages are rewritten only when Jira is prepared, and what they attach stays
until then. `index` digests the whole mirror, and reads each file that changed, whichever
source wrote it: `prepare worklog`, then `index`, refreshes the work log alone, and search
still finds every page and issue of the mirror.

## 4. Search by words alone

Stop after `index`:

```bash
kb-mcp fetch --yes && kb-mcp prepare --yes && kb-mcp index --yes
```

```toml
search_mode = "lexical"
```

The setting tells the server not to ask for meaning. An `index` run after an `embed`
keeps the vectors of the documents that did not change, which the server then never
reads; `kb-mcp index --rebuild` writes an index without any.

## 5. Decide what to do on a failure

Each command's exit status says what the next command can rely on:

| Status | Means | The next command |
|---|---|---|
| 0 | every row done | runs |
| 1 | a row failed, the others ran; or the run stopped, with no rows written, on a cache of conversions that it could not use, or on a `<data>/docs` or `<data>/raw` that is no folder; or you answered no | can run on what the raw store or the mirror holds, once you have read why |
| 2 | refused before any row | should not: nothing ran, and it is yours to fix |
| 3 | to sign in again | should not, until you have |
| 130 | stopped by Ctrl-C | should not |

`&&` stops on any of them. A script that goes on past a partial failure, and stops on the
others, tests the status:

```bash
kb-mcp fetch --yes
status=$?
[ "$status" -le 1 ] || exit "$status"
kb-mcp prepare --yes
```

Compose with `&&` rather than `;`: a run catches Ctrl-C and exits 130, on which `&&` stops
in every shell, while bash runs the next command after `;`.

A shell function keeps the chain, written on several lines:

```bash
refresh() {
  kb-mcp fetch --yes &&
    kb-mcp prepare --yes &&
    kb-mcp index --yes &&
    kb-mcp embed --yes
}
```

## 6. Look before running

```bash
kb-mcp fetch --dry-run --since 7d
kb-mcp prepare --dry-run
```

`fetch --dry-run` reads the site and fetches nothing: each target's fetch window first,
where it starts and why, then what it would fetch. `prepare --dry-run` counts the work log: its
documents, those it would convert, and the files it would remove. Confluence and Jira cannot
count without converting, so their rows say `not run` and that they are not counted. Neither
writes anything, nor asks. `index` and `embed` take none.

## 7. Read the result

A row per source says how it ended: `done`, `failed`, `sign in`, `interrupted` or `not run`,
then its counts; `--detail detailed` gives all of them, a fetch's beginning with each
target's fetch window and what became of its coverage. A fetch counts what it fetches: with
`--since`, the documents in the period and those already stored; without, those new or
changed since the last fetch. `--format json` writes one document: `exit_status`, and
`sources`, each with its `source`, `outcome` and `result`.
