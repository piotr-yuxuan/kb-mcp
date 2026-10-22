# Mirror the work log

Your work log, a folder of org files, is mirrored as Markdown beside Confluence and Jira,
under `<data>/docs/worklog/`. The index and the server do not read it yet: searching it
comes with the second phase of plan 017. It is read in place, never written, and never
through git: its folder may be a git repository or under a synchronised folder, as the
data directory may not be.

## 1. Point to the folder

```toml
[sources.worklog]
path = "~/todo"   # absolute or under ~
archives = true   # false leaves out todo.org_archive, transcripts/archive/ and ARCHIVE subtrees
```

Or by variable: `ATLASSIAN_OFFLINE_MCP_SOURCES__WORKLOG__PATH` and
`ATLASSIAN_OFFLINE_MCP_SOURCES__WORKLOG__ARCHIVES`. Check it with:

```bash
atlassian-offline-mcp check
```

## 2. What is read

- `todo.org` and `todo.org_archive`: each top-level heading, with everything below it,
  is an **entry**.
- Every `*.org` file under `transcripts/`, at any depth, is a **transcript**: the
  word-by-word record.
- HTML transcripts are counted, not read.
- Names beginning with `.` or `#`, or ending in `~`, are passed over: hidden files, and
  Emacs's lock, autosave and backup files. A link is followed only inside the folder.
- A file over 32 MiB, a link out of the folder, or a file that is not UTF-8 is named by
  its path, never by its content, and the run removes nothing until it is fixed. Past
  20,000 transcripts, the first in path order are read.

Keywords are those `todo.org` declares, as org reads them: put the line that your Emacs
configuration holds in the file, such as `#+TODO: TODO WAITING | DONE`, else only `TODO`
and `DONE` are known, and another keyword stays in the title. `COMMENT` and `noexport`
subtrees are mirrored too: they are your notes.

## 3. Keep each entry in its file

An entry's title is its heading without keyword, priority, tags and statistics cookies
(`[1/3]`). Its id, and so its file, come from its `:ID:` property; else from its title
and `:CREATED:`; else from its title alone, the second of a title numbered `-2`. Closing,
retagging, ticking or archiving an entry keeps its file; renaming one keeps it only with
an `:ID:` (`M-x org-id-get-create` adds one). Two entries of one title and neither
property may swap files when reordered.

A transcript's id is the day that begins its folder's name (or its own) and its name:
`transcripts/current/2026-10-20 Tue/1.org` is `t-20261020-1`, kept when the file moves
under `transcripts/archive/`. A name with a blank, or without a day, takes a digest of
its path instead. Of two files of one id, a copy and its original, the first in path
order keeps it, and a warning names both.

## 4. Mirror it

```bash
atlassian-offline-mcp sync --include worklog
```

The files go to `<data>/docs/worklog/entries/` and `<data>/docs/worklog/transcripts/`,
as `<id>-<title>.md`. Each holds the usual front matter: the entry's keyword as its
`status` (else `current`), its tags, the file's `#+FILETAGS` and `ARCHIVE` as `labels`,
its earliest and latest timestamps as `created` and `updated` (a timestamp after the
file's last change is a plan, and does not count), its file as `breadcrumb`. A document
whose text did not change is not converted again, and its file keeps its dates, so an
edit to one entry moves no other. pandoc converts each document; a transcript's lines
stay apart.

## 5. What a change does at the next sync

- An entry edited, closed, retagged, ticked or archived keeps its id and its file. The
  file is written again only when the entry's revision changed (its text, or pandoc's
  version); an edit to one entry leaves every other entry's file, dates included, as it
  was. An entry renamed without an `:ID:` takes a new id: its old file goes and a new one
  is written.
- An entry or transcript removed loses its file, unless the run reported a problem (a
  file not read, a conversion that failed): then every file stays, until a run reads the
  work log whole.
- `archives = false` removes, at the next run, the files of the archive file's entries,
  of `transcripts/archive/` and of the entries tagged `ARCHIVE`.
- Search: `index` rebuilds the index whole from the mirror each time, so a document's
  old pieces leave search with its old text. Each piece's vector is kept in
  `<data>/vectors.sqlite` by its model and its text, so only the pieces whose text
  changed are embedded again; the vectors of text no longer mirrored stay there, unused.
  The work log takes part once the index reads it, with the second phase of plan 017,
  when `sync` also ends by rebuilding the index.
