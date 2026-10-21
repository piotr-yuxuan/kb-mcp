"""The window each run fetches, and how the covered period grows, as the plan rules."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from atlassian_offline_mcp.domain.coverage import Coverage, Target, window
from atlassian_offline_mcp.domain.period import EPOCH, Period, PeriodError, length

NOW = datetime(2026, 11, 1, 9, tzinfo=UTC)
COVERED = datetime(2026, 10, 15, 9, tzinfo=UTC)
SPACE = Target("confluence", "ENG")
PROJECT = Target("jira", "PLAT")
SIX_MONTHS = timedelta(days=180)


def covered() -> Coverage:
    """Return coverage of the space from mid-October to now."""
    return Coverage({SPACE: Period(COVERED, NOW)})


def test_a_run_without_since_catches_up_on_the_covered_period() -> None:
    """No --since: from the covered start to now, the end pinned too."""
    assert window(covered(), SPACE, None, None, NOW) == Period(COVERED, NOW)


def test_a_run_with_since_starts_there() -> None:
    """--since wins over the coverage."""
    since = datetime(2026, 10, 25, tzinfo=UTC)
    assert window(covered(), SPACE, since, None, NOW) == Period(since, NOW)


def test_since_and_back_together_reach_back_from_since() -> None:
    """--back reaches back from --since when both are given."""
    since = datetime(2026, 10, 25, tzinfo=UTC)
    assert window(covered(), SPACE, since, SIX_MONTHS, NOW).start == since - SIX_MONTHS


def test_back_reaches_before_the_covered_start_and_then_before_that() -> None:
    """--back 6mo, twice, covers twelve months before the first start."""
    first = window(covered(), SPACE, None, length("6mo", "--back"), NOW)
    assert first == Period(COVERED - SIX_MONTHS, NOW)
    after = covered().extended(SPACE, first)
    assert after.periods[SPACE] == Period(COVERED - SIX_MONTHS, NOW)
    second = window(after, SPACE, None, length("6mo", "--back"), NOW)
    assert second.start == COVERED - 2 * SIX_MONTHS


def test_back_all_reaches_everything() -> None:
    """--back all starts at the epoch, before any content of Atlassian Cloud."""
    assert window(covered(), SPACE, None, length("all", "--back"), NOW).start == EPOCH


def test_a_target_never_covered_needs_since() -> None:
    """A first run must say where to start; the refusal names the target."""
    with pytest.raises(PeriodError, match=r"^project PLAT: nothing covered yet"):
        window(covered(), PROJECT, None, None, NOW)


def test_a_first_run_covers_its_period() -> None:
    """--since 7d on a new target covers the last seven days."""
    fetched = Period(NOW - timedelta(days=7), NOW)
    assert Coverage().extended(PROJECT, fetched).periods == {PROJECT: fetched}


def test_a_run_apart_from_the_covered_period_leaves_it() -> None:
    """A period that does not touch the covered one would claim the gap; it is not joined."""
    fetched = Period(datetime(2026, 1, 1, tzinfo=UTC), datetime(2026, 6, 1, tzinfo=UTC))
    assert covered().extended(SPACE, fetched) == covered()


def test_a_later_short_run_does_not_claim_the_days_between() -> None:
    """Covered to 8 October, then --since 3d on the 21st: the 8th to the 18th were not seen."""
    early = Coverage(
        {SPACE: Period(datetime(2026, 10, 1, tzinfo=UTC), datetime(2026, 10, 8, tzinfo=UTC))}
    )
    late = Period(datetime(2026, 10, 18, tzinfo=UTC), datetime(2026, 10, 21, tzinfo=UTC))
    assert early.extended(SPACE, late) == early


def test_a_run_that_reaches_the_covered_start_joins_it() -> None:
    """A period ending at the covered start makes one period with it."""
    fetched = Period(datetime(2026, 6, 1, tzinfo=UTC), COVERED)
    assert covered().extended(SPACE, fetched).periods[SPACE] == Period(fetched.start, NOW)


def test_a_run_inside_the_covered_period_keeps_it() -> None:
    """A catch-up never moves the covered start forward, nor the end back."""
    fetched = Period(COVERED + timedelta(days=3), NOW - timedelta(days=1))
    assert covered().extended(SPACE, fetched) == covered()


@pytest.mark.parametrize("text", ["6m", "0mo", "forever", "-1d", "9999y"])
def test_a_length_that_is_not_one_is_refused(text: str) -> None:
    """Days, weeks, months, years, or all; nothing else."""
    with pytest.raises(PeriodError, match=r"^--back: "):
        length(text, "--back")
