# Add a source

For contributors: how to add a source of documents, so that the settings, `check`, `prepare`
and search know it. A [source](../reference/concepts.md#connector) is added as a package and one line of the registry; [sources](../explanation/sources.md)
says why. The example here is a folder of text files, read in place, under the name `notes`.
[`kb_memo`](../../tests/fixtures/memo_source/kb_memo/declared.py), in the tests, is the same
source, outside `src/`, which [its test](../../tests/test_memo_source.py) registers and runs.

You need a checkout whose checks pass, as [your first change](../tutorials/first-change.md)
shows, and pandoc on `PATH`: `prepare` refuses a run without it, whichever sources it takes
([`register`](../../src/kb_mcp/cli/options/prepare.py) names it among its programs).

## 1. Choose its name

The name is a table, `[sources.notes]`, a folder of the mirror, `docs/notes/`, and the
front matter's `source`, so the source is configured once. It is lower-case letters and
digits, beginning with a letter, and not `assets`
([`refuse`](../../src/kb_mcp/sources/registry.py)).

## 2. Make its package

A source read in place takes part in one stage, `prepare/`:

```bash
mkdir -p src/kb_mcp/sources/notes/prepare/app
```

Each folder is a package with a docstring. Create `src/kb_mcp/sources/notes/__init__.py`:

```python
"""Notes: a folder's text files, read in place, never written."""
```

Create `src/kb_mcp/sources/notes/prepare/__init__.py`:

```python
"""The prepare of the notes: read in place, as the mirror's files."""
```

Create `src/kb_mcp/sources/notes/prepare/app/__init__.py`:

```python
"""The notes' use case: their preparer."""
```

## 3. Write its table

The table is a Pydantic model of `[sources.notes]`. Its first setting names what the source
covers: a source whose first setting is not set is left out, as not configured
([`chosen`](../../src/kb_mcp/cli/domain/sources.py)). `TABLE` refuses a misspelt key, and
`LocalPath` reads a folder, absolute or under `~`
([`TABLE`](../../src/kb_mcp/config/domain/settings.py),
[`LocalPath`](../../src/kb_mcp/config/domain/settings.py)). A setting is text, a flag, a
number, a choice, a path, a secret, or a list of text, `tuple[str, ...]`; anything else,
such as a list of paths or a table inside the table, is refused as the settings are
composed, naming the source ([`kind_of`](../../src/kb_mcp/config/domain/settings.py)). Create
`src/kb_mcp/sources/notes/settings.py`:

```python
"""The notes' table of settings, ``[sources.notes]``.

Its declaration names it; the entry composes it into the settings' model.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from kb_mcp.config.domain.settings import TABLE, LocalPath


class NotesTable(BaseModel):
    """The folder of the notes, read in place and never written."""

    model_config = TABLE

    folder: LocalPath | None = Field(
        default=None,
        description="The notes' folder, absolute or under ~: its *.txt files, read in place.",
    )
```

## 4. Write its declaration

The declaration is data ([`Source`](../../src/kb_mcp/sources/declaration.py)), in the
standard library alone, since `--help` imports it: it names the table, the fetcher and the preparers by
module path. Each resource type says what the source reads and how
([`ResourceType`](../../src/kb_mcp/sources/declaration.py)). A source that signs in also
names its `account`, and one with a fetcher its `fetcher`; a light check that `fetch` asks
before anything else goes in `refused`, as Confluence's does
([`CONFLUENCE`](../../src/kb_mcp/sources/atlassian/declared.py)). Create
`src/kb_mcp/sources/notes/declared.py`:

```python
"""The notes' declaration: what they read in place, their table, and their preparer.

Read in place, they have no fetcher and no account. Standard library alone, as every
declaration is: ``--help`` imports it.
"""

from __future__ import annotations

from kb_mcp.sources.declaration import ResourceType, Source

NOTES = Source(
    name="notes",
    help="Notes: a folder's text files, read in place, never written",
    resource_types=(ResourceType(name="notes", help="the folder's *.txt files", read="in place"),),
    settings=("folder",),
    table_path="kb_mcp.sources.notes.settings:NotesTable",
    preparers=("kb_mcp.sources.notes.prepare.app.preparer",),
)
```

## 5. Write its preparer

A preparer has two functions ([`Preparer`](../../src/kb_mcp/sources/stages.py)): `preflight`,
what it cannot go on with, read before any source starts, which `prepare` says after the
source's name and the stage, and `prepare`, which writes the
documents through the mirror and gives a [`Result`](../../src/kb_mcp/sources/stages.py), its
counts and how they read as text. Mind what the writer and the front matter ask:

- **Write every document, each time.** The writer leaves a file whose bytes have not
  changed, and removes what `owned` finds and no document wants
  ([`write_changed`](../../src/kb_mcp/mirror/adapters/mirror_files.py)). So a document's bytes depend
  on its source alone, never on the time of the run: a second run then writes nothing.
- **Own your folder alone.** `owned` finds your files under `docs/notes/`, and nothing else;
  a source is trusted code, and no writer is bound to its folder.
- **Fill every key.** A key that does not apply is `None`, or empty where the type says so;
  the keys that Atlassian shapes stay `None`
  ([`FrontMatter`](../../src/kb_mcp/mirror/domain/mirror.py),
  [the table](../reference/data-layout.md#the-markdown-mirror)). `id` is one safe path part,
  and so a digest of a name makes one of any name; a text is one line
  ([`one_line`](../../src/kb_mcp/mirror/domain/mirror_text.py)).
- **Keep out of `docs/assets/`.** It is Confluence's and Jira's. A source that attaches
  files keeps them under `docs/notes/_assets/`, which the rule of documents leaves out
  ([`documents`](../../src/kb_mcp/mirror/adapters/markdown.py)).

A larger source splits this module by layer, its effects in `prepare/adapters/` and its
rules in `prepare/domain/`, as the work log's does
([`prepare_worklog`](../../src/kb_mcp/sources/worklog/prepare/app/prepare.py)). Create
`src/kb_mcp/sources/notes/prepare/app/preparer.py`:

```python
"""The notes' preparer: a folder's text files, as the mirror's documents.

The notes' declaration names this module, a ``Preparer``: ``preflight`` refuses a folder
that is not one before any source starts, and ``prepare`` writes each ``*.txt`` file as
``docs/notes/<id>.md`` through the mirror's writer, which leaves a file that has not
changed and removes those of notes gone, under ``docs/notes/`` alone. A note's times are
its file's, so that a run that finds it unchanged writes the same bytes; its id is a
digest of its file's name, so that any name makes an id.
"""

from __future__ import annotations

from datetime import UTC, datetime
from hashlib import sha256
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, override

from kb_mcp.mirror.adapters.markdown import documents, dump
from kb_mcp.mirror.adapters.mirror_files import Changes, regular_files, write_changed
from kb_mcp.mirror.domain.mirror import FrontMatter
from kb_mcp.mirror.domain.mirror_text import one_line
from kb_mcp.sources.stages import Result

if TYPE_CHECKING:
    from pathlib import Path

    from kb_mcp.kernel.output import Detail
    from kb_mcp.sources.stages import SourceRun

# The source's name, which is its folder of the mirror too, as the registry's rule has it.
SOURCE = "notes"


class NotesPrepared(Result):
    """A prepare: how it ended, and the files it changed, None in a dry run, which writes none."""

    changes: Changes | None

    @override
    def text(self, summary: Detail) -> str:
        """Write the files that it changed, whichever the detail; nothing in a dry run."""
        done = self.changes
        return (
            ""
            if done is None
            else f"written: {done.written}\nunchanged: {done.unchanged}\nremoved: {done.removed}\n"
        )


def owned(docs: Path) -> set[PurePosixPath]:
    """Return the files under ``docs`` that the source may remove: its documents alone."""
    return regular_files(docs, documents(docs, (f"{SOURCE}/*.md",)))


def preflight(run: SourceRun) -> str | None:
    """Refuse a folder of notes that is not one, by its setting, before any source starts."""
    return None if run.source_table.folder.is_dir() else f"sources.{SOURCE}.folder: not a folder"


def prepare(run: SourceRun) -> NotesPrepared:
    """Write a document per note and remove those of notes gone, unless a dry run."""
    if run.dry_run:
        return NotesPrepared(outcome="not run", changes=None)
    wanted: dict[PurePosixPath, bytes | Path] = {}
    for path in sorted(run.source_table.folder.glob("*.txt")):
        text = path.read_text("utf-8", errors="replace")
        when = datetime.fromtimestamp(path.stat().st_mtime, UTC)
        identifier = sha256(path.name.encode()).hexdigest()[:16]
        matter = FrontMatter(
            source=SOURCE,
            type="note",
            id=identifier,
            key=None,
            title=one_line(path.stem),
            space=None,
            project=None,
            status="",
            issue_type=None,
            labels=(),
            people=(),
            links=(),
            created=when,
            updated=when,
            version=None,
            revision=sha256(text.encode()).hexdigest(),
            url=None,
            breadcrumb=(),
            fetched_at=when,
        )
        wanted[PurePosixPath(SOURCE, f"{identifier}.md")] = dump(matter, text).encode()
    return NotesPrepared(
        outcome="done", changes=write_changed(run.settings.docs, wanted, owned, remove=True)
    )
```

## 6. Register it

In `src/kb_mcp/sources/registry.py`, import the declaration, beside the others:

```python
from kb_mcp.sources.notes.declared import NOTES
```

and add it to the registry, in name order:

```python
SOURCES = (CONFLUENCE, JIRA, NOTES, WORKLOG)
```

That one line makes `[sources.notes]` a setting, `notes` a choice of `prepare`, and
its `preparers` part of each run that takes it
([`settings_model`](../../src/kb_mcp/config/domain/settings.py),
[`run_each`](../../src/kb_mcp/cli/app/sources.py)).

## 7. Give it its place in the contracts

Contracts B, C, G and J reach a new package by their wildcards; contracts I and K list
theirs, and [the tests](../../tests/test_code_layout.py) fail, naming what differs, until
it joins them. In `pyproject.toml`, add it to contract I's `modules`:

```toml
modules = ["kb_mcp.sources.atlassian", "kb_mcp.sources.notes", "kb_mcp.sources.worklog"]
```

and to contract K's `source_modules`, beside the work log:

```toml
"kb_mcp.sources.notes",
```

Then check them:

```bash
uv run lint-imports
```

It ends with:

```text
Contracts: 11 kept, 0 broken.
```

## 8. Test it

Create `tests/test_notes_source.py`, its expectations from what a source must do. The
notes here are invented; so are any other fixture's, or come from the sandbox:

```python
"""The notes: a folder's text files, prepared, found, and gone with their file."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from kb_mcp.cli.main import main
from kb_mcp.kernel.exit_status import ExitStatus
from kb_mcp.mcp.app.tools import Library

if TYPE_CHECKING:
    from pathlib import Path


def test_a_note_is_mirrored_found_and_gone_with_its_file(tmp_path: Path) -> None:
    """Prepare writes it under its folder alone, search finds it, and its removal takes its file."""
    notes, data = tmp_path / "notes", tmp_path / "data"
    notes.mkdir()
    note = notes / "orchard.txt"
    note.write_text("The orchard's quillwort flowers in May.\n", "utf-8")
    config = tmp_path / "config.toml"
    config.write_text(
        f'data_dir = {json.dumps(str(data))}\nsearch_mode = "lexical"\n'
        f"[sources.notes]\nfolder = {json.dumps(str(notes))}\n",
        "utf-8",
    )
    given = ["prepare", "notes", "--yes", "--config", str(config)]
    assert main(given) == ExitStatus.OK
    assert main(["index", "--yes", "--config", str(config)]) == ExitStatus.OK
    (file,) = (data / "docs").rglob("*.md")
    assert file.parent == data / "docs" / "notes"
    assert "orchard" in Library(data / "index.sqlite", data / "docs").search("quillwort")

    before = file.stat().st_mtime_ns
    assert main(given) == ExitStatus.OK
    assert file.stat().st_mtime_ns == before

    note.unlink()
    assert main(given) == ExitStatus.OK
    assert not file.exists()
```

Some tests name the registry whole, or give every setting by its path, so they name a new
source too: those of `tests/test_registry.py`, `tests/test_stages.py`, `tests/test_settings.py`,
`tests/test_cli.py`, `tests/test_sources.py`, `tests/test_preview.py` and `tests/test_docs.py`
that do fail until they do, each naming what it lacks, such as
`KeyError: 'sources.notes.folder'`. Run them all, and give each its line:

```bash
uv run pytest -n auto
```

## 9. Generate the reference

The reference of settings and commands comes from the code, and `prepare`'s choices and the
new table have changed. Write the pages again, and commit what changes:

```bash
uv run python -m tests.reference_pages
```

Then run every check of [`AGENTS.md`](../../AGENTS.md).

## 10. Try it

Point a settings file of its own at a folder of notes, and a data folder that is neither in
a synchronised folder nor in a git tree:

```bash
mkdir -p ~/notes-try/notes
echo "The rota changes on Monday." > ~/notes-try/notes/rota.txt
```

Create `~/notes-try/config.toml`, with your home's absolute path:

```toml
data_dir = "/home/you/notes-try/data"
search_mode = "lexical"

[sources.notes]
folder = "/home/you/notes-try/notes"
```

`check` lists the setting that the file gives, and the rest of the file's:

```bash
uv run kb-mcp check --config ~/notes-try/config.toml
```

```text
data_dir: /home/you/notes-try/data
search_mode: lexical
sources.notes.folder: /home/you/notes-try/notes
```

`prepare` takes it, the one source read in place that this file configures, after each
source that keeps a store, each with nothing to do; `fetch` does not offer it, as it has no
fetcher. Then `index` reads the mirror:

```bash
uv run kb-mcp prepare --yes --config ~/notes-try/config.toml
uv run kb-mcp index --yes --config ~/notes-try/config.toml
```

Its last row, after those of each store:

```text
notes: done
  written: 1
  unchanged: 0
  removed: 0
documents: 1
sections: 1
```

Remove `~/notes-try` once you have seen it.

## A source that fetches

A source that reaches a system also has a fetcher: `fetch/app/fetcher.py`, a module with
`preflight` and `fetch` ([`Fetcher`](../../src/kb_mcp/sources/stages.py)), its declaration's
`fetcher`, which keeps its system's responses raw, for its preparer to read. Preparing may
use what fetching keeps, never the reverse (contract J). One that signs in names an
[`Account`](../../src/kb_mcp/sources/declaration.py), whose table is `[accounts.<name>]`, read
by `run.account_table`. [Confluence and Jira](../../src/kb_mcp/sources/atlassian/fetch/app/fetcher.py)
are the worked example: one fetcher, reading the resource types of the source that it runs for from
`run.source`. No other source keeps a store yet: its place under the data directory is a
plan's to add, since the data guard judges each
([`Settings.parts`](../../src/kb_mcp/config/domain/settings.py)).

## What it does not get yet

The server's words for sources wait until a plan composes them from the declarations:

- **`read` opens a hit by its path.** A hit shows the document's id and its path; the id is
  looked up for Confluence's and the work log's documents alone
  ([`ENTRIES`](../../src/kb_mcp/search/adapters/sqlite_index.py)), so that the `read` call
  that a hit gives says the document is not mirrored, and `read` by the path opens it
  ([`NOT_MIRRORED`](../../src/kb_mcp/mcp/app/tools.py)).
- **The `source` filter** takes `confluence`, `jira` or `worklog` alone
  ([`SearchFilters`](../../src/kb_mcp/mcp/app/tools.py)), and the server's instructions name
  those three ([`CLOSING`](../../src/kb_mcp/mcp/app/surface.py)).
- **Filters by space or project** read the front matter's Atlassian-shaped keys, which a new
  source fills with `null`.
