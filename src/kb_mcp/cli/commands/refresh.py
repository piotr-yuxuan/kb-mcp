"""``refresh``: one recorded run of every stage over the sources taken, or any run resumed."""

from __future__ import annotations

from datetime import UTC, datetime
from functools import partial
from typing import TYPE_CHECKING

from kb_mcp.cli.commands._runs import recorded
from kb_mcp.cli.commands._stages import planned
from kb_mcp.cli.domain.command import FETCH, INDEX, PREPARE, STAGES
from kb_mcp.cli.domain.echo import values_of
from kb_mcp.cli.domain.rows import Refreshed
from kb_mcp.cli.domain.runs import Configuration, keyed
from kb_mcp.cli.domain.sources import chosen_to_fetch, chosen_to_prepare, fetch_options
from kb_mcp.config.domain.settings import without_secrets

if TYPE_CHECKING:
    import argparse

    from kb_mcp.config.domain.settings import Loaded
    from kb_mcp.kernel.exit_status import ExitStatus
    from kb_mcp.kernel.output import Detail


def run(
    arguments: argparse.Namespace, loaded: Loaded, run: str
) -> tuple[ExitStatus, Refreshed | None]:
    """Run every stage as a run recorded, or resume the run that --resume names; exit as it folds.

    A refresh records its configuration, resolved now: the sources that a fetch would
    take and those that a prepare would, each in their order, the fetch's options as of
    now, and an index not rebuilt. A resume runs the configuration that its run recorded,
    whichever command started it: each unit not last ended done, and each that follows
    one of those. The status folds every unit's last ending and this invocation's own.
    """
    started = datetime.now(UTC)
    values = values_of(loaded)
    configuration = (
        None
        if arguments.resume
        else Configuration(
            run=run,
            command="refresh",
            started=started,
            stages=STAGES,
            sources={
                FETCH: tuple(each.name for each in chosen_to_fetch(arguments, values)[0]),
                PREPARE: tuple(each.name for each in chosen_to_prepare(arguments, values)[0]),
            },
            options={FETCH: fetch_options(arguments, started), INDEX: {"--rebuild": False}},
            settings=without_secrets(loaded.settings),
        )
    )
    status, done = recorded(loaded, run, started, configuration, partial(planned, arguments))
    if done is None:
        return status, None
    return status, Refreshed(
        run=run, exit_status=status, units=done.entries, outcomes=done.outcomes
    )


def text(refreshed: Refreshed, detail: Detail) -> str:
    """Write the run's id, then each unit, how it last ended, and this invocation's outcome.

    A unit that an earlier invocation ended names when that invocation started; one that
    this invocation ended is followed by its outcome's own text, indented.
    """
    written = [f"run {refreshed.run}\n"]
    for unit, entry in keyed(refreshed.units).items():
        outcome = refreshed.outcomes.get(unit)
        earlier = "" if outcome else f", in the invocation of {entry.invocation.isoformat()}"
        written.append(f"{unit.name}: {entry.ending}{earlier}\n")
        said = "" if outcome is None else outcome.text(detail)
        written.extend(f"  {line}\n" for line in said.splitlines())
    return "".join(written)
