"""The index: built from the mirror alone, replaced whole, opened read-only."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import pty
import re
import shutil
import sqlite3
import subprocess
import sys
from contextlib import closing
from copy import replace
from datetime import timedelta
from typing import TYPE_CHECKING

import pytest

from kb_mcp.cli.main import main
from kb_mcp.kernel.names import WORKLOG_TYPES
from kb_mcp.mirror.adapters.markdown import dump
from kb_mcp.mirror.domain.mirror import RELATIONS, ROLES, Link, Mention
from kb_mcp.search.adapters import sqlite_index, vector_cache
from kb_mcp.search.adapters.sqlite_index import SqliteIndex, reading
from kb_mcp.search.app import indexing as indexing_module
from kb_mcp.search.app.indexing import (
    CHANGED_MEANWHILE,
    Embedding,
    Indexing,
    build_index,
    update_index,
)
from kb_mcp.search.domain.indexes import Put, UnavailableIndexError
from kb_mcp.search.domain.people import (
    UNHELD,
    Ambiguity,
    JoinOutcome,
    Person,
    Spelling,
)
from kb_mcp.search.domain.search import WORDS, Filters, sections
from tests.endpoint import nothing_listening, tiny
from tests.mirrors import (
    CREATED,
    FILLERS,
    MOMENT,
    PEOPLE,
    PERSONS,
    fillers,
    issue,
    location,
    page,
    worklog_document,
    write,
)
from tests.test_cli import logged_as
from tests.test_confirmation import read_until
from tests.test_observed import CONTROL, said
from tests.test_people import (
    ALEX,
    ALEX_EXAMPLE,
    ROBIN,
    ROBIN_ALONE,
    ROBIN_OTHER,
    SAM_2,
    SAM_3,
    SAM_ALONE,
    anchored,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable
    from pathlib import Path

    from _pytest.capture import CaptureFixture
    from _pytest.monkeypatch import MonkeyPatch

    from kb_mcp.mirror.domain.mirror import FrontMatter
    from kb_mcp.search.domain.search import Sort

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
    data: Path,
    capsys: CaptureFixture[str],
    settings: str = 'search_mode = "lexical"\n',
    *options: str,
) -> tuple[int, str, str]:
    """Run ``index`` on the data directory, by words alone unless the settings say otherwise.

    Return its exit status, stdout and stderr.
    """
    config = data.parent / "config.toml"
    config.write_text(settings, encoding="utf-8")
    status = main(["index", "--yes", "--config", str(config), "--data-dir", str(data), *options])
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
        (entry,) = reader.indexed_documents(paths=[path])
        assert entry.front == front
        assert (entry.length, entry.sections) == (len(BODY), 2)
        assert reader.text(path, 0, entry.length) == BODY
        assert reader.text(path, 9, 14) == BODY[9:14]
        second = BODY.index("## ")
        assert reader.bounds(path) == [(0, second), (second, len(BODY))]
        summary = reader.index_status()
    assert summary.built_at.tzinfo is not None
    assert (summary.types, summary.spaces, summary.projects) == (
        {"issue": 1, "page": 1},
        {"ENG": 1},
        {"PROJ": 1},
    )


# What the first index of a mirror of one page says: none to update, so built whole.
FIRST_SHORT = (
    "documents: 1\nsections: 2\ncopied: 0\nadded: 1\nreplaced: 0\nremoved: 0\nskipped: 0\n"
    "rebuilt whole: unavailable\n"
)
FIRST_DETAILED = (
    "rebuilt {index} whole, there being none that this version reads:"
    " 1 documents (page: 1), 2 sections\n"
)


@pytest.mark.parametrize(
    ("summary", "shown"), [("short", FIRST_SHORT), ("detailed", FIRST_DETAILED)]
)
def test_by_words_alone_the_command_shows_documents_and_sections(
    data: Path, capsys: CaptureFixture[str], summary: str, shown: str
) -> None:
    """Short gives the counts; detailed, the documents by type and the index too; no chunks."""
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


def test_embed_needs_the_endpoint_and_index_never_asks_it(
    data: Path, capsys: CaptureFixture[str]
) -> None:
    """No endpoint answering: ``index`` never asks it, and ``embed`` exits 1 saying why.

    Whatever the mode says, as neither reads it to decide: plan 031, criterion 5.
    """
    write(data / "docs", page("196845", "Kafka"), BODY)
    config = data.parent / "config.toml"
    with nothing_listening() as url:
        status, out, _ = index(data, capsys, f"embedding_url = {json.dumps(url)}\n")
        assert (status, out) == (0, FIRST_SHORT)
        options = ["--yes", "--config", str(config), "--data-dir", str(data)]
        assert main(["embed", *options]) == 1
    assert "no answer from the embedding endpoint" in capsys.readouterr().err


def test_line_endings_read_back_as_written(data: Path) -> None:
    """A body holding CR LF line breaks keeps them, and is cut at its headings."""
    body = "# Kafka\r\n\r\nLead.\r\n## Retention\r\nSeven days.\r\n"
    path = write(data / "docs", page("196845", "Kafka"), body)
    build_index(data / "docs", data / "index.sqlite", MOMENT)
    with reading(data / "index.sqlite") as reader:
        (entry,) = reader.indexed_documents(paths=[path])
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
        assert reader.index_status().skipped == SKIPPED


def test_a_stray_markdown_file_is_read_and_reported(
    data: Path, capsys: CaptureFixture[str]
) -> None:
    """A Markdown file under docs/ that no source wrote is read, and skipped, said why.

    One under assets/, or under a name beginning with ``_``, is no document, and not read.
    """
    write(data / "docs", page("196845", "Kafka"), BODY)
    for name in ("x.md", "assets/x.md", "confluence/QM/_x.md"):
        (data / "docs" / name).parent.mkdir(parents=True, exist_ok=True)
        (data / "docs" / name).write_text("", encoding="utf-8")
    status, out, err = index(data, capsys)
    assert status == 1
    assert out.startswith("documents: 1\n")
    assert said(err).count(("warning", "index.file_skipped")) == 1
    skipped = logged_as(data.parent / "home", "index.file_skipped")
    assert [(line["path"], line["reason"]) for line in skipped] == [("x.md", "no front matter")]


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
        assert reader.index_status().built_at == MOMENT


def test_a_build_leaves_no_temporary_file(data: Path, capsys: CaptureFixture[str]) -> None:
    """Built, then updated, the data directory holds the mirror, one index and its lock.

    No journal, no write-ahead log, no build file.
    """
    write(data / "docs", page("196845", "Kafka"))
    assert index(data, capsys)[0] == 0
    write(data / "docs", page("196846", "Another"))
    assert index(data, capsys)[0] == 0
    names = ["docs", "index.sqlite", "index.sqlite.lock"]
    assert sorted(path.name for path in data.iterdir()) == names


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


def test_a_database_error_is_a_failure_and_keeps_the_old_index(
    data: Path, capsys: CaptureFixture[str], monkeypatch: MonkeyPatch
) -> None:
    """The database's error while building, as of a full disk, simulated: exit 1, said.

    The index in place stays as it was, and no traceback is written.
    """
    write(data / "docs", page("196845", "Kafka"))
    assert index(data, capsys)[0] == 0
    before = (data / "index.sqlite").read_bytes()
    write(data / "docs", page("196846", "Another"))

    def full(*_: object) -> None:
        message = "database or disk is full"
        raise sqlite3.OperationalError(message)

    monkeypatch.setattr(sqlite_index.Writer, "add", full)
    status, _, err = index(data, capsys)
    assert status == 1
    assert ("error", "index.not_built") in said(err)
    assert "Traceback" not in err
    assert (data / "index.sqlite").read_bytes() == before


def test_a_bug_in_the_database_s_use_is_not_taken_for_a_failure_to_write(
    data: Path, monkeypatch: MonkeyPatch
) -> None:
    """A ProgrammingError is a bug: it propagates, rather than being said as not built."""

    def misused(*_: object) -> None:
        message = "misused cursor"
        raise sqlite3.ProgrammingError(message)

    write(data / "docs", page("196845", "Kafka"))
    monkeypatch.setattr(sqlite_index.Writer, "add", misused)
    indexing = Indexing(
        docs=data / "docs",
        index=data / "index.sqlite",
        vectors=data / "vectors.sqlite",
        evaluation_indexes=data / "eval" / "indexes",
        aliases=data / "aliases.toml",
        model="tiny",
        chunking="sections",
        endpoint=None,
    )
    with pytest.raises(sqlite3.ProgrammingError):
        update_index(indexing, MOMENT)


@pytest.mark.parametrize("mode", ["lexical", "hybrid"])
def test_by_words_alone_no_endpoint_is_asked_even_one_elsewhere(
    data: Path, capsys: CaptureFixture[str], mode: str
) -> None:
    """``index`` never opens the endpoint, so an address off this machine is no matter."""
    write(data / "docs", page("196845", "Kafka"))
    remote = f'search_mode = "{mode}"\nembedding_url = "https://embeddings.example/v1"\n'
    assert index(data, capsys, remote)[0] == 0


@pytest.mark.parametrize("mode", ["hybrid", "lexical"])
def test_embed_with_an_endpoint_elsewhere_needs_the_flag_and_https(
    data: Path, capsys: CaptureFixture[str], mode: str
) -> None:
    """An endpoint off this machine: refused without the flag, over http with it, in any mode."""
    write(data / "docs", page("196845", "Kafka"))
    config = data.parent / "config.toml"
    settings = f'search_mode = "{mode}"\nembedding_url = "{{}}://embeddings.example/v1"\n'
    config.write_text(settings.format("https"), encoding="utf-8")
    options = ["--yes", "--config", str(config), "--data-dir", str(data)]
    assert main(["embed", *options]) == BAD_SETTINGS
    err = capsys.readouterr().err
    assert said(err) == [("error", "run.refused")]
    assert "embedding_url: not an address of this machine" in err
    config.write_text(settings.format("http"), encoding="utf-8")
    assert main(["embed", *options, "--allow-remote-embeddings"]) == BAD_SETTINGS
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
        assert reader.index_status().types == {"page": 1}
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            opened[0].execute("CREATE TABLE written (value)")


def test_no_index_or_another_file_is_unavailable(data: Path) -> None:
    """A missing index, or a file that is not one, names the command that builds it."""
    with (
        pytest.raises(UnavailableIndexError, match=r"^no index at .*kb-mcp index"),
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
        assert reader.index_status().spaces == {"ENG": 1, "OPS": 1}


@pytest.fixture
def people(data: Path) -> Path:
    """Index PEOPLE, each document holding the word lorem; give the index's path."""
    for front in PEOPLE:
        write(data / "docs", front)
    build_index(data / "docs", data / "index.sqlite", MOMENT)
    return data / "index.sqlite"


@pytest.mark.parametrize(
    ("filters", "expected"),
    [
        (Filters(issue_type="Bug"), ["PROJ-1"]),
        (Filters(author=anchored("name\nbo sample")), ["196845", "PROJ-1"]),
        (Filters(assignee=anchored("name\nada example")), ["PROJ-1", "PROJ-3"]),
        (Filters(created_after=CREATED), ["PROJ-1", "PROJ-3"]),
        (Filters(created_before=CREATED), ["196845", "PROJ-2"]),
        (Filters(author=anchored("name\nada example"), created_after=CREATED), []),
    ],
)
def test_people_and_the_created_range_narrow_each_list(
    people: Path, filters: Filters, expected: list[str]
) -> None:
    """A listing, a search by words and a page of the newest narrow alike.

    A person by their id, as plan 043 gives it: these, by name alone. created_after
    keeps a document created at that moment; created_before does not.
    """
    paths = {location(front): front.key or front.id for front in PEOPLE}
    with reading(people) as reader:
        listed = [entry.front.key or entry.front.id for entry in reader.listing(filters)]
        scored, _ = reader.scores('"lorem"', filters)
        total, recent = reader.recent(filters, "created", 0, 10)
    assert listed == expected
    assert sorted(paths[path] for path in scored) == sorted(expected)
    assert (total, sorted(entry.path for entry in recent)) == (len(expected), sorted(scored))


def test_issue_types_authors_and_assignees_are_values_most_used_first(people: Path) -> None:
    """Each value that documents have, with its count; a page adds no issue type nor assignee."""
    with reading(people) as reader:
        assert reader.values("issue_type") == [("Bug", 1), ("Story", 1), ("Task", 1)]
        assert reader.values("author") == [("Bo Sample", 2), ("A Person", 1), ("Ada Example", 1)]
        assert reader.values("assignee") == [("Ada Example", 2), ("Hélène Example", 1)]


@pytest.mark.parametrize(
    ("by", "expected"),
    [
        ("created", ["PROJ-3", "PROJ-1", "PROJ-2", "196845"]),
        ("updated", ["PROJ-2", "PROJ-3", "PROJ-1", "196845"]),
    ],
)
def test_the_newest_are_listed_by_either_date(people: Path, by: Sort, expected: list[str]) -> None:
    """Newest first by the date asked, ties to the newest update; a page from an offset."""
    with reading(people) as reader:
        total, listed = reader.recent(Filters(), by, 0, 10)
        assert (total, [entry.front.key or entry.front.id for entry in listed]) == (4, expected)
        _, second = reader.recent(Filters(), by, 1, 2)
    assert [entry.front.key or entry.front.id for entry in second] == expected[1:3]


def test_a_score_by_words_holds_the_created_date(people: Path) -> None:
    """What a sort by created date reads, as the front matter gave it."""
    with reading(people) as reader:
        scored, _ = reader.scores('"lorem"', Filters())
    assert {path: score.created for path, score in scored.items()} == {
        location(front): front.created for front in PEOPLE
    }


# An issue with an author, a creator and two commenters, one of whom commented twice.
COMMENTED = issue(
    "PROJ-9",
    "Broker rebalance",
    people=(
        Mention(role="author", name="A Person", account="account-1"),
        Mention(role="creator", name="Another Person", account="account-2"),
        Mention(
            role="commenter",
            name="Another Person",
            account="account-2",
            at=(CREATED, CREATED + timedelta(hours=1)),
        ),
        Mention(
            role="commenter",
            name="A Person",
            account="account-1",
            at=(CREATED + timedelta(hours=2),),
        ),
    ),
)


def test_people_are_a_row_per_person_and_role_and_a_commenter_s_per_comment(data: Path) -> None:
    """The side table filters; the documents' own column gives the front matter back whole."""
    path = write(data / "docs", COMMENTED)
    build_index(data / "docs", data / "index.sqlite", MOMENT)
    with closing(sqlite3.connect(data / "index.sqlite")) as connection:
        rows = connection.execute("SELECT role, name, account, at FROM people ORDER BY rowid")
        people = rows.fetchall()
        columns = {row[1] for row in connection.execute("PRAGMA table_info(documents)")}
    assert people == [
        ("author", "A Person", "account-1", None),
        ("creator", "Another Person", "account-2", None),
        ("commenter", "Another Person", "account-2", "2026-10-25T00:00:00+00:00"),
        ("commenter", "Another Person", "account-2", "2026-10-25T01:00:00+00:00"),
        ("commenter", "A Person", "account-1", "2026-10-25T02:00:00+00:00"),
    ]
    assert "people" in columns
    assert not {"author", "assignee"} & columns
    with reading(data / "index.sqlite") as reader:
        (entry,) = reader.indexed_documents(paths=[path])
    assert entry.front == COMMENTED


def test_people_are_not_embedded_so_a_rebuild_with_new_people_embeds_nothing(data: Path) -> None:
    """A chunk embeds its document's title, breadcrumb and text alone, never its people."""
    write(data / "docs", issue("PROJ-9", "Broker rebalance"))
    embedding = Embedding(tiny(), data / "v.db")
    first = build_index(data / "docs", data / "index.sqlite", MOMENT, embedding)
    write(data / "docs", COMMENTED)
    again = build_index(data / "docs", data / "index.sqlite", MOMENT, embedding)
    assert first.embedded > 0
    assert again.embedded == 0


# A meeting and its transcript of the work log, each naming the other, with their
# participants: the meeting's as written, the transcript's speakers.
MEETING = replace(
    page("m-20261027-payments-stand-up", "Payments stand-up"),
    source="worklog",
    type="meeting",
    space=None,
    version=None,
    revision="0123456789abcdef",
    people=(
        Mention(role="participant", name="Alex Example"),
        Mention(role="participant", name="Kim (not in the header)"),
    ),
    links=(Link(relation="transcript", ref="t-20261027-meeting-1"),),
)
TRANSCRIPT = replace(
    MEETING,
    type="transcript",
    id="t-20261027-meeting-1",
    title="Meeting 1",
    people=(
        Mention(role="participant", name="Alex Example"),
        Mention(role="participant", name="Sam Sample"),
    ),
    links=(Link(relation="summary", ref="m-20261027-payments-stand-up"),),
)


def test_links_and_participants_read_back_and_participants_are_rows_of_people(
    data: Path,
) -> None:
    """A row gives the front matter back whole, links included; each participant is a row."""
    paths = [write(data / "docs", front) for front in (MEETING, TRANSCRIPT)]
    build_index(data / "docs", data / "index.sqlite", MOMENT)
    with closing(sqlite3.connect(data / "index.sqlite")) as connection:
        rows = connection.execute(
            "SELECT d.id, p.role, p.name, p.account, p.at"
            " FROM people p JOIN documents d ON d.rowid = p.document ORDER BY p.rowid"
        )
        people = rows.fetchall()
    assert people == [
        ("m-20261027-payments-stand-up", "participant", "Alex Example", None, None),
        ("m-20261027-payments-stand-up", "participant", "Kim (not in the header)", None, None),
        ("t-20261027-meeting-1", "participant", "Alex Example", None, None),
        ("t-20261027-meeting-1", "participant", "Sam Sample", None, None),
    ]
    with reading(data / "index.sqlite") as reader:
        fronts = {entry.path: entry.front for entry in reader.indexed_documents(paths=paths)}
    assert fronts == dict(zip(paths, (MEETING, TRANSCRIPT), strict=True))


@pytest.fixture
def persons(data: Path) -> Path:
    """Index PERSONS, the made-up people of three sources; give the index's path."""
    for front in PERSONS:
        write(data / "docs", front)
    build_index(data / "docs", data / "index.sqlite", MOMENT)
    return data / "index.sqlite"


# The persons of PERSONS, by id, each named and spelt as plan 043's rules give them by
# hand. Robin's account is named as on PAY-1, its newest document; a name alone, by its
# spellings' first in the order of the files, all being as frequent: the review's Alex
# Example, the stand-up's Sam Sample.
ROBIN_SPELT = (
    Spelling(name="Robin", name_key="robin", how="meeting"),
    Spelling(name="Robin Example", name_key="robin example", how="account"),
    Spelling(name="Robin Example", name_key="robin example", how="name"),
    Spelling(name="Robin Sample", name_key="robin sample", how="account"),
    Spelling(name="robin  EXAMPLE", name_key="robin example", how="name"),
)
JOINED = {
    ROBIN: ("Robin Sample", ROBIN_SPELT),
    SAM_2: ("Sam Sample", (Spelling(name="Sam Sample", name_key="sam sample", how="account"),)),
    SAM_3: ("Sam Sample", (Spelling(name="Sam Sample", name_key="sam sample", how="account"),)),
    SAM_ALONE: (
        "Sam Sample",
        (
            Spelling(name="Sam", name_key="sam", how="meeting"),
            Spelling(name="Sam Sample", name_key="sam sample", how="name"),
        ),
    ),
    ALEX_EXAMPLE: (
        "Alex Example",
        (
            Spelling(name="Alex", name_key="alex", how="meeting"),
            Spelling(name="Alex Example", name_key="alex example", how="name"),
            Spelling(name="Alex Example (not in the header)", name_key="alex example", how="name"),
        ),
    ),
    ALEX: ("Alex", (Spelling(name="Alex", name_key="alex", how="name"),)),
    ROBIN_ALONE: ("Robin", (Spelling(name="Robin", name_key="robin", how="name"),)),
    ROBIN_OTHER: (
        "Robin Other",
        (Spelling(name="Robin Other", name_key="robin other", how="name"),),
    ),
}
# The person of each document's people, by the document's key or id and the name.
PERSON_OF = {
    ("300001", "Robin Example"): ROBIN,
    ("PAY-1", "Sam Sample"): SAM_2,
    ("PAY-1", "Robin Sample"): ROBIN,
    ("PAY-2", "Sam Sample"): SAM_3,
    ("PAY-2", "Robin Example"): ROBIN,
    ("m-20261020-planning", "Robin Example"): ROBIN,
    ("m-20261020-planning", "Robin Other"): ROBIN_OTHER,
    ("m-20261020-review", "Robin Example"): ROBIN,
    ("m-20261020-review", "Alex Example"): ALEX_EXAMPLE,
    ("m-20261020-stand-up", "robin  EXAMPLE"): ROBIN,
    ("m-20261020-stand-up", "Sam Sample"): SAM_ALONE,  # of two accounts' name: none
    ("m-20261020-stand-up", "Alex Example (not in the header)"): ALEX_EXAMPLE,
    ("t-20261020-1", "Robin"): ROBIN,  # by the review
    ("t-20261020-1", "Alex"): ALEX_EXAMPLE,  # by the review
    ("t-20261020-2", "Robin"): ROBIN_ALONE,  # the planning has two Robins: none
    ("t-20261020-3", "Sam"): SAM_ALONE,  # by the stand-up
    ("t-20261021-1", "Robin"): ROBIN_ALONE,
    ("t-20261021-1", "Alex"): ALEX,
    ("t-20261021-2", "Alex"): ALEX,
}


def joined_rows(
    index: Path,
) -> tuple[list[tuple[str, ...]], list[tuple[str, ...]], dict[tuple[str, str], str]]:
    """Read the index's persons and their names, in order, and each person of people.

    The people's by their document's key or id and their name, as PERSON_OF has them.
    """
    with closing(sqlite3.connect(index)) as connection:
        persons = connection.execute("SELECT id, name FROM persons ORDER BY id").fetchall()
        names = connection.execute(
            "SELECT person, name, key, joined FROM person_names ORDER BY 1, 2, 3, 4"
        ).fetchall()
        people = connection.execute(
            "SELECT coalesce(d.key, d.id), p.name, p.person"
            " FROM people p JOIN documents d ON d.rowid = p.document"
        ).fetchall()
    return persons, names, {(document, name): person for document, name, person in people}


def test_every_row_of_people_has_its_person_as_the_rules_join_them(persons: Path) -> None:
    """Plan 043, criteria 2 and 4, through the index: no row of people is left without one.

    Each person once, with the name it is served by, and each spelling with how it joined.
    """
    with closing(sqlite3.connect(persons)) as connection:
        rows = connection.execute("SELECT count(*), count(person) FROM people").fetchone()
    assert rows == (len(PERSON_OF) + 1, len(PERSON_OF) + 1)  # a row per comment of PAY-2's
    held, names, person_of = joined_rows(persons)
    assert held == [(person, name) for person, (name, _) in sorted(JOINED.items())]
    assert names == [
        (person, spelling.name, spelling.name_key, spelling.how)
        for person, (_, spellings) in sorted(JOINED.items())
        for spelling in spellings
    ]
    assert person_of == PERSON_OF


def test_the_report_counts_the_persons_and_gives_what_the_join_left_apart(data: Path) -> None:
    """Two names could be several persons; without aliases, none is unused."""
    for front in PERSONS:
        write(data / "docs", front)
    report = build_index(data / "docs", data / "index.sqlite", MOMENT)
    assert report.persons == JoinOutcome(
        count=len(JOINED),
        ambiguous=(
            Ambiguity(name="Robin", persons=frozenset({ROBIN, ROBIN_OTHER})),
            Ambiguity(name="Sam Sample", persons=frozenset({SAM_2, SAM_3})),
        ),
        unused=(),
    )


def test_aliases_join_names_alone_and_one_that_changes_nothing_is_reported(data: Path) -> None:
    """With the alias of Robin to Robin Example, every Robin without an account is Robin's.

    The planning's Robin is no longer ambiguous, and Robin by name alone is gone; an
    alias whose key no name holds changes nothing, and is given back.
    """
    for front in PERSONS:
        write(data / "docs", front)
    aliases = {"Robin": "Robin Example", "Jo Placeholder": "Robin Example"}
    report = build_index(data / "docs", data / "index.sqlite", MOMENT, aliases=aliases)
    assert report.persons.count == len(JOINED) - 1
    assert [ambiguity.name for ambiguity in report.persons.ambiguous] == ["Sam Sample"]
    unused = [(alias.name, alias.reason) for alias in report.persons.unused]
    assert unused == [("Jo Placeholder", UNHELD)]
    held, names, person_of = joined_rows(data / "index.sqlite")
    assert ROBIN_ALONE not in {person for person, _ in held}
    assert (ROBIN, "Robin", "robin", "alias") in names
    assert person_of == PERSON_OF | {
        ("t-20261020-2", "Robin"): ROBIN,
        ("t-20261021-1", "Robin"): ROBIN,
        ("t-20261020-1", "Robin"): ROBIN,
    }


def test_a_transcript_s_meeting_is_of_the_work_log_alone(data: Path) -> None:
    """A page whose id is the review's is not the review: its Robin Third makes no Robin."""
    for front in PERSONS:
        write(data / "docs", front)
    namesake = page(
        "m-20261020-review",
        "Review",
        people=(Mention(role="author", name="Robin Third", account="acct-0004"),),
    )
    write(data / "docs", namesake)
    build_index(data / "docs", data / "index.sqlite", MOMENT)
    assert joined_rows(data / "index.sqlite")[2][("t-20261020-1", "Robin")] == ROBIN


def test_a_transcript_s_summary_of_no_meeting_names_no_meeting(data: Path) -> None:
    """Two transcripts whose summaries link each other, as a hand-edited mirror may.

    Neither link names a meeting: the build completes, and their speakers are persons by
    name alone, as in a transcript that links nothing.
    """
    for front in PERSONS:
        write(data / "docs", front)
    write(
        data / "docs",
        worklog_document("transcript", "t-20261022-1", "Loop", ("Alex",), "t-20261022-2"),
    )
    write(
        data / "docs",
        worklog_document("transcript", "t-20261022-2", "Loop", ("Alex",), "t-20261022-1"),
    )
    report = build_index(data / "docs", data / "index.sqlite", MOMENT)
    assert report.skipped == []
    assert joined_rows(data / "index.sqlite")[2] == PERSON_OF | {
        ("t-20261022-1", "Alex"): ALEX,
        ("t-20261022-2", "Alex"): ALEX,
    }


def test_a_transcript_s_meetings_are_found_by_source_and_id_not_by_scanning(
    persons: Path,
) -> None:
    """The join reads each transcript's links, then each meeting by its key.

    Its work then grows with the links, where a search of a source's documents for each
    of a source's documents grows with their square: a build of 20,000 issues took
    tens of seconds so.
    """
    with closing(sqlite3.connect(persons)) as connection:
        plan_query = connection.execute(
            f"EXPLAIN QUERY PLAN {sqlite_index.SUMMARY_LINKS}"
        ).fetchall()
    steps = [row[3] for row in plan_query]
    meeting = [step for step in steps if step.startswith(("SCAN m", "SEARCH m "))]
    assert len(meeting) == 1
    assert meeting[0].startswith("SEARCH m USING ")
    assert meeting[0].endswith("(source=? AND id=?)")


def test_a_person_is_found_by_the_key_of_any_of_its_names(persons: Path) -> None:
    """Every person holding the key, in order; none for a key that no one holds.

    Given how a name joined, those of the names that joined so alone.
    """
    with reading(persons) as reader:
        assert reader.persons("sam sample") == sorted([SAM_2, SAM_3, SAM_ALONE])
        assert reader.persons("robin") == sorted([ROBIN, ROBIN_ALONE])
        assert reader.persons("robin example") == [ROBIN]  # of three spellings, once
        assert reader.persons("Robin Sample") == []  # a name, not its key
        assert reader.persons("nobody") == []
        assert reader.persons("sam sample", "account") == sorted([SAM_2, SAM_3])
        assert reader.persons("robin", "account") == []  # by meeting and by name alone


def test_a_person_s_documents_are_counted_by_role_and_by_source(persons: Path) -> None:
    """Robin: a page authored, an issue created, one commented, four meetings attended.

    The most first, ties by name; the newest of them is PAY-1. An id that no person has
    gives none.
    """
    with reading(persons) as reader:
        robin = reader.person(ROBIN)
        assert reader.person("p-0123456789abcdef") is None
    assert robin is not None
    assert robin.person == Person(id=ROBIN, name="Robin Sample", spellings=ROBIN_SPELT)
    assert list(robin.roles.items()) == [
        ("participant", 4),
        ("author", 1),
        ("commenter", 1),
        ("creator", 1),
    ]
    assert list(robin.sources.items()) == [("worklog", 4), ("jira", 2), ("confluence", 1)]
    assert robin.last == MOMENT + timedelta(days=1)


def test_a_rebuild_embeds_nothing_with_or_without_new_aliases(data: Path) -> None:
    """Plan 043, criterion 4: persons are not embedded, so aliases that move names embed none."""
    for front in PERSONS:
        write(data / "docs", front)
    embedding = Embedding(tiny(), data / "v.db")
    first = build_index(data / "docs", data / "index.sqlite", MOMENT, embedding)
    again = build_index(data / "docs", data / "index.sqlite", MOMENT, embedding)
    aliased = build_index(
        data / "docs", data / "index.sqlite", MOMENT, embedding, {"Robin": "Robin Example"}
    )
    assert first.embedded > 0
    assert (again.embedded, aliased.embedded) == (0, 0)
    assert (again.persons.count, aliased.persons.count) == (len(JOINED), len(JOINED) - 1)


@pytest.mark.parametrize("schema", ["1", "2", "3", "4", "5"])
def test_an_index_of_an_earlier_schema_is_refused_with_the_command_to_rebuild(
    data: Path, schema: str
) -> None:
    """An index of plan 006, or built before the build id, people, links or persons.

    The commands named write the mirror's files before the index, as 041 changed them:
    ``prepare``, then ``index``, then ``embed``.
    """
    write(data / "docs", page("196845", "Kafka"), BODY)
    build_index(data / "docs", data / "index.sqlite", MOMENT)
    with sqlite3.connect(data / "index.sqlite") as connection:
        connection.execute("UPDATE meta SET value = ? WHERE name = 'schema'", (schema,))
        connection.execute("DELETE FROM meta WHERE name = 'build'")
    connection.close()
    refused = pytest.raises(
        UnavailableIndexError,
        match=(
            "rebuild it with `kb-mcp prepare`, which writes the mirror again first,"
            " then `kb-mcp index`, then `kb-mcp embed`"
        ),
    )
    with refused, reading(data / "index.sqlite"):
        pass


def test_an_index_of_schema_6_is_refused_with_index_alone(data: Path) -> None:
    """Plan 054: the mirror's files of schema 6 are read as they are, so no prepare first."""
    write(data / "docs", page("196845", "Kafka"), BODY)
    build_index(data / "docs", data / "index.sqlite", MOMENT)
    with sqlite3.connect(data / "index.sqlite") as connection:
        connection.execute("UPDATE meta SET value = '6' WHERE name = 'schema'")
    connection.close()
    with pytest.raises(UnavailableIndexError) as refused, reading(data / "index.sqlite"):
        pass
    assert str(refused.value).endswith("rebuild it with `kb-mcp index`, then `kb-mcp embed`")
    assert "prepare" not in str(refused.value)


def child_environment(data: Path) -> dict[str, str]:
    """Give a child its scratch home, the data directory and the lexical mode, 200 columns wide."""
    return {
        "HOME": str(data.parent / "home"),
        "PATH": os.environ["PATH"],
        "COLUMNS": "200",
        "KB_MCP_DATA_DIR": str(data),
        "KB_MCP_SEARCH_MODE": "lexical",
    }


def to_the_end(controller: int, child: subprocess.Popen[bytes]) -> tuple[str, bytes]:
    """Give what a child sent its terminal until it ended, controls taken out; then its stdout."""
    shown = read_until(controller, b"\0")  # never sent: read until the child ends
    out, _ = child.communicate()
    return CONTROL.sub("", shown.decode()), out


def test_progress_is_bars_on_a_terminal_events_in_the_file_piped_and_nothing_quiet(
    data: Path,
) -> None:
    """Stdout piped throughout, the same document each time, by plan 016's criterion 12.

    Piped, stderr has no bar, and the log file holds the events progress; on a terminal,
    the files' bar shows them all done, with the time elapsed and the time left; with
    -q, the terminal is sent no bar. Each run reads every file, rebuilding whole.
    """
    fillers(data / "docs")
    piped = subprocess.run(
        [sys.executable, "-m", "kb_mcp", "index", "--yes", "--rebuild", "--format", "json"],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        env=child_environment(data),
        cwd=data.parent,
        check=False,
    )
    assert piped.returncode == 0
    assert "━" not in piped.stderr.decode()
    assert b"\x1b" not in piped.stderr
    *_, last = logged_as(data.parent / "home", "progress")
    assert (last["task"], last["done"], last["total"]) == ("files", FILLERS, FILLERS)
    controller, terminal = pty.openpty()
    with subprocess.Popen(
        [sys.executable, "-m", "kb_mcp", "index", "--yes", "--rebuild", "--format", "json"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=terminal,
        env=child_environment(data),
        cwd=data.parent,
    ) as child:
        os.close(terminal)
        shown, out = to_the_end(controller, child)
    os.close(controller)
    assert child.returncode == 0
    clock = "[0-9]+:[0-9]{2}:[0-9]{2}"
    assert re.search(rf"files [━╸╺ ]+ {FILLERS}/{FILLERS} {clock} {clock} ", shown)
    controller, terminal = pty.openpty()
    with subprocess.Popen(
        [sys.executable, "-m", "kb_mcp", "index", "--yes", "--rebuild", "--format", "json", "-q"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=terminal,
        env=child_environment(data),
        cwd=data.parent,
    ) as child:
        os.close(terminal)
        shown, quiet = to_the_end(controller, child)
    os.close(controller)
    assert child.returncode == 0
    assert "━" not in shown
    assert piped.stdout == out == quiet
    assert json.loads(out)["report"]["types"] == {"page": FILLERS}


def test_an_index_that_cannot_be_written_exits_1_and_keeps_the_one_in_place(
    data: Path, capsys: CaptureFixture[str], monkeypatch: MonkeyPatch
) -> None:
    """The database's error while indexing, as of a full disk, simulated: said, nothing lost."""

    def full(*_: object) -> None:
        message = "database or disk is full"
        raise sqlite3.OperationalError(message)

    write(data / "docs", page("196845", "Kafka"), BODY)
    assert index(data, capsys)[0] == 0
    before = (data / "index.sqlite").read_bytes()
    write(data / "docs", page("196846", "Another"), BODY)
    monkeypatch.setattr(sqlite_index.Writer, "add", full)
    status, _, err = index(data, capsys)
    assert status == 1
    assert ("error", "index.not_built") in said(err)
    assert "database or disk is full" in err
    assert (data / "index.sqlite").read_bytes() == before


def rows_of(index: Path, query: str) -> list[tuple[object, ...]]:
    """Read rows of an index as they are written."""
    with closing(sqlite3.connect(index)) as connection:
        return connection.execute(query).fetchall()


def digest_of(file: Path) -> str:
    """Give the digest of a file as the plan defines it: the SHA-256 of its bytes."""
    return hashlib.sha256(file.read_bytes()).hexdigest()


def test_a_document_records_the_digest_of_its_file_s_bytes(data: Path) -> None:
    """Its line endings as written, its accents as the bytes that encode them."""
    path = write(data / "docs", page("196845", "Kafka"), "# Kafka\r\n\r\nDélai.\r\n")
    build_index(data / "docs", data / "index.sqlite", MOMENT)
    assert rows_of(data / "index.sqlite", "SELECT path, digest FROM documents") == [
        (path, digest_of(data / "docs" / path))
    ]


@pytest.mark.skipif(os.geteuid() == 0, reason="root reads a file whatever its mode")
def test_each_file_skipped_is_recorded_with_its_digest_and_why(data: Path) -> None:
    """Refused, not in UTF-8, or a duplicate, by its digest; one that cannot be read has none."""
    docs = data / "docs"
    kept = write(docs, page("900001", "First"))
    twin = write(docs, page("900001", "Second"))
    broken = docs / "confluence" / "ENG" / "1-broken.md"
    broken.write_text("---\ntitle: no other key\n---\n", encoding="utf-8")
    latin = docs / "confluence" / "ENG" / "2-latin.md"
    latin.write_bytes(b"---\ntitle: \xe9\n---\n")
    closed = docs / "confluence" / "ENG" / "3-closed.md"
    closed.write_text("---\n", encoding="utf-8")
    closed.chmod(0)
    report = build_index(docs, data / "index.sqlite", MOMENT)
    rows = rows_of(data / "index.sqlite", "SELECT path, digest, reason FROM skipped ORDER BY path")
    assert [(path, digest) for path, digest, _ in rows] == [
        ("confluence/ENG/1-broken.md", digest_of(broken)),
        ("confluence/ENG/2-latin.md", digest_of(latin)),
        ("confluence/ENG/3-closed.md", None),
        (twin, digest_of(docs / twin)),
    ]
    reasons = [str(reason) for _, _, reason in rows]
    assert reasons[0].startswith("front matter without exactly the mirror's keys")
    assert reasons[1:] == [
        "not UTF-8",
        "not readable (PermissionError)",
        "another document has the same source and id",
    ]
    assert sorted(report.skipped) == [(path, reason) for path, _, reason in rows]
    assert rows_of(data / "index.sqlite", "SELECT path FROM documents") == [(kept,)]
    with reading(data / "index.sqlite") as reader:
        assert reader.index_status().skipped == len(rows)


@pytest.mark.skipif(sys.platform == "darwin", reason="APFS refuses names that are not UTF-8")
def test_a_file_named_in_bytes_that_are_not_utf_8_is_indexed_or_skipped_all_the_same(
    data: Path, capsys: CaptureFixture[str]
) -> None:
    """The index holds text: its name goes in ASCII escapes, two such names staying two."""
    folder = data / "docs" / "confluence" / "ENG"
    folder.mkdir(parents=True)
    (folder / os.fsdecode(b"caf\xe9.md")).write_text("not a document\n", encoding="utf-8")
    good = dump(page("196845", "Kafka"), BODY)
    (folder / os.fsdecode(b"th\xe9.md")).write_text(good, encoding="utf-8")
    status, out, err = index(data, capsys)
    assert status == 1
    assert out.startswith("documents: 1\n")
    assert ("warning", "index.file_skipped") in said(err)
    assert rows_of(data / "index.sqlite", "SELECT path, reason FROM skipped") == [
        ("confluence/ENG/caf\\xe9.md", "no front matter")
    ]
    assert rows_of(data / "index.sqlite", "SELECT path FROM documents") == [
        ("confluence/ENG/th\\xe9.md",)
    ]


def test_a_build_with_no_file_skipped_records_none(data: Path) -> None:
    """The table is there, and empty, as the count says."""
    write(data / "docs", page("196845", "Kafka"))
    build_index(data / "docs", data / "index.sqlite", MOMENT)
    assert rows_of(data / "index.sqlite", "SELECT * FROM skipped") == []
    with reading(data / "index.sqlite") as reader:
        assert reader.index_status().skipped == 0


def test_a_build_records_its_words_and_what_the_alias_file_means(
    data: Path, capsys: CaptureFixture[str]
) -> None:
    """The names and values, in their order: no other change of the file moves the row."""
    write(data / "docs", page("196845", "Kafka"))

    def recorded(text: str | None) -> tuple[object, ...]:
        if text is None:
            (data / "aliases.toml").unlink(missing_ok=True)
        else:
            (data / "aliases.toml").write_text(text, encoding="utf-8")
        assert index(data, capsys)[0] == 0
        ((words, aliases),) = rows_of(
            data / "index.sqlite",
            "SELECT (SELECT value FROM meta WHERE name = 'words'),"
            " (SELECT value FROM meta WHERE name = 'aliases')",
        )
        assert words == WORDS
        return aliases

    none = recorded(None)
    build_index(data / "docs", data / "evaluated.sqlite", MOMENT)
    assert rows_of(data / "evaluated.sqlite", "SELECT value FROM meta WHERE name = 'aliases'") == [
        (none,)
    ]
    assert recorded("") == none
    assert recorded("# Nobody yet.\n") == none
    one = recorded('"Sam" = "Sam Sample"\n"Kim" = "Kim Example"\n')
    assert one != none
    assert recorded('# Who is who.\n\nSam = "Sam Sample"\n\nKim  =  "Kim Example"\n') == one
    assert recorded('"Kim" = "Kim Example"\n"Sam" = "Sam Sample"\n') != one
    assert recorded('"Sam" = "Sam Example"\n"Kim" = "Kim Example"\n') != one
    assert recorded('"Samuel" = "Sam Sample"\n"Kim" = "Kim Example"\n') != one


def test_an_index_built_before_digests_is_read_as_any_other(data: Path) -> None:
    """``SCHEMA`` stays: readers ignore the column, the table and the meta rows that it lacks."""
    path = write(data / "docs", page("196845", "Kafka"), BODY)
    build_index(data / "docs", data / "index.sqlite", MOMENT)
    with closing(sqlite3.connect(data / "index.sqlite")) as connection:
        connection.execute("ALTER TABLE documents DROP COLUMN digest")
        connection.execute("DROP TABLE skipped")
        connection.execute("DELETE FROM meta WHERE name IN ('words', 'aliases')")
        connection.commit()
    with reading(data / "index.sqlite") as reader:
        assert [entry.path for entry in reader.indexed_documents(paths=[path])] == [path]
        assert list(reader.scores('"retention"', Filters())[0]) == [path]
        summary = reader.index_status()
    assert (summary.types, summary.skipped) == ({"page": 1}, 0)


def written_backwards(index: Path, fronts: Iterable[FrontMatter]) -> JoinOutcome:
    """Write documents the last by path first, join them, and give what the join said.

    Their rowids then go against their paths, as they do where an edited file comes last.
    """
    cut = tuple(sections(""))
    with sqlite_index.building(index, MOMENT) as writer:
        for front in sorted(fronts, key=location, reverse=True):
            writer.add(Put(path=location(front), digest="d", front=front, sections=cut))
        return writer.join({})


@pytest.mark.parametrize(
    ("account", "first", "second", "person"),
    [
        ("acct-0001", "Robin Example", "Robin Sample", ROBIN),
        (None, "Sam SAMPLE", "sam sample", SAM_ALONE),
    ],
    ids=["an account's", "a name alone's"],
)
def test_two_names_tied_serve_the_first_by_path_whatever_the_rowids(
    data: Path, account: str | None, first: str, second: str, person: str
) -> None:
    """On documents of one update time, as an edit leaves them, the person keeps its name."""
    fronts = [
        page(number, "Tied", people=(Mention(role="author", name=name, account=account),))
        for number, name in (("1", first), ("2", second))
    ]
    written_backwards(data / "index.sqlite", fronts)
    with reading(data / "index.sqlite") as reader:
        activity = reader.person(person)
    assert activity is not None
    assert activity.person.name == first


def test_an_ambiguous_name_is_said_by_its_first_spelling_by_path(data: Path) -> None:
    """Whichever of the documents spelling it was written last."""
    fronts = [
        page("1", "Tied", author="Sam SAMPLE"),
        page("2", "Tied", author="sam sample"),
        *(
            page(number, "Tied", people=(Mention(role="author", name="Sam Sample", account=who),))
            for number, who in (("3", "acct-0002"), ("4", "acct-0003"))
        ),
    ]
    outcome = written_backwards(data / "index.sqlite", fronts)
    assert outcome.ambiguous == (Ambiguity(name="Sam SAMPLE", persons=frozenset({SAM_2, SAM_3})),)


def test_a_transcript_joins_its_meeting_whatever_the_rowids(data: Path) -> None:
    """Its speaker, by first name alone, takes the person of the participant that it links to."""
    fronts = [
        worklog_document("meeting", "m-20261020-review", "Review", ("Sam Sample",)),
        worklog_document("transcript", "t-20261020-1", "Review", ("Sam",), "m-20261020-review"),
    ]
    written_backwards(data / "index.sqlite", fronts)
    assert sorted(rows_of(data / "index.sqlite", "SELECT name, person FROM people")) == [
        ("Sam", SAM_ALONE),
        ("Sam Sample", SAM_ALONE),
    ]


def test_a_whole_build_numbers_documents_by_their_paths_text(data: Path) -> None:
    """Files come by the parts of their paths, ``a/b.md`` first; ties by their text, ``a-b.md``."""
    folder = data / "docs" / "confluence" / "ENG"
    (folder / "a").mkdir(parents=True)
    first = dump(page("1", "Tied", author="Sam SAMPLE"), "# Tied\n")
    (folder / "a" / "b.md").write_text(first, encoding="utf-8")
    second = dump(page("2", "Tied", author="sam sample"), "# Tied\n")
    (folder / "a-b.md").write_text(second, encoding="utf-8")
    build_index(data / "docs", data / "index.sqlite", MOMENT)
    assert rows_of(data / "index.sqlite", "SELECT path FROM documents ORDER BY rowid") == [
        ("confluence/ENG/a/b.md",),
        ("confluence/ENG/a-b.md",),
    ]
    with reading(data / "index.sqlite") as reader:
        activity = reader.person(SAM_ALONE)
    assert activity is not None
    assert activity.person.name == "sam sample"


# What a whole build writes under this value of ``WORDS``, from files of the same bytes:
# sections cut, words tokenized, a document's rows written and people joined. Changing any
# pin below goes with a new value of ``WORDS``, here and in the code.
PINNED_WORDS = "1"
WORDS_CHANGED = (
    "a whole build writes otherwise from the same files: change WORDS, in"
    " search/domain/search.py, so that no update keeps rows of the old one; then pin this"
)
HANDBOOK = page(
    "1001",
    "Deploy",
    labels=("ops", "été"),
    breadcrumb=("Home", "Guidés"),
    created=MOMENT - timedelta(days=3),
    fetched_at=MOMENT + timedelta(hours=1),
    url="https://example.atlassian.net/wiki/spaces/ENG/pages/1001",
    people=(
        Mention(role="author", name="A Person", account="acct-0001"),
        Mention(
            role="commenter",
            name="Kim Doé",
            at=(MOMENT - timedelta(hours=2), MOMENT - timedelta(hours=1)),
        ),
    ),
    links=(Link(relation="summary", ref="m-20261020-review"),),
)
HANDBOOK_BODY = (
    "# Deploy\n\nWhy we deploy_it.\n\n"
    "## Rollback ##\r\n\r\nUndo it.\n\n```\n# not a heading\n```\n\n"
    "### Steps\n\n####### nor this\n"
)
NOTE = issue("PROJ-1", "Économie", author=None)
# Việt's letter of two diacritics is what ``remove_diacritics 2`` folds, and 1 does not.
NOTE_BODY = "Avant l'été à Vi\u1ec7t.\n\n# Économie\n\nRetour.\n"
# Per section: its document, number, start, head, title, labels, breadcrumb, heading, body.
PINNED_SECTIONS = [
    (
        "confluence/ENG/1001-deploy.md",
        1,
        0,
        "# Deploy\n",
        "Deploy",
        "ops été",
        "Home / Guidés",
        "",
        "\nWhy we deploy_it.\n\n",
    ),
    (
        "confluence/ENG/1001-deploy.md",
        2,
        29,
        "## Rollback ##\r\n",
        "",
        "",
        "",
        "Rollback",
        "\r\nUndo it.\n\n```\n# not a heading\n```\n\n",
    ),
    (
        "confluence/ENG/1001-deploy.md",
        3,
        82,
        "### Steps\n",
        "",
        "",
        "",
        "Steps",
        "\n####### nor this\n",
    ),
    ("jira/PROJ/PROJ-1.md", 1, 0, "", "Économie", "", "", "", "Avant l'été à Vi\u1ec7t.\n\n"),
    ("jira/PROJ/PROJ-1.md", 2, 21, "# Économie\n", "", "", "", "Économie", "\nRetour.\n"),
]
# Each term of the two documents: in how many sections, how many times, as FTS5 counts.
PINNED_TERMS = [
    ("a", 2, 2),
    ("avant", 1, 1),
    ("deploy", 1, 2),
    ("economie", 2, 2),
    ("ete", 2, 2),
    ("guides", 1, 1),
    ("heading", 1, 1),
    ("home", 1, 1),
    ("it", 2, 2),
    ("l", 1, 1),
    ("nor", 1, 1),
    ("not", 1, 1),
    ("ops", 1, 1),
    ("retour", 1, 1),
    ("rollback", 1, 1),
    ("steps", 1, 1),
    ("this", 1, 1),
    ("undo", 1, 1),
    ("viet", 1, 1),
    ("we", 1, 1),
    ("why", 1, 1),
]
# Each document's row but its rowid and its file's digest: times, people, links as written.
PINNED_DOCUMENTS = [
    (
        "confluence/ENG/1001-deploy.md",
        "confluence",
        "page",
        "1001",
        None,
        "Deploy",
        "ENG",
        None,
        "current",
        None,
        '["ops", "été"]',
        (
            '[{"role": "author", "name": "A Person", "account": "acct-0001", "at": []},'
            ' {"role": "commenter", "name": "Kim Doé", "account": null,'
            ' "at": ["2026-10-20T19:52:41+00:00", "2026-10-20T20:52:41+00:00"]}]'
        ),
        '[{"relation": "summary", "ref": "m-20261020-review"}]',
        "2026-10-17T21:52:41+00:00",
        "2026-10-20T21:52:41+00:00",
        1,
        "000001",
        "https://example.atlassian.net/wiki/spaces/ENG/pages/1001",
        '["Home", "Guidés"]',
        "2026-10-20T22:52:41+00:00",
        110,
        1,
        3,
    ),
    (
        "jira/PROJ/PROJ-1.md",
        "jira",
        "issue",
        "10001",
        "PROJ-1",
        "Économie",
        None,
        "PROJ",
        "To Do",
        "Task",
        "[]",
        "[]",
        "[]",
        "2026-10-20T21:52:41+00:00",
        "2026-10-20T21:52:41+00:00",
        None,
        "20261020T215241.000000Z",
        None,
        "[]",
        "2026-10-20T21:52:41+00:00",
        41,
        4,
        5,
    ),
]
# Each row of people, a commenter's one per comment, and the file refused with why.
PINNED_ROWS = [
    ("confluence/ENG/1001-deploy.md", "author", "A Person", "acct-0001", None),
    ("confluence/ENG/1001-deploy.md", "commenter", "Kim Doé", None, "2026-10-20T19:52:41+00:00"),
    ("confluence/ENG/1001-deploy.md", "commenter", "Kim Doé", None, "2026-10-20T20:52:41+00:00"),
]
PINNED_LABELS = [("confluence/ENG/1001-deploy.md", "ops"), ("confluence/ENG/1001-deploy.md", "été")]
REFUSED = "---\ntitle: no other key\n---\n"
# Its reason, but the mirror's keys, which change with the mirror rather than the index.
PINNED_SKIPPED = [("confluence/ENG/1-broken.md", "front matter without exactly the mirror's keys")]


def test_what_a_whole_build_writes_of_a_document_is_pinned_under_words(data: Path) -> None:
    """The sections, the words and the rows of two documents, and a refusal, under ``WORDS``.

    Every column of their rows, labels and people, each time distinct, names and labels
    beyond ASCII, so that no change to how a time, a name, the people or the links are
    written leaves an update's copied rows otherwise than a whole build's.
    """
    write(data / "docs", HANDBOOK, HANDBOOK_BODY)
    write(data / "docs", NOTE, NOTE_BODY)
    (data / "docs" / "confluence" / "ENG" / "1-broken.md").write_text(REFUSED, encoding="utf-8")
    build_index(data / "docs", data / "index.sqlite", MOMENT)
    assert WORDS == PINNED_WORDS, WORDS_CHANGED
    index = data / "index.sqlite"
    assert (
        rows_of(
            index,
            "SELECT d.path, s.number, s.start, s.head, s.title, s.labels, s.breadcrumb,"
            " s.heading, s.body FROM sections s JOIN documents d ON d.rowid = s.document"
            " ORDER BY d.path, s.number",
        )
        == PINNED_SECTIONS
    ), WORDS_CHANGED
    assert (
        rows_of(
            index,
            "SELECT path, source, type, id, key, title, space, project, status, issue_type,"
            " labels, people, links, created, updated, version, revision, url, breadcrumb,"
            " fetched_at, length, first_section, last_section FROM documents ORDER BY path",
        )
        == PINNED_DOCUMENTS
    ), WORDS_CHANGED
    assert (
        rows_of(
            index,
            "SELECT d.path, p.role, p.name, p.account, p.at FROM people p"
            " JOIN documents d ON d.rowid = p.document ORDER BY 1, 2, 3, 5",
        )
        == PINNED_ROWS
    ), WORDS_CHANGED
    assert (
        rows_of(
            index,
            "SELECT d.path, l.label FROM labels l JOIN documents d ON d.rowid = l.document"
            " ORDER BY l.rowid",
        )
        == PINNED_LABELS
    ), WORDS_CHANGED
    skipped = rows_of(index, "SELECT path, reason FROM skipped")
    pinned = [(path, reason[: len(PINNED_SKIPPED[0][1])]) for path, reason in skipped]
    assert pinned == PINNED_SKIPPED, WORDS_CHANGED
    with closing(sqlite3.connect(index)) as connection:
        connection.execute(
            "CREATE VIRTUAL TABLE temp.terms USING fts5vocab(main, section_words, row)"
        )
        terms = connection.execute("SELECT term, doc, cnt FROM terms ORDER BY term").fetchall()
    assert terms == PINNED_TERMS, WORDS_CHANGED


# One account under two names; a name that joins it, an alias and a meeting's speaker that
# join a name alone; a name of two accounts, which joins neither.
JO_2, JO_3 = anchored("account\nacct-0002"), anchored("account\nacct-0003")
JO_ALONE = anchored("name\njo two")
PINNED_MIRROR = (
    page(
        "1",
        "One",
        people=(Mention(role="author", name="Robin Example", account="acct-0001"),),
    ),
    issue(
        "PROJ-1",
        "Two",
        updated=MOMENT + timedelta(days=1),
        people=(Mention(role="creator", name="Robin Sample", account="acct-0001"),),
    ),
    *(
        issue(key, "Same", people=(Mention(role="author", name="Jo Two", account=account),))
        for key, account in (("PROJ-2", "acct-0002"), ("PROJ-3", "acct-0003"))
    ),
    worklog_document(
        "meeting", "m-20261020-review", "Review", ("robin  EXAMPLE", "Sam Sample", "Kim", "Jo Two")
    ),
    worklog_document("transcript", "t-20261020-1", "Review", ("Sam", "Alex"), "m-20261020-review"),
)
PINNED_PERSONS = sorted(
    [
        (ROBIN, "Robin Sample"),
        (SAM_ALONE, "Sam Sample"),
        (ALEX, "Alex"),
        (JO_2, "Jo Two"),
        (JO_3, "Jo Two"),
        (JO_ALONE, "Jo Two"),
    ]
)
PINNED_SPELLINGS = sorted(
    [
        (ROBIN, "Robin Example", "robin example", "account"),
        (ROBIN, "Robin Sample", "robin sample", "account"),
        (ROBIN, "robin  EXAMPLE", "robin example", "name"),
        (SAM_ALONE, "Sam Sample", "sam sample", "name"),
        (SAM_ALONE, "Kim", "kim", "alias"),
        (SAM_ALONE, "Sam", "sam", "meeting"),
        (ALEX, "Alex", "alex", "name"),
        (JO_2, "Jo Two", "jo two", "account"),
        (JO_3, "Jo Two", "jo two", "account"),
        (JO_ALONE, "Jo Two", "jo two", "name"),
    ]
)
PINNED_PEOPLE = sorted(
    [
        ("confluence/ENG/1-one.md", "author", "Robin Example", "acct-0001", ROBIN),
        ("jira/PROJ/PROJ-1.md", "creator", "Robin Sample", "acct-0001", ROBIN),
        ("jira/PROJ/PROJ-2.md", "author", "Jo Two", "acct-0002", JO_2),
        ("jira/PROJ/PROJ-3.md", "author", "Jo Two", "acct-0003", JO_3),
        ("worklog/meetings/m-20261020-review.md", "participant", "robin  EXAMPLE", None, ROBIN),
        ("worklog/meetings/m-20261020-review.md", "participant", "Sam Sample", None, SAM_ALONE),
        ("worklog/meetings/m-20261020-review.md", "participant", "Kim", None, SAM_ALONE),
        ("worklog/meetings/m-20261020-review.md", "participant", "Jo Two", None, JO_ALONE),
        ("worklog/transcripts/t-20261020-1-review.md", "participant", "Sam", None, SAM_ALONE),
        ("worklog/transcripts/t-20261020-1-review.md", "participant", "Alex", None, ALEX),
    ]
)


def test_what_a_whole_build_joins_of_a_small_mirror_is_pinned_under_words(data: Path) -> None:
    """Each person, each spelling and each row's person, as ``WORDS`` names them."""
    for front in PINNED_MIRROR:
        write(data / "docs", front)
    report = build_index(
        data / "docs", data / "index.sqlite", MOMENT, aliases={"Kim": "Sam Sample"}
    )
    assert WORDS == PINNED_WORDS, WORDS_CHANGED
    index = data / "index.sqlite"
    persons = rows_of(index, "SELECT id, name FROM persons ORDER BY 1")
    assert persons == PINNED_PERSONS, WORDS_CHANGED
    assert (
        rows_of(index, "SELECT person, name, key, joined FROM person_names ORDER BY 1, 2, 3, 4")
        == PINNED_SPELLINGS
    ), WORDS_CHANGED
    assert (
        rows_of(
            index,
            "SELECT d.path, p.role, p.name, p.account, p.person"
            " FROM people p JOIN documents d ON d.rowid = p.document ORDER BY 1, 2, 3",
        )
        == PINNED_PEOPLE
    ), WORDS_CHANGED
    assert report.persons.ambiguous == (
        Ambiguity(name="Jo Two", persons=frozenset({JO_2, JO_3})),
    ), WORDS_CHANGED


LEXICAL = 'search_mode = "lexical"\n'
PAGES = 3  # the fillers of a test's mirror, Kafka's page aside
KAFKA = page("196845", "Kafka", labels=("streaming",))
KAFKA_PATH = location(KAFKA)


def embedded(data: Path) -> None:
    """Write a mirror of a few pages and Kafka's, and build its index whole, by meaning."""
    fillers(data / "docs", PAGES)
    write(data / "docs", KAFKA, BODY)
    build_index(data / "docs", data / "index.sqlite", MOMENT, Embedding(tiny(), data / "v.db"))


def snapshot(index: Path) -> tuple[bytes, int, str]:
    """Give an index's bytes, its time and its build: what a run that writes nothing keeps."""
    with reading(index) as reader:
        return index.read_bytes(), index.stat().st_mtime_ns, reader.build()


# Each row of every document but one, with its rowids: what an update copies as it was.
KEPT_ROWS = (
    "SELECT * FROM documents WHERE path <> :path ORDER BY rowid",
    """
    SELECT l.* FROM labels l JOIN documents d ON d.rowid = l.document
    WHERE d.path <> :path ORDER BY l.document, l.label
    """,
    """
    SELECT p.document, p.role, p.name, p.account, p.at FROM people p
    JOIN documents d ON d.rowid = p.document WHERE d.path <> :path
    ORDER BY p.document, p.role, p.name
    """,
    """
    SELECT s.* FROM sections s JOIN documents d ON d.rowid = s.document
    WHERE d.path <> :path ORDER BY s.rowid
    """,
    """
    SELECT p.* FROM chunks p JOIN sections s ON s.rowid = p.section
    JOIN documents d ON d.rowid = s.document WHERE d.path <> :path ORDER BY p.rowid
    """,
)
# The rows of one document, by path.
ITS_ROWS = (
    "SELECT * FROM documents WHERE path = :path",
    "SELECT l.* FROM labels l JOIN documents d ON d.rowid = l.document WHERE d.path = :path",
    "SELECT p.* FROM people p JOIN documents d ON d.rowid = p.document WHERE d.path = :path",
    "SELECT s.* FROM sections s JOIN documents d ON d.rowid = s.document WHERE d.path = :path",
    """
    SELECT p.* FROM chunks p JOIN sections s ON s.rowid = p.section
    JOIN documents d ON d.rowid = s.document WHERE d.path = :path
    """,
)


def rows_by(index: Path, queries: Iterable[str], path: str) -> list[list[tuple[object, ...]]]:
    """Read the rows that each query gives of a path, as they are written."""
    with closing(sqlite3.connect(index)) as connection:
        return [connection.execute(query, {"path": path}).fetchall() for query in queries]


def test_nothing_changed_writes_nothing_and_says_so(
    data: Path, capsys: CaptureFixture[str]
) -> None:
    """Plan 035, criterion 3: the index's bytes, time and build as they were, exit 0.

    The summary still counts what the index holds; ``index.unchanged`` says it.
    """
    fillers(data / "docs", PAGES)
    assert index(data, capsys)[0] == 0
    before = snapshot(data / "index.sqlite")
    status, out, _ = index(data, capsys)
    assert status == 0
    assert out == f"documents: {PAGES}\nsections: {2 * PAGES}\nnothing written\nskipped: 0\n"
    assert snapshot(data / "index.sqlite") == before
    (unchanged,) = logged_as(data.parent / "home", "index.unchanged")
    assert unchanged["documents"] == PAGES
    assert (unchanged["sections"], unchanged["skipped"]) == (2 * PAGES, 0)
    assert len(logged_as(data.parent / "home", "index.built")) == 1


def test_an_edited_file_is_replaced_and_every_other_document_keeps_its_rows(
    data: Path, capsys: CaptureFixture[str]
) -> None:
    """Criterion 3: 1 replaced; every other document's rows, rowids and chunks as they were.

    The edited document has no chunks, awaiting vectors, and its new words find it; the
    index stays in SQLite's rollback journal.
    """
    embedded(data)
    kept = rows_by(data / "index.sqlite", KEPT_ROWS, KAFKA_PATH)
    assert kept[0]
    assert kept[-1]
    write(data / "docs", KAFKA, BODY.replace("Seven days.", "Fourteen days."))
    status, out, _ = index(data, capsys)
    assert status == 0
    assert f"copied: {PAGES}\nadded: 0\nreplaced: 1\nremoved: 0\nskipped: 0\n" in out
    assert out.endswith("awaiting vectors: 1\n")
    assert rows_by(data / "index.sqlite", KEPT_ROWS, KAFKA_PATH) == kept
    assert rows_by(data / "index.sqlite", ITS_ROWS, KAFKA_PATH)[4] == []
    assert rows_of(data / "index.sqlite", "PRAGMA journal_mode") == [("delete",)]
    with reading(data / "index.sqlite") as reader:
        assert list(reader.scores('"fourteen"', Filters())[0]) == [KAFKA_PATH]
        assert reader.scores('"seven"', Filters())[0] == {}


def test_a_removed_file_leaves_no_row_and_full_text_search_whole(
    data: Path, capsys: CaptureFixture[str]
) -> None:
    """Criterion 4: its document, labels, people, sections and chunks gone; FTS5 checks out.

    A word that it alone held finds nothing, and its label is no value any more.
    """
    embedded(data)
    assert all(rows_by(data / "index.sqlite", ITS_ROWS, KAFKA_PATH))
    (data / "docs" / KAFKA_PATH).unlink()
    status, out, _ = index(data, capsys)
    assert status == 0
    assert f"copied: {PAGES}\nadded: 0\nreplaced: 0\nremoved: 1\n" in out
    assert rows_by(data / "index.sqlite", ITS_ROWS, KAFKA_PATH) == [[]] * len(ITS_ROWS)
    orphans = "SELECT count(*) FROM chunks WHERE section NOT IN (SELECT rowid FROM sections)"
    assert rows_of(data / "index.sqlite", orphans) == [(0,)]
    checked = data.parent / "checked.sqlite"
    checked.write_bytes((data / "index.sqlite").read_bytes())
    with closing(sqlite3.connect(checked)) as connection:
        connection.execute(
            "INSERT INTO section_words (section_words, rank) VALUES ('integrity-check', 1)"
        )
    with reading(data / "index.sqlite") as reader:
        assert reader.scores('"retention"', Filters()) == ({}, True)
        assert ("streaming", 1) not in reader.values("label")


def made_before_digests(path: Path) -> None:
    """Make an index as one of schema 6 was before plan 035: no digest, skipped or words."""
    with closing(sqlite3.connect(path)) as connection:
        connection.execute("DELETE FROM meta WHERE name IN ('words', 'aliases')")
        connection.execute("ALTER TABLE documents DROP COLUMN digest")
        connection.execute("DROP TABLE skipped")
        connection.commit()


def another_schema(path: Path) -> None:
    """Make an index of the schema before persons."""
    with closing(sqlite3.connect(path)) as connection:
        connection.execute("UPDATE meta SET value = '5' WHERE name = 'schema'")
        connection.commit()


def unknown_chunking(path: Path) -> None:
    """Make an index cut by a chunking that this version lacks."""
    with closing(sqlite3.connect(path)) as connection:
        connection.execute("UPDATE meta SET value = 'paragraphs' WHERE name = 'chunking'")
        connection.commit()


@pytest.mark.parametrize(
    ("made", "options", "reason"),
    [
        (made_before_digests, (), "another version"),
        (another_schema, (), "unavailable"),
        (unknown_chunking, (), "unavailable"),
        (None, ("--rebuild",), "--rebuild"),
    ],
)
def test_an_index_that_cannot_be_updated_is_rebuilt_whole_saying_why(
    data: Path,
    capsys: CaptureFixture[str],
    made: Callable[[Path], None] | None,
    options: tuple[str, ...],
    reason: str,
) -> None:
    """Criterion 7: without digests, at another schema, cut otherwise, or --rebuild: whole.

    ``index.whole`` says why, the summary too; nothing is copied; exit 0; the index then
    holds every document with its digest, under this code's ``WORDS``, and no chunks.
    """
    embedded(data)
    if made is not None:
        made(data / "index.sqlite")
    status, out, _ = index(data, capsys, LEXICAL, *options)
    assert status == 0
    assert f"copied: 0\nadded: {PAGES + 1}\nreplaced: 0\nremoved: 0\n" in out
    assert f"rebuilt whole: {reason}\n" in out
    (whole,) = logged_as(data.parent / "home", "index.whole")
    assert whole["reason"] == reason
    with reading(data / "index.sqlite") as reader:
        held = reader.held()
        assert (held.words, len(held.documents), reader.embedded()) == (WORDS, PAGES + 1, None)


def test_an_index_of_another_words_is_rebuilt_whole(
    data: Path, capsys: CaptureFixture[str], monkeypatch: MonkeyPatch
) -> None:
    """Criterion 7: the constant changed by the test, the index read as another version's."""
    fillers(data / "docs", PAGES)
    assert index(data, capsys)[0] == 0
    monkeypatch.setattr(indexing_module, "WORDS", "another")
    status, out, _ = index(data, capsys)
    assert status == 0
    assert "rebuilt whole: another version\n" in out


def damage(index: Path, table: str) -> None:
    """Overwrite the root page of a table of the index, which ``reading`` alone passes."""
    with closing(sqlite3.connect(index)) as connection:
        root = connection.execute("SELECT rootpage FROM sqlite_master WHERE name = ?", (table,))
        page_number = root.fetchone()[0]
        size = connection.execute("PRAGMA page_size").fetchone()[0]
    with index.open("r+b") as file:
        file.seek((page_number - 1) * size)
        file.write(b"\xff" * size)


@pytest.mark.parametrize(
    ("table", "changed"), [("documents", False), ("sections", True), ("labels", True)]
)
def test_a_damaged_index_is_rebuilt_whole(
    data: Path, capsys: CaptureFixture[str], table: str, *, changed: bool
) -> None:
    """Criterion 7: a table's root page overwritten: ``index.whole``, reason damaged, exit 0.

    That of documents, read whether anything changed; of sections, read for the summary;
    of labels, which the copy alone reads, once a file changed.
    """
    fillers(data / "docs", PAGES)
    write(data / "docs", KAFKA, BODY)
    assert index(data, capsys)[0] == 0
    damage(data / "index.sqlite", table)
    if changed:
        write(data / "docs", KAFKA, BODY + "\nEdited.\n")
    status, out, err = index(data, capsys)
    assert status == 0
    assert "Traceback" not in err
    assert "rebuilt whole: damaged\n" in out
    with reading(data / "index.sqlite") as reader:
        assert len(reader.listing(Filters())) == PAGES + 1
        assert reader.values("label") == [("streaming", 1)]


def test_an_index_written_meanwhile_starts_the_update_again_once(
    data: Path, capsys: CaptureFixture[str], monkeypatch: MonkeyPatch
) -> None:
    """Criterion 8: another build renamed in between the read and the write; then twice.

    The other run builds the mirror as it was. Once, ``index.restarted`` says so, and the
    update reads the new build and writes; twice, it stops, ``index.not_built`` naming
    the other run, exit 1.
    """
    fillers(data / "docs", PAGES)
    assert index(data, capsys)[0] == 0
    before = data.parent / "before"
    shutil.copytree(data / "docs", before)
    update = SqliteIndex.update
    builds: list[str | None] = []
    meanwhile_at = {1}

    def meanwhile(self: SqliteIndex, change: object, expected: str | None) -> object:
        builds.append(expected)
        if len(builds) in meanwhile_at:
            build_index(before, data / "index.sqlite", MOMENT)
        return update(self, change, expected)

    monkeypatch.setattr(SqliteIndex, "update", meanwhile)
    write(data / "docs", KAFKA, BODY)
    status, out, _ = index(data, capsys)
    assert status == 0
    assert "added: 1\n" in out
    assert len(builds) == len(set(builds)) == len(meanwhile_at) + 1
    assert len(logged_as(data.parent / "home", "index.restarted")) == 1
    builds.clear()
    meanwhile_at.add(2)
    write(data / "docs", KAFKA, BODY + "\nEdited.\n")
    status, _, err = index(data, capsys)
    assert status == 1
    assert ("error", "index.not_built") in said(err)
    assert CHANGED_MEANWHILE in err
    assert len(builds) == len(set(builds)) == len(meanwhile_at)


def test_a_lock_held_too_long_fails_naming_it(
    data: Path, capsys: CaptureFixture[str], monkeypatch: MonkeyPatch
) -> None:
    """Criterion 8: a wait past WAIT_S, shortened here, said first: exit 1, the index in place."""
    monkeypatch.setattr(vector_cache, "WAIT_S", 0.3)
    fillers(data / "docs", PAGES)
    assert index(data, capsys)[0] == 0
    before = (data / "index.sqlite").read_bytes()
    write(data / "docs", KAFKA, BODY)
    lock = data / "index.sqlite.lock"
    with lock.open("a") as file:
        fcntl.flock(file, fcntl.LOCK_EX)
        status, _, err = index(data, capsys)
    assert status == 1
    assert ("error", "index.not_built") in said(err)
    assert f"{lock}: another kb-mcp index or kb-mcp embed held it" in err
    (waited,) = logged_as(data.parent / "home", "index.lock_wait")
    assert waited["lock"] == str(lock)
    assert (data / "index.sqlite").read_bytes() == before
    assert index(data, capsys)[0] == 0


def test_an_update_that_fails_before_its_rename_leaves_the_index_as_it_was(
    data: Path, capsys: CaptureFixture[str], monkeypatch: MonkeyPatch
) -> None:
    """Criterion 9: its bytes as they were, no build file left, and the lock free."""
    fillers(data / "docs", PAGES)
    assert index(data, capsys)[0] == 0
    before = (data / "index.sqlite").read_bytes()
    write(data / "docs", KAFKA, BODY)

    def fail(*_: object) -> None:
        raise RuntimeError

    indexing = Indexing(
        docs=data / "docs",
        index=data / "index.sqlite",
        vectors=data / "vectors.sqlite",
        evaluation_indexes=data / "eval" / "indexes",
        aliases=data / "aliases.toml",
        model="tiny",
        chunking="sections",
        endpoint=None,
    )
    with monkeypatch.context() as patch:
        patch.setattr(sqlite_index.Writer, "join", fail)
        with pytest.raises(RuntimeError):
            update_index(indexing, MOMENT)
    assert (data / "index.sqlite").read_bytes() == before
    names = ["docs", "index.sqlite", "index.sqlite.lock"]
    assert sorted(path.name for path in data.iterdir()) == names
    assert index(data, capsys)[0] == 0


def test_an_update_killed_leaves_the_index_as_it_was_and_its_lock_free(
    data: Path, capsys: CaptureFixture[str]
) -> None:
    """Criterion 9: killed by SIGKILL in its join, its build file ignored by readers and prune.

    No write-ahead log is beside the index; the next run takes the lock and updates.
    """
    fillers(data / "docs", PAGES)
    assert index(data, capsys)[0] == 0
    before = (data / "index.sqlite").read_bytes()
    write(data / "docs", KAFKA, BODY)
    with subprocess.Popen(
        [
            sys.executable,
            "-c",
            (
                "import sys, time\n"
                "from kb_mcp.cli.main import main\n"
                "from kb_mcp.search.adapters import sqlite_index\n"
                "def join(self, aliases):\n"
                "    print('joining', flush=True)\n"
                "    time.sleep(60)\n"
                "sqlite_index.Writer.join = join\n"
                "sys.exit(main(['index', '--yes']))\n"
            ),
        ],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        text=True,
        env=child_environment(data),
        cwd=data.parent,
    ) as child:
        assert child.stdout is not None
        assert child.stdout.readline() == "joining\n"
        child.kill()
        child.wait(30)
    assert (data / "index.sqlite").read_bytes() == before
    assert list(data.glob(f"{sqlite_index.BUILDING}*.sqlite"))
    assert sqlite_index.indexes_in(data) == [data / "index.sqlite"]
    assert not (data / "index.sqlite-wal").exists()
    with reading(data / "index.sqlite") as reader:
        assert len(reader.listing(Filters())) == PAGES
    status, out, _ = index(data, capsys)
    assert (status, "added: 1\n" in out) == (0, True)


def test_a_whole_update_s_own_damage_is_raised_once_not_retried(
    data: Path, monkeypatch: MonkeyPatch
) -> None:
    """A corrupt error as a whole update writes its new file: no index in place was read.

    It is raised, after one attempt, rather than taken for the index's damage and tried
    again whole without end.
    """
    fillers(data / "docs", PAGES)
    attempts: list[object] = []

    def corrupt(*arguments: object) -> None:
        assert not attempts, "a whole update tried again"
        attempts.append(arguments)
        error = sqlite3.DatabaseError("database disk image is malformed")
        error.sqlite_errorcode = sqlite3.SQLITE_CORRUPT
        raise error

    monkeypatch.setattr(sqlite_index.Writer, "update", corrupt)
    indexing = Indexing(
        docs=data / "docs",
        index=data / "index.sqlite",
        vectors=data / "vectors.sqlite",
        evaluation_indexes=data / "eval" / "indexes",
        aliases=data / "aliases.toml",
        model="tiny",
        chunking="sections",
        endpoint=None,
    )
    with pytest.raises(sqlite3.DatabaseError, match="malformed"):
        update_index(indexing, MOMENT, rebuild=True)
    assert len(attempts) == 1
    assert sorted(path.name for path in data.iterdir()) == ["docs", "index.sqlite.lock"]
    lock = data / "index.sqlite.lock"
    with lock.open("a") as file:
        fcntl.flock(file, fcntl.LOCK_EX | fcntl.LOCK_NB)  # free, or this raises


def test_the_index_s_sql_names_roles_types_and_relations_as_the_mirror_does() -> None:
    """Plan 052: each role, type and relation that the SQL spells is one the mirror names.

    The SQL holds them as text, which Ruff's S608 keeps from being built from the mirror's
    constants: a role it compares is one of ``ROLES``, a type one of the work log's, a
    relation one of ``RELATIONS``, so that a role or a relation renamed in the mirror
    fails here rather than matching nothing.
    """
    sql = "\n".join(
        [value for value in vars(sqlite_index).values() if isinstance(value, str)]
        + list(sqlite_index.VALUES.values())
    )
    said = {
        "roles": set(re.findall(r"role = '(\w+)'", sql)),
        "types": set(re.findall(r"type (?:=|<>) '(\w+)'", sql)),
        "relations": set(re.findall(r"'\$\.relation'\) = '(\w+)'", sql)),
    }
    assert all(said.values())
    assert said["roles"] <= set(ROLES)
    assert said["types"] <= set(WORKLOG_TYPES)
    assert said["relations"] <= set(RELATIONS)


def test_the_index_lists_the_values_of_each_role_s_filter() -> None:
    """Plan 052: each role of ``ROLES`` has its values, as ``browse`` and ``status`` list them."""
    assert [role for role in ROLES if role not in sqlite_index.VALUES] == []
