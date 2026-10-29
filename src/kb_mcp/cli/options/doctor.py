"""``doctor``'s declaration; ``cli.commands.doctor`` runs it."""

from __future__ import annotations

from typing import TYPE_CHECKING

from kb_mcp.cli.domain.command import Command
from kb_mcp.cli.options._common import (
    SIGN_IN,
    add_output_options,
    add_settings_options,
    email_without_token,
    token_without_email,
)

if TYPE_CHECKING:
    import argparse


def register(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """Add ``doctor`` to the command."""
    parser = subparsers.add_parser(
        "doctor",
        help="check the machine and the sign-in",
        epilog=(
            "With --format json: a list of verdicts, each a check's name, what it found, and"
            " its state: well, failed, or sign in."
        ),
    )
    actions, flags = add_settings_options(parser)
    add_output_options(parser)
    parser.set_defaults(
        command=Command(
            "doctor",
            "kb_mcp.cli.commands.doctor",
            reads=("site", *SIGN_IN, "data_dir"),
            flags=flags,
            actions=actions,
            unapplied=email_without_token,
            refused=token_without_email,
        )
    )
