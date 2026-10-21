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

    from atlassian_offline_mcp.adapters.fields import Fields

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
# GETs failing one after another, after which a run stops.
MAX_FAILED_IN_A_ROW = 10


@dataclass(frozen=True)
class Request:
    """A GET on the site: a site-relative path, perhaps with a query, and parameters.

    A parameter with a list of values is repeated, once per value.
    """

    path: str
    params: Mapping[str, str | list[str]] = field(default_factory=dict)


# How a representation reads one page of a paged listing: its entries, and the request
# for the next page, or None on the last.
type ReadPage = Callable[[Fields, Request], tuple[list[Fields], Request | None]]


class TooManyFailuresError(Exception):
    """GETs failed one after another: the site, the network or the session is wrong."""


class SignInNeededError(Exception):
    """The session no longer opens the site: the user must sign in again."""


class SiteError(Exception):
    """A GET that did not succeed; the message holds a status or an error class only."""


def refuse_plain_http(request: httpx.Request) -> None:
    """Refuse a request over plain HTTP, which would carry the session's cookies in clear."""
    if request.url.scheme != "https":
        message = "plain HTTP refused"
        raise SiteError(message)


@dataclass
class Breaker:
    """Stop a run once GETs fail one after another, rather than fail each item slowly."""

    limit: int
    failed: int = 0

    def failure(self) -> None:
        """Count a failed GET; raise TooManyFailuresError at the limit."""
        self.failed += 1
        if self.failed >= self.limit:
            raise TooManyFailuresError

    def success(self) -> None:
        """Start counting again."""
        self.failed = 0


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


def jar(http: httpx.Client) -> list[dict[str, object]]:
    """Return the client's cookies as the session file keeps them, rolled ones included."""
    return [
        {"name": cookie.name, "value": cookie.value, "domain": cookie.domain, "path": cookie.path}
        for cookie in http.cookies.jar
    ]


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
        self._breaker = Breaker(MAX_FAILED_IN_A_ROW)

    def json(self, request: Request) -> object:
        """GET a JSON response; a body that is not JSON (a proxy's page, say) fails it."""
        body = self.get(request, MAX_JSON_BYTES)
        try:
            return json.loads(body)
        except ValueError:
            message = "not JSON"
            raise SiteError(message) from None

    def file(self, path: str, max_bytes: int) -> bytes:
        """GET an attached file, through its redirect to Atlassian's media hosts.

        A refusal on the way (a 401 from the media host, a redirect to a host that is not
        known) fails this file alone: the session was checked when the run began.
        """
        try:
            return self.get(Request(path), max_bytes)
        except SignInNeededError:
            message = "refused, or sent to an unknown host"
            raise SiteError(message) from None

    def get(self, request: Request, max_bytes: int) -> bytes:
        """GET a body, retrying throttling, gateway and transport failures four times.

        Raises SiteError for this GET, and TooManyFailuresError once ``MAX_FAILED_IN_A_ROW``
        GETs have failed one after another.
        """
        failure, wait = "", 0.0
        for attempt in range(RETRIES + 1):
            if attempt:
                self._sleep(min(wait, MAX_WAIT_S))
            try:
                status, headers, body = self.once(request, max_bytes)
            except httpx.TransportError as error:
                failure, wait = type(error).__name__, 2.0**attempt
                continue
            except (httpx.DecodingError, httpx.InvalidURL) as error:
                failure = type(error).__name__
                break
            if status == HTTP_OK:
                self._breaker.success()
                return body
            failure = f"status {status}"
            if status not in RETRIED:
                break
            after = headers.get("retry-after", "").strip()
            wait = float(after) if after.isascii() and after.isdigit() else 2.0**attempt
        self._breaker.failure()
        raise SiteError(failure)

    def once(self, request: Request, max_bytes: int) -> tuple[int, httpx.Headers, bytes]:
        """Make one GET, following redirects to the site or its media hosts only."""
        if not SITE_PATH.fullmatch(request.path):
            message = "not a site-relative path"
            raise SiteError(message)
        # httpx would drop the path's own query (a next link's cursor) given parameters.
        url = httpx.URL(request.path)
        if request.params:
            url = url.copy_merge_params(request.params)
        outgoing = self._http.build_request("GET", url)
        for _ in range(MAX_REDIRECTS + 1):
            self._sleep(max(0.0, self._last + INTERVAL_S - self._clock()))
            self._last = self._clock()
            response = self._http.send(outgoing, stream=True)
            try:
                if response.status_code == HTTP_UNAUTHORISED:
                    raise SignInNeededError
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
                raise SignInNeededError
        message = "too many redirects"
        raise SiteError(message)
