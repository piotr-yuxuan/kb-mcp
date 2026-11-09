"""The files that runs write their logs to: their names, and when they expire.

A run writes ``<command>-<start>-<pid>.jsonl``, its start in UTC as ``%Y%m%dT%H%M%SZ``,
so that a command's files sort by time and two runs never share one. A file of this
pattern expires once its run started more than 30 days ago, as its name says: its age
is read from its name, never from the file. It is the program's only if it is named
after one of its commands: in a folder that ``logs.dir`` shares with another program, a
file of the same shape named otherwise is that program's, and stays.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Collection

# A moment in a file's name, a run's start in its log file's or an evaluation's in its
# results': UTC, to the second.
STAMP = "%Y%m%dT%H%M%SZ"
# How long a log file is kept after its run started.
KEPT = timedelta(days=30)
# A log file's name: a subcommand's name, its run's start and its process's id.
LOG_FILE = re.compile(r"([a-z][a-z0-9-]*)-([0-9]{8}T[0-9]{6}Z)-[0-9]+\.jsonl")


def log_file_name(command: str, start: datetime, pid: int) -> str:
    """Name the log file of a run of ``command``, started at ``start`` (aware) by ``pid``."""
    return f"{command}-{start.astimezone(UTC):{STAMP}}-{pid}.jsonl"


def expired(name: str, commands: Collection[str], now: datetime) -> bool:
    """Say whether a file so named is a log file of one of ``commands``, over 30 days old.

    A name of this pattern whose start is no time, such as month 13, is no log file;
    nor is one named otherwise, such as another program's in the folder.
    """
    match = LOG_FILE.fullmatch(name)
    if match is None or match[1] not in commands:
        return False
    try:
        start = datetime.fromisoformat(match[2])
    except ValueError:
        return False
    return now - start > KEPT
