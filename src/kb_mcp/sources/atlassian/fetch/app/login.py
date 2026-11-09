"""Signing in once, in a browser, and keeping the session for later runs."""

from __future__ import annotations

from typing import TYPE_CHECKING
from urllib.parse import urlsplit

import structlog

from kb_mcp.sources.atlassian.fetch.adapters.browser import (
    SignInFailedError,
    disable_password_saving,
    open_sign_in_window,
)
from kb_mcp.sources.atlassian.fetch.adapters.session_file import (
    COOKIES,
    for_site,
    write_cookies,
)
from kb_mcp.sources.stages import SignedIn

if TYPE_CHECKING:
    from pathlib import Path

    from kb_mcp.config.domain.settings import Settings

PROFILE = "browser"


def save_session(settings: Settings, site: str, chrome: Path | None, *, extensions: bool) -> None:
    """Open the sign-in window, wait for the user, and save the site's cookies.

    The browser profile and the cookies stay under ``Settings.session``, readable by the
    user alone. Raises SignInFailedError when the user does not finish in time.
    """
    profile = settings.session / PROFILE
    profile.mkdir(parents=True, exist_ok=True, mode=0o700)
    settings.session.chmod(0o700)
    disable_password_saving(profile)
    cookies = open_sign_in_window(site, profile, chrome, extensions=extensions)
    write_cookies(settings.session / COOKIES, for_site(cookies, urlsplit(site).hostname or ""))


def login(settings: Settings, chrome: Path | None, *, extensions: bool) -> SignedIn | None:
    """Sign in to the account's site; a sign-in that does not complete is an error, and None."""
    site = str(settings.accounts.atlassian.site)
    try:
        save_session(settings, site, chrome, extensions=extensions)
    except SignInFailedError as error:
        structlog.get_logger().error("login.not_signed_in", reason=str(error))
        return None
    return SignedIn(site=site, session=settings.session)
