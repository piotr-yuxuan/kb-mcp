"""The period that a download covers: documents updated from its start until its end."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

# A length of time: a number of hours, days, weeks, months or years, such as 12h, 7d, 2w,
# 6mo or 1y. A month counts 30 days and a year 365: windows need no calendar.
AGO = re.compile(r"([1-9][0-9]{0,3})(h|d|w|mo|y)")
UNITS = {
    "h": timedelta(hours=1),
    "d": timedelta(days=1),
    "w": timedelta(days=7),
    "mo": timedelta(days=30),
    "y": timedelta(days=365),
}
# Before any content of Atlassian Cloud: the start of a window back to everything, which
# --since all names.
EPOCH = datetime(2000, 1, 1, tzinfo=UTC)
# The longest length of time read: a hundred years, far past the epoch, never past the
# calendar.
LONGEST = timedelta(days=100 * 365)
# How far back a target never covered starts without --since.
FIRST_FETCH = timedelta(days=7)
# The largest file that a download keeps when no --max-file-mb says, in MB: an option of
# the period, as the commands add it.
DEFAULT_MAX_FILE_MB = 50


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


def moment(text: str, now: datetime, option: str) -> datetime:
    """Read ``12h``, ``7d``, ``6mo`` and the like before now, or an ISO date (midnight UTC) or time.

    ``all``, for ``--since`` alone, is the epoch: everything. A time is given in UTC,
    whatever offset it carries, so that the dates searched hold it in every time zone.
    """
    if option == "--since" and text == "all":
        return EPOCH
    ago = AGO.fullmatch(text)
    if ago and int(ago[1]) * UNITS[ago[2]] <= LONGEST:
        return now - int(ago[1]) * UNITS[ago[2]]
    try:
        parsed = datetime.fromisoformat(text)
        # A time at the calendar's edge, once in UTC, can fall out of it.
        return (parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)).astimezone(UTC)
    except ValueError, OverflowError:
        everything = ", or all" if option == "--since" else ""
        message = (
            f"{option}: a length before now (12h, 7d, 2w, 6mo, 1y), an ISO date or time{everything}"
        )
        raise PeriodError(message) from None


def period(since: str, until: str | None, now: datetime) -> Period:
    """Read ``--since`` and ``--until``; without ``--until`` the period ends now."""
    end = now if until is None else moment(until, now, "--until")
    return Period(moment(since, now, "--since"), end)


def period_rule(*, since: bool) -> str:
    """Say in words where a run's windows start, with --since given or not.

    Said before a run, which reads no store yet: the rule, not each target's window.
    """
    if since:
        return "period: from --since"
    return (
        "period: since each target's last fetch;"
        f" the last {FIRST_FETCH.days} days for one never fetched"
    )
