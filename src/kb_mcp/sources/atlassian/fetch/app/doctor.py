"""Checks of the site and the sign-in that a download needs, each with a verdict."""

from __future__ import annotations

from typing import TYPE_CHECKING

from kb_mcp.kernel.fields import Fields, RepresentationError
from kb_mcp.sources.atlassian.fetch.adapters import confluence_v2, http, jira_v3
from kb_mcp.sources.atlassian.fetch.adapters.http import SignInNeededError, SiteClient, SiteError
from kb_mcp.sources.atlassian.fetch.adapters.sign_in import choose_sign_in
from kb_mcp.sources.atlassian.fetch.domain.names import CONFLUENCE, JIRA
from kb_mcp.sources.stages import FAILED, SIGN_IN, Verdict

if TYPE_CHECKING:
    from kb_mcp.config.domain.settings import Settings


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
    signing = choose_sign_in(settings)
    try:
        client = signing.client()
    except SignInNeededError:
        return [Verdict(name="sign-in", found=f"no session saved: {signing.again}", state=SIGN_IN)]
    verdicts = [Verdict(name="sign-in", found=signing.name)]
    with client:
        reader = SiteClient(client)
        for name, request, signed_in in (
            (CONFLUENCE, confluence_v2.current_user_request(), confluence_v2.is_signed_in),
            (JIRA, jira_v3.myself_request(), jira_v3.is_signed_in),
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


def checks(settings: Settings) -> list[Verdict]:
    """Say whether a site is set, whether it answers, and whether the sign-in still opens it."""
    site = settings.accounts.atlassian.site
    if site is None:
        return [
            Verdict(
                name="site",
                found="not set: add accounts.atlassian.site to the settings or pass --site",
                state=FAILED,
            ),
        ]
    return [public_trust(site), *access(settings)]
