"""The sign-in window: done once the site answers with an account, from inside the page."""

from __future__ import annotations

from typing import TYPE_CHECKING, Self

import pytest
from playwright.sync_api import Error

from kb_mcp.sources.atlassian.adapters import browser
from kb_mcp.sources.atlassian.adapters.browser import SignInFailedError, sign_in

if TYPE_CHECKING:
    from pathlib import Path

    from _pytest.monkeypatch import MonkeyPatch

SITE = "https://sandbox.example.invalid"
IDENTITY_PROVIDER = "https://login.example.invalid/authorize"


class Page:
    """A page that, like Playwright's, learns of navigation only during its own calls.

    It stops on the identity provider, then lands on the site after ``waits`` waits; or
    it is closed by the user after them.
    """

    def __init__(self, waits: int, *, closes: bool = False) -> None:
        """Start before the first page is opened."""
        self.url = "about:blank"
        self.waits = waits
        self.closes = closes
        self.closed = False
        self.checks = 0

    def goto(self, _: str, **__: float) -> None:
        """Stop on the identity provider, as single sign-on does."""
        self.url = IDENTITY_PROVIDER
        message = "navigation timed out on the identity provider"
        raise Error(message)

    def wait_for_timeout(self, _: float) -> None:
        """Let time pass: the only moment the page's state is brought up to date."""
        self.waits -= 1
        if self.waits <= 0:
            self.closed = self.closes
            self.url = f"{SITE}/wiki/home"

    def evaluate(self, _: str, paths: list[str]) -> bool:
        """Answer the in-page check: signed in once on the site."""
        self.checks += 1
        assert paths == ["/wiki/rest/api/user/current", "/rest/api/3/myself"]
        return self.url.startswith(SITE)

    def is_closed(self) -> bool:
        """Say whether the user closed the window."""
        return self.closed


class Context:
    """A browser context with one page and the cookies of a signed-in site."""

    def __init__(self, page: Page) -> None:
        """Hold the page."""
        self.pages = [page]
        self.closed = False

    def cookies(self) -> list[dict[str, object]]:
        """Return every cookie of the browser, the site's among them."""
        return [{"name": "tenant", "value": "1", "domain": "sandbox.example.invalid"}]

    def close(self) -> None:
        """Close the browser."""
        self.closed = True


class Playwright:
    """Playwright's entry, launching the one context."""

    def __init__(self, context: Context) -> None:
        """Hold the context to launch."""
        self.context = context
        self.chromium = self

    def __enter__(self) -> Self:
        """Start."""
        return self

    def __exit__(self, *_: object) -> None:
        """Stop."""

    def launch_persistent_context(self, *_: object, **__: object) -> Context:
        """Open the persistent profile."""
        return self.context


def test_a_sign_in_through_an_identity_provider_is_seen_to_end(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """The window comes back to the site after the user signs in, and the cookies follow."""
    page = Page(waits=3)
    context = Context(page)
    monkeypatch.setattr(browser, "sync_playwright", lambda: Playwright(context))
    monkeypatch.setattr(browser, "SIGN_IN_TIMEOUT_S", 5)
    assert sign_in(SITE, tmp_path / "profile", None) == context.cookies()
    assert page.checks == 1
    assert context.closed


def test_closing_the_window_on_the_identity_provider_is_seen(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """The user giving up ends the wait at once, saying why."""
    context = Context(Page(waits=2, closes=True))
    monkeypatch.setattr(browser, "sync_playwright", lambda: Playwright(context))
    monkeypatch.setattr(browser, "SIGN_IN_TIMEOUT_S", 5)
    with pytest.raises(SignInFailedError, match="the sign-in window was closed"):
        sign_in(SITE, tmp_path / "profile", None)
