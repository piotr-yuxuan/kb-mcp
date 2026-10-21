"""Documents that the site no longer has: when to say so, and when not to believe it.

A document absent from its space's new listing gets a tombstone, pending until a probe
answers. A first answer of gone dates it; a second, on a later run, confirms it, and
the mirror then leaves the document out. Too many gone at once is more likely a lost session than a
mass deletion, so the caller checks the session before believing it.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import timedelta
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Collection, Mapping
    from datetime import datetime

# Gone answers in one space beyond which the session is checked again: a count, and a
# share of the space's stored documents.
MASS_COUNT = 10
MASS_SHARE = 0.05
# How long after a first answer of gone a second one confirms it.
CONFIRM_AFTER = timedelta(hours=1)
# The statuses of a document that the site still answers for, but that is gone.
GONE_STATUSES = frozenset({"trashed", "deleted", "purged"})


class Answer(StrEnum):
    """What a probe of an absent document found."""

    GONE = "gone"  # 404 (deleted, or no longer visible), trashed, or moved out of scope
    MOVED = "moved"  # in another space that the store keeps
    PRESENT = "present"  # still in its space: the listing missed it


@dataclass(frozen=True)
class Tombstone:
    """A document absent from its space's listing, on its way to being believed gone.

    It is pending until a probe answers gone (``first_gone`` is then that time), and
    confirmed once a later probe, at least ``CONFIRM_AFTER`` later, answers gone again.
    A pending one waits for a probe, however many runs that takes.
    """

    kind: str  # pages or blogposts
    id: str
    space_id: str
    first_gone: datetime | None = None
    confirmed: bool = False

    @property
    def key(self) -> tuple[str, str]:
        """Name the document by its kind and id."""
        return self.kind, self.id


def after_probes(
    known: Mapping[tuple[str, str], Tombstone],
    absent: Mapping[tuple[str, str], str],
    answers: Mapping[tuple[str, str], Answer],
    now: datetime,
) -> dict[tuple[str, str], Tombstone]:
    """Return the tombstones of one space once its absent documents were probed.

    ``known`` are the space's tombstones before; ``absent`` maps each document missing
    from the new listing to its space; ``answers`` holds the probes made, which may be
    fewer than the absent, or none. An absent document without an answer keeps its
    tombstone, or becomes pending; one answering gone moves on a step; one listed again,
    moved or present loses its tombstone.
    """
    kept: dict[tuple[str, str], Tombstone] = {}
    for key, space_id in absent.items():
        stone = known.get(key, Tombstone(key[0], key[1], space_id))
        answer = answers.get(key)
        if answer is None:
            kept[key] = stone
        elif answer is Answer.GONE and stone.first_gone is None:
            kept[key] = replace(stone, first_gone=now)
        elif answer is Answer.GONE:
            # Two answers moments apart prove little: confirmation waits a while.
            kept[key] = replace(stone, confirmed=now - stone.first_gone >= CONFIRM_AFTER)
    return kept


def too_many_gone(answers: Mapping[tuple[str, str], Answer], stored: int) -> bool:
    """Say whether so many answered gone that the session must be checked first."""
    gone = sum(answer is Answer.GONE for answer in answers.values())
    return gone > MASS_COUNT or gone > MASS_SHARE * stored


def answer_of(found_space: str, status: str, listed_space: str, kept: Collection[str]) -> Answer:
    """Say what a probe that the site answered found: gone, moved, or still there.

    ``kept`` are the spaces whose listings the store keeps. A document trashed, or moved
    to a space the store does not keep, has left the mirror's scope: it is gone too.
    """
    if status in GONE_STATUSES or found_space not in kept:
        return Answer.GONE
    return Answer.MOVED if found_space != listed_space else Answer.PRESENT


def probing_order(
    absent: Collection[tuple[str, str]], known: Mapping[tuple[str, str], Tombstone]
) -> list[tuple[str, str]]:
    """Order the absent for probing, leaving out those confirmed gone.

    Those on their way (answered gone once, or pending) come first, so that a cap on
    probes never starves them; a confirmed one comes back by being listed again, not by
    a probe.
    """
    open_ = [key for key in absent if not (key in known and known[key].confirmed)]
    return sorted(open_, key=lambda key: (key not in known, key))
