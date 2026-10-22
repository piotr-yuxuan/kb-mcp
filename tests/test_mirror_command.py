"""The ``mirror`` command as the user meets it, and pandoc as the mirror runs it."""

from __future__ import annotations

import json
import os
import stat
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from atlassian_offline_mcp.cli.main import main
from atlassian_offline_mcp.kernel.content import Page
from atlassian_offline_mcp.mirror.adapters.pandoc import Pandoc, PandocFailedError
from atlassian_offline_mcp.sources.atlassian.adapters import confluence_v2
from atlassian_offline_mcp.sources.atlassian.adapters.raw_store import RawStore
from tests.samples import v2_page, v2_space, v2_view
from tests.test_mirror import FETCHED, SPACE_ID, listing_page, page_responses

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
    return ["mirror", "--config", str(home / "none.toml"), "--data-dir", str(home / "data"), *extra]


def test_without_pandoc_the_mirror_names_it_and_writes_nothing(
    home: Path, monkeypatch: MonkeyPatch, capsys: CaptureFixture[str]
) -> None:
    """Exit 1, a message naming pandoc, and no mirror."""
    empty = home / "bin"
    empty.mkdir()
    monkeypatch.setenv("PATH", str(empty))
    assert main(arguments(home)) == SOME_FAILED
    assert "pandoc" in capsys.readouterr().err
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
        "documents: 0\nfiles written: 0\nfiles unchanged: 0\nfiles removed: 0\nproblems: 0\n"
    )


def test_what_the_mirror_does_not_show_is_counted_in_detail_alone(
    home: Path, capsys: CaptureFixture[str]
) -> None:
    """A page with a frame: short gives the counts; detailed, the frame's too, by its name.

    The second run writes nothing, and finds unchanged what the first wrote.
    """
    store = RawStore(home / "data" / "raw")
    html = '<p>Home.</p><iframe src="http://example.invalid/x"></iframe>'
    with store.writing():
        store.put_space(v2_space(id=SPACE_ID), [listing_page("100", "Home", None, None)], [], [])
        store.put(Page, page_responses("100", "Home", 1, html, []), FETCHED, {})
    assert main(arguments(home)) == 0
    first = capsys.readouterr().out.splitlines()
    names = ["documents", "files written", "files unchanged", "files removed", "problems"]
    assert [line.split(": ")[0] for line in first] == names
    assert first[0] == "documents: 1"
    written = first[1].removeprefix("files written: ")
    assert main(arguments(home, "--summary", "detailed")) == 0
    assert capsys.readouterr().out == (
        "documents: 1\n"
        "files written: 0\n"
        f"files unchanged: {written}\n"
        "files removed: 0\n"
        "not shown, element: iframe: 1\n"
        "problems: 0\n"
    )


def test_pandoc_runs_sandboxed_on_its_standard_input(home: Path, monkeypatch: MonkeyPatch) -> None:
    """The pandoc on PATH gets --sandbox, the HTML on its input, and its output is kept."""
    folder = fake_pandoc(home / "bin", f'printf "%s\\n" "$@" > "{home}/arguments"; cat')
    monkeypatch.setenv("PATH", f"{folder}{os.pathsep}{os.environ['PATH']}")
    assert Pandoc.find().markdown("<p>x</p>") == "<p>x</p>"
    assert "--sandbox" in (home / "arguments").read_text("utf-8").splitlines()


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
    """A page whose space is not listed is reported by its place in the store."""
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
    assert "not mirrored: confluence/pages/196845/000001: space not listed\n" in captured.err
    assert "nothing was removed" in captured.err
    assert main(arguments(home, "--format", "json")) == SOME_FAILED
    document = json.loads(capsys.readouterr().out)
    assert document["documents"] == 0
    assert document["problems"] == [
        {"where": "confluence/pages/196845/000001", "reason": "space not listed"}
    ]
