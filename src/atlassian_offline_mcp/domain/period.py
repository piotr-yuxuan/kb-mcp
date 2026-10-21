"""The period that a download covers: documents updated from its start until its end."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal

# A length of time: a number of days, weeks, months or years, such as 7d, 2w, 6mo or 1y.
# A month counts 30 days and a year 365: windows need no calendar.
AGO = re.compile(r"([1-9][0-9]{0,3})(d|w|mo|y)")
DAYS = {"d": 1, "w": 7, "mo": 30, "y": 365}
# Before any content of Atlassian Cloud: the start of a window back to everything.
EPOCH = datetime(2000, 1, 1, tzinfo=UTC)
# The longest length of time read: a hundred years, far past the epoch, never past the
# calendar.
MAX_DAYS = 100 * 365


class PeriodError(ValueError):
    """A period that cannot be used; the message names the option at fault."""


@dataclass(frozen=True)
class Period:
    """From ``start``, included, to ``end``, excluded; both aware of their offset."""

    start: datetime
    end: datetime

    def __post_init__(self) -> None:
        """Refuse a period that ends before it starts."""
        if not self.start < self.end:
            message = "--until: must come after --since"
            raise PeriodError(message)

    def __contains__(self, moment: datetime) -> bool:
        """Say whether a moment falls in the period."""
        return self.start <= moment < self.end


def length(text: str, option: str) -> timedelta | Literal["all"]:
    """Read a length of time (``7d``, ``2w``, ``6mo``, ``1y``), or ``all`` of it."""
    if text == "all":
        return "all"
    ago = AGO.fullmatch(text)
    if not ago or int(ago[1]) * DAYS[ago[2]] > MAX_DAYS:
        message = f"{option}: a number of days, weeks, months or years (7d, 2w, 6mo, 1y), or all"
        raise PeriodError(message)
    return timedelta(days=int(ago[1]) * DAYS[ago[2]])


def moment(text: str, now: datetime, option: str) -> datetime:
    """Read ``7d``, ``6mo`` and the like before now, or an ISO date (midnight UTC) or time."""
    ago = AGO.fullmatch(text)
    if ago and int(ago[1]) * DAYS[ago[2]] <= MAX_DAYS:
        return now - timedelta(days=int(ago[1]) * DAYS[ago[2]])
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        message = f"{option}: a length before now (7d, 2w, 6mo, 1y), or an ISO date"
        raise PeriodError(message) from None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def period(since: str, until: str | None, now: datetime) -> Period:
    """Read ``--since`` and ``--until``; without ``--until`` the period ends now."""
    end = now if until is None else moment(until, now, "--until")
    return Period(moment(since, now, "--since"), end)
