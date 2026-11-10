"""The period covered for each scope, and the window that each run fetches.

A scope (a space or a project) is covered over one period, over which every change was
asked for; the period is exact when every change in it is known stored, and an inexact
one may hide a failure. Without --since, a run fetches what changed since each scope's
last fetch: an exact scope from its covered end, another from its covered start; a scope
never covered, its last week.
"""

from __future__ import annotations

from collections.abc import Mapping
from copy import replace
from datetime import datetime, timedelta
from typing import Literal, Self

from pydantic import Field, InstanceOf, field_serializer, model_validator

from kb_mcp.kernel.names import SOURCE_NAME, RefusedError, require
from kb_mcp.kernel.record import Record
from kb_mcp.sources.atlassian.fetch.domain.period import EPOCH, FIRST_FETCH, Period
from kb_mcp.sources.declaration import ScopeType

# What a run made of a scope's coverage: grown to its window's end, ended at a failure,
# or left as it was.
type CoverageChange = Literal["extended", "capped", "held"]
# Why a window starts where it does: at --since, a day before an exact covered end, at the
# covered start (a space, or a project's entry from before plan 034), or a week back.
type Reason = Literal["given", "since the last fetch", "covered start", "first fetch"]
# How far before its covered end an exact scope's catch-up starts: a search index can lag
# behind an edit, the window ends at this machine's clock while documents carry the
# site's, and an issue saved while its search pages through moves in it. A day survives a
# laptop's clock off after sleep; it costs no request, since a search reads whole days
# and a listing is read whole.
CATCH_UP_MARGIN = timedelta(days=1)


class Scope(Record):
    """A part of one source, read and tracked as a unit: its source, its scope type, its key.

    Written by its scope type's name.
    """

    source: str
    type: InstanceOf[ScopeType]
    key: str

    @model_validator(mode="after")
    def check_scope(self) -> Self:
        """Refuse a source off its rule, and a key off its scope type's, which must have one."""
        require(SOURCE_NAME, self.source, "source")
        if self.type.key is None:
            message = "type: its one scope is the whole source, without a key"
            raise RefusedError(message)
        require(self.type.key, self.key, "key")
        return self

    @field_serializer("type")
    def type_name(self, scope_type: ScopeType) -> str:
        """Write the scope type by its name."""
        return scope_type.name

    def __str__(self) -> str:
        """Name the scope as the user does: ``space ENG``, ``project PLAT``."""
        return f"{self.type.name} {self.key}"


class Coverage(Record):
    """Each scope's covered period, over which every change was asked for.

    Such a period is ``exact`` when every change in it is known stored; one written before
    plan 034 is not, and its end may hide a failure. A space is listed whole: a failure
    within its period (a document whose fetch failed, an entry the adapter refuses) leaves
    it inexact, so that a run without --since starts at its covered start, and asks for
    the whole period again. A project is searched by update time: its period ends at its
    first failure, so that a search from its end asks for that again. ``as_of`` holds
    each scope's as-of time, the end of its coverage when a run last left it exact;
    ``whole_read_at`` the time of its last whole read.
    """

    periods: Mapping[Scope, Period] = Field(default_factory=dict)
    exact: frozenset[Scope] = frozenset()
    as_of: Mapping[Scope, datetime] = Field(default_factory=dict)
    whole_read_at: Mapping[Scope, datetime] = Field(default_factory=dict)

    def extended(
        self, scope: Scope, fetched: Period, failed: datetime | None = None
    ) -> tuple[Coverage, CoverageChange]:
        """Return the coverage once a run listed or searched ``fetched`` whole for the scope.

        ``failed`` is the update time of the earliest document found and not stored whole.
        The covered period stays one period: a run apart from it leaves it as it was,
        ``held``, since joining would claim the gap between them; one that overlaps or
        touches it joins it, ``extended``. A run sees the period whole when it is a first
        run, a run over an exact entry, or one that starts at or before an inexact entry,
        which it replaces; without a failure, it leaves the period exact. There a failure
        leaves a space's inexact, and ends a project's at ``failed``, even below the old
        end, ``capped``, or leaves it as it was when the period would then be empty,
        inexact if it starts at the failure, so that the next run searches it whole. Any
        other run over an inexact entry joins it and leaves it inexact. A run that leaves
        it exact sets its as-of time to its end; any other leaves that as it was.
        """
        covered = self.periods.get(scope)
        if covered is not None and (fetched.start > covered.end or fetched.end < covered.start):
            return self, "held"
        whole = covered is None or scope in self.exact or fetched.start <= covered.start
        if covered is None or (whole and scope not in self.exact):
            start, end = fetched.start, fetched.end
        else:
            start, end = min(covered.start, fetched.start), max(covered.end, fetched.end)
        if failed is None or not whole or scope.type.enumeration != "searched":
            exact = whole and failed is None
            return self.covering(scope, Period(start, end), exact=exact), "extended"
        if failed <= start:
            inside = covered is not None and covered.start <= failed
            return replace(self, exact=self.exact - {scope} if inside else self.exact), "capped"
        return self.covering(scope, Period(start, failed), exact=True), "capped"

    def covering(self, scope: Scope, period: Period, *, exact: bool) -> Coverage:
        """Return this coverage with the scope covered over ``period``, as of its end if exact."""
        return replace(
            self,
            periods={**self.periods, scope: period},
            exact=self.exact | {scope} if exact else self.exact - {scope},
            as_of={**self.as_of, scope: period.end} if exact else self.as_of,
        )


class FetchWindow(Record):
    """The period that a run fetches for a scope, and why it starts where it does."""

    period: Period
    reason: Reason


def fetch_window(
    coverage: Coverage, scope: Scope, since: datetime | None, end: datetime
) -> FetchWindow | None:
    """Return the window a run fetches for a scope, to ``end``; None to skip the scope.

    It starts at ``since`` when given, and raises PeriodError when that is not before
    ``end``. Otherwise an exact scope catches up from ``CATCH_UP_MARGIN`` before its
    covered end, another scope covered from its covered start, and one never covered
    starts ``FIRST_FETCH`` before ``end``; a catch-up that would start at or after
    ``end``, an ``--until`` before it, skips the scope. Nothing starts before the epoch:
    nothing on the site is older, and dates stay in range.
    """
    if since is not None:
        return FetchWindow(period=Period(max(since, EPOCH), end), reason="given")
    covered = coverage.periods.get(scope)
    start: datetime
    reason: Reason
    if covered is None:
        start, reason = end - FIRST_FETCH, "first fetch"
    elif scope in coverage.exact:
        start, reason = covered.end - CATCH_UP_MARGIN, "since the last fetch"
    else:
        start, reason = covered.start, "covered start"
    start = max(start, EPOCH)
    if start >= end:
        return None
    return FetchWindow(period=Period(start, end), reason=reason)


__all__ = ["EPOCH", "Coverage", "CoverageChange", "FetchWindow", "Scope", "fetch_window"]
