"""The period of a download: from --since, included, to --until, excluded, as plan 034 says."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

import pytest

from kb_mcp.sources.atlassian.domain.period import PeriodError, period

NOW = datetime(2026, 10, 22, 9, 30, tzinfo=UTC)
# The moment of plan 034's examples.
EXAMPLE = datetime(2026, 10, 28, 12, tzinfo=UTC)


@pytest.mark.parametrize(
    ("since", "start"),
    [
        ("12h", datetime(2026, 10, 28, tzinfo=UTC)),
        ("7d", datetime(2026, 10, 21, 12, tzinfo=UTC)),
        ("2w", EXAMPLE - timedelta(days=14)),
        ("6mo", EXAMPLE - timedelta(days=180)),
        ("1y", EXAMPLE - timedelta(days=365)),
        ("2026-10-20", datetime(2026, 10, 20, tzinfo=UTC)),
        ("2026-10-20T09:00+02:00", datetime(2026, 10, 20, 7, tzinfo=UTC)),
        ("all", datetime(2000, 1, 1, tzinfo=UTC)),
    ],
)
def test_since_reads_a_length_before_now_a_date_a_time_or_all(since: str, start: datetime) -> None:
    """Hours, days, weeks, months of 30 days, years of 365; a date, a time; all, from 2000."""
    assert period(since, None, EXAMPLE).start == start


def test_until_reads_a_length_before_now_too_and_the_period_ends_now_without_it() -> None:
    """--until 12h ends twelve hours before now; no --until, now."""
    assert period("7d", "12h", EXAMPLE).end == datetime(2026, 10, 28, tzinfo=UTC)
    assert period("7d", None, EXAMPLE).end == EXAMPLE


def test_an_iso_date_starts_at_midnight_utc() -> None:
    """A date without a time means the start of that day in UTC."""
    assert period("2026-10-15", "2026-10-22", NOW).start == datetime(2026, 10, 15, tzinfo=UTC)


def test_an_iso_time_is_read_as_its_instant_in_utc() -> None:
    """A time with an offset is that instant, given in UTC for the dates searched."""
    start = period("2026-10-15T08:00:00+02:00", None, NOW).start
    assert start == datetime(2026, 10, 15, 6, tzinfo=UTC)
    assert start.utcoffset() == timedelta(0)


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
        ("7m", None, "--since"),
        ("0d", None, "--since"),
        ("0h", None, "--since"),
        ("0mo", None, "--since"),
        ("-1d", None, "--since"),
        ("9999y", None, "--since"),
        ("forever", None, "--since"),
        ("2026-10-15", "all", "--until"),
        ("0001-01-01T00:00:00+05:00", None, "--since"),
        ("2026-10-15", "9999-12-31T23:59:59-05:00", "--until"),
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
