"""``doctor``'s declaration, from the sources that sign in; ``cli.commands.doctor`` runs it."""

from __future__ import annotations

from typing import TYPE_CHECKING

from kb_mcp.cli.domain.command import Command
from kb_mcp.cli.options._common import add_output_options, add_settings_options

if TYPE_CHECKING:
    import argparse
    from collections.abc import Mapping, Sequence

    from kb_mcp.sources.declaration import Source


def checked(arguments: argparse.Namespace, settings: Mapping[str, object]) -> tuple[Source, ...]:
    """Give the sources whose sign-in ``doctor`` checks: each in use whose connector checks.

    One is in use when its first setting, what it covers, or its location is set.
    """
    return tuple(
        each
        for each in arguments.sources
        if each.connector.checks is not None
        and (
            settings[each.paths[0]]
            or (each.connector.location and settings[each.path(each.connector.location)])
        )
    )


def refused(arguments: argparse.Namespace, settings: Mapping[str, object]) -> str | None:
    """Refuse what a sign-in to check cannot run with, by its connector's ``refused``: the first.

    Asked with none of its options given.
    """
    faults = (
        each.connector.refused(each, dict.fromkeys(each.connector.flags), settings)
        for each in checked(arguments, settings)
        if each.connector.refused is not None
    )
    return next((fault for fault in faults if fault is not None), None)


def unapplied(arguments: argparse.Namespace, settings: Mapping[str, object]) -> dict[str, str]:
    """Name what each sign-in does not apply, by its connector's ``unapplied``, and the unchecked.

    The settings of a source not in use are not checked, whatever they say, so that a
    token and an email without a site do not read as a sign-in that holds.
    """
    taken = checked(arguments, settings)
    unused: dict[str, str] = {}
    for each in (each for each in arguments.sources if each.connector.checks is not None):
        connector = each.connector
        if each not in taken:
            unused |= dict.fromkeys(each.paths[1:], f"{each.name} not in use: not checked")
        elif connector.unapplied:
            unused |= connector.unapplied(each, dict.fromkeys(connector.flags), settings)
    return unused


def register(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
    sources: Sequence[Source],
) -> None:
    """Add ``doctor`` to the command.

    It reads the data folder and the settings of each source of a connector with checks,
    whose first says whether it is checked.
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
                "data_dir",
                *(path for each in sources if each.connector.checks for path in each.paths),
            ),
            flags=flags,
            actions=actions,
            unapplied=unapplied,
            refused=refused,
        )
    )
