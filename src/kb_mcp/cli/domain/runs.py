"""A run's configuration as recorded, its units, and what each unit last gave.

A run resolves its configuration as it starts, each relative value made absolute against
that start, records it under ``runs/<run id>/`` (``cli.adapters.run_record``), then runs
from what it reads back, its first invocation as each that resumes it. Its work is units,
one for each stage enabled at that stage's grain, in pipeline order; each unit's last
entry says how it ended and which invocation gave it. Pure: the record, the clock and
the units' work are the caller's.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from typing import TYPE_CHECKING, Self

from pydantic import AwareDatetime, Field, JsonValue, model_validator

from kb_mcp.cli.domain.command import EMBED, FETCH, INDEX, PREPARE, STAGES, WHOLE, Stage
from kb_mcp.kernel.endpoint import EMBEDDINGS, refused_endpoint
from kb_mcp.kernel.exit_status import Ending
from kb_mcp.kernel.names import RUN_ID, RefusedError
from kb_mcp.kernel.outcome import OutcomeWarning, Problem
from kb_mcp.kernel.record import Record

if TYPE_CHECKING:
    from collections.abc import Collection, Iterable, Sequence
    from pathlib import Path

    from kb_mcp.config.domain.settings import Settings


class Unit(Record):
    """A unit of a run: a stage over one source, by its position among that source's, or the whole.

    ``part`` is the position of the preparer that it runs among its source's, 0 for any
    other unit.
    """

    stage: Stage
    source: str | None = None
    part: int = 0

    @property
    def name(self) -> str:
        """Name it as a person reads it: its stage, then its source, if any."""
        return self.stage if self.source is None else f"{self.stage} {self.source}"


class Configuration(Record):
    """What decides a run, resolved as it starts, then recorded and read back.

    Its id, its command and its start; the stages that it enables, in pipeline order;
    whether it is a dry run; the sources that each stage per source takes, in their
    order; each stage's options by flag, each relative value made absolute against the
    start; and the settings, as JSON, without any secret.
    """

    run: str
    command: str
    started: AwareDatetime
    stages: tuple[Stage, ...]
    dry_run: bool = False
    sources: Mapping[Stage, tuple[str, ...]] = Field(default_factory=dict)
    options: Mapping[Stage, Mapping[str, JsonValue]] = Field(default_factory=dict)
    settings: Mapping[str, JsonValue]

    @model_validator(mode="after")
    def check_configuration(self) -> Self:
        """Refuse another run id, no stage or stages out of order, or sources of no stage.

        Each stage enabled per source has its sources, and only those; fetch and index,
        when enabled, have their options, and only they: index's ``--rebuild``, true or
        false.
        """
        if not RUN_ID.fullmatch(self.run):
            message = f"run: not a run id, {RUN_ID.pattern}"
            raise RefusedError(message)
        if not self.stages or list(self.stages) != [each for each in STAGES if each in self.stages]:
            message = f"stages: some of {', '.join(STAGES)}, in that order, each once"
            raise RefusedError(message)
        if set(self.sources) != {each for each in self.stages if each not in WHOLE}:
            message = "sources: those of each stage enabled per source, and only those"
            raise RefusedError(message)
        rebuild = self.options.get(INDEX, {}).get("--rebuild")
        taking = {each for each in self.stages if each in {FETCH, INDEX}}
        if set(self.options) != taking or (INDEX in taking and not isinstance(rebuild, bool)):
            message = (
                "options: fetch's and index's, when enabled, and only those; --rebuild, a boolean"
            )
            raise RefusedError(message)
        return self


class Recorded(Record):
    """A unit's last entry: its stage and source, how it ended, what it gave, and when.

    Its counts as JSON, its problems and warnings, and the start of the invocation that
    gave it, which names that invocation's log file.
    """

    stage: Stage
    source: str | None
    ending: Ending
    counts: JsonValue = None
    problems: tuple[Problem, ...] = ()
    warnings: tuple[OutcomeWarning, ...] = ()
    invocation: AwareDatetime


class Outcomes(Record):
    """Each unit's last entry, in the order of the units."""

    units: tuple[Recorded, ...] = ()


def units_of(configuration: Configuration, parts: Mapping[str, int]) -> tuple[Unit, ...]:
    """Give a configuration's units in the order in which they run.

    Each stage enabled, in pipeline order: over the whole, one unit; per source, one for
    each of its sources in their order, and in prepare one for each of a source's
    ``parts``, its preparers, by position.
    """
    return tuple(
        unit
        for stage in configuration.stages
        for unit in (
            (Unit(stage=stage),)
            if stage in WHOLE
            else tuple(
                Unit(stage=stage, source=name, part=part)
                for name in configuration.sources[stage]
                for part in range(parts[name] if stage == PREPARE else 1)
            )
        )
    )


def followed(unit: Unit, units: Sequence[Unit]) -> tuple[Unit, ...]:
    """Give the units that ``unit`` runs after: those of the stage enabled before its own.

    A unit per source follows its own source's alone; a unit over the whole, every one.
    """
    stages = list(dict.fromkeys(each.stage for each in units))
    at = stages.index(unit.stage)
    return tuple(
        each
        for each in units
        if at and each.stage == stages[at - 1] and unit.source in {None, each.source}
    )


def attempted(units: Sequence[Unit], last: Mapping[Unit, Ending]) -> frozenset[Unit]:
    """Give the units that an invocation runs: each not last ended done, and each after one.

    So a unit done is run again when a unit that it follows is: an index done, after a
    source's fetch that runs again.
    """
    chosen: set[Unit] = set()
    for unit in units:
        if last.get(unit) != "done" or any(each in chosen for each in followed(unit, units)):
            chosen.add(unit)
    return frozenset(chosen)


def resumable(entries: Iterable[Recorded], settled: Collection[Unit]) -> bool:
    """Say whether a resume of a run could do what a new run would not, by its last entries.

    So when some unit last ended other than done, but each that the settings recorded
    refuse (``settled``), which a resume, run by them, refuses again, and each not run
    as it follows one of those.
    """
    found = keyed(entries)
    units = tuple(found)
    return any(
        entry.ending != "done"
        and unit not in settled
        and not (entry.ending == "not run" and set(followed(unit, units)) & set(settled))
        for unit, entry in found.items()
    )


def keyed(entries: Iterable[Recorded]) -> dict[Unit, Recorded]:
    """Give each entry by its unit: its stage, its source and its position among theirs."""
    seen: Counter[tuple[Stage, str | None]] = Counter()
    found: dict[Unit, Recorded] = {}
    for entry in entries:
        place = (entry.stage, entry.source)
        found[Unit(stage=entry.stage, source=entry.source, part=seen[place])] = entry
        seen[place] += 1
    return found


def resume_refused(
    settings: Settings,
    units: Sequence[Unit],
    last: Mapping[Unit, Ending],
    *,
    data_dir: Path,
    remote_allowed: bool,
) -> str | None:
    """Say why this invocation may not resume a run of these settings, or None when it may.

    ``settings`` are the run's, as recorded; ``data_dir``, where its record was found,
    which must be its own. An embedding endpoint off this machine needs this invocation's
    consent, ``remote_allowed``, when embed runs again.
    """
    if settings.data_dir != data_dir:
        return f"recorded for the data directory {settings.data_dir}"
    embeds = any(unit.stage == EMBED for unit in attempted(units, last))
    refusal = refused_endpoint(settings.embedding_url, EMBEDDINGS, remote_allowed=remote_allowed)
    return f"{EMBEDDINGS.setting}: {refusal}" if embeds and refusal else None


def resume_said(
    configuration: Configuration,
    units: Sequence[Unit],
    last: Mapping[Unit, Ending],
    refused: Mapping[str, str],
) -> str:
    """Say what a resume of a run will do: whose run it is, its units done, those it runs.

    Each unit that it runs with its last ending, or ``none yet``; then each fetch that it
    runs that will not run, as ``refused`` says why by its source, by the settings that
    the run recorded, and each unit after one of those, which will not run either. A
    unit after a fetch done runs, whatever ``refused`` says of its source.
    """
    chosen = attempted(units, last)
    done = [unit.name for unit in units if unit not in chosen]
    runs = [f"{unit.name} ({last.get(unit, 'none yet')})" for unit in units if unit in chosen]
    refusing = {unit for unit in chosen if unit.stage == FETCH and unit.source in refused}
    unrun = [
        f"  {unit.name}: will not run, by the settings that the run recorded:"
        f" {refused[unit.source]}\n"
        if unit in refusing
        else f"  {unit.name}: will not run, as its fetch will not\n"
        for unit in units
        if unit in refusing or refusing & set(followed(unit, units))
    ]
    return (
        f"refresh --resume {configuration.run}: the run of {configuration.command}, started"
        f" {configuration.started.isoformat()}\n"
        f"  done: {', '.join(done) or 'none'}\n"
        f"  to run: {', '.join(runs) or 'none'}\n" + "".join(dict.fromkeys(unrun))
    )
