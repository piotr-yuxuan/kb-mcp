# Internals

How the program turns a site into answers for agents: four stages, each a command, each
reading what the one before it wrote. Only the first reads the site; every later stage
can be run again offline, from what is on the disk. This page follows the data through
them, then follows one change, from a page edited on the site to the next search. The
formats of what each stage writes are in [the data layout](../reference/data-layout.md);
where the code of each lives, in [the code's layout](code-layout.md); why it is built
so, in [the trade-offs](trade-offs.md).

```mermaid
flowchart LR
    site["Confluence and Jira Cloud"]
    raw[("raw store")]
    docs[("Markdown mirror")]
    vectors[("vector store")]
    index[("index")]
    endpoint["embedding endpoint"]
    server["MCP server"]
    agents["coding agents"]
    site -- "download, GET only" --> raw
    raw -- "mirror, offline" --> docs
    docs -- "index" --> index
    endpoint -- "vectors of new texts" --> vectors
    vectors -- "index" --> index
    index -- "serve, read-only" --> server
    endpoint -- "vectors of queries" --> server
    server -- "MCP over stdio" --> agents
    docs -- "files, read-only" --> agents
```

| Stage | Reads | Writes | Never half-written, by | When one thing fails |
|---|---|---|---|---|
| `download` | the site, GET only | `<data>/raw/` | a lock, and each snapshot renamed into place | the document is counted and skipped; the run goes on |
| `mirror` | the raw store | `<data>/docs/` | each file renamed into place | the document is reported, its last good file kept |
| `index` | the mirror; the endpoint, for new texts | `<data>/index.sqlite`, `<data>/vectors.sqlite` | the index built aside, then renamed into place | the file is skipped and named; without the endpoint, the old index stays |
| `serve` | the index; the endpoint, for queries | nothing | the index opened read-only for each call | without meaning, the search ranks by words and says why |

## Download: from the site to the raw store

[`download`](../../src/atlassian_offline_mcp/sources/atlassian/app/download.py) reads the
site through one port, [`Site`](../../src/atlassian_offline_mcp/sources/atlassian/adapters/http.py),
which makes GETs alone, one at a time and paced, signed in by the saved session or an API
token ([`sign_in`](../../src/atlassian_offline_mcp/sources/atlassian/adapters/sign_in.py)).
For each Confluence space, it lists every page, blog post and folder, and stores the
listings whole; for each Jira project, it searches the issues updated in the period. Then
it fetches each document updated in the period whose revision the store lacks
([`Download.consider`](../../src/atlassian_offline_mcp/sources/atlassian/app/download.py)),
its files first, the snapshot last
([`Download.keep`](../../src/atlassian_offline_mcp/sources/atlassian/app/download.py)).
Without `--since`, a target's period starts where the period it already covers starts
([`window`](../../src/atlassian_offline_mcp/sources/atlassian/domain/coverage.py)), so a
run asks again for whatever failed before.

- **Writes**, into `<data>/raw/` alone, through
  [`RawStore`](../../src/atlassian_offline_mcp/sources/atlassian/adapters/raw_store.py):
  snapshots, listings, files by digest, the coverage and the tombstones of documents
  gone. One run at a time:
  [`RawStore.writing`](../../src/atlassian_offline_mcp/sources/atlassian/adapters/raw_store.py)
  holds a lock, and a second run stops at once with
  [`StoreBusyError`](../../src/atlassian_offline_mcp/sources/atlassian/adapters/raw_store.py).
  A snapshot is written into a hidden folder and renamed into place
  ([`RawStore.put`](../../src/atlassian_offline_mcp/sources/atlassian/adapters/raw_store.py)):
  complete or absent, and never written again.
- **One document's failure** is counted, logged with its id, and skipped; the run goes
  on. A response that its adapter refuses is stored all the same, raw, for a fixed
  adapter to read. Only ten GETs in a row without an answer
  ([`MAX_FAILED_IN_A_ROW`](../../src/atlassian_offline_mcp/sources/atlassian/adapters/http.py)),
  or a session that no longer holds
  ([`SignInNeededError`](../../src/atlassian_offline_mcp/sources/atlassian/adapters/http.py)),
  stop a run; its report is saved even then.
- **Offline**, nothing: this is the one stage that reads the site.

## Mirror: from the raw store to Markdown

[`mirror`](../../src/atlassian_offline_mcp/mirror/app/mirror.py) reads the newest
snapshot of each document
([`RawStore.latest`](../../src/atlassian_offline_mcp/sources/atlassian/adapters/raw_store.py)),
the listings, the users and the tombstones, and the setting `site`: nothing else. It
places each document in the space whose freshest listing names it, leaving out those
confirmed gone ([`place`](../../src/atlassian_offline_mcp/mirror/app/mirror.py)); turns
the site's HTML into plain HTML, the one module that knows the site's markup
([`normalise`](../../src/atlassian_offline_mcp/mirror/adapters/site_html.py)); and has
pandoc write it as Markdown, one process a document
([`Pandoc.markdown`](../../src/atlassian_offline_mcp/mirror/adapters/pandoc.py)).

- **Writes**, into `<data>/docs/` alone, through
  [`sync`](../../src/atlassian_offline_mcp/mirror/adapters/mirror_files.py): each file
  whose bytes differ, through a hidden file renamed into place, so that no reader sees
  half of one. A file whose bytes are the same keeps them and its time. No lock: the
  snapshots read are each complete, and each file is replaced whole.
- **One document's failure**, a field refused or pandoc failing, is reported by its place
  in the store, never its content; the run goes on. A run that reported anything removes
  no file but those of documents gone or moved, so that the last good copy of each
  stays.
- **Offline**, everything: the mirror is rebuilt from the raw store, byte for byte, as
  long as pandoc's version is the same.

## Index: from Markdown to words and vectors

[`build_index`](../../src/atlassian_offline_mcp/search/app/indexing.py) reads the files
of the mirror alone, never the raw store (an import contract holds it). It cuts each
body into sections before each heading
([`sections`](../../src/atlassian_offline_mcp/search/domain/search.py)), indexes them by
words, and, unless `search_mode = "lexical"`, cuts each document into pieces by the
setting `chunking` ([`CHUNKERS`](../../src/atlassian_offline_mcp/search/domain/chunking.py))
and gives each piece a vector.

- **Writes** a new `<data>/index.sqlite` in a file beside the old one, in one
  transaction, renamed into place once complete
  ([`building`](../../src/atlassian_offline_mcp/search/adapters/sqlite_index.py)); on any
  failure, the old index stays. Each build has a random id, its meta row `build`.
  Vectors are kept in `<data>/vectors.sqlite`, committed 256 texts at a time
  ([`VectorStore.vectors`](../../src/atlassian_offline_mcp/search/adapters/vector_store.py)),
  so that an interrupted build loses little; in SQLite's WAL mode, an `index` and an
  `eval` can share it, a write waiting for the other's
  ([`opened`](../../src/atlassian_offline_mcp/search/adapters/vector_store.py)).
- **One document's failure**, a file not UTF-8, front matter refused, or a second
  document of the same id, skips that file and names it, with a reason that holds no
  content; the build completes and exits 1. A piece whose text the endpoint refuses is
  left without a vector, its document named, and asked again at the next build. Only an
  endpoint that does not answer, or lacks the model, stops the build: the old index
  stays.
- **Offline**, the words: the index is rebuilt from the mirror alone. Meaning needs the
  endpoint, but only for texts that the vector store lacks (below).

## Serve: from the index to agents

The server ([`run`](../../src/atlassian_offline_mcp/cli/commands/serve.py)) answers the
tools of [`Library`](../../src/atlassian_offline_mcp/mcp/app/tools.py) over stdio. It
writes nothing. Each call opens the index read-only for itself
([`reading`](../../src/atlassian_offline_mcp/search/adapters/sqlite_index.py)), so a new
build is read from the next call on, and each answer stays within its budget, with what
it copies from the site inside a block marked as untrusted
([`answer`](../../src/atlassian_offline_mcp/mcp/app/responses.py)). In the lexical mode
it never opens the endpoint. A search ranks in the mode that `search_mode` sets
([`ranking`](../../src/atlassian_offline_mcp/mcp/app/tools.py)); issue keys and page ids
named in a query put their documents first, in every mode.

### By words

The query becomes words ([`plan`](../../src/atlassian_offline_mcp/search/domain/search.py)):
split, in lower case, without the English and French stop words unless nothing else is
left, at most ten, each a quoted string, so that nothing a query holds is read as an
operator; and the whole phrase too, when it has 2 to 16 words. For each word, and the
phrase, the index scores each document that matches by its best section's bm25, with
weights per column, the title first
([`Reader.scores`](../../src/atlassian_offline_mcp/search/adapters/sqlite_index.py));
a document's score is the sum of its scores
([`rank`](../../src/atlassian_offline_mcp/search/domain/search.py)).

### By meaning

The query is embedded, with the model's query prefix, and compared with every piece of
the index: the vectors are of unit length, so one product of the matrix of pieces by the
query gives every cosine, exactly, with no approximate index
([`Pieces.nearest`](../../src/atlassian_offline_mcp/search/domain/search.py)). A document
scores by its best piece, and the 100 nearest are kept
([`Meaning.nearest`](../../src/atlassian_offline_mcp/search/app/meaning.py)). The model
is the one the index names, never the setting, and only while the endpoint's fingerprint
for it is the index's: vectors of other weights would not compare with the query's.

### Fused

In the hybrid mode, the default, the two rankings are fused by reciprocal rank: each
list gives a document 1 / (60 + its rank), and the sums order them
([`fuse`](../../src/atlassian_offline_mcp/search/domain/search.py)). Ranks, not scores,
are added, as a bm25 and a cosine have no common scale. A document is shown by the
section of whichever list ranks it higher.

### Falling back to words

When meaning cannot be searched, a search in the hybrid or semantic mode ranks by words
alone, and its answer says why, never failing
([`ranking`](../../src/atlassian_offline_mcp/mcp/app/tools.py)): the index holds no
vectors ([`NO_VECTORS`](../../src/atlassian_offline_mcp/search/app/meaning.py)), it was
built with other weights of its model
([`STALE`](../../src/atlassian_offline_mcp/search/app/meaning.py)), or the endpoint does
not answer or lacks the model. A failed connection is not tried again for 30 seconds
([`QUIET_S`](../../src/atlassian_offline_mcp/search/app/meaning.py)), so that searches in
the meantime answer at once.

## How a change on the site reaches search

Follow one page, edited on the site, to the answers of the next search. Nothing in the
program watches for changes: each step below is a command run by hand.

### 1. A new snapshot, or a tombstone

An edit gives the page a new version. The next `download` lists its space whole, finds
the page updated within the period it covers, sees that this revision is not stored
([`RawStore.has`](../../src/atlassian_offline_mcp/sources/atlassian/adapters/raw_store.py)),
and fetches it as a new snapshot, beside the old one, which stays. An issue edited in
Jira has a new update time, its revision, and is fetched the same way.

- **Moved** to another space that the run keeps, a page is listed there, and the store
  notes when each space was listed.
- **Deleted**, a page is absent from its space's listing. The run records a
  [`Tombstone`](../../src/atlassian_offline_mcp/sources/atlassian/domain/deletions.py) and
  probes the page; a second answer of gone, an hour or more after the first, confirms
  it. When many probes of one space answer that their pages are gone, the run first
  checks that its session still holds
  ([`too_many_gone`](../../src/atlassian_offline_mcp/sources/atlassian/domain/deletions.py)),
  so that a lost session deletes nothing.
- **Not yet seen**: a change that makes no new version, such as labels changed or a
  file attached without an edit, and Jira's deletions; [the data
  layout](../reference/data-layout.md#snapshots) lists these limits.

### 2. The mirror's file rewritten or removed

`mirror` builds every file again from the newest snapshot of each document, and writes
only those whose bytes changed: the edited page's file is replaced whole, and every
other file keeps its bytes and its time. A changed title renames the file, as its name
holds the title, and the old name goes. A moved page's file goes to its new space's
folder. A confirmed deletion removes the file, even in a run that reports problems with
other documents.

### 3. The index rebuilt aside, then renamed in

`index` patches nothing. It builds a whole new index from every file of the mirror,
beside the old one, and renames it into place once it is complete. So a deleted page's
sections and pieces are simply absent from the new build, and an edited page's are its
new ones: nothing stale is left in the index, and a build that fails leaves the old one
whole. Reading and cutting the whole mirror again is cheap; what would be dear,
embedding it all again, the next step avoids.

### 4. Vectors reused by the key of model and text

Each piece is embedded as a text that its chunking composes: by `windows`, the default,
the document's title and the window
([`windows`](../../src/atlassian_offline_mcp/search/domain/chunking.py)). Its vector is
kept under a key, the SHA-256 of the model's fingerprint and that text
([`key`](../../src/atlassian_offline_mcp/search/adapters/vector_store.py)). A build asks
the vector store for every key, and the endpoint for the missing texts alone. So a piece
whose text did not change is never embedded again: a page moved to another space keeps
its vectors, unless its chunking embeds the breadcrumb that the move changed. What
widens the texts embedded again:

- **A chunking whose cuts shift.** `windows` cut the whole body at fixed steps from its
  start, so an edit shifts every window after it, all new texts, while the windows
  before it are reused. `sections`, `section-paths` and `small-to-big` cut each section
  apart, so an edit re-embeds the pieces of its own section.
- **A renamed title or heading.** Each piece's text begins with the title, so a new
  title re-embeds the whole page. A renamed heading re-embeds the windows from it on by
  `windows`; its section's pieces by `sections`; and by `section-paths` and
  `small-to-big`, whose texts carry the breadcrumb and the path of headings, the pieces
  of its section and of every section under it, and every piece of a page whose
  breadcrumb changes.
- **Another chunking**, which cuts other texts: the first `index` after changing
  `chunking` embeds the whole mirror, unless an `eval` of that chunking with the same
  model embedded it already.
- **Another model, or new weights.** The fingerprint
  ([`ApiEmbedder.fingerprint`](../../src/atlassian_offline_mcp/search/adapters/embedding.py))
  holds the model's name, the digest that Ollama lists for it, its dimensions, its
  prefixes and the adapter's format, so a change to any of them makes every key new. A
  server other than Ollama, any other OpenAI-compatible one, lists no digest: after
  changing the weights behind a name there, delete the vector store.

[Chunking](chunking.md#when-pages-change) counts what one edit costs by each chunking on
the sandbox's mirror.

### 5. The server picks up the new build

The server needs no restart. Each call opens the index anew, so the call after the
rename reads the new build. A search by meaning keeps the vectors of one build in memory,
with its connection to the model, and loads them again when the build's id changes
([`Meaning.prepared`](../../src/atlassian_offline_mcp/search/app/meaning.py)). A cursor
given by the old build is refused, with the advice to call again without it
([`start_of`](../../src/atlassian_offline_mcp/mcp/app/tools.py)). After `ollama pull`
of new weights, a server that connects finds the fingerprint changed and answers by words
until `index` runs, while one connected before the pull goes on with the new weights
against the old vectors until the index is rebuilt.

### 6. The vector store only grows

No build removes a vector: those of deleted pages, of texts since edited, of other
chunkings and other models, and those that `eval` embedded, all stay. A vector left
there is read by nothing; an index never holds one whose text the mirror no longer has,
since it is rebuilt. What it costs is disk: a vector of the default model is 1,024
numbers of 4 bytes, so each 10,000 texts kept take about 40 MB. Deleting
`<data>/vectors.sqlite` costs one full embedding at the next `index`, and nothing else:
the index holds its own copy of each vector, so the server goes on answering meanwhile.
