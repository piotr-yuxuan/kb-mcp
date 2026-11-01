"""``doctor``: check the machine, the data directory and each sign-in, by session or token."""

from __future__ import annotations

from typing import TYPE_CHECKING

from kb_mcp.cli.app.doctor import doctor
from kb_mcp.cli.domain.summary import values_of
from kb_mcp.kernel.exit_status import ExitStatus
from kb_mcp.sources.roles import FAILED, SIGN_IN, WELL

if TYPE_CHECKING:
    import argparse

    from kb_mcp.config.domain.settings import Loaded
    from kb_mcp.kernel.output import Summary
    from kb_mcp.sources.roles import Verdict


def run(arguments: argparse.Namespace, loaded: Loaded) -> tuple[ExitStatus, list[Verdict]]:
    """Give each check's verdict; exit 1 if one fails, 3 to sign in again.

    A sign-in is checked when a source naming it is configured, or its first setting, where
    it signs in, is set: a machine with neither needs none, and gets the machine's alone.
    """
    values = values_of(loaded)
    accounts = {
        declared.account.name: declared.account
        for declared in arguments.sources
        if declared.account is not None
        and (values[declared.paths[0]] or values[declared.account.paths[0]])
    }
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
