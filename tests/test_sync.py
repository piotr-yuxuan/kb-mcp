"""``sync`` as plan 017 defines it: the sources it takes, what it says, its steps, its status.

The expectations come from the plan's "What sync does" and "Choosing sources", and its
criteria 3 to 6, 11 and 12. The Atlassian sources are served by plan 004's scripted site,
the work log is the invented fixture; each test has a scratch home, and terminals are
injected or ``--yes`` given. Each test searches by words alone, which need no embedding
endpoint, rather than rely on the default; one whose requirement is meaning, or the
defaults, sets or removes the mode itself.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import sqlite3
import time
from collections import Counter
from contextlib import closing
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from pydantic_core import to_json
from structlog.testing import capture_logs

from kb_mcp.cli.app import sync as sync_app
from kb_mcp.cli.app.sync import Atlassian, Context, Index, Row, Worklog, sync
from kb_mcp.cli.domain.sync import SOURCES, chosen
from kb_mcp.cli.main import main, parser
from kb_mcp.cli.options.sync import refused
from kb_mcp.config.domain.settings import DEFAULT_MODEL, Settings
from kb_mcp.kernel.content import SOURCE_NAMES
from kb_mcp.kernel.exit_status import ExitStatus
from kb_mcp.mirror.adapters import pandoc as pandoc_adapter
from kb_mcp.mirror.adapters.mirror_files import Changes
from kb_mcp.mirror.adapters.pandoc import (
    Pandoc,
    PandocFailedError,
    PandocMissingError,
)
from kb_mcp.mirror.app import mirror as mirror_app
from kb_mcp.search.adapters import sqlite_index, vector_store
from kb_mcp.search.app.indexing import Indexing
from kb_mcp.sources.atlassian.adapters import http
from kb_mcp.sources.atlassian.adapters.raw_store import RawStore, StoreBusyError
from kb_mcp.sources.atlassian.adapters.session_file import COOKIES, write_cookies
from kb_mcp.sources.atlassian.app.download import Outcome, Report, Targets
from kb_mcp.sources.atlassian.domain.coverage import Target
from tests.endpoint import DIGEST, Scripted, scripted, serving
from tests.mirrors import fillers
from tests.reference import Emitted, documented, pattern, undocumented
from tests.test_cli import logged_as as logged_in_files
from tests.test_download import CAP, PAGES, SITE, FakeSite
from tests.test_question import QUESTION, Terminal
from tests.test_refresh import FIRST, SECOND, WEEK, RefreshSite, stored_pages
from tests.test_worklog_mirror import FIXTURE, Counting, settle, snapshot

if TYPE_CHECKING:
    import argparse
    from collections.abc import Callable
    from datetime import datetime

    from _pytest.capture import CaptureFixture
    from _pytest.monkeypatch import MonkeyPatch
    from opentelemetry.sdk.metrics.export import Metric

    from tests.conftest import InMemory

# Each setting that chooses a source, as the declaration's functions take them.
CONFIGURED = {
    "site": SITE,
    "email": None,
    "api_token": None,
    "sources.confluence.spaces": ("MFS",),
    "sources.jira.projects": ("PRB",),
    "sources.worklog.path": Path("/work/todo"),
    "sources.worklog.archives": True,
    "search_mode": "lexical",
    "embedding_url": "https://embeddings.example/v1",
}
ALL = ["confluence", "jira", "worklog"]
# The work log's documents in the fixture, by kind: thirteen entries, two days, eight
# meetings and six transcripts, one of them under meetings/.
WORKLOG_KINDS = {"entry": 13, "day": 2, "meeting": 8, "transcript": 6}
WORKLOG_DOCUMENTS = sum(WORKLOG_KINDS.values())


def arguments(*given: str) -> argparse.Namespace:
    """Parse sync's arguments as the command does."""
    return parser().parse_args(["sync", *given])


@pytest.mark.parametrize(
    ("given", "taken"),
    [
        ((), ALL),
        (("--include", "jira"), ["jira"]),
        (("--exclude", "worklog"), ["confluence", "jira"]),
        (("--include", "worklog", "--include", "jira"), ["jira", "worklog"]),
        (("--exclude", "confluence", "--exclude", "jira"), ["worklog"]),
    ],
)
def test_the_flags_choose_among_the_configured_sources(
    given: tuple[str, ...], taken: list[str]
) -> None:
    """No flag takes every one; --include those named; --exclude the others."""
    found, _ = chosen(arguments(*given), CONFIGURED)
    assert [source.name for source in found] == taken


def test_a_source_without_its_table_is_left_out_saying_why() -> None:
    """Configured means its table names a space, a project or a folder."""
    settings = CONFIGURED | {"sources.jira.projects": ()}
    found, left = chosen(arguments(), settings)
    assert [source.name for source in found] == ["confluence", "worklog"]
    assert left == {"jira": "not configured"}


@pytest.fixture
def home(tmp_path: Path, monkeypatch: MonkeyPatch) -> Path:
    """Give each test a scratch home, and no waiting between requests."""
    scratch = tmp_path / "home"
    scratch.mkdir()
    monkeypatch.setenv("HOME", str(scratch))
    monkeypatch.setattr(time, "sleep", lambda _: None)
    return scratch


@pytest.fixture
def worklog(tmp_path: Path) -> Path:
    """Copy the fixture's work log, at fixed times."""
    root = tmp_path / "todo"
    shutil.copytree(FIXTURE, root)
    settle(root)
    return root


@pytest.fixture(autouse=True)
def words_alone(monkeypatch: MonkeyPatch) -> None:
    """Search by words alone, so that the index that sync builds calls no endpoint."""
    monkeypatch.setenv("ATLASSIAN_OFFLINE_MCP_SEARCH_MODE", "lexical")


def settings_file(home: Path, worklog: Path | None, *, atlassian: bool = False) -> Path:
    """Write a settings file naming the work log, and with ``atlassian``, MFS and PRB."""
    text = ""
    if atlassian:
        text += f'site = "{SITE}"\n[sources.confluence]\nspaces = ["MFS"]\n'
        text += '[sources.jira]\nprojects = ["PRB"]\n'
    if worklog is not None:
        text += f'[sources.worklog]\npath = "{worklog}"\n'
    config = home / "config.toml"
    config.write_text(text, "utf-8")
    return config


def command(home: Path, config: Path, *more: str) -> list[str]:
    """Give sync's arguments: this settings file, the data in the home, then ``more``."""
    return ["sync", "--config", str(config), "--data-dir", str(home / "data"), *more]


@pytest.mark.parametrize(
    ("given", "named"),
    [
        (("--include", "worklog"), "--include worklog: not configured"),
        (("--exclude", "confluence", "--exclude", "jira", "--exclude", "worklog"), "nothing"),
    ],
)
def test_a_choice_that_leaves_nothing_to_run_exits_2_saying_why(
    home: Path, capsys: CaptureFixture[str], given: tuple[str, ...], named: str
) -> None:
    """A source included without its table, or every source excluded."""
    config = settings_file(home, None, atlassian=True)
    assert main(command(home, config, "--yes", *given)) == ExitStatus.REFUSED
    assert named in capsys.readouterr().err


def test_a_source_that_does_not_exist_is_refused_by_the_options(
    home: Path, capsys: CaptureFixture[str]
) -> None:
    """--include gitlab: argparse names the choices."""
    config = settings_file(home, None, atlassian=True)
    with pytest.raises(SystemExit) as stopped:
        main(command(home, config, "--include", "gitlab"))
    assert stopped.value.code == ExitStatus.REFUSED
    assert "invalid choice: 'gitlab'" in capsys.readouterr().err


def test_the_work_log_alone_says_the_period_it_ignores_and_a_dry_run_writes_nothing(
    home: Path, worklog: Path, monkeypatch: MonkeyPatch, capsys: CaptureFixture[str]
) -> None:
    """--since given, ignored by the work log, said; no other option; nothing written.

    No setting is given by variable either: a dry run would say the mode ignored.
    """
    monkeypatch.delenv("ATLASSIAN_OFFLINE_MCP_SEARCH_MODE")
    config = settings_file(home, worklog)
    before = snapshot(worklog)
    assert main(command(home, config, "--include", "worklog", "--since", "7d", "--dry-run")) == 0
    said = capsys.readouterr().err
    assert "--since: ignored by worklog\n" in said
    assert said.count("ignored") == 1
    assert snapshot(worklog) == before
    assert not (home / "data").exists()


def test_the_work_log_alone_ignores_nothing_when_given_nothing_to_ignore(
    home: Path, worklog: Path, capsys: CaptureFixture[str]
) -> None:
    """Sync --include worklog, its table alone in the file: nothing said to be ignored."""
    config = settings_file(home, worklog)
    assert main(command(home, config, "--include", "worklog", "--yes")) == 0
    captured = capsys.readouterr()
    assert "ignored" not in captured.err
    assert captured.out.startswith(f"worklog: done\n  documents: {WORKLOG_DOCUMENTS}\n")


def test_sync_asks_once_after_naming_each_source_taken_and_left_out(
    home: Path, worklog: Path, monkeypatch: MonkeyPatch
) -> None:
    """On terminals: each source taken, with its keys or folder, each left out, one question."""
    config = settings_file(home, worklog, atlassian=True)
    stderr = Terminal()
    monkeypatch.setattr("sys.stdin", Terminal("n\n"))
    monkeypatch.setattr("sys.stderr", stderr)
    assert main(command(home, config, "--exclude", "jira")) == ExitStatus.FAILED
    said = stderr.getvalue()
    asked = said.index(QUESTION)
    for line in (
        "source confluence: spaces MFS\n",
        f"source worklog: path {worklog}, archives True\n",
        "source jira: left out, excluded\n",
    ):
        assert -1 < said.index(line) < asked
    assert said.count(QUESTION) == 1
    assert not (home / "data").exists()


@pytest.fixture
def signed_in(home: Path, monkeypatch: MonkeyPatch) -> FakeSite:
    """Save a session in the home's data folder, and serve the scripted site of plan 004."""
    chosen_settings = Settings(site=SITE, data_dir=(home / "data").resolve())
    write_cookies(chosen_settings.session / COOKIES, [{"name": "s", "value": "v", "domain": "x"}])
    fake = FakeSite()
    monkeypatch.setattr(http, "client", lambda *_: fake.client())
    return fake


def test_json_is_one_document_with_a_row_per_step(
    home: Path, worklog: Path, signed_in: FakeSite, capsys: CaptureFixture[str]
) -> None:
    """exit_status, then download, mirror, the work log and the index, each with its result."""
    config = settings_file(home, worklog, atlassian=True)
    given = ("--yes", "--since", "2026-10-02", "--format", "json")
    status = main(command(home, config, *given))
    document = json.loads(capsys.readouterr().out)
    assert document["exit_status"] == status == ExitStatus.FAILED  # one file fails
    assert [(row["step"], row["outcome"]) for row in document["steps"]] == [
        ("download", "failed"),
        ("mirror", "done"),
        ("worklog", "done"),
        ("index", "done"),
    ]
    assert document["steps"][2]["result"]["documents"] == WORKLOG_DOCUMENTS
    assert signed_in.asked


def test_an_until_before_since_exits_2_by_name_before_any_get(
    home: Path, signed_in: FakeSite, capsys: CaptureFixture[str]
) -> None:
    """Refused before the first step, naming them."""
    config = settings_file(home, None, atlassian=True)
    backwards = ("--since", "2026-10-22", "--until", "2026-10-01")
    assert main(command(home, config, "--yes", *backwards)) == ExitStatus.REFUSED
    err = capsys.readouterr().err
    assert "sync.refused" in err
    assert "--until: must come after --since" in err
    assert signed_in.asked == []


def test_a_first_sync_without_since_fetches_the_last_week_of_each_target(
    home: Path, signed_in: FakeSite, capsys: CaptureFixture[str]
) -> None:
    """Nothing covered no longer refuses the run: each target covers the 7 days before it.

    The line before the run states the rule, since the store is not read before then.
    """
    config = settings_file(home, None, atlassian=True)
    assert main(command(home, config, "--yes")) != ExitStatus.REFUSED
    rule = "period: since each target's last fetch; the last 7 days for one never fetched\n"
    assert rule in capsys.readouterr().err
    assert signed_in.asked
    periods = RawStore((home / "data" / "raw").resolve()).coverage().periods
    assert set(periods) == {Target("confluence", "MFS"), Target("jira", "PRB")}
    assert {each.end - each.start for each in periods.values()} == {WEEK}


def context(settings: Settings, now: datetime, pandoc: Pandoc | None = None) -> Context:
    """Give a sync's context at ``now``."""
    return Context(settings, pandoc or Pandoc.find(), lambda: now, lambda _: None, dry_run=False)


def by_words(settings: Settings) -> Index:
    """Give the index's step as sync builds it in the lexical mode: no endpoint."""
    return Index(
        Indexing(
            settings.docs,
            settings.index,
            settings.vectors,
            settings.evaluation_indexes,
            settings.aliases,
            settings.model,
            settings.chunking,
            None,
        )
    )


def test_the_index_step_prunes_and_a_deferred_prune_leaves_it_done(tmp_path: Path) -> None:
    """Its row holds what the prune did; one that a build in progress defers fails nothing."""
    settings = Settings(data_dir=tmp_path / "data", model="tiny")
    fillers(settings.docs, 3)
    step = Index(
        Indexing(
            settings.docs,
            settings.index,
            settings.vectors,
            settings.evaluation_indexes,
            settings.aliases,
            "tiny",
            "sections",
            scripted,
        )
    )
    with vector_store.shared(settings.vectors):
        deferred = sync(context(settings, FIRST), [step])
    done = sync(context(settings, FIRST), [step])
    rows = [json.loads(to_json(synced))["steps"] for synced in (deferred, done)]
    assert [(row["outcome"], row["result"]["pruned"]["outcome"]) for [row] in rows] == [
        ("done", "deferred"),
        ("done", "pruned"),
    ]


def logged_as(logged: list[dict[str, object]], event: str) -> list[dict[str, object]]:
    """Give each event of this name that ``capture_logs`` held."""
    return [each for each in logged if each["event"] == event]


def chosen_settings(tmp_path: Path, worklog: Path) -> Settings:
    """Give settings with a site, a data folder with a saved session, and the work log."""
    settings = Settings(
        site=SITE, data_dir=tmp_path / "data", sources={"worklog": {"path": worklog}}
    )
    write_cookies(settings.session / COOKIES, [{"name": "s", "value": "v", "domain": "x"}])
    return settings


def test_a_later_sync_catches_up_on_an_old_page_edited_today_and_nothing_stored(
    tmp_path: Path, worklog: Path, monkeypatch: MonkeyPatch
) -> None:
    """A first sync over a week; a second, with no --since, fetches the edited page alone."""
    settings = chosen_settings(tmp_path, worklog)
    monkeypatch.setattr(http, "client", lambda *_: RefreshSite().client())
    first = Atlassian(Targets(["MFS"], [], CAP, since=FIRST - WEEK))
    assert sync(context(settings, FIRST), [first]).exit_status == ExitStatus.OK
    assert "1003" not in stored_pages(settings)
    edited = {"number": 4, "createdAt": "2026-10-23T08:00:00.000Z"}
    later = RefreshSite(listing={**PAGES, "1003": {**PAGES["1003"], "version": edited}})
    monkeypatch.setattr(http, "client", lambda *_: later.client())
    synced = sync(context(settings, SECOND), [Atlassian(Targets(["MFS"], [], CAP))])
    assert synced.exit_status == ExitStatus.OK
    fetched = synced.steps[0].result
    assert isinstance(fetched, Outcome)
    assert fetched.report.counts["confluence pages: fetched"] == 1
    assert stored_pages(settings)["1003"] == "000004"


def test_the_site_asking_to_sign_in_still_lets_the_work_log_run_exit_3(
    tmp_path: Path, worklog: Path
) -> None:
    """No session saved: the download says to sign in; the mirror, work log and index run."""
    settings = Settings(data_dir=tmp_path / "data", site=SITE)
    steps = [
        Atlassian(Targets(["MFS"], [], CAP, since=FIRST - WEEK)),
        Worklog(worklog, archives=True),
        by_words(settings),
    ]
    with capture_logs() as logged:
        synced = sync(context(settings, FIRST), steps)
    assert [(row.step, row.outcome) for row in synced.steps] == [
        ("download", "sign in"),
        ("mirror", "done"),
        ("worklog", "done"),
        ("index", "done"),
    ]
    assert synced.exit_status == ExitStatus.SIGN_IN_AGAIN
    assert logged_as(logged, "download.sign_in_needed")
    assert len(list((settings.docs / "worklog").rglob("*.md"))) == WORKLOG_DOCUMENTS


def test_ctrl_c_in_the_download_exits_130_and_no_later_step_runs(
    tmp_path: Path, worklog: Path, monkeypatch: MonkeyPatch
) -> None:
    """The download interrupted; the mirror, the work log and the index not run."""

    def interrupted(*_: object) -> Outcome:
        raise KeyboardInterrupt

    monkeypatch.setattr(sync_app, "download", interrupted)
    settings = chosen_settings(tmp_path, worklog)
    steps = [
        Atlassian(Targets(["MFS"], [], CAP, since=FIRST - WEEK)),
        Worklog(worklog, archives=True),
    ]
    synced = sync(context(settings, FIRST), [*steps, by_words(settings)])
    assert [(row.step, row.outcome) for row in synced.steps] == [
        ("download", "interrupted"),
        ("mirror", "not run"),
        ("worklog", "not run"),
        ("index", "not run"),
    ]
    assert synced.exit_status == ExitStatus.INTERRUPTED
    assert not settings.docs.exists()
    assert not settings.index.exists()


def test_a_mirror_problem_exits_1_with_the_work_log_mirrored(
    tmp_path: Path, worklog: Path, monkeypatch: MonkeyPatch
) -> None:
    """The mirror fails, said by place; the work log and the index still run."""
    problem = mirror_app.Problem("confluence/pages/1001/000001", "pandoc: exit status 9")
    monkeypatch.setattr(sync_app, "download", lambda *_: Outcome(Report(), [], ExitStatus.OK))
    monkeypatch.setattr(
        sync_app,
        "mirror",
        lambda *_: mirror_app.Outcome(0, 0, 0, Changes(0, 0, 0), Counter(), (problem,)),
    )
    settings = chosen_settings(tmp_path, worklog)
    steps = [
        Atlassian(Targets(["MFS"], [], CAP, since=FIRST - WEEK)),
        Worklog(worklog, archives=True),
    ]
    with capture_logs() as logged:
        synced = sync(context(settings, FIRST), [*steps, by_words(settings)])
    assert [(row.step, row.outcome) for row in synced.steps] == [
        ("download", "done"),
        ("mirror", "failed"),
        ("worklog", "done"),
        ("index", "done"),
    ]
    assert synced.exit_status == ExitStatus.FAILED
    (said,) = logged_as(logged, "mirror.not_mirrored")
    assert (said["where"], said["reason"]) == (problem.where, problem.reason)
    assert len(list((settings.docs / "worklog").rglob("*.md"))) == WORKLOG_DOCUMENTS


def test_an_index_that_cannot_be_written_fails_its_row_and_keeps_the_others(
    tmp_path: Path, worklog: Path, monkeypatch: MonkeyPatch
) -> None:
    """The database's error while indexing, as of a full disk, simulated: exit 1.

    The work log's row stays, the index's fails, and the index in place stays as it was.
    """

    def full(*_: object) -> None:
        message = "database or disk is full"
        raise sqlite3.OperationalError(message)

    settings = chosen_settings(tmp_path, worklog)
    steps = [Worklog(worklog, archives=True), by_words(settings)]
    assert sync(context(settings, FIRST), steps).exit_status == ExitStatus.OK
    before = settings.index.read_bytes()
    monkeypatch.setattr(sqlite_index.Writer, "add", full)
    with capture_logs() as logged:
        synced = sync(context(settings, FIRST), steps)
    assert [(row.step, row.outcome) for row in synced.steps] == [
        ("worklog", "done"),
        ("index", "failed"),
    ]
    assert synced.exit_status == ExitStatus.FAILED
    (said,) = logged_as(logged, "index.not_built")
    assert said["reason"] == "database or disk is full"
    assert settings.index.read_bytes() == before


def test_a_work_log_that_is_not_a_folder_is_refused_before_any_step(
    home: Path, tmp_path: Path, capsys: CaptureFixture[str]
) -> None:
    """Named by its setting; nothing is written."""
    config = settings_file(home, tmp_path / "absent")
    assert main(command(home, config, "--yes")) == ExitStatus.REFUSED
    err = capsys.readouterr().err
    assert "sync.refused" in err
    assert "sources.worklog.path: not a folder" in err
    assert not (home / "data").exists()


def test_sync_and_its_dry_run_leave_the_work_log_as_it_was(
    home: Path, worklog: Path, capsys: CaptureFixture[str]
) -> None:
    """Every byte and time of the folder, a .git folder in it, stay as they were."""
    (worklog / ".git" / "objects").mkdir(parents=True)
    (worklog / ".git" / "HEAD").write_text("ref: refs/heads/main\n", "utf-8")
    settle(worklog)
    before = snapshot(worklog)
    config = settings_file(home, worklog)
    assert main(command(home, config, "--dry-run")) == 0
    assert main(command(home, config, "--yes")) == 0
    assert main(command(home, config, "--yes")) == 0
    assert snapshot(worklog) == before
    second = capsys.readouterr().out.split("worklog: done\n")[-1]
    assert "files written: 0\n" in second


def test_a_failed_conversion_keeps_a_deleted_transcript_s_file_saying_so(
    tmp_path: Path, worklog: Path, telemetry: InMemory
) -> None:
    """Until the next clean run; the logs say that nothing was removed, nor held back.

    The row's event and span say that it failed, and the entry is counted failed.
    """
    settings = chosen_settings(tmp_path, worklog)
    step = Worklog(worklog, archives=True)
    sync(context(settings, FIRST), [step])
    gone = next((settings.docs / "worklog/transcripts").glob("*waiting-notes.md"))
    (worklog / "transcripts/misc/a.org").unlink()
    todo = worklog / "todo.org"
    todo.write_text(todo.read_text("utf-8").replace("Drafted on", "Drafted, failing, on"), "utf-8")
    failing = Counting(Pandoc.find().path, failing="failing")
    telemetry.spans.clear()
    telemetry.measured()
    with capture_logs() as logged:
        synced = sync(context(settings, FIRST, failing), [step])
    assert (synced.steps[0].outcome, synced.exit_status) == ("failed", ExitStatus.FAILED)
    (kept,) = logged_as(logged, "worklog.nothing_removed")
    assert (kept["problems"], kept["held_back"]) == (1, 0)
    assert [each["outcome"] for each in logged_as(logged, "sync.step")] == ["failed"]
    spans = telemetry.spans.get_finished_spans()
    (row,) = [span for span in spans if span.name == "sync.step"]
    assert row.attributes["aom.outcome"] == "failed"
    assert by_kind_and_outcome(telemetry.measured()).get(("entry", "failed")) == 1
    assert gone.exists()
    todo.write_text(todo.read_text("utf-8").replace("Drafted, failing, on", "Drafted on"), "utf-8")
    assert sync(context(settings, FIRST), [step]).exit_status == ExitStatus.OK
    assert not gone.exists()


def test_the_text_gives_a_row_per_step_then_its_counts(
    home: Path, worklog: Path, capsys: CaptureFixture[str]
) -> None:
    """The work log's: documents, files, HTML left out, problems; a dry run's to convert.

    Then the index's row: not run in a dry run, else index's counts, the work log's
    documents among them.
    """
    config = settings_file(home, worklog)
    assert main(command(home, config, "--dry-run")) == 0
    assert capsys.readouterr().out == (
        "worklog: done\n"
        f"  documents: {WORKLOG_DOCUMENTS}\n"
        f"  to convert: {WORKLOG_DOCUMENTS}\n"
        "  files to remove: 0\n"
        "  HTML left out: 1\n"
        "  problems: 0\n"
        "index: not run\n"
    )
    assert main(command(home, config, "--yes")) == 0
    assert re.fullmatch(
        "worklog: done\n"
        f"  documents: {WORKLOG_DOCUMENTS}\n"
        f"  files written: {WORKLOG_DOCUMENTS}\n"
        "  files unchanged: 0\n"
        "  files removed: 0\n"
        "  HTML left out: 1\n"
        "  problems: 0\n"
        "index: done\n"
        f"  documents: {WORKLOG_DOCUMENTS}\n"
        r"  sections: [1-9][0-9]*\n",
        capsys.readouterr().out,
    )


def test_the_sources_are_the_names_that_the_options_offer() -> None:
    """--include and --exclude offer the kernel's names; sync's records bear the same."""
    assert tuple(source.name for source in SOURCES) == SOURCE_NAMES


def test_a_dry_run_of_the_site_plans_and_writes_nothing(
    home: Path, signed_in: FakeSite, capsys: CaptureFixture[str]
) -> None:
    """The download planned, mirror and index not run; the data folder holds the session alone."""
    config = settings_file(home, None, atlassian=True)
    given = ("--dry-run", "--since", "2026-10-02", "--format", "json")
    assert main(command(home, config, *given)) == ExitStatus.OK
    rows = json.loads(capsys.readouterr().out)["steps"]
    assert [(row["step"], row["outcome"]) for row in rows] == [
        ("download", "done"),
        ("mirror", "not run"),
        ("index", "not run"),
    ]
    assert "confluence pages: to fetch" in rows[0]["result"]["report"]["counts"]
    windows = rows[0]["result"]["windows"]
    assert [(each["target"]["key"], each["reason"], each["coverage"]) for each in windows] == [
        ("MFS", "given", None),
        ("PRB", "given", None),
    ]
    assert rows[0]["result"]["dry_run"] is True
    assert sorted(path.name for path in (home / "data").iterdir()) == ["session"]
    assert signed_in.asked


def test_a_dry_run_of_the_site_says_each_target_s_window_under_its_row(
    home: Path, signed_in: FakeSite, capsys: CaptureFixture[str]
) -> None:
    """Short as it is: the window of each target, where it starts and why, then the counts."""
    config = settings_file(home, None, atlassian=True)
    assert main(command(home, config, "--dry-run", "--since", "2026-10-02")) == ExitStatus.OK
    download_step, space, project, *_ = capsys.readouterr().out.splitlines()
    assert download_step == "download: done"
    assert space.startswith("  space MFS: from 2026-10-02T00:00:00+00:00 to ")
    assert project.startswith("  project PRB: from 2026-10-02T00:00:00+00:00 to ")
    assert space.endswith(", given")
    assert signed_in.asked


@pytest.mark.parametrize(
    "case",
    [
        (("--exclude", "worklog"), ["download", "mirror", "index"], True),
        (("--exclude", "confluence"), ["download", "mirror", "worklog", "index"], False),
        (("--include", "worklog"), ["worklog", "index"], False),
    ],
)
def test_the_sources_chosen_are_the_steps_run(
    home: Path,
    worklog: Path,
    signed_in: FakeSite,
    capsys: CaptureFixture[str],
    case: tuple[tuple[str, ...], list[str], bool],
) -> None:
    """Excluded or not included: no step, no request, no file of it; the index runs always."""
    given, steps, confluence = case
    config = settings_file(home, worklog, atlassian=True)
    main(command(home, config, "--yes", "--since", "2026-10-02", "--format", "json", *given))
    rows = json.loads(capsys.readouterr().out)["steps"]
    assert [row["step"] for row in rows] == steps
    assert any("/wiki/" in url.path for url in signed_in.asked) is confluence
    assert (home / "data" / "docs" / "worklog").exists() is ("worklog" in steps)


def test_archives_off_leaves_the_archived_documents_out_of_a_sync(
    home: Path, worklog: Path, capsys: CaptureFixture[str]
) -> None:
    """The archive file's entry and meetings, the ARCHIVE entry, the archived transcript."""
    config = settings_file(home, worklog)
    config.write_text(config.read_text("utf-8") + "archives = false\n", "utf-8")
    assert main(command(home, config, "--yes", "--format", "json")) == 0
    result = json.loads(capsys.readouterr().out)["steps"][0]["result"]
    archived = ["vendor", "old incident", "1.org", "incident review", "capacity planning"]
    assert result["documents"] == WORKLOG_DOCUMENTS - len(archived)
    labels = [
        line for path in (home / "data").rglob("*.md") for line in path.read_text("utf-8").split()
    ]
    assert "ARCHIVE" not in labels


def test_the_settings_of_sources_left_out_are_said_not_applied(
    home: Path, worklog: Path, capsys: CaptureFixture[str]
) -> None:
    """Their values, given by the file, are ignored by name and layer, saying why."""
    config = settings_file(home, worklog, atlassian=True)
    assert main(command(home, config, "--yes", "--include", "worklog")) == 0
    said = capsys.readouterr().err
    assert "ignored: site (config.toml): no Atlassian source in this sync\n" in said
    assert "ignored: sources.jira.projects (config.toml): jira not included\n" in said


def test_a_work_log_that_is_a_file_is_refused_as_not_a_folder(
    home: Path, tmp_path: Path, capsys: CaptureFixture[str]
) -> None:
    """A regular file named as the folder: exit 2."""
    (tmp_path / "todo.org").write_text("* x\n", "utf-8")
    config = settings_file(home, tmp_path / "todo.org")
    assert main(command(home, config, "--yes")) == ExitStatus.REFUSED
    assert "sources.worklog.path: not a folder" in capsys.readouterr().err


@pytest.mark.usefixtures("signed_in")
def test_a_second_sync_reuses_every_conversion_and_the_work_log_adds_none(
    home: Path, worklog: Path, capsys: CaptureFixture[str]
) -> None:
    """Plan 039, criterion 7: the data folder's cache holds the mirror's conversions alone.

    A first sync converts, a second reuses each conversion, by its mirror row in JSON,
    then in text.
    """
    config = settings_file(home, worklog, atlassian=True)
    given = ("--yes", "--since", "2026-10-02")
    rows = []
    for output in (("--format", "json"), ("--format", "json"), ()):
        main(command(home, config, *given, *output))
        rows.append(capsys.readouterr().out)
    first, second = (json.loads(row)["steps"][1] for row in rows[:2])
    assert (first["step"], first["outcome"], first["result"]["reused"]) == ("mirror", "done", 0)
    converted = first["result"]["converted"]
    assert converted > first["result"]["documents"] > 0  # a tree among them
    assert (second["result"]["converted"], second["result"]["reused"]) == (0, converted)
    documents = first["result"]["documents"]
    assert (
        f"mirror: done\n  documents: {documents}\n"
        f"  converted by pandoc: 0\n  reused from the cache: {converted}\n"
    ) in rows[2]
    with closing(sqlite3.connect(home / "data" / "conversions.sqlite")) as cache:
        assert cache.execute("SELECT count(*) FROM conversions").fetchone() == (converted,)


def test_a_damaged_cache_is_replaced_and_every_step_runs_exit_0(
    tmp_path: Path, worklog: Path, monkeypatch: MonkeyPatch
) -> None:
    """Plan 039, criterion 8: the mirror converts all again, reusing nothing, said once."""
    settings = chosen_settings(tmp_path, worklog)
    monkeypatch.setattr(http, "client", lambda *_: RefreshSite().client())
    steps = [
        Atlassian(Targets(["MFS"], [], CAP, since=FIRST - WEEK)),
        Worklog(worklog, archives=True),
    ]
    first = sync(context(settings, FIRST), steps).steps[1].result
    assert isinstance(first, mirror_app.Outcome)
    settings.conversions.write_bytes(hashlib.shake_256(b"cache").digest(8192))
    with capture_logs() as logged:
        synced = sync(context(settings, FIRST), steps)
    assert synced.exit_status == ExitStatus.OK
    assert [(row.step, row.outcome) for row in synced.steps] == [
        ("download", "done"),
        ("mirror", "done"),
        ("worklog", "done"),
    ]
    mirrored = synced.steps[1].result
    assert isinstance(mirrored, mirror_app.Outcome)
    assert (mirrored.converted, mirrored.reused) == (first.converted, 0)
    replaced = logged_as(logged, "mirror.cache_replaced")
    assert [each["reason"] for each in replaced] == ["SQLITE_NOTADB"]


def test_other_arguments_for_pandoc_convert_the_mirror_again(
    tmp_path: Path, worklog: Path, monkeypatch: MonkeyPatch
) -> None:
    """Review of 039: sync keeps the conversions of the arguments that pandoc is given.

    A second sync gives pandoc one argument more, `--columns=72`.
    """
    settings = chosen_settings(tmp_path, worklog)
    monkeypatch.setattr(http, "client", lambda *_: RefreshSite().client())
    steps = [Atlassian(Targets(["MFS"], [], CAP, since=FIRST - WEEK))]
    first = sync(context(settings, FIRST), steps).steps[1].result
    assert isinstance(first, mirror_app.Outcome)
    more = (*pandoc_adapter.ARGUMENTS, "--columns=72")
    monkeypatch.setattr(pandoc_adapter, "ARGUMENTS", more)
    again = sync(context(settings, FIRST), steps).steps[1].result
    assert isinstance(again, mirror_app.Outcome)
    assert (again.converted, again.reused) == (first.converted, 0)
    assert first.converted > 0


def test_the_text_of_a_full_sync_gives_each_command_s_counts_under_its_row(
    home: Path, worklog: Path, signed_in: FakeSite, capsys: CaptureFixture[str]
) -> None:
    """Download's counts, as download writes them, indented under its row."""
    config = settings_file(home, worklog, atlassian=True)
    assert main(command(home, config, "--yes", "--since", "2026-10-02")) == ExitStatus.FAILED
    out = capsys.readouterr().out
    assert out.startswith("download: failed\n  confluence blogposts: fetched: 1\n")
    assert "  failures: 1\nmirror: done\n  documents: " in out
    assert signed_in.asked


def test_with_the_work_log_alone_the_index_still_holds_every_page(
    home: Path, worklog: Path, signed_in: FakeSite, capsys: CaptureFixture[str]
) -> None:
    """--include worklog refreshes the work log alone; the index, from the whole mirror."""
    config = settings_file(home, worklog, atlassian=True)
    main(command(home, config, "--yes", "--since", "2026-10-02", "--format", "json"))
    first = json.loads(capsys.readouterr().out)["steps"][-1]["result"]["report"]["types"]
    assert {"page", "blogpost", "issue"} <= set(first)
    signed_in.asked.clear()
    given = ("--yes", "--include", "worklog", "--format", "json")
    assert main(command(home, config, *given)) == ExitStatus.OK
    rows = json.loads(capsys.readouterr().out)["steps"]
    assert [(row["step"], row["outcome"]) for row in rows] == [
        ("worklog", "done"),
        ("index", "done"),
    ]
    assert rows[-1]["result"]["report"]["types"] == first
    assert not signed_in.asked


def test_an_endpoint_elsewhere_is_refused_before_any_step(
    home: Path,
    worklog: Path,
    signed_in: FakeSite,
    monkeypatch: MonkeyPatch,
    capsys: CaptureFixture[str],
) -> None:
    """By meaning, an endpoint off this machine without --allow-remote-embeddings: exit 2."""
    monkeypatch.setenv("ATLASSIAN_OFFLINE_MCP_SEARCH_MODE", "hybrid")
    config = settings_file(home, worklog, atlassian=True)
    remote = 'embedding_url = "https://embeddings.example/v1"\n'
    config.write_text(remote + config.read_text("utf-8"), "utf-8")
    assert main(command(home, config, "--yes", "--since", "2026-10-02")) == ExitStatus.REFUSED
    assert "embedding_url: not an address of this machine" in capsys.readouterr().err
    assert not signed_in.asked
    assert not (home / "data" / "docs").exists()


@pytest.mark.parametrize(
    ("given", "mode", "said"),
    [
        ((), "lexical", None),
        (("--allow-remote-embeddings",), "hybrid", None),
        (("--dry-run",), "hybrid", None),
        ((), "hybrid", "embedding_url: not an address of this machine"),
    ],
)
def test_an_endpoint_elsewhere_is_refused_only_where_the_index_would_call_it(
    given: tuple[str, ...], mode: str, said: str | None
) -> None:
    """By words alone, with the run's word, or in a dry run, which builds no index: not refused."""
    fault = refused(arguments(*given), CONFIGURED | {"search_mode": mode})
    assert fault is None if said is None else fault is not None and said in fault


def test_an_index_not_built_fails_its_row_and_keeps_the_others(
    home: Path, worklog: Path, monkeypatch: MonkeyPatch, capsys: CaptureFixture[str]
) -> None:
    """The endpoint lacks the model: the work log done, the index failed, exit 1, said."""
    monkeypatch.setenv("ATLASSIAN_OFFLINE_MCP_SEARCH_MODE", "hybrid")
    config = settings_file(home, worklog)
    with serving(Scripted(models={})) as url:
        monkeypatch.setenv("ATLASSIAN_OFFLINE_MCP_EMBEDDING_URL", url)
        status = main(command(home, config, "--yes", "--format", "json"))
    rows = json.loads(capsys.readouterr().out)["steps"]
    assert status == ExitStatus.FAILED
    assert [(row["step"], row["outcome"]) for row in rows] == [
        ("worklog", "done"),
        ("index", "failed"),
    ]
    assert rows[-1]["result"] is None
    assert [line["level"] for line in logged_in_files(home, "index.not_built")] == ["error"]


def test_the_index_s_settings_are_said_not_applied_by_words_alone_and_in_a_dry_run(
    home: Path, worklog: Path, capsys: CaptureFixture[str]
) -> None:
    """The lexical mode embeds nothing; a dry run builds no index at all."""
    config = settings_file(home, worklog)
    assert main(command(home, config, "--yes")) == ExitStatus.OK
    said = capsys.readouterr().err
    assert "model: " in said
    assert said.count("(not applied: the lexical mode embeds nothing)") == len(
        ["model", "embedding_url", "embedding_api_key", "chunking"]
    )
    assert main(command(home, config, "--dry-run")) == ExitStatus.OK
    said = capsys.readouterr().err
    assert "search_mode: lexical" in said
    assert said.count("(not applied: a dry run builds no index)") == len(
        ["model", "search_mode", "chunking", "embedding_url", "embedding_api_key"]
    )


def interrupting(*_: object) -> None:
    """Stop a step as Ctrl-C would."""
    raise KeyboardInterrupt


def test_ctrl_c_in_the_mirror_marks_it_interrupted_and_the_work_log_not_run(
    tmp_path: Path, worklog: Path, monkeypatch: MonkeyPatch
) -> None:
    """The download done, the mirror interrupted, the work log not run: exit 130."""
    monkeypatch.setattr(sync_app, "download", lambda *_: Outcome(Report(), [], ExitStatus.OK))
    monkeypatch.setattr(sync_app, "mirror", interrupting)
    settings = chosen_settings(tmp_path, worklog)
    steps = [
        Atlassian(Targets(["MFS"], [], CAP, since=FIRST - WEEK)),
        Worklog(worklog, archives=True),
    ]
    with capture_logs() as logged:
        synced = sync(context(settings, FIRST), steps)
    assert [(row.step, row.outcome) for row in synced.steps] == [
        ("download", "done"),
        ("mirror", "interrupted"),
        ("worklog", "not run"),
    ]
    assert synced.exit_status == ExitStatus.INTERRUPTED
    assert [each["step"] for each in logged_as(logged, "sync.interrupted")] == ["mirror"]


def test_ctrl_c_once_every_step_ended_still_exits_130(
    tmp_path: Path, worklog: Path, monkeypatch: MonkeyPatch
) -> None:
    """Every row kept as it ended, and the run interrupted."""

    def ended_then_stopped(_context: Context, _step: Worklog, add: Callable[[Row], None]) -> None:
        add(Row("worklog", "done", None))
        raise KeyboardInterrupt

    monkeypatch.setattr(sync_app, "worklog", ended_then_stopped)
    settings = chosen_settings(tmp_path, worklog)
    synced = sync(context(settings, FIRST), [Worklog(worklog, archives=True)])
    assert [(row.step, row.outcome) for row in synced.steps] == [("worklog", "done")]
    assert synced.exit_status == ExitStatus.INTERRUPTED


def test_to_sign_in_again_ranks_above_a_failure_and_below_an_interruption(
    tmp_path: Path, worklog: Path, monkeypatch: MonkeyPatch
) -> None:
    """No session saved and a mirror problem exit 3; Ctrl-C after them exits 130."""
    problem = mirror_app.Problem("confluence/pages/1001/000001", "pandoc: exit status 9")
    monkeypatch.setattr(
        sync_app,
        "mirror",
        lambda *_: mirror_app.Outcome(0, 0, 0, Changes(0, 0, 0), Counter(), (problem,)),
    )
    settings = Settings(data_dir=tmp_path / "data", site=SITE)
    atlassian = Atlassian(Targets(["MFS"], [], CAP, since=FIRST - WEEK))
    synced = sync(context(settings, FIRST), [atlassian, Worklog(worklog, archives=True)])
    assert [row.outcome for row in synced.steps] == ["sign in", "failed", "done"]
    assert synced.exit_status == ExitStatus.SIGN_IN_AGAIN
    monkeypatch.setattr(sync_app, "worklog", interrupting)
    synced = sync(context(settings, FIRST), [atlassian, Worklog(worklog, archives=True)])
    assert [row.outcome for row in synced.steps] == ["sign in", "failed", "interrupted"]
    assert synced.exit_status == ExitStatus.INTERRUPTED


def test_an_included_source_without_its_table_is_refused_beside_one_that_has_it(
    home: Path, capsys: CaptureFixture[str]
) -> None:
    """--include confluence --include worklog, no work log: exit 2, naming its setting."""
    config = settings_file(home, None, atlassian=True)
    given = ("--yes", "--include", "confluence", "--include", "worklog")
    assert main(command(home, config, *given)) == ExitStatus.REFUSED
    said = capsys.readouterr().err
    assert "run.refused" in said
    assert "--include worklog: not configured; set sources.worklog.path" in said


def test_with_a_site_source_an_email_without_a_token_alone_is_not_applied(
    home: Path, signed_in: FakeSite, monkeypatch: MonkeyPatch, capsys: CaptureFixture[str]
) -> None:
    """The site is used; the email, without its token, signs nothing in."""
    monkeypatch.setenv("ATLASSIAN_OFFLINE_MCP_EMAIL", "someone@example.invalid")
    config = settings_file(home, None, atlassian=True)
    assert main(command(home, config, "--dry-run", "--since", "2026-10-02")) == ExitStatus.OK
    said = capsys.readouterr().err
    assert "no Atlassian source" not in said
    assert "email: someone@example.invalid (not applied: without an API token" in said
    assert signed_in.asked


def test_without_a_site_source_the_sign_in_s_settings_are_not_applied(
    home: Path, worklog: Path, monkeypatch: MonkeyPatch, capsys: CaptureFixture[str]
) -> None:
    """The email and the token, given, are said ignored, by their variables."""
    monkeypatch.setenv("ATLASSIAN_OFFLINE_MCP_EMAIL", "someone@example.invalid")
    monkeypatch.setenv("ATLASSIAN_OFFLINE_MCP_API_TOKEN", "token-sentinel-7f2b")
    config = settings_file(home, worklog)
    assert main(command(home, config, "--dry-run")) == ExitStatus.OK
    said = capsys.readouterr().err
    for setting, variable in (
        ("email", "ATLASSIAN_OFFLINE_MCP_EMAIL"),
        ("api_token", "ATLASSIAN_OFFLINE_MCP_API_TOKEN"),
    ):
        assert f"ignored: {setting} ({variable}): no Atlassian source in this sync\n" in said
    assert "token-sentinel-7f2b" not in said


def test_a_busy_raw_store_fails_the_download_and_the_next_steps_run(
    tmp_path: Path, worklog: Path, monkeypatch: MonkeyPatch
) -> None:
    """Another run writing the store: the download failed, said; mirror and work log run."""

    def busy(*_: object) -> Outcome:
        raise StoreBusyError

    monkeypatch.setattr(sync_app, "download", busy)
    settings = chosen_settings(tmp_path, worklog)
    steps = [
        Atlassian(Targets(["MFS"], [], CAP, since=FIRST - WEEK)),
        Worklog(worklog, archives=True),
    ]
    with capture_logs() as logged:
        synced = sync(context(settings, FIRST), steps)
    assert [(row.step, row.outcome) for row in synced.steps] == [
        ("download", "failed"),
        ("mirror", "done"),
        ("worklog", "done"),
    ]
    assert synced.exit_status == ExitStatus.FAILED
    assert logged_as(logged, "download.store_busy")


# The commands whose steps sync runs: what their pages list, and sync's does not, is
# theirs, and sync records it as they do.
STEP_PAGES = ("download", "mirror", "index")


@pytest.mark.usefixtures("signed_in")
@pytest.mark.parametrize("mode", ["lexical", None], ids=["words alone", "the defaults"])
def test_what_sync_records_is_what_its_page_says(
    home: Path, worklog: Path, telemetry: InMemory, monkeypatch: MonkeyPatch, mode: str | None
) -> None:
    """Runs that between them record each event, span and instrument of sync's page.

    A full run, a dry run, one interrupted, one refused, one without pandoc, one meeting
    a problem and two transcripts of one id, one whose pandoc gives no version. What a
    step's page lists, and sync's does not, is the step's: each such event is recorded
    with listed fields alone, and is left out of sync's, as are the step's spans and
    instruments. No line of the log files holds a document's text. Under the defaults,
    hybrid search over windows, the index embeds by the scripted endpoint, which serves
    the default model; by words alone, it does not. Either way, the index is built.
    """
    if mode is None:
        monkeypatch.delenv("ATLASSIAN_OFFLINE_MCP_SEARCH_MODE")
    config = settings_file(home, worklog, atlassian=True)
    period = ("--since", "2026-10-02")
    emitted = Emitted()
    with serving(Scripted(models={DEFAULT_MODEL: DIGEST})) as url:
        monkeypatch.setenv("ATLASSIAN_OFFLINE_MCP_EMBEDDING_URL", url)
        with emitted.gathering(telemetry, "sync"):
            assert main(command(home, config, "--yes", "-vv", *period)) == ExitStatus.FAILED
        with emitted.gathering(telemetry, "sync"):
            assert main(command(home, config, "--dry-run", *period)) == ExitStatus.OK
        shutil.copytree(worklog / "transcripts/current", worklog / "transcripts/archive/2026/x")
        (worklog / "transcripts/misc/a.org").write_bytes(b"* Caf\xe9\n")
        with emitted.gathering(telemetry, "sync"):
            assert main(command(home, config, "--yes", "--include", "worklog")) == ExitStatus.FAILED
        with monkeypatch.context() as patch:
            patch.setattr(sync_app, "download", interrupting)
            with emitted.gathering(telemetry, "sync"):
                assert main(command(home, config, "--yes", *period)) == ExitStatus.INTERRUPTED
        with monkeypatch.context() as patch:
            patch.setattr(Pandoc, "org_converter", lambda _: unconverted())
            with emitted.gathering(telemetry, "sync"):
                assert main(command(home, config, "--yes", "--include", "worklog")) == 1
        with monkeypatch.context() as patch:
            patch.setattr(Pandoc, "find", missing)
            with emitted.gathering(telemetry, "sync"):
                assert main(command(home, config, "--yes", "--include", "worklog")) == 1
        absent = settings_file(home, home / "absent")
        with emitted.gathering(telemetry, "sync"):
            assert main(command(home, absent, "--yes")) == ExitStatus.REFUSED
    assert (
        any(span.name == f"embeddings {DEFAULT_MODEL}" for span in emitted.spans),
        "index.not_built" in emitted.events,
    ) == (mode is None, False)
    mine, steps = documented("sync"), [documented(page) for page in STEP_PAGES]
    theirs = {
        name: fields
        for page in steps
        for name, fields in page.events.items()
        if name not in mine.events
    }
    unlisted = {
        name: sorted(recorded - theirs[name])
        for name, recorded in emitted.events.items()
        if name in theirs and recorded - theirs[name]
    }
    assert unlisted == {}, "a step's event with fields its page does not list"
    spans = [
        pattern(name, "sync") for page in steps for name in page.spans if name not in mine.spans
    ]
    instruments = {name for page in steps for name in page.instruments} - set(mine.instruments)
    own = Emitted()
    for name, fields in emitted.events.items():
        if name not in theirs:
            own.events[name] |= fields
    own.logged = [each for each in emitted.logged if each[0] not in theirs]
    own.records = [each for each in emitted.records if each[0] not in theirs]
    own.spans = [
        each for each in emitted.spans if not any(listed.fullmatch(each.name) for listed in spans)
    ]
    own.instruments.update(
        (name, value) for name, value in emitted.instruments.items() if name not in instruments
    )
    assert undocumented("sync", own) == []
    logs = "".join(path.read_text("utf-8") for path in home.rglob("sync-*.jsonl"))
    assert '"event": "worklog.document"' in logs  # the files hold DEBUG, titles too
    assert "Nothing dated here yet" in (worklog / "todo.org").read_text("utf-8")
    assert all(text not in logs for text in ("zanzibarite", "PWNED", "Nothing dated here yet"))


def unconverted() -> str:
    """Fail as pandoc does when it gives no version."""
    message = "pandoc: exit status 9"
    raise PandocFailedError(message)


def missing() -> Pandoc:
    """Fail as when pandoc went from PATH once the run began."""
    message = "pandoc: not found on PATH"
    raise PandocMissingError(message)


def by_kind_and_outcome(measured: dict[str, Metric]) -> dict[tuple[object, object], object]:
    """Give the work log's documents counted, by kind and outcome."""
    return {
        (point.attributes["aom.kind"], point.attributes["aom.outcome"]): point.value
        for point in measured["aom.mirror.documents"].data.data_points
        if point.attributes and "aom.kind" in point.attributes
    }


def test_the_work_log_is_counted_by_kind_and_its_spans_are_in_its_row(
    home: Path, worklog: Path, telemetry: InMemory
) -> None:
    """Each document counted by kind and outcome, each work-log span in the row's step.

    Fresh, every entry, day, meeting and transcript is mirrored, each conversion timed by
    kind; unchanged, all are kept and none timed. Each work-log span is in the row's
    ``sync.step``, which names the step and its outcome, in the run's root; each
    document's event is logged in ``worklog.convert``.
    """
    config = settings_file(home, worklog)
    assert main(command(home, config, "--yes")) == ExitStatus.OK
    first, spans = telemetry.measured(), telemetry.spans.get_finished_spans()
    assert main(command(home, config, "--yes")) == ExitStatus.OK
    second = telemetry.measured()
    assert by_kind_and_outcome(first) == {
        (kind, "mirrored"): count for kind, count in WORKLOG_KINDS.items()
    }
    assert by_kind_and_outcome(second) == {
        (kind, "kept"): count for kind, count in WORKLOG_KINDS.items()
    }
    timed = first["aom.mirror.conversion.duration"].data.data_points
    assert {point.attributes["aom.kind"]: point.count for point in timed} == WORKLOG_KINDS
    assert "aom.mirror.conversion.duration" not in second
    rows = {span.attributes["aom.step"]: span for span in spans if span.name == "sync.step"}
    assert list(rows) == ["worklog", "index"]
    row = rows["worklog"]
    assert row.attributes["aom.outcome"] == "done"
    (root,) = [span for span in spans if span.name == "sync"]
    assert row.parent is not None
    assert row.parent.span_id == root.context.span_id
    worklog_spans = {span.name: span for span in spans if span.name.startswith("worklog.")}
    assert set(worklog_spans) == {"worklog.read", "worklog.convert", "worklog.write"}
    assert all(
        span.parent is not None and span.parent.span_id == row.context.span_id
        for span in worklog_spans.values()
    )
    emitted = Emitted()
    with emitted.gathering(telemetry, "sync"):
        assert main(command(home, config, "--yes", "-vv")) == ExitStatus.OK
    (converting,) = [span.span_id for span in emitted.spans if span.name == "worklog.convert"]
    documents = [each for each in emitted.logged if each[0] == "worklog.document"]
    assert len(documents) == WORKLOG_DOCUMENTS
    assert {span for _, _, _, span, _ in documents} == {converting}


def ended_with(logged: list[dict[str, object]], *fields: str) -> tuple[object, ...]:
    """Give the values of these fields of the one ``worklog.end`` logged."""
    (ended,) = logged_as(logged, "worklog.end")
    return tuple(ended[field] for field in fields)


def test_the_work_log_s_events_say_what_was_read_written_and_would_be(
    tmp_path: Path, worklog: Path
) -> None:
    """``worklog.read``, ``worklog.document`` and ``worklog.end``, by their values.

    Fresh, thirteen entries, two days, eight meetings, six transcripts and one HTML
    transcript read, none unread; each document mirrored, by its kind and path; a file
    each written. Unchanged, each kept and none written. A dry run says each to convert
    on an empty mirror, none after a run, and one file to remove once a transcript is
    deleted.
    """
    settings, step = chosen_settings(tmp_path, worklog), Worklog(worklog, archives=True)
    dry = Context(settings, Pandoc.find(), lambda: FIRST, lambda _: None, dry_run=True)
    with capture_logs() as planned:
        sync(dry, [step])
    with capture_logs() as fresh:
        sync(context(settings, FIRST), [step])
    with capture_logs() as unchanged:
        sync(context(settings, FIRST), [step])
    (worklog / "transcripts/misc/a.org").unlink()
    with capture_logs() as planned_again:
        sync(dry, [step])
    (read,) = logged_as(fresh, "worklog.read")
    counts = ("entries", "days", "meetings", "transcripts", "html", "problems")
    assert tuple(read[each] for each in counts) == (13, 2, 8, 6, 1, 0)
    documents = logged_as(fresh, "worklog.document")
    assert Counter(each["kind"] for each in documents) == WORKLOG_KINDS
    assert {each["outcome"] for each in documents} == {"mirrored"}
    folders = {
        "entry": "worklog/entries/",
        "day": "worklog/days/",
        "meeting": "worklog/meetings/",
        "transcript": "worklog/transcripts/",
    }
    assert all(str(each["path"]).startswith(folders[str(each["kind"])]) for each in documents)
    fields = ("documents", "written", "unchanged", "removed", "problems")
    every = WORKLOG_DOCUMENTS
    assert ended_with(fresh, *fields) == (every, every, 0, 0, 0)
    assert ended_with(unchanged, *fields) == (every, 0, every, 0, 0)
    kept = {each["outcome"] for each in logged_as(unchanged, "worklog.document")}
    assert kept == {"kept"}
    assert ended_with(planned, "to_convert", "to_remove", "problems") == (every, 0, 0)
    assert ended_with(planned_again, "to_convert", "to_remove", "problems") == (0, 1, 0)
