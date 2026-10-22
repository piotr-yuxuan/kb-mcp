"""``login``: sign in once in a Chrome window, and keep the session for later runs."""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

from atlassian_offline_mcp.kernel.exit_status import ExitStatus
from atlassian_offline_mcp.sources.atlassian.adapters.browser import SignInFailedError
from atlassian_offline_mcp.sources.atlassian.app.login import login

if TYPE_CHECKING:
    import argparse

    from atlassian_offline_mcp.config.domain.settings import Settings


def run(arguments: argparse.Namespace, settings: Settings) -> ExitStatus:
    """Sign in; exit 2 without a site, 3 when no sign-in completes."""
    if settings.site is None:
        sys.stderr.write("settings refused: site: not set; add it to the settings or pass --site\n")
        return ExitStatus.REFUSED
    sys.stdout.write(f"Sign in to {settings.site} in the Chrome window that opens.\n")
    try:
        login(settings, settings.site, arguments.chrome, extensions=arguments.keep_extensions)
    except SignInFailedError as error:
        sys.stderr.write(f"not signed in: {error}\n")
        return ExitStatus.SIGN_IN_AGAIN
    sys.stdout.write("Signed in; the session is saved.\n")
    return ExitStatus.OK
