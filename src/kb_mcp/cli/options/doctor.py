"""``doctor``'s declaration, from the registry's accounts; ``cli.commands.doctor`` runs it."""

from __future__ import annotations

from typing import TYPE_CHECKING

from kb_mcp.cli.domain.command import Command
from kb_mcp.cli.options._common import add_output_options, add_settings_options
from kb_mcp.sources.registry import accounts_of

if TYPE_CHECKING:
    import argparse
    from collections.abc import Mapping, Sequence

    from kb_mcp.sources.declaration import Declared


def refused(arguments: argparse.Namespace, settings: Mapping[str, object]) -> str | None:
    """Refuse what a sign-in cannot be checked with, by each account's ``refused``: the first."""
    faults = (
        account.refused({}, settings)
        for account in accounts_of(arguments.sources).values()
        if account.refused is not None
    )
    return next((fault for fault in faults if fault is not None), None)


def unapplied(arguments: argparse.Namespace, settings: Mapping[str, object]) -> dict[str, str]:
    """Name what each sign-in does not apply, by each account's ``unapplied``."""
    unused: dict[str, str] = {}
    for account in accounts_of(arguments.sources).values():
        unused |= account.unapplied({}, settings) if account.unapplied else {}
    return unused


def register(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
    sources: Sequence[Declared],
) -> None:
    """Add ``doctor`` to the command, which reads each account's settings and the data folder."""
    parser = subparsers.add_parser(
        "doctor",
        help="check the machine and each sign-in",
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
            reads=(
                *(path for account in accounts_of(sources).values() for path in account.paths),
                "data_dir",
            ),
            flags=flags,
            actions=actions,
            unapplied=unapplied,
            refused=refused,
        )
    )
