"""The one port to the site: GET only, signed in by the saved session's cookies or a token."""

from __future__ import annotations

import json
import ssl
import time
from collections.abc import Mapping
from typing import TYPE_CHECKING

import certifi
import httpx
import structlog
import truststore
from pydantic import ConfigDict, Field

from kb_mcp.kernel.record import Record
from kb_mcp.observability.adapters.http import ObservedTransport
from kb_mcp.sources.atlassian.fetch.domain.content import SITE_PATH

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

    from kb_mcp.kernel.fields import Fields

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
# GETs in a row that got no answer, after which a run stops.
MAX_FAILED_IN_A_ROW = 10
# How many causes to follow to find a certificate error within a connection error.
CAUSE_DEPTH = 10


class Request(Record):
    """A GET on the site: a site-relative path, perhaps with a query, and parameters.

    A parameter with a list of values is repeated, once per value.
    """

    path: str
    params: Mapping[str, str | list[str]] = Field(default_factory=dict)


# How a representation reads one page of a paged listing: its entries, and the request
# for the next page, or None on the last.
type ReadPage = Callable[[Fields, Request], tuple[list[Fields], Request | None]]


class TooManyFailuresError(Exception):
    """GETs failed one after another: the site, the network or the session is wrong."""


class SignInNeededError(Exception):
    """The sign-in does not open the site, or there is none: the user must sign in again."""


class SiteError(Exception):
    """A GET that did not succeed; the message holds a status or an error class only.

    ``status`` is the HTTP status of the last answer, when the site answered.
    """

    def __init__(self, message: str, status: int | None = None) -> None:
        """Hold the message, and the status when there was one."""
        super().__init__(message)
        self.status = status


def refuse_plain_http(request: httpx.Request) -> None:
    """Refuse a request over plain HTTP, which would carry the sign-in in clear."""
    if request.url.scheme != "https":
        message = "plain HTTP refused"
        raise SiteError(message)


class Breaker(Record):
    """Stop a run once the site or the network stops answering, GET after GET.

    Only a GET that got no answer counts: a transport error, or a throttling or gateway
    status, once its retries are spent. Any other answer, even a refusal of one item,
    shows the site is there, and starts the count again.
    """

    model_config = ConfigDict(frozen=False)

    limit: int
    failed: int = 0

    def check(self) -> None:
        """Raise TooManyFailuresError when the last ``limit`` GETs got no answer."""
        if self.failed >= self.limit:
            raise TooManyFailuresError

    def unanswered(self) -> None:
        """Count a GET that got no answer."""
        self.failed += 1

    def answered(self) -> None:
        """Start counting again."""
        self.failed = 0


def client(
    site: str,
    cookies: Iterable[Mapping[str, str]],
    hooks: Iterable[Callable[[httpx.Request], None]] = (),
    transport: httpx.BaseTransport | None = None,
) -> httpx.Client:
    """Return an httpx client for the site, carrying cookies, verifying TLS with the OS.

    Each of ``hooks`` sees every request before it is sent, once plain HTTP is refused.
    Each request sent is observed, as ``ObservedTransport`` has it, with its query on the site's
    host alone. ``transport`` replaces the network, for tests.
    """
    cookie_jar = httpx.Cookies()
    for cookie in cookies:
        cookie_jar.set(
            cookie["name"], cookie["value"], domain=cookie["domain"], path=cookie["path"]
        )
    network = httpx.Client(
        verify=truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT), transport=transport
    )
    return httpx.Client(
        base_url=site,
        cookies=cookie_jar,
        follow_redirects=False,
        timeout=TIMEOUT_S,
        event_hooks={"request": [refuse_plain_http, *hooks]},
        transport=ObservedTransport(network, httpx.URL(site).host),
    )


def jar(http: httpx.Client) -> list[dict[str, object]]:
    """Return the client's cookies as the session file keeps them, rolled ones included."""
    return [
        {"name": cookie.name, "value": cookie.value, "domain": cookie.domain, "path": cookie.path}
        for cookie in http.cookies.jar
    ]


class SiteClient:
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
        self._breaker = Breaker(limit=MAX_FAILED_IN_A_ROW)

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
            return self.get(Request(path=path), max_bytes)
        except SignInNeededError:
            message = "refused, or sent to an unknown host"
            raise SiteError(message) from None

    def get(self, request: Request, max_bytes: int) -> bytes:
        """GET a body, retrying throttling, gateway and transport failures four times.

        Raises SiteError for this GET, and TooManyFailuresError, before trying, once
        ``MAX_FAILED_IN_A_ROW`` GETs in a row got no answer. Each retry is said at DEBUG,
        ``http.retry``, by the path, without its query, and why.
        """
        self._breaker.check()
        failure, wait, answered, last = "", 0.0, True, None
        for attempt in range(RETRIES + 1):
            if attempt:
                structlog.get_logger().debug(
                    "http.retry",
                    path=request.path.partition("?")[0],
                    attempt=attempt,
                    failure=failure,
                    wait_s=min(wait, MAX_WAIT_S),
                )
                self._sleep(min(wait, MAX_WAIT_S))
            try:
                status, headers, body = self.once(request, max_bytes)
            except httpx.TransportError as error:
                failure, wait, answered = type(error).__name__, 2.0**attempt, False
                continue
            except (httpx.DecodingError, httpx.InvalidURL) as error:
                failure, answered = type(error).__name__, True
                break
            answered = status not in RETRIED
            if status == HTTP_OK:
                self._breaker.answered()
                return body
            failure, last = f"status {status}", status
            if answered:
                break
            after = headers.get("retry-after", "").strip()
            wait = float(after) if after.isascii() and after.isdigit() else 2.0**attempt
        if answered:
            self._breaker.answered()
        else:
            self._breaker.unanswered()
        raise SiteError(failure, last)

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


def verified_by_public_cas(url: str) -> bool | None:
    """Say whether the public CA bundle verifies the site, or None when nothing answers.

    False means TLS is inspected on the way, which the OS trust store, used by every run,
    already allows for.
    """
    context = ssl.create_default_context(cafile=certifi.where())
    transport = ObservedTransport(httpx.Client(verify=context), httpx.URL(url).host)
    with httpx.Client(timeout=TIMEOUT_S, transport=transport) as client:
        try:
            client.get(url)
        except httpx.HTTPError as error:
            cause: BaseException | None = error
            for _ in range(CAUSE_DEPTH):
                if cause is None or isinstance(cause, ssl.SSLCertVerificationError):
                    break
                cause = cause.__cause__ or cause.__context__
            return False if isinstance(cause, ssl.SSLCertVerificationError) else None
    return True
