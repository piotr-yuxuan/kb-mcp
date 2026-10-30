"""Pandoc's conversions kept by their input across mirrors (plan 039, criteria 2 to 4 and 8).

A run is one ``opened`` of the file, here in a data folder not made yet, for one source's
rows, which plan 030 adds: Confluence's, unless a test names another. A key is
computed as the plan defines it, the SHA-256 of the UTF-8 bytes of the converter's name,
a NUL, then the HTML, so that the file is read as its layout says. The damage that the
plan's first review found, each a byte of a sound file changed, is made by hand: a page
of a table or of its index lies where ``sqlite_schema`` and the page size put it.
"""

from __future__ import annotations

import hashlib
import os
import sqlite3
import time
from contextlib import closing
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import pytest
from structlog.testing import capture_logs

from kb_mcp.mirror.adapters import conversions
from kb_mcp.mirror.adapters.pandoc import PandocFailedError
from tests.test_pruning import events_named

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable
    from pathlib import Path

    from _pytest.monkeypatch import MonkeyPatch

NAME = "pandoc 3.7.0.2\n--sandbox\n--from=html-native_divs-native_spans\n--to=gfm"
TEXTS = ("<p>a</p>", "<p>b</p>", "<p>c</p>", "<p>d</p>")
# The source whose rows a run reads and prunes, unless a test names another.
SOURCE = "confluence"
WAIT_S = 0.3


@dataclass
class Scripted:
    """A converter named ``name``, which counts the times it is named and what it is given.

    Its first ``unnamed`` names raise PandocFailedError, as a pandoc that gives no version
    does; its conversion number ``fails_at``, counting from 1, raises ``failure``. Before
    each conversion, ``meanwhile``, when given, acts on the file as another run might.
    """

    name: str = NAME
    unnamed: int = 0
    fails_at: int | None = None
    failure: type[BaseException] = PandocFailedError
    meanwhile: Callable[[], object] | None = None
    named: int = 0
    inputs: list[str] = field(default_factory=list)

    def converter(self) -> str:
        """Give the name, unless this is one of the first ``unnamed`` times."""
        self.named += 1
        if self.named <= self.unnamed:
            message = "pandoc: exit status 2"
            raise PandocFailedError(message)
        return self.name

    def convert(self, html: str) -> str:
        """Give the Markdown of ``html``, unless this is conversion number ``fails_at``."""
        if self.meanwhile is not None:
            self.meanwhile()
        self.inputs.append(html)
        if len(self.inputs) == self.fails_at:
            message = "pandoc: exit status 3"
            raise self.failure(message)
        return f"Markdown of {html}"


@pytest.fixture
def path(tmp_path: Path) -> Path:
    """Where runs keep their conversions, in a data folder that no run has made yet."""
    return tmp_path / "data" / "conversions.sqlite"


def key(name: str, html: str) -> str:
    """Name the conversion of ``html`` by the converter ``name``, as the plan says."""
    return hashlib.sha256(name.encode() + b"\0" + html.encode()).hexdigest()


def stored(path: Path) -> set[str]:
    """Give the keys of the conversions that the file holds."""
    with closing(sqlite3.connect(path)) as connection:
        return {each for (each,) in connection.execute("SELECT key FROM conversions")}


def rows(path: Path) -> set[tuple[str, str]]:
    """Give the conversions that the file holds, each by its source and its key."""
    with closing(sqlite3.connect(path)) as connection:
        return set(connection.execute("SELECT source, key FROM conversions"))


def page(path: Path, kind: str) -> slice:
    """Give where the root page of the file's ``table``, or of its ``index``, lies in it."""
    with closing(sqlite3.connect(path)) as connection:
        (root,) = connection.execute(
            "SELECT rootpage FROM sqlite_schema WHERE type = ?", (kind,)
        ).fetchone()
        (size,) = connection.execute("PRAGMA page_size").fetchone()
    return slice((root - 1) * size, root * size)


def run(
    path: Path, scripted: Scripted, texts: Iterable[str], source: str = SOURCE
) -> tuple[list[str], int, int]:
    """Convert ``texts`` in one run of ``source``; give their Markdown, and the counts.

    The counts are how many it converted, then how many it reused.
    """
    with conversions.opened(path, scripted.converter, scripted.convert, source=source) as cache:
        markdown = [cache.markdown(text) for text in texts]
        return markdown, cache.converted, cache.reused


def test_a_text_converted_twice_is_converted_once_then_reused(path: Path) -> None:
    """Criterion 2: within a run, then by the next, which converts nothing."""
    scripted = Scripted()
    assert run(path, scripted, [TEXTS[0], TEXTS[0]]) == (["Markdown of <p>a</p>"] * 2, 1, 1)
    assert run(path, scripted, [TEXTS[0]]) == (["Markdown of <p>a</p>"], 0, 1)
    assert scripted.inputs == [TEXTS[0]]


@pytest.mark.parametrize(
    ("name", "html"),
    [(NAME.replace("3.7.0.2", "3.7.0.3"), TEXTS[0]), (NAME, "<p>A</p>")],
    ids=["another converter", "one byte changed"],
)
def test_another_converter_or_one_byte_changed_is_a_miss(path: Path, name: str, html: str) -> None:
    """Criterion 2: the conversion kept is not given for an input that differs."""
    run(path, Scripted(), [TEXTS[0]])
    other = Scripted(name=name)
    assert run(path, other, [html]) == ([f"Markdown of {html}"], 1, 0)
    assert other.inputs == [html]


def test_a_text_that_fails_to_convert_raises_and_keeps_no_row(path: Path) -> None:
    """Criterion 2: neither converted nor reused, so that the next run converts it again."""
    failing = Scripted(fails_at=1)
    with conversions.opened(path, failing.converter, failing.convert, source=SOURCE) as cache:
        with pytest.raises(PandocFailedError, match="exit status 3"):
            cache.markdown(TEXTS[0])
        assert (cache.converted, cache.reused) == (0, 0)
    assert stored(path) == set()
    assert run(path, Scripted(), [TEXTS[0]])[1:] == (1, 0)


def test_the_converter_is_named_once_a_run(path: Path) -> None:
    """Criterion 3: four conversions, then four reused, ask for the name once a run."""
    scripted = Scripted()
    named = []
    for _ in range(2):
        run(path, scripted, TEXTS)
        named.append(scripted.named)
    assert named == [1, 2]


def test_a_converter_that_cannot_be_named_fails_each_conversion_and_is_asked_again(
    path: Path,
) -> None:
    """Criterion 3: unnamed twice, two conversions fail, converting nothing; then it is named."""
    scripted = Scripted(unnamed=2)
    with conversions.opened(path, scripted.converter, scripted.convert, source=SOURCE) as cache:
        for text in TEXTS[:2]:
            with pytest.raises(PandocFailedError, match="exit status 2"):
                cache.markdown(text)
        assert stored(path) == set()
        markdown = [cache.markdown(text) for text in TEXTS[2:]]
    assert markdown == ["Markdown of <p>c</p>", "Markdown of <p>d</p>"]
    assert (scripted.named, scripted.inputs) == (3, list(TEXTS[2:]))
    assert stored(path) == {key(NAME, text) for text in TEXTS[2:]}


def test_a_prune_keeps_exactly_the_conversions_that_its_run_used(path: Path) -> None:
    """Criterion 4: a, b and c kept; then a run uses b, c and d, and its prune deletes a."""
    scripted = Scripted()
    run(path, scripted, TEXTS[:3])
    with conversions.opened(path, scripted.converter, scripted.convert, source=SOURCE) as cache:
        for text in TEXTS[1:]:
            cache.markdown(text)
        assert cache.prune(remove=True) == 1
    assert stored(path) == {key(NAME, text) for text in TEXTS[1:]}


def test_a_prune_told_not_to_remove_deletes_nothing(path: Path) -> None:
    """Criterion 4: as a run that reports a problem removes no file, it removes no row."""
    scripted = Scripted()
    run(path, scripted, TEXTS[:3])
    with conversions.opened(path, scripted.converter, scripted.convert, source=SOURCE) as cache:
        cache.markdown(TEXTS[3])
        assert cache.prune(remove=False) == 0
    assert stored(path) == {key(NAME, text) for text in TEXTS}


def test_a_text_that_two_sources_convert_is_a_row_of_each_that_neither_prune_takes(
    path: Path,
) -> None:
    """Plan 030: each source looks up and prunes its own rows; another's stay.

    Confluence converts a and b, then Jira b and c, b again, since Confluence's row is not
    Jira's. Confluence then uses a alone, and prunes its b; Jira's b and c stay, and its
    next run converts nothing.
    """
    assert run(path, Scripted(), TEXTS[:2], "confluence")[1:] == (2, 0)
    assert run(path, Scripted(), TEXTS[1:3], "jira")[1:] == (2, 0)
    scripted = Scripted()
    with conversions.opened(
        path, scripted.converter, scripted.convert, source="confluence"
    ) as cache:
        cache.markdown(TEXTS[0])
        assert cache.prune(remove=True) == 1
    assert rows(path) == {
        ("confluence", key(NAME, TEXTS[0])),
        ("jira", key(NAME, TEXTS[1])),
        ("jira", key(NAME, TEXTS[2])),
    }
    assert run(path, Scripted(), TEXTS[1:3], "jira")[1:] == (0, 2)


def test_a_file_of_plan_039_s_two_columns_is_replaced_once(path: Path) -> None:
    """Plan 030: its rows name no source, though each holds the conversion asked for.

    The run converts every text again, and says once, by SQLite's error, that it replaced
    the file; the next reuses each.
    """
    path.parent.mkdir(parents=True)
    with closing(sqlite3.connect(path)) as connection:
        connection.execute(
            "CREATE TABLE conversions (key TEXT PRIMARY KEY, markdown TEXT NOT NULL)"
        )
        connection.executemany(
            "INSERT INTO conversions (key, markdown) VALUES (?, ?)",
            [(key(NAME, text), f"Markdown of {text}") for text in TEXTS],
        )
        connection.commit()
    with capture_logs() as events:
        assert run(path, Scripted(), TEXTS)[1:] == (4, 0)
        assert run(path, Scripted(), TEXTS)[1:] == (0, 4)
    assert events_named(events, "mirror.cache_replaced") == [
        {"reason": "SQLITE_ERROR", "log_level": "warning"}
    ]


def test_an_interrupted_run_keeps_the_conversions_it_made_for_the_next(path: Path) -> None:
    """Criterion 4: interrupted at its fourth conversion, a run keeps three, which are reused."""
    with pytest.raises(KeyboardInterrupt):
        run(path, Scripted(fails_at=4, failure=KeyboardInterrupt), TEXTS)
    assert stored(path) == {key(NAME, text) for text in TEXTS[:3]}
    again = Scripted()
    assert run(path, again, TEXTS)[1:] == (1, 3)
    assert again.inputs == [TEXTS[3]]


def test_a_file_of_random_bytes_is_replaced_and_says_so_by_sqlite_s_error(path: Path) -> None:
    """Criterion 8: the run converts everything; one warning, its reason alone; no -wal left."""
    path.parent.mkdir(parents=True)
    for suffix, seed in (("", 0), ("-wal", 1), ("-shm", 2)):
        noise = hashlib.shake_256(bytes([seed])).digest(8192)
        path.with_name(f"{path.name}{suffix}").write_bytes(noise)
    scripted = Scripted()
    with capture_logs() as events:
        assert run(path, scripted, TEXTS)[1:] == (4, 0)
    assert events_named(events, "mirror.cache_replaced") == [
        {"reason": "SQLITE_NOTADB", "log_level": "warning"}
    ]
    assert [each.name for each in path.parent.iterdir()] == [path.name]
    assert stored(path) == {key(NAME, text) for text in TEXTS}


def test_a_file_whose_index_root_is_zeroed_is_replaced(path: Path) -> None:
    """Criterion 8: the root page of the table's index overwritten, every text is converted."""
    run(path, Scripted(), TEXTS)
    data = bytearray(path.read_bytes())
    index = page(path, "index")
    data[index] = bytes(index.stop - index.start)
    path.write_bytes(data)
    scripted = Scripted()
    with capture_logs() as events:
        assert run(path, scripted, TEXTS)[1:] == (4, 0)
    assert events_named(events, "mirror.cache_replaced") == [
        {"reason": "SQLITE_CORRUPT", "log_level": "warning"}
    ]
    assert scripted.inputs == list(TEXTS)


def test_an_index_that_leads_one_key_to_another_s_row_is_replaced(path: Path) -> None:
    """Review of 039: rows a and b, and the index of a file of rows a and c, so c's key finds b.

    Each file's second row has the same place, so that the index copied over counts as
    many entries as there are rows, and only a check of each entry against its row sees
    it. Replaced, the file gives c's own Markdown.
    """
    run(path, Scripted(), TEXTS[:2])
    other = path.parent.parent / "other.sqlite"
    run(other, Scripted(), [TEXTS[0], TEXTS[2]])
    index = page(path, "index")
    assert page(other, "index") == index
    data = bytearray(path.read_bytes())
    data[index] = other.read_bytes()[index]
    path.write_bytes(data)
    with capture_logs() as events:
        assert run(path, Scripted(), TEXTS[2:3]) == (["Markdown of <p>c</p>"], 1, 0)
    assert events_named(events, "mirror.cache_replaced") == [
        {"reason": "integrity_check", "log_level": "warning"}
    ]


def change_key(path: Path) -> None:
    """Change a byte of a's key in the table's page, not in the index's; then write the header.

    Another connection writes the header, so that one already open reads the file again.
    """
    table = page(path, "table")
    data = path.read_bytes()
    at = data.index(key(NAME, TEXTS[0]).encode(), table.start, table.stop)
    with path.open("r+b") as file:
        file.seek(at)
        file.write(bytes([data[at] ^ 1]))
    with closing(sqlite3.connect(path)) as other:
        other.execute("PRAGMA user_version = 1")


def test_a_key_changed_in_its_row_alone_is_replaced(path: Path) -> None:
    """Review of 039: a quick check passes it, and the run's prune then failed."""
    run(path, Scripted(), TEXTS)
    change_key(path)
    scripted = Scripted()
    with capture_logs() as events:
        assert run(path, scripted, TEXTS)[1:] == (4, 0)
    assert events_named(events, "mirror.cache_replaced") == [
        {"reason": "integrity_check", "log_level": "warning"}
    ]


@pytest.mark.parametrize(
    ("offset", "reason"),
    [(18, "SQLITE_READONLY"), (47, "SQLITE_ERROR")],
    ids=["a write version to come", "a schema format to come"],
)
def test_a_header_that_sqlite_cannot_use_is_replaced(path: Path, offset: int, reason: str) -> None:
    """Review of 039: the header's write version, or its schema format, set to 255.

    SQLite reads the first, but may not write it; it cannot read the second at all.
    """
    run(path, Scripted(), TEXTS)
    data = bytearray(path.read_bytes())
    data[offset] = 0xFF
    path.write_bytes(data)
    scripted = Scripted()
    with capture_logs() as events:
        assert run(path, scripted, TEXTS)[1:] == (4, 0)
    assert events_named(events, "mirror.cache_replaced") == [
        {"reason": reason, "log_level": "warning"}
    ]


@pytest.mark.parametrize(
    ("text", "byte", "reason"),
    [
        (b"sqlite_autoindex_conversions_1", 0xFF, "UnicodeDecodeError"),
        (b"markdown TEXT", ord("l"), "SQLITE_ERROR"),
    ],
    ids=["an index's name no longer UTF-8", "a column renamed"],
)
def test_a_schema_whose_text_is_changed_is_replaced(
    path: Path, text: bytes, byte: int, reason: str
) -> None:
    """Review of 039: the first byte of a name in the schema's text, on the file's first page.

    SQLite's report of the first quotes a name that is no longer UTF-8 text; the second
    leaves a schema that SQLite reads, whose table has no column ``markdown``.
    """
    run(path, Scripted(), TEXTS)
    data = bytearray(path.read_bytes())
    data[data.index(text)] = byte
    path.write_bytes(data)
    scripted = Scripted()
    with capture_logs() as events:
        assert run(path, scripted, TEXTS)[1:] == (4, 0)
    assert events_named(events, "mirror.cache_replaced") == [
        {"reason": reason, "log_level": "warning"}
    ]


def misplace_index(path: Path) -> None:
    """Point the file's index at a page that is not there, as damage during a run would."""
    with closing(sqlite3.connect(path, isolation_level=None)) as other:
        (version,) = other.execute("PRAGMA schema_version").fetchone()
        other.execute("PRAGMA writable_schema = ON")
        other.execute("UPDATE sqlite_schema SET rootpage = 99 WHERE type = 'index'")
        other.execute(f"PRAGMA schema_version = {version + 1}")


@pytest.mark.parametrize(
    ("damage", "name"),
    [(misplace_index, "SQLITE_CORRUPT"), (change_key, "SQLITE_CORRUPT_INDEX")],
    ids=["an index misplaced", "a key changed in its row"],
)
def test_damage_found_during_a_run_raises_and_deletes_the_file(
    path: Path, damage: Callable[[Path], None], name: str
) -> None:
    """Review of 039: the run fails, and the next starts a new file, without a warning.

    The file is damaged once the run has checked it, while c is converted; then the run
    keeps c, and prunes a, which it did not use.
    """
    run(path, Scripted(), TEXTS[:2])
    damaging = Scripted(meanwhile=lambda: damage(path))

    def mirrored() -> None:
        with conversions.opened(path, damaging.converter, damaging.convert, source=SOURCE) as cache:
            for text in TEXTS[1:3]:
                cache.markdown(text)
            cache.prune(remove=True)

    with pytest.raises(sqlite3.DatabaseError) as raised:
        mirrored()
    assert raised.value.sqlite_errorname == name
    assert list(path.parent.iterdir()) == []
    with capture_logs() as events:
        assert run(path, Scripted(), TEXTS)[1:] == (4, 0)
    assert events_named(events, "mirror.cache_replaced") == []


def test_a_write_locked_past_the_wait_during_a_run_raises_and_keeps_the_file(
    path: Path, monkeypatch: MonkeyPatch
) -> None:
    """Review of 039: locked is not damaged, during a run as at its start."""
    run(path, Scripted(), TEXTS[:1])
    monkeypatch.setattr(conversions, "WAIT_S", WAIT_S)
    with closing(sqlite3.connect(path, isolation_level=None)) as other:
        locking = Scripted(meanwhile=lambda: other.execute("BEGIN IMMEDIATE"))
        with pytest.raises(sqlite3.OperationalError, match="locked"):
            run(path, locking, TEXTS[1:2])
    assert run(path, Scripted(), TEXTS[:1])[1:] == (0, 1)


def test_a_file_locked_past_the_wait_fails_the_run_and_is_kept(
    path: Path, monkeypatch: MonkeyPatch
) -> None:
    """Criterion 8: locked is not damaged; the run waits, then raises; the next one reuses."""
    run(path, Scripted(), TEXTS[:1])
    monkeypatch.setattr(conversions, "WAIT_S", WAIT_S)
    with closing(sqlite3.connect(path, isolation_level=None)) as other:
        other.execute("PRAGMA locking_mode = EXCLUSIVE")
        other.execute("BEGIN EXCLUSIVE")
        start = time.monotonic()
        with capture_logs() as events, pytest.raises(sqlite3.OperationalError, match="locked"):
            run(path, Scripted(), TEXTS[:1])
        waited = time.monotonic() - start
    assert waited >= WAIT_S
    assert events_named(events, "mirror.cache_replaced") == []
    assert run(path, Scripted(), TEXTS[:1])[1:] == (0, 1)


@pytest.mark.skipif(os.geteuid() == 0, reason="root writes a folder whatever its mode")
def test_a_sound_file_in_a_folder_the_run_may_not_write_fails_the_run_and_is_kept(
    path: Path,
) -> None:
    """Review of 039: SQLite may not write the file for want of its folder, not for its content.

    The run fails as SQLite says; the file stays as it was, and once the folder may be
    written, the next run reuses every conversion.
    """
    run(path, Scripted(), TEXTS)
    sound = path.read_bytes()
    path.parent.chmod(0o555)
    try:
        with capture_logs() as events, pytest.raises(sqlite3.OperationalError):
            run(path, Scripted(), TEXTS)
    finally:
        path.parent.chmod(0o755)
    assert events_named(events, "mirror.cache_replaced") == []
    assert path.read_bytes() == sound
    assert run(path, Scripted(), TEXTS)[1:] == (0, 4)


def test_a_run_keeps_its_conversions_while_another_reads_the_file(
    path: Path, monkeypatch: MonkeyPatch
) -> None:
    """In WAL mode, a reader in the middle of its read does not hold a writer back."""
    run(path, Scripted(), TEXTS[:1])
    monkeypatch.setattr(conversions, "WAIT_S", WAIT_S)
    with closing(sqlite3.connect(path, isolation_level=None)) as other:
        other.execute("BEGIN")
        other.execute("SELECT count(*) FROM conversions").fetchone()
        assert run(path, Scripted(), TEXTS[:2])[1:] == (1, 1)
    assert stored(path) == {key(NAME, text) for text in TEXTS[:2]}
