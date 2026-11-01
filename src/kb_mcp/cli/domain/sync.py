"""What ``sync`` chooses and says, as pure functions of its arguments and settings.

The sources are the registry's, which the arguments hold (``sources``). A source is
configured when its first setting, which names what it covers, is set. ``sync`` takes
every source configured, ``--include NAME`` those named alone, ``--exclude NAME`` all
but those. Each source taken says what the summary says of it, by its declaration; an
option given is said ignored by each source taken that does not declare it. A row names
its step and its source; the exit status ranks how the rows ended.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from kb_mcp.kernel.exit_status import ExitStatus

if TYPE_CHECKING:
    import argparse
    from collections.abc import Iterable, Mapping

    from kb_mcp.sources.declaration import Declared

# How a step ended, as its row says.
type Outcome = Literal["done", "failed", "sign in", "interrupted", "not run"]
# How the run ends, by the first of these outcomes that it had, else OK: interrupted, then
# to sign in again, then failed.
RANKED: tuple[tuple[Outcome, ExitStatus], ...] = (
    ("interrupted", ExitStatus.INTERRUPTED),
    ("sign in", ExitStatus.SIGN_IN_AGAIN),
    ("failed", ExitStatus.FAILED),
)


def label(step: str, source: str | None) -> str:
    """Name a row: its step, then its source, unless it has none."""
    return step if source is None else f"{step} {source}"


def given(arguments: argparse.Namespace, flags: Iterable[str]) -> dict[str, object]:
    """Give the value of each option by its flag, None when not given, unless a default.

    argparse keeps an option's value under its flag, its dashes before dropped and
    within made underscores.
    """
    return {flag: getattr(arguments, flag.lstrip("-").replace("-", "_")) for flag in flags}


def chosen(
    arguments: argparse.Namespace, settings: Mapping[str, object]
) -> tuple[tuple[Declared, ...], dict[str, str]]:
    """Return the sources that a run takes, in their order, and why each other is left out."""
    included = set(arguments.include or ())
    excluded = set(arguments.exclude or ())
    taken: list[Declared] = []
    left: dict[str, str] = {}
    for declared in arguments.sources:
        if included and declared.name not in included:
            left[declared.name] = "not included"
        elif declared.name in excluded:
            left[declared.name] = "excluded"
        elif not settings[declared.paths[0]]:
            left[declared.name] = "not configured"
        else:
            taken.append(declared)
    return tuple(taken), left


def described(arguments: argparse.Namespace, settings: Mapping[str, object]) -> tuple[str, ...]:
    """Say each source taken, with its settings, each left out and why, and the options ignored.

    The lines that a source taken says follow, each once, as its declaration's
    ``described`` gives them. An option given is ignored by each source taken that does
    not declare it.
    """
    taken, left = chosen(arguments, settings)
    values = {
        setting: ", ".join(value) if isinstance(value, tuple) else str(value)
        for setting, value in settings.items()
    }
    lines: list[str] = []
    said: list[str] = []
    for declared in taken:
        shown = (f"{path.rpartition('.')[2]} {values[path]}" for path in declared.paths)
        lines.append(f"source {declared.name}: {', '.join(shown)}")
        options = given(arguments, declared.options)
        said += declared.described(options, settings) if declared.described else ()
    lines += [f"source {name}: left out, {why}" for name, why in left.items()]
    lines += said
    flags = dict.fromkeys(flag for declared in arguments.sources for flag in declared.options)
    for flag, value in given(arguments, flags).items():
        ignoring = [declared.name for declared in taken if flag not in declared.options]
        if value is not None and ignoring:
            lines.append(f"{flag}: ignored by {', '.join(ignoring)}")
    return tuple(dict.fromkeys(lines))
