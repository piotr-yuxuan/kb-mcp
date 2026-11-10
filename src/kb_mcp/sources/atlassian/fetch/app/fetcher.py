"""Confluence's and Jira's fetcher: one source's scopes fetched into the raw store.

Both connectors name this module, a ``Fetcher``: ``preflight`` and ``fetch`` read the
scope types of the connector of the source that a run is for, and fetch that source's
scopes alone, each of its table's keys of each scope type, over the period that its
options give. ``fetch_purview`` fetches them, or plans their fetch, and says what went
wrong.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

from kb_mcp.kernel.fields import RepresentationError
from kb_mcp.kernel.outcome import Outcome, Problem
from kb_mcp.sources.atlassian.fetch.adapters.raw_store import RawStore, StoreBusyError
from kb_mcp.sources.atlassian.fetch.adapters.sign_in import choose_sign_in
from kb_mcp.sources.atlassian.fetch.app.fetching import Purview, plan_fetch, run_fetch
from kb_mcp.sources.atlassian.fetch.domain.content import Space
from kb_mcp.sources.atlassian.fetch.domain.coverage import Scope
from kb_mcp.sources.atlassian.fetch.domain.files import MEBIBYTE
from kb_mcp.sources.atlassian.fetch.domain.names import SPACE
from kb_mcp.sources.atlassian.fetch.domain.period import (
    DEFAULT_MAX_FILE_MB,
    MAX_FILE_MB_FLAG,
    SINCE_FLAG,
    UNTIL_FLAG,
    PeriodError,
    moment,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from datetime import datetime

    from kb_mcp.config.domain.settings import Settings
    from kb_mcp.sources.atlassian.fetch.app.fetching import FetchCounts
    from kb_mcp.sources.stages import SourceRun

# What to do while another run writes the raw store.
BUSY = "another run is writing it; try again once that run ends"


def purview_of(run: SourceRun) -> Purview:
    """Read what ``run`` fetches: each key of each scope type that its table lists, its period.

    The list is the setting that the scope type's option replaces. ``run.options`` holds
    each option by its flag, as typed, None when not given: --since and --until read as
    ``moment`` reads them, at the run's start; --max-file-mb not given is
    ``DEFAULT_MAX_FILE_MB``. Raises KeyError for one that it does not hold, so that a flag
    renamed cannot read as not given.
    """
    options, now = run.options, run.now()
    since, until = options[SINCE_FLAG], options[UNTIL_FLAG]
    return Purview(
        scopes=[
            Scope(source=run.source.name, type=scope_type, key=key)
            for scope_type in run.source.connector.scope_types
            if scope_type.option is not None and scope_type.option.setting is not None
            for key in getattr(run.source_table, scope_type.option.setting)
        ],
        max_file_bytes=(options[MAX_FILE_MB_FLAG] or DEFAULT_MAX_FILE_MB) * MEBIBYTE,
        since=moment(since, now, SINCE_FLAG) if since else None,
        until=moment(until, now, UNTIL_FLAG) if until else None,
    )


def preflight(run: SourceRun) -> str | None:
    """Say why the fetch cannot start: an --until before --since, or a store's record not read.

    Those are the records that a fetch reads before its first request: what is
    covered, and for a fetch of spaces what answered as gone and each space's joined
    documents still to fetch. So that these stop no fetch of projects.
    """
    store = RawStore(run.settings.raw, run.source.name)
    try:
        purview = purview_of(run)
        purview.windows(store.coverage(), run.now())
        if SPACE in run.source.connector.scope_types:
            store.tombstones()
            for space in store.spaces():
                if isinstance(space, Space):
                    store.pending(space.id)
    except (PeriodError, RepresentationError) as error:
        return str(error)
    return None


def fetch(run: SourceRun) -> Outcome[FetchCounts]:
    """Fetch what changed of the run's source, or in a dry run plan it, by ``fetch_purview``.

    What ``preflight`` refuses may still come once the run began: a period read at a
    later fetch's start, or a record damaged since. It fails this fetch alone, a problem
    by the source and an error, ``fetch.refused``, naming the source, and the run's next
    rows go on.
    """
    try:
        return fetch_purview(run.settings, purview_of(run), run.now, run.sleep, dry_run=run.dry_run)
    except (PeriodError, RepresentationError) as error:
        structlog.get_logger().error("fetch.refused", source=run.source.name, reason=str(error))
        return Outcome.of(problems=(Problem(where=run.source.name, reason=str(error)),))


def fetch_purview(
    settings: Settings,
    purview: Purview,
    now: Callable[[], datetime],
    sleep: Callable[[float], None],
    *,
    dry_run: bool,
) -> Outcome[FetchCounts]:
    """Fetch these scopes, one source's, or plan their fetch; say what went wrong.

    Another run writing the raw store fails the fetch before it starts, a problem by the
    raw store and an error, ``fetch.store_busy``; each scope that failed is a warning,
    ``fetch.scope_failed``, and a sign-in that no longer holds an error,
    ``fetch.sign_in_needed``, saying how to sign in again; both errors name the source,
    since each source's fetch can give them.
    """
    act = plan_fetch if dry_run else run_fetch
    source = purview.source
    try:
        outcome = act(settings, purview, now, sleep)
    except StoreBusyError:
        structlog.get_logger().error(
            "fetch.store_busy", source=source, store=str(settings.raw), hint=BUSY
        )
        return Outcome.of(problems=(Problem(where="raw store", reason=BUSY),))
    if outcome.ending == "sign in again":
        structlog.get_logger().error(
            "fetch.sign_in_needed", source=source, hint=choose_sign_in(settings).again
        )
    return outcome
