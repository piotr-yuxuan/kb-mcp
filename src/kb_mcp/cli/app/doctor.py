"""``doctor``'s run: the machine's checks, then each sign-in's, each with what it found."""

from __future__ import annotations

import pkgutil
import shutil
import sys
from typing import TYPE_CHECKING

from kb_mcp.cli.domain.sources import refusals
from kb_mcp.config.settings import values_of
from kb_mcp.sources.stages import Check

if TYPE_CHECKING:
    from collections.abc import Sequence

    from kb_mcp.config.settings import Settings
    from kb_mcp.sources.declaration import Source


def doctor(settings: Settings, sources: Sequence[Source]) -> list[Check]:
    """Check the machine, then the sources by the checks that their connectors name.

    The sources of one checks' function are checked once, by one call, in the order of the
    first of them; one that its light check refuses fails a check of its own instead, after
    the others.
    """
    found = shutil.which("pandoc")  # The mirror needs it.
    checks = [
        Check(name="python", found=sys.version.split()[0]),
        Check(name="pandoc", found=found)
        if found
        else Check(name="pandoc", found="not found on PATH", state="failed"),
        Check(name="data directory", found=f"{settings.data_dir}: allowed"),
    ]
    refused = refusals(sources, values_of(settings))
    by_checks: dict[str, list[Source]] = {}
    for each in (each for each in sources if each.name not in refused):
        by_checks.setdefault(str(each.connector.checks), []).append(each)
    for path, checked in by_checks.items():
        checks += pkgutil.resolve_name(path)(settings, tuple(checked))
    return checks + [Check(name=name, found=why, state="failed") for name, why in refused.items()]
