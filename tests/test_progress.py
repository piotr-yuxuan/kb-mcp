"""Tasks' progress: events every 10 s at most and at the end, bars on a display installed."""

from __future__ import annotations

import contextlib
from dataclasses import dataclass, field
from typing import override

from structlog.testing import capture_logs

from kb_mcp.observability.adapters.progress import Bar, Display, drawn, task


@dataclass
class Clock:
    """A clock that says the time it is set to, in seconds."""

    now: float = 0.0

    def __call__(self) -> float:
        """Say the time."""
        return self.now


@dataclass
class Recorded(Display, Bar):
    """A display that records what it is asked to draw, in order."""

    calls: list[tuple[object, ...]] = field(default_factory=list)

    @override
    def bar(self, what: str, total: int | None) -> Bar:
        self.calls.append(("begin", what, total))
        return self

    @override
    def show(self, done: int, item: str) -> None:
        self.calls.append(("show", done, item))

    @override
    def close(self) -> None:
        self.calls.append(("end",))


def said(events: list[dict[str, object]]) -> list[tuple[object, ...]]:
    """Give each progress event's task, items done, total and seconds left."""
    return [
        (each["task"], each["done"], each["total"], each["remaining"])
        for each in events
        if each["event"] == "progress"
    ]


def test_a_task_says_its_progress_once_at_its_end_and_draws_nothing_unobserved() -> None:
    """Two of four items in 6 s: 6 s left, at the pace kept; the event is at info."""
    clock = Clock()
    with capture_logs() as events, task("files", 4, clock) as files:
        clock.now = 3.0
        files.advance()
        clock.now = 6.0
        files.advance()
    assert said(events) == [("files", 2, 4, 6)]
    assert events[0]["log_level"] == "info"


def test_a_task_says_its_progress_every_10_s_at_most_then_at_its_end() -> None:
    """From its start: an event once 10 s have passed since the last, never sooner."""
    clock = Clock()
    with capture_logs() as events, task("texts to embed", 10, clock) as texts:
        for now in (1.0, 4.0, 9.9, 10.0, 12.0, 19.9, 20.5, 25.0):
            clock.now = now
            texts.advance()
        clock.now = 28.0
    # At 10 s, 4 done: 6 left at 2.5 s each; at 20.5 s, 7 done; at the end, 8 in 28 s.
    assert said(events) == [
        ("texts to embed", 4, 10, 15),
        ("texts to embed", 7, 10, round(3 * 20.5 / 7)),
        ("texts to embed", 8, 10, 7),
    ]


def test_items_advance_by_any_count() -> None:
    """A batch of texts counts as many items as it holds."""
    clock = Clock()
    with capture_logs() as events, task("texts to embed", 300, clock) as texts:
        texts.advance(128)
        texts.advance(128)
        clock.now = 2.0
    assert said(events) == [("texts to embed", 256, 300, 0)]


def test_a_task_of_no_known_total_has_no_time_left() -> None:
    """A listing read page by page: its count, and neither total nor time left."""
    clock = Clock()
    with capture_logs() as events, task("listing", clock=clock) as listing:
        clock.now = 5.0
        listing.advance()
    assert said(events) == [("listing", 1, None, None)]


def test_each_item_shows_before_it_is_handled_and_counts_once_the_next_is_asked() -> None:
    """On the display installed: the bar begins, shows each item by its name, then ends."""
    display = Recorded()
    with capture_logs(), drawn(display), task("documents", 3, Clock()) as documents:
        handled = [(item, documents.done) for item in documents.each(["a", "b", "c"], str.upper)]
    assert handled == [("a", 0), ("b", 1), ("c", 2)]
    assert display.calls == [
        ("begin", "documents", 3),
        ("show", 0, "A"),
        ("show", 1, "A"),
        ("show", 1, "B"),
        ("show", 2, "B"),
        ("show", 2, "C"),
        ("show", 3, "C"),
        ("end",),
    ]


def test_a_task_that_raises_ends_its_bar_and_says_how_far_it_went() -> None:
    """Interrupted at its second item, 4 s in, which is not counted done: 8 s were left."""
    clock, display, handled = Clock(), Recorded(), []
    with (
        capture_logs() as events,
        drawn(display),
        contextlib.suppress(KeyboardInterrupt),
        task("documents", 3, clock) as documents,
    ):
        for item in documents.each(["a", "b", "c"], str):
            handled.append(item)
            if item == "b":
                clock.now = 4.0
                raise KeyboardInterrupt
    assert handled == ["a", "b"]
    assert display.calls[-1] == ("end",)
    assert said(events) == [("documents", 1, 3, 8)]


def test_a_display_draws_only_the_tasks_begun_while_it_is_installed() -> None:
    """Before and after ``drawn``, a task is drawn nowhere; within, on the display."""
    display = Recorded()
    with capture_logs():
        with task("before", 1) as before:
            before.advance()
        with drawn(display), task("within", 1) as within:
            within.advance()
        with task("after", 1) as after:
            after.advance()
    assert display.calls == [("begin", "within", 1), ("show", 1, ""), ("end",)]
