"""The one port to the site: GET only, carrying the saved session's cookies."""

from __future__ import annotations

import json
import ssl
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import httpx
import truststore

from atlassian_offline_mcp.domain.content import SITE_PATH

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Mapping

# Atlassian serves attached files from these hosts, after a redirect from the site.
MEDIA_HOSTS = ("media.atlassian.com", "media-cdn.atlassian.com")
HTTP_OK = 200
HTTP_UNAUTHORISED = 401
RETRIED = frozenset({429, 502, 503, 504})
RETRIES = 4
MAX_REDIRECTS = 5
MAX_WAIT_S = 60.0
TIMEOUT_S = 30.0
MAX_JSON_BYTES = 25 * 1024 * 1024
INTERVAL_S = 0.2


@dataclass(frozen=True)
class Request:
    """A GET on the site: a site-relative path, perhaps with a query, and parameters."""

    path: str
    params: Mapping[str, str] = field(default_factory=dict)


class SignInNeeded(Exception):  # noqa: N818 a state of the session, not a fault
    """The session no longer opens the site: the user must sign in again."""


class SiteError(Exception):
    """A GET that did not succeed; the message holds a status or an error class only."""


def refuse_plain_http(request: httpx.Request) -> None:
    """Refuse a request over plain HTTP, which would carry the session's cookies in clear."""
    if request.url.scheme != "https":
        message = "plain HTTP refused"
        raise httpx.UnsupportedProtocol(message, request=request)


def client(site: str, cookies: Iterable[Mapping[str, str]]) -> httpx.Client:
    """Return an httpx client for the site, carrying cookies, verifying TLS with the OS."""
    jar = httpx.Cookies()
    for cookie in cookies:
        jar.set(cookie["name"], cookie["value"], domain=cookie["domain"], path=cookie["path"])
    return httpx.Client(
        base_url=site,
        cookies=jar,
        follow_redirects=False,
        timeout=TIMEOUT_S,
        verify=truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT),
        event_hooks={"request": [refuse_plain_http]},
    )


class Site:
    """GETs on one site: paced, retried within bounds, stopped when sign-in is needed."""

    def __init__(
        self,
        http: httpx.Client,
        *,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        """Use an httpx client whose base URL is the site."""
        self._http = http
        self._sleep = sleep
        self._clock = clock
        self._last = float("-inf")

    def json(self, request: Request) -> object:
        """GET a JSON response."""
        return json.loads(self.get(request, MAX_JSON_BYTES))

    def file(self, path: str, max_bytes: int) -> bytes:
        """GET an attached file, through its redirect to Atlassian's media hosts."""
        return self.get(Request(path), max_bytes)

    def get(self, request: Request, max_bytes: int) -> bytes:
        """GET a body, retrying throttling, gateway and transport failures four times."""
        failure, wait = "", 0.0
        for attempt in range(RETRIES + 1):
            if attempt:
                self._sleep(min(wait, MAX_WAIT_S))
            try:
                status, headers, body = self.once(request, max_bytes)
            except httpx.TransportError as error:
                failure, wait = type(error).__name__, 2.0**attempt
                continue
            if status == HTTP_OK:
                return body
            failure = f"status {status}"
            if status not in RETRIED:
                break
            after = headers.get("retry-after", "").strip()
            wait = float(after) if after.isdigit() else 2.0**attempt
        raise SiteError(failure)

    def once(self, request: Request, max_bytes: int) -> tuple[int, httpx.Headers, bytes]:
        """Make one GET, following redirects to the site or its media hosts only."""
        if not SITE_PATH.fullmatch(request.path):
            message = "not a site-relative path"
            raise SiteError(message)
        outgoing = self._http.build_request("GET", request.path, params=request.params)
        for _ in range(MAX_REDIRECTS + 1):
            self._sleep(max(0.0, self._last + INTERVAL_S - self._clock()))
            self._last = self._clock()
            response = self._http.send(outgoing, stream=True)
            try:
                if response.status_code == HTTP_UNAUTHORISED:
                    raise SignInNeeded
                if not response.has_redirect_location:
                    body = bytearray()
                    for chunk in response.iter_bytes():
                        body.extend(chunk)
                        if len(body) > max_bytes:
                            message = f"body over {max_bytes} bytes"
                            raise SiteError(message)
                    return response.status_code, response.headers, bytes(body)
                outgoing = response.next_request
            finally:
                response.close()
            host = outgoing.url.host if outgoing is not None else ""
            if host != self._http.base_url.host and not any(
                host == media or host.endswith(f".{media}") for media in MEDIA_HOSTS
            ):
                raise SignInNeeded
        message = "too many redirects"
        raise SiteError(message)
