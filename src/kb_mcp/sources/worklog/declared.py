"""The work log's declaration: what it reads in place, its table, and its preparer.

Each resource type is a type of its documents: entries, days and meetings split from
``todo.org`` and its archive at their headings, transcripts read from ``transcripts/``
and ``meetings/``. Read in place, it has no fetcher.
"""

from __future__ import annotations

from kb_mcp.sources.declaration import ResourceType, Source

WORKLOG = Source(
    name="worklog",
    help="The user's work log: org files read in place, never written",
    resource_types=(
        ResourceType(name="entries", help="the entries of todo.org", read="in place"),
        ResourceType(name="days", help="the days of todo.org", read="in place"),
        ResourceType(name="meetings", help="the meetings of todo.org", read="in place"),
        ResourceType(
            name="transcripts",
            help="the transcripts of transcripts/ and meetings/",
            read="in place",
        ),
    ),
    settings=("path", "archives"),
    table_path="kb_mcp.sources.worklog.settings:WorklogTable",
    preparers=("kb_mcp.sources.worklog.prepare.app.preparer",),
)
