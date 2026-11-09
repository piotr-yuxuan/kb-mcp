"""The memo source's table of settings, ``[sources.memo]``.

Its declaration names it; the entry composes it into the settings' model.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from kb_mcp.config.domain.settings import TABLE, LocalPath


class MemoTable(BaseModel):
    """The folder of the notes, read in place and never written."""

    model_config = TABLE

    folder: LocalPath | None = Field(
        default=None,
        description="The notes' folder, absolute or under ~: its *.txt files, read in place.",
    )
