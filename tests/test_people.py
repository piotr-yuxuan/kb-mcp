"""Persons: mentions joined by identity, alias, name key, attendance and name.

The rules are those of the concepts page, as plans 043 and 058 build them. The names are
made up: Robin Example, an identity under two names; Sam Sample, the name of two
identities; Alex Example, a name alone; the work log's first names. Every expected
person is written by hand from the rules, its id from the plans' definition. The
alias file is read from a scratch folder, and refused by the plan's list; ``index`` reads
it from a scratch data directory, over the mirror of ``tests.mirrors.PERSONS``.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import closing
from copy import replace
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from kb_mcp.cli.main import main
from kb_mcp.search.adapters.aliases import AliasFileError, read_aliases
from kb_mcp.search.domain.people import (
    NOBODY,
    SEVERAL,
    UNHELD,
    UNOWNED,
    Ambiguity,
    Joined,
    Joining,
    Person,
    PersonRow,
    Spelling,
    by_alias,
    by_attendance,
    by_name,
    joined,
    name_key,
    written_key,
)
from tests.endpoint import nothing_listening
from tests.mirrors import PERSONS, worklog_document, write
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


def named(document: int, name: str) -> PersonRow:
    """Give a row of the work log's: a participant or a speaker, without an account."""
    return PersonRow(
        document=document, role="participant", name=name, identity=None, updated=day(20)
    )


ROBIN = anchored("account\nacct-0001")
SAM_2 = anchored("account\nacct-0002")
SAM_3 = anchored("account\nacct-0003")
SAM_ALONE = anchored("name\nsam sample")
ALEX_EXAMPLE = anchored("name\nalex example")
ALEX = anchored("name\nalex")
ROBIN_ALONE = anchored("name\nrobin")
ROBIN_OTHER = anchored("name\nrobin other")
# The documents, by number: meetings, then transcripts.
STAND_UP, REVIEW, PLANNING = 11, 12, 13
LINKED, UNLINKED, OTHER_UNLINKED, PLANNED, STOOD = 21, 22, 23, 24, 25
LINKS = {LINKED: {REVIEW}, PLANNED: {PLANNING}, STOOD: {STAND_UP}}
ACCOUNTS = (
    PersonRow(
        document=1,
        role="author",
        name="Robin Example",
        identity="atlassian:acct-0001",
        updated=day(20),
    ),
    PersonRow(
        document=2,
        role="creator",
        name="Robin Sample",
        identity="atlassian:acct-0001",
        updated=day(21),
    ),
    PersonRow(
        document=3,
        role="author",
        name="Sam Sample",
        identity="atlassian:acct-0002",
        updated=day(19),
    ),
    PersonRow(
        document=4,
        role="commenter",
        name="Sam Sample",
        identity="atlassian:acct-0003",
        updated=day(19),
    ),
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
        id=person,
        name=names[0],
        spellings=tuple(
            Spelling(name=name, name_key=name_key(name), how="identity") for name in names
        ),
    )


@pytest.mark.parametrize(
    ("identity", "former"),
    [
        ("atlassian:acct-0001", "p-32fd96c11bada084"),
        ("atlassian:557058:0f1e2d3c-4b5a-6978-8796-a5b4c3d2e1f0", "p-73e4d5e8d3110c05"),
    ],
    ids=["an account id", "an account id with a colon"],
)
def test_an_atlassian_identity_keeps_the_id_that_its_account_had(
    identity: str, former: str
) -> None:
    """Plan 058, criterion 2: each literal is the id that the former code gave the account.

    Computed by ``person_id("account", value)`` before identities had an issuer.
    """
    row = PersonRow(document=1, role="author", name="Robin", identity=identity, updated=day(20))
    assert joined((row,), {}, {}).of[row] == former


@pytest.mark.parametrize(
    "identities",
    [("atlassian:acct-0001", "elsewhere:acct-0001"), ("atlassian:qm:5f1a", "qm:5f1a")],
    ids=["an equal value", "an Atlassian value that writes the other's issuer"],
)
def test_another_issuer_s_identity_is_another_person(identities: tuple[str, str]) -> None:
    """Two issuers' identities never collide: the other's hashes under its own anchor.

    An Atlassian account id may hold a colon, so that ``atlassian:qm:5f1a`` holds the
    text of the issuer ``qm``'s ``5f1a``; the former hashes as an account id did.
    """
    rows = tuple(
        PersonRow(document=1, role="commenter", name="Robin", identity=identity, updated=day(20))
        for identity in identities
    )
    result = joined(rows, {}, {})
    atlassian, other = identities
    assert [result.of[row] for row in rows] == [
        anchored(f"account\n{atlassian.removeprefix('atlassian:')}"),
        anchored(f"identity\n{other}"),
    ]


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


def test_a_written_key_keeps_the_annotation() -> None:
    """The same folds as the key's, the part in brackets kept."""
    assert written_key("Kim  (Not in the HEADER)") == "kim (not in the header)"
    assert written_key("Hélène Example") == name_key("Hélène Example")


@pytest.mark.parametrize("name", ["Kim(not in the header)", "Kim ( not in the header )"])
def test_a_written_key_writes_one_annotation_however_it_is_spaced(name: str) -> None:
    """No space before the brackets, or spaces within them, write the same annotation."""
    assert written_key(name) == "kim (not in the header)"


def test_one_annotation_spaced_two_ways_is_one_person() -> None:
    """Kim with one annotation, written three ways: one person, as with one spelling.

    Two annotations would keep the names apart; the spaces make none.
    """
    rows = (
        named(STAND_UP, "Kim"),
        named(REVIEW, "Kim (not in the header)"),
        named(PLANNING, "Kim(not in the header)"),
        named(UNLINKED, "Kim ( not in the header )"),
    )
    result = joined(rows, {}, {})
    assert [person.id for person in result.persons] == [anchored("name\nkim")]
    assert result.ambiguous == ()


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
    """Rule 2 alone: by the name's key; a value that names nobody or several gives none."""
    rows = (*ACCOUNTS, named(UNLINKED, "Robin"), named(UNLINKED, "Alex"), named(UNLINKED, "Kim"))
    aliases = {"Robin": "Robin Example", "Alex": "Nobody", "Kim": "Sam Sample"}
    joining = Joining(rows, {}, aliases)
    assert by_alias(named(UNLINKED, "ROBIN"), joining) == ROBIN
    assert by_alias(named(UNLINKED, "Alex"), joining) is None
    assert by_alias(named(UNLINKED, "Kim"), joining) is None
    assert by_alias(named(UNLINKED, "Robin Other"), joining) is None


def test_by_name_joins_a_name_to_the_one_identity_of_its_key() -> None:
    """Rule 3 alone: any name of one account joins it; the name of two is ambiguous."""
    joining = Joining(ACCOUNTS, {}, {})
    assert by_name(named(STAND_UP, "robin  EXAMPLE"), joining) == ROBIN
    assert by_name(named(STAND_UP, "Robin Sample"), joining) == ROBIN
    assert by_name(named(STAND_UP, "Sam Sample"), joining) == Ambiguity(
        name="Sam Sample", persons=frozenset({SAM_2, SAM_3})
    )
    assert by_name(named(STAND_UP, "Alex Example"), joining) is None


def test_by_attendance_joins_a_speaker_to_the_one_person_whose_first_word_it_is() -> None:
    """Rule 4 alone: a one-word speaker, the whole first word of its meetings' participants.

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
    assert by_attendance(named(LINKED, "robin"), joining) == ROBIN
    assert by_attendance(named(linked_to_offsite, "Robin"), joining) == ROBIN
    assert by_attendance(named(PLANNED, "Robin"), joining) == Ambiguity(
        name="Robin", persons=frozenset({ROBIN, ROBIN_OTHER})
    )
    assert by_attendance(named(UNLINKED, "Robin"), joining) is None
    assert by_attendance(named(LINKED, "Example"), joining) is None  # not a first word
    assert by_attendance(named(LINKED, "Rob"), joining) is None  # a first word's start alone
    assert by_attendance(named(LINKED, "Alex Example"), joining) is None  # not one word


def test_attendance_joins_participants_to_participants_alone() -> None:
    """Rule 4 reads the role participant, never a document's type or another role.

    A one-word author of a document whose summary names Robin Example as a participant
    joins no one by attendance, nor does a one-word participant whose summary names
    Robin Example as its author alone.
    """
    summary, summarised, authored, by_author = 31, 32, 33, 34
    rows = (
        named(summary, "Robin Example"),
        replace(named(summarised, "Robin"), role="author"),
        replace(named(authored, "Robin Example"), role="author"),
        named(by_author, "Robin"),
    )
    joining = Joining(rows, {summarised: {summary}, by_author: {authored}}, {})
    robin_example = anchored("name\nrobin example")
    joining.persons |= {rows[0]: robin_example, rows[2]: robin_example}
    assert by_attendance(rows[1], joining) is None
    assert by_attendance(rows[3], joining) is None


def test_a_speaker_whose_word_only_begins_a_participant_s_is_a_name_alone() -> None:
    """Rob, in the review's transcript, is not its Robin Example: words compare whole.

    Joining them would quote one colleague as another, as plan 043 rejects.
    """
    rob = anchored("name\nrob")
    result = joined((*ROWS, named(LINKED, "Rob")), LINKS, {})
    assert result.of[named(LINKED, "Rob")] == rob
    assert (
        Person(id=rob, name="Rob", spellings=(Spelling(name="Rob", name_key="rob", how="name"),))
        in result.persons
    )


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
                        id=ROBIN,
                        name="Robin Sample",
                        spellings=(
                            Spelling(name="Robin", name_key="robin", how="attendance"),
                            Spelling(
                                name="Robin Example", name_key="robin example", how="identity"
                            ),
                            Spelling(name="Robin Example", name_key="robin example", how="name"),
                            Spelling(name="Robin Sample", name_key="robin sample", how="identity"),
                            Spelling(name="robin  EXAMPLE", name_key="robin example", how="name"),
                        ),
                    ),
                    account(SAM_2, "Sam Sample"),
                    account(SAM_3, "Sam Sample"),
                    Person(
                        id=SAM_ALONE,
                        name="Sam Sample",
                        spellings=(
                            Spelling(name="Sam", name_key="sam", how="attendance"),
                            Spelling(name="Sam Sample", name_key="sam sample", how="name"),
                        ),
                    ),
                    Person(
                        id=ALEX_EXAMPLE,
                        name="Alex Example (not in the header)",
                        spellings=(
                            Spelling(name="Alex", name_key="alex", how="attendance"),
                            Spelling(name="Alex Example", name_key="alex example", how="name"),
                            Spelling(
                                name="Alex Example (not in the header)",
                                name_key="alex example",
                                how="name",
                            ),
                        ),
                    ),
                    Person(
                        id=ALEX,
                        name="Alex",
                        spellings=(Spelling(name="Alex", name_key="alex", how="name"),),
                    ),
                    Person(
                        id=ROBIN_ALONE,
                        name="Robin",
                        spellings=(Spelling(name="Robin", name_key="robin", how="name"),),
                    ),
                    Person(
                        id=ROBIN_OTHER,
                        name="Robin Other",
                        spellings=(
                            Spelling(name="Robin Other", name_key="robin other", how="name"),
                        ),
                    ),
                ),
                key=lambda person: person.id,
            )
        ),
        of=dict(zip(ROWS, PERSONS_OF_ROWS, strict=True)),
        ambiguous=(
            Ambiguity(name="Robin", persons=frozenset({ROBIN, ROBIN_OTHER})),
            Ambiguity(name="Sam Sample", persons=frozenset({SAM_2, SAM_3})),
        ),
        unused=(),
    )
    assert joined(ROWS, LINKS, {}) == expected


def test_names_that_two_annotations_tell_apart_stay_apart() -> None:
    """The offsite lists Alex (Ops) and Alex (Sales): two persons, as the user wrote them.

    Its transcript's Alex could be either: it is reported, once with the two, under the
    first of them, and goes with the other Alexes by name alone. An alias's value names
    one of them by its annotation. One annotation of a key still joins its name: the
    stand-up's Alex Example (not in the header).
    """
    offsite, linked_to_offsite = 14, 26
    rows = (
        *ROWS,
        named(offsite, "Alex (Ops)"),
        named(offsite, "Alex (Sales)"),
        named(linked_to_offsite, "Alex"),
        named(UNLINKED, "A. Ops"),
    )
    links = LINKS | {linked_to_offsite: {offsite}}
    result = joined(rows, links, {"A. Ops": "alex  (OPS)"})
    ops, sales = anchored("name\nalex (ops)"), anchored("name\nalex (sales)")
    assert result.of[named(offsite, "Alex (Ops)")] == ops
    assert result.of[named(offsite, "Alex (Sales)")] == sales
    assert result.of[named(linked_to_offsite, "Alex")] == ALEX
    assert result.of[named(UNLINKED, "Alex")] == ALEX
    assert result.of[named(UNLINKED, "A. Ops")] == ops
    assert result.of[named(STAND_UP, "Alex Example (not in the header)")] == ALEX_EXAMPLE
    assert Ambiguity(name="Alex (Ops)", persons=frozenset({ops, sales})) in result.ambiguous
    assert next(person for person in result.persons if person.id == ops) == Person(
        id=ops,
        name="alex  (OPS)",
        spellings=(
            Spelling(name="A. Ops", name_key="a. ops", how="alias"),
            Spelling(name="Alex (Ops)", name_key="alex", how="name"),
        ),
    )


def test_two_notes_of_one_name_part_it_and_are_reported() -> None:
    """Kim, Kim (not in the header) and Kim (late): two notes, which may be one Kim's.

    The join cannot tell a note from a name that brackets tell apart: each annotated
    name is a person by name alone, reported as the first of them writes it.
    """
    rows = (
        named(STAND_UP, "Kim"),
        named(REVIEW, "Kim (not in the header)"),
        named(PLANNING, "Kim (late)"),
    )
    noted, late = anchored("name\nkim (not in the header)"), anchored("name\nkim (late)")
    result = joined(rows, {}, {})
    assert result.of == dict(zip(rows, (anchored("name\nkim"), noted, late), strict=True))
    assert result.ambiguous == (
        Ambiguity(name="Kim (not in the header)", persons=frozenset({noted, late})),
    )


def test_two_notes_of_an_identity_s_name_part_it_from_the_identity_and_are_reported() -> None:
    """Sam Sample's account, and two meetings writing Sam Sample with a note each.

    Each note is a person by name alone, reported; the alias of the name to the
    account's joins both to it, and nothing is reported then.
    """
    rows = (
        PersonRow(
            document=3,
            role="author",
            name="Sam Sample",
            identity="atlassian:acct-0002",
            updated=day(19),
        ),
        named(STAND_UP, "Sam Sample (not in the header)"),
        named(REVIEW, "Sam Sample (late)"),
    )
    noted = anchored("name\nsam sample (not in the header)")
    late = anchored("name\nsam sample (late)")
    result = joined(rows, {}, {})
    assert result.of == dict(zip(rows, (SAM_2, noted, late), strict=True))
    assert result.ambiguous == (
        Ambiguity(name="Sam Sample (not in the header)", persons=frozenset({noted, late})),
    )
    aliased = joined(rows, {}, {"Sam Sample": "Sam Sample"})
    assert set(aliased.of.values()) == {SAM_2}
    assert (aliased.ambiguous, aliased.unused) == ((), ())


def test_a_second_note_leaves_the_id_of_a_name_with_its_bare_spelling() -> None:
    """Kim and Kim (not in the header) are one person, whose id an alias of Kimmy names.

    Once a meeting writes Kim (late), the two notes part the annotated names from it: the
    id stays the bare Kim's, and the alias still joins Kimmy there, to fewer documents;
    the name is reported.
    """
    kim = anchored("name\nkim")
    rows = (
        named(STAND_UP, "Kim"),
        named(REVIEW, "Kim (not in the header)"),
        named(UNLINKED, "Kimmy"),
    )
    assert set(joined(rows, {}, {"Kimmy": kim}).of.values()) == {kim}
    late = named(PLANNING, "Kim (late)")
    after = joined((*rows, late), {}, {"Kimmy": kim})
    noted, noted_late = anchored("name\nkim (not in the header)"), anchored("name\nkim (late)")
    assert after.of == {rows[0]: kim, rows[1]: noted, rows[2]: kim, late: noted_late}
    assert after.unused == ()
    assert [ambiguity.name for ambiguity in after.ambiguous] == ["Kim (not in the header)"]


def test_a_name_written_as_one_identity_s_annotated_name_joins_that_identity() -> None:
    """Accounts Robin (Ops) and Robin (Sales): the meeting's Robin (Ops) is the first.

    The site wrote the two names apart, as the user would have; a bare Robin could be
    either, is reported, and joins neither.
    """
    ops, sales = anchored("account\nacct-0005"), anchored("account\nacct-0006")
    rows = (
        PersonRow(
            document=5,
            role="creator",
            name="Robin (Ops)",
            identity="atlassian:acct-0005",
            updated=day(20),
        ),
        PersonRow(
            document=6,
            role="creator",
            name="Robin (Sales)",
            identity="atlassian:acct-0006",
            updated=day(20),
        ),
        named(STAND_UP, "robin  (OPS)"),
        named(REVIEW, "Robin"),
    )
    result = joined(rows, {}, {})
    assert result.of == {rows[0]: ops, rows[1]: sales, rows[2]: ops, rows[3]: ROBIN_ALONE}
    assert result.ambiguous == (Ambiguity(name="Robin", persons=frozenset({ops, sales})),)


def test_a_name_annotated_otherwise_than_its_one_identity_joins_no_identity() -> None:
    """The meeting's Robin Example (Ops) is not the account Robin Example (Sales).

    Two annotations of one name tell its persons apart, whoever wrote each: a name that
    could be two people is not joined by a guess.
    """
    rows = (
        PersonRow(
            document=5,
            role="creator",
            name="Robin Example (Sales)",
            identity="atlassian:acct-0007",
            updated=day(20),
        ),
        named(STAND_UP, "Robin Example (Ops)"),
    )
    result = joined(rows, {}, {})
    assert result.of[rows[1]] == anchored("name\nrobin example (ops)")
    assert result.ambiguous == ()


def test_an_identity_named_on_two_documents_of_one_date_takes_the_first() -> None:
    """Ties between an account's newest documents go to the first row in order."""
    rows = (
        PersonRow(
            document=2,
            role="author",
            name="Robin Sample",
            identity="atlassian:acct-0001",
            updated=day(20),
        ),
        PersonRow(
            document=1,
            role="author",
            name="Robin Example",
            identity="atlassian:acct-0001",
            updated=day(20),
        ),
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

    The review's transcript's Robin, whom its meeting gives Robin's account too, joins by
    the alias, and the planning's, of two Robins, is no longer ambiguous.
    """
    result = joined(ROWS, LINKS, {"Robin": "Robin Example"})
    assert result.of[named(UNLINKED, "Robin")] == ROBIN
    assert result.of[named(PLANNED, "Robin")] == ROBIN
    robin = next(person for person in result.persons if person.id == ROBIN)
    assert Spelling(name="Robin", name_key="robin", how="alias") in robin.spellings
    assert Spelling(name="Robin", name_key="robin", how="attendance") not in robin.spellings
    assert ROBIN_ALONE not in {person.id for person in result.persons}
    assert [ambiguity.name for ambiguity in result.ambiguous] == ["Sam Sample"]
    assert result.unused == ()


def test_an_alias_never_takes_a_speaker_its_meeting_gives_another() -> None:
    """With "Robin" = "Robin Example", the retro's transcript's Robin stays Robin Other's.

    The retro's one Robin is Robin Other: the participants that the user wrote for that
    meeting tell more than the alias, written for the name anywhere. Robin elsewhere
    joins by the alias, as does no row of the retro's, and the alias is not unused.
    """
    retro, linked_to_retro = 14, 26
    rows = (*ROWS, named(retro, "Robin Other"), named(linked_to_retro, "Robin"))
    result = joined(rows, LINKS | {linked_to_retro: {retro}}, {"Robin": "Robin Example"})
    assert result.of[named(linked_to_retro, "Robin")] == ROBIN_OTHER
    assert result.of[named(UNLINKED, "Robin")] == ROBIN
    robin_other = next(person for person in result.persons if person.id == ROBIN_OTHER)
    assert Spelling(name="Robin", name_key="robin", how="attendance") in robin_other.spellings
    assert result.unused == ()


def test_an_alias_to_an_identity_s_id_settles_a_name_of_two_identities() -> None:
    """The meeting's Sam Sample joins acct-0003 and is no longer reported; Sam follows it.

    Sam, the speaker, joins by its meeting the person that the alias gave the meeting's
    Sam Sample.
    """
    result = joined(ROWS, LINKS, {"Sam Sample": SAM_3})
    assert result.of[named(STAND_UP, "Sam Sample")] == SAM_3
    assert result.of[named(STOOD, "Sam")] == SAM_3
    assert next(person for person in result.persons if person.id == SAM_3) == Person(
        id=SAM_3,
        name="Sam Sample",
        spellings=(
            Spelling(name="Sam", name_key="sam", how="attendance"),
            Spelling(name="Sam Sample", name_key="sam sample", how="alias"),
            Spelling(name="Sam Sample", name_key="sam sample", how="identity"),
        ),
    )
    assert SAM_ALONE not in {person.id for person in result.persons}
    assert [ambiguity.name for ambiguity in result.ambiguous] == ["Robin"]


def test_an_alias_to_a_name_alone_s_id_joins_it_even_where_identities_share_the_key() -> None:
    """The stand-up's Sam Sample, of two accounts' name, is a person by name alone.

    Its id, which a refusal of Sam Sample lists, is a value as any person's: a meeting's
    S. Sample and an unlinked transcript's Sam join it, and no alias is unused.
    """
    rows = (*ROWS, named(REVIEW, "S. Sample"), named(UNLINKED, "Sam"))
    result = joined(rows, LINKS, {"S. Sample": SAM_ALONE, "Sam": SAM_ALONE})
    assert result.of[named(REVIEW, "S. Sample")] == SAM_ALONE
    assert result.of[named(UNLINKED, "Sam")] == SAM_ALONE
    assert result.unused == ()


def test_an_alias_to_the_id_of_a_speaker_left_apart_joins_it() -> None:
    """Robin by name alone, the review's speaker, whom its meeting and an account dispute.

    One account is named Robin, yet the disputed speaker is a person by name alone: an
    alias of R. to its id joins it there.
    """
    rows = (
        *ROWS,
        PersonRow(
            document=5, role="author", name="Robin", identity="atlassian:acct-0004", updated=day(20)
        ),
        named(UNLINKED, "R."),
    )
    result = joined(rows, LINKS, {"R.": ROBIN_ALONE})
    assert result.of[named(LINKED, "Robin")] == ROBIN_ALONE
    assert result.of[named(UNLINKED, "R.")] == ROBIN_ALONE
    assert result.unused == ()


def test_an_alias_to_the_id_of_no_person_the_rows_make_names_nobody() -> None:
    """Robin Example by name alone: every one of its names joins Robin's account.

    As after an account fetched late, the id that its names had alone names nobody now;
    the alias to it is unused, and changes nothing, as one to an id of none.
    """
    gone = anchored("name\nrobin example")
    result = joined(ROWS, LINKS, {"Robin": gone, "Alex": "p-0123456789abcdef"})
    assert [(alias.name, alias.reason) for alias in result.unused] == [
        ("Robin", NOBODY),
        ("Alex", NOBODY),
    ]
    assert replace(result, unused=()) == joined(ROWS, LINKS, {})


SAM_2_ROW, SAM_3_ROW = ACCOUNTS[2:]


def test_two_identities_are_one_person_only_when_an_alias_says_so() -> None:
    """Plan 058, criterion 3, by rule 1: the two Sam Sample identities are two persons.

    An alias of acct-0003 naming acct-0002 by its identity makes them one, which keeps
    the id of acct-0002, the one named; a name without an identity of their key then
    joins that one person by rule 3, no longer ambiguous.
    """
    rows = (SAM_2_ROW, SAM_3_ROW, named(UNLINKED, "Sam Sample"))
    apart = joined(rows, {}, {})
    assert [apart.of[row] for row in rows] == [SAM_2, SAM_3, SAM_ALONE]
    assert apart.ambiguous == (Ambiguity(name="Sam Sample", persons=frozenset({SAM_2, SAM_3})),)
    one = joined(rows, {}, {"atlassian:acct-0003": "atlassian:acct-0002"})
    assert [one.of[row] for row in rows] == [SAM_2, SAM_2, SAM_2]
    assert one.persons == (
        Person(
            id=SAM_2,
            name="Sam Sample",
            spellings=(
                Spelling(name="Sam Sample", name_key="sam sample", how="alias"),
                Spelling(name="Sam Sample", name_key="sam sample", how="identity"),
                Spelling(name="Sam Sample", name_key="sam sample", how="name"),
            ),
        ),
    )
    assert (one.ambiguous, one.unused) == ((), ())


def test_an_alias_of_a_name_sees_two_identities_that_an_alias_makes_one() -> None:
    """Sam, by the name of the two Sam Sample identities that an alias makes one.

    By rule 3, the name of their key names one person once they are one, as rule 3
    joins a name without an identity: Sam joins it too, where without the alias of the
    identity, Sam's alias names several persons.
    """
    sam = named(UNLINKED, "Sam")
    rows = (SAM_2_ROW, SAM_3_ROW, sam)
    one = joined(rows, {}, {"atlassian:acct-0003": "atlassian:acct-0002", "Sam": "Sam Sample"})
    assert one.of[sam] == SAM_2
    assert one.unused == ()
    apart = joined(rows, {}, {"Sam": "Sam Sample"})
    assert [(alias.key, alias.reason) for alias in apart.unused] == [("sam", SEVERAL)]


def test_an_alias_of_an_identity_names_persons_as_the_mentions_alone_make_them() -> None:
    """Aliases of identities do not chain: each value is read before any is applied.

    acct-0009's alias to Sam Sample finds the two Sam Sample identities, though another
    alias makes them one: it names several persons, and changes nothing.
    """
    sammy = PersonRow(
        document=7, role="author", name="Sammy", identity="atlassian:acct-0009", updated=day(19)
    )
    aliases = {"atlassian:acct-0003": "atlassian:acct-0002", "atlassian:acct-0009": "Sam Sample"}
    result = joined((SAM_2_ROW, SAM_3_ROW, sammy), {}, aliases)
    assert result.of[sammy] == anchored("account\nacct-0009")
    assert [(alias.key, alias.reason) for alias in result.unused] == [
        ("atlassian:acct-0009", SEVERAL)
    ]


@pytest.mark.parametrize("value", [SAM_2, "Robin Sample"], ids=["a person's id", "a spelling"])
def test_an_alias_of_an_identity_names_a_person_by_an_id_or_a_spelling(value: str) -> None:
    """acct-0003 joins Robin's identity by its person's id, or by Robin Sample, its name."""
    person = ROBIN if value == "Robin Sample" else SAM_2
    result = joined(ACCOUNTS, {}, {"atlassian:acct-0003": value})
    assert result.of[SAM_3_ROW] == person
    assert result.unused == ()


def test_an_alias_of_a_name_names_a_person_by_an_identity() -> None:
    """Sam, without an identity, joins acct-0003 by its identity (rule 2)."""
    result = joined((*ACCOUNTS, named(UNLINKED, "Sam")), {}, {"Sam": "atlassian:acct-0003"})
    assert result.of[named(UNLINKED, "Sam")] == SAM_3
    assert result.unused == ()


def test_an_alias_of_a_name_to_an_identity_follows_where_an_alias_moved_it() -> None:
    """Sam names acct-0003, which an alias of its own makes acct-0002's person: Sam joins it.

    The identity's own person is made by nothing then, but the value names the identity,
    which is that person's, as rule 1 says.
    """
    sam = named(UNLINKED, "Sam")
    aliases = {"atlassian:acct-0003": "atlassian:acct-0002", "Sam": "atlassian:acct-0003"}
    result = joined((SAM_2_ROW, SAM_3_ROW, sam), {}, aliases)
    assert result.of[sam] == SAM_2
    assert result.unused == ()


def test_an_alias_of_a_name_to_an_identity_s_person_id_follows_where_an_alias_moved_it() -> None:
    """Sam names acct-0003's own person by id, which an alias makes acct-0002's: Sam joins it."""
    sam = named(UNLINKED, "Sam")
    aliases = {"atlassian:acct-0003": "atlassian:acct-0002", "Sam": SAM_3}
    result = joined((SAM_2_ROW, SAM_3_ROW, sam), {}, aliases)
    assert result.of[sam] == SAM_2
    assert result.unused == ()


def test_an_alias_of_an_identity_moves_no_name_written_as_it() -> None:
    """A name without an identity that writes acct-0003's identity is a name by rule 5.

    The alias of that identity moves its mentions alone (rule 1), not a name (rule 2).
    """
    written = named(UNLINKED, "atlassian:acct-0003")
    aliases = {"atlassian:acct-0003": "atlassian:acct-0002"}
    result = joined((SAM_2_ROW, SAM_3_ROW, written), {}, aliases)
    assert result.of[SAM_3_ROW] == SAM_2
    assert result.of[written] == anchored("name\natlassian:acct-0003")


def test_aliases_of_identities_are_not_chained() -> None:
    """acct-0003 names acct-0002, which an alias of its own moves to acct-0001.

    acct-0002's own person is then made by nothing: the alias naming it names nobody,
    and acct-0003 stays its own person.
    """
    aliases = {
        "atlassian:acct-0003": "atlassian:acct-0002",
        "atlassian:acct-0002": "atlassian:acct-0001",
    }
    result = joined(ACCOUNTS, {}, aliases)
    assert (result.of[SAM_2_ROW], result.of[SAM_3_ROW]) == (ROBIN, SAM_3)
    assert [(alias.key, alias.reason) for alias in result.unused] == [
        ("atlassian:acct-0003", NOBODY)
    ]


def test_an_alias_of_an_identity_that_no_mention_holds_is_reported() -> None:
    """It changes nothing, and says that no mention holds that identity."""
    result = joined(ACCOUNTS, {}, {"atlassian:acct-0009": "Robin Example"})
    assert [(alias.key, alias.reason) for alias in result.unused] == [
        ("atlassian:acct-0009", UNOWNED)
    ]
    assert replace(result, unused=()) == joined(ACCOUNTS, {}, {})


def test_an_alias_that_cannot_join_is_reported_and_changes_nothing() -> None:
    """A value of nobody, by name or id, or of several; a key held by no name alone.

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


def test_an_alias_moves_the_names_without_an_identity_alone() -> None:
    """With "Robin Example" = "Alex Example", the meetings' Robins go; the issue's stays."""
    result = joined(ROWS, LINKS, {"Robin Example": "Alex Example"})
    assert result.of[ACCOUNTS[0]] == ROBIN
    assert result.of[named(STAND_UP, "robin  EXAMPLE")] == ALEX_EXAMPLE
    assert result.of[named(REVIEW, "Robin Example")] == ALEX_EXAMPLE


def test_a_person_by_name_alone_that_an_alias_made_is_named_as_its_target_is_written() -> None:
    """The value as written names the person, not its most frequent spelling.

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
    """Two values written apart, of one key: the first alias in the file's order wins."""
    aliases = {"Alex": "alex EXAMPLE", "Kim": "Alex Example"}
    result = joined((*ROWS, named(UNLINKED, "Kim")), LINKS, aliases)
    assert next(person for person in result.persons if person.id == ALEX_EXAMPLE).name == (
        "alex EXAMPLE"
    )


def test_aliases_are_not_chained() -> None:
    """An alias's value must be a person that names make, as without the aliases.

    Robin Other's own alias, written first, takes every Robin Other to Robin's account:
    the name makes no person, so Alex's alias to it names nobody, and changes nothing.
    """
    first = {"Robin Other": "Robin Example"}
    result = joined(ROWS, LINKS, first | {"Alex": "Robin Other"})
    assert result.of[named(PLANNING, "Robin Other")] == ROBIN
    assert result.of[named(UNLINKED, "Alex")] == ALEX
    assert [(alias.name, alias.reason) for alias in result.unused] == [("Alex", NOBODY)]
    assert replace(result, unused=()) == joined(ROWS, LINKS, first)


def test_an_alias_to_a_name_that_its_meeting_joins_elsewhere_names_nobody() -> None:
    """With "Sammy" = "Sam": the stand-up's Sam is its Sam Sample, by its meeting.

    No name makes a person of Sam alone, so the alias names nobody, and Sammy stays
    apart, as without it.
    """
    rows = (*ROWS, named(UNLINKED, "Sammy"))
    result = joined(rows, LINKS, {"Sammy": "Sam"})
    assert result.of[named(UNLINKED, "Sammy")] == anchored("name\nsammy")
    assert [(alias.name, alias.reason) for alias in result.unused] == [("Sammy", NOBODY)]
    assert replace(result, unused=()) == joined(rows, LINKS, {})


@pytest.mark.parametrize("value", ["Kim", anchored("name\nkim")])
def test_an_alias_of_a_name_to_itself_joins_its_annotated_spellings(value: str) -> None:
    """Kim and two notes of Kim, which the two annotations part; "Kim" = "Kim" joins them.

    Its value is the person of Kim alone, which Kim makes though the alias takes it, as
    does that person's id; then no name is several persons.
    """
    rows = (
        named(STAND_UP, "Kim"),
        named(REVIEW, "Kim (not in the header)"),
        named(PLANNING, "Kim (late)"),
    )
    result = joined(rows, {}, {"Kim": value})
    assert set(result.of.values()) == {anchored("name\nkim")}
    assert (result.ambiguous, result.unused) == ((), ())


def test_a_speaker_whom_its_meeting_and_an_identity_tell_apart_is_ambiguous() -> None:
    """An account named Robin, one word, beside the review's Robin Example.

    The site's name and the participants that the user wrote disagree: the review's
    transcript's Robin joins neither, nor the planning's, and both are reported; Robin
    without a meeting joins the account by its name; and where a meeting's participants
    hold the account, the retro's Robin and Robin Other, its speaker is the account's.
    """
    one_word = anchored("account\nacct-0004")
    retro, linked_to_retro = 14, 26
    rows = (
        *ROWS,
        PersonRow(
            document=5, role="author", name="Robin", identity="atlassian:acct-0004", updated=day(20)
        ),
        named(retro, "Robin"),
        named(retro, "Robin Other"),
        named(linked_to_retro, "Robin"),
    )
    result = joined(rows, LINKS | {linked_to_retro: {retro}}, {})
    assert result.of[named(LINKED, "Robin")] == ROBIN_ALONE
    assert result.of[named(PLANNED, "Robin")] == ROBIN_ALONE
    assert result.of[named(UNLINKED, "Robin")] == one_word
    assert result.of[named(linked_to_retro, "Robin")] == one_word
    assert result.ambiguous[0] == Ambiguity(
        name="Robin", persons=frozenset({one_word, ROBIN, ROBIN_OTHER})
    )


def test_a_speaker_of_two_identities_name_is_reported_with_its_meeting_s_person() -> None:
    """Accounts Robin (Ops) and Robin (Sales), beside the review's Robin Example.

    The review's transcript's Robin could be either account, or Robin Example, whom the
    user wrote for that meeting: it joins none, and is reported with all three.
    """
    ops, sales = anchored("account\nacct-0005"), anchored("account\nacct-0006")
    rows = (
        *ACCOUNTS,
        PersonRow(
            document=5,
            role="creator",
            name="Robin (Ops)",
            identity="atlassian:acct-0005",
            updated=day(20),
        ),
        PersonRow(
            document=6,
            role="creator",
            name="Robin (Sales)",
            identity="atlassian:acct-0006",
            updated=day(20),
        ),
        named(REVIEW, "Robin Example"),
        named(LINKED, "Robin"),
    )
    result = joined(rows, LINKS, {})
    assert result.of[named(LINKED, "Robin")] == ROBIN_ALONE
    assert result.ambiguous == (Ambiguity(name="Robin", persons=frozenset({ops, sales, ROBIN})),)


def test_a_transcript_before_its_meeting_joins_by_it() -> None:
    """A transcript of a lower rowid than its meeting's is joined after the meeting."""
    early, late = 5, 30
    rows = (named(early, "Robin"), named(late, "Robin Example"), *ACCOUNTS)
    assert joined(rows, {early: {late}}, {}).of[named(early, "Robin")] == ROBIN


@pytest.mark.parametrize(
    ("summaries", "chained", "kept"),
    [
        ({LINKED: {REVIEW}, REVIEW: {LINKED}}, (REVIEW, LINKED), {}),
        ({LINKED: {LINKED}}, (LINKED,), {}),
        ({LINKED: {REVIEW}, REVIEW: set()}, (), {LINKED: {REVIEW}}),
        ({PLANNED: {LINKED}, LINKED: {REVIEW}}, (LINKED,), {LINKED: {REVIEW}}),
    ],
    ids=["two summarising each other", "one its own", "one whose own links none", "a chain"],
)
def test_a_summary_with_summaries_itself_is_dropped_and_named(
    summaries: dict[int, set[int]], chained: tuple[int, ...], kept: dict[int, set[int]]
) -> None:
    """Rule 4 needs each summary joined before what it summarises: one with summaries is not.

    It is dropped and named, by number; the rest join as if it never were a summary, and
    an empty set of summaries is none.
    """
    result = joined(ROWS, summaries, {})
    assert sorted(result.chained) == sorted(chained)
    assert replace(result, chained=()) == joined(ROWS, kept, {})


def test_a_name_is_reported_once_with_every_person_it_could_be() -> None:
    """Robin of two transcripts, each of a meeting of two Robins: one name, three persons."""
    retro, linked_to_retro = 14, 26
    rows = (*ROWS, named(retro, "Robin Example"), named(retro, "Robin Third"))
    result = joined(
        (*rows, named(linked_to_retro, "Robin")), LINKS | {linked_to_retro: {retro}}, {}
    )
    robin_third = anchored("name\nrobin third")
    assert result.ambiguous[0] == Ambiguity(
        name="Robin", persons=frozenset({ROBIN, ROBIN_OTHER, robin_third})
    )


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
def test_the_result_is_the_same_for_the_rows_in_any_order(rows: tuple[PersonRow, ...]) -> None:
    """Transcripts before their meetings, ties in another order, a row twice: no change."""
    aliases = {"Sam Sample": SAM_3, "Alex": "alex EXAMPLE"}
    assert joined(rows, LINKS, aliases) == joined(ROWS, LINKS, aliases)


def test_an_alias_file_gives_each_name_and_its_target_as_written(tmp_path: Path) -> None:
    """Names and values as written, in the file's order; 200 characters are not too many."""
    path = tmp_path / "aliases.toml"
    long = "R" * 200
    path.write_text(
        "# Who each name means.\n"
        '"Sam" = "Sam Sample"\n'
        f'"Robin" = "{SAM_3}"\n'
        '"Hélène" = "helene  EXAMPLE"\n'
        '"atlassian:acct-0003" = "atlassian:acct-0002"\n'
        f'"{long}" = "{long}"\n',
        encoding="utf-8",
    )
    assert list(read_aliases(path).items()) == [
        ("Sam", "Sam Sample"),
        ("Robin", SAM_3),
        ("Hélène", "helene  EXAMPLE"),
        ("atlassian:acct-0003", "atlassian:acct-0002"),
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
        ('"\\u0301" = "Robin"\n', ["\u0301"], "the name is empty"),
        ('"Robin" = "\\u0301\\u0300"\n', ["Robin"], "its value is empty"),
        ('"Sam" = ""\n', ["Sam"], "its value is empty"),
        ('"Sam\\nSample" = "Sam Sample"\n', ["Sam\nSample"], "the name holds a line break"),
        ('"Sam\\u2028" = "Sam Sample"\n', ["Sam\u2028"], "the name holds a line break"),
        ('"Sam" = """Sam\nSample"""\n', ["Sam"], "its value holds a line break"),
        ('"Sam" = "Sam Sample\\r"\n', ["Sam"], "its value holds a line break"),
        (f'"{"R" * 201}" = "Robin"\n', ["R" * 201], "the name is longer than 200"),
        (f'"Robin" = "{"R" * 201}"\n', ["Robin"], "its value is longer than 200"),
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
        "name of an accent alone",
        "value of accents alone",
        "empty value",
        "line feed in a name",
        "line separator in a name",
        "line feed in a value",
        "carriage return in a value",
        "name of 201 characters",
        "value of 201 characters",
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


def test_an_unused_alias_keeps_its_keys_in_index_s_json(
    data: Path, capsys: CaptureFixture[str]
) -> None:
    """Plan 052 renames no key of ``--format json``: an alias still says its key and target."""
    (data / "aliases.toml").write_text('"Jo Placeholder" = "Robin Example"\n', encoding="utf-8")
    config = data.parent / "config.toml"
    config.write_text('search_mode = "lexical"\n', encoding="utf-8")
    given = ["index", "--yes", "--format", "json", "--config", str(config), "--data-dir", str(data)]
    assert main(given) == 0
    (unused,) = json.loads(capsys.readouterr().out)["report"]["persons"]["unused"]
    assert (sorted(unused), unused["key"], unused["target"]) == (
        ["held", "key", "means", "name", "target"],
        "jo placeholder",
        "Robin Example",
    )


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
    assert (ambiguous["spelling"], ambiguous["persons"]) == ("Sam Sample", 2)
    (unused,) = logged_as(home, "index.alias_unused")
    assert (unused["alias"], unused["key"], unused["reason"]) == (
        "Jo Placeholder",
        "jo placeholder",
        UNHELD,
    )
    (built,) = logged_as(home, "index.built")
    # Robin by name alone is gone; the other seven persons stay.
    persons = {ROBIN, SAM_2, SAM_3, SAM_ALONE, ALEX_EXAMPLE, ALEX, ROBIN_OTHER}
    assert built["persons"] == len(persons)
    with closing(sqlite3.connect(data / "index.sqlite")) as connection:
        robins = connection.execute("SELECT DISTINCT person FROM people WHERE name = 'Robin'")
        assert robins.fetchall() == [(ROBIN,)]


def test_index_joins_two_identities_by_a_quoted_key_of_the_alias_file(
    data: Path, capsys: CaptureFixture[str]
) -> None:
    """An identity is a TOML key in quotes: the two Sam Sample identities are one person."""
    alias = '"atlassian:acct-0003" = "atlassian:acct-0002"\n'
    (data / "aliases.toml").write_text(alias, encoding="utf-8")
    assert index(data, capsys)[0] == 0
    assert logged_as(data.parent / "home", "index.alias_unused") == []
    with closing(sqlite3.connect(data / "index.sqlite")) as connection:
        sams = connection.execute(
            "SELECT DISTINCT person FROM people WHERE identity IS NOT NULL AND name = 'Sam Sample'"
        )
        assert sams.fetchall() == [(SAM_2,)]


def test_index_names_each_summary_that_summarises_another_itself(
    data: Path, capsys: CaptureFixture[str]
) -> None:
    """Two transcripts whose summaries link each other, as a hand-edited mirror may.

    Neither is a summary: ``index.built`` names each by its path; the build exits 0.
    """
    paths = [
        write(data / "docs", worklog_document("transcript", one, "Loop", ("Alex",), other))
        for one, other in (("t-20261022-1", "t-20261022-2"), ("t-20261022-2", "t-20261022-1"))
    ]
    assert index(data, capsys)[0] == 0
    (built,) = logged_as(data.parent / "home", "index.built")
    assert built["chained"] == sorted(paths)


@pytest.mark.parametrize(
    ("place", "why"),
    [
        (
            lambda path: path.write_text('"Sam" = "Sam Sample"\n"sam" = "Sam Other"\n', "utf-8"),
            "'Sam' and 'sam' are one name",
        ),
        (lambda path: path.write_text('"Sam" = 1\n', "utf-8"), "'Sam': its value is not text"),
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
        "'Sam': its value is not text; write a name, an identity or a person's id in quotes"
    )
    assert "hint" not in failed
