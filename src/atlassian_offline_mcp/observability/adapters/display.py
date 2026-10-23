"""The display: what a run draws with Rich on stderr's console, log lines and tasks' bars.

This module alone of ``observability`` draws, so that what imports the others, the
settings' loader and ``progress`` among them, imports no Rich.
"""

from __future__ import annotations

import logging
import sys
import traceback
from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING, override

import structlog
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    ProgressColumn,
    TaskID,
    TextColumn,
    TimeElapsedColumn,
)
from rich.table import Column
from rich.text import Text

from atlassian_offline_mcp.observability.adapters.logs import SDK, SHARED
from atlassian_offline_mcp.observability.adapters.progress import Bar, Display
from atlassian_offline_mcp.observability.domain.inert_text import printable
from atlassian_offline_mcp.observability.domain.time_remaining import remaining

if TYPE_CHECKING:
    from rich.console import Console
    from rich.progress import Task

# The fields of an event that carry text of the site or of the mirror: its titles,
# headings, queries, excerpts and references. A line on a terminal cuts these to its
# width; every other, such as the event, a reason, an error or a path, is whole.
SITE_TEXT = frozenset({"title", "heading", "query", "snippet", "ref"})


class ConsoleLines(logging.Handler):
    """Draw each record on a console as structlog's console layout has it, its text inert.

    A line holds the time, the level, the event, the logger, then the event's fields.
    Each text among them first passes ``printable()``, so that text from the site or the
    mirror moves no cursor and reorders nothing: those of ``SITE_TEXT`` cut to the
    console's width on a terminal, whole elsewhere, and the others whole everywhere, the
    terminal wrapping them. The line is drawn as Rich's ``Text``, never as markup, and is
    coloured on a terminal without ``NO_COLOR`` alone. A traceback follows its line, with
    no frame's locals, each of its lines through ``printable()`` too, whole and indented
    as it was. The SDK's own records are left to the file.
    """

    def __init__(self, console: Console, level: int) -> None:
        """Draw on ``console`` what is of ``level`` or above."""
        super().__init__(level)
        self.console = console
        colours = console.is_terminal and not console.no_color
        width = console.width if console.is_terminal else sys.maxsize
        self.setFormatter(
            structlog.stdlib.ProcessorFormatter(
                foreign_pre_chain=SHARED,
                processors=[
                    structlog.stdlib.ProcessorFormatter.remove_processors_meta,
                    lambda _logger, _method, event: {
                        key: printable(value, width=width if key in SITE_TEXT else sys.maxsize)
                        if isinstance(value, str)
                        else value
                        for key, value in event.items()
                    },
                    structlog.dev.ConsoleRenderer(
                        colors=colours,
                        exception_formatter=lambda out, exc_info: out.writelines(
                            f"\n{line[: len(line) - len(line.lstrip(' '))]}"
                            f"{printable(line, width=sys.maxsize)}"
                            for line in "".join(traceback.format_exception(*exc_info)).splitlines()
                        ),
                    ),
                ],
            )
        )
        self.addFilter(lambda record: record.name.partition(".")[0] != SDK)

    @override
    def emit(self, record: logging.LogRecord) -> None:
        """Draw the record's line, and its traceback if any, unwrapped: the terminal wraps.

        A record whose message its arguments cannot fill, or a console that can no
        longer be written, such as a closed pipe, goes to ``handleError``, as with the
        standard library's handlers, so that the run goes on.
        """
        try:
            self.console.print(Text.from_ansi(self.format(record)), soft_wrap=True)
        except OSError, TypeError, ValueError:
            self.handleError(record)


class Remaining(ProgressColumn):
    """A task's time left by ``remaining``, in hours, minutes and seconds; dashes if unknown."""

    @override
    def render(self, task: Task) -> Text:
        """Show the time that the task has left, at the pace it has kept."""
        left = remaining(task.completed, task.total, task.elapsed or 0.0)
        shown = "-:--:--" if left is None else str(timedelta(seconds=round(left)))
        return Text(shown, style="progress.remaining")


@dataclass(frozen=True)
class TaskBar(Bar):
    """A task's line among the bars, from its start to its end."""

    progress: Progress
    id: TaskID

    @override
    def show(self, done: int, item: str) -> None:
        """Show the items done, and the item that the task is at, inert on one line."""
        width = self.progress.console.width
        self.progress.update(self.id, completed=done, item=printable(item, width=width))

    @override
    def close(self) -> None:
        """Draw the task's line once more, then take it away, and the bars with the last."""
        self.progress.refresh()
        self.progress.remove_task(self.id)
        if not self.progress.task_ids:
            self.progress.stop()


class Bars(Display):
    """Tasks' bars, drawn with Rich on a console below its log lines while a task runs.

    A task's line holds its name, its bar, its items done of its total (``?`` when not
    known), the time elapsed, the time left by ``remaining``, and the item it is at,
    through ``printable()`` and drawn as plain text, never as markup. While a bar is
    drawn, what is written on stderr goes above the bars; stdout is left as it is.
    Unless ``shown``, nothing is drawn.
    """

    def __init__(self, console: Console, *, shown: bool) -> None:
        """Draw on ``console``, if ``shown``."""
        self.progress = Progress(
            TextColumn("{task.description}", markup=False),
            BarColumn(bar_width=None, table_column=Column(ratio=1)),
            MofNCompleteColumn(),
            TimeElapsedColumn(),
            Remaining(),
            TextColumn(
                "{task.fields[item]}",
                markup=False,
                table_column=Column(no_wrap=True, overflow="ellipsis", ratio=1),
            ),
            console=console,
            redirect_stdout=False,
            disable=not shown,
            expand=True,
        )

    @override
    def bar(self, what: str, total: int | None) -> Bar:
        """Begin the line of a task, below those of the tasks under way."""
        self.progress.start()
        return TaskBar(self.progress, self.progress.add_task(what, total=total, item=""))
