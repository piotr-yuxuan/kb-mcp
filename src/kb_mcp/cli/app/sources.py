"""A source's part in a stage per source, as a unit: its fetcher, or one of its preparers.

A connector names its fetcher and its preparers by module path, which this module loads
for the run that uses it, never ``--help``.
"""

from __future__ import annotations

import pkgutil
from functools import partial
from typing import TYPE_CHECKING

from kb_mcp.cli.app.units import Planned, SourcesRefusedError
from kb_mcp.cli.domain.command import FETCH, PREPARE
from kb_mcp.config.domain.settings import values_of, without_secrets
from kb_mcp.sources.stages import Fetcher, Preparer

if TYPE_CHECKING:
    from kb_mcp.cli.domain.runs import Unit
    from kb_mcp.sources.declaration import Source
    from kb_mcp.sources.stages import SourceRun


def loaded[R: (Fetcher, Preparer)](declared: Source, path: str, interface: type[R]) -> R:
    """Load a fetcher or a preparer by the module path that its source's connector names.

    Raises ``SourcesRefusedError``, naming the source and the path, for a path that does
    not load, whatever its import raises, such as a syntax error in a module of the
    source's or its own error at import, or for what it names that lacks the interface's
    methods.
    """
    stage = FETCH if interface is Fetcher else PREPARE
    try:
        found = pkgutil.resolve_name(path)
    except Exception as error:
        message = f"source {declared.name!r}: {path}: does not load: {error}"
        raise SourcesRefusedError(message, stage) from error
    if not isinstance(found, interface):
        message = f"source {declared.name!r}: {path}: not a {interface.__name__}"
        raise SourcesRefusedError(message, stage)
    return found


def source_planned(unit: Unit, run: SourceRun) -> Planned:
    """Give a unit per source as its source's fetcher, or its preparer of the unit's part, does it.

    A fetch is refused by its source's light check of the run's settings
    (``Source.refusal``), else by its fetcher's preflight: either fails the unit alone.
    What the check refuses of the settings without their secrets, such as a site not set,
    is the unit's ``refused``, as every invocation of the run would refuse it; what it
    refuses only with this invocation's secrets, such as an API token without its email,
    begins its preflight, as a resume takes its secrets from its own environment. Raises
    ``SourcesRefusedError`` as ``loaded`` does.
    """
    connector = run.source.connector
    if unit.stage == FETCH:
        fetcher = loaded(run.source, str(connector.fetcher), Fetcher)
        secretless = type(run.settings).model_validate(without_secrets(run.settings))
        return Planned(
            unit=unit,
            act=partial(fetcher.fetch, run),
            refused=run.source.refusal(values_of(secretless)),
            preflight=lambda: run.source.refusal(values_of(run.settings)) or fetcher.preflight(run),
        )
    preparer = loaded(run.source, connector.preparers[unit.part], Preparer)
    return Planned(
        unit=unit, act=partial(preparer.prepare, run), preflight=partial(preparer.preflight, run)
    )
