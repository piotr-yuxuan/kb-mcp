"""``login``: sign in once in a Chrome window, and keep the session for later runs."""

from __future__ import annotations

import pkgutil
import sys
from typing import TYPE_CHECKING

from kb_mcp.kernel.exit_status import ExitStatus
from kb_mcp.sources.registry import accounts_of

if TYPE_CHECKING:
    import argparse

    from kb_mcp.config.domain.settings import Loaded
    from kb_mcp.kernel.output import Summary
    from kb_mcp.sources.roles import SignedIn


def run(arguments: argparse.Namespace, loaded: Loaded) -> tuple[ExitStatus, SignedIn | None]:
    """Sign in by the account named, which the declaration requires; exit 3 when none completes.

    The run is the one that its account's declaration names, loaded by that path, so that
    this module imports neither the browser's adapter nor Playwright. What to do in the
    window goes to stderr, a line for the user, so that stdout holds the result alone; the
    run says why a sign-in did not complete.
    """
    settings = loaded.settings
    account = accounts_of(arguments.sources)[arguments.account]
    site = getattr(getattr(settings.accounts, account.name), account.settings[0])
    sys.stderr.write(f"Sign in to {site} in the Chrome window that opens.\n")
    signing = pkgutil.resolve_name(account.login)
    signed = signing(settings, arguments.chrome, extensions=arguments.keep_extensions)
    return (ExitStatus.SIGN_IN_AGAIN, None) if signed is None else (ExitStatus.OK, signed)


def text(_signed_in: SignedIn, _summary: Summary) -> str:
    """Say that the session is saved."""
    return "Signed in; the session is saved.\n"
