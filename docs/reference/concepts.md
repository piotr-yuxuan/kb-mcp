# Concepts

The code is being conformed to these concepts, as [the roadmap](../work/README.md) says;
where a sentence here and the code differ, the code is what runs, under the names of
each entry's "In the code" paragraph.

[The entity-relationship views](concepts-er.html) draw the core concepts with their
relationships and cardinalities.

The program brings knowledge from many origins, keeps it current, and serves it to
agents with its provenance. Three concepts say where knowledge comes from: a
**connector** reads one kind of origin, a **source** is one configured instance of it,
and a **scope** is the part of a source that the user selects. Three say what knowledge
is: a **document**, cut into **sections**, and a **person**, joined from the mentions of
every document. Two serve it: a **ranking** answers a query, and a **tool** is what an
agent calls; the mirror's files are served besides. Three keep it current: a **stage**
is one step of the pipeline, a **run** is what the program does for one command, and a
**store** keeps durable data. One, **service**, is every server other than an origin
that a run sends text to, each under a rule of where it may be.

## Core concepts

Twelve concepts, in five groups:

- **Where knowledge comes from:** connector, source, scope.
- **What it is:** document, section, person.
- **How it is served:** ranking, tool; and the mirror's files, a store served as it is.
- **How it is kept current:** stage, run, store.
- **Where text is sent:** service.

A core entry may name an instance of a core concept, such as "the mirror, a derived
store", and the parts that it defines, such as a document's links or a run's outcomes.
It relies on, and links, core entries and their parts only.

### connector

**Definition.** The code that reads one kind of origin. An **origin** is a system
outside the program that holds documents, which the program reads and never writes: a
site of a cloud service, a client's own server, a folder of files on this machine, later
a repository. Confluence, Jira and the work log are kinds of origin; git, Notion or
Google Drive may be later. A connector declares, for its kind:

- its scope types, and how each fetch enumerates the documents of each: listed whole,
  searched by update time, or read in place; a scope type searched by update time also
  declares how often a whole read looks for deletions;
- its document types, which no other connector declares, and which of them are
  containers, with no body;
- how the origin's fields map onto the program's closed sets: the document properties,
  the link relations and the mention roles, with the roles that each document type
  takes;
- the issuer of the identities that its documents give, for each source;
- what a source of it needs: a location, such as an address or a folder, and, if the
  origin asks for one, a way to sign in.

A connector holds no data and no setting's value. "Connector" is not an MCP client's
connector, which kb-mcp itself is to Claude's apps.

**Composes.** Every source is of one connector, and reads one origin at its location.
The connector does a source's part of fetch, observing the origin into the source's copy
stores, and of prepare, deriving its documents into the mirror. No later stage knows a
connector.

**In the code.** The package [`sources/atlassian/`](../../src/kb_mcp/sources/atlassian/)
holds two connectors, Confluence and Jira, which share one sign-in, one raw store and
one coverage file; [`sources/worklog/`](../../src/kb_mcp/sources/worklog/) holds the
work log's. A connector's declaration is carried by
[`Source`](../../src/kb_mcp/sources/declaration.py), with
[`Source.fetcher`](../../src/kb_mcp/sources/declaration.py),
[`Source.preparers`](../../src/kb_mcp/sources/declaration.py),
[`Source.resource_types`](../../src/kb_mcp/sources/declaration.py) and
[`Source.account`](../../src/kb_mcp/sources/declaration.py); by
[`Account`](../../src/kb_mcp/sources/declaration.py), with
[`Account.login`](../../src/kb_mcp/sources/declaration.py) and
[`Account.checks`](../../src/kb_mcp/sources/declaration.py); and by
[`Reading`](../../src/kb_mcp/sources/declaration.py), the enumeration of a scope type.

### source

**Definition.** One configured instance of one connector, with a name that the user
chooses (a slug, other than `http` and `https`), its connector, its location, and its
way to sign in, as its connector defines them. Document ids are unique within a source,
so (source, id) is unique across every site and every client: two Jira sites for two
clients are two sources of one connector.

**Composes.** A source has scopes, and every document has exactly one source. Fetch and
prepare work per source. Sources whose sign-ins reach the same place may share that
sign-in's state, as their connector defines.

**In the code.** [`Source`](../../src/kb_mcp/sources/declaration.py), a declaration
whose name is also its one instance; [`SourceRun`](../../src/kb_mcp/sources/stages.py),
which binds it to its settings;
[`FrontMatter.source`](../../src/kb_mcp/mirror/domain/mirror.py) and the index's column
`documents.source`, which hold its name; the names
[`CONFLUENCE`](../../src/kb_mcp/sources/atlassian/declared.py),
[`JIRA`](../../src/kb_mcp/sources/atlassian/declared.py) and
[`WORKLOG`](../../src/kb_mcp/sources/worklog/declared.py); and the filter `source` of
[`SearchFilters`](../../src/kb_mcp/mcp/app/tools.py).

### scope

**Definition.** A part of one source that the user selects, read and tracked as a unit,
known by (source, scope type, scope key): a space, a project, the work log's folder,
later a repository. Its scope type, declared by the connector, says how its documents
are enumerated and which document types it holds. A scope keeps its **coverage** between
runs: a covered period [start, end) over which the origin was asked for every change, by
a whole read or by a search by update time, and then for each change that it listed or
returned. A change, here, is a new revision of a document or a change of what the scope
lists; an origin that keeps a document's revision when only an attachment or a label
changes (see [document](#document)) hides that change from the coverage. The coverage is
exact when every change in the period is known to be stored; an inexact period may hide
a failure. A run that asks for a period apart from the covered one leaves the coverage
as it was, so that no gap is ever claimed covered; the covered start says which older
history was never fetched. A scope's **as-of time** is the last moment at which it is
known complete: a run that leaves its coverage exact sets it to the coverage's end, and
one that leaves it inexact leaves it as it was. The coverage and the as-of time are kept
in its source's copy store, since they record what the origin answered. Not an API
token's scopes, nor an MCP client's `--scope`.

**Composes.** A scope holds documents, each in exactly one scope, and its documents form
a tree by their parents. A run selects scopes, and they are its purview. Change is found
by comparing what the origin lists or returns for the scope with what is stored: a new
revision is fetched, a document listed in another scope has moved, and a document
missing from a whole read is probed (see [document](#document)). The coverage decides
where the next fetch starts: a scope read whole is asked again from its covered start
while its coverage is inexact; a scope searched by update time ends its period at the
earliest change that it failed to store, which keeps its coverage exact; a read in place
covers its scope up to the moment of the read. A source read in place has one scope, the
whole source. A search by update time sees no deletion: only a whole read, which its
scope type may make less often, starts a document's absence. `browse` walks a scope's
tree.

**In the code.** On the fetching side:
[`Target`](../../src/kb_mcp/sources/atlassian/fetch/domain/coverage.py),
[`Coverage`](../../src/kb_mcp/sources/atlassian/fetch/domain/coverage.py), with
[`Coverage.periods`](../../src/kb_mcp/sources/atlassian/fetch/domain/coverage.py) and
[`Coverage.exact`](../../src/kb_mcp/sources/atlassian/fetch/domain/coverage.py), and
[`FetchWindow`](../../src/kb_mcp/sources/atlassian/fetch/domain/coverage.py);
[`TargetFetchWindow`](../../src/kb_mcp/sources/atlassian/fetch/app/fetching.py);
[`Listed`](../../src/kb_mcp/sources/atlassian/fetch/domain/content.py), the stored
listings and `listed_at.json`, which are what a scope listed at its last whole read. On
the serving side: [`SCOPES`](../../src/kb_mcp/mcp/app/surface.py) and
[`Library.key_of`](../../src/kb_mcp/mcp/app/tools.py); the front matter's fields `space`
and `project`, the filters of the same names, and `browse(space=, project=, parent=)`.

### document

**Definition.** A unit of content that an origin holds and a scope lists, known by its
document id (source, id). "Identity" is kept for persons. A document has:

- a document type, declared by its connector. A container type has no body: a folder of
  a document store, a directory of a repository. It has a title, a place in the tree,
  and children;
- a document key, where the origin gives one: its human key, such as `PRB-12`;
- a revision: one state of the document, known by the origin's token for it, such as a
  version number or the digest of a work-log entry's text, never by how the program
  converts it;
- a title, and properties from one closed set that the program declares and every
  connector maps onto, each saying whether tools filter, sort or search on it. Status,
  labels and subtype are filtered; a subtype is the origin's own finer kind of a
  document within its document type, from the origin's open set of values, such as an
  issue's type or a file's media type. Created and updated are filtered and sorted. URL,
  where the origin shows the document, is resolved by `read` and `search`. Version, the
  revision's number where the origin numbers its revisions, is stored and not shown.
  Breadcrumb, the titles of the places above the document, its parents' where it has
  them, is searched and put in the context prefix of some chunkings;
- a parent: the document id of the document above it at its origin, if it has one. The
  parents make the scope's tree, where a parent that is not mirrored, being outside the
  selected scopes or hidden from the sign-in, shows as an ancestor not listed;
- links: each a link relation, from a closed set: `transcript` and `summary`, and the
  document id of the document linked to. A link out of the program's remit stays text of
  the body;
- mentions of people, defined under [person](#person);
- an absence state, which only a whole read of its scope starts: present; absent,
  missing from that read; probed gone; confirmed gone. An absent document is asked for,
  and the origin answers one of three: gone, when it is deleted, hidden from the
  sign-in, or found in a scope that no source keeps; moved, when a kept scope's listing
  names it, which makes it present there; or unsettled, when it is found where no
  listing names it yet, which forgets any earlier answer of gone so that it is asked
  again on a later run. A first answer of gone makes it probed gone, and a second, on a
  later run at least a set time after the first, confirmed gone. A document missing from
  a read in place that met no problem is confirmed gone at once. Only a confirmed
  absence removes a document from the mirror. A run removes nothing while its sign-in is
  in doubt: when one scope gets more answers of gone in one run than a set count, or
  than a set share of its stored documents, the run checks the sign-in before believing
  them;
- a body, in Markdown, cut into sections, unless its type is a container, and its
  attachments, whose files lie beside its own in the mirror.

Its as-of time is its scope's. Its front matter carries its document id, scope, document
type, document key, title, revision, properties, parent, links and mentions. Two parts
are kept elsewhere: the as-of time, by its scope, and the absence state, by its source's
copy store, since it records what the origin answered. Its **ref**, how people and
agents cite it, is `<source>:<document key>`, else `<source>:<id>`; a bare key or id is
accepted wherever it is unique, and so is its URL. A ref can change when the origin
gives the document a new key (a moved issue takes one); its document id does not, unless
its connector derives the id from a name, as the work log's does from a meeting's title,
where a rename makes another document. So the front matter names a parent and a link by
document id, written `<source>:<id>`, and a rendering shows each as that document's ref.
A document's content is untrusted data: every rendering marks it as reference data,
never instructions.

**Composes.** A document belongs to one source and one scope. It becomes known when its
scope lists it, and each stage then carries a revision of it from one store to the next:
fetch into a copy store, prepare into the mirror as one file, index and embed into the
index. Which stores hold which revision is all there is to its life; whether a store
keeps its body at all is a choice about stores, not about the concept. A revision alone
does not show every change: some origins, Confluence among them, keep the version when
an attachment, a label, an archive or a comment changes ([the data layout,
"Snapshots"](data-layout.md#snapshots)), so what the scope lists, not the revision
alone, decides a document's place and absence. The mirror holds a document's file until
the document is confirmed gone.

**In the code.** [`FrontMatter`](../../src/kb_mcp/mirror/domain/mirror.py) and the body;
the same document at other stages,
[`FetchedDocument`](../../src/kb_mcp/sources/atlassian/fetch/domain/content.py),
[`Page`](../../src/kb_mcp/sources/atlassian/fetch/domain/content.py),
[`BlogPost`](../../src/kb_mcp/sources/atlassian/fetch/domain/content.py),
[`Issue`](../../src/kb_mcp/sources/atlassian/fetch/domain/content.py),
[`WorklogDocument`](../../src/kb_mcp/sources/worklog/prepare/domain/worklog.py) and
[`IndexedDocument`](../../src/kb_mcp/search/domain/search.py);
[`ref_of`](../../src/kb_mcp/mirror/domain/mirror.py); the type lists
[`TYPES`](../../src/kb_mcp/sources/atlassian/prepare/domain/catalogue.py) and
[`WORKLOG_TYPES`](../../src/kb_mcp/kernel/names.py);
[`Link`](../../src/kb_mcp/mirror/domain/mirror.py),
[`Link.ref`](../../src/kb_mcp/mirror/domain/mirror.py) and
[`RELATIONS`](../../src/kb_mcp/mirror/domain/mirror.py);
[`tree_paths`](../../src/kb_mcp/search/domain/search.py), which gives the breadcrumb;
the work log's [`revision`](../../src/kb_mcp/sources/worklog/prepare/domain/worklog.py);
[`Tombstone`](../../src/kb_mcp/sources/atlassian/fetch/domain/deletions.py),
[`CONFIRM_AFTER`](../../src/kb_mcp/sources/atlassian/fetch/domain/deletions.py),
[`too_many_gone`](../../src/kb_mcp/sources/atlassian/fetch/domain/deletions.py) and
[`MASS_COUNT`](../../src/kb_mcp/sources/atlassian/fetch/domain/deletions.py), which
carry the absence; [`SearchFilters`](../../src/kb_mcp/mcp/app/tools.py),
[`Asked.sort`](../../src/kb_mcp/mcp/app/tools.py),
[`metadata`](../../src/kb_mcp/mcp/app/responses.py) and
[`facts`](../../src/kb_mcp/mcp/app/responses.py), which serve the properties; the front
matter's keys `issue_type` and `url`, with the index's columns and the filter of the
same names, which hold subtype and URL; the wrapper `<untrusted-reference-data>` of
[`answer`](../../src/kb_mcp/mcp/app/responses.py) and the text
[`UNTRUSTED`](../../src/kb_mcp/mcp/app/surface.py).

### section

**Definition.** One part of a document's body, from one heading to the next, numbered
from 1; text before the first heading, if any, is section 1, with no heading. It is the
unit of reading, of citation (a ref plus a section number) and of matching by words. A
**chunk** is the text that one vector stands for. The **chunking** is the rule that cuts
chunks from a body and gives each its context prefix, one of a named set (`sections`,
`windows`, `section-paths`, `small-to-big`); one chunking holds for a whole index, and
it says what `ask` quotes of a chunk that matched. It cuts within each section or across
the whole body, so that a chunk may run over a heading; a chunk lies at the section that
holds its middle, and is embedded with its context prefix, so that the text embedded is
more than the chunk's. Positions in a body are offsets. No other range of a body is a
concept: any other range that a tool shows is cited by the section that holds its anchor
(a chunk's middle, the best place of the words matched, or the body's start), even where
it runs past that section; `read` pages by offset and cites no range.

**Composes.** A document's body is cut into sections. Embed cuts its chunks by the
chunking, each at one section, and gives each a vector through a service. A ranking
gives each of its documents one section, and names the chunk that matched when meaning
placed the document.

**In the code.** [`Section`](../../src/kb_mcp/search/domain/search.py),
[`sections`](../../src/kb_mcp/search/domain/search.py) and
[`Pieces`](../../src/kb_mcp/search/domain/search.py);
[`Piece`](../../src/kb_mcp/search/domain/indexes.py), a chunk;
[`Chunker`](../../src/kb_mcp/search/domain/chunking.py),
[`CHUNKERS`](../../src/kb_mcp/search/domain/chunking.py),
[`Cut`](../../src/kb_mcp/search/domain/chunking.py) and
[`windows`](../../src/kb_mcp/search/domain/chunking.py), one chunking;
[`place_of`](../../src/kb_mcp/mcp/app/tools.py),
[`snippet_of`](../../src/kb_mcp/mcp/app/tools.py) and
[`around`](../../src/kb_mcp/search/domain/chunking.py), which place the other ranges at
a section. The index's table `pieces` holds the chunks, and its table `chunks` the
sections' words.

### person

**Definition.** What the program takes for one human: the class of the mentions that the
joining rules below put together, across every source, scope and sign-in, under one
opaque person id (`p-…`). A **mention** is one role that one document gives to one name.
A document gives each of `author`, `creator` and `assignee` to one name at most, and any
other role once for each spelling and identity. A mention has:

- its document;
- a role, from one closed set that every connector maps onto: from the origin's fields,
  `author`, `creator` and `assignee`; from activity, `commenter`, with the times of the
  comments; from attendance, `participant`; from the text, `tagged`, for a person
  @-mentioned, a role that no connector extracts;
- an identity, when the origin gives one: (issuer, value), the issuer being the
  authority that issued the value, as the connector declares it for each source. Several
  sites of one cloud service may share one issuer; an origin hosted by a client issues
  its own. Equal values from two issuers never collide;
- a spelling: the name as the source writes it.

A spelling's **name key** is its normal form: casefolded, without accents, its runs of
white space made one space, and without a trailing annotation in brackets, so that
"Hélène Example" and "helene example" share a key, as do "Kim" and "Kim (late)". Where
one key's spellings carry two annotations or more, such as "Alex (Ops)" and "Alex
(Sales)", rules 3 and 5 compare them with their annotations, so that they stay apart. An
**alias** is a line of the user's `aliases.toml`: it holds a name key or an identity,
and names a person by a person id, a spelling or an identity. Each mention joins exactly
one person, by the first of these rules that answers:

1. **By identity.** A mention with an identity belongs to the person that an alias of
   that identity names, else to that identity's own person, whatever its spelling. Two
   identities are one person only when an alias says so, and that person keeps the id of
   the one that the alias names.
2. **By alias.** A mention without an identity whose name key an alias holds belongs to
   the person that the alias names: by a person id, or by a spelling, which names the
   person of the one identity whose mentions share its key, else the person by name of
   that key. An alias gives way where rule 4 gives exactly one other person. An alias
   that no mention reaches, or that names nobody or several persons, changes nothing and
   is reported as unused. Aliases do not chain.
3. **By name key.** A mention without an identity whose name key the mentions of exactly
   one identity share belongs to that identity's person. It is ambiguous instead when
   several identities share its key, or when rule 4 finds persons for it and that one is
   not among them.
4. **By attendance.** A mention without an identity, in the role `participant`, whose
   name key is one word, in a document that links by `summary` to other documents of its
   source, belongs to the one person among those documents' `participant` mentions whose
   name key's first word is that word; it is ambiguous when they are several.
5. **By name.** Any other mention without an identity belongs to the person by name of
   its name key, whom every mention that reaches this rule with that key shares.

A mention that rule 3 or rule 4 finds ambiguous, and that no alias takes, is
**ambiguous**: rule 5 joins it to the person by name of its key, and its key is reported
with every person that it could be. Each spelling records how it joined: by identity, by
alias, by attendance or by name. Rule 4 is the one partial match that joins: an
inference, not the user's word, which a namesake who took part without being listed
would mislead. Elsewhere a first word only informs: a tool that narrows to a person
shows, as "perhaps the same, not joined", each person by name whose one-word key begins
one of that person's spellings, with the alias line that would join them.

For example, a Jira issue's reporter (`author`), creator, assignee and each comment's
author (`commenter`) are mentions whose identity is the account id; a meeting of the work log names its participants by
spelling alone.

**Composes.** Persons are derived by index, after the mirror, from the mentions and the
`summary` links of every document and from the user's `aliases.toml`. Tools filter by
person and by role. Sources, scopes and sign-ins do not partition persons. A document's
`people` are its mentions; a count of persons is never called "people".

**In the code.** [`PersonRole`](../../src/kb_mcp/mirror/domain/mirror.py), a mention,
with [`PersonRole.account`](../../src/kb_mcp/mirror/domain/mirror.py), an identity's
value, and [`ROLES`](../../src/kb_mcp/mirror/domain/mirror.py) and
[`SOLE`](../../src/kb_mcp/mirror/domain/mirror.py);
[`Person`](../../src/kb_mcp/search/domain/people.py),
[`Spelling`](../../src/kb_mcp/search/domain/people.py),
[`joined`](../../src/kb_mcp/search/domain/people.py),
[`person_id`](../../src/kb_mcp/search/domain/people.py),
[`JoinOutcome`](../../src/kb_mcp/search/domain/people.py),
[`Alias`](../../src/kb_mcp/search/domain/people.py),
[`name_key`](../../src/kb_mcp/search/domain/people.py),
[`first_word`](../../src/kb_mcp/search/domain/people.py),
[`RULES`](../../src/kb_mcp/search/domain/people.py),
[`by_alias`](../../src/kb_mcp/search/domain/people.py),
[`by_name`](../../src/kb_mcp/search/domain/people.py) and
[`by_meeting`](../../src/kb_mcp/search/domain/people.py);
[`SUMMARY_LINKS`](../../src/kb_mcp/search/adapters/sqlite_index.py);
[`about`](../../src/kb_mcp/mcp/app/tools.py), which finds those perhaps the same; the
column `person_names.joined` and [`JOINED`](../../src/kb_mcp/mcp/app/responses.py),
where how a spelling joined is stored as `account`, `alias`, `meeting` or `name`;
[`SiteUser.account_id`](../../src/kb_mcp/sources/atlassian/fetch/domain/content.py) and
`users.json`.

### ranking

**Definition.** The ordered answer to a query: a sequence of sections, at most one per
document, best first by relevance, or by a date (updated or created). A document's
section is the one that placed it. Meaning places every document that a ranking by
meaning alone finds, and, in a fused ranking, a document that it ranks higher than words
do or that words did not find; the section is then that of the document's best chunk,
which the ranking names. Else it is the document's best section by words, else its
first. Documents that the query names by ref or by URL come first, pinned. A ranking
records how it was made: its mode (words, meaning, or both fused by reciprocal rank);
whether its first sections were reranked; a note of why meaning or reranking was not
used; and whether its count is whole or a lower bound. It holds no score, since the
modes' scores cannot be compared and only a reranker's judges relevance, and nothing of
how it is shown.

**Composes.** Tools show rankings as passages (see [tool](#tool)). Embedding the query
and reranking are calls to services; a reranker reads each candidate's title, heading
and the text about its best place. The evaluation scores rankings (MRR@10, Section@10).

**In the code.** [`Ranking`](../../src/kb_mcp/mcp/app/tools.py), which holds the
documents' paths and, for those that meaning placed, the section, start and end of the
chunk; [`ranking`](../../src/kb_mcp/mcp/app/tools.py),
[`reranked`](../../src/kb_mcp/mcp/app/tools.py) and
[`Reader.recent`](../../src/kb_mcp/search/adapters/sqlite_index.py).

### tool

**Definition.** An operation that the server offers an agent: `ask`, `search`, `read`,
`browse` and `status`. `serve` hosts the tools until it is stopped; it writes nothing
and is not a stage. Each answer fits a token budget, which sets the length of a page. A
cursor continues a list answer: it holds a position, the build of the index that it is
valid under, and the reranked order of a ranking's first sections, so that the next page
asks no reranker; `read` pages through a whole body, or one section, by offset instead.
A **passage** is what a tool shows of one ranked section: its number, its heading and
some of its text, made as the answer is written and never stored. `search` shows a
snippet: the opening of the chunk that matched, else lines about the words matched, else
the body's opening. `ask` shows a quote, verbatim: what the chunking quotes of the chunk
that matched, else a bounded part of the section about its best place. A **hit** is one
ranked document as `search` shows it, with its passage. The **surface** is what the
server says of its tools: its instructions, their descriptions and its prompts.

**Composes.** Tools read the index only. Beside them, the mirror is served as files: an
agent that reads files, or another program, reads them read-only, one file per document,
its front matter then its body, and knows a document by its source and id, never by its
path, which changes when the document's title or key does. `status` names the mirror's
folder, and `search` each document's path in it. `read` takes a ref, a document id, a
URL or a path in the mirror. Tools answer with rankings, with documents and their
sections, with scopes and their trees, and with the state of the index: what it holds
and when it was built.

**In the code.** [`Tool`](../../src/kb_mcp/kernel/tools.py) and
[`TOOLS`](../../src/kb_mcp/kernel/tools.py);
[`Library`](../../src/kb_mcp/mcp/app/tools.py),
[`cursor_at`](../../src/kb_mcp/mcp/app/tools.py),
[`continued`](../../src/kb_mcp/mcp/app/tools.py),
[`start_of`](../../src/kb_mcp/mcp/app/tools.py),
[`snippet_of`](../../src/kb_mcp/mcp/app/tools.py),
[`passages`](../../src/kb_mcp/mcp/app/tools.py) and
[`Shown`](../../src/kb_mcp/mcp/app/tools.py);
[`written`](../../src/kb_mcp/search/domain/reranking.py);
[`Passage`](../../src/kb_mcp/search/domain/search.py);
[`hit`](../../src/kb_mcp/mcp/app/responses.py) and
[`passage`](../../src/kb_mcp/mcp/app/responses.py);
[`BUDGET`](../../src/kb_mcp/mcp/app/responses.py),
[`PASSAGE_CHARS`](../../src/kb_mcp/search/domain/chunking.py) and
[`Chunker.quoted_span`](../../src/kb_mcp/search/domain/chunking.py);
[`Surface`](../../src/kb_mcp/mcp/app/surface.py),
[`ServedPrompt`](../../src/kb_mcp/mcp/app/surface.py) and
[`guides`](../../src/kb_mcp/mcp/app/surface.py), the prompts; the command `serve`; the
telemetry attributes `kb_mcp.hits`, which counts the documents that a ranking holds, for
`search` and `ask` alike, and `kb_mcp.passages`, the quotes of `ask`.

### stage

**Definition.** One of the four steps of the pipeline, each also the name of the command
whose run enables it alone, in this order:

- **fetch,** per source: the origin into the copy stores, by its scope types'
  enumeration;
- **prepare,** per source: the copy stores into the mirror;
- **index,** over the whole: the mirror, the scopes' as-of times and the aliases into
  the index's words and persons;
- **embed,** over the whole: the index's documents, cut into chunks by the chunking,
  into vectors, written to the index through the vector cache.

These four, in this order, are the pipeline. A stage is defined by what it reads and
writes, its grain (per source, or over the whole) and its change test, never by a run.
Each runs after the one before it, over what that one left. Each is incremental, redoing
only what its change test finds changed, and idempotent as a [run](#run) is. A connector takes part in fetch and prepare only. Not
`eval-agents prepare`, nor any other step of `eval-agents`.

**Composes.** A run applies the stages that its configuration enables, each at its grain
(see [run](#run)). Each stage knows what changed by the means of its stores: fetch
compares what a scope lists or returns with what is stored, and the work log's fetch
each document's revision with its copy's; a prepare from a raw store places every
document of its scopes again from the listings, its conversions memoised, and the work
log's prepare compares revisions and the converter's fingerprint; index compares the
files' digests, the scopes' as-of times, its fingerprint `WORDS` and the aliases'
digest; embed compares cache keys. Index and embed work on the whole, never on a run's
selection: index takes every file of the mirror that changed since the index was last
written, whichever run or person changed it, and joins persons from every document's
mentions; embed adds the chunks that the index's documents want and removes the others.
Of the stages, embed alone calls a service that computes; index asks none.

**In the code.** [`Fetcher`](../../src/kb_mcp/sources/stages.py),
[`Preparer`](../../src/kb_mcp/sources/stages.py) and
[`SourceRun`](../../src/kb_mcp/sources/stages.py); the commands `fetch`, `prepare`,
`index` and `embed`, in [`cli/commands/`](../../src/kb_mcp/cli/commands/).

### run

**Definition.** What the program does for one command, from its start until each of its
units has ended, known by its run id. One invocation starts it and any later one resumes
it; each writes its own log file and its own trace, tagged with the run id, save that
`serve` makes a trace for each request.

Its **configuration** is the named values that decide it, each taken from the strongest
layer that gives it: the options, then the environment, then the settings file, then the
value's default. A value may also have a layer of its own: the telemetry endpoint's
variable, shared with other programs, lies below the settings file, and the switch that
turns telemetry off lies above every layer. The configuration is resolved without
reading any store when the run starts, and fixed for the run:

- the stages enabled, in pipeline order;
- its selection: all or some sources, and all or some scopes of each, which are its
  purview;
- whether it is a dry run, which writes nothing;
- every other value that it uses, each relative value made absolute against the run's
  start: `--since 7d` becomes a date, and an end left to now becomes that start; a start
  left to a scope's coverage stays a rule, which fetch applies.

A secret, which the environment alone gives, is part of the configuration but never
recorded: a resumed run takes it from its environment again. Three things belong to each
invocation, not to the configuration: the consent to send text off this machine
(`--allow-remote-embeddings`), the answer to the question asked before a run writes (or
`--yes`), and how the result is written (its format, detail and level). Not `--config`,
which names the settings file, one layer.

Its work is units, one for each enabled stage at that stage's grain: the stage applied
to one source, or over the whole; or the one unit of a command that is no stage. A unit
per source runs after the unit of the stage before for the same source, and only if that
one ended done; a whole unit runs after every unit of the stage before, over what they
left, whatever their endings. No source depends on another. Each unit gives an
**outcome**:

- counts;
- problems: items left undone, each with where and why, never content. A problem ends
  its unit failed, and makes the stage keep what it would otherwise remove;
- warnings: what a person should know that changes neither the ending nor what is
  removed, such as an ambiguous name, an unused alias, a meeting whose link reaches no
  transcript, or a mirror that changed since the index;
- an ending: done; failed; sign in again; not run, for a unit that a dry run leaves
  alone, that an interruption reached before it started, or whose unit before it on its
  source did not end done; or interrupted.

A run may also end with an ending of its own: before any unit acts, declined (the
question asked before it writes is answered otherwise than yes), refused (its
configuration, options or input are refused, a program that it needs is missing, or no
terminal is there to ask on) or interrupted; after, failed, by an error that no unit
catches. A run that stops before any unit acts exits 1 if declined, 2 if refused, 130 if
interrupted; otherwise its exit status is that of the most severe of its own ending and
its units' last endings, whichever invocation gave them: interrupted 130, sign in again
3, failed 1, else 0. A **refresh** is a run whose configuration enables every stage,
whatever its selection.

Five invariants hold:

- **Idempotent.** Resuming a run whose units have all ended done, or running its
  configuration again, with nothing changed at the origins, in the input stores, or in
  the fingerprints of the derivations, changes no document in a copy store, the mirror
  or the index, and no vector. What it may change records time and the run alone: the
  scopes' coverage and as-of times, the dates of absence states, a record under `runs/`,
  a log file, and a sign-in that the origin renewed. One change of content is by design:
  a document that one run probed gone and a later run, past the set time, confirms gone
  leaves the mirror.
- **Resumable.** Resuming a run by its id reloads its configuration, takes its secrets
  from the environment again, and does the units not yet done.
- **Within its purview.** Of the copy stores and the mirror, a run adds, changes and
  removes only what belongs to the scopes that it selects: the documents that they held
  before it or hold after it, and each scope's coverage, listing and tree. Refreshing
  one project may update its issues and remove those, and their comments, that its
  origin deleted; it leaves every other scope and source as they are. Beyond them, a run
  writes its own record, may renew the sign-in state that it used, and never writes an
  input.
- **Derived from the whole.** The index, with its persons and its vectors, is a function
  of the whole mirror, the scopes' as-of times, the aliases and the fingerprints of its
  derivations, never of a run's selection: once a run's index and embed are done, the
  index holds what a whole build from those inputs would hold. What it says of a
  document outside the purview therefore changes only as an input changed: a file of the
  mirror changed since the index was last written, by an earlier run or by hand; a
  mention within the purview that joins or parts mentions of other scopes, since persons
  are joined across every source; or a derivation of a new fingerprint. A memo store may
  lose any entry that no derived store on disk still uses, whichever scope it served, as
  losing one costs only recomputation.
- **Determined by its configuration.** How a configuration is given makes no difference:
  a long, explicit command and a generic refresh that reads the settings file give the
  same run when they resolve to the same configuration. What a run does is a function of
  that configuration, of each invocation's consent, of the stores, of the sign-in state
  of its sources, of what the origins and the services answer, and of the time at which
  each unit acts.

The configuration is resolved without state, but a run relies on state that comes before
it and that it does not create: the sign-in state of its sources, in the credential
store, and services that answer. A run checks a source's sign-in before that source's
first unit; a source whose sign-in does not hold ends "sign in again", and the others go
on. A command that is no stage of the pipeline is a run too, whose configuration enables
no stage and whose work is one unit of its own, giving one outcome: `check`, `doctor`,
`login`, `model`, `reranker`, `serve`, `eval`, `eval-rerank` and each step of
`eval-agents`. `login` writes the sign-in state that later runs rely on. `completion`
reads no settings, writes no log and no trace, and is no run.

An outcome is not the field `outcome` of an event, nor the telemetry attribute
`kb_mcp.outcome`, which say what became of one item or one step, such as a document
fetched or a vector pruned. A run is not an agent run of `eval-agents`, one question put
to an agent on one surface, known by an id such as `r001`.

**Composes.** A run applies stages over its scopes. Its configuration, secrets excepted,
and its outcomes are kept under `runs/`, by run id, and read back only to resume it. The
command line prints its outcomes, writes them as JSON and folds them into its exit
status; telemetry tags every span and event of a run with its run id.

**In the code.** [`Run`](../../src/kb_mcp/observability/app/observed.py), one
invocation, with its run id, log and trace; the event `run.start`, which logs the
settings, secrets masked. The outcome:
[`RunReport`](../../src/kb_mcp/sources/atlassian/fetch/app/fetching.py) and
[`FetchOutcome`](../../src/kb_mcp/sources/atlassian/fetch/app/fetching.py),
[`AtlassianPrepareOutcome`](../../src/kb_mcp/sources/atlassian/prepare/app/prepare.py),
[`WorklogPrepareOutcome`](../../src/kb_mcp/sources/worklog/prepare/app/prepare.py),
[`IndexReport`](../../src/kb_mcp/search/app/indexing.py) and
[`Filled`](../../src/kb_mcp/search/app/indexing.py). The ending:
[`Outcome`](../../src/kb_mcp/sources/stages.py),
[`RowOutcome`](../../src/kb_mcp/cli/domain/rows.py) and
[`RANKED`](../../src/kb_mcp/cli/domain/rows.py),
[`Verdict`](../../src/kb_mcp/sources/stages.py) and
[`Verdict.state`](../../src/kb_mcp/sources/stages.py),
[`ExitStatus`](../../src/kb_mcp/kernel/exit_status.py) and
[`MEANINGS`](../../src/kb_mcp/kernel/exit_status.py). The problem:
[`Problem`](../../src/kb_mcp/mirror/domain/mirror.py),
[`WorklogProblem`](../../src/kb_mcp/sources/worklog/prepare/app/prepare.py),
[`Unreadable`](../../src/kb_mcp/sources/atlassian/fetch/adapters/raw_store.py),
[`UnreadFile`](../../src/kb_mcp/sources/worklog/prepare/adapters/files.py) and
[`IndexReport.skipped`](../../src/kb_mcp/search/app/indexing.py).

### store

**Definition.** Durable data that the program owns and keeps between runs, with one
owner of its layout; a store that two runs may write at once has a writers' lock. All
the stores of one deployment lie under one folder, the **data directory**, which the
configuration names. A store is one of six sorts:

- **copy:** what was observed of an origin, lost unless it is observed again, kept for
  each source, though the sources of one origin may share a store: the raw store, which
  Confluence's and Jira's sources share; the work log's copy store, which holds the text
  of each document as last read whole and the time that it was first seen;
- **derived:** rebuilt from its inputs by derivations, recording the fingerprint of
  each: the mirror, the index, the evaluated indexes;
- **memo:** the results of one derivation, each under a cache key, the digest of that
  derivation's fingerprint and its input, costing only recomputation to delete: the
  conversion cache, the vector cache;
- **input:** written by the user alone, never by the program: `aliases.toml`, the golden
  files;
- **credential:** sign-in state, private to the user: the session;
- **journal:** what runs configured, did and measured, kept for people and never derived
  again: each run's configuration and outcomes under `runs/`, read back only to resume
  that run, and the evaluations' results under `eval/results/`, never read back.

A **derivation** is a function that a stage, or an evaluation, applies to stored data:
converting a body to Markdown; cutting a body into sections, words and persons; cutting
chunks; embedding a text. Its **fingerprint** names everything but its input that its
output depends on: either a digest, such as a converter's release and arguments, or an
embedding model's name, weights' digest, dimensions and prefixes with the format in
which the program asks; or a number that the code raises when the derivation changes and
a test pins, such as `WORDS`. An output of another fingerprint is stale: a derived store
derives it again, and a memo never serves it. A store's layout version, such as the
index's `SCHEMA`, is no fingerprint: it says how the store is written, and a store of
another layout is rebuilt whole. Each write of the index is a **build**, known by its
build id: a write token, never a revision of content; a cursor is valid under one build,
and a writer whose index another build replaced since it read it starts again.

Durable data outside the data directory is no store, and in no run's purview: a run's
log file belongs to its run and is kept 30 days in the log folder, each run removing
older ones; the folder that `eval-agents` writes, which the user names, belongs to the
evaluation.

**Composes.** Data flows from copies to derived stores, memos serving the derivations on
the way. The mirror is the boundary past which no connector is known. It is also the one
store served as it is: its files' paths, and its front matter's fields, their types and
their order, are an interface ([the data layout, "Reading the mirror from another
program"](data-layout.md#reading-the-mirror-from-another-program)), so that a change to
them is a served change, made by a plan that says what readers must change. Runs read
and write stores as [the data layout](data-layout.md) lists: the copy stores by fetch;
the mirror by prepare; the index by index (words, persons) and embed (vectors); the
vector cache by embed, `eval` and `eval-rerank`; the evaluated indexes by `eval`, and
the results by `eval` and `eval-rerank`; the inputs by the user alone; the credential
store by `login` and by a fetch whose sign-in is renewed; prepare also reads the mirror
as it was, and the conversion cache.

**In the code.**
[`RawStore`](../../src/kb_mcp/sources/atlassian/fetch/adapters/raw_store.py) and
[`StoredSnapshot`](../../src/kb_mcp/sources/atlassian/fetch/adapters/raw_store.py);
[`Settings.data_dir`](../../src/kb_mcp/config/domain/settings.py),
[`Settings.docs`](../../src/kb_mcp/config/domain/settings.py) and
[`write_changed`](../../src/kb_mcp/mirror/adapters/mirror_files.py);
[`SqliteIndex`](../../src/kb_mcp/search/adapters/sqlite_index.py) and
[`SCHEMA`](../../src/kb_mcp/search/adapters/sqlite_index.py);
[`Conversions`](../../src/kb_mcp/mirror/adapters/conversions.py) and
[`VectorStore`](../../src/kb_mcp/search/adapters/vector_store.py); the locks
`raw/.lock`, `index.sqlite.lock` and `vectors.sqlite.lock`. The fingerprints are
[`WORDS`](../../src/kb_mcp/search/domain/search.py), for sections, words and persons;
[`Embedded.chunking`](../../src/kb_mcp/search/domain/search.py);
[`Embedded.fingerprint`](../../src/kb_mcp/search/domain/search.py), from
[`ApiEmbedder.fingerprint`](../../src/kb_mcp/search/adapters/embedding.py); and pandoc's
converter name, version line and arguments
([`Pandoc.html_converter`](../../src/kb_mcp/mirror/adapters/pandoc.py),
[`Pandoc.org_converter`](../../src/kb_mcp/mirror/adapters/pandoc.py)). The cache keys
are [`vector_key`](../../src/kb_mcp/search/adapters/vector_store.py) and the conversion
cache's key, each the SHA-256 of a fingerprint, a NUL and the input. A server that lists
no digest of its model leaves the embedding's fingerprint blind to new weights under one
name.

### service

**Definition.** A server, other than an origin, that a run sends text to, whether drawn
from the stores or from a query: the embedding endpoint, the reranking server and the
telemetry endpoint. Each has a locality rule that every call obeys. The embedding
endpoint is on this machine, or off it over https with the user's consent, given to that
invocation alone (`--allow-remote-embeddings`, never a setting). The reranking server
and the telemetry endpoint are on this machine only, and no option widens their rule.
The embedding endpoint and the reranking server compute on the text that they receive;
the telemetry endpoint keeps what a run records, titles and names of persons among it.
An origin is not a service: its connector only reads it, asking for what it holds under
the source's sign-in, and never sends it the mirror's text. Nor is an agent, the client
that `serve` answers, nor pandoc, a program that prepare runs on this machine.

**Composes.** Of the stages, embed alone calls a service that computes: it sends the
chunks' texts to the embedding endpoint, whose results the vector cache keeps under the
embedding's fingerprint. `serve` sends each query to the embedding endpoint unless it
ranks by words alone and, when reranking is on, sends the query with each first
candidate's text to the reranking server. `eval` and `eval-rerank` do likewise for the
indexes that they evaluate and their golden questions, and `model` and `reranker` send
fixed probes. Every run sends the telemetry endpoint what it records, when one is set. A
ranking notes when it went without a service; a failing service is skipped for a while
rather than called on every query.

**In the code.** [`Service`](../../src/kb_mcp/kernel/endpoint.py),
[`EMBEDDINGS`](../../src/kb_mcp/kernel/endpoint.py) and
[`RERANKING`](../../src/kb_mcp/kernel/endpoint.py);
[`loopback`](../../src/kb_mcp/kernel/endpoint.py),
[`refused_endpoint`](../../src/kb_mcp/kernel/endpoint.py) and
[`endpoint_host`](../../src/kb_mcp/kernel/endpoint.py);
[`rerank_address`](../../src/kb_mcp/config/domain/settings.py) and
[`telemetry_address`](../../src/kb_mcp/config/domain/settings.py), which holds the
telemetry endpoint's rule; [`QUIET_S`](../../src/kb_mcp/search/app/meaning.py), how long
a failing service is skipped; the commands `model` and `reranker`; the telemetry
exporter ([the telemetry reference](telemetry/README.md)).

## Context vocabulary

Words that hold in one part of the program, each with the core entry that it belongs to.
A word that a core entry defines has no entry of its own.

### account

The Atlassian user, by email and API token or by a saved session, that a
[source](#source) of the Atlassian connectors signs in as. A person's identifier on the
site is a mention's identity (see [person](#person)).

- **In the code.** [`Account`](../../src/kb_mcp/sources/declaration.py); the settings
  `accounts.atlassian.site`, `accounts.atlassian.email` and
  `accounts.atlassian.api_token`.

### saved session

One way for an Atlassian [source](#source) to sign in: the cookies of a browser sign-in
by `login`, and its browser profile, kept in the credential [store](#store) under
`<data>/session/`; a run writes the cookies back as the site renews them.

- **In the code.**
  [`SavedSession`](../../src/kb_mcp/sources/atlassian/fetch/adapters/sign_in.py),
  [`read_cookies`](../../src/kb_mcp/sources/atlassian/fetch/adapters/session_file.py)
  and
  [`write_cookies`](../../src/kb_mcp/sources/atlassian/fetch/adapters/session_file.py).

### API token

The other way for an Atlassian [source](#source) to sign in: the account's email and a
token made on the site, a secret that the environment alone gives to each [run](#run),
and that no store keeps.

- **In the code.**
  [`ApiToken`](../../src/kb_mcp/sources/atlassian/fetch/adapters/sign_in.py) and
  [`choose_sign_in`](../../src/kb_mcp/sources/atlassian/fetch/adapters/sign_in.py).

### raw store

The copy [store](#store) of the Atlassian connectors, under `<data>/raw/`, which
Confluence's and Jira's sources share: the origin's responses as received, with the
store's own records.

- **In the code.**
  [`RawStore`](../../src/kb_mcp/sources/atlassian/fetch/adapters/raw_store.py),
  [`StoredSnapshot`](../../src/kb_mcp/sources/atlassian/fetch/adapters/raw_store.py) and
  [`Unreadable`](../../src/kb_mcp/sources/atlassian/fetch/adapters/raw_store.py).

### snapshot

A [document](#document)'s revision as received, kept raw in the raw store, stored whole
or not at all.

- **In the code.**
  [`Snapshot`](../../src/kb_mcp/sources/atlassian/fetch/domain/content.py) and
  [`StoredSnapshot`](../../src/kb_mcp/sources/atlassian/fetch/adapters/raw_store.py).

### fetch window

The period that one fetch asks of a [scope](#scope), its start included and its end
excluded, and why the period starts there.

- **In the code.**
  [`FetchWindow`](../../src/kb_mcp/sources/atlassian/fetch/domain/coverage.py),
  [`fetch_window`](../../src/kb_mcp/sources/atlassian/fetch/domain/coverage.py),
  [`TargetFetchWindow`](../../src/kb_mcp/sources/atlassian/fetch/app/fetching.py) and
  [`Period`](../../src/kb_mcp/sources/atlassian/fetch/domain/period.py).

### work log

One [source](#source) of the `worklog` connector: the user's folder of Org files, read
in place and never written, with one scope, whose documents are days, meetings, entries
and transcripts.

- **In the code.** [`WORKLOG`](../../src/kb_mcp/sources/worklog/declared.py),
  [`OrgFile`](../../src/kb_mcp/sources/worklog/prepare/domain/org.py) and
  [`WorklogDocument`](../../src/kb_mcp/sources/worklog/prepare/domain/worklog.py).

### conversion cache

The memo [store](#store) of pandoc's output, under `<data>/conversions.sqlite`, each
conversion under its cache key; prepare reads and fills it.

- **In the code.** [`Conversions`](../../src/kb_mcp/mirror/adapters/conversions.py).

### index

The derived [store](#store) that the [tools](#tool) read, under `<data>/index.sqlite`:
the documents, their sections and words, the persons and the vectors. Not the
[stage](#stage) `index`, which writes its words and persons.

- **In the code.** [`SqliteIndex`](../../src/kb_mcp/search/adapters/sqlite_index.py).

### vector cache

The memo [store](#store) of the embedding derivation, under `<data>/vectors.sqlite`:
each vector under its cache key, from the embedding's fingerprint and the text embedded.

- **In the code.** [`VectorStore`](../../src/kb_mcp/search/adapters/vector_store.py) and
  [`vector_key`](../../src/kb_mcp/search/adapters/vector_store.py).

### golden question

A question that the user writes in a golden file, an input [store](#store), with the
refs of the documents that answer it and of those that help; the evaluation scores
[rankings](#ranking) against it.

- **In the code.** [`GoldenQuestion`](../../src/kb_mcp/evaluation/domain/golden.py) and
  [`Golden`](../../src/kb_mcp/evaluation/domain/golden.py).

### measure

One number of how a [ranking](#ranking) answers a golden question, or many on average,
such as MRR@10 or Section@10.

- **In the code.** [`Measures`](../../src/kb_mcp/evaluation/domain/evaluation.py),
  [`measure`](../../src/kb_mcp/evaluation/domain/evaluation.py) and
  [`CUTOFF`](../../src/kb_mcp/evaluation/domain/evaluation.py).

### command

A subcommand of `kb-mcp`; each invocation of one is a [run](#run), save `completion`'s.

- **In the code.** [`Command`](../../src/kb_mcp/cli/domain/command.py) and
  [`PROGRAM`](../../src/kb_mcp/kernel/names.py).

### echo

What a [run](#run) writes on stderr before it acts or asks: the resolved settings and
their layers, each source's lines, and the command to copy.

- **In the code.** The module [preview.py](../../src/kb_mcp/cli/domain/preview.py), with
  [`before`](../../src/kb_mcp/cli/domain/preview.py).

### detail

One axis of how a [run](#run)'s result is written, beside its format and level: `short`
or `detailed`. JSON ignores it.

- **In the code.** [`Detail`](../../src/kb_mcp/kernel/output.py) and
  [`DETAILS`](../../src/kb_mcp/kernel/output.py); the option `--summary`.

### setting

One named value of a [run](#run)'s configuration, as a layer gives it: an option, an
environment variable, the settings file or its default.

- **In the code.** [`Settings`](../../src/kb_mcp/config/domain/settings.py),
  [`Loaded`](../../src/kb_mcp/config/domain/settings.py) and
  [`LayerValue`](../../src/kb_mcp/config/domain/settings.py).
