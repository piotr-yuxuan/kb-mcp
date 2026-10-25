"""Plan 022's bar: whether search reranks by default, and how deep, from an evaluation.

Fixed before any run. A depth qualifies when it beats the order not reranked on MRR@10,
significantly once adjusted for testing four depths; loses little on the questions
that agents send as names and keywords; and keeps a search within the user's bound.
"""

from __future__ import annotations

from dataclasses import dataclass
from statistics import fmean
from typing import TYPE_CHECKING

from atlassian_offline_mcp.evaluation.domain.evaluation import ALPHA, holm, paired_test
from atlassian_offline_mcp.kernel.reranking import BAR_DEPTHS, BOUND_S

if TYPE_CHECKING:
    from collections.abc import Mapping

# The loss of MRR@10 that a group may show: with some 32 questions a group, the standard
# error of its mean difference is about 0.05, so that 0.02 would refuse a harmless
# reranker about one time in three.
GROUP_LOSS = 0.05
# The groups that may not lose: questions that agents send as names and as keywords.
GROUPS = ("identifier", "keyword")


@dataclass(frozen=True)
class Depthed:
    """What the bar reads of one arm: its MRR@10 per question, per group, and its time."""

    reciprocal: tuple[float, ...]  # each question's, in the questions' order
    groups: Mapping[str, float]  # each group's mean, of those that the golden file names
    tail_ms: int  # a search's 95th percentile, in whole milliseconds


@dataclass(frozen=True)
class Verdict:
    """The bar's clauses at one depth, and the adjusted p-value of its gain."""

    depth: int
    adjusted: float
    beats: bool  # a gain on MRR@10, its adjusted p below ALPHA
    holds: bool  # no group of GROUPS losing more than GROUP_LOSS
    fast: bool  # a search's 95th percentile within BOUND_S

    @property
    def qualifies(self) -> bool:
        """Say whether the depth passes every clause."""
        return self.beats and self.holds and self.fast


@dataclass(frozen=True)
class Decision:
    """The bar's verdicts, depth by depth, and the default depth; None: reranking off."""

    verdicts: tuple[Verdict, ...]
    depth: int | None


def default_reranking(plain: Depthed, arms: Mapping[int, Depthed]) -> Decision | None:
    """Apply the bar to arms at BAR_DEPTHS exactly, against the arm not reranked.

    Another set of depths gets no verdict. Among the depths qualifying, the smallest
    whose MRR@10 is not shown lower than the best's, by the paired test, p of ALPHA or
    more. Values compare as an evaluation reports them: means to three decimals,
    p-values to four, times in whole milliseconds.
    """
    if tuple(sorted(arms)) != BAR_DEPTHS:
        return None
    pvalues = [paired_test(plain.reciprocal, arms[depth].reciprocal) for depth in BAR_DEPTHS]
    before = round(fmean(plain.reciprocal), 3)
    verdicts = tuple(
        Verdict(
            depth,
            adjusted,
            beats=round(fmean(arms[depth].reciprocal), 3) > before and round(adjusted, 4) < ALPHA,
            holds=all(
                round(plain.groups[group] - arms[depth].groups[group], 3) <= GROUP_LOSS
                for group in GROUPS
                if group in plain.groups
            ),
            fast=arms[depth].tail_ms <= BOUND_S * 1000,
        )
        for depth, adjusted in zip(BAR_DEPTHS, holm(pvalues), strict=True)
    )
    qualifying = [verdict.depth for verdict in verdicts if verdict.qualifies]
    if not qualifying:
        return Decision(verdicts, None)
    best = max(qualifying, key=lambda depth: fmean(arms[depth].reciprocal))
    shown = arms[best].reciprocal
    kept = (depth for depth in qualifying if paired_test(shown, arms[depth].reciprocal) >= ALPHA)
    return Decision(verdicts, min(kept))
