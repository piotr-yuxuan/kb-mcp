# Data layout

What each part of the program writes and reads under the data directory, so that the
fetch (plan 004), the mirror (005) and search (006) can be built apart.
Where this file and the code disagree, the code named here is right and this file is
fixed.

## The data directory

`<data>` is the setting `data_dir`, by default `~/kb-mcp`. It is never
under a synchronised folder (iCloud, `~/Library/CloudStorage`, Dropbox, OneDrive, Google
Drive, `~/Desktop`, `~/Documents`) and never inside a git working tree. Settings come
from `config.app.settings.load_settings`, which merges the settings file, the
environment and the flags given, then resolves the data directory and each of the places
below that the program writes (links followed, `..` removed), judges each resolved path
with names compared regardless of case, and raises `UnsafeDataDirError` when one is
refused; `aliases.toml`, which the user alone writes, is not judged. Links deeper
inside those places are not followed. Every command loads its settings that way, in its
entry; `config.domain.settings.settings_of`, which builds them from the layers, checks
no location and is not for commands.

| Path | `Settings` | Written by | Read by |
|---|---|---|---|
| `<data>/raw/` | `raw` | `fetch` (004) | `prepare` (005) |
| `<data>/docs/` | `docs` | `prepare` (005) | agents, and `index` (006); `embed`, for the files' digests alone (035) |
| `<data>/conversions.sqlite` | `conversions` | `prepare` (039) | `prepare` (039) |
| `<data>/index.sqlite` | `index` | `index` (006), `embed` (031) | the MCP server (006), `embed`'s prune (023), `index` and `embed`, which update it (035) |
| `<data>/index.sqlite.lock` | `index`, by `vector_cache.lock_of` | `index`, `embed` (035) | `index`, `embed` (035), [below](#updates) |
| `<data>/aliases.toml` | `aliases` | the user (043) | `index` (043), [below](#the-alias-file) |
| `<data>/vectors.sqlite` | `vectors` | `embed`, `eval`, `eval-rerank` (011) | `embed`, `eval`, `eval-rerank` (011) |
| `<data>/vectors.sqlite.lock` | `vectors`, by `vector_cache.lock_of` | `embed`, `eval`, `eval-rerank` (023) | `embed`, `eval`, `eval-rerank` (023) |
| `<data>/eval/` | `evaluations` | the user, `eval`, `eval-rerank` (011) | `eval`, `eval-rerank` (011); its indexes, `embed` (023) |
| `<data>/session/` | `session` | `login`, a `fetch` whose site renews its cookies (004) | a run signed in by the saved session (004, 015) |
| `<data>/runs/` | `runs` | `fetch` (004) | the user |

No code builds these paths otherwise.

## The log folder

Outside the data directory, each run but `completion`'s, unless it is refused or
declined before it starts, writes one file of JSON lines into the setting `logs.dir`,
by default the user's log folder as platformdirs places it:
`~/Library/Logs/kb-mcp` on macOS,
`$XDG_STATE_HOME/kb-mcp/log` on Linux. `load_settings` resolves and
judges it as it does the data directory, and names `logs.dir` when it refuses it.
`observability.adapters.logs.log_file` alone writes there: one file a run,
`<command>-<start>-<pid>.jsonl`, 0600, in a folder that it makes 0700, and it removes
the files of that pattern, named after any of the program's commands, whose run
started more than 30 days before. The program reads none back. [The telemetry
reference](telemetry/README.md) gives the file's fields.

## The ontology, and where details of the site live

The site's responses and its HTML change without notice. So that a change stays local:

- **One vocabulary.** [The concepts](concepts.md) define each word; this bullet says
  which module holds which record. `sources.atlassian.fetch.domain.content` holds what
  the fetch of Confluence and Jira stores and their prepare reads: `Space`, `Folder`,
  `Page` and `BlogPost` (both `ConfluenceDocument`), `Issue`, `Attachment` (an
  [attachment](concepts.md#document)), `Comment`, `SiteUser` (a site user, whose account id is a
  mention's [identity](concepts.md#person)), and `Snapshot` (a [snapshot](concepts.md#snapshot),
  with its rendered body). `Listed` is what a [listing](concepts.md#scope) says of a
  document (its type, id, revision, update time and Confluence version), read apart from
  the rest of the entry, so that an entry whose other fields have changed still lets the
  document be fetched. `mirror.domain.mirror.FrontMatter` holds what the mirror says of
  each [document](concepts.md#document). A fetched document knows where it is stored
  (`source`, `resource_type`) and names its state (`revision`). Every layer above the adapters
  works with these types alone.
- **One module per representation.** `sources.atlassian.fetch.adapters.confluence_v2`
  and `sources.atlassian.fetch.adapters.jira_v3` hold all that the code knows of those
  JSON responses: field names, which response holds what, and the file names a snapshot
  uses.
  The API paths, query parameters and paging that 004 needs go into the same modules.
  `mirror.adapters.markdown` alone writes and reads front matter. No other code indexes
  into a response or a front matter.
- **Strict reading.** Adapters read through `kernel.fields.Fields`. Every field must be
  present: a missing field, a wrong type or a time without an offset raises
  `RepresentationError` with the field's path, such as
  `document.json.version.number: expected an integer`. The `optional_` readers also
  accept null, and accept absence only where the documented response may leave the field
  out (labels in a listing, an issue's `parent`). A value that a domain type refuses
  (`kernel.names.RefusedError`) is reported the same way, through `Fields.refusals`,
  as `page: id: does not match <rule>`. Messages never hold the value, so reports can
  print them.
- **Raw first.** The raw store keeps responses exactly as received, reading only what
  names their folder. A response whose other fields have changed is therefore kept; it
  reads as `Unreadable` until its adapter is fixed, and then `prepare` reads it again
  without fetching anything.
- **HTML likewise.** The site's markup (class names, data attributes, macro names) is
  known to one module of 005, as named constants. Markup it does not know becomes a
  visible placeholder naming the construct, not an error.
- **Ids are checked by the domain.** The domain types refuse an id or a space id that is
  not one safe path part (`[A-Za-z0-9_-]+`), a space key, project key or issue key that
  does not look like one, and a download or web page that is not a path on the site.

## The raw store

Owned by `sources.atlassian.fetch.adapters.raw_store.RawStore`; nothing else reads or
writes under `<data>/raw/`. One run at a time writes, inside `RawStore.writing()`, which
holds a lock on `<data>/raw/.lock` and raises `StoreBusyError` when another run holds
it; every method that writes refuses to run outside it.

### Snapshots

A [snapshot](concepts.md#snapshot) lies at:

```
<data>/raw/<source>/<resource type>/<id>/<revision>/<file>.json
```

- `source` and `resource_type`: `confluence/pages`, `confluence/blogposts`, `jira/issues`, the
  `source` and `resource_type` of `Page`, `BlogPost` and `Issue`.
- `id`: the content id (Confluence) or the issue id (Jira, which stays when the key
  changes).
- `revision`: the version number padded to six digits for Confluence (`000003`), the
  update time in UTC to the microsecond for Jira (`20261020T213758.027000Z`). Names sort
  as text in the order of revisions; the newest snapshot is the last name.
- A snapshot is written into a hidden folder and renamed into place: it is complete or
  absent. Its responses are never written again. Only names the store writes are read:
  ids, revisions and response files that match their rules. Hidden leftovers of a crash,
  Finder's `.DS_Store`, AppleDouble `._` files and copies are skipped.

Files of a Confluence snapshot, named by constants of
`sources.atlassian.fetch.adapters.confluence_v2`, both GETs pinned to the version the
listing gave (`version=N`):

| File | Content |
|---|---|
| `document.json` (`DOCUMENT`) | `GET /wiki/api/v2/{pages,blogposts}/{id}?version=N&body-format=storage&include-labels=true` |
| `view.json` (`VIEW`) | `GET /wiki/api/v2/{pages,blogposts}/{id}?version=N&body-format=view` |
| `attachments.json` (`ATTACHMENTS`) | the `results` of every page of `GET /wiki/api/v2/{pages,blogposts}/{id}/attachments`, as one list |

`confluence_v2.identity` refuses a view of another page or version than the document,
so a page edited between the two GETs is never stored as one snapshot.

Files of a Jira snapshot, named by constants of
`sources.atlassian.fetch.adapters.jira_v3`:

| File | Content |
|---|---|
| `issue.json` (`ISSUE`) | `GET /rest/api/3/issue/{id}?expand=renderedFields` |
| `comments.json` (`COMMENTS`) | the `comments` of every page of `GET /rest/api/3/issue/{id}/comment?expand=renderedBody`, as one list |

Every snapshot also has the store's own record, `store.json` (`raw_store.RECORD`), which
only the store reads and writes:

```json
{"fetched_at": "2026-10-22T08:15:00Z", "blobs": [{"attachment": "att196895", "sha256": "<digest>"}]}
```

The store's interface for snapshots:

- `put(document_class, responses, fetched_at, blobs)`, with `document_class` one of `Page`, `BlogPost` and
  `Issue`, refuses a snapshot without one of the type's files (above), reads only the
  id and the revision (the type's `identity`), stores the responses as received, and
  returns the folder. `blobs` maps attachment ids to digests
  of files already stored with `put_blob`: files first, snapshot last, so a record never
  names a missing file. For a revision stored already, `put` keeps the responses and
  records the new blobs.
- `add_blobs(document, blobs)` records files downloaded later, such as on a retry,
  replacing the record alone, whole. It, `has` and `read` take a `FetchedDocument` or a
  `Listed`.
- `has(document)`; `read(document)`, which returns a `StoredSnapshot` or raises one of
  `raw_store.UNREADABLE` (`RepresentationError` for a refused field, another
  `ValueError` or an `OSError` for a damaged file); and `latest(document_class)`, which yields
  the newest snapshot of each document of its type as a `StoredSnapshot`, or as an `Unreadable`
  (where it is, and the refused field's path or the error's class) when it cannot be
  read. The others still follow.
- `StoredSnapshot` is the snapshot read into the domain (`Snapshot`), its folder, `fetched_at`
  and `blobs`, the files of its own attachments only. An attachment absent from `blobs`
  was not downloaded: a media type not kept, over the size cap, or a failed download.
- `responses(folder)` gives the responses as received, for adapters to read what the
  domain does not yet carry (a macro's parameters in the storage body, say).

Known limits, for a later plan: a change that makes no new version (an attachment added
without an edit, labels changed, a page archived, a comment) leaves the stored snapshot
as it was, as does an edit of a page that this page includes; the mirror takes a page's
status from the space's listing, which is fresher; labels beyond the first page that
`include-labels` returns are not seen.

Known faults, which no check guards: **a store that cannot be read reads as an empty
one.** `prepare` keeps the files that it builds and, when it finds no problem, removes
every other file of its source. A raw store that is missing, a regular file, a dangling
link or unreadable yields no snapshot and no problem, so `prepare` removes every file of
the Confluence and Jira sources from the mirror, with their attached files and their
conversions, and exits 0; the next `index` then drops their documents. The work log
alike: a folder that lists no file removes every work-log file, and a journal
(`todo.org`) that is missing, not a regular file or empty removes the documents drawn
from it. Check that `raw/` and the work log's folder are in place before a `prepare`;
`kb-mcp fetch`, with a `--since` that reaches back far enough, fills the raw store
again.

**Some broken files end in a traceback, not a refusal.** A damaged vector cache ends
`embed` and `eval`; an attached file missing from the raw store ends `prepare`; one
source's exception ends a `fetch` or `prepare` of several sources, the other sources'
rows unreported; and a golden file that is not UTF-8 ends `eval`. Each traceback names
the file, but it reads as a bug would.

### A space's listings, and users

Each run that fetches a space replaces that space's listings, each as received, every
result of every page of each list:

```
<data>/raw/confluence/spaces/<space id>/space.json      the space, from GET /wiki/api/v2/spaces?keys=KEY
<data>/raw/confluence/spaces/<space id>/pages.json      every page, from GET /wiki/api/v2/spaces/{id}/pages, without bodies
<data>/raw/confluence/spaces/<space id>/blogposts.json  every blog post, likewise
<data>/raw/confluence/spaces/<space id>/folders.json    every folder that is an ancestor of a listed page, from GET /wiki/api/v2/folders/{id}
<data>/raw/confluence/users.json                        every author seen, from GET /wiki/rest/api/user/bulk
```

`put_space(space, pages, blog_posts, folders, listed_at=...)` replaces one space's
listings, each file whole, one after another, and records in `listed_at.json` when they
were listed (`listed_at(space_id)`); other spaces' are kept. Of each listing entry it
reads only the space's id, and of each user only the account id. `put_users(users)` merges users into those kept, by account id, so the
newest name wins. They are read, each entry by its adapter, with `spaces()`,
`listed(space_id, Page | BlogPost)`, `folders(space_id)` and `users()`; an entry that its
adapter refuses comes back as an `Unreadable` at its index, and the others are read.

Listings give 005 the whole tree, titles and breadcrumbs, even of pages whose bodies are
outside the period fetched, folders included (`Page.parent_type` says whether a parent
is a page or a folder), and the names of Confluence authors, whom v2 gives by account id
only.

### Files

Attached files: `<data>/raw/blobs/<sha256[:2]>/<sha256>`, written once, by
`put_blob(data)`; `blob(digest)` gives the path.

### Coverage and tombstones

Two more of the store's own records, each replaced whole:

- `<data>/raw/coverage.json`, read by `coverage()` and written by `put_coverage()`: for
  each target (a space key or a project key,
  `sources.atlassian.fetch.domain.coverage.Target`), the one period over which every
  document updated is stored (`sources.atlassian.fetch.domain.coverage.Coverage`), and
  `"exact": true` on a project's entry written since plan 034. A run that listed a
  target whole joins its fetch window to that period when the two overlap or touch. A space's
  period ends at the fetch window's end whatever failed, since a run without `--since` starts
  at its covered start and asks again for whatever failed inside. A project's ends at
  the update time of its earliest document found and not stored whole (a fetch failed, a
  snapshot that the adapter refuses, a kept file failed, a stored snapshot unreadable),
  even below the old end, else at the fetch window's end; a search entry that the adapter
  refuses leaves it as it was, and a failure at its very start makes it inexact. A run
  without `--since` searches an exact project from a day before its covered end, and an
  entry without `exact` from its covered start, which replaces it with an exact one.
  `exact` on a space's entry is read as false. Versions before plan 034 read the record,
  and ignore `exact`.
- `<data>/raw/tombstones.json`, read by `tombstones()` and written by
  `put_tombstones()`: each Confluence document absent from its space's listing
  (`sources.atlassian.fetch.domain.deletions.Tombstone`), pending until a probe answers,
  then dated by its first answer of gone (404, trashed, or moved to a space the store
  does not keep), and confirmed by a second, at least an hour later. A document found in
  a kept space whose stored listing names it has moved, and loses its tombstone, as does
  one listed again; one found in a kept space whose listing does not name it goes back
  to pending. The absent are found from the last listing read by id alone
  (`listed_ids(space_id, document_class)`), so that an entry the adapter would refuse is still
  followed, and the ids that have a snapshot (`stored_ids(document_class)`); the record is written
  before the space's listing is replaced, so that no absent document is lost to a run
  that stops, and they are probed once every space of the run is listed. A fetch of
  projects neither reads nor rewrites the record.

## Run reports

Owned by the fetch of Confluence and Jira, which `fetch` runs (004):
`<data>/runs/<UTC time as %Y%m%dT%H%M%SZ>-<source>.json`, one for each source fetched,
`confluence` or `jira`, since two fetches can start within a second (030), in the format
004's plan defines. A run report holds counts and refused fields' paths, never content,
and names no target. No code reads one back. Its counts of documents depend on whether
`--since` was given (034): with it, `<source> <resource type>: in the period` and `<source> <resource type>: already
stored`; without, `<source> <resource type>: new or changed since the last fetch`; `listed` and `fetched` either way.

## The Markdown mirror

Each source writes under a folder of its own name, through the mirror's writer,
`mirror.adapters.mirror_files.write_changed`, and removes only the files that its `owned` module
finds there (030):

| Folder | Owned by | Removed by |
|---|---|---|
| `confluence/` | Confluence's prepare (005) | `sources.atlassian.prepare.adapters.owned.owned` |
| `jira/` | Jira's prepare (005) | the same |
| `assets/` | Confluence's and Jira's together: each writes the files of its own documents | `sources.atlassian.prepare.adapters.owned.attached`, a file that no placed document of either wants and no document file of either links (`unlinked`), unless a problem was found, of either source |
| `worklog/` | the work log's prepare (017, [below](#the-work-log)) | `sources.worklog.prepare.adapters.owned.worklog_owned` |
| `<name>/` | any other source: `<name>` is its declaration's, which the registry's rule keeps off `assets` | its own |

A source that attaches files keeps them under `<name>/_assets/`, in its own folder, so that
no other source removes them, and under a name beginning with `_`, which keeps them out of
the documents. Confluence's and Jira's parts are derived from the raw store and the setting
`accounts.atlassian.site` alone, so they can be rebuilt without network, byte for byte:
nothing in them depends on when they were prepared.

```
<data>/docs/confluence/<SPACE>/<id>-<slug>.md        a page
<data>/docs/confluence/<SPACE>/blog/<id>-<slug>.md   a blog post
<data>/docs/confluence/<SPACE>/_tree.md              the space's tree
<data>/docs/jira/<PROJECT>/<KEY>.md                  an issue
<data>/docs/assets/<sha256>.<ext>                    an attached file
<data>/docs/worklog/entries/<id>-<slug>.md           a work-log entry
<data>/docs/worklog/days/<id>.md                     a work-log day
<data>/docs/worklog/meetings/<id>.md                 a work-log meeting
<data>/docs/worklog/transcripts/<id>-<slug>.md       a work-log transcript
```

- The documents are exactly the files that `mirror.adapters.markdown.documents(docs)`
  yields, sorted by path: every `.md` file under `docs/`, but those under `assets/`, where
  an attached `x.md` is an asset, and those with a name beginning with `_` or `.` on their
  path (030). `_tree.md` has no front matter. A stray `.md` file is read too, and the index
  reports it as a file without front matter.
- `<SPACE>` is the space key, `<PROJECT>` the project key, `<KEY>` the issue key.
- `<slug>`: the title decomposed (Unicode NFKD) and lowered, its combining marks dropped
  (`Crème` gives `creme`), keeping ASCII letters and digits; every run of other
  characters becomes one `-`; leading and trailing `-` are removed; it is cut at 60
  characters, and a `-` left at the cut is removed. An empty slug leaves `<id>.md`, as
  does a work-log day or meeting, whose id holds its date or its title's slug already
  (`kernel.names.WORKLOG_TYPES`, by `named_by_id`). When a title changes, the file
  is renamed and the old name removed.
- `<ext>`: the attachment file name's extension in lower case when it matches
  `[a-z0-9]{1,8}`, otherwise none. Links from documents to assets are relative.
- `_tree.md`: one nested list item per page and folder of the listings, linking the
  page's file, or naming the page as "not yet mirrored" when its body was not
  downloaded.

Each document starts with front matter written by `mirror.adapters.markdown.dump` and
read by `mirror.adapters.markdown.load`, from a `mirror.domain.mirror.FrontMatter`;
nothing else writes or reads it. Its keys come in this order, all always present (`null`
when unknown or not applicable). `FrontMatter` checks what every source shares, and so
does `load`: `source` a source's name, `type` a lower-case word, `id` one safe path part,
`revision` a token, each key its own rule when it is set. What a source fills is checked
by the code that builds its front matter
(`sources.atlassian.prepare.domain.catalogue.AtlassianFrontMatter`,
`sources.worklog.prepare.domain.worklog.WorklogFrontMatter`): a key that one Atlassian
source alone has is `null` for the other and never for its own, and the work log fills
none of them. Every text is one line, with no line break of any kind;
times are in UTC, written as quoted strings to the second; strings that YAML 1.1 could
read as another type (`'000003'`, `'Yes'`) are quoted; `load` refuses any other key,
order or type, by name.

| Key | Type | Value |
|---|---|---|
| `source` | string | the source's name: `confluence`, `jira` or `worklog` today |
| `type` | string | `page` or `blogpost` (Confluence), `issue` (Jira), `entry`, `day`, `meeting` or `transcript` (work log) |
| `id` | string | the content id or issue id; a work-log document's, [below](#the-work-log) |
| `key` | string or null | the issue key; `null` for Confluence |
| `title` | string | the title |
| `space` | string or null | the space key; `null` for Jira |
| `project` | string or null | the project key; `null` for Confluence |
| `status` | string | as the site names it; a work-log entry's, day's or meeting's keyword, else `current`, as a transcript's |
| `issue_type` | string or null | the issue type, such as `Bug`; `null` for Confluence |
| `labels` | list of strings | the labels, `[]` when none; a work-log document's tags, its file's `#+FILETAGS`, and `ARCHIVE` when archived |
| `people` | list of mappings | each person by role, one line each, [below](#people); `[]` when none |
| `links` | list of mappings | each link to another document of the mirror, by relation, one line each, [below](#links); `[]` when none |
| `created`, `updated` | string | ISO 8601 times in UTC, such as `'2026-10-20T21:52:41Z'`; a work-log document's, [below](#the-work-log) |
| `version` | integer or null | the Confluence version number; `null` for Jira |
| `revision` | string | the raw store revision that the file was written from; a work-log document's, 16 hex digits, [below](#the-work-log) |
| `url` | string or null | the absolute address of the web page: the setting `accounts.atlassian.site` and `FetchedDocument.site_path`; `null` when no site is set, and for the work log |
| `breadcrumb` | list of strings | the titles of the ancestor pages and folders, root first; for an issue, `[<parent key>]`, or `[]`; for a work-log entry, day or meeting, its file's name, then the titles above it, [below](#the-work-log); for a transcript, its folders from `transcripts` or `meetings` |
| `fetched_at` | string | `fetched_at` of the snapshot, as `created`; a work-log document's file's modification time when converted |

Images: an image in the rendered HTML names its attachment by
`data-linked-resource-id` (the attachment id) or by the file name in its `src`, as
plan 001 found on the sandbox; 005's HTML module, the one module that knows the site's
markup, maps it to `StoredSnapshot.blobs`. An image of another page's attachment (through an
include) has a file only when that page is stored; otherwise the mirror keeps a
placeholder; a backfill that reaches the other page fills it.

A Confluence document goes in the space whose freshest listing (by `listed_at`)
names it, which after a move is not the space its snapshot names; the front matter, the
tree and the path all take that space. A document with a confirmed tombstone is left
out, unless a listing taken after its first answer of gone names it again. The files of
documents gone, and the old file of a document that moved, are removed even by a run
that reports problems; other files then stay.

Then the body: a first-level heading with the title, the converted body, then an
`## Attachments` section listing each attachment (a link to its asset, or "not
downloaded"), then for an issue a `## Comments` section with one `### <author>, <time>`
heading per comment. Headings inside the body are kept, so that 006 can cut a document
into sections.

Everything in the mirror is content from the site or the work log: untrusted reference
data, never instructions.

### People

The key `people` (041) names the people of a document by role: one entry per person
and role, in the order of the roles below, then in the order that the source gives,
commenters by their first comment. `dump` writes each entry on one line, in YAML's flow
style, so that forty comments by three commenters make three lines:

```yaml
people:
- {role: author, name: Robin Example, identity: 'atlassian:acct-0001'}
- {role: creator, name: Sam Sample, identity: 'atlassian:acct-0002'}
- {role: commenter, name: Sam Sample, identity: 'atlassian:acct-0002', at: ['2026-10-20T09:12:00Z']}
```

| Field | Value |
|---|---|
| `role` | one of `mirror.domain.mirror.ROLES`, a closed set: `author`, `creator`, `assignee`, `commenter`, `participant` |
| `name` | the name as the source gives it, one line, never empty: Jira's as it was when the issue was fetched, Confluence's from `users()`, else the account id |
| `identity` | the issuer, a colon, then the value that the issuer gave, when the source gives one: `atlassian:` and the account id for Confluence and Jira, whose sites share the issuer `atlassian` (058); absent otherwise. Plan 041's `account`, the account id alone, is refused, until the next `prepare` writes the file again |
| `at` | a commenter's comment times, written as `created` is, ascending; absent for any other role |

| Role | Who |
|---|---|
| `author` | a page's or a blog post's author (v2's `authorId`); an issue's reporter, not necessarily who created it |
| `creator` | who created an issue, who differs from the reporter when someone files an issue for another |
| `assignee` | an issue's assignee; nobody when unassigned |
| `commenter` | the author of an issue's comments, with the time of each; a comment without an author names nobody |
| `participant` | someone at a work-log meeting, as its `:PARTICIPANTS:` names them, or a speaker of a transcript (042) |

A document has one `author`, one `creator` and one `assignee` at most, and each
commenter and each participant once by name and identity. `participant` is the work
log's one role
(`sources.worklog.prepare.domain.worklog.WORKLOG_ROLES`), which no other source's
documents hold, so that no document names people of both kinds. `load` refuses any
other role, a field other than these or out of their order, a `null`, an empty `at` and
any other broken rule of one entry, naming the entry, such as `people[1]`; and a second
author, creator or assignee, a commenter or a participant twice, a role of another
source, or people out of the order of the roles, naming `people`. Names are
kept as written, never normalised, merged or masked: a colleague renamed between two
fetches appears under two names, with one identity, which the index alone joins into
one person ([persons](#persons)). `FrontMatter.author`,
`FrontMatter.creator` and `FrontMatter.assignee` name the one person of that role, or
nobody.

Names, and the identities beside them, are personal data, kept wherever the content
is:

- `<data>/raw/`, the responses as the site gave them: an issue's reporter, creator,
  assignee and comments' authors, by name and account id, in `issue.json` and
  `comments.json`; Confluence's authors by account id, named in `users.json`; and a
  person's email address wherever the site gives one, which the adapters leave behind;
- `<data>/docs/`: `people`, by name and identity; each comment's heading, by name;
  and whatever a body says;
- `<data>/conversions.sqlite`: the bodies' Markdown, the comments' headings in it;
- `<data>/index.sqlite`, and each index under `<data>/eval/indexes/`: the column and
  the table `people`, by name and identity, and the bodies' words; the tables
  `persons` and `person_names`, each person's names and their keys, and its id, a digest
  of an identity or of a name's key ([persons](#persons));
- `<data>/aliases.toml`, the user's own: names as the sources write them, and the
  persons they mean;
- the texts sent to the embedding endpoint, on this machine unless a run is given
  `--allow-remote-embeddings`, and to the reranking server when it is on, which are
  chunks of the bodies; `<data>/vectors.sqlite` keeps vectors under a digest, never a
  text;
- the log folder, for 30 days: `serve.call` gives each tool call's arguments at DEBUG,
  a name given to a filter or in a query among them; `index.person_ambiguous` and
  `index.alias_unused`, at WARNING, the names that the join could not give one person
  and the aliases that changed nothing, which stderr shows too, as does telemetry's
  endpoint when one is set;
- the folder given to `eval-agents` by `--out`, whose calls and answers hold what the
  server answered.

The MCP server serves no entry's `identity` (`mcp.app.responses.metadata`); the files
that agents may read hold it. It serves a person by name and id, never by identity,
although hashing a known identity gives its person's id. Deleting `<data>/docs/` and
`<data>/index.sqlite` removes the people from all that agents and the server read,
until the next `prepare` and `index` write them again from the raw store.
Persons live in the index alone: deleting `<data>/index.sqlite` removes them, until the
next `index` joins them again; `<data>/aliases.toml` stays until the user
deletes it. Deleting every copy is deleting the data directory, the log folder and the
folders of `eval-agents`, after which the mirror is fetched again, as from a first
run.

### Links

The key `links` (042) names the documents of the mirror that a document links to, by
relation: one entry per link, in the order that the source gives. `dump` writes each
entry on one line, in YAML's flow style, as it does a person:

```yaml
links:
- {relation: transcript, ref: t-20261027-meeting-1}
```

| Field | Value |
|---|---|
| `relation` | one of `mirror.domain.mirror.RELATIONS`, a closed set: `transcript`, `summary` |
| `ref` | the other document's ref, which `read` takes: its id, of the rule `kernel.names.IDENTIFIER`, `[A-Za-z0-9_-]+` |

| Relation | On | Ref |
|---|---|---|
| `transcript` | a work-log meeting | the transcript that its `:MEETING:` property names |
| `summary` | a work-log transcript | each meeting whose `:MEETING:` property names it |

The two relations are each other's reverse, and a link is written on both documents,
so that a program that reads one file finds the other without reading them all. A ref
always names a file: in a run where a document is not read, or its conversion fails,
and it has no file yet, the links to it are left out of the other documents' files,
until a run reads and converts it. A link added or removed while a work-log transcript
is not read is written on its meeting alone until a run reads the transcript, whose
last copy stays as it was; and while a problem holds removals back, the file of a
meeting or a transcript gone from the work log stays, naming documents that no longer
name it back.
`load` refuses any other relation, a field other than these or out of their order, a
`null` and a ref off its rule, naming the entry, such as `links[0]`; and a link to the
document itself, by its id or key, or a link given twice, naming `links`.

### Pandoc's conversions

Owned by `mirror.adapters.conversions`, which each prepare of Confluence and Jira opens
around the mirror, which converts through it (039):
`<data>/conversions.sqlite`, one table, `conversions`, a row per conversion, its `source`
the source whose prepare asked for it, `source` and `key` the primary key, and its
`markdown` what pandoc wrote; each prepare reads and prunes its own source's rows alone, so
that a text that both convert is a row of each, which neither prune takes from the other
(030). The key is the SHA-256, in hex, of
the UTF-8 bytes of the converter's name, a NUL, then the HTML given to pandoc; the name
is pandoc's version line, then its arguments, one a line
(`mirror.adapters.pandoc.Pandoc.html_converter`). A document's file and a space's tree
are one conversion each; the front matter, written after pandoc, is outside the key. A
conversion is committed as soon as it is made, in WAL mode with `synchronous = NORMAL`,
and a write waits up to 60 seconds for another run's. Once its files are written, a
prepare that reports no problem deletes every row of its source that it did not use; one
that reports a problem deletes none, as it removes none of its source's files.

The file changes no byte of the mirror while its rows are sound. Deleting it costs one
conversion of everything at the next run, and downloads nothing: the one way to start
afresh after installing a pandoc rebuilt under the same version line, which the key
cannot tell apart. The work log does not use the file: its `revision`
([below](#the-work-log)) already skips what has not changed.

As the file is opened, the run takes its write lock, then `PRAGMA integrity_check`
judges it, each index against its table: one that the check finds damaged, or that
SQLite finds damaged, no database, or of a format that it cannot read or may not write
(`SQLITE_CORRUPT` and `SQLITE_NOTADB` by their primary codes, `SQLITE_ERROR` and
`SQLITE_READONLY` exactly, since their extended codes, such as
`SQLITE_READONLY_DIRECTORY` for a folder that the run may not write, say nothing of the
file), or whose schema names columns other than `source`, `key` and `markdown`, as one
written before plan 030 does, or a name that is no longer UTF-8 text, is deleted with its
`-wal` and `-shm`, `prepare.cache_replaced` says why ([prepare's
telemetry](telemetry/prepare.md)), and an empty file takes its
place, so that the run goes on and converts everything. Damage that SQLite finds during
the run, `SQLITE_CORRUPT` or `SQLITE_NOTADB`, fails it, once the file is deleted, so
that the next run starts a new one. The check sees the file's structure, not the text of
each row: a row whose Markdown was damaged in place, such as by a file cut short within
its last page, is given as it is, or fails every run if its text no longer reads as
UTF-8. Deleting the file is the remedy for a mirror that looks wrong, or a run that
fails on the file.

A file locked past the wait, or in a folder that the run may not write, is not
replaced: the run fails, and the file stays. Nor does
the wait cover the file's creation: of two runs that create it at the same moment, one
may fail at once, seldom, as SQLite's switch of a new file to WAL mode does not wait.

### The work log

Owned by the work log's row of `prepare` (017), in `sources.worklog.prepare.app.prepare`:
`<data>/docs/worklog/`, from the folder that `sources.worklog.path` names, read in place
and never written. `sources.atlassian.prepare.adapters.owned.owned` and
`sources.worklog.prepare.adapters.owned.worklog_owned` tell each owner's files apart,
so that Confluence's and Jira's rows and the work log's never remove each other's. A run
that meets a problem (a file not read, a conversion that failed) removes none of its files
but the
old file of a document written again under another path, as an entry's or a transcript's
whose title changed, and a file not read holds back the files of what it builds: every
one for `todo.org` or `todo.org_archive`, on which days, meetings and entries' numbers
draw; for a transcript, its own; for a folder not listed, or the files past the bound,
the transcripts under it, but one whose id a file found takes, whose copy then replaces
it. Each problem says what it held back, as `worklog.problem` ([prepare's
telemetry](telemetry/prepare.md)), at each run until it is fixed.

- The **journal** (042) is a top-level heading of `todo.org` or `todo.org_archive` with
  a day among its children, whatever its title. A **day** is a heading at level 1, or 2
  below the journal, whose title is one active timestamp of a date alone, such as
  `<2026-10-28 Wed>`; a **meeting**, a child of a day with `:MEETING:` or
  `:PARTICIPANTS:` in its drawer. A top-level heading whose `:ARCHIVE_OLPATH:`, which
  org writes when it archives a subtree, names a day joins that day: a meeting archived
  alone is one of its meetings; anything else joins the meeting whose title, as org
  writes it there (each link its description, else its target; filled statistics
  cookies left out; a `/` within unescaped), is the path after the day or begins it
  before a `/`, the longest such title, if one meeting of the day alone has it; else
  the day.
- A **day** is one document per date: each of its headings, `todo.org` first, each
  meeting among their children cut to its heading line, then what joins it. Its id is
  `d-` and the date, `%Y%m%d`; its title, its first heading's, else the path's part.
- A **meeting** is its subtree, then what joins it. Its id is `m-`, its day's date, `-`
  and its title's slug, as a file name's, else the first 16 hex digits of the title's
  SHA-256; of one day and id, the meetings take `--2`, `--3` in the journal's order,
  `todo.org` first, then the archive, each in its file's order, never by a time or a
  file's name: two dashes, which no slug or digest holds, so that a numbered id is
  never another title's. Its people are the names that its `:PARTICIPANTS:` gives,
  split at commas outside brackets, each once and as written, in the role
  `participant`; its link
  `transcript` names the transcript whose file its `:MEETING:` names, from the folder of
  its org file, when that file is found, read or not, by the id that its path gives;
  else, for a file under `transcripts/` or `meetings/`, the transcript found of the id
  that the file's path gives, since a move under `archive/` keeps the id and org
  rewrites no link; that transcript's link `summary` names it back; a `:MEETING:` that
  reaches no file found links nothing, and
  `worklog.unlinked` counts it, a warning that holds no removal back ([prepare's
  telemetry](telemetry/prepare.md)). A day and a meeting begin at level 1, what joins them
  at level 2.
- An **entry** is any other top-level heading, a child of the journal that is no day, or
  the journal's own lines above its children when they hold text besides its planning
  line and property drawer, with what lies below it, beginning at level 1. Its id is
  `e-` and the first 16 hex digits of the SHA-256 of its `:ID:` property; else of its
  title, a line feed, and its `:CREATED:` property; else of its title alone. The title
  is the heading without keyword, priority, tags and statistics cookies. The second
  entry of one digest takes `-2`, the third `-3`, in file order, `todo.org` first.
- The breadcrumb of an entry, a day or a meeting is its file's name, then the titles
  above it: the journal's, then a meeting's day's; for a heading at the top of a file,
  its `:ARCHIVE_OLPATH:` instead. Its labels are its tags and those of the headings
  above it in its file, as org inherits them (not the `:ARCHIVE_ITAGS:` that archiving
  writes), its file's `#+FILETAGS` and `ARCHIVE` when it, or a heading above it, is
  archived; a day's are those of each of its headings, in order, else, when it has
  none, its first part's file's `#+FILETAGS` and `ARCHIVE`.
- A **transcript** is an `*.org` file under `transcripts/` or `meetings/`, where the
  user's meeting-notes tool saves the file that a meeting's `:MEETING:` names, both read
  by the same rules, their 20,000 files shared. Its id is `t-`, the day that begins its
  folder's name, else its own, as `%Y%m%d`, `-`, then `meeting-` for a file under
  `meetings/`, then its name without `.org` when the id so matches the rule below, else
  that name's slug, as a file name's, else the first 16 hex digits of the SHA-256 of its
  name: `notes on x.org` of 21 October is `t-20261021-notes-on-x`,
  `meetings/2026-10-27 Tue/1.org` is `t-20261027-meeting-1`. Without a day, it is `t-`
  and the digest of its name, `meeting-` before it under `meetings/`. No folder below
  the first is in an id, so a move under `archive/` keeps it. The name is a label
  alone, from which no number, order or time is read. Of two files of one id, the
  second in order of first folder, the folder that holds it, name, then path takes the
  digest of its whole path from the work log's root, written with a leading `/`, which
  no name has: a move under `archive/` with the folder that holds a file never hands
  its id to the other, unless both folders have one name. Each file found, read or
  not, takes its id from its path alone, so that a file not read moves no other's; that
  order decides nothing else.
- A transcript's people are its speakers, in the role `participant`, each once, in
  order of first speech: inside its `#+begin_quote` blocks when it has any, the notes
  outside them being the user's, else on any line, each line that holds an optional
  `[time]`, which dates nothing, and a blank, then a name of at most 64 characters that
  begins with a letter and holds no colon or bracket, then `: `, blanks before the
  colon not the name's; the name is none of `SCHEDULED`, `DEADLINE`, `CLOSED` and
  `CLOCK`.
- The rule of an id is its type's, `kernel.names.WORKLOG_TYPES`:
  `e-[0-9a-f]{16}(?:-[0-9]+)?` for an entry;
  `t-(?:[0-9]{8}-[A-Za-z0-9_-]{1,64}|[0-9a-f]{16})` for a transcript; `d-[0-9]{8}` for
  a day, its date; `m-[0-9]{8}-[a-z0-9-]{1,64}` for a meeting, its day's date and its
  title's slug. A front matter whose id has another type's shape is refused. The id
  names the file, with the title's slug for an entry or a transcript, as for a page,
  and alone for a day or a meeting.
- `revision` is the digest of pandoc's version and options, a NUL, and the org text
  that pandoc converts: a document whose revision has not changed is not converted
  again, and its file keeps its dates, but a day's, a meeting's and a dated
  transcript's, their day, found at each run, so that a file that held another date
  takes it without a conversion.
- `created` and `updated` are a day's date at midnight UTC; so are a meeting's, its
  day's, and a dated transcript's, the day that begins its folder's name or its own,
  whatever their lines, turns and timestamps hold, since the work log gives the day of a
  meeting and never its time; else the earliest and latest timestamps of the
  document's lines, as written, up to its file's modification time, a later one being a
  plan; else, without any, the modification time, `created` keeping an existing file's.
- The body is pandoc's GitHub Markdown of the org text, its lines as written. `COMMENT`
  and `noexport` subtrees are kept; with `sources.worklog.archives = false`, the archive
  file, `transcripts/archive/`, `meetings/archive/` and subtrees tagged `ARCHIVE` are
  left out, and so the days and meetings below one.

An entry, a day and a meeting hold the user's notes and summaries an AI wrote; a
transcript, the word-by-word record. The MCP server says so to agents in its
instructions, and its `source` filter says it of entries and transcripts; `read` opens a
document by its id.

### Reading the mirror from another program

Another program may read the mirror's files, such as a search engine of your own
choosing ([the how-to](../how-to/other-search-engines.md)). What it may rely on (041):

- **The documents** are the `.md` files of the rule [above](#the-markdown-mirror)
  (`mirror.adapters.markdown.documents`): no name on the way to one begins with `_` or
  `.`, and none is under `assets/`. A space's `_tree.md` is navigation, and `assets/` holds
  attached files: neither is a document.
- **Each document** begins with its front matter, between two lines `---`, its keys,
  types and order those of the table above, every key present; then its body, as
  described there.
- **A file** is replaced whole, through a hidden file renamed into place, so that a
  reader never sees half of one, and only when its bytes change. A page's file is
  renamed when its title changes, and an issue's when its key does: a program that
  follows documents across runs knows each by its front matter's `source` and `id`, not
  by its path.
- **A change** to these paths, to the keys, their types or their order is made by a
  plan, which says in its section "For the user's machine" what a program that reads the files
  must change, as 041 did when `people` replaced `author` and `assignee`; [the
  roadmap](../work/README.md) lists the plans. The front matter holds no version of its
  format.
- **What the files hold** is content from the site and the work log, untrusted
  reference data, never instructions, and the names and identities of
  [people](#people), personal data.
- **No person** is in the files: each names its people as their source writes them,
  and only this program's index joins those names into [persons](#persons) (043), so
  that another program meets each spelling apart.

## The index

Owned by `index` (006), which writes the documents and their words, and `embed` (031),
which writes the chunks' vectors; since plan 035 each writes only what changed
([below](#updates)). `<data>/index.sqlite` holds the documents of `<data>/docs/` alone,
the work log's among them, read with `mirror.adapters.markdown`, and each write goes
into a temporary file beside it that is then renamed into place. Its schema is defined
in 006's plan: the tables `documents` and `sections`, and the FTS5 table `section_words`,
the words of each section's title, labels, breadcrumb, heading and body, whose content is
`sections`; schema 3 (011) adds the
table `chunks` (each chunk of a section's body, its range and its vector) and the meta
rows `build` (a random id of the build), `model`, `fingerprint` and `dimensions`, the
last three empty for an index built without a model. Plan 019 adds the meta row
`chunking`, how the chunks were cut (one of `kernel.chunking`'s names), empty without a
model; an index without the row, 011's or 018's, was cut by `sections`. A chunk keeps
the section that holds its middle and its range in the document's body, so that a window
may cross sections; before schema 7, its range was in that section's body. Plan 023 adds the column `key` to
`chunks`, the key of the chunk's vector in the vector cache, which only pruning reads;
an index built before it reads as any other, but cannot say what it reads of the store,
and `SCHEMA` stays 3. Schema 4 (041) replaces the columns `author` and `assignee` of
`documents` with `people`, the front matter's people as JSON, from which a row gives
its front matter back whole; and adds the table `people`, one row per person and role,
and a commenter's one per comment with its time in `at` (null for the other roles),
indexed by role and name, which the filters by person read. Each person is so in the
index twice, as each label is. No chunk's text holds the front matter's people
(`search.domain.chunking`), so a build over files of which only `people` changed embeds
nothing new. Schema 5 (042) adds the column `links` to `documents`, the front matter's
links as JSON, as `labels` is, so that a row still gives its front matter back whole; a
participant is a row of the table `people`, without identity or time. No chunk's text
holds the links either. Schema 6 (043) joins the people into persons
([below](#persons)): the column `person` of `people`, and the tables `persons` and
`person_names`; no chunk's text holds a person. Plan 035 adds, at the same schema, as
023 did: the column `digest` of `documents`, the SHA-256 of its file's bytes; the table
`skipped`, each file of the mirror that the index could not take, by its `path`, with
its `digest`, null for a file that could not be read, and its `reason`, which holds no
content; and the meta rows `words`, the `search.domain.search.WORDS` of the code that
cut the sections, and `aliases`, the digest of what the alias file meant
(`search.domain.people.aliases_digest`). The server's readers ignore them; an index
built before them is served, rebuilt whole by the next `index`, and refused by `embed`
until then. Schema 7 (054) gives the tables their names now: `chunks` was `pieces`, its
column `end` was `stop`, and `section_words` was `chunks`; an index of 6 is rebuilt whole
by the next `index`, and `embed` then finds in the vector cache every vector that
`vectors.sqlite` still holds, no text embedded having changed. Schema 8 (058) names
identities: the column `account` of `people` becomes `identity`, written
`<issuer>:<value>` as the front matter writes it, and `person_names.joined` says
`identity` and `attendance` where it said `account` and `meeting`; an index of 7 is
rebuilt whole by the next `index`, after the `prepare` that writes each file's
`identity`, and `embed` then finds every vector in the vector cache, no chunk's text
holding a person. An index of another schema is refused, naming `prepare`, then
`index`, then `embed`: `prepare` writes the mirror again before `index` rebuilds the
index, as a new schema can come with a new format of the files; one of schema 6, whose
files this version reads as they are, naming `index`, then `embed`; one cut by a
chunking that this version
lacks, naming `index`, then `embed`. The MCP server opens it read-only, never writes,
and reopens it when the file is replaced; it searches by meaning with the model that the
index names, and only while the endpoint's fingerprint for it is the index's.

### Updates

`index` (`search.app.indexing.update_index`) reads the alias file first, then digests
every file of the mirror, the SHA-256 of its bytes, and compares them with what the
index holds (`search.adapters.sqlite_index.Reader.held`): each document's path and
digest, each file skipped, and the meta rows `words`, `aliases` and `build`. With no
file added, changed or gone, and the same alias file, it writes nothing,
`index.unchanged`, and the index keeps its bytes and its `build`. Else it reads the
files added or changed, and each file skipped again, as what kept it out may be gone,
before it takes any lock; then it writes a new file beside the index, named by
`sqlite_index.BUILDING` (`.index-*.sqlite`), which readers and the prune skip
(`search.adapters.sqlite_index.Writer.update`):

1. the index in place attached read-only, and every document copied whose file did not
   change, with its labels, people, sections and chunks, their rowids kept, so that each
   chunk still names its section; each row of `people` without its person;
2. the documents read added, their sections numbered after the largest copied, so that
   a document's sections stay consecutive; those gone left out;
3. FTS5's index rebuilt from the sections (`rebuild`, then `optimize`);
4. persons joined again over every document ([below](#persons));
5. the meta rows written, the model's copied, with a new `build` and `built_at`; the
   file committed, then renamed into place.

Of two files of one source and id, the first by the parts of its path, as `Path` sorts
them, not by its text, is held, and the other skipped, whichever of them came first.
Each file skipped is said at each run, whether it writes or not, and the run exits 1. A
whole rebuild copies nothing and reads every file: with no index that this version
reads, one without `words` or of another `words`, one damaged (a table of it that SQLite
finds corrupt, in the update's read or its copy), or on `index --rebuild`, `index.whole`
naming which. Its index has no chunks and no model's rows: the next `embed` takes their
vectors back from the vector cache.

`embed` (`search.app.indexing.fill_and_prune`) reads the index in one use: what it holds of the
mirror, the model it names, each document's front matter and body, and its chunks by
path, section number, range and key. It reads no file of the mirror but to digest it,
compares those digests with the index's, and when they differ warns,
`embed.mirror_changed`, naming `kb-mcp index`, then goes on as it would have; it never
reads the alias file. It stops, `index.not_built`, exit 1, before it opens the endpoint:
with no index, naming `kb-mcp index`, or one at another schema, naming `prepare` first;
with one without `words` or of another `words`, "run kb-mcp index first", as its chunks
would land on other sections; with one damaged, naming `kb-mcp index --rebuild`. It cuts
each document's body again by this code's sections and the run's chunking, keys each
chunk by the model's fingerprint, adds the chunks wanted that the index does not hold,
their vectors from the vector cache, else from the model, and removes those it holds
that none wants: a chunking or a model changed needs no rule of its own, a chunk of
another range or key being replaced and an identical one kept. Nothing to add or remove,
and the same model: nothing is written, `embed.unchanged`. Else a copy of the index, by
SQLite's backup, beside it, takes the chunks removed and added, each naming its section
by path and number, the model's meta rows and a new `build`, its `built_at` kept, and is
renamed into place (`search.adapters.sqlite_index.SqliteIndex.fill`). Between `index`
and `embed`, a document added or changed has no chunks: search finds it by its words,
not by its meaning, and `index` counts the documents awaiting vectors, those that the
index's chunking cuts some text from; a page of white space alone, or of a title alone
cut by sections, awaits none.

`<data>/index.sqlite.lock`, beside the index (`vector_cache.lock_of`), is the writers'
lock: `index` and `embed` take it exclusive by `flock` from their check that the index
is still the build they read until the rename, never while they read files or ask the
model. A run that finds it held says so, `index.lock_wait`, and gives up after a minute
(`conversions.WAIT_S`, which `vector_cache` imports), naming the lock; one that finds
the index written by another meanwhile starts again once, `index.restarted`, then stops. The file is never removed,
and `flock` releases it at a process's end, a kill included. The index stays in SQLite's
rollback journal, never in WAL mode, whose `-wal` file a rename would pair with the new
index. A build file that a kill leaves, `.index-*.sqlite`, is ignored, and never
removed.

### Persons

Once the files are read, each write of `index` joins the rows of `people` of every
document, copied or read, into persons (043, 058,
`search.adapters.sqlite_index.Writer.join`), by the first of the rules of [the
concepts](concepts.md#person) that answers (`search.domain.people.joined`, rules 2 to
4 its `RULES`):

1. a row with an identity is the identity's person, under each of its names, unless an
   alias of that identity names another person; two identities are one person only
   when an alias says so, even of one name;
2. a name without an identity whose key an alias holds goes to the person that the
   alias means ([below](#the-alias-file)), but for a participant whom rule 4 gives one
   other person;
3. one whose key is the key of a name of exactly one identity's person joins that
   person, but for a participant to whom rule 4 gives persons that do not hold that
   identity, which is ambiguous;
4. a participant whose key is the first word of the keys of the participants of the
   documents that its document's `summary` links name in its source joins their
   person, when they are one;
5. else, a person by name alone, shared by every name without an identity of its key.

A name's key (`search.domain.people.name_key`) is the name casefolded, decomposed by
Unicode NFKD without the combining marks of U+0300 to U+036F, casefolded again, its
runs of white space made one space, trimmed, and a trailing part in brackets dropped
when a name comes before it: `Hélène  Example` and `helene example` share one, and
`Kim (not in the header)` has `kim`. The join keeps that part, though
(`search.domain.people.Joining.compared_key`), however it is spaced, for the names of a
key that two parts or more tell apart, as a site or the user wrote them: `Alex (Ops)` and
`Alex (Sales)` are two persons, and a bare `Alex` is neither; a meeting's `Robin (Ops)`
is the identity named `Robin (Ops)`, not one named `Robin (Sales)`, and a bare `Robin`
could be either, so that rule 3 finds it among several identities. A name that rule 3
finds among several identities' persons, or among persons other than its summaries',
or rule 4 among several persons, is ambiguous: it goes by rule 5 to the person by name
of its key, which may be one of them, and the build warns of it, as
`index.person_ambiguous` ([index's telemetry](telemetry/index.md)); two identities of
one name are no warning. The join cannot tell a
note in brackets from a part that tells names apart: two notes of one name,
`Kim (not in the header)` and `Kim (late)`, part it too, each a person by name alone,
and the build warns of that name, under the first of them, when they are two persons
or more; an alias of the name to one of its spellings, such as `"Kim" = "Kim"`, joins
them. The same rows in any order give the same persons.

A person's id is `p-` and the first 16 hex digits of the SHA-256 of `account`, a line
feed and the identity, or of `name`, a line feed and the key by which the join compares
the name (`search.domain.people.person_id`): stable while what anchors the person
stays. An identity of the issuer `atlassian` is hashed by its value alone, the account
id, so that every id made before identities had an issuer stays; any other issuer's
whole, so that equal values of two issuers are two persons. Two identities that an
alias makes one keep the id of the one that it names. A second note on a name, which parts its annotated spellings, anchors
each of them anew: the bare name keeps the id, and an alias to it, or an id that an
agent kept, names fewer documents, as the build warns of that name. A person is served
by a name: an identity's, the name on its identities' most recently updated document;
a person by name alone's, the value of the first alias that made it, when that is a
name, else its most frequent spelling; ties go to the first row in the join's order, by
document, in the order of their paths' text whichever file was written last, then
role, name and identity, the rows of documents that link by `summary` last, so that
their summaries' persons are known. The join reads the `summary` links that name a
document of the same source, by its id, which links by `summary` itself to none, as a
file edited by hand may (`search.adapters.sqlite_index.SUMMARY_LINKS`); it refuses such
a chain from another caller, as a programming error.

| Table or column | Holds |
|---|---|
| `people.person` | each row's person, by id, filled before the build commits; indexed with the role, `(person, role)` |
| `persons` | each person: `id`, the primary key, and `name`, as served |
| `person_names` | each spelling of each person: `person`, `name` as the source writes it, `key`, and `joined`, how it joined, `identity`, `alias`, `attendance` or `name`; indexed by `key` |

The filters by person read them (`mcp.app.tools.who`): a value is a person's id, or a
name whose key one person holds in the filter's role, and `KEPT` keeps that person's
rows of `people` ([the tools](mcp-tools.md#search)). The join is whole at each write of
`index`, a copied document's rows joined again with the others: one identity fetched late
can make a work-log name ambiguous, so no person is patched document by document.
`embed` joins nothing.

### The alias file

`<data>/aliases.toml` (`Settings.aliases`) is the user's: the program never writes it.
`index` alone reads it, at the start of each run, before the mirror
(`search.adapters.aliases.read_aliases`, through `search.app.indexing.update_index`),
and the index records the digest of what it means, its meta row `aliases`; `embed` and
`serve` never do, and `eval` builds its indexes without aliases. Each line is a name
as some source writes it, or an identity as the front matter writes it, then the
person it means, by a name, an identity or a person's id, all TOML strings, an identity
quoted for its colon:

```toml
"Sam" = "Sam Sample"
"Robin" = "p-0123456789abcdef"
"atlassian:acct-0003" = "atlassian:acct-0002"
```

- No file is no alias.
- An alias of a name moves names without an identity alone (rule 2): an identity's
  names are its origin's. It means its name anywhere but for a participant whose
  document's summaries give it one other person: the participants that the user wrote
  for a meeting tell more. Its name compares by its key, without annotation, so that
  `"Alex"` moves `Alex (Ops)` and `Alex (Sales)` alike.
- An alias of an identity moves that identity's mentions to the person that it names
  (rule 1), which keeps its id: the third line above makes the two `Sam Sample`
  identities one person, of `acct-0002`'s id. It holds an identity only where a mention
  holds it; else it is taken for a name.
- A value that is a name means the one identity's person with a name of its key, else
  the person by name alone of its key; one that is an identity, that identity's own
  person; one that is a person's id, that person. Each must be a person that an
  identity or a name makes, not aliases or attendance alone: aliases are not chained,
  and an alias whose value's every mention another alias or attendance joins elsewhere
  names nobody.
- A file that is not UTF-8 TOML; a value that is a table or not a string; a name or
  a value of an empty key, such as white space or accents alone, holding a line break
  or longer than 200 characters; or two names of one key: the build stops before it
  reads the mirror, `index.not_built` naming the file and, but for a file that is not
  TOML, the alias; the index in place stays, and the run exits 1.
- An alias whose key no name without an identity holds, or whose value names nobody
  or several persons, changes nothing, and the build warns of it, as
  `index.alias_unused`. Neither warning changes the exit status.
- A change takes effect at the next `index`, which writes a new build for it alone,
  every document copied with its chunks and joined again; the next `embed` has nothing
  to write.

### Models and vectors

No model runs in this program (plan 018): `search.adapters.embedding` alone asks an
OpenAI-compatible endpoint, the setting `embedding_url` (by default Ollama's
`http://127.0.0.1:11434/v1`), and `search.adapters.reranking` alone a reranking server,
the setting `rerank.url` (by default `http://127.0.0.1:9931/v1`, plan 022). Both
connect through `search.adapters.model_api`, which refuses an address that is not a
literal loopback one by the kernel's rule (`kernel.endpoint`): for embeddings unless
the command is given `--allow-remote-embeddings`, for reranking always. Nothing that
the reranking server answers is stored. A model's fingerprint is the
SHA-256 of its name, the digest that Ollama lists for it (`/api/tags`, empty from a
server that lists none), its dimensions, its query and document prefixes, and the
adapter's format version. `<data>/vectors.sqlite` keeps the vectors embedded, keyed
by the SHA-256 of that fingerprint and the text, committed in batches; deleting it costs
no embedding at the next `embed` while the index holds its chunks, each with its vector,
but a full embedding of the mirror by the model once a whole rebuild of the index has
dropped them, and of each evaluation's chunks at its next `eval`; it downloads nothing.
A text that the endpoint refuses has no vector there, and is asked again at the next
`embed`.

After each `embed`, the store is pruned (plan 023) to the vectors that
`<data>/index.sqlite` and the indexes under `<data>/eval/indexes/` read, by the keys
their chunks record, and to those of the index that the `embed` wrote, should an `index`
have renamed another in place meanwhile: the files are the truth, so that deleting an
evaluation's index lets the next prune drop its vectors, and `eval --model M` keeps a
model's. A vector that no index on disk reads is deleted: an edited chunk's old text, a
deleted document's, a model replaced, a build interrupted before its index was renamed
in. The prune is held back, deleting nothing, when the index lacks a file of the mirror
or holds no document; when an index there cannot say which vectors it reads (built by
words alone, before plan 023 or at another schema, damaged, or not an index):
`eval` rebuilds those of the models and chunkings it is given, else delete them; and
when a folder there cannot be reached or listed, an entry below `<data>/eval/indexes/`
is a link, which is not followed, or `<data>/eval` is a dangling link, as to a disk
away: make it readable, or put what the link points to in its place. `embed`, from its
read of the vectors, and each build of `eval` hold `<data>/vectors.sqlite.lock` shared
by `flock` until their index is in place, and a prune takes it exclusive or is deferred
to the next `embed`. A store made from plan 023 on
gives the pages freed back to the file system (`auto_vacuum = INCREMENTAL`). One made
before is converted at its first prune, once the vectors that no index reads are
deleted: the mode set, then one `VACUUM`, which rewrites the vectors kept while the
prune holds the lock, and needs about their size free in SQLite's temporary folder
(`SQLITE_TMPDIR`, else `TMPDIR`, else `/var/tmp`) and as much again beside the store,
for its WAL. The result says so; a conversion that fails, for want of space, says why,
leaves the deletions, and the next prune tries again. An evaluation's index builds whole
through `search.app.indexing.build_index`, every file read, with no writers' lock, as
each of those files has one writer; a later index that reads the store does so too, and
so takes the store's lock, and adds its files to what the prune follows. Under
`<data>/eval/`, `indexes/<chunking>/<model>.sqlite` (each `/` and `:` of the name
written `_`) are the indexes that `eval` builds, one per model and chunking, and
`results/<UTC time>.json`
its numbers: the golden file's SHA-256, models, chunkings, measures of `search` and of
`ask`, costs, ranks and tests, by question id, never a question's text, and for each
model the chunking that plan 019's rule chooses. `results/<UTC time>-rerank.json` are
`eval-rerank`'s (plan 022): the golden file's SHA-256, the mode, the models, the
chunking, the ids that the reranking server lists, and the sample, its number of
questions and its seed, or `null` for every question; for each depth, 0 for the order
not reranked, the measures of `search` and of `ask` by group, the times, the tokens and
the ranks by question id, and for depth 0 Recall@N at each depth measured; then the
bar's verdicts and the depth it chooses, or `null` when the depths measured are not
the bar's. `eval-agents` writes into a directory
of its own, given by `--out`, never under `<data>/` unless placed there: its layout is
in [evaluating with agents](../how-to/evaluate-with-agents.md).
A `<data>/models/` folder left by plan 011 is read by nothing.

## The session

Owned by `login` (004). `<data>/session/` has mode `0700`; it holds the browser profile
of the sign-in window and the saved session cookies (mode `0600`). Agents are never
given access to it: only `<data>/docs/` is shared with them.

`sources.atlassian.fetch.adapters.sign_in` chooses how a run signs in (015): by an API
token when the setting `accounts.atlassian.api_token` is set, else by the saved session,
whose cookies a run writes back as the site renews them. A run signed in by a token reads and writes
nothing under `<data>/session/`, and keeps nothing of the token, which the environment
gives to each run and no file under `<data>` holds.
