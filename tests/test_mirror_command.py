"""The ``mirror`` command as the user meets it, and pandoc as the mirror runs it."""

from __future__ import annotations

import hashlib
import json
import os
import stat
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from atlassian_offline_mcp.cli.main import main
from atlassian_offline_mcp.kernel.content import Page
from atlassian_offline_mcp.mirror.adapters.pandoc import (
    Pandoc,
    PandocFailedError,
    PandocMissingError,
)
from atlassian_offline_mcp.sources.atlassian.adapters import confluence_v2
from atlassian_offline_mcp.sources.atlassian.adapters.raw_store import RawStore
from tests.reference import STANDARD
from tests.samples import v2_page, v2_space, v2_view
from tests.test_cli import logged_as
from tests.test_mirror import FETCHED, SPACE_ID, listing_page, page_responses
from tests.test_observed import said

if TYPE_CHECKING:
    from pathlib import Path

    from _pytest.capture import CaptureFixture
    from _pytest.monkeypatch import MonkeyPatch

SOME_FAILED = 1
BAD_SETTINGS = 2


@pytest.fixture
def home(tmp_path: Path, monkeypatch: MonkeyPatch) -> Path:
    """Give each test a scratch home directory, so that none reads or writes the user's."""
    scratch = tmp_path / "home"
    scratch.mkdir()
    monkeypatch.setenv("HOME", str(scratch))
    return scratch


def fake_pandoc(folder: Path, script: str) -> Path:
    """Put an executable ``pandoc`` running this shell script in a folder, and return it."""
    folder.mkdir(exist_ok=True)
    pandoc = folder / "pandoc"
    pandoc.write_text(f"#!/bin/sh\n{script}\n", "utf-8")
    pandoc.chmod(pandoc.stat().st_mode | stat.S_IXUSR)
    return folder


def arguments(home: Path, *extra: str) -> list[str]:
    """Return the command line of ``mirror`` with a scratch settings file and data."""
    return [
        "mirror",
        "--yes",
        "--config",
        str(home / "none.toml"),
        "--data-dir",
        str(home / "data"),
        *extra,
    ]


def test_without_pandoc_the_mirror_names_it_and_writes_nothing(
    home: Path, monkeypatch: MonkeyPatch, capsys: CaptureFixture[str]
) -> None:
    """Refused before anything is asked, exit 2, naming pandoc by run.refused; and no mirror."""
    empty = home / "bin"
    empty.mkdir()
    monkeypatch.setenv("PATH", str(empty))
    assert main(arguments(home)) == BAD_SETTINGS
    err = capsys.readouterr().err
    assert said(err) == [("error", "run.refused")]
    assert "pandoc: not found on PATH" in err
    assert not (home / "data" / "docs").exists()


def test_pandoc_gone_once_the_run_starts_fails_it_with_an_error(
    home: Path, monkeypatch: MonkeyPatch, capsys: CaptureFixture[str]
) -> None:
    """On PATH for the entry, gone for the run: exit 1, the error mirror.pandoc_missing.

    The run's log file holds it with its reason, and no mirror is written.
    """
    monkeypatch.setenv("PATH", str(fake_pandoc(home / "bin", "cat")))
    message = "pandoc: not found on PATH; install pandoc 3"

    def gone() -> Pandoc:
        raise PandocMissingError(message)

    monkeypatch.setattr(Pandoc, "find", gone)
    assert main(arguments(home)) == SOME_FAILED
    err = capsys.readouterr().err
    assert ("error", "mirror.pandoc_missing") in said(err)
    assert message in err
    (missing,) = logged_as(home, "mirror.pandoc_missing")
    assert (missing["level"], missing["reason"]) == ("error", message)
    assert not (home / "data" / "docs").exists()


def test_refused_settings_exit_two(home: Path, capsys: CaptureFixture[str]) -> None:
    """A site that is not an https host is refused before anything runs."""
    assert main(arguments(home, "--site", "http://plain.example.invalid")) == BAD_SETTINGS
    assert "site" in capsys.readouterr().err


def test_an_empty_store_mirrors_nothing_and_exits_zero(
    home: Path, capsys: CaptureFixture[str]
) -> None:
    """A data directory without a raw store gives an empty mirror, and counts of zero."""
    assert main(arguments(home)) == 0
    assert capsys.readouterr().out == (
        "documents: 0\n"
        "converted by pandoc: 0\n"
        "reused from the cache: 0\n"
        "files written: 0\n"
        "files unchanged: 0\n"
        "files removed: 0\n"
        "problems: 0\n"
    )


def test_what_the_mirror_does_not_show_is_counted_in_detail_alone(
    home: Path, capsys: CaptureFixture[str]
) -> None:
    """A page with a frame: short gives the counts; detailed, the frame's too, by its name.

    The second run converts nothing and writes nothing: it reuses what the first
    converted, and finds unchanged what the first wrote.
    """
    store = RawStore(home / "data" / "raw")
    html = '<p>Home.</p><iframe src="http://example.invalid/x"></iframe>'
    with store.writing():
        store.put_space(v2_space(id=SPACE_ID), [listing_page("100", "Home", None, None)], [], [])
        store.put(Page, page_responses("100", "Home", 1, html, []), FETCHED, {})
    assert main(arguments(home)) == 0
    first = capsys.readouterr().out.splitlines()
    names = [
        "documents",
        "converted by pandoc",
        "reused from the cache",
        "files written",
        "files unchanged",
        "files removed",
        "problems",
    ]
    assert [line.split(": ")[0] for line in first] == names
    assert first[0] == "documents: 1"
    converted = first[1].removeprefix("converted by pandoc: ")
    written = first[3].removeprefix("files written: ")
    assert main(arguments(home, "--summary", "detailed")) == 0
    assert capsys.readouterr().out == (
        "documents: 1\n"
        "converted by pandoc: 0\n"
        f"reused from the cache: {converted}\n"
        "files written: 0\n"
        f"files unchanged: {written}\n"
        "files removed: 0\n"
        "not shown, element: iframe: 1\n"
        "problems: 0\n"
    )


def test_the_command_reports_the_documents_it_builds(
    home: Path, capsys: CaptureFixture[str]
) -> None:
    """Two pages: the run's log file ends the task documents with both done."""
    store = RawStore(home / "data" / "raw")
    listed = [listing_page("100", "Home", None, None), listing_page("101", "Away", None, None)]
    with store.writing():
        store.put_space(v2_space(id=SPACE_ID), listed, [], [])
        store.put(Page, page_responses("100", "Home", 1, "<p>Home.</p>", []), FETCHED, {})
        store.put(Page, page_responses("101", "Away", 1, "<p>Away.</p>", []), FETCHED, {})
    assert main(arguments(home)) == 0
    assert capsys.readouterr().out.startswith("documents: 2\n")
    assert [
        (line["task"], line["done"], line["total"]) for line in logged_as(home, "progress")
    ] == [("documents", 2, 2)]


def two_pages(home: Path, monkeypatch: MonkeyPatch) -> Path:
    """Store a space and two pages; put a pandoc on PATH that notes each conversion it runs.

    It passes its input through, and answers ``--version`` with a version line. Give the
    file that holds a line per conversion.
    """
    runs = home / "runs"
    script = f'case "$1" in --version) echo "pandoc 9.9";; *) echo run >> "{runs}"; cat;; esac'
    folder = fake_pandoc(home / "bin", script)
    monkeypatch.setenv("PATH", f"{folder}{os.pathsep}{os.environ['PATH']}")
    store = RawStore(home / "data" / "raw")
    listed = [listing_page("100", "Home", None, None), listing_page("101", "Away", None, None)]
    with store.writing():
        store.put_space(v2_space(id=SPACE_ID), listed, [], [])
        store.put(Page, page_responses("100", "Home", 1, "<p>Home.</p>", []), FETCHED, {})
        store.put(Page, page_responses("101", "Away", 1, "<p>Away.</p>", []), FETCHED, {})
    return runs


# The two pages' files and their space's tree.
CONVERSIONS = 3


def test_a_second_mirror_with_nothing_changed_runs_pandoc_on_nothing(
    home: Path, monkeypatch: MonkeyPatch, capsys: CaptureFixture[str]
) -> None:
    """Plan 039, criterion 5: its text and its JSON say that each conversion was reused."""
    runs = two_pages(home, monkeypatch)
    assert main(arguments(home)) == 0
    assert "documents: 2\nconverted by pandoc: 3\nreused from the cache: 0\n" in (
        capsys.readouterr().out
    )
    assert len(runs.read_text("utf-8").splitlines()) == CONVERSIONS
    assert main(arguments(home)) == 0
    assert capsys.readouterr().out.startswith(
        "documents: 2\nconverted by pandoc: 0\nreused from the cache: 3\nfiles written: 0\n"
    )
    assert main(arguments(home, "--format", "json")) == 0
    document = json.loads(capsys.readouterr().out)
    assert (document["converted"], document["reused"]) == (0, CONVERSIONS)
    assert len(runs.read_text("utf-8").splitlines()) == CONVERSIONS


def test_a_damaged_cache_is_replaced_and_the_mirror_converts_everything(
    home: Path, monkeypatch: MonkeyPatch, capsys: CaptureFixture[str]
) -> None:
    """Plan 039, criterion 8: exit 0, nothing reused, one warning by SQLite's error name.

    The cache, filled by a first run, and its -wal and -shm become random bytes; the run
    leaves the cache alone, which the next run reuses.
    """
    two_pages(home, monkeypatch)
    assert main(arguments(home)) == 0
    cache = home / "data" / "conversions.sqlite"
    for suffix in ("", "-wal", "-shm"):
        noise = hashlib.shake_256(suffix.encode()).digest(8192)
        cache.with_name(f"{cache.name}{suffix}").write_bytes(noise)
    capsys.readouterr()
    assert main(arguments(home)) == 0
    assert "converted by pandoc: 3\nreused from the cache: 0\n" in capsys.readouterr().out
    (replaced,) = logged_as(home, "mirror.cache_replaced")
    assert (replaced["level"], replaced["reason"]) == ("warning", "SQLITE_NOTADB")
    assert set(replaced) - STANDARD == {"reason"}
    assert sorted(path.name for path in cache.parent.glob(f"{cache.name}*")) == [cache.name]
    assert main(arguments(home)) == 0
    assert "converted by pandoc: 0\nreused from the cache: 3\n" in capsys.readouterr().out


def test_pandoc_runs_sandboxed_on_its_standard_input(home: Path, monkeypatch: MonkeyPatch) -> None:
    """The pandoc on PATH gets --sandbox, the HTML on its input, and its output is kept."""
    folder = fake_pandoc(home / "bin", f'printf "%s\\n" "$@" > "{home}/arguments"; cat')
    monkeypatch.setenv("PATH", f"{folder}{os.pathsep}{os.environ['PATH']}")
    assert Pandoc.find().markdown("<p>x</p>") == "<p>x</p>"
    assert "--sandbox" in (home / "arguments").read_text("utf-8").splitlines()


def test_html_s_converter_is_named_by_pandoc_s_version_line_then_its_arguments(
    home: Path, monkeypatch: MonkeyPatch
) -> None:
    """Plan 039: the first line of --version, not the folder it names, then those given HTML."""
    script = (
        'if [ "$1" = --version ]; then printf "pandoc 9.9\\nUser data directory: %s\\n" "$HOME";'
        f' else printf "%s\\n" "$@" > "{home}/arguments"; cat; fi'
    )
    folder = fake_pandoc(home / "bin", script)
    monkeypatch.setenv("PATH", f"{folder}{os.pathsep}{os.environ['PATH']}")
    pandoc = Pandoc.find()
    pandoc.markdown("<p>x</p>")
    given = (home / "arguments").read_text("utf-8").splitlines()
    assert "--sandbox" in given
    assert pandoc.html_converter().split("\n") == ["pandoc 9.9", *given]


def test_a_pandoc_failure_names_its_status_and_no_content(
    home: Path, monkeypatch: MonkeyPatch
) -> None:
    """Pandoc's own message, which may quote the document, is not passed on."""
    folder = fake_pandoc(home / "bin", 'echo "secret text" >&2; exit 3')
    monkeypatch.setenv("PATH", str(folder))
    with pytest.raises(PandocFailedError) as failed:
        Pandoc.find().markdown("<p>secret text</p>")
    assert str(failed.value) == "pandoc: exit status 3"


def test_a_run_with_a_problem_exits_one_and_says_what_was_not_mirrored(
    home: Path, capsys: CaptureFixture[str]
) -> None:
    """A page whose space is not listed is reported by its place in the store.

    Each such page is the warning mirror.not_mirrored, then mirror.nothing_removed warns
    that nothing was removed; the run's log file holds both.
    """
    store = RawStore(home / "data" / "raw")
    stamp = {"number": 1, "createdAt": "2026-10-20T21:52:41Z"}
    responses = {
        confluence_v2.DOCUMENT: v2_page(version=stamp),
        confluence_v2.VIEW: v2_view(version=stamp),
        confluence_v2.ATTACHMENTS: [],
    }
    with store.writing():
        store.put(Page, responses, datetime(2026, 10, 22, 8, 15, tzinfo=UTC), {})
    assert main(arguments(home)) == SOME_FAILED
    captured = capsys.readouterr()
    assert "documents: 0\n" in captured.out
    assert "problems: 1\n" in captured.out
    warnings = said(captured.err)
    assert ("warning", "mirror.not_mirrored") in warnings
    assert ("warning", "mirror.nothing_removed") in warnings
    assert "confluence/pages/196845/000001" in captured.err
    assert "space not listed" in captured.err
    (problem,) = logged_as(home, "mirror.not_mirrored")
    assert {key: problem[key] for key in ("level", "where", "reason")} == {
        "level": "warning",
        "where": "confluence/pages/196845/000001",
        "reason": "space not listed",
    }
    (kept,) = logged_as(home, "mirror.nothing_removed")
    assert (kept["level"], kept["problems"]) == ("warning", 1)
    assert main(arguments(home, "--format", "json")) == SOME_FAILED
    document = json.loads(capsys.readouterr().out)
    assert document["documents"] == 0
    assert document["problems"] == [
        {"where": "confluence/pages/196845/000001", "reason": "space not listed"}
    ]
