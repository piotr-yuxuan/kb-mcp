"""The default rules as data: the search mode's, clause by clause, on hand-built arms (D2)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from kb_mcp.evaluation.domain import evaluation as rules
from kb_mcp.evaluation.domain.evaluation import RULES, verdict

if TYPE_CHECKING:
    from collections.abc import Mapping

    from _pytest.monkeypatch import MonkeyPatch

QUESTIONS = 30
# The p-value that each paired test gives, but where a row sets another: significant once
# multiplied by the family's size, two modes.
SIGNIFICANT = 0.001
# An arm as the default rule reads it: MRR@10 question by question, by group, and its time.
type Arm = tuple[tuple[float, ...], dict[str, float], int]


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
