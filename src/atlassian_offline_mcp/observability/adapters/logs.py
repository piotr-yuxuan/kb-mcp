"""Structured logs: structlog through the standard library, and the file each run writes.

Code logs with ``structlog.get_logger()``; libraries log with the standard library.
Once ``route_through_logging`` is called, both reach the root logger, whose handlers are
the sinks, so that a library's record lands where an event does. Every event and record
gets ``timestamp`` (UTC), ``level`` and ``logger`` before a sink, and has its secrets
redacted; ``log_file`` adds a sink, the run's own file.
"""

from __future__ import annotations

import logging
import os
from contextlib import contextmanager
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING, TextIO, override

import platformdirs
import structlog
from opentelemetry import trace
from structlog.tracebacks import ExceptionDictTransformer

from atlassian_offline_mcp.observability.domain.log_files import expired, log_file_name
from atlassian_offline_mcp.observability.domain.redaction import redact_secrets

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping
    from datetime import datetime

# The program's name, as pyproject.toml names its script, which names its log folder.
PROGRAM = "atlassian-offline-mcp"
# What an event or a library's record gets before any sink renders it, redaction last.
SHARED = (
    structlog.stdlib.add_log_level,
    structlog.stdlib.add_logger_name,
    structlog.processors.TimeStamper(fmt="iso", utc=True),
    redact_secrets,
)
# Libraries that name each request at INFO or DEBUG, with its query: from WARNING only.
QUIET = ("httpx", "httpcore", "urllib3", "requests")
# The most that a run's file holds of lines, in bytes, before the line log.capped.
CAP = 256 * 2**20
# The OpenTelemetry SDK's loggers, whose records go to the file alone: on stderr they
# would break -q, and exported, a failed export would log about itself.
SDK = "opentelemetry"


class CappedFile(logging.StreamHandler[TextIO]):
    """Write each record as a line to a stream, until the lines would pass ``cap`` bytes.

    The line that would pass the cap is replaced by one of its own, the event
    ``log.capped``, and nothing is written after it.
    """

    def __init__(self, stream: TextIO, cap: int) -> None:
        """Write to ``stream``, in UTF-8, which its owner closes."""
        super().__init__(stream)
        self.room = cap

    @override
    def emit(self, record: logging.LogRecord) -> None:
        """Write the record's line, unless the cap was reached already."""
        if self.room >= 0:
            super().emit(record)

    @override
    def format(self, record: logging.LogRecord) -> str:
        """Format the record, its line counted against the room left; past it, the cap's."""
        line = super().format(record)
        self.room -= len(f"{line}{self.terminator}".encode())
        if self.room >= 0:
            return line
        capped = logging.makeLogRecord(
            {
                "name": __name__,
                "levelno": logging.WARNING,
                "levelname": "WARNING",
                "msg": "log.capped",
            }
        )
        return super().format(capped)


def span_ids(
    _logger: object, _method_name: str, event_dict: Mapping[str, object]
) -> Mapping[str, object]:
    """Add the ids of the span that an event or a record is logged in, if any.

    ``trace_id`` and ``span_id`` are in hex, as OTLP's JSON and Tempo show them, so that
    a line of the file leads to its trace.
    """
    context = trace.get_current_span().get_span_context()
    if not context.is_valid:
        return event_dict
    return {
        **event_dict,
        "trace_id": trace.format_trace_id(context.trace_id),
        "span_id": trace.format_span_id(context.span_id),
    }


def default_log_folder() -> Path:
    """Return the user's log folder for this program, as platformdirs places it.

    On macOS ``~/Library/Logs/atlassian-offline-mcp``; on Linux
    ``$XDG_STATE_HOME/atlassian-offline-mcp/log``, ``~/.local/state`` by default.
    """
    return Path(platformdirs.user_log_dir(PROGRAM, appauthor=False))


def route_through_logging() -> None:
    """Send structlog's events through the standard library's root logger, from DEBUG.

    Each sink is a handler of the root logger, at its own level. The libraries of
    ``QUIET`` reach the sinks from WARNING only.
    """
    structlog.configure(
        processors=[*SHARED, structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
    )
    logging.getLogger().setLevel(logging.DEBUG)
    for name in QUIET:
        logging.getLogger(name).setLevel(logging.WARNING)


@contextmanager
def log_file(folder: Path, command: str, run: str, now: datetime, cap: int = CAP) -> Iterator[Path]:
    """Write every event and record, from DEBUG, as JSON lines into the run's own file.

    The run of ``command``, whose id is ``run``, starts at ``now``. Within, the file is a
    sink of the root logger, for all that ``route_through_logging`` lets through, and its
    path is given: ``<folder>/<command>-<UTC start>-<pid>.jsonl``, which the user alone
    can read, as ``folder`` when it is made here; one that exists keeps its mode, since
    the user may have chosen it. Before the file is opened, the log files in ``folder``
    whose run started over 30 days before ``now`` are removed. Each line adds ``run``
    and ``command``, which replace an event's own of these names, and, within a span, its
    ``trace_id`` and ``span_id``; a traceback shows no frame's locals. Past ``cap`` bytes
    of lines, a line ``log.capped`` ends the file. Raises OSError when ``folder`` cannot
    be made or written.
    """
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    for old in folder.iterdir():
        if expired(old.name, now):
            old.unlink(missing_ok=True)
    path = folder / log_file_name(command, now, os.getpid())
    with open(path, "a", encoding="utf-8", opener=partial(os.open, mode=0o600)) as stream:
        handler = CappedFile(stream, cap)
        handler.setFormatter(
            structlog.stdlib.ProcessorFormatter(
                foreign_pre_chain=SHARED,
                processors=[
                    structlog.stdlib.ProcessorFormatter.remove_processors_meta,
                    lambda _logger, _method, event: {**event, "run": run, "command": command},
                    span_ids,
                    structlog.processors.ExceptionRenderer(
                        ExceptionDictTransformer(show_locals=False)
                    ),
                    structlog.processors.JSONRenderer(),
                ],
            )
        )
        root = logging.getLogger()
        root.addHandler(handler)
        try:
            yield path
        finally:
            root.removeHandler(handler)
            handler.close()
