"""A run's log file: JSON lines from DEBUG, the user's alone, capped, kept 30 days."""

from __future__ import annotations

import base64
import errno
import io
import json
import logging
import os
import pwd
import stat
import sys
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING, override

import pytest
import structlog
from opentelemetry.sdk.trace import TracerProvider
from structlog.testing import capture_logs

from atlassian_offline_mcp.observability.adapters import logs
from atlassian_offline_mcp.observability.adapters.logs import (
    default_log_folder,
    log_file,
    route_through_logging,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

    from _pytest.capture import CaptureFixture
    from _pytest.monkeypatch import MonkeyPatch

NOW = datetime(2026, 10, 22, 21, 5, 9, tzinfo=UTC)
RUN = "0123456789abcdef"
# Commands of the program, as the command line gives them, some of them.
COMMANDS = frozenset({"check", "download", "index", "login"})
SENTINEL = "sentinel-token-3f8a"
BASIC = base64.b64encode(f"tests@example.invalid:{SENTINEL}".encode()).decode()
# The loggers whose levels a test changes, the root's first.
CHANGED = ("", "httpx", "httpcore", "urllib3", "requests")


@pytest.fixture(autouse=True)
def through_logging() -> Iterator[None]:
    """Route structlog through the standard library for one test, then undo it."""
    levels = {name: logging.getLogger(name).level for name in CHANGED}
    route_through_logging()
    yield
    structlog.reset_defaults()
    for name, level in levels.items():
        logging.getLogger(name).setLevel(level)


class FullDisk(io.RawIOBase):
    """A file on a full disk: it takes no byte, each write failing for want of room."""

    def __init__(self, name: str) -> None:
        """Be the file of this path."""
        super().__init__()
        self.name = name

    @override
    def writable(self) -> bool:
        return True

    @override
    def write(self, _: object) -> int:
        raise OSError(errno.ENOSPC, os.strerror(errno.ENOSPC))


def lines(path: Path) -> list[dict[str, object]]:
    """Read a log file's lines, each a JSON object."""
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_the_file_is_named_by_command_utc_start_and_process(tmp_path: Path) -> None:
    """``<folder>/<command>-<UTC %Y%m%dT%H%M%SZ>-<pid>.jsonl``, whatever the start's offset."""
    paris = NOW.astimezone(timezone(timedelta(hours=2)))
    with log_file(tmp_path, "check", RUN, paris, COMMANDS) as path:
        pass
    assert path == tmp_path / f"check-20261022T210509Z-{os.getpid()}.jsonl"
    assert path.is_file()


def test_the_folder_and_the_file_are_the_user_s_alone(tmp_path: Path) -> None:
    """A folder made 0700, a file 0600, even where the process's mask leaves all open."""
    folder = tmp_path / "state" / "logs"
    mask = os.umask(0)
    try:
        with log_file(folder, "check", RUN, NOW, COMMANDS) as path:
            pass
    finally:
        os.umask(mask)
    assert stat.S_IMODE(folder.stat().st_mode) == stat.S_IRWXU
    assert stat.S_IMODE(path.stat().st_mode) == stat.S_IRUSR | stat.S_IWUSR


def test_a_folder_that_exists_keeps_its_mode(tmp_path: Path) -> None:
    """The user may have chosen it; the file in it is still the user's alone."""
    folder = tmp_path / "logs"
    folder.mkdir()
    shared = stat.S_IRWXU | stat.S_IRGRP | stat.S_IXGRP | stat.S_IROTH | stat.S_IXOTH
    folder.chmod(shared)
    with log_file(folder, "check", RUN, NOW, COMMANDS) as path:
        pass
    assert stat.S_IMODE(folder.stat().st_mode) == shared
    assert stat.S_IMODE(path.stat().st_mode) == stat.S_IRUSR | stat.S_IWUSR


def test_events_and_libraries_records_share_the_file_from_debug(tmp_path: Path) -> None:
    """Each line: timestamp in UTC, level, event, logger, run, command, and the event's own."""
    before = datetime.now(UTC)
    with log_file(tmp_path, "download", RUN, NOW, COMMANDS) as path:
        structlog.get_logger().debug("download.document", id="65601", title="Plan")
        logging.getLogger("some.library").info("connected to %s", "the site")
    after = datetime.now(UTC)
    event, record = lines(path)
    assert {key: value for key, value in event.items() if key != "timestamp"} == {
        "level": "debug",
        "event": "download.document",
        "logger": __name__,
        "run": RUN,
        "command": "download",
        "id": "65601",
        "title": "Plan",
    }
    assert {key: value for key, value in record.items() if key != "timestamp"} == {
        "level": "info",
        "event": "connected to the site",
        "logger": "some.library",
        "run": RUN,
        "command": "download",
    }
    for line in (event, record):
        timestamp = str(line["timestamp"])
        assert timestamp.endswith("Z")
        assert before <= datetime.fromisoformat(timestamp) <= after


def test_the_run_s_fields_replace_an_event_s_own(tmp_path: Path) -> None:
    """``run`` and ``command`` are always the run's."""
    with log_file(tmp_path, "check", RUN, NOW, COMMANDS) as path:
        structlog.get_logger().info("run.start", run="another", command="index")
    (line,) = lines(path)
    assert (line["run"], line["command"]) == (RUN, "check")


def test_a_line_within_a_span_carries_its_ids_in_hex_and_one_outside_none(
    tmp_path: Path,
) -> None:
    """As OTLP's JSON writes them: the trace's in 32 hex digits, the span's in 16."""
    tracer = TracerProvider(shutdown_on_exit=False).get_tracer(__name__)
    with log_file(tmp_path, "download", RUN, NOW, COMMANDS) as path:
        with tracer.start_as_current_span("download.document") as span:
            structlog.get_logger().debug("download.document", id="65601")
            logging.getLogger("some.library").info("connected")
        structlog.get_logger().info("run.end")
    inside_event, inside_record, outside = lines(path)
    context = span.get_span_context()
    for line in (inside_event, inside_record):
        assert (line["trace_id"], line["span_id"]) == (
            f"{context.trace_id:032x}",
            f"{context.span_id:016x}",
        )
    assert "trace_id" not in outside
    assert "span_id" not in outside


@pytest.mark.parametrize(
    "library", ["httpx", "httpcore.connection", "urllib3.connectionpool", "requests"]
)
def test_http_libraries_reach_the_file_from_warning(tmp_path: Path, library: str) -> None:
    """Their requests at DEBUG and INFO, with queries, stay out; their warnings go in."""
    with log_file(tmp_path, "download", RUN, NOW, COMMANDS) as path:
        logging.getLogger(library).debug("sending headers")
        logging.getLogger(library).info("GET https://example.invalid/media?token=%s", SENTINEL)
        logging.getLogger(library).warning("retrying")
    assert [(line["logger"], line["event"]) for line in lines(path)] == [(library, "retrying")]


def test_secrets_are_redacted_before_the_file(tmp_path: Path) -> None:
    """Under headers.Authorization or as a token, neither sentinel nor its base64 is written."""
    with log_file(tmp_path, "login", RUN, NOW, COMMANDS) as path:
        structlog.get_logger().warning(
            "sign_in.refused",
            status=401,
            headers={"Authorization": f"Basic {BASIC}", "Accept": "application/json"},
            api_token=SENTINEL,
        )
    written = path.read_text(encoding="utf-8")
    assert SENTINEL not in written
    assert BASIC not in written
    (line,) = lines(path)
    assert (line["headers"], line["api_token"]) == (
        {"Authorization": "[redacted]", "Accept": "application/json"},
        "[redacted]",
    )


def test_a_traceback_is_structured_and_shows_no_frame_s_locals(tmp_path: Path) -> None:
    """The exception's type, message and frames are there; what any frame held is not.

    The title is a local of the test's frame, and of json's frames as their argument.
    """
    with log_file(tmp_path, "index", RUN, NOW, COMMANDS) as path:
        try:
            title = SENTINEL
            json.loads(title)
        except ValueError:
            structlog.get_logger().exception("run.failed")
    assert SENTINEL not in path.read_text(encoding="utf-8")
    (line,) = lines(path)
    assert (line["level"], line["event"]) == ("error", "run.failed")
    (stack,) = line["exception"]
    assert stack["exc_type"] == "JSONDecodeError"
    assert stack["exc_value"] == "Expecting value: line 1 column 1 (char 0)"
    assert stack["frames"]
    assert all(frame.get("locals") is None for frame in stack["frames"])


def test_a_run_first_removes_the_program_s_log_files_past_30_days_and_leaves_the_rest(
    tmp_path: Path,
) -> None:
    """Of any of its commands, a run started over 30 days before now goes; the rest stays.

    Another command's goes too, so that a command not run again keeps none past 30 days;
    another program's, of the same shape, in a folder that it shares, is not this
    program's to remove.
    """
    folder = tmp_path / "logs"
    folder.mkdir()

    def name(command: str, age: timedelta, pid: int = 7) -> str:
        return f"{command}-{NOW - age:%Y%m%dT%H%M%SZ}-{pid}.jsonl"

    gone = [
        name("check", timedelta(days=30, seconds=1)),
        name("download", timedelta(days=400), 99999),
        name("login", timedelta(days=31)),
    ]
    kept = [
        name("nightly-backup", timedelta(days=400), 42),
        name("backup", timedelta(days=400), 42),
        name("index", timedelta(days=30)),
        name("check", timedelta(days=2)),
        name("eval", -timedelta(days=1)),
        "notes.txt",
        f"{name('check', timedelta(days=400))}.gz",
        name("check", timedelta(days=400)).removesuffix(".jsonl") + ".json",
    ]
    for file_name in [*gone, *kept]:
        (folder / file_name).write_text("{}\n", encoding="utf-8")
    with log_file(folder, "check", RUN, NOW, COMMANDS) as path:
        assert {file.name for file in folder.iterdir()} == {*kept, path.name}


def test_past_the_cap_a_line_log_capped_ends_the_file(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """The earliest lines, whole, as many as fit in the cap; then log.capped; then none."""
    cap = 100_000
    monkeypatch.setattr(logs, "CAP", cap)
    with log_file(tmp_path, "download", RUN, NOW, COMMANDS) as path:
        for count in range(1000):
            structlog.get_logger().debug("download.document", count=f"{count:03}")
        logging.getLogger("some.library").warning("after the cap")
    written = path.read_text(encoding="utf-8").splitlines()
    *documents, capped = map(json.loads, written)
    assert (capped["level"], capped["event"], capped["run"], capped["command"]) == (
        "warning",
        "log.capped",
        RUN,
        "download",
    )
    assert documents
    assert [line["count"] for line in documents] == [
        f"{count:03}" for count in range(len(documents))
    ]
    sizes = [len(f"{line}\n".encode()) for line in written[:-1]]
    assert sum(sizes) <= cap < sum(sizes) + max(sizes)


def test_a_file_that_stops_taking_lines_ends_saying_so_once_elsewhere(
    tmp_path: Path, monkeypatch: MonkeyPatch, capsys: CaptureFixture[str]
) -> None:
    """As on a full disk: the first line that fails ends the file, and no other is tried.

    ``log.unwritable`` names the folder and the reason, once, to the other sinks;
    logging prints no error of its own, and the file's close at the run's end raises
    nothing, though the lines it held were never written.
    """
    full = FullDisk(str(tmp_path / "check.jsonl"))
    monkeypatch.setattr(
        logs,
        "open",
        lambda *_, **__: io.TextIOWrapper(io.BufferedWriter(full), encoding="utf-8"),
        raising=False,
    )
    with capture_logs() as events, log_file(tmp_path, "check", RUN, NOW, COMMANDS):
        for count in range(3):
            logging.getLogger("some.library").warning("line %d", count)
    assert full.closed
    assert events == [
        {
            "event": "log.unwritable",
            "log_level": "warning",
            "folder": str(tmp_path),
            "reason": str(OSError(errno.ENOSPC, os.strerror(errno.ENOSPC))),
        }
    ]
    assert capsys.readouterr().err == ""


def test_the_cap_is_256_mib() -> None:
    """256 MiB, where a first download of 20,000 documents writes about 40 MB."""
    assert logs.CAP == 256 * 2**20


def test_the_default_folder_is_the_platform_s_log_folder_for_the_user(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """On macOS ~/Library/Logs/atlassian-offline-mcp, on Linux ~/.local/state's log folder."""
    monkeypatch.setenv("HOME", str(tmp_path))
    for variable in ("XDG_STATE_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME", "XDG_CONFIG_HOME"):
        monkeypatch.delenv(variable, raising=False)
    expected = {
        "darwin": tmp_path / "Library" / "Logs" / "atlassian-offline-mcp",
        "linux": tmp_path / ".local" / "state" / "atlassian-offline-mcp" / "log",
    }
    assert default_log_folder() == expected[sys.platform]


def test_each_test_s_log_folder_is_under_a_scratch_home() -> None:
    """So a full test run leaves the user's log folder as it was, as plan 016 requires."""
    home = Path(os.environ["HOME"])
    assert home != Path(pwd.getpwuid(os.getuid()).pw_dir)
    assert default_log_folder().is_relative_to(home)
