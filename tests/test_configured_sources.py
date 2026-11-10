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

from typing import TYPE_CHECKING

import pytest

from kb_mcp.cli.commands import sources as sources_command
from kb_mcp.cli.main import main
from kb_mcp.kernel.exit_status import ExitStatus

if TYPE_CHECKING:
    import argparse
    from pathlib import Path

    from _pytest.capture import CaptureFixture
    from _pytest.monkeypatch import MonkeyPatch

    from kb_mcp.config.domain.settings import Loaded

# A second Jira site's source, as a settings file writes it.
CLIENT = '[sources.clientjira]\nconnector = "jira"\nprojects = ["ABC"]\n'


@pytest.fixture
def runs(monkeypatch: MonkeyPatch) -> list[tuple[argparse.Namespace, Loaded]]:
    """Make ``fetch`` and ``prepare`` record what their run was given, and do nothing."""
    recorded: list[tuple[argparse.Namespace, Loaded]] = []

    def run(arguments: argparse.Namespace, loaded: Loaded) -> tuple[int, None]:
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
        f'{CLIENT}[sources.jira]\nprojects = ["PRB"]\n'
        '[accounts.atlassian]\nsite = "https://client.example.invalid"\n',
        "utf-8",
    )
    assert main(["fetch", "clientjira", "--yes", "--config", str(config), "--project", "XYZ"]) == 0
    [(_, loaded)] = runs
    assert loaded.settings.sources.clientjira.projects == ("XYZ",)
    assert loaded.settings.sources.jira.projects == ("PRB",)
    assert loaded.layers["sources.clientjira.projects"] == "--project"
    assert "--project XYZ" in capsys.readouterr().err
