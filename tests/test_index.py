"""The index: built from the mirror alone, replaced whole, opened read-only."""

from __future__ import annotations

import hashlib
import json
import os
import pty
import re
import sqlite3
import subprocess
import sys
from contextlib import closing
from copy import replace
from datetime import timedelta
from typing import TYPE_CHECKING

import pytest

from kb_mcp.cli.main import main
from kb_mcp.mirror.adapters.markdown import dump
from kb_mcp.mirror.domain.mirror import Link, PersonRole
from kb_mcp.search.adapters import sqlite_index
from kb_mcp.search.adapters.sqlite_index import reading
from kb_mcp.search.app.indexing import Embedding, Indexing, build_index, index_mirror
from kb_mcp.search.domain.indexes import Put, UnavailableIndexError
from kb_mcp.search.domain.people import (
    UNHELD,
    Ambiguity,
    Outcome,
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
from tests.test_question import read_until

if TYPE_CHECKING:
    from collections.abc import Iterable
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


def test_embed_needs_the_endpoint_and_index_never_asks_it(
    data: Path, capsys: CaptureFixture[str]
) -> None:
    """No endpoint answering: ``embed`` exits 1 naming the way out, which runs by words alone.

    Whatever the mode says, as neither reads it to decide: plan 031, criterion 5.
    """
    write(data / "docs", page("196845", "Kafka"), BODY)
    config = data.parent / "config.toml"
    with nothing_listening() as url:
        config.write_text(f"embedding_url = {json.dumps(url)}\n", encoding="utf-8")
        options = ["--yes", "--config", str(config), "--data-dir", str(data)]
        assert main(["embed", *options]) == 1
        assert "run kb-mcp index for an index by words alone" in capsys.readouterr().err
        status, out, _ = index(data, capsys, f"embedding_url = {json.dumps(url)}\n")
    assert (status, out) == (0, "documents: 1\nsections: 2\n")


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


def test_a_database_error_is_a_failure_and_keeps_the_old_index(
    data: Path, capsys: CaptureFixture[str], monkeypatch: MonkeyPatch
) -> None:
    """The database's error while building, as of a full disk, simulated: exit 1, said.

    The index in place stays as it was, and no traceback is written.
    """
    write(data / "docs", page("196845", "Kafka"))
    assert index(data, capsys)[0] == 0
    before = (data / "index.sqlite").read_bytes()

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
        index_mirror(indexing, MOMENT)


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
        assert reader.summary().types == {"page": 1}
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
        assert reader.summary().spaces == {"ENG": 1, "OPS": 1}


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
        PersonRole(role="author", name="A Person", account="account-1"),
        PersonRole(role="creator", name="Another Person", account="account-2"),
        PersonRole(
            role="commenter",
            name="Another Person",
            account="account-2",
            at=(CREATED, CREATED + timedelta(hours=1)),
        ),
        PersonRole(
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
        (entry,) = reader.entries(paths=[path])
    assert entry.front == COMMENTED


def test_people_are_not_embedded_so_a_rebuild_with_new_people_embeds_nothing(data: Path) -> None:
    """A piece embeds its document's title, breadcrumb and text alone, never its people."""
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
        PersonRole(role="participant", name="Alex Example"),
        PersonRole(role="participant", name="Kim (not in the header)"),
    ),
    links=(Link(relation="transcript", ref="t-20261027-meeting-1"),),
)
TRANSCRIPT = replace(
    MEETING,
    type="transcript",
    id="t-20261027-meeting-1",
    title="Meeting 1",
    people=(
        PersonRole(role="participant", name="Alex Example"),
        PersonRole(role="participant", name="Sam Sample"),
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
        fronts = {entry.path: entry.front for entry in reader.entries(paths=paths)}
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
    Spelling(name="Robin", key="robin", how="meeting"),
    Spelling(name="Robin Example", key="robin example", how="account"),
    Spelling(name="Robin Example", key="robin example", how="name"),
    Spelling(name="Robin Sample", key="robin sample", how="account"),
    Spelling(name="robin  EXAMPLE", key="robin example", how="name"),
)
JOINED = {
    ROBIN: ("Robin Sample", ROBIN_SPELT),
    SAM_2: ("Sam Sample", (Spelling(name="Sam Sample", key="sam sample", how="account"),)),
    SAM_3: ("Sam Sample", (Spelling(name="Sam Sample", key="sam sample", how="account"),)),
    SAM_ALONE: (
        "Sam Sample",
        (
            Spelling(name="Sam", key="sam", how="meeting"),
            Spelling(name="Sam Sample", key="sam sample", how="name"),
        ),
    ),
    ALEX_EXAMPLE: (
        "Alex Example",
        (
            Spelling(name="Alex", key="alex", how="meeting"),
            Spelling(name="Alex Example", key="alex example", how="name"),
            Spelling(name="Alex Example (not in the header)", key="alex example", how="name"),
        ),
    ),
    ALEX: ("Alex", (Spelling(name="Alex", key="alex", how="name"),)),
    ROBIN_ALONE: ("Robin", (Spelling(name="Robin", key="robin", how="name"),)),
    ROBIN_OTHER: ("Robin Other", (Spelling(name="Robin Other", key="robin other", how="name"),)),
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
        (person, spelling.name, spelling.key, spelling.how)
        for person, (_, spellings) in sorted(JOINED.items())
        for spelling in spellings
    ]
    assert person_of == PERSON_OF


def test_the_report_counts_the_persons_and_gives_what_the_join_left_apart(data: Path) -> None:
    """Two names could be several persons; without aliases, none is unused."""
    for front in PERSONS:
        write(data / "docs", front)
    report = build_index(data / "docs", data / "index.sqlite", MOMENT)
    assert report.persons == Outcome(
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
        people=(PersonRole(role="author", name="Robin Third", account="acct-0004"),),
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
        plan = connection.execute(f"EXPLAIN QUERY PLAN {sqlite_index.SUMMARIES}").fetchall()
    steps = [row[3] for row in plan]
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
    assert robin.person == Person(id=ROBIN, name="Robin Sample", names=ROBIN_SPELT)
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
    ``prepare``, then ``index`` or ``embed``.
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
            " then `kb-mcp index` or `kb-mcp embed`"
        ),
    )
    with refused, reading(data / "index.sqlite"):
        pass


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
    -q, the terminal is sent no bar.
    """
    fillers(data / "docs")
    piped = subprocess.run(
        [sys.executable, "-m", "kb_mcp", "index", "--yes", "--format", "json"],
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
        [sys.executable, "-m", "kb_mcp", "index", "--yes", "--format", "json"],
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
        [sys.executable, "-m", "kb_mcp", "index", "--yes", "--format", "json", "-q"],
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
        assert reader.summary().skipped == len(rows)


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
        assert reader.summary().skipped == 0


def test_a_build_records_its_words_and_what_the_alias_file_means(
    data: Path, capsys: CaptureFixture[str]
) -> None:
    """The names and targets, in their order: no other change of the file moves the row."""
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
        assert [entry.path for entry in reader.entries(paths=[path])] == [path]
        assert list(reader.scores('"retention"', Filters())[0]) == [path]
        summary = reader.summary()
    assert (summary.types, summary.skipped) == ({"page": 1}, 0)


def written_backwards(index: Path, fronts: Iterable[FrontMatter]) -> Outcome:
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
        page(number, "Tied", people=(PersonRole(role="author", name=name, account=account),))
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
            page(
                number, "Tied", people=(PersonRole(role="author", name="Sam Sample", account=who),)
            )
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
HANDBOOK = page("1001", "Deploy", labels=("ops", "été"), breadcrumb=("Home", "Guides"))
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
        "Home / Guides",
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
# Of each document's row, what the front matter does not give back by itself.
PINNED_DOCUMENTS = [
    ("confluence/ENG/1001-deploy.md", '["ops", "été"]', '["Home", "Guides"]', 110, 1, 3),
    ("jira/PROJ/PROJ-1.md", "[]", "[]", 41, 4, 5),
]


def test_what_a_whole_build_writes_of_a_document_is_pinned_under_words(data: Path) -> None:
    """The sections, the words and the rows of two documents, as ``WORDS`` names them."""
    write(data / "docs", HANDBOOK, HANDBOOK_BODY)
    write(data / "docs", NOTE, NOTE_BODY)
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
            "SELECT path, labels, breadcrumb, length, first_section, last_section"
            " FROM documents ORDER BY path",
        )
        == PINNED_DOCUMENTS
    ), WORDS_CHANGED
    with closing(sqlite3.connect(index)) as connection:
        connection.execute("CREATE VIRTUAL TABLE temp.terms USING fts5vocab(main, chunks, row)")
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
        people=(PersonRole(role="author", name="Robin Example", account="acct-0001"),),
    ),
    issue(
        "PROJ-1",
        "Two",
        updated=MOMENT + timedelta(days=1),
        people=(PersonRole(role="creator", name="Robin Sample", account="acct-0001"),),
    ),
    *(
        issue(key, "Same", people=(PersonRole(role="author", name="Jo Two", account=account),))
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
