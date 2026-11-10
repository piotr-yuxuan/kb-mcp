"""The saved session: a site's cookies, in a file that the user alone can read.

Each site's session is a folder of the session's place, named after its host: its
cookies and the browser profile that signed it in.
"""

from __future__ import annotations

import fcntl
import json
import os
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

import structlog

from kb_mcp.kernel.fields import Fields

if TYPE_CHECKING:
    from collections.abc import Collection, Iterable, Mapping

COOKIES = "cookies.json"
# The browser profile of the sign-in window, beside the cookies.
PROFILE = "browser"


def folder_of(root: Path, site: str) -> Path:
    """Give the folder that keeps a site's session, under the session's place ``root``."""
    return root / (urlsplit(site).hostname or "")


def kept_why(former: Path, folder: Path, sites: Collection[str]) -> str | None:
    """Say why the session kept before stays, or None when this site's folder takes it.

    ``folder`` is the site's, ``sites`` every site that the settings name. It is this
    site's when every cookie is of its host, as ``login`` saved them filtered to one host,
    and of no other site's, and this site has no cookies of its own yet. An empty reason
    is one that another site's run says, or that it moves the session: one run says each.
    """
    try:
        cookies = read_cookies(former)
    except OSError, ValueError:
        cookies = []
    host = folder.name
    hosts = sorted({urlsplit(each).hostname or "" for each in sites} | {host})
    matching = [each for each in hosts if cookies and len(for_site(cookies, each)) == len(cookies)]
    if matching == [host]:
        own = (folder / COOKIES).exists()
        return "this site has a session of its own; remove the former one" if own else None
    if host != (matching or hosts)[0]:
        return ""
    if not matching:
        return "its cookies are of no site that the settings name; remove it"
    return (
        f"its cookies are of several sites, {', '.join(matching)}: log in to each, then remove it"
    )


def adopt_former_session(root: Path, site: str, sites: Collection[str]) -> None:
    """Move the session kept before sessions were a site's into this site's folder, once.

    That is ``root/cookies.json`` and the profile beside it, as ``kept_why`` judges,
    under a lock of ``root``, which another run holding skips the move: it makes it. The
    profile goes first, unless the site has one, then the cookies, whose place says that
    the move is done: ``session.moved``, at INFO. Else, or when a move fails, they stay,
    with a warning, ``session.not_moved``, saying why. With none, nothing is said.
    """
    former, folder = root / COOKIES, folder_of(root, site)
    if not former.exists():
        return
    log = structlog.get_logger()
    handle = os.open(root / ".lock", os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        why = kept_why(former, folder, sites)
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
    data = json.dumps([dict(cookie) for cookie in cookies]).encode()
    handle, hidden = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)  # mode 0600
    try:
        with os.fdopen(handle, "wb") as file:
            file.write(data)
            file.flush()
            os.fsync(file.fileno())
        Path(hidden).replace(path)
    finally:
        Path(hidden).unlink(missing_ok=True)


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
