"""The default rules as data, clause by clause, on hand-built arms (085's D2, 093's D2).

The search mode's; then the two kinds of rule, on rules built for the test.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from kb_mcp.evaluation.domain import evaluation as rules
from kb_mcp.evaluation.domain.evaluation import RULES, DefaultRule, verdict

if TYPE_CHECKING:
    from collections.abc import Mapping

    from _pytest.monkeypatch import MonkeyPatch

QUESTIONS = 30
# The p-value that each paired test gives, but where a row sets another: significant once
# multiplied by the family's size, two modes.
SIGNIFICANT = 0.001
# An arm as the default rule reads it: MRR@10 question by question, by group, and its time.
type Arm = tuple[tuple[float, ...], dict[str, float], int]
# The groups that the embedding model's rule guards, beside all the questions.
GUARDED = ("identifier", "keyword", "paraphrase")


def mode(score: float, tail_ms: int = 100, **groups: float) -> Arm:
    """Measure a mode whose every question scores ``score``; its guarded groups, 0.6 or as given."""
    return (score,) * QUESTIONS, {"identifier": 0.6, "keyword": 0.6} | groups, tail_ms


@pytest.mark.parametrize(
    ("control", "arms", "pvalue", "kept"),
    [
        # A challenger higher, significantly: it replaces the setting's mode.
        ("hybrid", {"hybrid": mode(0.5), "semantic": mode(0.6)}, SIGNIFICANT, "semantic"),
        # Its p-value times two, the family's size: 0.0500 is no gain, 0.0498 is one.
        ("hybrid", {"hybrid": mode(0.5), "semantic": mode(0.6)}, 0.025, "hybrid"),
        ("hybrid", {"hybrid": mode(0.5), "semantic": mode(0.6)}, 0.0249, "semantic"),
        # Lower, however significant: no gain.
        ("hybrid", {"hybrid": mode(0.5), "lexical": mode(0.4)}, SIGNIFICANT, "hybrid"),
        # Identifier and keyword may lose 0.05 of MRR@10, and no more.
        (
            "hybrid",
            {"hybrid": mode(0.5), "semantic": mode(0.6, identifier=0.55)},
            SIGNIFICANT,
            "semantic",
        ),
        (
            "hybrid",
            {"hybrid": mode(0.5), "semantic": mode(0.6, keyword=0.549)},
            SIGNIFICANT,
            "hybrid",
        ),
        # A search's 95th percentile within 500 ms, and no more.
        ("hybrid", {"hybrid": mode(0.5), "semantic": mode(0.6, 500)}, SIGNIFICANT, "semantic"),
        ("hybrid", {"hybrid": mode(0.5), "semantic": mode(0.6, 501)}, SIGNIFICANT, "hybrid"),
        # Within 0.01 of the best, the cheaper: lexical, then semantic, then hybrid.
        (
            "hybrid",
            {"hybrid": mode(0.5), "semantic": mode(0.6), "lexical": mode(0.59)},
            SIGNIFICANT,
            "lexical",
        ),
        (
            "hybrid",
            {"hybrid": mode(0.5), "semantic": mode(0.6), "lexical": mode(0.589)},
            SIGNIFICANT,
            "semantic",
        ),
        (
            "lexical",
            {"lexical": mode(0.5), "semantic": mode(0.595), "hybrid": mode(0.6)},
            SIGNIFICANT,
            "semantic",
        ),
    ],
)
def test_the_search_mode_rule_holds_its_clauses(
    monkeypatch: MonkeyPatch, control: str, arms: Mapping[str, Arm], pvalue: float, kept: str
) -> None:
    """The control is ``search_mode``'s value; the family, the two other modes.

    A mode qualifies when its MRR@10 is higher, with a p-value below 0.05 once multiplied
    by two; when identifier and keyword lose at most 0.05; and when a search's 95th
    percentile is within 500 ms. Of those qualifying, the cheapest within 0.01 of the best.
    """
    monkeypatch.setattr(rules, "paired_test", lambda *_: pvalue)
    found = verdict(RULES["search mode"], control, arms, {})
    assert found.control == control
    assert found.adjusted == pytest.approx(dict.fromkeys(set(arms) - {control}, 2 * pvalue))
    assert found.kept == kept


def ruled(monkeypatch: MonkeyPatch, **changed: object) -> DefaultRule:
    """Put in RULES, where a verdict's lines read it, a rule on MRR@10 as given, else as below.

    Two values, the control first, a guard of 0.05 on identifier, a search's 95th
    percentile within 500 ms, a gain asked.
    """
    fields = {"name": "test", "values": ("control", "b"), "decides": "MRR@10"}
    fields |= {"guards": {"identifier": 0.05}, "spends": "ms", "bound": 500}
    rule = DefaultRule(**fields | changed)
    monkeypatch.setitem(RULES, rule.name, rule)
    return rule


@pytest.mark.parametrize(("gains", "kept"), [(True, "control"), (False, "b")])
def test_a_rule_without_gain_needs_none(
    monkeypatch: MonkeyPatch, *, gains: bool, kept: str
) -> None:
    """D2: a challenger lower on MRR@10, within the guards and the bound, qualifies only then.

    No p-value is adjusted, and its line gives none, nor ``gains``.
    """
    monkeypatch.setattr(rules, "paired_test", lambda *_: SIGNIFICANT)
    rule = ruled(monkeypatch, gains=gains)
    found = verdict(rule, "control", {"control": mode(0.6), "b": mode(0.58)}, {})
    assert found.kept == kept
    assert found.adjusted == ({"b": SIGNIFICANT} if gains else {})
    tested = ", adjusted p = 0.0010, gains no" if gains else ""
    assert found.lines()[1] == (
        f"  b: MRR@10 0.580 against 0.600{tested}; MRR@10 lost: identifier 0.000, holds yes;"
        " 95th percentile 100 ms, at most 500 ms, within yes"
    )


@pytest.mark.parametrize(
    ("tail_ms", "kept", "cheaper"),
    [(187, "b", "yes"), (188, "control", "no"), (189, "control", "no")],
)
def test_a_bound_of_none_asks_strictly_less(
    monkeypatch: MonkeyPatch, tail_ms: int, kept: str, cheaper: str
) -> None:
    """D2: without a bound, a challenger must spend less than the control, 188 ms here.

    Its line gives each 95th percentile, and whether it is cheaper.
    """
    monkeypatch.setattr(rules, "paired_test", lambda *_: SIGNIFICANT)
    rule = ruled(monkeypatch, bound=None)
    found = verdict(rule, "control", {"control": mode(0.6, 188), "b": mode(0.7, tail_ms)}, {})
    assert found.kept == kept
    assert found.lines()[1] == (
        "  b: MRR@10 0.700 against 0.600, adjusted p = 0.0010, gains yes; MRR@10 lost:"
        f" identifier 0.000, holds yes; 95th percentile {tail_ms} ms against 188 ms,"
        f" cheaper {cheaper}"
    )


def test_a_family_of_the_values_run(monkeypatch: MonkeyPatch) -> None:
    """D2: a rule without values weighs every arm run but the control, and names none untested.

    Of those that qualify within the margin, the one that spends the least is kept.
    """
    rule = ruled(monkeypatch, values=(), gains=False, bound=None)
    arms = {"current": mode(0.6, 188), "x": mode(0.6, 150), "y": mode(0.595, 120)}
    found = verdict(rule, "current", arms | {"z": mode(0.7, 200)}, {})
    assert found.untested == ()
    assert set(found.failed) == {"x", "y", "z"}
    assert found.failed["z"] == ("bound",)
    assert found.kept == "y"


def test_a_rule_without_values_asks_no_gain() -> None:
    """D2: no Bonferroni correction runs over a family that the run sets."""
    assert [name for name, rule in RULES.items() if not rule.values and rule.gains] == []


def test_a_verdict_with_modes_names_each_value_s_mode(monkeypatch: MonkeyPatch) -> None:
    """D2, D4: ``verdict`` gives no modes; once set, a challenger's line names each value's."""
    rule = ruled(monkeypatch, values=(), gains=False, bound=None)
    found = verdict(rule, "current", {"current": mode(0.6, 188), "x": mode(0.6, 150)}, {})
    assert found.modes == {}
    moded = found.model_copy(update={"modes": {"current": "semantic", "x": "hybrid"}})
    assert moded.lines()[1] == (
        "  x, in hybrid: MRR@10 0.600 against 0.600 in semantic; MRR@10 lost: identifier"
        " 0.000, holds yes; 95th percentile 150 ms against 188 ms, cheaper yes"
    )


def model(score: float, tail_ms: int, **groups: float) -> Arm:
    """Measure a model in its mode: every question at ``score``, as is all; its groups 0.6."""
    guarded = {"all": score} | dict.fromkeys(GUARDED, 0.6)
    return (score,) * QUESTIONS, guarded | groups, tail_ms


@pytest.mark.parametrize(
    ("candidates", "kept"),
    [
        # It may lose 0.03 of MRR@10 over all the questions, and no more.
        ({"candidate": model(0.57, 187)}, "candidate"),
        ({"candidate": model(0.569, 187)}, "current"),
        # It may lose 0.05 on each of identifier, keyword and paraphrase, and no more.
        *(({"candidate": model(0.6, 187, **{group: 0.55})}, "candidate") for group in GUARDED),
        *(({"candidate": model(0.6, 187, **{group: 0.549})}, "current") for group in GUARDED),
        # Better on MRR@10, but its search as slow as the control's, or slower: no change.
        ({"candidate": model(0.7, 188)}, "current"),
        ({"candidate": model(0.7, 189)}, "current"),
        # Worse, within the guards, and 1 ms faster: it replaces the current model.
        ({"candidate": model(0.59, 187)}, "candidate"),
        # Of two that pass, the faster within 0.01 of the better mean; else the better.
        ({"slower": model(0.605, 170), "faster": model(0.6, 150)}, "faster"),
        ({"slower": model(0.62, 170), "faster": model(0.6, 150)}, "slower"),
    ],
)
def test_the_embedding_model_rule_holds_its_clauses(
    candidates: Mapping[str, Arm], kept: str
) -> None:
    """D1, the owner's bar: no gain asked, a little lost, and a faster search.

    A candidate may lose 0.03 of MRR@10 over all the questions and 0.05 on each of
    identifier, keyword and paraphrase; its search's 95th percentile must be less than the
    current model's, 188 ms.
    """
    arms = {"current": model(0.6, 188), **candidates}
    found = verdict(RULES["embedding model"], "current", arms, {"chunking": "windows"})
    assert found.adjusted == {}
    assert found.untested == ()
    assert found.kept == kept


def test_the_embedding_model_verdict_names_each_mode_and_cost() -> None:
    """D4's example: each model in its mode, its losses, its search time against the control's."""
    current = model(0.608, 188, identifier=0.7, keyword=0.5)
    candidate = model(0.633, 156, identifier=0.69, keyword=0.58, paraphrase=0.592)
    arms = {"qwen3-embedding:0.6b": current, "embeddinggemma:300m": candidate}
    found = verdict(RULES["embedding model"], "qwen3-embedding:0.6b", arms, {"chunking": "windows"})
    moded = found.model_copy(update={"modes": dict.fromkeys(arms, "hybrid")})
    assert moded.lines() == [
        (
            "Embedding model for windows, by the default rule: embeddinggemma:300m, in place"
            " of qwen3-embedding:0.6b."
        ),
        (
            "  embeddinggemma:300m, in hybrid: MRR@10 0.633 against 0.608 in hybrid; MRR@10"
            " lost: all -0.025, identifier 0.010, keyword -0.080, paraphrase 0.008, holds yes;"
            " 95th percentile 156 ms against 188 ms, cheaper yes"
        ),
    ]
