"""A source's part in a stage per source, as a unit: its fetcher, or one of its preparers.

Each is loaded by the module path that its connector names, for the run that uses it,
never for ``--help``.
"""

from __future__ import annotations

import pkgutil
from functools import partial
from typing import TYPE_CHECKING

from kb_mcp.cli.app.units import Planned, SourcesRefusedError
from kb_mcp.cli.domain.command import FETCH, PREPARE
from kb_mcp.config.settings import values_of, without_secrets
from kb_mcp.sources.stages import Fetcher, Preparer

if TYPE_CHECKING:
    from kb_mcp.cli.domain.runs import Unit
    from kb_mcp.sources.declaration import Source
    from kb_mcp.sources.stages import SourceRun


def loaded[R: (Fetcher, Preparer)](source: Source, path: str, interface: type[R]) -> R:
    """Load a fetcher or a preparer by the module path that its source's connector names.

    Raises ``SourcesRefusedError``, naming the source and the path, for a path that does
    not load, whatever its import raises, or that names what lacks the interface's methods.
    """
    stage = FETCH if interface is Fetcher else PREPARE
    try:
        found = pkgutil.resolve_name(path)
    except Exception as error:
        message = f"source {source.name!r}: {path}: does not load: {error}"
        raise SourcesRefusedError(message, stage) from error
    if not isinstance(found, interface):
        message = f"source {source.name!r}: {path}: not a {interface.__name__}"
        raise SourcesRefusedError(message, stage)
    return found


def source_planned(unit: Unit, run: SourceRun) -> Planned:
    """Give a unit per source as its source's fetcher, or its preparer of the unit's part, does it.

    A fetch's light check, like its preflight, fails the unit alone: what it refuses of the
    settings without their secrets is the unit's ``refused``; what it refuses only with
    this invocation's secrets begins its preflight, as a resume takes its secrets from its
    own environment. Raises ``SourcesRefusedError`` as ``loaded`` does.
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
