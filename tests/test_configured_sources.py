"""Sources that the settings configure: any number of each connector, by name.

The expectations come from plan 059, "The settings": ``[sources.<name>]`` names its
``connector``, by default its own name, so that a second Jira site is a second source of
one connector; the registry's sources always exist; a name off the rule, or of a
connector that the registry does not hold, is refused naming it; the environment names
sources as the file does. ``--space`` and ``--project`` override the list of the one
source that declares them among those named, and are refused, naming the sources, when
several are left.
"""

from __future__ import annotations

import json
import time
from typing import TYPE_CHECKING

import pytest

from kb_mcp.cli.commands import sources as sources_command
from kb_mcp.cli.main import main
from kb_mcp.kernel.exit_status import ExitStatus
from kb_mcp.sources.atlassian.fetch.adapters import http
from kb_mcp.sources.atlassian.fetch.adapters.raw_store import RawStore
from kb_mcp.sources.atlassian.fetch.adapters.session_file import COOKIES, folder_of, write_cookies
from tests.test_fetching import SITE, FakeSite

if TYPE_CHECKING:
    import argparse
    from pathlib import Path

    from _pytest.capture import CaptureFixture
    from _pytest.monkeypatch import MonkeyPatch

    from kb_mcp.config.domain.settings import Loaded

# The client's site, a second one.
CLIENT_SITE = "https://client.example.invalid"
# A second Jira site's source, as a settings file writes it.
CLIENT = '[sources.clientjira]\nconnector = "jira"\nprojects = ["ABC"]\n'


@pytest.fixture
def runs(monkeypatch: MonkeyPatch) -> list[tuple[argparse.Namespace, Loaded]]:
    """Make ``fetch`` and ``prepare`` record what their run was given, and do nothing."""
    recorded: list[tuple[argparse.Namespace, Loaded]] = []

    def run(arguments: argparse.Namespace, loaded: Loaded, *_: str) -> tuple[int, None]:
        recorded.append((arguments, loaded))
        return 0, None

    monkeypatch.setattr(sources_command, "run", run)
    return recorded


def checked(config: Path, capsys: CaptureFixture[str]) -> str:
    """Run ``check`` in detail on a settings file; give what it wrote, once it passed."""
    assert main(["check", "--detail", "detailed", "--config", str(config)]) == ExitStatus.OK
    return capsys.readouterr().out


def test_a_source_that_the_file_names_is_of_the_connector_it_names(
    tmp_path: Path, capsys: CaptureFixture[str]
) -> None:
    """Beside the registry's, whose settings stay at their defaults."""
    config = tmp_path / "config.toml"
    config.write_text(CLIENT, "utf-8")
    out = checked(config, capsys)
    assert "sources.clientjira.projects: ABC [config.toml]\n" in out
    assert "sources.clientjira.connector: jira [config.toml]\n" in out
    assert "sources.jira.projects: (none) [default]\n" in out


def test_a_source_that_the_environment_names_is_of_the_connector_it_names(
    tmp_path: Path, monkeypatch: MonkeyPatch, capsys: CaptureFixture[str]
) -> None:
    """By its own variable, or in the JSON of its table's."""
    monkeypatch.setenv("KB_MCP_SOURCES__CLIENTJIRA__CONNECTOR", "jira")
    monkeypatch.setenv("KB_MCP_SOURCES__CLIENTJIRA__PROJECTS", '["ABC"]')
    monkeypatch.setenv("KB_MCP_SOURCES__WIKI", '{"connector": "confluence", "spaces": ["ENG"]}')
    out = checked(tmp_path / "none.toml", capsys)
    assert "sources.clientjira.projects: ABC [KB_MCP_SOURCES__CLIENTJIRA__PROJECTS]\n" in out
    assert "sources.wiki.spaces: ENG [KB_MCP_SOURCES__WIKI]\n" in out


@pytest.mark.parametrize(
    ("text", "said"),
    [
        (
            '[sources.clientjira]\nprojects = ["ABC"]\n',
            "sources.clientjira (config.toml): not a source",
        ),
        (
            '[sources.tracker]\nconnector = "gitlab"\n',
            "sources.tracker (config.toml): not a source",
        ),
        (
            '[sources.client-jira]\nconnector = "jira"\n',
            "sources.client-jira (config.toml): not a source",
        ),
        ('[sources.https]\nconnector = "jira"\n', "sources.https (config.toml): not a source"),
        ('[sources.jira]\nconnector = "confluence"\n', "sources.jira.connector (config.toml):"),
    ],
    ids=["no connector", "an unknown connector", "a dash", "a scheme", "another connector"],
)
def test_a_source_of_no_known_connector_or_off_the_rule_is_refused_naming_it(
    tmp_path: Path, capsys: CaptureFixture[str], text: str, said: str
) -> None:
    """Exit 2, by the settings' refusal, never by a traceback.

    A source of the registry keeps its connector.
    """
    config = tmp_path / "config.toml"
    config.write_text(text, "utf-8")
    assert main(["check", "--config", str(config)]) == ExitStatus.REFUSED
    assert said in capsys.readouterr().err


@pytest.mark.usefixtures("runs")
def test_project_given_for_two_jira_sources_is_refused_naming_both(
    tmp_path: Path, capsys: CaptureFixture[str]
) -> None:
    """Which list it overrides would be a guess."""
    config = tmp_path / "config.toml"
    config.write_text(CLIENT, "utf-8")
    given = ["fetch", "--yes", "--config", str(config), "--project", "XYZ"]
    assert main(given) == ExitStatus.REFUSED
    assert "--project: overrides a setting of one source; name one of jira, clientjira" in (
        capsys.readouterr().err
    )


def test_project_overrides_the_list_of_the_source_named(
    tmp_path: Path, capsys: CaptureFixture[str], runs: list[tuple[argparse.Namespace, Loaded]]
) -> None:
    """Named, the source is the one left; the other's list stays the file's."""
    config = tmp_path / "config.toml"
    config.write_text(
        f'{CLIENT}site = "https://client.example.invalid"\n[sources.jira]\nprojects = ["PRB"]\n',
        "utf-8",
    )
    assert main(["fetch", "clientjira", "--yes", "--config", str(config), "--project", "XYZ"]) == 0
    [(_, loaded)] = runs
    assert loaded.settings.sources.clientjira.projects == ("XYZ",)
    assert loaded.settings.sources.jira.projects == ("PRB",)
    assert loaded.layers["sources.clientjira.projects"] == "--project"
    assert "--project XYZ" in capsys.readouterr().err


def test_a_dry_run_plans_each_source_of_one_connector_with_its_own_site(
    tmp_path: Path, capsys: CaptureFixture[str]
) -> None:
    """Criterion 1: a row each, and the echo names each one's site.

    No session is saved: each row asks to sign in again, as its own sign-in does, before
    any request.
    """
    config = tmp_path / "config.toml"
    config.write_text(
        f'{CLIENT}site = "https://client.example.invalid"\n'
        '[sources.jira]\nprojects = ["PRB"]\nsite = "https://sandbox.example.invalid"\n',
        "utf-8",
    )
    given = ["fetch", "--dry-run", "--config", str(config), "--data-dir", str(tmp_path / "data")]
    assert main([*given, "--format", "json"]) == ExitStatus.SIGN_IN_AGAIN
    out, err = capsys.readouterr()
    rows = json.loads(out)["sources"]
    assert [(row["source"], row["ending"]) for row in rows] == [
        ("jira", "sign in again"),
        ("clientjira", "sign in again"),
    ]
    assert "source jira: projects PRB, site https://sandbox.example.invalid" in err
    assert "source clientjira: projects ABC, site https://client.example.invalid" in err


# What criterion 2 refuses: the account's table in the file, or its variable, each with
# the line that names its new places.
FORMER = {
    "a table": (
        '[accounts.atlassian]\nsite = "https://x.atlassian.net"\n',
        {},
        ("accounts.atlassian.site (config.toml) to sources.confluence.site and sources.jira.site"),
    ),
    "a variable": (
        "",
        {"KB_MCP_ACCOUNTS__ATLASSIAN__API_TOKEN": "token-sentinel-1b8f"},
        (
            "accounts.atlassian.api_token (KB_MCP_ACCOUNTS__ATLASSIAN__API_TOKEN) to"
            " KB_MCP_SOURCES__CONFLUENCE__API_TOKEN and KB_MCP_SOURCES__JIRA__API_TOKEN"
        ),
    ),
}


@pytest.mark.parametrize("case", FORMER.values(), ids=FORMER.keys())
def test_the_account_s_former_settings_are_refused_naming_each_source_s(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    capsys: CaptureFixture[str],
    case: tuple[str, dict[str, str], str],
) -> None:
    """Criterion 2: exit 2, with advice naming the key or variable of each Atlassian source."""
    text, variables, named = case
    config = tmp_path / "config.toml"
    config.write_text(text, "utf-8")
    for name, value in variables.items():
        monkeypatch.setenv(name, value)
    assert main(["check", "--config", str(config)]) == ExitStatus.REFUSED
    err = capsys.readouterr().err
    assert f"  {named}\n" in err
    assert "token-sentinel-1b8f" not in err


def test_two_sites_of_one_connector_fetch_sign_in_and_prepare_apart(
    tmp_path: Path, monkeypatch: MonkeyPatch, capsys: CaptureFixture[str]
) -> None:
    """Plan 059, step 3: each source its raw folder, coverage, sign-in and mirror's folder.

    The client's site, without a session, asks to sign in again, and Jira's goes on; once
    signed in, both fetch the same project's key apart, and each document's address is
    its own site's.
    """
    monkeypatch.setattr(time, "sleep", lambda _: None)
    monkeypatch.setattr(http, "client", lambda *_: FakeSite().client())
    config = tmp_path / "config.toml"
    config.write_text(
        f'[sources.jira]\nprojects = ["PRB"]\nsite = "{SITE}"\n'
        f'[sources.clientjira]\nconnector = "jira"\nprojects = ["PRB"]\nsite = "{CLIENT_SITE}"\n',
        "utf-8",
    )
    data = tmp_path / "data"
    write_cookies(
        folder_of(data / "session", SITE) / COOKIES, [{"name": "s", "value": "v", "domain": "x"}]
    )
    given = ["--yes", "--config", str(config), "--data-dir", str(data), "--format", "json"]
    fetch = ["fetch", *given, "--since", "2026-10-02"]
    assert main(fetch) == ExitStatus.SIGN_IN_AGAIN
    rows = {row["source"]: row["ending"] for row in json.loads(capsys.readouterr().out)["sources"]}
    assert rows == {"jira": "done", "clientjira": "sign in again"}
    session = folder_of(data / "session", CLIENT_SITE) / COOKIES
    write_cookies(session, [{"name": "s", "value": "v", "domain": "x"}])
    assert main(fetch) == ExitStatus.OK
    assert sorted(each.name for each in (data / "raw").iterdir() if each.is_dir()) == [
        "blobs",
        "clientjira",
        "jira",
    ]
    covered = RawStore(data / "raw", "jira").coverage().periods
    assert {(scope.source, scope.key) for scope in covered} == {
        ("jira", "PRB"),
        ("clientjira", "PRB"),
    }
    capsys.readouterr()
    assert main(["prepare", *given]) == ExitStatus.OK
    for name, site in (("jira", SITE), ("clientjira", CLIENT_SITE)):
        written = list((data / "docs" / name).rglob("*.md"))
        assert written
        assert all(f"url: {site}/" in path.read_text("utf-8") for path in written)


def test_a_site_of_two_sources_of_pages_refuses_their_prepare(
    tmp_path: Path, capsys: CaptureFixture[str]
) -> None:
    """Their pages are placed by one listing of the site's spaces: the row fails, naming both."""
    config = tmp_path / "config.toml"
    config.write_text(
        f'[sources.confluence]\nspaces = ["MFS"]\nsite = "{SITE}"\n'
        f'[sources.wiki]\nconnector = "confluence"\nspaces = ["ENG"]\nsite = "{SITE}"\n',
        "utf-8",
    )
    given = ["prepare", "--yes", "--config", str(config), "--data-dir", str(tmp_path / "data")]
    assert main([*given, "confluence"]) == ExitStatus.FAILED
    assert "sources confluence, wiki: two sources of the pages of one site" in (
        capsys.readouterr().err
    )


def test_a_prepare_of_one_site_keeps_the_files_that_another_site_s_documents_link(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """Review round 1: every source keeps its attached files in one folder, ``assets``.

    A prepare of the client's site, whose store holds nothing yet, places its own site's
    documents alone, but each source's files still link theirs: none of Confluence's goes.
    """
    monkeypatch.setattr(time, "sleep", lambda _: None)
    monkeypatch.setattr(http, "client", lambda *_: FakeSite().client())
    config = tmp_path / "config.toml"
    config.write_text(
        f'[sources.confluence]\nspaces = ["MFS"]\nsite = "{SITE}"\n'
        f'[sources.clientjira]\nconnector = "jira"\nprojects = ["PRB"]\nsite = "{CLIENT_SITE}"\n',
        "utf-8",
    )
    data = tmp_path / "data"
    cookie = [{"name": "s", "value": "v", "domain": "x"}]
    write_cookies(folder_of(data / "session", SITE) / COOKIES, cookie)
    given = ["--yes", "--config", str(config), "--data-dir", str(data)]
    main(["fetch", *given, "--since", "2026-10-02", "confluence"])
    assert main(["prepare", *given, "confluence"]) == ExitStatus.OK
    assets = sorted((data / "docs" / "assets").iterdir())
    linked = [
        each
        for each in assets
        if any(
            each.name in path.read_text("utf-8")
            for path in (data / "docs" / "confluence").rglob("*.md")
        )
    ]
    assert linked
    assert main(["prepare", *given, "clientjira"]) == ExitStatus.OK
    assert all(each.exists() for each in linked)


@pytest.mark.parametrize(
    ("given", "said"),
    [
        (["check", "--site", SITE], "--site: gone; each source's site is its setting"),
        (["fetch", "--site", SITE], "KB_MCP_SOURCES__<NAME>__SITE"),
    ],
    ids=["check", "fetch"],
)
def test_the_options_that_went_are_refused_saying_what_took_their_place(
    tmp_path: Path, capsys: CaptureFixture[str], given: list[str], said: str
) -> None:
    """Review round 1: --site, exit 2, never taken for another word."""
    with pytest.raises(SystemExit) as stopped:
        main([*given, "--config", str(tmp_path / "none.toml")])
    assert stopped.value.code == ExitStatus.REFUSED
    assert said in capsys.readouterr().err


def test_login_atlassian_is_refused_naming_the_sources(
    tmp_path: Path, capsys: CaptureFixture[str]
) -> None:
    """Review rounds 1 and 2: by login's own check, exit 2, before a window opens."""
    given = ["login", "atlassian", "--yes", "--config", str(tmp_path / "none.toml")]
    assert main(given) == ExitStatus.REFUSED
    assert "atlassian: gone; name a source, login confluence or login jira" in (
        capsys.readouterr().err
    )


def test_an_empty_variable_of_a_source_that_the_settings_do_not_name_is_ignored(
    tmp_path: Path, monkeypatch: MonkeyPatch, capsys: CaptureFixture[str]
) -> None:
    """Review round 1: as any empty variable, said ignored; refused once it holds a value."""
    monkeypatch.setenv("KB_MCP_SOURCES__TRACKER__SITE", "")
    assert main(["check", "--config", str(tmp_path / "none.toml")]) == ExitStatus.OK
    assert "ignored: KB_MCP_SOURCES__TRACKER__SITE: names no setting\n" in capsys.readouterr().err
    monkeypatch.setenv("KB_MCP_SOURCES__TRACKER__SITE", SITE)
    assert main(["check", "--config", str(tmp_path / "none.toml")]) == ExitStatus.REFUSED
    assert "sources.tracker (KB_MCP_SOURCES__TRACKER__SITE): not a source" in (
        capsys.readouterr().err
    )


def test_project_given_with_sources_none_of_which_has_projects_is_ignored_by_them(
    tmp_path: Path, capsys: CaptureFixture[str], runs: list[tuple[argparse.Namespace, Loaded]]
) -> None:
    """Review round 1: overriding no list, it is said ignored by the source named."""
    config = tmp_path / "config.toml"
    config.write_text(f'{CLIENT}[sources.confluence]\nspaces = ["MFS"]\nsite = "{SITE}"\n', "utf-8")
    given = ["fetch", "confluence", "--yes", "--config", str(config), "--project", "XYZ"]
    assert main(given) == ExitStatus.OK
    assert "  --project: ignored by confluence\n" in capsys.readouterr().err
    [(_, loaded)] = runs
    assert loaded.settings.sources.jira.projects == ()
    assert loaded.settings.sources.clientjira.projects == ("ABC",)


@pytest.mark.parametrize(
    ("text", "said"),
    [
        ('[sources.json]\nconnector = "jira"\n', "sources.json: a name that the settings' model"),
        ('[sources.blobs]\nconnector = "jira"\n', "sources.blobs (config.toml): not a source"),
    ],
    ids=["a model's attribute", "the raw store's folder"],
)
def test_a_source_named_as_the_model_or_the_raw_store_names_its_own_is_refused(
    tmp_path: Path, capsys: CaptureFixture[str], text: str, said: str
) -> None:
    """Review round 2: exit 2, naming it, never a traceback nor a folder of the raw store's."""
    config = tmp_path / "config.toml"
    config.write_text(text, "utf-8")
    assert main(["check", "--config", str(config)]) == ExitStatus.REFUSED
    assert said in capsys.readouterr().err


def test_a_variable_of_a_source_named_as_the_model_s_attribute_is_refused(
    tmp_path: Path, monkeypatch: MonkeyPatch, capsys: CaptureFixture[str]
) -> None:
    """Review round 2: as in the file."""
    monkeypatch.setenv("KB_MCP_SOURCES__COPY__CONNECTOR", "jira")
    assert main(["check", "--config", str(tmp_path / "none.toml")]) == ExitStatus.REFUSED
    assert "sources.copy: a name that the settings' model holds" in capsys.readouterr().err


def test_the_account_s_keys_go_to_the_registry_s_sources_alone(
    tmp_path: Path, capsys: CaptureFixture[str]
) -> None:
    """Review round 2: a source added since never read the account; no key goes to it."""
    config = tmp_path / "config.toml"
    config.write_text(f'[accounts.atlassian]\nsite = "{SITE}"\n{CLIENT}', "utf-8")
    assert main(["check", "--config", str(config)]) == ExitStatus.REFUSED
    err = capsys.readouterr().err
    assert (
        "  accounts.atlassian.site (config.toml) to sources.confluence.site and sources.jira.site\n"
    ) in err
    assert "sources.clientjira.site" not in err
