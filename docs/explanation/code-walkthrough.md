# A walkthrough of the code

For contributors: one run of `sync` over one Confluence space, then one `search` that an
agent makes over MCP, followed through the code in the order in which it runs. Each
step names the function or class that takes it and links its module, so that the page
reads best beside the code, one link at a time. Links name functions, never lines:
lines move, and [the docs' checks](../../tests/test_docs.py) fail once a linked name is
no longer defined in its file. [The code's layout](code-layout.md) says why each module
sits where it does; [the internals](internals.md), what each stage reads and writes and
how a failure stays within one document; [the data layout](../reference/data-layout.md),
the formats.

The run followed has a settings file that names the site and one space, and Ollama on
this machine as the embedding endpoint, the example of any OpenAI-compatible API:

```toml
site = "https://<your-site>.atlassian.net"

[sources.confluence]
spaces = ["ENG"]
```

```bash
atlassian-offline-mcp sync --since 2026-01-01
```

The space was never downloaded, so `--since` gives its first period. The search settings
keep their defaults: `search_mode` hybrid, `chunking` windows, and the model
[`DEFAULT_MODEL`](../../src/atlassian_offline_mcp/config/domain/settings.py).

## Part 1: a sync

### 1. The entry point and the parser

`pyproject.toml` makes the script `atlassian-offline-mcp` call
[`main`](../../src/atlassian_offline_mcp/cli/main.py), as `__main__.py` does for
`python -m atlassian_offline_mcp`. `main` first builds the parser with
[`parser`](../../src/atlassian_offline_mcp/cli/main.py), which imports each module of
`cli/options/` whose name does not begin with `_` and calls its `register`. Sync's
[`register`](../../src/atlassian_offline_mcp/cli/options/sync.py) adds its options and
sets one default, `command`, a
[`Command`](../../src/atlassian_offline_mcp/cli/domain/command.py): the module that runs
it, named as a string and not imported; the settings it reads; that it writes, and so
asks first; and three pure functions of the arguments and settings,
[`refused`](../../src/atlassian_offline_mcp/cli/options/sync.py),
[`unapplied`](../../src/atlassian_offline_mcp/cli/options/sync.py) and
[`described`](../../src/atlassian_offline_mcp/cli/domain/sync.py).

Nothing heavier is imported to parse: argcomplete runs the program at every Tab, and
answers before any run is imported ([why argparse and
argcomplete](trade-offs.md#argparse-with-argcomplete)). With no arguments at all, `main`
parses `serve`, which is how agents start it (part 2). Once parsed, `sync` is observed:
[`early`](../../src/atlassian_offline_mcp/observability/app/observed.py) sends warnings
to stderr until the settings are read, and `main` imports the
[`ENTRY`](../../src/atlassian_offline_mcp/cli/main.py) shared by every observed command.

### 2. Settings, the guard and the summary

[`enter`](../../src/atlassian_offline_mcp/cli/commands/_shared.py) maps each flag given to
its setting ([`Command.setting_flags`](../../src/atlassian_offline_mcp/cli/domain/command.py))
and calls [`load_settings`](../../src/atlassian_offline_mcp/config/app/settings.py). Three
layers, each stronger than the last: the file
([`read_settings_file`](../../src/atlassian_offline_mcp/config/adapters/settings_file.py)),
the environment
([`environment_entries`](../../src/atlassian_offline_mcp/config/domain/settings.py)) and
the flags. [`settings_of`](../../src/atlassian_offline_mcp/config/domain/settings.py)
merges their [`Entry`](../../src/atlassian_offline_mcp/config/domain/settings.py) rows,
weakest first, into one [`Settings`](../../src/atlassian_offline_mcp/config/domain/settings.py),
which Pydantic validates, and keeps each value's layer in a
[`Loaded`](../../src/atlassian_offline_mcp/config/domain/settings.py). A value refused is
a [`SettingsError`](../../src/atlassian_offline_mcp/config/domain/settings.py) that names
the setting and its layers, never the value.

Then the guard. The data directory, each folder under it and the log folder are resolved,
links followed, and judged by
[`unsafe_location`](../../src/atlassian_offline_mcp/config/domain/settings.py), given the
git working tree that holds each, if any
([`git_root`](../../src/atlassian_offline_mcp/config/adapters/settings_file.py)). Under a
synchronised folder, or inside a git tree, the run stops with
[`UnsafeDataDirError`](../../src/atlassian_offline_mcp/config/app/settings.py), exit 2,
before anything is written.

Then what sync cannot run with. Its
[`refused`](../../src/atlassian_offline_mcp/cli/options/sync.py) takes the sources by
[`chosen`](../../src/atlassian_offline_mcp/cli/domain/sync.py), from the three records of
[`SOURCES`](../../src/atlassian_offline_mcp/cli/domain/sync.py), and refuses the first of
these that it finds: a source that `--include` names and the settings do not configure;
nothing to sync, no source being both configured and chosen; an embedding endpoint off
this machine without `--allow-remote-embeddings`, or over plain http even with it
([`endpoint_by_meaning`](../../src/atlassian_offline_mcp/cli/options/_common.py)), except
in a dry run, which builds no index; and, with Confluence or Jira taken, a site not set
([`site_not_set`](../../src/atlassian_offline_mcp/cli/options/_common.py)), an API token
without its email
([`token_without_email`](../../src/atlassian_offline_mcp/cli/options/_common.py)) or an
option of the period that does not read
([`period_refused`](../../src/atlassian_offline_mcp/cli/options/download.py)). `enter`
adds pandoc missing from `PATH`. Each is exit 2, said on stderr alone: no run has
started, so there is no log file.

Then [`before`](../../src/atlassian_offline_mcp/cli/domain/summary.py) writes the summary
on stderr: each setting that sync reads, with its value, a secret only as set or not
([`setting_line`](../../src/atlassian_offline_mcp/cli/domain/summary.py)); the sources
taken and left out ([`described`](../../src/atlassian_offline_mcp/cli/domain/sync.py));
each value ignored, and why; and the command to copy
([`command_line`](../../src/atlassian_offline_mcp/cli/domain/command_line.py)).
[`ask`](../../src/atlassian_offline_mcp/cli/adapters/question.py) asks `Proceed? [y/N]`;
`--yes` skips the question, and with no terminal to answer it, the run is refused.

Only now does the run begin.
[`observed`](../../src/atlassian_offline_mcp/observability/app/observed.py) opens its log
file, its telemetry when an endpoint is set, and the trace's root span, named `sync`, and
logs `run.start`; `enter` then imports `cli.commands.sync` and calls its
[`run`](../../src/atlassian_offline_mcp/cli/commands/sync.py) with the arguments and the
settings loaded.

### 3. The steps of a sync

[`run`](../../src/atlassian_offline_mcp/cli/commands/sync.py) turns the settings into
steps, each a small frozen record:
[`Atlassian`](../../src/atlassian_offline_mcp/cli/app/sync.py), holding the
[`Targets`](../../src/atlassian_offline_mcp/sources/atlassian/app/download.py) that
[`targets_of`](../../src/atlassian_offline_mcp/cli/commands/download.py) reads from the
period's options, here one space and `--since`; and
[`Index`](../../src/atlassian_offline_mcp/cli/app/sync.py), holding the
[`Indexing`](../../src/atlassian_offline_mcp/search/app/indexing.py) that
[`indexing_of`](../../src/atlassian_offline_mcp/cli/commands/_embedding.py) reads from the
settings. No work log is configured, so there is no
[`Worklog`](../../src/atlassian_offline_mcp/cli/app/sync.py) step. A
[`Context`](../../src/atlassian_offline_mcp/cli/app/sync.py) carries what every step needs:
the settings, pandoc ([`Pandoc.find`](../../src/atlassian_offline_mcp/mirror/adapters/pandoc.py)),
the clock and the pause, which tests replace.

[`sync`](../../src/atlassian_offline_mcp/cli/app/sync.py) first refuses what it can before
any step: each target needs a period to start from.
[`Targets.windows`](../../src/atlassian_offline_mcp/sources/atlassian/app/download.py)
asks [`window`](../../src/atlassian_offline_mcp/sources/atlassian/domain/coverage.py),
from the coverage that the raw store holds, and a space never covered, without
`--since`, raises [`PeriodError`](../../src/atlassian_offline_mcp/sources/atlassian/domain/period.py):
exit 2, naming the space. Then each step runs in turn,
[`atlassian`](../../src/atlassian_offline_mcp/cli/app/sync.py) (a download, then the
mirror) and [`index`](../../src/atlassian_offline_mcp/cli/app/sync.py), each row within
a span `sync.step` and kept by
[`Rows.add`](../../src/atlassian_offline_mcp/cli/app/sync.py). A step runs even when the
one before it failed, as it reads what is on disk. The exit status is the first outcome
of [`RANKED`](../../src/atlassian_offline_mcp/cli/domain/sync.py) that a row had:
interrupted, then sign in, then failed; else 0.

### 4. The source and the site's port

[`atlassian`](../../src/atlassian_offline_mcp/cli/app/sync.py) calls
[`download`](../../src/atlassian_offline_mcp/sources/atlassian/app/download.py), which
opens the [`RawStore`](../../src/atlassian_offline_mcp/sources/atlassian/adapters/raw_store.py)
under `<data>/raw/` and takes its lock
([`RawStore.writing`](../../src/atlassian_offline_mcp/sources/atlassian/adapters/raw_store.py)):
a second run stops at once with
[`StoreBusyError`](../../src/atlassian_offline_mcp/sources/atlassian/adapters/raw_store.py),
and sync's download row fails while the next steps run.

The sign-in comes from
[`sign_in`](../../src/atlassian_offline_mcp/sources/atlassian/adapters/sign_in.py): an
[`ApiToken`](../../src/atlassian_offline_mcp/sources/atlassian/adapters/sign_in.py) when
the environment gives a token, else the
[`SavedSession`](../../src/atlassian_offline_mcp/sources/atlassian/adapters/sign_in.py)
that `login` saved. Either gives an httpx client built by
[`client`](../../src/atlassian_offline_mcp/sources/atlassian/adapters/http.py): TLS checked
by the system's certificates, plain http refused
([`refuse_plain_http`](../../src/atlassian_offline_mcp/sources/atlassian/adapters/http.py)),
no redirect followed by httpx itself, and each request observed by
[`Recorded`](../../src/atlassian_offline_mcp/observability/adapters/http.py). A token's
header goes to the site's host alone
([`ApiToken.authorise`](../../src/atlassian_offline_mcp/sources/atlassian/adapters/sign_in.py));
[credentials](credentials.md#on-the-wire) say why.

Every request then goes through
[`Site`](../../src/atlassian_offline_mcp/sources/atlassian/adapters/http.py), the one port
for the session and the token, and is a [`Request`](../../src/atlassian_offline_mcp/sources/atlassian/adapters/http.py):
a path on the site and its parameters, with no host to send the sign-in elsewhere.
[`Site.json`](../../src/atlassian_offline_mcp/sources/atlassian/adapters/http.py) and
[`Site.file`](../../src/atlassian_offline_mcp/sources/atlassian/adapters/http.py) call
[`Site.get`](../../src/atlassian_offline_mcp/sources/atlassian/adapters/http.py), which
retries throttling and gateway errors within bounds, and stops the run once
[`MAX_FAILED_IN_A_ROW`](../../src/atlassian_offline_mcp/sources/atlassian/adapters/http.py)
GETs in a row got no answer
([`Breaker`](../../src/atlassian_offline_mcp/sources/atlassian/adapters/http.py)).
[`Site.once`](../../src/atlassian_offline_mcp/sources/atlassian/adapters/http.py) makes
one GET, at least [`INTERVAL_S`](../../src/atlassian_offline_mcp/sources/atlassian/adapters/http.py)
after the last, and follows a redirect only to the site or to Atlassian's
[`MEDIA_HOSTS`](../../src/atlassian_offline_mcp/sources/atlassian/adapters/http.py). A 401,
or a redirect anywhere else, such as to a page to sign in, raises
[`SignInNeededError`](../../src/atlassian_offline_mcp/sources/atlassian/adapters/http.py):
exit 3.

One [`Download`](../../src/atlassian_offline_mcp/sources/atlassian/app/download.py) runs
the space. [`Download.run`](../../src/atlassian_offline_mcp/sources/atlassian/app/download.py)
first asks Confluence who is signed in
([`Download.reachable`](../../src/atlassian_offline_mcp/sources/atlassian/app/download.py)),
so that a session that no longer holds stops the run before anything is written. Then
[`Download.space`](../../src/atlassian_offline_mcp/sources/atlassian/app/download.py) lists
the space whole: [`Download.collect`](../../src/atlassian_offline_mcp/sources/atlassian/app/download.py)
follows each paged listing to its end, by the Confluence adapter's
[`listing_request`](../../src/atlassian_offline_mcp/sources/atlassian/adapters/confluence_v2.py)
and [`listing_page`](../../src/atlassian_offline_mcp/sources/atlassian/adapters/confluence_v2.py).
It stores the listings whole
([`RawStore.put_space`](../../src/atlassian_offline_mcp/sources/atlassian/adapters/raw_store.py)),
after noting what the last listing named and this one does not
([`Download.track`](../../src/atlassian_offline_mcp/sources/atlassian/app/download.py)).
For each document listed,
[`Download.consider`](../../src/atlassian_offline_mcp/sources/atlassian/app/download.py)
decides: updated within the period, and its revision not stored
([`RawStore.has`](../../src/atlassian_offline_mcp/sources/atlassian/adapters/raw_store.py)),
it is fetched, by the GETs of
[`snapshot_requests`](../../src/atlassian_offline_mcp/sources/atlassian/adapters/confluence_v2.py):
the page in its storage format with its labels, the page as the site renders it, and
its attachments. Updated within the period and its revision stored,
[`Download.complete`](../../src/atlassian_offline_mcp/sources/atlassian/app/download.py)
fetches only the files that its snapshot should have and lacks.

Once the space is listed,
[`Download.probe_absent`](../../src/atlassian_offline_mcp/sources/atlassian/app/download.py)
asks after the documents gone from their listing, and
[`Download.users`](../../src/atlassian_offline_mcp/sources/atlassian/app/download.py)
names the authors seen. Last, `download` extends the coverage of each space listed whole
([`Coverage.extended`](../../src/atlassian_offline_mcp/sources/atlassian/domain/coverage.py)),
so that the next run needs no `--since`; writes it and the tombstones; writes back the
cookies that the site renewed
([`SavedSession.keep`](../../src/atlassian_offline_mcp/sources/atlassian/adapters/sign_in.py));
and saves the run's report under `<data>/runs/`, even when the run was stopped.

### 5. Strict reading

A response is read by the adapter of its representation alone, here
[the Confluence adapter](../../src/atlassian_offline_mcp/sources/atlassian/adapters/confluence_v2.py),
and only through [`Fields`](../../src/atlassian_offline_mcp/kernel/fields.py). Each field
is asked for by its name and type
([`Fields.text`](../../src/atlassian_offline_mcp/kernel/fields.py),
[`Fields.object`](../../src/atlassian_offline_mcp/kernel/fields.py),
[`Fields.time`](../../src/atlassian_offline_mcp/kernel/fields.py)), and must be there:
otherwise [`RepresentationError`](../../src/atlassian_offline_mcp/kernel/fields.py) names
its path and what was expected, never the value found, such as
`document.json.version.number: expected an integer`.

[`Download.documents`](../../src/atlassian_offline_mcp/sources/atlassian/app/download.py)
reads a listing's entries so, through
[`LISTED`](../../src/atlassian_offline_mcp/sources/atlassian/app/download.py), counting and
skipping an entry refused.
[`Download.keep`](../../src/atlassian_offline_mcp/sources/atlassian/app/download.py) reads
a fetched snapshot through
[`REPRESENTATIONS`](../../src/atlassian_offline_mcp/sources/atlassian/adapters/raw_store.py),
whose [`Representation`](../../src/atlassian_offline_mcp/sources/atlassian/adapters/raw_store.py)
of a page pairs the adapter's
[`identity`](../../src/atlassian_offline_mcp/sources/atlassian/adapters/confluence_v2.py)
and [`snapshot`](../../src/atlassian_offline_mcp/sources/atlassian/adapters/confluence_v2.py).
The latter builds a [`Page`](../../src/atlassian_offline_mcp/kernel/content.py) through
[`document`](../../src/atlassian_offline_mcp/sources/atlassian/adapters/confluence_v2.py),
and its files through
[`attachment`](../../src/atlassian_offline_mcp/sources/atlassian/adapters/confluence_v2.py):
frozen records of the kernel, each checking its own rules. A snapshot that the adapter
refuses is stored all the same, raw, so that `mirror` reads it once the adapter is fixed,
without a download ([raw first](trade-offs.md#raw-first), [strict
reading](trade-offs.md#strict-reading-a-module-per-representation)).

### 6. The snapshot

[`Download.keep`](../../src/atlassian_offline_mcp/sources/atlassian/app/download.py) first
downloads the files that the snapshot's attachments name and that are kept
([`Download.files`](../../src/atlassian_offline_mcp/sources/atlassian/app/download.py),
[`skip_reason`](../../src/atlassian_offline_mcp/sources/atlassian/domain/files.py)), each
through [`Site.file`](../../src/atlassian_offline_mcp/sources/atlassian/adapters/http.py)
and stored once, by its SHA-256
([`RawStore.put_blob`](../../src/atlassian_offline_mcp/sources/atlassian/adapters/raw_store.py)).
Then [`RawStore.put`](../../src/atlassian_offline_mcp/sources/atlassian/adapters/raw_store.py)
stores the responses exactly as received. It reads only the id and the revision, by
[`identity`](../../src/atlassian_offline_mcp/sources/atlassian/adapters/confluence_v2.py),
which also checks that the view is of the page's version, as two GETs may straddle an
edit; writes each response and the store's record into a hidden folder; and renames it
to `<data>/raw/confluence/pages/<id>/<revision>/`, so that a snapshot is complete or
absent. Its responses are never written again: the next run's
[`RawStore.has`](../../src/atlassian_offline_mcp/sources/atlassian/adapters/raw_store.py)
finds the revision and asks for none of them. Its files may still grow:
[`Download.complete`](../../src/atlassian_offline_mcp/sources/atlassian/app/download.py)
downloads the kept files that the snapshot lacks, one that failed, say, and adds them to
its record
([`RawStore.add_blobs`](../../src/atlassian_offline_mcp/sources/atlassian/adapters/raw_store.py)).
The layout: [snapshots](../reference/data-layout.md#snapshots).

### 7. HTML, pandoc and front matter

Back in [`atlassian`](../../src/atlassian_offline_mcp/cli/app/sync.py),
[`mirror`](../../src/atlassian_offline_mcp/mirror/app/mirror.py) reads the raw store,
whatever the download did.
[`read_catalogue`](../../src/atlassian_offline_mcp/mirror/app/mirror.py) reads the spaces,
users and listings into a
[`Catalogue`](../../src/atlassian_offline_mcp/mirror/domain/catalogue.py);
[`place`](../../src/atlassian_offline_mcp/mirror/app/mirror.py) reads the newest snapshot
of each document
([`RawStore.latest`](../../src/atlassian_offline_mcp/sources/atlassian/adapters/raw_store.py)),
leaves out those confirmed gone, unless a listing taken since names them again, puts a
page or a post in the space whose freshest listing names it, and names each one's file
by [`confluence_path`](../../src/atlassian_offline_mcp/mirror/domain/mirror_layout.py): the
space's key, then the id and the title's
[`slug`](../../src/atlassian_offline_mcp/mirror/domain/mirror_layout.py).

[`document_file`](../../src/atlassian_offline_mcp/mirror/app/mirror.py) then builds each
document's file:

- [`front_matter`](../../src/atlassian_offline_mcp/mirror/domain/catalogue.py) says what
  the mirror says of the document, as a
  [`FrontMatter`](../../src/atlassian_offline_mcp/mirror/domain/mirror.py) that refuses
  what the layout rules out, such as a title with a line break.
- [`normalise`](../../src/atlassian_offline_mcp/mirror/adapters/site_html.py), in the one
  module that knows the site's markup, makes the view's HTML plain. Each kind of markup
  is a small [`Construct`](../../src/atlassian_offline_mcp/mirror/adapters/site_html.py),
  such as a [`Macro`](../../src/atlassian_offline_mcp/mirror/adapters/site_html.py) or a
  [`Link`](../../src/atlassian_offline_mcp/mirror/adapters/site_html.py), whose links to
  mirrored documents become relative; markup that no construct knows stays, as a
  placeholder that names it.
- [`document_html`](../../src/atlassian_offline_mcp/mirror/domain/mirror_layout.py) lays
  out the title, the body and the attachments (and an issue's comments).
- [`Pandoc.markdown`](../../src/atlassian_offline_mcp/mirror/adapters/pandoc.py) writes
  that HTML as GitHub's Markdown, one process a document, with `--sandbox` among its
  [`ARGUMENTS`](../../src/atlassian_offline_mcp/mirror/adapters/pandoc.py), so that pandoc
  reads no other file and fetches nothing; its own messages, which may quote the page,
  are left out ([`Pandoc.run`](../../src/atlassian_offline_mcp/mirror/adapters/pandoc.py)).
- [`dump`](../../src/atlassian_offline_mcp/mirror/adapters/markdown.py) writes the front
  matter as YAML, then the body. The index reads it with the same module's
  [`load`](../../src/atlassian_offline_mcp/mirror/adapters/markdown.py), so the two agree
  on every key, type and quotation.

A document whose conversion fails is reported by its place in the store, and the others
go on. The space's tree, `_tree.md`, is written from the listings
([`Catalogue.tree`](../../src/atlassian_offline_mcp/mirror/domain/catalogue.py)). Last,
[`sync`](../../src/atlassian_offline_mcp/mirror/adapters/mirror_files.py) writes each file
whose bytes differ, through a hidden file renamed into place. Then, when nothing was
reported, it removes every file that it owns
([`owned`](../../src/atlassian_offline_mcp/mirror/adapters/mirror_files.py): documents,
trees and assets) and no longer wants, such as the file of a document gone or moved, or
the old name of one whose title changed. When something was reported, it removes only
the files of documents confirmed gone, and the old file of a document that moved once
its new file is built, so that the last good copy of every other stays.

### 8. Pieces and their embeddings

[`index`](../../src/atlassian_offline_mcp/cli/app/sync.py) calls
[`index_mirror`](../../src/atlassian_offline_mcp/search/app/indexing.py), as the `index`
command does. It opens the embedding endpoint first, by
[`open_endpoint`](../../src/atlassian_offline_mcp/cli/commands/_embedding.py), then
[`endpoint`](../../src/atlassian_offline_mcp/search/adapters/model_api.py), the only way to
a client: [`refused_endpoint`](../../src/atlassian_offline_mcp/kernel/endpoint.py) refuses
an address that is not a literal one of this machine
([`loopback`](../../src/atlassian_offline_mcp/kernel/endpoint.py)) unless the run allows
it, and plain http to one even then. The default,
[`DEFAULT_EMBEDDING_URL`](../../src/atlassian_offline_mcp/config/domain/settings.py), is
Ollama's on `127.0.0.1`. An API key, if the environment gives one, goes as the bearer
token of this client alone.

[`connect`](../../src/atlassian_offline_mcp/search/adapters/embedding.py) then meets the
model: [`digest`](../../src/atlassian_offline_mcp/search/adapters/embedding.py) asks
Ollama's list of models for the digest of its weights, nothing from a server that lists
none, and one probe gives its vectors' dimensions. The
[`ApiEmbedder`](../../src/atlassian_offline_mcp/search/adapters/embedding.py) it returns is
all that the rest of the code sees of a model, an
[`Embedder`](../../src/atlassian_offline_mcp/search/adapters/embedding.py): a name, a
fingerprint of all that its vectors depend on
([`ApiEmbedder.fingerprint`](../../src/atlassian_offline_mcp/search/adapters/embedding.py)),
their dimensions, and texts in, unit vectors out. Only this module
knows the API: a POST of the model and the texts to `/v1/embeddings`
([`embeddings`](../../src/atlassian_offline_mcp/search/adapters/embedding.py), through
[`send`](../../src/atlassian_offline_mcp/search/adapters/model_api.py), within bounds), and
Ollama's own `/api/tags` for the digest. So any server that answers OpenAI's
`/v1/embeddings` will do, Ollama being only the example ([use another OpenAI-compatible
API](../how-to/embeddings.md#use-another-openai-compatible-api)).

[`build_index`](../../src/atlassian_offline_mcp/search/app/indexing.py) then reads every
file of the mirror ([`documents`](../../src/atlassian_offline_mcp/mirror/adapters/markdown.py),
then [`load`](../../src/atlassian_offline_mcp/mirror/adapters/markdown.py), which refuses
any other front matter than `dump` writes). It cuts each body into sections, one before
each heading ([`sections`](../../src/atlassian_offline_mcp/search/domain/search.py)),
indexes them by words ([`Writer.add`](../../src/atlassian_offline_mcp/search/adapters/sqlite_index.py)),
and cuts the document into pieces by the chunking that
[`CHUNKERS`](../../src/atlassian_offline_mcp/search/domain/chunking.py) names: by default
[`windows`](../../src/atlassian_offline_mcp/search/domain/chunking.py) of about 300 tokens,
starting 240 apart, so that two in a row overlap, each embedded with the title. Each
piece's text gets a [`key`](../../src/atlassian_offline_mcp/search/adapters/vector_store.py),
the SHA-256 of the fingerprint and the text.

[`VectorStore.vectors`](../../src/atlassian_offline_mcp/search/adapters/vector_store.py)
then gives each key its vector: from `<data>/vectors.sqlite` when it holds it, else
embedded by [`ApiEmbedder.documents`](../../src/atlassian_offline_mcp/search/adapters/embedding.py),
with the model's document prefix, [`BATCH`](../../src/atlassian_offline_mcp/search/adapters/embedding.py)
texts a request, and kept, [`BATCH`](../../src/atlassian_offline_mcp/search/adapters/vector_store.py)
texts a commit, so that an interrupted build loses little. The digest is read again
before and after ([`ApiEmbedder.check`](../../src/atlassian_offline_mcp/search/adapters/embedding.py)),
so that no vector of other weights is kept under this fingerprint. Only the texts that
the store lacks reach the endpoint: [the internals](internals.md#4-vectors-reused-by-the-key-of-model-and-text)
say which an edit changes.
[`Writer.add_pieces`](../../src/atlassian_offline_mcp/search/adapters/sqlite_index.py)
copies the vectors into the index.

### 9. The index swapped in

All of this writes into a new file:
[`building`](../../src/atlassian_offline_mcp/search/adapters/sqlite_index.py) creates it
beside the old index, yields its
[`Writer`](../../src/atlassian_offline_mcp/search/adapters/sqlite_index.py), writes in the
same transaction the meta rows (a random `build` id, the model, its fingerprint, the
chunking), and renames the file over `<data>/index.sqlite` once complete. On any failure
the new file goes and the old index stays: an endpoint that does not answer, or lacks the
model, raises [`ModelError`](../../src/atlassian_offline_mcp/search/adapters/model_api.py),
which [`index_mirror`](../../src/atlassian_offline_mcp/search/app/indexing.py) logs as
`index.not_built`, with the hint to search by words alone. A file skipped or a piece
refused is named in the [`Report`](../../src/atlassian_offline_mcp/search/app/indexing.py),
and the row is `done` only when the report is
[`Report.whole`](../../src/atlassian_offline_mcp/search/app/indexing.py).

### 10. The result

[`sync`](../../src/atlassian_offline_mcp/cli/app/sync.py) returns a
[`Synced`](../../src/atlassian_offline_mcp/cli/app/sync.py), the status and a
[`Row`](../../src/atlassian_offline_mcp/cli/app/sync.py) per step.
[`enter`](../../src/atlassian_offline_mcp/cli/commands/_shared.py) writes it on stdout,
as one JSON document with `--format json`, else as
[`text`](../../src/atlassian_offline_mcp/cli/commands/sync.py) writes it: each row, then
its step's counts as its own command writes them
([`TEXTS`](../../src/atlassian_offline_mcp/cli/commands/sync.py)).
[`observed`](../../src/atlassian_offline_mcp/observability/app/observed.py) ends the run:
`run.end`, the exit status on the root span, the run's duration.

## Part 2: a search

### 11. The server starts

An agent starts the command with no arguments, as [coding agents](../how-to/agents.md)
set it up, and `main` reads that as `serve`. The entry is the one of step 2, without a
summary or a question, as `serve` writes nothing, and its
[`Command`](../../src/atlassian_offline_mcp/cli/domain/command.py) is not `traced`: each
request will be a trace of its own.

[`run`](../../src/atlassian_offline_mcp/cli/commands/serve.py) opens the endpoint, unless
`search_mode = "lexical"`, and gives a
[`Meaning`](../../src/atlassian_offline_mcp/search/app/meaning.py) the means to connect,
without connecting yet. A [`Library`](../../src/atlassian_offline_mcp/mcp/app/tools.py)
over `<data>/index.sqlite` holds the tools, each a method: the MCP SDK takes its signature
as the tool's schema and its docstring as its description, so the two cannot drift
apart. [`surface`](../../src/atlassian_offline_mcp/mcp/app/surface.py) composes the
server's instructions, which end by telling agents that text between the markers is
reference data, never instructions
([`CLOSING`](../../src/atlassian_offline_mcp/mcp/app/surface.py)). Each method, wrapped by
[`served`](../../src/atlassian_offline_mcp/cli/commands/serve.py), which measures each
call and hands an
[`UnanswerableError`](../../src/atlassian_offline_mcp/mcp/app/tools.py) to the agent as
its message, is registered, and the server answers on stdio until the agent closes it.
`cli/commands/serve.py` alone knows the SDK.

### 12. The call

The agent calls `search` with a query, say `rollback runbook`. The SDK's span `tools/call
search` is the trace's root; [`served`](../../src/atlassian_offline_mcp/cli/commands/serve.py)
times the call;
[`Library.search`](../../src/atlassian_offline_mcp/mcp/app/tools.py) checks its arguments
(their lengths by [`LONGEST`](../../src/atlassian_offline_mcp/mcp/app/tools.py), the
filters by [`checked`](../../src/atlassian_offline_mcp/mcp/app/tools.py)), and
[`plan`](../../src/atlassian_offline_mcp/search/domain/search.py) plans the query: its
words in lower case, without stop words unless nothing else is left, at most ten, each
made one FTS5 string ([`quote`](../../src/atlassian_offline_mcp/search/domain/search.py))
so that nothing in it reads as an operator; the phrase; and the issue keys and page ids
that it names ([`identifiers`](../../src/atlassian_offline_mcp/search/domain/search.py)).

[`reading`](../../src/atlassian_offline_mcp/search/adapters/sqlite_index.py) then opens
the index read-only, for this call alone, so that a build renamed in since the last call
is read now, without a restart. A cursor from an earlier answer is refused once the build
it came from is gone ([`start_of`](../../src/atlassian_offline_mcp/mcp/app/tools.py)).

### 13. Words, meaning and their fusion

[`ranking`](../../src/atlassian_offline_mcp/mcp/app/tools.py) ranks the documents in two
spans:

- **`search.lexical`.** For each word, and the phrase,
  [`Reader.scores`](../../src/atlassian_offline_mcp/search/adapters/sqlite_index.py)
  scores each document that matches by its best section's bm25, with weights per column
  ([`WEIGHTS`](../../src/atlassian_offline_mcp/search/adapters/sqlite_index.py)). The
  documents that the query names by key or id come first
  ([`Reader.entries`](../../src/atlassian_offline_mcp/search/adapters/sqlite_index.py)),
  and [`rank`](../../src/atlassian_offline_mcp/search/domain/search.py) orders the rest by
  the sum of their scores.
- **`search.semantic`.**
  [`Meaning.nearest`](../../src/atlassian_offline_mcp/search/app/meaning.py) reads the
  model that the index was built with
  ([`Reader.embedded`](../../src/atlassian_offline_mcp/search/adapters/sqlite_index.py)).
  [`Meaning.prepared`](../../src/atlassian_offline_mcp/search/app/meaning.py) connects to
  it once, and loads the index's vectors once a build
  ([`Reader.pieces`](../../src/atlassian_offline_mcp/search/adapters/sqlite_index.py)),
  by the build's id. The query is embedded, with the model's query prefix
  ([`ApiEmbedder.query`](../../src/atlassian_offline_mcp/search/adapters/embedding.py)),
  only while the endpoint's fingerprint is the index's; then
  [`Pieces.nearest`](../../src/atlassian_offline_mcp/search/domain/search.py) multiplies
  the matrix of the pieces' unit vectors by the query's, which gives every cosine
  exactly, and keeps the documents whose best piece is nearest, at most
  [`DEPTH`](../../src/atlassian_offline_mcp/search/app/meaning.py).

When meaning cannot be searched (no vectors, other weights, an endpoint that does not
answer), the [`Nearest`](../../src/atlassian_offline_mcp/search/app/meaning.py) returned
says why: the search ranks by words alone, its answer says so, and the warning
`search.fallback` is logged; it never fails. Otherwise, in the hybrid mode,
[`fuse`](../../src/atlassian_offline_mcp/search/domain/search.py) merges the two lists by
reciprocal rank: each list gives a document 1 / (k + its rank), where k is
[`FUSION`](../../src/atlassian_offline_mcp/search/domain/search.py), 60. [The
internals](internals.md#fused) say why ranks, not scores.

### 14. Budgets and markers

For each document of the page of hits asked,
[`passage_of`](../../src/atlassian_offline_mcp/mcp/app/tools.py) chooses the section to
show, by meaning or by words, as the document was ranked;
[`call`](../../src/atlassian_offline_mcp/mcp/app/responses.py) writes the `read(...)` call
that opens it from `read`'s own signature, so that a call never names a parameter the
tool lacks; and [`hit`](../../src/atlassian_offline_mcp/mcp/app/responses.py) writes the
hit, with its mirror date. [`page`](../../src/atlassian_offline_mcp/mcp/app/responses.py)
keeps as many hits as fit the budget,
[`BUDGET`](../../src/atlassian_offline_mcp/mcp/app/responses.py) estimated tokens
([`tokens`](../../src/atlassian_offline_mcp/mcp/app/responses.py)), and ends a list that it
cuts with the `search(...)` call that continues it, its cursor from
[`cursor_at`](../../src/atlassian_offline_mcp/mcp/app/tools.py). Last,
[`answer`](../../src/atlassian_offline_mcp/mcp/app/responses.py) puts the hits, everything
copied from the site, inside one `<untrusted-reference-data>` block, whose boundary is the
start of the content's SHA-256, so that a page cannot hold the closing marker but by a
chance of 2^-64 ([budgets and
markers](trade-offs.md#budgets-and-untrusted-data-markers)).

Back in [`served`](../../src/atlassian_offline_mcp/cli/commands/serve.py), the call's
duration and the answer's size are recorded, `serve.call` is logged at DEBUG, and the SDK
sends the text to the agent.

## Where the spans open

Plan 016's telemetry opens each span in the code that does the work, so that a trace
reads in the order of this page. With a telemetry endpoint set ([observe runs with
Grafana](../how-to/observe-with-grafana.md)), a sync is one trace, apart from each
document fetched, and a call of a tool is one trace:

| Span | Opened by |
|---|---|
| `sync`, the run's root | [`observed`](../../src/atlassian_offline_mcp/observability/app/observed.py), after the command's name |
| `sync.step`, one a row | [`atlassian`](../../src/atlassian_offline_mcp/cli/app/sync.py), [`worklog`](../../src/atlassian_offline_mcp/cli/app/sync.py) and [`index`](../../src/atlassian_offline_mcp/cli/app/sync.py) |
| `download.space`, `download.probes`, `download.users` | [`Download.space`](../../src/atlassian_offline_mcp/sources/atlassian/app/download.py), [`Download.probe_absent`](../../src/atlassian_offline_mcp/sources/atlassian/app/download.py), [`Download.users`](../../src/atlassian_offline_mcp/sources/atlassian/app/download.py) |
| `download.document`, a trace of its own linked to the run's | [`Download.consider`](../../src/atlassian_offline_mcp/sources/atlassian/app/download.py) |
| `GET` and `POST`, one a request | [`Recorded`](../../src/atlassian_offline_mcp/observability/adapters/http.py), through [`client_span`](../../src/atlassian_offline_mcp/observability/adapters/http.py) |
| `mirror.read`, `mirror.build`, `mirror.write` | [`mirror`](../../src/atlassian_offline_mcp/mirror/app/mirror.py) |
| `index.files`, `index.embed` | [`build_index`](../../src/atlassian_offline_mcp/search/app/indexing.py) |
| `embeddings <model>`, one an embedding | [`embeddings`](../../src/atlassian_offline_mcp/search/adapters/embedding.py), through [`client_span`](../../src/atlassian_offline_mcp/observability/adapters/http.py) |
| `tools/call search`, a call's root | the MCP SDK; [`Library.search`](../../src/atlassian_offline_mcp/mcp/app/tools.py) adds the mode, the documents found and whether words stood in for meaning |
| `search.lexical`, `search.semantic` | [`ranking`](../../src/atlassian_offline_mcp/mcp/app/tools.py) |

In the index's row, the model's connection comes first, its `GET` and probe before
`index.files`; within `index.embed`, a `GET` of the digest frames the embeddings. Every
span and its attributes are listed in [telemetry](../reference/telemetry/README.md), a
page per command; [observability](observability.md#a-trace-per-document) says why a
document fetched is a trace of its own.

## Beside the tests

Each step has its tests, which say what the code must do in the requirement's words:
[`test_settings.py`](../../tests/test_settings.py),
[`test_summary.py`](../../tests/test_summary.py) and
[`test_question.py`](../../tests/test_question.py) for step 2;
[`test_sync.py`](../../tests/test_sync.py) for 2, 3 and 10;
[`test_download.py`](../../tests/test_download.py),
[`test_http.py`](../../tests/test_http.py) and
[`test_raw_store.py`](../../tests/test_raw_store.py) for 4 to 6;
[`test_adapters.py`](../../tests/test_adapters.py) and
[`test_fields.py`](../../tests/test_fields.py) for 5;
[`test_mirror.py`](../../tests/test_mirror.py) and
[`test_site_html.py`](../../tests/test_site_html.py) for 7;
[`test_index.py`](../../tests/test_index.py),
[`test_embedding.py`](../../tests/test_embedding.py) and
[`test_vectors.py`](../../tests/test_vectors.py) for 8 and 9; and
[`test_serve.py`](../../tests/test_serve.py),
[`test_tools.py`](../../tests/test_tools.py),
[`test_meaning.py`](../../tests/test_meaning.py) and
[`test_budgets.py`](../../tests/test_budgets.py) for part 2.
