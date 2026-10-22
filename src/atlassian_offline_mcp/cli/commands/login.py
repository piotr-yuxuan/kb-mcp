"""``login``: sign in once in a Chrome window, and keep the session for later runs."""

from __future__ import annotations

import sys
from dataclasses import dataclass
from typing import TYPE_CHECKING

from atlassian_offline_mcp.kernel.exit_status import ExitStatus
from atlassian_offline_mcp.sources.atlassian.adapters.browser import SignInFailedError
from atlassian_offline_mcp.sources.atlassian.app.login import login

if TYPE_CHECKING:
    import argparse
    from pathlib import Path

    from atlassian_offline_mcp.config.domain.settings import Loaded
    from atlassian_offline_mcp.kernel.output import Summary


@dataclass(frozen=True)
class SignedIn:
    """The site signed in to, and the folder that keeps its session."""

    site: str
    session: Path


def run(arguments: argparse.Namespace, loaded: Loaded) -> tuple[ExitStatus, SignedIn | None]:
    """Sign in to the site, which the declaration requires; exit 3 when no sign-in completes.

    What to do in the window goes to stderr, with the messages, so that stdout holds
    the result alone.
    """
    settings = loaded.settings
    site = str(settings.site)
    sys.stderr.write(f"Sign in to {site} in the Chrome window that opens.\n")
    try:
        login(settings, site, arguments.chrome, extensions=arguments.keep_extensions)
    except SignInFailedError as error:
        sys.stderr.write(f"not signed in: {error}\n")
        return ExitStatus.SIGN_IN_AGAIN, None
    return ExitStatus.OK, SignedIn(site, settings.session)


def text(_signed_in: SignedIn, _summary: Summary) -> str:
    """Say that the session is saved."""
    return "Signed in; the session is saved.\n"
