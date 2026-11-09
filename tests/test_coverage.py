"""The window each run fetches, and how the covered period grows, as the plan rules."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest

from kb_mcp.sources.atlassian.fetch.domain.coverage import (
    Coverage,
    FetchWindow,
    Target,
    fetch_window,
)
from kb_mcp.sources.atlassian.fetch.domain.period import Period, PeriodError

if TYPE_CHECKING:
    from collections.abc import Callable

NOW = datetime(2026, 11, 1, 9, tzinfo=UTC)
COVERED = datetime(2026, 10, 15, 9, tzinfo=UTC)
SPACE = Target(source="confluence", key="ENG")
PROJECT = Target(source="jira", key="PLAT")


def covered() -> Coverage:
    """Return coverage of the space from mid-October to now."""
    return Coverage(periods={SPACE: Period(COVERED, NOW)})


def test_a_space_without_since_catches_up_on_its_covered_period() -> None:
    """No --since: from the covered start to now, the end pinned too; its listing is whole."""
    assert fetch_window(covered(), SPACE, None, NOW) == FetchWindow(
        period=Period(COVERED, NOW), reason="covered start"
    )


def test_a_run_with_since_starts_there() -> None:
    """--since wins over the coverage."""
    since = datetime(2026, 10, 25, tzinfo=UTC)
    assert fetch_window(covered(), SPACE, since, NOW) == FetchWindow(
        period=Period(since, NOW), reason="given"
    )
    assert fetch_window(covered(), PROJECT, since, NOW) == FetchWindow(
        period=Period(since, NOW), reason="given"
    )


def test_a_since_that_does_not_come_before_the_end_is_refused() -> None:
    """An --until before --since, or at it, is refused, naming them."""
    with pytest.raises(PeriodError, match=r"^--until: must come after --since"):
        fetch_window(covered(), SPACE, NOW, NOW)


def test_a_target_never_covered_fetches_its_last_week() -> None:
    """Rather than refusing the run: seven days before the window's end, said first fetch."""
    assert fetch_window(covered(), PROJECT, None, NOW) == FetchWindow(
        period=Period(NOW - timedelta(days=7), NOW), reason="first fetch"
    )


def test_an_exact_project_catches_up_from_a_day_before_its_covered_end() -> None:
    """Covered exactly to 27 October 09:00, a run on the 28th at noon: from the 26th 09:00."""
    end = datetime(2026, 10, 27, 9, tzinfo=UTC)
    run = datetime(2026, 10, 28, 12, tzinfo=UTC)
    exact = Coverage(periods={PROJECT: Period(COVERED, end)}, exact=frozenset({PROJECT}))
    assert fetch_window(exact, PROJECT, None, run) == FetchWindow(
        period=Period(datetime(2026, 10, 26, 9, tzinfo=UTC), run), reason="since the last fetch"
    )


def test_a_project_recorded_before_034_catches_up_from_its_covered_start() -> None:
    """Its end may hide a failure: the whole period is searched again, once."""
    old = Coverage(periods={PROJECT: Period(COVERED, NOW - timedelta(days=1))})
    assert fetch_window(old, PROJECT, None, NOW) == FetchWindow(
        period=Period(COVERED, NOW), reason="covered start"
    )


def test_a_catch_up_that_would_start_at_or_after_the_end_skips_the_target() -> None:
    """An --until before the catch-up's start: no window, rather than a refused run."""
    exact = Coverage(periods={PROJECT: Period(COVERED, NOW)}, exact=frozenset({PROJECT}))
    until = NOW - timedelta(days=1)
    assert fetch_window(exact, PROJECT, None, until) is None
    assert fetch_window(covered(), SPACE, None, COVERED) is None


def test_a_first_run_covers_its_period() -> None:
    """--since 7d on a new target covers the last seven days; a project's, exactly."""
    fetched = Period(NOW - timedelta(days=7), NOW)
    exact = Coverage(periods={PROJECT: fetched}, exact=frozenset({PROJECT}))
    assert Coverage().extended(PROJECT, fetched) == (exact, "extended")
    assert Coverage().extended(SPACE, fetched) == (Coverage(periods={SPACE: fetched}), "extended")


def test_a_run_apart_from_the_covered_period_leaves_it() -> None:
    """A period that does not touch the covered one would claim the gap; it is not joined."""
    fetched = Period(datetime(2026, 1, 1, tzinfo=UTC), datetime(2026, 6, 1, tzinfo=UTC))
    assert covered().extended(SPACE, fetched) == (covered(), "held")


def test_a_later_short_run_does_not_claim_the_days_between() -> None:
    """Covered to 8 October, then --since 3d on the 21st: the 8th to the 18th were not seen."""
    early = Coverage(
        periods={
            SPACE: Period(datetime(2026, 10, 1, tzinfo=UTC), datetime(2026, 10, 8, tzinfo=UTC))
        }
    )
    late = Period(datetime(2026, 10, 18, tzinfo=UTC), datetime(2026, 10, 21, tzinfo=UTC))
    assert early.extended(SPACE, late) == (early, "held")


def test_a_run_that_reaches_the_covered_start_joins_it() -> None:
    """A period ending at the covered start makes one period with it."""
    fetched = Period(datetime(2026, 6, 1, tzinfo=UTC), COVERED)
    assert covered().extended(SPACE, fetched)[0].periods[SPACE] == Period(fetched.start, NOW)


def test_a_run_inside_the_covered_period_keeps_it() -> None:
    """A catch-up never moves the covered start forward, nor the end back."""
    fetched = Period(COVERED + timedelta(days=3), NOW - timedelta(days=1))
    assert covered().extended(SPACE, fetched) == (covered(), "extended")


# Plan 034: a project's end is exact, and capped at its first failure.
END = datetime(2026, 10, 27, 9, tzinfo=UTC)
DAY = timedelta(days=1)


def exactly(start: datetime, end: datetime) -> Coverage:
    """Return the project covered exactly from ``start`` to ``end``."""
    return Coverage(periods={PROJECT: Period(start, end)}, exact=frozenset({PROJECT}))


def before_034(start: datetime, end: datetime) -> Coverage:
    """Return the project covered from ``start`` to ``end`` by a record without exact."""
    return Coverage(periods={PROJECT: Period(start, end)})


def test_a_failure_does_not_end_a_space_s_period() -> None:
    """A space is listed whole: the next catch-up asks for its whole period again."""
    fetched = Period(COVERED, NOW + DAY)
    after = covered().extended(SPACE, fetched, NOW)
    assert after == (Coverage(periods={SPACE: fetched}), "extended")


def test_a_project_s_period_ends_at_its_first_failure_whatever_the_run() -> None:
    """A first run, or a run over an exact entry: the end is the failure's update time."""
    failed = NOW - 2 * DAY
    first = Period(NOW - 7 * DAY, NOW)
    assert Coverage().extended(PROJECT, first, failed) == (exactly(first.start, failed), "capped")
    later = Period(END - DAY, NOW)
    capped = exactly(COVERED, failed)
    assert exactly(COVERED, END).extended(PROJECT, later, failed) == (capped, "capped")
    assert exactly(COVERED, END).extended(PROJECT, later) == (exactly(COVERED, NOW), "extended")


def test_a_failure_below_the_old_end_lowers_it() -> None:
    """--since before the covered end, and a failure there: the end comes back to it."""
    failed = END - 3 * DAY
    fetched = Period(END - 5 * DAY, NOW)
    assert exactly(COVERED, END).extended(PROJECT, fetched, failed) == (
        exactly(COVERED, failed),
        "capped",
    )


def test_a_failure_at_the_start_of_a_catch_up_ends_the_period_there() -> None:
    """The window starts a day before the covered end; failing at its start ends it there."""
    fetched = Period(END - DAY, NOW)
    assert exactly(COVERED, END).extended(PROJECT, fetched, END - DAY) == (
        exactly(COVERED, END - DAY),
        "capped",
    )


@pytest.mark.parametrize("record", [exactly, before_034])
def test_a_failure_at_the_very_start_of_an_earlier_window_leaves_the_coverage(
    record: Callable[[datetime, datetime], Coverage],
) -> None:
    """The period would be empty: nothing is claimed of that moment, nor is it forgotten."""
    fetched = Period(COVERED - 3 * DAY, NOW)
    before = record(COVERED, END)
    assert before.extended(PROJECT, fetched, fetched.start) == (before, "capped")


def test_an_entry_from_before_034_is_replaced_by_a_run_from_its_start() -> None:
    """That run saw it whole: from its start to the reach, exact from then on."""
    fetched = Period(COVERED, NOW)
    failed = END - DAY
    old = before_034(COVERED, END)
    assert old.extended(PROJECT, fetched, failed) == (exactly(COVERED, failed), "capped")
    assert old.extended(PROJECT, fetched) == (exactly(COVERED, NOW), "extended")


def test_an_entry_from_before_034_replaced_ends_at_the_run_even_before_its_old_end() -> None:
    """--since its start and --until inside it: what the run saw, not the old end it hid."""
    until = END - 2 * DAY
    old = before_034(COVERED, END)
    assert old.extended(PROJECT, Period(COVERED, until)) == (exactly(COVERED, until), "extended")


def test_a_failure_at_the_start_of_an_exact_entry_makes_it_inexact() -> None:
    """Nothing is claimed of that moment: the next catch-up searches the period whole."""
    fetched = Period(COVERED, NOW)
    after = exactly(COVERED, END).extended(PROJECT, fetched, COVERED)
    assert after == (before_034(COVERED, END), "capped")
    assert fetch_window(after[0], PROJECT, None, NOW) == FetchWindow(
        period=Period(COVERED, NOW), reason="covered start"
    )


def test_an_entry_from_before_034_met_inside_is_joined_and_stays_inexact() -> None:
    """--since after its start: joined as before, so that a hidden failure is never blessed."""
    fetched = Period(END - 2 * DAY, NOW)
    old = before_034(COVERED, END)
    assert old.extended(PROJECT, fetched, END - DAY) == (before_034(COVERED, NOW), "extended")
