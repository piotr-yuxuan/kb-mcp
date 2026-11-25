"""Plan 022's bar: whether to rerank on the machine measured, and how deep, from an evaluation.

Fixed before any run. Its family is the depths of BAR_DEPTHS, whichever of them are run. A
depth qualifies when it beats the order not reranked on MRR@10, significantly once its
p-value is multiplied by the family's size; loses little on the questions that agents
send as names and keywords; and keeps a search within the user's bound.
"""

from __future__ import annotations

from collections.abc import Mapping
from statistics import fmean

from pydantic import Field

from kb_mcp.evaluation.domain.evaluation import ALPHA, paired_test
from kb_mcp.kernel.names import BAR_DEPTHS, BOUND_S
from kb_mcp.kernel.records import Record

# The arm not reranked, the control, as the verdict names it.
NONE = "none"
# The loss of MRR@10 that a group may show: with some 32 questions a group, the standard
# error of its mean difference is about 0.05, so that 0.02 would refuse a harmless
# reranker about one time in three.
GROUP_LOSS = 0.05
# The groups that may not lose: questions that agents send as names and as keywords.
GROUPS = ("identifier", "keyword")
# Within how much of the best MRR@10 a smaller depth is kept.
MARGIN = 0.01


class Depthed(Record):
    """What the bar reads of one arm: its MRR@10 per question, per group, and its time."""

    reciprocal: tuple[float, ...]  # each question's, in the questions' order
    groups: Mapping[str, float]  # each group's mean, of those that the golden file names
    tail_ms: int  # a search's 95th percentile, in whole milliseconds


class Decision(Record):
    """The bar's verdict on the arms run: the depth kept, or why there is none.

    Each arm is named by its depth, ``none`` the order not reranked. Each depth of the
    family run has its clauses: its gain, the groups' losses, its time; ``failed`` names
    those it fails, of ``gain``, ``guards`` and ``bound``.
    """

    rule: str
    fixed: Mapping[str, str]  # the settings that the arms share, none here
    control: str
    kept: str | None  # None: no verdict
    reason: str | None = None  # why there is no verdict
    untested: tuple[str, ...] = ()  # the family's depths not run, which cannot qualify
    means: Mapping[str, float] = Field(default_factory=dict)  # MRR@10, to three decimals
    adjusted: Mapping[str, float] = Field(default_factory=dict)  # times the family's size
    losses: Mapping[str, Mapping[str, float]] = Field(default_factory=dict)  # by group
    spent: Mapping[str, int] = Field(default_factory=dict)  # a search's 95th percentile, ms
    failed: Mapping[str, tuple[str, ...]] = Field(default_factory=dict)

    def lines(self) -> list[str]:
        """Say the verdict, then each depth's clauses, then the depths not run."""
        if self.kept is None:
            said = f"no verdict, since {self.reason}"
        elif self.kept == self.control:
            said = f"{self.kept} stays"
        else:
            said = f"{self.kept}, in place of {self.control}"
        lines = [f"Reranking depth, by the default rule: {said}."]
        for name, failed in self.failed.items():
            losses = ", ".join(
                f"{group} {self.losses[name][group]:.3f}"
                if group in self.losses[name]
                else f"{group} n/a"
                for group in GROUPS
            )
            gains, holds, within = (
                "no" if clause in failed else "yes" for clause in ("gain", "guards", "bound")
            )
            lines.append(
                f"  {name}: MRR@10 {self.means[name]:.3f} against {self.means[self.control]:.3f},"
                f" adjusted p = {self.adjusted[name]:.4f}, gains {gains};"
                f" MRR@10 lost: {losses}, holds {holds};"
                f" 95th percentile {self.spent[name]:,} ms, at most {BOUND_S * 1000:,.0f} ms,"
                f" within {within}"
            )
        if self.untested:
            lines.append(f"  {', '.join(self.untested)}: not run, so cannot qualify")
        return lines


def default_reranking(arms: Mapping[str, Depthed]) -> Decision:
    """Apply the bar to the arms run, each named by its depth, ``none`` the order not reranked.

    A depth of the family not run cannot qualify, and one outside it is left out. Without
    the arm not reranked, or a depth of the family, there is no verdict, and the reason
    says why. Among the depths qualifying, the smallest within MARGIN of the best MRR@10 is
    kept. Values compare as an evaluation reports them: means to three decimals, and a
    loss as their difference, p-values to four, times in whole milliseconds. A group that
    the golden file does not name has no loss, and holds.
    """
    family = [str(depth) for depth in BAR_DEPTHS]
    run = [depth for depth in family if depth in arms]
    untested = tuple(depth for depth in family if depth not in arms)
    if NONE not in arms:
        reason = f"its control, {NONE}, was not run"
    elif not run:
        reason = "no challenger of its family was run"
    else:
        reason = None
    if reason:
        return Decision(
            rule="reranking depth",
            fixed={},
            control=NONE,
            kept=None,
            reason=reason,
            untested=untested,
        )
    plain = arms[NONE]
    means = {name: round(fmean(arms[name].reciprocal), 3) for name in (NONE, *run)}
    adjusted = {
        name: min(1.0, len(family) * paired_test(plain.reciprocal, arms[name].reciprocal))
        for name in run
    }
    losses = {
        name: {
            group: round(round(plain.groups[group], 3) - round(arms[name].groups[group], 3), 3)
            for group in GROUPS
            if group in plain.groups
        }
        for name in run
    }
    spent = {name: arms[name].tail_ms for name in (NONE, *run)}
    failed = {
        name: tuple(
            clause
            for clause, holds in (
                ("gain", means[name] > means[NONE] and round(adjusted[name], 4) < ALPHA),
                ("guards", all(loss <= GROUP_LOSS for loss in losses[name].values())),
                ("bound", spent[name] <= BOUND_S * 1000),
            )
            if not holds
        )
        for name in run
    }
    qualified = [name for name in run if not failed[name]]
    best = max((means[name] for name in qualified), default=0.0)
    close = [name for name in qualified if round(best - means[name], 3) <= MARGIN]
    return Decision(
        rule="reranking depth",
        fixed={},
        control=NONE,
        kept=min(close, key=family.index, default=NONE),
        untested=untested,
        means=means,
        adjusted=adjusted,
        losses=losses,
        spent=spent,
        failed=failed,
    )
