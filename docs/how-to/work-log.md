# Mirror the work log

Your work log, a folder of org files, is mirrored as Markdown beside Confluence and Jira,
under `<data>/docs/worklog/`, indexed with them, and served to agents. It is read in
place, never written, and never through git: its folder may be a git repository or
under a synchronised folder, as the data directory may not be.

## 1. Point to the folder

```toml
[sources.worklog]
path = "~/todo"   # absolute or under ~
archives = true   # false leaves out todo.org_archive, the archive/ folders and ARCHIVE subtrees
```

Or by variable: `ATLASSIAN_OFFLINE_MCP_SOURCES__WORKLOG__PATH` and
`ATLASSIAN_OFFLINE_MCP_SOURCES__WORKLOG__ARCHIVES`. Check it with:

```bash
atlassian-offline-mcp check
```

## 2. What is read

- `todo.org` and `todo.org_archive`: the journal's **days** and **meetings**, below;
  every other top-level heading, with everything below it, is an **entry**.
- Every `*.org` file under `transcripts/` and `meetings/`, at any depth, is a
  **transcript**: the word-by-word record. `meetings/` is where a meeting's file, which
  its `:MEETING:` property links, is kept, such as `meetings/2026-10-27 Tue/1.org`.
- HTML transcripts are counted, not read.
- Names beginning with `.` or `#`, or ending in `~`, are passed over: hidden files, and
  Emacs's lock, autosave and backup files. A link is followed only inside the folder.
- A file over 32 MiB, a link out of the folder, or a file that is not UTF-8 is named by
  its path, never by its content, and the run removes nothing, nor writes what draws on
  it, until it is fixed. Past 20,000 transcripts in the two folders, the first in path
  order are read.

Keywords are those `todo.org` declares, as org reads them: put the line that your Emacs
configuration holds in the file, such as `#+TODO: TODO WAITING | DONE`, else only `TODO`
and `DONE` are known, and another keyword stays in the title. `COMMENT` and `noexport`
subtrees are mirrored too: they are your notes.

### The journal: days and meetings

The journal is found by its shape, whatever its title ("Entries", "Daily notes"): a
top-level heading with a day among its children.

```org
* Entries
** <2026-10-27 Tue>
A note of the day.
*** Payments stand-up
:PROPERTIES:
:MEETING: [[./meetings/2026-10-27 Tue/1.org]]
:PARTICIPANTS: Alex Example, Sam Sample, Kim (not in the header)
:END:
**** Summary
**** Details
**** Actions
***** TODO Send the rollback figures
** From <2026-10-05 Mon> to <2026-10-09 Fri> (summary)
```

- A **day** is a heading at level 1, or 2 below the journal, whose title is one active
  timestamp of a date alone: `<2026-10-27 Tue>`, not `<2026-10-27 Tue 10:00>` nor
  `[2026-10-27 Tue]`. It holds its own lines and its other children, such as a note or
  a task, and of each meeting the heading line alone, so that a meeting's title finds
  its day too.
- A **meeting** is a child of a day with `:MEETING:` or `:PARTICIPANTS:` in its drawer.
  It holds its subtree whole, its sections Summary, Details and Actions kept as
  headings, which search cuts at and `read` opens by number.
- The journal's other children, such as the range of days above, are entries; its own
  lines above its first child make one only when they hold text besides its planning
  line and property drawer.
- Any other top-level heading with a child titled by a date alone is a journal too: that
  child joins the day of its date, after the other parts of that day, under its own
  heading line, and the heading's title is lost, in neither the day's text nor its
  breadcrumb, which are its first part's. Give such notes a title of words, such as
  `** Sync of <2026-10-13 Tue>`, to keep them in their heading's entry.
- `:PARTICIPANTS:` names the meeting's people, separated by commas outside brackets,
  each kept as written, annotation included. `:MEETING:` links its transcript, as org
  writes a link to a file (`[[./path]]`, `[[file:path][text]]` or a path alone), from
  the folder of the org file that holds the meeting. A `:TRANSCRIPT:` URL is no link
  here.
- A transcript's people are its speakers: each line such as
  `[09:31] Alex Example: Morning.`, the time optional, read inside the file's
  `#+begin_quote` blocks when it has any, so that your notes outside them name nobody;
  else on every line, where a line of prose such as `Decision: we wait` reads as a
  speaker too.
- Archiving keeps all this: org writes a day archived at level 1 of `todo.org_archive`,
  and a meeting or a task archived alone with `:ARCHIVE_OLPATH:` naming its day, which
  it joins again, or its meeting. Every part of one date, `todo.org` first, makes one
  day. A task archived from one of two meetings of one day and title stays in the day,
  as its path names both alike.

## 3. Keep each document in its file

An entry's title is its heading without keyword, priority, tags and statistics cookies
(`[1/3]`). Its id, and so its file, come from its `:ID:` property; else from its title
and `:CREATED:`; else from its title alone, the second of a title numbered `-2`. Closing,
retagging, ticking or archiving an entry keeps its file; renaming one keeps it only with
an `:ID:` (`M-x org-id-get-create` adds one). Two entries of one title and neither
property may swap files when reordered.

A day's id is `d-` and its date, `d-20261027`. A meeting's is `m-`, its day's date and
its title's slug, `m-20261027-payments-stand-up`; a second meeting of one day and title
takes `-2`, by start time, then in order. Archiving a day or a meeting keeps its id;
renaming a meeting gives it a new one. Two meetings of one day and one title swap ids
when the order of their start times changes: when the first is archived alone and
neither has a transcript, or when the first gains a transcript and the second has none.
A distinct title avoids it.

A transcript's id is the day that begins its folder's name (or its own) and its name:
`transcripts/current/2026-10-20 Tue/1.org` is `t-20261020-1`, kept when the file moves
under `transcripts/archive/`. A name holding other characters than ASCII letters,
digits, `_` and `-` takes its slug, as a file name does: `notes on x.org` of 21 October
is `t-20261021-notes-on-x`. A file under `meetings/` takes `meeting-` before its name,
so that `meetings/2026-10-27 Tue/1.org` is `t-20261027-meeting-1`. A file without a day
takes a digest of its name. Of two files of one id, such as a copy and its original,
or two `notes.org` in two folders, the file whose folder comes first by name keeps it,
then the first in path order, and a warning names both. So archiving one, with its
folder, never hands its id to the other, unless the two folders have one name, as a
copy's may.

## 4. Mirror it

```bash
atlassian-offline-mcp sync --include worklog
```

The files go to `<data>/docs/worklog/`: `entries/` and `transcripts/` as
`<id>-<title>.md`, `days/` and `meetings/` as `<id>.md`. Each holds the usual front
matter: the heading's keyword as its `status` (else `current`), its tags, the file's
`#+FILETAGS` and `ARCHIVE` as `labels`, its file and the titles above it, or a
transcript's folders, as `breadcrumb`. A meeting's participants and a transcript's
speakers are its `people`, and each names the other in `links`:

```yaml
people:
- {role: participant, name: Alex Example}
- {role: participant, name: Sam Sample}
- {role: participant, name: Kim (not in the header)}
links:
- {relation: transcript, ref: t-20261027-meeting-1}
```

The transcript's file has `{relation: summary, ref: m-20261027-payments-stand-up}`.

Dates, as `created` and `updated`:

- An entry: its earliest and latest timestamps (a timestamp after the file's last change
  is a plan, and does not count).
- A day, a meeting and a transcript: when it happened. A day at its date's midnight; a
  transcript at its first turn's time, when it reads strictly as `HH:MM` or `HH:MM:SS`,
  else at its earliest timestamp on its day, else at its day's midnight; a meeting when
  its transcript starts on the meeting's day, else at its day's midnight. A meeting
  copied with its link to another day's transcript, as a recurring meeting may be,
  keeps the link and its own day, and that transcript names both meetings. Times are
  read as written, as UTC, as org's timestamps are: a caption tool that writes an
  offset from the start, `00:05`, dates its transcript at five past midnight.

A document whose text did not change is not converted again, and an entry's file keeps
its dates, so an edit to one entry moves no other. A day's, a meeting's and a dated
transcript's dates and links are found afresh at each run: a transcript saved later
dates and links its meeting without converting it again. pandoc converts each document;
a transcript's lines stay apart.

`sync` then rebuilds the index, by default in hybrid mode, which needs the embedding
model, served by Ollama on this machine or any other OpenAI-compatible API
([embeddings](embeddings.md)): without it, the index's row fails and `sync` exits 1,
the work log mirrored all the same. The first such run embeds the whole mirror;
`search_mode = "lexical"` indexes by words alone, without a model.

## 5. What a change does at the next sync

- An entry edited, closed, retagged, ticked or archived keeps its id and its file. The
  file is written again only when the entry's revision changed (its text, or pandoc's
  version); an edit to one entry leaves every other entry's file, dates included, as it
  was. An entry renamed without an `:ID:` takes a new id: its old file goes and a new one
  is written.
- A day or a meeting archived keeps its id and its file. A meeting renamed takes a new
  id, as an entry without `:ID:` does.
- A transcript added, removed, or moved from the path that a `:MEETING:` names changes
  the links and dates of that meeting, whose file is written again without a
  conversion.
- A `:MEETING:` that links no transcript read, through `..`, absolute, of another type,
  or to a file not read, such as one outside `transcripts/` and `meetings/`, leaves its
  meeting without a link. The run warns once, `worklog.unlinked`, with how many and the
  first: the file that its link names when it is in brackets or begins `file:` or `./`,
  else the meeting's id, a path alone included, since any text, a meeting room's URL
  among them, reads as one; never the link itself
  ([sync's telemetry](../reference/telemetry/sync.md)). It goes on: the warning holds no
  removal back.
- A document removed loses its file, unless the run reported a problem (a file not
  read, a conversion that failed): then every file stays, until a run reads the work
  log whole.
- A file not read also holds back the files that draw on it, which stay as they were:
  for `todo.org` or its archive, every file; for a transcript, every meeting's and each
  that links a meeting. The others are written as usual.
- `archives = false` removes, at the next run, the files of what the archive file holds,
  of `transcripts/archive/` and `meetings/archive/`, and of the headings tagged
  `ARCHIVE`.
- Search: `sync` ends by rebuilding the index whole from the mirror, as `index` does,
  so a document's old pieces leave search with its old text, and a document removed
  leaves search. Each piece's vector is kept in `<data>/vectors.sqlite` by its model and
  its text, so only the pieces whose text changed are embedded again; the vectors of
  text no longer mirrored are then pruned, unless an evaluation's index reads them.

## 6. Search it

`sync` ends with the index, so a server started afterwards, or already running, finds
the work log from its next call on. `search` and `ask` narrow to it with
`filters={"source": "worklog"}`; each hit's ref is the document's id, `e-…` for an
entry, `d-…` for a day, `m-…` for a meeting and `t-…` for a transcript, which `read`
opens. `read` of a meeting names its participants and its transcript, such as
`transcript: t-20261027-meeting-1`, and of a transcript each meeting that links it, as
`summary:`, so that an agent goes from a summary to its record in one call.

`filters={"participant": "Sam Sample"}` keeps the meetings that name Sam Sample and the
transcripts in which Sam Sample speaks, the name matched whole, in any case: `Kim` and
`Kim (not in the header)` are two names. With `"created_after": "2026-10-26"` beside
it, those since that day. A name that no document holds is refused with the valid
ones, those that the most meetings name first ([the tools](../reference/mcp-tools.md)).

The server tells agents what each kind is: days, meetings and entries are your notes and
the summaries an AI wrote, a meeting linking its transcript; transcripts are the
word-by-word record, which they should prefer when quoting and check a summary against.
Its text comes to them as untrusted reference data, as a page's does. `browse` lists
spaces and projects, not the work log:
`search(sort="updated", filters={"source": "worklog"})` lists its entries by their last
change, but its days, meetings and dated transcripts by when they happened, so that an
edit to an old meeting does not surface there and a day written ahead sorts first.
