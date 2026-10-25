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
what pandoc reads and of pandoc's version, keeps that file as it is: an edit elsewhere
in `todo.org`, which changes the file's time, moves no other entry's dates.

A file that breaks a bound, links out, or is not UTF-8 is named by its path alone, as
its content could be anything, and the run then removes no file: the last good copy of
each document stays until a run reads the folder whole.

## Identity that survives org's edits

Org adds a `CLOSED:` line and a logged state when an entry is closed, moves it to the
archive file when archived, and rewrites its tags and statistics cookies as the user
works. An entry's id is therefore taken from what those edits leave alone: its `:ID:`
property, else its title and `:CREATED:`, else its title. Planning lines, notes, the
keyword, tags and cookies never count. Transcripts are named by their day and file name,
so that moving one under `transcripts/archive/` keeps its id, and a copy left beside its
original is told apart by its path, with a warning.

## One front matter for every source

A work-log document takes the keys every document has, so that search and the index read
it as they read a page: its keyword as `status`, its tags as `labels`, its timestamps as
`created` and `updated`, its file as `breadcrumb`; the keys of other sources are `null`.
Keys of its own (scheduled, deadline, priority) would change every file of the mirror
and the index's schema; they wait until something filters on them.

## Untrusted, local

The work log holds the user's notes and summaries an AI wrote, and transcripts, the
word-by-word record. The server tells agents so, in its instructions and its `source`
filter, so that they quote a transcript rather than a summary of it, and check the one
against the other. It stays on this machine, as all the data does: by default `sync`
sends its text to the embedding endpoint, which must be a loopback address unless the
run is given `--allow-remote-embeddings` ([an endpoint off this
machine](../how-to/embeddings.md#reach-an-endpoint-off-this-machine)). Served to agents
it is untrusted reference data, like every page: a line in it that tells the reader
what to do is text, not an instruction.
