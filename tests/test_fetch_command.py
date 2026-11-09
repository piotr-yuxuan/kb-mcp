"""The fetch command as the user meets it: its refusals, messages and exit statuses."""

from __future__ import annotations

import json
import re
import time
from collections import Counter
from copy import replace
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
from pydantic_core import to_jsonable_python
from structlog.testing import capture_logs

from kb_mcp.cli.main import main
from kb_mcp.kernel.exit_status import ExitStatus
from kb_mcp.sources.atlassian.declared import JIRA
from kb_mcp.sources.atlassian.fetch.adapters import http
from kb_mcp.sources.atlassian.fetch.adapters.raw_store import RawStore
from kb_mcp.sources.atlassian.fetch.adapters.session_file import COOKIES, write_cookies
from kb_mcp.sources.atlassian.fetch.app import fetcher
from kb_mcp.sources.atlassian.fetch.app.fetching import (
    FetchOutcome,
    RunReport,
    Targets,
    run_fetch,
)
from kb_mcp.sources.registry import SOURCES, refuse
from kb_mcp.sources.worklog.declared import WORKLOG
from tests.composed import MODEL
from tests.samples import v2_page
from tests.test_cli import logged_as
from tests.test_fetching import CAP, SITE, FakeSite, stamp
from tests.test_incremental_fetch import RefreshSite, run, settings
from tests.test_observed import said

if TYPE_CHECKING:
    from pathlib import Path

    from _pytest.capture import CaptureFixture
    from _pytest.monkeypatch import MonkeyPatch

    from kb_mcp.config.domain.settings import Settings

REFUSED = 2
SOME_FAILED = 1
SIGN_IN_NEEDED = 3
INTERRUPTED = 130


@pytest.fixture
def home(tmp_path: Path, monkeypatch: MonkeyPatch) -> Path:
    """Give each test a scratch home directory, and no waiting between requests."""
    scratch = tmp_path / "home"
    scratch.mkdir()
    monkeypatch.setenv("HOME", str(scratch))
    monkeypatch.setattr(time, "sleep", lambda _: None)
    return scratch


def command(home: Path, *options: str) -> list[str]:
    """Return the arguments of a fetch with no settings file."""
    return ["fetch", "--yes", "--config", str(home / "none.toml"), *options]


@pytest.fixture
def signed_in(home: Path, monkeypatch: MonkeyPatch) -> list[str]:
    """Save a session, and serve the scripted site; give the options of a run over it.

    Its space and project changed since 2 October: two pages, a blog post and an issue,
    with three files to keep, of which one fails, and a video, which is not kept.
    """
    chosen = MODEL(accounts={"atlassian": {"site": SITE}}, data_dir=(home / "kb-mcp").resolve())
    write_cookies(chosen.session / COOKIES, [{"name": "s", "value": "v", "domain": "x"}])
    monkeypatch.setattr(http, "client", lambda *_: FakeSite().client())
    return command(
        home, "--site", SITE, "--space", "MFS", "--project", "PRB", "--since", "2026-10-02"
    )


def test_a_fetch_shows_what_it_fetched_by_kind_its_files_and_failures(
    signed_in: list[str], capsys: CaptureFixture[str]
) -> None:
    """In short, a row per source, Confluence then Jira, each with its own counts.

    The documents fetched of each type, the files downloaded, the failures: the file
    that fails is a page's, which fails Confluence's row alone, and the run.
    """
    assert main(signed_in) == SOME_FAILED
    assert capsys.readouterr().out == (
        "confluence: failed\n"
        "  confluence blogposts: fetched: 1\n"
        "  confluence pages: fetched: 2\n"
        "  files: downloaded: 1\n"
        "  failures: 1\n"
        "jira: done\n"
        "  files: downloaded: 1\n"
        "  jira issues: fetched: 1\n"
        "  failures: 0\n"
    )


def test_a_fetch_in_detail_shows_each_window_every_count_then_the_failures(
    signed_in: list[str], capsys: CaptureFixture[str]
) -> None:
    """Under each source's row, its target's window, then each count, in order, then failures.

    With what short leaves out: listings, files skipped or failed. Each window starts at
    --since, and the coverage of each target grew.
    """
    assert main([*signed_in, "--summary", "detailed"]) == SOME_FAILED
    confluence, jira = capsys.readouterr().out.split("jira: done\n")
    row, space, *counts, failures = confluence.splitlines()
    project, *issues, none_failed = jira.splitlines()
    since = "from 2026-10-02T00:00:00+00:00 to "
    assert row == "confluence: failed"
    assert space.startswith(f"  space MFS: {since}")
    assert project.startswith(f"  project PRB: {since}")
    assert space.endswith(", given; coverage extended")
    assert project.endswith(", given; coverage extended")
    assert counts == sorted(counts)
    assert issues == sorted(issues)
    assert {
        "  confluence pages: listed: 3",
        "  confluence pages: fetched: 2",
        "  files: downloaded: 1",
        "  files: skipped, media type not kept: 1",
        "  files failed: status 404: 1",
    } <= set(counts)
    assert {"  jira issues: listed: 2", "  files: downloaded: 1"} <= set(issues)
    assert (failures, none_failed) == ("  failures: 1", "  failures: 0")


def test_each_source_is_fetched_alone_into_a_report_of_its_own(
    home: Path, monkeypatch: MonkeyPatch
) -> None:
    """Plan 030: Confluence's fetch, then Jira's, each with its report, of its own counts.

    Every request of Jira's comes after the last of Confluence's; the reports are
    ``<time>-confluence.json`` and ``<time>-jira.json``, and neither counts anything of
    the other source's.
    """
    chosen = MODEL(accounts={"atlassian": {"site": SITE}}, data_dir=(home / "kb-mcp").resolve())
    write_cookies(chosen.session / COOKIES, [{"name": "s", "value": "v", "domain": "x"}])
    fake = FakeSite()
    monkeypatch.setattr(http, "client", lambda *_: fake.client())
    options = ("--site", SITE, "--space", "MFS", "--project", "PRB", "--since", "2026-10-02")
    assert main(command(home, *options)) == SOME_FAILED
    paths = [url.path for url in fake.asked]
    jira = [at for at, path in enumerate(paths) if path.startswith("/rest/api/3/")]
    confluence = [at for at, path in enumerate(paths) if path.startswith("/wiki/")]
    assert confluence
    assert jira
    assert max(confluence) < min(jira)
    reports = {
        path.name.rpartition("-")[2]: json.loads(path.read_text("utf-8"))
        for path in chosen.runs.iterdir()
    }
    assert sorted(reports) == ["confluence.json", "jira.json"]
    assert all(
        re.fullmatch(r"\d{8}T\d{6}Z-(confluence|jira)\.json", path.name)
        for path in chosen.runs.iterdir()
    )
    assert [what for what in reports["confluence.json"]["counts"] if "jira" in what] == []
    assert [what for what in reports["jira.json"]["counts"] if "confluence" in what] == []
    assert (reports["confluence.json"]["status"], reports["jira.json"]["status"]) == (
        SOME_FAILED,
        0,
    )


def test_without_a_session_each_source_is_to_sign_in_before_any_request(
    home: Path, monkeypatch: MonkeyPatch, capsys: CaptureFixture[str]
) -> None:
    """Each fetch checks its own sign-in: both rows say so, by an error naming each source.

    Nothing is asked of the site; exit 3.
    """
    fake = FakeSite()
    monkeypatch.setattr(http, "client", lambda *_: fake.client())
    options = ("--site", SITE, "--space", "MFS", "--project", "PRB", "--since", "7d")
    assert main(command(home, *options)) == SIGN_IN_NEEDED
    rows = [line for line in capsys.readouterr().out.splitlines() if not line.startswith(" ")]
    assert rows == ["confluence: sign in", "jira: sign in"]
    needed = logged_as(home, "fetch.sign_in_needed")
    assert [(each["source"], each["hint"]) for each in needed] == [
        ("confluence", "run kb-mcp login atlassian"),
        ("jira", "run kb-mcp login atlassian"),
    ]
    assert fake.asked == []


def test_a_stopped_fetch_says_why_in_short(
    home: Path, monkeypatch: MonkeyPatch, capsys: CaptureFixture[str]
) -> None:
    """Too many failures in a row stop a run: short says so, else it reads as a whole run."""
    counts = {
        "confluence pages: fetched": 3,
        "confluence pages failed: status 503": 5,
        "runs: stopped, too many failures in a row": 1,
    }
    stopped = FetchOutcome(
        report=RunReport(counts=Counter(counts)), failed_targets=[], status=ExitStatus.FAILED
    )
    monkeypatch.setattr(fetcher, "run_fetch", lambda *_: stopped)
    assert main(command(home, "--site", SITE, "--space", "MFS")) == SOME_FAILED
    assert capsys.readouterr().out == (
        "confluence: failed\n"
        "  confluence pages: fetched: 3\n"
        "  runs: stopped, too many failures in a row: 1\n"
        "  failures: 5\n"
    )


def test_a_dry_run_shows_what_it_would_fetch(
    signed_in: list[str], capsys: CaptureFixture[str]
) -> None:
    """In short, under each source's row: its window, the documents to fetch, the files.

    No failure. The files to download are those that a listing names: the issue's. The
    windows say nothing of the coverage, which a dry run does not write.
    """
    assert main([*signed_in, "--dry-run"]) == 0
    confluence, jira = capsys.readouterr().out.split("jira: done\n")
    row, space, *pages = confluence.splitlines(keepends=True)
    project, *issues = jira.splitlines(keepends=True)
    assert row == "confluence: done\n"
    assert space.startswith("  space MFS: from 2026-10-02T00:00:00+00:00 to ")
    assert space.endswith(", given\n")
    assert project.startswith("  project PRB: from 2026-10-02T00:00:00+00:00 to ")
    assert "".join(pages) == (
        "  confluence blogposts: to fetch: 1\n  confluence pages: to fetch: 2\n  failures: 0\n"
    )
    assert "".join(issues) == (
        "  files: to download: 1\n  jira issues: to fetch: 1\n  failures: 0\n"
    )


def test_a_fetch_gives_its_counts_failed_keys_and_status_as_json(
    signed_in: list[str], capsys: CaptureFixture[str]
) -> None:
    """One document: the exit status, then a row per source, each with its result whole.

    Its counts, the user's keys that failed, its exit status, its target's window.
    """
    assert main([*signed_in, "--format", "json"]) == SOME_FAILED
    document = json.loads(capsys.readouterr().out)
    assert document["exit_status"] == SOME_FAILED
    rows = document["sources"]
    assert [sorted(row) for row in rows] == [["outcome", "result", "source"]] * 2
    assert [(row["source"], row["outcome"]) for row in rows] == [
        ("confluence", "failed"),
        ("jira", "done"),
    ]
    confluence, jira = (row["result"]["downloaded"] for row in rows)
    assert confluence["report"]["counts"]["confluence pages: fetched"] == len(["1001", "1002"])
    assert jira["report"]["counts"]["jira issues: fetched"] == 1
    assert [each["failed_targets"] for each in (confluence, jira)] == [[], []]
    assert [each["status"] for each in (confluence, jira)] == [SOME_FAILED, 0]
    assert [
        (each["target"], each["start"], each["reason"], each["coverage"])
        for result in (confluence, jira)
        for each in result["windows"]
    ] == [
        ({"source": "confluence", "key": "MFS"}, "2026-10-02T00:00:00Z", "given", "extended"),
        ({"source": "jira", "key": "PRB"}, "2026-10-02T00:00:00Z", "given", "extended"),
    ]
    assert all(each["end"] for result in (confluence, jira) for each in result["windows"])
    assert [each["dry_run"] for each in (confluence, jira)] == [False, False]


def test_a_fetch_without_a_site_is_refused_by_name(home: Path, capsys: CaptureFixture[str]) -> None:
    """The site is named as the missing setting, by the error run.refused."""
    assert main(command(home, "--space", "MFS", "--since", "7d")) == REFUSED
    err = capsys.readouterr().err
    assert said(err) == [("error", "run.refused")]
    assert "site: not set" in err


def test_a_fetch_of_nothing_is_refused(home: Path, capsys: CaptureFixture[str]) -> None:
    """Without a space or a project, there is nothing to do."""
    assert main(command(home, "--site", SITE, "--since", "7d")) == REFUSED
    assert "nothing to fetch" in capsys.readouterr().err


@pytest.mark.parametrize(("option", "value"), [("--space", "not a key"), ("--project", "prb")])
def test_a_key_that_is_not_one_is_refused_by_the_options(
    home: Path, option: str, value: str, capsys: CaptureFixture[str]
) -> None:
    """A space or project key is checked before anything runs."""
    with pytest.raises(SystemExit) as stopped:
        main(command(home, "--site", SITE, option, value, "--since", "7d"))
    assert stopped.value.code == REFUSED
    assert "key" in capsys.readouterr().err


def test_a_period_that_ends_before_it_starts_is_refused(
    home: Path, capsys: CaptureFixture[str]
) -> None:
    """The option at fault is named, by the error fetch.refused, in the log file too."""
    options = ("--site", SITE, "--space", "MFS", "--since", "2026-10-22", "--until", "2026-10-01")
    assert main(command(home, *options)) == REFUSED
    err = capsys.readouterr().err
    assert ("error", "fetch.refused") in said(err)
    assert "--until" in err
    (refused,) = logged_as(home, "fetch.refused")
    assert refused["level"] == "error"
    assert "--until" in str(refused["reason"])


def test_without_a_session_the_user_is_told_to_sign_in(
    home: Path, capsys: CaptureFixture[str]
) -> None:
    """No saved session: exit 3, and the command to run, by fetch.sign_in_needed."""
    assert main(command(home, "--site", SITE, "--space", "MFS", "--since", "7d")) == SIGN_IN_NEEDED
    err = capsys.readouterr().err
    assert ("error", "fetch.sign_in_needed") in said(err)
    assert "run kb-mcp login atlassian" in err
    (needed,) = logged_as(home, "fetch.sign_in_needed")
    assert (needed["level"], needed["hint"]) == ("error", "run kb-mcp login atlassian")


def test_a_space_that_finds_nothing_is_named_on_stderr_and_not_in_the_report(
    home: Path, monkeypatch: MonkeyPatch, capsys: CaptureFixture[str]
) -> None:
    """The user's own key is shown to them, and never written to the run report.

    It is the warning fetch.target_failed, which the run's log file holds too.
    """
    chosen = MODEL(accounts={"atlassian": {"site": SITE}}, data_dir=(home / "kb-mcp").resolve())
    write_cookies(chosen.session / COOKIES, [{"name": "s", "value": "v", "domain": "x"}])
    fake = FakeSite(spaces=[])
    monkeypatch.setattr(http, "client", lambda *_: fake.client())
    options = ("--site", SITE, "--space", "NOPE", "--since", "7d", "--summary", "detailed")
    assert main(command(home, *options)) == SOME_FAILED
    captured = capsys.readouterr()
    assert ("warning", "fetch.target_failed") in said(captured.err)
    assert "space NOPE: not found" in captured.err
    (failed,) = logged_as(home, "fetch.target_failed")
    assert (failed["level"], failed["target"]) == ("warning", "space NOPE: not found")
    assert "  confluence spaces failed: not found: 1\n" in captured.out
    [report] = chosen.runs.iterdir()
    assert report.name.endswith("-confluence.json")
    assert "NOPE" not in report.read_text("utf-8")
    assert json.loads(report.read_text("utf-8"))["status"] == SOME_FAILED


def test_ctrl_c_exits_130_and_says_which_source_it_stopped(
    home: Path, monkeypatch: MonkeyPatch, capsys: CaptureFixture[str]
) -> None:
    """An interrupted run is the shell's 130, not a failure: fetch.interrupted warns.

    Its row says so, and a later one is not run.
    """

    def interrupted(*_: object) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr(fetcher, "run_fetch", interrupted)
    options = ("--site", SITE, "--space", "MFS", "--project", "PRB", "--since", "7d")
    assert main(command(home, *options)) == INTERRUPTED
    captured = capsys.readouterr()
    assert ("warning", "fetch.interrupted") in said(captured.err)
    assert captured.out == "confluence: interrupted\njira: not run\n"
    (interrupted,) = logged_as(home, "fetch.interrupted")
    assert (interrupted["level"], interrupted["source"]) == ("warning", "confluence")


def test_a_busy_store_exits_1_with_its_reason(
    home: Path, monkeypatch: MonkeyPatch, capsys: CaptureFixture[str]
) -> None:
    """Another run writing the store: the user is told to wait for it, by an error."""
    chosen = MODEL(accounts={"atlassian": {"site": SITE}}, data_dir=(home / "kb-mcp").resolve())
    write_cookies(chosen.session / COOKIES, [{"name": "s", "value": "v", "domain": "x"}])
    monkeypatch.setattr(http, "client", lambda *_: FakeSite().client())
    options = ("--site", SITE, "--space", "MFS", "--since", "7d")
    with RawStore(chosen.raw).writing():
        assert main(command(home, *options)) == SOME_FAILED
    err = capsys.readouterr().err
    assert ("error", "fetch.store_busy") in said(err)
    assert "another run is writing it; try again once that run ends" in err
    (busy,) = logged_as(home, "fetch.store_busy")
    assert (busy["level"], busy["store"]) == ("error", str(chosen.raw))


# Plan 034: what a run counts is what it fetches, apart from what it lists.
LISTED_AT = datetime(2026, 10, 22, 9, tzinfo=UTC)
COUNTED_AT = datetime(2026, 10, 27, 9, tzinfo=UTC)
SINCE = datetime(2026, 10, 20, tzinfo=UTC)


def counted(
    tmp_path: Path, monkeypatch: MonkeyPatch, since: datetime | None, *, first_fetch: bool
) -> tuple[FetchOutcome, list[dict[str, object]], Settings]:
    """Run over a space of 50 pages: 7 changed in the window, of which 4 were stored first.

    The 4 changed on the 21st, stored by a run --since the 20th; 3 more on the 23rd; 43 on
    the 1st. ``first_fetch`` forgets the coverage before the run counted, on the 27th.
    Give its outcome, the events it logged, and its settings.
    """
    days = [21] * 4 + [23] * 3 + [1] * 43
    pages = {
        str(6000 + n): v2_page(id=str(6000 + n), version=stamp(day)) for n, day in enumerate(days)
    }
    chosen = settings(tmp_path)
    first = RefreshSite(listing=dict(list(pages.items())[:4]), posts={})
    assert (
        run(
            chosen,
            monkeypatch,
            first,
            Targets(spaces=["MFS"], projects=[], max_file_bytes=CAP, since=SINCE),
            LISTED_AT,
        )
        == 0
    )
    if first_fetch:
        (chosen.raw / "coverage.json").unlink()
    monkeypatch.setattr(http, "client", lambda *_: RefreshSite(listing=pages, posts={}).client())
    targets = Targets(spaces=["MFS"], projects=[], max_file_bytes=CAP, since=since)
    with capture_logs() as events:
        outcome = run_fetch(chosen, targets, lambda: COUNTED_AT, lambda _: None)
    return outcome, events, chosen


@pytest.mark.parametrize(
    ("since", "first_fetch", "reason"),
    [(SINCE, False, "given"), (None, False, "covered start"), (None, True, "first fetch")],
)
def test_a_run_counts_what_it_fetches_apart_from_what_it_lists(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    since: datetime | None,
    *,
    first_fetch: bool,
    reason: str,
) -> None:
    """50 listed, 7 in the window of which 4 stored: the task, short and its JSON say 3.

    fetch.listed says each number, and the window's reason; the window goes to the
    JSON, and the run report names no target.
    """
    outcome, events, chosen = counted(tmp_path, monkeypatch, since, first_fetch=first_fetch)
    listed = [event for event in events if event["event"] == "fetch.listed"]
    assert [
        (each["listed"], each["in_window"], each["stored"], each["to_fetch"], each["reason"])
        for each in listed
    ] == [(50, 7, 4, 3, reason)]
    tasks = [(each["done"], each["total"]) for each in events if each.get("task") == "documents"]
    assert tasks[-1] == (3, 3)
    assert outcome.text("short") == "confluence pages: fetched: 3\nfailures: 0\n"
    [window] = to_jsonable_python(outcome)["windows"]
    assert (window["target"], window["end"], window["reason"], window["coverage"]) == (
        {"source": "confluence", "key": "MFS"},
        "2026-10-27T09:00:00Z",
        reason,
        "extended",
    )
    assert "MFS" not in max(chosen.runs.iterdir()).read_text("utf-8")


@pytest.mark.parametrize("first_fetch", [False, True])
def test_without_since_the_detail_counts_what_is_new_or_changed_since_the_last_fetch(
    tmp_path: Path, monkeypatch: MonkeyPatch, *, first_fetch: bool
) -> None:
    """A catch-up, or a first fetch: not what is in the period, which can be a whole space."""
    outcome, _, _ = counted(tmp_path, monkeypatch, None, first_fetch=first_fetch)
    detailed = outcome.text("detailed")
    assert "confluence pages: new or changed since the last fetch: 3\n" in detailed
    assert "confluence pages: fetched: 3\n" in detailed
    assert "in the period" not in detailed
    assert "already stored" not in detailed


def test_with_since_the_detail_counts_what_is_in_the_period_and_stored(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """Given --since, the period is the user's: what is in it, and what was stored already."""
    outcome, _, _ = counted(tmp_path, monkeypatch, SINCE, first_fetch=False)
    detailed = outcome.text("detailed")
    assert "confluence pages: in the period: 7\n" in detailed
    assert "confluence pages: already stored: 4\n" in detailed
    assert "confluence pages: fetched: 3\n" in detailed
    assert "new or changed" not in detailed


@pytest.mark.usefixtures("signed_in")
def test_options_before_the_names_keep_their_values_with_no_question(
    home: Path, capsys: CaptureFixture[str]
) -> None:
    """Plan 031, criterion 3: the file, the period, --yes and a source's name, in this order."""
    config = home / "mine.toml"
    config.write_text('[sources.confluence]\nspaces = ["MFS"]\n', "utf-8")
    given = ("fetch", "--yes", "--config", str(config), "--site", SITE, "--since", "2026-10-02")
    assert main([*given, "confluence"]) == SOME_FAILED
    captured = capsys.readouterr()
    assert captured.out.startswith("confluence: failed\n")
    assert "jira:" not in captured.out
    assert f"--config {config}" in captured.err
    assert "--since 2026-10-02" in captured.err


def test_names_are_taken_once_each_in_the_registry_s_order(
    signed_in: list[str], capsys: CaptureFixture[str]
) -> None:
    """Whatever the order typed: Confluence first, as Jira's links read it."""
    assert main([*signed_in, "jira", "confluence", "jira"]) == SOME_FAILED
    rows = [line for line in capsys.readouterr().out.splitlines() if not line.startswith(" ")]
    assert rows == ["confluence: failed", "jira: done"]


def test_names_split_by_an_option_are_refused_by_the_parser(
    signed_in: list[str], capsys: CaptureFixture[str]
) -> None:
    """Argparse takes one run of names: exit 2, nothing fetched."""
    with pytest.raises(SystemExit) as stopped:
        main([*signed_in, "confluence", "--summary", "short", "jira"])
    assert stopped.value.code == REFUSED
    assert "unrecognized arguments: jira" in capsys.readouterr().err


def test_a_flag_of_a_source_not_named_is_said_not_applied(
    signed_in: list[str], capsys: CaptureFixture[str]
) -> None:
    """``--project`` replaces Jira's setting, which this run does not read: said, and not copied."""
    assert main([*signed_in, "confluence"]) == SOME_FAILED
    err = capsys.readouterr().err
    assert "\n  sources.jira.projects: PRB (not applied: jira not named)\n" in err
    assert "ignored: sources.jira.projects (--project): jira not named\n" in err
    assert "--project" not in err.split("kb-mcp fetch")[1]


def test_a_source_named_but_not_configured_is_refused_naming_its_setting(
    home: Path, capsys: CaptureFixture[str]
) -> None:
    """Before anything is asked: exit 2."""
    assert main(command(home, "--site", SITE, "--space", "MFS", "jira")) == REFUSED
    assert "jira: not configured; set sources.jira.projects" in capsys.readouterr().err


def test_without_a_name_each_source_configured_runs_and_the_others_are_said_left_out(
    home: Path, monkeypatch: MonkeyPatch, capsys: CaptureFixture[str]
) -> None:
    """Jira has no project; the work log is read in place: each named, with why."""
    monkeypatch.setattr(
        fetcher,
        "run_fetch",
        lambda *_: FetchOutcome(report=RunReport(), failed_targets=[], status=ExitStatus.OK),
    )
    assert main(command(home, "--site", SITE, "--space", "MFS")) == 0
    captured = capsys.readouterr()
    assert captured.out.splitlines()[0] == "confluence: done"
    assert "jira:" not in captured.out
    assert "\n  source jira: left out, not configured\n" in captured.err
    assert "\n  source worklog: left out, read in place, it has nothing to fetch\n" in captured.err


@pytest.mark.parametrize("name", ["worklog", "memo"])
def test_a_source_without_a_fetcher_is_no_choice(
    home: Path, capsys: CaptureFixture[str], name: str
) -> None:
    """Argparse refuses the work log, and a source of the tests read in place alike: exit 2."""
    memo = replace(WORKLOG, name="memo")
    with pytest.raises(SystemExit) as stopped:
        main(command(home, name), (*SOURCES, memo))
    assert stopped.value.code == REFUSED
    assert f"invalid choice: {name!r} (choose from 'confluence', 'jira')" in capsys.readouterr().err


def test_the_help_shows_a_group_per_source_that_has_a_fetcher(
    capsys: CaptureFixture[str],
) -> None:
    """Each with its resource types, how each is read, and the options that it alone declares.

    Those that both declare, in a group of their own; none of the work log.
    """
    with pytest.raises(SystemExit):
        main(["fetch", "--help"])
    said_of = " ".join(capsys.readouterr().out.split())
    _, confluence = said_of.split(" confluence: Confluence, on the Atlassian site", 1)
    confluence, jira = confluence.split(" jira: Jira, on the Atlassian site", 1)
    jira, both = jira.split(" several sources: The options of confluence, jira.", 1)
    assert "pages, listed whole; blogposts, listed whole." in confluence
    assert "--space SPACE" in confluence
    assert "--project" not in confluence
    assert "issues, searched by update time." in jira
    assert "--project PROJECT" in jira
    assert "--since" not in jira
    assert all(flag in both for flag in ("--since SINCE", "--until UNTIL", "--max-file-mb"))
    assert "worklog:" not in said_of


def test_a_source_alone_keeps_its_options_in_its_own_group(capsys: CaptureFixture[str]) -> None:
    """No other source shares them, so no group of several sources, under this registry."""
    with pytest.raises(SystemExit):
        main(["fetch", "--help"], (JIRA, WORKLOG))
    said_of = " ".join(capsys.readouterr().out.split())
    assert "several sources" not in said_of
    _, jira = said_of.split(" jira: Jira, on the Atlassian site", 1)
    assert all(flag in jira for flag in ("--project PROJECT", "--since SINCE", "--until UNTIL"))


def test_each_flag_of_the_registry_is_declared_alike_by_each_source_that_declares_it() -> None:
    """Options that several sources share are added once, so each must mean one thing."""
    refuse(SOURCES)
    by_flag = [option for declared in SOURCES for option in declared.options.values()]
    for option in by_flag:
        assert {each for each in by_flag if each.flag == option.flag} == {option}
