"""Persons: every mention joined into one person, as each build of the index does.

``joined`` gives each mention, as a row of the index's people, the person of the first of
the joining rules of the concepts page that answers (docs/reference/concepts.md#person):
by identity, by alias, by name key, by attendance, by name. Beyond the page, a key whose
annotated names go by rule 5 to several persons is reported as ambiguous too, as the
annotations may be notes rather than names. Nothing here reads the index or the alias
file.
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
from typing import TYPE_CHECKING

from pydantic import ConfigDict, Field

from kb_mcp.kernel.names import ATLASSIAN_ISSUER, IDENTITY
from kb_mcp.kernel.record import Record
from kb_mcp.mirror.domain.mirror import PARTICIPANT

if TYPE_CHECKING:
    from collections.abc import Callable, Collection, Iterable

# A trailing part in brackets, once a key's spaces are collapsed: an annotation of the
# work log's, such as "Kim (not in the header)", and what it says. It needs a name
# before it.
ANNOTATION = re.compile(r"(?<=\S) ?\(([^()]*)\)\Z")
# A person's id, as an alias's value may give it.
PERSON_ID = re.compile(r"p-[0-9a-f]{16}")
# How a mention joined its person, as ``person_names.joined`` stores it.
BY_IDENTITY = "identity"
BY_ALIAS = "alias"
BY_ATTENDANCE = "attendance"
BY_NAME = "name"
# What a person's id hashes before an identity, and before a name's key.
IDENTITY_ANCHOR = "identity"
NAME_ANCHOR = "name"
# The issuers whose identities hash as account ids did before identities had an issuer:
# under LEGACY_ANCHOR and by their value alone, so that no id made then changed.
LEGACY_BARE_ISSUERS = frozenset({ATLASSIAN_ISSUER})
LEGACY_ANCHOR = "account"
# Why an alias changes nothing.
UNHELD = "no name without an identity has its key"
UNOWNED = "no mention holds this identity"
NOBODY = "its value names nobody"
SEVERAL = "its value names several persons"


def written_key(name: str) -> str:
    """Give a name's key with its annotation: ``name_key`` but for the part in brackets.

    The name casefolded, decomposed by NFKD without its accents, the combining
    diacritical marks of U+0300 to U+036F, as filters drop them, and casefolded again;
    its runs of white space made one space, trimmed; its annotation after one space,
    trimmed within its brackets, so that "Kim(late)" and "Kim ( late )" write one. A
    kana's voicing mark, which makes another letter, stays. The filters fold a value
    otherwise (``mcp.app.tools.canonical``): composed before they casefold it, its
    brackets as written, since a value is no name.
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
    """Give the first word of a name's key: a participant of that word may be its person.

    Rule 4 joins such a participant by its document's summaries; elsewhere, an answer
    shows them as perhaps the same.
    """
    return name_key(name).partition(" ")[0]


def person_id(anchor: str, value: str) -> str:
    """Give the id of the person that an identity, or a name's key, anchors.

    ``anchor`` is IDENTITY_ANCHOR or NAME_ANCHOR. The id is ``p-`` and the first 16 hex
    digits of the SHA-256 of the anchor, a line feed and the value; an identity of one of
    LEGACY_BARE_ISSUERS, of LEGACY_ANCHOR, a line feed and its value alone, which no
    other identity's hash can equal: an opaque id, stable while what anchors the person
    stays, so that no identity is served. It protects nothing: hashing a known identity
    finds it again. A second note on a name, which parts its annotated spellings by
    ``Joining.compared_key``, anchors each of them anew; the bare name keeps the id,
    which then names fewer documents.
    """
    issuer, _, bare = value.partition(":")
    legacy = anchor == IDENTITY_ANCHOR and issuer in LEGACY_BARE_ISSUERS
    hashed = f"{LEGACY_ANCHOR}\n{bare}" if legacy else f"{anchor}\n{value}"
    return "p-" + hashlib.sha256(hashed.encode()).hexdigest()[:16]


def aliases_digest(aliases: Mapping[str, str]) -> str:
    """Give the digest of what an alias file means: its names and values, in their order.

    All that ``joined`` reads of it, so a comment or a blank line leaves it as it was.
    """
    return hashlib.sha256(json.dumps(list(aliases.items())).encode()).hexdigest()


class PersonRow(Record):
    """A mention, as a row of the index's people holds it.

    ``identity`` is None for a name alone; ``updated`` is when the document was last
    updated, by which an identity's person is named.
    """

    document: int  # the document's number, by which rows are ordered
    role: str
    name: str
    identity: str | None
    updated: datetime


class Ambiguity(Record):
    """A name that could be several persons, which rule 5 gives the person by name of its key.

    That person may be one of those it could be. Or a key whose names annotations part
    among persons by name alone, such as "Kim (not in the header)" and "Kim (late)",
    which may be one Kim's notes.
    """

    name: str  # as the first of its rows in order writes it
    persons: frozenset[str]  # the ids of those it could be


# What a rule answers for a row: a person's id, an ambiguity, or nothing.
type Meant = str | Ambiguity | None


class Alias(Record):
    """A line of the alias file: a name as a source writes it, or an identity, and whom.

    ``index``'s JSON keeps the key that ``value`` had before plan 052, ``target``,
    whichever serialiser writes it.
    """

    model_config = ConfigDict(serialize_by_alias=True)
    name: str  # as the file writes it
    key: str  # the name's key, or the identity that a mention holds, as written
    value: str = Field(serialization_alias="target")  # a name, an identity or a person's id
    means: Meant  # the person its value names, several, or nobody
    held: bool  # whether a name without an identity has its key, or a mention its identity

    @property
    def reason(self) -> str | None:
        """Say why the alias changes nothing, or None when it joins its names.

        One written as an identity, which no mention holds, says so rather than that no
        name has its key.
        """
        if not self.held:
            return UNOWNED if IDENTITY.fullmatch(self.name) else UNHELD
        if self.means is None:
            return NOBODY
        return SEVERAL if isinstance(self.means, Ambiguity) else None


class Spelling(Record):
    """A name of a person as a source writes it, its key, and how it joined the person."""

    name: str
    name_key: str
    how: str  # BY_IDENTITY, BY_ALIAS, BY_ATTENDANCE or BY_NAME


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
    chained: tuple[int, ...] = ()  # the summaries that have summaries, dropped, by number


class JoinOutcome(Record):
    """What a build says of its join: how many persons, and what it left apart, as Joined."""

    count: int = 0
    ambiguous: tuple[Ambiguity, ...] = ()
    unused: tuple[Alias, ...] = ()
    chained: tuple[str, ...] = ()  # the paths of the summaries that summarise others too


class Joining:
    """What the rules read, and the person of each row joined so far.

    The names of the identities, the aliases, each document's summaries and each
    document's rows. Names compare by ``compared_key``: by their key, but for the names
    of a key written with two annotations or more, by a source or the user, such as
    "Alex (Ops)" and "Alex (Sales)", which were written apart, and which then keep them.
    """

    def __init__(
        self,
        rows: Iterable[PersonRow],
        summaries: Mapping[int, Collection[int]],
        aliases: Mapping[str, str],
    ) -> None:
        """Read the rows, the summaries of each document, by number, and the aliases.

        The aliases of identities are read first, by ``alias``, so that the values of
        the aliases of names see the identities that they make one. ``joined`` keeps an
        alias when an identity or a name makes the person that it means: aliases are not
        chained. No summary may have summaries itself, as ``joined`` ensures.
        """
        self.summaries = summaries
        self.persons: dict[PersonRow, str] = {}
        self.rows: dict[int, list[PersonRow]] = {}  # each document's
        # Each name key's names, by their written key, with their identity's own person,
        # None for a name without an identity.
        spelt: dict[str, set[tuple[str, str | None]]] = {}
        for row in rows:
            self.rows.setdefault(row.document, []).append(row)
            written = written_key(row.name)
            own = None if row.identity is None else person_id(IDENTITY_ANCHOR, row.identity)
            spelt.setdefault(ANNOTATION.sub("", written), set()).add((written, own))
        # Each identity that a mention holds, with its own person.
        self.owned = {
            row.identity: person_id(IDENTITY_ANCHOR, row.identity)
            for each in self.rows.values()
            for row in each
            if row.identity is not None
        }
        # The name keys that names, of an identity or not, write with two annotations or more.
        self.split = {
            key
            for key, names in spelt.items()
            if len({written for written, _ in names} - {key}) > 1
        }
        # Each ``compared_key``'s identities' own persons, and each name key's: a bare name
        # could be any identity of its key, an annotated one is that of its annotation.
        self.identities: dict[str, set[str]] = {}
        self.held: set[str] = set()  # the ``compared_key`` of each name without an identity
        for key, names in spelt.items():
            for written, own in names:
                compared = written if key in self.split else key
                if own is None:
                    self.held.add(compared)
                else:
                    for each in {key, compared}:
                        self.identities.setdefault(each, set()).add(own)
        # The name keys of the names without an identity.
        self.alone = {key for key, names in spelt.items() if any(own is None for _, own in names)}
        # The aliases of identities, whose values name persons as the mentions alone make
        # them; then each identity's own person that one names another, with that other.
        read = {
            name: self.alias(name, value, {})
            for name, value in aliases.items()
            if name in self.owned
        }
        self.moved: dict[str, str] = {
            self.owned[alias.key]: alias.means
            for alias in read.values()
            if isinstance(alias.means, str) and alias.reason is None
        }
        read |= {
            name: self.alias(name, value, self.moved)
            for name, value in aliases.items()
            if name not in self.owned
        }
        self.aliases = {read[name].key: read[name] for name in aliases}

    def alias(self, name: str, value: str, moved: Mapping[str, str]) -> Alias:
        """Read a line of the alias file: what it holds, and the person its value means.

        It holds a name's key, or an identity that a mention holds. Its value is a
        person's id, or the person that ``moved`` gives that id; an identity that a
        mention holds, which means that identity's own
        person, or the one that ``moved`` gives it; or a name, which means the one
        identity's person of its key, as rule 3 finds it with ``moved``, else the person
        by name alone of a key that a name without an identity holds.
        """
        if PERSON_ID.fullmatch(value):
            means: Meant = moved.get(value, value)
        else:
            compared, own = self.compared_key(value), self.owned.get(value)
            means = (
                moved.get(own, own)
                or self.identified(value, moved)
                or (person_id(NAME_ANCHOR, compared) if compared in self.held else None)
            )
        key = name if name in self.owned else name_key(name)
        held = name in self.owned or key in self.alone
        return Alias(name=name, key=key, value=value, means=means, held=held)

    def compared_key(self, name: str) -> str:
        """Give the key by which the join compares a name, and a name alone's id hashes.

        Its key, but its written key, annotation kept, where two annotations or more
        tell apart names of that key.
        """
        written = written_key(name)
        key = ANNOTATION.sub("", written)
        return written if key in self.split else key

    def identified(self, name: str, moved: Mapping[str, str] | None = None) -> Meant:
        """Find the person of the one identity with a name of this name's ``key``.

        Identities that ``moved``, by default the aliases' ``self.moved``, makes one, each
        own person to another's, are one. A name of several identities' key is ambiguous,
        as is a bare name whose key's identities annotations tell apart; one of none,
        None.
        """
        found = self.identities.get(self.compared_key(name), set())
        made_one = self.moved if moved is None else moved
        persons = {made_one.get(person, person) for person in found}
        if len(persons) > 1:
            return Ambiguity(name=name, persons=frozenset(persons))
        return next(iter(persons), None)


def by_alias(row: PersonRow, joining: Joining) -> Meant:
    """Give a name without an identity to the person its alias means (rule 2).

    An alias whose value names nobody, or several, changes nothing; nor does it take a
    participant whom rule 4 gives one other person: the user wrote the summaries'
    participants for that document, and the alias for the name anywhere.
    """
    alias = joining.aliases.get(name_key(row.name))
    if alias is None or alias.reason is not None:
        return None
    attended = by_attendance(row, joining)
    return None if isinstance(attended, str) and attended != alias.means else alias.means


def by_name(row: PersonRow, joining: Joining) -> Meant:
    """Join a name without an identity to the one identity of its key (rule 3).

    A name of several identities' key is ambiguous; so is a participant whom rule 4
    gives persons that do not hold that identity: the origin's name and the summaries'
    participants then disagree. A participant of several identities' key could be any
    of them or rule 4's persons.
    """
    found = joining.identified(row.name)
    attended = by_attendance(row, joining)
    if attended is None or found is None:
        return found
    others = attended.persons if isinstance(attended, Ambiguity) else frozenset({attended})
    if isinstance(found, Ambiguity):
        return Ambiguity(name=row.name, persons=found.persons | others)
    return found if found in others else Ambiguity(name=row.name, persons=others | {found})


def by_attendance(row: PersonRow, joining: Joining) -> Meant:
    """Join a participant by the summaries of its document (rule 4).

    A participant whose key is the first word of the keys of some of the summaries'
    participants, and so one word, joins their person when they are one, and is
    ambiguous when they are several. Their rows must be joined already.
    """
    if row.role != PARTICIPANT:
        return None
    key = name_key(row.name)
    persons = {
        joining.persons[other]
        for summary in joining.summaries.get(row.document, ())
        for other in joining.rows.get(summary, ())
        if other.role == PARTICIPANT and first_word(other.name) == key
    }
    if len(persons) > 1:
        return Ambiguity(name=row.name, persons=frozenset(persons))
    return next(iter(persons), None)


# Rules 2 to 4, each with how a name joins by it, in the order that ``joined`` tries them,
# the first answer winning. The order is not all of it: rules 2 and 3 read rule 4's
# answer, so that neither takes a participant whom the summaries give another person; a
# rule added here says how it stands to rule 4.
RULES: tuple[tuple[str, Callable[[PersonRow, Joining], Meant]], ...] = (
    (BY_ALIAS, by_alias),
    (BY_NAME, by_name),
    (BY_ATTENDANCE, by_attendance),
)


def joined(
    rows: Iterable[PersonRow], summaries: Mapping[int, Collection[int]], aliases: Mapping[str, str]
) -> Joined:
    """Join every row into its person: by its identity, by RULES in order, or by its name.

    ``summaries`` gives each document's summaries, by number, as its ``summary`` links
    name them; one that has summaries itself, as a file edited by hand may, is dropped
    and named in ``chained``, as rule 4 needs each summary joined before; ``aliases`` each
    alias's name and value, of distinct keys, as the alias file's reader checks. Rows go
    in order of document, role, name and identity, those of documents with summaries
    last, so that their summaries' persons are known; the same rows in any order give
    the same result. A person is served by the name on its identities' most recently
    updated document; else by the value of the alias that made it, when that is a name;
    else by its most frequent spelling: ties go to the first row in order. An alias whose
    value means a person that no identity or name makes, but aliases or attendance
    alone, names nobody: the join is made again without it, each pass with fewer
    aliases.
    """
    chained = {each for linked in summaries.values() for each in linked if summaries.get(each)}
    kept = {
        document: rest for document, linked in summaries.items() if (rest := set(linked) - chained)
    }
    ordered = sorted(
        set(rows),
        key=lambda row: (
            row.document in kept,
            row.document,
            row.role,
            row.name,
            row.identity or "",
            row.updated,
        ),
    )
    joining = Joining(ordered, kept, aliases)
    members: dict[str, list[tuple[PersonRow, str]]] = {}  # each person's rows, and how each joined
    ambiguous: dict[str, Ambiguity] = {}  # by key
    for row in ordered:
        if row.identity is not None:
            itself = person_id(IDENTITY_ANCHOR, row.identity)
            found = joining.moved.get(itself, itself)
            how = BY_IDENTITY if found == itself else BY_ALIAS
        else:
            answers = ((how, rule(row, joining)) for how, rule in RULES)
            how, found = next(
                ((how, each) for how, each in answers if each is not None), (BY_NAME, None)
            )
        # The persons that the row could be, of whom rule 5 may give it one; and, for a
        # name alone that its annotation keeps from the other names of its key, its own.
        could = found.persons if isinstance(found, Ambiguity) else frozenset()
        if not isinstance(found, str):
            compared = joining.compared_key(row.name)
            how, found = BY_NAME, person_id(NAME_ANCHOR, compared)
            if compared != name_key(row.name):
                could |= {found}
        if could:
            key = name_key(row.name)
            known = ambiguous.setdefault(key, Ambiguity(name=row.name, persons=could))
            ambiguous[key] = replace(known, persons=known.persons | could)
        joining.persons[row] = found
        members.setdefault(found, []).append((row, how))
    # The persons that an identity or a name makes, whatever rule joined that name to its
    # own person, but not an alias or attendance alone, which join a name to another's.
    made = {
        person
        for person, joins in members.items()
        for row, how in joins
        if how == BY_IDENTITY or person == person_id(NAME_ANCHOR, joining.compared_key(row.name))
    }
    nobody = {
        alias.key: replace(alias, means=None)
        for alias in joining.aliases.values()
        if alias.reason is None and alias.means not in made
    }
    if nobody:
        remaining = {
            each.name: each.value for each in joining.aliases.values() if each.key not in nobody
        }
        again = joined(ordered, summaries, remaining)
        unused = {alias.key: alias for alias in again.unused} | nobody
        return replace(again, unused=tuple(unused[key] for key in joining.aliases if key in unused))
    # Each name alone's value as an alias writes it, the first alias's in their order.
    written = {
        alias.means: alias.value
        for alias in reversed(joining.aliases.values())
        if alias.reason is None and not PERSON_ID.fullmatch(alias.value)
    }
    persons = []
    for person, joins in sorted(members.items()):
        own = [row for row, _ in joins if row.identity is not None]
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
        chained=tuple(sorted(chained)),
    )
