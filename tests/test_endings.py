"""How a run's endings fold into its exit status, and what an outcome holds, as the run says.

The most severe ending gives the status: interrupted 130, over sign in again 3, over
failed 1, over done 0; not run, a unit that a dry run left alone, is 0 as well. A run
that stops of its own before any unit acts exits 1 if declined, 2 if refused, 130 if
interrupted, as ``tests/test_confirmation.py`` and ``tests/test_cli.py`` show through the
command line.
"""

from __future__ import annotations

from itertools import product
from typing import TYPE_CHECKING

import pytest
from pydantic import ValidationError

from kb_mcp.kernel.exit_status import Ending, ExitStatus, folded
from kb_mcp.kernel.names import RefusedError
from kb_mcp.kernel.outcome import Outcome, OutcomeWarning, Problem
from kb_mcp.kernel.record import Record

if TYPE_CHECKING:
    from kb_mcp.kernel.output import Detail

# Each ending and its status, most severe first, as the page lists them.
SEVERITY = (
    ("interrupted", 130),
    ("sign in again", 3),
    ("failed", 1),
    ("done", 0),
    ("not run", 0),
)


@pytest.mark.parametrize(
    ("first", "second"), list(product(SEVERITY, repeat=2)), ids=lambda pair: pair[0]
)
def test_two_endings_fold_into_the_status_of_the_more_severe(
    first: tuple[str, int], second: tuple[str, int]
) -> None:
    """Each pair, in either order, exits as the more severe of the two."""
    expected = SEVERITY[min(SEVERITY.index(first), SEVERITY.index(second))][1]
    assert folded([first[0], second[0]]) == expected


def test_not_run_alone_and_no_ending_at_all_exit_0() -> None:
    """A run whose units a dry run left alone, or that has none, exits 0."""
    assert folded(["not run"]) == ExitStatus.OK
    assert folded([]) == ExitStatus.OK


# A problem's place and reason, as fetch gives one.
PROBLEM = Problem(where="space MFS", reason="not found")


@pytest.mark.parametrize("ending", ["done", "not run"])
def test_an_outcome_done_or_not_run_with_a_problem_is_refused(ending: str) -> None:
    """A problem ends its unit failed, a dry run's too."""
    with pytest.raises(RefusedError, match=f"^ending {ending} with 1 problems"):
        Outcome(ending=ending, problems=(PROBLEM,))


@pytest.mark.parametrize("ending", ["failed", "sign in again", "interrupted"])
def test_an_outcome_that_did_not_end_well_may_hold_problems(ending: str) -> None:
    """Failed, to sign in again or interrupted, a unit says what it left undone."""
    assert Outcome(ending=ending, problems=(PROBLEM,)).problems == (PROBLEM,)


class Untold(Record):
    """Counts that cannot write themselves: no ``text``."""

    documents: int


def test_counts_that_cannot_write_themselves_are_refused() -> None:
    """The counts are a stage's record that writes itself as text, short or detailed."""
    with pytest.raises(ValidationError, match="instance of Counts"):
        Outcome(ending="done", counts=Untold(documents=1))


class Counted(Record):
    """Counts that write themselves, whichever the detail."""

    documents: int

    def text(self, _detail: Detail) -> str:
        """Write the documents counted."""
        return f"documents: {self.documents}\n"


def test_short_names_three_problems_and_warnings_of_each_and_counts_the_rest() -> None:
    """Short stays short; detailed names every one; both give each total."""
    problems = tuple(Problem(where=f"page {n}", reason="status 503") for n in range(5))
    warnings = (OutcomeWarning(where="meeting 1", reason="no transcript"),)
    outcome = Outcome(
        ending="failed", counts=Counted(documents=2), problems=problems, warnings=warnings
    )
    named = [f"problem: page {n}: status 503\n" for n in range(5)]
    said = "warning: meeting 1: no transcript\nproblems: 5\nwarnings: 1\n"
    assert outcome.text("short") == "documents: 2\n" + "".join(named[:3]) + (
        "and 2 more problems\n" + said
    )
    assert outcome.text("detailed") == "documents: 2\n" + "".join(named) + said


@pytest.mark.parametrize(
    ("otherwise", "problems", "ending"),
    [
        ("done", (), "done"),
        ("not run", (), "not run"),
        ("done", (PROBLEM,), "failed"),
        ("not run", (PROBLEM,), "failed"),
    ],
)
def test_an_outcome_of_a_problem_ends_failed_whatever_it_would_end_otherwise(
    otherwise: Ending, problems: tuple[Problem, ...], ending: str
) -> None:
    """The kernel owns the rule: a problem ends its unit failed, a dry run's too."""
    assert Outcome.of(problems=problems, otherwise=otherwise).ending == ending
