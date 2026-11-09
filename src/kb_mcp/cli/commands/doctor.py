"""``doctor``: check the machine, the data directory and each sign-in, by session or token."""

from __future__ import annotations

from typing import TYPE_CHECKING

from kb_mcp.cli.app.doctor import doctor
from kb_mcp.cli.domain.sources import accounts_to_check
from kb_mcp.cli.domain.summary import values_of
from kb_mcp.kernel.exit_status import ExitStatus
from kb_mcp.sources.stages import FAILED, SIGN_IN, WELL

if TYPE_CHECKING:
    import argparse

    from kb_mcp.config.domain.settings import Loaded
    from kb_mcp.kernel.output import Summary
    from kb_mcp.sources.stages import Verdict


def run(arguments: argparse.Namespace, loaded: Loaded) -> tuple[ExitStatus, list[Verdict]]:
    """Give each check's verdict; exit 1 if one fails, 3 to sign in again.

    A machine that uses no sign-in, as ``accounts_to_check`` judges, gets the machine's alone.
    """
    accounts = accounts_to_check(arguments.sources, values_of(loaded))
    verdicts = doctor(loaded.settings, accounts.values())
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
