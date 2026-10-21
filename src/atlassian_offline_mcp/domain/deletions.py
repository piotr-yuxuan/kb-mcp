"""Documents that the site no longer has: when to say so, and when not to believe it.

A document absent from its space's new listing is probed once a run. A first answer of
gone makes a tombstone; a second, on a later run, confirms it, and the mirror then
leaves the document out. Too many gone at once is more likely a lost session than a
mass deletion, so the caller checks the session before believing it.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping
    from datetime import datetime

# Gone answers in one space beyond which the session is checked again: a count, and a
# share of the space's stored documents.
MASS_COUNT = 10
MASS_SHARE = 0.05


class Answer(StrEnum):
    """What a probe of an absent document found."""

    GONE = "gone"  # 404, or trashed
    MOVED = "moved"  # in another space
    PRESENT = "present"  # still in its space: the listing missed it


@dataclass(frozen=True)
class Tombstone:
    """A document that answered as gone: confirmed once it answers so on a later run."""

    kind: str  # pages or blogposts
    id: str
    space_id: str
    first_gone: datetime
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
    fewer than the absent. A document listed again, moved or present loses its tombstone;
    one not probed this time keeps it as it was.
    """
    kept: dict[tuple[str, str], Tombstone] = {}
    for key, stone in known.items():
        answer = answers.get(key)
        if key in absent and answer is None:
            kept[key] = stone
        elif key in absent and answer is Answer.GONE:
            kept[key] = replace(stone, confirmed=True)
    for key, space_id in absent.items():
        if key not in known and answers.get(key) is Answer.GONE:
            kept[key] = Tombstone(key[0], key[1], space_id, now)
    return kept


def too_many_gone(answers: Mapping[tuple[str, str], Answer], stored: int) -> bool:
    """Say whether so many answered gone that the session must be checked first."""
    gone = sum(answer is Answer.GONE for answer in answers.values())
    return gone > MASS_COUNT or gone > MASS_SHARE * stored
