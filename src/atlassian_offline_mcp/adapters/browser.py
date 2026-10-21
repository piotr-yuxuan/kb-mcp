"""Sign-in in a Chrome window: the one place that drives a browser.

Playwright starts the installed Chrome with a dedicated profile; the user signs in as
they always do, and the site's cookies are handed back. Nothing else reads through the
browser.
"""

from __future__ import annotations

import json
import time
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

from playwright.sync_api import Error, sync_playwright

if TYPE_CHECKING:
    from pathlib import Path

SIGN_IN_TIMEOUT_S = 300
POLL_MS = 2_000
# Signed in once Jira or Confluence answers with an account, from inside the page.
SIGNED_IN_JS = """async () => {
  for (const path of ['/rest/api/3/myself', '/wiki/rest/api/user/current']) {
    try {
      const reply = await fetch(path, {signal: AbortSignal.timeout(10000)});
      if (reply.ok && (await reply.json()).accountId) return true;
    } catch (error) {}
  }
  return false;
}"""


class SignInTimeoutError(Exception):
    """The user did not finish signing in within the time allowed."""


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


def sign_in(
    site: str, profile: Path, chrome: str | None, *, extensions: bool = False
) -> list[dict[str, object]]:
    """Open the site in Chrome, wait until the user is signed in, return its cookies.

    No script runs in the identity provider's pages: only once back on the site.
    ``extensions`` lets Chrome load extensions, in case the sign-in needs one. Raises
    SignInTimeoutError when no sign-in completes within ``SIGN_IN_TIMEOUT_S``.
    """
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
            page.goto(f"{site}/wiki/home")
            deadline = time.monotonic() + SIGN_IN_TIMEOUT_S
            while time.monotonic() < deadline:
                try:
                    on_site = urlsplit(page.url).hostname == urlsplit(site).hostname
                    if on_site and page.evaluate(SIGNED_IN_JS):
                        return [dict(cookie) for cookie in context.cookies([site])]
                except Error:
                    pass  # the page navigated while the check ran; check again
                page.wait_for_timeout(POLL_MS)
        finally:
            context.close()
    raise SignInTimeoutError
