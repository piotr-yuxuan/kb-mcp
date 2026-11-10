"""``doctor``'s run: the machine's checks, then each sign-in's, each with what it found."""

from __future__ import annotations

import pkgutil
import shutil
import sys
from typing import TYPE_CHECKING

from kb_mcp.sources.stages import Check

if TYPE_CHECKING:
    from collections.abc import Iterable

    from kb_mcp.config.domain.settings import Settings
    from kb_mcp.sources.declaration import Source


def pandoc() -> Check:
    """Say where the pandoc that the mirror needs is on PATH, or that there is none."""
    found = shutil.which("pandoc")
    return (
        Check(name="pandoc", found=found)
        if found
        else Check(name="pandoc", found="not found on PATH", state="failed")
    )


def doctor(settings: Settings, sources: Iterable[Source]) -> list[Check]:
    """Check the machine, then the sources by the checks that their connectors name.

    The sources of one checks' function are checked by one call, in the order of the
    first of them, so that sources that share a sign-in are checked once.
    """
    checks = [
        Check(name="python", found=sys.version.split()[0]),
        pandoc(),
        Check(name="data directory", found=f"{settings.data_dir}: allowed"),
    ]
    by_checks: dict[str, list[Source]] = {}
    for each in sources:
        by_checks.setdefault(str(each.connector.checks), []).append(each)
    for path, checked in by_checks.items():
        checks += pkgutil.resolve_name(path)(settings, tuple(checked))
    return checks
