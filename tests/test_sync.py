"""``sync`` as plan 017 defines it: the sources it takes, what it says, its steps, its status.

The expectations come from the plan's "What sync does" and "Choosing sources", and its
criteria 3 to 6, 11 and 12, and from plan 030's "``sync`` through the registry": a row
for each source's fetch, then for each source's prepare, then the index, each with its
role's result, and the sources, their options and light checks the declarations'. The
Atlassian sources are served by plan 004's scripted site, the work log is the invented
fixture; each test has a scratch home, and terminals are injected or ``--yes`` given.
Each test searches by words alone, which need no embedding endpoint, rather than rely on
the default; one whose requirement is meaning, or the defaults, sets or removes the mode
itself.
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
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from pydantic_core import to_json
from structlog.testing import capture_logs

from kb_mcp.cli.app import sync as sync_app
from kb_mcp.cli.app.sync import Index, sync
from kb_mcp.cli.domain.rows import Row
from kb_mcp.cli.domain.sync import chosen, given
from kb_mcp.cli.main import main, parser
from kb_mcp.cli.options.sync import refused
from kb_mcp.config.domain.settings import DEFAULT_MODEL, Settings
from kb_mcp.kernel.exit_status import ExitStatus
from kb_mcp.mirror.adapters import pandoc as pandoc_adapter
from kb_mcp.mirror.adapters.mirror_files import Changes
from kb_mcp.mirror.adapters.pandoc import (
    Pandoc,
    PandocFailedError,
    PandocMissingError,
)
from kb_mcp.search.adapters import sqlite_index, vector_store
from kb_mcp.search.app.indexing import Indexing
from kb_mcp.sources.atlassian.declared import CONFLUENCE
from kb_mcp.sources.atlassian.fetch.adapters import http
from kb_mcp.sources.atlassian.fetch.adapters.raw_store import RawStore, StoreBusyError
from kb_mcp.sources.atlassian.fetch.adapters.session_file import COOKIES, write_cookies
from kb_mcp.sources.atlassian.fetch.app import fetcher
from kb_mcp.sources.atlassian.fetch.app.download import Outcome, Report
from kb_mcp.sources.atlassian.fetch.domain.coverage import Target
from kb_mcp.sources.atlassian.prepare.app import prepare as mirror_app
from kb_mcp.sources.atlassian.prepare.app import preparer
from kb_mcp.sources.registry import SOURCES
from kb_mcp.sources.roles import Run
from kb_mcp.sources.worklog.declared import WORKLOG
from kb_mcp.sources.worklog.prepare.app import preparer as worklog_preparer
from tests.composed import MODEL
from tests.endpoint import DIGEST, Scripted, scripted, serving
from tests.mirrors import fillers
from tests.reference import Emitted, documented, pattern, undocumented
from tests.test_cli import logged_as as logged_in_files
from tests.test_download import PAGES, SITE, FakeSite
from tests.test_question import QUESTION, Terminal
from tests.test_refresh import FIRST, SECOND, WEEK, RefreshSite, stored_pages
from tests.test_worklog_mirror import FIXTURE, Counting, settle, snapshot

if TYPE_CHECKING:
    import argparse
    from collections.abc import Callable, Mapping
    from datetime import datetime

    from _pytest.capture import CaptureFixture
    from _pytest.monkeypatch import MonkeyPatch
    from opentelemetry.sdk.metrics.export import Metric

    from kb_mcp.sources.declaration import Declared
    from tests.conftest import InMemory

# Each setting that chooses a source, as the declaration's functions take them.
CONFIGURED = {
    "accounts.atlassian.site": SITE,
    "accounts.atlassian.email": None,
    "accounts.atlassian.api_token": None,
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
# The period of a fetch that covers what the scripted sites serve: the week before FIRST.
SINCE = {"--since": (FIRST - WEEK).isoformat()}


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
    monkeypatch.setenv("KB_MCP_SEARCH_MODE", "lexical")


def settings_file(home: Path, worklog: Path | None, *, atlassian: bool = False) -> Path:
    """Write a settings file naming the work log, and with ``atlassian``, MFS and PRB."""
    text = ""
    if atlassian:
        text += f'[accounts.atlassian]\nsite = "{SITE}"\n[sources.confluence]\nspaces = ["MFS"]\n'
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
    monkeypatch.delenv("KB_MCP_SEARCH_MODE")
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
    assert captured.out.startswith(f"prepare worklog: done\n  documents: {WORKLOG_DOCUMENTS}\n")


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
    chosen_settings = MODEL(
        accounts={"atlassian": {"site": SITE}}, data_dir=(home / "data").resolve()
    )
    write_cookies(chosen_settings.session / COOKIES, [{"name": "s", "value": "v", "domain": "x"}])
    fake = FakeSite()
    monkeypatch.setattr(http, "client", lambda *_: fake.client())
    return fake


def test_json_is_one_document_with_a_row_per_step(
    home: Path, worklog: Path, signed_in: FakeSite, capsys: CaptureFixture[str]
) -> None:
    """exit_status, then each source's fetch, each source's prepare, then the index.

    Plan 030: the rows run from ``fetch confluence`` to ``prepare worklog``, then
    ``index``, each naming its source, none for the index, the file that fails, a
    page's, failing Confluence's fetch alone. A row's result is its role's: its outcome,
    and what the source's own command gives.
    """
    config = settings_file(home, worklog, atlassian=True)
    given = ("--yes", "--since", "2026-10-02", "--format", "json")
    status = main(command(home, config, *given))
    document = json.loads(capsys.readouterr().out)
    assert document["exit_status"] == status == ExitStatus.FAILED  # one file fails
    assert [(row["step"], row["source"], row["outcome"]) for row in document["steps"]] == [
        ("fetch", "confluence", "failed"),
        ("fetch", "jira", "done"),
        ("prepare", "confluence", "done"),
        ("prepare", "jira", "done"),
        ("prepare", "worklog", "done"),
        ("index", None, "done"),
    ]
    roles = document["steps"][:-1]
    assert [row["result"]["outcome"] for row in roles] == [row["outcome"] for row in roles]
    assert document["steps"][4]["result"]["mirrored"]["documents"] == WORKLOG_DOCUMENTS
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
    assert "source 'confluence': fetch: --until: must come after --since" in err
    assert signed_in.asked == []


def test_a_first_sync_without_since_fetches_the_last_week_of_each_target(
    home: Path, signed_in: FakeSite, capsys: CaptureFixture[str]
) -> None:
    """Nothing covered no longer refuses the run: each target covers the 7 days before it.

    The line before the run states the rule, since the store is not read before then,
    once though both sources taken say it.
    """
    config = settings_file(home, None, atlassian=True)
    assert main(command(home, config, "--yes")) != ExitStatus.REFUSED
    rule = "period: since each target's last fetch; the last 7 days for one never fetched\n"
    assert capsys.readouterr().err.count(rule) == 1
    assert signed_in.asked
    periods = RawStore((home / "data" / "raw").resolve()).coverage().periods
    assert set(periods) == {
        Target(source="confluence", key="MFS"),
        Target(source="jira", key="PRB"),
    }
    assert {each.end - each.start for each in periods.values()} == {WEEK}


def runs(
    settings: Settings,
    now: datetime,
    *declared: Declared,
    options: Mapping[str, object] | None = None,
    dry_run: bool = False,
) -> list[Run]:
    """Give a run of each source, at ``now``, as sync's command builds it from the settings.

    Each source's options are those of ``options`` that it declares, None when not given.
    """
    return [
        Run(
            declared=each,
            settings=settings,
            table=getattr(settings.sources, each.name),
            account=None if each.account is None else getattr(settings.accounts, each.account.name),
            options={flag: (options or {}).get(flag) for flag in each.options},
            now=lambda: now,
            sleep=lambda _: None,
            dry_run=dry_run,
        )
        for each in declared
    ]


def by_words(settings: Settings) -> Index:
    """Give the index's step as sync builds it in the lexical mode: no endpoint."""
    return Index(
        indexing=Indexing(
            docs=settings.docs,
            index=settings.index,
            vectors=settings.vectors,
            evaluation_indexes=settings.evaluation_indexes,
            aliases=settings.aliases,
            model=settings.model,
            chunking=settings.chunking,
            endpoint=None,
        )
    )


def test_the_index_step_prunes_and_a_deferred_prune_leaves_it_done(tmp_path: Path) -> None:
    """Its row holds what the prune did; one that a build in progress defers fails nothing."""
    settings = Settings(data_dir=tmp_path / "data", model="tiny")
    fillers(settings.docs, 3)
    step = Index(
        indexing=Indexing(
            docs=settings.docs,
            index=settings.index,
            vectors=settings.vectors,
            evaluation_indexes=settings.evaluation_indexes,
            aliases=settings.aliases,
            model="tiny",
            chunking="sections",
            endpoint=scripted,
        )
    )
    with vector_store.shared(settings.vectors):
        deferred = sync([], step, lambda: FIRST)
    done = sync([], step, lambda: FIRST)
    rows = [json.loads(to_json(synced))["steps"] for synced in (deferred, done)]
    assert [(row["outcome"], row["result"]["pruned"]["outcome"]) for [row] in rows] == [
        ("done", "deferred"),
        ("done", "pruned"),
    ]


def logged_as(logged: list[dict[str, object]], event: str) -> list[dict[str, object]]:
    """Give each event of this name that ``capture_logs`` held."""
    return [each for each in logged if each["event"] == event]


def chosen_settings(tmp_path: Path, worklog: Path) -> Settings:
    """Give settings with a site, a data folder with a saved session, MFS and the work log."""
    settings = MODEL(
        accounts={"atlassian": {"site": SITE}},
        data_dir=tmp_path / "data",
        sources={"confluence": {"spaces": ["MFS"]}, "worklog": {"path": worklog}},
    )
    write_cookies(settings.session / COOKIES, [{"name": "s", "value": "v", "domain": "x"}])
    return settings


def test_a_later_sync_catches_up_on_an_old_page_edited_today_and_nothing_stored(
    tmp_path: Path, worklog: Path, monkeypatch: MonkeyPatch
) -> None:
    """A first sync over a week; a second, with no --since, fetches the edited page alone."""
    settings = chosen_settings(tmp_path, worklog)
    monkeypatch.setattr(http, "client", lambda *_: RefreshSite().client())
    first = runs(settings, FIRST, CONFLUENCE, options=SINCE)
    assert sync(first, by_words(settings), lambda: FIRST).exit_status == 0
    assert "1003" not in stored_pages(settings)
    edited = {"number": 4, "createdAt": "2026-10-23T08:00:00.000Z"}
    later = RefreshSite(listing={**PAGES, "1003": {**PAGES["1003"], "version": edited}})
    monkeypatch.setattr(http, "client", lambda *_: later.client())
    synced = sync(runs(settings, SECOND, CONFLUENCE), by_words(settings), lambda: SECOND)
    assert synced.exit_status == ExitStatus.OK
    fetched = synced.steps[0].result
    assert isinstance(fetched, fetcher.Fetched)
    assert isinstance(fetched.downloaded, Outcome)
    assert fetched.downloaded.report.counts["confluence pages: fetched"] == 1
    assert stored_pages(settings)["1003"] == "000004"


def test_the_site_asking_to_sign_in_still_lets_the_work_log_run_exit_3(
    tmp_path: Path, worklog: Path
) -> None:
    """No session saved: the fetch says to sign in; each prepare and the index run."""
    settings = MODEL(
        accounts={"atlassian": {"site": SITE}},
        data_dir=tmp_path / "data",
        sources={"confluence": {"spaces": ["MFS"]}, "worklog": {"path": worklog}},
    )
    taken = runs(settings, FIRST, CONFLUENCE, WORKLOG, options=SINCE)
    with capture_logs() as logged:
        synced = sync(taken, by_words(settings), lambda: FIRST)
    assert [(row.step, row.source, row.outcome) for row in synced.steps] == [
        ("fetch", "confluence", "sign in"),
        ("prepare", "confluence", "done"),
        ("prepare", "worklog", "done"),
        ("index", None, "done"),
    ]
    assert synced.exit_status == ExitStatus.SIGN_IN_AGAIN
    assert logged_as(logged, "download.sign_in_needed")
    assert len(list((settings.docs / "worklog").rglob("*.md"))) == WORKLOG_DOCUMENTS


def test_ctrl_c_in_the_download_exits_130_and_no_later_step_runs(
    tmp_path: Path, worklog: Path, monkeypatch: MonkeyPatch
) -> None:
    """The fetch interrupted; each prepare and the index not run."""

    def interrupted(*_: object) -> Outcome:
        raise KeyboardInterrupt

    monkeypatch.setattr(fetcher, "download", interrupted)
    settings = chosen_settings(tmp_path, worklog)
    taken = runs(settings, FIRST, CONFLUENCE, WORKLOG, options=SINCE)
    synced = sync(taken, by_words(settings), lambda: FIRST)
    assert [(row.step, row.source, row.outcome) for row in synced.steps] == [
        ("fetch", "confluence", "interrupted"),
        ("prepare", "confluence", "not run"),
        ("prepare", "worklog", "not run"),
        ("index", None, "not run"),
    ]
    assert synced.exit_status == ExitStatus.INTERRUPTED
    assert not settings.docs.exists()
    assert not settings.index.exists()


def test_a_mirror_problem_exits_1_with_the_work_log_mirrored(
    tmp_path: Path, worklog: Path, monkeypatch: MonkeyPatch
) -> None:
    """Confluence's prepare fails, said by place; the work log's and the index still run."""
    problem = mirror_app.Problem(
        where="confluence/pages/1001/000001", reason="pandoc: exit status 9"
    )
    monkeypatch.setattr(
        fetcher,
        "download",
        lambda *_: Outcome(report=Report(), failed_targets=[], status=ExitStatus.OK),
    )
    monkeypatch.setattr(
        preparer,
        "mirror",
        lambda *_: mirror_app.Outcome(
            documents=0,
            converted=0,
            reused=0,
            changes=Changes(written=0, unchanged=0, removed=0),
            unsupported=Counter(),
            problems=(problem,),
        ),
    )
    settings = chosen_settings(tmp_path, worklog)
    taken = runs(settings, FIRST, CONFLUENCE, WORKLOG, options=SINCE)
    with capture_logs() as logged:
        synced = sync(taken, by_words(settings), lambda: FIRST)
    assert [(row.step, row.source, row.outcome) for row in synced.steps] == [
        ("fetch", "confluence", "done"),
        ("prepare", "confluence", "failed"),
        ("prepare", "worklog", "done"),
        ("index", None, "done"),
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
    taken = runs(settings, FIRST, WORKLOG)
    assert sync(taken, by_words(settings), lambda: FIRST).exit_status == 0
    before = settings.index.read_bytes()
    monkeypatch.setattr(sqlite_index.Writer, "add", full)
    with capture_logs() as logged:
        synced = sync(taken, by_words(settings), lambda: FIRST)
    assert [(row.step, row.outcome) for row in synced.steps] == [
        ("prepare", "done"),
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
    assert "source 'worklog': prepare: sources.worklog.path: not a folder" in err
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
    second = capsys.readouterr().out.split("prepare worklog: done\n")[-1]
    assert "files written: 0\n" in second


def test_a_failed_conversion_keeps_a_deleted_transcript_s_file_saying_so(
    tmp_path: Path, worklog: Path, telemetry: InMemory, monkeypatch: MonkeyPatch
) -> None:
    """Until the next clean run; the logs say that nothing was removed, and what was held.

    The row's event and span say that it failed, and the entry is counted failed; its
    problem says that its entry alone was held back, "reported loudly in logs" (the
    user, 2026-10-29, plan 044).
    """
    settings = chosen_settings(tmp_path, worklog)
    taken, step = runs(settings, FIRST, WORKLOG), by_words(settings)
    sync(taken, step, lambda: FIRST)
    gone = next((settings.docs / "worklog/transcripts").glob("*waiting-notes.md"))
    (worklog / "transcripts/misc/a.org").unlink()
    todo = worklog / "todo.org"
    todo.write_text(todo.read_text("utf-8").replace("Drafted on", "Drafted, failing, on"), "utf-8")
    failing = Counting(path=Pandoc.find().path, failing="failing")
    telemetry.spans.clear()
    telemetry.measured()
    with monkeypatch.context() as patch, capture_logs() as logged:
        patch.setattr(Pandoc, "find", lambda: failing)
        synced = sync(taken, step, lambda: FIRST)
    assert (synced.steps[0].outcome, synced.exit_status) == ("failed", ExitStatus.FAILED)
    (kept,) = logged_as(logged, "worklog.nothing_removed")
    assert {key: kept[key] for key in kept if key not in {"event", "log_level"}} == {"problems": 1}
    (problem,) = logged_as(logged, "worklog.problem")
    assert problem["where"] == f"todo.org, {problem['held_back']}"
    assert re.fullmatch(r"e-[0-9a-f]{16}", problem["held_back"])
    steps = [(each["step"], each["outcome"]) for each in logged_as(logged, "sync.step")]
    assert steps == [("prepare worklog", "failed"), ("index", "done")]
    spans = telemetry.spans.get_finished_spans()
    (row,) = [
        span
        for span in spans
        if span.name == "sync.step" and span.attributes["kb_mcp.step"] == "prepare"
    ]
    assert row.attributes["kb_mcp.outcome"] == "failed"
    assert by_kind_and_outcome(telemetry.measured()).get(("entry", "failed")) == 1
    assert gone.exists()
    todo.write_text(todo.read_text("utf-8").replace("Drafted, failing, on", "Drafted on"), "utf-8")
    assert sync(taken, step, lambda: FIRST).exit_status == ExitStatus.OK
    assert not gone.exists()


def test_a_transcript_not_read_is_said_loudly_with_what_it_held_back(
    home: Path, worklog: Path, capsys: CaptureFixture[str]
) -> None:
    """On stderr at the default level, one worklog.problem: where, why, what it held back.

    "It should be flagged and reported loudly in logs" (the user, 2026-10-29, plan 044):
    the run exits 1; its JSON gives the problem's held_back, and none at the row's top.
    """
    where = "transcripts/current/2026-10-27 Tue/1.org"
    (worklog / where).write_bytes(b"* Caf\xe9\n")
    config = settings_file(home, worklog)
    assert main(command(home, config, "--yes", "--format", "json")) == ExitStatus.FAILED
    captured = capsys.readouterr()
    (said,) = [line for line in captured.err.splitlines() if "worklog.problem" in line]
    assert all(part in said for part in (where, "not UTF-8", "held_back=t-20261027-1"))
    (row,) = [each for each in json.loads(captured.out)["steps"] if each["source"] == "worklog"]
    assert row["result"]["mirrored"]["problems"] == [
        {"where": where, "reason": "not UTF-8", "held_back": "t-20261027-1"}
    ]
    assert "held_back" not in row["result"]
    assert "held_back" not in row["result"]["mirrored"]


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
        "prepare worklog: done\n"
        f"  documents: {WORKLOG_DOCUMENTS}\n"
        f"  to convert: {WORKLOG_DOCUMENTS}\n"
        "  files to remove: 0\n"
        "  HTML left out: 1\n"
        "  problems: 0\n"
        "index: not run\n"
    )
    assert main(command(home, config, "--yes")) == 0
    assert re.fullmatch(
        "prepare worklog: done\n"
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


@pytest.mark.parametrize("flag", ["--include", "--exclude"])
@pytest.mark.parametrize("registry", [SOURCES, (WORKLOG,), (CONFLUENCE, WORKLOG)])
def test_the_sources_offered_are_the_registry_s(
    flag: str, registry: tuple[Declared, ...], capsys: CaptureFixture[str]
) -> None:
    """Plan 030: --include and --exclude take the names of the registry's declarations.

    Each name that the registry declares is taken; each other is refused by argparse.
    """
    names = [each.name for each in registry]
    for name in names:
        assert getattr(parser(sources=registry).parse_args(["sync", flag, name]), flag[2:]) == [
            name
        ]
    for name in (each.name for each in SOURCES if each.name not in names):
        with pytest.raises(SystemExit) as stopped:
            parser(sources=registry).parse_args(["sync", flag, name])
        assert stopped.value.code == ExitStatus.REFUSED
        assert f"invalid choice: '{name}'" in capsys.readouterr().err


def test_a_dry_run_of_the_site_plans_and_writes_nothing(
    home: Path, signed_in: FakeSite, capsys: CaptureFixture[str]
) -> None:
    """Each fetch planned, each prepare and the index not run; the session alone is written."""
    config = settings_file(home, None, atlassian=True)
    given = ("--dry-run", "--since", "2026-10-02", "--format", "json")
    assert main(command(home, config, *given)) == ExitStatus.OK
    rows = json.loads(capsys.readouterr().out)["steps"]
    assert [(row["step"], row["source"], row["outcome"]) for row in rows] == [
        ("fetch", "confluence", "done"),
        ("fetch", "jira", "done"),
        ("prepare", "confluence", "not run"),
        ("prepare", "jira", "not run"),
        ("index", None, "not run"),
    ]
    fetched = [row["result"]["downloaded"] for row in rows[:2]]
    assert "confluence pages: to fetch" in fetched[0]["report"]["counts"]
    assert "jira issues: to fetch" in fetched[1]["report"]["counts"]
    windows = [each for each_fetched in fetched for each in each_fetched["windows"]]
    assert [(each["target"]["key"], each["reason"], each["coverage"]) for each in windows] == [
        ("MFS", "given", None),
        ("PRB", "given", None),
    ]
    assert [each["dry_run"] for each in fetched] == [True, True]
    assert sorted(path.name for path in (home / "data").iterdir()) == ["session"]
    assert signed_in.asked


def test_a_dry_run_of_the_site_says_each_target_s_window_under_its_row(
    home: Path, signed_in: FakeSite, capsys: CaptureFixture[str]
) -> None:
    """Short as it is: under each fetch's row, its target's window and why, then counts."""
    config = settings_file(home, None, atlassian=True)
    assert main(command(home, config, "--dry-run", "--since", "2026-10-02")) == ExitStatus.OK
    confluence, jira = capsys.readouterr().out.split("fetch jira: done\n")
    fetch_step, space, *_ = confluence.splitlines()
    project, *_ = jira.splitlines()
    assert fetch_step == "fetch confluence: done"
    assert space.startswith("  space MFS: from 2026-10-02T00:00:00+00:00 to ")
    assert project.startswith("  project PRB: from 2026-10-02T00:00:00+00:00 to ")
    assert space.endswith(", given")
    assert signed_in.asked


@pytest.mark.parametrize(
    "case",
    [
        (
            ("--exclude", "worklog"),
            [
                ("fetch", "confluence"),
                ("fetch", "jira"),
                ("prepare", "confluence"),
                ("prepare", "jira"),
                ("index", None),
            ],
            True,
        ),
        (
            ("--exclude", "confluence"),
            [("fetch", "jira"), ("prepare", "jira"), ("prepare", "worklog"), ("index", None)],
            False,
        ),
        (("--include", "worklog"), [("prepare", "worklog"), ("index", None)], False),
    ],
)
def test_the_sources_chosen_are_the_steps_run(
    home: Path,
    worklog: Path,
    signed_in: FakeSite,
    capsys: CaptureFixture[str],
    case: tuple[tuple[str, ...], list[tuple[str, str | None]], bool],
) -> None:
    """Excluded or not included: no step, no request, no file of it; the index runs always."""
    given, steps, confluence = case
    config = settings_file(home, worklog, atlassian=True)
    main(command(home, config, "--yes", "--since", "2026-10-02", "--format", "json", *given))
    rows = json.loads(capsys.readouterr().out)["steps"]
    assert [(row["step"], row["source"]) for row in rows] == steps
    assert any("/wiki/" in url.path for url in signed_in.asked) is confluence
    assert (home / "data" / "docs" / "worklog").exists() is (("prepare", "worklog") in steps)


def test_a_source_left_out_is_not_mirrored_though_its_documents_are_stored(
    home: Path, signed_in: FakeSite, capsys: CaptureFixture[str]
) -> None:
    """Plan 030: --include jira mirrors Jira alone; a Confluence file deleted stays so."""
    config = settings_file(home, None, atlassian=True)
    given = ("--yes", "--since", "2026-10-02", "--format", "json")
    main(command(home, config, *given))
    capsys.readouterr()
    page = next((home / "data" / "docs" / "confluence").rglob("*.md"))
    page.unlink()
    main(command(home, config, *given, "--include", "jira"))
    rows = json.loads(capsys.readouterr().out)["steps"]
    steps = [(row["step"], row["source"], row["outcome"]) for row in rows]
    assert steps == [
        ("fetch", "jira", "done"),
        ("prepare", "jira", "done"),
        ("index", None, "done"),
    ]
    assert not page.exists()
    assert signed_in.asked


def test_archives_off_leaves_the_archived_documents_out_of_a_sync(
    home: Path, worklog: Path, capsys: CaptureFixture[str]
) -> None:
    """The archive file's entry and meetings, the ARCHIVE entry, the archived transcript."""
    config = settings_file(home, worklog)
    config.write_text(config.read_text("utf-8") + "archives = false\n", "utf-8")
    assert main(command(home, config, "--yes", "--format", "json")) == 0
    result = json.loads(capsys.readouterr().out)["steps"][0]["result"]["mirrored"]
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
    unsigned = "no source of the atlassian account in this sync"
    assert f"ignored: accounts.atlassian.site (config.toml): {unsigned}\n" in said
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
    first, second = (json.loads(row)["steps"][2] for row in rows[:2])
    mirrored = first["result"]["mirrored"]
    assert (first["step"], first["outcome"], mirrored["reused"]) == ("prepare", "done", 0)
    converted = mirrored["converted"]
    assert converted > mirrored["documents"] > 0  # a tree among them
    again = second["result"]["mirrored"]
    assert (again["converted"], again["reused"]) == (0, converted)
    documents = mirrored["documents"]
    assert (
        f"prepare confluence: done\n  documents: {documents}\n"
        f"  converted by pandoc: 0\n  reused from the cache: {converted}\n"
    ) in rows[2]
    jira = json.loads(rows[0])["steps"][3]
    assert (jira["step"], jira["source"], jira["outcome"]) == ("prepare", "jira", "done")
    total = converted + jira["result"]["mirrored"]["converted"]
    with closing(sqlite3.connect(home / "data" / "conversions.sqlite")) as cache:
        assert cache.execute("SELECT count(*) FROM conversions").fetchone() == (total,)


def test_a_damaged_cache_is_replaced_and_every_step_runs_exit_0(
    tmp_path: Path, worklog: Path, monkeypatch: MonkeyPatch
) -> None:
    """Plan 039, criterion 8: the mirror converts all again, reusing nothing, said once."""
    settings = chosen_settings(tmp_path, worklog)
    monkeypatch.setattr(http, "client", lambda *_: RefreshSite().client())
    taken = runs(settings, FIRST, CONFLUENCE, WORKLOG, options=SINCE)
    first = sync(taken, by_words(settings), lambda: FIRST).steps[1].result
    assert isinstance(first, preparer.Prepared)
    assert isinstance(first.mirrored, mirror_app.Outcome)
    settings.conversions.write_bytes(hashlib.shake_256(b"cache").digest(8192))
    with capture_logs() as logged:
        synced = sync(taken, by_words(settings), lambda: FIRST)
    assert synced.exit_status == ExitStatus.OK
    assert [(row.step, row.source, row.outcome) for row in synced.steps] == [
        ("fetch", "confluence", "done"),
        ("prepare", "confluence", "done"),
        ("prepare", "worklog", "done"),
        ("index", None, "done"),
    ]
    result = synced.steps[1].result
    assert isinstance(result, preparer.Prepared)
    mirrored, first = result.mirrored, first.mirrored
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
    taken = runs(settings, FIRST, CONFLUENCE, options=SINCE)
    first = sync(taken, by_words(settings), lambda: FIRST).steps[1].result
    assert isinstance(first, preparer.Prepared)
    first = first.mirrored
    assert isinstance(first, mirror_app.Outcome)
    more = (*pandoc_adapter.ARGUMENTS, "--columns=72")
    monkeypatch.setattr(pandoc_adapter, "ARGUMENTS", more)
    again = sync(taken, by_words(settings), lambda: FIRST).steps[1].result
    assert isinstance(again, preparer.Prepared)
    again = again.mirrored
    assert isinstance(again, mirror_app.Outcome)
    assert (again.converted, again.reused) == (first.converted, 0)
    assert first.converted > 0


def test_the_text_of_a_full_sync_gives_each_command_s_counts_under_its_row(
    home: Path, worklog: Path, signed_in: FakeSite, capsys: CaptureFixture[str]
) -> None:
    """Each fetch's counts, as download writes them, indented under its source's row."""
    config = settings_file(home, worklog, atlassian=True)
    assert main(command(home, config, "--yes", "--since", "2026-10-02")) == ExitStatus.FAILED
    out = capsys.readouterr().out
    assert out.startswith("fetch confluence: failed\n  confluence blogposts: fetched: 1\n")
    assert "  failures: 1\nfetch jira: done\n  files: downloaded: 1\n" in out
    assert "  failures: 0\nprepare confluence: done\n  documents: " in out
    assert "\nprepare jira: done\n  documents: " in out
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
    assert [(row["step"], row["source"], row["outcome"]) for row in rows] == [
        ("prepare", "worklog", "done"),
        ("index", None, "done"),
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
    monkeypatch.setenv("KB_MCP_SEARCH_MODE", "hybrid")
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
    monkeypatch.setenv("KB_MCP_SEARCH_MODE", "hybrid")
    config = settings_file(home, worklog)
    with serving(Scripted(models={})) as url:
        monkeypatch.setenv("KB_MCP_EMBEDDING_URL", url)
        status = main(command(home, config, "--yes", "--format", "json"))
    rows = json.loads(capsys.readouterr().out)["steps"]
    assert status == ExitStatus.FAILED
    assert [(row["step"], row["source"], row["outcome"]) for row in rows] == [
        ("prepare", "worklog", "done"),
        ("index", None, "failed"),
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
    """The fetch done, Confluence's prepare interrupted, the work log's not run: exit 130."""
    monkeypatch.setattr(
        fetcher,
        "download",
        lambda *_: Outcome(report=Report(), failed_targets=[], status=ExitStatus.OK),
    )
    monkeypatch.setattr(preparer, "mirror", interrupting)
    settings = chosen_settings(tmp_path, worklog)
    taken = runs(settings, FIRST, CONFLUENCE, WORKLOG, options=SINCE)
    with capture_logs() as logged:
        synced = sync(taken, by_words(settings), lambda: FIRST)
    assert [(row.step, row.source, row.outcome) for row in synced.steps] == [
        ("fetch", "confluence", "done"),
        ("prepare", "confluence", "interrupted"),
        ("prepare", "worklog", "not run"),
        ("index", None, "not run"),
    ]
    assert synced.exit_status == ExitStatus.INTERRUPTED
    stopped = logged_as(logged, "sync.interrupted")
    assert [each["step"] for each in stopped] == ["prepare confluence"]


def test_ctrl_c_once_every_step_ended_still_exits_130(
    tmp_path: Path, worklog: Path, monkeypatch: MonkeyPatch
) -> None:
    """Every row kept as it ended, and the run interrupted."""

    def ended_then_stopped(
        _step: Index, _now: Callable[[], datetime], add: Callable[[Row], None], **_: bool
    ) -> None:
        add(Row(step="index", source=None, outcome="done", result=None))
        raise KeyboardInterrupt

    monkeypatch.setattr(sync_app, "index", ended_then_stopped)
    settings = chosen_settings(tmp_path, worklog)
    synced = sync(runs(settings, FIRST, WORKLOG), by_words(settings), lambda: FIRST)
    assert [(row.step, row.outcome) for row in synced.steps] == [
        ("prepare", "done"),
        ("index", "done"),
    ]
    assert synced.exit_status == ExitStatus.INTERRUPTED


def test_to_sign_in_again_ranks_above_a_failure_and_below_an_interruption(
    tmp_path: Path, worklog: Path, monkeypatch: MonkeyPatch
) -> None:
    """No session saved and a mirror problem exit 3; Ctrl-C after them exits 130."""
    problem = mirror_app.Problem(
        where="confluence/pages/1001/000001", reason="pandoc: exit status 9"
    )
    monkeypatch.setattr(
        preparer,
        "mirror",
        lambda *_: mirror_app.Outcome(
            documents=0,
            converted=0,
            reused=0,
            changes=Changes(written=0, unchanged=0, removed=0),
            unsupported=Counter(),
            problems=(problem,),
        ),
    )
    settings = MODEL(
        accounts={"atlassian": {"site": SITE}},
        data_dir=tmp_path / "data",
        sources={"confluence": {"spaces": ["MFS"]}, "worklog": {"path": worklog}},
    )
    taken = runs(settings, FIRST, CONFLUENCE, WORKLOG, options=SINCE)
    synced = sync(taken, by_words(settings), lambda: FIRST)
    assert [row.outcome for row in synced.steps] == ["sign in", "failed", "done", "done"]
    assert synced.exit_status == ExitStatus.SIGN_IN_AGAIN
    monkeypatch.setattr(worklog_preparer, "prepare", interrupting)
    synced = sync(taken, by_words(settings), lambda: FIRST)
    assert [row.outcome for row in synced.steps] == ["sign in", "failed", "interrupted", "not run"]
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
    monkeypatch.setenv("KB_MCP_ACCOUNTS__ATLASSIAN__EMAIL", "someone@example.invalid")
    config = settings_file(home, None, atlassian=True)
    assert main(command(home, config, "--dry-run", "--since", "2026-10-02")) == ExitStatus.OK
    said = capsys.readouterr().err
    assert "no source of the atlassian account" not in said
    assert (
        "accounts.atlassian.email: someone@example.invalid (not applied: without an API token"
        in said
    )
    assert signed_in.asked


def test_without_a_site_source_the_sign_in_s_settings_are_not_applied(
    home: Path, worklog: Path, monkeypatch: MonkeyPatch, capsys: CaptureFixture[str]
) -> None:
    """The email and the token, given, are said ignored, by their variables."""
    monkeypatch.setenv("KB_MCP_ACCOUNTS__ATLASSIAN__EMAIL", "someone@example.invalid")
    monkeypatch.setenv("KB_MCP_ACCOUNTS__ATLASSIAN__API_TOKEN", "token-sentinel-7f2b")
    config = settings_file(home, worklog)
    assert main(command(home, config, "--dry-run")) == ExitStatus.OK
    said = capsys.readouterr().err
    for setting, variable in (
        ("accounts.atlassian.email", "KB_MCP_ACCOUNTS__ATLASSIAN__EMAIL"),
        ("accounts.atlassian.api_token", "KB_MCP_ACCOUNTS__ATLASSIAN__API_TOKEN"),
    ):
        unsigned = "no source of the atlassian account in this sync"
        assert f"ignored: {setting} ({variable}): {unsigned}\n" in said
    assert "token-sentinel-7f2b" not in said


def test_a_busy_raw_store_fails_the_download_and_the_next_steps_run(
    tmp_path: Path, worklog: Path, monkeypatch: MonkeyPatch
) -> None:
    """Another run writing the store: the fetch failed, said; each prepare runs."""

    def busy(*_: object) -> Outcome:
        raise StoreBusyError

    monkeypatch.setattr(fetcher, "download", busy)
    settings = chosen_settings(tmp_path, worklog)
    taken = runs(settings, FIRST, CONFLUENCE, WORKLOG, options=SINCE)
    with capture_logs() as logged:
        synced = sync(taken, by_words(settings), lambda: FIRST)
    assert [(row.step, row.source, row.outcome) for row in synced.steps] == [
        ("fetch", "confluence", "failed"),
        ("prepare", "confluence", "done"),
        ("prepare", "worklog", "done"),
        ("index", None, "done"),
    ]
    assert synced.exit_status == ExitStatus.FAILED
    assert logged_as(logged, "download.store_busy")


# The commands whose steps sync runs: what their pages list, and sync's does not, is
# theirs, and sync records it as they do.
STEP_PAGES = ("download", "mirror", "index", "embed")


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
        monkeypatch.delenv("KB_MCP_SEARCH_MODE")
    config = settings_file(home, worklog, atlassian=True)
    period = ("--since", "2026-10-02")
    emitted = Emitted()
    with serving(Scripted(models={DEFAULT_MODEL: DIGEST})) as url:
        monkeypatch.setenv("KB_MCP_EMBEDDING_URL", url)
        with emitted.gathering(telemetry, "sync"):
            assert main(command(home, config, "--yes", "-vv", *period)) == ExitStatus.FAILED
        with emitted.gathering(telemetry, "sync"):
            assert main(command(home, config, "--dry-run", *period)) == ExitStatus.OK
        shutil.copytree(worklog / "transcripts/current", worklog / "transcripts/archive/2026/x")
        (worklog / "transcripts/misc/a.org").write_bytes(b"* Caf\xe9\n")
        with emitted.gathering(telemetry, "sync"):
            assert main(command(home, config, "--yes", "--include", "worklog")) == ExitStatus.FAILED
        with monkeypatch.context() as patch:
            patch.setattr(fetcher, "download", interrupting)
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
        (point.attributes["kb_mcp.kind"], point.attributes["kb_mcp.outcome"]): point.value
        for point in measured["kb_mcp.mirror.documents"].data.data_points
        if point.attributes and "kb_mcp.kind" in point.attributes
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
    timed = first["kb_mcp.mirror.conversion.duration"].data.data_points
    assert {point.attributes["kb_mcp.kind"]: point.count for point in timed} == WORKLOG_KINDS
    assert "kb_mcp.mirror.conversion.duration" not in second
    rows = {span.attributes["kb_mcp.step"]: span for span in spans if span.name == "sync.step"}
    assert list(rows) == ["prepare", "index"]
    row = rows["prepare"]
    assert (row.attributes["kb_mcp.source"], row.attributes["kb_mcp.outcome"]) == (
        "worklog",
        "done",
    )
    assert "kb_mcp.source" not in rows["index"].attributes
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
    settings = chosen_settings(tmp_path, worklog)
    dry, step = runs(settings, FIRST, WORKLOG, dry_run=True), by_words(settings)
    with capture_logs() as planned:
        sync(dry, step, lambda: FIRST)
    with capture_logs() as fresh:
        sync(runs(settings, FIRST, WORKLOG), step, lambda: FIRST)
    with capture_logs() as unchanged:
        sync(runs(settings, FIRST, WORKLOG), step, lambda: FIRST)
    (worklog / "transcripts/misc/a.org").unlink()
    with capture_logs() as planned_again:
        sync(dry, step, lambda: FIRST)
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


def test_every_role_s_preflight_runs_before_the_first_row(
    home: Path, tmp_path: Path, signed_in: FakeSite, capsys: CaptureFixture[str]
) -> None:
    """Plan 030: a work log that is not a folder refuses the run before any fetch.

    Its preparer's preflight refuses it, so that Confluence's and Jira's fetchers, whose
    rows come first, ask the site nothing.
    """
    config = settings_file(home, tmp_path / "absent", atlassian=True)
    assert main(command(home, config, "--yes", "--since", "2026-10-02")) == ExitStatus.REFUSED
    assert "sources.worklog.path: not a folder" in capsys.readouterr().err
    assert signed_in.asked == []


@pytest.mark.parametrize(
    "case",
    [
        ((), {}, "accounts.atlassian.site: not set; add it to the settings or pass --site"),
        (
            ("--site", SITE),
            {"KB_MCP_ACCOUNTS__ATLASSIAN__API_TOKEN": "token-sentinel-7f2b"},
            "accounts.atlassian.email: not set; an API token signs in with its account's email",
        ),
        (("--site", SITE, "--max-file-mb", "0"), {}, "--max-file-mb: at least 1"),
        (("--site", SITE, "--until", "soon"), {}, "--until: a length before now"),
    ],
)
def test_the_site_s_light_checks_refuse_a_sync_of_its_sources_alone(
    home: Path,
    worklog: Path,
    monkeypatch: MonkeyPatch,
    capsys: CaptureFixture[str],
    case: tuple[tuple[str, ...], dict[str, str], str],
) -> None:
    """Plan 030: Confluence's and Jira's declarations refuse a run of either, by name.

    No site, an API token without its email, or an option of the period that does not
    read, exit 2 before anything is asked; a sync of the work log alone asks the site's
    declarations nothing, and says the period's options ignored.
    """
    given, variables, said = case
    for name, value in variables.items():
        monkeypatch.setenv(name, value)
    config = settings_file(home, worklog)
    config.write_text(config.read_text("utf-8") + '[sources.jira]\nprojects = ["PRB"]\n', "utf-8")
    assert main(command(home, config, "--yes", *given)) == ExitStatus.REFUSED
    assert said in capsys.readouterr().err
    assert main(command(home, config, "--dry-run", "--include", "worklog", *given)) == 0
    assert said not in capsys.readouterr().err


def test_a_source_s_own_light_checks_are_asked_when_it_is_taken(
    home: Path, worklog: Path, capsys: CaptureFixture[str]
) -> None:
    """Plan 030: sync asks each source taken what it refuses, says and does not apply.

    By its declaration's functions, given its options and the settings: here the work
    log's, in a registry of the test's own.
    """
    config = settings_file(home, worklog)
    config.write_text(config.read_text("utf-8") + "archives = false\n", "utf-8")

    def said(_options: Mapping[str, object], _settings: Mapping[str, object]) -> tuple[str, ...]:
        return ("read in place, as declared",)

    def unused(_options: Mapping[str, object], settings: Mapping[str, object]) -> dict[str, str]:
        assert settings["sources.worklog.archives"] is False
        return {"sources.worklog.archives": "a declaration's reason"}

    checked = replace(WORKLOG, described=said, unapplied=unused)
    assert main(command(home, config, "--dry-run"), (*SOURCES[:2], checked)) == ExitStatus.OK
    err = capsys.readouterr().err
    assert "  read in place, as declared\n" in err
    assert "(not applied: a declaration's reason)" in err

    refusing = replace(WORKLOG, refused=lambda _options, _settings: "a declaration's refusal")
    refused_run = main(command(home, config, "--dry-run"), (*SOURCES[:2], refusing))
    assert refused_run == ExitStatus.REFUSED
    assert "a declaration's refusal" in capsys.readouterr().err
    left_out = main(command(home, config, "--dry-run", "--exclude", "worklog"), (refusing,))
    assert left_out == ExitStatus.REFUSED
    assert "a declaration's refusal" not in capsys.readouterr().err


def test_a_sync_is_a_dry_run_by_its_runs_alone(tmp_path: Path, worklog: Path) -> None:
    """Plan 030: one flag for a run, which each role reads: the index and the events follow it.

    A sync of no run, which the entry refuses, is no dry run.
    """
    settings = chosen_settings(tmp_path, worklog)
    step = by_words(settings)
    with capture_logs() as dry:
        synced = sync(runs(settings, FIRST, WORKLOG, dry_run=True), step, lambda: FIRST)
    assert [(row.step, row.outcome) for row in synced.steps] == [
        ("prepare", "done"),
        ("index", "not run"),
    ]
    assert logged_as(dry, "sync.start")[0]["dry_run"] is True
    assert not settings.docs.exists()
    assert not settings.index.exists()
    with capture_logs() as real:
        synced = sync(runs(settings, FIRST, WORKLOG), step, lambda: FIRST)
    assert [(row.step, row.outcome) for row in synced.steps] == [
        ("prepare", "done"),
        ("index", "done"),
    ]
    assert logged_as(real, "sync.start")[0]["dry_run"] is False
    assert settings.index.exists()
    assert [(row.step, row.outcome) for row in sync([], step, lambda: FIRST).steps] == [
        ("index", "done")
    ]


def test_each_preparer_that_a_source_declares_is_a_row_of_its_own(
    tmp_path: Path, worklog: Path
) -> None:
    """Plan 030: a declaration's preparers are a tuple: each runs, in its order, a row each.

    The same preparer twice here, the second finding its files written by the first.
    """
    settings = chosen_settings(tmp_path, worklog)
    twice = replace(WORKLOG, preparers=WORKLOG.preparers * 2)
    synced = sync(runs(settings, FIRST, twice), by_words(settings), lambda: FIRST)
    assert [(row.step, row.source, row.outcome) for row in synced.steps] == [
        ("prepare", "worklog", "done"),
        ("prepare", "worklog", "done"),
        ("index", None, "done"),
    ]
    written = [row.result.mirrored.changes.written for row in synced.steps[:2]]
    assert written == [WORKLOG_DOCUMENTS, 0]


@pytest.mark.parametrize(
    "case",
    [
        (ExitStatus.OK, "done", ExitStatus.FAILED),
        (ExitStatus.SIGN_IN_AGAIN, "sign in", ExitStatus.SIGN_IN_AGAIN),
    ],
)
def test_pandoc_gone_fails_each_preparer_s_row_and_the_run_exits_as_its_rows_rank(
    tmp_path: Path,
    worklog: Path,
    monkeypatch: MonkeyPatch,
    case: tuple[ExitStatus, str, ExitStatus],
) -> None:
    """Plan 030's departure: no role but a preparer needs pandoc, so the fetch still runs.

    Gone from PATH after the entry's check, it fails each preparer's row alone, each
    saying so, and the run exits 1, or 3 when a fetch needs sign-in.
    """
    ended, fetched, status = case
    monkeypatch.setattr(Pandoc, "find", missing)
    monkeypatch.setattr(
        fetcher,
        "download",
        lambda *_: Outcome(report=Report(), failed_targets=[], status=ended),
    )
    settings = chosen_settings(tmp_path, worklog)
    taken = runs(settings, FIRST, CONFLUENCE, WORKLOG, options=SINCE)
    with capture_logs() as logged:
        synced = sync(taken, by_words(settings), lambda: FIRST)
    assert [(row.step, row.source, row.outcome) for row in synced.steps[:3]] == [
        ("fetch", "confluence", fetched),
        ("prepare", "confluence", "failed"),
        ("prepare", "worklog", "failed"),
    ]
    assert synced.exit_status == status
    assert len(logged_as(logged, "mirror.pandoc_missing")) == 1
    assert len(logged_as(logged, "worklog.pandoc_failed")) == 1
    assert not (settings.docs / "worklog").exists()


def test_pandoc_giving_no_version_fails_the_work_log_s_row_writing_nothing(
    tmp_path: Path, worklog: Path, monkeypatch: MonkeyPatch
) -> None:
    """No revision can be named: the row fails, an error says why, and the run goes on."""
    monkeypatch.setattr(Pandoc, "org_converter", lambda _: unconverted())
    settings = chosen_settings(tmp_path, worklog)
    taken = runs(settings, FIRST, WORKLOG)
    with capture_logs() as logged:
        synced = sync(taken, by_words(settings), lambda: FIRST)
    assert [(row.step, row.source) for row in synced.steps] == [
        ("prepare", "worklog"),
        ("index", None),
    ]
    assert (synced.steps[0].outcome, synced.exit_status) == ("failed", ExitStatus.FAILED)
    (said,) = logged_as(logged, "worklog.pandoc_failed")
    assert said["reason"] == "pandoc: exit status 9"
    assert not (settings.docs / "worklog").exists()


def test_only_a_run_that_writes_says_that_its_problems_held_removals_back(
    tmp_path: Path, worklog: Path
) -> None:
    """A file not read is a problem of both; a dry run, which removes nothing, says no more."""
    (worklog / "transcripts/misc/a.org").write_bytes(b"* Caf\xe9\n")
    settings = chosen_settings(tmp_path, worklog)
    step = by_words(settings)
    with capture_logs() as dry:
        sync(runs(settings, FIRST, WORKLOG, dry_run=True), step, lambda: FIRST)
    with capture_logs() as real:
        sync(runs(settings, FIRST, WORKLOG), step, lambda: FIRST)
    assert logged_as(dry, "worklog.problem")
    assert not logged_as(dry, "worklog.nothing_removed")
    assert logged_as(real, "worklog.problem")
    assert logged_as(real, "worklog.nothing_removed")


def test_sync_offers_each_option_that_its_sources_declare_once(
    capsys: CaptureFixture[str],
) -> None:
    """Plan 030: the period's options are Confluence's and Jira's, each flag once.

    Each is read as its declaration types it; a registry of the work log alone, which
    declares none, offers none.
    """
    arguments = parser().parse_args(["sync", "--since", "7d", "--max-file-mb", "2"])
    assert given(arguments, ("--since", "--max-file-mb")) == {"--since": "7d", "--max-file-mb": 2}
    with pytest.raises(SystemExit) as stopped:
        parser(sources=(WORKLOG,)).parse_args(["sync", "--since", "7d"])
    assert stopped.value.code == ExitStatus.REFUSED
    assert "unrecognized arguments: --since 7d" in capsys.readouterr().err
