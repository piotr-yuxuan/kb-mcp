"""The download command as the user meets it: its refusals, messages and exit statuses."""

from __future__ import annotations

import json
import time
from collections import Counter
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
from pydantic_core import to_jsonable_python
from structlog.testing import capture_logs

from kb_mcp.cli.commands import download as download_command
from kb_mcp.cli.main import main
from kb_mcp.config.domain.settings import Settings
from kb_mcp.kernel.exit_status import ExitStatus
from kb_mcp.sources.atlassian.fetch.adapters import http
from kb_mcp.sources.atlassian.fetch.adapters.raw_store import RawStore
from kb_mcp.sources.atlassian.fetch.adapters.session_file import COOKIES, write_cookies
from kb_mcp.sources.atlassian.fetch.app.download import (
    Outcome,
    Report,
    Targets,
    download,
)
from tests.composed import MODEL
from tests.samples import v2_page
from tests.test_cli import logged_as
from tests.test_download import CAP, SITE, FakeSite, stamp
from tests.test_observed import said
from tests.test_refresh import RefreshSite, run, settings

if TYPE_CHECKING:
    from pathlib import Path

    from _pytest.capture import CaptureFixture
    from _pytest.monkeypatch import MonkeyPatch

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
    """Return the arguments of a download with no settings file."""
    return ["download", "--yes", "--config", str(home / "none.toml"), *options]


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


def test_a_download_shows_what_it_fetched_by_kind_its_files_and_failures(
    signed_in: list[str], capsys: CaptureFixture[str]
) -> None:
    """In short: the documents fetched of each kind, the files downloaded, the failures."""
    assert main(signed_in) == SOME_FAILED
    assert capsys.readouterr().out == (
        "confluence blogposts: fetched: 1\n"
        "confluence pages: fetched: 2\n"
        "files: downloaded: 2\n"
        "jira issues: fetched: 1\n"
        "failures: 1\n"
    )


def test_a_download_in_detail_shows_each_window_every_count_then_the_failures(
    signed_in: list[str], capsys: CaptureFixture[str]
) -> None:
    """Each target's window first, then each count, in order, with what short leaves out.

    Listings, files skipped or failed. Each window starts at --since, and the coverage of
    each target grew.
    """
    assert main([*signed_in, "--summary", "detailed"]) == SOME_FAILED
    space, project, *counts, failures = capsys.readouterr().out.splitlines()
    since = "from 2026-10-02T00:00:00+00:00 to "
    assert space.startswith(f"space MFS: {since}")
    assert project.startswith(f"project PRB: {since}")
    assert space.endswith(", given; coverage extended")
    assert counts == sorted(counts)
    assert {
        "confluence pages: listed: 3",
        "confluence pages: fetched: 2",
        "files: downloaded: 2",
        "files: skipped, media type not kept: 1",
        "files failed: status 404: 1",
    } <= set(counts)
    assert failures == "failures: 1"


def test_a_stopped_download_says_why_in_short(
    home: Path, monkeypatch: MonkeyPatch, capsys: CaptureFixture[str]
) -> None:
    """Too many failures in a row stop a run: short says so, else it reads as a whole run."""
    counts = {
        "confluence pages: fetched": 3,
        "confluence pages failed: status 503": 5,
        "runs: stopped, too many failures in a row": 1,
    }
    stopped = Outcome(
        report=Report(counts=Counter(counts)), failed_targets=[], status=ExitStatus.FAILED
    )
    monkeypatch.setattr(download_command, "download", lambda *_: stopped)
    assert main(command(home, "--site", SITE, "--space", "MFS")) == SOME_FAILED
    assert capsys.readouterr().out == (
        "confluence pages: fetched: 3\nruns: stopped, too many failures in a row: 1\nfailures: 5\n"
    )


def test_a_dry_run_shows_what_it_would_fetch(
    signed_in: list[str], capsys: CaptureFixture[str]
) -> None:
    """In short: each window, the documents to fetch of each kind, the files to download.

    No failure. The files to download are those that a listing names: the issue's. The
    windows say nothing of the coverage, which a dry run does not write.
    """
    assert main([*signed_in, "--dry-run"]) == 0
    space, project, *rest = capsys.readouterr().out.splitlines(keepends=True)
    assert space.startswith("space MFS: from 2026-10-02T00:00:00+00:00 to ")
    assert space.endswith(", given\n")
    assert project.startswith("project PRB: from 2026-10-02T00:00:00+00:00 to ")
    assert "".join(rest) == (
        "confluence blogposts: to fetch: 1\n"
        "confluence pages: to fetch: 2\n"
        "files: to download: 1\n"
        "jira issues: to fetch: 1\n"
        "failures: 0\n"
    )


def test_a_download_gives_its_counts_failed_keys_and_status_as_json(
    signed_in: list[str], capsys: CaptureFixture[str]
) -> None:
    """One document: the counts whole, the user's keys that failed, the exit status."""
    assert main([*signed_in, "--format", "json"]) == SOME_FAILED
    document = json.loads(capsys.readouterr().out)
    fetched = {"confluence pages: fetched": 2, "jira issues: fetched": 1}
    assert fetched.items() <= document["report"]["counts"].items()
    assert document["failed_targets"] == []
    assert document["status"] == SOME_FAILED
    assert [
        (each["target"], each["start"], each["reason"], each["coverage"])
        for each in document["windows"]
    ] == [
        ({"source": "confluence", "key": "MFS"}, "2026-10-02T00:00:00Z", "given", "extended"),
        ({"source": "jira", "key": "PRB"}, "2026-10-02T00:00:00Z", "given", "extended"),
    ]
    assert all(each["end"] for each in document["windows"])
    assert document["dry_run"] is False


def test_a_download_without_a_site_is_refused_by_name(
    home: Path, capsys: CaptureFixture[str]
) -> None:
    """The site is named as the missing setting, by the error run.refused."""
    assert main(command(home, "--space", "MFS", "--since", "7d")) == REFUSED
    err = capsys.readouterr().err
    assert said(err) == [("error", "run.refused")]
    assert "site: not set" in err


def test_a_download_of_nothing_is_refused(home: Path, capsys: CaptureFixture[str]) -> None:
    """Without a space or a project, there is nothing to do."""
    assert main(command(home, "--site", SITE, "--since", "7d")) == REFUSED
    assert "nothing to download" in capsys.readouterr().err


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
    """The option at fault is named, by the error download.refused, in the log file too."""
    options = ("--site", SITE, "--space", "MFS", "--since", "2026-10-22", "--until", "2026-10-01")
    assert main(command(home, *options)) == REFUSED
    err = capsys.readouterr().err
    assert ("error", "download.refused") in said(err)
    assert "--until" in err
    (refused,) = logged_as(home, "download.refused")
    assert refused["level"] == "error"
    assert "--until" in str(refused["reason"])


def test_without_a_session_the_user_is_told_to_sign_in(
    home: Path, capsys: CaptureFixture[str]
) -> None:
    """No saved session: exit 3, and the command to run, by download.sign_in_needed."""
    assert main(command(home, "--site", SITE, "--space", "MFS", "--since", "7d")) == SIGN_IN_NEEDED
    err = capsys.readouterr().err
    assert ("error", "download.sign_in_needed") in said(err)
    assert "run kb-mcp login" in err
    (needed,) = logged_as(home, "download.sign_in_needed")
    assert (needed["level"], needed["hint"]) == ("error", "run kb-mcp login")


def test_a_space_that_finds_nothing_is_named_on_stderr_and_not_in_the_report(
    home: Path, monkeypatch: MonkeyPatch, capsys: CaptureFixture[str]
) -> None:
    """The user's own key is shown to them, and never written to the run report.

    It is the warning download.target_failed, which the run's log file holds too.
    """
    chosen = MODEL(accounts={"atlassian": {"site": SITE}}, data_dir=(home / "kb-mcp").resolve())
    write_cookies(chosen.session / COOKIES, [{"name": "s", "value": "v", "domain": "x"}])
    fake = FakeSite(spaces=[])
    monkeypatch.setattr(http, "client", lambda *_: fake.client())
    options = ("--site", SITE, "--space", "NOPE", "--since", "7d", "--summary", "detailed")
    assert main(command(home, *options)) == SOME_FAILED
    captured = capsys.readouterr()
    assert ("warning", "download.target_failed") in said(captured.err)
    assert "space NOPE: not found" in captured.err
    (failed,) = logged_as(home, "download.target_failed")
    assert (failed["level"], failed["target"]) == ("warning", "space NOPE: not found")
    assert "confluence spaces failed: not found: 1" in captured.out
    [report] = chosen.runs.iterdir()
    assert "NOPE" not in report.read_text("utf-8")
    assert json.loads(report.read_text("utf-8"))["status"] == SOME_FAILED


def test_ctrl_c_exits_130_and_says_where_the_counts_are(
    home: Path, monkeypatch: MonkeyPatch, capsys: CaptureFixture[str]
) -> None:
    """An interrupted run is the shell's 130, not a failure: download.interrupted warns."""

    def interrupted(*_: object) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr(download_command, "download", interrupted)
    options = ("--site", SITE, "--space", "MFS", "--since", "7d")
    assert main(command(home, *options)) == INTERRUPTED
    runs = str(Settings(data_dir=(home / "kb-mcp").resolve()).runs)
    err = capsys.readouterr().err
    assert ("warning", "download.interrupted") in said(err)
    assert runs in err
    (interrupted,) = logged_as(home, "download.interrupted")
    assert (interrupted["level"], interrupted["counts"]) == ("warning", runs)


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
    assert ("error", "download.store_busy") in said(err)
    assert "another run is writing it; try again once that run ends" in err
    (busy,) = logged_as(home, "download.store_busy")
    assert (busy["level"], busy["store"]) == ("error", str(chosen.raw))


# Plan 034: what a run counts is what it fetches, apart from what it lists.
LISTED_AT = datetime(2026, 10, 22, 9, tzinfo=UTC)
COUNTED_AT = datetime(2026, 10, 27, 9, tzinfo=UTC)
SINCE = datetime(2026, 10, 20, tzinfo=UTC)


def counted(
    tmp_path: Path, monkeypatch: MonkeyPatch, since: datetime | None, *, first_fetch: bool
) -> tuple[Outcome, list[dict[str, object]], Settings]:
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
        outcome = download(chosen, targets, lambda: COUNTED_AT, lambda _: None)
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

    download.listed says each number, and the window's reason; the window goes to the
    JSON, and the run report names no target.
    """
    outcome, events, chosen = counted(tmp_path, monkeypatch, since, first_fetch=first_fetch)
    listed = [event for event in events if event["event"] == "download.listed"]
    assert [
        (each["listed"], each["in_window"], each["stored"], each["to_fetch"], each["reason"])
        for each in listed
    ] == [(50, 7, 4, 3, reason)]
    tasks = [(each["done"], each["total"]) for each in events if each.get("task") == "documents"]
    assert tasks[-1] == (3, 3)
    assert download_command.text(outcome, "short") == "confluence pages: fetched: 3\nfailures: 0\n"
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
    detailed = download_command.text(outcome, "detailed")
    assert "confluence pages: new or changed since the last fetch: 3\n" in detailed
    assert "confluence pages: fetched: 3\n" in detailed
    assert "in the period" not in detailed
    assert "already stored" not in detailed


def test_with_since_the_detail_counts_what_is_in_the_period_and_stored(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """Given --since, the period is the user's: what is in it, and what was stored already."""
    outcome, _, _ = counted(tmp_path, monkeypatch, SINCE, first_fetch=False)
    detailed = download_command.text(outcome, "detailed")
    assert "confluence pages: in the period: 7\n" in detailed
    assert "confluence pages: already stored: 4\n" in detailed
    assert "confluence pages: fetched: 3\n" in detailed
    assert "new or changed" not in detailed
