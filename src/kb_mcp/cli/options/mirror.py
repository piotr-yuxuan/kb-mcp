"""``mirror``'s declaration; ``cli.commands.mirror`` runs it."""

from __future__ import annotations

from typing import TYPE_CHECKING

from kb_mcp.cli.domain.command import Command
from kb_mcp.cli.options._common import (
    SITE,
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
            "With --format json: exit_status, the run's; steps, a row per source,"
            " confluence then jira, each with its step, mirror, its source, its outcome"
            " (done, failed) and its result: documents, how many are mirrored; converted,"
            " the conversions pandoc ran, and reused, those the cache gave, a document's"
            " file and a space's tree being one each; changes, the files written,"
            " unchanged and removed; unsupported, what the mirror does not show, by name;"
            " problems, each by its place and why."
        ),
    )
    actions, flags = add_settings_options(parser)
    add_output_options(parser)
    add_yes_option(parser)
    parser.set_defaults(
        command=Command(
            "mirror",
            "kb_mcp.cli.commands.mirror",
            reads=(SITE, "data_dir"),
            flags=flags,
            actions=actions,
            writes=True,
            programs=("pandoc",),
        )
    )
