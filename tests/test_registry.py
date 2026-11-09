"""The registry of sources: its declarations, its rules, and the settings it composes.

The expectations come from plan 030: the registry lists Confluence, Jira and the work
log in name order; any registry that the entry is given is refused, naming the
declaration, for a name off the rule, ``assets``, a name declared twice, a name that a
model holds, an account that two declarations name differently, no setting, neither
fetcher nor preparer,
settings that are not its table's, a type read in a way that the help has no words for,
or an option that is no flag, that another source declares otherwise, or that is
``fetch``'s own; an option's value takes no name that the program holds; each
declaration names its table, whose settings are the declaration's; Confluence and Jira
sign in with one account,
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

from kb_mcp.cli.domain.sources import given
from kb_mcp.cli.main import main, parser
from kb_mcp.config.domain.settings import TABLE, settings_model
from kb_mcp.kernel.exit_status import ExitStatus
from kb_mcp.sources.atlassian.declared import ATLASSIAN, CONFLUENCE, JIRA, SINCE
from kb_mcp.sources.atlassian.fetch.domain.content import BlogPost, Issue, Page
from kb_mcp.sources.atlassian.prepare.app.prepare import PREPARED
from kb_mcp.sources.declaration import Option, ResourceType
from kb_mcp.sources.registry import SOURCES, refuse
from kb_mcp.sources.worklog.declared import WORKLOG

if TYPE_CHECKING:
    from pathlib import Path

    from _pytest.capture import CaptureFixture
    from _pytest.monkeypatch import MonkeyPatch

    from kb_mcp.sources.declaration import Source

# A setting of each source's table, by source, and a value of it in a settings file.
SET = {"confluence": ("spaces", '["MFS"]'), "worklog": ("archives", "false")}


def test_the_registry_holds_confluence_jira_and_the_work_log_in_name_order() -> None:
    """Plan 030: a new source is its package and one line of ``SOURCES``."""
    assert [each.name for each in SOURCES] == ["confluence", "jira", "worklog"]


@pytest.mark.parametrize("declared", SOURCES, ids=lambda each: each.name)
def test_each_declaration_names_a_table_that_holds_its_settings_in_order(
    declared: Source,
) -> None:
    """The table loads by its module path, a model whose settings are the declaration's."""
    table = pkgutil.resolve_name(declared.table_path)
    assert isinstance(table, type)
    assert issubclass(table, BaseModel)
    assert tuple(table.model_fields) == declared.settings


def test_the_resource_types_are_the_plan_s_and_the_raw_store_s_types() -> None:
    """Each source's types and how each is read, as plan 030's table gives them.

    Confluence's and Jira's are the types that the raw store keeps.
    """
    assert {
        each.name: [
            (resource_type.name, resource_type.read) for resource_type in each.resource_types
        ]
        for each in SOURCES
    } == {
        "confluence": [("pages", "listed"), ("blogposts", "listed")],
        "jira": [("issues", "searched")],
        "worklog": [
            ("entries", "in place"),
            ("days", "in place"),
            ("meetings", "in place"),
            ("transcripts", "in place"),
        ],
    }
    assert [
        resource_type.name for resource_type in (*CONFLUENCE.resource_types, *JIRA.resource_types)
    ] == [
        Page.resource_type,
        BlogPost.resource_type,
        Issue.resource_type,
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
    """Each source is configured once: a second Jira, by another table, is refused."""
    registry = (*SOURCES, replace(JIRA, table_path=WORKLOG.table_path))
    with pytest.raises(ValueError, match=r"^source 'jira': declared twice$"):
        main(["check", "--config", str(tmp_path / "none.toml")], registry)


def test_each_source_prepares_the_types_that_its_declaration_names() -> None:
    """A type added to a declaration reaches its preparer, and the tests' store of each type."""
    assert {
        source: [each.resource_type for each in classes] for source, classes in PREPARED.items()
    } == {
        declared.name: [resource_type.name for resource_type in declared.resource_types]
        for declared in (CONFLUENCE, JIRA)
    }


@pytest.mark.parametrize(
    ("types", "named"),
    [(CONFLUENCE.resource_types[:1], "pages"), (CONFLUENCE.resource_types[1:], "blogposts")],
    ids=["pages", "blog posts"],
)
def test_a_source_that_names_some_of_its_types_is_refused_and_no_file_removed(
    tmp_path: Path, capsys: CaptureFixture[str], types: tuple[ResourceType, ...], named: str
) -> None:
    """Plan 030: Atlassian's preparer removes the files of all of a source's resource types.

    So a registry that names the pages alone would remove every blog post: ``prepare`` is
    refused before any row, naming the source and its types.
    """
    registry = (replace(CONFLUENCE, resource_types=types), JIRA, WORKLOG)
    config = tmp_path / "config.toml"
    config.write_text(
        '[accounts.atlassian]\nsite = "https://x.atlassian.net"\n'
        '[sources.confluence]\nspaces = ["MFS"]\n',
        "utf-8",
    )
    data = tmp_path / "data"
    post = data / "docs" / "confluence" / "MFS" / "blog" / "600-news.md"
    post.parent.mkdir(parents=True)
    post.write_text("kept", "utf-8")
    given = ["prepare", "confluence", "--yes", "--config", str(config)]
    assert main([*given, "--data-dir", str(data)], registry) == ExitStatus.REFUSED
    err = capsys.readouterr().err
    assert "prepare.refused" in err
    assert f"source 'confluence': prepare: types {named}: not all the resource types of one" in err
    assert post.read_text("utf-8") == "kept"


def declaring(*options: Option) -> Source:
    """Give the work log's declaration, its entries taking these options."""
    return replace(
        WORKLOG,
        resource_types=(
            ResourceType(name="entries", help="its entries", read="in place", options=options),
        ),
    )


class Required(BaseModel):
    """A table that cannot be built by default: a source left unset still has its table."""

    model_config = TABLE

    folder: str


def test_a_registry_with_a_source_that_names_no_setting_is_refused_naming_it(
    tmp_path: Path,
) -> None:
    """Its first setting says whether it is configured: any run would have nothing to read."""
    registry = (CONFLUENCE, JIRA, replace(WORKLOG, settings=()))
    with pytest.raises(ValueError, match=r"^source 'worklog': names no setting$"):
        main(["check", "--config", str(tmp_path / "none.toml")], registry)


@pytest.mark.parametrize(
    ("registry", "said"),
    [
        pytest.param(
            (CONFLUENCE, JIRA, replace(WORKLOG, settings=("path", "archive"))),
            "source 'worklog': kb_mcp.sources.worklog.settings:WorklogTable: holds"
            " ('path', 'archives'), not the settings named, ('path', 'archive')",
            id="a setting the table lacks",
        ),
        pytest.param(
            (CONFLUENCE, JIRA, replace(WORKLOG, settings=("archives", "path"))),
            "source 'worklog': kb_mcp.sources.worklog.settings:WorklogTable: holds"
            " ('path', 'archives'), not the settings named, ('archives', 'path')",
            id="the first setting another",
        ),
        pytest.param(
            (
                replace(CONFLUENCE, account=replace(ATLASSIAN, settings=("site",))),
                replace(JIRA, account=replace(ATLASSIAN, settings=("site",))),
                WORKLOG,
            ),
            "account 'atlassian': kb_mcp.sources.atlassian.settings:AtlassianAccountTable: holds"
            " ('site', 'email', 'api_token'), not the settings named, ('site',)",
            id="an account's",
        ),
    ],
)
def test_a_registry_whose_settings_are_not_its_table_s_is_refused_naming_it(
    tmp_path: Path, registry: tuple[Source, ...], said: str
) -> None:
    """By the entry, which loads the tables: ``--help`` loads none, and is not refused."""
    with pytest.raises(ValueError, match=rf"^{re.escape(said)}$"):
        main(["check", "--config", str(tmp_path / "none.toml")], registry)
    with pytest.raises(SystemExit) as stopped:
        main(["--help"], registry)
    assert stopped.value.code == ExitStatus.OK


def test_a_table_that_cannot_be_built_by_default_is_refused_naming_its_source(
    tmp_path: Path,
) -> None:
    """Refused as the model is composed: not a validation error of no source at a first read."""
    said = r"^sources\.memo: a setting without a default: folder$"
    with pytest.raises(TypeError, match=said):
        settings_model({"memo": Required}, {})
    memo = replace(
        WORKLOG, name="memo", settings=("folder",), table_path=f"{__name__}:{Required.__name__}"
    )
    with pytest.raises(TypeError, match=said):
        main(["check", "--config", str(tmp_path / "none.toml")], (*SOURCES, memo))


class Numbers(BaseModel):
    """A table with a list of numbers, which no summary can join."""

    model_config = TABLE

    values: tuple[int, ...] = ()


class Folders(BaseModel):
    """A table with a list of paths, whose ``~`` no rule would judge."""

    model_config = TABLE

    values: tuple[Path, ...] = ()


class Inner(BaseModel):
    """A table inside another."""

    model_config = TABLE

    value: str = "a"


class Outer(BaseModel):
    """A table holding a table, whose path holds no value to show."""

    model_config = TABLE

    values: tuple[str, ...] = ()
    inner: Inner = Inner()


class Tags(BaseModel):
    """A table with a list that may be None, which is its default."""

    model_config = TABLE

    values: tuple[str, ...] | None = None
    more: tuple[str, ...] | None = None


@pytest.mark.parametrize(
    ("table", "said"),
    [
        (Numbers, "a setting of a type that has no kind"),
        (Folders, "a setting of a type that has no kind"),
        (Outer, "a table inside a table: inner"),
    ],
    ids=["numbers", "paths", "a table"],
)
@pytest.mark.parametrize(
    "command", [["check"], ["prepare", "added", "--yes"]], ids=["check", "prepare"]
)
def test_a_table_that_a_command_could_not_read_is_refused_naming_its_source(
    tmp_path: Path, table: type[BaseModel], said: str, command: list[str]
) -> None:
    """Criterion 4's promise: by the entry, before any value is read, and no traceback later.

    Named ``values`` in each, so that a declaration's ``settings`` are the table's.
    """
    config = tmp_path / "config.toml"
    config.write_text('[sources.added]\nvalues = ["a"]\n', "utf-8")
    settings = tuple(table.model_fields)
    added = replace(
        WORKLOG, name="added", settings=settings, table_path=f"{__name__}:{table.__name__}"
    )
    with pytest.raises(TypeError, match=rf"^sources\.added: {said}"):
        main([*command, "--config", str(config), "--data-dir", str(tmp_path / "data")], (added,))


def test_a_list_left_at_none_reads_as_no_value(tmp_path: Path, capsys: CaptureFixture[str]) -> None:
    """A list that may be None is a list: unset, ``check`` says so, and runs on."""
    config = tmp_path / "config.toml"
    config.write_text('[sources.added]\nvalues = ["a"]\n', "utf-8")
    added = replace(
        WORKLOG, name="added", settings=("values", "more"), table_path=f"{__name__}:{Tags.__name__}"
    )
    given = ["check", "--summary", "detailed", "--config", str(config)]
    assert main([*given, "--data-dir", str(tmp_path / "data")], (added,)) == ExitStatus.OK
    assert "sources.added.more: (none) [default]" in capsys.readouterr().out


@pytest.mark.parametrize("name", ["json", "copy", "schema"])
def test_a_name_that_a_model_holds_is_refused_naming_it(tmp_path: Path, name: str) -> None:
    """Its field would shadow the attribute, as Pydantic warns: no warning on every run."""
    registry = (*SOURCES, replace(WORKLOG, name=name))
    with pytest.raises(TypeError, match=rf"^sources\.{name}: a name that a model already holds$"):
        main(["check", "--config", str(tmp_path / "none.toml")], registry)


def test_a_source_that_names_neither_fetcher_nor_preparer_is_refused(tmp_path: Path) -> None:
    """A run of it would have no row, its absence said by nothing; a fetcher alone has a row."""
    with pytest.raises(ValueError, match=r"^source 'worklog': names neither fetcher nor preparer"):
        main(
            ["check", "--config", str(tmp_path / "none.toml")],
            (CONFLUENCE, JIRA, replace(WORKLOG, preparers=())),
        )
    refuse((replace(CONFLUENCE, preparers=()),))


@pytest.mark.parametrize(
    "flag", ["--sources", "--command", "--commands", "--dry_run", "--level", "--quiet"]
)
def test_an_option_takes_no_name_that_the_program_holds(
    tmp_path: Path, capsys: CaptureFixture[str], flag: str
) -> None:
    """Its flag is another's name for what the program holds: its value replaces none of it.

    A whole ``fetch`` runs, its summary and its command to copy carrying it, and it asks the
    site nothing, as no session is saved.
    """
    option = Option(flag=flag, help="one of the source's own")
    issues = ResourceType(name="more", help="more", read="searched", options=(option,))
    registry = (CONFLUENCE, replace(JIRA, resource_types=(*JIRA.resource_types, issues)), WORKLOG)
    arguments = parser(sources=registry).parse_args(["fetch", flag, "kept"])
    assert given(arguments, (flag,)) == {flag: "kept"}
    assert arguments.sources == registry
    assert arguments.command.name == "fetch"
    assert (arguments.dry_run, arguments.level, arguments.quiet) == (False, "warning", False)
    config = tmp_path / "config.toml"
    config.write_text('[accounts.atlassian]\nsite = "https://x.atlassian.net"\n', "utf-8")
    command = [
        "fetch",
        "jira",
        flag,
        "kept",
        "--project",
        "PRB",
        "--dry-run",
        "--config",
        str(config),
    ]
    assert (
        main([*command, "--data-dir", str(tmp_path / "data")], registry) == ExitStatus.SIGN_IN_AGAIN
    )
    assert f"{flag} kept" in capsys.readouterr().err


@pytest.mark.parametrize(
    "option",
    [Option(flag=SINCE.flag, help=SINCE.help, parse=int), Option(flag=SINCE.flag, help="another")],
    ids=["another type", "other help"],
)
def test_a_flag_that_two_sources_declare_otherwise_is_refused_naming_both(
    tmp_path: Path, option: Option
) -> None:
    """One flag of ``fetch``: one definition would change for every source."""
    registry = (CONFLUENCE, JIRA, declaring(option))
    with pytest.raises(
        ValueError, match=r"^source 'worklog': option --since declared otherwise by 'confluence'$"
    ):
        main(["check", "--config", str(tmp_path / "none.toml")], registry)


def test_a_flag_that_two_sources_declare_alike_is_one_option(
    tmp_path: Path, capsys: CaptureFixture[str]
) -> None:
    """The work log taking ``--since`` as Confluence does: one flag, which each reads."""
    registry = (CONFLUENCE, JIRA, declaring(SINCE))
    given = ["fetch", "--since", "7d", "--dry-run", "--config", str(tmp_path / "none.toml")]
    assert main(given, registry) == ExitStatus.REFUSED
    assert "nothing to fetch" in capsys.readouterr().err


@pytest.mark.parametrize("flag", ["--yes", "--dry-run", "--config", "--format"])
def test_an_option_that_takes_a_flag_of_fetch_s_own_is_refused_naming_it(flag: str) -> None:
    """In every command, as the registry's other rules: ``--help`` builds every parser."""
    issues = ResourceType(
        name="issues",
        help="a project's issues",
        read="searched",
        options=(Option(flag=flag, help="another"),),
    )
    registry = (CONFLUENCE, replace(JIRA, resource_types=(issues,)), WORKLOG)
    with pytest.raises(
        ValueError, match=rf"^source 'jira': option {flag}: a flag of the command's own"
    ):
        main(["--help"], registry)


@pytest.mark.parametrize("given", [["--help"], ["serve", "--help"], ["check", "--help"]], ids=str)
def test_a_type_read_in_a_way_of_no_known_word_is_refused_naming_its_source(
    given: list[str],
) -> None:
    """In every command: the groups of ``fetch`` and ``prepare`` say how each type is read."""
    more = ResourceType(name="more", help="more", read="scanned")
    registry = (CONFLUENCE, replace(JIRA, resource_types=(*JIRA.resource_types, more)), WORKLOG)
    with pytest.raises(
        ValueError, match=r"^source 'jira': type 'more': read 'scanned': not one of listed,"
    ):
        main(given, registry)


@pytest.mark.parametrize("flag", ["since2", "", "-", "--", "--two words", "-since"])
def test_an_option_whose_flag_has_not_a_flag_s_shape_is_refused_naming_it(flag: str) -> None:
    """Argparse would take it for a positional, and every command, ``--help`` too, would die."""
    registry = (CONFLUENCE, JIRA, declaring(Option(flag=flag, help="another")))
    with pytest.raises(ValueError, match=rf"^source 'worklog': option {flag!r}: a flag is"):
        main(["--help"], registry)


@pytest.mark.parametrize("flag", ["-s", "--since2", "--max-size-mb"])
def test_a_flag_of_one_dash_and_a_letter_or_of_two_and_a_word_is_a_flag(flag: str) -> None:
    """As argparse reads them, an option's value kept under its flag."""
    refuse((CONFLUENCE, JIRA, declaring(Option(flag=flag, help="another"))))


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
    table = pkgutil.resolve_name(ATLASSIAN.table_path)
    assert tuple(table.model_fields) == ("site", "email", "api_token")


def test_a_registry_naming_one_account_differently_is_refused_naming_the_source(
    tmp_path: Path,
) -> None:
    """The sources that name an account share its table: two tables of one name are refused."""
    other = replace(ATLASSIAN, table_path=WORKLOG.table_path)
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
def test_a_source_that_the_registry_leaves_out_cannot_be_prepared(
    tmp_path: Path, capsys: CaptureFixture[str], left_out: str
) -> None:
    """Criterion 3: ``prepare`` of it exits 2, argparse naming the choice refused.

    With every source registered, the same name is a choice, here refused as not
    configured, by the run's own check.
    """
    registry = tuple(each for each in SOURCES if each.name != left_out)
    given = ["prepare", "--yes", "--config", str(tmp_path / "none.toml"), left_out]
    with pytest.raises(SystemExit) as stopped:
        main(given, registry)
    assert stopped.value.code == ExitStatus.REFUSED
    assert f"invalid choice: '{left_out}'" in capsys.readouterr().err
    assert main(given) == (ExitStatus.REFUSED if left_out == "worklog" else ExitStatus.OK)
    if left_out == "worklog":
        assert f"{left_out}: not configured" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("field", "path", "said"),
    [
        ("fetcher", "kb_mcp.sources.atlassian.fetch.app.absent", "does not load"),
        ("fetcher", "kb_absent.fetcher", "does not load"),
        ("fetcher", "not a module path", "does not load"),
        ("fetcher", "kb_mcp.sources.atlassian.declared", "not a Fetcher"),
        ("preparers", "kb_mcp.sources.atlassian.fetch.app.fetcher", "not a Preparer"),
    ],
)
def test_a_fetcher_or_preparer_that_does_not_load_refuses_the_run_of_its_source(
    tmp_path: Path, capsys: CaptureFixture[str], field: str, path: str, said: str
) -> None:
    """Criterion 3: a declaration naming a fetcher or a preparer that does not load, or not one.

    The command of its stage, of that source, exits 2 before any row, naming the source and
    the path; with the registry's own declaration, the same run goes on, a fetch to sign
    in, no session being saved, a prepare not counted.
    """
    named = path if field == "fetcher" else (path,)
    registry = (replace(CONFLUENCE, **{field: named}), JIRA, WORKLOG)
    config = tmp_path / "config.toml"
    config.write_text(
        '[accounts.atlassian]\nsite = "https://x.atlassian.net"\n'
        '[sources.confluence]\nspaces = ["MFS"]\n',
        "utf-8",
    )
    data = tmp_path / "data"
    stage, status = ("fetch", ExitStatus.SIGN_IN_AGAIN) if field == "fetcher" else ("prepare", 0)
    given = [stage, "--yes", "--config", str(config), "--data-dir", str(data)]
    given += ["confluence", "--dry-run", "--format", "json"]
    assert main(given, registry) == ExitStatus.REFUSED
    err = capsys.readouterr().err
    assert f"{stage}.refused" in err
    assert f"source 'confluence': {path}: {said}" in err
    assert not data.exists()
    assert main(given) == status


@pytest.mark.parametrize(
    ("body", "said"),
    [
        ("def broken(:\n", "invalid syntax"),
        ('raise RuntimeError("at its import")\n', "at its import"),
    ],
    ids=["a syntax error", "its own error at import"],
)
def test_a_role_whose_module_breaks_on_import_refuses_the_run_naming_the_path(
    tmp_path: Path, monkeypatch: MonkeyPatch, capsys: CaptureFixture[str], body: str, said: str
) -> None:
    """Criterion 3 and ``sources.md``: whatever its import raises, exit 2, not a traceback."""
    (tmp_path / "kb_broken.py").write_text(body, "utf-8")
    monkeypatch.syspath_prepend(tmp_path)
    registry = (replace(CONFLUENCE, preparers=("kb_broken",)), JIRA, WORKLOG)
    config = tmp_path / "config.toml"
    config.write_text(
        '[accounts.atlassian]\nsite = "https://x.atlassian.net"\n'
        '[sources.confluence]\nspaces = ["MFS"]\n',
        "utf-8",
    )
    given = ["prepare", "--yes", "--config", str(config), "--data-dir", str(tmp_path / "data")]
    assert main([*given, "confluence"], registry) == ExitStatus.REFUSED
    err = capsys.readouterr().err
    assert "prepare.refused" in err
    assert "source 'confluence': kb_broken: does not load:" in err
    assert said in err
