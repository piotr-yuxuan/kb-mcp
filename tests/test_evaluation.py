"""The measures of a ranking and the paired test, against values worked out by hand."""

from __future__ import annotations

import math

import pytest

from atlassian_offline_mcp.domain.evaluation import (
    Measures,
    Question,
    averages,
    measure,
    paired_test,
)

QUESTION = Question("q1", "a question", expected=("a", "b"), partial=("c",), group="keyword")
SIGNIFICANT = 0.05
HALF = 0.5


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
    """Each group averages its own questions; None holds them all."""
    other = Question("q2", "another", expected=("z",), group="paraphrase")
    found = averages({"q1": ["a"], "q2": ["x"]}, [QUESTION, other])
    assert found["keyword"].success == 1.0
    assert found["paraphrase"].success == 0.0
    overall = found[None]
    assert overall == Measures(recall=0.25, reciprocal_rank=HALF, ndcg=overall.ndcg, success=HALF)


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
