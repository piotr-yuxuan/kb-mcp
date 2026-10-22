"""``completion``'s declaration; ``cli.commands.completion`` runs it."""

from __future__ import annotations

from typing import TYPE_CHECKING

from atlassian_offline_mcp.cli.domain.command import PROGRAM, Command

if TYPE_CHECKING:
    import argparse


def register(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """Add ``completion`` to the command."""
    parser = subparsers.add_parser(
        "completion",
        help="print the code that completes the command in bash and zsh",
        description=(
            "Print the code that completes the command in bash and zsh. Add"
            f' eval "$({PROGRAM} completion)" to ~/.bashrc, or to ~/.zshrc after compinit.'
        ),
    )
    parser.set_defaults(
        command=Command(
            "completion", "atlassian_offline_mcp.cli.commands.completion", reads_settings=False
        )
    )
