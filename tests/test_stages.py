"""A source's part in each stage, each one that the registry names, as plan 030 defines it.

The expectations come from the plan's "A source's declaration, and the roles'
interfaces": a declaration names its fetcher, if any, and its preparers by module path,
which ``--help`` never imports; one fetcher and one preparer serve Confluence and Jira,
each reading from ``run.source`` the source that it runs for, so its document types and its
rows of the cache of conversions; the work log, read in place, has no fetcher;
``preflight`` says what a fetcher or a preparer cannot go on with, which fails its row alone; each
preparer that converts finds pandoc itself, so that pandoc gone fails its result alone;
a dry run plans the fetch, counts the work log and leaves Atlassian's prepare alone; and
a result's ``text`` writes what its command writes. The site is plan 004's scripted one,
the work log the invented fixture; each test has a scratch home.
"""

from __future__ import annotations

import json
import os
import pkgutil
import shutil
import sqlite3
import subprocess
import sys
from contextlib import closing
from textwrap import indent
from typing import TYPE_CHECKING

import pytest
from structlog.testing import capture_logs

from kb_mcp.cli.main import main
from kb_mcp.kernel.exit_status import ExitStatus
from kb_mcp.kernel.outcome import Problem
from kb_mcp.mirror.adapters.markdown import load
from kb_mcp.mirror.adapters.pandoc import Pandoc, PandocMissingError
from kb_mcp.sources.atlassian.declared import CONFLUENCE, JIRA
from kb_mcp.sources.atlassian.fetch.adapters import http
from kb_mcp.sources.atlassian.fetch.adapters.raw_store import RawStore
from kb_mcp.sources.atlassian.fetch.adapters.session_file import COOKIES, folder_of, write_cookies
from kb_mcp.sources.atlassian.fetch.app.fetching import FetchCounts
from kb_mcp.sources.atlassian.fetch.domain import names
from kb_mcp.sources.atlassian.fetch.domain.content import Issue, Page
from kb_mcp.sources.atlassian.fetch.domain.coverage import Scope
from kb_mcp.sources.atlassian.prepare.domain.layout import TREE
from kb_mcp.sources.declaration import Source
from kb_mcp.sources.registry import SOURCES
from kb_mcp.sources.stages import Fetcher, Preparer, SourceRun
from kb_mcp.sources.worklog.declared import WORKLOG
from kb_mcp.sources.worklog.prepare.app.prepare import WorklogCounts, WorklogPlanned
from tests.composed import MODEL, sourced
from tests.recorded import unrun
from tests.samples import v2_space
from tests.test_fetching import SITE, FakeSite
from tests.test_incremental_fetch import FIRST, WEEK
from tests.test_prepare_atlassian import (
    FETCHED,
    SPACE_ID,
    issue_responses,
    listing_page,
    page_responses,
)
from tests.test_prepare_worklog import FIXTURE, settle
from tests.test_sources import WORKLOG_DOCUMENTS

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

    from _pytest.capture import CaptureFixture
    from _pytest.monkeypatch import MonkeyPatch

    from kb_mcp.config.domain.settings import Settings
    from kb_mcp.sources.declaration import Connector

# The period of a fetch: the week before the run, which holds what the scripted site serves.
SINCE = {"--since": (FIRST - WEEK).isoformat()}
# Each module that a connector of the registry names, its stages' and its tables'.
NAMED = frozenset(
    path.partition(":")[0]
    for each in (source.connector for source in SOURCES)
    for path in (
        each.table_path,
        *each.preparers,
        *(() if each.fetcher is None else (each.fetcher,)),
    )
)


@pytest.fixture
def home(tmp_path: Path, monkeypatch: MonkeyPatch) -> Path:
    """Give each test a scratch home, and no waiting between requests."""
    scratch = tmp_path / "home"
    scratch.mkdir()
    monkeypatch.setenv("HOME", str(scratch))
    monkeypatch.setenv("KB_MCP_SEARCH_MODE", "lexical")
    return scratch


@pytest.fixture
def worklog(tmp_path: Path) -> Path:
    """Copy the fixture's work log, at fixed times."""
    root = tmp_path / "todo"
    shutil.copytree(FIXTURE, root)
    settle(root)
    return root


def settings_of(data: Path, worklog: Path) -> Settings:
    """Give settings with the site, a data folder, MFS, PRB and the work log."""
    return MODEL(
        data_dir=data,
        sources={
            "confluence": {"spaces": ["MFS"], "site": SITE},
            "jira": {"projects": ["PRB"], "site": SITE},
            "worklog": {"path": worklog},
        },
    )


@pytest.fixture
def settings(home: Path, worklog: Path) -> Settings:
    """Give the settings of every source, the data in the scratch home."""
    return settings_of(home / "data", worklog)


@pytest.fixture
def site(monkeypatch: MonkeyPatch) -> FakeSite:
    """Serve the scripted site of plan 004."""
    fake = FakeSite()
    monkeypatch.setattr(http, "client", lambda *_: fake.client())
    return fake


def signed_in(settings: Settings) -> Settings:
    """Save a session in the settings' data folder, and give the settings."""
    write_cookies(
        folder_of(settings.session, SITE) / COOKIES, [{"name": "s", "value": "v", "domain": "x"}]
    )
    return settings


@pytest.fixture
def stored(settings: Settings) -> Settings:
    """Store a space with one page, and one issue; give the settings."""
    store = RawStore(settings.raw, "confluence")
    with store.writing():
        store.put_space(v2_space(id=SPACE_ID), [listing_page("100", "Home", None, None)], [], [])
        store.put(Page, page_responses("100", "Home", 1, "<p>Home page.</p>", []), FETCHED, {})
    jira = RawStore(settings.raw, "jira")
    with jira.writing():
        jira.put(Issue, issue_responses("What are archived ideas?"), FETCHED, {})
    return settings


def run_of(
    declared: Connector,
    settings: Settings,
    options: Mapping[str, object] | None = None,
    *,
    dry_run: bool = False,
) -> SourceRun:
    """Give a run of a connector's stages for its one source, its tables from the settings.

    At FIRST. Each option that it declares is held, as ``fetch``'s command gives them: None
    when not among ``options``.
    """
    return SourceRun(
        source=Source(name=declared.name, connector=declared),
        sources=SOURCES,
        settings=settings,
        source_table=getattr(settings.sources, declared.name),
        options={**dict.fromkeys(declared.flags), **(options or {})},
        now=lambda: FIRST,
        sleep=lambda _: None,
        dry_run=dry_run,
    )


def fetcher_of(declared: Connector) -> Fetcher:
    """Load the fetcher that a connector names, checked against its interface."""
    assert declared.fetcher is not None
    fetcher = pkgutil.resolve_name(declared.fetcher)
    assert isinstance(fetcher, Fetcher)
    return fetcher


def preparer_of(declared: Connector) -> Preparer:
    """Load the one preparer that a connector names, checked against its interface."""
    (path,) = declared.preparers
    preparer = pkgutil.resolve_name(path)
    assert isinstance(preparer, Preparer)
    return preparer


def folders(docs: Path) -> set[str]:
    """Give the top folders of the mirror that hold a file."""
    return {path.relative_to(docs).parts[0] for path in docs.rglob("*") if path.is_file()}


def files(docs: Path) -> dict[str, bytes]:
    """Give every file of the mirror, by its path within it."""
    return {
        path.relative_to(docs).as_posix(): path.read_bytes()
        for path in sorted(docs.rglob("*"))
        if path.is_file()
    }


def cached(settings: Settings) -> set[str]:
    """Give the sources that rows of the cache of conversions belong to."""
    with closing(sqlite3.connect(settings.conversions)) as connection:
        return {source for (source,) in connection.execute("SELECT source FROM conversions")}


def row_text(name: str, outcome: str, text: str) -> str:
    """Write a row as ``fetch`` and ``prepare`` write it: its name and outcome, then its text."""
    return f"{name}: {outcome}\n" + indent(text, "  ")


@pytest.mark.parametrize(
    "path",
    sorted({each.connector.fetcher for each in SOURCES if each.connector.fetcher is not None}),
)
def test_each_fetcher_that_the_registry_names_loads_as_a_fetcher(path: str) -> None:
    """Loaded by its module path, it has the interface's methods."""
    assert isinstance(pkgutil.resolve_name(path), Fetcher)


@pytest.mark.parametrize(
    "path", sorted({path for each in SOURCES for path in each.connector.preparers})
)
def test_each_preparer_that_the_registry_names_loads_as_a_preparer(path: str) -> None:
    """Loaded by its module path, it has the interface's methods."""
    assert isinstance(pkgutil.resolve_name(path), Preparer)


def test_confluence_and_jira_share_their_roles_and_the_work_log_has_its_own() -> None:
    """One fetcher and one preparer serve both sources of the site; one preparer each.

    The work log's fetcher reads its folder into its copy store, since plan 060.
    """
    assert {
        each.name: (each.connector.fetcher, len(each.connector.preparers)) for each in SOURCES
    } == {
        "confluence": (CONFLUENCE.fetcher, 1),
        "jira": (CONFLUENCE.fetcher, 1),
        "worklog": ("kb_mcp.sources.worklog.fetch.app.fetcher", 1),
    }
    assert CONFLUENCE.fetcher is not None
    assert JIRA.preparers == CONFLUENCE.preparers


def test_help_imports_the_declarations_and_no_module_that_they_name(home: Path) -> None:
    """A declaration names its fetcher, preparers and tables by module path: ``--help`` loads none.

    Neither the command's help nor ``fetch``'s, which lists the sources; ``-X importtime``
    names each module that the child imports.
    """
    environment = {"HOME": str(home), "PATH": os.environ["PATH"]}
    children = (
        subprocess.run(
            [sys.executable, "-X", "importtime", "-m", "kb_mcp", "--help"],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            env=environment,
            cwd=home,
            check=False,
        ),
        subprocess.run(
            [sys.executable, "-X", "importtime", "-m", "kb_mcp", "fetch", "--help"],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            env=environment,
            cwd=home,
            check=False,
        ),
    )
    declared = {"kb_mcp.sources.atlassian.declared", "kb_mcp.sources.worklog.declared"}
    for child in children:
        assert child.returncode == 0
        imported = {
            line.rsplit("|", 1)[-1].strip()
            for line in child.stderr.splitlines()
            if line.startswith("import time:")
        }
        assert declared | {"kb_mcp.sources.registry"} <= imported
        assert imported & (NAMED | {"kb_mcp.sources.stages"}) == set()


def test_the_fetcher_fetches_the_targets_of_the_source_that_it_runs_for(
    settings: Settings, site: FakeSite
) -> None:
    """Confluence's run lists its spaces and asks Jira nothing; Jira's, its projects alone."""
    fetcher = fetcher_of(CONFLUENCE)
    confluence = fetcher.fetch(run_of(CONFLUENCE, signed_in(settings), SINCE))
    first = list(site.asked)
    assert isinstance(confluence.counts, FetchCounts)
    covered = RawStore(settings.raw, "confluence").coverage().periods
    assert set(covered) == {Scope(source="confluence", type=names.SPACE, key="MFS")}
    jira = fetcher_of(JIRA).fetch(run_of(JIRA, settings, SINCE))
    then = site.asked[len(first) :]
    assert isinstance(jira.counts, FetchCounts)
    assert first
    assert [url.path for url in first if url.path.startswith("/rest/api/3/")] == []
    assert then
    assert [url.path for url in then if url.path.startswith("/wiki/")] == []
    assert set(RawStore(settings.raw, "confluence").coverage().periods) == {
        Scope(source="confluence", type=names.SPACE, key="MFS"),
        Scope(source="jira", type=names.PROJECT, key="PRB"),
    }


@pytest.mark.usefixtures("site")
def test_a_source_of_another_name_is_fetched_and_prepared_under_its_name(home: Path) -> None:
    """Plan 056, criterion 3: Confluence's connector, its one source named ``wiki``.

    Fetched, then prepared, from the scripted site: its raw folder, its mirror's folder
    and each of its documents' front matter carry its name; nothing carries the
    connector's, the site's users neither, which plan 059 keeps in its folder.
    """
    registry = (Source(name="wiki", connector=CONFLUENCE), *sourced(JIRA, WORKLOG))
    config = home / "config.toml"
    config.write_text(f'[sources.wiki]\nspaces = ["MFS"]\nsite = "{SITE}"\n')
    data = home / "data"
    write_cookies(
        folder_of(data / "session", SITE) / COOKIES, [{"name": "s", "value": "v", "domain": "x"}]
    )
    given = ["--yes", "--config", str(config), "--data-dir", str(data), "wiki"]
    # A file of the scripted site fails, which fails the fetch.
    assert main(["fetch", *given, "--since", SINCE["--since"]], registry) == ExitStatus.FAILED
    assert main(["prepare", *given], registry) == ExitStatus.OK
    assert sorted(each.name for each in (data / "raw").iterdir() if each.is_dir()) == [
        "blobs",
        "wiki",
    ]
    assert (data / "raw" / "wiki" / "users.json").is_file()
    assert (data / "raw" / "wiki" / "pages").is_dir()
    assert (data / "raw" / "wiki" / "spaces").is_dir()
    assert sorted(each.name for each in (data / "docs").iterdir()) == ["assets", "wiki"]
    written = sorted((data / "docs" / "wiki").rglob("*.md"))
    assert written
    sources = {
        load(path.read_text("utf-8"), path.name)[0].source for path in written if path.name != TREE
    }
    assert sources == {"wiki"}


def test_a_work_log_of_another_name_is_prepared_under_its_name(home: Path, worklog: Path) -> None:
    """Plan 056: the work log's connector, its one source named ``notes``: its folder and name."""
    registry = (*sourced(CONFLUENCE, JIRA), Source(name="notes", connector=WORKLOG))
    config = home / "config.toml"
    config.write_text(f"[sources.notes]\npath = {json.dumps(str(worklog))}\n", "utf-8")
    data = home / "data"
    given = ["notes", "--yes", "--config", str(config), "--data-dir", str(data)]
    assert main(["fetch", *given], registry) == ExitStatus.OK
    assert sorted(each.name for each in (data / "copies").iterdir()) == ["notes"]
    assert main(["prepare", *given], registry) == ExitStatus.OK
    assert sorted(each.name for each in (data / "docs").iterdir()) == ["notes"]
    written = sorted((data / "docs" / "notes").rglob("*.md"))
    assert len(written) == WORKLOG_DOCUMENTS
    assert {load(path.read_text("utf-8"), path.name)[0].source for path in written} == {"notes"}


def test_a_fetch_with_no_session_saved_is_to_sign_in_before_any_request(
    settings: Settings, site: FakeSite
) -> None:
    """No token and no session: the outcome says to sign in, and the site is asked nothing."""
    fetched = fetcher_of(CONFLUENCE).fetch(run_of(CONFLUENCE, settings, SINCE))
    assert fetched.ending == "sign in again"
    assert site.asked == []


def test_a_dry_run_fetch_plans_and_writes_nothing(settings: Settings, site: FakeSite) -> None:
    """The fetcher plans: it asks the site, and the raw store is not written."""
    fetched = fetcher_of(JIRA).fetch(run_of(JIRA, signed_in(settings), SINCE, dry_run=True))
    assert fetched.ending == "not run"
    assert isinstance(fetched.counts, FetchCounts)
    assert fetched.counts.dry_run
    assert site.asked
    assert not settings.raw.exists()


def test_the_fetcher_refuses_an_until_before_since_before_any_request(
    settings: Settings, site: FakeSite
) -> None:
    """Read before the fetch asks anything: the period names the options at fault."""
    fetcher = fetcher_of(JIRA)
    assert fetcher.preflight(run_of(JIRA, signed_in(settings), SINCE)) is None
    backwards = {"--since": "2026-10-20", "--until": "2026-10-01"}
    refusal = fetcher.preflight(run_of(JIRA, settings, backwards))
    assert refusal is not None
    assert "--until: must come after --since" in refusal
    assert site.asked == []


def test_a_damaged_record_of_what_answered_as_gone_fails_its_fetch_before_any_request(
    home: Path, monkeypatch: MonkeyPatch, capsys: CaptureFixture[str]
) -> None:
    """Its row fails, exit 1, an event naming the source and the file, no traceback.

    The fetch reads the record before its first request, so its preflight reads it too.
    A site and a token, made up, leave nothing else to stop the run.
    """
    data = home / "data"
    (data / "raw").mkdir(parents=True)
    (data / "raw" / "tombstones.json").write_text("not json", "utf-8")
    config = home / "config.toml"
    config.write_text(
        f'[sources.confluence]\nspaces = ["MFS"]\nsite = "{SITE}"\n'
        'email = "someone@example.invalid"\n',
        "utf-8",
    )
    monkeypatch.setenv("KB_MCP_SOURCES__CONFLUENCE__API_TOKEN", "made-up")
    given = ["fetch", "--yes", "--config", str(config), "--data-dir", str(data)]
    assert main(given) == ExitStatus.FAILED
    err = capsys.readouterr().err
    assert "fetch.refused" in err
    assert "tombstones.json: not JSON" in err
    assert "run.failed" not in err
    assert "Traceback" not in err
    assert not (data / "docs").exists()


@pytest.mark.parametrize("name", ["tombstones.json", "coverage.json"])
def test_a_record_that_no_read_reaches_fails_the_fetch_as_a_damaged_one(
    home: Path,
    monkeypatch: MonkeyPatch,
    capsys: CaptureFixture[str],
    site: FakeSite,
    name: str,
) -> None:
    """A folder in its place: exit 1, naming the file, no traceback, nothing asked of the site.

    In ``fetch``, by its preflight, with or without a source named.
    """
    data = home / "data"
    (data / "raw" / name).mkdir(parents=True)
    config = home / "config.toml"
    config.write_text(
        f'[sources.confluence]\nspaces = ["MFS"]\nsite = "{SITE}"\n'
        'email = "someone@example.invalid"\n',
        "utf-8",
    )
    monkeypatch.setenv("KB_MCP_SOURCES__CONFLUENCE__API_TOKEN", "made-up")
    given = ["--yes", "--config", str(config), "--data-dir", str(data)]
    for command in (["fetch"], ["fetch", "confluence"]):
        assert main([*command, *given]) == ExitStatus.FAILED
        err = capsys.readouterr().err
        assert f"{name}: not read: IsADirectoryError" in err
        assert "run.failed" not in err
        assert "Traceback" not in err
    assert site.asked == []


# A record of what answered as gone, whole but not as the store writes it: a page of
# another space that the scripted space lists, and one that it does not.
RECORD = (
    '[{"source":"confluence","type":"page","id":"1001","scope":"OPS","first_gone":null,'
    '"confirmed":false},'
    '{"source":"confluence","type":"page","id":"1009","scope":"OPS","first_gone":null,'
    '"confirmed":false}]'
)


def test_a_fetch_of_jira_reads_what_answered_as_gone_and_keeps_confluence_s(
    settings: Settings, site: FakeSite
) -> None:
    """Plan 061: every connector's whole reads start absences, in the one record.

    Jira's fetch keeps each tombstone of Confluence's as it finds it, and asks Confluence
    nothing. The record damaged fails Jira's fetch alone, by the record's name, before
    anything is asked: its preflight stops no other source.
    """
    settings.raw.mkdir(parents=True)
    stones = settings.raw / "tombstones.json"
    stones.write_text(RECORD, "utf-8")
    run = run_of(JIRA, signed_in(settings), SINCE)
    assert fetcher_of(JIRA).preflight(run) is None
    assert fetcher_of(JIRA).fetch(run).ending == "done"
    assert list(RawStore(settings.raw, "jira").tombstones()) == [
        ("confluence", "page", "1001"),
        ("confluence", "page", "1009"),
    ]
    assert any(each.path.startswith("/rest/api/3/") for each in site.asked)
    assert not any(each.path.startswith("/wiki/") for each in site.asked)
    stones.write_text("not json", "utf-8")
    asked = len(site.asked)
    assert fetcher_of(JIRA).preflight(run) is None
    failed = fetcher_of(JIRA).fetch(run)
    assert (failed.ending, failed.problems) == (
        "failed",
        (Problem(where="jira", reason="tombstones.json: not JSON"),),
    )
    assert len(site.asked) == asked


def test_a_fetch_of_confluence_keeps_each_tombstone_that_it_finds(
    settings: Settings, site: FakeSite
) -> None:
    """Whole, the record is read, and what it holds of another space is there once it ends.

    But for a page that the space's whole read lists, present there, plan 061's.
    """
    settings.raw.mkdir(parents=True)
    (settings.raw / "tombstones.json").write_text(RECORD, "utf-8")
    run = run_of(CONFLUENCE, signed_in(settings), SINCE)
    assert fetcher_of(CONFLUENCE).preflight(run) is None
    assert fetcher_of(CONFLUENCE).fetch(run).counts is not None
    assert list(RawStore(settings.raw, "confluence").tombstones()) == [
        ("confluence", "page", "1009")
    ]
    assert any(each.path.startswith("/wiki/") for each in site.asked)


@pytest.mark.parametrize(
    "given",
    [("prepare", "jira", "--yes"), ("fetch", "worklog", "--yes")],
    ids=["a prepare of Jira", "a fetch of the work log"],
)
def test_a_damaged_record_of_what_answered_as_gone_stops_no_prepare_nor_work_log_fetch(
    home: Path,
    worklog: Path,
    capsys: CaptureFixture[str],
    given: tuple[str, ...],
) -> None:
    """Each gives the row of the source that it names, on a damaged record of what is gone.

    The record's problem is the prepare of spaces', a warning of Jira's, nothing of the work
    log's, whose fetch reads its copy store alone.
    """
    data = home / "data"
    (data / "raw").mkdir(parents=True)
    stones = data / "raw" / "tombstones.json"
    stones.write_text("not json", "utf-8")
    config = home / "config.toml"
    config.write_text(
        f'[sources.confluence]\nspaces = ["MFS"]\nsite = "{SITE}"\n'
        f'[sources.jira]\nprojects = ["PRB"]\nsite = "{SITE}"\n'
        f"[sources.worklog]\npath = {json.dumps(str(worklog))}\n",
        "utf-8",
    )
    arguments = [*given, "--format", "json", "--config", str(config), "--data-dir", str(data)]
    assert main(arguments) == ExitStatus.OK
    out, err = capsys.readouterr()
    assert ".refused" not in err
    assert [row["source"] for row in json.loads(out)["sources"]] == [given[1]]
    assert stones.read_text("utf-8") == "not json"


def test_a_damaged_pending_record_refuses_a_fetch_of_its_space_alone(
    settings: Settings, site: FakeSite
) -> None:
    """Truncated: named by its path by the preflight of a run of its space, and of no other.

    The run's space is MFS; a space outside it, damaged, stops nothing.
    """
    store = RawStore(settings.raw, "confluence")
    with store.writing():
        store.put_space(v2_space(id="111", key="OPS"), [], [], [])
        store.put_space(v2_space(id=SPACE_ID), [], [], [])
    (settings.raw / "confluence" / "spaces" / "111" / "pending.json").write_text("[", "utf-8")
    run = run_of(CONFLUENCE, signed_in(settings), SINCE)
    assert fetcher_of(CONFLUENCE).preflight(run) is None
    (settings.raw / "confluence" / "spaces" / SPACE_ID / "pending.json").write_text("[", "utf-8")
    refusal = fetcher_of(CONFLUENCE).preflight(run)
    assert refusal == f"confluence/spaces/{SPACE_ID}/pending.json: not JSON"
    assert site.asked == []


@pytest.mark.parametrize(
    ("damaged", "options", "said"),
    [
        (True, SINCE, "tombstones.json: not JSON"),
        (False, {"--since": "2026-10-20", "--until": "2026-10-01"}, "--until: must come after"),
    ],
    ids=["a record damaged since", "a period read at a later fetch's start"],
)
def test_what_a_preflight_refuses_once_the_run_began_fails_the_fetch_saying_why(
    settings: Settings,
    site: FakeSite,
    *,
    damaged: bool,
    options: Mapping[str, object],
    said: str,
) -> None:
    """Its row fails, naming the source, where the run's other rows then go on.

    Not an exception out of the run, as a run that cannot read a record has no row to
    rank; nothing is asked of the site.
    """
    if damaged:
        settings.raw.mkdir(parents=True)
        (settings.raw / "tombstones.json").write_text("not json", "utf-8")
    with capture_logs() as events:
        fetched = fetcher_of(CONFLUENCE).fetch(run_of(CONFLUENCE, signed_in(settings), options))
    assert (fetched.ending, fetched.counts) == ("failed", None)
    (problem,) = fetched.problems
    assert problem.where == "confluence"
    assert said in problem.reason
    (refused,) = [each for each in events if each["event"] == "fetch.refused"]
    assert refused["log_level"] == "error"
    assert refused["source"] == "confluence"
    assert said in refused["reason"]
    assert site.asked == []


@pytest.mark.usefixtures("site")
def test_the_fetch_s_text_is_what_download_writes(
    home: Path,
    settings: Settings,
    worklog: Path,
    monkeypatch: MonkeyPatch,
    capsys: CaptureFixture[str],
) -> None:
    """Confluence's fetch writes the counts that ``fetch --space MFS`` writes under its row.

    A file of the scripted site fails, which fails both.
    """
    fetched = fetcher_of(CONFLUENCE).fetch(run_of(CONFLUENCE, signed_in(settings), SINCE))
    assert fetched.ending == "failed"
    other = signed_in(settings_of(home / "other", worklog))
    command = ["fetch", "--yes", "--config", str(home / "none.toml"), "--space", "MFS"]
    period = ["--since", SINCE["--since"]]
    given = [*command, "--data-dir", str(other.data_dir), *period]
    monkeypatch.setenv("KB_MCP_SOURCES__CONFLUENCE__SITE", SITE)
    capsys.readouterr()  # what the fetch logged, outside a run, which has no log file
    assert main(given) == ExitStatus.FAILED
    indented = "".join(f"  {line}\n" for line in fetched.text("short").splitlines())
    assert unrun(capsys.readouterr().out) == f"confluence: failed\n{indented}"


def test_the_atlassian_preparer_mirrors_the_kinds_of_the_source_that_it_runs_for(
    stored: Settings,
) -> None:
    """Confluence's run writes its files and cache rows alone; Jira's, then, its own."""
    preparer = preparer_of(CONFLUENCE)
    assert preparer.preflight(run_of(CONFLUENCE, stored)) is None
    confluence = preparer.prepare(run_of(CONFLUENCE, stored))
    assert (confluence.ending, folders(stored.docs), cached(stored)) == (
        "done",
        {"confluence"},
        {"confluence"},
    )
    jira = preparer_of(JIRA).prepare(run_of(JIRA, stored))
    assert (jira.ending, folders(stored.docs), cached(stored)) == (
        "done",
        {"confluence", "jira"},
        {"confluence", "jira"},
    )


def test_the_atlassian_preparer_writes_and_says_what_prepare_does(
    home: Path, stored: Settings, monkeypatch: MonkeyPatch, capsys: CaptureFixture[str]
) -> None:
    """Confluence's preparer, then Jira's, write the command's files and rows byte for byte."""
    other = home / "other"
    shutil.copytree(stored.raw, other / "raw")
    said = ""
    for declared in (CONFLUENCE, JIRA):
        result = preparer_of(declared).prepare(run_of(declared, stored))
        said += row_text(declared.name, result.ending, result.text("detailed"))
    command = ["prepare", "--yes", "--config", str(home / "none.toml"), "--detail", "detailed"]
    capsys.readouterr()  # what the prepares logged, outside a run, which has no log file
    for source in ("CONFLUENCE", "JIRA"):
        monkeypatch.setenv(f"KB_MCP_SOURCES__{source}__SITE", SITE)
    assert main([*command, "--data-dir", str(other)]) == ExitStatus.OK
    assert unrun(capsys.readouterr().out) == said
    assert files(stored.docs) == files(other / "docs")


def test_a_dry_run_leaves_the_atlassian_prepare_alone(stored: Settings) -> None:
    """Nothing is converted nor written, and the result says that it counts nothing."""
    result = preparer_of(CONFLUENCE).prepare(run_of(CONFLUENCE, stored, dry_run=True))
    assert (result.ending, result.counts) == ("not run", None)
    assert result.text("detailed").startswith("warning: confluence: not counted: ")
    assert not stored.docs.exists()


def test_pandoc_gone_fails_each_preparer_that_converts_and_writes_nothing(
    stored: Settings, monkeypatch: MonkeyPatch
) -> None:
    """Each finds pandoc itself, when it runs: gone since, its result fails, an error says so."""
    message = "pandoc: not found on PATH; install pandoc 3"

    def gone() -> Pandoc:
        raise PandocMissingError(message)

    assert fetcher_of(WORKLOG).fetch(run_of(WORKLOG, stored)).ending == "done"
    monkeypatch.setattr(Pandoc, "find", gone)
    with capture_logs() as logged:
        results = [
            preparer_of(declared).prepare(run_of(declared, stored))
            for declared in (CONFLUENCE, WORKLOG)
        ]
    assert [(result.ending, result.counts, result.problems) for result in results] == [
        ("failed", None, (Problem(where="pandoc", reason=message),)),
        ("failed", None, (Problem(where="pandoc", reason=message),)),
    ]
    assert [(each["event"], each["log_level"], each["reason"]) for each in logged] == [
        ("prepare.pandoc_missing", "error", message),
        ("worklog.pandoc_failed", "error", message),
    ]
    assert not stored.docs.exists()


@pytest.mark.parametrize("name", ["todo.org", "missing"])
def test_the_work_log_s_preflight_refuses_a_path_that_is_not_a_folder(
    home: Path, settings: Settings, worklog: Path, name: str
) -> None:
    """The fetcher's: its own folder passes; a file, or nothing, is refused by its setting.

    The preparer, which reads the copy store alone, refuses neither.
    """
    fetcher = fetcher_of(WORKLOG)
    assert fetcher.preflight(run_of(WORKLOG, settings)) is None
    elsewhere = settings_of(home / "data", worklog / name)
    refusal = fetcher.preflight(run_of(WORKLOG, elsewhere))
    assert refusal == "sources.worklog.path: not a folder"
    assert preparer_of(WORKLOG).preflight(run_of(WORKLOG, elsewhere)) is None


def test_the_work_log_s_preparer_counts_in_a_dry_run_then_mirrors_its_copy_store(
    settings: Settings,
) -> None:
    """Without a copy store, its row fails, naming the fetch; then a dry run, then a run.

    Plan 060: a prepare never fetches; a dry run writes nothing, a run every document.
    """
    preparer = preparer_of(WORKLOG)
    with capture_logs() as logged:
        unfetched = preparer.prepare(run_of(WORKLOG, settings))
    assert (unfetched.ending, unfetched.counts, unfetched.problems) == (
        "failed",
        None,
        (Problem(where="copy store", reason="none yet: `kb-mcp fetch worklog` writes it"),),
    )
    assert [(each["event"], each["log_level"]) for each in logged] == [
        ("worklog.store_unread", "error")
    ]
    assert fetcher_of(WORKLOG).fetch(run_of(WORKLOG, settings)).ending == "done"
    planned = preparer.prepare(run_of(WORKLOG, settings, dry_run=True))
    assert planned.ending == "not run"
    assert isinstance(planned.counts, WorklogPlanned)
    assert (planned.counts.documents, planned.counts.to_remove) == (WORKLOG_DOCUMENTS, 0)
    assert not settings.docs.exists()
    done = preparer.prepare(run_of(WORKLOG, settings))
    assert done.ending == "done"
    assert isinstance(done.counts, WorklogCounts)
    assert done.counts.documents == WORKLOG_DOCUMENTS
    assert folders(settings.docs) == {"worklog"}


def test_the_work_log_s_text_is_what_prepare_writes_under_its_row(
    home: Path, settings: Settings, worklog: Path, tmp_path: Path, capsys: CaptureFixture[str]
) -> None:
    """The prepare's text, under its row, is what ``prepare worklog`` writes there."""
    fetcher_of(WORKLOG).fetch(run_of(WORKLOG, settings))
    result = preparer_of(WORKLOG).prepare(run_of(WORKLOG, settings))
    copied = tmp_path / "copied"
    shutil.copytree(worklog, copied)
    settle(copied)
    config = home / "config.toml"
    config.write_text(f'[sources.worklog]\npath = "{copied}"\n', "utf-8")
    options = ["--yes", "--config", str(config), "worklog", "--data-dir", str(home / "other")]
    assert main(["fetch", *options]) == ExitStatus.OK
    given = ["prepare", *options, "--detail", "detailed"]
    capsys.readouterr()  # what the prepare logged, outside a run, which has no log file
    assert main(given) == ExitStatus.OK
    out = unrun(capsys.readouterr().out)
    assert out.startswith(row_text("worklog", result.ending, result.text("detailed")))
