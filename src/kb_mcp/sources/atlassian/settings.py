"""Confluence's and Jira's tables of settings, and the Atlassian account's.

``[sources.confluence]``, ``[sources.jira]`` and ``[accounts.atlassian]``: their
declarations name them; the entry composes them into the settings' model.
"""

from __future__ import annotations

from typing import Annotated
from urllib.parse import urlsplit

from pydantic import AfterValidator, BaseModel, Field, SecretStr
from pydantic_core import PydanticCustomError

from kb_mcp.config.domain.settings import RULE, TABLE, matching
from kb_mcp.kernel.names import PROJECT_KEY, SPACE_KEY


def site_address(value: str) -> str:
    """Give a site's address as ``https://<host>``; refuse one that is not a host alone."""
    try:
        parts = urlsplit(value)
        usable = (
            parts.scheme == "https"
            and bool(parts.hostname)
            and parts.netloc.lower() == parts.hostname
            and parts.path in {"", "/"}
        )
    except ValueError:  # such as an unclosed [ in the host
        usable = False
    if not usable:
        message = "an https address with a host name alone, such as https://x.atlassian.net"
        raise PydanticCustomError(RULE, message)
    return f"https://{parts.hostname}"


Site = Annotated[str, AfterValidator(site_address)]
SpaceKey = Annotated[str, matching(SPACE_KEY, "a space key, such as ENG or ~5f1a2b")]
ProjectKey = Annotated[str, matching(PROJECT_KEY, "a project key, such as PLAT")]


class AtlassianAccount(BaseModel):
    """The Atlassian account that Confluence and Jira sign in with, on its site."""

    model_config = TABLE

    site: Site | None = Field(
        default=None,
        description=(
            "The Atlassian site, for Confluence and Jira alike: https://<name>.atlassian.net."
        ),
    )
    email: str | None = Field(
        default=None, description="The email address of the Atlassian account that signs in."
    )
    api_token: SecretStr | None = Field(
        default=None,
        description="The Atlassian account's API token, a secret: from the environment alone.",
    )


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
