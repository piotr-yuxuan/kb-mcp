# The MCP server's tools and prompts

`atlassian-offline-mcp serve`, or the command with no arguments, serves these over stdio.
Every tool is read-only and answers in text, never in structured content: compact
Markdown within a budget of estimated tokens, 4,000 for arguments at or below their
defaults and 10,000 at most, where an estimated token is three ASCII characters or one
other. Everything copied from the mirror stands inside one block marked as untrusted
reference data, whose closing marker repeats its boundary; a truncated answer ends with
`More:` and the call that continues it. A call that cannot be answered as asked is
refused with a message that says what would do.

`serve --tools` serves some of them, in this order whatever the order given: `--tools
search,read,browse,status` serves the four tools of plan 006, and nothing the server
says then names `ask`. Why the surface is so is in [the MCP
surface](../explanation/mcp-surface.md).

## Tools

### ask

Answers a question with passages to quote, the best first: one passage per document,
as many documents as fit the budget, 20 at most, then the call that continues.

- `question`: the question, in words, at most 500 characters. Issue keys and page ids
  in it put their documents first.
- `filters`: as `search`'s, below.
- `cursor`: the one that the previous answer ended with.

A passage is a line of its number, title, ref, section, heading and dates, ending as a
`search` hit's second line does; a line of the site's address (or the mirror's path)
and the `read(ref=..., section=N)` call that opens its section; then its text,
verbatim. With the filter `person`, the passages follow the person, as `search`'s hits
do. By meaning, the text is the unit of the index's chunking (see
[chunking](../explanation/chunking.md)); by words, the section
that holds the question's words best, whole up to 2,400 characters, else 2,400 of it
centred on the first of the question's words that it holds, cut to whole lines.
The setting `search_mode` gives the mode; without vectors, `ask` answers by words and
says why.

### search

Finds documents by words, issue keys, page ids or page addresses, the best first, each
with its best section's `read()` call and a snippet. A hit's second line gives its ref,
path, update and mirror date, then what the document has of its issue type, its status
unless `current`, `assignee <name>` (`unassigned` for an issue with none, which no
filter selects), `author <name>`, `creator <name>` when an issue's creator is named
otherwise than its author, and `created <day>`, such as
`Bug | Done | assignee Ada Example | author Bo Sample | created 2026-10-01`.

With the filter `person`, the block opens with the person, then a blank line: a line
of who they are and what they did, such as `Person: Sam Sample, p-0123456789abcdef:
creator 3, commenter 2; jira 4; last updated 2026-10-21.`; a line of their names as the
sources write them, by how each joined (by its account, by an alias, by name, or as a
speaker, by the meeting of each transcript), ten at most, then how many more; and a
line for each person by name alone who is perhaps the same, not joined, a one-word
name that begins one of theirs, that no account is named by and whose names are that
one person, which no annotation parts, by id, with the line of `aliases.toml` that would
join them, ten at most. Each name is cut at 60 characters. Each hit's second line then
ends with that person's roles there, in the order of the roles, a commenter's with their
comments' count and the day of the last, such as
`Sam Sample: creator, commenter 2 (last 2026-10-21)`. Other filters of people add
neither.

- `query`: the words, at most 500 characters.
- `filters`: an object of `source` (`confluence`, `jira` or `worklog`), `space`,
  `project`, `status`, `label`, `issue_type`, `person` (someone in any role, by any
  name that a source writes for them or by their id, `p-` and 16 hex digits),
  `author` (an issue's reporter, the person it is for, who may not be who created it; a
  page's creator), `creator` (who created an issue), `assignee`, `commenter` (who wrote
  one of an issue's comments), `participant` (someone at a work-log meeting, as its
  `:PARTICIPANTS:` names them, such as `Kim (not in the header)`, or a speaker of a
  transcript), `updated_after`, `created_after` and `commented_after` (included), and
  `updated_before`, `created_before` and `commented_before` (excluded). The comment
  dates narrow by one comment: the commenter's, when `commenter` is given, so that
  `{"commenter": "Bo Sample", "commented_after": "2026-10-20"}` keeps the issues that
  Bo Sample commented on since that day; else anyone's. A meeting and a transcript are
  created when they began, so that
  `{"participant": "Bo Sample", "created_after": "2026-10-26"}` keeps what Bo Sample
  attended or said since that day. Dates are ISO 8601, a date being its midnight UTC.
  The work log's days, meetings and entries are the user's notes and AI-written
  summaries, a meeting linking its transcript; its transcripts are the word-by-word
  record.

  The six filters of people each mean a person, as the index joins the names of every
  source into persons: by account, by the user's aliases, by name, and a speaker by
  the meeting of its transcript. A name matches one of a person's names whole, without
  regard to case, accents, runs of spaces or a trailing part in brackets, so that `Kim`
  is `Kim (not in the header)`, unless a second note, `Kim (late)`, parts them; of
  several persons, a name in brackets that one alone holds as written is taken, such
  as `Robin (Ops)` beside `Robin (Sales)`. It keeps the documents where that person
  holds the filter's role, under any of their names: when one account wrote both names,
  `{"creator": "Robin Sample"}` keeps the issues created as Robin Example too; a name
  that a hit cuts at 60 characters, `read` gives whole. A name or id that no person
  holds in that role is refused with the role's names, by `person` every role's, those
  that hold it first, the most used first, by documents; participants, and those of
  `person`, by meetings or documents other than transcripts first, so that the speakers
  that a caption tool writes, `You` and `Unverified`, never lead. A name that several
  persons hold there, such as two accounts of one name, or `Alex` beside `Alex (Ops)`
  and `Alex (Sales)`, which brackets tell apart, even where another person is written
  `Alex`, is refused listing ten of them at most, those of the most documents first,
  then in order of id, then how many more, each by name, id, documents by role then by
  source, and the day of the last update, such as
  `Sam Sample, p-0123456789abcdef: author 1; jira 1; last updated 2026-10-20`: give the
  id of the one meant. The other values match whole, without regard to case, accents or
  runs of spaces. Of several values that match, one is kept: the one given, else one
  that a hit shows alike, the most used first, so that a lookalike's documents are left
  out. A value that no document has, or that several have but for accents alone, is
  refused with the valid ones, those that hold it first, the most used first, by
  documents.
- `sort`: `relevance`; `updated` or `created`, newest first, by words alone and
  counting every match, after the documents that the query names; with no query, they
  list the documents that pass the filters.
- `limit`: 1 to 50 documents, 8 by default.
- `cursor`: the one that the previous answer ended with.

### read

Reads a document, or one of its sections, from a character offset, in slices. Each
slice opens with the document's title, path and mirror date, and one from the body's
start with its whole front matter, a `key: value` line each. People come there one line
per role, `author`, `creator`, `assignee`, `commenter` and `participant`, by name,
without the account id that the mirror keeps beside it, which stands for the name only
where the source gives none: ten names at most, then how many more, each commenter with
their count of comments and the day of the last, such as
`commenter: Ada Example (2, last 2026-10-21); Bo Sample (1, last 2026-10-20)`. Links
come after them, one line per relation, by the ref that `read` takes: a meeting's
`transcript`, and a transcript's `summary`, each meeting that links it, ten refs at
most, then how many more, such as `transcript: t-20261027-1`.

- `ref`: a page id, an issue key, a work-log id (`e-...`, `d-...`, `m-...` or `t-...`),
  a page's or an issue's address, or a path in the mirror, at most 300 characters.
- `section`: a section's number, from 1.
- `offset`: a character of the body to start from.
- `max_chars`: 1 to 40,000 characters, 12,000 by default.

### browse

Lists the documents of a space or a project in tree order, or those under a parent.

- `space`: a space's key.
- `project`: a project's key; give `space` or `project`, not both.
- `parent`: a page id, an issue key or an address within it.
- `limit`: 1 to 200 documents, 50 by default.
- `cursor`: the one that the previous answer ended with.

### status

Says what the mirror holds, when its index was built, and whether it searches by
meaning: the model, the pieces, and the chunking that cut them. A line counts the
persons, those in more than one source and those by name alone, of no account, then
names the names that several accounts hold, five at most, then how many more, each
with the persons holding it, such as `people: 42, 12 in more than one source, 9 by name
alone; names of several accounts: "Sam Sample" (3)`: an alias settles a name that a
source writes without an account, and a filter takes a person's id where the name is
not enough. It takes no argument.

## Prompts

A prompt is the user's to choose, as a slash command in Claude Code. Its arguments are
single words, checked before any text is written; only their values as the index holds
them enter the text. A refused argument is JSON-RPC error -32602, its message naming
the argument. A prompt is listed only when the tools it uses are served.

### brief

Read the document whole; summarise its purpose, facts, decisions, status and dates,
each cited by section. Needs `read`.

- `ref`: a page, issue or work-log id, an address or a path in the mirror.

### changes

List what changed in a space or a project since a date, through `search` by update;
summarise by theme, with refs and dates. Needs `search`.

- `scope`: `space:KEY` or `project:KEY`, since a site may use one key for both; a bare
  key is refused, naming both forms.
- `since`: an ISO 8601 date or time, such as `2026-10-01`.

### overview

Browse a space or a project, read its top documents' first sections, and say how it is
organised and what to read first. Needs `browse` and `read`.

- `scope`: `space:KEY` or `project:KEY`.
