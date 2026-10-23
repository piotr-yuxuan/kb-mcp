"""How long a task has left, at the pace it has kept since it began.

Both the bars on the terminal and the events ``progress`` say it, so that they agree.
"""

from __future__ import annotations


def remaining(done: float, total: float | None, elapsed: float) -> float | None:
    """Say how many seconds a task of ``total`` items has left, ``done`` in ``elapsed`` s.

    Each item left takes as long as those done took on average. None when it cannot be
    told: the total is not known, or nothing is done yet. A task with all its items
    done, or more, has none left.
    """
    if total is None or done <= 0:
        return None
    return max(total - done, 0) * elapsed / done
