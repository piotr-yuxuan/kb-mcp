"""How well a ranking answers golden questions, and whether one ranking beats another.

Pure: rankings come in as lists of document paths, best first, and questions name the
paths that answer them; so do the passages that ask quotes, with their texts. Nothing
here runs a search. ``RULES`` holds the default rules as data, and ``verdict`` applies one.
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping
from statistics import fmean
from typing import TYPE_CHECKING, Literal, get_args

import numpy as np
from pydantic import Field

from kb_mcp.config.settings import SearchMode
from kb_mcp.kernel.names import BAR_DEPTHS, BOUND_S, CHUNKINGS
from kb_mcp.kernel.records import Record

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

# Measures look at the first CUTOFF documents of a ranking.
CUTOFF = 10
# Relevance of a document that answers a question, and of one that helps.
EXPECTED, PARTIAL = 2, 1
SAMPLES = 10_000
SEED = 11
# What evidence is compared without: Markdown's backslash escapes, a link's or an image's
# address and an image's mark, emphasis and code marks, and the pipes of a table's cells,
# which plain text renders as spaces.
ESCAPE = re.compile(r"\\([!-/:-@\[-`{-~])")
LINK = re.compile(r"!?\[([^\]]*)\]\([^)]*\)")
MARKS = re.compile(r"[*_`|]")
# The level of an adjusted p-value; within how much of the best mean a default rule keeps
# the cheapest challenger that qualifies.
ALPHA = 0.05
MARGIN = 0.01
# The arm not reranked, the control of the reranking depth, as a verdict names it.
NOT_RERANKED = "none"
# The search modes, the cheapest first.
MODES: tuple[SearchMode, ...] = get_args(SearchMode.__value__)


class Question(Record):
    """A golden question, with the documents that answer it and those that help."""

    id: str
    text: str
    expected: tuple[str, ...]  # paths, relevance 2
    partial: tuple[str, ...] = ()  # paths, relevance 1
    groups: tuple[str, ...] = ()  # such as the kind of wording, or the language
    evidence: Mapping[str, str] = Field(default_factory=dict)  # a phrase of an expected path

    def evidenced(self, path: str, text: str) -> bool:
        """Say whether a document's text holds its evidence; False for one without."""
        return path in self.evidence and holds(text, self.evidence[path])


class Measures(Record):
    """How one ranking answers one question, or many on average."""

    recall: float  # share of the expected documents in the first CUTOFF
    reciprocal_rank: float  # of the first expected document within CUTOFF, else 0
    ndcg: float  # expected and partial documents, by their relevance, within CUTOFF
    success: float  # 1 when the first document is expected
    # Of the expected documents with evidence found within CUTOFF, the share whose shown
    # section holds the evidence; None when there is none such.
    section: float | None = None
    tokens: float = 0  # of search's first answer, as served

    @classmethod
    def mean(cls, many: Sequence[Measures]) -> Measures:
        """Average measures over questions; Section@10 over those that have one."""
        sections = [each.section for each in many if each.section is not None]
        return cls(
            recall=fmean(each.recall for each in many),
            reciprocal_rank=fmean(each.reciprocal_rank for each in many),
            ndcg=fmean(each.ndcg for each in many),
            success=fmean(each.success for each in many),
            section=fmean(sections) if sections else None,
            tokens=fmean(each.tokens for each in many),
        )


class Quoted(Record):
    """How ask's first answer serves one question, or many on average."""

    found: float  # Found@ask: the share of the expected documents among its passages
    # Evidence@ask: of the expected documents with evidence, the share whose evidence
    # their passage holds; None when none has evidence.
    evidence: float | None
    tokens: float = 0  # of ask's first answer, as served
    per_kilotoken: float | None = None  # E/kT: evidence held per thousand tokens

    @classmethod
    def mean(cls, many: Sequence[Quoted]) -> Quoted:
        """Average over questions; Evidence@ask over those that have evidence.

        E/kT is a ratio of sums over the questions with evidence: the evidence held over
        the thousands of tokens that their answers cost.
        """
        held = [each for each in many if each.evidence is not None]
        spent = sum(each.tokens for each in held) / 1000
        return cls(
            found=fmean(each.found for each in many),
            evidence=fmean(each.evidence for each in held) if held else None,
            tokens=fmean(each.tokens for each in many),
            per_kilotoken=sum(each.evidence for each in held) / spent if spent else None,
        )


class DefaultRule(Record):
    """The rule that keeps a setting's value unless a challenger qualifies on the same questions.

    Of two kinds. With ``values``, its family is they but the control, and a challenger
    qualifies when its mean on ``decides`` is higher than the control's, with a p-value
    below ALPHA once multiplied by the family's size; when no group of ``guards`` loses more
    of MRR@10 than it allows; and when it spends at most ``bound``: tokens embedded, as a
    multiple of the control's, or a search's 95th percentile, in milliseconds. Without
    values, its family is the arms run but the control; it asks no gain, has no bound and
    spends ms: a challenger must search faster than the control. Of those qualifying, the
    cheapest within MARGIN of the best mean is kept: the fewest tokens, or the first of
    ``values``, or without values the least spent, then the higher mean, then the name.
    """

    name: str  # the decision, as a verdict says it
    values: tuple[str, ...]  # cheapest first, when what it spends is time
    decides: Literal["MRR@10", "Evidence@ask"]
    guards: Mapping[str, float]  # the most MRR@10 that each group may lose, "all" of them
    spends: Literal["tokens", "ms"]
    bound: float | None  # None exactly without values

    @property
    def gains(self) -> bool:
        """Whether a challenger must gain on ``decides``: exactly when the rule names values."""
        return bool(self.values)


class Verdict(Record):
    """What a default rule gave on the arms run: the value kept, or why there is none.

    Each arm is named by its value, or by its value and mode. Each challenger run has its
    clauses, its gain, the groups' losses and what it spends; ``failed`` names those that it
    fails, of ``gain``, ``guards`` and ``bound``.
    """

    rule: str  # its name
    fixed: Mapping[str, str]  # the settings that the arms share, such as the model
    control: str
    kept: str | None  # None: no verdict
    reason: str | None = None  # why there is no verdict
    untested: tuple[str, ...] = ()  # the family's values not run, which cannot qualify
    means: Mapping[str, float] = Field(default_factory=dict)  # on decides, to three decimals
    adjusted: Mapping[str, float] = Field(default_factory=dict)  # times the family's size
    losses: Mapping[str, Mapping[str, float]] = Field(default_factory=dict)  # by group
    spent: Mapping[str, int] = Field(default_factory=dict)  # as the bound reads it
    failed: Mapping[str, tuple[str, ...]] = Field(default_factory=dict)

    def lines(self) -> list[str]:
        """Say the verdict, then each challenger's clauses, then the values not run.

        No p-value for a rule that asks no gain; without a bound, each cost against the
        control's.
        """
        rule = RULES[self.rule]
        if self.kept is None:
            said = f"no verdict, since {self.reason}"
        elif self.kept == self.control:
            said = f"{self.kept} stays"
        else:
            said = f"{self.kept}, in place of {self.control}"
        held = f" for {', '.join(self.fixed.values())}" if self.fixed else ""
        lines = [f"{rule.name.capitalize()}{held}, by the default rule: {said}."]
        for name, failed in self.failed.items():
            losses = ", ".join(
                f"{group} {self.losses[name][group]:.3f}"
                if group in self.losses[name]
                else f"{group} n/a"
                for group in rule.guards
            )
            gains, holds, within = (
                "no" if clause in failed else "yes" for clause in ("gain", "guards", "bound")
            )
            tested = ""
            if rule.gains:
                tested = f", adjusted p = {self.adjusted[name]:.4f}, gains {gains}"
            if rule.bound is None:
                spent = (
                    f"95th percentile {self.spent[name]:,} ms against"
                    f" {self.spent[self.control]:,} ms, cheaper {within}"
                )
            elif rule.spends == "tokens":
                most = rule.bound * self.spent[self.control]
                spent = (
                    f"{self.spent[name]:,} tokens embedded, at most {most:,.0f}, within {within}"
                )
            else:
                spent = (
                    f"95th percentile {self.spent[name]:,} ms, at most {rule.bound:,.0f} ms,"
                    f" within {within}"
                )
            lines.append(
                f"  {name}: {rule.decides} {self.means[name]:.3f} against"
                f" {self.means[self.control]:.3f}{tested};"
                f" MRR@10 lost: {losses}, holds {holds}; {spent}"
            )
        if self.untested:
            lines.append(f"  {', '.join(self.untested)}: not run, so cannot qualify")
        return lines


# The default rules, by name. A guard of 0.05 is about one standard error of a group's
# mean difference at some 32 questions: one of 0.02 would refuse a harmless challenger
# about one time in three. The embedding model's asks no gain: a leaderboard chooses the
# candidates, and the golden questions check that one loses little and searches faster.
RULES = {
    rule.name: rule
    for rule in (
        DefaultRule(
            name="search mode",
            values=MODES,
            decides="MRR@10",
            guards={"identifier": 0.05, "keyword": 0.05},
            spends="ms",
            bound=500,
        ),
        DefaultRule(
            name="chunking",
            values=CHUNKINGS,
            decides="Evidence@ask",
            guards={"all": 0.02, "identifier": 0.05, "keyword": 0.05, "paraphrase": 0.05},
            spends="tokens",
            bound=3,
        ),
        DefaultRule(
            name="reranking depth",
            values=(NOT_RERANKED, *(str(depth) for depth in BAR_DEPTHS)),
            decides="MRR@10",
            guards={"identifier": 0.05, "keyword": 0.05},
            spends="ms",
            bound=BOUND_S * 1000,
        ),
        DefaultRule(
            name="embedding model",
            values=(),
            decides="MRR@10",
            guards={"all": 0.03, "identifier": 0.05, "keyword": 0.05, "paraphrase": 0.05},
            spends="ms",
            bound=None,
        ),
    )
}


def plain(text: str) -> str:
    """Write text as evidence is compared: unescaped, links as their words, no marks, one case."""
    return " ".join(MARKS.sub("", LINK.sub(r"\1", ESCAPE.sub(r"\1", text))).casefold().split())


def holds(text: str, phrase: str) -> bool:
    """Say whether a text holds a phrase: both ``plain``, the phrase as whole words."""
    return re.search(rf"(?<!\w){re.escape(plain(phrase))}(?!\w)", plain(text)) is not None


def measure(
    ranked: Sequence[str],
    question: Question,
    shown: Mapping[str, str] | None = None,
    tokens: int = 0,
) -> Measures:
    """Measure one ranking against the documents of one question.

    nDCG takes each document's relevance as its gain, discounted by the logarithm of
    its rank, over the best ordering of the question's documents. ``shown`` gives the
    text of the section shown for each ranked document, for Section@10; ``tokens``, those
    of search's answer.
    """
    top = list(ranked[:CUTOFF])
    expected = set(question.expected)
    gains = dict.fromkeys(question.partial, PARTIAL) | dict.fromkeys(expected, EXPECTED)
    first = next((rank for rank, path in enumerate(top, 1) if path in expected), None)
    found = sum(gains.get(path, 0) / math.log2(rank + 1) for rank, path in enumerate(top, 1))
    ideal = sorted(gains.values(), reverse=True)[:CUTOFF]
    best = sum(gain / math.log2(rank + 1) for rank, gain in enumerate(ideal, 1))
    texts = shown or {}
    held = [
        holds(texts.get(path, ""), question.evidence[path])
        for path in top
        if path in expected and path in question.evidence
    ]
    return Measures(
        recall=len(expected.intersection(top)) / len(expected),
        reciprocal_rank=0.0 if first is None else 1 / first,
        ndcg=found / best,
        success=1.0 if top[:1] and top[0] in expected else 0.0,
        section=fmean(held) if held else None,
        tokens=tokens,
    )


def quoting(passages: Sequence[tuple[str, str]], question: Question, tokens: int = 0) -> Quoted:
    """Measure the passages of ask's first answer, each a path and its text, for a question.

    ``tokens`` are the answer's; one question's E/kT is reckoned as a group's.
    """
    texts = dict(passages)
    held = [
        holds(texts.get(path, ""), phrase)
        for path, phrase in question.evidence.items()
        if path in question.expected
    ]
    found = sum(path in texts for path in question.expected) / len(question.expected)
    return Quoted.mean([Quoted(found=found, evidence=fmean(held) if held else None, tokens=tokens)])


def verdict(
    rule: DefaultRule,
    control: str,
    arms: Mapping[str, tuple[Sequence[float], Mapping[str, float], int]],
    fixed: Mapping[str, str],
) -> Verdict:
    """Apply a default rule to the arms run, each named by its value, against the control.

    Each arm gives the measure that the rule decides on, question by question, of the
    questions that it measures, in the same order for all; its MRR@10 by group, "all" the
    questions; and what it spends. An arm outside the rule's values, if it names any, is
    left out. Without the control, a challenger, or a question measured, there is no
    verdict, and the reason says why. Values compare as reported: means and losses to three
    decimals, p-values to four, times in whole milliseconds. A group that the golden file
    does not name has no loss, and holds.
    """
    family = [value for value in rule.values or arms if value != control]
    run = [value for value in family if value in arms]
    untested = tuple(value for value in family if value not in arms)
    if control not in arms:
        reason = f"its control, {control}, was not run"
    elif not run:
        reason = "no challenger of its family was run"
    elif not arms[control][0]:
        reason = f"no golden question has a measure of {rule.decides}"
    else:
        reason = None
    if reason:
        return Verdict(
            rule=rule.name,
            fixed=fixed,
            control=control,
            kept=None,
            reason=reason,
            untested=untested,
        )
    scores = {name: arms[name][0] for name in (control, *run)}
    groups = {name: arms[name][1] for name in (control, *run)}
    spent = {name: arms[name][2] for name in (control, *run)}
    means = {name: round(fmean(each), 3) for name, each in scores.items()}
    adjusted: dict[str, float] = {}
    if rule.gains:
        adjusted = {
            name: min(1.0, len(family) * paired_test(scores[control], scores[name])) for name in run
        }
    losses = {
        name: {
            group: round(round(groups[control][group], 3) - round(groups[name][group], 3), 3)
            for group in rule.guards
            if group in groups[control]
        }
        for name in run
    }
    most = spent[control] - 1  # without a bound: less than the control, in whole units
    if rule.bound is not None:
        most = rule.bound * (spent[control] if rule.spends == "tokens" else 1)
    failed = {
        name: tuple(
            clause
            for clause, holds in (
                (
                    "gain",
                    not rule.gains
                    or (means[name] > means[control] and round(adjusted[name], 4) < ALPHA),
                ),
                ("guards", all(loss <= rule.guards[group] for group, loss in losses[name].items())),
                ("bound", spent[name] <= most),
            )
            if not holds
        )
        for name in run
    }
    qualified = [name for name in run if not failed[name]]
    best = max((means[name] for name in qualified), default=0.0)
    close = [name for name in qualified if round(best - means[name], 3) <= MARGIN]
    if rule.values:  # the fewest tokens, or the first of the values
        cheaper = spent.__getitem__ if rule.spends == "tokens" else rule.values.index
        kept = min(close, key=cheaper, default=control)
    else:  # the least spent, of equal times the higher mean, then the name
        kept = min(close, key=lambda name: (spent[name], -means[name], name), default=control)
    return Verdict(
        rule=rule.name,
        fixed=fixed,
        control=control,
        kept=kept,
        untested=untested,
        means=means,
        adjusted=adjusted,
        losses=losses,
        spent=spent,
        failed=failed,
    )


def paired_test(before: Sequence[float], after: Sequence[float], seed: int = SEED) -> float:
    """Give the two-sided p-value that ``after`` differs from ``before``, question by question.

    A paired randomisation test: under the hypothesis of no difference, each question's
    difference is as likely to have either sign, so the observed mean difference is
    compared with the means of SAMPLES random sign flips. The same seed gives the
    same p-value; two equal runs give 1.
    """
    differences = [b - a for a, b in zip(before, after, strict=True)]
    observed = abs(fmean(differences)) if differences else 0.0
    if observed == 0.0:
        return 1.0
    signs = np.random.default_rng(seed).choice((-1.0, 1.0), size=(SAMPLES, len(differences)))
    flipped = np.abs((signs * np.array(differences)).mean(axis=1))
    beyond = int((flipped >= observed * (1 - 1e-12)).sum())
    return (beyond + 1) / (SAMPLES + 1)


def percentile(values: Sequence[float], share: float) -> float:
    """Give the nearest-rank percentile: the smallest value that ``share`` of them reach."""
    ordered = sorted(values)
    return ordered[max(0, math.ceil(share * len(ordered)) - 1)]


def holm(pvalues: Sequence[float]) -> list[float]:
    """Adjust p-values for testing several hypotheses at once, by Holm's step-down method.

    The i-th smallest of m is multiplied by m - i + 1, kept no smaller than the one
    before it, and capped at 1; the adjusted values come back in the given order.
    """
    order = sorted(range(len(pvalues)), key=lambda index: pvalues[index])
    adjusted = [0.0] * len(pvalues)
    floor = 0.0
    for step, index in enumerate(order):
        floor = max(floor, min(1.0, (len(pvalues) - step) * pvalues[index]))
        adjusted[index] = floor
    return adjusted


def averages[M](
    per: Mapping[str, M], questions: Sequence[Question], mean: Callable[[Sequence[M]], M]
) -> dict[str, M]:
    """Average each question's measures over all of them (under "all") and per group."""
    groups: dict[str, list[M]] = {"all": [per[question.id] for question in questions]}
    for question in questions:
        for group in question.groups:
            groups.setdefault(group, []).append(per[question.id])
    return {group: mean(each) for group, each in groups.items()}
