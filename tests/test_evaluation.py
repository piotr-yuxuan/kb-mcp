"""The measures of a ranking and the paired test, against values worked out by hand."""

from __future__ import annotations

import itertools
import math
from statistics import fmean
from typing import TYPE_CHECKING

import pytest

from kb_mcp.evaluation.domain import evaluation as rules
from kb_mcp.evaluation.domain.evaluation import (
    RULES,
    Measures,
    Question,
    Quoted,
    Verdict,
    averages,
    holds,
    holm,
    measure,
    paired_test,
    percentile,
    quoting,
    verdict,
)
from kb_mcp.evaluation.domain.grading import AgentAnswer, Quote, grade

if TYPE_CHECKING:
    from collections.abc import Mapping

    from _pytest.monkeypatch import MonkeyPatch

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


def held_everywhere(text: str, phrase: str) -> list[bool]:
    """Say whether ``text`` holds ``phrase`` as each comparer of evidence finds it.

    Section@10, Evidence@ask, an agent's evidence quoted, and an agent's quote grounded,
    the text being the document's body and the phrase the quote.
    """
    question = Question(id="q", text="x", expected=("a",), evidence={"a": phrase})
    graded = grade(
        AgentAnswer(found=True, answer="x", quotes=(Quote(ref="a", text=text),)),
        question,
        str,
        lambda _: text,
    )
    quote = AgentAnswer(found=True, answer="x", quotes=(Quote(ref="a", text=phrase),))
    return [
        holds(text, phrase),
        measure(["a"], question, {"a": text}).section == 1.0,
        quoting([("a", text)], question).evidence == 1.0,
        graded.evidence,
        grade(quote, question, str, lambda _: text).grounded,
    ]


@pytest.mark.parametrize(
    ("text", "phrase"),
    [
        (r"The plan costs \$5 a month.", "costs $5 a month"),
        (r"1\. Install the agent", "1. install the agent"),
        (r"a \[draft\] page", "a [draft] page"),
        ("See ![the rollback diagram](rollback.png) below.", "see the rollback diagram below"),
        ("See [the runbook](../x.md), **then** wait.", "the runbook, then wait"),
    ],
)
def test_evidence_matches_through_escapes_and_images(text: str, phrase: str) -> None:
    """D8, E14: Markdown's backslash escapes undone, an image's mark and address dropped."""
    assert held_everywhere(text, phrase) == [True] * 5


@pytest.mark.parametrize(
    ("text", "phrase", "held"),
    [
        ("Restart the service.", "art", False),
        ("The art of it.", "art", True),
        ("It costs $50.", "$5", False),
        ("It costs $5.", "$5", True),
        ("Blending in.", "the end", False),
        ("At the end.", "the end", True),
        ("Ninety days, then", "ninety days", True),
    ],
)
def test_evidence_matches_whole_words_only(text: str, phrase: str, *, held: bool) -> None:
    """D8, E14: a phrase within a word is not held, one between words or signs is."""
    assert held_everywhere(text, phrase) == [held] * 5


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
# An arm as a default rule reads it: its deciding measure question by question, its MRR@10
# by group, and what it spends.
type Arm = tuple[tuple[float, ...], dict[str, float], int]


def chunked(
    evidence: float,
    mrr: float = 0.5,
    tokens: int = TOKENS,
    *,
    last: float | None = None,
    **groups: float,
) -> Arm:
    """Score a chunking on QUESTIONS questions, all alike unless ``last`` sets the last one.

    Its MRR@10 is ``mrr`` on all of them and in each group that D2 guards, but those given.
    """
    each = (evidence,) * (QUESTIONS - 1) + ((evidence if last is None else last),)
    guarded = dict.fromkeys(("all", "identifier", "keyword", "paraphrase"), mrr)
    return each, guarded | groups, tokens


# A chunking scored on golden questions none of which has evidence.
UNMEASURED: Arm = ((), {"all": 0.5}, TOKENS)


def depthed(score: float, tail_ms: int = 900) -> Arm:
    """Measure a depth whose every question scores ``score`` on MRR@10, ``none`` included."""
    return (score,) * QUESTIONS, {"all": score}, tail_ms


def decide(rule: str, control: str, arms: Mapping[str, Arm]) -> Verdict:
    """Apply the rule named, the chunking's or the reranking depth's, to the arms run."""
    return verdict(RULES[rule], control, arms, {})


def scripted(monkeypatch: MonkeyPatch, pvalue: float) -> None:
    """Have every paired test of the rules give ``pvalue``."""
    monkeypatch.setattr(rules, "paired_test", lambda *_: pvalue)


def test_a_challenger_better_on_evidence_and_no_worse_otherwise_is_kept() -> None:
    """Evidence@ask from 0 to 1 on every question: significant once multiplied by three."""
    found = decide("chunking", "windows", {"windows": chunked(0.0), "sections": chunked(1.0)})
    assert found.kept == "sections"
    assert found.adjusted["sections"] < ALPHA_LEVEL


@pytest.mark.parametrize(
    ("challenger", "kept"),
    [
        (chunked(1.0, 0.48), "sections"),
        (chunked(1.0, 0.479), "windows"),
        (chunked(1.0, paraphrase=0.45), "sections"),
        (chunked(1.0, paraphrase=0.449), "windows"),
        (chunked(1.0, identifier=0.449), "windows"),
        (chunked(1.0, keyword=0.449), "windows"),
    ],
)
def test_mrr_may_fall_0_02_overall_and_0_05_in_a_group(challenger: Arm, kept: str) -> None:
    """D2's guards against 0.500 everywhere: 0.02 overall, 0.05 in each group that it names.

    Losses of 0.020 and 0.050 hold; 0.021 and 0.051 do not.
    """
    found = decide("chunking", "windows", {"windows": chunked(0.0), "sections": challenger})
    assert found.kept == kept


@pytest.mark.parametrize(
    ("tokens", "kept"), [(3 * TOKENS, "sections"), (3 * TOKENS + 1, "windows")]
)
def test_a_challenger_may_embed_three_times_the_control_s_tokens(tokens: int, kept: str) -> None:
    """The bound is relative: three times the control's tokens, and no more."""
    arms = {"windows": chunked(0.0), "sections": chunked(1.0, tokens=tokens)}
    found = decide("chunking", "windows", arms)
    assert ("bound" in found.failed["sections"]) is (kept == "windows")
    assert found.kept == kept


def test_a_gain_on_one_question_alone_is_no_reason_to_change() -> None:
    """Higher on average, by one question of twenty: not significant once adjusted."""
    arms = {"windows": chunked(0.0), "sections": chunked(0.0, last=1.0)}
    found = decide("chunking", "windows", arms)
    assert found.kept == "windows"
    assert found.adjusted["sections"] >= ALPHA_LEVEL


def test_a_challenger_significantly_worse_on_evidence_never_qualifies() -> None:
    """Different on every question, the wrong way: the control stays."""
    found = decide("chunking", "windows", {"windows": chunked(1.0), "sections": chunked(0.0)})
    assert found.adjusted["sections"] < ALPHA_LEVEL
    assert found.kept == "windows"


EVERY_CHUNKING = {
    "windows": chunked(0.0),
    "sections": chunked(0.3),
    "section-paths": chunked(0.2),
    "small-to-big": chunked(0.1),
}
EVERY_DEPTH = {
    "none": depthed(0.0),
    "10": depthed(0.3),
    "20": depthed(0.2),
    "30": depthed(0.1),
    "50": depthed(0.1),
}


@pytest.mark.parametrize(
    ("rule", "control", "run", "adjusted"),
    [
        ("chunking", "windows", ("windows", "sections"), 0.06),
        ("chunking", "windows", tuple(EVERY_CHUNKING), 0.06),
        ("reranking depth", "none", ("none", "10"), 0.08),
        ("reranking depth", "none", tuple(EVERY_DEPTH), 0.08),
    ],
)
def test_the_family_is_fixed_whatever_the_arms_run(
    monkeypatch: MonkeyPatch, rule: str, control: str, run: tuple[str, ...], adjusted: float
) -> None:
    """E8: each p-value of 0.02 is multiplied by its family's size, 3 chunkings or 4 depths.

    Whichever others were run: 0.06 or 0.08, which no challenger passes; adjusting over the
    arms run alone would give 0.02 to a challenger run alone, which would pass.
    """
    scripted(monkeypatch, 0.02)
    every = EVERY_CHUNKING if rule == "chunking" else EVERY_DEPTH
    found = decide(rule, control, {name: every[name] for name in run})
    assert found.adjusted == pytest.approx(dict.fromkeys(run[1:], adjusted))
    assert found.kept == control


@pytest.mark.parametrize(
    ("rule", "control", "arms", "untested"),
    [
        (
            "chunking",
            "windows",
            {"windows": chunked(0.0), "small-to-big": chunked(0.0)},
            ("sections", "section-paths"),
        ),
        ("reranking depth", "none", {"none": depthed(0.0), "20": depthed(0.0)}, ("10", "30", "50")),
    ],
)
def test_an_untested_challenger_cannot_qualify_and_is_named(
    rule: str, control: str, arms: Mapping[str, Arm], untested: tuple[str, ...]
) -> None:
    """A challenger of the family not run is named, in the family's order, and never judged.

    The one run that does not qualify leaves the control in place.
    """
    found = decide(rule, control, arms)
    assert found.untested == untested
    assert set(found.failed) == set(arms) - {control}
    assert found.kept == control


@pytest.mark.parametrize(
    ("rule", "control", "arms", "reason"),
    [
        (
            "chunking",
            "windows",
            {"sections": chunked(1.0), "small-to-big": chunked(1.0)},
            "its control, windows, was not run",
        ),
        ("chunking", "windows", {"windows": chunked(1.0)}, "no challenger of its family was run"),
        (
            "chunking",
            "windows",
            {"windows": UNMEASURED, "sections": UNMEASURED},
            "no golden question has a measure of Evidence@ask",
        ),
        (
            "reranking depth",
            "none",
            {"none": depthed(0.0), "2": depthed(1.0), "3": depthed(1.0)},
            "no challenger of its family was run",
        ),
        ("reranking depth", "none", {"10": depthed(1.0)}, "its control, none, was not run"),
    ],
)
def test_no_control_no_challenger_or_no_measure_gives_no_verdict(
    rule: str, control: str, arms: Mapping[str, Arm], reason: str
) -> None:
    """No verdict, and why: the control not run, no challenger of the family, no measure."""
    found = decide(rule, control, arms)
    assert found.kept is None
    assert found.reason == reason


@pytest.mark.parametrize(
    ("rule", "control", "arms", "kept"),
    [
        (
            "reranking depth",
            "none",
            {"none": depthed(0.0), "10": depthed(0.592), "20": depthed(0.6)},
            "10",
        ),
        (
            "reranking depth",
            "none",
            {"none": depthed(0.0), "10": depthed(0.589), "20": depthed(0.6)},
            "20",
        ),
        (
            "reranking depth",
            "none",
            {"none": depthed(0.0), "10": depthed(0.59), "20": depthed(0.6)},
            "10",
        ),
        (
            "chunking",
            "windows",
            {
                "windows": chunked(0.0),
                "sections": chunked(1.0, tokens=2 * TOKENS),
                "section-paths": chunked(1.0, tokens=int(1.5 * TOKENS), last=0.9),
                "small-to-big": chunked(1.0, tokens=TOKENS, last=0.6),
            },
            "section-paths",
        ),
    ],
)
def test_within_the_margin_the_cheapest_qualifier_wins(
    rule: str, control: str, arms: Mapping[str, Arm], kept: str
) -> None:
    """D2: of the challengers qualifying, the cheapest within 0.01 of the best mean is kept.

    The smaller depth, or the chunking that embeds fewer tokens: 0.592 and 0.590 are within
    0.01 of 0.600, and 0.589 is not; 0.995 is within 0.01 of 1.000, and 0.980 is not.
    """
    assert decide(rule, control, arms).kept == kept
