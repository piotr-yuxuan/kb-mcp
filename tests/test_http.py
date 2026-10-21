"""The port to the site: GET only, paced, retried within bounds, stopped at sign-in."""

from __future__ import annotations

import json

import httpx
import pytest

from atlassian_offline_mcp.adapters.http import (
    INTERVAL_S,
    RETRIES,
    Request,
    SignInNeededError,
    Site,
    SiteError,
)

SITE = "https://sandbox.example.invalid"
RETRY_AFTER_S = 2.0


class Clock:
    """A clock that sleeping moves on, and that records each sleep."""

    def __init__(self) -> None:
        """Start at zero, having slept never."""
        self.now = 0.0
        self.sleeps: list[float] = []

    def sleep(self, seconds: float) -> None:
        """Move on by ``seconds``, and record any sleep that waits."""
        if seconds > 0:
            self.sleeps.append(seconds)
        self.now += seconds

    def time(self) -> float:
        """Return the time now."""
        return self.now


def site(*responses: httpx.Response, clock: Clock | None = None) -> tuple[Site, list[str]]:
    """Return a site that answers with ``responses`` in turn, and the URLs it was asked."""
    asked: list[str] = []
    answers = iter(responses)

    def handle(request: httpx.Request) -> httpx.Response:
        asked.append(str(request.url))
        return next(answers)

    clock = clock or Clock()
    http = httpx.Client(base_url=SITE, transport=httpx.MockTransport(handle))
    return Site(http, sleep=clock.sleep, clock=clock.time), asked


def test_a_json_response_is_read_with_its_parameters() -> None:
    """A GET carries its parameters, and its JSON is decoded."""
    reader, asked = site(httpx.Response(200, json={"results": []}))
    assert reader.json(Request("/wiki/api/v2/spaces", {"keys": "MFS"})) == {"results": []}
    assert asked == [f"{SITE}/wiki/api/v2/spaces?keys=MFS"]


def test_a_401_means_sign_in_is_needed() -> None:
    """An expired session stops the run rather than failing one document."""
    reader, _ = site(httpx.Response(401))
    with pytest.raises(SignInNeededError):
        reader.json(Request("/rest/api/3/myself"))


def test_a_redirect_to_the_identity_provider_means_sign_in_is_needed() -> None:
    """A sign-in page is never followed, nor read as content."""
    reader, asked = site(
        httpx.Response(302, headers={"location": "https://id.atlassian.com/login?continue=x"})
    )
    with pytest.raises(SignInNeededError):
        reader.json(Request("/wiki/api/v2/spaces"))
    assert len(asked) == 1


def test_a_redirect_to_the_media_host_is_followed() -> None:
    """Attached files come from Atlassian's media host, after a redirect."""
    media = "https://api.media.atlassian.com/file/abc/binary?token=t"
    reader, asked = site(
        httpx.Response(302, headers={"location": media}), httpx.Response(200, content=b"PNG")
    )
    assert reader.file("/wiki/rest/api/content/1/child/attachment/att1/download", 10) == b"PNG"
    assert asked[1] == media


def test_a_redirect_within_the_site_is_followed() -> None:
    """The site may move a path within itself."""
    reader, _ = site(
        httpx.Response(301, headers={"location": "/wiki/api/v2/spaces?limit=1"}),
        httpx.Response(200, json={}),
    )
    assert reader.json(Request("/wiki/api/v2/spaces")) == {}


def test_throttling_waits_as_the_site_asks_then_retries() -> None:
    """A 429 with Retry-After waits that long, then the GET is made again."""
    clock = Clock()
    reader, asked = site(
        httpx.Response(429, headers={"retry-after": "2"}),
        httpx.Response(200, json={"ok": True}),
        clock=clock,
    )
    assert reader.json(Request("/rest/api/3/search/jql")) == {"ok": True}
    url = f"{SITE}/rest/api/3/search/jql"
    assert asked == [url, url]
    assert RETRY_AFTER_S in clock.sleeps


def test_a_failure_that_persists_fails_after_the_last_retry() -> None:
    """Five 503s in a row fail, having waited 1, 2, 4 and 8 s between them."""
    clock = Clock()
    reader, asked = site(*[httpx.Response(503)] * (RETRIES + 1), clock=clock)
    with pytest.raises(SiteError, match=r"^status 503$"):
        reader.json(Request("/wiki/api/v2/spaces"))
    assert len(asked) == RETRIES + 1
    assert [wait for wait in clock.sleeps if wait > INTERVAL_S] == [1.0, 2.0, 4.0, 8.0]


def test_a_missing_page_fails_at_once() -> None:
    """A 404 is not retried: it is a failure of that one item."""
    reader, asked = site(httpx.Response(404))
    with pytest.raises(SiteError, match=r"^status 404$"):
        reader.json(Request("/wiki/api/v2/pages/1"))
    assert len(asked) == 1


def test_a_lost_connection_is_retried_then_named_by_its_class() -> None:
    """A transport error is retried within the bound; its message is never reported."""
    clock = Clock()
    calls = 0

    def handle(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        message = "connection to secret.example refused"
        raise httpx.ConnectError(message, request=request)

    http = httpx.Client(base_url=SITE, transport=httpx.MockTransport(handle))
    reader = Site(http, sleep=clock.sleep, clock=clock.time)
    with pytest.raises(SiteError, match=r"^ConnectError$"):
        reader.json(Request("/wiki/api/v2/spaces"))
    assert calls == RETRIES + 1


@pytest.mark.parametrize(
    "path", ["https://elsewhere.example/x", "//elsewhere.example/x", "wiki/x", "/\\elsewhere"]
)
def test_a_path_off_the_site_is_refused_before_any_request(path: str) -> None:
    """Only site-relative paths are ever asked for, whatever a response's link says."""
    reader, asked = site()
    with pytest.raises(SiteError, match="not a site-relative path"):
        reader.json(Request(path))
    assert asked == []


def test_a_body_over_its_bound_fails() -> None:
    """A file larger than the cap is not read whole."""
    reader, _ = site(httpx.Response(200, content=b"x" * 11))
    with pytest.raises(SiteError, match="body over 10 bytes"):
        reader.file("/wiki/download/file", 10)


def test_requests_are_paced() -> None:
    """Two GETs in a row are at least the interval apart."""
    clock = Clock()
    reader, _ = site(
        httpx.Response(200, content=json.dumps({}).encode()),
        httpx.Response(200, content=json.dumps({}).encode()),
        clock=clock,
    )
    reader.json(Request("/a"))
    reader.json(Request("/b"))
    assert clock.sleeps == [INTERVAL_S]
