# Data layout

What each part of the program writes and reads under the data directory, so that the
download (plan 004), the Markdown mirror (005) and search (006) can be built apart.
Where this file and the code disagree, the code named here is right and this file is
fixed.

## The data directory

`<data>` is the setting `data_dir`, by default `~/atlassian-offline-mcp`. Every command
that writes under it first runs the guard of `check`: never under a synchronised
folder, never inside a git working tree.

| Path | Written by | Read by |
|---|---|---|
| `<data>/raw/` | `download` (004) | `mirror` (005) |
| `<data>/docs/` | `mirror` (005) | agents, and `index` (006) |
| `<data>/index.sqlite` | `index` (006) | the MCP server (006) |
| `<data>/session/` | `login` (004) | the carriers of 004 only |

The paths come from `Settings.raw`, `Settings.docs`, `Settings.index` and
`Settings.session`; no code builds them otherwise.

## The ontology, and where details of the site live

The site's responses and its HTML change without notice. So that a change stays local:

- **One vocabulary.** `domain.content` names what the mirror holds: `Space`, `Page`,
  `BlogPost` (both `ConfluenceDocument`), `Issue`, `Attachment`, `Comment`, `Person`, and
  `Snapshot`, a document at one revision with its rendered body. A document knows where
  it is stored (`source`, `kind`) and names its state (`revision`). Every layer above the
  adapters works with these types alone.
- **One module per representation.** `adapters.confluence_v2` and `adapters.jira_v3` hold
  all that the code knows of those JSON responses: field names, which response holds
  what, and the file names a snapshot uses. The API paths and query parameters that 004
  needs go into the same modules. No other code indexes into a response.
- **Strict reading.** Adapters read through `adapters.fields.Fields`. A missing field, a
  wrong type or a time without an offset raises `RepresentationError` with the field's
  path, such as `document.json.version.number: expected an integer`. Reports print the
  path, never the value.
- **Raw first.** The raw store keeps responses exactly as received. After an adapter is
  fixed, `mirror` reads the store again; nothing is fetched.
- **HTML likewise.** The site's markup (class names, data attributes, macro names) is
  known to one module of 005, as named constants. Markup it does not know becomes a
  visible placeholder naming the construct, not an error.
- **Ids are checked once.** The domain types refuse an id that is not one safe path part
  (`[A-Za-z0-9_-]+`), a space key, project key or issue key that does not look like one,
  and an attachment download that is not a site-relative path.

## The raw store

Owned by `adapters.raw_store.RawStore`; nothing else writes under `<data>/raw/`.

### Snapshots

A snapshot is one document at one revision:

```
<data>/raw/<source>/<kind>/<id>/<revision>/<file>.json
```

- `source` and `kind`: `confluence/pages`, `confluence/blogposts`, `jira/issues`.
- `id`: the content id (Confluence) or the issue id (Jira, which stays when the key
  changes).
- `revision`: the version number padded to six digits for Confluence (`000003`), the
  update time in UTC for Jira (`20261020T213758.027000Z`). Names sort as text in the
  order of revisions; the newest snapshot is the last name.
- A snapshot is written into a hidden folder and renamed into place: it is complete or
  absent. A stored revision is never written again. Names that begin with `.` are not
  snapshots.

Files of a Confluence snapshot, named by constants of `adapters.confluence_v2`:

| File | Content |
|---|---|
| `document.json` (`DOCUMENT`) | `GET /wiki/api/v2/{pages,blogposts}/{id}?body-format=storage&include-labels=true` |
| `view.json` (`VIEW`) | the same with `body-format=view` |
| `attachments.json` (`ATTACHMENTS`) | the `results` of every page of `GET /wiki/api/v2/{pages,blogposts}/{id}/attachments`, as one list |

Files of a Jira snapshot, named by constants of `adapters.jira_v3`:

| File | Content |
|---|---|
| `issue.json` (`ISSUE`) | `GET /rest/api/3/issue/{id}?expand=renderedFields` |
| `comments.json` (`COMMENTS`) | the `comments` of every page of `GET /rest/api/3/issue/{id}/comment?expand=renderedBody`, as one list |

Every snapshot also has the store's own `store.json` (`raw_store.STORE`):

```json
{"fetched_at": "2026-10-22T08:15:00Z", "blobs": {"att196895": "<sha256>"}}
```

`blobs` maps each downloaded attachment's id to the SHA-256 of its file. An attachment
that is listed but absent from `blobs` was not downloaded: too large, a media type that
is not kept, or a failed download; 004 reports which, by count.

`confluence_v2.snapshot(kind, responses)` and `jira_v3.snapshot(responses)` turn a
snapshot's files into a `Snapshot`.

### Listings

A listing is every result of a paged list, as one JSON list, replaced whole on each run:

```
<data>/raw/<source>/listings/<name>.json
```

| Name | Content |
|---|---|
| `spaces` | each configured space, as `GET /wiki/api/v2/spaces/{id}` returns it |
| `pages-<space id>` | every page of the space, from `GET /wiki/api/v2/spaces/{id}/pages` without bodies |
| `blogposts-<space id>` | every blog post of the space, likewise |

Listings give 005 the whole tree, titles and breadcrumbs, even of pages whose bodies are
outside the period downloaded. Each result reads with `confluence_v2.document` or
`confluence_v2.space`.

### Files and runs

- Attached files: `<data>/raw/blobs/<sha256[:2]>/<sha256>`, written once.
- Run reports: `<data>/raw/runs/<UTC time>.json`, written by 004, in the format its plan
  defines. A run report holds counts and error paths, never content.

## The Markdown mirror

Owned by `mirror` (005). Derived from the raw store alone, so it can be rebuilt without
network, byte for byte: nothing in it depends on when `mirror` ran.

```
<data>/docs/confluence/<SPACE>/<id>-<slug>.md        a page
<data>/docs/confluence/<SPACE>/blog/<id>-<slug>.md   a blog post
<data>/docs/confluence/<SPACE>/_tree.md              the space's page tree
<data>/docs/jira/<PROJECT>/<KEY>.md                  an issue
<data>/docs/assets/<sha256>.<ext>                    an attached file
```

- `<SPACE>` is the space key, `<PROJECT>` the project key, `<KEY>` the issue key.
- `<slug>`: the title in lower-case ASCII, runs of other characters made one `-`, at most
  60 characters; a title with no such characters leaves `<id>.md`. When a title
  changes, the file is renamed and the old name removed.
- `<ext>`: the attachment file name's extension in lower case when it matches
  `[a-z0-9]{1,8}`, otherwise none. Links from documents to assets are relative.
- `_tree.md`: one nested list item per page of the listing, linking the mirrored file,
  or naming the page as "not yet mirrored" when its body was not downloaded.

Each document starts with YAML front matter, with these keys in this order, all always
present (`null` when unknown or not applicable):

| Key | Value |
|---|---|
| `source` | `confluence` or `jira` |
| `type` | `page`, `blogpost` or `issue` |
| `id` | the content id or issue id, as a string |
| `key` | the issue key; `null` for Confluence |
| `title` | the title |
| `space` | the space key; `null` for Jira |
| `project` | the project key; `null` for Confluence |
| `status` | as the site names it |
| `labels` | a list of strings |
| `author` | the display name when known, otherwise the account id |
| `created`, `updated` | ISO 8601 times in UTC, such as `2026-10-20T21:52:41Z` |
| `version` | the Confluence version number; `null` for Jira |
| `revision` | the raw store revision mirrored |
| `url` | the absolute address of the web page |
| `breadcrumb` | the titles of the ancestors, root first; for an issue, its parent key if any |
| `fetched_at` | `fetched_at` of the snapshot |

Then the body: a first-level heading with the title, the converted body, then an
`## Attachments` section listing each attachment (a link to its asset, or "not
downloaded"), then for an issue a `## Comments` section with one `### <author>, <time>`
heading per comment. Headings inside the body are kept, so that 006 can cut a document
into sections.

Everything in the mirror is content from the site: untrusted reference data, never
instructions.

## The index

Owned by `index` (006). `<data>/index.sqlite` is built from `<data>/docs/` alone (front
matter and Markdown), into a temporary file that is then renamed into place. Its schema
is defined in 006's plan. The MCP server opens it read-only, never writes, and reopens it
when the file is replaced.

## The session

Owned by `login` (004). `<data>/session/` has mode `0700`; it holds the browser profile
of the sign-in window and the saved session cookies (mode `0600`). Agents are never
given access to it: only `<data>/docs/` is shared with them.
