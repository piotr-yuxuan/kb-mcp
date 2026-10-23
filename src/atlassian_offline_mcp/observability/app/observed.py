"""Observing a run: its logs, on stderr and in its own file, its progress, its telemetry.

The command line enters ``early`` once its arguments are parsed, then ``observed`` once
the run's settings are read, with plain values: how the run reports, its log folder, its
telemetry endpoint. It names no type of the settings, so that ``observability`` imports
neither ``config`` nor ``cli``.
"""

from __future__ import annotations

import importlib
import logging
import secrets
import time
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from importlib.metadata import version
from typing import TYPE_CHECKING

import structlog
from rich.console import Console

from atlassian_offline_mcp.kernel.exit_status import ExitStatus
from atlassian_offline_mcp.observability.adapters import progress
from atlassian_offline_mcp.observability.adapters.display import Bars, ConsoleLines
from atlassian_offline_mcp.observability.adapters.logs import (
    PROGRAM,
    QUIET,
    log_file,
    route_through_logging,
)

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping
    from pathlib import Path

    from atlassian_offline_mcp.kernel.output import Output

# What exports telemetry, imported only for a run that has an endpoint: the SDK, its
# exporters and requests take a tenth of a second to import, which a run without would
# pay for nothing.
TELEMETRY = "atlassian_offline_mcp.observability.adapters.telemetry"


@dataclass
class Run:
    """A run that ``observed`` watches: its id, and the exit status its body sets before it ends."""

    id: str
    status: int = ExitStatus.OK


@contextmanager
def early() -> Iterator[None]:
    """Send every event and record to stderr from WARNING, until the run's settings are read.

    structlog's events go through the standard library, as ``observed`` will have them,
    never to stdout, where structlog prints by default. On leaving, structlog and the
    levels of the standard library's loggers are as they were.
    """
    levels = {name: logging.getLogger(name).level for name in ("", *QUIET)}
    stderr = ConsoleLines(Console(stderr=True), logging.WARNING)
    route_through_logging()
    logging.getLogger().addHandler(stderr)
    try:
        yield
    finally:
        logging.getLogger().removeHandler(stderr)
        structlog.reset_defaults()
        for name, level in levels.items():
            logging.getLogger(name).setLevel(level)


@contextmanager
def observed(
    output: Output,
    folder: Path | None,
    endpoint: str | None,
    command: str,
    described: Mapping[str, object],
) -> Iterator[Run]:
    """Observe a run of ``command``: its logs on stderr at its level, and in its own file.

    Within ``early``, whose stderr this one replaces while it lasts. The run's id, 16
    random hex digits, is made first, so that a run without a file has one too. Stderr
    is drawn at ``output``'s level, through a console that is a terminal as ``output``
    says. The file, ``log_file``'s in ``folder``, holds all from DEBUG, under the run's
    id; a run that reads no settings has no ``folder``, and one that cannot be written
    gives one warning, ``log.unwritable``, and no file. The run then writes
    ``run.start``: the version, ``described``, the command line's fields such as the
    arguments and the settings, the log file and the telemetry endpoint, if any. It ends
    with ``run.end``, its status as the body set it, or ``run.interrupted`` by Ctrl-C, or
    ``run.failed`` with the exception's traceback; each says how many seconds it lasted.
    The run's status is then ``ExitStatus.INTERRUPTED`` or ``ExitStatus.FAILED``: the
    interruption or the exception goes no further.

    On a terminal, unless -q, the tasks' progress is drawn on stderr as bars, and their
    events ``progress`` are kept off it; elsewhere, these events show it from -v.
    ``serve`` reports no task, so it draws no bar.

    With an ``endpoint``, the run's traces, metrics and logs from INFO are sent there,
    as ``exporting`` has it, from before ``run.start`` to after ``run.end``; one that
    does not take a connection gives one warning, ``telemetry.undelivered``, and the run
    goes on without. Without, the SDK is not even imported: what the run traces and
    measures goes nowhere.
    """
    root = logging.getLogger()
    log = structlog.get_logger()
    run = Run(secrets.token_hex(8))
    with ExitStack() as stack:
        for handler in [handler for handler in root.handlers if isinstance(handler, ConsoleLines)]:
            root.removeHandler(handler)
            stack.callback(root.addHandler, handler)
        console = Console(stderr=True, force_terminal=output.stderr_terminal)
        stderr = ConsoleLines(console, logging.getLevelNamesMapping()[output.level.upper()])
        bars = output.stderr_terminal and not output.quiet
        stderr.addFilter(lambda record: not bars or record.name != progress.__name__)
        root.addHandler(stderr)
        stack.callback(root.removeHandler, stderr)
        stack.enter_context(progress.drawn(Bars(console, shown=bars)))
        path = None
        if folder is not None:
            try:
                path = stack.enter_context(log_file(folder, command, run.id, datetime.now(UTC)))
            except OSError as error:
                log.warning("log.unwritable", folder=str(folder), reason=str(error))
        if endpoint is not None:
            try:
                exporting = importlib.import_module(TELEMETRY).exporting
                stack.enter_context(exporting(endpoint, run.id, command))
            except OSError as error:
                log.warning("telemetry.undelivered", endpoint=endpoint, reason=str(error))
        log.info(
            "run.start",
            version=version(PROGRAM),
            **described,
            log_file=None if path is None else str(path),
            telemetry=endpoint,
        )
        began = time.monotonic()
        try:
            yield run
        except KeyboardInterrupt:
            run.status = ExitStatus.INTERRUPTED
            log.warning("run.interrupted", seconds=round(time.monotonic() - began, 3))
        except Exception:
            run.status = ExitStatus.FAILED
            log.exception("run.failed", seconds=round(time.monotonic() - began, 3))
        else:
            log.info("run.end", status=run.status, seconds=round(time.monotonic() - began, 3))
