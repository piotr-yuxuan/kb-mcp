"""Checks of the machine and the session that a download needs, each with a verdict."""

from __future__ import annotations

import shutil
import sys
from dataclasses import dataclass
from typing import TYPE_CHECKING

from atlassian_offline_mcp.adapters import confluence_v2, http, jira_v3
from atlassian_offline_mcp.adapters.fields import Fields, RepresentationError
from atlassian_offline_mcp.adapters.http import SignInNeededError, Site, SiteError
from atlassian_offline_mcp.adapters.session_file import COOKIES, read_cookies

if TYPE_CHECKING:
    from atlassian_offline_mcp.domain.settings import Settings

# What a check concludes: all is well, the user must sign in again, or something fails.
WELL, SIGN_IN, FAILED = "well", "sign in", "failed"


@dataclass(frozen=True)
class Verdict:
    """One check: what it looked at, what it found, and what that means."""

    name: str
    found: str
    state: str = WELL


def pandoc() -> Verdict:
    """Say where the pandoc that the mirror needs is on PATH, or that there is none."""
    found = shutil.which("pandoc")
    return Verdict("pandoc", found) if found else Verdict("pandoc", "not found on PATH", FAILED)


def public_trust(site: str) -> Verdict:
    """Say whether the public CAs verify the site; if not, TLS is inspected on the way."""
    verified = http.verified_by_public_cas(site + confluence_v2.current_user_request().path)
    if verified is None:
        return Verdict("tls", "no answer from the site", FAILED)
    if verified:
        return Verdict("tls", "verified by public CAs")
    return Verdict(
        "tls", "not verified by public CAs: TLS is inspected; the OS trust store is used"
    )


def session(settings: Settings, site: str) -> list[Verdict]:
    """Say whether the saved session still signs in to Confluence and to Jira."""
    try:
        cookies = read_cookies(settings.session / COOKIES)
    except OSError, ValueError:
        return [Verdict("session", "none saved: run atlassian-offline-mcp login", SIGN_IN)]
    verdicts = [Verdict("session", f"{len(cookies)} cookies saved")]
    with http.client(site, cookies) as client:
        reader = Site(client)
        for name, request, signed_in in (
            ("confluence", confluence_v2.current_user_request(), confluence_v2.signed_in),
            ("jira", jira_v3.myself_request(), jira_v3.signed_in),
        ):
            try:
                user = Fields(reader.json(request), "user")
                verdict = (
                    Verdict(name, "signed in")
                    if signed_in(user)
                    else Verdict(name, "anonymous: sign in again", SIGN_IN)
                )
            except SignInNeededError:
                verdict = Verdict(name, "refused: sign in again", SIGN_IN)
            except (RepresentationError, SiteError) as error:
                verdict = Verdict(name, f"no answer ({error})", FAILED)
            verdicts.append(verdict)
    return verdicts


def doctor(settings: Settings) -> list[Verdict]:
    """Run every check, and return each one's verdict."""
    verdicts = [
        Verdict("python", sys.version.split()[0]),
        pandoc(),
        Verdict("data directory", f"{settings.data_dir}: allowed"),
    ]
    if settings.site is None:
        return [
            *verdicts,
            Verdict("site", "not set: add it to the settings or pass --site", FAILED),
        ]
    return [*verdicts, public_trust(settings.site), *session(settings, settings.site)]
