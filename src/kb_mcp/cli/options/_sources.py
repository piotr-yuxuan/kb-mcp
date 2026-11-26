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
# How often a scope type searched by update time is read whole besides, said of its interval.
WHOLE = ", read whole every {.days} days for what it no longer holds"


def source_groups(
    parser: argparse.ArgumentParser, sources: Sequence[Source]
) -> dict[str, argparse._ArgumentGroup]:
    """Add a group per source to the help: what it is, its scope types and how each is read.

    Give each group by its source's name. Raises ValueError, naming the source, for a scope
    type enumerated in a way that ``READ`` has no words for.
    """
    unknown = [
        f"source {source.name!r}: scope type {each.name!r}: enumerated {each.enumeration!r}:"
        f" not one of {', '.join(READ)}"
        for source in sources
        for each in source.connector.scope_types
        if each.enumeration not in READ
    ]
    if unknown:
        raise ValueError(unknown[0])
    return {
        source.name: parser.add_argument_group(
            source.name,
            f"{source.connector.help}: "
            + "; ".join(
                READ[each.enumeration].format(each.name)
                + ("" if each.whole_read_every is None else WHOLE.format(each.whole_read_every))
                for each in source.connector.scope_types
            )
            + ".",
        )
        for source in sources
    }


def add_source_options(
    parser: argparse.ArgumentParser, sources: Sequence[Source]
) -> tuple[tuple[argparse.Action, ...], dict[str, dict[str, str]]]:
    """Add a group per source, with the options that it alone declares; then the others.

    An option that several sources declare is added once, in a group of its own. None has
    a default, so that one given is told from one not given; one that replaces a setting
    repeats. Each value is kept under its flag itself. Give the actions, and each flag's
    setting by source, by its path. Raises ValueError, naming the source, for an option
    that takes a flag of the command's own.
    """
    groups = source_groups(parser, sources)
    options = {
        flag: option for source in sources for flag, option in source.connector.flags.items()
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
    scoped = {
        added[flag].dest: {
            each.name: f"sources.{each.name}.{option.setting}" for each in declaring[flag]
        }
        for flag, option in options.items()
        if option.setting
    }
    return tuple(added.values()), scoped


def choice_refused(arguments: argparse.Namespace, settings: Mapping[str, object]) -> str | None:
    """Refuse a source named but not configured, or a run left with none: the first found."""
    taken, left = chosen(arguments, settings, arguments.command.name)
    faults = [
        f"{source.name}: not configured; set {source.paths[0]}"
        for source in arguments.sources
        if source.name in arguments.source and left.get(source.name) == "not configured"
    ]
    stage = arguments.command.name
    faults.append(None if taken else f"nothing to {stage}: none of its sources is configured")
    return next((fault for fault in faults if fault is not None), None)


def left_unapplied(arguments: argparse.Namespace, settings: Mapping[str, object]) -> dict[str, str]:
    """Name each setting read of those left out, but the first of one not configured, and why."""
    _, left = chosen(arguments, settings, arguments.command.name)
    reads = arguments.command.reads
    return {
        path: f"{source.name} {left[source.name]}"
        for source in arguments.sources
        if source.name in left
        for path in source.paths
        if path in reads and (left[source.name] != "not configured" or path != source.paths[0])
    }
