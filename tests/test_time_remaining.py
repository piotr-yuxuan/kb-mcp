"""The time a task has left: at the pace kept so far, unknown before an item is done."""

from __future__ import annotations

import pytest

from atlassian_offline_mcp.observability.domain.time_remaining import remaining


@pytest.mark.parametrize(
    ("done", "total", "elapsed", "left"),
    [
        (50, 100, 10.0, 10.0),
        (1, 4, 3.0, 9.0),
        (3, 4, 3.0, 1.0),
        (10, 10, 60.0, 0.0),
        (12, 10, 60.0, 0.0),
        (1, 1000, 0.0, 0.0),
    ],
)
def test_each_item_left_takes_as_long_as_those_done_did(
    done: int, total: int, elapsed: float, left: float
) -> None:
    """Half done in 10 s leaves 10 s; all done, or more than the total, leaves none."""
    assert remaining(done, total, elapsed) == pytest.approx(left)


@pytest.mark.parametrize(("done", "total"), [(0, 100), (0, 0), (5, None), (0, None)])
def test_with_nothing_done_or_no_total_the_time_left_is_unknown(
    done: int, total: int | None
) -> None:
    """No pace yet, or nothing to measure it against: None, never a guess."""
    assert remaining(done, total, 30.0) is None
