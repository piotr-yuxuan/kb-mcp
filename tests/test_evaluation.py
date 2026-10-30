"""The measures of a ranking and the paired test, against values worked out by hand."""

from __future__ import annotations

import itertools
import math
from statistics import fmean

import pytest

from kb_mcp.evaluation.domain.evaluation import (
    Measures,
    Question,
    Quoted,
    Scored,
    averages,
    default_chunking,
    holm,
    measure,
    paired_test,
    percentile,
    quoting,
)

QUESTION = Question(
    id="q1",
    text="a question",
    expected=("a", "b"),
    partial=("c",),
    groups=("keyword", "en"),
    evidence={"a": "Pause, drain, then roll back.", "b": "ninety days"},
)
CLOSE = 0.02
SIGNIFICANT = 0.05
HALF = 0.5
NINETEEN = 19
TWENTY_NINE = 29
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
    other = Question(id="q2", text="another", expected=("z",), groups=("paraphrase", "en"))
    per = {"q1": measure(["a"], QUESTION), "q2": measure(["x"], other)}
    found = averages(per, [QUESTION, other], Measures.mean)
    assert found["keyword"].success == 1.0
    assert found["paraphrase"].success == 0.0
    assert found["en"] == found["all"]
    overall = found["all"]
    expected = Measures(
        recall=0.25, reciprocal_rank=HALF, ndcg=overall.ndcg, success=HALF, section=0.0
    )
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
    question = Question(id="q", text="x", expected=("a",), evidence={"a": "SEV1 15 minutes"})
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


def test_a_consistent_loss_is_significant_too() -> None:
    """Two-sided: thirty questions each a little worse are as telling as better."""
    assert paired_test([0.3] * 30, [0.2] * 30) < SIGNIFICANT


def test_the_seed_makes_the_p_value_reproducible() -> None:
    """Where sampling matters, the same seed gives the same p, another seed another."""
    differences = [0.5, 0.25, -0.25, 0.5, 0.25]
    p = paired_test([0.0] * 5, differences, seed=11)
    assert paired_test([0.0] * 5, differences, seed=11) == p
    assert paired_test([0.0] * 5, differences, seed=12) != p


def test_ndcg_reaches_one_with_more_relevant_documents_than_ten() -> None:
    """The ideal ranking is cut at ten too: a perfect top ten is perfect."""
    many = Question(id="q", text="x", expected=tuple(f"d{n}" for n in range(11)))
    assert measure([f"d{n}" for n in range(10)], many).ndcg == pytest.approx(1.0)


def test_the_percentile_of_thirty_is_the_twenty_ninth() -> None:
    """0.95 x 30 = 28.5, so the nearest rank is the 29th, not the 28th."""
    assert percentile(list(range(1, 31)), 0.95) == TWENTY_NINE


def test_found_and_evidence_at_ask_are_shares_of_the_expected_documents() -> None:
    """Worked by hand: half found, evidence held; all found, none held; none, no evidence."""
    first = Question(id="q1", text="x", expected=("a", "b"), evidence={"a": "Rollback pause"})
    second = Question(id="q2", text="y", expected=("a",), evidence={"a": "drain"})
    third = Question(id="q3", text="z", expected=("z",))
    shown = [("a", "## Rollback\n\n**Rollback** pause, then go on."), ("c", "drain")]
    measured = [
        quoting(shown, first),
        quoting([("a", "nothing to see")], second),
        quoting([], third),
    ]
    assert measured == [
        Quoted(found=0.5, evidence=1.0),
        Quoted(found=1.0, evidence=0.0),
        Quoted(found=0.0, evidence=None),
    ]
    assert Quoted.mean(measured) == Quoted(found=0.5, evidence=0.5)


QUESTIONS = 20
TOKENS = 1000
ALPHA_LEVEL = 0.05  # the plan's level for an adjusted p-value


def scored(
    evidence: float, mrr: float, tokens: int = TOKENS, *, last: float | None = None
) -> Scored:
    """Score a chunking on QUESTIONS questions, all alike unless ``last`` sets the last one."""
    each = (evidence,) * (QUESTIONS - 1) + ((evidence if last is None else last),)
    return Scored(reciprocal_ranks=(mrr,) * QUESTIONS, evidence=each, tokens=tokens)


def test_a_challenger_better_on_evidence_and_no_worse_otherwise_becomes_the_default() -> None:
    """Evidence@ask from 0 to 1 on every question: significant once adjusted over its two."""
    choice = default_chunking({"sections": scored(0.0, 0.5), "windows": scored(1.0, 0.5)})
    assert choice.chunking == "windows"
    assert choice.adjusted["windows"]["evidence"] < ALPHA_LEVEL
    assert set(choice.pvalues["windows"]) == {"mrr", "evidence"}


def test_the_control_stays_against_a_challenger_that_loses_0_03_of_mrr() -> None:
    """It wins Evidence@ask, but MRR@10 may fall by 0.02 at most."""
    choice = default_chunking({"sections": scored(0.0, 0.5), "windows": scored(1.0, 0.47)})
    assert choice.chunking == "sections"


def test_a_challenger_at_3_1_times_the_tokens_is_left_out() -> None:
    """Three times the control's tokens at most: the costlier one is out, the other chosen."""
    choice = default_chunking(
        {
            "sections": scored(0.0, 0.5),
            "small-to-big": scored(1.0, 0.5, int(3.1 * TOKENS)),
            "windows": scored(0.9, 0.5, 3 * TOKENS),
        }
    )
    assert choice.chunking == "windows"


def test_of_two_within_0_01_of_evidence_the_cheaper_wins() -> None:
    """1.0 against 0.995: as good, so the one that embeds less is chosen."""
    choice = default_chunking(
        {
            "sections": scored(0.0, 0.5),
            "section-paths": scored(1.0, 0.5, 2 * TOKENS),
            "windows": scored(1.0, 0.5, int(1.5 * TOKENS), last=0.9),
        }
    )
    assert choice.chunking == "windows"
    tested = {"mrr", "evidence"}
    assert {name: set(each) for name, each in choice.adjusted.items()} == {
        "section-paths": tested,
        "windows": tested,
    }


def test_a_gain_on_one_question_alone_is_no_reason_to_change() -> None:
    """Higher on average, by one question of twenty: not significant once adjusted."""
    choice = default_chunking({"sections": scored(0.0, 0.5), "windows": scored(0.0, 0.5, last=1.0)})
    assert choice.chunking == "sections"
    assert choice.adjusted["windows"]["evidence"] >= ALPHA_LEVEL


def test_a_challenger_significantly_worse_on_evidence_never_qualifies() -> None:
    """Different on every question, the wrong way: the control stays."""
    choice = default_chunking({"sections": scored(1.0, 0.5), "windows": scored(0.0, 0.5)})
    assert choice.adjusted["windows"]["evidence"] < ALPHA_LEVEL
    assert choice.chunking == "sections"
