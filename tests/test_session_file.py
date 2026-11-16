"""The saved session: cookies replaced whole, readable by the user alone, a folder a site."""

from __future__ import annotations

import fcntl
import os
from pathlib import Path

import pytest
from structlog.testing import capture_logs

from kb_mcp.kernel.fields import RepresentationError
from kb_mcp.sources.atlassian.fetch.adapters.http import SignInNeededError
from kb_mcp.sources.atlassian.fetch.adapters.session_file import (
    COOKIES,
    PROFILE,
    adopt_former_session,
    folder_of,
    read_cookies,
    write_cookies,
)
from kb_mcp.sources.atlassian.fetch.adapters.sign_in import SavedSession

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


# The sources' sites: Confluence's and Jira's of one, the client's of another.
SITES = {"confluence": SITE, "jira": SITE, "clientjira": CLIENT}


def test_the_former_session_moves_into_its_site_s_folder_once(tmp_path: Path) -> None:
    """Plan 059: the cookies and the profile beside them, said at INFO; then nothing."""
    root = tmp_path / "session"
    former(root, f".{HOST}")
    with capture_logs() as logged:
        for source in ("confluence", "jira", "clientjira", "confluence"):
            adopt_former_session(root, source, SITES)
    assert sorted(each.name for each in root.iterdir() if each.name != ".lock") == [HOST]
    assert sorted(each.name for each in (root / HOST).iterdir()) == [PROFILE, COOKIES]
    assert (root / HOST).stat().st_mode & 0o777 == OWNER_ONLY_FOLDER
    assert [(each["event"], each["host"]) for each in logged] == [("session.moved", HOST)]


def test_a_site_s_folder_without_cookies_takes_the_former_session(tmp_path: Path) -> None:
    """Review round 1: a profile alone, of a login not done, is no session of its own."""
    root = tmp_path / "session"
    former(root, HOST)
    (folder_of(root, SITE) / PROFILE).mkdir(parents=True)
    adopt_former_session(root, "jira", {"jira": SITE})
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
    """A warning says why, once whichever sources' runs find it; nothing moves or goes.

    Review round 2: once, though two sources share a site.
    """
    root = tmp_path / "session"
    former(root, domain)
    if own:
        write_cookies(folder_of(root, SITE) / COOKIES, [])
    before = files(root)
    with capture_logs() as logged:
        for source in SITES:
            adopt_former_session(root, source, SITES)
    assert files(root) == before
    assert [(each["event"], each["log_level"]) for each in logged] == [
        ("session.not_moved", "warning")
    ]
    assert reason in logged[0]["reason"]


def test_the_former_session_signs_in_its_own_site_alone_until_it_moves(tmp_path: Path) -> None:
    """Review round 2: another site, without cookies of its own, is asked to log in."""
    root = tmp_path / "session"
    former(root, HOST)
    own = SavedSession(
        site=SITE, folder=folder_of(root, SITE), again="", source="jira", sites=SITES
    )
    with own.client() as client:
        assert [cookie.domain for cookie in client.cookies.jar] == [HOST]
    other = SavedSession(
        site=CLIENT, folder=folder_of(root, CLIENT), again="", source="clientjira", sites=SITES
    )
    with pytest.raises(SignInNeededError):
        other.client()


def test_a_former_session_locked_by_another_run_is_left_to_it(tmp_path: Path) -> None:
    """Review round 2: nothing moves, nothing is said: the other run moves it."""
    root = tmp_path / "session"
    former(root, HOST)
    before = files(root)
    handle = os.open(root / ".lock", os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(handle, fcntl.LOCK_EX)
        with capture_logs() as logged:
            adopt_former_session(root, "jira", SITES)
    finally:
        os.close(handle)
    assert files(root) == before
    assert logged == []


def failing_rename(monkeypatch: pytest.MonkeyPatch, name: str) -> None:
    """Make renaming a file or folder of this name fail, as a full disk would."""
    rename = Path.rename

    def renamed(self: Path, target: Path) -> Path:
        if self.name == name:
            raise OSError(28, "No space left on device")
        return rename(self, target)

    monkeypatch.setattr(Path, "rename", renamed)


def test_cookies_that_fail_to_move_stay_and_a_later_run_moves_them(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Review round 2: the profile moved first; a warning; the next call ends the move."""
    root = tmp_path / "session"
    former(root, HOST)
    with monkeypatch.context() as full:
        failing_rename(full, COOKIES)
        with capture_logs() as logged:
            adopt_former_session(root, "jira", SITES)
    assert (folder_of(root, SITE) / PROFILE).exists()
    assert (root / COOKIES).exists()
    assert [(each["event"], each["reason"]) for each in logged] == [
        ("session.not_moved", "not moved: OSError")
    ]
    adopt_former_session(root, "jira", SITES)
    assert (folder_of(root, SITE) / COOKIES).exists()
    assert not (root / COOKIES).exists()


def test_a_profile_that_fails_to_move_leaves_the_cookies(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Review round 2: the cookies, moved last, stay where they sign in still."""
    root = tmp_path / "session"
    former(root, HOST)
    failing_rename(monkeypatch, PROFILE)
    with capture_logs() as logged:
        adopt_former_session(root, "jira", SITES)
    assert (root / COOKIES).exists()
    assert not (folder_of(root, SITE) / COOKIES).exists()
    assert [each["event"] for each in logged] == ["session.not_moved"]


def test_a_run_signed_in_by_a_session_not_moved_keeps_it_there_for_the_next_move(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Review round 3: a fetch whose move failed signs in and keeps; the next run moves all.

    Kept into the site's folder, the cookies would give the site a session of its own, and
    the former profile would never move.
    """
    root = tmp_path / "session"
    former(root, HOST)
    session = SavedSession(
        site=SITE, folder=folder_of(root, SITE), again="", source="jira", sites=SITES
    )
    with monkeypatch.context() as full:
        failing_rename(full, PROFILE)
        session.adopt_former()
    with session.client() as client:
        session.keep(client)
    assert not (folder_of(root, SITE) / COOKIES).exists()
    with capture_logs() as logged:
        session.adopt_former()
    assert sorted(each.name for each in folder_of(root, SITE).iterdir()) == [PROFILE, COOKIES]
    assert not (root / COOKIES).exists()
    assert not (root / PROFILE).exists()
    assert [each["event"] for each in logged] == ["session.moved"]


def test_a_lock_that_cannot_be_made_is_a_warning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Review round 2: an unwritable folder stops no run."""
    root = tmp_path / "session"
    former(root, HOST)

    def refused(*_: object) -> int:
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(os, "open", refused)
    with capture_logs() as logged:
        adopt_former_session(root, "jira", SITES)
    assert [(each["event"], each["reason"]) for each in logged] == [
        ("session.not_moved", "not moved: PermissionError")
    ]
