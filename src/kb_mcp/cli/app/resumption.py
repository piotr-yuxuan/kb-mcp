"""Whether an invocation may resume a run, by its record, and what the resume will do."""

from __future__ import annotations

from typing import TYPE_CHECKING

from kb_mcp.cli.adapters.run_record import CONFIGURATION, RunRecord
from kb_mcp.cli.domain.command import FETCH
from kb_mcp.cli.domain.runs import keyed, resume_refused, resume_said, units_of
from kb_mcp.cli.domain.sources import fetch_flags
from kb_mcp.kernel.fields import RepresentationError
from kb_mcp.kernel.record import Record

if TYPE_CHECKING:
    from collections.abc import Sequence

    from kb_mcp.config.domain.settings import Loaded
    from kb_mcp.sources.declaration import Source


class Resumption(Record):
    """Why an invocation may not resume a run, if it may not, and what the resume will do."""

    refusal: str | None = None
    said: str = ""


def resumption(
    run: str, loaded: Loaded, sources: Sequence[Source], *, remote_allowed: bool
) -> Resumption:
    """Read a run's record, under the data directory that ``loaded`` names, to resume it.

    It may not be resumed when no record of it is there, its record does not read, a
    source of its units is no longer among ``sources``, its fetch lacks an option that a
    source of it declares, its settings no longer build with the secrets that ``loaded``
    holds, or ``resume_refused`` says so; each refusal names the run, and the file at
    fault. Else the resume says what it will do, as ``resume_said`` gives it.
    """
    runs = loaded.settings.runs
    record = RunRecord(runs / run)
    try:
        configuration = record.read_configuration()
        last = keyed(record.read_outcomes())
    except FileNotFoundError:
        return Resumption(refusal=f"run {run}: no record under {runs}")
    except RepresentationError as error:
        return Resumption(refusal=f"run {run}: {error}")
    configured = {each.name: each for each in sources}
    gone = [
        name for names in configuration.sources.values() for name in names if name not in configured
    ]
    if gone:
        return Resumption(refusal=f"run {run}: source {gone[0]}: no longer configured")
    fetched = configuration.options.get(FETCH, {})
    declared = fetch_flags(configured[name] for name in configuration.sources.get(FETCH, ()))
    missing = [
        flag for flag, option in declared.items() if option.setting is None and flag not in fetched
    ]
    if missing:
        where = record.where(CONFIGURATION)
        return Resumption(refusal=f"run {run}: {where}: options.fetch.{missing[0]}: missing")
    try:
        settings = record.settings(configuration, loaded.settings)
    except RepresentationError as error:
        return Resumption(refusal=f"run {run}: {error}")
    units = units_of(
        configuration, {name: len(each.connector.preparers) for name, each in configured.items()}
    )
    endings = {unit: entry.ending for unit, entry in last.items()}
    refusal = resume_refused(
        settings,
        units,
        endings,
        data_dir=loaded.settings.data_dir,
        remote_allowed=remote_allowed,
    )
    return Resumption(
        refusal=refusal and f"run {run}: {refusal}",
        said=resume_said(configuration, units, endings),
    )
