"""``mirror``'s declaration; ``cli.commands.mirror`` runs it."""

from __future__ import annotations

from typing import TYPE_CHECKING

from atlassian_offline_mcp.cli.domain.command import Command
from atlassian_offline_mcp.cli.options._common import (
    add_output_options,
    add_settings_options,
    add_yes_option,
)

if TYPE_CHECKING:
    import argparse


def register(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """Add ``mirror`` to the command."""
    parser = subparsers.add_parser(
        "mirror",
        help="write the Markdown mirror from the raw store",
        epilog=(
            "With --format json: documents, how many are mirrored; changes, the files"
            " written, unchanged and removed; unsupported, what the mirror does not show, by"
            " name; problems, each by its place and why."
        ),
    )
    actions, flags = add_settings_options(parser)
    add_output_options(parser)
    add_yes_option(parser)
    parser.set_defaults(
        command=Command(
            "mirror",
            "atlassian_offline_mcp.cli.commands.mirror",
            reads=("site", "data_dir"),
            flags=flags,
            actions=actions,
            writes=True,
            programs=("pandoc",),
        )
    )
