# Sources

The mirror has three sources: Confluence and Jira, on the Atlassian site, and the user's
work log, a folder of org files on this machine. A source is a declaration and the code
that it names, and the three are declared alike, so that a new one is a package and one
line of a registry. This page says why a source is put together as it is; [bring every
source up to date](../how-to/refresh.md) and [mirror the work log](../how-to/work-log.md)
say how to use them, and [add a source](../how-to/add-a-source.md) how to write one.

## Three roles, not a bundle

A source could be one bundle of a fetcher, a processor and tools of its own. That fits a
system where the three come as one, such as Google Drive, Notion or SharePoint. It does
not fit:

- **git**, fetched once and prepared twice, as code and as history;
- **persons**, a preparation over every source's documents, which is no source;
- **tools per source**, which would bring back the several calls and merges that one
  server in front of every source avoids.

So the roles vary apart: a fetcher by system, a preparer by format, and the serving side
by kind of question. A [`Fetcher`](../../src/kb_mcp/sources/roles.py) and a
[`Preparer`](../../src/kb_mcp/sources/roles.py) are an interface each; the serving side
reads documents alone, and imports no source ([contract
E](code-layout.md#the-contracts)). Their seams are data, not calls: the store that a
fetcher keeps ([`RawStore`](../../src/kb_mcp/sources/atlassian/fetch/adapters/raw_store.py)),
whose items each have an id, a revision and dates, and are present or gone; and documents
with their front matter ([`FrontMatter`](../../src/kb_mcp/mirror/domain/mirror.py)).
[The trade-offs](trade-offs.md#three-roles-not-a-bundle) give what this costs.

Each source's package is nested by role: `sources/atlassian/fetch/` brings the site's
changes into the raw store, and `sources/atlassian/prepare/` writes Confluence's and
Jira's files from it; the work log, read in place, has `sources/worklog/prepare/` alone.
Each writes through the mirror's common part: the front matter, which search reads back,
the writer of the files that changed, and pandoc. So the mirror imports no source, and no
source another ([the code's layout](code-layout.md#the-roles-within-a-source)).

## A source is a declaration

A source is data that names the code of its roles
([`Declared`](../../src/kb_mcp/sources/declaration.py)), and the three are declared alike:
[`CONFLUENCE`](../../src/kb_mcp/sources/atlassian/declared.py),
[`JIRA`](../../src/kb_mcp/sources/atlassian/declared.py) and
[`WORKLOG`](../../src/kb_mcp/sources/worklog/declared.py).

| Part | Where | Holds | Loaded |
|---|---|---|---|
| Declaration | `sources/<package>/declared.py` | its name, summary, resource types and options, its settings' names, its account, its table, its fetcher and preparers by module path, and its light checks | at every parse: standard library alone |
| Tables | `sources/<package>/settings.py` | the Pydantic models of `[sources.<name>]` and of its account | with the settings |
| Fetcher | `sources/<package>/fetch/app/` | a `Fetcher`; none for a source read in place | by the run that uses it |
| Preparers | `sources/<package>/prepare/app/` | a `Preparer` each, one per source today | by the run that uses it |

`--help` builds the whole parser, as a completion does at every Tab, so a declaration
stays light, and names the rest by module path, which the entry loads for its tables
([`enter`](../../src/kb_mcp/cli/commands/_shared.py)) and a run for its roles
([`loaded`](../../src/kb_mcp/cli/app/sources.py)). Within a package, the declaration sits
above the preparers, they above the fetcher, it above the tables: both roles read the
tables, and the declaration imports neither role ([contract
J](code-layout.md#the-contracts)). A declaration's light checks are functions that it
holds, which `fetch` asks before anything is asked of the user: what it refuses, such as
an API token without its email
([`token_without_email`](../../src/kb_mcp/sources/atlassian/declared.py)), what its run
does not apply, and what its summary says.

- **One fetcher may serve several sources.** Confluence and Jira name one fetcher, which
  reads the kinds of the source that it runs for from `run.declared`
  ([`targets_of`](../../src/kb_mcp/sources/atlassian/fetch/app/fetcher.py)), as their one
  preparer reads the kinds that it converts, and the source whose rows of the cache of
  conversions it reads ([`prepare_kinds`](../../src/kb_mcp/sources/atlassian/prepare/app/preparer.py)).
  Git, once re-planned, will name one fetcher and two preparers, which is why a
  declaration's preparers are a tuple. Until then no source names two, and two would share
  one row's name, `git`, told apart by their order alone: that plan names them.
- **A source keeps a store when it has a fetcher**, so no field says so.
- **Later plans add their fields**: 032 its flag rows; 033 a description and examples.

## The roles' interfaces

A role takes a [`Run`](../../src/kb_mcp/sources/roles.py), the source that it runs for and
all that it reads, and gives a [`Result`](../../src/kb_mcp/sources/roles.py). Any object
with a role's methods is one, and each source's is the module of its role, its functions
the methods, since none holds state. [`loaded`](../../src/kb_mcp/cli/app/sources.py) checks
it against the runtime-checkable protocol. A role may use the interfaces, the mirror,
`config`'s rules of a table ([`TABLE`](../../src/kb_mcp/config/domain/settings.py),
[`LocalPath`](../../src/kb_mcp/config/domain/settings.py)), `observability` and the
kernel, and no other source ([contract I](code-layout.md#the-contracts)).

- **`preflight`** says what a role cannot go on with, read from disk before any source
  starts, so that a run is refused before its first row, whichever source is at fault: an
  `--until` before `--since`
  ([the fetcher's](../../src/kb_mcp/sources/atlassian/fetch/app/fetcher.py)), or a work
  log that is not a folder
  ([its preparer's](../../src/kb_mcp/sources/worklog/prepare/app/preparer.py)).
- **`fetch`** brings a system's changes into the store that it owns, raw first
  ([`fetch_targets`](../../src/kb_mcp/sources/atlassian/fetch/app/fetcher.py)). A source
  read in place has no fetcher: the work log's preparer reads its folder, and its
  `preflight` checks it.
- **`prepare`** writes the source's documents through the mirror. In a dry run the
  fetcher plans ([`plan`](../../src/kb_mcp/sources/atlassian/fetch/app/download.py)), the
  work log's preparer counts
  ([`plan_worklog`](../../src/kb_mcp/sources/worklog/prepare/app/prepare.py)), and
  Atlassian's does not run.
- **A result** is a record, which `--format json` writes as every result, and whose `text`
  its row writes ([`text`](../../src/kb_mcp/cli/commands/sources.py)). Each keeps its
  own problems: the Atlassian prepare's
  [`Problem`](../../src/kb_mcp/sources/atlassian/prepare/app/prepare.py) has a place and a
  reason, the work log's
  [`Problem`](../../src/kb_mcp/sources/worklog/prepare/app/prepare.py) what it held back
  too, so `Result` holds none.
- **Pandoc is the preparers' own.** `Run` holds no tool that a role alone needs, so each
  preparer that converts finds it
  ([`Pandoc.find`](../../src/kb_mcp/mirror/adapters/pandoc.py)). Pandoc gone from `PATH`
  once the run began fails those rows alone; the run then exits as its rows rank, 1. The
  entry still refuses a `prepare` without pandoc on `PATH` before anything is asked,
  whichever sources it takes
  ([`enter`](../../src/kb_mcp/cli/commands/_shared.py)).

## Resource types

A source declares what it can read, each a
[`ResourceType`](../../src/kb_mcp/sources/declaration.py): its name, a summary, how it is
read ([`Reading`](../../src/kb_mcp/sources/declaration.py)), and its options, each an
[`Option`](../../src/kb_mcp/sources/declaration.py) that no setting holds. They match the
kinds that the raw store keeps
([`Page`](../../src/kb_mcp/sources/atlassian/fetch/domain/content.py),
[`BlogPost`](../../src/kb_mcp/sources/atlassian/fetch/domain/content.py),
[`Issue`](../../src/kb_mcp/sources/atlassian/fetch/domain/content.py)) and, for the work
log, which keeps no store, its documents' types
([`ENTRY`](../../src/kb_mcp/sources/worklog/prepare/domain/worklog.py) and the three
beside it):

| Source | Type | Read | Options |
|---|---|---|---|
| `confluence` | `pages`, `blogposts` | listed whole, per space | `--since`, `--until`, `--max-file-mb` |
| `jira` | `issues` | searched by update time, per project | the same |
| `worklog` | `entries`, `days`, `meetings`, `transcripts` | read whole, in place | none |

`--space` and `--project` replace a setting for one run
([`SPACE`](../../src/kb_mcp/sources/atlassian/declared.py), by its `setting`), until plan
032 generates flags from the settings. Plan 034 needs how each type is read: coverage per target, an exact
end only where searched by time. Choosing among a source's types waits for one worth
fetching apart, such as Jira's boards: until then a source's types are read whole. The
Atlassian fetcher lists every kind of a space, and its preparer, which removes the files
of every kind of its source, refuses a declaration that names some of them
([`preflight`](../../src/kb_mcp/sources/atlassian/prepare/app/preparer.py)). So a type's
name, its options and how it is read are read so far, the last in the groups of `fetch
--help` and `prepare --help`, each opening with its source's summary: plan 033 reads a
type's summary.

## The registry, a list in the code

[`SOURCES`](../../src/kb_mcp/sources/registry.py) holds the declarations in name order. The
entry, [`main`](../../src/kb_mcp/cli/main.py), takes the registry as a parameter, `SOURCES`
by default, and hands it to the parser's declarations and to
[`enter`](../../src/kb_mcp/cli/commands/_shared.py), so that a test registers a source of
its own without touching `src/`
([`registry`](../../tests/test_memo_source.py)).

Its rules hold for any registry that the entry is given
([`refuse`](../../src/kb_mcp/sources/registry.py)), and refuse, naming the declaration: a
name off `[a-z][a-z0-9]*` ([`SOURCE_NAME`](../../src/kb_mcp/kernel/names.py)), or `assets`;
two of one name; two declarations naming one account differently; a source naming no
setting, or neither a fetcher nor a preparer; an option that another source declares
otherwise, or that takes a flag of `fetch`'s own
([`add_source_options`](../../src/kb_mcp/cli/options/_sources.py)); a type read in a way that
the help has no words for ([`source_groups`](../../src/kb_mcp/cli/options/_sources.py)). An
option's value is kept
under its flag itself, so no flag takes a
name that the program holds. Once the arguments are parsed, so that `--help` imports no
table, the entry also refuses a table whose settings are not those that its declaration
names ([`tables`](../../src/kb_mcp/sources/registry.py)), whose name a model already holds,
such as `json`, or that cannot be built by default
([`settings_model`](../../src/kb_mcp/config/domain/settings.py)). These are a programmer's
errors, raised, not exits. A name is a table, a folder of the mirror, a command argument
from plan 031 on and the front matter's `source`, so one source type has one instance: two
Confluence sites or two work logs cannot be configured, and allowing them later (named
instances, `docs/<instance>/`) moves an existing source's files once. A run that cannot
load a role, whatever its import raises, exits 2, naming the declaration and the path
([`loaded`](../../src/kb_mcp/cli/app/sources.py)); a test loads every role of `SOURCES`
([`test_each_fetcher_that_the_registry_names_loads_as_a_fetcher`](../../tests/test_roles.py)).

`--help` imports the registry and the declarations, so contract G holds them to the
standard library, and modules put directly in `sources/`, outside contracts B and J, are
kept from effects and use cases by C
([`test_help_imports_the_declarations_and_no_module_that_they_name`](../../tests/test_roles.py)).
Contract I stays a list of packages, held to the registry by a test
([`test_contract_i_lists_the_package_of_each_registered_source_once`](../../tests/test_code_layout.py)):
Import Linter cannot read the registry, and the wildcard `kb_mcp.sources.*` would count
`roles`, `declaration` and `registry` as sources, so that a source importing `roles` would
break it. Each contract also carries its letter as its id, in the order of the layout
page's table
([`test_each_contract_s_id_is_its_letter_on_the_layout_page_in_its_order`](../../tests/test_code_layout.py)),
so that a contract added, removed or reordered without its row fails.

Entry points, which would let another distribution add a source without a line here, are
deferred: [the trade-offs](trade-offs.md#a-list-not-entry-points) say why, and a
declaration is what one would name, so that adding them later changes the registry's
module alone.

## Settings and accounts, composed from the registry

The settings file holds a table per source, `[sources.confluence]`, `[sources.jira]`,
`[sources.worklog]`, and the entry composes them into the settings' model, in name order,
each at its place among the fields
([`settings_model`](../../src/kb_mcp/config/domain/settings.py)), which
[`Loaded`](../../src/kb_mcp/config/domain/settings.py) carries for all that reads a
setting's path. So `config` imports no source: each table lives in its package
([`ConfluenceSource`](../../src/kb_mcp/sources/atlassian/settings.py),
[`JiraSource`](../../src/kb_mcp/sources/atlassian/settings.py),
[`WorklogSource`](../../src/kb_mcp/sources/worklog/settings.py)), with the rules that only
it uses ([`site_address`](../../src/kb_mcp/sources/atlassian/settings.py)). The file, the
environment (`KB_MCP_SOURCES__CONFLUENCE__SPACES`), the flags, layers, secrets and messages
work as for the core's settings, and a table with a setting of a type of no known kind is
refused, naming its source, as is a list of other than text, which no summary can show and
no rule of a path reads, and a table inside a table. Raw tables validated when their source runs were rejected:
they would let a misspelt key pass until then. `fetch` and `prepare` take their names from
the registry alone, and the names given choose among them. What a run does not apply, such
as Jira's projects in a `fetch confluence`, is said, not refused: the same settings serve
every run.

An account is what a fetcher signs in with: a light record in the declaration
([`ATLASSIAN`](../../src/kb_mcp/sources/atlassian/declared.py), an
[`Account`](../../src/kb_mcp/sources/declaration.py)) and a table in the package
([`AtlassianAccount`](../../src/kb_mcp/sources/atlassian/settings.py)). Confluence and Jira
name `atlassian`: `[accounts.atlassian]` holds `site`, `email` and `api_token`, the last
from `KB_MCP_ACCOUNTS__ATLASSIAN__API_TOKEN` alone. So the core knows no Atlassian setting,
and another sign-in is another account. `--site`, which
[`add_settings_options`](../../src/kb_mcp/cli/options/_common.py) gives every parser but
`completion`'s, replaces `accounts.atlassian.site` until plan 032 generates flags: so the
core still offers it under a registry without that account, as only a test gives, where it
exits 2, `not a setting`. The places `session/` and `runs/` stay `config`'s
([`Settings.parts`](../../src/kb_mcp/config/domain/settings.py)), which the data guard
judges.

A settings file of the former name, the default's or one that `--config` names, holding
these keys at its top is stopped before its entries are refused, each key named by its
final one ([`RENAMED`](../../src/kb_mcp/config/domain/former_name.py)), a token by the
variable that alone sets it, so that the user's machine's file gets its advice, and a value that
the former default's file holds and a setting refuses names that file's path as its layer
([move to kb-mcp](../how-to/move-to-kb-mcp.md)). Any other file holding
a top-level `site` or `email` is refused by
[`MOVED`](../../src/kb_mcp/config/domain/settings.py), naming `[accounts.atlassian]`.

## What every source's documents share

**The front matter checks what is common**
([`FrontMatter.check_front_matter`](../../src/kb_mcp/mirror/domain/mirror.py)): `source` a
source's name, `type` a lower-case word, `id` one safe path part, `revision` a token, a
key's own rule when it is set, one line per text, times in UTC, and the rules of people and
links, which name no source. A document that names a participant names no other role, so
that `read` stays within its budget. What `load` checks is this alone, so that a document of
a source that no registry names loads. Each builder checks its own, each by a subclass:
which source fills which key, its types, ids and revisions
([`AtlassianFrontMatter`](../../src/kb_mcp/sources/atlassian/prepare/domain/catalogue.py),
[`WorklogFrontMatter`](../../src/kb_mcp/sources/worklog/prepare/domain/worklog.py)). The keys
and their order do not change. The names follow: the Atlassian revision's rule moved to
the fetch's records ([`REVISION`](../../src/kb_mcp/sources/atlassian/fetch/domain/content.py)),
the work log's to its domain
([`WORKLOG_REVISION`](../../src/kb_mcp/sources/worklog/prepare/domain/worklog.py)).

**One rule says which files are documents**
([`documents`](../../src/kb_mcp/mirror/adapters/markdown.py)): every `.md` file under
`docs/`, but those under `assets/`, where an attached `x.md` is an asset, and those with a
name beginning with `_` or `.` on their path. A mirror that the program wrote holds the same
documents as under the patterns of three sources that it replaced; a stray `.md` file is
now read, and the index reports it as a file without front matter. It yields them sorted by
path, and search breaks its ties by path, so one thing served follows that order alone: where
two spellings of one person tie, on one account's documents of one second or by their counts,
the first in the order of the documents names the person
([`joined`](../../src/kb_mcp/search/domain/people.py)). So such a name can change at the first
index since the rule.

**Each source says which files it may remove**, in its `owned.py`
([`owned`](../../src/kb_mcp/sources/atlassian/prepare/adapters/owned.py),
[`worklog_owned`](../../src/kb_mcp/sources/worklog/prepare/adapters/owned.py)), and the
writer removes those alone
([`sync`](../../src/kb_mcp/mirror/adapters/mirror_files.py)). A source is code that the user
installs and trusts, run in process: no writer is bound to its folder, and ownership is
tested for each source.

**Attached files are deferred.** `docs/assets/` is Confluence's and Jira's together, a name
that the registry refuses. No other source attaches files yet, so no shared rule is built:
the first that does keeps them under `docs/<name>/_assets/`, in its own folder, so that no
other source removes them, and under a name beginning with `_`, which the rule of documents
keeps out of the index.

## Confluence and Jira, fetched and prepared apart

They share the site, the sign-in and the raw store, so `sources/atlassian/` stays one
package, but each is a source: a row, a report and a set of files of its own.

- **Fetched apart.** Each fetch is a download of its own source's targets
  ([`targets_of`](../../src/kb_mcp/sources/atlassian/fetch/app/fetcher.py)), so spaces,
  probes, projects and users keep their order across two runs, each with its own sign-in
  check, hold on the store and report, `<data>/runs/<time>-<source>.json`. The record of
  what answered as gone is Confluence's: a fetch of projects neither reads nor rewrites
  it, so that one damaged stops no run without Confluence.
- **Each placing both.** A page links an issue, and an issue a page, through one map of
  mirrored documents
  ([`Mirrored.documents`](../../src/kb_mcp/sources/atlassian/prepare/adapters/site_html.py)),
  and both attach files in `docs/assets/`. So each prepare reads the whole raw store and
  places every document, and converts only its own kinds
  ([`mirror`](../../src/kb_mcp/sources/atlassian/prepare/app/prepare.py)): pages and blog
  posts, with the spaces' trees, for Confluence; issues for Jira. Prepared in name order,
  Confluence then Jira, after any download, every link is what one prepare of both would
  make. `prepare confluence` prepares Confluence alone, so Jira's files whose links
  depend on Confluence's pages are rewritten only when Jira is prepared.
- **What each owns.** Confluence writes and removes under `docs/confluence/`, Jira under
  `docs/jira/`. `docs/assets/` is theirs together: each writes the files of its own
  documents, and removes a file that no placed document of either wants and no document
  file left links, since the last good copy of a document not rebuilt still shows it
  ([`unlinked`](../../src/kb_mcp/sources/atlassian/prepare/adapters/owned.py)).
- **Problems.** Each reports the problems of its own kinds. A snapshot or listing that
  cannot be read stops the removals of the source that it belongs to, and every removal
  under `docs/assets/`, since the files wanted are then unknown; each source's conversion
  problems stop its own removals alone. So an issue that pandoc fails on keeps its file, and
  Confluence's stale pages still go. What a prepare could not read of the other source
  fails nothing of its own, yet its files may then link the document's address on the site:
  it says so, by that source, under a row that stays done
  ([`prepare_kinds`](../../src/kb_mcp/sources/atlassian/prepare/app/preparer.py)).
- **The conversion cache.** Each prepare looks up and prunes its own rows
  ([`Conversions`](../../src/kb_mcp/mirror/adapters/conversions.py)), keyed by source and
  key, so that a text that both convert is a row of each, which neither prune takes from the
  other. A column keeps one file, which the data guard already judges. A file of the former
  columns fails [`COLUMNS`](../../src/kb_mcp/mirror/adapters/conversions.py) and is replaced
  once, so that the first prepare since converts everything again.
- **Cost.** The raw store is read and placed twice per prepare of both, in place of once:
  0.41 s more on a store of 1,474 documents, against 2.3 s for a `prepare` that the cache
  spares pandoc, and 31 s for one that it does not.

## `fetch` and `prepare` through the registry

[`run_each`](../../src/kb_mcp/cli/app/sources.py) is one use case over the sources taken:
every `preflight`, then each role, a row each. Each row runs even when an earlier one failed,
since the next reads what is on disk, Ctrl-C stops the rest, and the rows rank the exit status
([`RANKED`](../../src/kb_mcp/cli/domain/sources.py)). A row names its source, with its
result's text ([`Row`](../../src/kb_mcp/cli/domain/rows.py)); `index` and `embed` stay apart,
reading the mirror whatever sources it holds.

What a run says of a source comes from the declarations: the names that each command takes
are the registry's ([`register`](../../src/kb_mcp/cli/options/fetch.py),
[`register`](../../src/kb_mcp/cli/options/prepare.py)); a source is configured when its first
setting is set ([`chosen`](../../src/kb_mcp/cli/domain/sources.py)); and so do the summary's
lines ([`fetch_described`](../../src/kb_mcp/cli/domain/sources.py)), the settings not applied
of the sources left out ([`left_unapplied`](../../src/kb_mcp/cli/options/_sources.py)), the
light refusals ([`refused`](../../src/kb_mcp/cli/options/fetch.py)) and the options, each flag once. A
source's options and light checks are its fetch's, so a site not set refuses `fetch`, never
`prepare`. Both commands run by one module
([`run`](../../src/kb_mcp/cli/commands/sources.py)). `login` and `doctor` read each account
from the registry: its run, its checks and its light rules, each named by its
[`Account`](../../src/kb_mcp/sources/declaration.py).

## Kept for the extras, later

No extra is built, by the user's word. What makes them, later, a change of `pyproject.toml`
alone is kept: Playwright (138 MB installed) and lxml (12 MB) stay inside the Atlassian
package, by [contract K](code-layout.md#the-contracts). Of `sources/atlassian/`,
[its browser](../../src/kb_mcp/sources/atlassian/fetch/adapters/browser.py) alone imports
Playwright, for `login`, and [the site's HTML](../../src/kb_mcp/sources/atlassian/prepare/adapters/site_html.py)
alone lxml; `fetch`, `doctor`, the work log's prepare and `check` import neither. A
forbidden contract cannot leave one package out of a wildcard, so K names each context, and
a test holds it to them
([`test_contract_k_names_every_context_and_source_but_the_atlassian_package`](../../tests/test_code_layout.py)).

## A source added in one line

[`kb_memo`](../../tests/fixtures/memo_source/kb_memo/declared.py), in the tests, is shaped as
a package of this monorepo would be: its declaration, its table and a preparer that reads a
folder's text files in place and writes `docs/memo/<id>.md` through the mirror's
[`dump`](../../src/kb_mcp/mirror/adapters/markdown.py) and writer. It has no fetcher, as the
work log; the Atlassian sources prove the fetcher's seam. Given `SOURCES` and its declaration,
[its test](../../tests/test_memo_source.py) runs `--help`, `check`, `prepare` and `index`
through the entry, with no line of `src/` naming it.

## Not built

- **Persons and links across sources**, a later plan: a preparer over every document, listed
  in the registry apart from any source and run after the sources' own, writes person
  documents and links that one serving tool follows.
- **Plans 021 and 024, re-planned on the roles**: one package for the clones, its fetcher
  reading them in place or refreshing them, its preparers code and history; whether a code
  graph is served beside this program is the re-plan's question.
- **The identity that a document was synced as, whether a source's terms allow keeping
  content, and a live re-fetch on `read`**, each a change of its own: a key of the front
  matter, which rewrites every file; a field of the declaration, for a source that is only
  federated; a port in `mcp` that fetchers implement, which would change contract E.
- **The server's words for sources.** Its instructions, the `source` filter's values
  ([`SearchFilters`](../../src/kb_mcp/mcp/app/tools.py)), the id that `read` looks up, for
  Confluence's and the work log's documents alone
  ([`ENTRIES`](../../src/kb_mcp/search/adapters/sqlite_index.py)), and the front matter's
  Atlassian-shaped keys stay, until the first plan that adds a source composes them from the
  declarations: until a fourth source there is nothing to compose, and changing the keys
  rebuilds every file and the index.
- **Choosing a source's fetcher or preparers in the settings**: a declaration names them.
  **New places under the data directory, checks per source in `doctor`, a writer bound to a
  source's folder, isolation**: a source is code that the user installs and trusts.

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
([`WORKLOG_ROLES`](../../src/kb_mcp/sources/worklog/prepare/domain/worklog.py)),
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
work log's prepare writes each link both ways
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
It stays on this machine, as all the data does: `embed` sends its text to the
embedding endpoint, which must be a loopback address unless the run is given
`--allow-remote-embeddings` ([an endpoint off this
machine](../how-to/embeddings.md#reach-an-endpoint-off-this-machine)). Served to agents
it is untrusted reference data, like every page: a line in it that tells the reader
what to do is text, not an instruction.
