"""What ``fetch`` and ``prepare`` choose and say, as pure functions of arguments and settings.

The sources are those that the settings configure, which the arguments hold
(``sources``), and those named among them (``source``). A source is configured when its
first setting, which names what it covers, is set. ``fetch`` takes every source that has
a fetcher and is configured, or those named. ``prepare`` takes every source whose store
keeps scopes by key, whatever the store holds, and each other when it is configured, as
``Source.prepared_by_default`` says, or those named. Each is taken once, in the sources'
order, whatever the order typed. A source's options and light checks are its connector's
fetch's: each source taken says what the echo says of it, by its connector, and one whose
settings its light check refuses, that it will not run, and why; an option that no
setting holds, given, is said ignored by each source taken whose connector does not
declare it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from kb_mcp.cli.domain.command import PREPARE

if TYPE_CHECKING:
    import argparse
    from collections.abc import Iterable, Mapping
    from datetime import datetime

    from kb_mcp.sources.declaration import Option, Source


def given(arguments: argparse.Namespace, flags: Iterable[str]) -> dict[str, object]:
    """Give the value of each option by its flag, None when not given.

    ``add_source_options`` keeps an option's value under its flag itself.
    """
    return {flag: getattr(arguments, flag) for flag in flags}


def fetch_flags(sources: Iterable[Source]) -> dict[str, Option]:
    """Give each option of those of ``sources`` that have a fetcher, by its flag."""
    return {
        flag: option
        for each in sources
        if each.connector.fetcher is not None
        for flag, option in each.connector.flags.items()
    }


def fetch_options(
    arguments: argparse.Namespace, taken: Iterable[Source], start: datetime
) -> dict[str, object]:
    """Give each option of the sources ``taken`` that no setting holds, by flag, as recorded.

    As of the run's ``start`` where its declaration says how, such as --since 7d, a time,
    and --until not given, that start; else as given, None when not given. An option
    that replaces a setting, such as --space, is in the settings that the run records.
    No source's options are read unless it is taken, as ``fetch``'s refusals read them.
    """
    return {
        flag: getattr(arguments, flag)
        if option.absolute is None
        else option.absolute(getattr(arguments, flag), start)
        for flag, option in sorted(fetch_flags(taken).items())
        if option.setting is None
    }


def chosen_to_fetch(
    arguments: argparse.Namespace, settings: Mapping[str, object]
) -> tuple[tuple[Source, ...], dict[str, str]]:
    """Return the sources that a fetch takes, in their order, and why each other is left out."""
    named = set(arguments.source)
    taken: list[Source] = []
    left: dict[str, str] = {}
    for declared in arguments.sources:
        if declared.connector.fetcher is None:
            left[declared.name] = "read in place, it has nothing to fetch"
        elif named and declared.name not in named:
            left[declared.name] = "not named"
        elif not settings[declared.paths[0]]:
            left[declared.name] = "not configured"
        else:
            taken.append(declared)
    return tuple(taken), left


def refusals(arguments: argparse.Namespace, settings: Mapping[str, object]) -> dict[str, str]:
    """Give why each source that a fetch takes cannot run, by its settings, by its name.

    As its connector's light check of its settings says (``Source.refusal``), such as a
    site not set; a source that it lets run is not given.
    """
    taken, _ = chosen_to_fetch(arguments, settings)
    return {each.name: why for each in taken if (why := each.refusal(settings)) is not None}


def chosen_to_prepare(
    arguments: argparse.Namespace, settings: Mapping[str, object]
) -> tuple[tuple[Source, ...], dict[str, str]]:
    """Return the sources that a prepare takes, in their order, and why each other is left out."""
    named = set(arguments.source)
    taken: list[Source] = []
    left: dict[str, str] = {}
    for declared in arguments.sources:
        if named and declared.name not in named:
            left[declared.name] = "not named"
        elif not declared.prepared_by_default(settings):
            left[declared.name] = "not configured"
        else:
            taken.append(declared)
    return tuple(taken), left


def chosen(
    arguments: argparse.Namespace, settings: Mapping[str, object]
) -> tuple[tuple[Source, ...], dict[str, str]]:
    """Return what the command that the arguments name takes, and why each other is left out.

    ``prepare`` takes what a prepare takes; ``fetch`` and ``refresh``, what a fetch takes.
    """
    choose = chosen_to_prepare if arguments.command.name == PREPARE else chosen_to_fetch
    return choose(arguments, settings)


def source_line(declared: Source, settings: Mapping[str, object]) -> str:
    """Say a source taken, with the value of each of its settings that holds one."""
    values = {
        path: ", ".join(value) if isinstance(value := settings[path], tuple) else str(value)
        for path in declared.paths
        if settings[path] is not None
    }
    shown = (f"{path.rpartition('.')[2]} {value}" for path, value in values.items())
    return f"source {declared.name}: {', '.join(shown)}"


def fetch_described(
    arguments: argparse.Namespace, settings: Mapping[str, object]
) -> tuple[str, ...]:
    """Say each source taken, with its settings, each that will not run or is left out and why.

    A source taken that will not run is one whose settings its light check refuses
    (``refusals``): its unit fails, and the others run. The lines that each other source
    taken says follow, each once, as its connector's ``described`` gives them; then the
    options ignored. An option that no setting holds, given, is ignored by each source
    taken whose connector does not declare it, as is one that replaces a setting of no
    source named (``Command.narrowed``); another that replaces a setting is said by
    ``unapplied``, as for any setting.
    """
    taken, left = chosen_to_fetch(arguments, settings)
    refused = refusals(arguments, settings)
    lines = [source_line(declared, settings) for declared in taken]
    said: list[str] = []
    for declared in (each for each in taken if each.name not in refused):
        connector = declared.connector
        options = given(arguments, connector.flags)
        said += connector.described(declared, options, settings) if connector.described else ()
    lines += [f"source {name}: will not run, {why}" for name, why in refused.items()]
    lines += [f"source {name}: left out, {why}" for name, why in left.items()]
    lines += said
    unbound = {flag for flag, left in arguments.command.narrowed(arguments).items() if not left}
    flags = {
        flag
        for flag, option in fetch_flags(arguments.sources).items()
        if option.setting is None or flag in unbound
    }
    for flag, value in sorted(given(arguments, flags).items()):
        ignoring = [each.name for each in taken if flag not in each.connector.flags]
        if value is not None and ignoring:
            lines.append(f"{flag}: ignored by {', '.join(ignoring)}")
    return tuple(dict.fromkeys(lines))


def prepare_described(
    arguments: argparse.Namespace, settings: Mapping[str, object]
) -> tuple[str, ...]:
    """Say each source taken, each left out and why, and each one's location not set.

    A source read in place is said by its settings; one that keeps a store gives all that
    its store holds, whatever its settings cover. Without its location, such as its site,
    a prepare still runs, its documents without an address there.
    """
    taken, left = chosen_to_prepare(arguments, settings)
    unset = [
        (path, declared.name)
        for declared in taken
        if declared.connector.location is not None
        and settings[path := declared.path(declared.connector.location)] is None
    ]
    return (
        *(
            source_line(declared, settings)
            if declared.connector.fetcher is None
            else f"source {declared.name}: all that its store holds"
            for declared in taken
        ),
        *(f"source {name}: left out, {why}" for name, why in left.items()),
        *(
            f"{path}: not set; any documents of {names} get no address there"
            for path, names in unset
        ),
    )
