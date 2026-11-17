# Bring every source up to date

Four stages: `fetch` brings each source's changes into its store, `prepare` turns what each
source holds into the Markdown mirror, `index` brings the index of the mirror's words up to
the mirror, and `embed` gives the index's chunks their vectors, for search by meaning.
`refresh` runs the four as one run; each is a command of its own too, to run one alone.
Every run of them is recorded under `<data>/runs/<run id>/`, so that one stopped part-way
is resumed by its id. Nothing runs them for you on a schedule.

## 1. Name the sources

Each source is configured by its table in `~/.config/kb-mcp/config.toml`:

```toml
[sources.confluence]
spaces = ["ENG", "OPS"]
site = "https://<your-site>.atlassian.net"

[sources.jira]
projects = ["PLAT"]
site = "https://<your-site>.atlassian.net"

[sources.worklog]
path = "~/todo"  # absolute or under ~
```

Confluence and Jira each sign in on their own site, which may be one; a second Jira site
is a second source, such as `[sources.clientjira]` with `connector = "jira"`, its own
projects and its own site. A table that names
nothing (no space, no project, no folder) leaves its source out of `fetch`, and the work log
out of `prepare`. The work log has its own guide: [add the work log](work-log.md).

## 2. Refresh

```bash
kb-mcp refresh --yes
```

Without `--yes`, it writes on stderr each setting it reads, what each stage takes, each
source left out and why, and the command written in full, then asks `Proceed? [y/N]` once,
as every command that writes does. The run's work is units, in this order:

1. **fetch**, a unit per source configured that has a fetcher, Confluence's spaces, Jira's
   projects, then the work log. Without `--since`, each space and project fetches what
   changed since its last fetch, and asks again for what failed; one never fetched takes its
   last 7 days, as the echo before the question says. `--since` (`12h`, `7d`, `6mo`, an ISO
   date or time, or `all`) and `--until` set the period, and `--max-file-mb` the largest
   file kept, which the work log, read whole each time, ignores. `--space` and `--project`
   replace a setting for one run. The work log's fetch keeps each document's text in its
   copy store, `<data>/copies/worklog/`.
2. **prepare**, a unit per source: each source that keeps a store, from all that its store
   holds, even a space no longer configured, and the work log, when configured, from its copy
   store alone, the files of documents gone removed. A source's prepare runs only once its
   fetch is done: a source whose fetch failed, or must sign in again, is `not run`, and its
   files of the mirror stay as they were, while the other sources go on. Prepare reaches no
   site and signs in nowhere, but it reads the site's address, which gives each document its
   `url` and resolves the links between pages: without a site set, it still runs, and says
   that those documents get no address.

   The mirror keeps pandoc's conversions in `<data>/conversions.sqlite`: the first run
   converts every document, taking as long as a mirror always has, and each run after it
   only what changed; each of their units says how many were `converted by pandoc` and how
   many `reused from the cache`. Deleting the file starts again, converting everything once and
   downloading nothing: do so after installing a pandoc rebuilt under the same version
   line, the one change that the cache cannot see. A damaged file is replaced by the run
   itself, which converts everything and says so in its log (`prepare.cache_replaced`):
   nothing to do. One that another run holds for more than a minute, or that breaks during
   the run, fails the prepare and stops it there; the next run tries again, on a new file
   if it broke. Deleting the file is also the remedy for a mirror that looks wrong.
3. **index**, over the whole, whatever the prepares ended: it brings the index of the
   mirror's words up to the mirror, whichever sources wrote it. It reads only the files whose
   bytes changed, copies every other document from the index in place, with its vectors,
   leaves out the documents gone, and writes nothing when nothing changed; the first run, or
   `kb-mcp index --rebuild`, builds it whole. It asks no endpoint, whatever `search_mode`
   says, and leaves `<data>/vectors.sqlite` as it is.
4. **embed**, over the whole: it gives the index's chunks their vectors. By default it needs
   Ollama on this machine, or any other OpenAI-compatible API, as [embeddings](embeddings.md)
   says: without them, its unit fails, and the index in place stays. It embeds what
   `<data>/vectors.sqlite` lacks: every chunk of the mirror the first time, then only the
   chunks whose text changed, as [building the index](embeddings.md#3-build-the-index)
   says. An endpoint off this machine needs `--allow-remote-embeddings`, and is refused
   without it. `embed` then prunes the vector cache of what no index reads.

With the work log alone, the run is the same: its fetch reads its folder, and its prepare
writes from what the fetch kept.

The run resolves its configuration as it starts, before it reads any store: the stages, the
sources that each takes, the period, with `--since 7d` made the time 7 days before and an
end left to now made that start, and every setting. It writes it to
`<data>/runs/<run id>/configuration.json`, without any secret, then runs from what it reads
back; each unit's outcome goes to `outcomes.json` as it ends, as [the data
layout](../reference/data-layout.md#runs) says.

## 3. Resume a run

The result's first line names the run, `run 3f2a9c1d0b7e4a65`, as `--format json` does by
`run`. A run whose units did not all end done says on stderr, by the warning
`run.resumable`, the command that resumes it:

```bash
kb-mcp refresh --resume 3f2a9c1d0b7e4a65 --yes
```

A resume runs the configuration that the run recorded, whichever command started it,
`fetch` and the others included: each unit that did not end done, a fetch to sign in again,
an interrupted prepare, and each unit that follows one of those, such as the index after a
source fetched and prepared again. The units done stay as they are. It takes the secrets,
such as an API token, from its environment again, and the consent to an endpoint off this
machine, `--allow-remote-embeddings`, from its own command line, when embed runs again. It
asks again unless given `--yes`, saying the units done and those it runs in place of the
settings, then, as any run, whether telemetry is on, the values ignored and the command to
copy, which resumes it again.

It finds the run under the data directory that its settings, or `--data-dir`, name, so give
the same `--config` or `--data-dir` as the run did. Anything that would change the
configuration is refused, exit 2: a source named, `--since`, `--until`, `--max-file-mb`,
`--space` or `--project`; so is a run of another data directory, a source no longer in the
settings, and a run that another invocation holds. Its exit status folds the last ending of
every unit, whichever invocation gave it.

## 4. Take some of the sources

```bash
kb-mcp refresh confluence --space ENG --since 7d
```

A refresh takes the sources named, once each, in the registry's order, however you type
them; together, before or after the options, never split by one: it fetches and prepares
them alone, then indexes and embeds the whole mirror. It takes those that `fetch` takes,
`confluence`, `jira` and `worklog`. Without a name, it fetches every one configured, and
prepares every one that keeps a store of spaces or projects, and the work log when
configured. A source named but not configured is refused, naming its setting, as is a run
left with none. A flag of a source not taken, such as `--project` with `refresh
confluence`, is said not applied.

Preparing Confluence alone leaves Jira's files whose links depend on Confluence's pages
as they are until Jira is prepared, and what they attach stays until then. `index` digests
the whole mirror, and reads each file that changed, whichever source wrote it: `refresh
worklog` refreshes the work log alone, and search still finds every page and issue of the
mirror.

## 5. Run one stage alone

Each stage is a command of its own, a run of that stage alone, recorded and resumable as a
refresh is: `fetch` and `prepare` take sources by name as `refresh` does, `index` takes
`--rebuild`, and `embed` takes `--allow-remote-embeddings`. To search by words alone, stop
after `index`:

```bash
kb-mcp fetch --yes && kb-mcp prepare --yes && kb-mcp index --yes
```

```toml
search_mode = "lexical"
```

The setting tells the server not to ask for meaning. An `index` run after an `embed`
keeps the vectors of the documents that did not change, which the server then never
reads; `kb-mcp index --rebuild` writes an index without any.

`embed` reads the index, not the mirror: `prepare && embed`, leaving out `index`, is a
wrong use. `embed` then fills the index as the last `index` left it, so that a page that
`prepare` removed, and an edited page's old text, stay served until the next `index`.
`embed` compares the mirror's files with the index, and when they differ warns,
`embed.mirror_changed`, naming `kb-mcp index`, then goes on, with the exit status it would
have had. A refresh always indexes between them.

Compose with `&&` rather than `;`: a run catches Ctrl-C and exits 130, on which `&&` stops
in every shell, while bash runs the next command after `;`.

## 6. Decide what to do on a failure

A run's exit status folds how its units last ended, the most severe first:

| Status | Means | Then |
|---|---|---|
| 0 | every unit done | nothing to do |
| 1 | a unit failed, or its source's check refused it, the others ran; or the run stopped, with no unit written, on a cache of conversions that it could not use, or on a `<data>/docs` or `<data>/raw` that is no folder; or you answered no | read why, fix it, and resume the run |
| 2 | refused before any unit | nothing ran, and it is yours to fix |
| 3 | to sign in again | sign in, then resume the run |
| 130 | stopped by Ctrl-C | resume the run |

A source's fetch that fails stops none of the others: their prepares run, then index and
embed, and the run exits 1. Resuming it, once you have fixed what failed, fetches and
prepares that source alone, then indexes and embeds again.

## 7. Look before running

```bash
kb-mcp fetch --dry-run --since 7d
kb-mcp prepare --dry-run
```

`fetch --dry-run` reads the site and fetches nothing: each scope's fetch window first,
where it starts and why, then what it would fetch; of the work log, what its read would
change in its copy store, the documents new, changed and gone. `prepare --dry-run` counts
the work log's documents and the files that it would remove, from what its last fetch kept,
but not what it would convert. Confluence and Jira cannot count without converting, so
their rows say `not run` and that they are not counted. Neither writes anything, nor
asks, nor records itself under `<data>/runs/`, so neither can be resumed: its text says
`run <run id>, not recorded`. `refresh`, `index` and `embed` take none.

## 8. Read the result

After the run's id, a row per unit says how it ended: `done`, `failed`, `sign in again`,
`interrupted` or `not run`, then what matters of its counts, and each problem and warning
by its place and reason; `--detail detailed` gives every count, a fetch's beginning with
each scope's fetch window and what became of its coverage. A unit done by an earlier
invocation of a resumed run names when that invocation started, without its counts, which
its record keeps. A fetch counts what it fetches: with `--since`, the documents in the
period and those already stored; without, those new or changed since the last fetch.
`--format json` writes one document: `run`, `exit_status`, and `units`, each with its
`stage`, `source`, `ending`, `counts`, `problems`, `warnings` and `invocation`. `fetch` and
`prepare` write `run`, `exit_status` and `sources`, a row each with its `source`,
`ending`, `counts`, `problems` and `warnings`; `index` and `embed`, `run`, then their
unit's `ending`, `counts`, `problems` and `warnings`.
