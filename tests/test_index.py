"""The index: built from the mirror alone, replaced whole, opened read-only."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import replace
from datetime import timedelta
from typing import TYPE_CHECKING

import pytest

from atlassian_offline_mcp.cli.main import main
from atlassian_offline_mcp.search.adapters import sqlite_index
from atlassian_offline_mcp.search.adapters.sqlite_index import UnavailableIndexError, reading
from atlassian_offline_mcp.search.app.indexing import build_index
from tests.mirrors import FILLERS, MOMENT, fillers, issue, location, page, write
from tests.test_cli import logged_as
from tests.test_observed import said

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


def index(
    data: Path, capsys: CaptureFixture[str], settings: str = 'search_mode = "lexical"\n'
) -> tuple[int, str, str]:
    """Run ``index`` on the data directory, by words alone unless the settings say otherwise.

    Return its exit status, stdout and stderr.
    """
    config = data.parent / "config.toml"
    config.write_text(settings, encoding="utf-8")
    status = main(["index", "--yes", "--config", str(config), "--data-dir", str(data)])
    out, err = capsys.readouterr()
    return status, out, err


def test_every_document_is_indexed_and_reads_back(data: Path, capsys: CaptureFixture[str]) -> None:
    """The index holds each document's front matter whole, and its body exactly."""
    front = page("196845", "Kafka", labels=("ops",), breadcrumb=("Home",))
    path = write(data / "docs", front, BODY)
    write(data / "docs", issue("PROJ-1", "An issue"))
    status, out, err = index(data, capsys)
    assert status == 0
    assert "skipped" not in err
    assert out.startswith("documents: 2\n")
    with reading(data / "index.sqlite") as reader:
        assert reader.embedded() is None
        (entry,) = reader.entries(paths=[path])
        assert entry.front == front
        assert (entry.length, entry.sections) == (len(BODY), 2)
        assert reader.text(path, 0, entry.length) == BODY
        assert reader.text(path, 9, 14) == BODY[9:14]
        second = BODY.index("## ")
        assert reader.bounds(path) == [(0, second), (second, len(BODY))]
        summary = reader.summary()
    assert summary.built_at.tzinfo is not None
    assert (summary.types, summary.spaces, summary.projects) == (
        {"issue": 1, "page": 1},
        {"ENG": 1},
        {"PROJ": 1},
    )


@pytest.mark.parametrize(
    ("summary", "shown"),
    [
        ("short", "documents: 1\nsections: 2\n"),
        ("detailed", "indexed 1 documents (page: 1), 2 sections, into {index}\n"),
    ],
)
def test_by_words_alone_the_command_shows_documents_and_sections(
    data: Path, capsys: CaptureFixture[str], summary: str, shown: str
) -> None:
    """Short gives the counts; detailed, the documents by type and the index too; no pieces."""
    write(data / "docs", page("196845", "Kafka"), BODY)
    config = data.parent / "config.toml"
    config.write_text('search_mode = "lexical"\n', encoding="utf-8")
    options = ["--config", str(config), "--data-dir", str(data), "--summary", summary]
    assert main(["index", "--yes", *options]) == 0
    assert capsys.readouterr().out == shown.format(index=(data / "index.sqlite").resolve())


def test_the_command_gives_its_report_index_and_model_as_json(
    data: Path, capsys: CaptureFixture[str]
) -> None:
    """One document: what the build did, the index it wrote, and no model by words alone."""
    write(data / "docs", page("196845", "Kafka"), BODY)
    config = data.parent / "config.toml"
    config.write_text('search_mode = "lexical"\n', encoding="utf-8")
    options = ["--config", str(config), "--data-dir", str(data), "--format", "json"]
    assert main(["index", "--yes", *options]) == 0
    document = json.loads(capsys.readouterr().out)
    assert document["report"]["types"] == {"page": 1}
    assert document["index"] == str((data / "index.sqlite").resolve())
    assert document["model"] is None


def test_line_endings_read_back_as_written(data: Path) -> None:
    """A body holding CR LF line breaks keeps them, and is cut at its headings."""
    body = "# Kafka\r\n\r\nLead.\r\n## Retention\r\nSeven days.\r\n"
    path = write(data / "docs", page("196845", "Kafka"), body)
    build_index(data / "docs", data / "index.sqlite", MOMENT)
    with reading(data / "index.sqlite") as reader:
        (entry,) = reader.entries(paths=[path])
        assert reader.text(path, 0, entry.length) == body
        second = body.index("## ")
        assert reader.bounds(path) == [(0, second), (second, len(body))]


def test_a_refused_file_is_named_and_the_others_indexed(
    data: Path, capsys: CaptureFixture[str]
) -> None:
    """Front matter that the codec refuses, a file not in UTF-8 and a duplicate are skipped.

    Each is the warning index.file_skipped, by its path and why; then index.lacks_files
    warns how many the index lacks. The run's log file holds them all.
    """
    fillers(data / "docs")
    broken = data / "docs" / "confluence" / "ENG" / "1-broken.md"
    broken.write_text("---\ntitle: no other key\n---\n", encoding="utf-8")
    (data / "docs" / "confluence" / "ENG" / "2-latin.md").write_bytes(b"---\ntitle: \xe9\n---\n")
    twin = write(data / "docs", page("900001", "Another title"))
    # Documents come in the order of their paths, so the later of two twins is skipped.
    later = max(twin, location(page("900001", "Lorem 1")))
    status, out, err = index(data, capsys)
    assert status == 1
    assert out.startswith(f"documents: {FILLERS}\n")
    reasons = {
        "confluence/ENG/1-broken.md": "front matter without exactly",
        "confluence/ENG/2-latin.md": "not UTF-8",
        later: "another document has the same source and id",
    }
    assert said(err).count(("warning", "index.file_skipped")) == SKIPPED
    assert ("warning", "index.lacks_files") in said(err)
    assert all(path in err and reason in err for path, reason in reasons.items())
    skipped = logged_as(data.parent / "home", "index.file_skipped")
    assert {line["level"] for line in skipped} == {"warning"}
    assert {str(line["path"]): str(line["reason"]) for line in skipped}.keys() == reasons.keys()
    assert all(str(line["reason"]).startswith(reasons[str(line["path"])]) for line in skipped)
    (lacking,) = logged_as(data.parent / "home", "index.lacks_files")
    assert (lacking["level"], lacking["count"]) == ("warning", SKIPPED)
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
    """Without <data>/docs, nothing is built and the command exits 1, by index.not_built.

    The run's log file holds the error and its reason, with no hint of words alone.
    """
    (data / "docs").rmdir()
    status, _, err = index(data, capsys)
    assert status == 1
    assert ("error", "index.not_built") in said(err)
    assert "no mirror at" in err
    (failed,) = logged_as(data.parent / "home", "index.not_built")
    assert failed["level"] == "error"
    assert str(failed["reason"]).startswith("no mirror at")
    assert "hint" not in failed
    assert list(data.iterdir()) == []


def test_by_words_alone_no_endpoint_is_asked_even_one_elsewhere(
    data: Path, capsys: CaptureFixture[str]
) -> None:
    """The lexical mode never opens the endpoint, so an address off this machine is no matter."""
    write(data / "docs", page("196845", "Kafka"))
    remote = 'search_mode = "lexical"\nembedding_url = "https://embeddings.example/v1"\n'
    assert index(data, capsys, remote)[0] == 0


def test_by_meaning_an_endpoint_elsewhere_needs_the_flag_and_https(
    data: Path, capsys: CaptureFixture[str]
) -> None:
    """Hybrid, an endpoint off this machine: refused without the flag, and over http with it."""
    write(data / "docs", page("196845", "Kafka"))
    remote = 'search_mode = "hybrid"\nembedding_url = "https://embeddings.example/v1"\n'
    status, _, err = index(data, capsys, remote)
    assert status == BAD_SETTINGS
    assert said(err) == [("error", "run.refused")]
    assert "embedding_url: not an address of this machine" in err
    config = data.parent / "config.toml"
    config.write_text(
        'search_mode = "hybrid"\nembedding_url = "http://embeddings.example/v1"\n',
        encoding="utf-8",
    )
    options = ["--config", str(config), "--data-dir", str(data), "--allow-remote-embeddings"]
    assert main(["index", "--yes", *options]) == BAD_SETTINGS
    err = capsys.readouterr().err
    assert said(err) == [("error", "run.refused")]
    assert "over https only" in err
    assert not (data / "index.sqlite").exists()


def test_refused_settings_exit_2(data: Path, capsys: CaptureFixture[str]) -> None:
    """A data directory in a synchronised folder is refused before anything is built."""
    dropbox = data.parent / "home" / "Dropbox" / "data"
    status = main(
        ["index", "--yes", "--config", str(data / "none.toml"), "--data-dir", str(dropbox)]
    )
    assert status == BAD_SETTINGS
    err = capsys.readouterr().err
    assert said(err) == [("error", "settings.refused")]
    assert "data_dir (--data-dir): under a Dropbox folder" in err


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


@pytest.mark.parametrize("schema", ["1", "2"])
def test_an_index_of_an_earlier_schema_is_refused_with_the_command_to_rebuild(
    data: Path, schema: str
) -> None:
    """Plan 006's index, or one built before the build id: never half read."""
    write(data / "docs", page("196845", "Kafka"), BODY)
    build_index(data / "docs", data / "index.sqlite", MOMENT)
    with sqlite3.connect(data / "index.sqlite") as connection:
        connection.execute("UPDATE meta SET value = ? WHERE name = 'schema'", (schema,))
        connection.execute("DELETE FROM meta WHERE name = 'build'")
    connection.close()
    refused = pytest.raises(
        UnavailableIndexError, match="build it with `atlassian-offline-mcp index`"
    )
    with refused, reading(data / "index.sqlite"):
        pass
