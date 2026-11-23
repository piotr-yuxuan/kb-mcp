"""The user's work log: org files read in place, never written; its documents' types.

What its declaration, its fetch and its prepare share, light, as the declaration is.
"""

from __future__ import annotations

import re
from typing import NamedTuple


class WorklogType(NamedTuple):
    """A type of the work log's documents: its plural, its id's rule, its file's name.

    ``plural`` names its folder of the mirror; a type
    ``named_by_id`` names its file by its id alone, which holds what a title would add.
    """

    plural: str
    id_rule: re.Pattern[str]
    named_by_id: bool


# The work log's document types, as the front matter names them, each with its own.
ENTRY_TYPE, TRANSCRIPT_TYPE, DAY_TYPE, MEETING_TYPE = "entry", "transcript", "day", "meeting"
WORKLOG_TYPES = {
    ENTRY_TYPE: WorklogType(
        "entries", re.compile(r"e-[0-9a-f]{16}(?:-[0-9]+)?"), named_by_id=False
    ),
    TRANSCRIPT_TYPE: WorklogType(
        "transcripts",
        re.compile(r"t-(?:[0-9]{8}-[A-Za-z0-9_-]{1,64}|[0-9a-f]{16})"),
        named_by_id=False,
    ),
    DAY_TYPE: WorklogType("days", re.compile(r"d-[0-9]{8}"), named_by_id=True),
    MEETING_TYPE: WorklogType(
        "meetings", re.compile(r"m-[0-9]{8}-[a-z0-9-]{1,64}"), named_by_id=True
    ),
}
