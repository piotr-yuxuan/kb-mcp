"""What ``fetch`` and ``prepare`` declare from the registry's declarations, and refuse alike."""

from __future__ import annotations

import argparse
from typing import TYPE_CHECKING

from kb_mcp.cli.domain.sources import chosen

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from kb_mcp.sources.declaration import Source

# How a fetch enumerates a scope type's documents, in the words of its source's group,
# each said of the scope type's name.
READ = {
    "listed": "each {} listed whole",
    "searched": "each {} searched by update time",
    "in place": "its {}, read whole, in place",
}


def source_groups(
    parser: argparse.ArgumentParser, sources: Sequence[Source]
) -> dict[str, argparse._ArgumentGroup]:
    """Add a group per source to the help: what it is, its scope types and how each is read.

    Give each group by its source's name. Raises ValueError, naming the source, for a scope
    type enumerated in a way that ``READ`` has no words for, the first found, as the
    registry's rules do.
    """
    unknown = [
        f"source {declared.name!r}: scope type {each.name!r}: enumerated {each.enumeration!r}:"
        f" not one of {', '.join(READ)}"
        for declared in sources
        for each in declared.connector.scope_types
        if each.enumeration not in READ
    ]
    if unknown:
        raise ValueError(unknown[0])
    return {
        declared.name: parser.add_argument_group(
            declared.name,
            f"{declared.connector.help}: "
            + "; ".join(
                READ[each.enumeration].format(each.name) for each in declared.connector.scope_types
            )
            + ".",
        )
        for declared in sources
    }


def add_source_options(
    parser: argparse.ArgumentParser, sources: Sequence[Source]
) -> tuple[tuple[argparse.Action, ...], dict[str, str]]:
    """Add a group per source, with the options that it alone declares; then the others.

    An option that several sources declare is added once, in a group of its own, naming
    them. None has a default, so that one given is told from one not given; one that
    replaces a setting of its source's table repeats. Its value is kept under its flag
    itself, so that no flag that a source declares takes a name that the program holds,
    such as ``sources``; help names its value as it would by the flag alone. Give the
    actions, and each flag's setting, by its path.
    Raises ValueError, naming the source, for an option that takes a flag of the
    command's own, as the registry's rules do.
    """
    groups = source_groups(parser, sources)
    options = {
        flag: option for declared in sources for flag, option in declared.connector.flags.items()
    }
    declaring = {
        flag: [each for each in sources if flag in each.connector.flags] for flag in options
    }
    several = sorted({each.name for found in declaring.values() if found[1:] for each in found})
    shared = (
        parser.add_argument_group("several sources", f"The options of {', '.join(several)}.")
        if several
        else None
    )
    try:
        added = {
            flag: (shared if declaring[flag][1:] else groups[declaring[flag][0].name]).add_argument(
                flag,
                dest=flag,
                metavar=flag.lstrip("-").replace("-", "_").upper(),
                action="append" if option.setting else "store",
                type=option.parse,
                help=option.help,
            )
            for flag, option in options.items()
        }
    except argparse.ArgumentError as error:
        flag = error.argument_name
        message = f"source {declaring[flag][0].name!r}: option {flag}: a flag of the command's own"
        raise ValueError(message) from error
    flags = {
        added[flag].dest: f"sources.{declaring[flag][0].name}.{option.setting}"
        for flag, option in options.items()
        if option.setting
    }
    return tuple(added.values()), flags


def choice_refused(arguments: argparse.Namespace, settings: Mapping[str, object]) -> str | None:
    """Refuse a source named but not configured, or a run left with none: the first found."""
    taken, left = chosen(arguments, settings)
    faults = [
        f"{declared.name}: not configured; set {declared.paths[0]}"
        for declared in arguments.sources
        if declared.name in arguments.source and left.get(declared.name) == "not configured"
    ]
    stage = arguments.command.name
    faults.append(None if taken else f"nothing to {stage}: none of its sources is configured")
    return next((fault for fault in faults if fault is not None), None)


def left_unapplied(arguments: argparse.Namespace, settings: Mapping[str, object]) -> dict[str, str]:
    """Name what the run does not apply of the sources left out, and why.

    The settings that the command reads of those left out, but the first of one not
    configured, which holds nothing to apply; and those of an account that no source taken
    names.
    """
    taken, left = chosen(arguments, settings)
    reads = arguments.command.reads
    signing = {each.account.name for each in (d.connector for d in taken) if each.account}
    unused = {
        path: f"{declared.name} {left[declared.name]}"
        for declared in arguments.sources
        if declared.name in left
        for path in declared.paths
        if path in reads and (left[declared.name] != "not configured" or path != declared.paths[0])
    }
    unused |= {
        path: f"no source of the {account.name} account in this {arguments.command.name}"
        for account in (declared.connector.account for declared in arguments.sources)
        if account is not None and account.name not in signing
        for path in account.paths
    }
    return unused
