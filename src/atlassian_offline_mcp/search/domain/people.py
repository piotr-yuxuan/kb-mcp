"""Persons: the names of every source joined into people, as each build of the index does.

A person is an account, or else a name. ``joined`` takes every row of the index's
people, the meetings that each transcript links to and the user's aliases, and gives
each row a person, by the first of these rules that answers:

1. an account is a person, under each of its names: two accounts are never one;
2. a name without an account whose key an alias holds goes to the alias's target;
3. a name of the key of exactly one account's name joins that account's person;
4. a transcript's speaker of one word joins the one person among its meetings'
   participants whose key begins with that word;
5. any other name is a person by name alone, shared by every name of its key.

A name that could be several persons, by rule 3 or 4, is ambiguous: it is reported,
never given to one of them, and goes by rule 5. Every rule compares names by their
key. Nothing here reads the index or the alias file.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable, Collection, Iterable, Mapping
    from datetime import datetime

# A trailing part in brackets, once a key's spaces are collapsed: an annotation of the
# work log's, such as "Kim (not in the header)". It needs a name before it.
ANNOTATION = re.compile(r"(?<=\S) ?\([^()]*\)\Z")
# A person's id, as an alias's target may give it.
PERSON_ID = re.compile(r"p-[0-9a-f]{16}")
# How a name joined its person. ACCOUNT and NAME also say what a person's id hashes.
ACCOUNT = "account"
ALIAS = "alias"
MEETING = "meeting"
NAME = "name"
# Why an alias changes nothing.
UNHELD = "no name without an account has its key"
NOBODY = "its target names nobody"
SEVERAL = "its target names several people"


def name_key(name: str) -> str:
    """Give the key by which names are compared: names of one key are one name.

    The name casefolded, decomposed by NFKD without its accents, the combining
    diacritical marks of U+0300 to U+036F, as filters drop them, and casefolded again;
    its runs of white space made one space, trimmed; and a trailing part in brackets
    dropped when a name comes before it. So "Hélène  Example" and "helene example" share
    a key, and "Kim (not in the header)" has Kim's. A kana's voicing mark, which makes
    another letter, stays.
    """
    decomposed = unicodedata.normalize("NFKD", name.casefold())
    plain = "".join(char for char in decomposed if not "\u0300" <= char <= "\u036f").casefold()
    return ANNOTATION.sub("", " ".join(plain.split()))


def person_id(anchor: str, value: str) -> str:
    """Give the id of the person that an account id, or a name's key, anchors.

    ``anchor`` is ACCOUNT or NAME. The id is ``p-`` and the first 16 hex digits of the
    SHA-256 of the anchor, a line feed and the value: an opaque handle, stable while what
    anchors the person stays, so that no account id is served. It protects nothing:
    hashing a known account id finds it again.
    """
    return "p-" + hashlib.sha256(f"{anchor}\n{value}".encode()).hexdigest()[:16]


@dataclass(frozen=True)
class Row:
    """A person in a role of a document, as a row of the index's people holds it.

    ``account`` is the source's account id, None for a name alone; ``updated`` is when
    the document was last updated, by which an account's person is named.
    """

    document: int  # the document's rowid
    role: str
    name: str
    account: str | None
    updated: datetime


@dataclass(frozen=True)
class Ambiguity:
    """A name that could be several persons: none of them is given it."""

    name: str  # as the first of its rows in order writes it
    persons: frozenset[str]  # the ids of those it could be


# What a rule answers for a row: a person's id, an ambiguity, or nothing.
type Answer = str | Ambiguity | None


@dataclass(frozen=True)
class Alias:
    """A line of the alias file: a name as a source writes it, and the person it means."""

    name: str  # as the file writes it
    key: str  # the name's key
    target: str  # a name, or a person's id, as the file writes it
    means: Answer  # the person its target names, several, or nobody
    held: bool  # whether a name without an account has its key

    @property
    def reason(self) -> str | None:
        """Say why the alias changes nothing, or None when it joins its names."""
        if not self.held:
            return UNHELD
        if self.means is None:
            return NOBODY
        return SEVERAL if isinstance(self.means, Ambiguity) else None


@dataclass(frozen=True, order=True)
class Spelling:
    """A name of a person as a source writes it, its key, and how it joined the person."""

    name: str
    key: str
    how: str  # ACCOUNT, ALIAS, MEETING or NAME


@dataclass(frozen=True)
class Person:
    """One person across sources: its id, the name it is served by, and its spellings."""

    id: str
    name: str
    names: tuple[Spelling, ...]  # in order


@dataclass(frozen=True)
class Joined:
    """What the join gives: the persons, the person of each row, and what it left apart."""

    persons: tuple[Person, ...]  # by id
    of: Mapping[Row, str]  # each row's person, by id
    ambiguous: tuple[Ambiguity, ...]  # one per key, by key
    unused: tuple[Alias, ...]  # the aliases that changed nothing, in their order


class Joining:
    """What the rules read, and the person of each row joined so far.

    The names of the accounts, the aliases, each transcript's meetings and each
    document's rows.
    """

    def __init__(
        self,
        rows: Iterable[Row],
        meetings: Mapping[int, Collection[int]],
        aliases: Mapping[str, str],
    ) -> None:
        """Read the rows, the meetings of each transcript, by rowid, and the aliases.

        An alias's target is a person's id, which ``joined`` keeps when an account or a
        name makes that person; or a name, which means the one account of its key, as
        rule 3 finds it, else the person by name alone of a key that a name without an
        account holds. Aliases are not chained.
        """
        self.meetings = meetings
        self.persons: dict[Row, str] = {}
        self.rows: dict[int, list[Row]] = {}  # each document's
        self.accounts: dict[str, set[str]] = {}  # each name key's accounts' persons
        self.held: set[str] = set()  # the keys of the names without an account
        for row in rows:
            self.rows.setdefault(row.document, []).append(row)
            key = name_key(row.name)
            if row.account is None:
                self.held.add(key)
            else:
                self.accounts.setdefault(key, set()).add(person_id(ACCOUNT, row.account))
        self.aliases: dict[str, Alias] = {}
        for name, target in aliases.items():
            if PERSON_ID.fullmatch(target):
                means: Answer = target
            else:
                key = name_key(target)
                means = self.account(target) or (person_id(NAME, key) if key in self.held else None)
            key = name_key(name)
            self.aliases[key] = Alias(name, key, target, means, held=key in self.held)

    def account(self, name: str) -> Answer:
        """Find the person of the one account with a name of this name's key.

        A name of several accounts' key is ambiguous; one of none, None.
        """
        persons = self.accounts.get(name_key(name), set())
        if len(persons) > 1:
            return Ambiguity(name, frozenset(persons))
        return next(iter(persons), None)


def by_alias(row: Row, joining: Joining) -> Answer:
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


def by_name(row: Row, joining: Joining) -> Answer:
    """Join a name without an account to the one account of its key (rule 3).

    A name of several accounts' key is ambiguous; so is a transcript's speaker whose
    meetings give it, by rule 4, persons that do not hold that account: the site's name
    and the participants that the user wrote for the meeting then disagree.
    """
    found = joining.account(row.name)
    meeting = by_meeting(row, joining)
    if meeting is None or not isinstance(found, str):
        return found
    others = meeting.persons if isinstance(meeting, Ambiguity) else frozenset({meeting})
    return found if found in others else Ambiguity(row.name, others | {found})


def by_meeting(row: Row, joining: Joining) -> Answer:
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
        if name_key(other.name).partition(" ")[0] == key
    }
    if len(persons) > 1:
        return Ambiguity(row.name, frozenset(persons))
    return next(iter(persons), None)


# Rules 2 to 4, each with how a name joins by it, in the order that ``joined`` tries them.
RULES: tuple[tuple[str, Callable[[Row, Joining], Answer]], ...] = (
    (ALIAS, by_alias),
    (NAME, by_name),
    (MEETING, by_meeting),
)


def joined(
    rows: Iterable[Row], meetings: Mapping[int, Collection[int]], aliases: Mapping[str, str]
) -> Joined:
    """Join every row into its person: by its account, by RULES in order, or by its name.

    ``meetings`` gives each transcript's meetings, by rowid, as its ``summary`` links
    name them; ``aliases`` each alias's name and target, of distinct keys, as the alias
    file's reader checks. Rows go in order of document, role, name and account, linked
    transcripts' last, so that their meetings' persons are known; the same rows in any
    order give the same result. A person is served by the name on its account's most
    recently updated document; else by the target of the alias that made it, when that
    is a name; else by its most frequent spelling: ties go to the first row in order.
    An alias to a person's id that no account or name makes, but aliases alone, names
    nobody: the join is made again without it, each pass with fewer aliases.
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
    members: dict[str, list[tuple[Row, str]]] = {}  # each person's rows, and how each joined
    ambiguous: dict[str, Ambiguity] = {}  # by key
    for row in ordered:
        if row.account is not None:
            how, found = ACCOUNT, person_id(ACCOUNT, row.account)
        else:
            answers = ((how, rule(row, joining)) for how, rule in RULES)
            how, found = next(
                ((how, each) for how, each in answers if each is not None), (NAME, None)
            )
        if isinstance(found, Ambiguity):
            known = ambiguous.setdefault(name_key(row.name), found)
            ambiguous[name_key(row.name)] = replace(known, persons=known.persons | found.persons)
        if not isinstance(found, str):
            how, found = NAME, person_id(NAME, name_key(row.name))
        joining.persons[row] = found
        members.setdefault(found, []).append((row, how))
    # The persons that an account or a name makes, not an alias or a meeting alone.
    made = {
        person for person, joins in members.items() for _, how in joins if how in {ACCOUNT, NAME}
    }
    nobody = {
        alias.key: replace(alias, means=None)
        for alias in joining.aliases.values()
        if alias.reason is None and PERSON_ID.fullmatch(alias.target) and alias.means not in made
    }
    if nobody:
        kept = {name: target for name, target in aliases.items() if name_key(name) not in nobody}
        again = joined(ordered, meetings, kept)
        unused = {alias.key: alias for alias in again.unused} | nobody
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
        spellings = sorted({Spelling(row.name, name_key(row.name), how) for row, how in joins})
        persons.append(Person(person, name, tuple(spellings)))
    return Joined(
        persons=tuple(persons),
        of=joining.persons,
        ambiguous=tuple(ambiguous[key] for key in sorted(ambiguous)),
        unused=tuple(alias for alias in joining.aliases.values() if alias.reason is not None),
    )
