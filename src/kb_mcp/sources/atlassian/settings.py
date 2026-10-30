"""Confluence's and Jira's tables of settings, ``[sources.confluence]`` and ``[sources.jira]``.

Their declarations name them; the entry composes them into the settings' model.
"""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, Field

from kb_mcp.config.domain.settings import TABLE, matching
from kb_mcp.kernel.names import PROJECT_KEY, SPACE_KEY

SpaceKey = Annotated[str, matching(SPACE_KEY, "a space key, such as ENG or ~5f1a2b")]
ProjectKey = Annotated[str, matching(PROJECT_KEY, "a project key, such as PLAT")]


class ConfluenceSource(BaseModel):
    """What to download from Confluence when no flag says."""

    model_config = TABLE

    spaces: tuple[SpaceKey, ...] = Field(
        default=(), description="The spaces to download when no --space is given, by key."
    )


class JiraSource(BaseModel):
    """What to download from Jira when no flag says."""

    model_config = TABLE

    projects: tuple[ProjectKey, ...] = Field(
        default=(), description="The projects to download when no --project is given, by key."
    )
