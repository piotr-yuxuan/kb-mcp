"""What a recorded run writes that each run makes anew: its run's id, first in its text.

Plan 062: each run of ``fetch``, ``prepare``, ``index``, ``embed`` and ``refresh`` is
recorded under ``runs/<run id>/``, and its text begins with ``run <run id>``; one that
records nothing, such as a dry run, says ``, not recorded`` after it.
"""

from __future__ import annotations

import json

from kb_mcp.kernel.names import RUN_ID


def unrun(text: str) -> str:
    """Give a recorded run's text without its first line, which names its run's id."""
    first, _, rest = text.partition("\n")
    head, _, run = first.removesuffix(", not recorded").partition(" ")
    if head != "run" or not RUN_ID.fullmatch(run):
        message = f"not a run's id first: {first!r}"
        raise AssertionError(message)
    return rest


def runless(document: str | bytes) -> dict[str, object]:
    """Give a recorded run's JSON result without its run's id, which each run makes anew."""
    found = json.loads(document)
    if not RUN_ID.fullmatch(str(found.pop("run", ""))):
        message = "no run's id in the result"
        raise AssertionError(message)
    return found
