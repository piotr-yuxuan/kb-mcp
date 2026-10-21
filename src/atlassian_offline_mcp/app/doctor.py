"""Checks of the machine and the session that a download needs, each with a verdict."""

from __future__ import annotations

import shutil
import ssl
import sys
from typing import TYPE_CHECKING

import certifi
import httpx

from atlassian_offline_mcp.adapters import confluence_v2, http, jira_v3
from atlassian_offline_mcp.adapters.fields import Fields, RepresentationError
from atlassian_offline_mcp.adapters.http import SignInNeededError, Site, SiteError
from atlassian_offline_mcp.adapters.session_file import COOKIES, read_cookies

if TYPE_CHECKING:
    from atlassian_offline_mcp.domain.settings import Settings

# How many causes to follow to find a certificate error within a connection error.
CAUSE_DEPTH = 10


def pandoc() -> str:
    """Say where the pandoc that the mirror needs is on PATH, or that there is none."""
    found = shutil.which("pandoc")
    return "not found on PATH" if found is None else found


def public_trust(site: str) -> str:
    """Say whether the public CA bundle verifies the site: if not, TLS is inspected.

    httpx then needs the operating system's trust store, which every run uses already.
    """
    with httpx.Client(
        timeout=http.TIMEOUT_S, verify=ssl.create_default_context(cafile=certifi.where())
    ) as client:
        try:
            client.get(f"{site}/wiki/rest/api/user/current")
        except httpx.HTTPError as error:
            cause: BaseException | None = error
            for _ in range(CAUSE_DEPTH):
                if cause is None or isinstance(cause, ssl.SSLCertVerificationError):
                    break
                cause = cause.__cause__ or cause.__context__
            if isinstance(cause, ssl.SSLCertVerificationError):
                return "not verified by public CAs: TLS is inspected; the OS trust store is used"
            return f"inconclusive ({type(error).__name__})"
    return "verified by public CAs"


def session(settings: Settings, site: str) -> list[tuple[str, str]]:
    """Say whether the saved session still signs in to Confluence and to Jira."""
    try:
        cookies = read_cookies(settings.session / COOKIES)
    except OSError, ValueError:
        return [("session", "none saved: run atlassian-offline-mcp login")]
    verdicts = [("session", f"{len(cookies)} cookies saved")]
    with http.client(site, cookies) as client:
        reader = Site(client)
        for name, request, signed_in in (
            ("confluence", confluence_v2.current_user_request(), confluence_v2.signed_in),
            ("jira", jira_v3.myself_request(), jira_v3.signed_in),
        ):
            try:
                user = Fields(reader.json(request), "user")
                verdict = "signed in" if signed_in(user) else "anonymous: sign in again"
            except SignInNeededError:
                verdict = "refused: sign in again"
            except (RepresentationError, SiteError) as error:
                verdict = f"no answer ({error})"
            verdicts.append((name, verdict))
    return verdicts


def doctor(settings: Settings) -> list[tuple[str, str]]:
    """Run every check, and return each one's name and verdict."""
    verdicts = [
        ("python", sys.version.split()[0]),
        ("pandoc", pandoc()),
        ("data directory", f"{settings.data_dir}: allowed"),
    ]
    if settings.site is None:
        return [*verdicts, ("site", "not set: add it to the settings or pass --site")]
    return [*verdicts, ("tls", public_trust(settings.site)), *session(settings, settings.site)]
