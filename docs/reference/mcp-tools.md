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
verbatim. By meaning, the text is the unit of the index's chunking (see
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

- `query`: the words, at most 500 characters.
- `filters`: an object of `source` (`confluence`, `jira` or `worklog`), `space`,
  `project`, `status`, `label`, `issue_type`, `author` (an issue's reporter, the person
  it is for, who may not be who created it; a page's creator), `creator` (who created
  an issue), `assignee`, `commenter` (who wrote one of an issue's comments),
  `participant` (someone at a work-log meeting, as its `:PARTICIPANTS:` names them,
  such as `Kim (not in the header)`, or a speaker of a transcript), `updated_after`,
  `created_after` and `commented_after` (included), and `updated_before`,
  `created_before` and `commented_before` (excluded). The comment dates narrow by one
  comment: the commenter's, when `commenter` is given, so that
  `{"commenter": "Bo Sample", "commented_after": "2026-10-20"}` keeps the issues that
  Bo Sample commented on since that day; else anyone's. A meeting and a transcript are
  created when they began, so that
  `{"participant": "Bo Sample", "created_after": "2026-10-26"}` keeps what Bo Sample
  attended or said since that day. Values match whole, without regard to case, accents
  or runs of spaces; a name that a hit cuts at 60 characters, `read` gives whole. Of
  several values that match, one is kept: the one given, else one that a hit shows
  alike, the most used first, so that a lookalike's documents are left out. A value
  that no document has (a name, in that role), or that several have but for accents
  alone, is refused with the valid ones, those that hold it first, the most used first,
  by documents; participants by meetings first, so that the speakers that a caption
  tool writes, `You` and `Unverified`, never lead. Dates are ISO 8601, a date being its
  midnight UTC. The work log's entries are the user's notes and AI-written summaries,
  its transcripts the word-by-word record.
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
meaning: the model, the pieces, and the chunking that cut them. It takes no argument.

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
