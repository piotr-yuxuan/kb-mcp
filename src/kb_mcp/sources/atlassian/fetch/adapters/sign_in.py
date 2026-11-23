"""How a run signs in to the site: by the session that ``login`` saved, or by an API token.

Either gives a client for the site, and keeps what a run leaves of it: the site renews
the session's cookies as it answers, so they are written back; nothing of a token is
kept, and a run signed in by one reads and writes nothing of the session.
"""

from __future__ import annotations

import base64
from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Protocol
from urllib.parse import urlsplit

from pydantic import Field

from kb_mcp.config.domain.settings import variable
from kb_mcp.kernel.records import Record
from kb_mcp.sources.atlassian.fetch.adapters import http
from kb_mcp.sources.atlassian.fetch.adapters.http import SignInNeededError
from kb_mcp.sources.atlassian.fetch.adapters.session_file import (
    COOKIES,
    adopt_former_session,
    folder_of,
    for_site,
    kept_why,
    read_cookies,
    write_cookies,
)

if TYPE_CHECKING:
    import httpx

    from kb_mcp.config.domain.settings import Settings


class SignIn(Protocol):
    """A way to sign in to a site: what it is, a client for the site, what a run keeps.

    ``site`` is where it signs in, ``name`` says which it is, and ``again`` what the user
    does once the site refuses it.
    """

    site: str
    name: str
    again: str

    def client(self) -> httpx.Client:
        """Return a client for the site, signed in; raise SignInNeededError if none can be."""

    def keep(self, client: httpx.Client) -> None:
        """Keep what a run has left of the sign-in, for the next run."""

    def adopt_former(self) -> None:
        """Take what a run that writes finds of the sign-in kept before it was a site's."""


class SavedSession(Record):
    """The site's cookies, which ``login`` saved under the site's folder of the session.

    ``source`` is the source that signs in, and ``sites`` the site of every source that
    names one, its own among them, as ``kept_why`` takes them for the session kept before
    sessions were a site's.
    """

    site: str
    folder: Path
    again: str
    source: str
    sites: Mapping[str, str]
    name: str = "the session saved by login"

    def cookies(self) -> Path:
        """Give the file of the site's cookies: its own, or the session kept before.

        Until a run that writes moves it, the session kept before sessions were a site's
        is this site's when ``kept_why`` judges it so and the site has no cookies of its
        own, so that a dry run or ``doctor`` before it needs no login; never another site's.
        """
        own, former = self.folder / COOKIES, self.folder.parent / COOKIES
        if not own.exists() and kept_why(former.parent, self.source, self.sites) is None:
            return former
        return own

    def client(self) -> httpx.Client:
        """Return a client carrying the saved cookies; raise SignInNeededError if none are."""
        try:
            cookies = read_cookies(self.cookies())
        except OSError, ValueError:
            raise SignInNeededError from None
        return http.client(self.site, cookies)

    def keep(self, client: httpx.Client) -> None:
        """Write back the site's cookies that the client holds, renewed ones included.

        Into the file that signed it in, so that a session kept before and not moved yet,
        as when its move failed, stays whole for the next run to move.
        """
        host = urlsplit(self.site).hostname or ""
        write_cookies(self.cookies(), for_site(http.jar(client), host))

    def adopt_former(self) -> None:
        """Move the session kept before sessions were a site's into this site's folder."""
        adopt_former_session(self.folder.parent, self.source, self.sites)


class ApiToken(Record):
    """An account's API token, with its email, as the Authorization header of Basic auth."""

    site: str
    authorisation: str = Field(repr=False)
    again: str
    name: str = "an API token"

    def client(self) -> httpx.Client:
        """Return a client that sends the header to the site's host, and to no other."""
        return http.client(self.site, (), (self.authorise,))

    def authorise(self, request: httpx.Request) -> None:
        """Give a request to the site's host the header; take it from one to another host.

        httpx's own ``auth`` would go with every request that ``send`` makes, such as one
        to a media host after a redirect.
        """
        if request.url.host == urlsplit(self.site).hostname:
            request.headers["Authorization"] = self.authorisation
        else:
            request.headers.pop("Authorization", None)

    def keep(self, client: httpx.Client) -> None:
        """Keep nothing: the environment gives the token to each run."""

    def adopt_former(self) -> None:
        """Take nothing: a token reads and writes nothing of a session."""


def sites_of(settings: Settings) -> dict[str, str]:
    """Give the site of every source whose table holds one, by its name, in name order."""
    return {
        name: str(table.site) for name, table in settings.sources if getattr(table, "site", None)
    }


def choose_sign_in(settings: Settings, source: str) -> SignIn:
    """Sign in by the source's API token when one is set, else by the session that ``login`` saved.

    Either signs in as the account that the source's table, ``[sources.<source>]``, gives,
    to its site. The token goes with the account's email; the commands refuse a token
    without one before they run, and the site would refuse it.
    """
    table = getattr(settings.sources, source)
    token = table.api_token
    if token is None:
        again = f"run kb-mcp login {source}"
        site = str(table.site)
        folder = folder_of(settings.session, site)
        sites = {**sites_of(settings), source: site}
        return SavedSession(site=site, folder=folder, again=again, source=source, sites=sites)
    pair = f"{table.email or ''}:{token.get_secret_value()}"
    return ApiToken(
        site=str(table.site),
        authorisation=f"Basic {base64.b64encode(pair.encode()).decode()}",
        again=(
            f"check {variable(('sources', source, 'email'))}"
            f" and {variable(('sources', source, 'api_token'))}"
        ),
    )
