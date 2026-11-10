"""What a unit of a run gives: how it ended, its stage's counts, its problems, its warnings.

A unit is a stage applied to one source, or over the whole. ``--format json`` writes its
outcome as it is; ``text`` writes it as the command's text does.
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
    interruption reached; else a record whose ``text`` writes it, short or detailed. A
    problem ends its unit failed, a dry run's too: never done nor not run.
    """

    ending: Ending
    counts: C | None = None
    problems: tuple[Problem, ...] = ()
    warnings: tuple[OutcomeWarning, ...] = ()

    @model_validator(mode="after")
    def check_outcome(self) -> Self:
        """Refuse an outcome done or not run with a problem."""
        if self.ending in {"done", "not run"} and self.problems:
            message = (
                f"ending {self.ending} with {len(self.problems)} problems: a problem fails its unit"
            )
            raise RefusedError(message)
        return self

    def text(self, detail: Detail) -> str:
        """Write the counts, then how many problems and warnings; in detail, each of them.

        A unit that gave nothing, no counts, problems or warnings, writes nothing.
        """
        if self.counts is None and not self.problems and not self.warnings:
            return ""
        shown = (
            [("problem", each) for each in self.problems]
            + [("warning", each) for each in self.warnings]
            if detail == "detailed"
            else []
        )
        return (
            ("" if self.counts is None else self.counts.text(detail))
            + "".join(f"{kind}: {each.where}: {each.reason}\n" for kind, each in shown)
            + f"problems: {len(self.problems)}\n"
            + f"warnings: {len(self.warnings)}\n"
        )
