"""The exit statuses of every command, and the endings of a run's units that fold into them."""

from __future__ import annotations

from enum import IntEnum
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from collections.abc import Iterable

# How a unit of a run ended: done; failed; the sign-in no longer holding; not run, as a
# unit that a dry run leaves alone or that an interruption reached before it started; or
# interrupted.
type Ending = Literal["done", "failed", "sign in again", "not run", "interrupted"]
# How a run ended of its own: before any unit acted, declined, refused or interrupted;
# after, failed by an error that no unit caught.
type RunEnding = Literal["declined", "refused", "interrupted", "failed"]


class ExitStatus(IntEnum):
    """How a run ended, as the shell reads it; ``MEANINGS`` says what each means."""

    OK = 0
    FAILED = 1
    REFUSED = 2
    SIGN_IN_AGAIN = 3
    INTERRUPTED = 130


# What each status means, as the program's --help lists them.
MEANINGS = {
    ExitStatus.OK: "done",
    ExitStatus.FAILED: "something failed (a document, a file, a check, the endpoint), or the"
    " question was declined",
    ExitStatus.REFUSED: "refused before acting: settings, options or input, or no terminal to"
    " ask on",
    ExitStatus.SIGN_IN_AGAIN: "sign in again: no session saved, it no longer holds, or the"
    " site refused the API token",
    ExitStatus.INTERRUPTED: "stopped by Ctrl-C",
}

# The exit status of each ending, a unit's or the run's own. Their numbers rank them, most
# severe highest: interrupted, then sign in again, then failed; done and not run are 0.
# Declined and refused end a run before any unit acts, so that nothing else folds with them.
ENDED: dict[Ending | RunEnding, ExitStatus] = {
    "done": ExitStatus.OK,
    "not run": ExitStatus.OK,
    "failed": ExitStatus.FAILED,
    "declined": ExitStatus.FAILED,
    "refused": ExitStatus.REFUSED,
    "sign in again": ExitStatus.SIGN_IN_AGAIN,
    "interrupted": ExitStatus.INTERRUPTED,
}


def folded(endings: Iterable[Ending | RunEnding]) -> ExitStatus:
    """Give the exit status of the most severe of these endings; OK for none."""
    return max((ENDED[ending] for ending in endings), default=ExitStatus.OK)
