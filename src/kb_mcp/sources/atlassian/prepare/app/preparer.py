"""Confluence's and Jira's preparer: one source's documents written into the mirror.

Both connectors name this module, a ``Preparer``: ``prepare`` reads from the connector
of the source that a run is for the document types that it converts, and the source
whose rows of the cache of conversions it reads, finds pandoc, then writes the documents
of those classes alone, among those of every source that signs in with its account; a
dry run leaves the mirror as it is, and says that it counts nothing. ``prepare_source``
writes them and says what it could not.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

from kb_mcp.kernel.outcome import Outcome, OutcomeWarning, Problem
from kb_mcp.mirror.adapters import conversions
from kb_mcp.mirror.adapters.pandoc import Pandoc, PandocMissingError
from kb_mcp.sources.atlassian.fetch.adapters.raw_store import RawStore
from kb_mcp.sources.atlassian.fetch.domain.content import DOCUMENT_CLASSES
from kb_mcp.sources.atlassian.fetch.domain.names import PROJECT, SPACE
from kb_mcp.sources.atlassian.prepare.app.prepare import prepare_atlassian

if TYPE_CHECKING:
    from collections.abc import Mapping

    from kb_mcp.config.domain.settings import Settings
    from kb_mcp.sources.atlassian.prepare.app.prepare import AtlassianCounts, Classes
    from kb_mcp.sources.declaration import Connector
    from kb_mcp.sources.stages import SourceRun

# What a dry run says of these sources: a count needs a lookup without converting.
NOT_COUNTED = "not counted: a dry run of this source converts nothing, and cannot tell"


def classes_of(connector: Connector) -> Classes:
    """Give the classes of a connector's document types, in their order."""
    return tuple(
        document_class
        for document_class in DOCUMENT_CLASSES
        if document_class.document_type in connector.document_types
    )


def preflight(run: SourceRun) -> str | None:
    """Refuse a connector whose scope types are not a space's or a project's, by name.

    Each holds all of its document types: a prepare removes the files of all of them,
    those of a type that it did not build too. The raw store is read as it is, whatever
    it holds.
    """
    unknown = [
        each.name for each in run.source.connector.scope_types if each not in (SPACE, PROJECT)
    ]
    if not unknown:
        return None
    return f"scope types {', '.join(unknown)}: not a space's or a project's, whole"


def prepare(run: SourceRun) -> Outcome[AtlassianCounts]:
    """Prepare the document types of the run's source, unless a dry run, with the pandoc found now.

    A dry run ends not run, with no counts, and a warning that says why.

    Pandoc gone from PATH since the run began fails the prepare, which writes nothing:
    a problem by pandoc and an error, ``prepare.pandoc_missing``. The site is the
    account's, so that links to its pages resolve and addresses are absolute; the
    sources of the run that sign in with that account are the site's.
    """
    if run.dry_run:
        return Outcome(
            ending="not run", warnings=(OutcomeWarning(where=run.source.name, reason=NOT_COUNTED),)
        )
    try:
        pandoc = Pandoc.find()
    except PandocMissingError as error:
        structlog.get_logger().error("prepare.pandoc_missing", reason=str(error))
        return Outcome.of(problems=(Problem(where="pandoc", reason=str(error)),))
    account = run.source.connector.account
    sources = {
        each.name: classes_of(each.connector)
        for each in run.sources
        if each.connector.account == account
    }
    return prepare_source(run.settings, run.account_table.site, pandoc, run.source.name, sources)


def prepare_source(
    settings: Settings,
    site: str | None,
    pandoc: Pandoc,
    source: str,
    sources: Mapping[str, Classes],
) -> Outcome[AtlassianCounts]:
    """Prepare a source's documents from the raw store, among those of ``sources``; say why not.

    ``sources`` gives each source of the site's document classes by its name. The data
    folder's cache of pandoc's conversions is open for this mirror alone, on the rows of
    ``source``; a cache of the former layout is adopted for each source of ``sources``.
    What it could not mirror is a warning, ``prepare.not_mirrored``, by the source whose
    prepare found it, its place and the reason, never its content, as is
    that the source then removed none of its files, ``prepare.nothing_removed``. What it
    could not read of another source is a warning of its outcome, said alike, since its
    own files may then link around that source's document, and fails nothing of its own.
    """
    log = structlog.get_logger()
    with conversions.opened(
        settings.conversions,
        pandoc.html_converter,
        pandoc.markdown,
        source=source,
        adopted=tuple(sources),
    ) as cache:
        outcome = prepare_atlassian(
            RawStore(settings.raw, source), settings.docs, site, cache, sources
        )
    for each in (*outcome.problems, *outcome.warnings):
        log.warning("prepare.not_mirrored", source=source, where=each.where, reason=each.reason)
    if outcome.problems:
        log.warning("prepare.nothing_removed", source=source, problems=len(outcome.problems))
    return outcome
