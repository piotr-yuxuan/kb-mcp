"""``fetch`` and ``prepare`` as plan 031 defines them: what each takes, says, runs and exits.

The expectations come from its section "``fetch`` and ``prepare``: a list of sources", and
from plans 017 and 030 before it: a row for each source's stage, with its result, and the
sources, their options and light checks the declarations'. The Atlassian sources are served
by plan 004's scripted site, the work log is the invented fixture; each test has a scratch
home, and terminals are injected or ``--yes`` given.
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
from types import SimpleNamespace
from typing import TYPE_CHECKING, Self

import pytest
from opentelemetry import trace
from structlog.testing import capture_logs

from kb_mcp.cli.app import sources as sources_app
from kb_mcp.cli.app.sources import run_each
from kb_mcp.cli.domain.sources import chosen, fetch_described, given
from kb_mcp.cli.main import main, parser
from kb_mcp.kernel.exit_status import Ending, ExitStatus
from kb_mcp.kernel.outcome import Outcome, Problem
from kb_mcp.mirror.adapters import pandoc as pandoc_adapter
from kb_mcp.mirror.adapters.mirror_files import Changes
from kb_mcp.mirror.adapters.pandoc import (
    Pandoc,
    PandocFailedError,
    PandocMissingError,
)
from kb_mcp.sources.atlassian.declared import CONFLUENCE, JIRA
from kb_mcp.sources.atlassian.fetch.adapters import http
from kb_mcp.sources.atlassian.fetch.adapters.raw_store import RawStore, StoreBusyError
from kb_mcp.sources.atlassian.fetch.adapters.session_file import COOKIES, write_cookies
from kb_mcp.sources.atlassian.fetch.app import fetcher
from kb_mcp.sources.atlassian.fetch.app.fetching import FetchCounts
from kb_mcp.sources.atlassian.fetch.domain import names
from kb_mcp.sources.atlassian.fetch.domain.coverage import Scope
from kb_mcp.sources.atlassian.prepare.app import prepare as atlassian_prepare
from kb_mcp.sources.atlassian.prepare.app import preparer
from kb_mcp.sources.declaration import Option
from kb_mcp.sources.registry import SOURCES
from kb_mcp.sources.stages import SourceRun
from kb_mcp.sources.worklog.declared import WORKLOG
from tests.composed import MODEL, sourced
from tests.reference import Emitted
from tests.test_confirmation import QUESTION, Terminal
from tests.test_fetching import PAGES, SITE, FakeSite
from tests.test_incremental_fetch import FIRST, SECOND, WEEK, RefreshSite, stored_pages
from tests.test_prepare_worklog import FIXTURE, Counting, settle, snapshot

if TYPE_CHECKING:
    import argparse
    from collections.abc import Callable, Mapping
    from datetime import datetime

    from _pytest.capture import CaptureFixture
    from _pytest.monkeypatch import MonkeyPatch
    from opentelemetry.sdk.metrics.export import Metric

    from kb_mcp.config.domain.settings import Settings
    from kb_mcp.sources.declaration import Connector, Source
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
}
# The work log's documents in the fixture, by type: thirteen entries, two days, eight
# meetings and six transcripts, one of them under meetings/.
WORKLOG_BY_TYPE = {"entry": 13, "day": 2, "meeting": 8, "transcript": 6}
WORKLOG_DOCUMENTS = sum(WORKLOG_BY_TYPE.values())
# The keys of each row of fetch's and prepare's JSON, in order: its source, then its outcome.
ROW_KEYS = ["source", "ending", "counts", "problems", "warnings"]
# The period of a fetch that covers what the scripted sites serve: the week before FIRST.
SINCE = {"--since": (FIRST - WEEK).isoformat()}


def arguments(stage: str, *given: str) -> argparse.Namespace:
    """Parse a command's arguments as the command does."""
    return parser().parse_args([stage, *given])


@pytest.mark.parametrize(
    ("stage", "given", "taken"),
    [
        ("fetch", (), ["confluence", "jira"]),
        ("fetch", ("jira",), ["jira"]),
        ("fetch", ("jira", "confluence", "jira"), ["confluence", "jira"]),
        ("prepare", (), ["confluence", "jira", "worklog"]),
        ("prepare", ("jira",), ["jira"]),
        ("prepare", ("worklog", "jira"), ["jira", "worklog"]),
    ],
)
def test_names_choose_among_the_sources_each_once_in_the_registry_s_order(
    stage: str, given: tuple[str, ...], taken: list[str]
) -> None:
    """No name takes every one that the command can run; a name, those named alone."""
    found, _ = chosen(arguments(stage, *given), CONFIGURED)
    assert [source.name for source in found] == taken


def test_what_each_command_leaves_out_says_why() -> None:
    """A fetch needs a source's setting; a prepare, of a source read in place alone."""
    settings = CONFIGURED | {"sources.jira.projects": (), "sources.worklog.path": None}
    found, left = chosen(arguments("fetch"), settings)
    assert [source.name for source in found] == ["confluence"]
    assert left == {"jira": "not configured", "worklog": "read in place, it has nothing to fetch"}
    found, left = chosen(arguments("prepare"), settings)
    assert [source.name for source in found] == ["confluence", "jira"]
    assert left == {"worklog": "not configured"}
    found, left = chosen(arguments("prepare", "confluence"), CONFIGURED)
    assert [source.name for source in found] == ["confluence"]
    assert left == {"jira": "not named", "worklog": "not named"}


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
        text += f'[accounts.atlassian]\nsite = "{SITE}"\n[sources.confluence]\nspaces = ["MFS"]\n'
        text += '[sources.jira]\nprojects = ["PRB"]\n'
    if worklog is not None:
        text += f'[sources.worklog]\npath = "{worklog}"\n'
    config = home / "config.toml"
    config.write_text(text, "utf-8")
    return config


def command(home: Path, config: Path, stage: str, *more: str) -> list[str]:
    """Give a command's arguments: this settings file, the data in the home, then ``more``."""
    return [stage, "--config", str(config), "--data-dir", str(home / "data"), *more]


@pytest.mark.parametrize(
    ("stage", "given", "named"),
    [
        ("prepare", ("worklog",), "worklog: not configured; set sources.worklog.path"),
        ("fetch", ("jira",), "jira: not configured; set sources.jira.projects"),
        ("fetch", (), "nothing to fetch: none of its sources is configured"),
    ],
)
def test_a_choice_that_leaves_nothing_to_run_exits_2_saying_why(
    home: Path, capsys: CaptureFixture[str], stage: str, given: tuple[str, ...], named: str
) -> None:
    """A source named without its setting, or none configured, before anything is asked."""
    config = settings_file(home, None)
    assert main(command(home, config, stage, "--yes", *given)) == ExitStatus.REFUSED
    assert named in capsys.readouterr().err
    assert not (home / "data").exists()


def test_a_registry_with_nothing_to_prepare_is_refused(
    home: Path, capsys: CaptureFixture[str]
) -> None:
    """The work log alone, not configured: exit 2, since no store is kept either."""
    config = settings_file(home, None)
    given = command(home, config, "prepare", "--yes")
    assert main(given, sourced(WORKLOG)) == ExitStatus.REFUSED
    assert "nothing to prepare: none of its sources is configured" in capsys.readouterr().err


@pytest.mark.parametrize("stage", ["fetch", "prepare"])
def test_a_source_that_does_not_exist_is_refused_by_the_options(
    home: Path, capsys: CaptureFixture[str], stage: str
) -> None:
    """Argparse names the choices."""
    config = settings_file(home, None, atlassian=True)
    with pytest.raises(SystemExit) as stopped:
        main(command(home, config, stage, "gitlab"))
    assert stopped.value.code == ExitStatus.REFUSED
    assert "invalid choice: 'gitlab'" in capsys.readouterr().err


def test_an_option_that_no_setting_holds_is_said_ignored_by_a_source_that_declares_none() -> None:
    """Of the sources taken: --since by Jira, under a registry whose Jira has no option."""
    plain = replace(
        JIRA, scope_types=(replace(names.PROJECT, option=None),), options=(), described=None
    )
    registry = sourced(CONFLUENCE, plain, WORKLOG)
    given = parser(sources=registry).parse_args(["fetch", "--since", "7d"])
    assert "--since: ignored by jira" in fetch_described(given, CONFIGURED)
    alone = parser(sources=registry).parse_args(["fetch", "--since", "7d", "confluence"])
    assert not [line for line in fetch_described(alone, CONFIGURED) if "ignored" in line]


def test_an_option_of_a_source_without_a_fetcher_is_no_flag_and_said_of_none() -> None:
    """A source's options are its fetch's: the parser offers none, and the summary reads none."""
    noted = replace(WORKLOG, options=(Option(flag="--tag", help="a tag"),))
    registry = sourced(CONFLUENCE, JIRA, noted)
    given = parser(sources=registry).parse_args(["fetch"])
    assert not hasattr(given, "tag")
    assert "source confluence: spaces MFS" in fetch_described(given, CONFIGURED)


def test_a_dry_run_of_the_work_log_alone_writes_nothing_and_ignores_nothing(
    home: Path, worklog: Path, capsys: CaptureFixture[str]
) -> None:
    """Nothing written, of the folder nor the data; none of its settings said ignored."""
    config = settings_file(home, worklog)
    before = snapshot(worklog)
    assert main(command(home, config, "prepare", "worklog", "--dry-run")) == 0
    assert "ignored" not in capsys.readouterr().err
    assert snapshot(worklog) == before
    assert not (home / "data").exists()


def test_a_prepare_of_the_work_log_alone_ignores_nothing_when_given_nothing_to_ignore(
    home: Path, worklog: Path, capsys: CaptureFixture[str]
) -> None:
    """Its table alone in the file: nothing said to be ignored; its counts under its row."""
    config = settings_file(home, worklog)
    assert main(command(home, config, "prepare", "worklog", "--yes")) == 0
    captured = capsys.readouterr()
    assert "ignored" not in captured.err
    assert captured.out.startswith(f"worklog: done\n  documents: {WORKLOG_DOCUMENTS}\n")


@pytest.mark.parametrize(
    ("stage", "lines"),
    [
        (
            "fetch",
            (
                "source confluence: spaces MFS\n",
                "source jira: left out, not named\n",
                "source worklog: left out, read in place, it has nothing to fetch\n",
            ),
        ),
        (
            "prepare",
            (
                "source confluence: all that its store holds\n",
                "source jira: left out, not named\n",
                "source worklog: left out, not named\n",
            ),
        ),
    ],
)
def test_a_command_asks_once_after_naming_each_source_taken_and_left_out(
    home: Path, worklog: Path, monkeypatch: MonkeyPatch, stage: str, lines: tuple[str, ...]
) -> None:
    """On terminals: each source taken, with what it covers, each left out, one question."""
    config = settings_file(home, worklog, atlassian=True)
    stderr = Terminal()
    monkeypatch.setattr("sys.stdin", Terminal("n\n"))
    monkeypatch.setattr("sys.stderr", stderr)
    assert main(command(home, config, stage, "confluence")) == ExitStatus.FAILED
    said = stderr.getvalue()
    asked = said.index(QUESTION)
    for line in lines:
        assert -1 < said.index(line) < asked
    assert said.count(QUESTION) == 1
    assert not (home / "data").exists()


def test_an_index_with_nothing_prepared_says_so_and_names_the_command(
    home: Path, capsys: CaptureFixture[str]
) -> None:
    """``prepare`` done with no document leaves no mirror, which ``index`` says, exit 1."""
    config = settings_file(home, None)
    assert main(command(home, config, "prepare", "--yes", "jira")) == ExitStatus.OK
    assert main(command(home, config, "index", "--yes")) == ExitStatus.FAILED
    assert "nothing is prepared yet; `kb-mcp prepare` writes it" in capsys.readouterr().err


def test_a_machine_with_the_work_log_alone_has_nothing_to_fetch_and_something_to_prepare(
    home: Path, worklog: Path, capsys: CaptureFixture[str]
) -> None:
    """The first exits 2, saying of its own sources, as the how-to tells; the second runs."""
    config = settings_file(home, worklog)
    assert main(command(home, config, "fetch", "--yes")) == ExitStatus.REFUSED
    assert "nothing to fetch: none of its sources is configured" in capsys.readouterr().err
    assert main(command(home, config, "prepare", "--yes", "worklog")) == ExitStatus.OK


def test_a_work_log_named_by_an_empty_variable_is_not_configured(
    home: Path, monkeypatch: MonkeyPatch, capsys: CaptureFixture[str]
) -> None:
    """An empty variable sets nothing, for a path as for any setting: named, exit 2."""
    monkeypatch.setenv("KB_MCP_SOURCES__WORKLOG__PATH", "")
    config = settings_file(home, None)
    assert main(command(home, config, "prepare", "--yes", "worklog")) == ExitStatus.REFUSED
    assert "worklog: not configured; set sources.worklog.path" in capsys.readouterr().err


def test_a_prepare_without_a_site_runs_and_says_what_it_costs(
    home: Path, worklog: Path, capsys: CaptureFixture[str]
) -> None:
    """Its documents get no address: said once, of a source of that account alone."""
    config = settings_file(home, worklog)
    line = (
        "accounts.atlassian.site: not set; any documents of confluence, jira get no address there\n"
    )
    assert main(command(home, config, "prepare", "--yes")) == ExitStatus.OK
    assert capsys.readouterr().err.count(line) == 1
    assert main(command(home, config, "prepare", "--yes", "worklog")) == ExitStatus.OK
    assert line not in capsys.readouterr().err
    assert main(command(home, config, "prepare", "--yes", "--site", SITE)) == ExitStatus.OK
    assert line not in capsys.readouterr().err


def test_a_false_value_of_a_source_left_out_is_said_not_applied_as_a_true_one_is(
    home: Path, worklog: Path, capsys: CaptureFixture[str]
) -> None:
    """What holds a value is not the same as what is true: ``archives = false`` is one."""
    config = settings_file(home, worklog)
    config.write_text(config.read_text("utf-8") + "archives = false\n", "utf-8")
    assert main(command(home, config, "prepare", "--dry-run", "confluence")) == ExitStatus.OK
    err = capsys.readouterr().err
    assert "sources.worklog.archives: False (not applied: worklog not named)\n" in err
    assert "not in the command: sources.worklog.archives" not in err


def test_a_list_emptied_of_a_source_not_named_is_not_said_to_be_lost_by_the_command(
    home: Path, signed_in: FakeSite, monkeypatch: MonkeyPatch, capsys: CaptureFixture[str]
) -> None:
    """The command, run again, does not read it: nothing to carry."""
    monkeypatch.setenv("KB_MCP_SOURCES__CONFLUENCE__SPACES", "[]")
    config = settings_file(home, None, atlassian=True)
    given = command(home, config, "fetch", "--dry-run", "--since", "2026-10-02", "jira")
    assert main(given) == ExitStatus.OK
    assert "not in the command: sources.confluence.spaces" not in capsys.readouterr().err
    assert signed_in.asked


def test_a_source_read_in_place_is_said_by_its_settings(
    home: Path, worklog: Path, capsys: CaptureFixture[str]
) -> None:
    """What it covers, in a prepare, as a store's is in a fetch."""
    config = settings_file(home, worklog)
    assert main(command(home, config, "prepare", "worklog", "--dry-run")) == 0
    assert f"source worklog: path {worklog}, archives True\n" in capsys.readouterr().err


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


def test_json_is_one_document_with_a_row_per_source(
    home: Path, worklog: Path, signed_in: FakeSite, capsys: CaptureFixture[str]
) -> None:
    """exit_status, then each source's row; one shape for a fetch as for a prepare.

    The file that fails, a page's, fails Confluence's fetch alone. A row is its fetcher's
    or preparer's outcome, under its source's name: its ending, its counts, problems and
    warnings, and no other key.
    """
    config = settings_file(home, worklog, atlassian=True)
    given = ("--yes", "--since", "2026-10-02", "--format", "json")
    status = main(command(home, config, "fetch", *given))
    document = json.loads(capsys.readouterr().out)
    assert document["exit_status"] == status == ExitStatus.FAILED  # one file fails
    assert sorted(document) == ["exit_status", "sources"]
    assert [(row["source"], row["ending"]) for row in document["sources"]] == [
        ("confluence", "failed"),
        ("jira", "done"),
    ]
    assert all(list(row) == ROW_KEYS for row in document["sources"])
    assert "confluence pages: fetched" in document["sources"][0]["counts"]
    assert signed_in.asked
    assert main(command(home, config, "prepare", "--yes", "--format", "json")) == ExitStatus.OK
    document = json.loads(capsys.readouterr().out)
    assert [(row["source"], row["ending"]) for row in document["sources"]] == [
        ("confluence", "done"),
        ("jira", "done"),
        ("worklog", "done"),
    ]
    assert all(list(row) == ROW_KEYS for row in document["sources"])
    assert document["sources"][2]["counts"]["documents"] == WORKLOG_DOCUMENTS


def keys_of(document: object) -> set[str]:
    """Give every key of a JSON document, at every depth."""
    if isinstance(document, dict):
        return set(document) | {key for value in document.values() for key in keys_of(value)}
    if isinstance(document, list):
        return {key for value in document for key in keys_of(value)}
    return set()


@pytest.mark.usefixtures("signed_in")
def test_each_key_that_the_help_names_is_one_of_the_json(
    home: Path, worklog: Path, capsys: CaptureFixture[str]
) -> None:
    """Fetch's and prepare's --help name, in backquotes, keys that their --format json writes.

    A run and a dry run of each, over the scripted site and the work log, write every key
    that the help names, so that the help cannot tell a script of a key that is gone.
    """
    config = settings_file(home, worklog, atlassian=True)
    written: set[str] = set()
    for stage, options in (
        ("fetch", ("--since", "2026-10-02")),
        ("fetch", ("--since", "2026-10-02", "--dry-run")),
        ("prepare", ()),
        ("prepare", ("--dry-run",)),
    ):
        main(command(home, config, stage, "--yes", "--format", "json", *options))
        written |= keys_of(json.loads(capsys.readouterr().out))
    for stage in ("fetch", "prepare"):
        with pytest.raises(SystemExit):
            main([stage, "--help"])
        named = set(re.findall(r"`([a-z_]+)`", capsys.readouterr().out))
        assert named, stage
        assert sorted(named - written) == [], stage


def test_an_until_before_since_exits_2_by_name_before_any_get(
    home: Path, signed_in: FakeSite, capsys: CaptureFixture[str]
) -> None:
    """Refused before the first row, naming them."""
    config = settings_file(home, None, atlassian=True)
    backwards = ("--since", "2026-10-22", "--until", "2026-10-01")
    assert main(command(home, config, "fetch", "--yes", *backwards)) == ExitStatus.REFUSED
    err = capsys.readouterr().err
    assert "fetch.refused" in err
    assert "source 'confluence': fetch: --until: must come after --since" in err
    assert signed_in.asked == []


def test_a_first_fetch_without_since_fetches_the_last_week_of_each_target(
    home: Path, signed_in: FakeSite, capsys: CaptureFixture[str]
) -> None:
    """Nothing covered no longer refuses the run: each target covers the 7 days before it.

    The line before the run states the rule, since the store is not read before then,
    once though both sources taken say it.
    """
    config = settings_file(home, None, atlassian=True)
    assert main(command(home, config, "fetch", "--yes")) != ExitStatus.REFUSED
    rule = "period: since each scope's last fetch; the last 7 days for one never fetched\n"
    assert capsys.readouterr().err.count(rule) == 1
    assert signed_in.asked
    periods = RawStore((home / "data" / "raw").resolve(), "confluence").coverage().periods
    assert set(periods) == {
        Scope(source="confluence", type=names.SPACE, key="MFS"),
        Scope(source="jira", type=names.PROJECT, key="PRB"),
    }
    assert {each.end - each.start for each in periods.values()} == {WEEK}


def runs(
    settings: Settings,
    now: datetime,
    *declared: Connector,
    options: Mapping[str, object] | None = None,
    dry_run: bool = False,
) -> list[SourceRun]:
    """Give a run of each connector's one source, at ``now``, as the command builds it.

    Each source's options are those of ``options`` that its connector declares, None when
    not given; the registry is ``SOURCES``.
    """
    return [
        SourceRun(
            source=each,
            sources=SOURCES,
            settings=settings,
            source_table=getattr(settings.sources, each.name),
            account_table=None
            if each.connector.account is None
            else getattr(settings.accounts, each.connector.account.name),
            options={flag: (options or {}).get(flag) for flag in each.connector.flags},
            now=lambda: now,
            sleep=lambda _: None,
            dry_run=dry_run,
        )
        for each in sourced(*declared)
    ]


def logged_as(logged: list[dict[str, object]], event: str) -> list[dict[str, object]]:
    """Give each event of this name that ``capture_logs`` held."""
    return [each for each in logged if each["event"] == event]


def chosen_settings(tmp_path: Path, worklog: Path) -> Settings:
    """Give settings with a site, a data folder with a saved session, MFS, PRB and the work log."""
    settings = MODEL(
        accounts={"atlassian": {"site": SITE}},
        data_dir=tmp_path / "data",
        sources={
            "confluence": {"spaces": ["MFS"]},
            "jira": {"projects": ["PRB"]},
            "worklog": {"path": worklog},
        },
    )
    write_cookies(settings.session / COOKIES, [{"name": "s", "value": "v", "domain": "x"}])
    return settings


def test_a_later_fetch_catches_up_on_an_old_page_edited_today_and_nothing_stored(
    tmp_path: Path, worklog: Path, monkeypatch: MonkeyPatch
) -> None:
    """A first fetch over a week; a second, with no --since, fetches the edited page alone."""
    settings = chosen_settings(tmp_path, worklog)
    monkeypatch.setattr(http, "client", lambda *_: RefreshSite().client())
    first = runs(settings, FIRST, CONFLUENCE, options=SINCE)
    assert run_each("fetch", first).exit_status == 0
    assert "1003" not in stored_pages(settings)
    edited = {"number": 4, "createdAt": "2026-10-23T08:00:00.000Z"}
    later = RefreshSite(listing={**PAGES, "1003": {**PAGES["1003"], "version": edited}})
    monkeypatch.setattr(http, "client", lambda *_: later.client())
    ran = run_each("fetch", runs(settings, SECOND, CONFLUENCE))
    assert ran.exit_status == ExitStatus.OK
    fetched = ran.sources[0].counts
    assert isinstance(fetched, FetchCounts)
    assert fetched.counts["confluence pages: fetched"] == 1
    assert stored_pages(settings)["1003"] == "000004"


def test_a_fetch_that_must_sign_in_leaves_each_prepare_to_run_on_what_is_stored(
    tmp_path: Path, worklog: Path
) -> None:
    """No session saved: the fetch says to sign in, exit 3; each prepare then runs, exit 0."""
    settings = MODEL(
        accounts={"atlassian": {"site": SITE}},
        data_dir=tmp_path / "data",
        sources={"confluence": {"spaces": ["MFS"]}, "worklog": {"path": worklog}},
    )
    first = runs(settings, FIRST, CONFLUENCE, options=SINCE)
    with capture_logs() as logged:
        fetched = run_each("fetch", first)
    assert [(row.source, row.ending) for row in fetched.sources] == [
        ("confluence", "sign in again")
    ]
    assert fetched.exit_status == ExitStatus.SIGN_IN_AGAIN
    assert logged_as(logged, "fetch.sign_in_needed")
    prepared = run_each("prepare", runs(settings, FIRST, CONFLUENCE, WORKLOG))
    assert [(row.source, row.ending) for row in prepared.sources] == [
        ("confluence", "done"),
        ("worklog", "done"),
    ]
    assert prepared.exit_status == ExitStatus.OK
    assert len(list((settings.docs / "worklog").rglob("*.md"))) == WORKLOG_DOCUMENTS


def test_ctrl_c_in_a_fetch_exits_130_and_no_later_source_runs(
    tmp_path: Path, worklog: Path, monkeypatch: MonkeyPatch
) -> None:
    """The first interrupted; the next not run, nothing of it asked; the event names the first."""
    monkeypatch.setattr(fetcher, "run_fetch", interrupting)
    settings = chosen_settings(tmp_path, worklog)
    taken = runs(settings, FIRST, CONFLUENCE, JIRA, options=SINCE)
    with capture_logs() as logged:
        ran = run_each("fetch", taken)
    assert [(row.source, row.ending) for row in ran.sources] == [
        ("confluence", "interrupted"),
        ("jira", "not run"),
    ]
    assert ran.exit_status == ExitStatus.INTERRUPTED
    stopped = logged_as(logged, "fetch.interrupted")
    assert [each["source"] for each in stopped] == ["confluence"]
    assert not settings.docs.exists()


def problem_prepared() -> Outcome[atlassian_prepare.AtlassianCounts]:
    """Give a mirror that could not convert a page."""
    return Outcome(
        ending="failed",
        counts=atlassian_prepare.AtlassianCounts(
            documents=0,
            converted=0,
            reused=0,
            changes=Changes(written=0, unchanged=0, removed=0),
            unsupported=Counter(),
        ),
        problems=(Problem(where="confluence/pages/1001/000001", reason="pandoc: exit status 9"),),
    )


def test_a_prepare_problem_exits_1_with_the_work_log_mirrored(
    tmp_path: Path, worklog: Path, monkeypatch: MonkeyPatch
) -> None:
    """Confluence's prepare fails, said by place; the work log's still runs."""
    monkeypatch.setattr(preparer, "prepare_atlassian", lambda *_: problem_prepared())
    settings = chosen_settings(tmp_path, worklog)
    with capture_logs() as logged:
        ran = run_each("prepare", runs(settings, FIRST, CONFLUENCE, WORKLOG))
    assert [(row.source, row.ending) for row in ran.sources] == [
        ("confluence", "failed"),
        ("worklog", "done"),
    ]
    assert ran.exit_status == ExitStatus.FAILED
    (said,) = logged_as(logged, "prepare.not_mirrored")
    assert (said["where"], said["reason"]) == (
        "confluence/pages/1001/000001",
        "pandoc: exit status 9",
    )
    assert len(list((settings.docs / "worklog").rglob("*.md"))) == WORKLOG_DOCUMENTS


def test_a_work_log_that_is_not_a_folder_is_refused_before_any_row(
    home: Path, tmp_path: Path, capsys: CaptureFixture[str]
) -> None:
    """Named by its setting; nothing is written."""
    config = settings_file(home, tmp_path / "absent")
    assert main(command(home, config, "prepare", "--yes")) == ExitStatus.REFUSED
    err = capsys.readouterr().err
    assert "prepare.refused" in err
    assert "source 'worklog': prepare: sources.worklog.path: not a folder" in err
    assert not (home / "data" / "docs").exists()


def test_a_prepare_and_its_dry_run_leave_the_work_log_as_it_was(
    home: Path, worklog: Path, capsys: CaptureFixture[str]
) -> None:
    """Every byte and time of the folder, a .git folder in it, stay as they were."""
    (worklog / ".git" / "objects").mkdir(parents=True)
    (worklog / ".git" / "HEAD").write_text("ref: refs/heads/main\n", "utf-8")
    settle(worklog)
    before = snapshot(worklog)
    config = settings_file(home, worklog)
    assert main(command(home, config, "prepare", "worklog", "--dry-run")) == 0
    assert main(command(home, config, "prepare", "worklog", "--yes")) == 0
    assert main(command(home, config, "prepare", "worklog", "--yes")) == 0
    assert snapshot(worklog) == before
    second = capsys.readouterr().out.split("worklog: done\n")[-1]
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
    taken = runs(settings, FIRST, WORKLOG)
    run_each("prepare", taken)
    gone = next((settings.docs / "worklog/transcripts").glob("*waiting-notes.md"))
    (worklog / "transcripts/misc/a.org").unlink()
    todo = worklog / "todo.org"
    todo.write_text(todo.read_text("utf-8").replace("Drafted on", "Drafted, failing, on"), "utf-8")
    failing = Counting(path=Pandoc.find().path, failing="failing")
    telemetry.spans.clear()
    telemetry.measured()
    with monkeypatch.context() as patch, capture_logs() as logged:
        patch.setattr(Pandoc, "find", lambda: failing)
        ran = run_each("prepare", taken)
    assert (ran.sources[0].ending, ran.exit_status) == ("failed", ExitStatus.FAILED)
    (kept,) = logged_as(logged, "worklog.nothing_removed")
    assert {key: kept[key] for key in kept if key not in {"event", "log_level"}} == {"problems": 1}
    (problem,) = logged_as(logged, "worklog.problem")
    assert problem["where"] == f"todo.org, {problem['held_back']}"
    assert re.fullmatch(r"e-[0-9a-f]{16}", problem["held_back"])
    rows = [(each["source"], each["ending"]) for each in logged_as(logged, "prepare.source")]
    assert rows == [("worklog", "failed")]
    spans = telemetry.spans.get_finished_spans()
    (row,) = [span for span in spans if span.name == "prepare.source"]
    assert row.attributes["kb_mcp.ending"] == "failed"
    assert by_type_and_outcome(telemetry.measured()).get(("entry", "failed")) == 1
    assert gone.exists()
    todo.write_text(todo.read_text("utf-8").replace("Drafted, failing, on", "Drafted on"), "utf-8")
    assert run_each("prepare", taken).exit_status == ExitStatus.OK
    assert not gone.exists()


def test_a_dry_run_of_a_work_log_with_a_file_not_read_fails_and_exits_1(
    home: Path, worklog: Path, capsys: CaptureFixture[str]
) -> None:
    """A dry run that finds a problem ends failed, not not run, so that its exit says so."""
    where = "transcripts/current/2026-10-27 Tue/1.org"
    (worklog / where).write_bytes(b"* Caf\xe9\n")
    config = settings_file(home, worklog)
    given = command(home, config, "prepare", "worklog", "--dry-run", "--format", "json")
    assert main(given) == ExitStatus.FAILED
    (row,) = json.loads(capsys.readouterr().out)["sources"]
    assert (row["source"], row["ending"]) == ("worklog", "failed")
    assert row["problems"] == [{"where": where, "reason": "not UTF-8"}]


def test_a_transcript_not_read_is_said_loudly_with_what_it_held_back(
    home: Path, worklog: Path, capsys: CaptureFixture[str]
) -> None:
    """On stderr at the default level, one worklog.problem: where, why, what it held back.

    "It should be flagged and reported loudly in logs" (the user, 2026-10-29, plan 044):
    the run exits 1; its JSON gives the problem, and by its place what it held back.
    """
    where = "transcripts/current/2026-10-27 Tue/1.org"
    (worklog / where).write_bytes(b"* Caf\xe9\n")
    config = settings_file(home, worklog)
    given = command(home, config, "prepare", "--yes", "--format", "json")
    assert main(given) == ExitStatus.FAILED
    captured = capsys.readouterr()
    (said,) = [line for line in captured.err.splitlines() if "worklog.problem" in line]
    assert all(part in said for part in (where, "not UTF-8", "held_back=t-20261027-1"))
    (row,) = [each for each in json.loads(captured.out)["sources"] if each["source"] == "worklog"]
    assert row["problems"] == [{"where": where, "reason": "not UTF-8"}]
    assert row["counts"]["held_back"] == {where: "t-20261027-1"}


def test_the_text_gives_a_row_per_source_then_its_counts(
    home: Path, worklog: Path, capsys: CaptureFixture[str]
) -> None:
    """The work log's: documents, files, HTML left out, problems; a dry run's to convert."""
    config = settings_file(home, worklog)
    assert main(command(home, config, "prepare", "worklog", "--dry-run")) == 0
    assert capsys.readouterr().out == (
        "worklog: not run\n"
        f"  documents: {WORKLOG_DOCUMENTS}\n"
        f"  to convert: {WORKLOG_DOCUMENTS}\n"
        "  files to remove: 0\n"
        "  HTML left out: 1\n"
        "  warning: meetings/2026-10-27 Tue/2.org: its :MEETING: link reaches no transcript found\n"
        "  warnings: 1\n"
    )
    assert main(command(home, config, "prepare", "worklog", "--yes")) == 0
    assert capsys.readouterr().out == (
        "worklog: done\n"
        f"  documents: {WORKLOG_DOCUMENTS}\n"
        f"  files written: {WORKLOG_DOCUMENTS}\n"
        "  files unchanged: 0\n"
        "  files removed: 0\n"
        "  HTML left out: 1\n"
        "  warning: meetings/2026-10-27 Tue/2.org: its :MEETING: link reaches no transcript found\n"
        "  warnings: 1\n"
    )


@pytest.mark.parametrize("stage", ["fetch", "prepare"])
@pytest.mark.parametrize("registry", [SOURCES, sourced(WORKLOG), sourced(CONFLUENCE, WORKLOG)])
def test_the_sources_offered_are_the_registry_s(
    stage: str, registry: tuple[Source, ...], capsys: CaptureFixture[str]
) -> None:
    """Each name that the registry declares is taken; each other is refused by argparse.

    By ``prepare`` every source, by ``fetch`` those that have a fetcher.
    """
    names = [
        each.name for each in registry if stage == "prepare" or each.connector.fetcher is not None
    ]
    for name in names:
        assert parser(sources=registry).parse_args([stage, name]).source == [name]
    for name in (each.name for each in SOURCES if each.name not in names):
        with pytest.raises(SystemExit) as stopped:
            parser(sources=registry).parse_args([stage, name])
        assert stopped.value.code == ExitStatus.REFUSED
        assert f"invalid choice: '{name}'" in capsys.readouterr().err


def test_a_dry_run_of_the_site_plans_and_writes_nothing(
    home: Path, signed_in: FakeSite, capsys: CaptureFixture[str]
) -> None:
    """Each fetch planned; each prepare not run, saying so; the session alone is written."""
    config = settings_file(home, None, atlassian=True)
    given = ("--dry-run", "--since", "2026-10-02", "--format", "json")
    assert main(command(home, config, "fetch", *given)) == ExitStatus.OK
    rows = json.loads(capsys.readouterr().out)["sources"]
    assert [(row["source"], row["ending"]) for row in rows] == [
        ("confluence", "not run"),
        ("jira", "not run"),
    ]
    fetched = [row["counts"] for row in rows]
    assert "confluence pages: to fetch" in fetched[0]
    assert "jira issues: to fetch" in fetched[1]
    windows = [each for each_fetched in fetched for each in each_fetched["windows"]]
    assert [(each["scope"]["key"], each["reason"], each["coverage"]) for each in windows] == [
        ("MFS", "given", None),
        ("PRB", "given", None),
    ]
    assert [each["dry_run"] for each in fetched] == [True, True]
    assert main(command(home, config, "prepare", "--dry-run", "--format", "json")) == ExitStatus.OK
    rows = json.loads(capsys.readouterr().out)["sources"]
    assert [(row["source"], row["ending"]) for row in rows] == [
        ("confluence", "not run"),
        ("jira", "not run"),
    ]
    assert all(list(row) == ROW_KEYS for row in rows)
    assert sorted(path.name for path in (home / "data").iterdir()) == ["session"]
    assert signed_in.asked


def test_a_dry_run_of_the_site_says_each_target_s_window_under_its_row(
    home: Path, signed_in: FakeSite, capsys: CaptureFixture[str]
) -> None:
    """Short as it is: under each fetch's row, its target's window and why, then counts."""
    config = settings_file(home, None, atlassian=True)
    given = command(home, config, "fetch", "--dry-run", "--since", "2026-10-02")
    assert main(given) == ExitStatus.OK
    confluence, jira = capsys.readouterr().out.split("jira: not run\n")
    row, space, *_ = confluence.splitlines()
    project, *_ = jira.splitlines()
    assert row == "confluence: not run"
    assert space.startswith("  space MFS: from 2026-10-02T00:00:00+00:00 to ")
    assert project.startswith("  project PRB: from 2026-10-02T00:00:00+00:00 to ")
    assert space.endswith(", given")
    assert signed_in.asked


@pytest.mark.parametrize("named", [["confluence", "jira"], ["jira"]])
def test_the_sources_named_are_the_rows_run(
    home: Path,
    worklog: Path,
    signed_in: FakeSite,
    capsys: CaptureFixture[str],
    named: list[str],
) -> None:
    """Not named: no row, no request, no file of it."""
    config = settings_file(home, worklog, atlassian=True)
    options = ("--yes", "--since", "2026-10-02", "--format", "json")
    main(command(home, config, "fetch", *options, *named))
    found = json.loads(capsys.readouterr().out)["sources"]
    assert [row["source"] for row in found] == named
    assert any("/wiki/" in url.path for url in signed_in.asked) is ("confluence" in named)


def test_a_source_not_named_is_not_mirrored_though_its_documents_are_stored(
    home: Path, signed_in: FakeSite, capsys: CaptureFixture[str]
) -> None:
    """``prepare jira`` prepares Jira alone; a Confluence file deleted stays so."""
    config = settings_file(home, None, atlassian=True)
    main(command(home, config, "fetch", "--yes", "--since", "2026-10-02"))
    main(command(home, config, "prepare", "--yes"))
    capsys.readouterr()
    page = next((home / "data" / "docs" / "confluence").rglob("*.md"))
    page.unlink()
    main(command(home, config, "prepare", "--yes", "--format", "json", "jira"))
    rows = json.loads(capsys.readouterr().out)["sources"]
    assert [(row["source"], row["ending"]) for row in rows] == [("jira", "done")]
    assert not page.exists()
    assert signed_in.asked


def test_archives_off_leaves_the_archived_documents_out_of_a_prepare(
    home: Path, worklog: Path, capsys: CaptureFixture[str]
) -> None:
    """The archive file's entry and meetings, the ARCHIVE entry, the archived transcript."""
    config = settings_file(home, worklog)
    config.write_text(config.read_text("utf-8") + "archives = false\n", "utf-8")
    given = command(home, config, "prepare", "worklog", "--yes", "--format", "json")
    assert main(given) == 0
    result = json.loads(capsys.readouterr().out)["sources"][0]["counts"]
    archived = ["vendor", "old incident", "1.org", "incident review", "capacity planning"]
    assert result["documents"] == WORKLOG_DOCUMENTS - len(archived)
    labels = [
        line for path in (home / "data").rglob("*.md") for line in path.read_text("utf-8").split()
    ]
    assert "ARCHIVE" not in labels


def test_the_settings_of_sources_left_out_are_said_not_applied(
    home: Path, worklog: Path, signed_in: FakeSite, capsys: CaptureFixture[str]
) -> None:
    """Their values, given by the file, are ignored by name and layer, saying why.

    Those that the command reads: a prepare does not read a store's, said in detail alone.
    """
    config = settings_file(home, worklog, atlassian=True)
    assert main(command(home, config, "prepare", "worklog", "--yes")) == 0
    said = capsys.readouterr().err
    unsigned = "no source of the atlassian account in this prepare"
    assert f"ignored: accounts.atlassian.site (config.toml): {unsigned}\n" in said
    assert "sources.jira.projects" not in said
    assert main(command(home, config, "fetch", "--dry-run", "confluence")) == 0
    assert "ignored: sources.jira.projects (config.toml): jira not named\n" in (
        capsys.readouterr().err
    )
    assert signed_in.asked


def test_a_work_log_that_is_a_file_is_refused_as_not_a_folder(
    home: Path, tmp_path: Path, capsys: CaptureFixture[str]
) -> None:
    """A regular file named as the folder: exit 2."""
    (tmp_path / "todo.org").write_text("* x\n", "utf-8")
    config = settings_file(home, tmp_path / "todo.org")
    assert main(command(home, config, "prepare", "--yes")) == ExitStatus.REFUSED
    assert "sources.worklog.path: not a folder" in capsys.readouterr().err


@pytest.mark.usefixtures("signed_in")
def test_a_second_prepare_reuses_every_conversion_and_the_work_log_adds_none(
    home: Path, worklog: Path, capsys: CaptureFixture[str]
) -> None:
    """Plan 039, criterion 7: the data folder's cache holds the mirror's conversions alone.

    A first prepare converts, a second reuses each conversion, by its row in JSON, then in
    text.
    """
    config = settings_file(home, worklog, atlassian=True)
    main(command(home, config, "fetch", "--yes", "--since", "2026-10-02"))
    capsys.readouterr()
    rows = []
    for output in (("--format", "json"), ("--format", "json"), ()):
        main(command(home, config, "prepare", "--yes", *output))
        rows.append(capsys.readouterr().out)
    first, second = (json.loads(row)["sources"][0] for row in rows[:2])
    outcome = first["counts"]
    assert (first["source"], first["ending"], outcome["reused"]) == ("confluence", "done", 0)
    converted = outcome["converted"]
    assert converted > outcome["documents"] > 0  # a tree among them
    again = second["counts"]
    assert (again["converted"], again["reused"]) == (0, converted)
    documents = outcome["documents"]
    assert (
        f"confluence: done\n  documents: {documents}\n"
        f"  converted by pandoc: 0\n  reused from the cache: {converted}\n"
    ) in rows[2]
    jira = json.loads(rows[0])["sources"][1]
    assert (jira["source"], jira["ending"]) == ("jira", "done")
    total = converted + jira["counts"]["converted"]
    with closing(sqlite3.connect(home / "data" / "conversions.sqlite")) as cache:
        assert cache.execute("SELECT count(*) FROM conversions").fetchone() == (total,)


def test_a_damaged_cache_is_replaced_and_every_row_runs_exit_0(
    tmp_path: Path, worklog: Path, monkeypatch: MonkeyPatch
) -> None:
    """Plan 039, criterion 8: the mirror converts all again, reusing nothing, said once."""
    settings = chosen_settings(tmp_path, worklog)
    monkeypatch.setattr(http, "client", lambda *_: RefreshSite().client())
    run_each("fetch", runs(settings, FIRST, CONFLUENCE, options=SINCE))
    taken = runs(settings, FIRST, CONFLUENCE, WORKLOG)
    first = run_each("prepare", taken).sources[0].counts
    assert isinstance(first, atlassian_prepare.AtlassianCounts)
    settings.conversions.write_bytes(hashlib.shake_256(b"cache").digest(8192))
    with capture_logs() as logged:
        ran = run_each("prepare", taken)
    assert ran.exit_status == ExitStatus.OK
    assert [(row.source, row.ending) for row in ran.sources] == [
        ("confluence", "done"),
        ("worklog", "done"),
    ]
    outcome = ran.sources[0].counts
    assert isinstance(outcome, atlassian_prepare.AtlassianCounts)
    assert (outcome.converted, outcome.reused) == (first.converted, 0)
    replaced = logged_as(logged, "prepare.cache_replaced")
    assert [each["reason"] for each in replaced] == ["SQLITE_NOTADB"]


def test_other_arguments_for_pandoc_convert_the_mirror_again(
    tmp_path: Path, worklog: Path, monkeypatch: MonkeyPatch
) -> None:
    """Review of 039: a prepare keeps the conversions of the arguments that pandoc is given.

    A second prepare gives pandoc one argument more, `--columns=72`.
    """
    settings = chosen_settings(tmp_path, worklog)
    monkeypatch.setattr(http, "client", lambda *_: RefreshSite().client())
    run_each("fetch", runs(settings, FIRST, CONFLUENCE, options=SINCE))
    taken = runs(settings, FIRST, CONFLUENCE)
    first = run_each("prepare", taken).sources[0].counts
    assert isinstance(first, atlassian_prepare.AtlassianCounts)
    more = (*pandoc_adapter.ARGUMENTS, "--columns=72")
    monkeypatch.setattr(pandoc_adapter, "ARGUMENTS", more)
    again = run_each("prepare", taken).sources[0].counts
    assert isinstance(again, atlassian_prepare.AtlassianCounts)
    assert (again.converted, again.reused) == (first.converted, 0)
    assert first.converted > 0


def test_each_command_s_text_gives_each_source_s_counts_under_its_row(
    home: Path, worklog: Path, signed_in: FakeSite, capsys: CaptureFixture[str]
) -> None:
    """Each fetch's counts, then each prepare's, indented under its source's row."""
    config = settings_file(home, worklog, atlassian=True)
    given = command(home, config, "fetch", "--yes", "--since", "2026-10-02")
    assert main(given) == ExitStatus.FAILED
    out = capsys.readouterr().out
    assert out.startswith("confluence: failed\n  confluence blogposts: fetched: 1\n")
    assert (
        "  problem: file att3: status 404\n  problems: 1\njira: done\n  files: downloaded: 1\n"
        in out
    )
    assert main(command(home, config, "prepare", "--yes")) == ExitStatus.OK
    out = capsys.readouterr().out
    assert out.startswith("confluence: done\n  documents: ")
    assert "\njira: done\n  documents: " in out
    assert signed_in.asked


def test_with_the_work_log_alone_the_index_still_holds_every_page(
    home: Path, worklog: Path, signed_in: FakeSite, capsys: CaptureFixture[str]
) -> None:
    """``prepare worklog`` refreshes the work log alone; ``index`` reads the whole mirror."""
    config = settings_file(home, worklog, atlassian=True)
    main(command(home, config, "fetch", "--yes", "--since", "2026-10-02"))
    main(command(home, config, "prepare", "--yes"))
    capsys.readouterr()
    main(command(home, config, "index", "--yes", "--format", "json"))
    first = json.loads(capsys.readouterr().out)["counts"]["types"]
    assert {"page", "blogpost", "issue"} <= set(first)
    signed_in.asked.clear()
    assert main(command(home, config, "prepare", "--yes", "--format", "json", "worklog")) == 0
    rows = json.loads(capsys.readouterr().out)["sources"]
    assert [(row["source"], row["ending"]) for row in rows] == [("worklog", "done")]
    main(command(home, config, "index", "--yes", "--format", "json"))
    assert json.loads(capsys.readouterr().out)["counts"]["types"] == first
    assert not signed_in.asked


def interrupting(*_: object) -> None:
    """Stop a fetcher or a preparer as Ctrl-C would."""
    raise KeyboardInterrupt


def test_ctrl_c_in_a_prepare_marks_it_interrupted_and_the_work_log_not_run(
    tmp_path: Path, worklog: Path, monkeypatch: MonkeyPatch
) -> None:
    """Confluence's prepare interrupted, the work log's not run: exit 130."""
    monkeypatch.setattr(preparer, "prepare_atlassian", interrupting)
    settings = chosen_settings(tmp_path, worklog)
    with capture_logs() as logged:
        ran = run_each("prepare", runs(settings, FIRST, CONFLUENCE, WORKLOG))
    assert [(row.source, row.ending) for row in ran.sources] == [
        ("confluence", "interrupted"),
        ("worklog", "not run"),
    ]
    assert ran.exit_status == ExitStatus.INTERRUPTED
    stopped = logged_as(logged, "prepare.interrupted")
    assert [each["source"] for each in stopped] == ["confluence"]


class EndingInCtrlC:
    """A row's span whose end Ctrl-C reaches, once its row is kept."""

    def __enter__(self) -> Self:
        """Open it."""
        return self

    def __exit__(self, *_: object) -> None:
        """Stop the run as Ctrl-C would."""
        raise KeyboardInterrupt

    def set_attribute(self, *_: object) -> None:
        """Record nothing."""


def test_ctrl_c_once_every_row_ended_still_exits_130(
    tmp_path: Path, worklog: Path, monkeypatch: MonkeyPatch
) -> None:
    """Every row kept as it ended, and the run interrupted; the event names no source."""
    tracer = SimpleNamespace(start_as_current_span=lambda *_, **__: EndingInCtrlC())
    monkeypatch.setattr(sources_app, "TRACER", tracer)
    settings = chosen_settings(tmp_path, worklog)
    with capture_logs() as logged:
        ran = run_each("prepare", runs(settings, FIRST, WORKLOG))
    assert [(row.source, row.ending) for row in ran.sources] == [("worklog", "done")]
    assert ran.exit_status == ExitStatus.INTERRUPTED
    assert [each["source"] for each in logged_as(logged, "prepare.interrupted")] == [None]


def ending(*endings: Ending) -> Callable[..., Outcome[FetchCounts]]:
    """Give a fetch that ends as told, once each, then stops as Ctrl-C would."""
    left = iter(endings)

    def fetch(*_: object) -> Outcome[FetchCounts]:
        for each in left:
            return Outcome(ending=each, counts=FetchCounts())
        raise KeyboardInterrupt

    return fetch


def test_to_sign_in_again_ranks_above_a_failure_and_below_an_interruption(
    tmp_path: Path, worklog: Path, monkeypatch: MonkeyPatch
) -> None:
    """A failed fetch and one to sign in again exit 3, whichever comes first; Ctrl-C, 130."""
    settings = chosen_settings(tmp_path, worklog)
    taken = runs(settings, FIRST, CONFLUENCE, JIRA, options=SINCE)
    monkeypatch.setattr(fetcher, "run_fetch", ending("failed", "sign in again"))
    ran = run_each("fetch", taken)
    assert [row.ending for row in ran.sources] == ["failed", "sign in again"]
    assert ran.exit_status == ExitStatus.SIGN_IN_AGAIN
    monkeypatch.setattr(fetcher, "run_fetch", ending("sign in again"))
    ran = run_each("fetch", taken)
    assert [row.ending for row in ran.sources] == ["sign in again", "interrupted"]
    assert ran.exit_status == ExitStatus.INTERRUPTED


def test_a_source_named_without_its_table_is_refused_beside_one_that_has_it(
    home: Path, capsys: CaptureFixture[str]
) -> None:
    """``prepare confluence worklog``, no work log: exit 2, naming its setting."""
    config = settings_file(home, None, atlassian=True)
    assert main(command(home, config, "prepare", "--yes", "confluence", "worklog")) == (
        ExitStatus.REFUSED
    )
    said = capsys.readouterr().err
    assert "run.refused" in said
    assert "worklog: not configured; set sources.worklog.path" in said


def test_with_a_site_source_an_email_without_a_token_alone_is_not_applied(
    home: Path, signed_in: FakeSite, monkeypatch: MonkeyPatch, capsys: CaptureFixture[str]
) -> None:
    """The site is used; the email, without its token, signs nothing in."""
    monkeypatch.setenv("KB_MCP_ACCOUNTS__ATLASSIAN__EMAIL", "someone@example.invalid")
    config = settings_file(home, None, atlassian=True)
    given = command(home, config, "fetch", "--dry-run", "--since", "2026-10-02")
    assert main(given) == ExitStatus.OK
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
    assert main(command(home, config, "prepare", "worklog", "--dry-run")) == ExitStatus.OK
    said = capsys.readouterr().err
    for setting, variable in (
        ("accounts.atlassian.email", "KB_MCP_ACCOUNTS__ATLASSIAN__EMAIL"),
        ("accounts.atlassian.api_token", "KB_MCP_ACCOUNTS__ATLASSIAN__API_TOKEN"),
    ):
        unsigned = "no source of the atlassian account in this prepare"
        assert f"ignored: {setting} ({variable}): {unsigned}\n" in said
    assert "token-sentinel-7f2b" not in said


def test_a_busy_raw_store_fails_the_fetch_and_a_prepare_still_runs(
    tmp_path: Path, worklog: Path, monkeypatch: MonkeyPatch
) -> None:
    """Another run writing the store: each fetch failed, said; each next row runs."""

    def busy(*_: object) -> Outcome[FetchCounts]:
        raise StoreBusyError

    monkeypatch.setattr(fetcher, "run_fetch", busy)
    settings = chosen_settings(tmp_path, worklog)
    taken = runs(settings, FIRST, CONFLUENCE, JIRA, options=SINCE)
    with capture_logs() as logged:
        ran = run_each("fetch", taken)
    assert [(row.source, row.ending) for row in ran.sources] == [
        ("confluence", "failed"),
        ("jira", "failed"),
    ]
    assert ran.exit_status == ExitStatus.FAILED
    assert [row.problems for row in ran.sources] == [
        (Problem(where="raw store", reason=fetcher.BUSY),)
    ] * 2
    assert len(logged_as(logged, "fetch.store_busy")) == len(ran.sources)
    prepared = run_each("prepare", runs(settings, FIRST, WORKLOG))
    assert prepared.exit_status == ExitStatus.OK


def test_the_log_files_hold_no_document_s_text(
    home: Path, worklog: Path, capsys: CaptureFixture[str]
) -> None:
    """They hold DEBUG, titles too; never a document's body."""
    config = settings_file(home, worklog)
    assert main(command(home, config, "prepare", "--yes", "-vv", "worklog")) == ExitStatus.OK
    capsys.readouterr()
    logs = "".join(path.read_text("utf-8") for path in home.rglob("prepare-*.jsonl"))
    assert '"event": "worklog.document"' in logs
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


def by_type_and_outcome(measured: dict[str, Metric]) -> dict[tuple[object, object], object]:
    """Give the work log's documents counted, by type and outcome."""
    return {
        (point.attributes["kb_mcp.type"], point.attributes["kb_mcp.outcome"]): point.value
        for point in measured["kb_mcp.prepare.documents"].data.data_points
        if point.attributes and "kb_mcp.type" in point.attributes
    }


def test_the_work_log_is_counted_by_type_and_its_spans_are_in_its_row(
    home: Path, worklog: Path, telemetry: InMemory
) -> None:
    """Each document counted by type and outcome, each work-log span in the source's row.

    Fresh, every entry, day, meeting and transcript is prepared, each conversion timed by
    type; unchanged, all are kept and none timed. Each work-log span is in the row's
    ``prepare.source``, which names the source and its outcome, in the run's root; each
    document's event is logged in ``worklog.convert``.
    """
    config = settings_file(home, worklog)
    given = command(home, config, "prepare", "--yes", "worklog")
    assert main(given) == ExitStatus.OK
    first, spans = telemetry.measured(), telemetry.spans.get_finished_spans()
    assert main(given) == ExitStatus.OK
    second = telemetry.measured()
    assert by_type_and_outcome(first) == {
        (document_type, "mirrored"): count for document_type, count in WORKLOG_BY_TYPE.items()
    }
    assert by_type_and_outcome(second) == {
        (document_type, "kept"): count for document_type, count in WORKLOG_BY_TYPE.items()
    }
    timed = first["kb_mcp.prepare.conversion.duration"].data.data_points
    assert {point.attributes["kb_mcp.type"]: point.count for point in timed} == WORKLOG_BY_TYPE
    assert "kb_mcp.prepare.conversion.duration" not in second
    (row,) = [span for span in spans if span.name == "prepare.source"]
    assert (row.attributes["kb_mcp.source"], row.attributes["kb_mcp.ending"]) == (
        "worklog",
        "done",
    )
    (root,) = [span for span in spans if span.name == "prepare"]
    assert row.parent is not None
    assert row.parent.span_id == root.context.span_id
    worklog_spans = {span.name: span for span in spans if span.name.startswith("worklog.")}
    assert set(worklog_spans) == {"worklog.read", "worklog.convert", "worklog.write"}
    assert all(
        span.parent is not None and span.parent.span_id == row.context.span_id
        for span in worklog_spans.values()
    )
    emitted = Emitted()
    with emitted.gathering(telemetry, "prepare"):
        assert main([*given, "-vv"]) == ExitStatus.OK
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
    transcript read, none unread; each document prepared, by its type and path; a file
    each written. Unchanged, each kept and none written. A dry run says each to convert
    on an empty mirror, none after a run, and one file to remove once a transcript is
    deleted.
    """
    settings = chosen_settings(tmp_path, worklog)
    dry = runs(settings, FIRST, WORKLOG, dry_run=True)
    with capture_logs() as planned:
        run_each("prepare", dry)
    with capture_logs() as fresh:
        run_each("prepare", runs(settings, FIRST, WORKLOG))
    with capture_logs() as unchanged:
        run_each("prepare", runs(settings, FIRST, WORKLOG))
    (worklog / "transcripts/misc/a.org").unlink()
    with capture_logs() as planned_again:
        run_each("prepare", dry)
    (read,) = logged_as(fresh, "worklog.read")
    counts = ("entries", "days", "meetings", "transcripts", "html", "problems")
    assert tuple(read[each] for each in counts) == (13, 2, 8, 6, 1, 0)
    documents = logged_as(fresh, "worklog.document")
    assert Counter(each["type"] for each in documents) == WORKLOG_BY_TYPE
    assert {each["outcome"] for each in documents} == {"mirrored"}
    folders = {
        "entry": "worklog/entries/",
        "day": "worklog/days/",
        "meeting": "worklog/meetings/",
        "transcript": "worklog/transcripts/",
    }
    assert all(str(each["path"]).startswith(folders[str(each["type"])]) for each in documents)
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
    """Plan 030: a work log that is not a folder refuses the run before any other's row.

    Its preparer's preflight refuses it, so that Confluence's, whose row comes first, writes
    nothing.
    """
    config = settings_file(home, tmp_path / "absent", atlassian=True)
    assert main(command(home, config, "prepare", "--yes")) == ExitStatus.REFUSED
    assert "sources.worklog.path: not a folder" in capsys.readouterr().err
    assert not (home / "data" / "docs").exists()
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
def test_the_site_s_light_checks_refuse_a_fetch_and_never_a_prepare(
    home: Path,
    worklog: Path,
    monkeypatch: MonkeyPatch,
    capsys: CaptureFixture[str],
    case: tuple[tuple[str, ...], dict[str, str], str],
) -> None:
    """Plan 031: a source's light checks are its fetch's.

    No site, an API token without its email, or an option of the period that does not
    read, exit 2 before anything is asked; a prepare, without a site too, is asked none.
    """
    given, variables, named = case
    for name, value in variables.items():
        monkeypatch.setenv(name, value)
    config = settings_file(home, worklog)
    config.write_text(config.read_text("utf-8") + '[sources.jira]\nprojects = ["PRB"]\n', "utf-8")
    assert main(command(home, config, "fetch", "--yes", *given)) == ExitStatus.REFUSED
    assert named in capsys.readouterr().err
    assert main(command(home, config, "prepare", "--dry-run")) == 0
    assert named not in capsys.readouterr().err


def test_a_source_s_own_light_checks_are_asked_when_a_fetch_takes_it(
    home: Path, signed_in: FakeSite, capsys: CaptureFixture[str]
) -> None:
    """Plan 030: a fetch asks each source taken what it refuses, says and does not apply.

    By its declaration's functions, given its options and the settings: here Jira's, in a
    registry of the test's own.
    """
    config = settings_file(home, None, atlassian=True)

    def said(_options: Mapping[str, object], _settings: Mapping[str, object]) -> tuple[str, ...]:
        return ("a declaration's line",)

    def unused(_options: Mapping[str, object], settings: Mapping[str, object]) -> dict[str, str]:
        assert settings["sources.jira.projects"] == ("PRB",)
        return {"sources.jira.projects": "a declaration's reason"}

    checked = replace(JIRA, described=said, unapplied=unused)
    registry = sourced(CONFLUENCE, checked, WORKLOG)
    given = command(home, config, "fetch", "--dry-run", "--since", "2026-10-02")
    assert main(given, registry) == ExitStatus.OK
    err = capsys.readouterr().err
    assert "  a declaration's line\n" in err
    assert "(not applied: a declaration's reason)" in err
    refusing = replace(JIRA, refused=lambda _options, _settings: "a declaration's refusal")
    registry = sourced(CONFLUENCE, refusing, WORKLOG)
    assert main(given, registry) == ExitStatus.REFUSED
    assert "a declaration's refusal" in capsys.readouterr().err
    assert main([*given, "confluence"], registry) == ExitStatus.OK
    assert "a declaration's refusal" not in capsys.readouterr().err
    assert signed_in.asked


def test_a_command_is_a_dry_run_by_its_runs_alone(tmp_path: Path, worklog: Path) -> None:
    """Plan 030: one flag for a run, which each fetcher and preparer reads: the events follow it."""
    settings = chosen_settings(tmp_path, worklog)
    with capture_logs() as dry:
        ran = run_each("prepare", runs(settings, FIRST, WORKLOG, dry_run=True))
    assert [(row.source, row.ending) for row in ran.sources] == [("worklog", "not run")]
    assert logged_as(dry, "prepare.start")[0]["dry_run"] is True
    assert not settings.docs.exists()
    with capture_logs() as real:
        run_each("prepare", runs(settings, FIRST, WORKLOG))
    assert logged_as(real, "prepare.start")[0]["dry_run"] is False
    assert settings.docs.exists()


def test_each_preparer_that_a_source_declares_is_a_row_of_its_own(
    tmp_path: Path, worklog: Path
) -> None:
    """Plan 030: a declaration's preparers are a tuple: each runs, in its order, a row each.

    The same preparer twice here, the second finding its files written by the first.
    """
    settings = chosen_settings(tmp_path, worklog)
    twice = replace(WORKLOG, preparers=WORKLOG.preparers * 2)
    ran = run_each("prepare", runs(settings, FIRST, twice))
    assert [(row.source, row.ending) for row in ran.sources] == [
        ("worklog", "done"),
        ("worklog", "done"),
    ]
    written = [row.counts.changes.written for row in ran.sources]
    assert written == [WORKLOG_DOCUMENTS, 0]


def test_pandoc_gone_fails_each_preparer_s_row_and_the_run_exits_1(
    tmp_path: Path, worklog: Path, monkeypatch: MonkeyPatch
) -> None:
    """Gone from PATH after the entry's check: each row fails alone, each saying so."""
    monkeypatch.setattr(Pandoc, "find", missing)
    settings = chosen_settings(tmp_path, worklog)
    with capture_logs() as logged:
        ran = run_each("prepare", runs(settings, FIRST, CONFLUENCE, WORKLOG))
    assert [(row.source, row.ending) for row in ran.sources] == [
        ("confluence", "failed"),
        ("worklog", "failed"),
    ]
    assert ran.exit_status == ExitStatus.FAILED
    assert len(logged_as(logged, "prepare.pandoc_missing")) == 1
    assert len(logged_as(logged, "worklog.pandoc_failed")) == 1
    assert not (settings.docs / "worklog").exists()


def test_pandoc_giving_no_version_fails_the_work_log_s_row_writing_nothing(
    tmp_path: Path, worklog: Path, monkeypatch: MonkeyPatch
) -> None:
    """No revision can be named: the row fails, an error says why."""
    monkeypatch.setattr(Pandoc, "org_converter", lambda _: unconverted())
    settings = chosen_settings(tmp_path, worklog)
    with capture_logs() as logged:
        ran = run_each("prepare", runs(settings, FIRST, WORKLOG))
    assert [(row.source, row.ending) for row in ran.sources] == [("worklog", "failed")]
    assert ran.exit_status == ExitStatus.FAILED
    (said,) = logged_as(logged, "worklog.pandoc_failed")
    assert said["reason"] == "pandoc: exit status 9"
    assert not (settings.docs / "worklog").exists()


def test_only_a_run_that_writes_says_that_its_problems_held_removals_back(
    tmp_path: Path, worklog: Path
) -> None:
    """A file not read is a problem of both; a dry run, which removes nothing, says no more."""
    (worklog / "transcripts/misc/a.org").write_bytes(b"* Caf\xe9\n")
    settings = chosen_settings(tmp_path, worklog)
    with capture_logs() as dry:
        run_each("prepare", runs(settings, FIRST, WORKLOG, dry_run=True))
    with capture_logs() as real:
        run_each("prepare", runs(settings, FIRST, WORKLOG))
    assert logged_as(dry, "worklog.problem")
    assert not logged_as(dry, "worklog.nothing_removed")
    assert logged_as(real, "worklog.problem")
    assert logged_as(real, "worklog.nothing_removed")


def test_fetch_offers_each_option_that_its_sources_declare_once(
    capsys: CaptureFixture[str],
) -> None:
    """Plan 030: the period's options are Confluence's and Jira's, each flag once.

    Each is read as its declaration types it; a registry of the work log alone, which
    declares none, offers none.
    """
    arguments = parser().parse_args(["fetch", "--since", "7d", "--max-file-mb", "2"])
    assert given(arguments, ("--since", "--max-file-mb")) == {"--since": "7d", "--max-file-mb": 2}
    with pytest.raises(SystemExit) as stopped:
        parser(sources=sourced(WORKLOG)).parse_args(["fetch", "--since=7d"])
    assert stopped.value.code == ExitStatus.REFUSED
    assert "unrecognized arguments: --since=7d" in capsys.readouterr().err


def test_a_prepare_refused_by_a_token_without_its_email_is_none_of_its_concern(
    home: Path, worklog: Path, monkeypatch: MonkeyPatch, capsys: CaptureFixture[str]
) -> None:
    """Prepare signs in nowhere: an API token without its email refuses no prepare."""
    monkeypatch.setenv("KB_MCP_ACCOUNTS__ATLASSIAN__API_TOKEN", "token-sentinel-7f2b")
    config = settings_file(home, worklog)
    assert main(command(home, config, "prepare", "--yes", "worklog")) == ExitStatus.OK
    assert "accounts.atlassian.email: not set" not in capsys.readouterr().err


@pytest.mark.usefixtures("signed_in")
@pytest.mark.parametrize("stage", ["fetch", "prepare"])
def test_the_same_command_runs_either_way_round_its_options(
    home: Path, capsys: CaptureFixture[str], stage: str
) -> None:
    """Names before the options, or after: one command to copy, the names last."""
    config = settings_file(home, None, atlassian=True)
    period = ("--since", "2026-10-02") if stage == "fetch" else ()
    data = str(home / "data")
    given = [stage, "confluence", "--config", str(config), "--data-dir", data, "--dry-run", *period]
    assert main(given) == ExitStatus.OK
    copied = capsys.readouterr().err.split(f"kb-mcp {stage} \\\n")[1]
    assert copied.rstrip().rsplit("\n", 1)[-1].strip() == "confluence"


def test_the_span_of_a_row_names_its_source_and_how_it_ended(
    tmp_path: Path, worklog: Path, telemetry: InMemory
) -> None:
    """Within the current trace: a fetch's as a prepare's, as their pages list them."""
    settings = chosen_settings(tmp_path, worklog)
    with trace.get_tracer(__name__).start_as_current_span("root"):
        run_each("prepare", runs(settings, FIRST, WORKLOG))
    (row,) = [
        span for span in telemetry.spans.get_finished_spans() if span.name == "prepare.source"
    ]
    assert dict(row.attributes) == {"kb_mcp.source": "worklog", "kb_mcp.ending": "done"}
