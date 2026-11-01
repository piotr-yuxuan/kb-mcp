"""What ``fetch`` and ``prepare`` choose and say, as pure functions of arguments and settings.

The sources are the registry's, which the arguments hold (``sources``), and those named
among them (``source``). A source is configured when its first setting, which names what
it covers, is set. ``fetch`` takes every source that has a fetcher and is configured, or
those named. ``prepare`` takes every source that keeps a store, which its fetcher says,
whatever the store holds, and each read in place when it is configured, or those named.
Each is taken once, in the registry's order, whatever the order typed. A source's options
and light checks are its fetch's: each source taken says what the summary says of it, by
its declaration; an option that no setting holds, given, is said ignored by each source
taken that does not declare it. The exit status ranks how the rows ended.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from kb_mcp.kernel.exit_status import ExitStatus

if TYPE_CHECKING:
    import argparse
    from collections.abc import Iterable, Mapping

    from kb_mcp.sources.declaration import Declared

# The commands over sources, whose names a run reads.
FETCH, PREPARE = "fetch", "prepare"
# How a row ended, as it says.
type Outcome = Literal["done", "failed", "sign in", "interrupted", "not run"]
# How the run ends, by the first of these outcomes that it had, else OK: interrupted, then
# to sign in again, then failed.
RANKED: tuple[tuple[Outcome, ExitStatus], ...] = (
    ("interrupted", ExitStatus.INTERRUPTED),
    ("sign in", ExitStatus.SIGN_IN_AGAIN),
    ("failed", ExitStatus.FAILED),
)


def given(arguments: argparse.Namespace, flags: Iterable[str]) -> dict[str, object]:
    """Give the value of each option by its flag, None when not given.

    ``add_source_options`` keeps an option's value under its flag itself.
    """
    return {flag: getattr(arguments, flag) for flag in flags}


def chosen(
    arguments: argparse.Namespace, settings: Mapping[str, object]
) -> tuple[tuple[Declared, ...], dict[str, str]]:
    """Return the sources that a run takes, in their order, and why each other is left out."""
    fetching = arguments.command.name == FETCH
    named = set(arguments.source)
    taken: list[Declared] = []
    left: dict[str, str] = {}
    for declared in arguments.sources:
        in_place = declared.fetcher is None
        if fetching and in_place:
            left[declared.name] = "read in place, it has nothing to fetch"
        elif named and declared.name not in named:
            left[declared.name] = "not named"
        elif (fetching or in_place) and not settings[declared.paths[0]]:
            left[declared.name] = "not configured"
        else:
            taken.append(declared)
    return tuple(taken), left


def described(arguments: argparse.Namespace, settings: Mapping[str, object]) -> tuple[str, ...]:
    """Say each source taken, with its settings, each left out and why, and the options ignored.

    A source that keeps a store, in a prepare, is said to give what it holds. In a fetch,
    the lines that a source taken says follow, each once, as its declaration's
    ``described`` gives them. An option that no setting holds, given, is ignored by each
    source taken that does not declare it; one that replaces a setting is said by
    ``unapplied``, as for any setting.
    """
    fetching = arguments.command.name == FETCH
    taken, left = chosen(arguments, settings)
    values = {
        setting: ", ".join(value) if isinstance(value, tuple) else str(value)
        for setting, value in settings.items()
    }
    lines: list[str] = []
    said: list[str] = []
    for declared in taken:
        if fetching or declared.fetcher is None:
            shown = (f"{path.rpartition('.')[2]} {values[path]}" for path in declared.paths)
            lines.append(f"source {declared.name}: {', '.join(shown)}")
        else:
            lines.append(f"source {declared.name}: all that its store holds")
        if fetching and declared.described:
            said += declared.described(given(arguments, declared.options), settings)
    lines += [f"source {name}: left out, {why}" for name, why in left.items()]
    lines += said
    if not fetching:
        return tuple(dict.fromkeys(lines))
    flags = {
        flag
        for declared in arguments.sources
        for flag, option in declared.options.items()
        if option.setting is None
    }
    for flag, value in sorted(given(arguments, flags).items()):
        ignoring = [declared.name for declared in taken if flag not in declared.options]
        if value is not None and ignoring:
            lines.append(f"{flag}: ignored by {', '.join(ignoring)}")
    return tuple(dict.fromkeys(lines))
