"""Whether an invocation may resume a run, by its record, and what the resume will do."""

from __future__ import annotations

from typing import TYPE_CHECKING

from kb_mcp.cli.adapters.run_record import RunRecord
from kb_mcp.cli.domain.command import FETCH
from kb_mcp.cli.domain.runs import keyed, resume_refused, resume_said, units_of
from kb_mcp.cli.domain.sources import fetch_flags, refusals
from kb_mcp.config.settings import values_of
from kb_mcp.kernel.fields import RepresentationError
from kb_mcp.kernel.names import RefusedError
from kb_mcp.kernel.records import Record

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from kb_mcp.cli.domain.runs import Configuration
    from kb_mcp.config.settings import Loaded
    from kb_mcp.sources.declaration import Source


class Resumption(Record):
    """Why an invocation may not resume a run, if it may not, and what the resume will do."""

    refusal: str | None = None
    said: str = ""


def require_configured(configuration: Configuration, configured: Mapping[str, Source]) -> None:
    """Refuse a run's configuration that the sources ``configured`` no longer run, by its field.

    Raises RefusedError for a source of its units no longer among them, and for an option
    of its fetch that no setting holds, missing from its fetch's options.
    """
    gone = [
        name for names in configuration.sources.values() for name in names if name not in configured
    ]
    if gone:
        message = f"source {gone[0]}: no longer configured"
        raise RefusedError(message)
    fetched = configuration.options.get(FETCH, {})
    declared = fetch_flags(configured[name] for name in configuration.sources.get(FETCH, ()))
    missing = [
        flag for flag, option in declared.items() if option.setting is None and flag not in fetched
    ]
    if missing:
        message = f"options.fetch.{missing[0]}: missing"
        raise RefusedError(message)


def resumption(
    run: str, loaded: Loaded, sources: Sequence[Source], *, remote_allowed: bool
) -> Resumption:
    """Read a run's record, under the data directory that ``loaded`` names, to resume it.

    It may not be resumed when no record of it is there, its record or its settings do not
    read, ``sources`` no longer run its configuration, or ``resume_refused`` says so; each
    refusal names the run. Else the resume says what it will do, and which source's fetch
    will not run, by the light check of the settings that the run recorded.
    """
    runs = loaded.settings.runs
    record = RunRecord(runs / run)
    configured = {each.name: each for each in sources}
    try:
        configuration = record.read_configuration()
        last = keyed(record.read_outcomes())
        with record.checking():
            require_configured(configuration, configured)
        settings = record.settings(configuration, loaded.settings)
    except FileNotFoundError:
        return Resumption(refusal=f"run {run}: no record under {runs}")
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
    fetched = [configured[name] for name in configuration.sources.get(FETCH, ())]
    refused = refusals(fetched, values_of(settings))
    return Resumption(
        refusal=refusal and f"run {run}: {refusal}",
        said=resume_said(configuration, units, endings, refused),
    )
