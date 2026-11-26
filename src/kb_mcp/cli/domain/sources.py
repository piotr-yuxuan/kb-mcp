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

from kb_mcp.cli.domain.command import FETCH, PREPARE

if TYPE_CHECKING:
    import argparse
    from collections.abc import Collection, Iterable, Mapping
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


def chosen(
    arguments: argparse.Namespace, settings: Mapping[str, object], stage: str
) -> tuple[tuple[Source, ...], dict[str, str]]:
    """Return the sources that a stage takes, in their order, and why each other is left out.

    ``PREPARE`` takes what a prepare takes; any other stage, what a fetch takes.
    """
    preparing = stage == PREPARE
    named = set(arguments.source)
    taken: list[Source] = []
    left: dict[str, str] = {}
    for source in arguments.sources:
        if not preparing and source.connector.fetcher is None:
            left[source.name] = "read in place, it has nothing to fetch"
        elif named and source.name not in named:
            left[source.name] = "not named"
        elif not (source.prepared_by_default(settings) if preparing else settings[source.paths[0]]):
            left[source.name] = "not configured"
        else:
            taken.append(source)
    return tuple(taken), left


def refusals(sources: Iterable[Source], settings: Mapping[str, object]) -> dict[str, str]:
    """Give why each of ``sources`` cannot run, by its settings, by its name.

    As its connector's light check of its settings says (``Source.refusal``), such as a
    site not set; a source that it lets run is not given.
    """
    return {each.name: why for each in sources if (why := each.refusal(settings)) is not None}


def source_line(source: Source, settings: Mapping[str, object]) -> str:
    """Say a source taken, with the value of each of its settings that holds one."""
    values = {
        path: ", ".join(value) if isinstance(value := settings[path], tuple) else str(value)
        for path in source.paths
        if settings[path] is not None
    }
    shown = (f"{path.rpartition('.')[2]} {value}" for path, value in values.items())
    return f"source {source.name}: {', '.join(shown)}"


def fetch_described(
    arguments: argparse.Namespace,
    settings: Mapping[str, object],
    refused: Mapping[str, str] | None = None,
) -> tuple[str, ...]:
    """Say each source taken, with its settings, each that will not run or is left out and why.

    A source taken that will not run is one whose settings its light check refuses
    (``refusals``), as ``refused`` gives it when the caller asked it already, such as a
    refresh, whose prepare says those too: its unit fails, and the others run. The lines
    that each other source taken says follow, each once, as its connector's
    ``described`` gives them; then the options ignored. An option that no setting holds,
    given, is ignored by each source taken whose connector does not declare it, as is one
    that replaces a setting of no source named (``Command.narrowed``); another that
    replaces a setting is said by ``unapplied``, as for any setting.
    """
    taken, left = chosen(arguments, settings, FETCH)
    refused = refusals(taken, settings) if refused is None else refused
    lines = [source_line(source, settings) for source in taken]
    said: list[str] = []
    for source in (each for each in taken if each.name not in refused):
        connector = source.connector
        options = given(arguments, connector.flags)
        said += connector.described(source, options, settings) if connector.described else ()
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
    arguments: argparse.Namespace,
    settings: Mapping[str, object],
    unfetched: Collection[str] = (),
) -> tuple[str, ...]:
    """Say each source taken, each left out and why, and each one's location not set.

    A source read in place is said by its settings; one that keeps a store gives all that
    its store holds, whatever its settings cover. Without its location, such as its site
    (``Source.unlocated``), a prepare still runs, its documents without an address there.
    A source ``unfetched``, whose fetch will not run before, as in a refresh, is said
    alone not to run.
    """
    taken, left = chosen(arguments, settings, PREPARE)
    unset = [
        source
        for source in taken
        if source.name not in unfetched and source.unlocated(settings) is not None
    ]
    return (
        *(
            f"source {source.name}: will not run, as its fetch will not"
            if source.name in unfetched
            else source_line(source, settings)
            if source.connector.fetcher is None
            else f"source {source.name}: all that its store holds"
            for source in taken
        ),
        *(f"source {name}: left out, {why}" for name, why in left.items()),
        *(
            f"{source.path(source.connector.location)}: not set; any documents of"
            f" {source.name} get no address there"
            for source in unset
        ),
    )
