"""Confluence's and Jira's fetcher: one source's scopes fetched into the raw store.

Both connectors name this module, a ``Fetcher``: ``preflight`` and ``fetch`` read the
scope types of the connector of the source that a run is for, and fetch that source's
scopes alone, each of its table's keys of each scope type, over the period that its
options give.
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

    It reads what is covered and, for a source of spaces, what answered as gone and the
    joined documents still to fetch of each space that the fetch lists, so that a damaged
    record of another space stops nothing. A source of projects reads what answered as
    gone once its fetch has begun (``run_fetch``), before its first request, and what
    each project's searches found since its last whole read when the fetch reaches that
    project, after the projects before it: either damaged then fails that source's unit
    alone, its searches by update time too, or those still to come.
    """
    store = RawStore(run.settings.raw, run.source.name)
    try:
        purview = purview_of(run)
        purview.windows(store.coverage(), run.now())
        if SPACE in run.source.connector.scope_types:
            store.tombstones()
            keys = {scope.key for scope in purview.scopes}
            for space in store.spaces():
                if isinstance(space, Space) and space.key in keys:
                    store.pending(space.id)
    except (PeriodError, RepresentationError) as error:
        return str(error)
    return None


def fetch(run: SourceRun) -> Outcome[FetchCounts]:
    """Fetch what changed of the run's source, or in a dry run plan it; say what went wrong.

    A fetch, not its plan, first takes the session kept before sessions were a site's, as
    ``SignIn.adopt_former`` says.

    What ``preflight`` refuses may still come once the run began: a period read at a
    later fetch's start, a record damaged since, or one that ``preflight`` leaves to the
    run. It fails this fetch alone, a problem
    by the source and an error, ``fetch.refused``, naming the source, and the run's next
    units go on.

    Another run writing the raw store fails the fetch before it starts, a problem by the
    raw store and an error, ``fetch.store_busy``; each scope that failed is a warning,
    ``fetch.scope_failed``, and a sign-in that no longer holds an error,
    ``fetch.sign_in_needed``, saying how to sign in again; both errors name the source,
    since each source's fetch can give them.
    """
    try:
        purview = purview_of(run)
        source = purview.source
        signing = choose_sign_in(run.settings, source)
        if not run.dry_run:
            signing.adopt_former()
        act = plan_fetch if run.dry_run else run_fetch
        outcome = act(run.settings, purview, run.now, run.sleep)
    except StoreBusyError:
        structlog.get_logger().error(
            "fetch.store_busy", source=run.source.name, store=str(run.settings.raw), hint=BUSY
        )
        return Outcome.of(problems=(Problem(where="raw store", reason=BUSY),))
    except (PeriodError, RepresentationError) as error:
        structlog.get_logger().error("fetch.refused", source=run.source.name, reason=str(error))
        return Outcome.of(problems=(Problem(where=run.source.name, reason=str(error)),))
    if outcome.ending == "sign in again":
        structlog.get_logger().error("fetch.sign_in_needed", source=source, hint=signing.again)
    return outcome
