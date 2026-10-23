"""Log files' names, and which of them a run removes: the program's past 30 days, by name."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

import pytest

from atlassian_offline_mcp.observability.domain.log_files import expired, log_file_name

NOW = datetime(2026, 10, 22, 21, 5, 9, tzinfo=UTC)
# A start long past, as a log file's name writes it.
OLD = "20200101T000000Z"
# Commands of the program, as the command line gives them, some of them.
COMMANDS = frozenset({"check", "download", "eval", "index"})


def test_a_file_is_named_by_command_utc_start_and_process() -> None:
    """``<command>-<UTC %Y%m%dT%H%M%SZ>-<pid>.jsonl``, whatever the start's offset."""
    assert log_file_name("check", NOW, 4242) == "check-20261022T210509Z-4242.jsonl"
    paris = datetime(2026, 10, 22, 23, 5, 9, tzinfo=timezone(timedelta(hours=2)))
    assert log_file_name("download", paris, 7) == "download-20261022T210509Z-7.jsonl"


@pytest.mark.parametrize("command", ["check", "download", "eval", "index"])
@pytest.mark.parametrize(
    ("age", "gone"),
    [
        (timedelta(days=400), True),
        (timedelta(days=31), True),
        (timedelta(days=30, seconds=1), True),
        (timedelta(days=30), False),
        (timedelta(days=29, hours=23), False),
        (timedelta(0), False),
        (-timedelta(days=1), False),
    ],
)
def test_a_run_s_file_expires_once_its_run_started_over_30_days_ago(
    command: str, age: timedelta, *, gone: bool
) -> None:
    """Older than 30 days goes; 30 days to the second, younger, or ahead of the clock, stays.

    Whichever of the program's commands the name gives.
    """
    assert expired(log_file_name(command, NOW - age, 4242), COMMANDS, NOW) is gone


@pytest.mark.parametrize(
    "name",
    [
        "notes.txt",
        f"check-{OLD}-7.json",
        f"check-{OLD}.jsonl",
        f"check-{OLD}-7.jsonl.gz",
        f"check-{OLD}-7.jsonl~",
        f".check-{OLD}-7.jsonl",
        f"-{OLD}-7.jsonl",
        f"check-{OLD}-.jsonl",
        "check-2020-01-01T00:00:00Z-7.jsonl",
        "check-20200101T000000-7.jsonl",
        "check-20201301T000000Z-7.jsonl",
        "check-20200230T000000Z-7.jsonl",
        f"backup-{OLD}-7.jsonl",
        f"nightly-backup-{OLD}-7.jsonl",
        f"check-backup-{OLD}-7.jsonl",
    ],
)
def test_no_other_file_expires_however_old_it_says_it_is(name: str) -> None:
    """Another suffix, a part missing, another way to write the start, or no such time.

    Nor does one named after no command of the program, such as another program's of
    the same shape, which a folder shared with it may hold.
    """
    assert not expired(name, COMMANDS, NOW)
