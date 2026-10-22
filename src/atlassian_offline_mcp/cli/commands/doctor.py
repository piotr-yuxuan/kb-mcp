"""``doctor``: check the machine, the data directory and the sign-in, by session or token."""

from __future__ import annotations

from typing import TYPE_CHECKING

from atlassian_offline_mcp.kernel.exit_status import ExitStatus
from atlassian_offline_mcp.sources.atlassian.app.doctor import FAILED, SIGN_IN, WELL, doctor

if TYPE_CHECKING:
    import argparse

    from atlassian_offline_mcp.config.domain.settings import Loaded
    from atlassian_offline_mcp.kernel.output import Summary
    from atlassian_offline_mcp.sources.atlassian.app.doctor import Verdict


def run(_arguments: argparse.Namespace, loaded: Loaded) -> tuple[ExitStatus, list[Verdict]]:
    """Give each check's verdict; exit 1 if one fails, 3 to sign in again."""
    settings = loaded.settings
    verdicts = doctor(settings)
    states = {verdict.state for verdict in verdicts}
    if SIGN_IN in states:
        return ExitStatus.SIGN_IN_AGAIN, verdicts
    return ExitStatus.FAILED if FAILED in states else ExitStatus.OK, verdicts


def text(verdicts: list[Verdict], summary: Summary) -> str:
    """Write the verdicts of the checks not well, in detail every one, then how many are well."""
    shown = [verdict for verdict in verdicts if summary == "detailed" or verdict.state != WELL]
    well = sum(verdict.state == WELL for verdict in verdicts)
    return "".join(f"{verdict.name}: {verdict.found}\n" for verdict in shown) + (
        f"{well} of {len(verdicts)} checks well\n"
    )
