"""The names of the mirror: the rules of its sources' names, ids, keys and revisions.

A value that breaks a rule is refused where a domain type is built, by ``require``,
with a ``RefusedError`` that names the field and the rule, never the value.
"""

from __future__ import annotations

import re

# The mirror's folder of the files that Confluence's and Jira's documents attach,
# docs/assets/: no document is under it, and no source's folder may be it.
ASSETS = "assets"
# A source's name, and a type of its documents, as the front matter names them.
SOURCE_NAME = re.compile(r"[a-z][a-z0-9]*")
TYPE_NAME = re.compile(r"[a-z]+")
# An id names a folder of the raw store, so it must be one safe path part.
IDENTIFIER = re.compile(r"[A-Za-z0-9_-]+")
# A revision's name, whichever source names it: one token, which each source's rule
# narrows.
REVISION_NAME = re.compile(r"[A-Za-z0-9._-]+")
# A Confluence space key; a personal space's key begins with a tilde.
SPACE_KEY = re.compile(r"~?[A-Za-z0-9]+")
PROJECT_KEY = re.compile(r"[A-Z][A-Z0-9_]+")
ISSUE_KEY = re.compile(r"[A-Z][A-Z0-9_]+-[0-9]+")
# An embedding model's name, as the endpoint names it: the settings and the command
# line check it alike.
MODEL_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}")
# A work-log document's id, by its type: an entry's digest, numbered from the second
# entry of one digest; a transcript's day and name, or its digest; a day's date; a
# meeting's day and title's slug, numbered after -- from the second meeting of one day
# and slug.
WORKLOG_IDS = {
    "entry": re.compile(r"e-[0-9a-f]{16}(?:-[0-9]+)?"),
    "transcript": re.compile(r"t-(?:[0-9]{8}-[A-Za-z0-9_-]{1,64}|[0-9a-f]{16})"),
    "day": re.compile(r"d-[0-9]{8}"),
    "meeting": re.compile(r"m-[0-9]{8}-[a-z0-9-]{1,64}"),
}
# Any work-log document's id, of whichever type.
WORKLOG_ID = re.compile("|".join(f"(?:{each.pattern})" for each in WORKLOG_IDS.values()))


class RefusedError(ValueError):
    """A value that a domain type refuses; the message names the field, never the value."""


def require(pattern: re.Pattern[str], value: str, name: str) -> None:
    """Refuse a value that does not match its rule, naming the field and the rule."""
    if not pattern.fullmatch(value):
        message = f"{name}: does not match {pattern.pattern}"
        raise RefusedError(message)
