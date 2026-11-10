"""Checks of each site and of the sign-in that a fetch needs, each with what it found."""

from __future__ import annotations

from typing import TYPE_CHECKING
from urllib.parse import urlsplit

from kb_mcp.kernel.fields import Fields, RepresentationError
from kb_mcp.sources.atlassian.fetch.adapters import confluence_v2, http, jira_v3
from kb_mcp.sources.atlassian.fetch.adapters.http import SignInNeededError, SiteClient, SiteError
from kb_mcp.sources.atlassian.fetch.adapters.sign_in import choose_sign_in
from kb_mcp.sources.atlassian.fetch.domain.names import CONFLUENCE, JIRA
from kb_mcp.sources.stages import Check

if TYPE_CHECKING:
    from collections.abc import Sequence

    from kb_mcp.config.domain.settings import Settings
    from kb_mcp.sources.declaration import Source

# What says whether a source of each connector is signed in: its request, and its rule.
SIGNED_IN = {
    CONFLUENCE: (confluence_v2.current_user_request, confluence_v2.is_signed_in),
    JIRA: (jira_v3.myself_request, jira_v3.is_signed_in),
}


def public_trust(site: str) -> Check:
    """Say whether the public CAs verify the site; if not, TLS is inspected on the way."""
    name = f"tls {urlsplit(site).hostname}"
    verified = http.verified_by_public_cas(site + confluence_v2.current_user_request().path)
    if verified is None:
        return Check(name=name, found="no answer from the site", state="failed")
    if verified:
        return Check(name=name, found="verified by public CAs")
    return Check(
        name=name, found="not verified by public CAs: TLS is inspected; the OS trust store is used"
    )


def access(settings: Settings, sources: Sequence[Source]) -> list[Check]:
    """Say how the first of these sources of one site signs in, and whether that opens each.

    By its API token when one is set, else by the session that ``login`` saved. Each
    source's check is named after it.
    """
    signing = choose_sign_in(settings, sources[0].name)
    name = f"sign-in {urlsplit(signing.site).hostname}"
    try:
        client = signing.client()
    except SignInNeededError:
        return [Check(name=name, found=f"no session saved: {signing.again}", state="sign in again")]
    done = [Check(name=name, found=signing.name)]
    with client:
        reader = SiteClient(client)
        for source in sources:
            request, signed_in = SIGNED_IN[source.connector.name]
            try:
                user = Fields(reader.json(request()), "user")
                check = (
                    Check(name=source.name, found="signed in")
                    if signed_in(user)
                    else Check(
                        name=source.name, found=f"anonymous: {signing.again}", state="sign in again"
                    )
                )
            except SignInNeededError:
                found = f"refused: {signing.again}"
                check = Check(name=source.name, found=found, state="sign in again")
            except (RepresentationError, SiteError) as error:
                check = Check(name=source.name, found=f"no answer ({error})", state="failed")
            done.append(check)
    return done


def checks(settings: Settings, sources: Sequence[Source]) -> list[Check]:
    """Say, once a site, whether it answers, and whether a sign-in still opens each source.

    The sources are configured, and each has a site, as ``doctor``'s light checks refuse
    one without.
    """
    by_site: dict[str, list[Source]] = {}
    for each in sources:
        by_site.setdefault(str(getattr(settings.sources, each.name).site), []).append(each)
    return [
        check
        for site, on_site in by_site.items()
        for check in (public_trust(site), *access(settings, on_site))
    ]
