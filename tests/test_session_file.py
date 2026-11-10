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


# A site, its host, and another site's host and site.
SITE = "https://sandbox.example.invalid"
HOST = "sandbox.example.invalid"
ELSEWHERE = "client.example.invalid"
CLIENT = f"https://{ELSEWHERE}"


def former(root: Path, domain: str) -> None:
    """Keep a session as runs kept it before sessions were a site's: cookies and profile."""
    write_cookies(root / COOKIES, [{"name": "s", "value": "v", "domain": domain}])
    (root / PROFILE / "Default").mkdir(parents=True)


def files(root: Path) -> list[Path]:
    """Give every file and folder under the session's place, but its lock, by its path."""
    return sorted(path.relative_to(root) for path in root.rglob("*") if path.name != ".lock")


def test_the_former_session_moves_into_its_site_s_folder_once(tmp_path: Path) -> None:
    """Plan 059: the cookies and the profile beside them, said at INFO; then nothing."""
    root = tmp_path / "session"
    former(root, f".{HOST}")
    with capture_logs() as logged:
        adopt_former_session(root, SITE, (SITE, CLIENT))
        adopt_former_session(root, SITE, (SITE, CLIENT))
        adopt_former_session(root, CLIENT, (SITE, CLIENT))
    assert sorted(each.name for each in root.iterdir() if each.name != ".lock") == [HOST]
    assert sorted(each.name for each in (root / HOST).iterdir()) == [PROFILE, COOKIES]
    assert (root / HOST).stat().st_mode & 0o777 == OWNER_ONLY_FOLDER
    assert [(each["event"], each["host"]) for each in logged] == [("session.moved", HOST)]


def test_a_site_s_folder_without_cookies_takes_the_former_session(tmp_path: Path) -> None:
    """Review round 1: a profile alone, of a login not done, is no session of its own."""
    root = tmp_path / "session"
    former(root, HOST)
    (folder_of(root, SITE) / PROFILE).mkdir(parents=True)
    adopt_former_session(root, SITE, (SITE,))
    assert (folder_of(root, SITE) / COOKIES).exists()
    assert not (root / COOKIES).exists()


@pytest.mark.parametrize(
    ("domain", "own", "reason"),
    [
        ("elsewhere.invalid", False, "of no site that the settings name"),
        (HOST, True, "a session of its own"),
        (".example.invalid", False, "of several sites"),
    ],
    ids=["no site's", "beside one of its own", "several sites'"],
)
def test_a_former_session_that_no_one_site_takes_stays_said_once(
    tmp_path: Path, domain: str, *, own: bool, reason: str
) -> None:
    """A warning says why, once whichever site's runs find it; nothing moves or goes."""
    root = tmp_path / "session"
    former(root, domain)
    if own:
        write_cookies(folder_of(root, SITE) / COOKIES, [])
    before = files(root)
    with capture_logs() as logged:
        for site in (SITE, CLIENT):
            adopt_former_session(root, site, (SITE, CLIENT))
    assert files(root) == before
    assert [(each["event"], each["log_level"]) for each in logged] == [
        ("session.not_moved", "warning")
    ]
    assert reason in logged[0]["reason"]
