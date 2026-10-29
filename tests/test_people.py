"""Persons: names joined by account, alias, exact name and meeting, as plan 043 rules.

The names are made up: Robin Example, an account under two names; Sam Sample, the name
of two accounts; Alex Example, a name alone; the work log's first names. Every expected
person is written by hand from the plan's rules, its id from the plan's definition. The
alias file is read from a scratch folder, and refused by the plan's list; ``index`` reads
it from a scratch data directory, over the mirror of ``tests.mirrors.PERSONS``.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import closing
from dataclasses import replace
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from atlassian_offline_mcp.cli.main import main
from atlassian_offline_mcp.search.adapters.aliases import AliasFileError, read_aliases
from atlassian_offline_mcp.search.domain.people import (
    NOBODY,
    SEVERAL,
    UNHELD,
    Ambiguity,
    Joined,
    Joining,
    Person,
    Row,
    Spelling,
    by_alias,
    by_meeting,
    by_name,
    joined,
    name_key,
)
from tests.endpoint import nothing_listening
from tests.mirrors import PERSONS, write
from tests.test_cli import logged_as
from tests.test_observed import said

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from _pytest.capture import CaptureFixture
    from _pytest.monkeypatch import MonkeyPatch


def anchored(text: str) -> str:
    """Give a person's id as the plan defines it: p- and 16 hex digits of the SHA-256."""
    return "p-" + hashlib.sha256(text.encode()).hexdigest()[:16]


def day(number: int) -> datetime:
    """Give a day of October 2026, at midnight UTC."""
    return datetime(2026, 10, number, tzinfo=UTC)


def named(document: int, name: str) -> Row:
    """Give a row of the work log's: a participant or a speaker, without an account."""
    return Row(document, "participant", name, None, day(20))


ROBIN = anchored("account\nacct-0001")
SAM_2 = anchored("account\nacct-0002")
SAM_3 = anchored("account\nacct-0003")
SAM_ALONE = anchored("name\nsam sample")
ALEX_EXAMPLE = anchored("name\nalex example")
ALEX = anchored("name\nalex")
ROBIN_ALONE = anchored("name\nrobin")
ROBIN_OTHER = anchored("name\nrobin other")
# The documents, by rowid: meetings, then transcripts.
STAND_UP, REVIEW, PLANNING = 11, 12, 13
LINKED, UNLINKED, OTHER_UNLINKED, PLANNED, STOOD = 21, 22, 23, 24, 25
LINKS = {LINKED: {REVIEW}, PLANNED: {PLANNING}, STOOD: {STAND_UP}}
ACCOUNTS = (
    Row(1, "author", "Robin Example", "acct-0001", day(20)),
    Row(2, "creator", "Robin Sample", "acct-0001", day(21)),
    Row(3, "author", "Sam Sample", "acct-0002", day(19)),
    Row(4, "commenter", "Sam Sample", "acct-0003", day(19)),
)
ROWS = (
    *ACCOUNTS,
    named(STAND_UP, "robin  EXAMPLE"),
    named(STAND_UP, "Sam Sample"),
    named(STAND_UP, "Alex Example (not in the header)"),
    named(REVIEW, "Robin Example"),
    named(REVIEW, "Alex Example"),
    named(PLANNING, "Robin Example"),
    named(PLANNING, "Robin Other"),
    named(LINKED, "Robin"),
    named(LINKED, "Alex"),
    named(UNLINKED, "Robin"),
    named(UNLINKED, "Alex"),
    named(OTHER_UNLINKED, "Alex"),
    named(PLANNED, "Robin"),
    named(STOOD, "Sam"),
)
# The person of each of ROWS, without aliases.
PERSONS_OF_ROWS = (
    ROBIN,
    ROBIN,
    SAM_2,
    SAM_3,
    ROBIN,  # the one account of its key
    SAM_ALONE,  # the key of two accounts: ambiguous, a name alone
    ALEX_EXAMPLE,
    ROBIN,
    ALEX_EXAMPLE,
    ROBIN,
    ROBIN_OTHER,
    ROBIN,  # by its meeting, whose Robin Example is Robin's account
    ALEX_EXAMPLE,  # by its meeting, a name alone
    ROBIN_ALONE,  # no meeting
    ALEX,
    ALEX,
    ROBIN_ALONE,  # its meeting has two Robins: ambiguous, a name alone
    SAM_ALONE,  # by its meeting, whose Sam Sample is a name alone
)


def account(person: str, *names: str) -> Person:
    """Give an account's person: its spellings are its account's names alone."""
    return Person(
        person, names[0], tuple(Spelling(name, name_key(name), "account") for name in names)
    )


def test_a_key_ignores_case_accents_and_spaces() -> None:
    """Case, accents, compatibility forms and runs of white space make no other key."""
    assert name_key("Hélène Example") == "helene example"
    assert name_key("helene  example") == "helene example"
    assert name_key("He\u0301le\u0300ne Example") == "helene example"  # written decomposed
    assert name_key("  ROBIN\tExample\n") == "robin example"
    assert name_key("\uff32\uff4f\uff42\uff49\uff4e") == "robin"  # full-width letters
    assert name_key("\U0001d411\U0001d428\U0001d41b\U0001d422\U0001d427") == "robin"  # bold
    assert name_key("Kim Straße") == "kim strasse"
    assert name_key("\u1fbc") == "\u03b1\u03b9"  # casefolded first: the iota subscript is a letter


def test_a_key_drops_a_trailing_part_in_brackets() -> None:
    """An annotation after a name is not part of its key; a name in brackets alone is."""
    assert name_key("Kim (not in the header)") == "kim"
    assert name_key("Alex Example(guest)") == "alex example"
    assert name_key("(Guest)") == "(guest)"


@pytest.mark.parametrize(
    ("one", "other"),
    [
        ("\u30ac", "\u30ab"),  # ga and ka: a kana's voicing mark makes another letter
        ("Robin", "Robin Example"),
        ("(guest) Kim", "Kim"),  # brackets that do not end the name
        ("Kim (a) (b)", "Kim"),  # one trailing part alone is dropped
    ],
)
def test_a_key_keeps_what_makes_another_name(one: str, other: str) -> None:
    """What tells two names apart stays in their keys."""
    assert name_key(one) != name_key(other)


def test_by_alias_gives_a_name_the_person_its_alias_means() -> None:
    """Rule 2 alone: by the name's key; a target that names nobody or several gives none."""
    rows = (*ACCOUNTS, named(UNLINKED, "Robin"), named(UNLINKED, "Alex"), named(UNLINKED, "Kim"))
    aliases = {"Robin": "Robin Example", "Alex": "Nobody", "Kim": "Sam Sample"}
    joining = Joining(rows, {}, aliases)
    assert by_alias(named(UNLINKED, "ROBIN"), joining) == ROBIN
    assert by_alias(named(UNLINKED, "Alex"), joining) is None
    assert by_alias(named(UNLINKED, "Kim"), joining) is None
    assert by_alias(named(UNLINKED, "Robin Other"), joining) is None


def test_by_name_joins_a_name_to_the_one_account_of_its_key() -> None:
    """Rule 3 alone: any name of one account joins it; the name of two is ambiguous."""
    joining = Joining(ACCOUNTS, {}, {})
    assert by_name(named(STAND_UP, "robin  EXAMPLE"), joining) == ROBIN
    assert by_name(named(STAND_UP, "Robin Sample"), joining) == ROBIN
    assert by_name(named(STAND_UP, "Sam Sample"), joining) == Ambiguity(
        "Sam Sample", frozenset({SAM_2, SAM_3})
    )
    assert by_name(named(STAND_UP, "Alex Example"), joining) is None


def test_by_meeting_joins_a_speaker_to_the_one_person_its_word_begins() -> None:
    """Rule 4 alone: a one-word speaker, the first word of its meetings' participants.

    The participants' persons are given, as the other rules would have joined them: two
    participants of one person are one; two persons make the speaker ambiguous.
    """
    offsite, linked_to_offsite = 14, 26
    meetings = (
        named(REVIEW, "Robin Example"),
        named(REVIEW, "Alex Example"),
        named(PLANNING, "Robin Example"),
        named(PLANNING, "Robin Other"),
        named(offsite, "Robin Example"),
        named(offsite, "Robin Example (late)"),
    )
    links = {LINKED: {REVIEW}, PLANNED: {PLANNING}, linked_to_offsite: {offsite}}
    joining = Joining(meetings, links, {})
    persons = (ROBIN, ALEX_EXAMPLE, ROBIN, ROBIN_OTHER, ROBIN, ROBIN)
    joining.persons |= dict(zip(meetings, persons, strict=True))
    assert by_meeting(named(LINKED, "robin"), joining) == ROBIN
    assert by_meeting(named(linked_to_offsite, "Robin"), joining) == ROBIN
    assert by_meeting(named(PLANNED, "Robin"), joining) == Ambiguity(
        "Robin", frozenset({ROBIN, ROBIN_OTHER})
    )
    assert by_meeting(named(UNLINKED, "Robin"), joining) is None
    assert by_meeting(named(LINKED, "Example"), joining) is None  # not a first word
    assert by_meeting(named(LINKED, "Alex Example"), joining) is None  # not one word


def test_every_name_joins_its_person_as_the_rules_say() -> None:
    """Accounts, exact names, meetings and names alone, without aliases.

    Robin's account is one person under both names, named as on its newest document;
    the two Sam Sample accounts are two, and the meeting's Sam Sample neither, reported;
    a meeting's Robin and Sam join by their meetings, as their participants joined;
    Alex is one person by name alone across two transcripts, as is Alex Example with or
    without its annotation, whose spellings tie, so the first document names it.
    """
    expected = Joined(
        persons=tuple(
            sorted(
                (
                    Person(
                        ROBIN,
                        "Robin Sample",
                        (
                            Spelling("Robin", "robin", "meeting"),
                            Spelling("Robin Example", "robin example", "account"),
                            Spelling("Robin Example", "robin example", "name"),
                            Spelling("Robin Sample", "robin sample", "account"),
                            Spelling("robin  EXAMPLE", "robin example", "name"),
                        ),
                    ),
                    account(SAM_2, "Sam Sample"),
                    account(SAM_3, "Sam Sample"),
                    Person(
                        SAM_ALONE,
                        "Sam Sample",
                        (
                            Spelling("Sam", "sam", "meeting"),
                            Spelling("Sam Sample", "sam sample", "name"),
                        ),
                    ),
                    Person(
                        ALEX_EXAMPLE,
                        "Alex Example (not in the header)",
                        (
                            Spelling("Alex", "alex", "meeting"),
                            Spelling("Alex Example", "alex example", "name"),
                            Spelling("Alex Example (not in the header)", "alex example", "name"),
                        ),
                    ),
                    Person(ALEX, "Alex", (Spelling("Alex", "alex", "name"),)),
                    Person(ROBIN_ALONE, "Robin", (Spelling("Robin", "robin", "name"),)),
                    Person(
                        ROBIN_OTHER,
                        "Robin Other",
                        (Spelling("Robin Other", "robin other", "name"),),
                    ),
                ),
                key=lambda person: person.id,
            )
        ),
        of=dict(zip(ROWS, PERSONS_OF_ROWS, strict=True)),
        ambiguous=(
            Ambiguity("Robin", frozenset({ROBIN, ROBIN_OTHER})),
            Ambiguity("Sam Sample", frozenset({SAM_2, SAM_3})),
        ),
        unused=(),
    )
    assert joined(ROWS, LINKS, {}) == expected


def test_an_account_named_on_two_documents_of_one_date_takes_the_first() -> None:
    """Ties between an account's newest documents go to the first row in order."""
    rows = (
        Row(2, "author", "Robin Sample", "acct-0001", day(20)),
        Row(1, "author", "Robin Example", "acct-0001", day(20)),
    )
    assert joined(rows, {}, {}).persons[0].name == "Robin Example"


def test_a_name_alone_is_named_by_its_most_frequent_spelling_ties_to_the_first() -> None:
    """The spelling of the most rows names a person by name alone; a tie, the first row."""
    frequent = (named(UNLINKED, "alex"), named(OTHER_UNLINKED, "Alex"), named(PLANNED, "Alex"))
    assert joined(frequent, {}, {}).persons[0].name == "Alex"
    tied = (named(OTHER_UNLINKED, "Alex"), named(UNLINKED, "alex"))
    assert joined(tied, {}, {}).persons[0].name == "alex"


def test_an_alias_joins_a_name_without_a_meeting_to_its_target() -> None:
    """With "Robin" = "Robin Example", every Robin without an account is Robin's account.

    Before any meeting: the linked transcript's Robin joins by the alias too, and the
    planning's is no longer ambiguous.
    """
    result = joined(ROWS, LINKS, {"Robin": "Robin Example"})
    assert result.of[named(UNLINKED, "Robin")] == ROBIN
    assert result.of[named(PLANNED, "Robin")] == ROBIN
    robin = next(person for person in result.persons if person.id == ROBIN)
    assert Spelling("Robin", "robin", "alias") in robin.names
    assert Spelling("Robin", "robin", "meeting") not in robin.names
    assert ROBIN_ALONE not in {person.id for person in result.persons}
    assert [ambiguity.name for ambiguity in result.ambiguous] == ["Sam Sample"]
    assert result.unused == ()


def test_an_alias_to_an_account_s_id_settles_a_name_of_two_accounts() -> None:
    """The meeting's Sam Sample joins acct-0003 and is no longer reported; Sam follows it.

    Sam, the speaker, joins by its meeting the person that the alias gave the meeting's
    Sam Sample.
    """
    result = joined(ROWS, LINKS, {"Sam Sample": SAM_3})
    assert result.of[named(STAND_UP, "Sam Sample")] == SAM_3
    assert result.of[named(STOOD, "Sam")] == SAM_3
    assert next(person for person in result.persons if person.id == SAM_3) == Person(
        SAM_3,
        "Sam Sample",
        (
            Spelling("Sam", "sam", "meeting"),
            Spelling("Sam Sample", "sam sample", "account"),
            Spelling("Sam Sample", "sam sample", "alias"),
        ),
    )
    assert SAM_ALONE not in {person.id for person in result.persons}
    assert [ambiguity.name for ambiguity in result.ambiguous] == ["Robin"]


def test_an_alias_that_cannot_join_is_reported_and_changes_nothing() -> None:
    """A target of nobody, by name or id, or of several; a key held by no name alone.

    An account's name is the site's: an alias of it alone joins nothing.
    """
    aliases = {
        "Alex": "Nobody",
        "Robin Other": "p-0123456789abcdef",
        "Sam": "Sam Sample",
        "Jo Placeholder": "Robin Example",
        "Robin Sample": "Alex Example",
    }
    result = joined(ROWS, LINKS, aliases)
    assert [(alias.name, alias.key, alias.reason) for alias in result.unused] == [
        ("Alex", "alex", NOBODY),
        ("Robin Other", "robin other", NOBODY),
        ("Sam", "sam", SEVERAL),
        ("Jo Placeholder", "jo placeholder", UNHELD),
        ("Robin Sample", "robin sample", UNHELD),
    ]
    assert replace(result, unused=()) == joined(ROWS, LINKS, {})


def test_an_alias_moves_the_names_without_an_account_alone() -> None:
    """With "Robin Example" = "Alex Example", the meetings' Robins go; the issue's stays."""
    result = joined(ROWS, LINKS, {"Robin Example": "Alex Example"})
    assert result.of[ACCOUNTS[0]] == ROBIN
    assert result.of[named(STAND_UP, "robin  EXAMPLE")] == ALEX_EXAMPLE
    assert result.of[named(REVIEW, "Robin Example")] == ALEX_EXAMPLE


def test_a_person_by_name_alone_that_an_alias_made_is_named_as_its_target_is_written() -> None:
    """The target as written names the person, not its most frequent spelling.

    By the person's id, the most frequent spelling names it still: Alex, of three rows.
    """
    by_target = joined(ROWS, LINKS, {"Alex": "alex EXAMPLE"})
    assert by_target.of[named(UNLINKED, "Alex")] == ALEX_EXAMPLE
    alex_example = next(person for person in by_target.persons if person.id == ALEX_EXAMPLE)
    assert alex_example.name == "alex EXAMPLE"
    by_id = joined(ROWS, LINKS, {"Alex": ALEX_EXAMPLE})
    assert by_id.of[named(OTHER_UNLINKED, "Alex")] == ALEX_EXAMPLE
    assert next(person for person in by_id.persons if person.id == ALEX_EXAMPLE).name == "Alex"


def test_of_two_aliases_naming_one_person_the_first_names_it() -> None:
    """Two targets written apart, of one key: the first alias in the file's order wins."""
    aliases = {"Alex": "alex EXAMPLE", "Kim": "Alex Example"}
    result = joined((*ROWS, named(UNLINKED, "Kim")), LINKS, aliases)
    assert next(person for person in result.persons if person.id == ALEX_EXAMPLE).name == (
        "alex EXAMPLE"
    )


def test_aliases_are_not_chained() -> None:
    """An alias's target is looked up without the aliases: Alex joins Robin Other's name.

    Robin Other itself goes to Robin's account by its own alias, written first.
    """
    result = joined(ROWS, LINKS, {"Robin Other": "Robin Example", "Alex": "Robin Other"})
    assert result.of[named(PLANNING, "Robin Other")] == ROBIN
    assert result.of[named(UNLINKED, "Alex")] == ROBIN_OTHER
    robin_other = next(person for person in result.persons if person.id == ROBIN_OTHER)
    assert robin_other == Person(ROBIN_OTHER, "Robin Other", (Spelling("Alex", "alex", "alias"),))


def test_an_account_s_name_comes_before_a_meeting_s_participant() -> None:
    """Rule 3 before rule 4: a speaker of an account's one-word name joins the account."""
    robin = Row(5, "author", "Robin", "acct-0004", day(20))
    result = joined((*ROWS, robin), LINKS, {})
    assert result.of[named(LINKED, "Robin")] == anchored("account\nacct-0004")


def test_a_transcript_before_its_meeting_joins_by_it() -> None:
    """A transcript of a lower rowid than its meeting's is joined after the meeting."""
    early, late = 5, 30
    rows = (named(early, "Robin"), named(late, "Robin Example"), *ACCOUNTS)
    assert joined(rows, {early: {late}}, {}).of[named(early, "Robin")] == ROBIN


def test_a_name_is_reported_once_with_every_person_it_could_be() -> None:
    """Robin of two transcripts, each of a meeting of two Robins: one name, three persons."""
    retro, linked_to_retro = 14, 26
    rows = (*ROWS, named(retro, "Robin Example"), named(retro, "Robin Third"))
    result = joined(
        (*rows, named(linked_to_retro, "Robin")), LINKS | {linked_to_retro: {retro}}, {}
    )
    robin_third = anchored("name\nrobin third")
    assert result.ambiguous[0] == Ambiguity("Robin", frozenset({ROBIN, ROBIN_OTHER, robin_third}))


@pytest.mark.parametrize(
    "rows",
    [
        ROWS[::-1],
        ROWS[9:] + ROWS[:9],
        tuple(sorted(ROWS, key=lambda row: (row.name, -row.document))),
        ROWS + ROWS,
    ],
    ids=["reversed", "rotated", "by name", "twice"],
)
def test_the_result_is_the_same_for_the_rows_in_any_order(rows: tuple[Row, ...]) -> None:
    """Transcripts before their meetings, ties in another order, a row twice: no change."""
    aliases = {"Sam Sample": SAM_3, "Alex": "alex EXAMPLE"}
    assert joined(rows, LINKS, aliases) == joined(ROWS, LINKS, aliases)


def test_an_alias_file_gives_each_name_and_its_target_as_written(tmp_path: Path) -> None:
    """Names and targets as written, in the file's order; 200 characters are not too many."""
    path = tmp_path / "aliases.toml"
    long = "R" * 200
    path.write_text(
        "# Who each name means.\n"
        '"Sam" = "Sam Sample"\n'
        f'"Robin" = "{SAM_3}"\n'
        '"Hélène" = "helene  EXAMPLE"\n'
        f'"{long}" = "{long}"\n',
        encoding="utf-8",
    )
    assert list(read_aliases(path).items()) == [
        ("Sam", "Sam Sample"),
        ("Robin", SAM_3),
        ("Hélène", "helene  EXAMPLE"),
        (long, long),
    ]


def test_no_alias_file_gives_no_alias(tmp_path: Path) -> None:
    """The file is the user's, and optional: without it, no name has an alias."""
    assert read_aliases(tmp_path / "aliases.toml") == {}


@pytest.mark.parametrize(
    ("written", "names", "why"),
    [
        ('"" = "Sam Sample"\n', [""], "the name is empty"),
        ('" " = "Sam Sample"\n', [" "], "the name is empty"),
        ('"Sam" = ""\n', ["Sam"], "its target is empty"),
        ('"Sam\\nSample" = "Sam Sample"\n', ["Sam\nSample"], "the name holds a line break"),
        ('"Sam\\u2028" = "Sam Sample"\n', ["Sam\u2028"], "the name holds a line break"),
        ('"Sam" = """Sam\nSample"""\n', ["Sam"], "its target holds a line break"),
        ('"Sam" = "Sam Sample\\r"\n', ["Sam"], "its target holds a line break"),
        (f'"{"R" * 201}" = "Robin"\n', ["R" * 201], "the name is longer than 200"),
        (f'"Robin" = "{"R" * 201}"\n', ["Robin"], "its target is longer than 200"),
        ('[Sam]\nname = "Sam Sample"\n', ["Sam"], "a table"),
        ('"Sam" = { name = "Sam Sample" }\n', ["Sam"], "a table"),
        ('"Sam" = 1\n', ["Sam"], "not text"),
        ('"Sam" = ["Sam Sample"]\n', ["Sam"], "not text"),
        ('"Sam" = "Sam Sample"\n"sam" = "Sam Other"\n', ["Sam", "sam"], "one name"),
        (
            '"Hélène" = "Sam Sample"\n"helene (guest)" = "Sam"\n',
            ["Hélène", "helene (guest)"],
            "one name",
        ),
    ],
    ids=[
        "empty name",
        "blank name",
        "empty target",
        "line feed in a name",
        "line separator in a name",
        "line feed in a target",
        "carriage return in a target",
        "name of 201 characters",
        "target of 201 characters",
        "table",
        "inline table",
        "number",
        "array",
        "two names of one key",
        "two names of one key, by accent and annotation",
    ],
)
def test_an_alias_file_off_its_rules_is_refused_naming_it_and_the_alias(
    tmp_path: Path, written: str, names: list[str], why: str
) -> None:
    """Each refusal names the file and each name at fault, on one line, and says why."""
    path = tmp_path / "aliases.toml"
    path.write_text(written, encoding="utf-8")
    with pytest.raises(AliasFileError) as refusal:
        read_aliases(path)
    message = str(refusal.value)
    assert message.startswith(f"{path}: ")
    assert all(repr(name) in message for name in names)
    assert why in message
    assert message.splitlines() == [message]


@pytest.mark.parametrize(
    "written",
    [b'\xff\xfe"Sam" = "Sam Sample"\n', b"Sam = \n", b'"Sam" = "Sam Sample"\nSam = "x"\n'],
    ids=["not UTF-8", "not TOML", "one key twice"],
)
def test_an_alias_file_that_is_not_utf_8_toml_is_refused_naming_it(
    tmp_path: Path, written: bytes
) -> None:
    """A file that is not UTF-8 TOML holds no alias that could be named: the file is."""
    path = tmp_path / "aliases.toml"
    path.write_bytes(written)
    with pytest.raises(AliasFileError, match="not UTF-8 TOML") as refusal:
        read_aliases(path)
    assert str(refusal.value).startswith(f"{path}: ")


def test_an_alias_file_that_cannot_be_read_raises_os_error(tmp_path: Path) -> None:
    """A folder in the file's place is no alias file, nor a missing one."""
    (tmp_path / "aliases.toml").mkdir()
    with pytest.raises(IsADirectoryError):
        read_aliases(tmp_path / "aliases.toml")


@pytest.fixture
def data(tmp_path: Path, monkeypatch: MonkeyPatch) -> Path:
    """Give a scratch home, whose log files a test reads, and a data directory of PERSONS."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    for front in PERSONS:
        write(tmp_path / "data" / "docs", front)
    return tmp_path / "data"


def index(
    data: Path, capsys: CaptureFixture[str], settings: str = 'search_mode = "lexical"\n'
) -> tuple[int, str]:
    """Run ``index`` on the data directory, by words alone unless the settings say otherwise.

    Give its exit status and stderr.
    """
    config = data.parent / "config.toml"
    config.write_text(settings, encoding="utf-8")
    status = main(["index", "--yes", "--config", str(config), "--data-dir", str(data)])
    return status, capsys.readouterr().err


def test_index_joins_by_the_alias_file_and_warns_of_what_it_left_apart(
    data: Path, capsys: CaptureFixture[str]
) -> None:
    """Plan 043, criteria 3 and 5, by the command: a build with both warnings exits 0.

    The alias of Robin settles the planning's Robin, so that Sam Sample, of two accounts,
    is the one name warned of, with how many persons it could be; the alias whose key no
    name holds is warned of by its name, its key and why. Robin by name alone is gone.
    """
    aliases = '"Robin" = "Robin Example"\n"Jo Placeholder" = "Robin Example"\n'
    (data / "aliases.toml").write_text(aliases, encoding="utf-8")
    status, err = index(data, capsys)
    assert status == 0
    assert [each for each in said(err) if each[0] == "warning"] == [
        ("warning", "index.person_ambiguous"),
        ("warning", "index.alias_unused"),
    ]
    home = data.parent / "home"
    (ambiguous,) = logged_as(home, "index.person_ambiguous")
    assert (ambiguous["spelling"], ambiguous["people"]) == ("Sam Sample", 2)
    (unused,) = logged_as(home, "index.alias_unused")
    assert (unused["alias"], unused["key"], unused["reason"]) == (
        "Jo Placeholder",
        "jo placeholder",
        UNHELD,
    )
    (built,) = logged_as(home, "index.built")
    # Robin by name alone is gone; the other seven persons stay.
    persons = {ROBIN, SAM_2, SAM_3, SAM_ALONE, ALEX_EXAMPLE, ALEX, ROBIN_OTHER}
    assert built["people"] == len(persons)
    with closing(sqlite3.connect(data / "index.sqlite")) as connection:
        robins = connection.execute("SELECT DISTINCT person FROM people WHERE name = 'Robin'")
        assert robins.fetchall() == [(ROBIN,)]


@pytest.mark.parametrize(
    ("place", "why"),
    [
        (
            lambda path: path.write_text('"Sam" = "Sam Sample"\n"sam" = "Sam Other"\n', "utf-8"),
            "'Sam' and 'sam' are one name",
        ),
        (lambda path: path.write_text('"Sam" = 1\n', "utf-8"), "'Sam': its target is not text"),
        (lambda path: path.write_bytes(b"Sam = \n"), "not UTF-8 TOML"),
        (lambda path: path.mkdir(), "Is a directory"),
    ],
    ids=["two names of one key", "a number", "not TOML", "a folder"],
)
def test_index_over_an_alias_file_it_refuses_exits_1_and_keeps_the_index(
    data: Path, capsys: CaptureFixture[str], place: Callable[[Path], object], why: str
) -> None:
    """Plan 043, criterion 3: nothing is built, index.not_built naming the file and why.

    The index in place stays as it was, byte for byte.
    """
    assert index(data, capsys)[0] == 0
    before = (data / "index.sqlite").read_bytes()
    path = data / "aliases.toml"
    place(path)
    status, err = index(data, capsys)
    assert status == 1
    assert ("error", "index.not_built") in said(err)
    (failed,) = logged_as(data.parent / "home", "index.not_built")
    assert str(path.resolve()) in str(failed["reason"])
    assert why in str(failed["reason"])
    assert (data / "index.sqlite").read_bytes() == before


def test_a_refused_alias_file_stops_a_build_before_the_endpoint_is_asked(
    data: Path, capsys: CaptureFixture[str]
) -> None:
    """By meaning, with nothing listening: the alias file's refusal is the reason given."""
    (data / "aliases.toml").write_text('"Sam" = 1\n', encoding="utf-8")
    with nothing_listening() as url:
        settings = f'search_mode = "hybrid"\nembedding_url = {json.dumps(url)}\n'
        status, _ = index(data, capsys, settings)
    assert status == 1
    (failed,) = logged_as(data.parent / "home", "index.not_built")
    assert str(failed["reason"]).endswith(
        "'Sam': its target is not text; write a name or an id in quotes"
    )
    assert "hint" not in failed
