"""The saved session: cookies replaced whole, readable by the user alone, a folder a site."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from structlog.testing import capture_logs

from kb_mcp.kernel.fields import RepresentationError
from kb_mcp.sources.atlassian.fetch.adapters.session_file import (
    COOKIES,
    PROFILE,
    adopt_former_session,
    folder_of,
    read_cookies,
    write_cookies,
)

if TYPE_CHECKING:
    from pathlib import Path

OWNER_ONLY = 0o600
# A folder that the user alone may list and enter.
OWNER_ONLY_FOLDER = 0o700


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


# A site, its host, and another site's host.
SITE = "https://sandbox.example.invalid"
HOST = "sandbox.example.invalid"
ELSEWHERE = "client.example.invalid"


def former(root: Path, domain: str) -> None:
    """Keep a session as runs kept it before sessions were a site's: cookies and profile."""
    write_cookies(root / COOKIES, [{"name": "s", "value": "v", "domain": domain}])
    (root / PROFILE / "Default").mkdir(parents=True)


def test_the_former_session_moves_into_its_site_s_folder_once(tmp_path: Path) -> None:
    """Plan 059: the cookies and the profile beside them, said at INFO; then nothing."""
    root = tmp_path / "session"
    former(root, f".{HOST}")
    with capture_logs() as logged:
        adopt_former_session(root, SITE)
        adopt_former_session(root, SITE)
    assert sorted(each.name for each in root.iterdir()) == [HOST]
    assert sorted(each.name for each in (root / HOST).iterdir()) == [PROFILE, COOKIES]
    assert (root / HOST).stat().st_mode & 0o777 == OWNER_ONLY_FOLDER
    assert [(each["event"], each["host"]) for each in logged] == [("session.moved", HOST)]


@pytest.mark.parametrize("own", [False, True], ids=["another site's", "one of its own"])
def test_a_former_session_of_another_site_or_beside_one_of_its_own_stays(
    tmp_path: Path, *, own: bool
) -> None:
    """A warning says why; nothing moves, nothing is removed."""
    root = tmp_path / "session"
    former(root, HOST if own else ELSEWHERE)
    if own:
        write_cookies(folder_of(root, SITE) / COOKIES, [])
    before = sorted(path.relative_to(root) for path in root.rglob("*"))
    with capture_logs() as logged:
        adopt_former_session(root, SITE)
    assert sorted(path.relative_to(root) for path in root.rglob("*")) == before
    assert [(each["event"], each["log_level"]) for each in logged] == [
        ("session.not_moved", "warning")
    ]
