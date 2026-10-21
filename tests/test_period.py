"""The period of a download: from --since, included, to --until, excluded."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

import pytest

from atlassian_offline_mcp.domain.period import PeriodError, period

NOW = datetime(2026, 10, 22, 9, 30, tzinfo=UTC)


def test_days_and_weeks_count_back_from_now() -> None:
    """--since 7d starts seven days before now, and the period ends now."""
    assert period("7d", None, NOW).start == NOW - timedelta(days=7)
    assert period("2w", None, NOW).start == NOW - timedelta(days=14)
    assert period("7d", None, NOW).end == NOW


def test_an_iso_date_starts_at_midnight_utc() -> None:
    """A date without a time means the start of that day in UTC."""
    assert period("2026-10-15", "2026-10-22", NOW).start == datetime(2026, 10, 15, tzinfo=UTC)


def test_an_iso_time_keeps_its_offset() -> None:
    """A time with an offset is that instant."""
    start = period("2026-10-15T08:00:00+02:00", None, NOW).start
    assert start == datetime(2026, 10, 15, 6, tzinfo=UTC)


def test_the_start_is_in_and_the_end_is_out() -> None:
    """A document updated exactly at the start is in the period; at the end, not."""
    span = period("2026-10-15", "2026-10-22", NOW)
    assert span.start in span
    assert span.end not in span
    assert datetime(2026, 10, 21, 23, 59, tzinfo=timezone(timedelta(hours=-1))) not in span


@pytest.mark.parametrize(
    ("since", "until", "option"),
    [
        ("7days", None, "--since"),
        ("0d", None, "--since"),
        ("2026-10-15", "yesterday", "--until"),
        ("2026-10-22", "2026-10-15", "--until"),
        ("2026-10-22", "2026-10-22", "--until"),
    ],
)
def test_an_unusable_period_is_refused_naming_its_option(
    since: str, until: str | None, option: str
) -> None:
    """Each refusal names the option at fault."""
    with pytest.raises(PeriodError, match=f"^{option}: "):
        period(since, until, NOW)
