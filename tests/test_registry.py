"""The registry of sources: its declarations, its rules, and the settings it composes.

The expectations come from plan 030: the registry lists Confluence, Jira and the work
log in name order; any registry that the entry is given is refused, naming the
declaration, for a name off the rule, ``assets``, or a name declared twice; each
declaration names its table, whose settings are the declaration's; and a source that a
registry leaves out has no setting (criterion 3).
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
from kb_mcp.sources.atlassian.declared import CONFLUENCE, JIRA
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
