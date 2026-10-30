# Sources

The mirror has three sources: Confluence and Jira, on the Atlassian site, and the user's
work log, a folder of org files on this machine. This page says why they are put
together as they are; [bring every source up to date](../how-to/sync.md) and [mirror the
work log](../how-to/work-log.md) say how to use them.

## Modular, and no more

`sync` needs four things of a source: its name, whether its table configures it, the
options of the period it uses, and its step. Those are three records in
`cli/domain/sync.py`, on which `cli/app/sync.py` dispatches; no interface spans fetching
or converting, since the sources share neither. Confluence and Jira share a step, one
download then one mirror of the raw store, because they share the site, the sign-in and
the store: `sources/atlassian/` stays one package. The work log skips the raw store,
since its files are already on this machine, and goes straight to the mirror.

The settings file holds a table per source, `[sources.confluence]`, `[sources.jira]`,
`[sources.worklog]`, so that adding a source adds a table and moves nothing. `sync`
takes its keys from the tables alone, and `--include` and `--exclude` choose among them.
What a run does not apply, such as the period's options for the work log, is said, not
refused: the same settings serve every run.

## The work log is read in place

The work log is the user's own folder, often a git repository, and stays theirs: the
program reads it and never writes there, never runs git, and follows a link only inside
it. Unlike the Atlassian sources, it has no raw store: re-reading it whole on every run
costs less than keeping a copy, and its files of a few megabytes are converted again
only when their text changed. A document whose file holds its revision, a digest of
what pandoc reads and of pandoc's version
([`revision`](../../src/kb_mcp/sources/worklog/prepare/domain/worklog.py)), keeps
that file's body: an edit elsewhere in `todo.org`, which changes the file's time, moves
no other entry's dates. A day, a meeting and a dated transcript are dated by their day,
and linked, afresh at each run
([`mirror_worklog`](../../src/kb_mcp/sources/worklog/prepare/app/prepare.py)): the
transcript may be saved after the meeting's notes, so a meeting's links are not part of
its revision, nor are its dates, so that a file that held another date takes its day
without a conversion. The work log gives the day of a meeting, never its time, so no
turn's time or timestamp dates a meeting or a transcript.

A file that breaks a bound, links out, or is not UTF-8 is named by its path alone, as
its content could be anything, with what it holds back
([`held_back`](../../src/kb_mcp/sources/worklog/prepare/domain/worklog.py)),
and the run then removes no file, but the old one of a document written again under
another title's path, nor writes one that the file not read builds: none
for `todo.org` or its archive, which every day, meeting and entry draws on; for a
transcript, its own alone
([`writable`](../../src/kb_mcp/sources/worklog/prepare/domain/worklog.py)). A
meeting needs nothing of its transcript but the id, which the path gives, so it is
written, linking the transcript, read or not. So the last good copy of what a file
builds stays until a run reads it, and one faulty file holds back no other document.
[The trade-offs](trade-offs.md#a-file-not-read-holds-back-its-own) give what this
costs.

## Days and meetings, found by shape

The user's journal, a top-level heading of `todo.org`, holds a heading per day, and
below a day a heading per meeting, with its participants, a link to its transcript, and
its summary, details and actions ([the
how-to](../how-to/work-log.md#the-journal-days-and-meetings)). Read as one entry, it was
one document of megabytes, whose meetings no filter or hit could tell apart; read by its
headings, each day and each meeting is a document of its own
([`journal`](../../src/kb_mcp/sources/worklog/prepare/domain/worklog.py)),
which search ranks, `read` opens and the filters narrow to. The rule reads the
outline's shape, not the journal's name: a day is a heading titled by a date alone
([`date_title`](../../src/kb_mcp/sources/worklog/prepare/domain/org.py)),
a meeting a child of a day with a meeting's property
([`Part.meeting`](../../src/kb_mcp/sources/worklog/prepare/domain/worklog.py)).
So a renamed journal reads as the old one, and so does the archive file, where org
moves a day to the top and names, in `:ARCHIVE_OLPATH:`, the day of a meeting archived
alone
([`days_and_meetings`](../../src/kb_mcp/sources/worklog/prepare/domain/worklog.py)).
[The trade-offs](trade-offs.md#the-journal-split-by-shape) give what this costs.

## Identity that survives org's edits

Org adds a `CLOSED:` line and a logged state when an entry is closed, moves it to the
archive file when archived, and rewrites its tags and statistics cookies as the user
works. An entry's id is therefore taken from what those edits leave alone: its `:ID:`
property, else its title and `:CREATED:`, else its title. Planning lines, notes, the
keyword, tags and cookies never count. A day is named by its date, so that every part
of one date, archived or not, makes one document
([`days_and_meetings`](../../src/kb_mcp/sources/worklog/prepare/domain/worklog.py));
a meeting by its day's date and its title's slug, numbered in the journal's order where
two share one
([`meeting_ids`](../../src/kb_mcp/sources/worklog/prepare/domain/worklog.py)),
so that archiving it keeps its id, but for two of one slug archived apart ([the
trade-offs](trade-offs.md#the-journal-split-by-shape)). Transcripts are named by their day and file name, or
that name's slug, never by their folders, and by their path alone, read or not
([`transcript_ids`](../../src/kb_mcp/sources/worklog/prepare/domain/worklog.py)),
so that moving one under `transcripts/archive/` keeps its id, and a copy left beside
its original is told apart by its path, with a warning. A name is a handle: no number,
order or time is read from it.

## One front matter for every source

A work-log document takes the keys every document has, so that search and the index read
it as they read a page: its keyword as `status`, its tags as `labels`, its timestamps,
or its day, as `created` and `updated`, its file and the titles above it as
`breadcrumb`; the keys of other sources are `null`. Keys of its own (scheduled,
deadline, priority) would change every file of the mirror and the index's schema; they
wait until something filters on them.

People are one key for every source, `people`, each person by role
([`FrontMatter.people`](../../src/kb_mcp/mirror/domain/mirror.py)),
rather than a key for each of Atlassian's fields. The roles are a closed set, as the
types of document are
([`ROLES`](../../src/kb_mcp/mirror/domain/mirror.py)): `author`,
`creator`, `assignee`, `commenter` and `participant`. Each source fills the roles that
it has ([`front_matter`](../../src/kb_mcp/sources/atlassian/prepare/domain/catalogue.py)): a
page or a blog post, its author; an issue, its reporter as its author, its creator, its
assignee, and each commenter with the times of their comments. The work log fills
`participant` alone
([`mirror_worklog`](../../src/kb_mcp/sources/worklog/prepare/app/prepare.py)):
a meeting's names as its `:PARTICIPANTS:` writes them
([`participants`](../../src/kb_mcp/sources/worklog/prepare/domain/worklog.py)),
a transcript's speakers
([`speakers`](../../src/kb_mcp/sources/worklog/prepare/domain/worklog.py)).
So the filters by person read every source alike
([`KEPT`](../../src/kb_mcp/search/adapters/sqlite_index.py)), and a role
that a source adds is one more value of `role`, where a key of its own would change
every file and the index's schema, as the work log's own keys would. No other source
holds `participant`, and the work log holds no other role
([`WORKLOG_ROLES`](../../src/kb_mcp/mirror/domain/mirror.py)),
so that no front matter, which `read` never cuts, names people of both kinds: an issue
with every role at its largest already fills most of a read's budget. The other keys
that Atlassian shapes, `key`, `space`, `project`, `issue_type` and `version`, stay as
they are, `null` for the other sources: nothing yet needs them generic. [The
trade-offs](trade-offs.md#people-a-generic-key) give what this costs.

Links between documents are one key too, `links`, each a relation and the other's ref
([`Link`](../../src/kb_mcp/mirror/domain/mirror.py)),
the relations a closed set
([`RELATIONS`](../../src/kb_mcp/mirror/domain/mirror.py)):
a meeting's `transcript`, and a transcript's `summary`, each meeting that links it. The
work log's step writes each link both ways
([`linked_back`](../../src/kb_mcp/sources/worklog/prepare/domain/worklog.py)),
since a program that reads one file cannot find those that link to it without reading
them all. A meeting finds its transcript by the path that its `:MEETING:` names, else by
the id that the path gives
([`Meeting.read`](../../src/kb_mcp/sources/worklog/prepare/domain/worklog.py)),
whether the file is read or not, as the link needs the id alone: org rewrites no link
when the user moves a transcript under `archive/`, and the move keeps its id.

## One person across sources

Each source names people its own way. Confluence and Jira name an account, under the
name that the site gave when the document was fetched, so that a colleague renamed
between two fetches is two names of one account. The work log names nobody by account:
a meeting as its `:PARTICIPANTS:` writes them, often with an annotation, and a
transcript as its caption tool heard its speakers, often by a first name. The files keep
every name as written, and each build of the index joins them into persons
([`joined`](../../src/kb_mcp/search/domain/people.py)), so that an agent
asks about one colleague once, whichever source named them.

The join takes what the sources and the user say, and guesses nothing. An account is a
person under each of its names, and two accounts are two persons, even of one name: the
site says they are two. A name without an account goes, by the first rule that answers
([`RULES`](../../src/kb_mcp/search/domain/people.py)), to the person
that the user's alias names; to the one account with a name of its key; for a
transcript's speaker, to the one participant of the meetings that the transcript links
to whose name's first word is the speaker's, whole
([`by_meeting`](../../src/kb_mcp/search/domain/people.py)), "Sam" to the
stand-up's "Sam Sample", but "Rob" to no "Robin Example"; else it is a person by name
alone, one for every name of its key. A key leaves out case, accents, runs of spaces
and a trailing part in brackets
([`name_key`](../../src/kb_mcp/search/domain/people.py)), so that
`Kim (not in the header)` is `Kim`, which plan 042 left to this join; but where two
such parts tell names apart, `Alex (Ops)` and `Alex (Sales)`, the join keeps them
([`Joining.key`](../../src/kb_mcp/search/domain/people.py)), as the
user or the site wrote them apart. It cannot tell such a part from a note, so that two
notes of one name part it too, and the build says so. A name that could be several
persons, the name of two accounts, a speaker whose word is two participants' first,
or one whose meeting names another than the one account of its name, is given to none of
them, and the build says so, for the user to settle by an alias.

A speaker is joined within its meeting alone, as the user wrote that meeting's
participants for it: there, one "Sam" is one person, and no alias, written for a name
anywhere, takes the speaker from that person
([`by_alias`](../../src/kb_mcp/search/domain/people.py)). Over the
whole mirror, a new colleague of the same first name would move the old one's meetings
without a word. Outside it, an answer narrowed to a person shows a one-word name alone
as perhaps the same, with the alias that would join them, unless an account is named
by that word, from which the alias would take it too, or annotations keep that word's
names apart, which the alias would join as well
([`about`](../../src/kb_mcp/mcp/app/tools.py)). The aliases are a file
that the user writes in the data directory, `aliases.toml`, read at each build
([`read_aliases`](../../src/kb_mcp/search/adapters/aliases.py)), rather
than a setting, which holds no mapping of names and is logged by every run.

Persons live in the index alone, joined whole at each build
([`Writer.join`](../../src/kb_mcp/search/adapters/sqlite_index.py)):
one account fetched late can make a name of the work log ambiguous, so persons cannot
be patched one document at a time. The files, which other programs read, name people as
their sources write them. A person's id, `p-` and a digest of its account id or its
name's key ([`person_id`](../../src/kb_mcp/search/domain/people.py)),
lets an agent choose between two namesakes without seeing an account id; it hides
nothing, since hashing a known account id gives it. Every filter by person then means a
person ([`PERSON_FILTERS`](../../src/kb_mcp/mcp/app/tools.py)): `person`
in any role, `author`, `creator`, `assignee`, `commenter` and `participant` in theirs,
under any of the person's names or by id
([`who`](../../src/kb_mcp/mcp/app/tools.py)). [The
trade-offs](trade-offs.md#persons-joined-by-account-then-exact-name) give what this
costs.

## Untrusted, local

The work log holds the user's notes and summaries an AI wrote, its days, meetings and
entries, and transcripts, the word-by-word record, which a meeting links. The server
tells agents so in its instructions
([`WORKLOG_KINDS`](../../src/kb_mcp/mcp/app/surface.py)), so that they
quote a transcript rather than a summary of it, and check the one against the other;
its `source` filter
([`SearchFilters`](../../src/kb_mcp/mcp/app/tools.py)) says it of
entries and transcripts alone, its words counted in the schemas of `search` and `ask`.
It stays on this machine, as all the data does: by default `sync` sends its text to the
embedding endpoint, which must be a loopback address unless the run is given
`--allow-remote-embeddings` ([an endpoint off this
machine](../how-to/embeddings.md#reach-an-endpoint-off-this-machine)). Served to agents
it is untrusted reference data, like every page: a line in it that tells the reader
what to do is text, not an instruction.
