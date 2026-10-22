"""``check``'s declaration; ``cli.commands.check`` runs it."""

from __future__ import annotations

from typing import TYPE_CHECKING

from atlassian_offline_mcp.cli.domain.command import Command
from atlassian_offline_mcp.cli.options._common import add_output_options, add_settings_options

if TYPE_CHECKING:
    import argparse

# Every setting, by its path, in the model's order: check shows them all.
EVERY_SETTING = (
    "site",
    "email",
    "api_token",
    "data_dir",
    "model",
    "search_mode",
    "embedding_url",
    "embedding_api_key",
    "sources.confluence.spaces",
    "sources.jira.projects",
    "logs.dir",
    "telemetry.endpoint",
)


def register(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """Add ``check`` to the command."""
    parser = subparsers.add_parser(
        "check",
        help="validate the settings and the data directory",
        epilog=(
            "With --format json: settings, secrets masked; layers, the layer of each setting"
            " that one gave; ignored, each value ignored, with its setting, layer and why."
        ),
    )
    actions, flags = add_settings_options(parser)
    add_output_options(parser)
    parser.set_defaults(
        command=Command(
            "check",
            "atlassian_offline_mcp.cli.commands.check",
            reads=EVERY_SETTING,
            flags=flags,
            actions=actions,
        )
    )
