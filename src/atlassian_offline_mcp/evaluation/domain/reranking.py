"""Plan 022's bar: whether to rerank on the machine measured, and how deep, from an evaluation.

Fixed before any run. A depth qualifies when it beats the order not reranked on MRR@10,
significantly once adjusted for testing four depths; loses little on the questions
that agents send as names and keywords; and keeps a search within the user's bound.
"""

from __future__ import annotations

from dataclasses import dataclass, field
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
    losses: Mapping[str, float]  # each group of GROUPS that the golden file names: its loss
    fast: bool  # a search's 95th percentile within BOUND_S

    @property
    def holds(self) -> bool:
        """Say whether no group of GROUPS loses more than GROUP_LOSS of MRR@10."""
        return all(loss <= GROUP_LOSS for loss in self.losses.values())

    @property
    def qualifies(self) -> bool:
        """Say whether the depth passes every clause."""
        return self.beats and self.holds and self.fast


@dataclass(frozen=True)
class Decision:
    """The bar's verdicts, depth by depth, and the default depth; None: reranking off."""

    verdicts: tuple[Verdict, ...]
    depth: int | None
    # Each qualifying depth's p-value against the best of them, on MRR@10.
    against_best: Mapping[int, float] = field(default_factory=dict)


def default_reranking(plain: Depthed, arms: Mapping[int, Depthed]) -> Decision | None:
    """Apply the bar to arms at BAR_DEPTHS exactly, against the arm not reranked.

    Another set of depths gets no verdict. Among the depths qualifying, the smallest
    whose MRR@10 is not shown lower than the best's, by the paired test, p of ALPHA or
    more. Values compare as an evaluation reports them: means to three decimals, and a
    loss as their difference, p-values to four, times in whole milliseconds. A group
    that the golden file does not name has no loss, and holds.
    """
    if tuple(sorted(arms)) != BAR_DEPTHS:
        return None
    pvalues = [paired_test(plain.reciprocal, arms[depth].reciprocal) for depth in BAR_DEPTHS]
    mean = {depth: round(fmean(arm.reciprocal), 3) for depth, arm in {0: plain, **arms}.items()}
    verdicts = tuple(
        Verdict(
            depth,
            adjusted,
            beats=mean[depth] > mean[0] and round(adjusted, 4) < ALPHA,
            losses={
                group: round(round(plain.groups[group], 3) - round(arms[depth].groups[group], 3), 3)
                for group in GROUPS
                if group in plain.groups
            },
            fast=arms[depth].tail_ms <= BOUND_S * 1000,
        )
        for depth, adjusted in zip(BAR_DEPTHS, holm(pvalues), strict=True)
    )
    qualifying = [verdict.depth for verdict in verdicts if verdict.qualifies]
    if not qualifying:
        return Decision(verdicts, None)
    shown = arms[max(qualifying, key=mean.__getitem__)].reciprocal
    against = {depth: paired_test(shown, arms[depth].reciprocal) for depth in qualifying}
    kept = (depth for depth, pvalue in against.items() if round(pvalue, 4) >= ALPHA)
    return Decision(verdicts, min(kept), against)
