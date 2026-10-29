"""Checks of the machine and the sign-in that a download needs, each with a verdict."""

from __future__ import annotations

import shutil
import sys
from dataclasses import dataclass
from typing import TYPE_CHECKING

from kb_mcp.kernel.fields import Fields, RepresentationError
from kb_mcp.sources.atlassian.adapters import confluence_v2, http, jira_v3
from kb_mcp.sources.atlassian.adapters.http import SignInNeededError, Site, SiteError
from kb_mcp.sources.atlassian.adapters.sign_in import sign_in

if TYPE_CHECKING:
    from kb_mcp.config.domain.settings import Settings

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
    return (
        Verdict(name="pandoc", found=found)
        if found
        else Verdict(name="pandoc", found="not found on PATH", state=FAILED)
    )


def public_trust(site: str) -> Verdict:
    """Say whether the public CAs verify the site; if not, TLS is inspected on the way."""
    verified = http.verified_by_public_cas(site + confluence_v2.current_user_request().path)
    if verified is None:
        return Verdict(name="tls", found="no answer from the site", state=FAILED)
    if verified:
        return Verdict(name="tls", found="verified by public CAs")
    return Verdict(
        name="tls", found="not verified by public CAs: TLS is inspected; the OS trust store is used"
    )


def access(settings: Settings) -> list[Verdict]:
    """Say how the run signs in, and whether that still opens Confluence and Jira.

    By the API token when one is set, else by the session that ``login`` saved.
    """
    signing = sign_in(settings)
    try:
        client = signing.client()
    except SignInNeededError:
        return [Verdict(name="sign-in", found=f"no session saved: {signing.again}", state=SIGN_IN)]
    verdicts = [Verdict(name="sign-in", found=signing.name)]
    with client:
        reader = Site(client)
        for name, request, signed_in in (
            ("confluence", confluence_v2.current_user_request(), confluence_v2.signed_in),
            ("jira", jira_v3.myself_request(), jira_v3.signed_in),
        ):
            try:
                user = Fields(reader.json(request), "user")
                verdict = (
                    Verdict(name=name, found="signed in")
                    if signed_in(user)
                    else Verdict(name=name, found=f"anonymous: {signing.again}", state=SIGN_IN)
                )
            except SignInNeededError:
                verdict = Verdict(name=name, found=f"refused: {signing.again}", state=SIGN_IN)
            except (RepresentationError, SiteError) as error:
                verdict = Verdict(name=name, found=f"no answer ({error})", state=FAILED)
            verdicts.append(verdict)
    return verdicts


def doctor(settings: Settings) -> list[Verdict]:
    """Run every check, and return each one's verdict."""
    verdicts = [
        Verdict(name="python", found=sys.version.split()[0]),
        pandoc(),
        Verdict(name="data directory", found=f"{settings.data_dir}: allowed"),
    ]
    if settings.site is None:
        return [
            *verdicts,
            Verdict(
                name="site", found="not set: add it to the settings or pass --site", state=FAILED
            ),
        ]
    return [*verdicts, public_trust(settings.site), *access(settings)]
