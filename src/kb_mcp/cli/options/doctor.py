"""``doctor``'s declaration, from the registry's accounts; ``cli.commands.doctor`` runs it."""

from __future__ import annotations

from typing import TYPE_CHECKING

from kb_mcp.cli.domain.command import Command
from kb_mcp.cli.domain.sources import accounts_to_check
from kb_mcp.cli.options._common import add_output_options, add_settings_options
from kb_mcp.sources.registry import accounts_of

if TYPE_CHECKING:
    import argparse
    from collections.abc import Mapping, Sequence

    from kb_mcp.sources.declaration import Source


def refused(arguments: argparse.Namespace, settings: Mapping[str, object]) -> str | None:
    """Refuse what a sign-in to check cannot run with, by its account's ``refused``: the first."""
    faults = (
        account.refused({}, settings)
        for account in accounts_to_check(arguments.sources, settings).values()
        if account.refused is not None
    )
    return next((fault for fault in faults if fault is not None), None)


def unapplied(arguments: argparse.Namespace, settings: Mapping[str, object]) -> dict[str, str]:
    """Name what each sign-in does not apply, by each account's ``unapplied``, and the unchecked.

    The settings of an account that this machine does not use are not checked, whatever they
    say, so that a token and an email without a site do not read as a sign-in that holds.
    """
    checked = accounts_to_check(arguments.sources, settings)
    unused: dict[str, str] = {}
    for name, account in accounts_of(arguments.sources).items():
        if name not in checked:
            unused |= dict.fromkeys(
                account.paths, "no site nor source of it: its sign-in not checked"
            )
        elif account.unapplied:
            unused |= account.unapplied({}, settings)
    return unused


def register(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
    sources: Sequence[Source],
) -> None:
    """Add ``doctor`` to the command.

    It reads each account's settings, the data folder, and the first setting of each source
    naming an account, which says whether that account is checked.
    """
    parser = subparsers.add_parser(
        "doctor",
        help="check the machine and each sign-in",
        epilog=(
            "With --format json: a list of checks, each with its name, what it found, and"
            " its state: well, failed, or sign in again."
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
                *(each.paths[0] for each in sources if each.account is not None),
            ),
            flags=flags,
            actions=actions,
            unapplied=unapplied,
            refused=refused,
        )
    )
