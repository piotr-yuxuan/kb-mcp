# download

What `download` records, besides what every command does ([README](README.md)). A run is
one trace: its root `download`, then a fetch of each source on its own, Confluence's,
then Jira's, each signing in and holding the raw store for itself: a span for each of
its spaces or projects listed, for Confluence one for the probes and one for the users,
and the requests between. So a run gives `download.store_busy` and
`download.sign_in_needed` once per source, naming it, and `download.refused` and
`download.interrupted` once at most. Each document fetched is a trace of its own,
`download.document`, linked to the span of its space or project: Tempo drops a trace
past 5 MB, which a run of thousands of documents would pass. The files that a document
already stored lacks are fetched in the run's trace, in its space's or project's span.

## Events

| Event | Level | Fields | When |
|---|---|---|---|
| `download.listed` | info | `target`, `listed`, `in_window`, `stored`, `to_fetch`, `start`, `reason` | A space or a project is listed whole: how many documents it lists, how many are in its window, stored already and to fetch; where the window starts and why: `given` (`--since`), `since the last fetch`, `covered start` or `first fetch` |
| `download.document` | debug | `id`, `kind`, `title` | A document is fetched, and its snapshot read |
| `download.document_failed` | warning | `id`, `kind`, `reason` | A document cannot be fetched: the run goes on, and exits 1 |
| `download.document_unread` | warning | `kind`, `reason` | A snapshot that its adapter refuses: stored as it came, without its files |
| `download.file_skipped` | info | `id`, `file_name`, `reason` | An attached file is not downloaded, by its media type or its size |
| `download.file_failed` | warning | `id`, `file_name`, `reason` | An attached file cannot be downloaded, or is not the size listed |
| `download.target_failed` | warning | `target` | A space or a project named cannot be listed |
| `download.coverage` | info | `target`, `outcome`, `reason` | A target finished or skipped: its coverage `extended` to its window's end, joined with it, or, for a project's entry from before plan 034 that the window starts at or before, replaced by it; a project's `capped` at the update time of its earliest document not stored whole; or `held` as it was, `reason` saying why: `entries refused` (a search entry that the adapter refuses), `after --until` (a catch-up that would start after it), `apart from what is covered` |
| `download.refused` | error | `reason` | The period or a setting is refused, before any request: exit 2. In `sync`, where a fetcher's preflight refused them before the first row, one that comes once the run began also names its `source`, and fails that fetch's row alone |
| `download.store_busy` | error | `source`, `store`, `hint` | Another run writes the raw store: the source's fetch fails, exit 1 |
| `download.interrupted` | warning | `counts` | Ctrl-C stopped the download, whose counts are saved there: exit 130 |
| `download.sign_in_needed` | error | `source`, `hint` | The session or the token no longer opens the site for the source's fetch: exit 3 |
| `http.get` | debug | `url`, `status`, `error`, `seconds` | Each request, a redirect's included; the query shown on the site alone |
| `http.retry` | debug | `path`, `attempt`, `failure`, `wait_s` | A request retried after a throttling, gateway or transport failure |

`source` is `confluence` or `jira`; `kind`, `confluence pages`, `confluence blogposts`
or `jira issues`; `target`, as `space MFS` or `project PRB`.

## Spans

| Span | Kind | Attributes | What |
|---|---|---|---|
| `download.space` | internal | `kb_mcp.target` | A space, by its key: listed, stored, its documents fetched; an error when it cannot be listed |
| `download.project` | internal | `kb_mcp.target` | A project, by its key: searched, its issues fetched; an error when the search cannot be read |
| `download.probes` | internal | | The documents that a space no longer lists, probed |
| `download.users` | internal | | The authors' names, fetched and merged |
| `download.document` | internal | `kb_mcp.document.id`, `kb_mcp.document.kind`, `kb_mcp.document.title` | A document fetched: the root of a trace of its own, linked to its space's or project's span; an error when the fetch fails |
| `GET` | client | `http.request.method`, `server.address`, `server.port`, `url.full`, `http.response.status_code`, `error.type` | Each request, by the HTTP conventions, until its answer's headers; an error from status 400 |

## Instruments

| Instrument | Kind | Unit | Attributes | What |
|---|---|---|---|---|
| `http.client.request.duration` | histogram | `s` | `http.request.method`, `server.address`, `server.port`, `http.response.status_code`, `error.type` | Each request, by the HTTP conventions |
| `kb_mcp.download.documents` | counter | `{document}` | `kb_mcp.outcome` | The documents fetched, `fetched` or `failed` |
| `kb_mcp.download.files` | counter | `{file}` | `kb_mcp.outcome` | The attached files, `downloaded`, `failed` or `skipped` |
| `kb_mcp.download.bytes` | counter | `By` | | The bytes of the files downloaded |
