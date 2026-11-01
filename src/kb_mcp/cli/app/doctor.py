"""``doctor``'s run: the machine's checks, then each sign-in's, each with a verdict."""

from __future__ import annotations

import pkgutil
import shutil
import sys
from typing import TYPE_CHECKING

from kb_mcp.sources.roles import FAILED, Verdict

if TYPE_CHECKING:
    from collections.abc import Iterable

    from kb_mcp.config.domain.settings import Settings
    from kb_mcp.sources.declaration import Account


def pandoc() -> Verdict:
    """Say where the pandoc that the mirror needs is on PATH, or that there is none."""
    found = shutil.which("pandoc")
    return (
        Verdict(name="pandoc", found=found)
        if found
        else Verdict(name="pandoc", found="not found on PATH", state=FAILED)
    )


def doctor(settings: Settings, accounts: Iterable[Account]) -> list[Verdict]:
    """Check the machine, then each account by the checks that it names; give every verdict."""
    verdicts = [
        Verdict(name="python", found=sys.version.split()[0]),
        pandoc(),
        Verdict(name="data directory", found=f"{settings.data_dir}: allowed"),
    ]
    for account in accounts:
        verdicts += pkgutil.resolve_name(account.checks)(settings)
    return verdicts
