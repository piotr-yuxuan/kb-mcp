"""The files that runs write their logs to: their names, and when they expire.

A run writes ``<command>-<start>-<pid>.jsonl``, its start in UTC as ``%Y%m%dT%H%M%SZ``,
so that a command's files sort by time and two runs never share one. A file of this
pattern expires once its run started more than 30 days ago, as its name says: its age
is read from its name, never from the file.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta

# A run's start in a log file's name: UTC, to the second.
STAMP = "%Y%m%dT%H%M%SZ"
# How long a log file is kept after its run started.
KEPT = timedelta(days=30)
# A log file's name: a subcommand's name, its run's start and its process's id.
LOG_FILE = re.compile(r"[a-z][a-z0-9-]*-([0-9]{8}T[0-9]{6}Z)-[0-9]+\.jsonl")


def log_file_name(command: str, start: datetime, pid: int) -> str:
    """Name the log file of a run of ``command``, started at ``start`` (aware) by ``pid``."""
    return f"{command}-{start.astimezone(UTC):{STAMP}}-{pid}.jsonl"


def expired(name: str, now: datetime) -> bool:
    """Say whether a file so named is a run's log file, its run started over 30 days ago.

    A name of this pattern whose start is no time, such as month 13, is no log file.
    """
    match = LOG_FILE.fullmatch(name)
    if match is None:
        return False
    try:
        start = datetime.fromisoformat(match[1])
    except ValueError:
        return False
    return now - start > KEPT
