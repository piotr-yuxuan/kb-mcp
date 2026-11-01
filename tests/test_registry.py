"""The registry of sources: its declarations, its rules, and the settings it composes.

The expectations come from plan 030: the registry lists Confluence, Jira and the work
log in name order; any registry that the entry is given is refused, naming the
declaration, for a name off the rule, ``assets``, a name declared twice, or an account
that two declarations name differently; each declaration names its table, whose
settings are the declaration's; Confluence and Jira sign in with one account,
``[accounts.atlassian]`` (question 1); and a source, or an account, that a registry
leaves out has no setting (criterion 3).
"""

from __future__ import annotations

import pkgutil
import re
from dataclasses import replace
from typing import TYPE_CHECKING

import pytest
from pydantic import BaseModel

from kb_mcp.cli.main import main
from kb_mcp.kernel.exit_status import ExitStatus
from kb_mcp.sources.atlassian.declared import ATLASSIAN, CONFLUENCE, JIRA
from kb_mcp.sources.atlassian.fetch.domain.content import BlogPost, Issue, Page
from kb_mcp.sources.registry import SOURCES
from kb_mcp.sources.worklog.declared import WORKLOG

if TYPE_CHECKING:
    from pathlib import Path

    from _pytest.capture import CaptureFixture
    from _pytest.monkeypatch import MonkeyPatch

    from kb_mcp.sources.declaration import Declared

# A setting of each source's table, by source, and a value of it in a settings file.
SET = {"confluence": ("spaces", '["MFS"]'), "worklog": ("archives", "false")}


def test_the_registry_holds_confluence_jira_and_the_work_log_in_name_order() -> None:
    """Plan 030: a new source is its package and one line of ``SOURCES``."""
    assert [each.name for each in SOURCES] == ["confluence", "jira", "worklog"]


@pytest.mark.parametrize("declared", SOURCES, ids=lambda each: each.name)
def test_each_declaration_names_a_table_that_holds_its_settings_in_order(
    declared: Declared,
) -> None:
    """The table loads by its module path, a model whose settings are the declaration's."""
    table = pkgutil.resolve_name(declared.table)
    assert isinstance(table, type)
    assert issubclass(table, BaseModel)
    assert tuple(table.model_fields) == declared.settings


def test_the_resource_types_are_the_plan_s_and_the_raw_store_s_kinds() -> None:
    """Each source's types and how each is read, as plan 030's table gives them.

    Confluence's and Jira's are the kinds that the raw store keeps.
    """
    assert {each.name: [(kind.name, kind.read) for kind in each.types] for each in SOURCES} == {
        "confluence": [("pages", "listed"), ("blogposts", "listed")],
        "jira": [("issues", "searched")],
        "worklog": [
            ("entries", "in place"),
            ("days", "in place"),
            ("meetings", "in place"),
            ("transcripts", "in place"),
        ],
    }
    assert [kind.name for kind in (*CONFLUENCE.types, *JIRA.types)] == [
        Page.kind,
        BlogPost.kind,
        Issue.kind,
    ]


@pytest.mark.parametrize("name", ["Worklog", "work-log", "work_log", "2log", "", "assets"])
def test_a_registry_with_a_name_off_the_rule_is_refused_naming_it(
    tmp_path: Path, name: str
) -> None:
    """A name is a table, a folder of the mirror and the front matter's ``source``."""
    registry = (CONFLUENCE, JIRA, replace(WORKLOG, name=name))
    with pytest.raises(ValueError, match=rf"^{re.escape(f'source {name!r}:')} a source's name"):
        main(["check", "--config", str(tmp_path / "none.toml")], registry)


def test_a_registry_with_two_declarations_of_one_name_is_refused_naming_it(
    tmp_path: Path,
) -> None:
    """One source type has one instance: a second Jira, by another table, is refused."""
    registry = (*SOURCES, replace(JIRA, table=WORKLOG.table))
    with pytest.raises(ValueError, match=r"^source 'jira': declared twice$"):
        main(["check", "--config", str(tmp_path / "none.toml")], registry)


def test_confluence_and_jira_sign_in_with_one_atlassian_account() -> None:
    """Question 1's answer: its site, email and token, in ``[accounts.atlassian]``.

    The work log, read in place, signs in with none.
    """
    assert {each.name: each.account for each in SOURCES} == {
        "confluence": ATLASSIAN,
        "jira": ATLASSIAN,
        "worklog": None,
    }
    assert ATLASSIAN.name == "atlassian"
    table = pkgutil.resolve_name(ATLASSIAN.table)
    assert tuple(table.model_fields) == ("site", "email", "api_token")


def test_a_registry_naming_one_account_differently_is_refused_naming_the_source(
    tmp_path: Path,
) -> None:
    """The sources that name an account share its table: two tables of one name are refused."""
    other = replace(ATLASSIAN, table=WORKLOG.table)
    registry = (CONFLUENCE, replace(JIRA, account=other), WORKLOG)
    with pytest.raises(
        ValueError, match=r"^source 'jira': account 'atlassian' declared otherwise$"
    ):
        main(["check", "--config", str(tmp_path / "none.toml")], registry)


def test_an_account_that_no_source_of_the_registry_names_has_no_setting(
    tmp_path: Path, capsys: CaptureFixture[str]
) -> None:
    """Without Confluence and Jira, ``[accounts.atlassian]`` is refused; with them, read."""
    config = tmp_path / "config.toml"
    config.write_text('[accounts.atlassian]\nsite = "https://x.atlassian.net"\n', "utf-8")
    assert main(["check", "--config", str(config)], (WORKLOG,)) == ExitStatus.REFUSED
    assert "accounts.atlassian.site (config.toml): not a setting" in capsys.readouterr().err
    assert main(["check", "--config", str(config)]) == ExitStatus.OK
    assert capsys.readouterr().out == "accounts.atlassian.site: https://x.atlassian.net\n"


@pytest.mark.parametrize("left_out", ["worklog", "confluence"])
def test_a_source_that_the_registry_leaves_out_has_no_setting(
    tmp_path: Path, monkeypatch: MonkeyPatch, capsys: CaptureFixture[str], left_out: str
) -> None:
    """Criterion 3: its table in the file is refused, its variable names no setting.

    With every source registered, the same file and variable are its settings.
    """
    registry = tuple(each for each in SOURCES if each.name != left_out)
    setting, value = SET[left_out]
    config = tmp_path / "config.toml"
    config.write_text(f"[sources.{left_out}]\n{setting} = {value}\n", "utf-8")
    assert main(["check", "--config", str(config)], registry) == ExitStatus.REFUSED
    refused = f"sources.{left_out}.{setting} (config.toml): not a setting"
    assert refused in capsys.readouterr().err
    assert main(["check", "--config", str(config)]) == ExitStatus.OK
    assert f"sources.{left_out}.{setting}: " in capsys.readouterr().out

    variable = f"KB_MCP_SOURCES__{left_out.upper()}"
    monkeypatch.setenv(variable, "{}")
    none = ["check", "--config", str(tmp_path / "none.toml"), "--summary", "detailed"]
    assert main(none, registry) == ExitStatus.OK
    out, err = capsys.readouterr()
    assert f"sources.{left_out}." not in out
    assert err == f"ignored: {variable}: names no setting\n"
    assert main(none) == ExitStatus.OK
    assert f"sources.{left_out}." in capsys.readouterr().out


@pytest.mark.parametrize("left_out", ["worklog", "confluence"])
def test_a_source_that_the_registry_leaves_out_cannot_be_synced(
    tmp_path: Path, capsys: CaptureFixture[str], left_out: str
) -> None:
    """Criterion 3: ``sync --include`` of it exits 2, argparse naming the choice refused.

    With every source registered, the same name is a choice, here refused as not
    configured, by the run's own check.
    """
    registry = tuple(each for each in SOURCES if each.name != left_out)
    given = ["sync", "--yes", "--config", str(tmp_path / "none.toml"), "--include", left_out]
    with pytest.raises(SystemExit) as stopped:
        main(given, registry)
    assert stopped.value.code == ExitStatus.REFUSED
    assert f"invalid choice: '{left_out}'" in capsys.readouterr().err
    assert main(given) == ExitStatus.REFUSED
    assert f"--include {left_out}: not configured" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("role", "path", "said"),
    [
        ("fetcher", "kb_mcp.sources.atlassian.fetch.app.absent", "does not load"),
        ("fetcher", "kb_absent.fetcher", "does not load"),
        ("fetcher", "not a module path", "does not load"),
        ("fetcher", "kb_mcp.sources.atlassian.declared", "not a Fetcher"),
        ("preparers", "kb_mcp.sources.atlassian.fetch.app.fetcher", "not a Preparer"),
    ],
)
def test_a_role_that_does_not_load_refuses_the_sync_of_its_source_naming_the_path(
    tmp_path: Path, capsys: CaptureFixture[str], role: str, path: str, said: str
) -> None:
    """Criterion 3: a declaration naming a role that does not load, or is not the role.

    ``sync --include`` of it exits 2 before any row, naming the source and the path;
    with the registry's own declaration, the same run goes on, its fetch to sign in,
    no session being saved.
    """
    named = path if role == "fetcher" else (path,)
    registry = (replace(CONFLUENCE, **{role: named}), JIRA, WORKLOG)
    config = tmp_path / "config.toml"
    config.write_text(
        '[accounts.atlassian]\nsite = "https://x.atlassian.net"\n'
        '[sources.confluence]\nspaces = ["MFS"]\n',
        "utf-8",
    )
    data = tmp_path / "data"
    given = ["sync", "--yes", "--config", str(config), "--data-dir", str(data)]
    given += ["--include", "confluence", "--dry-run", "--format", "json"]
    assert main(given, registry) == ExitStatus.REFUSED
    err = capsys.readouterr().err
    assert "sync.refused" in err
    assert f"source 'confluence': {path}: {said}" in err
    assert not data.exists()
    assert main(given) == ExitStatus.SIGN_IN_AGAIN
