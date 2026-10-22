"""The display: what a run draws with Rich on stderr's console, its log lines first.

This module alone of ``observability`` draws, so that what imports the others, the
settings' loader among them, imports no Rich.
"""

from __future__ import annotations

import logging
import sys
from typing import TYPE_CHECKING, override

import structlog
from rich.text import Text

from atlassian_offline_mcp.observability.adapters.logs import SDK, SHARED
from atlassian_offline_mcp.observability.domain.inert_text import printable

if TYPE_CHECKING:
    from rich.console import Console


class ConsoleLines(logging.Handler):
    """Draw each record on a console as structlog's console layout has it, its text inert.

    A line holds the time, the level, the event, the logger, then the event's fields.
    Each text among them first passes ``printable()``, cut to the console's width on a
    terminal, whole elsewhere, so that text from the site or the mirror moves no cursor
    and reorders nothing; the line is drawn as Rich's ``Text``, never as markup, and is
    coloured on a terminal without ``NO_COLOR`` alone. A traceback follows its line, with
    no frame's locals. The SDK's own records are left to the file.
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
                        key: printable(value, width=width) if isinstance(value, str) else value
                        for key, value in event.items()
                    },
                    structlog.dev.ConsoleRenderer(
                        colors=colours, exception_formatter=structlog.dev.plain_traceback
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
