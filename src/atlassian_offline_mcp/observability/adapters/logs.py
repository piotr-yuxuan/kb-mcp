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
from typing import TYPE_CHECKING

import platformdirs
import structlog
from structlog.tracebacks import ExceptionDictTransformer

from atlassian_offline_mcp.observability.domain.log_files import expired, log_file_name
from atlassian_offline_mcp.observability.domain.redaction import redact_secrets

if TYPE_CHECKING:
    from collections.abc import Iterator
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
def log_file(folder: Path, command: str, run: str, now: datetime) -> Iterator[Path]:
    """Write every event and record, from DEBUG, as JSON lines into the run's own file.

    The run of ``command``, whose id is ``run``, starts at ``now``. Within, the file is a
    sink of the root logger, for all that ``route_through_logging`` lets through, and its
    path is given: ``<folder>/<command>-<UTC start>-<pid>.jsonl``, which the user alone
    can read, as ``folder`` when it is made here; one that exists keeps its mode, since
    the user may have chosen it. Before the file is opened, the log files in ``folder``
    whose run started over 30 days before ``now`` are removed. Each line adds ``run``
    and ``command``, which replace an event's own of these names, and a traceback shows
    no frame's locals. Raises OSError when ``folder`` cannot be made or written.
    """
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    for old in folder.iterdir():
        if expired(old.name, now):
            old.unlink(missing_ok=True)
    path = folder / log_file_name(command, now, os.getpid())
    with open(path, "a", encoding="utf-8", opener=partial(os.open, mode=0o600)) as stream:
        handler = logging.StreamHandler(stream)
        handler.setFormatter(
            structlog.stdlib.ProcessorFormatter(
                foreign_pre_chain=SHARED,
                processors=[
                    structlog.stdlib.ProcessorFormatter.remove_processors_meta,
                    lambda _logger, _method, event: {**event, "run": run, "command": command},
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
