"""Redaction: what a key naming a secret holds never reaches a log, at any depth."""

from __future__ import annotations

import base64
import io
import json
from itertools import pairwise, product

import pytest
import structlog

from kb_mcp.observability.domain.redaction import redact_secrets, redacted

SENTINEL = "sentinel-token-5b1e"
COOKIE = "sentinel-cookie-9c4d"
# What a sign-in with an API token sends: the email and token in base64.
BASIC = base64.b64encode(f"tests@example.invalid:{SENTINEL}".encode()).decode()


@pytest.mark.parametrize(
    "key",
    [
        "Authorization",
        "authorization",
        "Cookie",
        "Set-Cookie",
        "x-api-key",
        "X-API-Key",
        "api_key",
        "API.KEY",
        "token",
        "access_token",
        "cloud.session.token",
        "_token",
        "password",
        "db-password",
        "client_secret",
        "Secret",
    ],
)
def test_a_key_naming_a_secret_reads_redacted(key: str) -> None:
    """Its words, lower case and split at _, - and ., hold a secret's word, or api then key."""
    assert redacted({key: SENTINEL, "title": "Kept"}) == {key: "[redacted]", "title": "Kept"}


@pytest.mark.parametrize(
    "key",
    ["max_tokens", "tokenizer", "secretary", "key_api", "api_url", "key", "event", "title"],
)
def test_a_word_matches_whole_and_api_only_before_key(key: str) -> None:
    """max_tokens is no token, and api names a secret only when key follows it."""
    assert redacted({key: "kept"}) == {key: "kept"}


VOCABULARY = ("api", "key", "token", "tokens", "max", "set", "cookie", "x", "secret")


def test_the_rule_holds_for_every_short_key_from_a_vocabulary() -> None:
    """Up to three words, joined by any one separator, in any case: secret by the rule."""
    for count in range(1, 4):
        for words in product(VOCABULARY, repeat=count):
            expected = bool({"authorization", "cookie", "token", "password", "secret"} & {*words})
            expected = expected or ("api", "key") in pairwise(words)
            for separator, case in product("_-.", (str.lower, str.upper, str.title)):
                key = case(separator.join(words))
                assert (redacted({key: SENTINEL}) == {key: "[redacted]"}) is expected, key


def test_secrets_are_redacted_at_any_depth() -> None:
    """Through dicts, lists and tuples, only what a secret's key holds changes."""
    event = {
        "event": "http.get",
        "pages": [{"title": "Plan", "token": SENTINEL}, "plain"],
        "attempts": ({"cookie": COOKIE, "status": 401},),
        "settings": {"site": {"api_token": SENTINEL, "url": "https://example.invalid"}},
    }
    assert redacted(event) == {
        "event": "http.get",
        "pages": [{"title": "Plan", "token": "[redacted]"}, "plain"],
        "attempts": ({"cookie": "[redacted]", "status": 401},),
        "settings": {"site": {"api_token": "[redacted]", "url": "https://example.invalid"}},
    }


def test_the_value_given_is_left_as_it_was() -> None:
    """Logging headers never takes their credentials from the request that sends them."""
    headers = {"Authorization": f"Basic {BASIC}", "Accept": "application/json"}
    event = {"event": "http.get", "headers": headers}
    redacted(event)
    assert event == {"event": "http.get", "headers": headers}
    assert headers["Authorization"] == f"Basic {BASIC}"


def test_an_exception_info_stays_one() -> None:
    """exc_info stays the tuple that structlog renders a traceback from."""
    error = ValueError("refused")
    exc_info = (ValueError, error, error.__traceback__)
    assert redacted({"exc_info": exc_info}) == {"exc_info": exc_info}
    assert type(redacted(exc_info)) is tuple


def test_the_processor_redacts_an_event_before_structlog_renders_it() -> None:
    """Nested under headers.Authorization, neither sentinel nor the base64 is written."""
    out = io.StringIO()
    log = structlog.wrap_logger(
        structlog.PrintLogger(out),
        processors=[redact_secrets, structlog.processors.JSONRenderer()],
    )
    log.warning(
        "sign_in.refused",
        status=401,
        headers={"Authorization": {"basic": BASIC, "cookie": COOKIE}, "Set-Cookie": COOKIE},
        token=SENTINEL,
    )
    written = out.getvalue()
    assert json.loads(written) == {
        "event": "sign_in.refused",
        "status": 401,
        "headers": {"Authorization": "[redacted]", "Set-Cookie": "[redacted]"},
        "token": "[redacted]",
    }
    assert all(secret not in written for secret in (SENTINEL, COOKIE, BASIC))
