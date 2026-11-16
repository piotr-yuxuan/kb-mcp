"""Confluence's and Jira's tables of settings, ``[sources.<name>]`` of each source.

Their declarations name them; the entry composes them into the settings' model. Each
source holds its site and its way to sign in, so that two sources of two sites are two
sources of one connector.
"""

from __future__ import annotations

import re
from typing import Annotated
from urllib.parse import urlsplit

from pydantic import AfterValidator, BaseModel, Field, SecretStr
from pydantic_core import PydanticCustomError

from kb_mcp.config.domain.settings import RULE, TABLE, matching
from kb_mcp.kernel.names import PROJECT_KEY, SPACE_KEY

# A host name: labels of letters, digits and inner hyphens, joined by dots; it names the
# folder of the site's session, so it is never empty, ``.`` nor ``..``.
HOST = re.compile(r"[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)*")


def site_address(value: str) -> str:
    """Give a site's address as ``https://<host>``; refuse one that is not a host alone."""
    try:
        parts = urlsplit(value)
        usable = (
            parts.scheme == "https"
            and HOST.fullmatch(parts.hostname or "") is not None
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
# The settings of a source's sign-in, which each table holds after its scopes: its site,
# then its account's email and API token, which sign in in place of the saved session.
SiteSetting = Annotated[
    Site | None,
    Field(description="The source's Atlassian site: https://<name>.atlassian.net."),
]
EmailSetting = Annotated[
    str | None, Field(description="The email address of the Atlassian account that signs in.")
]
TokenSetting = Annotated[
    SecretStr | None,
    Field(description="The Atlassian account's API token, a secret: from the environment alone."),
]


class ConfluenceTable(BaseModel):
    """A Confluence source: what to fetch when no flag says, on its site, and how it signs in."""

    model_config = TABLE

    spaces: tuple[SpaceKey, ...] = Field(
        default=(), description="The spaces to fetch when no --space is given, by key."
    )
    site: SiteSetting = None
    email: EmailSetting = None
    api_token: TokenSetting = None


class JiraTable(BaseModel):
    """A Jira source: what to fetch when no flag says, on its site, and how it signs in."""

    model_config = TABLE

    projects: tuple[ProjectKey, ...] = Field(
        default=(), description="The projects to fetch when no --project is given, by key."
    )
    site: SiteSetting = None
    email: EmailSetting = None
    api_token: TokenSetting = None
