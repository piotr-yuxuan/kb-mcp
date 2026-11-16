"""What the recorded runs share: a configuration run from its record, and the units over the whole.

Apart from the entry, so that a run that is not recorded loads none of this; and apart
from any source, so that ``index`` and ``embed`` read the mirror alone.
"""

from __future__ import annotations

from datetime import UTC, datetime
from functools import partial
from typing import TYPE_CHECKING

import structlog

from kb_mcp.cli.adapters.run_record import RunBusyError, RunRecord
from kb_mcp.cli.app.units import REFUSED, Planned, SourcesRefusedError, run_units
from kb_mcp.cli.commands._embedding import indexing_of, open_endpoint
from kb_mcp.cli.domain.command import INDEX
from kb_mcp.cli.domain.rows import Ended
from kb_mcp.cli.domain.runs import Configuration, units_of
from kb_mcp.config.domain.settings import without_secrets
from kb_mcp.kernel.exit_status import ExitStatus
from kb_mcp.kernel.names import PROGRAM
from kb_mcp.search.app.indexing import fill_and_prune, update_index

if TYPE_CHECKING:
    import argparse
    from collections.abc import Callable, Mapping, Sequence

    from pydantic import JsonValue

    from kb_mcp.cli.app.units import Done
    from kb_mcp.cli.domain.command import Stage
    from kb_mcp.cli.domain.runs import Unit
    from kb_mcp.config.domain.settings import Loaded, Settings
    from kb_mcp.kernel.output import Detail

# What to do while another invocation holds the run.
BUSY = "another invocation holds this run; try again once it ends"


def recorded(
    loaded: Loaded,
    run: str,
    started: datetime,
    configuration: Configuration | None,
    planned: Callable[[Configuration, Settings], Sequence[Planned]],
) -> tuple[ExitStatus, Done | None]:
    """Run a configuration from its record, ``runs/<run id>/``; give the status and what was done.

    ``configuration``, resolved by the invocation that starts the run at ``started``, is
    recorded first: a dry run's in memory alone, so that it writes nothing; None resumes
    the run recorded. Either way, the configuration is read back from the record, and
    the run's settings built from it, its secrets alone from this invocation's
    ``loaded``; ``planned`` gives its units' work from them, and each unit's entry is
    written as it ends (``run_units``), this invocation's started at ``started``.

    Another invocation holding the run refuses this one, exit 2, an error ``run.busy``; a
    fetcher or a preparer that does not load refuses it alike, ``fetch.refused`` or
    ``prepare.refused``, without a source. A run recorded whose units did not all last
    end done says, a warning ``run.resumable``, the command that resumes it, even as an
    error that no unit caught passes.
    """
    dry = configuration is not None and configuration.dry_run
    record = RunRecord(None if dry else loaded.settings.runs / run)
    try:
        with record.holding():
            if configuration is not None:
                record.write_configuration(configuration)
            fixed = record.read_configuration()
            settings = record.settings(fixed, loaded.settings)
            try:
                done = run_units(
                    planned(fixed, settings),
                    record.read_outcomes(),
                    started,
                    record.write_outcomes,
                    dry_run=fixed.dry_run,
                )
            finally:
                endings = {each.ending for each in record.read_outcomes()}
                if record.folder is not None and endings - {"done"}:
                    resume = f"{PROGRAM} refresh --resume {run}"
                    structlog.get_logger().warning("run.resumable", resume=resume)
    except RunBusyError:
        structlog.get_logger().error("run.busy", hint=BUSY)
        return ExitStatus.REFUSED, None
    except SourcesRefusedError as error:
        structlog.get_logger().error(REFUSED[error.stage], reason=str(error))
        return ExitStatus.REFUSED, None
    return done.exit_status, done


def whole_planned(
    arguments: argparse.Namespace, unit: Unit, configuration: Configuration, settings: Settings
) -> Planned:
    """Give a unit over the whole as its stage does it, with the run's settings.

    Index, by words alone, never asking an endpoint, rebuilt whole if the configuration
    says so; embed, through the endpoint that the setting names, as this invocation's
    --allow-remote-embeddings allows, then the prune of the vector cache.
    """
    if unit.stage == INDEX:
        rebuild = configuration.options[INDEX]["--rebuild"] is True
        return Planned(
            unit=unit,
            act=lambda: update_index(
                indexing_of(settings, None), datetime.now(UTC), rebuild=rebuild
            ),
        )
    opening = partial(open_endpoint, arguments, settings)
    return Planned(unit=unit, act=lambda: fill_and_prune(indexing_of(settings, opening)))


def whole_run(
    arguments: argparse.Namespace,
    loaded: Loaded,
    run: str,
    stage: Stage,
    options: Mapping[str, JsonValue],
) -> tuple[ExitStatus, Ended | None]:
    """Run one stage over the whole, as a run recorded, its options as given; give its outcome.

    The configuration, resolved now, enables that stage alone; the status is its unit's
    ending's, 2 when refused.
    """
    started = datetime.now(UTC)
    configuration = Configuration(
        run=run,
        command=stage,
        started=started,
        stages=(stage,),
        options={stage: options} if options else {},
        settings=without_secrets(loaded.settings),
    )
    status, done = recorded(
        loaded,
        run,
        started,
        configuration,
        lambda fixed, settings: [
            whole_planned(arguments, unit, fixed, settings) for unit in units_of(fixed, {})
        ],
    )
    if done is None:
        return status, None
    (outcome,) = done.outcomes.values()
    return status, Ended(run=run, **dict(outcome))


def ended_text(ended: Ended, detail: Detail) -> str:
    """Write the run's id, then its one unit's outcome: its counts, its problems and warnings."""
    return f"run {ended.run}\n{ended.text(detail)}"
