# fetch

What `fetch` records, besides what every command does ([README](README.md)). A run is one
trace: its root `fetch`, then a span of each source taken, `fetch.source`, Confluence's,
then Jira's, each signing in and holding the raw store for itself: a span for each of its
spaces or projects listed, for Confluence one for the probes and one for the users, and
the requests between. So a run gives `fetch.store_busy` and `fetch.sign_in_needed` once
per source, naming it. Each document fetched is a trace of its own, `fetch.document`,
linked to the span of its space or project: Tempo drops a trace past 5 MB, which a run of
thousands of documents would pass. The files that a document already stored lacks are
fetched in the run's trace, in its space's or project's span.

## Events

| Event | Level | Fields | When |
|---|---|---|---|
| `fetch.listed` | info | `target`, `listed`, `in_window`, `stored`, `to_fetch`, `start`, `reason` | A space is listed whole, or a project searched over its fetch window: how many documents it lists, how many are in its window, stored already and to fetch; where the window starts and why: `given` (`--since`), `since the last fetch`, `covered start` or `first fetch` |
| `fetch.document` | debug | `id`, `kind`, `title` | A document is fetched, and its snapshot read |
| `fetch.document_failed` | warning | `id`, `kind`, `reason` | A document cannot be fetched: the run goes on, and exits 1 |
| `fetch.document_unread` | warning | `kind`, `reason` | A snapshot that its adapter refuses: stored as it came, without its files |
| `fetch.file_skipped` | info | `id`, `file_name`, `reason` | An attached file is not downloaded, by its media type or its size |
| `fetch.file_failed` | warning | `id`, `file_name`, `reason` | An attached file cannot be downloaded, or is not the size listed |
| `fetch.target_failed` | warning | `target` | A space or a project named cannot be listed |
| `fetch.coverage` | info | `target`, `outcome`, `reason` | A target finished or skipped: its coverage `extended` to its fetch window's end, joined with it, or, for a project's entry from before plan 034 that the window starts at or before, replaced by it; a project's `capped` at the update time of its earliest document not stored whole; or `held` as it was, `reason` saying why: `entries refused` (a search entry that the adapter refuses), `after --until` (a catch-up that would start after it), `apart from what is covered` |
| `fetch.start` | info | `sources`, `dry_run` | The sources that the run takes, in their order, and whether it only plans |
| `fetch.source` | info | `source`, `outcome` | A source's row ended: `done`, `failed` or `sign in` |
| `fetch.end` | info | `status`, `sources` | The run's exit status, and how each row ended |
| `fetch.refused` | error | `source`, `reason` | A fetcher that does not load, naming the source and the path, or what a fetcher's preflight refuses, after its source and its stage (`source 'confluence': fetch: ...`), such as a period or a store's record, of what answered as gone for Confluence's fetch alone, stops the run before its first row, exit 2, without `source`. Such a record damaged once the run began fails that source's row alone, naming it, and the next rows go on |
| `fetch.store_busy` | error | `source`, `store`, `hint` | Another run writes the raw store: the source's fetch fails, exit 1 |
| `fetch.interrupted` | warning | `source` | Ctrl-C stopped the row of this source, none once every row ended: later rows do not run, exit 130 |
| `fetch.sign_in_needed` | error | `source`, `hint` | The session or the token no longer opens the site for the source's fetch: exit 3 |
| `http.get` | debug | `url`, `status`, `error`, `seconds` | Each request, a redirect's included; the query shown on the site alone |
| `http.retry` | debug | `path`, `attempt`, `failure`, `wait_s` | A request retried after a throttling, gateway or transport failure |

`source` is `confluence` or `jira`; `kind`, `confluence pages`, `confluence blogposts`
or `jira issues`; `target`, as `space MFS` or `project PRB`.

## Spans

| Span | Kind | Attributes | What |
|---|---|---|---|
| `fetch.source` | internal | `kb_mcp.source`, `kb_mcp.outcome` | A source's row: its source and how it ended, no outcome on one that Ctrl-C stopped |
| `fetch.space` | internal | `kb_mcp.target` | A space, by its key: listed, stored, its documents fetched; an error when it cannot be listed |
| `fetch.project` | internal | `kb_mcp.target` | A project, by its key: searched, its issues fetched; an error when the search cannot be read |
| `fetch.probes` | internal | | The documents that a space no longer lists, probed |
| `fetch.users` | internal | | The authors' names, fetched and merged |
| `fetch.document` | internal | `kb_mcp.document.id`, `kb_mcp.document.kind`, `kb_mcp.document.title` | A document fetched: the root of a trace of its own, linked to its space's or project's span; an error when the fetch fails |
| `GET` | client | `http.request.method`, `server.address`, `server.port`, `url.full`, `http.response.status_code`, `error.type` | Each request, by the HTTP conventions, until its answer's headers; an error from status 400 |

## Instruments

| Instrument | Kind | Unit | Attributes | What |
|---|---|---|---|---|
| `http.client.request.duration` | histogram | `s` | `http.request.method`, `server.address`, `server.port`, `http.response.status_code`, `error.type` | Each request, by the HTTP conventions |
| `kb_mcp.fetch.documents` | counter | `{document}` | `kb_mcp.outcome` | The documents fetched, `fetched` or `failed` |
| `kb_mcp.fetch.files` | counter | `{file}` | `kb_mcp.outcome` | The attached files, `downloaded`, `failed` or `skipped` |
| `kb_mcp.fetch.bytes` | counter | `By` | | The bytes of the files downloaded |
