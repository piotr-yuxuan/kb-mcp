"""Confluence's and Jira's names and types, each declared once: connectors, documents, scopes.

A connector's name is also that of the source declared for it. Standard library alone,
as the declaration, which ``--help`` imports, reads it too (contract G).
"""

from __future__ import annotations

from datetime import timedelta

from kb_mcp.sources.atlassian import PROJECT_KEY, SPACE_KEY
from kb_mcp.sources.declaration import DocumentType, Option, ScopeType, key_of

CONFLUENCE = "confluence"
JIRA = "jira"
PAGE = DocumentType(name="page", plural="pages")
BLOGPOST = DocumentType(name="blogpost", plural="blogposts")
FOLDER = DocumentType(name="folder", plural="folders", container=True)
ISSUE = DocumentType(name="issue", plural="issues")
SPACE = ScopeType(
    name="space",
    key=SPACE_KEY,
    enumeration="listed",
    document_types=(PAGE, BLOGPOST, FOLDER),
    option=Option(
        flag="--space",
        help="a space key, in place of the setting's; repeat for more",
        parse=key_of("space", SPACE_KEY),
        setting="spaces",
    ),
)
PROJECT = ScopeType(
    name="project",
    key=PROJECT_KEY,
    enumeration="searched",
    document_types=(ISSUE,),
    option=Option(
        flag="--project",
        help="a project key, in place of the setting's; repeat for more",
        parse=key_of("project", PROJECT_KEY),
        setting="projects",
    ),
    # A search by update time sees no deletion: a week bounds how long a deleted issue
    # stays, at the cost of one listing of the project's issue ids a week.
    whole_read_every=timedelta(days=7),
)
