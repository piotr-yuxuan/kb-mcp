"""The saved session: the site's cookies, in a file that the user alone can read."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

from atlassian_offline_mcp.adapters.fields import Fields

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

COOKIES = "cookies.json"


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
