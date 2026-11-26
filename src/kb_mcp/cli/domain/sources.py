"""What ``fetch`` and ``prepare`` choose and say, as pure functions of arguments and settings."""

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

    Made absolute as of the run's ``start`` where its declaration says how; else as given,
    None when not given. No source's options are read unless it is taken.
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
    """Give why each of ``sources`` that its light check refuses cannot run, by its name."""
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

    Then the lines that each source that runs says by its connector, each once, then each
    option given that a source taken does not declare, but one that replaces a setting of
    a source named, which ``unapplied`` says. ``refused``, when the caller asked it
    already, names the sources taken that their light check refuses.
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

    A source without its location still runs, its documents without an address there; one
    ``unfetched``, whose fetch will not run before, is said alone not to run.
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
