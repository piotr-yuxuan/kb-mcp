"""The port to the site: GET only, paced, retried within bounds, stopped at sign-in."""

from __future__ import annotations

import json

import httpx
import pytest

from atlassian_offline_mcp.adapters.http import (
    INTERVAL_S,
    MAX_FAILED_IN_A_ROW,
    RETRIES,
    Request,
    SignInNeededError,
    Site,
    SiteError,
    TooManyFailuresError,
    refuse_plain_http,
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
    "path",
    [
        "https://elsewhere.example/x",
        "//elsewhere.example/x",
        "wiki/x",
        "/\\elsewhere",
        "/wiki/api/v2/spaces?cursor=\x01",
    ],
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


def test_a_path_keeps_its_own_query_beside_the_parameters() -> None:
    """A next link carries its cursor in its query, which parameters must not replace."""
    reader, asked = site(httpx.Response(200, json={}), httpx.Response(200, json={}))
    reader.json(Request("/wiki/api/v2/spaces/1/pages?limit=250&cursor=c2"))
    reader.json(Request("/wiki/rest/api/user/bulk?limit=50", {"accountId": ["a", "b"]}))
    assert asked == [
        f"{SITE}/wiki/api/v2/spaces/1/pages?limit=250&cursor=c2",
        f"{SITE}/wiki/rest/api/user/bulk?limit=50&accountId=a&accountId=b",
    ]


def test_an_answer_that_is_not_json_fails_that_get() -> None:
    """A proxy's or a maintenance page's HTML, served with 200, is a failure of one GET."""
    reader, _ = site(httpx.Response(200, content=b"<html>Maintenance</html>"))
    with pytest.raises(SiteError, match=r"^not JSON$"):
        reader.json(Request("/wiki/api/v2/spaces"))


def test_a_body_that_does_not_decode_fails_without_retrying() -> None:
    """A body that its Content-Encoding cannot decode is not worth asking for again."""
    broken = httpx.Response(
        200, stream=httpx.ByteStream(b"not gzip"), headers={"content-encoding": "gzip"}
    )
    reader, asked = site(broken)
    with pytest.raises(SiteError, match=r"^DecodingError$"):
        reader.json(Request("/wiki/api/v2/spaces"))
    assert len(asked) == 1


def test_a_retry_after_that_is_not_ascii_digits_falls_back_to_backing_off() -> None:
    """A superscript digit is a digit to str.isdigit, but not a number of seconds."""
    clock = Clock()
    reader, _ = site(
        httpx.Response(429, headers=[(b"retry-after", "\u00b2".encode("latin-1"))]),
        httpx.Response(200, json={}),
        clock=clock,
    )
    assert reader.json(Request("/a")) == {}
    assert 1.0 in clock.sleeps


def test_gets_unanswered_one_after_another_stop_the_run() -> None:
    """After so many GETs without an answer, the site or the network is wrong.

    The GET after the last allowed one is refused before it is sent.
    """
    answers = [httpx.Response(503)] * ((RETRIES + 1) * MAX_FAILED_IN_A_ROW)
    reader, asked = site(*answers)
    for _ in range(MAX_FAILED_IN_A_ROW):
        with pytest.raises(SiteError, match=r"^status 503$"):
            reader.json(Request("/a"))
    with pytest.raises(TooManyFailuresError):
        reader.json(Request("/a"))
    assert len(asked) == len(answers)


def test_an_answer_starts_the_count_of_unanswered_gets_again() -> None:
    """Unanswered GETs spread among answered ones never stop a run."""
    unanswered = [httpx.Response(503)] * ((RETRIES + 1) * (MAX_FAILED_IN_A_ROW - 1))
    reader, _ = site(*unanswered, httpx.Response(404), *unanswered, httpx.Response(200, json={}))
    for _ in range(MAX_FAILED_IN_A_ROW - 1):
        with pytest.raises(SiteError):
            reader.json(Request("/a"))
    with pytest.raises(SiteError, match=r"^status 404$"):
        reader.json(Request("/a"))
    for _ in range(MAX_FAILED_IN_A_ROW - 1):
        with pytest.raises(SiteError):
            reader.json(Request("/a"))
    assert reader.json(Request("/a")) == {}


def test_refusals_of_one_item_never_stop_the_run() -> None:
    """A 404 is an answer: any number of them in a row leave the site usable."""
    refusals = [httpx.Response(404)] * (MAX_FAILED_IN_A_ROW * 2)
    reader, _ = site(*refusals, httpx.Response(200, json={}))
    for _ in refusals:
        with pytest.raises(SiteError, match=r"^status 404$"):
            reader.json(Request("/a"))
    assert reader.json(Request("/a")) == {}


def test_a_path_too_long_for_a_url_fails_that_get() -> None:
    """A next link that httpx cannot make a URL of fails its one GET, unsent."""
    reader, asked = site()
    with pytest.raises(SiteError, match=r"^InvalidURL$"):
        reader.json(Request("/" + "a" * 70_000))
    assert asked == []


def test_a_request_over_plain_http_is_refused_before_it_is_sent() -> None:
    """The session's cookies never travel in clear, and the refusal is not retried."""
    sent: list[httpx.Request] = []
    http_client = httpx.Client(
        base_url="http://sandbox.example.invalid",
        transport=httpx.MockTransport(lambda request: sent.append(request) or httpx.Response(200)),
        event_hooks={"request": [refuse_plain_http]},
    )
    with pytest.raises(SiteError, match="plain HTTP refused"):
        Site(http_client, sleep=lambda _: None).json(Request("/a"))
    assert sent == []
