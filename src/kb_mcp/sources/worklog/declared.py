"""The work log's connector: what it reads in place, its table, and its preparer.

Its one scope type, read in place, holds a document type for each of the work log's:
entries, days and meetings split from ``todo.org`` and its archive at their headings,
transcripts read from ``transcripts/`` and ``meetings/``. Read in place, it has no fetcher.
"""

from __future__ import annotations

from kb_mcp.kernel.names import WORKLOG_TYPES
from kb_mcp.sources.declaration import Connector, DocumentType, ScopeType

WORKLOG = Connector(
    name="worklog",
    help="The user's work log: org files read in place, never written",
    scope_types=(
        ScopeType(
            name="folder",
            key=None,
            enumeration="in place",
            document_types=tuple(
                DocumentType(name=name, plural=each.plural) for name, each in WORKLOG_TYPES.items()
            ),
        ),
    ),
    settings=("path", "archives"),
    table_path="kb_mcp.sources.worklog.settings:WorklogTable",
    preparers=("kb_mcp.sources.worklog.prepare.app.preparer",),
)
