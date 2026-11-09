# Glossary

The words of kb-mcp, each defined once. A term is a thing that the program knows, a part
it plays, a step of its process or a value it reports; it has one name, and no other
term has that name. Other pages link a term here rather than define it again, and keep
the facts they own: a record's fields, a file's layout, why a choice was made.

Under each term, after its definition, up to three lines:

- **In the code:** where it is defined, by link;
- **User-facing:** the names that a user or an agent types, reads or stores for it, in
  [commands](commands.md), [settings](settings.md), [the MCP server's
  tools](mcp-tools.md), [the data layout](data-layout.md) or
  [telemetry](telemetry/README.md);
- **Retires:** the names that no longer mean it, nor anything else, in the code or the
  docs, with any file that keeps one, as "(kept in ...)".

A word retired in one sense alone is said in the definition, as "Not ...", since it
keeps its other sense. `tests/test_glossary.py` holds the code and the docs to these
lines. The records of plans, under [`docs/work/`](../work/README.md), keep the words
of their time.

## Sources and fetching

### source

A provider of documents, declared once in the registry: `confluence`, `jira` or
`worklog`. Its name is also its settings table, its folders and the front matter's
`source`. Records before 052 call its declaration `Declared`; their `Source` is the
work log's org text or the sync command's source.

- In the code: [`Source`](../../src/kb_mcp/sources/declaration.py),
  [`SOURCES`](../../src/kb_mcp/sources/registry.py).
- User-facing: `source`, `sources.confluence.spaces`.
- Retires: `Declared`, "source type".

### resource type

What a source reads, named in the plural, which is also a folder of its raw store:
`pages`, `blogposts`, `issues`, `entries`, `days`, `meetings`, `transcripts`. Each is
read one way: `listed`, `searched` or `in place`. Not "kind".

- In the code: [`ResourceType`](../../src/kb_mcp/sources/declaration.py),
  [names.py](../../src/kb_mcp/sources/atlassian/fetch/domain/names.py),
  [`Source.resource_types`](../../src/kb_mcp/sources/declaration.py),
  [`Reading`](../../src/kb_mcp/sources/declaration.py).

### document type

A document's type, named in the singular, as its front matter's `type` says: `page`,
`blogpost`, `issue`, `entry`, `day`, `meeting`, `transcript`. Not "kind", which a
setting's kind, a panel of the site's HTML, an org link and telemetry keep.

- In the code: [`FrontMatter.type`](../../src/kb_mcp/mirror/domain/mirror.py),
  [`TYPES`](../../src/kb_mcp/sources/atlassian/prepare/domain/catalogue.py),
  [`WORKLOG_IDS`](../../src/kb_mcp/kernel/names.py).
- User-facing: `type`.

### stage

One of `fetch`, `prepare`, `index`, `embed` and `serve`, each a command. A source takes
part in `fetch` by its fetcher, which brings what changed into its raw store, and in
`prepare` by its preparers, which write its documents into the mirror. Not "role", which
a person keeps, nor "step".

- In the code: [stages.py](../../src/kb_mcp/sources/stages.py),
  [`Fetcher`](../../src/kb_mcp/sources/stages.py),
  [`Preparer`](../../src/kb_mcp/sources/stages.py).
- Retires: `roles.py`.

### account

An account on the Atlassian site, the Cloud instance by its address, known by its
account id. The program signs in with the user's own: the account's declaration says
how, and the table `[accounts.atlassian]` sets it. `users.json` names the others, each a
site user, and a person role holds one's id. Not "sign-in", nor "user" or "author" for a
site user.

- In the code: [`Account`](../../src/kb_mcp/sources/declaration.py),
  [`AtlassianAccountTable`](../../src/kb_mcp/sources/atlassian/settings.py),
  [`SiteUser`](../../src/kb_mcp/sources/atlassian/fetch/domain/content.py),
  [`SiteUser.account_id`](../../src/kb_mcp/sources/atlassian/fetch/domain/content.py),
  [`SiteClient`](../../src/kb_mcp/sources/atlassian/fetch/adapters/http.py).
- User-facing: `accounts.atlassian.site`, `users.json`, `account`.

### sign-in

How one run proves who it is to the site: the saved session, its cookies and a browser
profile under `<data>/session/`, or an API token.

- In the code: [`SignIn`](../../src/kb_mcp/sources/atlassian/fetch/adapters/sign_in.py),
  [`SavedSession`](../../src/kb_mcp/sources/atlassian/fetch/adapters/sign_in.py),
  [`ApiToken`](../../src/kb_mcp/sources/atlassian/fetch/adapters/sign_in.py),
  [`choose_sign_in`](../../src/kb_mcp/sources/atlassian/fetch/adapters/sign_in.py),
  [`open_sign_in_window`](../../src/kb_mcp/sources/atlassian/fetch/adapters/browser.py),
  [`is_signed_in`](../../src/kb_mcp/sources/atlassian/fetch/adapters/confluence_v2.py),
  [`is_signed_in`](../../src/kb_mcp/sources/atlassian/fetch/adapters/jira_v3.py).
- User-facing: `login`, `sign in`.

### target

A space or a project that a fetch covers. Not an evaluated index, nor the person that an
alias means.

- In the code: [`Target`](../../src/kb_mcp/sources/atlassian/fetch/domain/coverage.py).
- User-facing: `target`, `scope`.

### fetch window

The period that one fetch asks of a target, its start included and its end excluded,
and why it starts there.

- In the code: [`FetchWindow`](../../src/kb_mcp/sources/atlassian/fetch/domain/coverage.py),
  [`fetch_window`](../../src/kb_mcp/sources/atlassian/fetch/domain/coverage.py),
  [`TargetFetchWindow`](../../src/kb_mcp/sources/atlassian/fetch/app/fetching.py),
  [`Period`](../../src/kb_mcp/sources/atlassian/fetch/domain/period.py).
- User-facing: `windows`, a name of the fetch's JSON that chunking's `windows` also
  holds.
- Retires: `Window`, `TargetWindow`.

### coverage

The period of a target over which every updated document is stored, and what a fetch
did to it: extended, capped or held.

- In the code: [`Coverage`](../../src/kb_mcp/sources/atlassian/fetch/domain/coverage.py),
  [`CoverageChange`](../../src/kb_mcp/sources/atlassian/fetch/domain/coverage.py).
- User-facing: `coverage.json`, `fetch.coverage`.
- Retires: `Extension`.

### run report

One source's counts of one fetch, in `<data>/runs/<time>-<source>.json`.

- In the code: [`RunReport`](../../src/kb_mcp/sources/atlassian/fetch/app/fetching.py).
- User-facing: `runs/`.

### raw store

`<data>/raw/`: the site's responses as received, with the store's own records. Not
"the store" alone, which the vector store and the conversion cache also are.

- In the code: [`RawStore`](../../src/kb_mcp/sources/atlassian/fetch/adapters/raw_store.py),
  [`StoredSnapshot`](../../src/kb_mcp/sources/atlassian/fetch/adapters/raw_store.py),
  [`Unreadable`](../../src/kb_mcp/sources/atlassian/fetch/adapters/raw_store.py).
- User-facing: `raw/`, `store.json`.

### listing

What a space lists of its pages, blog posts and folders, as received; each document
that it names is a listed document.

- In the code: [`Listed`](../../src/kb_mcp/sources/atlassian/fetch/domain/content.py),
  [`Listed.document_class`](../../src/kb_mcp/sources/atlassian/fetch/domain/content.py).
- User-facing: `listed_at.json`, `fetch.listed`.

### snapshot

One fetched document at one revision, stored whole or not at all; a revision names one
state of a document.

- In the code: [`Snapshot`](../../src/kb_mcp/sources/atlassian/fetch/domain/content.py),
  [`REVISION`](../../src/kb_mcp/sources/atlassian/fetch/domain/content.py),
  [`FetchedDocument`](../../src/kb_mcp/sources/atlassian/fetch/domain/content.py),
  [`Page`](../../src/kb_mcp/sources/atlassian/fetch/domain/content.py),
  [`BlogPost`](../../src/kb_mcp/sources/atlassian/fetch/domain/content.py),
  [`Issue`](../../src/kb_mcp/sources/atlassian/fetch/domain/content.py).
- User-facing: `revision`.

### attachment

A file attached on the site. The raw store keeps its bytes as a blob, by SHA-256, under
`raw/blobs/`, and the mirror its copy as an asset under `docs/assets/`. Fetching an
attachment alone is a download.

- In the code: [`Attachment`](../../src/kb_mcp/sources/atlassian/fetch/domain/content.py),
  [`RawStore.put_blob`](../../src/kb_mcp/sources/atlassian/fetch/adapters/raw_store.py),
  [`ASSETS`](../../src/kb_mcp/kernel/names.py).
- User-facing: `--max-file-mb`, `fetch.file_skipped`, `raw/blobs/`, `assets/`.

## The mirror

### mirror

The Markdown files under `<data>/docs/`, which `prepare` writes. Not a verb, nor a
function for `prepare`'s work.

- In the code: the context [`kb_mcp.mirror`](../../src/kb_mcp/mirror/),
  [`Settings.docs`](../../src/kb_mcp/config/domain/settings.py).
- User-facing: `docs/`, `mirrored`.
- Retires: `mirror_layout.py`.

### document

A file of the mirror, known by its source and id, that opens with its front matter: a
YAML header whose keys are fixed in name, type and order.

- In the code: [`FrontMatter`](../../src/kb_mcp/mirror/domain/mirror.py),
  [`AtlassianFrontMatter`](../../src/kb_mcp/sources/atlassian/prepare/domain/catalogue.py),
  [`WorklogFrontMatter`](../../src/kb_mcp/sources/worklog/prepare/domain/worklog.py),
  [`FRONT_MATTER_KEYS`](../../src/kb_mcp/mirror/adapters/markdown.py).
- User-facing: `source`, `id`, `title`.

### ref

A document's key, else its id: what `read` takes besides an address or a path. Not
"handle", which a file keeps.

- In the code: [`Placed.ref`](../../src/kb_mcp/sources/atlassian/prepare/app/prepare.py).
- User-facing: `ref`.

### link

A relation, `transcript` or `summary`, from one document to another by ref. Not a link
of the site's HTML.

- In the code: [`Link`](../../src/kb_mcp/mirror/domain/mirror.py),
  [`RELATIONS`](../../src/kb_mcp/mirror/domain/mirror.py).
- User-facing: `links`, `summary`.

### conversion cache

`<data>/conversions.sqlite`: pandoc's output, by its input.

- In the code: [`Conversions`](../../src/kb_mcp/mirror/adapters/conversions.py),
  [`Conversions.drop_unused`](../../src/kb_mcp/mirror/adapters/conversions.py).
- User-facing: `conversions.sqlite`, `key`.

### problem

What a prepare did not write, and why; the work log's also says what it held back.

- In the code: [`Problem`](../../src/kb_mcp/sources/atlassian/prepare/app/prepare.py),
  [`Problem`](../../src/kb_mcp/sources/worklog/prepare/app/prepare.py).
- User-facing: `problems`, `prepare.not_mirrored`.

### fetch time

When a document's snapshot was fetched; for the work log, its org file's modification
time. Not "mirror date" in the docs' prose: the server's instructions, `status` and its
answers keep that name for it.

- In the code: [`FrontMatter.fetched_at`](../../src/kb_mcp/mirror/domain/mirror.py).
- User-facing: `fetched_at`, `mirrored`.

## The work log

### work log

The user's folder of org files, read in place and never written, whose documents are
days, meetings, entries and transcripts. Not "entries" for its entries, days and meetings
together.

- In the code: [`OrgText`](../../src/kb_mcp/sources/worklog/prepare/domain/worklog.py),
  [`OrgFile`](../../src/kb_mcp/sources/worklog/prepare/domain/org.py),
  [`Document`](../../src/kb_mcp/sources/worklog/prepare/domain/worklog.py),
  [`Problem`](../../src/kb_mcp/sources/worklog/prepare/adapters/files.py).
- User-facing: `sources.worklog.path`, `docs/worklog/`.

## People

### people

The persons of a document in their roles, as its source names them, each a person role:
`author`, `creator`, `assignee`, `commenter` or `participant`. Telemetry's and `status`'s
`people` count persons.

- In the code: [`PersonRole`](../../src/kb_mcp/mirror/domain/mirror.py),
  [`ROLES`](../../src/kb_mcp/mirror/domain/mirror.py).
- User-facing: `people`, `author`, `participant`.

### person

An identity that `index` joins from the people of every document, with an id `p-...` and
each spelling of its name that a source writes. Not "people" for a count of persons, but
in the names that telemetry and `status` keep.

- In the code: [`Person`](../../src/kb_mcp/search/domain/people.py),
  [`Person.names`](../../src/kb_mcp/search/domain/people.py).
- User-facing: `person`, `persons`, `person_names`.

### alias

A line of `aliases.toml` that says which person a name means. Not "target" for the
person meant.

- In the code: [`Alias`](../../src/kb_mcp/search/domain/people.py).
- User-facing: `aliases.toml`.

## The index and search

### index

`<data>/index.sqlite`: documents, sections, pieces and persons, which `serve` reads.

- In the code: [`SqliteIndex`](../../src/kb_mcp/search/adapters/sqlite_index.py),
  [`WordsIndex`](../../src/kb_mcp/search/domain/indexes.py),
  [`VectorIndex`](../../src/kb_mcp/search/domain/indexes.py),
  [`SearchIndex`](../../src/kb_mcp/search/domain/indexes.py).
- User-facing: `index.sqlite`, `index.built`.

### build

One write of the index, with its build id. `WORDS` is the version of what a whole build
writes from the same files.

- In the code: [`WORDS`](../../src/kb_mcp/search/domain/search.py),
  [`Report`](../../src/kb_mcp/search/app/indexing.py).
- User-facing: `build`, `words`, `index.built`.

### section

A body's part from one heading to the next.

- In the code: [`Section`](../../src/kb_mcp/search/domain/search.py).
- User-facing: `sections`, `chunks`.

### chunking

How bodies are cut into pieces: `sections`, `windows`, `section-paths` or
`small-to-big`. Not "chunk", but in the name of the index's table `chunks`.

- In the code: [`Chunker`](../../src/kb_mcp/search/domain/chunking.py),
  [`CHUNKERS`](../../src/kb_mcp/search/domain/chunking.py),
  [`passages`](../../src/kb_mcp/search/domain/chunking.py).
- User-facing: `chunking`.

### piece

The text that one vector stands for.

- In the code: [`Piece`](../../src/kb_mcp/search/domain/indexes.py),
  [`Piece.key`](../../src/kb_mcp/search/domain/indexes.py),
  [`key`](../../src/kb_mcp/search/adapters/vector_store.py).
- User-facing: `pieces`, `key`.

### vector store

`<data>/vectors.sqlite`: each vector by its piece's key, which `embed` fills and prunes.

- In the code: [`VectorStore`](../../src/kb_mcp/search/adapters/vector_store.py),
  [`refresh`](../../src/kb_mcp/search/app/indexing.py),
  [`Outcome`](../../src/kb_mcp/search/app/pruning.py).
- User-facing: `vectors.sqlite`, `index.pruned`.

### passage

A section's number, heading and text as a tool shows it: of a search hit, a snippet cut
about the match; of `ask`, the text quoted. Not "excerpt", which Confluence's macro
keeps, nor the text that a reranker scores.

- In the code: [`Passage`](../../src/kb_mcp/search/domain/search.py),
  [`Passage.snippet`](../../src/kb_mcp/search/domain/search.py),
  [`passage_of`](../../src/kb_mcp/mcp/app/tools.py),
  [`excerpts`](../../src/kb_mcp/mcp/app/tools.py),
  [`excerpt`](../../src/kb_mcp/mcp/app/responses.py),
  [`Chunker.unit`](../../src/kb_mcp/search/domain/chunking.py),
  [`UNIT`](../../src/kb_mcp/search/domain/chunking.py).
- User-facing: `kb_mcp.passages`.

## The MCP server

### tool

What `serve` offers an agent to call: `ask`, `search`, `read`, `browse` and `status`. A
prompt is a template that it serves, which calls them.

- In the code: [`Library`](../../src/kb_mcp/mcp/app/tools.py),
  [`Guide`](../../src/kb_mcp/mcp/app/surface.py).
- User-facing: `ask`, `search`, `read`, `browse`, `status`.

### hit

One document that `search` found, with its passage; a cursor names the next page of
hits.

- In the code: [`hit`](../../src/kb_mcp/mcp/app/responses.py),
  [`cursor_at`](../../src/kb_mcp/mcp/app/tools.py).
- User-facing: `cursor`.

### surface

What a server tells an agent: its instructions, each tool's description and its prompts.
`eval-agents` compares two.

- In the code: [`Surface`](../../src/kb_mcp/mcp/app/surface.py).

## Running a command

### command

One subcommand of `kb-mcp`.

- In the code: [`Command`](../../src/kb_mcp/cli/domain/command.py),
  [`PROGRAM`](../../src/kb_mcp/cli/domain/command.py),
  [`PROGRAM`](../../src/kb_mcp/observability/adapters/logs.py),
  [`NAME`](../../src/kb_mcp/cli/commands/serve.py).
- User-facing: `fetch`, `prepare`, `index`, `embed`, `serve`.

### run

One invocation of a command, with its run id, its log file and its trace.

- In the code: [`Run`](../../src/kb_mcp/observability/app/observed.py).
- User-facing: `run`, `runs`.

### refresh

The chain `fetch && prepare && index && embed`, which the user composes, as [bring every
source up to date](../how-to/refresh.md) says. A word of the docs alone: nothing in the
code is named so.

### preview

What a command writes on stderr before it acts or asks. Not "summary", which `--summary`
and the relation keep.

- In the code: [summary.py](../../src/kb_mcp/cli/domain/summary.py).

### detail

How much of a result a command writes: `short` or `detailed`.

- In the code: [`Summary`](../../src/kb_mcp/kernel/output.py),
  [`SUMMARIES`](../../src/kb_mcp/kernel/output.py).
- User-facing: `--summary`.

### exit status

0, 1, 2, 3 or 130: the outcome of a run. Not the `status` tool's index status.

- In the code: [`ExitStatus`](../../src/kb_mcp/kernel/exit_status.py).
- User-facing: `exit_status`, `status`.

## Settings and the project

### setting

One value that the settings file, an environment variable or an option gives, the
settings layers read in their order. A settings table is one TOML table of the file. Not
a bare "table" or "layer".

- In the code: [`Settings`](../../src/kb_mcp/config/domain/settings.py),
  [`Loaded`](../../src/kb_mcp/config/domain/settings.py),
  [`Entry`](../../src/kb_mcp/config/domain/settings.py),
  [`Kind`](../../src/kb_mcp/config/domain/settings.py),
  [`ConfluenceTable`](../../src/kb_mcp/sources/atlassian/settings.py),
  [`JiraTable`](../../src/kb_mcp/sources/atlassian/settings.py),
  [`WorklogTable`](../../src/kb_mcp/sources/worklog/settings.py).
- User-facing: `config.toml`, `KB_MCP_DATA_DIR`.

### data directory

Where the program keeps what it writes. The log folder, `logs.dir`, may lie elsewhere.

- In the code: [`Settings.data_dir`](../../src/kb_mcp/config/domain/settings.py).
- User-facing: `data_dir`, `logs.dir`.

### maintainer

Whoever settles a decision of the design; "the user" runs the program. A word of the
docs alone.

### managed machine

The computer that runs the program on a managed network, as [mirror the site on a managed
machine](../how-to/sso-machine.md) says. A word of the docs alone.
