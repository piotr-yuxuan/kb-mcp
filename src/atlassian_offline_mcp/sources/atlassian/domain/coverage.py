"""The period covered for each target, and the window that each run fetches.

A target (a space or a project) is covered over one period: every document updated in
it is stored. A run catches up from the covered start to now, unless --since starts it
elsewhere.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

from atlassian_offline_mcp.kernel.content import PROJECT_KEY, SPACE_KEY, RefusedError, require
from atlassian_offline_mcp.sources.atlassian.domain.period import EPOCH, Period, PeriodError

# The rule of a target's key, by source.
KEYS = {"confluence": SPACE_KEY, "jira": PROJECT_KEY}
# What a run made of a target's coverage: grown to its window's end, ended at a failure,
# or left as it was.
type Extension = Literal["extended", "capped", "held"]

if TYPE_CHECKING:
    from collections.abc import Mapping
    from datetime import datetime


@dataclass(frozen=True, order=True)
class Target:
    """A space of Confluence or a project of Jira, by its key."""

    source: str  # confluence or jira
    key: str

    def __post_init__(self) -> None:
        """Refuse a source that is neither, and a key that does not look like its kind's."""
        if self.source not in KEYS:
            message = "source: neither confluence nor jira"
            raise RefusedError(message)
        require(KEYS[self.source], self.key, "key")

    def __str__(self) -> str:
        """Name the target as the user does: ``space ENG``, ``project PLAT``."""
        return f"{'space' if self.source == 'confluence' else 'project'} {self.key}"

    @property
    def searched_by_time(self) -> bool:
        """Say whether its documents are found by their update time: a project's are.

        A space is listed whole.
        """
        return self.source == "jira"


@dataclass(frozen=True)
class Coverage:
    """Each target's covered period: every document updated in it is stored.

    A space is listed whole on every run, so a failure within its period (a document
    whose fetch failed, an entry the adapter refuses) leaves no hole for long: a run
    without --since starts at its covered start, and asks for the whole period again. A
    project is searched by update time: its period ends at its first failure, so that a
    search from its end asks for that again. Such an entry is ``exact``; one written
    before plan 034 is not, and its end may hide a failure.
    """

    periods: Mapping[Target, Period] = field(default_factory=dict)
    exact: frozenset[Target] = frozenset()

    def extended(
        self, target: Target, fetched: Period, failed: datetime | None = None
    ) -> tuple[Coverage, Extension]:
        """Return the coverage once a run listed or searched ``fetched`` whole for the target.

        ``failed`` is the update time of the earliest document found and not stored whole.
        The covered period stays one period: a run apart from it leaves it as it was,
        ``held``, since joining would claim the gap between them; one that overlaps or
        touches it joins it, ``extended``. A project's period is exact once a run has seen
        it whole: a first run, a run over an exact entry, or one that starts at or before
        an inexact entry, which it replaces; there a failure ends the period at
        ``failed``, even below the old end, ``capped``, or leaves it as it was when the
        period would then be empty. Any other run over an inexact entry joins it, as a
        space's does, and leaves it inexact.
        """
        covered = self.periods.get(target)
        exact = target.searched_by_time and (
            covered is None or target in self.exact or fetched.start <= covered.start
        )
        marked = self.exact | {target} if exact else self.exact
        if covered is not None and (fetched.start > covered.end or fetched.end < covered.start):
            return self, "held"
        if covered is None or (exact and target not in self.exact):
            start, end = fetched.start, fetched.end
        else:
            start, end = min(covered.start, fetched.start), max(covered.end, fetched.end)
        if not exact or failed is None:
            return Coverage({**self.periods, target: Period(start, end)}, marked), "extended"
        if failed <= start:
            return self, "capped"
        return Coverage({**self.periods, target: Period(start, failed)}, marked), "capped"


def window(coverage: Coverage, target: Target, since: datetime | None, end: datetime) -> Period:
    """Return the period a run fetches for a target, to ``end``.

    It starts at ``since`` when given, otherwise at the covered start (catch-up).
    """
    covered = coverage.periods.get(target)
    start = since if since is not None else (covered.start if covered else None)
    if start is None:
        message = f"{target}: nothing covered yet; give --since for its first run"
        raise PeriodError(message)
    # Nothing on the site is older, and dates stay in range.
    return Period(max(start, EPOCH), end)


__all__ = ["EPOCH", "Coverage", "Extension", "Target", "window"]
