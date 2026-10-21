"""Signing in once, in a browser, and keeping the session for later runs."""

from __future__ import annotations

from typing import TYPE_CHECKING

from atlassian_offline_mcp.adapters.browser import disable_password_saving, sign_in
from atlassian_offline_mcp.adapters.session_file import COOKIES, write_cookies

if TYPE_CHECKING:
    from atlassian_offline_mcp.domain.settings import Settings

PROFILE = "browser"


def login(settings: Settings, site: str, chrome: str | None) -> None:
    """Open the sign-in window, wait for the user, and save the site's cookies.

    The browser profile and the cookies stay under ``Settings.session``, readable by the
    user alone. Raises SignInTimeoutError when the user does not finish in time.
    """
    profile = settings.session / PROFILE
    profile.mkdir(parents=True, exist_ok=True, mode=0o700)
    settings.session.chmod(0o700)
    disable_password_saving(profile)
    write_cookies(settings.session / COOKIES, sign_in(site, profile, chrome))
