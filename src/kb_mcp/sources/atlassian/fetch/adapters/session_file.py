"""The saved session: a site's cookies, in a file that the user alone can read."""

from __future__ import annotations

import fcntl
import json
import os
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

import structlog

from kb_mcp.kernel.fields import Fields
from kb_mcp.sources.atlassian.fetch.adapters.raw_store import replace_synced

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping
    from pathlib import Path

COOKIES = "cookies.json"
# The browser profile of the sign-in window, beside the cookies.
PROFILE = "browser"


def folder_of(root: Path, site: str) -> Path:
    """Give the folder that keeps a site's session, under the session's place ``root``."""
    return root / (urlsplit(site).hostname or "")


def kept_why(root: Path, source: str, sites: Mapping[str, str]) -> str | None:
    """Say why the session kept before stays, or None when this source's site takes it.

    ``sites`` gives the site of every source that names one, ``source``'s among them, in
    their order. The session is a site's when every cookie is of its host, as ``login``
    saved them filtered to one host, and of no other site's, and the site has no cookies
    of its own yet. Only the first source of the host that it is of, or of the first host
    when it is of none, says why it stays: an empty reason is another's to say.
    """
    try:
        cookies = read_cookies(root / COOKIES)
    except OSError, ValueError:
        cookies = []
    hosts = {name: urlsplit(site).hostname or "" for name, site in sites.items()}
    host = hosts[source]
    matching = sorted(
        {
            each
            for each in hosts.values()
            if cookies and len(for_site(cookies, each)) == len(cookies)
        }
    )
    speaking = (matching or sorted(hosts.values()))[0]
    if matching == [host] and not (root / host / COOKIES).exists():
        return None
    if source != next(name for name, each in hosts.items() if each == speaking):
        return ""
    if matching == [host]:
        return "this site has a session of its own; remove the former one"
    if not matching:
        return "its cookies are of no site that the settings name; remove it"
    return (
        f"its cookies are of several sites, {', '.join(matching)}: log in to each, then remove it"
    )


def adopt_former_session(root: Path, source: str, sites: Mapping[str, str]) -> None:
    """Move the session kept before sessions were a site's into a source's site's folder, once.

    As ``kept_why`` judges, under a lock of ``root``: a run that finds it held leaves the
    move to the run that holds it. The cookies go last, so that their place says it is done.
    """
    former, folder = root / COOKIES, folder_of(root, sites[source])
    if not former.exists():
        return
    log = structlog.get_logger()
    handle = -1
    try:
        handle = os.open(root / ".lock", os.O_RDWR | os.O_CREAT, 0o600)
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        why = kept_why(root, source, sites)
        if why is None:
            folder.mkdir(mode=0o700, exist_ok=True)
            if (root / PROFILE).exists() and not (folder / PROFILE).exists():
                (root / PROFILE).rename(folder / PROFILE)
            former.rename(folder / COOKIES)
            log.info("session.moved", host=folder.name, session=str(folder))
        elif why:
            log.warning("session.not_moved", host=folder.name, session=str(former), reason=why)
    except BlockingIOError:
        return
    except OSError as error:
        why = f"not moved: {type(error).__name__}"
        log.warning("session.not_moved", host=folder.name, session=str(former), reason=why)
    finally:
        if handle >= 0:
            os.close(handle)


def read_cookies(path: Path) -> list[dict[str, str]]:
    """Read the saved cookies: name, value, domain and path of each.

    Raises FileNotFoundError when no session was saved, and RepresentationError for a
    file in another shape.
    """
    cookies = Fields.each(json.loads(path.read_text(encoding="utf-8")), path.name)
    return [
        {
            "name": cookie.text("name"),
            "value": cookie.text("value"),
            "domain": cookie.text("domain"),
            "path": cookie.optional_text("path", absent=True) or "/",
        }
        for cookie in cookies
    ]


def write_cookies(path: Path, cookies: Iterable[Mapping[str, object]]) -> None:
    """Replace the saved cookies whole, in a file the user alone can read from the start.

    A failure leaves the cookies saved before as they were.
    """
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    replace_synced(path, json.dumps([dict(cookie) for cookie in cookies]).encode())


def for_site(cookies: Iterable[Mapping[str, object]], host: str) -> list[dict[str, str]]:
    """Keep the cookies that the site's host is within, with a value: never a media host's.

    A cookie the site set without a value is left out, since it cannot be sent again.
    """
    kept: list[dict[str, str]] = []
    for cookie in cookies:
        name, value, domain = cookie.get("name"), cookie.get("value"), cookie.get("domain")
        if not (isinstance(name, str) and isinstance(value, str) and isinstance(domain, str)):
            continue
        bare = domain.lstrip(".")
        if host == bare or host.endswith(f".{bare}"):
            path = cookie.get("path")
            kept.append({"name": name, "value": value, "domain": domain, "path": str(path or "/")})
    return kept
