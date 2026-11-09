"""The work log's declaration: what it reads in place, its table, and its preparer.

Each resource type is a type of its documents: entries, days and meetings split from
``todo.org`` and its archive at their headings, transcripts read from ``transcripts/``
and ``meetings/``. Read in place, it has no fetcher.
"""

from __future__ import annotations

from kb_mcp.kernel.names import DAY_TYPE, ENTRY_TYPE, MEETING_TYPE, TRANSCRIPT_TYPE, WORKLOG_TYPES
from kb_mcp.sources.declaration import ResourceType, Source

WORKLOG = Source(
    name="worklog",
    help="The user's work log: org files read in place, never written",
    resource_types=(
        ResourceType(
            name=WORKLOG_TYPES[ENTRY_TYPE].plural, help="the entries of todo.org", read="in place"
        ),
        ResourceType(
            name=WORKLOG_TYPES[DAY_TYPE].plural, help="the days of todo.org", read="in place"
        ),
        ResourceType(
            name=WORKLOG_TYPES[MEETING_TYPE].plural,
            help="the meetings of todo.org",
            read="in place",
        ),
        ResourceType(
            name=WORKLOG_TYPES[TRANSCRIPT_TYPE].plural,
            help="the transcripts of transcripts/ and meetings/",
            read="in place",
        ),
    ),
    settings=("path", "archives"),
    table_path="kb_mcp.sources.worklog.settings:WorklogTable",
    preparers=("kb_mcp.sources.worklog.prepare.app.preparer",),
)
