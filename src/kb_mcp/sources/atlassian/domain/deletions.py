"""Documents that the site no longer has: when to say so, and when not to believe it.

A document absent from its space's new listing gets a tombstone, pending until a probe
answers. A first answer of gone dates it; a second, on a later run, confirms it, and
the mirror then leaves the document out. Too many gone at once is more likely a lost session than a
mass deletion, so the caller checks the session before believing it.
"""

from __future__ import annotations

from copy import replace
from datetime import datetime, timedelta
from enum import StrEnum
from typing import TYPE_CHECKING, Self

from pydantic import model_validator

from kb_mcp.kernel.names import RefusedError
from kb_mcp.kernel.record import Record

if TYPE_CHECKING:
    from collections.abc import Collection, Mapping

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

    GONE = "gone"  # 404 (deleted, or no longer visible), trashed, or in a space never kept
    MOVED = "moved"  # in a space whose stored listing names it: followed there now
    UNSETTLED = "unsettled"  # found, but no stored listing names it yet: probed again


class Tombstone(Record):
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

    @model_validator(mode="after")
    def check_tombstone(self) -> Self:
        """Refuse a confirmation without the first answer that it follows."""
        if self.confirmed and self.first_gone is None:
            message = "confirmed: without a first answer of gone"
            raise RefusedError(message)
        return self

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
        stone = known.get(key, Tombstone(kind=key[0], id=key[1], space_id=space_id))
        answer = answers.get(key)
        if answer is None:
            kept[key] = stone
        elif answer is Answer.GONE and stone.first_gone is None:
            kept[key] = replace(stone, first_gone=now)
        elif answer is Answer.GONE:
            # Two answers moments apart prove little: confirmation waits a while.
            kept[key] = replace(stone, confirmed=now - stone.first_gone >= CONFIRM_AFTER)
        elif answer is Answer.UNSETTLED:
            kept[key] = replace(stone, first_gone=None, confirmed=False)
    return kept


def too_many_gone(answers: Mapping[tuple[str, str], Answer], stored: int) -> bool:
    """Say whether so many answered gone that the session must be checked first."""
    gone = sum(answer is Answer.GONE for answer in answers.values())
    return gone > MASS_COUNT or gone > MASS_SHARE * stored


def answer_of(found_space: str, status: str, kept: Collection[str], *, named: bool) -> Answer:
    """Say what a probe that the site answered found.

    ``kept`` are the spaces whose listings the store keeps; ``named`` says whether the
    found space's stored listing names the document. A document trashed, or in a space
    the store never listed, is gone; one that a stored listing names has moved there, and
    is followed by that space's own listing; any other is still somewhere, unsettled,
    and probed again on a later run, so that its tracking never ends unseen.
    """
    if status in GONE_STATUSES or found_space not in kept:
        return Answer.GONE
    return Answer.MOVED if named else Answer.UNSETTLED


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
