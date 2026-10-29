# Trade-offs

Each decision that shapes atlassian-offline-mcp, as one section: what was decided, why,
what it costs, the alternative rejected, and the plan that settled it, whose record in
[`docs/work/changelog/`](../work/changelog/) holds the full reasoning and the measures.
[The internals](internals.md) say how the parts work together; this page says why they
are as they are. A decision costs something by definition: each section names its price,
so that the next person to weigh it knows what was paid.

## Reads only

Every request to the site is a GET, and nothing is ever written to Confluence or Jira.
[`Site`](../../src/atlassian_offline_mcp/sources/atlassian/adapters/http.py), the one
port for the session and the token, builds no other request ([`Site.once`](../../src/atlassian_offline_mcp/sources/atlassian/adapters/http.py)),
and the server's tools are read-only too.

- **Why.** A mirror needs nothing more, and a program that only reads can do the site no
  harm, whatever fails in it: the session or token it holds is used for reading alone.
- **Cost.** Nothing that needs a write: an agent cannot comment on a page or move an
  issue through this program, and must go to the site for that.
- **Rejected.** Write access, through the REST APIs or tools that edit pages and issues.
- **Settled** by the programme of plans, before plan 001, and held by
  [plan 004](../work/changelog/004-download.md#decisions)'s port, GET only.

## Refresh by hand

The mirror changes only when someone runs `sync`, which downloads and mirrors the site,
mirrors the work log, then rebuilds the index
([`sync`](../../src/atlassian_offline_mcp/cli/app/sync.py)), or its stages one at a time:
`download`, `mirror`, `index`. Nothing runs on a schedule, and the server never fetches
from the site.

- **Why.** The user chooses when the site is read, and is there when a session has
  expired: through single sign-on, only a person can sign in again. Coverage makes a run
  by hand cheap: without `--since`, a run fetches what changed since each target's last
  fetch ([`window`](../../src/atlassian_offline_mcp/sources/atlassian/domain/coverage.py)),
  so nobody keeps track of when the last run was, and a target never fetched takes its
  last 7 days rather than refusing the run. A project's search starts a day before its
  covered end, which stops at its first document not stored whole, so that what failed
  is asked for again; a space's listing is read whole anyway, so it is checked by
  version over its whole covered period, at no request, which finds a page moved in or
  restored with an older version. One command makes the refresh one thing to remember,
  while each stage still runs alone, to redo one after a fix.
- **Cost.** The mirror is as old as its last run. Each answer gives every document's
  mirror date, the time its snapshot was fetched, and `status` the newest, so that an
  agent can tell how old its evidence is. And catching up is not free: each run lists
  every space whole, and reads the work log whole. A project's search no longer grows
  with the age of its coverage, but misses an issue moved into it, or newly visible,
  whose last update predates the last fetch, until a `--since` reaches it, as it does
  the files of issues stored before `--max-file-mb` was raised. Its margin
  of a day bounds the clock's error: after a run on a clock more than a day ahead, the
  project's coverage ends in the future, its catch-up is skipped, said after `--until`,
  until the clock comes within a day of that end, and then starts after the edits made
  meanwhile, which only a `--since` fetches.
- **Rejected.** A schedule (cron, launchd) or a server that refreshes itself. For
  `sync`, a catch-up from the last run's time whatever failed in it, which would leave a
  lasting hole. A window from the last fetch for a space, which would miss what moved in
  and save no request. A refresh started from an MCP tool, after the user's approval, is
  planned (009), not built.
- **Settled** by the programme with the maintainer, before plan 001; catching up without
  dates by [plan 007](../work/changelog/007-incremental-refresh.md#decisions); `sync` by
  [plan 017](../work/changelog/017-modular-sources.md#what-sync-does); the catch-up from
  the last fetch, a project's end exact, by
  [plan 034](../work/changelog/034-incremental-fetch.md#decisions).

## Cookies and API tokens

A run signs in by the session saved from the user's own browser, or by an API token with
its account's email: [`sign_in`](../../src/atlassian_offline_mcp/sources/atlassian/adapters/sign_in.py)
takes the token when one is set, else the session.

- **Why.** On a managed network, single sign-on in the user's own browser is the route. Chrome opens
  for `login` alone; reads then go over httpx with the saved cookies, without a browser,
  to the same REST APIs that the site's pages read, which answer with the bodies the
  server renders. Plan 001 checked on the sandbox that these bodies hold what the browser
  shows. The token serves the sandbox, the agents that test against it, and anyone who
  has one.
- **Cost.** Cookies expire: a 401, or a redirect to sign in, stops a run with exit status
  3 until a person runs `login` again. The cookies sit in clear in `<data>/session/`,
  mode 0600, as the browser's own profile holds them. A token is in no file of the
  program: the environment gives it to one run, for instance through `sops exec-env`.
- **Rejected.** Reading the pages in a browser, which would paint every page and its
  includes, slowly, for text that REST gives directly; a token in the settings file,
  which is refused, since secrets come from the environment alone; the generic
  `ATLASSIAN_*` variables, as a token exported for another tool would then switch the
  sign-in.
- **Settled** by [plan 001](../work/changelog/001-proof-test.md#decisions) and
  [plan 004](../work/changelog/004-download.md#decisions) for the session, by
  [plan 015](../work/changelog/015-cli-and-configuration.md#sign-in-with-an-api-token)
  for the token.

## Raw first

`download` keeps each response exactly as received, in the raw store
([`RawStore`](../../src/atlassian_offline_mcp/sources/atlassian/adapters/raw_store.py));
the mirror, the index and the vectors are all derived from it, offline.

- **Why.** The site's responses and HTML "can and will unexpectedly change", in the
  maintainer's words. A response that a change breaks is still stored
  ([`Download.keep`](../../src/atlassian_offline_mcp/sources/atlassian/app/download.py)
  stores a snapshot that its adapter refuses), and once the adapter is fixed, `mirror`
  reads it again without fetching anything. A fix to the conversion is a rebuild, never
  a download.
- **Cost.** Disk: every revision fetched stays as received, a page with both its bodies,
  storage and view, and each attached file once, by its digest. A snapshot's responses are
  never rewritten, and no snapshot is removed; its record gains the files that a later run
  fetches ([`RawStore.add_blobs`](../../src/atlassian_offline_mcp/sources/atlassian/adapters/raw_store.py)).
- **Rejected.** Converting while downloading, which would fetch everything again after
  each fix of the conversion.
- **Settled** by [plan 003](../work/changelog/003-foundations.md#decisions).

## Strict reading, a module per representation

Only [the Confluence adapter](../../src/atlassian_offline_mcp/sources/atlassian/adapters/confluence_v2.py)
and [the Jira adapter](../../src/atlassian_offline_mcp/sources/atlassian/adapters/jira_v3.py)
know the JSON of their APIs, and only
[`normalise`](../../src/atlassian_offline_mcp/mirror/adapters/site_html.py)'s module
knows the site's HTML. Adapters read through
[`Fields`](../../src/atlassian_offline_mcp/kernel/fields.py), which requires every field
and raises [`RepresentationError`](../../src/atlassian_offline_mcp/kernel/fields.py)
naming its path, never its value.

- **Why.** When the site changes, the failure says where
  (`document.json.version.number: expected an integer`), and the fix stays in one
  module. A lenient reader would carry a wrong or empty value into the mirror, where an
  agent would quote it.
- **Cost.** A response that lacks a field the code reads is refused even when the field
  hardly matters: that document waits for the adapter's fix, its snapshot kept raw. Each
  absence that is allowed is named, one reader at a time.
- **Rejected.** Reading responses where they are used, or with defaults for what is
  missing; models of the site's JSON in Pydantic, which plan 015 left for later, if at
  all.
- **Settled** by [plan 003](../work/changelog/003-foundations.md#decisions), at the
  maintainer's request.

## Markdown beside MCP

The mirror is a folder of Markdown files, one per document with its front matter, under
`<data>/docs/`; the MCP server searches and reads an index built from those files alone.

- **Why.** Rendered HTML is a poor input for a language model, and pandoc
  ([`Pandoc.markdown`](../../src/atlassian_offline_mcp/mirror/adapters/pandoc.py)) writes
  the site's HTML as GitHub's Markdown. Files serve agents that prefer to search and read
  files, and any other tool; the server adds ranking, budgets and citations. As the index
  reads the files alone, the two never disagree.
- **Cost.** pandoc must be on `PATH`. What Markdown cannot hold stays as HTML (a table
  whose cells hold blocks), and a macro that only JavaScript draws is a placeholder that
  names it.
- **Rejected.** Serving the site's HTML; files alone, without search; exports to Word or
  PDF, which do not scale to a site.
- **Settled** by [plan 005](../work/changelog/005-markdown-mirror.md#goal) and
  [plan 006](../work/changelog/006-search-mcp.md#goal).

## Pandoc's conversions kept by their input

`mirror` keeps each conversion that pandoc makes in `<data>/conversions.sqlite`, under
the SHA-256 of pandoc's version line, its arguments and the HTML it was given
([`Conversions.markdown`](../../src/atlassian_offline_mcp/mirror/adapters/conversions.py)),
so that a run converts only the HTML that it has not converted before. Once its files
are written, a run deletes the conversions that it did not use
([`Conversions.prune`](../../src/atlassian_offline_mcp/mirror/adapters/conversions.py)).
Every run still reads the store and builds every document's HTML.

- **Why.** Pandoc was most of a mirror's time, one process a document whether it had
  changed or not: 27.7 of 31.2 seconds on the sandbox's store of 1,474 documents. The
  maintainer asked for the stages after the download to be incremental, and thought of
  a cache, wary that "cache invalidation is hard". Keyed by the whole of pandoc's input,
  this one has nothing to invalidate: with `--sandbox`, pandoc reads its standard input
  alone, and its version and arguments are in the key
  ([`Pandoc.html_converter`](../../src/atlassian_offline_mcp/mirror/adapters/pandoc.py));
  what else a file depends on, a link made relative, a user's name, the site, is inside
  the HTML that each run builds afresh, or in the front matter, which pandoc never
  reads. On that store, a mirror with nothing changed took 2.3 seconds, against 31.2
  from no cache, and wrote no file; [the tests](../../tests/test_mirror.py) find the
  bytes of a mirror from no cache after each kind of change.
- **Cost.** A file of about the Markdown's size, 3 MB on that store. Reading the store
  and building every document's HTML remain at each run, the 2.3 seconds there. A run
  that reports a problem deletes no conversion, as it removes no file: a store that
  reports one at every run keeps each edited document's old conversion, about 2 KB,
  until a run ends clean. The one input that the key misses is a pandoc rebuilt under
  the same version line, such as another package of one release: delete the file, which
  costs one conversion of everything and downloads nothing. A damaged file costs the
  same, as the run replaces it, says so, and converts everything
  ([`opened`](../../src/atlassian_offline_mcp/mirror/adapters/conversions.py)). The
  check that finds it sees the file's structure, each index against its table, not the
  text of each row: a row damaged in place would be given as it is, which deleting the
  file mends.
- **Rejected.** A record per document of everything its file depends on, which would
  skip the reading and the building too, at the risk of a stale file for any input it
  forgot; a cache wrapped around pandoc outside the mirror, which would count its
  conversions only after the mirror's own event, and copy its rule on problems;
  `mirror --rebuild`, which deleting the file replaces; the work log in the cache, whose
  revisions already skip what has not changed.
- **Settled** by the maintainer's answer to [plan
  034](../work/changelog/034-incremental-fetch.md#questions-for-the-user)'s fourth
  question, "Cache pandoc's output", and built by [plan
  039](../work/changelog/039-conversion-cache.md#decisions).

## People, a generic key

A document's front matter names its people under one key, `people`, one entry per
person and role, in place of the keys `author` and `assignee` that Atlassian shaped
([`FrontMatter.people`](../../src/atlassian_offline_mcp/mirror/domain/mirror.py)). An
entry gives the role, one of a closed set
([`ROLES`](../../src/atlassian_offline_mcp/mirror/domain/mirror.py)), the name as the
source gives it, the account id when the source has one, and a commenter's comment
times ([`PersonRole`](../../src/atlassian_offline_mcp/mirror/domain/mirror.py)). Each
entry is one line of the file
([`Dumper`](../../src/atlassian_offline_mcp/mirror/adapters/markdown.py)), read
strictly ([`load`](../../src/atlassian_offline_mcp/mirror/adapters/markdown.py)), as
[the data layout](../reference/data-layout.md#people) gives it. Names are kept as
written, never normalised, merged or masked
([`Catalogue.name`](../../src/atlassian_offline_mcp/mirror/domain/catalogue.py)).
`FrontMatter.author` and `FrontMatter.assignee` name the one person of each role
([`FrontMatter.author`](../../src/atlassian_offline_mcp/mirror/domain/mirror.py)), so
that what read the two keys, a hit's line among them
([`facts`](../../src/atlassian_offline_mcp/mcp/app/responses.py)), reads on.

- **Why.** Jira's creator and an issue's commenters had no key, and the maintainer's
  feedback asked for the creator among the filters, and for the comments' authors with
  their dates, as asks such as "what did a colleague say this week" are mostly
  comments. A key for each would have changed every file and the index's schema, and
  each later role another time. Read by role, one key serves every source alike, and
  the filters `author`, `creator`, `assignee` and `commenter` read one table
  ([`KEPT`](../../src/atlassian_offline_mcp/search/adapters/sqlite_index.py)). The
  creator cost no request: each stored `issue.json` holds every field of the issue
  ([`issue`](../../src/atlassian_offline_mcp/sources/atlassian/adapters/jira_v3.py)).
  Account ids are in the files, because the index is rebuilt from the files alone
  ([`entry`](../../src/atlassian_offline_mcp/search/adapters/sqlite_index.py)), and
  because a name alone cannot be told from the account id written when no name is
  known; one account id also ties together a colleague renamed between two fetches.
- **Cost.** One rewrite: every file of the mirror is written again once, and the index
  rebuilt once, at schema 4
  ([`SCHEMA`](../../src/atlassian_offline_mcp/search/adapters/sqlite_index.py)), which
  embeds nothing new; until then, the server refuses the old index, naming `sync`, or
  `mirror` then `index` where no source is configured, which write the files again
  before they rebuild the index, where `index` alone would skip every file of the old
  format
  ([`reading`](../../src/atlassian_offline_mcp/search/adapters/sqlite_index.py)). Each
  evaluation's index built before then holds every prune back, the vector store growing
  meanwhile, until `eval` rebuilds it, for each model and chunking still wanted, or
  `<data>/eval/indexes/` is deleted
  ([`prune`](../../src/atlassian_offline_mcp/search/app/pruning.py)). A program that
  read `author:` in the files reads `people`. Each person is in the index
  twice, as each label is: in the JSON from which a row gives its front matter back, and
  in the table that the filters read, both written by
  [`Writer.add`](../../src/atlassian_offline_mcp/search/adapters/sqlite_index.py). An
  issue's file has a line per commenter, not per comment. The four new filters add
  about 130 estimated tokens to what every request carries, the instructions and the
  tool listing, whose budget rose from 2,300 to 2,400, as [the
  tests](../../tests/test_surface.py) measure it over stdio. The names of `people` are
  not words of the index: a filter finds them, and words only where a body holds them,
  as a comment's heading does. A colleague renamed between two fetches appears under two
  names, which no filter yet joins by the account id.
- **Rejected.** `author` and `assignee` kept beside `people`, tied by an invariant: each
  name twice in each file, for agents and other programs to read twice. A person as a
  string, such as `author: Robin Example`: shorter, and plain text to another engine,
  but it needs a parser in `load` and a second format for dates, and leaves no room for
  the account id. `author` as whoever created a document, in every source, with
  `reporter` a role of its own, which would have changed the meaning of plan 040's
  filter: Jira's author stays its reporter, with its creator beside it. Generic names
  for the other keys that Atlassian shapes, `key`, `space`, `project`, `issue_type` and
  `version`, which nothing yet needs.
- **Settled** by [plan
  041](../work/changelog/041-people-in-documents.md#one-generic-key-in-place-of-two-atlassian-ones),
  on the maintainer's feedback, its questions answered by their defaults when the
  maintainer approved it.

## The journal split by shape

The work log's journal, a top-level heading with a day among its children, whatever its
title, is no longer one entry: each day is a document, and each meeting of a day
([`journal`](../../src/atlassian_offline_mcp/sources/worklog/domain/worklog.py)).
Both are found by their shape alone. A day is a heading at level 1 or 2 titled by one
active timestamp of a date alone, such as `<2026-10-28 Wed>`
([`date_title`](../../src/atlassian_offline_mcp/sources/worklog/domain/org.py),
[`Part.day`](../../src/atlassian_offline_mcp/sources/worklog/domain/worklog.py));
a meeting, a child of a day with `:MEETING:` or `:PARTICIPANTS:` in its drawer
([`Part.meeting`](../../src/atlassian_offline_mcp/sources/worklog/domain/worklog.py)).
A heading that org archived joins the day, or the meeting, that its `:ARCHIVE_OLPATH:`
names, and every part of one date makes one day
([`days_and_meetings`](../../src/atlassian_offline_mcp/sources/worklog/domain/worklog.py)).
A day's id is `d-` and its date; a meeting's, `m-`, its day's date and its title's
slug, numbered by start time where two share one
([`meeting_ids`](../../src/atlassian_offline_mcp/sources/worklog/domain/worklog.py)).
A meeting names its participants as its `:PARTICIPANTS:` writes them
([`participants`](../../src/atlassian_offline_mcp/sources/worklog/domain/worklog.py)),
and a transcript its speakers
([`speakers`](../../src/atlassian_offline_mcp/sources/worklog/domain/worklog.py));
a meeting links the transcript whose file its `:MEETING:` names
([`link_target`](../../src/atlassian_offline_mcp/sources/worklog/domain/org.py)),
which links it back
([`linked_back`](../../src/atlassian_offline_mcp/sources/worklog/domain/worklog.py)).
A day, a meeting and a transcript are dated by when they happened
([`start`](../../src/atlassian_offline_mcp/sources/worklog/domain/worklog.py),
[`Document.dates`](../../src/atlassian_offline_mcp/sources/worklog/domain/worklog.py)),
afresh at each run
([`mirror_worklog`](../../src/atlassian_offline_mcp/mirror/app/worklog.py)).

- **Why.** The journal was one entry of about 2 MB: a hit in any meeting named the
  whole journal, its meetings named nobody, a transcript was created at midnight,
  nothing tied a summary to its record, and the meeting files under `meetings/` were
  never read. The maintainer's feedback asked for days and meetings as documents, the
  meetings' sections kept, participants, and each summary and its transcript linked
  both ways. By shape rather than by the journal's name, so that a renamed journal, an
  older "Daily notes", and the archive file, where org writes a day at level 1 and a
  meeting archived alone with the path of its day, read alike: what Emacs 31.1's
  archiving writes was probed for it. A day's id is its date, so that archiving one
  part of a day moves nothing; a meeting's holds its title, readable in every hit, and
  never the file name that its `:MEETING:` gives, which a transcript exported again
  would change. Links are written on both files, since a program that reads one file
  cannot compute the reverse ([the data layout](../reference/data-layout.md#links)).
  With 040's created range, the meetings that someone attended this week are two
  filters, `participant` and `created_after`
  ([`KEPT`](../../src/atlassian_offline_mcp/search/adapters/sqlite_index.py)).
- **Cost.** A meeting renamed takes a new id, as an entry without `:ID:` does. Two
  meetings of one day and one slug, such as two of one title, or `Réunion d'équipe` and
  `Reunion d'equipe`, swap ids when the order of their starts changes, or, neither with
  a transcript, the order in which they are read: `todo.org` first, then the archive
  in the order org appended to it, so that archiving the first alone, or the second
  alone and then its day, swaps them; so does giving the first a transcript while the
  second has none. A top-level heading of any other purpose with a child titled by a
  date alone becomes a journal, that child a day and its other children entries; the
  child joins the day of its date that the journal's parts make, and the heading's title
  is lost: neither the day's text nor its breadcrumb, which are its first part's, holds
  it, so that a search for that title misses those notes. An archived heading joins its
  meeting by the meeting's title as org writes it in `:ARCHIVE_OLPATH:`, whose `/` org
  does not escape
  ([`Heading.outline_title`](../../src/atlassian_offline_mcp/sources/worklog/domain/org.py)):
  the longest title of the day that begins the path wins, but the day keeps a piece of
  one of two meetings of that title, which the path names alike; a title holding `//`,
  or beginning or ending with `/`, or one whose keyword `todo.org` does not declare,
  joins none, its pieces staying in the day. Times are read as written, as UTC: a
  caption tool that writes an offset from the start, `00:05`, dates its transcript at
  five past midnight. A meeting copied with its link to another day's transcript, as a recurring
  one may be, keeps the link, so that the transcript names two meetings, but its own
  day's date. In a transcript without quote blocks, a line of prose such as
  `Decision: we wait` reads as a speaker. A meeting's names and its transcript's
  speakers stay apart, as written: `Kim` and `Kim (not in the header)` are two names to
  the filter, until a person index joins them. The dates and links of
  every day, meeting and dated transcript are found again at each run, and a file
  whose own changed is written again, unconverted. One rebuild, with plan 041's: the
  index at schema 5
  ([`SCHEMA`](../../src/atlassian_offline_mcp/search/adapters/sqlite_index.py)),
  a column `links` in `documents`; the journal's text embedded again, as days and
  meetings; transcripts named with a blank, and undated ones, given new ids once; a
  bookmark to the journal's `e-` id broken. Every request carries 77 more estimated
  tokens, 59 for `participant` in the schemas of `search` and `ask` and 18 for the
  instructions' sentence: 2,471, within a standing budget raised from 2,400 to 2,500,
  as [the tests](../../tests/test_surface.py) measure it over stdio. A meeting's front
  matter at its largest, twelve participants and twelve refs per relation, each of the
  longest, reads in 3,463 of `read`'s 4,000 with the smallest slice
  ([the tests](../../tests/test_budgets.py)): `participant` is the work log's role
  alone ([`WORKLOG_ROLES`](../../src/atlassian_offline_mcp/mirror/domain/mirror.py)),
  since an issue with every other role and twelve participants would read 5,702, and
  an issue with those links 4,318, so backlinks for issue keys will need a budget of
  their own.
- **Rejected.** The journal by its name. A second heading of one date numbered `-2`,
  whose id archiving the first part would move. A second meeting of one slug numbered
  `-2`, which a title such as `Stand-up 2` holds already, so that passing over it tied
  the ids of two titles: the number follows `--`, which no slug holds. A meeting's id
  from its `:ID:`, which survives a rename and the swaps above, but needs one in every
  meeting, which org does not add by itself. A meeting's id from the file name that its
  `:MEETING:` gives. Relations between a day and its meetings, whose breadcrumb and id
  already name the day; a side table of links, and "Linked from" in `read`; participants
  joined across documents, left to plan 043; a filter by type, which `source` with a
  participant or a date already narrows.
- **Settled** by [plan
  042](../work/plans/042-work-log-days-and-meetings.md#days-and-meetings-the-rule), on
  the maintainer's feedback, its questions answered by their defaults when the
  maintainer approved it.

## SQLite FTS5

Words are indexed by SQLite's full-text engine, FTS5, in one file,
`<data>/index.sqlite`, with accents folded and bm25 weights per column: title 10, labels
3, breadcrumb 2, heading 5, body 1.

- **Why.** It comes with Python's standard library and needs no server. A build writes
  a new file aside and renames it into place
  ([`building`](../../src/atlassian_offline_mcp/search/adapters/sqlite_index.py)), and the
  server opens it read-only for each call
  ([`reading`](../../src/atlassian_offline_mcp/search/adapters/sqlite_index.py)), so a new
  build is served from the next call without a restart.
- **Cost.** No stemming: `deploy` does not find `deployment`. The weights are set by
  hand, and every `index` reads the whole mirror again.
- **Rejected.** The Porter stemmer, which knows English alone where the content mixes
  English and French ([plan 011](../work/changelog/011-search-strategies.md#deliberately-not-done)).
  No plan weighed another engine: the programme settled FTS5 with the maintainer.
- **Settled** by the programme, and built by
  [plan 006](../work/changelog/006-search-mcp.md#the-index).

## Filters on the index as it is

The filters of `search` and `ask`, the created range among them, are conditions on the
`documents` table, which no index of SQLite's covers, and those by person on the table
`people`, indexed by role and name: one scan per call lists the documents that pass
([`KEPT`](../../src/atlassian_offline_mcp/search/adapters/sqlite_index.py)). The
full-text match is still read whole and scored, and a join then drops the documents
outside that list. A sort by a date scores every match.

- **Why.** The index of schema 3 already held each column that the filters read: no
  rebuild, no change to its writer, and no setting. Schema 4 then moved the people to
  a table of their own, for another reason
  ([people, a generic key](#people-a-generic-key)), indexed as their filters read it.
- **Cost.** The scan reads every row, about 2 ms for 20,000 documents. A filter by
  person first checks the name given against those of its role, counting each name's
  documents at every call: 10 ms for an author, 42 for a commenter among 80,000
  comments. Its match then adds a search of `people` by role and name, 8 ms for a
  commenter: about 50 ms a call for a commenter. A comment range without `commenter`
  checks no name, but reads the row of every comment, 80 ms for those 80,000, since the
  table is indexed by name, not by time. FTS5 cannot use
  the list to skip anything, so a narrow filter makes a search for a common word only a
  little cheaper, 31 to 16 ms measured. A sort by a date gives up the cut at the best 5,000 documents per word, 31 ms
  for 20,000 matches before Python's own sort; with no words, SQLite sorts the documents
  that pass at each page, 2.7 ms for 20,000.
- **Rejected.** Indexes on `created` and the other columns of `documents` filtered: a
  seek rather than the scan, and a walk rather than the sort, saving a few milliseconds
  at this size, for a change of the writer and the schema, and a rebuild. An index of
  `people` by role and time, which SQLite then takes for a commenter too: a comment
  range alone in 52 ms rather than 80, a commenter's match in 77 rather than 8.
- **Settled** by [plan
  040](../work/changelog/040-jira-filters-and-sort.md#what-a-date-range-and-a-sort-cost-in-sqlite).

## Hybrid ranking, measured by `eval`

By default, `search` and `ask` rank by words and by meaning, each apart, then fuse the
two rankings by reciprocal rank: each list gives a document 1 / (60 + its rank)
([`fuse`](../../src/atlassian_offline_mcp/search/domain/search.py)). `eval` measures every
mode and chunking on golden questions, whose answers are known.

- **Why.** Words find identifiers and exact terms; meaning finds a question asked in
  other words than the page's. Fusing ranks, not scores, needs no common scale for bm25
  and cosines. And measuring keeps the default from being the one that sounds best: each
  plan wrote its bar before its run.
- **The record.** Plan 011 made hybrid search the default on the sandbox's questions.
  With the model of plan 018, hybrid search no longer beat words by 018's bar, and words
  became the default again. Plan 019 compared four chunkings: `windows` ranked best by
  hybrid search, but its rule, which asked for the evidence quoted significantly more
  often, kept `sections`. Plan 025 made hybrid search over `windows` the default, the
  maintainer's choice over both rules, knowing their numbers, which
  [the defaults](chunking.md#the-defaults-the-maintainers-choice) give: ranking
  mattered more to them than speed.
- **Cost.** A model by default: `index` and the server need an embedding endpoint
  unless `search_mode = "lexical"`. A query's 95th percentile on the development
  laptop's processor missed the bar of 200 ms set before the runs. And the sandbox's
  questions are not a real site's: the work set will decide again
  ([evaluating search](search-evaluation.md)).
- **Rejected.** Words alone and `sections`, which the rules of 018 and 019 kept; meaning
  alone, which scored higher still over `windows` on the sandbox, where the maintainer
  chose hybrid search.
- **Settled** by [plan 011](../work/changelog/011-search-strategies.md#search) for the
  modes and the measure; the defaults by [plan
  025](../work/changelog/025-windows-and-hybrid.md#settled-by-the-user), the
  maintainer's choice.

## Embeddings by any OpenAI-compatible API, not in process

No model runs in this program:
[`connect`](../../src/atlassian_offline_mcp/search/adapters/embedding.py) reaches a model
behind an OpenAI-compatible `/v1/embeddings` endpoint, by default Ollama on this machine,
which is only the example: any such server works.

- **Why.** The graphics processor does the work: Ollama on the host uses the Mac's GPU,
  where plan 011's models ran in process, on the processor. The code lost onnxruntime,
  the tokeniser, the downloader and the catalogue of model files. The model and the
  server are the user's to choose.
- **Cost.** One more program to install and keep running. Ollama lists the digest of
  each model, which its fingerprint holds
  ([`ApiEmbedder.fingerprint`](../../src/atlassian_offline_mcp/search/adapters/embedding.py)),
  so new weights call for new vectors; another server lists none, and vectors then
  follow the model's name alone. The text sent is the company's content: an address
  that is not a literal one of this machine needs `--allow-remote-embeddings` on every
  run, and https ([`refused_endpoint`](../../src/atlassian_offline_mcp/kernel/endpoint.py)).
- **Rejected.** Models in process with onnxruntime, from pinned files, as plan 011 built
  them; Ollama's own `/api/embed`, which other servers do not offer; a setting that
  allows a remote endpoint, which would allow it on every run without a word.
- **Settled** by the maintainer, in
  [plan 018](../work/changelog/018-embeddings-via-ollama.md#settled-by-the-user-not-reopened).

## A reranker on this machine, off by default

`search` and `ask` can send their first documents, after those that a query names, to a
cross-encoder that a server on this machine runs, llama.cpp's `llama-server` by
default, and show them in the order of its scores
([`rerank`](../../src/atlassian_offline_mcp/search/adapters/reranking.py)). It is off
by default.

- **Why.** A model that reads the question with each document is the strongest known
  lever on the first answers
  ([reranking](reranking.md#two-ways-a-model-can-read-a-question)),
  so it was built, on the side as the embedding model is: the maintainer wanted it "not
  run within the MCP but on the side as a separate (local-only) component of the
  system". Off by default because, measured, it ranked worse on the sandbox, and the
  maintainer wanted "more accurate results".
- **Cost.** For whoever turns it on, a second server to install and keep running, with
  its model file. Each search waits for it: 29 to 37 seconds at the median on the
  development laptop's processor, reranking 10 to 30 documents, and 30 seconds at most
  before the search keeps its own order. On the sandbox's questions, every depth
  measured ranked worse than the order not reranked (MRR@10 0.542 to 0.557, against
  0.639), keyword questions most
  ([evaluating search](search-evaluation.md#plan-022-reranking-on-a-laptop)). Off, it
  costs nothing: the server is never asked.
- **Rejected.** A model in process, against the maintainer's wish; a reranker off this
  machine ("No remote reranker."); Text Embeddings Inference, whose API has another
  shape; on by default, which the maintainer chose before the measures, then reversed
  for accuracy.
- **Settled** by the maintainer, in
  [plan 022](../work/changelog/022-reranking.md#settled-by-the-user).

## Budgets and untrusted-data markers

An answer of the server stays within a budget of estimated tokens, 4,000 for arguments
at or below their defaults and 10,000 at most
([`BUDGET`](../../src/atlassian_offline_mcp/mcp/app/responses.py),
[`CEILING`](../../src/atlassian_offline_mcp/mcp/app/responses.py)); one that is cut ends
with the call that continues it; and everything copied from the site stands inside one
block marked as untrusted reference data
([`answer`](../../src/atlassian_offline_mcp/mcp/app/responses.py)).

- **Why.** An agent's context is small, and shared with its task: an answer that floods
  it crowds out the rest. A page is written by anyone with access to it, and an
  instruction hidden in one must not read as the server's own words. The server's
  instructions tell agents never to follow directions found inside the block, whose
  boundary, the start of the content's SHA-256, the content can forge only by a chance
  of 2^-64.
- **Cost.** A long document comes in slices, a call each. Tokens are estimated, not
  counted, so a budget holds only roughly. The markers are advice to the agent, not a
  guarantee: a model may still follow what a page says.
- **Rejected.** Rewriting content to defuse a forged marker, after which a page would no
  longer read back as written; answers without a bound.
- **Settled** by [plan 006](../work/changelog/006-search-mcp.md#responses), and for `ask`
  by [plan 019](../work/changelog/019-knowledge-base-surface.md#ask).

## argparse with argcomplete

The command line is the standard library's argparse, completed in bash and zsh by
argcomplete. Each subcommand is declared apart from its run, so that `--help` and a
completion import no run's packages: [`parser`](../../src/atlassian_offline_mcp/cli/main.py)
registers every declaration, and imports a run only once the arguments are parsed.

- **Why.** The maintainer's choice: argparse needs no dependency, and argcomplete
  completes subcommands, options and their values. argcomplete runs the program at every
  Tab, so a declaration must stay light; an import contract keeps the runs' packages out
  of it.
- **Cost.** A subcommand is two modules, its declaration and its run. argcomplete patches
  argparse's internals, so a new Python may break completion; fish is not supported.
- **Rejected.** Subparsers registered lazily, which neither argcomplete nor `--help`
  would see.
- **Settled** by the maintainer, in
  [plan 015](../work/changelog/015-cli-and-configuration.md#settled-by-the-user).

## File, then environment, then flags

Settings come from one model,
[`Settings`](../../src/atlassian_offline_mcp/config/domain/settings.py), fed by three
layers, each stronger than the last: the settings file, the environment (the prefix
`ATLASSIAN_OFFLINE_MCP_`, `__` for nesting) and the flags.
[`load_settings`](../../src/atlassian_offline_mcp/config/app/settings.py) reads each layer,
merges them and keeps each value's layer.

- **Why.** The Unix convention: the file holds what stays, the environment what a
  session or a script sets, a flag what one run needs. Knowing each value's layer lets
  every command say which values it ignores, naming the layer and never the value, and
  lets `check` say where each value came from.
- **Cost.** Three places to look. A list from a stronger layer replaces a weaker one
  whole. Secrets come from the environment alone, so neither a flag nor the file can
  give a token or a key.
- **Rejected.** pydantic-settings' own sources, which would add a flag per field,
  secrets included, and cannot say which layer gave a value.
- **Settled** by the maintainer, in
  [plan 015](../work/changelog/015-cli-and-configuration.md#the-settings-one-model-three-layers).

## Telemetry off, logs that may hold titles

Each run writes a log file of JSON lines, from DEBUG, in the user's log folder; it may
hold titles, ids, paths and queries. Traces, metrics and logs go out by OpenTelemetry
only once an endpoint is set, and only to this machine.

- **Why.** In the maintainer's words, the logs "will most likely never leave any
  machine": they are there for detailed observability when needed, so they hold what
  explains a run. Telemetry carries the same titles and queries, hence off by default,
  and to a literal loopback address alone, as embeddings are.
- **Cost.** The log folder holds the company's titles: it passes the data directory's
  guard, its files are readable by their owner alone, and they go after 30 days. Seeing
  telemetry needs a container, Grafana's LGTM.
- **Rejected.** Logs without titles, which could not say which document was slow or
  failed; telemetry on by default, or to a collector elsewhere.
- **Settled** by the maintainer, in
  [plan 016](../work/changelog/016-observability-and-progress.md#settled-by-the-user);
  [observability](observability.md) explains it further.

## Data off synchronised folders and git trees

The data directory and the log folder are refused under a synchronised folder (iCloud,
`~/Library/CloudStorage`, Dropbox, OneDrive, Google Drive, `~/Desktop`, `~/Documents`)
or inside a git working tree
([`unsafe_location`](../../src/atlassian_offline_mcp/config/domain/settings.py)); a
command then stops with
[`UnsafeDataDirError`](../../src/atlassian_offline_mcp/config/app/settings.py) before
anything is written.

- **Why.** The mirror is the company's content. A synchronised folder would copy it off
  the machine, and a git tree could commit and push it: either by accident, and without
  a word.
- **Cost.** The guard judges by name: a folder named like a synchronised one is refused
  even when nothing synchronises it, and a sync client that it does not know passes.
- **Rejected.** No plan weighed another way: the rule came with the programme of plans,
  and plan 003 made every command enforce it.
- **Settled** by [plan 003](../work/changelog/003-foundations.md#decisions).
