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
    """Return coverage of the space from mid-October."""
    return Coverage({SPACE: COVERED})


def test_a_run_without_since_catches_up_on_the_covered_period() -> None:
    """No --since: from the covered start to now."""
    assert window(covered(), SPACE, None, None, NOW) == Period(COVERED, NOW)


def test_a_run_with_since_starts_there() -> None:
    """--since wins over the coverage."""
    since = datetime(2026, 10, 25, tzinfo=UTC)
    assert window(covered(), SPACE, since, None, NOW) == Period(since, NOW)


def test_back_reaches_before_the_covered_start_and_then_before_that() -> None:
    """--back 6mo, twice, covers twelve months before the first start."""
    first = window(covered(), SPACE, None, length("6mo", "--back"), NOW)
    assert first == Period(COVERED - SIX_MONTHS, NOW)
    after = covered().extended(SPACE, first, NOW)
    second = window(after, SPACE, None, length("6mo", "--back"), NOW)
    assert second.start == COVERED - 2 * SIX_MONTHS


def test_back_all_reaches_everything() -> None:
    """--back all starts at the epoch, before any content of Atlassian Cloud."""
    assert window(covered(), SPACE, None, length("all", "--back"), NOW).start == EPOCH


def test_a_target_never_covered_needs_since() -> None:
    """A first run must say where to start; the refusal names the target."""
    with pytest.raises(PeriodError, match=r"^project PLAT: nothing covered yet"):
        window(covered(), PROJECT, None, None, NOW)


def test_a_first_run_ending_now_starts_the_coverage() -> None:
    """--since 7d on a new target covers the last seven days."""
    fetched = Period(NOW - timedelta(days=7), NOW)
    assert Coverage().extended(PROJECT, fetched, NOW).starts == {PROJECT: fetched.start}


def test_a_run_that_ends_before_the_covered_start_leaves_the_coverage() -> None:
    """A period that does not join the covered one would leave a gap; it is not counted."""
    fetched = Period(datetime(2026, 1, 1, tzinfo=UTC), datetime(2026, 6, 1, tzinfo=UTC))
    assert covered().extended(SPACE, fetched, NOW) == covered()


def test_a_run_that_reaches_the_covered_start_joins_it() -> None:
    """A period ending at or after the covered start makes one period with it."""
    fetched = Period(datetime(2026, 6, 1, tzinfo=UTC), COVERED)
    assert covered().extended(SPACE, fetched, NOW).starts[SPACE] == fetched.start


def test_a_run_inside_the_covered_period_keeps_its_start() -> None:
    """A catch-up never moves the covered start forward."""
    fetched = Period(COVERED + timedelta(days=3), NOW)
    assert covered().extended(SPACE, fetched, NOW).starts[SPACE] == COVERED


@pytest.mark.parametrize("text", ["6m", "0mo", "forever", "-1d"])
def test_a_length_that_is_not_one_is_refused(text: str) -> None:
    """Days, weeks, months, years, or all; nothing else."""
    with pytest.raises(PeriodError, match=r"^--back: "):
        length(text, "--back")
