"""The program's name, and the mirror's: the rules of its sources' names, ids, keys and revisions.

A value that breaks a rule is refused where a domain type is built, by ``require``,
with a ``RefusedError`` that names the field and the rule, never the value.
"""

from __future__ import annotations

import re

# The program's name, as pyproject.toml names its script: its command, its log folder,
# and the name by which MCP clients know its server.
PROGRAM = "kb-mcp"
# Each setting's environment variable: the prefix, then its path in capitals, joined.
PREFIX = "KB_MCP_"
NESTING = "__"
# The mirror's folder of the files that Confluence's and Jira's documents attach,
# docs/assets/: no document is under it, and no source's folder may be it.
ASSETS = "assets"
# The raw store's folder of the files that documents attach, beside each source's.
BLOBS = "blobs"
# A source's name, and a type of its documents, as the front matter names them; no
# source takes ``assets`` nor ``blobs``, folders beside the sources', nor the schemes of
# a web address, which a link to a source's document would read as.
SOURCE_NAME = re.compile(r"[a-z][a-z0-9]*")
RESERVED = (ASSETS, BLOBS, "http", "https")
# The setting of each source's table that names its connector.
CONNECTOR = "connector"
# A run's id, as a run makes it and names its record's folder: 16 lower-case hex digits.
RUN_ID = re.compile(r"[0-9a-f]{16}")
TYPE_NAME = re.compile(r"[a-z]+")
# An id names a folder of the raw store, so it must be one safe path part.
IDENTIFIER = re.compile(r"[A-Za-z0-9_-]+")
# A revision's name, whichever source names it: one token, which each source's rule
# narrows.
REVISION_NAME = re.compile(r"[A-Za-z0-9._-]+")
# A document id, as a parent and a link name a document: its source, a colon, its id.
DOCUMENT_ID = re.compile(rf"{SOURCE_NAME.pattern}:{IDENTIFIER.pattern}")
# A scope, as a document names the one that holds it: its scope type, a colon, its key,
# which each scope type's rule narrows.
SCOPE = re.compile(r"[a-z]+:[~A-Za-z0-9_-]+")
ISSUE_KEY = re.compile(r"[A-Z][A-Z0-9_]+-[0-9]+")
# A mention's identity: its issuer, a colon, then the value that the issuer gave, which
# may hold colons itself.
IDENTITY = re.compile(r"[a-z][a-z0-9-]*:.+")
# The issuer of the identities of every Atlassian cloud site, Confluence's and Jira's.
ATLASSIAN_ISSUER = "atlassian"
# An embedding model's name, as the endpoint names it: the settings and the command
# line check it alike.
MODEL_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}")


# The work log's one scope type, read in place, whose one scope is the whole source.
WORKLOG_SCOPE_TYPE = "folder"


class RefusedError(ValueError):
    """A value that a domain type refuses; the message names the field, never the value."""


class StoreBusyError(RuntimeError):
    """Another run holds the lock of a store that this one would write."""


def require(pattern: re.Pattern[str], value: str, name: str) -> None:
    """Refuse a value that does not match its rule, naming the field and the rule."""
    if not pattern.fullmatch(value):
        message = f"{name}: does not match {pattern.pattern}"
        raise RefusedError(message)
