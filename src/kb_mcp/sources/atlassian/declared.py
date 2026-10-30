"""Confluence's and Jira's declarations: what each reads of the site, and its table.

Each resource type is a kind that the raw store keeps. Both sign in with one Atlassian
account, its site's.
"""

from __future__ import annotations

from kb_mcp.sources.declaration import Account, Declared, ResourceType

ATLASSIAN = Account(name="atlassian", table="kb_mcp.sources.atlassian.settings:AtlassianAccount")
CONFLUENCE = Declared(
    name="confluence",
    summary="Confluence, on the Atlassian site: the pages and blog posts of its spaces",
    types=(
        ResourceType(name="pages", summary="a space's pages", read="listed"),
        ResourceType(name="blogposts", summary="a space's blog posts", read="listed"),
    ),
    settings=("spaces",),
    table="kb_mcp.sources.atlassian.settings:ConfluenceSource",
    account=ATLASSIAN,
)
JIRA = Declared(
    name="jira",
    summary="Jira, on the Atlassian site: the issues of its projects",
    types=(ResourceType(name="issues", summary="a project's issues", read="searched"),),
    settings=("projects",),
    table="kb_mcp.sources.atlassian.settings:JiraSource",
    account=ATLASSIAN,
)
