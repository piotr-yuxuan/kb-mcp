"""Observing a run: stderr from WARNING until its settings are read, then at its level."""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

import pytest
import structlog

from atlassian_offline_mcp.kernel.exit_status import ExitStatus
from atlassian_offline_mcp.kernel.output import Output
from atlassian_offline_mcp.observability.app.observed import early, observed

if TYPE_CHECKING:
    from _pytest.capture import CaptureFixture

    from atlassian_offline_mcp.kernel.output import Level

# A log line on stderr: its time, its level padded in brackets, its event, then the rest.
LOG_LINE = re.compile(r"\S+ \[(\w+) *\] (\S+)")


def said(err: str) -> list[tuple[str, ...]]:
    """Give the level and the event of each log line on stderr, in order."""
    return [match.groups() for match in map(LOG_LINE.match, err.splitlines()) if match]


def output(level: Level) -> Output:
    """Give how a run reports at a level, stderr piped."""
    return Output(level, "short", "text", quiet=False, stdin_terminal=False, stderr_terminal=False)


def test_before_the_settings_are_read_stderr_says_warnings_and_stdout_nothing(
    capsys: CaptureFixture[str],
) -> None:
    """Events and libraries' records from WARNING; structlog would print on stdout else."""
    with early():
        structlog.get_logger().info("early.info")
        structlog.get_logger().warning("early.warning")
        logging.getLogger("some.library").info("early.noise")
        logging.getLogger("some.library").error("early.record")
    out, err = capsys.readouterr()
    assert out == ""
    assert said(err) == [("warning", "early.warning"), ("error", "early.record")]


def test_leaving_early_puts_structlog_and_the_loggers_back() -> None:
    """The root's level and handlers, and those of the HTTP libraries, are as they were."""
    root, httpx = logging.getLogger(), logging.getLogger("httpx")
    before = (root.level, list(root.handlers), httpx.level)
    with early():
        assert structlog.is_configured()
    assert (root.level, list(root.handlers), httpx.level) == before
    assert not structlog.is_configured()


def test_a_run_s_stderr_takes_the_place_of_early_s_and_gives_it_back(
    capsys: CaptureFixture[str],
) -> None:
    """At the run's level while it lasts, each line once; from WARNING again after."""
    with early():
        with observed(output("debug"), None, None, "check", {}):
            structlog.get_logger().debug("run.inside")
        structlog.get_logger().info("early.info")
        structlog.get_logger().warning("early.warning")
    assert said(capsys.readouterr().err) == [
        ("info", "run.start"),
        ("debug", "run.inside"),
        ("info", "run.end"),
        ("warning", "early.warning"),
    ]


@pytest.mark.parametrize(
    ("raised", "status", "ending"),
    [
        (None, 3, ("info", "run.end")),
        (ValueError("the run broke"), ExitStatus.FAILED, ("error", "run.failed")),
        (KeyboardInterrupt(), ExitStatus.INTERRUPTED, ("warning", "run.interrupted")),
    ],
)
def test_a_run_ends_with_its_body_s_status_or_as_failed_or_interrupted(
    capsys: CaptureFixture[str],
    raised: BaseException | None,
    status: int,
    ending: tuple[str, str],
) -> None:
    """What the body lets through is said, and goes no further: its status says it."""
    with early(), observed(output("info"), None, None, "check", {}) as run:
        run.status = 3
        if raised is not None:
            raise raised
    assert run.status == status
    assert said(capsys.readouterr().err) == [("info", "run.start"), ending]
