"""Confluence's and Jira's names, each spelt once: the sources, resource types, document types.

A source's name is also its table, its folders and the front matter's ``source``; a
resource type's, plural, is a folder of the raw store; a document type's, singular, is
the front matter's ``type``. Standard library alone, as the declaration, which ``--help``
imports, reads it too (contract G).
"""

from __future__ import annotations

CONFLUENCE = "confluence"
JIRA = "jira"
# Each resource type, then its document type.
PAGES, PAGE = "pages", "page"
BLOGPOSTS, BLOGPOST = "blogposts", "blogpost"
ISSUES, ISSUE = "issues", "issue"
