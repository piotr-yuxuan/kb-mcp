"""Sign-in in a Chrome window: the one place that drives a browser.

Playwright starts the installed Chrome with a dedicated profile; the user signs in as
they always do, and the site's cookies are handed back. Nothing else reads through the
browser.
"""

from __future__ import annotations

import contextlib
import json
import time
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

from playwright.sync_api import Error, sync_playwright

from kb_mcp.sources.atlassian.fetch.adapters import confluence_v2, jira_v3

if TYPE_CHECKING:
    from pathlib import Path

SIGN_IN_TIMEOUT_S = 300
POLL_MS = 2_000
# Signed in once one of the given paths answers with an account, from inside the page.
SIGNED_IN_JS = """async (paths) => {
  for (const path of paths) {
    try {
      const reply = await fetch(path, {signal: AbortSignal.timeout(10000)});
      if (reply.ok && (await reply.json()).accountId) return true;
    } catch (error) {}
  }
  return false;
}"""


class SignInFailedError(Exception):
    """No sign-in completed: the time ran out, or the window was closed."""


def disable_password_saving(profile: Path) -> None:
    """Stop Chrome offering to save the password typed at sign-in, in this profile.

    Playwright starts Chrome with a mock keychain, so the profile's key is a fixed,
    public one: a saved password would be readable by anyone who reads the profile.
    """
    preferences = profile / "Default" / "Preferences"
    preferences.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        settings = json.loads(preferences.read_text(encoding="utf-8"))
    except OSError, ValueError:
        settings = {}
    if not isinstance(settings, dict):
        settings = {}
    settings["credentials_enable_service"] = False
    settings["profile"] = {**(settings.get("profile") or {}), "password_manager_enabled": False}
    settings["autofill"] = {**(settings.get("autofill") or {}), "profile_enabled": False}
    preferences.write_text(json.dumps(settings), encoding="utf-8")


def open_sign_in_window(
    site: str, profile: Path, chrome: Path | None, *, extensions: bool = False
) -> list[dict[str, object]]:
    """Open the site in Chrome, wait until the user is signed in, return every cookie.

    No script runs in the identity provider's pages: only once back on the site. The
    caller keeps those of the site. ``extensions`` lets Chrome load extensions, in case
    the sign-in needs one. Raises SignInFailedError when no sign-in completes within
    ``SIGN_IN_TIMEOUT_S``, or when the window is closed.
    """
    paths = [confluence_v2.current_user_request().path, jira_v3.myself_request().path]
    with sync_playwright() as playwright:
        context = playwright.chromium.launch_persistent_context(
            profile,
            headless=False,
            channel=None if chrome else "chrome",
            executable_path=chrome,
            ignore_default_args=["--disable-extensions"] if extensions else None,
        )
        try:
            page = context.pages[0] if context.pages else context.new_page()
            deadline = time.monotonic() + SIGN_IN_TIMEOUT_S
            # A slow identity provider times the first page out: the polling goes on.
            with contextlib.suppress(Error):
                page.goto(f"{site}/wiki/home", timeout=SIGN_IN_TIMEOUT_S * 1000)
            while time.monotonic() < deadline:
                # The page may navigate while the check runs, or the window close. The
                # wait is Playwright's own: only its calls bring the page's address and
                # state up to date, so a plain sleep would never see the sign-in end.
                with contextlib.suppress(Error):
                    on_site = urlsplit(page.url).hostname == urlsplit(site).hostname
                    if on_site and page.evaluate(SIGNED_IN_JS, paths):
                        return [dict(cookie) for cookie in context.cookies()]
                with contextlib.suppress(Error):
                    page.wait_for_timeout(POLL_MS)
                if page.is_closed():
                    message = "the sign-in window was closed"
                    raise SignInFailedError(message)
        finally:
            context.close()
    message = f"no sign-in within {SIGN_IN_TIMEOUT_S} s"
    raise SignInFailedError(message)
