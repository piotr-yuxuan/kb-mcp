"""The work log's table of settings, ``[sources.worklog]``.

Its declaration names it; the entry composes it into the settings' model.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from kb_mcp.config.domain.settings import TABLE, LocalPath


class WorklogTable(BaseModel):
    """The user's work log, read in place and never written."""

    model_config = TABLE

    path: LocalPath | None = Field(
        default=None,
        description=(
            "The work log's folder, absolute or under ~, which holds todo.org,"
            " todo.org_archive, transcripts/ and meetings/; read in place, never written."
        ),
    )
    archives: bool = Field(
        default=True,
        description=(
            "Whether todo.org_archive, transcripts/archive/, meetings/archive/ and the"
            " subtrees tagged ARCHIVE are mirrored too."
        ),
    )
