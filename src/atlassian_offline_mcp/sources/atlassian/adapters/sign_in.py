"""How a run signs in to the site: by the session that ``login`` saved, or by an API token.

Either gives a client for the site, and keeps what a run leaves of it: the site renews
the session's cookies as it answers, so they are written back; nothing of a token is
kept, and a run signed in by one reads and writes nothing of the session.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol
from urllib.parse import urlsplit

from atlassian_offline_mcp.config.domain.settings import PREFIX
from atlassian_offline_mcp.sources.atlassian.adapters import http
from atlassian_offline_mcp.sources.atlassian.adapters.http import SignInNeededError
from atlassian_offline_mcp.sources.atlassian.adapters.session_file import (
    COOKIES,
    for_site,
    read_cookies,
    write_cookies,
)

if TYPE_CHECKING:
    from pathlib import Path

    import httpx

    from atlassian_offline_mcp.config.domain.settings import Settings


class SignIn(Protocol):
    """A way to sign in to the site: what it is, a client for the site, what a run keeps.

    ``name`` says which it is, and ``again`` what the user does once the site refuses it.
    """

    name: str
    again: str

    def client(self) -> httpx.Client:
        """Return a client for the site, signed in; raise SignInNeededError if none can be."""

    def keep(self, client: httpx.Client) -> None:
        """Keep what a run has left of the sign-in, for the next run."""


@dataclass(frozen=True)
class SavedSession:
    """The site's cookies, which ``login`` saved under the session's folder."""

    site: str
    folder: Path
    name: str = "the session saved by login"
    again: str = "run atlassian-offline-mcp login"

    def client(self) -> httpx.Client:
        """Return a client carrying the saved cookies; raise SignInNeededError if none are."""
        try:
            cookies = read_cookies(self.folder / COOKIES)
        except OSError, ValueError:
            raise SignInNeededError from None
        return http.client(self.site, cookies)

    def keep(self, client: httpx.Client) -> None:
        """Write back the site's cookies that the client holds, renewed ones included."""
        host = urlsplit(self.site).hostname or ""
        write_cookies(self.folder / COOKIES, for_site(http.jar(client), host))


@dataclass(frozen=True)
class ApiToken:
    """An account's API token, with its email, as the Authorization header of Basic auth."""

    site: str
    authorisation: str = field(repr=False)
    name: str = "an API token"
    again: str = f"check {PREFIX}EMAIL and {PREFIX}API_TOKEN"

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


def sign_in(settings: Settings) -> SignIn:
    """Sign in by the API token when one is set, else by the session that ``login`` saved.

    The token goes with its account's email; the commands refuse a token without one
    before they run, and the site would refuse it.
    """
    token = settings.api_token
    if token is None:
        return SavedSession(str(settings.site), settings.session)
    pair = f"{settings.email or ''}:{token.get_secret_value()}"
    return ApiToken(str(settings.site), f"Basic {base64.b64encode(pair.encode()).decode()}")
