# Data layout

What each part of the program writes and reads under the data directory, so that the
download (plan 004), the Markdown mirror (005) and search (006) can be built apart.
Where this file and the code disagree, the code named here is right and this file is
fixed.

## The data directory

`<data>` is the setting `data_dir`, by default `~/atlassian-offline-mcp`. It is never
under a synchronised folder (iCloud, `~/Library/CloudStorage`, Dropbox, OneDrive, Google
Drive, `~/Desktop`, `~/Documents`) and never inside a git working tree. Settings come
from `config.app.settings.load_settings`, which merges the settings file, the
environment and the flags given, then resolves the data directory and each of the places
below (links followed, `..` removed), judges each resolved path with names compared
regardless of case, and raises `UnsafeDataDirError` when one is refused. Links deeper
inside those places are not followed. Every command loads its settings that way, in its
entry; `config.domain.settings.settings_of`, which builds them from the layers, checks
no location and is not for commands.

| Path | `Settings` | Written by | Read by |
|---|---|---|---|
| `<data>/raw/` | `raw` | `download` (004) | `mirror` (005) |
| `<data>/docs/` | `docs` | `mirror` (005), `sync` (017) | agents, and `index` (006), `sync` (017) |
| `<data>/index.sqlite` | `index` | `index` (006), `sync` (017) | the MCP server (006) |
| `<data>/vectors.sqlite` | `vectors` | `index`, `eval` (011), `sync` (017) | `index`, `eval` (011), `sync` (017) |
| `<data>/vectors.sqlite.lock` | `vectors`, by `vector_store.lock_of` | `index`, `eval`, `sync` (023) | `index`, `eval`, `sync` (023) |
| `<data>/eval/` | `evaluations` | the user, `eval` (011) | `eval` (011); its indexes, `index` and `sync` (023) |
| `<data>/session/` | `session` | `login` (004) | a run signed in by the saved session (004, 015) |
| `<data>/runs/` | `runs` | `download` (004) | the user, and `doctor` (004) |

No code builds these paths otherwise.

## The log folder

Outside the data directory, each run but `completion`'s, unless it is refused or
declined before it starts, writes one file of JSON lines into the setting `logs.dir`,
by default the user's log folder as platformdirs places it:
`~/Library/Logs/atlassian-offline-mcp` on macOS,
`$XDG_STATE_HOME/atlassian-offline-mcp/log` on Linux. `load_settings` resolves and
judges it as it does the data directory, and names `logs.dir` when it refuses it.
`observability.adapters.logs.log_file` alone writes there: one file a run,
`<command>-<start>-<pid>.jsonl`, 0600, in a folder that it makes 0700, and it removes
the files of that pattern, named after any of the program's commands, whose run
started more than 30 days before. The program reads none back. [The telemetry
reference](telemetry/README.md) gives the file's fields.

## The ontology, and where details of the site live

The site's responses and its HTML change without notice. So that a change stays local:

- **One vocabulary.** `kernel.content` names what the mirror holds: `Space`, `Folder`,
  `Page` and `BlogPost` (both `ConfluenceDocument`), `Issue`, `Attachment`, `Comment`,
  `Person`, and `Snapshot`, a document at one revision with its rendered body. `Listed`
  is what a listing says of a document (its type, id, revision, update time and
  Confluence version), read apart from the rest of the entry, so that an entry whose
  other fields have changed still lets the document be fetched.
  `mirror.domain.mirror.FrontMatter` names what the mirror says of each document. A
  document knows where it is stored (`source`, `kind`) and names its state (`revision`).
  Every layer above the adapters works with these types alone.
- **One module per representation.** `sources.atlassian.adapters.confluence_v2` and
  `sources.atlassian.adapters.jira_v3` hold all that the code knows of those JSON
  responses: field names, which response holds what, and the file names a snapshot uses.
  The API paths, query parameters and paging that 004 needs go into the same modules.
  `mirror.adapters.markdown` alone writes and reads front matter. No other code indexes
  into a response or a front matter.
- **Strict reading.** Adapters read through `kernel.fields.Fields`. Every field must be
  present: a missing field, a wrong type or a time without an offset raises
  `RepresentationError` with the field's path, such as
  `document.json.version.number: expected an integer`. The `optional_` readers also
  accept null, and accept absence only where the documented response may leave the field
  out (labels in a listing, an issue's `parent`). A value that a domain type refuses
  (`kernel.content.RefusedError`) is reported the same way, through `Fields.refusals`,
  as `page: id: does not match <rule>`. Messages never hold the value, so reports can
  print them.
- **Raw first.** The raw store keeps responses exactly as received, reading only what
  names their folder. A response whose other fields have changed is therefore kept; it
  reads as `Unreadable` until its adapter is fixed, and then `mirror` reads it again
  without fetching anything.
- **HTML likewise.** The site's markup (class names, data attributes, macro names) is
  known to one module of 005, as named constants. Markup it does not know becomes a
  visible placeholder naming the construct, not an error.
- **Ids are checked by the domain.** The domain types refuse an id or a space id that is
  not one safe path part (`[A-Za-z0-9_-]+`), a space key, project key or issue key that
  does not look like one, and a download or web page that is not a path on the site.

## The raw store

Owned by `sources.atlassian.adapters.raw_store.RawStore`; nothing else reads or writes
under `<data>/raw/`. One run at a time writes, inside `RawStore.writing()`, which holds
a lock on `<data>/raw/.lock` and raises `StoreBusyError` when another run holds it;
every method that writes refuses to run outside it.

### Snapshots

A snapshot is one document at one revision:

```
<data>/raw/<source>/<kind>/<id>/<revision>/<file>.json
```

- `source` and `kind`: `confluence/pages`, `confluence/blogposts`, `jira/issues`, the
  `source` and `kind` of `Page`, `BlogPost` and `Issue`.
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
`sources.atlassian.adapters.confluence_v2`, both GETs pinned to the version the listing
gave (`version=N`):

| File | Content |
|---|---|
| `document.json` (`DOCUMENT`) | `GET /wiki/api/v2/{pages,blogposts}/{id}?version=N&body-format=storage&include-labels=true` |
| `view.json` (`VIEW`) | `GET /wiki/api/v2/{pages,blogposts}/{id}?version=N&body-format=view` |
| `attachments.json` (`ATTACHMENTS`) | the `results` of every page of `GET /wiki/api/v2/{pages,blogposts}/{id}/attachments`, as one list |

`confluence_v2.identity` refuses a view of another page or version than the document,
so a page edited between the two GETs is never stored as one snapshot.

Files of a Jira snapshot, named by constants of `sources.atlassian.adapters.jira_v3`:

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

- `put(kind, responses, fetched_at, blobs)`, with `kind` one of `Page`, `BlogPost` and
  `Issue`, refuses a snapshot without one of the kind's files (above), reads only the
  id and the revision (the kind's `identity`), stores the responses as received, and
  returns the folder. `blobs` maps attachment ids to digests
  of files already stored with `put_blob`: files first, snapshot last, so a record never
  names a missing file. For a revision stored already, `put` keeps the responses and
  records the new blobs.
- `add_blobs(document, blobs)` records files downloaded later, such as on a retry,
  replacing the record alone, whole. It, `has` and `read` take a `Document` or a
  `Listed`.
- `has(document)`; `read(document)`, which returns a `Stored` or raises one of
  `raw_store.UNREADABLE` (`RepresentationError` for a refused field, another
  `ValueError` or an `OSError` for a damaged file); and `latest(kind)`, which yields the
  newest snapshot of each document of a kind as a `Stored`, or as an `Unreadable`
  (where it is, and the refused field's path or the error's class) when it cannot be
  read. The others still follow.
- `Stored` is the snapshot read into the domain (`Snapshot`), its folder, `fetched_at`
  and `blobs`, the files of its own attachments only. An attachment absent from `blobs`
  was not downloaded: a media type not kept, over the size cap, or a failed download.
- `responses(folder)` gives the responses as received, for adapters to read what the
  domain does not yet carry (a macro's parameters in the storage body, say).

Known limits, for a later plan: a change that makes no new version (an attachment added
without an edit, labels changed, a page archived, a comment) leaves the stored snapshot
as it was, as does an edit of a page that this page includes; the mirror takes a page's
status from the space's listing, which is fresher; labels beyond the first page that
`include-labels` returns are not seen.

### A space's listings, and users

Each run that downloads a space replaces that space's listings, each as received, every
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
outside the period downloaded, folders included (`Page.parent_type` says whether a parent
is a page or a folder), and the names of Confluence authors, whom v2 gives by account id
only.

### Files

Attached files: `<data>/raw/blobs/<sha256[:2]>/<sha256>`, written once, by
`put_blob(data)`; `blob(digest)` gives the path.

### Coverage and tombstones

Two more of the store's own records, each replaced whole:

- `<data>/raw/coverage.json`, read by `coverage()` and written by `put_coverage()`: for
  each target (a space key or a project key,
  `sources.atlassian.domain.coverage.Target`), the one period over which every document
  updated is stored (`sources.atlassian.domain.coverage.Coverage`). A run that listed a
  target whole joins its window to that period when the two overlap or touch; a run
  without `--since` starts at the covered start, so every run asks again for whatever
  failed inside the period.
- `<data>/raw/tombstones.json`, read by `tombstones()` and written by
  `put_tombstones()`: each Confluence document absent from its space's listing
  (`sources.atlassian.domain.deletions.Tombstone`), pending until a probe answers, then
  dated by its first answer of gone (404, trashed, or moved to a space the store does
  not keep), and confirmed by a second, at least an hour later. A document found in a
  kept space whose stored listing names it has moved, and loses its tombstone, as does
  one listed again; one found in a kept space whose listing does not name it goes back
  to pending. The absent are found from the last listing read by id alone
  (`listed_ids(space_id, kind)`), so that an entry the adapter would refuse is still
  followed, and the ids that have a snapshot (`stored_ids(kind)`); the record is written
  before the space's listing is replaced, so that no absent document is lost to a run
  that stops, and they are probed once every space of the run is listed.

## Run reports

Owned by `download` (004): `<data>/runs/<UTC time as %Y%m%dT%H%M%SZ>.json`, in the format
004's plan defines. A run report holds counts and refused fields' paths, never content.

## The Markdown mirror

Owned by `mirror` (005), but for `worklog/`, which `sync`'s work-log step owns (017,
[below](#the-work-log)); neither removes the other's files. `mirror`'s part is derived
from the raw store and the `site` setting alone, so it can be rebuilt without network,
byte for byte: nothing in it depends on when `mirror` ran.

```
<data>/docs/confluence/<SPACE>/<id>-<slug>.md        a page
<data>/docs/confluence/<SPACE>/blog/<id>-<slug>.md   a blog post
<data>/docs/confluence/<SPACE>/_tree.md              the space's tree
<data>/docs/jira/<PROJECT>/<KEY>.md                  an issue
<data>/docs/assets/<sha256>.<ext>                    an attached file
<data>/docs/worklog/entries/<id>-<slug>.md           a work-log entry
<data>/docs/worklog/transcripts/<id>-<slug>.md       a work-log transcript
```

- The documents are exactly the files that `mirror.adapters.markdown.documents(docs)`
  yields: those of the first, second, fourth, sixth and seventh patterns, except names
  beginning with `_` or `.`. `_tree.md` has no front matter, and nothing under
  `assets/` is a document.
- `<SPACE>` is the space key, `<PROJECT>` the project key, `<KEY>` the issue key.
- `<slug>`: the title decomposed (Unicode NFKD) and lowered, its combining marks dropped
  (`Crème` gives `creme`), keeping ASCII letters and digits; every run of other
  characters becomes one `-`; leading and trailing `-` are
  removed; it is cut at 60 characters, and a `-` left at the cut is removed. An empty
  slug leaves `<id>.md`. When a title changes, the file is renamed and the old name
  removed.
- `<ext>`: the attachment file name's extension in lower case when it matches
  `[a-z0-9]{1,8}`, otherwise none. Links from documents to assets are relative.
- `_tree.md`: one nested list item per page and folder of the listings, linking the
  mirrored file, or naming the page as "not yet mirrored" when its body was not
  downloaded.

Each document starts with front matter written by `mirror.adapters.markdown.dump` and
read by `mirror.adapters.markdown.load`, from a `mirror.domain.mirror.FrontMatter`;
nothing else writes or reads it. Its keys come in this order, all always present (`null`
when unknown or not applicable), and a key that one source alone has is `null` for the
other and never for its own. Every text is one line, with no line break of any kind;
times are in UTC, written as quoted strings to the second; strings that YAML 1.1 could
read as another type (`'000003'`, `'Yes'`) are quoted; `load` refuses any other key,
order or type, by name.

| Key | Type | Value |
|---|---|---|
| `source` | string | `confluence`, `jira` or `worklog` |
| `type` | string | `page` or `blogpost` (Confluence), `issue` (Jira), `entry` or `transcript` (work log) |
| `id` | string | the content id or issue id; a work-log document's, [below](#the-work-log) |
| `key` | string or null | the issue key; `null` for Confluence |
| `title` | string | the title |
| `space` | string or null | the space key; `null` for Jira |
| `project` | string or null | the project key; `null` for Confluence |
| `status` | string | as the site names it; an entry's keyword, else `current`, as a transcript's |
| `issue_type` | string or null | the issue type, such as `Bug`; `null` for Confluence |
| `labels` | list of strings | the labels, `[]` when none; a work-log document's tags, its file's `#+FILETAGS`, and `ARCHIVE` when archived |
| `author` | string or null | the display name when known (from `users()` for Confluence), otherwise the account id; `null` when none, and for the work log |
| `assignee` | string or null | the assignee's display name, or account id; `null` when unassigned or for Confluence |
| `created`, `updated` | string | ISO 8601 times in UTC, such as `'2026-10-20T21:52:41Z'`; a work-log document's, [below](#the-work-log) |
| `version` | integer or null | the Confluence version number; `null` for Jira |
| `revision` | string | the raw store revision mirrored; a work-log document's, 16 hex digits, [below](#the-work-log) |
| `url` | string or null | the absolute address of the web page: the `site` setting and `Document.url`; `null` when no site is set, and for the work log |
| `breadcrumb` | list of strings | the titles of the ancestor pages and folders, root first; for an issue, `[<parent key>]`, or `[]`; for an entry, its file's name; for a transcript, its folders from `transcripts` |
| `fetched_at` | string | `fetched_at` of the snapshot, as `created`; a work-log document's file's modification time when converted |

Images: an image in the rendered HTML names its attachment by
`data-linked-resource-id` (the attachment id) or by the file name in its `src`, as
plan 001 found on the sandbox; 005's HTML module, the one module that knows the site's
markup, maps it to `Stored.blobs`. An image of another page's attachment (through an
include) has a file only when that page is stored; otherwise the mirror keeps a
placeholder; a backfill that reaches the other page fills it.

A Confluence document is mirrored in the space whose freshest listing (by `listed_at`)
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

### The work log

Owned by `sync`'s work-log step (017), in `mirror.app.worklog`: `<data>/docs/worklog/`,
from the folder that `sources.worklog.path` names, read in place and never written.
`mirror.adapters.mirror_files.owned` and `worklog_owned` tell each owner's files apart,
so that `mirror` and the work-log step never remove each other's. A run that meets a
problem (a file not read, a conversion that failed) removes none of its files.

- An **entry** is a top-level heading of `todo.org` or `todo.org_archive`, with what
  lies below it. Its id is `e-` and the first 16 hex digits of the SHA-256 of its `:ID:`
  property; else of its title, a line feed, and its `:CREATED:` property; else of its
  title alone. The title is the heading without keyword, priority, tags and statistics
  cookies. The second entry of one digest takes `-2`, the third `-3`, in file order,
  `todo.org` first.
- A **transcript** is an `*.org` file under `transcripts/`. Its id is `t-`, the day
  that begins its folder's name, else its own, as `%Y%m%d`, `-` and its name without
  `.org`, when that matches the rule below; else `t-` and the digest of its path below
  `transcripts/<first folder>/`. Of two files of one id, the second in path order takes
  the digest of its whole path from the work log's root, written with a leading `/`,
  which no path below a first folder has.
- The rule of an id is `kernel.content.WORKLOG_ID`,
  `e-[0-9a-f]{16}(?:-[0-9]+)?|t-(?:[0-9]{8}-[A-Za-z0-9_-]{1,64}|[0-9a-f]{16})`. It names
  the file, with the title's slug, as for a page.
- `revision` is the digest of pandoc's version and options, a NUL, and the org text
  that pandoc converts: a document whose revision has not changed is not converted
  again, and its file keeps its dates.
- `created` and `updated` are a transcript's day at midnight UTC; else the earliest and
  latest timestamps of the document's lines, as written, up to its file's modification
  time, a later one being a plan; else, without any, the modification time, `created`
  keeping an existing file's.
- The body is pandoc's GitHub Markdown of the org text, its lines as written. `COMMENT`
  and `noexport` subtrees are kept; with `sources.worklog.archives = false`, the archive
  file, `transcripts/archive/` and subtrees tagged `ARCHIVE` are left out.

An entry holds the user's notes and summaries an AI wrote; a transcript, the
word-by-word record. The MCP server says so to agents, in its instructions and its
`source` filter, and `read` opens a document by its id.

## The index

Owned by `index` (006), which `sync` runs as its last step (017).
`<data>/index.sqlite` is built from the documents of `<data>/docs/` alone, the work
log's among them, read with `mirror.adapters.markdown`, into a temporary file that
is then renamed into place. Its schema is defined in 006's plan; schema 3 (011) adds the
table `pieces` (each piece of a section's body, its span and its vector) and the meta
rows `build` (a random id of the build), `model`, `fingerprint` and `dimensions`, the
last three empty for an index built without a model. Plan 019 adds the meta row
`chunking`, how the pieces were cut (one of `kernel.chunking`'s names), empty without a
model; an index without the row, 011's or 018's, was cut by `sections`. A piece keeps
the section that holds its middle and a span relative to that section's body, so that
a window across sections needs no other schema. Plan 023 adds the column `key` to
`pieces`, the key of the piece's vector in the vector store, which only pruning reads;
an index built before it reads as any other, but cannot say what it reads of the store,
and `SCHEMA` stays 3. An index of another schema is
refused with the command that rebuilds it. The MCP server opens it read-only, never
writes, and reopens it when the file is replaced; it searches by meaning with the model
that the index names, and only while the endpoint's fingerprint for it is the index's.

### Models and vectors

No model runs in this program (plan 018): `search.adapters.embedding` alone asks an
OpenAI-compatible endpoint, the setting `embedding_url` (by default Ollama's
`http://127.0.0.1:11434/v1`), and refuses one that is not a literal loopback address
unless the command is given `--allow-remote-embeddings`. A model's fingerprint is the
SHA-256 of its name, the digest that Ollama lists for it (`/api/tags`, empty from a
server that lists none), its dimensions, its query and document prefixes, and the
adapter's format version. `<data>/vectors.sqlite` keeps the vectors embedded, keyed
by the SHA-256 of that fingerprint and the text, committed in batches; deleting it
costs a full embedding of the mirror by the model, and downloads nothing. A text that the endpoint refuses has no vector there, and is
asked again at the next build.

After each `index` by meaning, the step of `sync` included, the store is pruned (plan
023) to the vectors that `<data>/index.sqlite` and the indexes under
`<data>/eval/indexes/` read, by the keys their pieces record: the files are the truth,
so that deleting an evaluation's index lets the next prune drop its vectors, and
`eval --model M` keeps a model's. A vector that no index on disk reads is deleted: an
edited piece's old text, a deleted document's, a model replaced, a build interrupted
before its index was renamed in. The prune is held back, deleting nothing, when the
build skipped a file or indexed no document; when an index there cannot say which
vectors it reads (built by words alone or before plan 023, damaged, or not an index):
`eval` rebuilds those of the models and chunkings it is given, else delete them; and
when a folder there cannot be reached or listed, an entry below `<data>/eval/indexes/`
is a link, which is not followed, or `<data>/eval` is a dangling link, as to a disk
away: make it readable, or put what the link points to in its place. A build holds
`<data>/vectors.sqlite.lock` shared by `flock` until its index is in place, and a prune
takes it exclusive or is deferred to the next `index`. A store made from plan 023 on
gives the pages freed back to the file system (`auto_vacuum = INCREMENTAL`). One made
before is converted at its first prune, once the vectors that no index reads are
deleted: the mode set, then one `VACUUM`, which rewrites the vectors kept while the
prune holds the lock, and needs about their size free in SQLite's temporary folder
(`SQLITE_TMPDIR`, else `TMPDIR`, else `/var/tmp`) and as much again beside the store,
for its WAL. The result says so; a conversion that fails, for want of space, says why,
leaves the deletions, and the next prune tries again. A later
index that reads the store builds through `search.app.indexing.build_index`, and so its
lock, and adds its files to what the prune follows. Under `<data>/eval/`,
`indexes/<chunking>/<model>.sqlite` (each `/` and `:` of the name written `_`) are the
indexes that `eval` builds, one per model and chunking, and `results/<UTC time>.json`
its numbers: the golden file's SHA-256, models, chunkings, measures of `search` and of
`ask`, costs, ranks and tests, by question id, never a question's text, and for each
model the chunking that plan 019's rule chooses. `eval-agents` writes into a directory
of its own, given by `--out`, never under `<data>/` unless placed there: its layout is
in [evaluating with agents](../how-to/evaluate-with-agents.md).
A `<data>/models/` folder left by plan 011 is read by nothing.

## The session

Owned by `login` (004). `<data>/session/` has mode `0700`; it holds the browser profile
of the sign-in window and the saved session cookies (mode `0600`). Agents are never
given access to it: only `<data>/docs/` is shared with them.

`sources.atlassian.adapters.sign_in` chooses how a run signs in (015): by an API token
when the setting `api_token` is set, else by the saved session, whose cookies a run
writes back as the site renews them. A run signed in by a token reads and writes nothing
under `<data>/session/`, and keeps nothing of the token, which the environment gives to
each run and no file under `<data>` holds.
