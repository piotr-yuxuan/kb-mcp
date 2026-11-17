"""Recorded and resumable runs, and ``refresh``, as plan 062 defines them.

The expectations come from the plan, as the user settled it on 2026-11-16, and from the
concepts page's run: a run resolves its configuration as it starts, relative values made
absolute against that start, records it under ``runs/<run id>/`` without any secret, then
runs from what it reads back, its first invocation as each that resumes it; each unit's
entry is written as it ends; a resume runs each unit not last ended done, and each that
follows one of those. The site is plan 004's scripted one, the work log the invented
fixture, the embedding endpoint the tests' tiny model; each test has a scratch home.
"""

from __future__ import annotations

import json
import os
import shlex
import shutil
import sqlite3
import time
from contextlib import closing
from copy import replace
from datetime import UTC, datetime, timedelta, tzinfo
from typing import TYPE_CHECKING

import pytest
from structlog.testing import capture_logs

from kb_mcp.cli.adapters.run_record import RunBusyError, RunRecord
from kb_mcp.cli.app import resumption
from kb_mcp.cli.app.units import Planned, run_units
from kb_mcp.cli.domain.runs import (
    Configuration,
    Recorded,
    Unit,
    attempted,
    followed,
    units_of,
)
from kb_mcp.cli.main import main
from kb_mcp.config.domain.settings import with_secrets, without_secrets
from kb_mcp.kernel.exit_status import ExitStatus
from kb_mcp.kernel.fields import RepresentationError
from kb_mcp.kernel.names import RefusedError
from kb_mcp.kernel.outcome import Outcome, Problem
from kb_mcp.sources.atlassian.fetch.adapters import http
from kb_mcp.sources.atlassian.fetch.app import fetcher
from kb_mcp.sources.atlassian.fetch.app.fetching import FetchCounts
from kb_mcp.sources.atlassian.prepare.app import preparer as atlassian_preparer
from kb_mcp.sources.worklog.prepare.app import preparer as worklog_preparer
from tests.composed import MODEL
from tests.endpoint import Scripted, nothing_listening, serving
from tests.test_cli import logged_as
from tests.test_fetching import SITE, FakeSite
from tests.test_prepare_worklog import FIXTURE, settle
from tests.test_settings import user_log_folder

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator
    from pathlib import Path

    from _pytest.capture import CaptureFixture
    from _pytest.monkeypatch import MonkeyPatch

    from kb_mcp.sources.atlassian.fetch.app.fetching import Purview

# A run's id, as a run makes it.
RUN = "0123456789abcdef"
# The API token of Confluence's source and Jira's, and its email, by the environment
# alone; the token never reaches a file.
SENTINEL = "token-sentinel-062a"
SIGN_IN = {
    f"KB_MCP_SOURCES__{source}__{name}": value
    for source in ("CONFLUENCE", "JIRA")
    for name, value in (("EMAIL", "someone@example.invalid"), ("API_TOKEN", SENTINEL))
}
# What a refresh of the scripted site reads: the period that holds what it serves.
SINCE = ("--since", "2026-10-02")
# The units of a refresh of Jira and the work log, in their order: a prepare takes
# Confluence's store too, which a refresh that names no source keeps, though empty.
REFRESHED = [
    ("fetch", "jira"),
    ("fetch", "worklog"),
    ("prepare", "confluence"),
    ("prepare", "jira"),
    ("prepare", "worklog"),
    ("index", None),
    ("embed", None),
]


def configuration(**changed: object) -> Configuration:
    """Give a refresh's configuration of Jira and the work log, with these fields changed."""
    fields: dict[str, object] = {
        "run": RUN,
        "command": "refresh",
        "started": datetime(2026, 11, 16, 10, tzinfo=UTC),
        "stages": ("fetch", "prepare", "index", "embed"),
        "sources": {"fetch": ("jira", "worklog"), "prepare": ("jira", "worklog")},
        "options": {"fetch": {"--since": None}, "index": {"--rebuild": False}},
        "settings": {},
    }
    return Configuration(**{**fields, **changed})


def test_a_configuration_s_units_run_stage_by_stage_each_source_in_its_order() -> None:
    """Fetch and prepare per source, a prepare's unit per preparer, then index and embed."""
    units = units_of(configuration(), {"jira": 1, "worklog": 2})
    assert [(unit.stage, unit.source, unit.part) for unit in units] == [
        ("fetch", "jira", 0),
        ("fetch", "worklog", 0),
        ("prepare", "jira", 0),
        ("prepare", "worklog", 0),
        ("prepare", "worklog", 1),
        ("index", None, 0),
        ("embed", None, 0),
    ]


def test_a_unit_per_source_follows_its_own_source_s_and_a_whole_one_every_unit_before() -> None:
    """A source's prepare after its fetch alone; index after every prepare; embed after index."""
    units = units_of(configuration(), {"jira": 1, "worklog": 1})
    fetch_jira, fetch_worklog, prepare_jira, prepare_worklog, index, embed = units
    assert followed(fetch_jira, units) == ()
    assert followed(prepare_jira, units) == (fetch_jira,)
    assert followed(prepare_worklog, units) == (fetch_worklog,)
    assert followed(index, units) == (prepare_jira, prepare_worklog)
    assert followed(embed, units) == (index,)


def test_a_resume_runs_each_unit_not_done_and_each_that_follows_one() -> None:
    """Q6: an index done runs again after a source's fetch that runs again; all done, none."""
    units = units_of(configuration(), {"jira": 1, "worklog": 1})
    done = dict.fromkeys(units, "done")
    assert attempted(units, done) == frozenset()
    again = attempted(units, {**done, units[0]: "sign in again"})
    assert {unit.name for unit in again} == {"fetch jira", "prepare jira", "index", "embed"}
    assert attempted(units, {}) == frozenset(units)


@pytest.mark.parametrize(
    ("changed", "said"),
    [
        ({"run": "../elsewhere"}, "run: not a run id"),
        ({"stages": ("index", "fetch")}, "stages: some of fetch, prepare, index, embed"),
        ({"stages": ()}, "stages: some of"),
        ({"sources": {"fetch": ("jira",)}}, "sources: those of each stage enabled"),
        ({"options": {}}, "options: fetch's and index's"),
        ({"options": {"fetch": {}, "index": {}}}, "options: fetch's and index's"),
        ({"options": {"fetch": {}, "index": {"--rebuild": "no"}}}, "options: fetch's"),
        (
            {"options": {"fetch": {}, "index": {"--rebuild": False}, "embed": {}}},
            "options: fetch's and index's",
        ),
    ],
)
def test_a_configuration_refuses_what_no_run_can_be(changed: dict[str, object], said: str) -> None:
    """Another run id, which names a folder, stages out of order or none, sources of no stage.

    And a stage's options that its run reads missing: fetch's, or index's --rebuild, which
    must say true or false; or the options of a stage that reads none.
    """
    with pytest.raises(RefusedError, match=said):
        configuration(**changed)


def test_the_record_reads_back_what_it_wrote_and_refuses_a_damaged_file_by_its_field(
    tmp_path: Path,
) -> None:
    """Each file is written whole and read back; a field refused is named, never its value."""
    record = RunRecord(tmp_path / RUN)
    entry = Recorded(
        stage="fetch",
        source="jira",
        ending="failed",
        counts={"jira issues: fetched": 1},
        problems=(Problem(where="project PRB", reason="status 503"),),
        invocation=datetime(2026, 11, 16, 10, tzinfo=UTC),
    )
    with record.holding():
        assert record.read_outcomes() == ()
        record.write_configuration(configuration())
        record.write_outcomes([entry])
    assert record.read_configuration() == configuration()
    assert record.read_outcomes() == (entry,)
    assert sorted(path.name for path in (tmp_path / RUN).iterdir()) == [
        ".lock",
        "configuration.json",
        "outcomes.json",
    ]
    damaged = json.loads((tmp_path / RUN / "outcomes.json").read_text("utf-8"))
    damaged["units"][0]["ending"] = "value-sentinel"
    (tmp_path / RUN / "outcomes.json").write_text(json.dumps(damaged), "utf-8")
    with pytest.raises(RepresentationError) as refused:
        record.read_outcomes()
    assert str(refused.value).startswith(f"runs/{RUN}/outcomes.json: units.0.ending: ")
    assert "value-sentinel" not in str(refused.value)
    with pytest.raises(FileNotFoundError):
        RunRecord(tmp_path / "fedcba9876543210").read_configuration()


def test_one_invocation_at_a_time_holds_a_run(tmp_path: Path) -> None:
    """Q9: a second holder of one run is refused while the first holds it, not after."""
    first, second = RunRecord(tmp_path / RUN), RunRecord(tmp_path / RUN)
    with first.holding(), pytest.raises(RunBusyError), second.holding():
        pass
    with second.holding():
        pass


def test_a_record_without_a_folder_reads_back_what_it_kept() -> None:
    """A dry run's: its configuration read back as any run's is, by no folder."""
    record = RunRecord(None)
    with record.holding():
        assert record.read_outcomes() == ()
        record.write_configuration(configuration())
        assert record.read_configuration() == configuration()
    assert record.folder is None


def test_the_settings_recorded_hold_no_secret_and_take_it_back_from_the_environment() -> None:
    """A secret is never recorded; the settings rebuilt from the record take this one's."""
    settings = MODEL(
        data_dir="/data",
        sources={"jira": {"projects": ["PRB"], "site": SITE, "api_token": SENTINEL}},
        embedding_api_key="key-sentinel-062b",
    )
    recorded = without_secrets(settings)
    assert SENTINEL not in json.dumps(recorded)
    assert "key-sentinel-062b" not in json.dumps(recorded)
    assert "api_token" not in recorded["sources"]["jira"]  # type: ignore[index]
    assert with_secrets(recorded, settings) == settings


def acted(ending: str) -> Planned:
    """Give a unit of its own whose work ends as told."""
    return Planned(unit=Unit(stage="index"), act=lambda: Outcome(ending=ending))


def test_each_entry_is_written_as_its_unit_ends_and_ctrl_c_ends_the_invocation() -> None:
    """Units ended keep theirs; the one stopped is interrupted, those after it not run: 130.

    A unit per source whose source's fetch was interrupted is not run, nor acts. Each unit
    that ends is written as it ends; those that Ctrl-C ends, once.
    """
    written: list[list[tuple[str, str]]] = []
    acting: list[str] = []

    def act(name: str, ending: str) -> Callable[[], Outcome[FetchCounts]]:
        def work() -> Outcome[FetchCounts]:
            acting.append(name)
            if ending == "interrupted":
                raise KeyboardInterrupt
            return Outcome(ending=ending)  # type: ignore[arg-type]

        return work

    units = units_of(configuration(), {"jira": 1, "worklog": 1})
    endings = ["done", "interrupted", "done", "done", "done", "done"]
    planned = [
        Planned(unit=unit, act=act(unit.name, ending))
        for unit, ending in zip(units, endings, strict=True)
    ]
    done = run_units(
        planned,
        (),
        datetime(2026, 11, 16, 10, tzinfo=UTC),
        lambda entries: written.append([(each.stage, str(each.source)) for each in entries]),
        dry_run=False,
    )
    assert acting == ["fetch jira", "fetch worklog"]
    assert [entry.ending for entry in done.entries] == [
        "done",
        "interrupted",
        "not run",
        "not run",
        "not run",
        "not run",
    ]
    assert done.exit_status == ExitStatus.INTERRUPTED
    assert written[0] == [("fetch", "jira")]
    assert [len(entries) for entries in written[1:]] == [len(units)]


def test_an_error_that_no_unit_catches_passes_once_its_unit_is_recorded_failed() -> None:
    """The unit that raised fails, by the error's type alone; each later one taken, not run.

    So a resume runs them; the error passes as it was raised. The entries are written as
    the unit before it ends, then once more. Each stage's end says what the record does
    (telemetry/fetch.md and prepare.md): the status that its units' endings fold, and
    how each ended, the unit that raised among them.
    """
    written: list[tuple[Recorded, ...]] = []

    def broken() -> Outcome[FetchCounts]:
        message = "value-sentinel-062"
        raise OSError(message)

    planned = [
        Planned(unit=Unit(stage="fetch", source="worklog"), act=lambda: Outcome(ending="done")),
        Planned(unit=Unit(stage="fetch", source="jira"), act=broken),
        acted("done"),
    ]
    with capture_logs() as events, pytest.raises(OSError, match="value-sentinel-062"):
        run_units(planned, (), datetime(2026, 11, 16, tzinfo=UTC), written.append, dry_run=False)
    assert [len(entries) for entries in written] == [1, 3]
    fetched, failed, indexed = written[-1]
    assert (fetched.ending, failed.ending, indexed.ending) == ("done", "failed", "not run")
    (problem,) = failed.problems
    assert problem.where == "jira"
    assert "OSError" in problem.reason
    assert "value-sentinel-062" not in problem.reason
    (end,) = [each for each in events if each["event"] == "fetch.end"]
    assert (end["status"], end["sources"]) == (ExitStatus.FAILED, ["worklog: done", "jira: failed"])


@pytest.fixture
def home(tmp_path: Path, monkeypatch: MonkeyPatch) -> Path:
    """Give a scratch home, no waiting between requests, and the API tokens by the environment."""
    scratch = tmp_path / "home"
    scratch.mkdir()
    monkeypatch.setenv("HOME", str(scratch))
    monkeypatch.setattr(time, "sleep", lambda _: None)
    for name, value in SIGN_IN.items():
        monkeypatch.setenv(name, value)
    return scratch


@pytest.fixture
def site(monkeypatch: MonkeyPatch) -> FakeSite:
    """Serve plan 004's scripted site to every client that a run makes."""
    fake = FakeSite()
    monkeypatch.setattr(http, "client", lambda *_: fake.client())
    return fake


@pytest.fixture
def endpoint() -> Iterator[str]:
    """Serve the tests' tiny model on this machine; give its address."""
    with serving(Scripted()) as url:
        yield url


def given(home: Path, url: str, *, confluence: bool = False) -> list[str]:
    """Write the settings: Jira, the work log, Confluence if asked, the tiny model at ``url``.

    Give the options that name them and the data directory.
    """
    worklog = home / "todo"
    if not worklog.exists():
        shutil.copytree(FIXTURE, worklog)
        settle(worklog)
    text = f'model = "tiny"\nembedding_url = "{url}"\n'
    text += f'[sources.jira]\nprojects = ["PRB"]\nsite = "{SITE}"\n'
    text += f'[sources.worklog]\npath = "{worklog}"\n'
    if confluence:
        text += f'[sources.confluence]\nspaces = ["MFS"]\nsite = "{SITE}"\n'
    config = home / "config.toml"
    config.write_text(text, "utf-8")
    return ["--config", str(config), "--data-dir", str(home / "data")]


def refreshed(capsys: CaptureFixture[str], *options: str) -> tuple[int, dict]:
    """Run ``refresh`` with these options as JSON; give its exit status and its document."""
    status = main(["refresh", "--yes", "--format", "json", *options])
    out = capsys.readouterr().out
    return status, (json.loads(out) if out else {})


def record_of(home: Path, run: str) -> tuple[dict, list[dict]]:
    """Give a run's configuration, and its units' entries, as its files hold them."""
    folder = home / "data" / "runs" / run
    configured = json.loads((folder / "configuration.json").read_text("utf-8"))
    return configured, json.loads((folder / "outcomes.json").read_text("utf-8"))["units"]


def tree(folder: Path) -> dict[str, bytes]:
    """Give each file under a folder, by its path from it, and its bytes."""
    return {
        path.relative_to(folder).as_posix(): path.read_bytes()
        for path in sorted(folder.rglob("*"))
        if path.is_file()
    }


@pytest.mark.usefixtures("site")
def test_a_refresh_runs_each_stage_in_order_and_records_it_without_any_secret(
    home: Path, endpoint: str, capsys: CaptureFixture[str]
) -> None:
    """Criterion 1: fetch and prepare per source, then index, then embed; no secret recorded.

    Jira's API token, given by the environment, is in no file under ``runs/``; the
    configuration records the sources of each stage, the period's options as times, and
    the settings. The result's units are the record's.
    """
    status, document = refreshed(capsys, *given(home, endpoint), *SINCE)
    assert status == ExitStatus.OK
    run = document["run"]
    assert list(document) == ["run", "exit_status", "units"]
    assert [(each["stage"], each["source"]) for each in document["units"]] == REFRESHED
    assert {each["ending"] for each in document["units"]} == {"done"}
    configured, entries = record_of(home, run)
    assert entries == document["units"]
    assert (configured["command"], configured["stages"]) == (
        "refresh",
        ["fetch", "prepare", "index", "embed"],
    )
    assert configured["sources"] == {
        "fetch": ["jira", "worklog"],
        "prepare": ["confluence", "jira", "worklog"],
    }
    assert configured["options"]["fetch"]["--since"] == "2026-10-02T00:00:00+00:00"
    assert configured["options"]["fetch"]["--until"] == configured["started"].replace("Z", "+00:00")
    assert configured["settings"]["sources"]["jira"]["email"] == "someone@example.invalid"
    assert "api_token" not in configured["settings"]["sources"]["jira"]
    files = tree(home / "data" / "runs")
    assert sorted(files) == [f"{run}/.lock", f"{run}/configuration.json", f"{run}/outcomes.json"]
    assert [path for path, data in files.items() if SENTINEL.encode() in data] == []


@pytest.mark.usefixtures("site")
def test_a_refresh_whose_fetch_of_one_source_fails_prepares_the_others_then_the_index(
    home: Path, endpoint: str, capsys: CaptureFixture[str]
) -> None:
    """Criterion 2: Confluence's fetch fails, a file of a page answering 404: exit 1.

    Its prepare is not run; Jira's and the work log's are, then index and embed.
    """
    status, document = refreshed(capsys, *given(home, endpoint, confluence=True), *SINCE)
    assert status == ExitStatus.FAILED
    endings = {(each["stage"], each["source"]): each["ending"] for each in document["units"]}
    assert endings == {
        ("fetch", "confluence"): "failed",
        ("fetch", "jira"): "done",
        ("fetch", "worklog"): "done",
        ("prepare", "confluence"): "not run",
        ("prepare", "jira"): "done",
        ("prepare", "worklog"): "done",
        ("index", None): "done",
        ("embed", None): "done",
    }
    assert not (home / "data" / "docs" / "confluence").exists()
    (resumable,) = logged_as(home, "run.resumable")
    assert resumable["resume"] == f"kb-mcp refresh --resume {document['run']}"


def test_a_resume_after_an_interruption_runs_only_the_units_not_done(
    home: Path,
    site: FakeSite,
    endpoint: str,
    monkeypatch: MonkeyPatch,
    capsys: CaptureFixture[str],
) -> None:
    """Criterion 3: Ctrl-C in the work log's prepare; the resume runs it, then index and embed.

    The units done are not run again: nothing is asked of the site, Jira's preparer is
    not called, and the copy stores and Jira's files of the mirror stay byte for byte.
    Their entries keep the first invocation's start. The resume given --since is refused,
    exit 2, naming it.
    """
    options = given(home, endpoint)

    def interrupting(*_: object, **__: object) -> None:
        raise KeyboardInterrupt

    with monkeypatch.context() as patch:
        patch.setattr(worklog_preparer, "prepare_worklog", interrupting)
        status, first = refreshed(capsys, *options, *SINCE)
    assert status == ExitStatus.INTERRUPTED
    assert [each["ending"] for each in first["units"]] == [
        "done",
        "done",
        "done",
        "done",
        "interrupted",
        "not run",
        "not run",
    ]
    run = first["run"]
    data = home / "data"
    kept = (tree(data / "raw"), tree(data / "copies"), tree(data / "docs" / "jira"))
    asked = len(site.asked)
    prepared: list[str] = []
    original = atlassian_preparer.prepare_source
    monkeypatch.setattr(
        atlassian_preparer,
        "prepare_source",
        lambda *each: prepared.append(each[3]) or original(*each),
    )
    assert (
        main(["refresh", "--yes", "--resume", run, *options, "--since", "1d"]) == ExitStatus.REFUSED
    )
    assert "--since: would change the configuration" in capsys.readouterr().err
    status, resumed = refreshed(capsys, "--resume", run, *options)
    assert status == ExitStatus.OK
    assert resumed["run"] == run
    assert [each["ending"] for each in resumed["units"]] == ["done"] * len(REFRESHED)
    invocations = [each["invocation"] for each in resumed["units"]]
    assert invocations[:4] == [each["invocation"] for each in first["units"][:4]]
    assert len(set(invocations[4:])) == 1
    assert invocations[4] != invocations[0]
    assert (len(site.asked), prepared) == (asked, [])
    assert (tree(data / "raw"), tree(data / "copies"), tree(data / "docs" / "jira")) == kept
    assert (data / "docs" / "worklog").is_dir()
    assert (data / "index.sqlite").is_file()


def test_a_resume_runs_again_a_unit_done_before_that_an_error_stopped_and_those_after(
    home: Path,
    site: FakeSite,
    endpoint: str,
    monkeypatch: MonkeyPatch,
    capsys: CaptureFixture[str],
) -> None:
    """Q6: an index done once, run again after Jira's fetch, raises: it is recorded failed.

    Jira's fetch fails first, the index and embed done. Its resume fetches Jira, then
    the index raises an error that nothing catches: the run fails, exit 1, its traceback
    logged, the index recorded failed by the error's type and embed not run, though both
    were done, and resumable. A second resume runs the index and embed alone.
    """
    options = given(home, endpoint)
    failed = Outcome(ending="failed", problems=(Problem(where="jira", reason="told"),))
    with monkeypatch.context() as patch:
        patch.setattr(fetcher, "run_fetch", lambda *_: failed)
        status, first = refreshed(capsys, *options, *SINCE)
    assert status == ExitStatus.FAILED
    run = first["run"]
    endings = {(each["stage"], each["source"]): each["ending"] for each in first["units"]}
    assert (endings["index", None], endings["embed", None]) == ("done", "done")

    def full(*_: object, **__: object) -> None:
        message = "value-sentinel-062"
        raise OSError(message)

    with monkeypatch.context() as patch:
        patch.setattr("kb_mcp.cli.commands._runs.update_index", full)
        assert main(["refresh", "--yes", "--resume", run, *options]) == ExitStatus.FAILED
    capsys.readouterr()
    _, entries = record_of(home, run)
    last = {(each["stage"], each["source"]): each for each in entries}
    assert [last[unit]["ending"] for unit in [("fetch", "jira"), ("index", None)]] == [
        "done",
        "failed",
    ]
    assert last["embed", None]["ending"] == "not run"
    (problem,) = last["index", None]["problems"]
    assert "OSError" in problem["reason"]
    assert "value-sentinel-062" not in json.dumps(entries)
    assert len(logged_as(home, "run.resumable")) == len(["first", "resumed"])
    assert len(logged_as(home, "run.failed")) == 1
    asked = len(site.asked)
    status, resumed = refreshed(capsys, "--resume", run, *options)
    assert status == ExitStatus.OK
    ran = [
        each
        for each, before in zip(resumed["units"], entries, strict=True)
        if each["invocation"] != before["invocation"]
    ]
    assert [(each["stage"], each["ending"]) for each in ran] == [
        ("index", "done"),
        ("embed", "done"),
    ]
    assert len(site.asked) == asked


@pytest.mark.usefixtures("site")
def test_a_run_that_an_error_stops_says_it_resumable_whatever_its_record_then_does(
    home: Path, endpoint: str, monkeypatch: MonkeyPatch, capsys: CaptureFixture[str]
) -> None:
    """The error passes as raised, exit 1, and run.resumable is said, its units not all done.

    Every write of its entries fails, as on a full disk: none is on disk, yet a resume has
    every unit to run. Or the index raises, and the record no longer reads once written,
    as on a volume gone: the error that passes, which run.failed logs, is the index's.
    """
    options = given(home, endpoint)

    def full(*_: object) -> None:
        message = "no space left"
        raise OSError(message)

    with monkeypatch.context() as patch:
        patch.setattr(RunRecord, "write_outcomes", full)
        assert main(["refresh", "--yes", *options, *SINCE]) == ExitStatus.FAILED
    assert len(logged_as(home, "run.resumable")) == 1
    read = RunRecord.read_outcomes

    def gone(record: RunRecord) -> tuple[Recorded, ...]:
        if record.folder is not None and (record.folder / "outcomes.json").exists():
            message = "outcomes.json: not read: OSError"
            raise RepresentationError(message)
        return read(record)

    def broken(*_: object, **__: object) -> None:
        message = "value-sentinel-062"
        raise OSError(message)

    with monkeypatch.context() as patch:
        patch.setattr(RunRecord, "read_outcomes", gone)
        patch.setattr("kb_mcp.cli.commands._runs.update_index", broken)
        assert main(["refresh", "--yes", *options, *SINCE]) == ExitStatus.FAILED
    capsys.readouterr()
    # The traceback's first exception is the one that passed; those it was raised from follow.
    _, failed = logged_as(home, "run.failed")
    raised = failed["exception"][0]
    assert (raised["exc_type"], raised["exc_value"]) == ("OSError", "value-sentinel-062")
    assert len(logged_as(home, "run.resumable")) == len(["full", "gone"])


def test_since_7d_is_recorded_as_a_time_which_the_first_attempt_and_the_resume_use(
    home: Path,
    endpoint: str,
    monkeypatch: MonkeyPatch,
    capsys: CaptureFixture[str],
) -> None:
    """Criterion 4, and the user: the units run from the record, its first invocation too.

    --since 7d is recorded as the time 7 days before the run's start. The record written
    is then made to say another time, before it is read back: the fetch, at its first
    attempt, reads that time, not one of its own from 7d; failed, the resume reads it too.
    """
    seen: list[datetime | None] = []

    def fetched(_settings: object, purview: Purview, *_: object) -> Outcome[FetchCounts]:
        seen.append(purview.since)
        return Outcome(ending="failed", problems=(Problem(where="jira", reason="told"),))

    monkeypatch.setattr(fetcher, "run_fetch", fetched)
    recorded = datetime(2026, 9, 1, tzinfo=UTC)
    written = RunRecord.write_configuration

    def rewritten(self: RunRecord, configuration: Configuration) -> None:
        fetch = {**configuration.options["fetch"], "--since": recorded.isoformat()}
        written(self, replace(configuration, options={**configuration.options, "fetch": fetch}))

    options = [*given(home, endpoint), "jira", "--since", "7d"]
    with monkeypatch.context() as patch:
        patch.setattr(RunRecord, "write_configuration", rewritten)
        status, first = refreshed(capsys, *options)
    run = first["run"]
    assert status == ExitStatus.FAILED
    configured, _ = record_of(home, run)
    assert configured["options"]["fetch"]["--since"] == recorded.isoformat()
    assert seen == [recorded]
    seen.clear()
    status, _ = refreshed(capsys, "--resume", run, *given(home, endpoint))
    assert status == ExitStatus.FAILED
    assert seen == [recorded]


def test_the_settings_recorded_are_those_that_the_first_attempt_and_the_resume_use(
    home: Path, endpoint: str, monkeypatch: MonkeyPatch, capsys: CaptureFixture[str]
) -> None:
    """The user: the units run from the record, its settings as its options, never as given.

    The record written is made to name another Jira project than the settings file does,
    before it is read back: Jira's fetch, at its first attempt, reads that project; it is
    interrupted. The record then names a third project, and the settings file a fourth:
    the resume reads the record's.
    """
    seen: list[list[str]] = []

    def fetched(_settings: object, purview: Purview, *_: object) -> Outcome[FetchCounts]:
        seen.append([scope.key for scope in purview.scopes])
        if len(seen) == 1:
            raise KeyboardInterrupt
        return Outcome(ending="failed", problems=(Problem(where="jira", reason="told"),))

    monkeypatch.setattr(fetcher, "run_fetch", fetched)
    written = RunRecord.write_configuration

    def rewritten(self: RunRecord, configuration: Configuration) -> None:
        settings = json.loads(json.dumps(configuration.settings))
        settings["sources"]["jira"]["projects"] = ["REC"]
        written(self, replace(configuration, settings=settings))

    options = given(home, endpoint)
    with monkeypatch.context() as patch:
        patch.setattr(RunRecord, "write_configuration", rewritten)
        status, first = refreshed(capsys, *options, "jira", *SINCE)
    assert (status, seen) == (ExitStatus.INTERRUPTED, [["REC"]])
    run = first["run"]
    configured = home / "data" / "runs" / run / "configuration.json"
    held = json.loads(configured.read_text("utf-8"))
    assert held["settings"]["sources"]["jira"]["projects"] == ["REC"]
    held["settings"]["sources"]["jira"]["projects"] = ["RES"]
    configured.write_text(json.dumps(held), "utf-8")
    config = home / "config.toml"
    config.write_text(config.read_text("utf-8").replace('["PRB"]', '["CFG"]'), "utf-8")
    status, _ = refreshed(capsys, "--resume", run, *options)
    assert (status, seen) == (ExitStatus.FAILED, [["REC"], ["RES"]])


def test_since_7d_is_recorded_as_the_time_7_days_before_the_run_s_start(
    home: Path, endpoint: str, monkeypatch: MonkeyPatch, capsys: CaptureFixture[str]
) -> None:
    """Criterion 4: the recorded --since is the start, less 7 days; the units use it."""
    seen: list[datetime | None] = []

    def fetched(_settings: object, purview: Purview, *_: object) -> Outcome[FetchCounts]:
        seen.append(purview.since)
        return Outcome(ending="done", counts=FetchCounts())

    monkeypatch.setattr(fetcher, "run_fetch", fetched)
    _, first = refreshed(capsys, *given(home, endpoint), "jira", "--since", "7d")
    configured, _ = record_of(home, first["run"])
    started = datetime.fromisoformat(configured["started"])
    since = datetime.fromisoformat(configured["options"]["fetch"]["--since"])
    assert since == started - timedelta(days=7)
    assert seen == [since]


def files_but_times(folder: Path) -> dict[str, bytes]:
    """Give a folder's files but those that record times: coverage, a source's as-of time."""
    return {
        path: data
        for path, data in tree(folder).items()
        if path.rpartition("/")[2] not in {"coverage.json", "_source.json", "copies.json"}
    }


def indexed(index: Path) -> tuple[list[tuple[object, ...]], list[tuple[object, ...]]]:
    """Give the index's documents, as its rows hold them, and its chunks' keys."""
    with closing(sqlite3.connect(index)) as database:
        documents = database.execute("SELECT * FROM documents ORDER BY path").fetchall()
        chunks = database.execute("SELECT key FROM chunks ORDER BY key").fetchall()
    return documents, chunks


@pytest.mark.usefixtures("site")
def test_a_refresh_s_configuration_run_twice_changes_no_document(
    home: Path, endpoint: str, capsys: CaptureFixture[str]
) -> None:
    """Criterion 5: nothing changed at the fixtures, the second run changes no document.

    In the raw store and the work log's copy store, the mirror and the index; what
    records times alone may change: the coverage, the copy store's and the sources'
    as-of times, the index's build.
    """
    options = [*given(home, endpoint), *SINCE]
    data = home / "data"
    status, first = refreshed(capsys, *options)
    assert status == ExitStatus.OK
    copies = json.loads((data / "copies" / "worklog" / "copies.json").read_text("utf-8"))
    before = (files_but_times(data / "raw"), files_but_times(data / "docs"))
    built = indexed(data / "index.sqlite")
    status, second = refreshed(capsys, *options)
    assert status == ExitStatus.OK
    assert {each["ending"] for each in second["units"]} == {"done"}
    again = json.loads((data / "copies" / "worklog" / "copies.json").read_text("utf-8"))
    assert {**again, "as_of": None} == {**copies, "as_of": None}
    assert (files_but_times(data / "raw"), files_but_times(data / "docs")) == before
    assert indexed(data / "index.sqlite") == built
    # Each refresh is a run of its own, recorded in a folder of its own.
    assert {path.name for path in (data / "runs").iterdir()} == {first["run"], second["run"]}
    assert first["run"] != second["run"]


@pytest.mark.usefixtures("site")
def test_a_stage_command_s_run_is_resumed_by_refresh_as_that_stage_alone(
    home: Path, endpoint: str, monkeypatch: MonkeyPatch, capsys: CaptureFixture[str]
) -> None:
    """Any run's id: a fetch interrupted is resumed as a fetch, its unit done kept.

    Its text names the run first; the resume says what it will do, and its result
    names the unit of the earlier invocation by when that one started.
    """
    options = given(home, endpoint)
    with monkeypatch.context() as patch:
        patch.setattr(
            "kb_mcp.sources.worklog.fetch.app.fetcher.fetch_worklog",
            lambda *_, **__: (_ for _ in ()).throw(KeyboardInterrupt),
        )
        assert main(["fetch", "--yes", *options, *SINCE]) == ExitStatus.INTERRUPTED
    out, _ = capsys.readouterr()
    first, *rows = out.splitlines()
    run = first.removeprefix("run ")
    assert [row for row in rows if not row.startswith(" ")] == [
        "jira: done",
        "worklog: interrupted",
    ]
    assert main(["refresh", "--yes", "--resume", run, *options]) == ExitStatus.OK
    out, err = capsys.readouterr()
    assert f"refresh --resume {run}: the run of fetch, started " in err
    assert "  done: fetch jira\n  to run: fetch worklog (interrupted)\n" in err
    configured, entries = record_of(home, run)
    assert configured["stages"] == ["fetch"]
    assert [(each["source"], each["ending"]) for each in entries] == [
        ("jira", "done"),
        ("worklog", "done"),
    ]
    assert out.startswith(f"run {run}\nfetch jira: done, in the invocation of ")
    assert "\nfetch worklog: done\n  documents read: " in out


def test_a_resume_says_what_it_will_do_and_what_this_invocation_does_of_telemetry(
    home: Path, endpoint: str, monkeypatch: MonkeyPatch, capsys: CaptureFixture[str]
) -> None:
    """Q7: telemetry is this invocation's, so its echo says it on, though the settings are not.

    In place of the settings, which are the run's as recorded, it says what the resume
    will do; then, as any echo, telemetry on and where, and the command to copy, which
    resumes the run again, without an option that a resume refuses. Nothing listens there.
    """
    options = given(home, endpoint)
    with monkeypatch.context() as patch:
        patch.setattr(
            "kb_mcp.sources.worklog.fetch.app.fetcher.fetch_worklog",
            lambda *_, **__: (_ for _ in ()).throw(KeyboardInterrupt),
        )
        assert main(["fetch", "--yes", *options, "worklog"]) == ExitStatus.INTERRUPTED
    run = capsys.readouterr().out.splitlines()[0].removeprefix("run ")
    with nothing_listening() as url:
        listening = url.removesuffix("/v1")
        monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", listening)
        assert main(["refresh", "--yes", "--resume", run, *options]) == ExitStatus.OK
    err = capsys.readouterr().err
    assert f"refresh --resume {run}: the run of fetch, started " in err
    assert "  to run: fetch worklog (interrupted)\n" in err
    assert "with these settings" not in err
    assert f"telemetry: on, to {listening} (OTEL_EXPORTER_OTLP_ENDPOINT)\n" in err
    copied = shlex.split(err[err.index("kb-mcp refresh") :].replace("\\\n", "").split("\n", 1)[0])
    assert copied == ["kb-mcp", "refresh", *options, "--resume", run]


@pytest.mark.usefixtures("site")
def test_a_resume_is_refused_for_no_record_another_data_directory_or_no_consent(
    home: Path, endpoint: str, monkeypatch: MonkeyPatch, capsys: CaptureFixture[str]
) -> None:
    """Q7: each exit 2 before any unit, naming the run; a source named, too; a run held, too.

    An endpoint off this machine needs this invocation's --allow-remote-embeddings while
    embed has to run again; a run held by another invocation refuses the resume; so does
    a run of a source that the settings no longer configure.
    """
    options = given(home, endpoint)
    assert main(["refresh", "--yes", "--resume", RUN, *options]) == ExitStatus.REFUSED
    assert f"run {RUN}: no record under " in capsys.readouterr().err
    with monkeypatch.context() as patch:
        patch.setattr(
            "kb_mcp.cli.commands._runs.fill_and_prune",
            lambda *_: (_ for _ in ()).throw(KeyboardInterrupt),
        )
        status, document = refreshed(capsys, *options, *SINCE)
    assert status == ExitStatus.INTERRUPTED
    run = document["run"]
    moved = home / "moved"
    shutil.copytree(home / "data", moved)
    elsewhere = [*options[:2], "--data-dir", str(moved)]
    assert main(["refresh", "--yes", "--resume", run, *elsewhere]) == ExitStatus.REFUSED
    assert f"run {run}: recorded for the data directory {home / 'data'}" in (
        capsys.readouterr().err
    )
    assert main(["refresh", "--yes", "--resume", run, *options, "jira"]) == ExitStatus.REFUSED
    assert "jira: would change the configuration" in capsys.readouterr().err
    with RunRecord(home / "data" / "runs" / run).holding():
        assert main(["refresh", "--yes", "--resume", run, *options]) == ExitStatus.REFUSED
    assert ("error", "run.busy") in [
        (each["level"], each["event"]) for each in logged_as(home, "run.busy")
    ]
    capsys.readouterr()
    # Recorded off this machine, the endpoint needs this invocation's consent.
    configured = home / "data" / "runs" / run / "configuration.json"
    held = json.loads(configured.read_text("utf-8"))
    held["settings"]["embedding_url"] = "https://embeddings.example.invalid/v1"
    configured.write_text(json.dumps(held), "utf-8")
    assert main(["refresh", "--yes", "--resume", run, *options]) == ExitStatus.REFUSED
    assert f"run {run}: embedding_url: " in capsys.readouterr().err
    held["sources"]["fetch"] = ["clientjira", "worklog"]
    configured.write_text(json.dumps(held), "utf-8")
    assert main(["refresh", "--yes", "--resume", run, *options]) == ExitStatus.REFUSED
    assert f"run {run}: source clientjira: no longer configured" in capsys.readouterr().err


@pytest.mark.parametrize(
    "command",
    [["fetch", "--since", "banana"], ["refresh", "--until", "banana"]],
    ids=["fetch", "refresh"],
)
def test_a_period_that_no_source_taken_reads_is_ignored_as_before(
    home: Path, endpoint: str, capsys: CaptureFixture[str], command: list[str]
) -> None:
    """As before 062, an option that no source taken declares is said ignored, never read.

    Confluence configured, the work log named: the work log is fetched, the run records no
    option of a fetch, and exits 0, whether or not the value would read.
    """
    stage, flag, value = command
    options = given(home, endpoint, confluence=True)
    status = main([stage, "--yes", "--format", "json", *options, "worklog", flag, value])
    out, err = capsys.readouterr()
    assert status == ExitStatus.OK
    assert f"{flag}: ignored by worklog\n" in err
    configured, entries = record_of(home, json.loads(out)["run"])
    assert configured["options"]["fetch"] == {}
    assert ("fetch", "worklog", "done") in [
        (each["stage"], each["source"], each["ending"]) for each in entries
    ]
    assert (home / "data" / "copies" / "worklog" / "copies.json").is_file()


@pytest.mark.usefixtures("site")
def test_a_resume_refuses_a_record_that_lacks_what_a_stage_needs_naming_its_file(
    home: Path, endpoint: str, monkeypatch: MonkeyPatch, capsys: CaptureFixture[str]
) -> None:
    """The data layout: a field missing, or refused, is refused by its file and field, exit 2.

    Its options emptied, whose index's --rebuild its index reads; its fetch without an
    option that Jira's fetch declares; a setting refused, by its path in the settings. A
    folder copied under another run's id, whose record names its own, is refused alike.
    """
    options = given(home, endpoint)
    with monkeypatch.context() as patch:
        patch.setattr(
            "kb_mcp.cli.commands._runs.fill_and_prune",
            lambda *_: (_ for _ in ()).throw(KeyboardInterrupt),
        )
        status, document = refreshed(capsys, *options, *SINCE)
    assert status == ExitStatus.INTERRUPTED
    run = document["run"]
    configured = home / "data" / "runs" / run / "configuration.json"
    held = json.loads(configured.read_text("utf-8"))
    where = f"run {run}: runs/{run}/configuration.json: "
    for damaged, said in [
        ({**held, "options": {}}, "options: fetch's and index's"),
        (
            {**held, "options": {**held["options"], "fetch": {"--since": None}}},
            "options.fetch.--until: missing",
        ),
        ({**held, "settings": {**held["settings"], "data_dir": 5}}, "settings: data_dir: "),
    ]:
        configured.write_text(json.dumps(damaged), "utf-8")
        assert main(["refresh", "--yes", "--resume", run, *options]) == ExitStatus.REFUSED
        (line,) = [each for each in capsys.readouterr().err.splitlines() if where in each]
        assert said in line
    configured.write_text(json.dumps(held), "utf-8")
    copied = "fedcba9876543210"
    shutil.copytree(configured.parent, configured.parent.parent / copied)
    assert main(["refresh", "--yes", "--resume", copied, *options]) == ExitStatus.REFUSED
    assert f"run {copied}: runs/{copied}/configuration.json: run: " in capsys.readouterr().err
    assert main(["refresh", "--yes", "--resume", run, *options]) == ExitStatus.OK


@pytest.mark.usefixtures("site")
def test_a_record_changed_once_read_and_before_the_run_is_held_refuses_it(
    home: Path, endpoint: str, monkeypatch: MonkeyPatch, capsys: CaptureFixture[str]
) -> None:
    """Another program may change the record while the resume asks: refused, exit 2, by it.

    Once the entry has read the record, it is made to refuse a setting, then removed: the
    run, once it holds the record, reads it again and refuses it, naming it, no unit run.
    """
    options = given(home, endpoint)
    with monkeypatch.context() as patch:
        patch.setattr(
            "kb_mcp.cli.commands._runs.fill_and_prune",
            lambda *_: (_ for _ in ()).throw(KeyboardInterrupt),
        )
        status, document = refreshed(capsys, *options, *SINCE)
    assert status == ExitStatus.INTERRUPTED
    run = document["run"]
    folder = home / "data" / "runs" / run
    held = json.loads((folder / "configuration.json").read_text("utf-8"))
    entries = (folder / "outcomes.json").read_bytes()
    read = resumption.resumption

    def changing(*arguments: object, **named: object) -> object:
        found = read(*arguments, **named)  # type: ignore[arg-type]
        changed = {**held, "settings": {**held["settings"], "data_dir": 5}}
        (folder / "configuration.json").write_text(json.dumps(changed), "utf-8")
        return found

    monkeypatch.setattr("kb_mcp.cli.commands._shared.resumption", changing)
    assert main(["refresh", "--yes", "--resume", run, *options]) == ExitStatus.REFUSED
    said = f"run {run}: runs/{run}/configuration.json: settings: data_dir: "
    assert said in capsys.readouterr().err
    (refused,) = logged_as(home, "run.refused")
    assert refused["reason"].startswith(said)
    assert (folder / "outcomes.json").read_bytes() == entries

    def removing(*arguments: object, **named: object) -> object:
        found = read(*arguments, **named)  # type: ignore[arg-type]
        (folder / "configuration.json").unlink()
        return found

    (folder / "configuration.json").write_text(json.dumps(held), "utf-8")
    monkeypatch.setattr("kb_mcp.cli.commands._shared.resumption", removing)
    assert main(["refresh", "--yes", "--resume", run, *options]) == ExitStatus.REFUSED
    assert str(folder / "configuration.json") in capsys.readouterr().err
    assert (folder / "outcomes.json").read_bytes() == entries


def test_the_run_s_start_and_the_invocation_recorded_are_its_log_file_s_instant(
    home: Path, endpoint: str, monkeypatch: MonkeyPatch, capsys: CaptureFixture[str]
) -> None:
    """The data layout: an entry's invocation names that invocation's log file.

    One instant names the log file, starts the run and its invocation: the clock that
    names the log file is made to say a time of its own, which the record says too.
    """
    instant = datetime(2026, 1, 2, 3, 4, 5, 678000, tzinfo=UTC)

    class Clock(datetime):
        @classmethod
        def now(cls, _tz: tzinfo | None = None) -> datetime:
            return instant

    monkeypatch.setattr("kb_mcp.observability.app.observed.datetime", Clock)
    options = given(home, endpoint)
    assert main(["fetch", "--yes", "--format", "json", *options, "worklog"]) == ExitStatus.OK
    configured, entries = record_of(home, json.loads(capsys.readouterr().out)["run"])
    assert datetime.fromisoformat(configured["started"]) == instant
    assert [datetime.fromisoformat(each["invocation"]) for each in entries] == [instant]
    logs = {path.name for path in user_log_folder(home.resolve()).iterdir()}
    assert f"fetch-20260102T030405Z-{os.getpid()}.jsonl" in logs


@pytest.mark.parametrize("stage", ["index", "embed"])
def test_index_or_embed_on_a_data_directory_that_does_not_exist_makes_none(
    home: Path, endpoint: str, capsys: CaptureFixture[str], stage: str
) -> None:
    """As before 062: a data directory mistyped is not made; the run fails, exit 1.

    It has nothing to read, so it records nothing, which its text says after its id, and
    no resume of it is offered.
    """
    mistyped = home / "typo"
    options = [*given(home, endpoint)[:2], "--data-dir", str(mistyped)]
    assert main([stage, "--yes", *options]) == ExitStatus.FAILED
    assert capsys.readouterr().out.splitlines()[0].endswith(", not recorded")
    assert not mistyped.exists()
    assert logged_as(home, "run.resumable") == []


def test_a_dry_run_records_nothing(
    home: Path, site: FakeSite, endpoint: str, capsys: CaptureFixture[str]
) -> None:
    """Q8: it writes nothing, so neither its record; its result names its run, not recorded.

    Its text says so after the id, which no resume takes; its JSON keeps the key.
    """
    options = given(home, endpoint)
    assert main(["fetch", "--dry-run", *options, *SINCE, "jira"]) == ExitStatus.OK
    first = capsys.readouterr().out.splitlines()[0]
    assert first.startswith("run ")
    assert first.endswith(", not recorded")
    assert main(["fetch", "--dry-run", "--format", "json", *options, *SINCE, "jira"]) == 0
    run = json.loads(capsys.readouterr().out)["run"]
    assert not (home / "data" / "runs").exists()
    assert site.asked
    assert main(["refresh", "--yes", "--resume", run, *options]) == ExitStatus.REFUSED
    assert f"run {run}: no record under " in capsys.readouterr().err
    assert main(["fetch", "--yes", *options, *SINCE, "jira"]) == ExitStatus.OK
    assert not capsys.readouterr().out.splitlines()[0].endswith(", not recorded")
