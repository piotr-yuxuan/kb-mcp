"""``refresh``: one recorded run of every stage over the sources taken, or any run resumed."""

from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING

from kb_mcp.cli.commands._runs import recorded
from kb_mcp.cli.commands._stages import planned
from kb_mcp.cli.domain.command import FETCH, INDEX, PREPARE, STAGES
from kb_mcp.cli.domain.rows import Refreshed
from kb_mcp.cli.domain.runs import Configuration, keyed
from kb_mcp.cli.domain.sources import chosen, fetch_options
from kb_mcp.config.settings import values_of, without_secrets

if TYPE_CHECKING:
    import argparse
    from datetime import datetime

    from kb_mcp.config.settings import Loaded
    from kb_mcp.kernel.names import Detail, ExitStatus


def run(
    arguments: argparse.Namespace, loaded: Loaded, run: str, started: datetime
) -> tuple[ExitStatus, Refreshed | None]:
    """Run every stage as a run recorded, or resume the run that --resume names; exit as it folds.

    A refresh records its configuration as of ``started``, its index not rebuilt. A resume
    runs the configuration that its run recorded, whichever command started it: each unit
    not last ended done, and each that follows one of those. The status folds every unit's
    last ending and this invocation's own.
    """
    configuration = None
    if arguments.resume is None:
        values = values_of(loaded.settings)
        fetched, _ = chosen(arguments, values, FETCH)
        configuration = Configuration(
            run=run,
            command="refresh",
            started=started,
            stages=STAGES,
            sources={
                FETCH: tuple(each.name for each in fetched),
                PREPARE: tuple(each.name for each in chosen(arguments, values, PREPARE)[0]),
            },
            options={
                FETCH: fetch_options(arguments, fetched, started),
                INDEX: {"--rebuild": False},
            },
            settings=without_secrets(loaded.settings),
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
