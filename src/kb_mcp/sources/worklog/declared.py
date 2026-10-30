"""The work log's declaration: what it reads in place, and its table.

Each resource type is a type of its documents: entries, days and meetings split from
``todo.org`` and its archive at their headings, transcripts read from ``transcripts/``
and ``meetings/``.
"""

from __future__ import annotations

from kb_mcp.sources.declaration import Declared, ResourceType

WORKLOG = Declared(
    name="worklog",
    summary="The user's work log: org files read in place, never written",
    types=(
        ResourceType(name="entries", summary="the entries of todo.org", read="in place"),
        ResourceType(name="days", summary="the days of todo.org", read="in place"),
        ResourceType(name="meetings", summary="the meetings of todo.org", read="in place"),
        ResourceType(
            name="transcripts",
            summary="the transcripts of transcripts/ and meetings/",
            read="in place",
        ),
    ),
    settings=("path", "archives"),
    table="kb_mcp.sources.worklog.settings:WorklogSource",
)
