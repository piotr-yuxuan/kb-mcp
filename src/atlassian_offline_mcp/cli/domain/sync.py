"""What ``sync`` chooses and says, as pure functions of its arguments and settings.

A source is configured when its table names what it covers: a space, a project or a
folder. ``sync`` takes every source configured, ``--include NAME`` those named alone,
``--exclude NAME`` all but those. Confluence and Jira share a step, one download then one
mirror; the work log has its own, which reads no period, so that the period's options it
ignores are said. The exit status ranks how the steps ended.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from atlassian_offline_mcp.kernel.exit_status import ExitStatus
from atlassian_offline_mcp.sources.atlassian.domain.coverage import period_rule

if TYPE_CHECKING:
    import argparse
    from collections.abc import Mapping

    from atlassian_offline_mcp.kernel.content import SourceName

# The steps of a sync, in their order: Confluence's and Jira's together, the work log's.
type Step = Literal["atlassian", "worklog"]
# How a step ended, as its row says.
type Outcome = Literal["done", "failed", "sign in", "interrupted", "not run"]
# The options of a download's period, by their dest, and as typed.
PERIOD = {"since": "--since", "until": "--until", "max_file_mb": "--max-file-mb"}
# The settings that the Atlassian sources share: the site and its sign-in.
SITE_SETTINGS = ("site", "email", "api_token")
# How the run ends, by the first of these outcomes that it had, else OK: interrupted, then
# to sign in again, then failed.
RANKED: tuple[tuple[Outcome, ExitStatus], ...] = (
    ("interrupted", ExitStatus.INTERRUPTED),
    ("sign in", ExitStatus.SIGN_IN_AGAIN),
    ("failed", ExitStatus.FAILED),
)


@dataclass(frozen=True)
class Source:
    """A source as ``sync`` knows it: its name, its step, its table's settings, its options.

    Its first setting names what it covers, which makes it configured; ``options`` are
    the dests of the period's options that it uses.
    """

    name: SourceName
    step: Step
    settings: tuple[str, ...]
    options: tuple[str, ...]


SOURCES = (
    Source("confluence", "atlassian", ("sources.confluence.spaces",), tuple(PERIOD)),
    Source("jira", "atlassian", ("sources.jira.projects",), tuple(PERIOD)),
    Source("worklog", "worklog", ("sources.worklog.path", "sources.worklog.archives"), ()),
)


def chosen(
    arguments: argparse.Namespace, settings: Mapping[str, object]
) -> tuple[tuple[Source, ...], dict[SourceName, str]]:
    """Return the sources that a run takes, in their order, and why each other is left out."""
    included = set(arguments.include or ())
    excluded = set(arguments.exclude or ())
    taken: list[Source] = []
    left: dict[SourceName, str] = {}
    for source in SOURCES:
        if included and source.name not in included:
            left[source.name] = "not included"
        elif source.name in excluded:
            left[source.name] = "excluded"
        elif not settings[source.settings[0]]:
            left[source.name] = "not configured"
        else:
            taken.append(source)
    return tuple(taken), left


def described(arguments: argparse.Namespace, settings: Mapping[str, object]) -> tuple[str, ...]:
    """Say each source taken, with its settings, each left out and why, and the options ignored.

    With Confluence or Jira taken, the rule of where their windows start follows the
    sources. An option of the period given is ignored by each source taken that does not
    use it.
    """
    taken, left = chosen(arguments, settings)
    values = {
        setting: ", ".join(value) if isinstance(value, tuple) else str(value)
        for setting, value in settings.items()
    }
    lines: list[str] = []
    for source in taken:
        shown = (f"{setting.rpartition('.')[2]} {values[setting]}" for setting in source.settings)
        lines.append(f"source {source.name}: {', '.join(shown)}")
    lines += [f"source {name}: left out, {why}" for name, why in left.items()]
    if any(source.step == "atlassian" for source in taken):
        lines.append(period_rule(since=arguments.since is not None))
    for dest, option in PERIOD.items():
        ignoring = [source.name for source in taken if dest not in source.options]
        if getattr(arguments, dest) is not None and ignoring:
            lines.append(f"{option}: ignored by {', '.join(ignoring)}")
    return tuple(lines)
