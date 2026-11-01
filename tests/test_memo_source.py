"""A source added in one line: the memo package of the tests, given to the entry.

Plan 030's criterion 4. ``tests/fixtures/memo_source/`` holds ``kb_memo``, shaped as a
package of this monorepo would be, its declaration, its table and its preparer, and no
module of ``src/`` names it: ``SOURCES`` and its declaration, one line, are the whole
registration. Given them, ``--help`` lists it among ``sync``'s choices and imports none
of contract G's packages; ``check`` lists its setting; ``sync`` writes under
``docs/memo/`` alone, search finds a note by a word only it holds, a second run writes
nothing and a note removed takes its file with it. Without that line, its table is not
a setting. The notes are invented.
"""

from __future__ import annotations

import importlib
import json
import os
import re
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

import kb_mcp
from kb_mcp.cli.main import main
from kb_mcp.kernel.exit_status import ExitStatus
from kb_mcp.mcp.app.tools import Library
from kb_mcp.mirror.adapters.markdown import load
from kb_mcp.sources.registry import SOURCES
from tests.answers import parts
from tests.mirrors import page, write
from tests.test_cli import RUNS_PACKAGES
from tests.test_worklog_served import refs

if TYPE_CHECKING:
    from _pytest.capture import CaptureFixture
    from _pytest.monkeypatch import MonkeyPatch

    from kb_mcp.sources.declaration import Declared

FIXTURE = Path(__file__).parent / "fixtures" / "memo_source"
# A word that one note holds, and no other.
WORD = "quillwort"
# When the notes were last changed: a day that no run is on.
NOTED = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)
# The source's name, or its package's, as a module of the program would write it.
NAMED = re.compile(r"\bmemo\b|\bkb_memo\b", re.IGNORECASE)


@pytest.fixture
def registry(monkeypatch: MonkeyPatch) -> tuple[Declared, ...]:
    """Give ``SOURCES`` and the memo's declaration, its package on the path: the one line."""
    monkeypatch.syspath_prepend(FIXTURE)
    return (*SOURCES, importlib.import_module("kb_memo.declared").MEMO)


@pytest.fixture
def config(tmp_path: Path) -> Path:
    """Write the settings: a data folder, search by words, and a folder of two notes."""
    notes = tmp_path / "notes"
    notes.mkdir()
    (notes / "orchard.txt").write_text(f"The orchard's {WORD} flowers in May.\n", "utf-8")
    (notes / "rota.txt").write_text("The rota changes on Monday.\n", "utf-8")
    for note in notes.iterdir():
        os.utime(note, (NOTED.timestamp(), NOTED.timestamp()))
    path = tmp_path / "config.toml"
    path.write_text(
        f'data_dir = {json.dumps(str(tmp_path / "data"))}\nsearch_mode = "lexical"\n'
        f"[sources.memo]\nfolder = {json.dumps(str(notes))}\n",
        "utf-8",
    )
    return path


def sync_memo(
    config: Path, registry: tuple[Declared, ...], capsys: CaptureFixture[str]
) -> list[dict[str, object]]:
    """Sync the memo alone, by the user's word; check that it exits 0, and give its rows."""
    given = ["sync", "--include", "memo", "--yes", "--config", str(config), "--format", "json"]
    assert main(given, registry) == ExitStatus.OK
    return json.loads(capsys.readouterr().out)["steps"]


def changes_of(rows: list[dict[str, object]]) -> dict[str, int]:
    """Give the counts of the prepare's row, the first, and check what the rows name.

    A source read in place has no fetcher, so a prepare, then the index, and each done.
    """
    assert [(row["step"], row["source"], row["outcome"]) for row in rows] == [
        ("prepare", "memo", "done"),
        ("index", None, "done"),
    ]
    return rows[0]["result"]["changes"]


def files_of(docs: Path) -> dict[Path, tuple[bytes, int]]:
    """Give each file under ``docs``, by its path there: its bytes and its time."""
    return {
        path.relative_to(docs): (path.read_bytes(), path.stat().st_mtime_ns)
        for path in docs.rglob("*")
        if path.is_file()
    }


def test_help_lists_it_and_imports_none_of_the_runs_packages(tmp_path: Path) -> None:
    """In a fresh interpreter, ``sync --help`` offers it, having imported its declaration alone.

    ``-X importtime`` names each module that the child imports, so that a package it does
    not name never reached ``sys.modules``: neither one of G's, nor the source's table
    or role.
    """
    child = subprocess.run(
        [
            sys.executable,
            "-X",
            "importtime",
            "-c",
            (
                "from kb_mcp.cli.main import main\n"
                "from kb_mcp.sources.registry import SOURCES\n"
                "from kb_memo.declared import MEMO\n"
                "main(['sync', '--help'], (*SOURCES, MEMO))\n"
            ),
        ],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        env={
            "HOME": str(tmp_path),
            "PATH": os.environ["PATH"],
            "PYTHONPATH": str(FIXTURE),
            "COLUMNS": "200",
        },
        cwd=tmp_path,
        check=False,
    )
    assert child.returncode == 0
    assert re.search(r"--include \{(?:\w+,)*memo(?:,\w+)*\}", child.stdout)
    imported = {
        line.rsplit("|", 1)[-1].strip()
        for line in child.stderr.splitlines()
        if line.startswith("import time:")
    }
    assert "kb_memo.declared" in imported
    assert not imported & {"kb_memo.settings", "kb_memo.prepare.app.preparer"}
    assert not {module.split(".")[0] for module in imported} & RUNS_PACKAGES


def test_check_lists_its_setting(
    config: Path, registry: tuple[Declared, ...], capsys: CaptureFixture[str]
) -> None:
    """Its table is composed into the settings, read from the file, and read by ``check``.

    In detail too, whose every setting not read is said to be ignored.
    """
    assert main(["check", "--config", str(config)], registry) == ExitStatus.OK
    folder = config.parent / "notes"
    assert f"sources.memo.folder: {folder}\n" in capsys.readouterr().out
    detailed = ["check", "--config", str(config), "--summary", "detailed"]
    assert main(detailed, registry) == ExitStatus.OK
    out, err = capsys.readouterr()
    assert f"sources.memo.folder: {folder} " in out
    assert "sources.memo.folder" not in err


def test_sync_writes_under_its_folder_alone_and_search_finds_a_note(
    config: Path, registry: tuple[Declared, ...], capsys: CaptureFixture[str]
) -> None:
    """Each note is a file of ``docs/memo/``, and another source's stays as it was.

    Search finds the note by a word that it alone holds, and the path that its hit shows
    opens it: the server looks up a ref for Confluence's and the work log's documents
    alone (``ENTRIES``), until a plan composes its words for sources from the declarations.
    """
    data = config.parent / "data"
    write(data / "docs", page("196845", "Kafka"))
    before = files_of(data / "docs")
    assert changes_of(sync_memo(config, registry, capsys)) == {
        "written": 2,
        "unchanged": 0,
        "removed": 0,
    }
    after = files_of(data / "docs")
    assert {path: after[path] for path in before} == before
    made = [path for path in after if path not in before]
    assert len(made) == len(["orchard", "rota"])
    assert all(path.parts[0] == "memo" and len(path.parts) == len(["memo", "x"]) for path in made)
    served = Library(data / "index.sqlite", data / "docs")
    assert len(refs(served.search(WORD))) == 1
    _, hits, _ = parts(served.search(WORD))
    (found,) = [path.as_posix() for path in made if path.as_posix() in hits]
    _, read, _ = parts(served.read(found))
    assert WORD in read


def test_a_second_sync_writes_nothing(
    config: Path, registry: tuple[Declared, ...], capsys: CaptureFixture[str]
) -> None:
    """Each note found unchanged keeps its file, its bytes and its time.

    A document's times are its note's, never the run's, which would change its bytes.
    """
    docs = config.parent / "data" / "docs"
    sync_memo(config, registry, capsys)
    before = files_of(docs)
    for path, (data, _) in before.items():
        matter, _ = load(data.decode(), str(path))
        assert (matter.created, matter.updated, matter.fetched_at) == (NOTED, NOTED, NOTED)
    assert changes_of(sync_memo(config, registry, capsys)) == {
        "written": 0,
        "unchanged": 2,
        "removed": 0,
    }
    assert files_of(docs) == before


def test_a_note_removed_takes_its_file_with_it(
    config: Path, registry: tuple[Declared, ...], capsys: CaptureFixture[str]
) -> None:
    """Its file goes, and only its; search no longer finds it. Another source's file stays."""
    data = config.parent / "data"
    write(data / "docs", page("196845", "Kafka"))
    sync_memo(config, registry, capsys)
    before = files_of(data / "docs")
    (config.parent / "notes" / "orchard.txt").unlink()
    assert changes_of(sync_memo(config, registry, capsys)) == {
        "written": 0,
        "unchanged": 1,
        "removed": 1,
    }
    assert files_of(data / "docs") == {
        path: held for path, held in before.items() if WORD.encode() not in held[0]
    }
    assert refs(Library(data / "index.sqlite", data / "docs").search(WORD)) == []


def test_a_dry_run_writes_nothing(
    config: Path, registry: tuple[Declared, ...], capsys: CaptureFixture[str]
) -> None:
    """The prepare and the index are not run, and no file of the mirror is made."""
    given = ["sync", "--include", "memo", "--dry-run", "--config", str(config), "--format", "json"]
    assert main(given, registry) == ExitStatus.OK
    rows = json.loads(capsys.readouterr().out)["steps"]
    assert [(row["step"], row["outcome"]) for row in rows] == [
        ("prepare", "not run"),
        ("index", "not run"),
    ]
    assert not (config.parent / "data").exists()


def test_a_folder_of_notes_that_is_not_one_is_refused_before_any_row(
    config: Path, registry: tuple[Declared, ...], capsys: CaptureFixture[str]
) -> None:
    """Its preflight refuses the run, exit 2, by its setting; nothing is written."""
    (config.parent / "notes" / "orchard.txt").unlink()
    (config.parent / "notes" / "rota.txt").unlink()
    (config.parent / "notes").rmdir()
    given = ["sync", "--include", "memo", "--yes", "--config", str(config)]
    assert main(given, registry) == ExitStatus.REFUSED
    assert "sources.memo.folder: not a folder" in capsys.readouterr().err
    assert not (config.parent / "data" / "docs").exists()


def test_without_that_line_its_table_is_no_setting_and_its_name_no_choice(
    config: Path, capsys: CaptureFixture[str]
) -> None:
    """The registry is the only way in: the same file is refused, the same flag too."""
    assert main(["check", "--config", str(config)]) == ExitStatus.REFUSED
    assert "sources.memo.folder (config.toml): not a setting" in capsys.readouterr().err
    with pytest.raises(SystemExit) as stopped:
        main(["sync", "--include", "memo", "--yes", "--config", str(config)])
    assert stopped.value.code == ExitStatus.REFUSED
    assert "invalid choice: 'memo'" in capsys.readouterr().err


def test_no_module_of_the_program_names_it() -> None:
    """Nothing under ``src/`` knows the source that the test registers."""
    package = Path(kb_mcp.__file__).parent
    named = [path for path in package.rglob("*.py") if NAMED.search(path.read_text("utf-8"))]
    assert named == []
