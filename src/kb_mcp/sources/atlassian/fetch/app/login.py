"""Signing in once, in a browser, and keeping the session for later runs."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

import structlog

from kb_mcp.kernel.record import Record
from kb_mcp.sources.atlassian.fetch.adapters.browser import (
    SignInFailedError,
    disable_password_saving,
    open_sign_in_window,
)
from kb_mcp.sources.atlassian.fetch.adapters.session_file import (
    COOKIES,
    PROFILE,
    adopt_former_session,
    folder_of,
    for_site,
    write_cookies,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from kb_mcp.config.domain.settings import Settings
    from kb_mcp.sources.declaration import Source


class SignedIn(Record):
    """The site signed in to, and the folder that keeps its session."""

    site: str
    session: Path


def save_session(settings: Settings, site: str, chrome: Path | None, *, extensions: bool) -> None:
    """Open the sign-in window, wait for the user, and save the site's cookies.

    The browser profile and the cookies stay in the site's folder of ``Settings.session``,
    readable by the user alone, where a session kept before sessions were a site's first
    moves, its profile signed in. Raises SignInFailedError when the user does not finish
    in time.
    """
    folder = folder_of(settings.session, site)
    adopt_former_session(settings.session, site)
    profile = folder / PROFILE
    profile.mkdir(parents=True, exist_ok=True, mode=0o700)
    settings.session.chmod(0o700)
    folder.chmod(0o700)
    disable_password_saving(profile)
    cookies = open_sign_in_window(site, profile, chrome, extensions=extensions)
    write_cookies(folder / COOKIES, for_site(cookies, urlsplit(site).hostname or ""))


def login(
    settings: Settings,
    sources: Sequence[Source],
    chrome: Path | None,
    *,
    extensions: bool,
    named: bool,
) -> tuple[SignedIn, ...] | None:
    """Sign in to the site of each source, once a site, one after another.

    A source not ``named`` that signs in by an API token is left: a session would serve it
    nothing. A sign-in that does not complete is an error, and None; no site after it is
    tried.
    """
    tables = [getattr(settings.sources, each.name) for each in sources]
    sites = dict.fromkeys(str(each.site) for each in tables if named or each.api_token is None)
    signed: list[SignedIn] = []
    for site in sites:
        try:
            save_session(settings, site, chrome, extensions=extensions)
        except SignInFailedError as error:
            structlog.get_logger().error("login.not_signed_in", site=site, reason=str(error))
            return None
        signed.append(SignedIn(site=site, session=folder_of(settings.session, site)))
    return tuple(signed)
