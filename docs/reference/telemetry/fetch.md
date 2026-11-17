# fetch

What `fetch` records, besides what every command does ([README](README.md)). A run is one
trace: its root `fetch`, then a span of each source taken, `fetch.source`, in the
registry's order. Confluence's and Jira's each sign in and hold the raw store for itself:
a span for each of its spaces or projects listed, one for the probes of what their whole
reads no longer name, for Confluence one for the users, and the requests between. A work log's holds its copy store and a span
of its own, `worklog.read`. So a run gives `fetch.store_busy` once per source, naming it,
and `fetch.sign_in_needed` once per Atlassian source. Each document fetched is a trace of its own, `fetch.document`,
linked to the span of its space or project: Tempo drops a trace past 5 MB, which a run of
thousands of documents would pass. The files that a document already stored lacks are
fetched in the run's trace, in its space's or project's span.

## Events

| Event | Level | Fields | When |
|---|---|---|---|
| `fetch.listed` | info | `scope`, `listed`, `in_window`, `stored`, `to_fetch`, `start`, `reason` | A space is listed whole, or a project searched over its fetch window: how many documents it lists, how many are in its window, stored already and to fetch; where the window starts and why: `given` (`--since`), `since the last fetch`, `covered start` or `first fetch`. A project's whole read, every week, says nothing of its own |
| `fetch.document` | debug | `id`, `kind`, `title` | A document is fetched, and its snapshot read |
| `session.moved` | info | `host`, `session` | The session kept before sessions were a site's, `<data>/session/cookies.json` and its profile, moved into the site's folder, once, by a fetch that writes and signs in by the session |
| `session.not_moved` | warning | `host`, `session`, `reason` | That session stays where it is: its cookies are of no site that the settings name, or of several, or the site has a session of its own, said once a run by the first source of their site (none when that source signs in by an API token); or the move failed, said by each source that tried it |
| `fetch.document_failed` | warning | `id`, `kind`, `reason` | A document cannot be fetched: the run goes on, and exits 1 |
| `fetch.document_unread` | warning | `kind`, `reason` | A snapshot that its adapter refuses: stored as it came, without its files |
| `fetch.file_skipped` | info | `id`, `file_name`, `reason` | An attached file is not downloaded, by its media type or its size |
| `fetch.file_failed` | warning | `id`, `file_name`, `reason` | An attached file cannot be downloaded, or is not the size listed |
| `fetch.scope_failed` | warning | `scope` | A space or a project named cannot be listed, or a project cannot be read whole: then its search goes on, and its last whole read stays |
| `fetch.coverage` | info | `scope`, `outcome`, `reason` | A scope finished or skipped: its coverage `extended` to its fetch window's end, joined with it, or, for an inexact entry that the window starts at or before, replaced by it; a project's `capped` at the update time of its earliest document not stored whole; or `held` as it was, `reason` saying why: `entries refused` (a search entry that the adapter refuses), `after --until` (a catch-up that would start after it), `apart from what is covered` |
| `fetch.start` | info | `sources`, `dry_run` | The stage begins: the sources whose units it runs, in their order, and whether it only plans; in a resume, those not done |
| `fetch.source` | info | `source`, `ending` | A source's unit ended: `done`, `failed`, `sign in again` or, in a dry run, `not run` |
| `fetch.end` | info | `status`, `sources` | The stage ends: the exit status that its units' endings fold, and how each ended |
| `fetch.refused` | error | `source`, `reason` | What a source's light check of its settings refuses as its unit begins, such as a site not set or an API token without its email, by the settings that the run recorded, when the run takes it by default (named, the source refuses the run before it starts, `run.refused`, exit 2); or what a fetcher's preflight refuses then, such as a period, a store's record, of what answered as gone for Confluence's fetch alone, or a work log that is not a folder, by its setting, a problem by the source; or such a record damaged once the unit began (Jira's fetch reads it then, not in its preflight), or a work log's copy store that does not read, by its file and field: that source's unit fails alone, naming it, and the next units go on. Without `source`, a fetcher that does not load, naming the source and the path: the run stops before its first unit, exit 2 |
| `fetch.store_busy` | error | `source`, `store`, `hint` | Another run writes the raw store, or the work log's copy store: the source's fetch fails, exit 1 |
| `worklog.carried` | info | `documents`, `not_read` | A work log's copy store begins: the documents whose created and updated dates are carried over from its files of the mirror, with its source's as-of time, before the first read, and the files that did not read, each a problem of the unit by its path, which fails it |
| `worklog.read` | info | `entries`, `days`, `meetings`, `transcripts`, `html`, `problems` | The work log is read: its entries, days, meetings and transcripts, the HTML transcripts left out, the files not read |
| `worklog.fetched` | info | `documents`, `new`, `changed`, `gone`, `problems` | What the read found against the copy store: the documents read, those new or of another revision, those gone, which a fetch without a problem confirms at once, and the problems |
| `worklog.problem` | warning | `where`, `reason`, `held_back` | A file not read, by its path, never its content, and what keeps its last copy for it, once a run until it is fixed: `every document` for `todo.org`, its archive or the work log's folder itself; a transcript's id for a transcript, whose last copy, if it has one, stays; `the transcripts not read under it` for a folder, the bound's problem or an HTML file linking out, which a path does not tell apart. Or a file of the mirror that does not read as a copy store begins, by its path from the mirror, `nothing` held back: its dates, or its source's as-of time, are lost. Every other document is taken, but the unit fails |
| `worklog.same_id` | warning | `reason` | Two transcripts of one id: the second by the name of the folder that holds it, then by its own name, then in path order, is named by its whole path, both paths said. While the first is not read, a link to the id reaches the copy that the id last named, which may be the other file's |
| `worklog.unlinked` | warning | `meetings`, `first` | Meetings whose `:MEETING:` links no transcript found, read or not, once a run: how many, and the first one: by the file that its link names, from the work log's folder, when the link is in brackets or a path after `file:` or `./` and that file was not found, such as one in a folder other than `transcripts/` and `meetings/`; else by its id, for a path alone too, since any text reads as one. A link to a file found but not read is not counted: that file's `worklog.problem` names it. Never the link as written, which may be a meeting room's URL with its passcode. Each such meeting is kept without the link, and the unit neither fails nor holds a removal back |
| `worklog.nothing_removed` | warning | `problems` | A fetch with problems confirms no document gone, nor takes one that draws on a file not read, so that each last copy stays in the store: how many problems, each `worklog.problem` saying what it held back |
| `fetch.interrupted` | warning | `source` | Ctrl-C stopped the unit of this source, none once every unit ended: later units do not run, exit 130 |
| `fetch.sign_in_needed` | error | `source`, `hint` | The session or the token no longer opens the site for the source's fetch: exit 3 |
| `http.get` | debug | `url`, `status`, `error`, `seconds` | Each request, a redirect's included; the query shown on the site alone |
| `http.retry` | debug | `path`, `attempt`, `failure`, `wait_s` | A request retried after a throttling, gateway or transport failure |

`source` is a source's name, such as `confluence`, `jira` or `worklog`; `kind`,
`confluence pages`, `confluence blogposts` or `jira issues`; `scope`, as `space MFS` or
`project PRB`.

## Spans

| Span | Kind | Attributes | What |
|---|---|---|---|
| `fetch.source` | internal | `kb_mcp.source`, `kb_mcp.ending` | A source's unit: its source and how it ended, no ending on one that Ctrl-C stopped |
| `fetch.space` | internal | `kb_mcp.scope` | A space, by its key: listed, stored, its documents fetched; an error when it cannot be listed |
| `fetch.project` | internal | `kb_mcp.scope` | A project, by its key: read whole when due, searched, its issues fetched; an error when the search cannot be read |
| `fetch.probes` | internal | | The documents that the scopes' whole reads no longer name, probed |
| `fetch.users` | internal | | The authors' names, fetched and merged |
| `fetch.document` | internal | `kb_mcp.document.id`, `kb_mcp.document.kind`, `kb_mcp.document.title` | A document fetched: the root of a trace of its own, linked to its space's or project's span; an error when the fetch fails |
| `worklog.read` | internal | | The work log's folder listed, its files read and split into documents |
| `GET` | client | `http.request.method`, `server.address`, `server.port`, `url.full`, `http.response.status_code`, `error.type` | Each request, by the HTTP conventions, until its answer's headers; an error from status 400 |

## Instruments

| Instrument | Kind | Unit | Attributes | What |
|---|---|---|---|---|
| `http.client.request.duration` | histogram | `s` | `http.request.method`, `server.address`, `server.port`, `http.response.status_code`, `error.type` | Each request, by the HTTP conventions |
| `kb_mcp.fetch.documents` | counter | `{document}` | `kb_mcp.outcome` | The documents fetched, `fetched` or `failed` |
| `kb_mcp.fetch.files` | counter | `{file}` | `kb_mcp.outcome` | The attached files, `downloaded`, `failed` or `skipped` |
| `kb_mcp.fetch.bytes` | counter | `By` | | The bytes of the files downloaded |
