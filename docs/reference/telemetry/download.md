# download

What `download` records, besides what every command does ([README](README.md)). A run is
one trace: its root `download`, a span for each space and project listed, one for the
probes and one for the users, and the requests between. Each document fetched is a
trace of its own, `download.document`, linked to the span of its space or project:
Tempo drops a trace past 5 MB, which a run of thousands of documents would pass. The
files that a document already stored lacks are fetched in the run's trace, in its
space's or project's span.

## Events

| Event | Level | Fields | When |
|---|---|---|---|
| `download.listed` | info | `target`, `documents` | A space or a project is listed whole: how many documents it lists |
| `download.document` | debug | `id`, `kind`, `title` | A document is fetched, and its snapshot read |
| `download.document_failed` | warning | `id`, `kind`, `reason` | A document cannot be fetched: the run goes on, and exits 1 |
| `download.document_unread` | warning | `kind`, `reason` | A snapshot that its adapter refuses: stored as it came, without its files |
| `download.file_skipped` | info | `id`, `name`, `reason` | An attached file is not downloaded, by its media type or its size |
| `download.file_failed` | warning | `id`, `name`, `reason` | An attached file cannot be downloaded, or is not the size listed |
| `download.target_failed` | warning | `target` | A space or a project named cannot be listed |
| `download.refused` | error | `reason` | The period or a setting is refused, before any request: exit 2 |
| `download.store_busy` | error | `store`, `hint` | Another run writes the raw store: exit 1 |
| `download.interrupted` | warning | `counts` | Ctrl-C stopped the download, whose counts are saved there: exit 130 |
| `download.sign_in_needed` | error | `hint` | The session or the token no longer opens the site: exit 3 |
| `http.get` | debug | `url`, `status`, `error`, `seconds` | Each request, a redirect's included; the query shown on the site alone |
| `http.retry` | debug | `path`, `attempt`, `failure`, `wait_s` | A request retried after a throttling, gateway or transport failure |

`kind` is `confluence pages`, `confluence blogposts` or `jira issues`; `target`, as
`space MFS` or `project PRB`.

## Spans

| Span | Kind | Attributes | What |
|---|---|---|---|
| `download.space` | internal | `aom.target` | A space, by its key: listed, stored, its documents fetched; an error when it cannot be listed |
| `download.project` | internal | `aom.target` | A project, by its key: searched, its issues fetched; an error when the search cannot be read |
| `download.probes` | internal | | The documents that a space no longer lists, probed |
| `download.users` | internal | | The authors' names, fetched and merged |
| `download.document` | internal | `aom.document.id`, `aom.document.kind`, `aom.document.title` | A document fetched: the root of a trace of its own, linked to its space's or project's span; an error when the fetch fails |
| `GET` | client | `http.request.method`, `server.address`, `server.port`, `url.full`, `http.response.status_code`, `error.type` | Each request, by the HTTP conventions, until its answer's headers; an error from status 400 |

## Instruments

| Instrument | Kind | Unit | Attributes | What |
|---|---|---|---|---|
| `http.client.request.duration` | histogram | `s` | `http.request.method`, `server.address`, `server.port`, `http.response.status_code`, `error.type` | Each request, by the HTTP conventions |
| `aom.download.documents` | counter | `{document}` | `aom.outcome` | The documents fetched, `fetched` or `failed` |
| `aom.download.files` | counter | `{file}` | `aom.outcome` | The attached files, `downloaded`, `failed` or `skipped` |
| `aom.download.bytes` | counter | `By` | | The bytes of the files downloaded |
