"""The period covered for each target, and the window that each run fetches.

A target (a space or a project) is covered from a start up to the end of the last run
that fetched it whole: every document updated in that period is stored. A run catches
up on the covered period, and may reach further back.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

from atlassian_offline_mcp.domain.content import PROJECT_KEY, SPACE_KEY, RefusedError, require
from atlassian_offline_mcp.domain.period import EPOCH, Period, PeriodError

# The rule of a target's key, by source.
KEYS = {"confluence": SPACE_KEY, "jira": PROJECT_KEY}

if TYPE_CHECKING:
    from collections.abc import Mapping
    from datetime import datetime, timedelta


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


@dataclass(frozen=True)
class Coverage:
    """The start of each target's covered period."""

    starts: Mapping[Target, datetime] = field(default_factory=dict)

    def extended(self, target: Target, fetched: Period, now: datetime) -> Coverage:
        """Return the coverage once a run fetched ``fetched`` whole for the target.

        The covered period stays one period: a run that ends now, or that reaches the
        covered start, moves the start to the earlier of the two; another run leaves it.
        """
        start = self.starts.get(target)
        joins = fetched.end >= now if start is None else fetched.end >= start
        if not joins:
            return self
        earliest = fetched.start if start is None else min(start, fetched.start)
        return Coverage({**self.starts, target: earliest})


def window(
    coverage: Coverage,
    target: Target,
    since: datetime | None,
    back: timedelta | Literal["all"] | None,
    end: datetime,
) -> Period:
    """Return the period a run fetches for a target, to ``end``.

    It starts at ``since`` when given, otherwise at the covered start (catch-up); ``back``
    reaches that much further back, or to ``EPOCH`` for ``all``.
    """
    start = since if since is not None else coverage.starts.get(target)
    if start is None:
        message = f"{target}: nothing covered yet; give --since for its first run"
        raise PeriodError(message)
    if back == "all":
        start = EPOCH
    elif back is not None:
        start = max(EPOCH, start - back)
    return Period(start, end)


__all__ = ["EPOCH", "Coverage", "Target", "window"]
