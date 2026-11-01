"""What ``fetch`` and ``prepare`` declare from the registry's declarations, and refuse of them."""

from __future__ import annotations

import argparse
from typing import TYPE_CHECKING

from kb_mcp.cli.domain.sources import FETCH, chosen, given
from kb_mcp.cli.options._common import add_option

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from kb_mcp.sources.declaration import Declared

# How a resource type is read, in the words of its source's group.
READ = {"listed": "listed whole", "searched": "searched by update time", "in place": "in place"}


def source_group(parser: argparse.ArgumentParser, declared: Declared) -> argparse._ArgumentGroup:
    """Add a source's group to the help: what it is, what it reads, and how."""
    types = "; ".join(f"{each.name}, {READ[each.read]}" for each in declared.types)
    return parser.add_argument_group(declared.name, f"{declared.summary}: {types}.")


def add_source_options(
    parser: argparse.ArgumentParser, sources: Sequence[Declared]
) -> tuple[tuple[argparse.Action, ...], dict[str, str]]:
    """Add a group per source, with the options that it alone declares; then the others.

    An option that several sources declare is added once, in a group of its own, naming
    them. None has a default, so that one given is told from one not given. Give the
    actions, and each flag's setting by its ``dest``.
    Raises ValueError, naming the source, for an option that takes a flag of the
    command's own, as the registry's rules do.
    """
    declaring: dict[str, list[Declared]] = {}
    for declared in sources:
        for flag in declared.options:
            declaring.setdefault(flag, []).append(declared)
    groups = {declared.name: source_group(parser, declared) for declared in sources}
    several = sorted({each.name for found in declaring.values() if found[1:] for each in found})
    shared = (
        parser.add_argument_group("several sources", f"The options of {', '.join(several)}.")
        if several
        else None
    )
    actions: list[argparse.Action] = []
    flags: dict[str, str] = {}
    for flag, found in declaring.items():
        option = found[0].options[flag]
        group = shared if found[1:] else groups[found[0].name]
        try:
            added = add_option(group, option)
        except argparse.ArgumentError as error:
            message = f"source {found[0].name!r}: option {flag}: a flag of the command's own"
            raise ValueError(message) from error
        actions.append(added)
        if option.setting:
            flags[added.dest] = option.setting
    return tuple(actions), flags


def refused(arguments: argparse.Namespace, settings: Mapping[str, object]) -> str | None:
    """Refuse what no run can go on with, before anything is asked: the first found.

    A source named but not configured, or none left; then, in a fetch, what each source
    taken refuses, by its declaration's ``refused``, such as an option that does not read,
    or a site not set, which a prepare does not need: no source's options are read unless
    it is taken.
    """
    step = arguments.command.name
    taken, left = chosen(arguments, settings)
    faults = [
        f"{declared.name}: not configured; set {declared.paths[0]}"
        for declared in arguments.sources
        if declared.name in arguments.source and left.get(declared.name) == "not configured"
    ]
    faults.append(None if taken else f"nothing to {step}: no source is configured")
    if step == FETCH:
        faults += [
            declared.refused(given(arguments, declared.options), settings)
            for declared in taken
            if declared.refused is not None
        ]
    return next((fault for fault in faults if fault is not None), None)


def unapplied(arguments: argparse.Namespace, settings: Mapping[str, object]) -> dict[str, str]:
    """Name what the run does not apply, and why.

    The settings that the command reads of the sources left out, those that hold a value,
    since an empty list applies nothing, and those of an account that no source taken
    names; then, in a fetch, what each source taken does not apply, by its declaration's
    ``unapplied``, such as an email without the API token that it signs in with.
    """
    step = arguments.command.name
    reads = arguments.command.reads
    taken, left = chosen(arguments, settings)
    signing = {declared.account.name for declared in taken if declared.account is not None}
    unused = {
        path: f"{declared.name} {left[declared.name]}"
        for declared in arguments.sources
        if declared.name in left
        for path in declared.paths
        if path in reads and settings[path]
    }
    unused |= {
        path: f"no source of the {declared.account.name} account in this {step}"
        for declared in arguments.sources
        if declared.account is not None and declared.account.name not in signing
        for path in declared.account.paths
    }
    for declared in taken if step == FETCH else ():
        options = given(arguments, declared.options)
        unused |= declared.unapplied(options, settings) if declared.unapplied else {}
    return unused
