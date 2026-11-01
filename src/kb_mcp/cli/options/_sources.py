"""What ``fetch`` and ``prepare`` declare from the registry's declarations, and refuse alike."""

from __future__ import annotations

import argparse
from typing import TYPE_CHECKING

from kb_mcp.cli.domain.sources import chosen

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from kb_mcp.sources.declaration import Declared

# How a resource type is read, in the words of its source's group.
READ = {
    "listed": "listed whole",
    "searched": "searched by update time",
    "in place": "read whole, in place",
}


def source_groups(
    parser: argparse.ArgumentParser, sources: Sequence[Declared]
) -> dict[str, argparse._ArgumentGroup]:
    """Add a group per source to the help, what it is, what it reads and how; give each by name."""
    return {
        declared.name: parser.add_argument_group(
            declared.name,
            f"{declared.summary}: "
            + "; ".join(f"{each.name}, {READ[each.read]}" for each in declared.types)
            + ".",
        )
        for declared in sources
    }


def add_source_options(
    parser: argparse.ArgumentParser, sources: Sequence[Declared]
) -> tuple[tuple[argparse.Action, ...], dict[str, str]]:
    """Add a group per source, with the options that it alone declares; then the others.

    An option that several sources declare is added once, in a group of its own, naming
    them. None has a default, so that one given is told from one not given; one that
    replaces a setting repeats. Its value is kept under its flag itself, so that no flag that
    a source declares takes a name that the program holds, such as ``sources``; help names
    its value as it would by the flag alone. Give the actions, and each flag's setting.
    Raises ValueError, naming the source, for an option that takes a flag of the
    command's own, as the registry's rules do.
    """
    groups = source_groups(parser, sources)
    options = {flag: option for declared in sources for flag, option in declared.options.items()}
    declaring = {flag: [each for each in sources if flag in each.options] for flag in options}
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
                type=option.type,
                help=option.help,
            )
            for flag, option in options.items()
        }
    except argparse.ArgumentError as error:
        flag = error.argument_name
        message = f"source {declaring[flag][0].name!r}: option {flag}: a flag of the command's own"
        raise ValueError(message) from error
    flags = {added[flag].dest: option.setting for flag, option in options.items() if option.setting}
    return tuple(added.values()), flags


def choice_refused(arguments: argparse.Namespace, settings: Mapping[str, object]) -> str | None:
    """Refuse a source named but not configured, or a run left with none: the first found."""
    taken, left = chosen(arguments, settings)
    faults = [
        f"{declared.name}: not configured; set {declared.paths[0]}"
        for declared in arguments.sources
        if declared.name in arguments.source and left.get(declared.name) == "not configured"
    ]
    step = arguments.command.name
    faults.append(None if taken else f"nothing to {step}: none of its sources is configured")
    return next((fault for fault in faults if fault is not None), None)


def left_unapplied(arguments: argparse.Namespace, settings: Mapping[str, object]) -> dict[str, str]:
    """Name what the run does not apply of the sources left out, and why.

    The settings that the command reads of those left out, but the first of one not
    configured, which holds nothing to apply; and those of an account that no source taken
    names.
    """
    taken, left = chosen(arguments, settings)
    reads = arguments.command.reads
    signing = {declared.account.name for declared in taken if declared.account is not None}
    unused = {
        path: f"{declared.name} {left[declared.name]}"
        for declared in arguments.sources
        if declared.name in left
        for path in declared.paths
        if path in reads and (left[declared.name] != "not configured" or path != declared.paths[0])
    }
    unused |= {
        path: f"no source of the {declared.account.name} account in this {arguments.command.name}"
        for declared in arguments.sources
        if declared.account is not None and declared.account.name not in signing
        for path in declared.account.paths
    }
    return unused
