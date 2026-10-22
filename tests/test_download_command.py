"""The download command as the user meets it: its refusals, messages and exit statuses."""

from __future__ import annotations

import json
import time
from typing import TYPE_CHECKING

import pytest

from atlassian_offline_mcp.cli.commands import download as download_command
from atlassian_offline_mcp.cli.main import main
from atlassian_offline_mcp.config.domain.settings import Settings
from atlassian_offline_mcp.sources.atlassian.adapters import http
from atlassian_offline_mcp.sources.atlassian.adapters.raw_store import RawStore
from atlassian_offline_mcp.sources.atlassian.adapters.session_file import COOKIES, write_cookies
from tests.test_download import SITE, FakeSite

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
    return ["download", "--config", str(home / "none.toml"), *options]


@pytest.fixture
def signed_in(home: Path, monkeypatch: MonkeyPatch) -> list[str]:
    """Save a session, and serve the scripted site; give the options of a run over it.

    Its space and project changed since 2 October: two pages, a blog post and an issue,
    with three files to keep, of which one fails, and a video, which is not kept.
    """
    chosen = Settings(site=SITE, data_dir=(home / "atlassian-offline-mcp").resolve())
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


def test_a_download_in_detail_shows_every_count_then_the_failures(
    signed_in: list[str], capsys: CaptureFixture[str]
) -> None:
    """Each count, in order, with what short leaves out: listings, files skipped or failed."""
    assert main([*signed_in, "--summary", "detailed"]) == SOME_FAILED
    *counts, failures = capsys.readouterr().out.splitlines()
    assert counts == sorted(counts)
    assert {
        "confluence pages: listed: 3",
        "confluence pages: fetched: 2",
        "files: downloaded: 2",
        "files: skipped, media type not kept: 1",
        "files failed: status 404: 1",
    } <= set(counts)
    assert failures == "failures: 1"


def test_a_dry_run_shows_what_it_would_fetch(
    signed_in: list[str], capsys: CaptureFixture[str]
) -> None:
    """In short: the documents to fetch of each kind, the files to download, no failure.

    The files to download are those that a listing names: the issue's.
    """
    assert main([*signed_in, "--plan"]) == 0
    assert capsys.readouterr().out == (
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


def test_a_download_without_a_site_is_refused_by_name(
    home: Path, capsys: CaptureFixture[str]
) -> None:
    """The site is named as the missing setting."""
    assert main(command(home, "--space", "MFS", "--since", "7d")) == REFUSED
    assert "refused: site: not set" in capsys.readouterr().err


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
    """The option at fault is named."""
    options = ("--site", SITE, "--space", "MFS", "--since", "2026-10-22", "--until", "2026-10-01")
    assert main(command(home, *options)) == REFUSED
    assert "--until" in capsys.readouterr().err


def test_without_a_session_the_user_is_told_to_sign_in(
    home: Path, capsys: CaptureFixture[str]
) -> None:
    """No saved session: exit 3, and the command to run."""
    assert main(command(home, "--site", SITE, "--space", "MFS", "--since", "7d")) == SIGN_IN_NEEDED
    assert "sign-in needed: run atlassian-offline-mcp login" in capsys.readouterr().err


def test_a_space_that_finds_nothing_is_named_on_stderr_and_not_in_the_report(
    home: Path, monkeypatch: MonkeyPatch, capsys: CaptureFixture[str]
) -> None:
    """The user's own key is shown to them, and never written to the run report."""
    chosen = Settings(site=SITE, data_dir=(home / "atlassian-offline-mcp").resolve())
    write_cookies(chosen.session / COOKIES, [{"name": "s", "value": "v", "domain": "x"}])
    fake = FakeSite(spaces=[])
    monkeypatch.setattr(http, "client", lambda *_: fake.client())
    options = ("--site", SITE, "--space", "NOPE", "--since", "7d", "--summary", "detailed")
    assert main(command(home, *options)) == SOME_FAILED
    captured = capsys.readouterr()
    assert "space NOPE: not found" in captured.err
    assert "confluence spaces failed: not found: 1" in captured.out
    [report] = chosen.runs.iterdir()
    assert "NOPE" not in report.read_text("utf-8")
    assert json.loads(report.read_text("utf-8"))["status"] == SOME_FAILED


def test_ctrl_c_exits_130_and_says_where_the_counts_are(
    home: Path, monkeypatch: MonkeyPatch, capsys: CaptureFixture[str]
) -> None:
    """An interrupted run is the shell's 130, not a failure."""

    def interrupted(*_: object) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr(download_command, "download", interrupted)
    options = ("--site", SITE, "--space", "MFS", "--since", "7d")
    assert main(command(home, *options)) == INTERRUPTED
    assert "interrupted; the counts so far are in" in capsys.readouterr().err


def test_a_busy_store_exits_1_with_its_reason(
    home: Path, monkeypatch: MonkeyPatch, capsys: CaptureFixture[str]
) -> None:
    """Another run writing the store: the user is told to wait for it."""
    chosen = Settings(site=SITE, data_dir=(home / "atlassian-offline-mcp").resolve())
    write_cookies(chosen.session / COOKIES, [{"name": "s", "value": "v", "domain": "x"}])
    monkeypatch.setattr(http, "client", lambda *_: FakeSite().client())
    options = ("--site", SITE, "--space", "MFS", "--since", "7d")
    with RawStore(chosen.raw).writing():
        assert main(command(home, *options)) == SOME_FAILED
    assert "another run is writing the raw store" in capsys.readouterr().err
