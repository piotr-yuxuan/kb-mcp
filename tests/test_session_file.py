"""The saved session: cookies replaced whole, readable by the user alone."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from kb_mcp.kernel.fields import RepresentationError
from kb_mcp.sources.atlassian.fetch.adapters.session_file import (
    read_cookies,
    write_cookies,
)

if TYPE_CHECKING:
    from pathlib import Path

OWNER_ONLY = 0o600


def test_cookies_read_back_with_their_path_defaulted(tmp_path: Path) -> None:
    """What Playwright gives is kept whole; reading takes name, value, domain and path."""
    path = tmp_path / "session" / "cookies.json"
    write_cookies(path, [{"name": "s", "value": "v", "domain": ".x.invalid", "httpOnly": True}])
    assert read_cookies(path) == [{"name": "s", "value": "v", "domain": ".x.invalid", "path": "/"}]
    assert path.stat().st_mode & 0o777 == OWNER_ONLY
    assert [entry.name for entry in path.parent.iterdir()] == ["cookies.json"]


def test_a_file_already_open_to_others_is_replaced_by_one_that_is_not(tmp_path: Path) -> None:
    """Saving again never keeps a looser mode from before."""
    path = tmp_path / "cookies.json"
    path.write_text("[]", "utf-8")
    path.chmod(0o644)
    write_cookies(path, [])
    assert path.stat().st_mode & 0o777 == OWNER_ONLY


def test_a_cookie_file_in_another_shape_is_refused(tmp_path: Path) -> None:
    """A cookie without a value is not a session."""
    path = tmp_path / "cookies.json"
    path.write_text('[{"name": "s", "domain": "x"}]', "utf-8")
    with pytest.raises(RepresentationError, match=r"cookies\.json\[0\]\.value: missing"):
        read_cookies(path)
