"""The names of the mirror: its sources, and the rules of its ids, keys and revisions.

A value that breaks a rule is refused where a domain type is built, by ``require``,
with a ``RefusedError`` that names the field and the rule, never the value.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Literal

# The sources of the mirror, as sync's --include and --exclude name them.
type SourceName = Literal["confluence", "jira", "worklog"]
SOURCE_NAMES: tuple[SourceName, ...] = ("confluence", "jira", "worklog")
# An id names a folder of the raw store, so it must be one safe path part.
IDENTIFIER = re.compile(r"[A-Za-z0-9_-]+")
# A Confluence space key; a personal space's key begins with a tilde.
SPACE_KEY = re.compile(r"~?[A-Za-z0-9]+")
PROJECT_KEY = re.compile(r"[A-Z][A-Z0-9_]+")
ISSUE_KEY = re.compile(r"[A-Z][A-Z0-9_]+-[0-9]+")
# An embedding model's name, as the endpoint names it: the settings and the command
# line check it alike.
MODEL_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}")
# A path on the site, never another host's: one slash, no second one, no backslash, no
# control character.
SITE_PATH = re.compile(r"/(?![/\\])[^\s\\\x00-\x1f\x7f]*")
# A revision's name: a Confluence version, or a Jira update time in UTC.
REVISION = re.compile(r"[0-9]{6}|[0-9]{8}T[0-9]{6}\.[0-9]{6}Z")
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
# A work-log document's revision: a digest of what pandoc converts, and how.
WORKLOG_REVISION = re.compile(r"[0-9a-f]{16}")


class RefusedError(ValueError):
    """A value that a domain type refuses; the message names the field, never the value."""


def require(pattern: re.Pattern[str], value: str, name: str) -> None:
    """Refuse a value that does not match its rule, naming the field and the rule."""
    if not pattern.fullmatch(value):
        message = f"{name}: does not match {pattern.pattern}"
        raise RefusedError(message)


def version_revision(version: int) -> str:
    """Name a Confluence version, padded so that names sort as versions do."""
    return f"{version:06d}"


def time_revision(updated: datetime) -> str:
    """Name a state by its update time in UTC, so that names sort as times do."""
    return updated.astimezone(UTC).strftime("%Y%m%dT%H%M%S.%fZ")
