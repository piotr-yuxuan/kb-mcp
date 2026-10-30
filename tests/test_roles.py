"""The roles of a source, each one that the registry names, as plan 030 defines them.

The expectations come from the plan's "A source's declaration, and the roles'
interfaces": a declaration names its fetcher, if any, and its preparers by module path,
which ``--help`` never imports; one fetcher and one preparer serve Confluence and Jira,
each reading from ``run.declared`` the source that it runs for, so its kinds and its
rows of the cache of conversions; the work log, read in place, has no fetcher;
``preflight`` says what a role cannot go on with before any source starts; each
preparer that converts finds pandoc itself, so that pandoc gone fails its result alone;
a dry run plans the fetch, counts the work log and leaves Atlassian's prepare alone; and
a result's ``text`` writes what its command writes. The site is plan 004's scripted one,
the work log the invented fixture; each test has a scratch home.
"""

from __future__ import annotations

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
from kb_mcp.mirror.adapters.pandoc import Pandoc, PandocMissingError
from kb_mcp.sources.atlassian.declared import CONFLUENCE, JIRA
from kb_mcp.sources.atlassian.fetch.adapters import http
from kb_mcp.sources.atlassian.fetch.adapters.raw_store import RawStore
from kb_mcp.sources.atlassian.fetch.adapters.session_file import COOKIES, write_cookies
from kb_mcp.sources.atlassian.fetch.app.fetcher import Fetched
from kb_mcp.sources.atlassian.fetch.domain.content import Issue, Page
from kb_mcp.sources.atlassian.fetch.domain.coverage import Target
from kb_mcp.sources.registry import SOURCES
from kb_mcp.sources.roles import Fetcher, Preparer, Run
from kb_mcp.sources.worklog.declared import WORKLOG
from kb_mcp.sources.worklog.prepare.app.prepare import Outcome, Planned
from tests.composed import MODEL
from tests.samples import v2_space
from tests.test_download import SITE, FakeSite
from tests.test_mirror import FETCHED, SPACE_ID, issue_responses, listing_page, page_responses
from tests.test_refresh import FIRST, WEEK
from tests.test_sync import WORKLOG_DOCUMENTS
from tests.test_worklog_mirror import FIXTURE, settle

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

    from _pytest.capture import CaptureFixture
    from _pytest.monkeypatch import MonkeyPatch

    from kb_mcp.config.domain.settings import Settings
    from kb_mcp.sources.declaration import Declared

# The period of a fetch: the week before the run, which holds what the scripted site serves.
SINCE = {"--since": (FIRST - WEEK).isoformat()}
# Each module that a declaration of the registry names, its roles' and its tables'.
NAMED = frozenset(
    path.partition(":")[0]
    for each in SOURCES
    for path in (
        each.table,
        *each.preparers,
        *(() if each.fetcher is None else (each.fetcher,)),
        *(() if each.account is None else (each.account.table,)),
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
        accounts={"atlassian": {"site": SITE}},
        data_dir=data,
        sources={
            "confluence": {"spaces": ["MFS"]},
            "jira": {"projects": ["PRB"]},
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
    write_cookies(settings.session / COOKIES, [{"name": "s", "value": "v", "domain": "x"}])
    return settings


@pytest.fixture
def stored(settings: Settings) -> Settings:
    """Store a space with one page, and one issue; give the settings."""
    store = RawStore(settings.raw)
    with store.writing():
        store.put_space(v2_space(id=SPACE_ID), [listing_page("100", "Home", None, None)], [], [])
        store.put(Page, page_responses("100", "Home", 1, "<p>Home page.</p>", []), FETCHED, {})
        store.put(Issue, issue_responses("What are archived ideas?"), FETCHED, {})
    return settings


def run_of(
    declared: Declared,
    settings: Settings,
    options: Mapping[str, object] | None = None,
    *,
    dry_run: bool = False,
) -> Run:
    """Give a run of a declaration's roles, its tables from the settings, at FIRST."""
    account = declared.account
    return Run(
        declared=declared,
        settings=settings,
        table=getattr(settings.sources, declared.name),
        account=None if account is None else getattr(settings.accounts, account.name),
        options=options or {},
        now=lambda: FIRST,
        sleep=lambda _: None,
        dry_run=dry_run,
    )


def fetcher_of(declared: Declared) -> Fetcher:
    """Load the fetcher that a declaration names, checked against its role."""
    assert declared.fetcher is not None
    fetcher = pkgutil.resolve_name(declared.fetcher)
    assert isinstance(fetcher, Fetcher)
    return fetcher


def preparer_of(declared: Declared) -> Preparer:
    """Load the one preparer that a declaration names, checked against its role."""
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
    """Write a row as ``sync`` and ``mirror`` write it: its name and outcome, then its text."""
    return f"{name}: {outcome}\n" + indent(text, "  ")


@pytest.mark.parametrize(
    "path",
    sorted({each.fetcher for each in SOURCES if each.fetcher is not None}),
)
def test_each_fetcher_that_the_registry_names_loads_as_a_fetcher(path: str) -> None:
    """Loaded by its module path, it has the role's methods."""
    assert isinstance(pkgutil.resolve_name(path), Fetcher)


@pytest.mark.parametrize("path", sorted({path for each in SOURCES for path in each.preparers}))
def test_each_preparer_that_the_registry_names_loads_as_a_preparer(path: str) -> None:
    """Loaded by its module path, it has the role's methods."""
    assert isinstance(pkgutil.resolve_name(path), Preparer)


def test_confluence_and_jira_share_their_roles_and_the_work_log_has_no_fetcher() -> None:
    """One fetcher and one preparer serve both sources of the site; one preparer each."""
    assert {each.name: (each.fetcher, len(each.preparers)) for each in SOURCES} == {
        "confluence": (CONFLUENCE.fetcher, 1),
        "jira": (CONFLUENCE.fetcher, 1),
        "worklog": (None, 1),
    }
    assert CONFLUENCE.fetcher is not None
    assert JIRA.preparers == CONFLUENCE.preparers


def test_help_imports_the_declarations_and_no_module_that_they_name(home: Path) -> None:
    """A declaration names its roles and tables by module path: ``--help`` loads none.

    Neither the command's help nor ``sync``'s, which lists the sources; ``-X importtime``
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
            [sys.executable, "-X", "importtime", "-m", "kb_mcp", "sync", "--help"],
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
        assert imported & (NAMED | {"kb_mcp.sources.roles"}) == set()


def test_the_fetcher_fetches_the_targets_of_the_source_that_it_runs_for(
    settings: Settings, site: FakeSite
) -> None:
    """Confluence's run lists its spaces and asks Jira nothing; Jira's, its projects alone."""
    fetcher = fetcher_of(CONFLUENCE)
    confluence = fetcher.fetch(run_of(CONFLUENCE, signed_in(settings), SINCE))
    first = list(site.asked)
    assert isinstance(confluence, Fetched)
    assert confluence.downloaded is not None
    covered = RawStore(settings.raw).coverage().periods
    assert set(covered) == {Target(source="confluence", key="MFS")}
    jira = fetcher_of(JIRA).fetch(run_of(JIRA, settings, SINCE))
    then = site.asked[len(first) :]
    assert isinstance(jira, Fetched)
    assert jira.downloaded is not None
    assert first
    assert [url.path for url in first if url.path.startswith("/rest/api/3/")] == []
    assert then
    assert [url.path for url in then if url.path.startswith("/wiki/")] == []
    assert set(RawStore(settings.raw).coverage().periods) == {
        Target(source="confluence", key="MFS"),
        Target(source="jira", key="PRB"),
    }


def test_a_fetch_with_no_session_saved_is_to_sign_in_before_any_request(
    settings: Settings, site: FakeSite
) -> None:
    """No token and no session: the outcome says to sign in, and the site is asked nothing."""
    fetched = fetcher_of(CONFLUENCE).fetch(run_of(CONFLUENCE, settings, SINCE))
    assert fetched.outcome == "sign in"
    assert site.asked == []


def test_a_dry_run_fetch_plans_and_writes_nothing(settings: Settings, site: FakeSite) -> None:
    """The fetcher plans: it asks the site, and the raw store is not written."""
    fetched = fetcher_of(JIRA).fetch(run_of(JIRA, signed_in(settings), SINCE, dry_run=True))
    assert isinstance(fetched, Fetched)
    assert fetched.downloaded is not None
    assert fetched.downloaded.dry_run
    assert site.asked
    assert not settings.raw.exists()


def test_the_fetcher_refuses_an_until_before_since_before_any_request(
    settings: Settings, site: FakeSite
) -> None:
    """Read from disk before any source starts: the period names the options at fault."""
    fetcher = fetcher_of(JIRA)
    assert fetcher.preflight(run_of(JIRA, signed_in(settings), SINCE)) is None
    backwards = {"--since": "2026-10-20", "--until": "2026-10-01"}
    refusal = fetcher.preflight(run_of(JIRA, settings, backwards))
    assert refusal is not None
    assert "--until: must come after --since" in refusal
    assert site.asked == []


@pytest.mark.usefixtures("site")
def test_the_fetch_s_text_is_what_download_writes(
    home: Path, settings: Settings, worklog: Path, capsys: CaptureFixture[str]
) -> None:
    """Confluence's fetch writes the counts that ``download --space MFS`` writes under its row.

    A file of the scripted site fails, which fails both.
    """
    fetched = fetcher_of(CONFLUENCE).fetch(run_of(CONFLUENCE, signed_in(settings), SINCE))
    assert fetched.outcome == "failed"
    other = signed_in(settings_of(home / "other", worklog))
    command = ["download", "--yes", "--config", str(home / "none.toml"), "--space", "MFS"]
    period = ["--since", SINCE["--since"]]
    given = [*command, "--data-dir", str(other.data_dir), "--site", SITE, *period]
    capsys.readouterr()  # what the fetch logged, outside a run, which has no log file
    assert main(given) == ExitStatus.FAILED
    indented = "".join(f"  {line}\n" for line in fetched.text("short").splitlines())
    assert capsys.readouterr().out == f"download confluence: failed\n{indented}"


def test_the_atlassian_preparer_mirrors_the_kinds_of_the_source_that_it_runs_for(
    stored: Settings,
) -> None:
    """Confluence's run writes its files and cache rows alone; Jira's, then, its own."""
    preparer = preparer_of(CONFLUENCE)
    assert preparer.preflight(run_of(CONFLUENCE, stored)) is None
    confluence = preparer.prepare(run_of(CONFLUENCE, stored))
    assert (confluence.outcome, folders(stored.docs), cached(stored)) == (
        "done",
        {"confluence"},
        {"confluence"},
    )
    jira = preparer_of(JIRA).prepare(run_of(JIRA, stored))
    assert (jira.outcome, folders(stored.docs), cached(stored)) == (
        "done",
        {"confluence", "jira"},
        {"confluence", "jira"},
    )


def test_the_atlassian_preparer_writes_and_says_what_mirror_does(
    home: Path, stored: Settings, capsys: CaptureFixture[str]
) -> None:
    """Confluence's prepare, then Jira's, write mirror's files, byte for byte, and its rows."""
    other = home / "other"
    shutil.copytree(stored.raw, other / "raw")
    said = ""
    for declared in (CONFLUENCE, JIRA):
        result = preparer_of(declared).prepare(run_of(declared, stored))
        said += row_text(f"mirror {declared.name}", result.outcome, result.text("detailed"))
    command = ["mirror", "--yes", "--config", str(home / "none.toml"), "--summary", "detailed"]
    capsys.readouterr()  # what the prepares logged, outside a run, which has no log file
    assert main([*command, "--data-dir", str(other), "--site", SITE]) == ExitStatus.OK
    assert capsys.readouterr().out == said
    assert files(stored.docs) == files(other / "docs")


def test_a_dry_run_leaves_the_atlassian_prepare_alone(stored: Settings) -> None:
    """Nothing is converted nor written, and the result has no counts to write."""
    result = preparer_of(CONFLUENCE).prepare(run_of(CONFLUENCE, stored, dry_run=True))
    assert (result.outcome, result.text("detailed")) == ("not run", "")
    assert not stored.docs.exists()


def test_pandoc_gone_fails_each_preparer_that_converts_and_writes_nothing(
    stored: Settings, monkeypatch: MonkeyPatch
) -> None:
    """Each finds pandoc itself, when it runs: gone since, its result fails, an error says so."""
    message = "pandoc: not found on PATH; install pandoc 3"

    def gone() -> Pandoc:
        raise PandocMissingError(message)

    monkeypatch.setattr(Pandoc, "find", gone)
    with capture_logs() as logged:
        results = [
            preparer_of(declared).prepare(run_of(declared, stored))
            for declared in (CONFLUENCE, WORKLOG)
        ]
    assert [(result.outcome, result.text("detailed")) for result in results] == [
        ("failed", ""),
        ("failed", ""),
    ]
    assert [(each["event"], each["log_level"], each["reason"]) for each in logged] == [
        ("mirror.pandoc_missing", "error", message),
        ("worklog.pandoc_failed", "error", message),
    ]
    assert not stored.docs.exists()


@pytest.mark.parametrize("name", ["todo.org", "missing"])
def test_the_work_log_s_preflight_refuses_a_path_that_is_not_a_folder(
    home: Path, settings: Settings, worklog: Path, name: str
) -> None:
    """The work log's own folder passes; a file, or nothing, is refused by its setting."""
    preparer = preparer_of(WORKLOG)
    assert preparer.preflight(run_of(WORKLOG, settings)) is None
    elsewhere = settings_of(home / "data", worklog / name)
    refusal = preparer.preflight(run_of(WORKLOG, elsewhere))
    assert refusal == "sources.worklog.path: not a folder"


def test_the_work_log_s_preparer_counts_in_a_dry_run_then_mirrors_its_folder(
    settings: Settings,
) -> None:
    """A dry run converts and writes nothing; a run writes every document under worklog/."""
    preparer = preparer_of(WORKLOG)
    planned = preparer.prepare(run_of(WORKLOG, settings, dry_run=True))
    assert planned.outcome == "done"
    assert isinstance(planned.mirrored, Planned)
    assert planned.mirrored.to_convert == WORKLOG_DOCUMENTS
    assert not settings.docs.exists()
    done = preparer.prepare(run_of(WORKLOG, settings))
    assert done.outcome == "done"
    assert isinstance(done.mirrored, Outcome)
    assert done.mirrored.documents == WORKLOG_DOCUMENTS
    assert folders(settings.docs) == {"worklog"}


def test_the_work_log_s_text_is_what_sync_writes_under_its_row(
    home: Path, settings: Settings, worklog: Path, tmp_path: Path, capsys: CaptureFixture[str]
) -> None:
    """The prepare's text, under its row, is what ``sync --include worklog`` writes there."""
    result = preparer_of(WORKLOG).prepare(run_of(WORKLOG, settings))
    copied = tmp_path / "copied"
    shutil.copytree(worklog, copied)
    settle(copied)
    config = home / "config.toml"
    config.write_text(f'[sources.worklog]\npath = "{copied}"\n', "utf-8")
    command = ["sync", "--yes", "--config", str(config), "--include", "worklog"]
    given = [*command, "--data-dir", str(home / "other"), "--summary", "detailed"]
    capsys.readouterr()  # what the prepare logged, outside a run, which has no log file
    assert main(given) == ExitStatus.OK
    out = capsys.readouterr().out
    assert out.startswith(row_text("worklog", result.outcome, result.text("detailed")) + "index:")
