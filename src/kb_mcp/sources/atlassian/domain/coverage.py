"""The period covered for each target, and the window that each run fetches.

A target (a space or a project) is covered over one period: every document updated in
it is stored. Without --since, a run fetches what changed since each target's last fetch:
a project from its covered end, a space from its covered start, since its listing is read
whole anyway; a target never covered, its last week.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
from typing import TYPE_CHECKING, Literal

from kb_mcp.kernel.names import PROJECT_KEY, SPACE_KEY, RefusedError, require
from kb_mcp.sources.atlassian.domain.period import EPOCH, FIRST_FETCH, Period

# The rule of a target's key, by source.
KEYS = {"confluence": SPACE_KEY, "jira": PROJECT_KEY}
# What a run made of a target's coverage: grown to its window's end, ended at a failure,
# or left as it was.
type Extension = Literal["extended", "capped", "held"]
# Why a window starts where it does: at --since, a day before an exact covered end, at the
# covered start (a space, or a project's entry from before plan 034), or a week back.
type Reason = Literal["given", "since the last fetch", "covered start", "first fetch"]
# How far before its covered end a project's catch-up starts: a search index can lag
# behind an edit, the window ends at this machine's clock while issues carry the site's,
# and an issue saved while its search pages through moves in it. A day survives a laptop's
# clock off after sleep; it costs no request, since the search reads whole days.
CATCH_UP_MARGIN = timedelta(days=1)

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
        period would then be empty, inexact if it starts at the failure, so that the next
        run searches it whole. Any other run over an inexact entry joins it, as a space's
        does, and leaves it inexact.
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
            inside = covered is not None and covered.start <= failed
            return Coverage(self.periods, self.exact - {target} if inside else self.exact), "capped"
        return Coverage({**self.periods, target: Period(start, failed)}, marked), "capped"


@dataclass(frozen=True)
class Window:
    """The period that a run fetches for a target, and why it starts where it does."""

    period: Period
    reason: Reason


def window(
    coverage: Coverage, target: Target, since: datetime | None, end: datetime
) -> Window | None:
    """Return the window a run fetches for a target, to ``end``; None to skip the target.

    It starts at ``since`` when given, and raises PeriodError when that is not before
    ``end``. Otherwise an exact project catches up from ``CATCH_UP_MARGIN`` before its
    covered end, another target covered from its covered start, and one never covered
    starts ``FIRST_FETCH`` before ``end``; a catch-up that would start at or after
    ``end``, an ``--until`` before it, skips the target. Nothing starts before the epoch:
    nothing on the site is older, and dates stay in range.
    """
    if since is not None:
        return Window(Period(max(since, EPOCH), end), "given")
    covered = coverage.periods.get(target)
    start: datetime
    reason: Reason
    if covered is None:
        start, reason = end - FIRST_FETCH, "first fetch"
    elif target in coverage.exact:
        start, reason = covered.end - CATCH_UP_MARGIN, "since the last fetch"
    else:
        start, reason = covered.start, "covered start"
    start = max(start, EPOCH)
    if start >= end:
        return None
    return Window(Period(start, end), reason)


__all__ = ["EPOCH", "Coverage", "Extension", "Target", "Window", "window"]
