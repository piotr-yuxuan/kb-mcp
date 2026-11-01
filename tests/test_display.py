"""The display: log lines on stderr's console at a level, inert, coloured on a terminal; bars."""

from __future__ import annotations

import base64
import io
import json
import logging
import re
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
import structlog
from rich.console import Console
from rich.progress import Progress

from kb_mcp.observability.adapters import progress
from kb_mcp.observability.adapters.display import Bars, ConsoleLines, Remaining
from kb_mcp.observability.adapters.logs import log_file, route_through_logging

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
        structlog.get_logger().debug("fetch.document", id="65601")
        structlog.get_logger().info("fetch.listed", pages=3)
        logging.getLogger("some.library").warning("retrying %s", "the site")
    first, second = written(console).splitlines()
    assert "[info     ] fetch.listed" in first
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
        structlog.get_logger().warning("fetch.skipped", title=TITLE)
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
            structlog.get_logger().warning("fetch.skipped", title=title)
    assert f"title={'A' * 39}…" in written(terminal)
    assert title not in written(terminal)
    assert f"title={title}" in written(console)


def test_on_a_terminal_the_program_s_own_text_is_whole_and_inert() -> None:
    """The event, a reason, an error, a path and a library's message are never cut.

    Wider than the terminal, which wraps them, each is whole, its controls taken out,
    while a title from the site beside them is cut.
    """
    long = "b" * 60
    terminal = Console(file=io.StringIO(), force_terminal=True, color_system=None, width=40)
    with drawn(terminal):
        structlog.get_logger().error(
            f"eval.{long}",
            reason=f"/golden/{long}.yaml: not a\x07 file",
            error=f"{long}\N{RIGHT-TO-LEFT OVERRIDE}",
            path=f"/given/{long}",
            title="A" * 120,
        )
        logging.getLogger("some.library").warning("retrying %s", f"{long}\x07")
    event, record = written(terminal).splitlines()
    assert f" eval.{long} " in event
    assert f"reason='/golden/{long}.yaml: not a file'" in event
    assert f"error={long} " in event
    assert f"path=/given/{long} " in event
    assert f"title={'A' * 39}…" in event
    assert record.endswith(f"retrying {long} [some.library]")


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
        structlog.get_logger().warning("fetch.skipped", id="65601")
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


def test_a_traceback_on_the_console_is_inert_whole_and_indented() -> None:
    """An exception's message with the site's text: each line inert, none cut, as indented.

    On a terminal in colour, narrower than the message.
    """
    console = Console(file=io.StringIO(), force_terminal=True, color_system="truecolor", width=40)
    long = "b" * 60
    failure = ValueError(f"{TITLE} {long}")
    with pytest.raises(ValueError, match="second line") as raised:
        raise failure
    with drawn(console):
        structlog.get_logger().error("run.failed", exc_info=raised.value)
    out = written(console)
    for control in ("\x07", "\N{RIGHT-TO-LEFT OVERRIDE}", "\x1b[31mnotes"):
        assert control not in out
    lines = out.splitlines()
    assert "ValueError: Release [31mnotes plan [red]draft" in lines
    assert f"second line {long}" in lines
    assert any(line.startswith('  File "') for line in lines)
    assert "    raise failure" in lines


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
    with drawn(console), log_file(tmp_path, "check", RUN, NOW, {"check"}) as path:
        logging.getLogger("opentelemetry").error("export failed")
        logging.getLogger("opentelemetry.sdk.trace.export").error("export failed again")
        logging.getLogger("opentelemetry_like").error("not the SDK")
    events = [json.loads(line)["event"] for line in path.read_text("utf-8").splitlines()]
    assert events == ["export failed", "export failed again", "not the SDK"]
    (shown,) = written(console).splitlines()
    assert "not the SDK" in shown


@dataclass
class Clock:
    """A clock that says the time it is set to, in seconds."""

    now: float = 0.0

    def __call__(self) -> float:
        """Say the time."""
        return self.now


def drawn_now(bars: Bars) -> str:
    """Give the bars as they would be drawn now, as text on a wide console."""
    console = Console(file=io.StringIO(), force_terminal=False, width=200)
    console.print(bars.progress)
    return written(console)


def test_a_task_s_line_shows_its_name_bar_items_times_and_item_inert() -> None:
    """The item, a title from the site, passes printable() and is no markup: [red] stays."""
    bars = Bars(Console(file=io.StringIO(), force_terminal=True, width=200), shown=True)
    with progress.drawn(bars), progress.task("documents", 4) as documents:
        lines = [drawn_now(bars) for _ in documents.each([TITLE], str)]
    (line,) = lines
    assert re.fullmatch(rf"documents [━╸╺ ]+ 0/4 0:00:00 -:--:-- {re.escape(INERT)} *\n", line)


def test_a_task_of_no_known_total_shows_its_count_alone() -> None:
    """A listing's pages: a question mark for the total, dashes for the time left."""
    bars = Bars(Console(file=io.StringIO(), force_terminal=True, width=200), shown=True)
    with progress.drawn(bars), progress.task("listing") as listing:
        listing.advance()
        line = drawn_now(bars)
    assert re.fullmatch(r"listing [━╸╺ ]+ 1/\? 0:00:00 -:--:-- *\n", line)


def test_the_time_left_is_at_the_pace_kept_and_unknown_before_an_item_is_done() -> None:
    """One text of four embedded in 30 s: 1 min 30 s left; none done, or no total: dashes."""
    clock = Clock()
    bars = Progress(get_time=clock, disable=True)
    texts = bars.add_task("texts to embed", total=4)
    listing = bars.add_task("listing", total=None)
    assert [Remaining().render(each).plain for each in bars.tasks] == ["-:--:--", "-:--:--"]
    clock.now = 30.0
    bars.update(texts, completed=1)
    bars.update(listing, completed=3)
    assert [Remaining().render(each).plain for each in bars.tasks] == ["0:01:30", "-:--:--"]


def test_bars_are_drawn_while_a_task_runs_and_the_last_to_end_takes_them_away() -> None:
    """Each task's last state is drawn; once none runs, the console's cursor is back."""
    console = Console(file=io.StringIO(), force_terminal=True, color_system=None, width=100)
    bars = Bars(console, shown=True)
    with progress.drawn(bars):
        with progress.task("targets", 2) as targets:
            with progress.task("documents", 3) as documents:
                documents.advance(3)
            assert bars.progress.live.is_started
            targets.advance()
        assert not bars.progress.live.is_started
    out = written(console)
    assert re.search(r"documents [━╸╺ ]+ 3/3 0:00:00 0:00:00", out)
    assert re.search(r"targets [━╸╺ ]+ 1/2 0:00:00 0:00:00", out)
    assert out.endswith("\x1b[?25h")


def test_a_task_begun_once_the_bars_are_gone_brings_them_back() -> None:
    """As index's texts to embed after its files: each is drawn, the cursor hidden for each."""
    console = Console(file=io.StringIO(), force_terminal=True, color_system=None, width=100)
    tasks = ("files", "texts to embed")
    with progress.drawn(Bars(console, shown=True)):
        for what in tasks:
            with progress.task(what, 1) as running:
                running.advance()
    out = written(console)
    for what in tasks:
        assert re.search(rf"{what} [━╸╺ ]+ 1/1 ", out)
    assert out.count("\x1b[?25l") == out.count("\x1b[?25h") == len(tasks)


def test_bars_not_shown_draw_nothing() -> None:
    """As piped, or with -q: the task runs, and the console is left as it was."""
    console = Console(file=io.StringIO(), force_terminal=True, width=100)
    with progress.drawn(Bars(console, shown=False)), progress.task("files", 2) as files:
        files.advance(2)
    assert written(console) == ""
