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
    written_key,
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


def test_by_meeting_joins_a_speaker_to_the_one_person_whose_first_word_it_is() -> None:
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
    assert by_meeting(named(LINKED, "robin"), joining) == ROBIN
    assert by_meeting(named(linked_to_offsite, "Robin"), joining) == ROBIN
    assert by_meeting(named(PLANNED, "Robin"), joining) == Ambiguity(
        "Robin", frozenset({ROBIN, ROBIN_OTHER})
    )
    assert by_meeting(named(UNLINKED, "Robin"), joining) is None
    assert by_meeting(named(LINKED, "Example"), joining) is None  # not a first word
    assert by_meeting(named(LINKED, "Rob"), joining) is None  # a first word's start alone
    assert by_meeting(named(LINKED, "Alex Example"), joining) is None  # not one word


def test_a_speaker_whose_word_only_begins_a_participant_s_is_a_name_alone() -> None:
    """Rob, in the review's transcript, is not its Robin Example: words compare whole.

    Joining them would quote one colleague as another, as plan 043 rejects.
    """
    rob = anchored("name\nrob")
    result = joined((*ROWS, named(LINKED, "Rob")), LINKS, {})
    assert result.of[named(LINKED, "Rob")] == rob
    assert Person(rob, "Rob", (Spelling("Rob", "rob", "name"),)) in result.persons


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


def test_names_that_two_annotations_tell_apart_stay_apart() -> None:
    """The offsite lists Alex (Ops) and Alex (Sales): two persons, as the user wrote them.

    Its transcript's Alex could be either: it is reported, once with the two, under the
    first of them, and goes with the other Alexes by name alone. An alias's target names
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
    assert Ambiguity("Alex (Ops)", frozenset({ops, sales})) in result.ambiguous
    assert next(person for person in result.persons if person.id == ops) == Person(
        ops,
        "alex  (OPS)",
        (Spelling("A. Ops", "a. ops", "alias"), Spelling("Alex (Ops)", "alex", "name")),
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
    assert result.ambiguous == (Ambiguity("Kim (not in the header)", frozenset({noted, late})),)


def test_two_notes_of_an_account_s_name_part_it_from_the_account_and_are_reported() -> None:
    """Sam Sample's account, and two meetings writing Sam Sample with a note each.

    Each note is a person by name alone, reported; the alias of the name to the
    account's joins both to it, and nothing is reported then.
    """
    rows = (
        Row(3, "author", "Sam Sample", "acct-0002", day(19)),
        named(STAND_UP, "Sam Sample (not in the header)"),
        named(REVIEW, "Sam Sample (late)"),
    )
    noted = anchored("name\nsam sample (not in the header)")
    late = anchored("name\nsam sample (late)")
    result = joined(rows, {}, {})
    assert result.of == dict(zip(rows, (SAM_2, noted, late), strict=True))
    assert result.ambiguous == (
        Ambiguity("Sam Sample (not in the header)", frozenset({noted, late})),
    )
    aliased = joined(rows, {}, {"Sam Sample": "Sam Sample"})
    assert set(aliased.of.values()) == {SAM_2}
    assert (aliased.ambiguous, aliased.unused) == ((), ())


def test_a_name_written_as_one_account_s_annotated_name_joins_that_account() -> None:
    """Accounts Robin (Ops) and Robin (Sales): the meeting's Robin (Ops) is the first.

    The site wrote the two names apart, as the user would have; a bare Robin could be
    either, is reported, and joins neither.
    """
    ops, sales = anchored("account\nacct-0005"), anchored("account\nacct-0006")
    rows = (
        Row(5, "creator", "Robin (Ops)", "acct-0005", day(20)),
        Row(6, "creator", "Robin (Sales)", "acct-0006", day(20)),
        named(STAND_UP, "robin  (OPS)"),
        named(REVIEW, "Robin"),
    )
    result = joined(rows, {}, {})
    assert result.of == {rows[0]: ops, rows[1]: sales, rows[2]: ops, rows[3]: ROBIN_ALONE}
    assert result.ambiguous == (Ambiguity("Robin", frozenset({ops, sales})),)


def test_a_name_annotated_otherwise_than_its_one_account_joins_no_account() -> None:
    """The meeting's Robin Example (Ops) is not the account Robin Example (Sales).

    Two annotations of one name tell its persons apart, whoever wrote each: a name that
    could be two people is not joined by a guess.
    """
    rows = (
        Row(5, "creator", "Robin Example (Sales)", "acct-0007", day(20)),
        named(STAND_UP, "Robin Example (Ops)"),
    )
    result = joined(rows, {}, {})
    assert result.of[rows[1]] == anchored("name\nrobin example (ops)")
    assert result.ambiguous == ()


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

    The review's transcript's Robin, whom its meeting gives Robin's account too, joins by
    the alias, and the planning's, of two Robins, is no longer ambiguous.
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
    assert Spelling("Robin", "robin", "meeting") in robin_other.names
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


def test_an_alias_to_a_name_alone_s_id_joins_it_even_where_accounts_share_the_key() -> None:
    """The stand-up's Sam Sample, of two accounts' name, is a person by name alone.

    Its id, which a refusal of Sam Sample lists, is a target as any person's: a meeting's
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
    rows = (*ROWS, Row(5, "author", "Robin", "acct-0004", day(20)), named(UNLINKED, "R."))
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
    """An alias's target must be a person that names make, as without the aliases.

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


@pytest.mark.parametrize("target", ["Kim", anchored("name\nkim")])
def test_an_alias_of_a_name_to_itself_joins_its_annotated_spellings(target: str) -> None:
    """Kim and two notes of Kim, which the two annotations part; "Kim" = "Kim" joins them.

    Its target is the person of Kim alone, which Kim makes though the alias takes it, as
    does that person's id; then no name is several persons.
    """
    rows = (
        named(STAND_UP, "Kim"),
        named(REVIEW, "Kim (not in the header)"),
        named(PLANNING, "Kim (late)"),
    )
    result = joined(rows, {}, {"Kim": target})
    assert set(result.of.values()) == {anchored("name\nkim")}
    assert (result.ambiguous, result.unused) == ((), ())


def test_a_speaker_whom_its_meeting_and_an_account_tell_apart_is_ambiguous() -> None:
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
        Row(5, "author", "Robin", "acct-0004", day(20)),
        named(retro, "Robin"),
        named(retro, "Robin Other"),
        named(linked_to_retro, "Robin"),
    )
    result = joined(rows, LINKS | {linked_to_retro: {retro}}, {})
    assert result.of[named(LINKED, "Robin")] == ROBIN_ALONE
    assert result.of[named(PLANNED, "Robin")] == ROBIN_ALONE
    assert result.of[named(UNLINKED, "Robin")] == one_word
    assert result.of[named(linked_to_retro, "Robin")] == one_word
    assert result.ambiguous[0] == Ambiguity("Robin", frozenset({one_word, ROBIN, ROBIN_OTHER}))


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
