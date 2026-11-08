# A walkthrough of the code

For contributors: one `fetch`, `prepare` and `embed` over one Confluence space, then one
`search` that an agent makes over MCP, followed through the code in the order in which it
runs. Each
step names the function or class that takes it and links its module, so that the page
reads best beside the code, one link at a time. Links name functions, never lines:
lines move, and [the docs' checks](../../tests/test_docs.py) fail once a linked name is
no longer defined in its file. [The code's layout](code-layout.md) says why each module
sits where it does; [the internals](internals.md), what each stage reads and writes and
how a failure stays within one document; [the data layout](../reference/data-layout.md),
the formats.

The runs followed have a settings file that names the site and one space, and Ollama on
this machine as the embedding endpoint, the example of any OpenAI-compatible API:

```toml
[accounts.atlassian]
site = "https://<your-site>.atlassian.net"

[sources.confluence]
spaces = ["ENG"]
```

```bash
kb-mcp fetch --since 2026-01-01 && kb-mcp prepare && kb-mcp embed
```

The space was never downloaded: without `--since`, its first run would take its last 7
days, and `--since` reaches back to the start of the year. The search settings
keep their defaults: `search_mode` hybrid, `chunking` windows, and the model
[`DEFAULT_MODEL`](../../src/kb_mcp/config/domain/settings.py).

## Part 1: the chain

### 1. The entry point and the parser

`pyproject.toml` makes the script `kb-mcp` call
[`main`](../../src/kb_mcp/cli/main.py), as `__main__.py` does for
`python -m kb_mcp`. `main` first builds the parser with
[`parser`](../../src/kb_mcp/cli/main.py), which imports each module of
`cli/options/` whose name does not begin with `_` and calls its `register`. Fetch's
[`register`](../../src/kb_mcp/cli/options/fetch.py) adds its options and the names of the
sources that it can take, from the registry's declarations, and
sets one default, `command`, a
[`Command`](../../src/kb_mcp/cli/domain/command.py): the module that runs
it, named as a string and not imported; the settings it reads; that it writes, and so
asks first; and three pure functions of the arguments and settings,
[`refused`](../../src/kb_mcp/cli/options/fetch.py),
[`unapplied`](../../src/kb_mcp/cli/options/fetch.py) and
[`fetch_described`](../../src/kb_mcp/cli/domain/sources.py).

Nothing heavier is imported to parse: argcomplete runs the program at every Tab, and
answers before any run is imported ([why argparse and
argcomplete](trade-offs.md#argparse-with-argcomplete)). With no arguments at all, `main`
parses `serve`, which is how agents start it (part 2). Once parsed, `fetch` is observed:
[`early`](../../src/kb_mcp/observability/app/observed.py) sends warnings
to stderr until the settings are read, and `main` imports the
[`ENTRY`](../../src/kb_mcp/cli/main.py) shared by every observed command.

### 2. Settings, the guard and the summary

[`enter`](../../src/kb_mcp/cli/commands/_shared.py) maps each flag given to
its setting ([`Command.setting_flags`](../../src/kb_mcp/cli/domain/command.py))
and calls [`load_settings`](../../src/kb_mcp/config/app/settings.py). Three
layers, each stronger than the last: the file
([`read_settings_file`](../../src/kb_mcp/config/adapters/settings_file.py)),
the environment
([`environment_entries`](../../src/kb_mcp/config/domain/settings.py)) and
the flags. [`settings_of`](../../src/kb_mcp/config/domain/settings.py)
merges their [`Entry`](../../src/kb_mcp/config/domain/settings.py) rows,
weakest first, into one [`Settings`](../../src/kb_mcp/config/domain/settings.py),
which Pydantic validates, and keeps each value's layer in a
[`Loaded`](../../src/kb_mcp/config/domain/settings.py). A value refused is
a [`SettingsError`](../../src/kb_mcp/config/domain/settings.py) that names
the setting and its layers, never the value.

Then the guard. The data directory, each folder under it and the log folder are resolved,
links followed, and judged by
[`unsafe_location`](../../src/kb_mcp/config/domain/settings.py), given the
git working tree that holds each, if any
([`git_root`](../../src/kb_mcp/config/adapters/settings_file.py)). Under a
synchronised folder, or inside a git tree, the run stops with
[`UnsafeDataDirError`](../../src/kb_mcp/config/app/settings.py), exit 2,
before anything is written.

Then what fetch cannot run with. Its
[`refused`](../../src/kb_mcp/cli/options/fetch.py) takes the sources by
[`chosen`](../../src/kb_mcp/cli/domain/sources.py), from the registry's declarations,
[`SOURCES`](../../src/kb_mcp/sources/registry.py), and refuses the first of
these that it finds: a source named that the settings do not configure;
nothing to fetch, no source being configured; and what each source taken refuses by its
declaration, with Confluence or Jira a site not set
([`site_not_set`](../../src/kb_mcp/sources/atlassian/declared.py)), an API token
without its email
([`token_without_email`](../../src/kb_mcp/sources/atlassian/declared.py)) or an
option of the period that does not read
([`period_refused`](../../src/kb_mcp/sources/atlassian/declared.py)). For `prepare`, `enter`
adds pandoc missing from `PATH`, and for `embed` its
[`endpoint_elsewhere`](../../src/kb_mcp/cli/options/_common.py) refuses an embedding endpoint
off this machine without `--allow-remote-embeddings`, or over plain http even with it. Each
is exit 2, said on stderr alone: no run has
started, so there is no log file.

Then [`before`](../../src/kb_mcp/cli/domain/summary.py) writes the summary
on stderr: each setting that the command reads, with its value, a secret only as set or not
([`setting_line`](../../src/kb_mcp/cli/domain/summary.py)); the sources
taken and left out ([`fetch_described`](../../src/kb_mcp/cli/domain/sources.py));
each value ignored, and why; and the command to copy
([`command_line`](../../src/kb_mcp/cli/domain/command_line.py)).
[`ask`](../../src/kb_mcp/cli/adapters/question.py) asks `Proceed? [y/N]`;
`--yes` skips the question, and with no terminal to answer it, the run is refused.

Only now does the run begin.
[`observed`](../../src/kb_mcp/observability/app/observed.py) opens its log
file, its telemetry when an endpoint is set, and the trace's root span, named after the
command, and logs `run.start`; `enter` then imports `cli.commands.sources`, which `fetch` and
`prepare` share, and calls its
[`run`](../../src/kb_mcp/cli/commands/sources.py) with the arguments and the
settings loaded.

### 3. A row per source

[`run`](../../src/kb_mcp/cli/commands/sources.py) turns the settings into
a [`Run`](../../src/kb_mcp/sources/roles.py) for each source taken, a small frozen
record: its declaration, the settings, its table and its account's, its options'
values by flag, here `--since`, the clock and the pause, which tests replace. No work log is
configured, so no run is of it.

[`run_each`](../../src/kb_mcp/cli/app/sources.py) loads each role that a source's
declaration names ([`loaded`](../../src/kb_mcp/cli/app/sources.py)), then refuses what
it can before any row: here an `--until` before `--since`, which the fetcher's
[`preflight`](../../src/kb_mcp/sources/atlassian/fetch/app/fetcher.py) finds from the
[`Targets`](../../src/kb_mcp/sources/atlassian/fetch/app/download.py) of the
period's options, one space here.
[`Targets.windows`](../../src/kb_mcp/sources/atlassian/fetch/app/download.py)
asks [`window`](../../src/kb_mcp/sources/atlassian/fetch/domain/coverage.py),
from the coverage that the raw store holds, for each target's window and why it starts
there, here `given`; a `--since` that does not come before the windows' end raises
[`PeriodError`](../../src/kb_mcp/sources/atlassian/fetch/domain/period.py):
exit 2, naming both options. Then each row runs in turn, each source's role within a span
`fetch.source`, or `prepare.source` once the next command runs. A row runs even when the
one before it failed, as it reads what is on disk. The exit status is the first outcome
of [`RANKED`](../../src/kb_mcp/cli/domain/sources.py) that a row had:
interrupted, then sign in, then failed; else 0.

### 4. The source and the site's port

The fetcher's [`fetch`](../../src/kb_mcp/sources/atlassian/fetch/app/fetcher.py) calls
[`download`](../../src/kb_mcp/sources/atlassian/fetch/app/download.py), which
opens the [`RawStore`](../../src/kb_mcp/sources/atlassian/fetch/adapters/raw_store.py)
under `<data>/raw/` and takes its lock
([`RawStore.writing`](../../src/kb_mcp/sources/atlassian/fetch/adapters/raw_store.py)):
a second run stops at once with
[`StoreBusyError`](../../src/kb_mcp/sources/atlassian/fetch/adapters/raw_store.py),
and its row fails while the next one runs.

The sign-in comes from
[`sign_in`](../../src/kb_mcp/sources/atlassian/fetch/adapters/sign_in.py): an
[`ApiToken`](../../src/kb_mcp/sources/atlassian/fetch/adapters/sign_in.py) when
the environment gives a token, else the
[`SavedSession`](../../src/kb_mcp/sources/atlassian/fetch/adapters/sign_in.py)
that `login` saved. Either gives an httpx client built by
[`client`](../../src/kb_mcp/sources/atlassian/fetch/adapters/http.py): TLS checked
by the system's certificates, plain http refused
([`refuse_plain_http`](../../src/kb_mcp/sources/atlassian/fetch/adapters/http.py)),
no redirect followed by httpx itself, and each request observed by
[`Recorded`](../../src/kb_mcp/observability/adapters/http.py). A token's
header goes to the site's host alone
([`ApiToken.authorise`](../../src/kb_mcp/sources/atlassian/fetch/adapters/sign_in.py));
[credentials](credentials.md#on-the-wire) say why.

Every request then goes through
[`Site`](../../src/kb_mcp/sources/atlassian/fetch/adapters/http.py), the one port
for the session and the token, and is a [`Request`](../../src/kb_mcp/sources/atlassian/fetch/adapters/http.py):
a path on the site and its parameters, with no host to send the sign-in elsewhere.
[`Site.json`](../../src/kb_mcp/sources/atlassian/fetch/adapters/http.py) and
[`Site.file`](../../src/kb_mcp/sources/atlassian/fetch/adapters/http.py) call
[`Site.get`](../../src/kb_mcp/sources/atlassian/fetch/adapters/http.py), which
retries throttling and gateway errors within bounds, and stops the run once
[`MAX_FAILED_IN_A_ROW`](../../src/kb_mcp/sources/atlassian/fetch/adapters/http.py)
GETs in a row got no answer
([`Breaker`](../../src/kb_mcp/sources/atlassian/fetch/adapters/http.py)).
[`Site.once`](../../src/kb_mcp/sources/atlassian/fetch/adapters/http.py) makes
one GET, at least [`INTERVAL_S`](../../src/kb_mcp/sources/atlassian/fetch/adapters/http.py)
after the last, and follows a redirect only to the site or to Atlassian's
[`MEDIA_HOSTS`](../../src/kb_mcp/sources/atlassian/fetch/adapters/http.py). A 401,
or a redirect anywhere else, such as to a page to sign in, raises
[`SignInNeededError`](../../src/kb_mcp/sources/atlassian/fetch/adapters/http.py):
exit 3.

One [`Download`](../../src/kb_mcp/sources/atlassian/fetch/app/download.py) runs
the space. [`Download.run`](../../src/kb_mcp/sources/atlassian/fetch/app/download.py)
first asks Confluence who is signed in
([`Download.reachable`](../../src/kb_mcp/sources/atlassian/fetch/app/download.py)),
so that a session that no longer holds stops the run before anything is written. Then
[`Download.space`](../../src/kb_mcp/sources/atlassian/fetch/app/download.py) lists
the space whole: [`Download.collect`](../../src/kb_mcp/sources/atlassian/fetch/app/download.py)
follows each paged listing to its end, by the Confluence adapter's
[`listing_request`](../../src/kb_mcp/sources/atlassian/fetch/adapters/confluence_v2.py)
and [`listing_page`](../../src/kb_mcp/sources/atlassian/fetch/adapters/confluence_v2.py).
It stores the listings whole
([`RawStore.put_space`](../../src/kb_mcp/sources/atlassian/fetch/adapters/raw_store.py)),
after noting what the last listing named and this one does not
([`Download.track`](../../src/kb_mcp/sources/atlassian/fetch/app/download.py)).
[`Download.fetch_listed`](../../src/kb_mcp/sources/atlassian/fetch/app/download.py)
then splits the documents listed. Updated within the window, and its revision not stored
([`RawStore.has`](../../src/kb_mcp/sources/atlassian/fetch/adapters/raw_store.py)),
a document is fetched by
[`Download.fetch`](../../src/kb_mcp/sources/atlassian/fetch/app/download.py),
by the GETs of
[`snapshot_requests`](../../src/kb_mcp/sources/atlassian/fetch/adapters/confluence_v2.py):
the page in its storage format with its labels, the page as the site renders it, and
its attachments. Updated within the window and its revision stored,
[`Download.complete`](../../src/kb_mcp/sources/atlassian/fetch/app/download.py)
fetches only the files that its snapshot should have and lacks. The progress and the
counts are of what is fetched, apart from what is listed, as `fetch.listed` says.

Once the space is listed,
[`Download.probe_absent`](../../src/kb_mcp/sources/atlassian/fetch/app/download.py)
asks after the documents gone from their listing, and
[`Download.users`](../../src/kb_mcp/sources/atlassian/fetch/app/download.py)
names the authors seen. Last, `download` extends the coverage of each target listed whole
([`Coverage.extended`](../../src/kb_mcp/sources/atlassian/fetch/domain/coverage.py)),
a project's only to its earliest document not stored whole, so that the next run needs
no `--since` and asks again for what failed, as `fetch.coverage` says; writes it, each
change of the tombstones having been written where it was made, and a fetch of projects
rewriting none; writes back the
cookies that the site renewed
([`SavedSession.keep`](../../src/kb_mcp/sources/atlassian/fetch/adapters/sign_in.py));
and saves the run's report under `<data>/runs/`, named by its source, even when the run
was stopped.

### 5. Strict reading

A response is read by the adapter of its representation alone, here
[the Confluence adapter](../../src/kb_mcp/sources/atlassian/fetch/adapters/confluence_v2.py),
and only through [`Fields`](../../src/kb_mcp/kernel/fields.py). Each field
is asked for by its name and type
([`Fields.text`](../../src/kb_mcp/kernel/fields.py),
[`Fields.object`](../../src/kb_mcp/kernel/fields.py),
[`Fields.time`](../../src/kb_mcp/kernel/fields.py)), and must be there:
otherwise [`RepresentationError`](../../src/kb_mcp/kernel/fields.py) names
its path and what was expected, never the value found, such as
`document.json.version.number: expected an integer`.

[`Download.documents`](../../src/kb_mcp/sources/atlassian/fetch/app/download.py)
reads a listing's entries so, through
[`LISTED`](../../src/kb_mcp/sources/atlassian/fetch/app/download.py), counting and
skipping an entry refused.
[`Download.keep`](../../src/kb_mcp/sources/atlassian/fetch/app/download.py) reads
a fetched snapshot through
[`REPRESENTATIONS`](../../src/kb_mcp/sources/atlassian/fetch/adapters/raw_store.py),
whose [`Representation`](../../src/kb_mcp/sources/atlassian/fetch/adapters/raw_store.py)
of a page pairs the adapter's
[`identity`](../../src/kb_mcp/sources/atlassian/fetch/adapters/confluence_v2.py)
and [`snapshot`](../../src/kb_mcp/sources/atlassian/fetch/adapters/confluence_v2.py).
The latter builds a [`Page`](../../src/kb_mcp/sources/atlassian/fetch/domain/content.py) through
[`document`](../../src/kb_mcp/sources/atlassian/fetch/adapters/confluence_v2.py),
and its files through
[`attachment`](../../src/kb_mcp/sources/atlassian/fetch/adapters/confluence_v2.py):
frozen records of the fetch's domain, each checking its own rules. A snapshot that the
adapter refuses is stored all the same, raw, so that `prepare` reads it once the adapter
is fixed, without a fetch ([raw first](trade-offs.md#raw-first), [strict
reading](trade-offs.md#strict-reading-a-module-per-representation)).

### 6. The snapshot

[`Download.keep`](../../src/kb_mcp/sources/atlassian/fetch/app/download.py) first
downloads the files that the snapshot's attachments name and that are kept
([`Download.files`](../../src/kb_mcp/sources/atlassian/fetch/app/download.py),
[`skip_reason`](../../src/kb_mcp/sources/atlassian/fetch/domain/files.py)), each
through [`Site.file`](../../src/kb_mcp/sources/atlassian/fetch/adapters/http.py)
and stored once, by its SHA-256
([`RawStore.put_blob`](../../src/kb_mcp/sources/atlassian/fetch/adapters/raw_store.py)).
Then [`RawStore.put`](../../src/kb_mcp/sources/atlassian/fetch/adapters/raw_store.py)
stores the responses exactly as received. It reads only the id and the revision, by
[`identity`](../../src/kb_mcp/sources/atlassian/fetch/adapters/confluence_v2.py),
which also checks that the view is of the page's version, as two GETs may straddle an
edit; writes each response and the store's record into a hidden folder; and renames it
to `<data>/raw/confluence/pages/<id>/<revision>/`, so that a snapshot is complete or
absent. Its responses are never written again: the next run's
[`RawStore.has`](../../src/kb_mcp/sources/atlassian/fetch/adapters/raw_store.py)
finds the revision and asks for none of them. Its files may still grow:
[`Download.complete`](../../src/kb_mcp/sources/atlassian/fetch/app/download.py)
downloads the kept files that the snapshot lacks, one that failed, say, and adds them to
its record
([`RawStore.add_blobs`](../../src/kb_mcp/sources/atlassian/fetch/adapters/raw_store.py)).
The layout: [snapshots](../reference/data-layout.md#snapshots).

### 7. HTML, pandoc and front matter

Then the preparer's [`prepare`](../../src/kb_mcp/sources/atlassian/prepare/app/preparer.py),
through [`mirror`](../../src/kb_mcp/sources/atlassian/prepare/app/prepare.py), reads the raw store,
whatever the download did. It runs for Confluence here, and reads from `run.declared` the
kinds that it converts: Jira's issues are placed too, so that a link to one reaches its
file, and only pages and blog posts are built.
[`read_catalogue`](../../src/kb_mcp/sources/atlassian/prepare/app/prepare.py) reads the spaces,
users and listings into a
[`Catalogue`](../../src/kb_mcp/sources/atlassian/prepare/domain/catalogue.py);
[`place`](../../src/kb_mcp/sources/atlassian/prepare/app/prepare.py) reads the newest snapshot
of each document
([`RawStore.latest`](../../src/kb_mcp/sources/atlassian/fetch/adapters/raw_store.py)),
leaves out those confirmed gone, unless a listing taken since names them again, puts a
page or a post in the space whose freshest listing names it, and names each one's file
by [`confluence_path`](../../src/kb_mcp/sources/atlassian/prepare/domain/layout.py): the
space's key, then the id and the title's
[`slug`](../../src/kb_mcp/kernel/slug.py).

[`document_file`](../../src/kb_mcp/sources/atlassian/prepare/app/prepare.py) then builds each
document's file:

- [`front_matter`](../../src/kb_mcp/sources/atlassian/prepare/domain/catalogue.py) says what
  the mirror says of the document, as a
  [`FrontMatter`](../../src/kb_mcp/mirror/domain/mirror.py) that refuses
  what the layout rules out, such as a title with a line break.
- [`normalise`](../../src/kb_mcp/sources/atlassian/prepare/adapters/site_html.py), in the one
  module that knows the site's markup, makes the view's HTML plain. Each kind of markup
  is a small [`Construct`](../../src/kb_mcp/sources/atlassian/prepare/adapters/site_html.py),
  such as a [`Macro`](../../src/kb_mcp/sources/atlassian/prepare/adapters/site_html.py) or a
  [`Link`](../../src/kb_mcp/sources/atlassian/prepare/adapters/site_html.py), whose links to
  mirrored documents become relative; markup that no construct knows stays, as a
  placeholder that names it.
- [`document_html`](../../src/kb_mcp/sources/atlassian/prepare/domain/layout.py) lays
  out the title, the body and the attachments (and an issue's comments).
- [`Conversions.markdown`](../../src/kb_mcp/mirror/adapters/conversions.py)
  gives that HTML's Markdown from the rows of its source in the cache of conversions, which
  [`prepare_kinds`](../../src/kb_mcp/sources/atlassian/prepare/app/preparer.py) opened
  ([`opened`](../../src/kb_mcp/mirror/adapters/conversions.py)), or has
  [`Pandoc.markdown`](../../src/kb_mcp/mirror/adapters/pandoc.py) write it
  as GitHub's Markdown, one process a document, and keeps it. `--sandbox` is among
  pandoc's [`ARGUMENTS`](../../src/kb_mcp/mirror/adapters/pandoc.py), so
  that it reads no other file and fetches nothing; its own messages, which may quote the
  page, are left out ([`Pandoc.run`](../../src/kb_mcp/mirror/adapters/pandoc.py)).
- [`dump`](../../src/kb_mcp/mirror/adapters/markdown.py) writes the front
  matter as YAML, then the body. The index reads it with the same module's
  [`load`](../../src/kb_mcp/mirror/adapters/markdown.py), so the two agree
  on every key, type and quotation.

A document whose conversion fails is reported by its place in the store, and the others
go on. The space's tree, `_tree.md`, is written from the listings
([`Catalogue.tree`](../../src/kb_mcp/sources/atlassian/prepare/domain/catalogue.py)). Last,
[`sync`](../../src/kb_mcp/mirror/adapters/mirror_files.py) writes each file
whose bytes differ, through a hidden file renamed into place. Then, when nothing was
reported, it removes every file that its source owns
([`owned`](../../src/kb_mcp/sources/atlassian/prepare/adapters/owned.py): documents and
trees) and no longer wants, such as the file of a document gone or moved, or the old name
of one whose title changed. Then it removes an attached file that no placed document of
either source wants ([`attached`](../../src/kb_mcp/sources/atlassian/prepare/adapters/owned.py))
and no document's file left links
([`unlinked`](../../src/kb_mcp/sources/atlassian/prepare/adapters/owned.py)). When
something was reported of this source, it removes only
the files of documents confirmed gone, and the old file of a document that moved once
its new file is built, so that the last good copy of every other stays.

### 8. Pieces and their embeddings

`embed`'s [`run`](../../src/kb_mcp/cli/commands/embed.py) takes the
[`Indexing`](../../src/kb_mcp/search/app/indexing.py) that
[`indexing_of`](../../src/kb_mcp/cli/commands/_embedding.py) reads from the settings, and
[`refresh`](../../src/kb_mcp/search/app/indexing.py) calls
[`filling`](../../src/kb_mcp/search/app/indexing.py), as `index` does, by words alone. It
opens the embedding endpoint first, by
[`open_endpoint`](../../src/kb_mcp/cli/commands/_embedding.py), then
[`endpoint`](../../src/kb_mcp/search/adapters/model_api.py), the only way to
a client: [`refused_endpoint`](../../src/kb_mcp/kernel/endpoint.py) refuses
an address that is not a literal one of this machine
([`loopback`](../../src/kb_mcp/kernel/endpoint.py)) unless the run allows
it, and plain http to one even then. The default,
[`DEFAULT_EMBEDDING_URL`](../../src/kb_mcp/config/domain/settings.py), is
Ollama's on `127.0.0.1`. An API key, if the environment gives one, goes as the bearer
token of this client alone.

[`connect`](../../src/kb_mcp/search/adapters/embedding.py) then meets the
model: [`digest`](../../src/kb_mcp/search/adapters/embedding.py) asks
Ollama's list of models for the digest of its weights, nothing from a server that lists
none, and one probe gives its vectors' dimensions. The
[`ApiEmbedder`](../../src/kb_mcp/search/adapters/embedding.py) it returns is
all that the rest of the code sees of a model, an
[`Embedder`](../../src/kb_mcp/search/adapters/embedding.py): a name, a
fingerprint of all that its vectors depend on
([`ApiEmbedder.fingerprint`](../../src/kb_mcp/search/adapters/embedding.py)),
their dimensions, and texts in, unit vectors out. Only this module
knows the API: a POST of the model and the texts to `/v1/embeddings`
([`embeddings`](../../src/kb_mcp/search/adapters/embedding.py), through
[`send`](../../src/kb_mcp/search/adapters/model_api.py), within bounds), and
Ollama's own `/api/tags` for the digest. So any server that answers OpenAI's
`/v1/embeddings` will do, Ollama being only the example ([use another OpenAI-compatible
API](../how-to/embeddings.md#use-another-openai-compatible-api)).

[`build_index`](../../src/kb_mcp/search/app/indexing.py) then reads every
file of the mirror ([`documents`](../../src/kb_mcp/mirror/adapters/markdown.py),
then [`load`](../../src/kb_mcp/mirror/adapters/markdown.py), which refuses
any other front matter than `dump` writes). It cuts each body into sections, one before
each heading ([`sections`](../../src/kb_mcp/search/domain/search.py)),
indexes them by words ([`Writer.add`](../../src/kb_mcp/search/adapters/sqlite_index.py)),
and cuts the document into pieces by the chunking that
[`CHUNKERS`](../../src/kb_mcp/search/domain/chunking.py) names: by default
[`windows`](../../src/kb_mcp/search/domain/chunking.py) of about 300 tokens,
starting 240 apart, so that two in a row overlap, each embedded with the title. Each
piece's text gets a [`key`](../../src/kb_mcp/search/adapters/vector_store.py),
the SHA-256 of the fingerprint and the text.

[`VectorStore.vectors`](../../src/kb_mcp/search/adapters/vector_store.py)
then gives each key its vector: from `<data>/vectors.sqlite` when it holds it, else
embedded by [`ApiEmbedder.documents`](../../src/kb_mcp/search/adapters/embedding.py),
with the model's document prefix, [`BATCH`](../../src/kb_mcp/search/adapters/embedding.py)
texts a request, and kept, [`BATCH`](../../src/kb_mcp/search/adapters/vector_store.py)
texts a commit, so that an interrupted build loses little. The digest is read again
before and after ([`ApiEmbedder.check`](../../src/kb_mcp/search/adapters/embedding.py)),
so that no vector of other weights is kept under this fingerprint. Only the texts that
the store lacks reach the endpoint: [the internals](internals.md#4-vectors-reused-by-the-key-of-model-and-text)
say which an edit changes.
[`Writer.add_pieces`](../../src/kb_mcp/search/adapters/sqlite_index.py)
copies the vectors into the index.

### 9. The index swapped in

All of this writes into a new file:
[`building`](../../src/kb_mcp/search/adapters/sqlite_index.py) creates it
beside the old index, yields its
[`Writer`](../../src/kb_mcp/search/adapters/sqlite_index.py), writes in the
same transaction the meta rows (a random `build` id, the model, its fingerprint, the
chunking), and renames the file over `<data>/index.sqlite` once complete. On any failure
the new file goes and the old index stays: an endpoint that does not answer, or lacks the
model, raises [`ModelError`](../../src/kb_mcp/search/adapters/model_api.py),
which [`refresh`](../../src/kb_mcp/search/app/indexing.py) logs as
`index.not_built`, with the hint to index by words alone. A file skipped or a piece
refused is named in the [`Report`](../../src/kb_mcp/search/app/indexing.py),
and the run exits 0 only when the report is
[`Report.whole`](../../src/kb_mcp/search/app/indexing.py).

### 10. The result

[`run_each`](../../src/kb_mcp/cli/app/sources.py) returns a
[`Ran`](../../src/kb_mcp/cli/domain/rows.py), the status and a
[`Row`](../../src/kb_mcp/cli/domain/rows.py) per source.
[`enter`](../../src/kb_mcp/cli/commands/_shared.py) writes it on stdout,
as one JSON document with `--format json`, else as
[`text`](../../src/kb_mcp/cli/commands/sources.py) writes it: each row, then
its counts, by its role's [`Result.text`](../../src/kb_mcp/sources/roles.py). `embed` has one
result, written by its own [`text`](../../src/kb_mcp/cli/commands/embed.py).
[`observed`](../../src/kb_mcp/observability/app/observed.py) ends the run:
`run.end`, the exit status on the root span, the run's duration.

## Part 2: a search

### 11. The server starts

An agent starts the command with no arguments, as [coding agents](../how-to/agents.md)
set it up, and `main` reads that as `serve`. The entry is the one of step 2, without a
summary or a question, as `serve` writes nothing, and its
[`Command`](../../src/kb_mcp/cli/domain/command.py) is not `traced`: each
request will be a trace of its own.

[`run`](../../src/kb_mcp/cli/commands/serve.py) opens the endpoint, unless
`search_mode = "lexical"`, and gives a
[`Meaning`](../../src/kb_mcp/search/app/meaning.py) the means to connect,
without connecting yet. A [`Library`](../../src/kb_mcp/mcp/app/tools.py)
over `<data>/index.sqlite` holds the tools, each a method: the MCP SDK takes its signature
as the tool's schema and its docstring as its description, so the two cannot drift
apart. [`surface`](../../src/kb_mcp/mcp/app/surface.py) composes the
server's instructions, which end by telling agents that text between the markers is
reference data, never instructions
([`CLOSING`](../../src/kb_mcp/mcp/app/surface.py)). Each method, wrapped by
[`served`](../../src/kb_mcp/cli/commands/serve.py), which measures each
call and hands an
[`UnanswerableError`](../../src/kb_mcp/mcp/app/tools.py) to the agent as
its message, is registered, and the server answers on stdio until the agent closes it.
`cli/commands/serve.py` alone knows the SDK.

### 12. The call

The agent calls `search` with a query, say `rollback runbook`. The SDK's span `tools/call
search` is the trace's root; [`served`](../../src/kb_mcp/cli/commands/serve.py)
times the call;
[`Library.search`](../../src/kb_mcp/mcp/app/tools.py) checks its arguments
(their lengths by [`LONGEST`](../../src/kb_mcp/mcp/app/tools.py), the
filters by [`checked`](../../src/kb_mcp/mcp/app/tools.py)), and
[`plan`](../../src/kb_mcp/search/domain/search.py) plans the query: its
words in lower case, without stop words unless nothing else is left, at most ten, each
made one FTS5 string ([`quote`](../../src/kb_mcp/search/domain/search.py))
so that nothing in it reads as an operator; the phrase; and the issue keys and page ids
that it names ([`identifiers`](../../src/kb_mcp/search/domain/search.py)).

[`reading`](../../src/kb_mcp/search/adapters/sqlite_index.py) then opens
the index read-only, for this call alone, so that a build renamed in since the last call
is read now, without a restart. A cursor from an earlier answer is refused once the build
it came from is gone ([`start_of`](../../src/kb_mcp/mcp/app/tools.py)).

### 13. Words, meaning and their fusion

[`ranking`](../../src/kb_mcp/mcp/app/tools.py) ranks the documents in two
spans:

- **`search.lexical`.** For each word, and the phrase,
  [`Reader.scores`](../../src/kb_mcp/search/adapters/sqlite_index.py)
  scores each document that matches by its best section's bm25, with weights per column
  ([`WEIGHTS`](../../src/kb_mcp/search/adapters/sqlite_index.py)). The
  documents that the query names by key or id come first
  ([`Reader.entries`](../../src/kb_mcp/search/adapters/sqlite_index.py)),
  and [`rank`](../../src/kb_mcp/search/domain/search.py) orders the rest by
  the sum of their scores.
- **`search.semantic`.**
  [`Meaning.nearest`](../../src/kb_mcp/search/app/meaning.py) reads the
  model that the index was built with
  ([`Reader.embedded`](../../src/kb_mcp/search/adapters/sqlite_index.py)).
  [`Meaning.prepared`](../../src/kb_mcp/search/app/meaning.py) connects to
  it once, and loads the index's vectors once a build
  ([`Reader.pieces`](../../src/kb_mcp/search/adapters/sqlite_index.py)),
  by the build's id. The query is embedded, with the model's query prefix
  ([`ApiEmbedder.query`](../../src/kb_mcp/search/adapters/embedding.py)),
  only while the endpoint's fingerprint is the index's; then
  [`Pieces.nearest`](../../src/kb_mcp/search/domain/search.py) multiplies
  the matrix of the pieces' unit vectors by the query's, which gives every cosine
  exactly, and keeps the documents whose best piece is nearest, at most
  [`DEPTH`](../../src/kb_mcp/search/app/meaning.py).

When meaning cannot be searched (no vectors, other weights, an endpoint that does not
answer), the [`Nearest`](../../src/kb_mcp/search/app/meaning.py) returned
says why: the search ranks by words alone, its answer says so, and the warning
`search.fallback` is logged; it never fails. Otherwise, in the hybrid mode,
[`fuse`](../../src/kb_mcp/search/domain/search.py) merges the two lists by
reciprocal rank: each list gives a document 1 / (k + its rank), where k is
[`FUSION`](../../src/kb_mcp/search/domain/search.py), 60. [The
internals](internals.md#fused) say why ranks, not scores.

### 14. Budgets and markers

For each document of the page of hits asked,
[`passage_of`](../../src/kb_mcp/mcp/app/tools.py) chooses the section to
show, by meaning or by words, as the document was ranked;
[`call`](../../src/kb_mcp/mcp/app/responses.py) writes the `read(...)` call
that opens it from `read`'s own signature, so that a call never names a parameter the
tool lacks; and [`hit`](../../src/kb_mcp/mcp/app/responses.py) writes the
hit, with its mirror date. [`page`](../../src/kb_mcp/mcp/app/responses.py)
keeps as many hits as fit the budget,
[`BUDGET`](../../src/kb_mcp/mcp/app/responses.py) estimated tokens
([`tokens`](../../src/kb_mcp/mcp/app/responses.py)), and ends a list that it
cuts with the `search(...)` call that continues it, its cursor from
[`cursor_at`](../../src/kb_mcp/mcp/app/tools.py). Last,
[`answer`](../../src/kb_mcp/mcp/app/responses.py) puts the hits, everything
copied from the site, inside one `<untrusted-reference-data>` block, whose boundary is the
start of the content's SHA-256, so that a page cannot hold the closing marker but by a
chance of 2^-64 ([budgets and
markers](trade-offs.md#budgets-and-untrusted-data-markers)).

Back in [`served`](../../src/kb_mcp/cli/commands/serve.py), the call's
duration and the answer's size are recorded, `serve.call` is logged at DEBUG, and the SDK
sends the text to the agent.

## Where the spans open

Plan 016's telemetry opens each span in the code that does the work, so that a trace
reads in the order of this page. With a telemetry endpoint set ([observe runs with
Grafana](../how-to/observe-with-grafana.md)), each command of the chain is one trace, apart
from each document fetched, and a call of a tool is one trace:

| Span | Opened by |
|---|---|
| `fetch`, `prepare`, `embed`, the run's root | [`observed`](../../src/kb_mcp/observability/app/observed.py), after the command's name |
| `fetch.source`, `prepare.source`, one a row | [`run_each`](../../src/kb_mcp/cli/app/sources.py) |
| `fetch.space`, `fetch.probes`, `fetch.users` | [`Download.space`](../../src/kb_mcp/sources/atlassian/fetch/app/download.py), [`Download.probe_absent`](../../src/kb_mcp/sources/atlassian/fetch/app/download.py), [`Download.users`](../../src/kb_mcp/sources/atlassian/fetch/app/download.py) |
| `fetch.document`, a trace of its own linked to the run's | [`Download.fetch`](../../src/kb_mcp/sources/atlassian/fetch/app/download.py) |
| `GET` and `POST`, one a request | [`Recorded`](../../src/kb_mcp/observability/adapters/http.py), through [`client_span`](../../src/kb_mcp/observability/adapters/http.py) |
| `prepare.read`, `prepare.build`, `prepare.write` | [`mirror`](../../src/kb_mcp/sources/atlassian/prepare/app/prepare.py) |
| `index.files`, `index.embed` | [`build_index`](../../src/kb_mcp/search/app/indexing.py) |
| `embeddings <model>`, one an embedding | [`embeddings`](../../src/kb_mcp/search/adapters/embedding.py), through [`client_span`](../../src/kb_mcp/observability/adapters/http.py) |
| `tools/call search`, a call's root | the MCP SDK; [`Library.search`](../../src/kb_mcp/mcp/app/tools.py) adds the mode, the documents found and whether words stood in for meaning |
| `search.lexical`, `search.semantic` | [`ranking`](../../src/kb_mcp/mcp/app/tools.py) |

In `embed`'s trace, the model's connection comes first, its `GET` and probe before
`index.files`; within `index.embed`, a `GET` of the digest frames the embeddings. Every
span and its attributes are listed in [telemetry](../reference/telemetry/README.md), a
page per command; [observability](observability.md#a-trace-per-document) says why a
document fetched is a trace of its own.

## Beside the tests

Each step has its tests, which say what the code must do in the requirement's words:
[`test_settings.py`](../../tests/test_settings.py),
[`test_summary.py`](../../tests/test_summary.py) and
[`test_question.py`](../../tests/test_question.py) for step 2;
[`test_sources.py`](../../tests/test_sources.py) for 2, 3 and 10;
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
