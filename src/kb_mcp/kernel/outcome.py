"""What a unit of a run gives: how it ended, its stage's counts, its problems, its warnings.

A unit is a stage applied to one source, or over the whole. ``--format json`` writes its
outcome as it is; ``said`` writes its problems and warnings as the command's text does.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self

from pydantic import model_validator

from kb_mcp.kernel.exit_status import Ending
from kb_mcp.kernel.names import RefusedError
from kb_mcp.kernel.record import Record

if TYPE_CHECKING:
    from kb_mcp.kernel.output import Detail


class Problem(Record):
    """An item that a unit left undone: where it is, and why, never its content."""

    where: str
    reason: str


class OutcomeWarning(Record):
    """What a person should know of a unit that changes neither its ending nor what it removes."""

    where: str
    reason: str


class Outcome[C](Record):
    """How a unit ended, its stage's own record of counts, its problems and its warnings.

    ``counts`` is None for a unit that gave none: one that could not start, or that an
    interruption reached. A problem ends its unit failed, or, in a dry run, not run.
    """

    ending: Ending
    counts: C | None = None
    problems: tuple[Problem, ...] = ()
    warnings: tuple[OutcomeWarning, ...] = ()

    @model_validator(mode="after")
    def check_outcome(self) -> Self:
        """Refuse an outcome done with a problem."""
        if self.ending == "done" and self.problems:
            message = f"ending done with {len(self.problems)} problems: a problem fails its unit"
            raise RefusedError(message)
        return self

    def said(self, detail: Detail) -> str:
        """Write how many problems and warnings; in detail, each by its place and reason."""
        shown = (
            [("problem", each) for each in self.problems]
            + [("warning", each) for each in self.warnings]
            if detail == "detailed"
            else []
        )
        return (
            "".join(f"{kind}: {each.where}: {each.reason}\n" for kind, each in shown)
            + f"problems: {len(self.problems)}\n"
            + f"warnings: {len(self.warnings)}\n"
        )
