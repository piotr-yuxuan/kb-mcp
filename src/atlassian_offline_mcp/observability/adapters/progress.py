"""Progress: how far a run's long tasks are, as events and as bars on a terminal.

Code reports a task with ``task()``, wherever it runs and with no setup. Each task logs
the event ``progress``: its name, how many of its items are done, of how many, and the
seconds it has left by ``remaining``, every 10 s at most and once at its end. Its bar is
drawn only by a display installed with ``drawn``, as ``observed`` does on a terminal:
this module draws nothing and imports no Rich (contract H), so that what reports
progress imports none either.
"""

from __future__ import annotations

import time
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, override

import structlog

from atlassian_offline_mcp.observability.domain.time_remaining import remaining

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Iterator

# The fewest seconds between two events progress of a task, but before its last.
HEARTBEAT = 10.0


class Bar(Protocol):
    """A task's bar, as a display draws it from the task's start to its end."""

    def show(self, done: int, item: str) -> None:
        """Show how many items are done, and the item that the task is at."""

    def close(self) -> None:
        """Take the bar away, its task ended."""


class Display(Protocol):
    """What draws the tasks' bars."""

    def bar(self, what: str, total: int | None) -> Bar:
        """Begin the bar of the task ``what``, of ``total`` items, None when not known."""


class Unseen(Display, Bar):
    """No display: a task's bar is drawn nowhere, as when no run is observed."""

    @override
    def bar(self, what: str, total: int | None) -> Bar:
        """Give this bar, which shows nothing."""
        return self

    @override
    def show(self, done: int, item: str) -> None:
        """Show nothing."""

    @override
    def close(self) -> None:
        """Take nothing away."""


# The display of the tasks begun now: None until ``drawn`` installs one.
DISPLAY = ContextVar[Display | None]("display", default=None)


@dataclass
class Task:
    """A task under way: its items done, of ``total`` if known, and the item it is at.

    ``said`` is when it last logged ``progress``, on ``clock``, or when it began.
    """

    what: str
    total: int | None
    bar: Bar
    clock: Callable[[], float]
    began: float
    said: float
    done: int = 0
    item: str = ""

    def advance(self, count: int = 1) -> None:
        """Count ``count`` more items done; log ``progress`` if 10 s passed since it last did."""
        self.done += count
        self.bar.show(self.done, self.item)
        now = self.clock()
        if now - self.said >= HEARTBEAT:
            self.say(now)

    def each[T](self, items: Iterable[T], name: Callable[[T], str]) -> Iterator[T]:
        """Give each item in turn, shown by its ``name`` as the one the task is at.

        An item is counted done once the next is asked for, or the items end; one whose
        handling raises, or that a loop breaks at, is not.
        """
        for item in items:
            self.item = name(item)
            self.bar.show(self.done, self.item)
            yield item
            self.advance()

    def say(self, now: float) -> None:
        """Log ``progress``: the items done, of how many, and the whole seconds left."""
        self.said = now
        left = remaining(self.done, self.total, now - self.began)
        structlog.get_logger(__name__).info(
            "progress",
            task=self.what,
            done=self.done,
            total=self.total,
            remaining=None if left is None else round(left),
        )


@contextmanager
def task(
    what: str, total: int | None = None, clock: Callable[[], float] = time.monotonic
) -> Iterator[Task]:
    """Report the progress of the task ``what``, of ``total`` items if known, within.

    Its bar is drawn on the display installed, if any, until it ends, however it ends;
    it then logs ``progress`` a last time.
    """
    began = clock()
    bar = (DISPLAY.get() or Unseen()).bar(what, total)
    progress = Task(what, total, bar, clock, began, began)
    try:
        yield progress
    finally:
        progress.bar.close()
        progress.say(clock())


@contextmanager
def drawn(display: Display) -> Iterator[None]:
    """Draw on ``display`` the bars of the tasks begun within."""
    installed = DISPLAY.set(display)
    try:
        yield
    finally:
        DISPLAY.reset(installed)
