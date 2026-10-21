"""The index: built from the mirror alone, replaced whole, opened read-only."""

from __future__ import annotations

import sqlite3
from dataclasses import replace
from datetime import timedelta
from typing import TYPE_CHECKING

import pytest

from atlassian_offline_mcp.adapters import sqlite_index
from atlassian_offline_mcp.adapters.sqlite_index import UnavailableIndexError, reading
from atlassian_offline_mcp.app.indexing import build_index
from atlassian_offline_mcp.cli import main
from tests.mirrors import FILLERS, MOMENT, fillers, issue, location, page, write

if TYPE_CHECKING:
    from pathlib import Path

    from _pytest.capture import CaptureFixture
    from _pytest.monkeypatch import MonkeyPatch

BAD_SETTINGS = 2
SKIPPED = 3
BODY = "# Kafka\n\nLead.\n\n## Retention\n\nSeven days.\n\n```\n# not a heading\n```\n"


@pytest.fixture
def data(tmp_path: Path, monkeypatch: MonkeyPatch) -> Path:
    """Give each test a scratch home and a data directory with an empty mirror."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    (tmp_path / "data" / "docs").mkdir(parents=True)
    return tmp_path / "data"


def index(data: Path, capsys: CaptureFixture[str]) -> tuple[int, str, str]:
    """Run ``index`` on the data directory; return its exit status, stdout and stderr."""
    status = main(["index", "--config", str(data / "none.toml"), "--data-dir", str(data)])
    out, err = capsys.readouterr()
    return status, out, err


def test_every_document_is_indexed_and_reads_back(data: Path, capsys: CaptureFixture[str]) -> None:
    """The index holds each document's front matter whole, and its body exactly."""
    front = page("196845", "Kafka", labels=("ops",), breadcrumb=("Home",))
    path = write(data / "docs", front, BODY)
    write(data / "docs", issue("PROJ-1", "An issue"))
    status, out, err = index(data, capsys)
    assert (status, err) == (0, "")
    assert "indexed 2 documents (issue: 1, page: 1)" in out
    with reading(data / "index.sqlite") as reader:
        (entry,) = reader.entries(paths=[path])
        assert entry.front == front
        assert (entry.length, entry.sections) == (len(BODY), 2)
        assert reader.text(path, 0, entry.length) == BODY
        assert reader.text(path, 9, 14) == BODY[9:14]
        second = BODY.index("## ")
        assert reader.bounds(path) == [(0, second, "Kafka"), (second, len(BODY), "Retention")]
        summary = reader.summary()
    assert summary.built_at.tzinfo is not None
    assert (summary.types, summary.spaces, summary.projects) == (
        {"issue": 1, "page": 1},
        {"ENG": 1},
        {"PROJ": 1},
    )


def test_a_refused_file_is_named_and_the_others_indexed(
    data: Path, capsys: CaptureFixture[str]
) -> None:
    """Front matter that the codec refuses, a file not in UTF-8 and a duplicate are skipped."""
    fillers(data / "docs")
    broken = data / "docs" / "confluence" / "ENG" / "1-broken.md"
    broken.write_text("---\ntitle: no other key\n---\n", encoding="utf-8")
    (data / "docs" / "confluence" / "ENG" / "2-latin.md").write_bytes(b"---\ntitle: \xe9\n---\n")
    twin = write(data / "docs", page("900001", "Another title"))
    # Documents come in the order of their paths, so the later of two twins is skipped.
    later = max(twin, location(page("900001", "Lorem 1")))
    status, out, err = index(data, capsys)
    assert status == 1
    assert f"indexed {FILLERS} documents (page: {FILLERS})" in out
    assert "skipped confluence/ENG/1-broken.md: front matter without exactly" in err
    assert "skipped confluence/ENG/2-latin.md: not UTF-8" in err
    assert f"skipped {later}: another document has the same source and id" in err
    assert f"{SKIPPED} files skipped" in err
    with reading(data / "index.sqlite") as reader:
        assert reader.summary().skipped == SKIPPED


def test_a_failed_build_keeps_the_old_index(data: Path, monkeypatch: MonkeyPatch) -> None:
    """The new index replaces the old one only once complete; nothing is left behind."""
    write(data / "docs", page("196845", "Kafka"))
    build_index(data / "docs", data / "index.sqlite", MOMENT)
    write(data / "docs", page("196846", "Another"))

    def fail(*_: object) -> None:
        raise RuntimeError

    monkeypatch.setattr(sqlite_index.Writer, "add", fail)
    with pytest.raises(RuntimeError):
        build_index(data / "docs", data / "index.sqlite", MOMENT + timedelta(hours=1))
    assert sorted(path.name for path in data.iterdir()) == ["docs", "index.sqlite"]
    with reading(data / "index.sqlite") as reader:
        assert reader.summary().built_at == MOMENT


def test_a_build_leaves_no_temporary_file(data: Path, capsys: CaptureFixture[str]) -> None:
    """Built twice, the data directory holds the mirror and one index, no journal."""
    write(data / "docs", page("196845", "Kafka"))
    assert index(data, capsys)[0] == 0
    assert index(data, capsys)[0] == 0
    assert sorted(path.name for path in data.iterdir()) == ["docs", "index.sqlite"]


def test_no_mirror_is_a_failure(data: Path, capsys: CaptureFixture[str]) -> None:
    """Without <data>/docs, nothing is built and the command exits 1."""
    (data / "docs").rmdir()
    status, _, err = index(data, capsys)
    assert status == 1
    assert "no mirror at" in err
    assert list(data.iterdir()) == []


def test_refused_settings_exit_2(data: Path, capsys: CaptureFixture[str]) -> None:
    """A data directory in a synchronised folder is refused before anything is built."""
    dropbox = data.parent / "home" / "Dropbox" / "data"
    status = main(["index", "--config", str(data / "none.toml"), "--data-dir", str(dropbox)])
    assert status == BAD_SETTINGS
    assert "settings refused: data_dir: under a Dropbox folder" in capsys.readouterr().err


def test_reading_opens_read_only(data: Path, monkeypatch: MonkeyPatch) -> None:
    """The connection that a reading opens refuses to write."""
    write(data / "docs", page("196845", "Kafka"))
    build_index(data / "docs", data / "index.sqlite", MOMENT)
    opened: list[sqlite3.Connection] = []
    connect = sqlite3.connect

    def spy(database: str, *, uri: bool = False) -> sqlite3.Connection:
        connection = connect(database, uri=uri)
        opened.append(connection)
        return connection

    monkeypatch.setattr(sqlite3, "connect", spy)
    with reading(data / "index.sqlite") as reader:
        assert reader.summary().types == {"page": 1}
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            opened[0].execute("CREATE TABLE written (value)")


def test_no_index_or_another_file_is_unavailable(data: Path) -> None:
    """A missing index, or a file that is not one, names the command that builds it."""
    with (
        pytest.raises(UnavailableIndexError, match=r"^no index at .*atlassian-offline-mcp index"),
        reading(data / "index.sqlite"),
    ):
        pass
    (data / "index.sqlite").write_text("not a database", encoding="utf-8")
    with (
        pytest.raises(UnavailableIndexError, match="not an index that this version reads"),
        reading(data / "index.sqlite"),
    ):
        pass


def test_a_new_index_is_read_from_the_next_reading(data: Path) -> None:
    """Replacing the file while nothing reads it is seen by the next reading."""
    write(data / "docs", page("196845", "Kafka"))
    build_index(data / "docs", data / "index.sqlite", MOMENT)
    write(data / "docs", replace(page("196846", "Another"), space="OPS"))
    build_index(data / "docs", data / "index.sqlite", MOMENT)
    with reading(data / "index.sqlite") as reader:
        assert reader.summary().spaces == {"ENG": 1, "OPS": 1}
