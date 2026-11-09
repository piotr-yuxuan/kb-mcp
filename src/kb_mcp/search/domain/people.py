"""Persons: the names of every source joined into people, as each build of the index does.

A person is an account, or else a name. ``joined`` takes every row of the index's
people, the meetings that each transcript links to and the user's aliases, and gives
each row a person, by the first of these rules that answers:

1. an account is a person, under each of its names: two accounts are never one;
2. a name without an account whose key an alias holds goes to the alias's target, but
   for a transcript's speaker whom rule 4 gives one other person;
3. a name of the key of exactly one account's name joins that account's person;
4. a transcript's speaker of one word joins the one person among its meetings'
   participants whose key's first word, whole, is that word;
5. any other name is a person by name alone, shared by every name of its key.

A name that could be several persons, by rule 3 or 4, or a speaker whom they give
different persons, is ambiguous: it is reported, never given to one of them, and goes
by rule 5. Every rule compares names by their key, which keeps an annotation that
tells two names apart; a key whose annotated names go by rule 5 to several persons is
reported too, as the annotations may be notes rather than names. Nothing here reads
the index or the alias file.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections import Counter
from collections.abc import Mapping
from copy import replace
from datetime import datetime
from itertools import chain
from typing import TYPE_CHECKING

from kb_mcp.kernel.record import Record

if TYPE_CHECKING:
    from collections.abc import Callable, Collection, Iterable

# A trailing part in brackets, once a key's spaces are collapsed: an annotation of the
# work log's, such as "Kim (not in the header)", and what it says. It needs a name
# before it.
ANNOTATION = re.compile(r"(?<=\S) ?\(([^()]*)\)\Z")
# A person's id, as an alias's target may give it.
PERSON_ID = re.compile(r"p-[0-9a-f]{16}")
# How a name joined its person. BY_ACCOUNT and BY_NAME also say what a person's id hashes.
BY_ACCOUNT = "account"
BY_ALIAS = "alias"
BY_MEETING = "meeting"
BY_NAME = "name"
# Why an alias changes nothing.
UNHELD = "no name without an account has its key"
NOBODY = "its target names nobody"
SEVERAL = "its target names several people"


def written_key(name: str) -> str:
    """Give a name's key with its annotation: ``name_key`` but for the part in brackets.

    The name casefolded, decomposed by NFKD without its accents, the combining
    diacritical marks of U+0300 to U+036F, as filters drop them, and casefolded again;
    its runs of white space made one space, trimmed; its annotation after one space,
    trimmed within its brackets, so that "Kim(late)" and "Kim ( late )" write one. A
    kana's voicing mark, which makes another letter, stays.
    """
    decomposed = unicodedata.normalize("NFKD", name.casefold())
    plain = "".join(char for char in decomposed if not "\u0300" <= char <= "\u036f").casefold()
    return ANNOTATION.sub(lambda part: f" ({part[1].strip()})", " ".join(plain.split()))


def name_key(name: str) -> str:
    """Give the key by which names are compared: names of one key are one name.

    Its ``written_key``, without a trailing part in brackets when a name comes before
    it. So "Hélène  Example" and "helene example" share a key, and "Kim (not in the
    header)" has Kim's; ``Joining.compared_key`` keeps the part where two of them tell names
    apart.
    """
    return ANNOTATION.sub("", written_key(name))


def first_word(name: str) -> str:
    """Give the first word of a name's key: a speaker of that word may be its person.

    Rule 4 joins such a speaker within its meeting; elsewhere, an answer shows them as
    perhaps the same.
    """
    return name_key(name).partition(" ")[0]


def person_id(anchor: str, value: str) -> str:
    """Give the id of the person that an account id, or a name's key, anchors.

    ``anchor`` is BY_ACCOUNT or BY_NAME. The id is ``p-`` and the first 16 hex digits of the
    SHA-256 of the anchor, a line feed and the value: an opaque handle, stable while what
    anchors the person stays, so that no account id is served. It protects nothing:
    hashing a known account id finds it again. A second note on a name, which parts its
    annotated spellings by ``Joining.compared_key``, anchors each of them anew; the bare name
    keeps the id, which then names fewer documents.
    """
    return "p-" + hashlib.sha256(f"{anchor}\n{value}".encode()).hexdigest()[:16]


def aliases_digest(aliases: Mapping[str, str]) -> str:
    """Give the digest of what an alias file means: its names and targets, in their order.

    All that ``joined`` reads of it, so a comment or a blank line leaves it as it was.
    """
    return hashlib.sha256(json.dumps(list(aliases.items())).encode()).hexdigest()


class PersonRow(Record):
    """A person in a role of a document, as a row of the index's people holds it.

    ``account`` is the source's account id, None for a name alone; ``updated`` is when
    the document was last updated, by which an account's person is named.
    """

    document: int  # the document's number, by which rows are ordered
    role: str
    name: str
    account: str | None
    updated: datetime


class Ambiguity(Record):
    """A name that could be several persons, none of whom is given it.

    Or a key whose names annotations part among persons by name alone, such as
    "Kim (not in the header)" and "Kim (late)", which may be one Kim's notes.
    """

    name: str  # as the first of its rows in order writes it
    persons: frozenset[str]  # the ids of those it could be


# What a rule answers for a row: a person's id, an ambiguity, or nothing.
type Meant = str | Ambiguity | None


class Alias(Record):
    """A line of the alias file: a name as a source writes it, and the person it means."""

    name: str  # as the file writes it
    name_key: str  # the name's key
    target: str  # a name, or a person's id, as the file writes it
    means: Meant  # the person its target names, several, or nobody
    held: bool  # whether a name without an account has its key

    @property
    def reason(self) -> str | None:
        """Say why the alias changes nothing, or None when it joins its names."""
        if not self.held:
            return UNHELD
        if self.means is None:
            return NOBODY
        return SEVERAL if isinstance(self.means, Ambiguity) else None


class Spelling(Record):
    """A name of a person as a source writes it, its key, and how it joined the person."""

    name: str
    name_key: str
    how: str  # BY_ACCOUNT, BY_ALIAS, BY_MEETING or BY_NAME


class Person(Record):
    """One person across sources: its id, the name it is served by, and its spellings."""

    id: str
    name: str
    spellings: tuple[Spelling, ...]  # in order


class Joined(Record):
    """What the join gives: the persons, the person of each row, and what it left apart."""

    persons: tuple[Person, ...]  # by id
    of: Mapping[PersonRow, str]  # each row's person, by id
    ambiguous: tuple[Ambiguity, ...]  # one per key, by key
    unused: tuple[Alias, ...]  # the aliases that changed nothing, in their order


class JoinOutcome(Record):
    """What a build says of its join: how many persons, and what it left apart, as Joined."""

    count: int = 0
    ambiguous: tuple[Ambiguity, ...] = ()
    unused: tuple[Alias, ...] = ()


class Joining:
    """What the rules read, and the person of each row joined so far.

    The names of the accounts, the aliases, each transcript's meetings and each
    document's rows. Names compare by ``compared_key``: by their key, but for the names of a key
    written with two annotations or more, by a source or the user, such as "Alex (Ops)"
    and "Alex (Sales)", which were written apart, and which then keep them.
    """

    def __init__(
        self,
        rows: Iterable[PersonRow],
        meetings: Mapping[int, Collection[int]],
        aliases: Mapping[str, str],
    ) -> None:
        """Read the rows, the meetings of each transcript, by number, and the aliases.

        An alias's target is a person's id; or a name, which means the one account of
        its key, as rule 3 finds it, else the person by name alone of a key that a name
        without an account holds. ``joined`` keeps either when an account or a name
        makes that person: aliases are not chained. Raise ValueError, naming them, for
        documents that are a transcript's meetings and link to meetings themselves, as a
        transcript, or itself, would: rule 4 needs each meeting joined before.
        """
        if chained := sorted(set(meetings).intersection(chain.from_iterable(meetings.values()))):
            message = f"documents {chained} link to meetings and are linked to as meetings"
            raise ValueError(message)
        self.meetings = meetings
        self.persons: dict[PersonRow, str] = {}
        self.rows: dict[int, list[PersonRow]] = {}  # each document's
        # Each name key's names, by their written key, with their account's person, None
        # for a name without an account.
        spelt: dict[str, set[tuple[str, str | None]]] = {}
        for row in rows:
            self.rows.setdefault(row.document, []).append(row)
            written = written_key(row.name)
            account = None if row.account is None else person_id(BY_ACCOUNT, row.account)
            spelt.setdefault(ANNOTATION.sub("", written), set()).add((written, account))
        # The name keys that names, of an account or not, write with two annotations or more.
        self.split = {
            key
            for key, names in spelt.items()
            if len({written for written, _ in names} - {key}) > 1
        }
        # Each ``compared_key``'s accounts' persons, and each name key's: a bare name could be any
        # account of its key, an annotated one is the account of its annotation.
        self.accounts: dict[str, set[str]] = {}
        self.held: set[str] = set()  # the ``compared_key`` of each name without an account
        for key, names in spelt.items():
            for written, account in names:
                compared = written if key in self.split else key
                if account is None:
                    self.held.add(compared)
                else:
                    for each in {key, compared}:
                        self.accounts.setdefault(each, set()).add(account)
        self.aliases: dict[str, Alias] = {}
        for name, target in aliases.items():
            if PERSON_ID.fullmatch(target):
                means: Meant = target
            else:
                key = self.compared_key(target)
                means = self.account(target) or (
                    person_id(BY_NAME, key) if key in self.held else None
                )
            key = name_key(name)
            held = any(account is None for _, account in spelt.get(key, ()))
            self.aliases[key] = Alias(
                name=name, name_key=key, target=target, means=means, held=held
            )

    def compared_key(self, name: str) -> str:
        """Give the key by which the join compares a name, and a name alone's id hashes.

        Its key, but its written key, annotation kept, where two annotations or more
        tell apart names of that key.
        """
        written = written_key(name)
        key = ANNOTATION.sub("", written)
        return written if key in self.split else key

    def account(self, name: str) -> Meant:
        """Find the person of the one account with a name of this name's ``key``.

        A name of several accounts' key is ambiguous, as is a bare name whose key's
        accounts annotations tell apart; one of none, None.
        """
        persons = self.accounts.get(self.compared_key(name), set())
        if len(persons) > 1:
            return Ambiguity(name=name, persons=frozenset(persons))
        return next(iter(persons), None)


def by_alias(row: PersonRow, joining: Joining) -> Meant:
    """Give a name without an account to the person its alias means (rule 2).

    An alias whose target names nobody, or several, changes nothing; nor does it take a
    transcript's speaker whom its meetings give one other person, by rule 4: the user
    wrote those participants for that meeting, and the alias for the name anywhere.
    """
    alias = joining.aliases.get(name_key(row.name))
    if alias is None or alias.reason is not None:
        return None
    meeting = by_meeting(row, joining)
    return None if isinstance(meeting, str) and meeting != alias.means else alias.means


def by_name(row: PersonRow, joining: Joining) -> Meant:
    """Join a name without an account to the one account of its key (rule 3).

    A name of several accounts' key is ambiguous; so is a transcript's speaker whose
    meetings give it, by rule 4, persons that do not hold that account: the site's name
    and the participants that the user wrote for the meeting then disagree. A speaker of
    several accounts' key could be any of them or its meetings' persons.
    """
    found = joining.account(row.name)
    meeting = by_meeting(row, joining)
    if meeting is None or found is None:
        return found
    others = meeting.persons if isinstance(meeting, Ambiguity) else frozenset({meeting})
    if isinstance(found, Ambiguity):
        return Ambiguity(name=row.name, persons=found.persons | others)
    return found if found in others else Ambiguity(name=row.name, persons=others | {found})


def by_meeting(row: PersonRow, joining: Joining) -> Meant:
    """Join a transcript's speaker by the meetings that the transcript links to (rule 4).

    A speaker whose key is the first word of the keys of some of those meetings'
    participants, and so one word, joins their person when they are one, and is
    ambiguous when they are several. Their rows must be joined already. Every row of a
    document that links to meetings is a transcript's speaker, and every row of a
    meeting a participant: the work log's documents hold no other role.
    """
    key = name_key(row.name)
    persons = {
        joining.persons[other]
        for meeting in joining.meetings.get(row.document, ())
        for other in joining.rows.get(meeting, ())
        if first_word(other.name) == key
    }
    if len(persons) > 1:
        return Ambiguity(name=row.name, persons=frozenset(persons))
    return next(iter(persons), None)


# Rules 2 to 4, each with how a name joins by it, in the order that ``joined`` tries them,
# the first answer winning. The order is not all of it: rules 2 and 3 read rule 4's
# answer, so that neither takes a speaker whom its meeting gives another person; a rule
# added here says how it stands to rule 4.
RULES: tuple[tuple[str, Callable[[PersonRow, Joining], Meant]], ...] = (
    (BY_ALIAS, by_alias),
    (BY_NAME, by_name),
    (BY_MEETING, by_meeting),
)


def joined(
    rows: Iterable[PersonRow], meetings: Mapping[int, Collection[int]], aliases: Mapping[str, str]
) -> Joined:
    """Join every row into its person: by its account, by RULES in order, or by its name.

    ``meetings`` gives each transcript's meetings, by number, as its ``summary`` links
    name them, none of them a transcript (``Joining`` refuses one that links to
    meetings); ``aliases`` each alias's name and target, of distinct keys, as the alias
    file's reader checks. Rows go in order of document, role, name and account, linked
    transcripts' last, so that their meetings' persons are known; the same rows in any
    order give the same result. A person is served by the name on its account's most
    recently updated document; else by the target of the alias that made it, when that
    is a name; else by its most frequent spelling: ties go to the first row in order.
    An alias whose target, a person's id or a name, means a person that no account or
    name makes, but aliases or meetings alone, names nobody: the join is made again
    without it, each pass with fewer aliases.
    """
    ordered = sorted(
        set(rows),
        key=lambda row: (
            row.document in meetings,
            row.document,
            row.role,
            row.name,
            row.account or "",
            row.updated,
        ),
    )
    joining = Joining(ordered, meetings, aliases)
    members: dict[str, list[tuple[PersonRow, str]]] = {}  # each person's rows, and how each joined
    ambiguous: dict[str, Ambiguity] = {}  # by key
    for row in ordered:
        if row.account is not None:
            how, found = BY_ACCOUNT, person_id(BY_ACCOUNT, row.account)
        else:
            answers = ((how, rule(row, joining)) for how, rule in RULES)
            how, found = next(
                ((how, each) for how, each in answers if each is not None), (BY_NAME, None)
            )
        # The persons that the row could be, none of whom is given it; and, for a name
        # alone that its annotation keeps from the other names of its key, its own.
        could = found.persons if isinstance(found, Ambiguity) else frozenset()
        if not isinstance(found, str):
            compared = joining.compared_key(row.name)
            how, found = BY_NAME, person_id(BY_NAME, compared)
            if compared != name_key(row.name):
                could |= {found}
        if could:
            key = name_key(row.name)
            known = ambiguous.setdefault(key, Ambiguity(name=row.name, persons=could))
            ambiguous[key] = replace(known, persons=known.persons | could)
        joining.persons[row] = found
        members.setdefault(found, []).append((row, how))
    # The persons that an account or a name makes, whatever rule joined that name to its
    # own person, but not an alias or a meeting alone, which join a name to another's.
    made = {
        person
        for person, joins in members.items()
        for row, how in joins
        if how == BY_ACCOUNT or person == person_id(BY_NAME, joining.compared_key(row.name))
    }
    nobody = {
        alias.name_key: replace(alias, means=None)
        for alias in joining.aliases.values()
        if alias.reason is None and alias.means not in made
    }
    if nobody:
        kept = {name: target for name, target in aliases.items() if name_key(name) not in nobody}
        again = joined(ordered, meetings, kept)
        unused = {alias.name_key: alias for alias in again.unused} | nobody
        return replace(again, unused=tuple(unused[key] for key in joining.aliases if key in unused))
    # Each name alone's target as an alias writes it, the first alias's in their order.
    written = {
        alias.means: alias.target
        for alias in reversed(joining.aliases.values())
        if alias.reason is None and not PERSON_ID.fullmatch(alias.target)
    }
    persons = []
    for person, joins in sorted(members.items()):
        own = [row for row, _ in joins if row.account is not None]
        if own:
            name = max(own, key=lambda row: row.updated).name
        else:
            name = written.get(person) or Counter(row.name for row, _ in joins).most_common(1)[0][0]
        spellings = sorted(
            {Spelling(name=row.name, name_key=name_key(row.name), how=how) for row, how in joins},
            key=lambda each: (each.name, each.name_key, each.how),
        )
        persons.append(Person(id=person, name=name, spellings=tuple(spellings)))
    return Joined(
        persons=tuple(persons),
        of=joining.persons,
        ambiguous=tuple(
            ambiguous[key] for key in sorted(ambiguous) if len(ambiguous[key].persons) > 1
        ),
        unused=tuple(alias for alias in joining.aliases.values() if alias.reason is not None),
    )
