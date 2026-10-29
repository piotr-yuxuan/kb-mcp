"""``login``: sign in once in a Chrome window, and keep the session for later runs."""

from __future__ import annotations

import sys
from dataclasses import dataclass
from typing import TYPE_CHECKING

import structlog

from kb_mcp.kernel.exit_status import ExitStatus
from kb_mcp.sources.atlassian.adapters.browser import SignInFailedError
from kb_mcp.sources.atlassian.app.login import login

if TYPE_CHECKING:
    import argparse
    from pathlib import Path

    from kb_mcp.config.domain.settings import Loaded
    from kb_mcp.kernel.output import Summary


@dataclass(frozen=True)
class SignedIn:
    """The site signed in to, and the folder that keeps its session."""

    site: str
    session: Path


def run(arguments: argparse.Namespace, loaded: Loaded) -> tuple[ExitStatus, SignedIn | None]:
    """Sign in to the site, which the declaration requires; exit 3 when no sign-in completes.

    What to do in the window goes to stderr, a line for the user, so that stdout holds
    the result alone; a sign-in that does not complete is an error.
    """
    settings = loaded.settings
    site = str(settings.site)
    sys.stderr.write(f"Sign in to {site} in the Chrome window that opens.\n")
    try:
        login(settings, site, arguments.chrome, extensions=arguments.keep_extensions)
    except SignInFailedError as error:
        structlog.get_logger().error("login.not_signed_in", reason=str(error))
        return ExitStatus.SIGN_IN_AGAIN, None
    return ExitStatus.OK, SignedIn(site=site, session=settings.session)


def text(_signed_in: SignedIn, _summary: Summary) -> str:
    """Say that the session is saved."""
    return "Signed in; the session is saved.\n"
