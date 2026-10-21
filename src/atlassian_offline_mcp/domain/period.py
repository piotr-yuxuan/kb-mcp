"""The period that a download covers: documents updated from its start until its end."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

# A time before now: a number of days or weeks, such as 7d or 2w.
AGO = re.compile(r"([1-9][0-9]{0,3})([dw])")
DAYS = {"d": 1, "w": 7}


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
    """Read ``7d``, ``2w``, an ISO date (midnight UTC) or an ISO time (UTC unless given)."""
    ago = AGO.fullmatch(text)
    if ago:
        return now - timedelta(days=int(ago[1]) * DAYS[ago[2]])
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        message = f"{option}: a number of days or weeks (7d, 2w), or an ISO date"
        raise PeriodError(message) from None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def period(since: str, until: str | None, now: datetime) -> Period:
    """Read ``--since`` and ``--until``; without ``--until`` the period ends now."""
    end = now if until is None else moment(until, now, "--until")
    return Period(moment(since, now, "--since"), end)
