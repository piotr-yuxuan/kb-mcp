"""Observing an invocation: its logs, on stderr and in its own file, its bars, its telemetry."""

from __future__ import annotations

import importlib
import logging
import os
import re
import secrets
import sys
import time
import traceback
from collections.abc import Mapping
from contextlib import ExitStack, contextmanager, nullcontext, suppress
from datetime import UTC, datetime, timedelta
from functools import partial
from importlib.metadata import version
from itertools import pairwise
from pathlib import Path
from typing import TYPE_CHECKING, TextIO, cast, override

import structlog
from opentelemetry import metrics, trace
from pydantic import AwareDatetime, ConfigDict
from rich.console import Console
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
from structlog.tracebacks import ExceptionDictTransformer

from kb_mcp.kernel.names import PROGRAM, STAMP, ExitStatus
from kb_mcp.kernel.records import Record
from kb_mcp.observability import progress

if TYPE_CHECKING:
    from collections.abc import Collection, Iterator

    from rich.progress import Task

    from kb_mcp.kernel.records import Invocation

# What exports telemetry, imported only for a run that has an endpoint: the SDK, its
# exporters and requests take a tenth of a second to import, which a run without would
# pay for nothing.
TELEMETRY = "kb_mcp.observability.telemetry"
# How long each run lasted, by its command and its exit status: made once, as the API
# would have an instrument, and recorded once the SDK, if any, is behind it.
RUN_DURATION = metrics.get_meter(__name__).create_histogram(
    "kb_mcp.run.duration", unit="s", description="How long a run lasted"
)
# Libraries that name each request at INFO or DEBUG, with its query: from WARNING only.
QUIET = ("httpx", "httpcore", "urllib3", "requests")
# The most that a run's file holds of lines, in bytes, before the line log.capped.
CAP = 256 * 2**20
# The OpenTelemetry SDK's loggers, whose records go to the file alone: on stderr they
# would break -q, and exported, a failed export would log about itself.
SDK = "opentelemetry"
# How long a log file is kept after its run started; its name: a subcommand's name, its
# run's start and its process's id.
KEPT = timedelta(days=30)
LOG_FILE = re.compile(r"([a-z][a-z0-9-]*)-([0-9]{8}T[0-9]{6}Z)-[0-9]+\.jsonl")
# The fields of an event that carry text of the site or of the mirror, which a line on a
# terminal cuts to its width; every other, such as a reason or a path, is whole.
SITE_TEXT = frozenset({"title", "heading", "query", "snippet", "ref"})
# Unicode's bidirectional controls (Bidi_Control in PropList.txt): the marks ALM, LRM
# and RLM, the embeddings and overrides LRE to RLO, and the isolates LRI to PDI, which
# reorder what a terminal shows after them.
BIDI_CONTROLS = "\u061c\u200e\u200f\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069"
# The controls, C0, DEL and C1, that a terminal may obey rather than show, as escape
# sequences, bells and backspaces; those that are white space become a space instead.
CONTROLS = [code for code in (*range(0x20), *range(0x7F, 0xA0)) if not chr(code).isspace()]
REMOVED = dict.fromkeys([*CONTROLS, *map(ord, BIDI_CONTROLS)])
SPACES = re.compile(r"\s+")
REDACTED = "[redacted]"
# The words that name a secret on their own; ``api`` names one only before ``key``.
SECRET_WORDS = frozenset({"authorization", "cookie", "token", "password", "secret"})
WORD_SEPARATORS = re.compile(r"[-_.]+")


def printable(text: str, *, width: int) -> str:
    """Show a text without its controls, its white space one space, cut with an ellipsis."""
    flat = SPACES.sub(" ", text.translate(REMOVED)).strip()
    return flat if len(flat) <= width else flat[: width - 1] + "…"


def redacted(value: object) -> object:
    """Copy a value, what a key holds redacted, at any depth, when its words name a secret.

    A key's words are split at ``_``, ``-`` and ``.``, lowered: one of ``SECRET_WORDS``, or
    ``api`` then ``key``. A mapping, a list and a tuple are copied; another value is kept.
    """
    if isinstance(value, Mapping):
        kept: dict[object, object] = {}
        for key, item in value.items():
            words = WORD_SEPARATORS.split(str(key).lower())
            secret = not SECRET_WORDS.isdisjoint(words) or ("api", "key") in pairwise(words)
            kept[key] = REDACTED if secret else redacted(item)
        return kept
    if isinstance(value, list):
        return [redacted(item) for item in value]
    if isinstance(value, tuple):
        return tuple(redacted(item) for item in value)
    return value


def redact_secrets(
    _logger: object, _method_name: str, event_dict: Mapping[str, object]
) -> dict[str, object]:
    """Redact an event's secrets: a structlog processor, before every sink."""
    return cast("dict[str, object]", redacted(event_dict))


# What an event or a library's record gets before any sink renders it, redaction last.
SHARED = (
    structlog.stdlib.add_log_level,
    structlog.stdlib.add_logger_name,
    structlog.processors.TimeStamper(fmt="iso", utc=True),
    redact_secrets,
)


def log_file_name(command: str, start: datetime, pid: int) -> str:
    """Name the log file of a run of ``command``, started at ``start`` (aware) by ``pid``."""
    return f"{command}-{start.astimezone(UTC):{STAMP}}-{pid}.jsonl"


def expired(name: str, commands: Collection[str], now: datetime) -> bool:
    """Say whether a file so named is a log file of one of ``commands``, over 30 days old."""
    match = LOG_FILE.fullmatch(name)
    if match is None or match[1] not in commands:
        return False
    try:
        start = datetime.fromisoformat(match[2])
    except ValueError:
        return False
    return now - start > KEPT


class CappedFile(logging.StreamHandler[TextIO]):
    """Write records as lines to a stream until past ``cap`` bytes, or one fails; then end it."""

    def __init__(self, stream: TextIO, cap: int) -> None:
        """Write to ``stream``, a file, in UTF-8, which its owner closes."""
        super().__init__(stream)
        self.room = cap

    @override
    def handleError(self, record: logging.LogRecord) -> None:
        """End the file at an OSError, closing it, and say so elsewhere; else as logging does."""
        error = sys.exception()
        if not isinstance(error, OSError):
            super().handleError(record)
            return
        self.room = -1
        with suppress(OSError):
            self.stream.close()
        structlog.get_logger().warning(
            "log.unwritable", folder=str(Path(self.stream.name).parent), reason=str(error)
        )

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
        capped = {"name": __name__, "levelno": logging.WARNING, "levelname": "WARNING"}
        return super().format(logging.makeLogRecord({**capped, "msg": "log.capped"}))


def route_through_logging() -> None:
    """Send structlog's events through the root logger from DEBUG, ``QUIET``'s from WARNING."""
    structlog.configure(
        processors=[*SHARED, structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
    )
    logging.getLogger().setLevel(logging.DEBUG)
    for name in QUIET:
        logging.getLogger(name).setLevel(logging.WARNING)


@contextmanager
def log_file(
    folder: Path, command: str, run: str, now: datetime, commands: Collection[str]
) -> Iterator[Path]:
    """Write each event and record from DEBUG as a JSON line into the run's file, by its path.

    First the files of ``commands`` that ``expired`` are removed. Raises OSError when
    ``folder`` cannot be made or written.
    """
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    for old in folder.iterdir():
        if expired(old.name, commands, now):
            with suppress(OSError):
                old.unlink()
    path = folder / log_file_name(command, now, os.getpid())

    def stamped(_logger: object, _method: str, event: Mapping[str, object]) -> dict[str, object]:
        context = trace.get_current_span().get_span_context()
        spans = {
            "trace_id": trace.format_trace_id(context.trace_id),
            "span_id": trace.format_span_id(context.span_id),
        }
        return {**event, "run": run, "command": command, **(spans if context.is_valid else {})}

    with open(path, "a", encoding="utf-8", opener=partial(os.open, mode=0o600)) as stream:
        handler = CappedFile(stream, CAP)
        handler.setFormatter(
            structlog.stdlib.ProcessorFormatter(
                foreign_pre_chain=SHARED,
                processors=[
                    structlog.stdlib.ProcessorFormatter.remove_processors_meta,
                    stamped,
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


class ConsoleLines(logging.Handler):
    """Draw each record but the SDK's on a console in structlog's layout, its texts inert."""

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
        """Draw the record's lines, unwrapped; a failure goes to ``handleError``."""
        try:
            self.console.print(Text.from_ansi(self.format(record)), soft_wrap=True)
        except OSError, TypeError, ValueError:
            self.handleError(record)


class Remaining(ProgressColumn):
    """A task's time left by ``remaining``, in hours, minutes and seconds; dashes if unknown."""

    @override
    def render(self, task: Task) -> Text:
        """Show the time that the task has left, at the pace it has kept."""
        left = progress.remaining(task.completed, task.total, task.elapsed or 0.0)
        shown = "-:--:--" if left is None else str(timedelta(seconds=round(left)))
        return Text(shown, style="progress.remaining")


class TaskBar(Record):
    """A task's line among the bars, from its start to its end."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    progress: Progress
    id: TaskID

    def show(self, done: int, item: str) -> None:
        """Show the items done, and the item that the task is at, inert on one line."""
        width = self.progress.console.width
        self.progress.update(self.id, completed=done, item=printable(item, width=width))

    def close(self) -> None:
        """Draw the task's line once more, then take it away, and the bars with the last."""
        self.progress.refresh()
        self.progress.remove_task(self.id)
        if not self.progress.task_ids:
            self.progress.stop()


class Bars(progress.Display):
    """Tasks' bars, drawn with Rich below a console's log lines while a task runs, if ``shown``."""

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
    def bar(self, what: str, total: int | None) -> progress.Bar:
        """Begin the line of a task, below those of the tasks under way."""
        self.progress.start()
        return TaskBar(
            progress=self.progress, id=self.progress.add_task(what, total=total, item="")
        )


class Running(Record):
    """An invocation under way: its run's id, its start, which names its log file, its status."""

    model_config = ConfigDict(frozen=False)

    id: str
    started: AwareDatetime
    status: int = ExitStatus.OK


@contextmanager
def early() -> Iterator[None]:
    """Send each event and record to stderr from WARNING, then put the loggers back as they were."""
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
def observed(invocation: Invocation, folder: Path, endpoint: str | None) -> Iterator[Running]:
    """Observe an invocation, yielding a ``Running`` whose status the body sets.

    Ctrl-C or an exception in the body goes no further: the status says it. A ``folder`` or
    an ``endpoint`` that fails gives one warning, and the run goes on without it.
    """
    route_through_logging()
    root = logging.getLogger()
    log = structlog.get_logger()
    command = invocation.command
    running = Running(id=invocation.run or secrets.token_hex(8), started=datetime.now(UTC))
    with ExitStack() as stack:
        for handler in [handler for handler in root.handlers if isinstance(handler, ConsoleLines)]:
            root.removeHandler(handler)
            stack.callback(root.addHandler, handler)
        console = Console(stderr=True, force_terminal=invocation.stderr_terminal)
        stderr = ConsoleLines(console, logging.getLevelNamesMapping()[invocation.level.upper()])
        bars = invocation.stderr_terminal and not invocation.quiet
        stderr.addFilter(lambda record: not bars or record.name != progress.__name__)
        root.addHandler(stderr)
        stack.callback(root.removeHandler, stderr)
        stack.enter_context(progress.drawn(Bars(console, shown=bars)))
        path = None
        try:
            path = stack.enter_context(
                log_file(folder, command, running.id, running.started, invocation.commands)
            )
        except OSError as error:
            log.warning("log.unwritable", folder=str(folder), reason=str(error))
        if endpoint is not None:
            try:
                exporting = importlib.import_module(TELEMETRY).exporting
                stack.enter_context(exporting(endpoint, running.id, command))
            except OSError as error:
                log.warning("telemetry.undelivered", endpoint=endpoint, reason=str(error))
        spanned = (
            trace.get_tracer(__name__).start_as_current_span(
                command,
                attributes={"kb_mcp.command": command, "kb_mcp.dry_run": invocation.dry_run},
            )
            if invocation.traced
            else nullcontext(trace.INVALID_SPAN)
        )
        span = stack.enter_context(spanned)
        log.info(
            "run.start",
            version=version(PROGRAM),
            **invocation.described,
            log_file=None if path is None else str(path),
            telemetry=endpoint,
        )
        began = time.monotonic()
        try:
            yield running
        except KeyboardInterrupt:
            running.status = ExitStatus.INTERRUPTED
            log.warning("run.interrupted", seconds=round(time.monotonic() - began, 3))
        except Exception:
            running.status = ExitStatus.FAILED
            log.exception("run.failed", seconds=round(time.monotonic() - began, 3))
        else:
            log.info("run.end", status=running.status, seconds=round(time.monotonic() - began, 3))
        span.set_attribute("kb_mcp.exit_status", int(running.status))
        RUN_DURATION.record(
            time.monotonic() - began,
            {"kb_mcp.command": command, "kb_mcp.exit_status": int(running.status)},
        )
