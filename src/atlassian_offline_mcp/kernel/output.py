"""How a run reports: the level of what it says, -q, how its result is written, its terminals.

Standard library only, and light, since the parser takes its choices from here; the
entry builds ``Output`` from the options, for the command line and plan 016's logs.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

# The levels of what a run says on stderr, as --log-level names them, least severe first.
type Level = Literal["debug", "info", "warning", "error"]
LEVELS: tuple[Level, ...] = ("debug", "info", "warning", "error")
# How much of a result is written on stdout: what matters, or all of it.
type Summary = Literal["short", "detailed"]
SUMMARIES: tuple[Summary, ...] = ("short", "detailed")
# How a result is written on stdout: as lines to read, or as one JSON document.
type Format = Literal["text", "json"]
FORMATS: tuple[Format, ...] = ("text", "json")


@dataclass(frozen=True)
class Output:
    """How a run reports, as its options and its terminals say.

    ``level`` is the least severe of what it says on stderr, and leaves stdout alone;
    ``summary`` and ``format`` say how its result is written on stdout. ``quiet``, from
    -q alone, which sets the level error, leaves a result as text unwritten, and what is
    said before a run that asks nothing. ``stdin_terminal`` and ``stderr_terminal`` say
    whether someone can read a question there and answer it.
    """

    level: Level
    summary: Summary
    format: Format
    quiet: bool
    stdin_terminal: bool
    stderr_terminal: bool

    def __post_init__(self) -> None:
        """Refuse ``quiet`` at a level other than error, which -q sets.

        Raises ValueError.
        """
        if self.quiet and self.level != "error":
            message = f"quiet at the level {self.level}: -q sets the level error"
            raise ValueError(message)
