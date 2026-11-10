"""Confluence's and Jira's preparer: one source's documents written into the mirror.

Both declarations name this module, a ``Preparer``: ``prepare`` reads from the
declaration of the source that a run is for the resource types that it converts, and the source
whose rows of the cache of conversions it reads, finds pandoc, then writes the documents
of those classes alone; a dry run leaves the mirror as it is, and says that it counts
nothing. ``prepare_classes`` writes them and says what it could not.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

from kb_mcp.kernel.outcome import Outcome, OutcomeWarning
from kb_mcp.mirror.adapters import conversions
from kb_mcp.mirror.adapters.pandoc import Pandoc, PandocMissingError
from kb_mcp.sources.atlassian.fetch.adapters.raw_store import RawStore
from kb_mcp.sources.atlassian.fetch.domain.content import DOCUMENT_CLASSES
from kb_mcp.sources.atlassian.prepare.app.prepare import SOURCE_OF, prepare_atlassian

if TYPE_CHECKING:
    from kb_mcp.config.domain.settings import Settings
    from kb_mcp.sources.atlassian.fetch.domain.content import BlogPost, Issue, Page
    from kb_mcp.sources.atlassian.prepare.app.prepare import AtlassianCounts
    from kb_mcp.sources.stages import SourceRun

# What a dry run says of these sources: a count needs a lookup without converting.
NOT_COUNTED = "not counted: a dry run of this source converts nothing, and cannot tell"


def classes_of(run: SourceRun) -> tuple[type[Page | BlogPost | Issue], ...]:
    """Give the classes of the resource types that the declaration of the run's source names."""
    names = {each.name for each in run.source.resource_types}
    return tuple(
        document_class
        for document_class in DOCUMENT_CLASSES
        if document_class.resource_type in names
    )


def preflight(run: SourceRun) -> str | None:
    """Refuse a declaration whose types are not all the resource types of one source, by name.

    A prepare removes the files of all of them, those of a type that it did not build too.
    The raw store is read as it is, whatever it holds.
    """
    if classes_of(run) in SOURCE_OF:
        return None
    named = ", ".join(each.name for each in run.source.resource_types)
    return f"types {named}: not all the resource types of one source"


def prepare(run: SourceRun) -> Outcome[AtlassianCounts]:
    """Prepare the resource types of the run's source, unless a dry run, with the pandoc found now.

    A dry run ends not run, with no counts, and a warning that says why.

    Pandoc gone from PATH since the run began fails the prepare, which writes nothing:
    an error, ``prepare.pandoc_missing``. The site is the account's, so that links to its
    pages resolve and addresses are absolute.
    """
    if run.dry_run:
        return Outcome(
            ending="not run", warnings=(OutcomeWarning(where=run.source.name, reason=NOT_COUNTED),)
        )
    try:
        pandoc = Pandoc.find()
    except PandocMissingError as error:
        structlog.get_logger().error("prepare.pandoc_missing", reason=str(error))
        return Outcome(ending="failed")
    return prepare_classes(
        run.settings, run.account_table.site, pandoc, run.source.name, classes_of(run)
    )


def prepare_classes(
    settings: Settings,
    site: str | None,
    pandoc: Pandoc,
    source: str,
    document_classes: tuple[type[Page | BlogPost | Issue], ...],
) -> Outcome[AtlassianCounts]:
    """Prepare a source's documents of ``document_classes`` from the raw store; say its problems.

    The data folder's cache of pandoc's conversions is open for this mirror alone, on the
    rows of ``source``. What it could not mirror is a warning, ``prepare.not_mirrored``,
    by the source whose prepare found it, its place and the reason, never its content, as is
    that the source then removed none of its files, ``prepare.nothing_removed``. What it
    could not read of another source is a warning of its outcome, said alike, since its
    own files may then link around that source's document, and fails nothing of its own.
    """
    log = structlog.get_logger()
    with conversions.opened(
        settings.conversions, pandoc.html_converter, pandoc.markdown, source=source
    ) as cache:
        outcome = prepare_atlassian(
            RawStore(settings.raw), settings.docs, site, cache, document_classes
        )
    for each in (*outcome.problems, *outcome.warnings):
        log.warning("prepare.not_mirrored", source=source, where=each.where, reason=each.reason)
    if outcome.problems:
        log.warning("prepare.nothing_removed", source=source, problems=len(outcome.problems))
    return outcome
