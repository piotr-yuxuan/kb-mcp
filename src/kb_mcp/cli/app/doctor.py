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
    from kb_mcp.sources.declaration import Account


def pandoc() -> Check:
    """Say where the pandoc that the mirror needs is on PATH, or that there is none."""
    found = shutil.which("pandoc")
    return (
        Check(name="pandoc", found=found)
        if found
        else Check(name="pandoc", found="not found on PATH", state="failed")
    )


def doctor(settings: Settings, accounts: Iterable[Account]) -> list[Check]:
    """Check the machine, then each account by the checks that it names; give every check."""
    checks = [
        Check(name="python", found=sys.version.split()[0]),
        pandoc(),
        Check(name="data directory", found=f"{settings.data_dir}: allowed"),
    ]
    for account in accounts:
        checks += pkgutil.resolve_name(account.checks)(settings)
    return checks
