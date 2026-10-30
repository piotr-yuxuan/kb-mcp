"""Confluence's and Jira's preparer: the mirror of one source's kinds, as its role.

Both declarations name this module, a ``Preparer``: ``prepare`` reads from the
declaration of the source that a run is for the kinds that it converts, and the source
whose rows of the cache of conversions it reads, finds pandoc, then mirrors those kinds
alone; a dry run leaves the mirror as it is. ``prepare_kinds`` mirrors and says what it
could not, as ``mirror``'s events do; ``mirror`` and ``sync``'s Atlassian step run it
too.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

from kb_mcp.mirror.adapters import conversions
from kb_mcp.mirror.adapters.pandoc import Pandoc, PandocMissingError
from kb_mcp.sources.atlassian.fetch.adapters.raw_store import RawStore
from kb_mcp.sources.atlassian.prepare.app.prepare import KINDS, Outcome, mirror
from kb_mcp.sources.roles import Result

if TYPE_CHECKING:
    from kb_mcp.config.domain.settings import Settings
    from kb_mcp.kernel.output import Summary
    from kb_mcp.sources.atlassian.fetch.domain.content import BlogPost, Issue, Page
    from kb_mcp.sources.roles import Run


class Prepared(Result):
    """A prepare: how it ended, and what the mirror did, None when it did not run."""

    mirrored: Outcome | None

    def text(self, summary: Summary) -> str:
        """Write the mirror's counts as ``mirror`` does; nothing when it did not run."""
        return "" if self.mirrored is None else self.mirrored.text(summary)


def preflight(_run: Run) -> None:
    """Refuse nothing: the raw store is read as it is, whatever it holds."""


def prepare(run: Run) -> Prepared:
    """Mirror the kinds of the run's source, unless a dry run, with the pandoc found now.

    Pandoc gone from PATH since the run began fails the prepare, which writes nothing:
    an error, ``mirror.pandoc_missing``. The site is the account's, so that links to its
    pages resolve and addresses are absolute.
    """
    if run.dry_run:
        return Prepared(outcome="not run", mirrored=None)
    try:
        pandoc = Pandoc.find()
    except PandocMissingError as error:
        structlog.get_logger().error("mirror.pandoc_missing", reason=str(error))
        return Prepared(outcome="failed", mirrored=None)
    names = {each.name for each in run.declared.types}
    kinds = tuple(kind for kind in KINDS if kind.kind in names)
    return prepare_kinds(run.settings, run.account.site, pandoc, run.declared.name, kinds)


def prepare_kinds(
    settings: Settings,
    site: str | None,
    pandoc: Pandoc,
    source: str,
    kinds: tuple[type[Page | BlogPost | Issue], ...],
) -> Prepared:
    """Mirror one source's documents, those of ``kinds``, from the raw store; say its problems.

    The data folder's cache of pandoc's conversions is open for this mirror alone, on the
    rows of ``source``. What it could not mirror is a warning, ``mirror.not_mirrored``,
    by its place and the reason, never its content, as is that the source then removed
    none of its files, ``mirror.nothing_removed``.
    """
    log = structlog.get_logger()
    with conversions.opened(
        settings.conversions, pandoc.html_converter, pandoc.markdown, source=source
    ) as cache:
        mirrored = mirror(RawStore(settings.raw), settings.docs, site, cache, kinds)
    for problem in mirrored.problems:
        log.warning("mirror.not_mirrored", where=problem.where, reason=problem.reason)
    if mirrored.problems:
        log.warning("mirror.nothing_removed", source=source, problems=len(mirrored.problems))
    return Prepared(outcome="failed" if mirrored.problems else "done", mirrored=mirrored)
