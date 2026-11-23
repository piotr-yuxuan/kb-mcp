"""How a run's result is written and what it says: the choices that the options offer.

Standard library only, and light, since the parser takes its choices from here.
"""

from __future__ import annotations

from typing import Literal

# The levels of what a run says on stderr, as --log-level names them, least severe first.
type Level = Literal["debug", "info", "warning", "error"]
LEVELS: tuple[Level, ...] = ("debug", "info", "warning", "error")
# How much of a result is written on stdout: what matters, or all of it.
type Detail = Literal["short", "detailed"]
DETAILS: tuple[Detail, ...] = ("short", "detailed")
# How a result is written on stdout: as lines to read, or as one JSON document.
type Format = Literal["text", "json"]
FORMATS: tuple[Format, ...] = ("text", "json")
