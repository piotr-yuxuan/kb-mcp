"""How the units of any configuration are done, each as its stage does it, with its sources.

What ``fetch``, ``prepare`` and ``refresh`` share: per source, by its fetcher or its
preparers; over the whole, as ``_runs`` says.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from kb_mcp.cli.app.resumption import require_configured
from kb_mcp.cli.app.sources import source_planned
from kb_mcp.cli.commands._runs import whole_planned
from kb_mcp.cli.domain.command import FETCH
from kb_mcp.cli.domain.runs import units_of
from kb_mcp.sources.stages import SourceRun

if TYPE_CHECKING:
    import argparse

    from kb_mcp.cli.app.units import Planned
    from kb_mcp.cli.domain.runs import Configuration
    from kb_mcp.config.domain.settings import Settings


def planned(
    arguments: argparse.Namespace, configuration: Configuration, settings: Settings
) -> list[Planned]:
    """Give each unit of a configuration as its stage does it, with the run's settings.

    A unit per source is a run of its source, of those that the settings configure, with
    its table, its options as the configuration records them, by flag, in a fetch, and
    the configuration's dry run; a unit over the whole, as ``whole_planned`` says. Raises
    RefusedError, as ``require_configured`` does, for a configuration that the sources
    configured no longer run, and ``SourcesRefusedError`` for a fetcher or a preparer
    that does not load.
    """
    by_name = {each.name: each for each in arguments.sources}
    require_configured(configuration, by_name)
    parts = {name: len(each.connector.preparers) for name, each in by_name.items()}
    options = configuration.options.get(FETCH, {})
    units: list[Planned] = []
    for unit in units_of(configuration, parts):
        if unit.source is None:
            units.append(whole_planned(arguments, unit, configuration, settings))
            continue
        declared = by_name[unit.source]
        run = SourceRun(
            source=declared,
            sources=arguments.sources,
            settings=settings,
            source_table=getattr(settings.sources, declared.name),
            options=(
                {flag: options.get(flag) for flag in declared.connector.flags}
                if unit.stage == FETCH
                else {}
            ),
            now=lambda: datetime.now(UTC),
            sleep=time.sleep,
            dry_run=configuration.dry_run,
        )
        units.append(source_planned(unit, run))
    return units
