"""The display's log lines: on stderr's console at a level, inert, coloured on a terminal."""

from __future__ import annotations

import base64
import io
import json
import logging
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
import structlog
from rich.console import Console

from atlassian_offline_mcp.observability.adapters.display import ConsoleLines
from atlassian_offline_mcp.observability.adapters.logs import log_file, route_through_logging

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from _pytest.monkeypatch import MonkeyPatch

NOW = datetime(2026, 10, 22, 21, 5, 9, tzinfo=UTC)
RUN = "0123456789abcdef"
SENTINEL = "sentinel-token-3f8a"
BASIC = base64.b64encode(f"tests@example.invalid:{SENTINEL}".encode()).decode()
# The loggers whose levels a test changes, the root's first.
CHANGED = ("", "httpx", "httpcore", "urllib3", "requests")
# Criterion 6's title: an escape sequence, a bell, a right-to-left override and markup,
# on two lines.
TITLE = "Release \x1b[31mnotes\x07 \N{RIGHT-TO-LEFT OVERRIDE}plan [red]draft\nsecond line"
# The title as the console shows it.
INERT = "Release [31mnotes plan [red]draft second line"


@pytest.fixture(autouse=True)
def through_logging() -> Iterator[None]:
    """Route structlog through the standard library for one test, then undo it."""
    levels = {name: logging.getLogger(name).level for name in CHANGED}
    route_through_logging()
    yield
    structlog.reset_defaults()
    for name, level in levels.items():
        logging.getLogger(name).setLevel(level)


@contextmanager
def drawn(console: Console, level: int = logging.DEBUG) -> Iterator[None]:
    """Draw events and records on a console, at a level, within."""
    handler = ConsoleLines(console, level)
    logging.getLogger().addHandler(handler)
    try:
        yield
    finally:
        logging.getLogger().removeHandler(handler)


def piped() -> Console:
    """Give a console as stderr is when piped: no terminal, so no colour, and no width."""
    return Console(file=io.StringIO(), force_terminal=False)


def written(console: Console) -> str:
    """Give what was drawn on a console made by ``piped`` or alike."""
    file = console.file
    assert isinstance(file, io.StringIO)
    return file.getvalue()


def test_the_console_shows_what_is_of_its_level_or_above_one_line_each() -> None:
    """An event's level, name and fields; a library's record alike; below the level, nothing."""
    console = piped()
    with drawn(console, logging.INFO):
        structlog.get_logger().debug("download.document", id="65601")
        structlog.get_logger().info("download.listed", pages=3)
        logging.getLogger("some.library").warning("retrying %s", "the site")
    first, second = written(console).splitlines()
    assert "[info     ] download.listed" in first
    assert "pages=3" in first
    assert "[warning  ] retrying the site" in second
    assert "[some.library]" in second
    assert "65601" not in written(console)


def test_the_site_s_text_reaches_the_console_inert_on_one_line() -> None:
    """ESC, BEL and U+202E go, [red] stays as written, and a line break is a space.

    So in an event's field and in a library's message, on a terminal in colour.
    """
    console = Console(file=io.StringIO(), force_terminal=True, color_system="truecolor")
    with drawn(console):
        structlog.get_logger().warning("download.skipped", title=TITLE)
        logging.getLogger("some.library").warning("skipped %s", TITLE)
    out = written(console)
    for control in ("\x07", "\N{RIGHT-TO-LEFT OVERRIDE}", "\x1b[31mnotes"):
        assert control not in out
    event, record = out.splitlines()
    assert INERT in event
    assert f"skipped {INERT}" in record


def test_on_a_terminal_a_text_is_cut_to_its_width_and_piped_it_is_whole() -> None:
    """A title longer than the terminal ends with an ellipsis; piped, it is all there."""
    title = "A" * 120
    terminal = Console(file=io.StringIO(), force_terminal=True, color_system=None, width=40)
    console = piped()
    for each in (terminal, console):
        with drawn(each):
            structlog.get_logger().warning("download.skipped", title=title)
    assert f"title={'A' * 39}…" in written(terminal)
    assert title not in written(terminal)
    assert f"title={title}" in written(console)


@pytest.mark.parametrize(
    ("terminal", "no_color", "coloured"),
    [(True, "", True), (True, "1", False), (False, "", False)],
)
def test_the_console_is_coloured_on_a_terminal_without_no_color_alone(
    monkeypatch: MonkeyPatch, *, terminal: bool, no_color: str, coloured: bool
) -> None:
    """No escape byte at all piped, or under NO_COLOR, which an empty value leaves unset."""
    monkeypatch.setenv("NO_COLOR", no_color)
    console = Console(file=io.StringIO(), force_terminal=terminal, color_system="standard")
    with drawn(console):
        structlog.get_logger().warning("download.skipped", id="65601")
    assert ("\x1b" in written(console)) is coloured


def test_a_traceback_on_the_console_shows_no_frame_s_locals() -> None:
    """The exception's type and message follow the event; what any frame held does not."""
    console = piped()
    with drawn(console):
        try:
            title = SENTINEL
            json.loads(title)
        except ValueError:
            structlog.get_logger().exception("run.failed")
    out = written(console)
    assert "run.failed" in out
    assert "Traceback (most recent call last):" in out
    assert "JSONDecodeError: Expecting value: line 1 column 1 (char 0)" in out
    assert SENTINEL not in out


def test_secrets_are_redacted_before_the_console() -> None:
    """Under headers.Authorization or as a token, neither sentinel nor its base64 is shown."""
    console = piped()
    with drawn(console):
        structlog.get_logger().warning(
            "sign_in.refused", headers={"Authorization": f"Basic {BASIC}"}, api_token=SENTINEL
        )
    out = written(console)
    assert SENTINEL not in out
    assert BASIC not in out
    assert "[redacted]" in out


def test_the_sdk_s_own_records_stay_off_the_console(tmp_path: Path) -> None:
    """They go to the file alone, whatever their level; a library named alike is shown."""
    console = piped()
    with drawn(console), log_file(tmp_path, "check", RUN, NOW) as path:
        logging.getLogger("opentelemetry").error("export failed")
        logging.getLogger("opentelemetry.sdk.trace.export").error("export failed again")
        logging.getLogger("opentelemetry_like").error("not the SDK")
    events = [json.loads(line)["event"] for line in path.read_text("utf-8").splitlines()]
    assert events == ["export failed", "export failed again", "not the SDK"]
    (shown,) = written(console).splitlines()
    assert "not the SDK" in shown
