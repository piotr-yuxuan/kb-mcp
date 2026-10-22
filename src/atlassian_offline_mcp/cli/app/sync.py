"""``sync``'s steps: Confluence's and Jira's download and mirror, then the work log's.

Each step runs even when an earlier one failed, since the next reads what is on disk;
Ctrl-C stops the run, and no later step runs. What can be refused is refused before the
first step: a target with nowhere to start, and a work log that is not a folder. A dry
run plans the download and counts the work log, and writes nothing.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, ClassVar

from atlassian_offline_mcp.cli.domain.sync import RANKED
from atlassian_offline_mcp.kernel.exit_status import ExitStatus
from atlassian_offline_mcp.mirror.adapters.pandoc import PandocFailedError
from atlassian_offline_mcp.mirror.app.mirror import mirror
from atlassian_offline_mcp.mirror.app.worklog import mirror_worklog, plan_worklog
from atlassian_offline_mcp.sources.atlassian.adapters.raw_store import RawStore, StoreBusyError
from atlassian_offline_mcp.sources.atlassian.adapters.sign_in import sign_in
from atlassian_offline_mcp.sources.atlassian.app.download import download, plan

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence
    from datetime import datetime
    from pathlib import Path

    from atlassian_offline_mcp.cli.domain.sync import Outcome
    from atlassian_offline_mcp.config.domain.settings import Settings
    from atlassian_offline_mcp.mirror.adapters.pandoc import Pandoc
    from atlassian_offline_mcp.sources.atlassian.app.download import Targets

# How a download or its plan ended, by its status. A stopped download returns none: Ctrl-C
# leaves it as KeyboardInterrupt.
DOWNLOADED: dict[ExitStatus | None, Outcome] = {
    ExitStatus.OK: "done",
    ExitStatus.FAILED: "failed",
    ExitStatus.SIGN_IN_AGAIN: "sign in",
}


class SyncRefusedError(ValueError):
    """What a sync cannot run with, found before its first step; the message names it."""


@dataclass(frozen=True)
class Atlassian:
    """Confluence's and Jira's step: what to download, then the mirror of the raw store."""

    rows: ClassVar[tuple[str, ...]] = ("download", "mirror")

    targets: Targets


@dataclass(frozen=True)
class Worklog:
    """The work log's step: its folder, read in place, and whether archives are mirrored."""

    rows: ClassVar[tuple[str, ...]] = ("worklog",)

    folder: Path
    archives: bool


@dataclass(frozen=True)
class Context:
    """What every step needs: the settings, pandoc, the clock, the pause, where to say."""

    settings: Settings
    pandoc: Pandoc
    now: Callable[[], datetime]
    sleep: Callable[[float], None]
    say: Callable[[str], object]
    dry_run: bool


@dataclass(frozen=True)
class Row:
    """A step's row: its name, how it ended, and its own result, None when it gave none."""

    step: str
    outcome: Outcome
    result: object | None


@dataclass(frozen=True)
class Synced:
    """What a sync did: its exit status, then a row per step, in their order."""

    exit_status: ExitStatus
    steps: tuple[Row, ...]


def atlassian(context: Context, step: Atlassian, add: Callable[[Row], None]) -> None:
    """Download, or plan the download, then mirror the raw store, unless a dry run.

    The mirror runs whatever the download did, since it reads what is stored.
    """
    act = plan if context.dry_run else download
    try:
        fetched = act(context.settings, step.targets, context.now, context.sleep)
    except StoreBusyError:
        context.say("another run is writing the raw store; try again once it ends\n")
        add(Row("download", "failed", None))
    else:
        for target in fetched.failed_targets:
            context.say(f"{target}\n")
        if fetched.status == ExitStatus.SIGN_IN_AGAIN:
            context.say(f"sign-in needed: {sign_in(context.settings).again}\n")
        add(Row("download", DOWNLOADED[fetched.status], fetched))
    if context.dry_run:
        add(Row("mirror", "not run", None))
        return
    settings = context.settings
    mirrored = mirror(RawStore(settings.raw), settings.docs, settings.site, context.pandoc.markdown)
    for problem in mirrored.problems:
        context.say(f"not mirrored: {problem.where}: {problem.reason}\n")
    if mirrored.problems:
        context.say("nothing was removed, since something was not mirrored\n")
    add(Row("mirror", "failed" if mirrored.problems else "done", mirrored))


def worklog(context: Context, step: Worklog, add: Callable[[Row], None]) -> None:
    """Mirror the work log, or count what mirroring it would do; say its problems."""
    act = plan_worklog if context.dry_run else mirror_worklog
    try:
        done = act(step.folder, context.settings.docs, context.pandoc, archives=step.archives)
    except PandocFailedError as error:
        context.say(f"work log not mirrored: {error}\n")
        add(Row("worklog", "failed", None))
        return
    for problem in done.problems:
        context.say(f"not mirrored: {problem.where}: {problem.reason}\n")
    for warning in done.warnings:
        context.say(f"warning: {warning}\n")
    if done.problems and not context.dry_run:
        context.say("no work-log file was removed, since something was not mirrored\n")
    add(Row("worklog", "failed" if done.problems else "done", done))


def sync(context: Context, steps: Sequence[Atlassian | Worklog]) -> Synced:
    """Run the steps in their order; return a row per step and the exit status they rank.

    Raises ``SyncRefusedError`` for a work log that is not a folder, and PeriodError for
    a target with nowhere to start, both before the first step. Ctrl-C ends the step it
    stops as interrupted, and each later one as not run; the run is interrupted even
    when Ctrl-C comes once every step has ended. The status is the first of
    ``RANKED``'s outcomes that the run had, else OK.
    """
    for step in steps:
        if isinstance(step, Atlassian):
            step.targets.windows(RawStore(context.settings.raw).coverage(), context.now())
        elif not step.folder.is_dir():
            message = "sources.worklog.path: not a folder"
            raise SyncRefusedError(message)
    rows: list[Row] = []
    outcomes: set[Outcome] = set()
    try:
        for step in steps:
            if isinstance(step, Atlassian):
                atlassian(context, step, rows.append)
            else:
                worklog(context, step, rows.append)
    except KeyboardInterrupt:
        context.say("interrupted; no later step runs\n")
        outcomes.add("interrupted")
        planned = [row for step in steps for row in step.rows]
        stopped = len(rows)
        rows.extend(
            Row(name, "interrupted" if index == stopped else "not run", None)
            for index, name in enumerate(planned)
            if index >= stopped
        )
    outcomes.update(row.outcome for row in rows)
    status = next((status for outcome, status in RANKED if outcome in outcomes), ExitStatus.OK)
    return Synced(status, tuple(rows))
