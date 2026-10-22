"""``sync`` as plan 017 defines it: the sources it takes, what it says, its steps, its status.

The expectations come from the plan's "What sync does" and "Choosing sources", and its
criteria 3 to 6, 11 and 12. The Atlassian sources are served by plan 004's scripted site,
the work log is the invented fixture; each test has a scratch home, and terminals are
injected or ``--yes`` given.
"""

from __future__ import annotations

import json
import shutil
import time
from collections import Counter
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from atlassian_offline_mcp.cli.app import sync as sync_app
from atlassian_offline_mcp.cli.app.sync import Atlassian, Context, Row, Worklog, sync
from atlassian_offline_mcp.cli.domain.sync import SOURCES, chosen
from atlassian_offline_mcp.cli.main import main, parser
from atlassian_offline_mcp.config.domain.settings import Settings
from atlassian_offline_mcp.kernel.content import SOURCE_NAMES
from atlassian_offline_mcp.kernel.exit_status import ExitStatus
from atlassian_offline_mcp.mirror.adapters.mirror_files import Changes
from atlassian_offline_mcp.mirror.adapters.pandoc import Pandoc
from atlassian_offline_mcp.mirror.app import mirror as mirror_app
from atlassian_offline_mcp.sources.atlassian.adapters import http
from atlassian_offline_mcp.sources.atlassian.adapters.raw_store import StoreBusyError
from atlassian_offline_mcp.sources.atlassian.adapters.session_file import COOKIES, write_cookies
from atlassian_offline_mcp.sources.atlassian.app.download import Outcome, Report, Targets
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

# Each setting that chooses a source, as the declaration's functions take them.
CONFIGURED = {
    "site": SITE,
    "email": None,
    "api_token": None,
    "sources.confluence.spaces": ("MFS",),
    "sources.jira.projects": ("PRB",),
    "sources.worklog.path": Path("/work/todo"),
    "sources.worklog.archives": True,
}
ALL = ["confluence", "jira", "worklog"]
# The work log's documents in the fixture: twelve entries and four transcripts.
WORKLOG_DOCUMENTS = 16


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
    home: Path, worklog: Path, capsys: CaptureFixture[str]
) -> None:
    """--since given, ignored by the work log, said; no other option; nothing written."""
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
    """exit_status, then download, mirror and the work log, each with its own result."""
    config = settings_file(home, worklog, atlassian=True)
    given = ("--yes", "--since", "2026-10-02", "--format", "json")
    status = main(command(home, config, *given))
    document = json.loads(capsys.readouterr().out)
    assert document["exit_status"] == status == ExitStatus.FAILED  # one file fails
    assert [(row["step"], row["outcome"]) for row in document["steps"]] == [
        ("download", "failed"),
        ("mirror", "done"),
        ("worklog", "done"),
    ]
    assert document["steps"][2]["result"]["documents"] == WORKLOG_DOCUMENTS
    assert signed_in.asked


def test_a_space_never_covered_exits_2_by_name_before_any_get(
    home: Path, signed_in: FakeSite, capsys: CaptureFixture[str]
) -> None:
    """Without --since, a target with nowhere to start: refused before the first step."""
    config = settings_file(home, None, atlassian=True)
    assert main(command(home, config, "--yes", "--include", "confluence")) == ExitStatus.REFUSED
    assert "refused: space MFS: nothing covered yet" in capsys.readouterr().err
    assert signed_in.asked == []


def context(
    settings: Settings, said: list[str], now: datetime, pandoc: Pandoc | None = None
) -> Context:
    """Give a sync's context at ``now``, saying into ``said``."""
    return Context(
        settings, pandoc or Pandoc.find(), lambda: now, lambda _: None, said.append, dry_run=False
    )


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
    said: list[str] = []
    assert sync(context(settings, said, FIRST), [first]).exit_status == ExitStatus.OK
    assert "1003" not in stored_pages(settings)
    edited = {"number": 4, "createdAt": "2026-10-23T08:00:00.000Z"}
    later = RefreshSite(listing={**PAGES, "1003": {**PAGES["1003"], "version": edited}})
    monkeypatch.setattr(http, "client", lambda *_: later.client())
    synced = sync(context(settings, said, SECOND), [Atlassian(Targets(["MFS"], [], CAP))])
    assert synced.exit_status == ExitStatus.OK
    fetched = synced.steps[0].result
    assert isinstance(fetched, Outcome)
    assert fetched.report.counts["confluence pages: fetched"] == 1
    assert stored_pages(settings)["1003"] == "000004"


def test_the_site_asking_to_sign_in_still_lets_the_work_log_run_exit_3(
    tmp_path: Path, worklog: Path
) -> None:
    """No session saved: the download says to sign in, the mirror and the work log run."""
    settings = Settings(data_dir=tmp_path / "data", site=SITE)
    steps = [
        Atlassian(Targets(["MFS"], [], CAP, since=FIRST - WEEK)),
        Worklog(worklog, archives=True),
    ]
    said: list[str] = []
    synced = sync(context(settings, said, FIRST), steps)
    assert [(row.step, row.outcome) for row in synced.steps] == [
        ("download", "sign in"),
        ("mirror", "done"),
        ("worklog", "done"),
    ]
    assert synced.exit_status == ExitStatus.SIGN_IN_AGAIN
    assert any(line.startswith("sign-in needed: ") for line in said)
    assert len(list((settings.docs / "worklog").rglob("*.md"))) == WORKLOG_DOCUMENTS


def test_ctrl_c_in_the_download_exits_130_and_no_later_step_runs(
    tmp_path: Path, worklog: Path, monkeypatch: MonkeyPatch
) -> None:
    """The download interrupted, the mirror and the work log not run."""

    def interrupted(*_: object) -> Outcome:
        raise KeyboardInterrupt

    monkeypatch.setattr(sync_app, "download", interrupted)
    settings = chosen_settings(tmp_path, worklog)
    steps = [
        Atlassian(Targets(["MFS"], [], CAP, since=FIRST - WEEK)),
        Worklog(worklog, archives=True),
    ]
    synced = sync(context(settings, [], FIRST), steps)
    assert [(row.step, row.outcome) for row in synced.steps] == [
        ("download", "interrupted"),
        ("mirror", "not run"),
        ("worklog", "not run"),
    ]
    assert synced.exit_status == ExitStatus.INTERRUPTED
    assert not settings.docs.exists()


def test_a_mirror_problem_exits_1_with_the_work_log_mirrored(
    tmp_path: Path, worklog: Path, monkeypatch: MonkeyPatch
) -> None:
    """The mirror fails, said by place; the work log still runs."""
    problem = mirror_app.Problem("confluence/pages/1001/000001", "pandoc: exit status 9")
    monkeypatch.setattr(sync_app, "download", lambda *_: Outcome(Report(), [], ExitStatus.OK))
    monkeypatch.setattr(
        sync_app,
        "mirror",
        lambda *_: mirror_app.Outcome(0, Changes(0, 0, 0), Counter(), (problem,)),
    )
    settings = chosen_settings(tmp_path, worklog)
    steps = [
        Atlassian(Targets(["MFS"], [], CAP, since=FIRST - WEEK)),
        Worklog(worklog, archives=True),
    ]
    said: list[str] = []
    synced = sync(context(settings, said, FIRST), steps)
    assert [(row.step, row.outcome) for row in synced.steps] == [
        ("download", "done"),
        ("mirror", "failed"),
        ("worklog", "done"),
    ]
    assert synced.exit_status == ExitStatus.FAILED
    assert f"not mirrored: {problem.where}: {problem.reason}\n" in said
    assert len(list((settings.docs / "worklog").rglob("*.md"))) == WORKLOG_DOCUMENTS


def test_a_work_log_that_is_not_a_folder_is_refused_before_any_step(
    home: Path, tmp_path: Path, capsys: CaptureFixture[str]
) -> None:
    """Named by its setting; nothing is written."""
    config = settings_file(home, tmp_path / "absent")
    assert main(command(home, config, "--yes")) == ExitStatus.REFUSED
    assert "refused: sources.worklog.path: not a folder" in capsys.readouterr().err
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
    tmp_path: Path, worklog: Path
) -> None:
    """Until the next clean run; standard error says that nothing was removed."""
    settings = chosen_settings(tmp_path, worklog)
    step = Worklog(worklog, archives=True)
    said: list[str] = []
    sync(context(settings, said, FIRST), [step])
    gone = next((settings.docs / "worklog/transcripts").glob("*waiting-notes.md"))
    (worklog / "transcripts/misc/a.org").unlink()
    todo = worklog / "todo.org"
    todo.write_text(todo.read_text("utf-8").replace("Drafted on", "Drafted, failing, on"), "utf-8")
    failing = Counting(Pandoc.find().path, failing="failing")
    synced = sync(context(settings, said, FIRST, failing), [step])
    assert (synced.steps[0].outcome, synced.exit_status) == ("failed", ExitStatus.FAILED)
    assert "no work-log file was removed, since something was not mirrored\n" in said
    assert gone.exists()
    todo.write_text(todo.read_text("utf-8").replace("Drafted, failing, on", "Drafted on"), "utf-8")
    assert sync(context(settings, said, FIRST), [step]).exit_status == ExitStatus.OK
    assert not gone.exists()


def test_the_text_gives_a_row_per_step_then_its_counts(
    home: Path, worklog: Path, capsys: CaptureFixture[str]
) -> None:
    """The work log's: documents, files, HTML left out, problems; a dry run's to convert."""
    config = settings_file(home, worklog)
    assert main(command(home, config, "--dry-run")) == 0
    assert capsys.readouterr().out == (
        "worklog: done\n"
        f"  documents: {WORKLOG_DOCUMENTS}\n"
        f"  to convert: {WORKLOG_DOCUMENTS}\n"
        "  files to remove: 0\n"
        "  HTML left out: 1\n"
        "  problems: 0\n"
    )
    assert main(command(home, config, "--yes")) == 0
    assert capsys.readouterr().out == (
        "worklog: done\n"
        f"  documents: {WORKLOG_DOCUMENTS}\n"
        f"  files written: {WORKLOG_DOCUMENTS}\n"
        "  files unchanged: 0\n"
        "  files removed: 0\n"
        "  HTML left out: 1\n"
        "  problems: 0\n"
    )


def test_the_sources_are_the_names_that_the_options_offer() -> None:
    """--include and --exclude offer the kernel's names; sync's records bear the same."""
    assert tuple(source.name for source in SOURCES) == SOURCE_NAMES


def test_a_dry_run_of_the_site_plans_and_writes_nothing(
    home: Path, signed_in: FakeSite, capsys: CaptureFixture[str]
) -> None:
    """The download planned, the mirror not run; the data folder holds the session alone."""
    config = settings_file(home, None, atlassian=True)
    given = ("--dry-run", "--since", "2026-10-02", "--format", "json")
    assert main(command(home, config, *given)) == ExitStatus.OK
    rows = json.loads(capsys.readouterr().out)["steps"]
    assert [(row["step"], row["outcome"]) for row in rows] == [
        ("download", "done"),
        ("mirror", "not run"),
    ]
    assert "confluence pages: to fetch" in rows[0]["result"]["report"]["counts"]
    assert sorted(path.name for path in (home / "data").iterdir()) == ["session"]
    assert signed_in.asked


@pytest.mark.parametrize(
    "case",
    [
        (("--exclude", "worklog"), ["download", "mirror"], True),
        (("--exclude", "confluence"), ["download", "mirror", "worklog"], False),
        (("--include", "worklog"), ["worklog"], False),
    ],
)
def test_the_sources_chosen_are_the_steps_run(
    home: Path,
    worklog: Path,
    signed_in: FakeSite,
    capsys: CaptureFixture[str],
    case: tuple[tuple[str, ...], list[str], bool],
) -> None:
    """Excluded or not included: no step, no request, no file of it."""
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
    """The archive file's entry, the ARCHIVE entry and the archived transcript: 13 left."""
    config = settings_file(home, worklog)
    config.write_text(config.read_text("utf-8") + "archives = false\n", "utf-8")
    assert main(command(home, config, "--yes", "--format", "json")) == 0
    result = json.loads(capsys.readouterr().out)["steps"][0]["result"]
    assert result["documents"] == WORKLOG_DOCUMENTS - len(["vendor", "old incident", "1.org"])
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
    said: list[str] = []
    synced = sync(context(settings, said, FIRST), steps)
    assert [(row.step, row.outcome) for row in synced.steps] == [
        ("download", "done"),
        ("mirror", "interrupted"),
        ("worklog", "not run"),
    ]
    assert synced.exit_status == ExitStatus.INTERRUPTED
    assert "interrupted; no later step runs\n" in said


def test_ctrl_c_once_every_step_ended_still_exits_130(
    tmp_path: Path, worklog: Path, monkeypatch: MonkeyPatch
) -> None:
    """Every row kept as it ended, and the run interrupted."""

    def ended_then_stopped(_context: Context, _step: Worklog, add: Callable[[Row], None]) -> None:
        add(Row("worklog", "done", None))
        raise KeyboardInterrupt

    monkeypatch.setattr(sync_app, "worklog", ended_then_stopped)
    settings = chosen_settings(tmp_path, worklog)
    synced = sync(context(settings, [], FIRST), [Worklog(worklog, archives=True)])
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
        lambda *_: mirror_app.Outcome(0, Changes(0, 0, 0), Counter(), (problem,)),
    )
    settings = Settings(data_dir=tmp_path / "data", site=SITE)
    atlassian = Atlassian(Targets(["MFS"], [], CAP, since=FIRST - WEEK))
    synced = sync(context(settings, [], FIRST), [atlassian, Worklog(worklog, archives=True)])
    assert [row.outcome for row in synced.steps] == ["sign in", "failed", "done"]
    assert synced.exit_status == ExitStatus.SIGN_IN_AGAIN
    monkeypatch.setattr(sync_app, "worklog", interrupting)
    synced = sync(context(settings, [], FIRST), [atlassian, Worklog(worklog, archives=True)])
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
    assert "refused: --include worklog: not configured; set sources.worklog.path\n" in said


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
    said: list[str] = []
    synced = sync(context(settings, said, FIRST), steps)
    assert [(row.step, row.outcome) for row in synced.steps] == [
        ("download", "failed"),
        ("mirror", "done"),
        ("worklog", "done"),
    ]
    assert synced.exit_status == ExitStatus.FAILED
    assert "another run is writing the raw store; try again once it ends\n" in said
