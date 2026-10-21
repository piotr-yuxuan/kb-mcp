"""The measures of a ranking and the paired test, against values worked out by hand."""

from __future__ import annotations

import itertools
import math
from statistics import fmean

import pytest

from atlassian_offline_mcp.domain.evaluation import (
    Measures,
    Question,
    averages,
    holm,
    measure,
    paired_test,
    percentile,
)

QUESTION = Question(
    "q1",
    "a question",
    expected=("a", "b"),
    partial=("c",),
    groups=("keyword", "en"),
    evidence={"a": "Pause, drain, then roll back.", "b": "ninety days"},
)
CLOSE = 0.02
SIGNIFICANT = 0.05
HALF = 0.5
NINETEEN = 19
TEN = 10
SEVEN = 7.0


def test_recall_counts_the_expected_documents_within_ten() -> None:
    """One of two expected in the first ten is a half; one at rank 11 does not count."""
    assert measure(["x", "a", "y"], QUESTION).recall == HALF
    eleventh = [f"filler-{n}" for n in range(10)] + ["a", "b"]
    assert measure(eleventh, QUESTION).recall == 0.0


def test_the_reciprocal_rank_is_of_the_first_expected_document() -> None:
    """A partial document before it does not count; none within ten gives 0."""
    assert measure(["c", "x", "b", "a"], QUESTION).reciprocal_rank == pytest.approx(1 / 3)
    assert measure([f"filler-{n}" for n in range(10)] + ["a"], QUESTION).reciprocal_rank == 0.0


def test_ndcg_weighs_expected_documents_twice_partial_ones() -> None:
    """[c, a]: (1/log2 2 + 2/log2 3) over the ideal [a, b, c]: 2 + 2/log2 3 + 1/log2 4."""
    found = 1 + 2 / math.log2(3)
    ideal = 2 + 2 / math.log2(3) + 1 / math.log2(4)
    assert measure(["c", "a"], QUESTION).ndcg == pytest.approx(found / ideal)
    assert measure(["a", "b", "c"], QUESTION).ndcg == pytest.approx(1.0)


def test_success_is_an_expected_document_first() -> None:
    """A partial document first is not a success, and nor is an empty ranking."""
    assert measure(["b", "x"], QUESTION).success == 1.0
    assert measure(["c", "a"], QUESTION).success == 0.0
    assert measure([], QUESTION).success == 0.0


def test_averages_are_overall_and_per_group() -> None:
    """Each group averages its own questions, a question counting in each of its groups."""
    other = Question("q2", "another", expected=("z",), groups=("paraphrase", "en"))
    per = {"q1": measure(["a"], QUESTION), "q2": measure(["x"], other)}
    found = averages(per, [QUESTION, other])
    assert found["keyword"].success == 1.0
    assert found["paraphrase"].success == 0.0
    assert found["en"] == found["all"]
    overall = found["all"]
    expected = Measures(0.25, reciprocal_rank=HALF, ndcg=overall.ndcg, success=HALF, section=0.0)
    assert overall == expected


def test_section_counts_expected_documents_whose_shown_section_holds_the_evidence() -> None:
    """Marks and links aside, case and spacing aside; documents not found do not count."""
    shown = {
        "a": "## Rollback\n\n**Pause**, drain,\nthen [roll back](../x.md).",
        "b": "## Other\n\nNothing here.",
    }
    assert measure(["a", "b"], QUESTION, shown).section == HALF
    assert measure(["a"], QUESTION, shown).section == 1.0
    assert measure(["x"], QUESTION, shown).section is None
    assert (
        Measures.mean([measure(["x"], QUESTION, shown), measure(["a"], QUESTION, shown)]).section
        == 1.0
    )


def test_holm_adjusts_by_rank_and_keeps_the_order() -> None:
    """[0.01, 0.04, 0.03]: 3 x 0.01, 2 x 0.03, then at least that: 0.03, 0.06, 0.06."""
    assert holm([0.01, 0.04, 0.03]) == pytest.approx([0.03, 0.06, 0.06])
    assert holm([0.6, 0.7]) == [1.0, 1.0]  # 1.2 and 0.7, capped and kept rising


def test_the_percentile_is_the_nearest_rank() -> None:
    """The smallest value that the share of them reach: of 1 to 20, the 95th is 19."""
    assert percentile(list(range(20, 0, -1)), 0.95) == NINETEEN
    assert percentile(list(range(1, 11)), 0.95) == TEN
    assert percentile([SEVEN], 0.95) == SEVEN


def test_evidence_in_a_table_row_is_found_without_its_pipes() -> None:
    """Plain text renders a row's cells apart by spaces, as the evidence was taken."""
    question = Question("q", "x", expected=("a",), evidence={"a": "SEV1 15 minutes"})
    assert measure(["a"], question, {"a": "| SEV1 | 15 minutes |"}).section == 1.0


def test_two_equal_runs_do_not_differ() -> None:
    """No difference at all: p is 1."""
    assert paired_test([0.5, 1.0, 0.0], [0.5, 1.0, 0.0]) == 1.0


def test_a_consistent_improvement_is_significant_and_reproducible() -> None:
    """Thirty questions each a little better: no sign flip but one reaches it."""
    before = [0.2] * 30
    after = [0.3] * 30
    p = paired_test(before, after)
    assert p < SIGNIFICANT
    assert paired_test(before, after) == p


def test_a_mixed_difference_is_not_significant() -> None:
    """Half better, half worse by as much: no evidence either way."""
    before = [0.5] * 30
    after = [0.6, 0.4] * 15
    assert paired_test(before, after) == 1.0
    noisy = [0.6, 0.4] * 14 + [0.6, 0.6]
    assert paired_test(before, noisy) > SIGNIFICANT


def test_a_small_mixed_case_matches_the_exact_two_sided_p() -> None:
    """Enumerating every sign of five differences gives the p that sampling approaches."""
    differences = [0.5, 0.25, -0.25, 0.5, 0.25]
    observed = abs(fmean(differences))
    flips = list(itertools.product((-1, 1), repeat=len(differences)))
    beyond = sum(
        abs(fmean(s * d for s, d in zip(signs, differences, strict=True))) >= observed - 1e-12
        for signs in flips
    )
    exact = beyond / len(flips)
    assert paired_test([0.0] * 5, differences) == pytest.approx(exact, abs=CLOSE)
