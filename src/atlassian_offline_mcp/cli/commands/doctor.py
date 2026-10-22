"""``doctor``: check the machine, the data directory and the saved session."""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

from atlassian_offline_mcp.kernel.exit_status import ExitStatus
from atlassian_offline_mcp.sources.atlassian.app.doctor import FAILED, SIGN_IN, doctor

if TYPE_CHECKING:
    import argparse

    from atlassian_offline_mcp.config.domain.settings import Settings


def run(_arguments: argparse.Namespace, settings: Settings) -> ExitStatus:
    """Print each check's verdict; exit 1 if one fails, 3 to sign in again."""
    verdicts = doctor(settings)
    for verdict in verdicts:
        sys.stdout.write(f"{verdict.name}: {verdict.found}\n")
    states = {verdict.state for verdict in verdicts}
    if SIGN_IN in states:
        return ExitStatus.SIGN_IN_AGAIN
    return ExitStatus.FAILED if FAILED in states else ExitStatus.OK
