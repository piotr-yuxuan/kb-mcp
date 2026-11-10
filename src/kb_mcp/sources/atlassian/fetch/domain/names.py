"""Confluence's and Jira's names and types, each declared once: connectors, documents, scopes.

A connector's name is also its one source's, that source's table, folders and the front
matter's ``source``. A document type's plural is a folder of the raw store, its name the
front matter's ``type``. Standard library alone, as the declaration, which ``--help``
imports, reads it too (contract G).
"""

from __future__ import annotations

from kb_mcp.kernel.names import PROJECT_KEY, SPACE_KEY
from kb_mcp.sources.declaration import DocumentType, Option, ScopeType, key_of

CONFLUENCE = "confluence"
JIRA = "jira"
PAGE = DocumentType(name="page", plural="pages")
BLOGPOST = DocumentType(name="blogpost", plural="blogposts")
ISSUE = DocumentType(name="issue", plural="issues")
SPACE = ScopeType(
    name="space",
    key=SPACE_KEY,
    enumeration="listed",
    document_types=(PAGE, BLOGPOST),
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
)
