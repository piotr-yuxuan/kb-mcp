"""How a run's endings fold into its exit status, as the concepts page's run says.

The most severe ending gives the status: interrupted 130, over sign in again 3, over
failed 1, over done 0; not run, a unit that a dry run left alone, is 0 as well.
"""

from __future__ import annotations

from itertools import product

import pytest

from kb_mcp.kernel.exit_status import ExitStatus, folded

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
