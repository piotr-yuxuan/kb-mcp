"""Confluence's and Jira's preparer: the mirror of one source's kinds, as its role.

Both declarations name this module, a ``Preparer``: ``prepare`` reads from the
declaration of the source that a run is for the kinds that it converts, and the source
whose rows of the cache of conversions it reads, finds pandoc, then mirrors those kinds
alone; a dry run leaves the mirror as it is, and says that it counts nothing.
``prepare_kinds`` mirrors and says what it could not.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

from kb_mcp.mirror.adapters import conversions
from kb_mcp.mirror.adapters.pandoc import Pandoc, PandocMissingError
from kb_mcp.sources import roles
from kb_mcp.sources.atlassian.fetch.adapters.raw_store import RawStore
from kb_mcp.sources.atlassian.prepare.app.prepare import KINDS, SOURCE_OF, Outcome, mirror
from kb_mcp.sources.roles import Result

if TYPE_CHECKING:
    from kb_mcp.config.domain.settings import Settings
    from kb_mcp.kernel.output import Summary
    from kb_mcp.sources.atlassian.fetch.domain.content import BlogPost, Issue, Page
    from kb_mcp.sources.roles import Run

# What a dry run says of these sources: a count needs a lookup without converting.
NOT_COUNTED = "not counted: a dry run of this source converts nothing, and cannot tell"


class Prepared(Result):
    """A prepare: how it ended, and what the mirror did, None when it did not run."""

    mirrored: Outcome | None

    def text(self, summary: Summary) -> str:
        """Write the mirror's counts; nothing when it did not run."""
        return "" if self.mirrored is None else self.mirrored.text(summary)


class NotCounted(Prepared):
    """A dry run's prepare: nothing converted, so nothing counted, which its row says."""

    outcome: roles.Outcome = "not run"
    mirrored: None = None

    def text(self, _summary: Summary) -> str:
        """Say that a count needs what a dry run does not do."""
        return f"{NOT_COUNTED}\n"


def kinds_of(run: Run) -> tuple[type[Page | BlogPost | Issue], ...]:
    """Give the kinds that the declaration of the source that a run is for names by its types."""
    names = {each.name for each in run.declared.types}
    return tuple(kind for kind in KINDS if kind.kind in names)


def preflight(run: Run) -> str | None:
    """Refuse a declaration whose types are not all the kinds of one source, by its name.

    A prepare removes the files of all of them, those of a kind that it did not build too.
    The raw store is read as it is, whatever it holds.
    """
    if kinds_of(run) in SOURCE_OF:
        return None
    named = ", ".join(each.name for each in run.declared.types)
    return f"types {named}: not all the kinds of one source"


def prepare(run: Run) -> Prepared:
    """Mirror the kinds of the run's source, unless a dry run, with the pandoc found now.

    Pandoc gone from PATH since the run began fails the prepare, which writes nothing:
    an error, ``prepare.pandoc_missing``. The site is the account's, so that links to its
    pages resolve and addresses are absolute.
    """
    if run.dry_run:
        return NotCounted()
    try:
        pandoc = Pandoc.find()
    except PandocMissingError as error:
        structlog.get_logger().error("prepare.pandoc_missing", reason=str(error))
        return Prepared(outcome="failed", mirrored=None)
    return prepare_kinds(run.settings, run.account.site, pandoc, run.declared.name, kinds_of(run))


def prepare_kinds(
    settings: Settings,
    site: str | None,
    pandoc: Pandoc,
    source: str,
    kinds: tuple[type[Page | BlogPost | Issue], ...],
) -> Prepared:
    """Mirror one source's documents, those of ``kinds``, from the raw store; say its problems.

    The data folder's cache of pandoc's conversions is open for this mirror alone, on the
    rows of ``source``. What it could not mirror is a warning, ``prepare.not_mirrored``,
    by the source that it belongs to, its place and the reason, never its content, as is
    that the source then removed none of its files, ``prepare.nothing_removed``. What it
    could not read of another source is said alike, since its own files may then link
    around that source's document, and fails nothing of its own.
    """
    log = structlog.get_logger()
    with conversions.opened(
        settings.conversions, pandoc.html_converter, pandoc.markdown, source=source
    ) as cache:
        mirrored = mirror(RawStore(settings.raw), settings.docs, site, cache, kinds)
    for name, problems in {source: mirrored.problems, **mirrored.elsewhere}.items():
        for problem in problems:
            log.warning(
                "prepare.not_mirrored", source=name, where=problem.where, reason=problem.reason
            )
    if mirrored.problems:
        log.warning("prepare.nothing_removed", source=source, problems=len(mirrored.problems))
    return Prepared(outcome="failed" if mirrored.problems else "done", mirrored=mirrored)
