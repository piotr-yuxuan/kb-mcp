"""``doctor``: check the machine, the data directory and each sign-in, by session or token."""

from __future__ import annotations

from typing import TYPE_CHECKING

from kb_mcp.cli.app.doctor import doctor
from kb_mcp.cli.domain.preview import values_of
from kb_mcp.cli.domain.sources import accounts_to_check
from kb_mcp.kernel.exit_status import ExitStatus, folded

if TYPE_CHECKING:
    import argparse

    from kb_mcp.config.domain.settings import Loaded
    from kb_mcp.kernel.output import Detail
    from kb_mcp.sources.stages import Check


def run(arguments: argparse.Namespace, loaded: Loaded) -> tuple[ExitStatus, list[Check]]:
    """Give each check; exit as the worst of them ends the run: 1 failed, 3 to sign in again.

    A machine that uses no sign-in, as ``accounts_to_check`` judges, gets the machine's alone.
    """
    accounts = accounts_to_check(arguments.sources, values_of(loaded))
    checks = doctor(loaded.settings, accounts.values())
    return folded("done" if each.state == "well" else each.state for each in checks), checks


def text(checks: list[Check], summary: Detail) -> str:
    """Write what the checks not well found, in detail every one, then how many are well."""
    shown = [each for each in checks if summary == "detailed" or each.state != "well"]
    well = sum(each.state == "well" for each in checks)
    return "".join(f"{each.name}: {each.found}\n" for each in shown) + (
        f"{well} of {len(checks)} checks well\n"
    )
