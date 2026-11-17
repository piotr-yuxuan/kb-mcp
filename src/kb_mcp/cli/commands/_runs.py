"""What the recorded runs share: a configuration run from its record, and the units over the whole.

Apart from the entry, so that a run that is not recorded loads none of this; and apart
from any source, so that ``index`` and ``embed`` read the mirror alone.
"""

from __future__ import annotations

from copy import replace
from datetime import UTC, datetime
from functools import partial
from typing import TYPE_CHECKING

import structlog

from kb_mcp.cli.adapters.run_record import RunBusyError, RunRecord
from kb_mcp.cli.app.units import REFUSED, Planned, SourcesRefusedError, run_units
from kb_mcp.cli.commands._embedding import indexing_of, open_endpoint
from kb_mcp.cli.domain.command import INDEX, WHOLE
from kb_mcp.cli.domain.rows import Ended
from kb_mcp.cli.domain.runs import Configuration, resumable, units_of
from kb_mcp.config.domain.settings import without_secrets
from kb_mcp.kernel.exit_status import ExitStatus
from kb_mcp.kernel.fields import RepresentationError
from kb_mcp.kernel.names import PROGRAM
from kb_mcp.search.app.indexing import fill_and_prune, update_index

if TYPE_CHECKING:
    import argparse
    from collections.abc import Callable, Mapping, Sequence

    from pydantic import JsonValue

    from kb_mcp.cli.app.units import Done
    from kb_mcp.cli.domain.runs import Recorded, Unit
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
    recorded first: in memory alone for a dry run, so that it writes nothing, and for a
    run of stages over the whole alone, index or embed, whose data directory does not
    exist, so that it makes none, having nothing to read; None resumes
    the run recorded. Either way, the configuration is read back from the record, and
    the run's settings built from it, its secrets alone from this invocation's
    ``loaded``; ``planned`` gives its units' work from them, and each unit's entry is
    written as it ends (``run_units``), this invocation's started at ``started``.

    Another invocation holding the run refuses this one, exit 2, an error ``run.busy``; a
    record gone, that no longer reads, or whose configuration ``planned`` refuses
    (RefusedError, by its field, such as a source no longer configured) once the run is
    held, as another program may have changed it since the entry read it, refuses it
    alike, ``run.refused``, naming the record; and a fetcher or a preparer that does not
    load, ``fetch.refused`` or ``prepare.refused``, without a source: before a new run's
    record is written, as ``planned`` is first asked of the configuration resolved, then
    of the one read back.
    A run recorded whose units did not all last end done says, a warning
    ``run.resumable``, the command that resumes it, even as an error that no unit caught
    passes: as of the entries last handed to its record, those read before its units when
    none was, whether or not their write succeeded, so that no record read hides the
    error in flight; unless a resume could do no more than a new run (``resumable``), as
    each unit not done is one that its settings refuse whatever the secrets
    (``Planned.refused``), or after one.
    """
    unrecorded = configuration is not None and (
        configuration.dry_run
        or (set(configuration.stages) <= WHOLE and not loaded.settings.data_dir.is_dir())
    )
    record = RunRecord(None if unrecorded else loaded.settings.runs / run)
    try:
        if configuration is not None:
            planned(configuration, loaded.settings)
        with record.holding():
            try:
                if configuration is not None:
                    record.write_configuration(configuration)
                fixed = record.read_configuration()
                with record.checking():
                    units = planned(fixed, record.settings(fixed, loaded.settings))
                last = record.read_outcomes()
            except (FileNotFoundError, RepresentationError) as error:
                structlog.get_logger().error("run.refused", reason=f"run {run}: {error}")
                return ExitStatus.REFUSED, None
            # The entries last handed to the record, written or not.
            handed = last

            def write(entries: tuple[Recorded, ...]) -> None:
                nonlocal handed
                handed = entries
                record.write_outcomes(entries)

            try:
                done = run_units(units, last, started, write, dry_run=fixed.dry_run)
            finally:
                settled = {each.unit for each in units if each.refused is not None}
                if record.folder is not None and resumable(handed, settled):
                    resume = f"{PROGRAM} refresh --resume {run}"
                    structlog.get_logger().warning("run.resumable", resume=resume)
    except RunBusyError:
        structlog.get_logger().error("run.busy", hint=BUSY)
        return ExitStatus.REFUSED, None
    except SourcesRefusedError as error:
        structlog.get_logger().error(REFUSED[error.stage], reason=str(error))
        return ExitStatus.REFUSED, None
    return done.exit_status, replace(done, recorded=record.folder is not None)


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
    started: datetime,
    options: Mapping[str, JsonValue],
) -> tuple[ExitStatus, Ended | None]:
    """Run the command's stage over the whole, as a run recorded; give its outcome.

    The configuration, resolved as of the run's start, ``started``, enables that stage
    alone, with its ``options`` as given; the status is its unit's ending's, 2 when
    refused.
    """
    stage = arguments.command.name
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
    return status, Ended(run=run, recorded=done.recorded, **dict(outcome))


def ended_text(ended: Ended, detail: Detail) -> str:
    """Write the run's id, then its one unit's outcome: its counts, its problems and warnings.

    A run not recorded says so after its id, which no resume takes.
    """
    return f"run {ended.run}{'' if ended.recorded else ', not recorded'}\n{ended.text(detail)}"
