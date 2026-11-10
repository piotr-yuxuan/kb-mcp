"""The ``prepare`` command as the user meets it, and pandoc as the mirror runs it."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from kb_mcp.cli.main import main
from kb_mcp.mirror.adapters import pandoc as pandoc_adapter
from kb_mcp.mirror.adapters.pandoc import (
    Pandoc,
    PandocFailedError,
    PandocMissingError,
)
from kb_mcp.sources.atlassian.fetch.adapters import confluence_v2
from kb_mcp.sources.atlassian.fetch.adapters.raw_store import RawStore
from kb_mcp.sources.atlassian.fetch.domain.content import BlogPost, Page
from kb_mcp.sources.atlassian.prepare.app.preparer import NOT_COUNTED
from tests.reference import STANDARD
from tests.samples import v2_page, v2_space, v2_view
from tests.test_cli import logged_as
from tests.test_observed import said
from tests.test_prepare_atlassian import (
    FETCHED,
    LISTED,
    POST_LISTED,
    SPACE_ID,
    Sandbox,
    listing_page,
    page_responses,
    post_responses,
)

if TYPE_CHECKING:
    from _pytest.capture import CaptureFixture
    from _pytest.monkeypatch import MonkeyPatch

SOME_FAILED = 1
BAD_SETTINGS = 2
# The counts of a mirror that has nothing to do, as a row writes them.
NOTHING = (
    "  documents: 0\n"
    "  converted by pandoc: 0\n"
    "  reused from the cache: 0\n"
    "  files written: 0\n"
    "  files unchanged: 0\n"
    "  files removed: 0\n"
)


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
    """Return the command line of ``prepare`` with a scratch settings file and data."""
    return [
        "prepare",
        "--yes",
        "--config",
        str(home / "none.toml"),
        "--data-dir",
        str(home / "data"),
        *extra,
    ]


def test_without_pandoc_prepare_names_it_and_writes_nothing(
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
    """On PATH for the entry, gone for the run: exit 1, the error prepare.pandoc_missing.

    The run's log file holds it with its reason, and no mirror is written.
    """
    monkeypatch.setenv("PATH", str(fake_pandoc(home / "bin", "cat")))
    message = "pandoc: not found on PATH; install pandoc 3"

    def gone() -> Pandoc:
        raise PandocMissingError(message)

    monkeypatch.setattr(Pandoc, "find", gone)
    assert main(arguments(home)) == SOME_FAILED
    err = capsys.readouterr().err
    assert ("error", "prepare.pandoc_missing") in said(err)
    assert message in err
    missing = logged_as(home, "prepare.pandoc_missing")
    assert [(each["level"], each["reason"]) for each in missing] == [("error", message)] * 2
    assert not (home / "data" / "docs").exists()


def test_refused_settings_exit_two(home: Path, capsys: CaptureFixture[str]) -> None:
    """A site that is not an https host is refused before anything runs."""
    assert main(arguments(home, "--site", "http://plain.example.invalid")) == BAD_SETTINGS
    assert "site" in capsys.readouterr().err


def test_an_empty_store_prepares_nothing_and_exits_zero(
    home: Path, capsys: CaptureFixture[str]
) -> None:
    """A data directory without a raw store gives an empty mirror, and counts of zero.

    A row each, Confluence's then Jira's, names its source.
    """
    assert main(arguments(home)) == 0
    assert capsys.readouterr().out == (f"confluence: done\n{NOTHING}jira: done\n{NOTHING}")


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
        "confluence",
        "  documents",
        "  converted by pandoc",
        "  reused from the cache",
        "  files written",
        "  files unchanged",
        "  files removed",
        "jira",
    ]
    assert [line.split(": ")[0] for line in first[: len(names)]] == names
    assert first[1] == "  documents: 1"
    converted = first[2].removeprefix("  converted by pandoc: ")
    written = first[4].removeprefix("  files written: ")
    assert main(arguments(home, "--detail", "detailed")) == 0
    assert capsys.readouterr().out == (
        "confluence: done\n"
        "  documents: 1\n"
        "  converted by pandoc: 0\n"
        f"  reused from the cache: {converted}\n"
        "  files written: 0\n"
        f"  files unchanged: {written}\n"
        "  files removed: 0\n"
        "  not shown, element: iframe: 1\n"
        f"jira: done\n{NOTHING}"
    )


def test_the_command_reports_the_documents_it_builds(
    home: Path, capsys: CaptureFixture[str]
) -> None:
    """Two pages: the run's log file ends Confluence's task of documents with both done."""
    store = RawStore(home / "data" / "raw")
    listed = [listing_page("100", "Home", None, None), listing_page("101", "Away", None, None)]
    with store.writing():
        store.put_space(v2_space(id=SPACE_ID), listed, [], [])
        store.put(Page, page_responses("100", "Home", 1, "<p>Home.</p>", []), FETCHED, {})
        store.put(Page, page_responses("101", "Away", 1, "<p>Away.</p>", []), FETCHED, {})
    assert main(arguments(home)) == 0
    assert capsys.readouterr().out.startswith("confluence: done\n  documents: 2\n")
    assert [
        (line["task"], line["done"], line["total"]) for line in logged_as(home, "progress")
    ] == [("confluence documents", 2, 2), ("jira documents", 0, 0)]


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


def test_the_command_mirrors_both_of_confluence_s_kinds(
    home: Path, capsys: CaptureFixture[str]
) -> None:
    """A blog post is Confluence's as a page is: prepared, and counted under its row."""
    store = RawStore(home / "data" / "raw")
    with store.writing():
        store.put_space(v2_space(id=SPACE_ID), LISTED[:1], [POST_LISTED], [])
        store.put(Page, page_responses("100", "Home", 1, "<p>Home.</p>", []), FETCHED, {})
        store.put(BlogPost, post_responses("<p>News.</p>"), FETCHED, {})
    assert main(arguments(home)) == 0
    assert "documents: 2\n" in capsys.readouterr().out
    docs = home / "data" / "docs" / "confluence" / "MFS"
    assert (docs / "100-home.md").is_file()
    assert (docs / "blog" / "600-news.md").is_file()


def test_a_second_prepare_with_nothing_changed_runs_pandoc_on_nothing(
    home: Path, monkeypatch: MonkeyPatch, capsys: CaptureFixture[str]
) -> None:
    """Plan 039, criterion 5: its text and its JSON say that each conversion was reused."""
    runs = two_pages(home, monkeypatch)
    assert main(arguments(home)) == 0
    assert "  documents: 2\n  converted by pandoc: 3\n  reused from the cache: 0\n" in (
        capsys.readouterr().out
    )
    assert len(runs.read_text("utf-8").splitlines()) == CONVERSIONS
    assert main(arguments(home)) == 0
    assert capsys.readouterr().out.startswith(
        "confluence: done\n"
        "  documents: 2\n  converted by pandoc: 0\n  reused from the cache: 3\n"
        "  files written: 0\n"
    )
    assert main(arguments(home, "--format", "json")) == 0
    first, _ = json.loads(capsys.readouterr().out)["sources"]
    mirrored = first["counts"]
    assert (mirrored["converted"], mirrored["reused"]) == (0, CONVERSIONS)
    assert len(runs.read_text("utf-8").splitlines()) == CONVERSIONS


def test_a_damaged_cache_is_replaced_and_prepare_converts_everything(
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
    assert "  converted by pandoc: 3\n  reused from the cache: 0\n" in capsys.readouterr().out
    (replaced,) = logged_as(home, "prepare.cache_replaced")
    assert (replaced["level"], replaced["reason"]) == ("warning", "SQLITE_NOTADB")
    assert set(replaced) - STANDARD == {"reason"}
    assert sorted(path.name for path in cache.parent.glob(f"{cache.name}*")) == [cache.name]
    assert main(arguments(home)) == 0
    assert "  converted by pandoc: 0\n  reused from the cache: 3\n" in capsys.readouterr().out


def test_a_new_pandoc_converts_again_and_writes_the_bytes_of_a_prepare_from_no_cache(
    home: Path, monkeypatch: MonkeyPatch, capsys: CaptureFixture[str]
) -> None:
    """Plan 039, criterion 6: pandoc's version line changed, as a fake pandoc plays it.

    It writes its version line before its input, so that two versions give two files.
    The mirror from no cache runs in another data folder, over a copy of the raw store.
    """
    version = home / "version"
    version.write_text("pandoc 1\n", "utf-8")
    script = f'case "$1" in --version) cat "{version}";; *) cat "{version}" -;; esac'
    folder = fake_pandoc(home / "bin", script)
    monkeypatch.setenv("PATH", f"{folder}{os.pathsep}{os.environ['PATH']}")
    store = RawStore(home / "data" / "raw")
    with store.writing():
        store.put_space(v2_space(id=SPACE_ID), [listing_page("100", "Home", None, None)], [], [])
        store.put(Page, page_responses("100", "Home", 1, "<p>Home.</p>", []), FETCHED, {})
    assert main(arguments(home)) == 0
    version.write_text("pandoc 2\n", "utf-8")
    capsys.readouterr()
    assert main(arguments(home)) == 0
    # Home's file and the space's tree.
    assert "  converted by pandoc: 2\n  reused from the cache: 0\n" in capsys.readouterr().out
    tree = home / "data" / "docs" / "confluence" / "MFS" / "_tree.md"
    assert tree.read_text("utf-8").startswith("pandoc 2\n")
    fresh = home / "fresh"
    shutil.copytree(store.root, fresh / "data" / "raw")
    assert main(arguments(fresh)) == 0
    assert Sandbox(home / "data").files() == Sandbox(fresh / "data").files()


def test_other_arguments_for_pandoc_convert_everything_again(
    home: Path, monkeypatch: MonkeyPatch, capsys: CaptureFixture[str]
) -> None:
    """Review of 039: the conversions kept are those of the arguments that pandoc is given.

    A run, then one whose pandoc is given one argument more, which the fake passes over.
    """
    runs = two_pages(home, monkeypatch)
    assert main(arguments(home)) == 0
    more = (*pandoc_adapter.ARGUMENTS, "--columns=72")
    monkeypatch.setattr(pandoc_adapter, "ARGUMENTS", more)
    capsys.readouterr()
    assert main(arguments(home)) == 0
    assert "  converted by pandoc: 3\n  reused from the cache: 0\n" in capsys.readouterr().out
    assert len(runs.read_text("utf-8").splitlines()) == 2 * CONVERSIONS


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

    Each such page is the warning prepare.not_mirrored, by each source's prepare, as each
    places every document, then prepare.nothing_removed warns that Confluence removed none
    of its files; the run's log file holds both. Its row fails, Jira's is done.
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
    assert ("warning", "prepare.not_mirrored") in warnings
    assert ("warning", "prepare.nothing_removed") in warnings
    assert "confluence/pages/196845/000001" in captured.err
    assert "space not listed" in captured.err
    fields = ("level", "source", "where", "reason")
    told = [{key: each[key] for key in fields} for each in logged_as(home, "prepare.not_mirrored")]
    assert told == [
        {
            "level": "warning",
            "source": "confluence",
            "where": "confluence/pages/196845/000001",
            "reason": "space not listed",
        },
        {
            "level": "warning",
            "source": "jira",
            "where": "confluence/pages/196845/000001",
            "reason": "confluence's, read here: space not listed",
        },
    ]
    (kept,) = logged_as(home, "prepare.nothing_removed")
    assert (kept["level"], kept["source"], kept["problems"]) == ("warning", "confluence", 1)
    assert main(arguments(home, "--format", "json")) == SOME_FAILED
    document = json.loads(capsys.readouterr().out)
    assert document["exit_status"] == SOME_FAILED
    rows = [(row["source"], row["ending"]) for row in document["sources"]]
    assert rows == [("confluence", "failed"), ("jira", "done")]
    confluence = document["sources"][0]
    assert confluence["counts"]["documents"] == 0
    assert confluence["problems"] == [
        {"where": "confluence/pages/196845/000001", "reason": "space not listed"}
    ]


def worklog_folder(home: Path, monkeypatch: MonkeyPatch) -> Path:
    """Copy the fixture's work log, and name it by its setting."""
    folder = home / "todo"
    shutil.copytree(Path(__file__).parent / "fixtures" / "worklog", folder)
    monkeypatch.setenv("KB_MCP_SOURCES__WORKLOG__PATH", str(folder))
    return folder


def test_without_a_name_each_store_and_each_source_read_in_place_that_is_configured_run(
    home: Path, monkeypatch: MonkeyPatch, capsys: CaptureFixture[str]
) -> None:
    """Plan 031: no site, nor a source's setting, needed of a store; the work log by its own."""
    assert main(arguments(home)) == 0
    assert "worklog:" not in capsys.readouterr().out
    worklog_folder(home, monkeypatch)
    assert main(arguments(home)) == 0
    captured = capsys.readouterr()
    rows = [line for line in captured.out.splitlines() if not line.startswith(" ")]
    assert rows == ["confluence: done", "jira: done", "worklog: done"]
    assert "\n  source confluence: all that its store holds\n" in captured.err


def test_a_source_read_in_place_named_but_not_configured_is_refused_naming_its_setting(
    home: Path, capsys: CaptureFixture[str]
) -> None:
    """Before anything is asked: exit 2."""
    assert main(arguments(home, "worklog")) == BAD_SETTINGS
    err = capsys.readouterr().err
    assert "worklog: not configured; set sources.worklog.path" in err
    assert not (home / "data").exists()


def test_names_are_taken_once_each_in_the_registry_s_order(
    home: Path, capsys: CaptureFixture[str]
) -> None:
    """Whatever the order typed: Confluence before Jira, as links require of a whole store."""
    assert main(arguments(home, "jira", "confluence", "jira")) == 0
    rows = [line for line in capsys.readouterr().out.splitlines() if not line.startswith(" ")]
    assert rows == ["confluence: done", "jira: done"]


def test_a_dry_run_counts_the_work_log_and_says_of_the_others_that_it_cannot(
    home: Path, monkeypatch: MonkeyPatch, capsys: CaptureFixture[str]
) -> None:
    """Plan 031, criterion 4: exit 0, nothing written, by the data directory's files."""
    worklog_folder(home, monkeypatch)
    command = ["prepare", "--dry-run", "--config", str(home / "none.toml")]
    command += ["--data-dir", str(home / "data")]
    assert main(command) == 0
    out = capsys.readouterr().out
    assert "confluence: not run\n  warning: confluence: not counted: " in out
    assert "jira: not run\n  warning: jira: not counted: " in out
    assert "worklog: not run\n  documents: " in out
    assert not (home / "data" / "docs").exists()
    assert main([*command, "--format", "json"]) == 0
    rows = json.loads(capsys.readouterr().out)["sources"]
    assert [(row["source"], row["ending"]) for row in rows] == [
        ("confluence", "not run"),
        ("jira", "not run"),
        ("worklog", "not run"),
    ]
    assert (rows[0]["counts"], rows[0]["problems"]) == (None, [])
    assert [each["reason"] for each in rows[0]["warnings"]] == [NOT_COUNTED]


def test_what_a_fetch_reads_is_not_read_by_a_prepare(
    home: Path, capsys: CaptureFixture[str]
) -> None:
    """A source's list is said not read, in detail, as for any setting; no site is needed."""
    config = home / "mine.toml"
    config.write_text('[sources.confluence]\nspaces = ["MFS"]\n', "utf-8")
    command = ["prepare", "--yes", "--config", str(config), "--data-dir", str(home / "data")]
    assert main([*command, "--detail", "detailed"]) == 0
    assert "ignored: sources.confluence.spaces (mine.toml): not read by prepare\n" in (
        capsys.readouterr().err
    )


def test_the_help_shows_a_group_per_source_with_what_it_reads(
    capsys: CaptureFixture[str],
) -> None:
    """Every registered source, its scope types said; no option of a fetch."""
    with pytest.raises(SystemExit):
        main(["prepare", "--help"])
    said_of = " ".join(capsys.readouterr().out.split())
    assert "each space listed whole." in said_of
    assert "each project searched by update time." in said_of
    assert "its folder, read whole, in place." in said_of
    assert "--since" not in said_of
    assert "--space" not in said_of
