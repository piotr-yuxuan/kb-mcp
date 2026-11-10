"""How well a ranking answers golden questions, and whether one ranking beats another.

Pure: rankings come in as lists of document paths, best first, and questions name the
paths that answer them; so do the passages that ask quotes, with their texts. Nothing
here runs a search. ``default_chunking`` holds plan 019's rule for the default chunking.
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping
from statistics import fmean
from typing import TYPE_CHECKING

import numpy as np
from pydantic import Field

from kb_mcp.kernel.record import Record

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

# Measures look at the first CUTOFF documents of a ranking.
CUTOFF = 10
# Relevance of a document that answers a question, and of one that helps.
EXPECTED, PARTIAL = 2, 1
SAMPLES = 10_000
SEED = 11
# What evidence is compared without: a link's address, emphasis and code marks, and the
# pipes of a table's cells, which plain text renders as spaces.
LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")
MARKS = re.compile(r"[*_`|]")
# Plan 019's rule: the chunking that a challenger must beat; the level of its adjusted
# p-value on Evidence@ask; the MRR@10 it may lose; how many times the control's tokens
# it may cost; and within how much Evidence@ask two are taken as equal.
CONTROL = "sections"
ALPHA = 0.05
MRR_LOSS = 0.02
COST = 3
TIE = 0.01


class Question(Record):
    """A golden question, with the documents that answer it and those that help."""

    id: str
    text: str
    expected: tuple[str, ...]  # paths, relevance 2
    partial: tuple[str, ...] = ()  # paths, relevance 1
    groups: tuple[str, ...] = ()  # such as the kind of wording, or the language
    evidence: Mapping[str, str] = Field(default_factory=dict)  # a phrase of an expected path


class Measures(Record):
    """How one ranking answers one question, or many on average."""

    recall: float  # share of the expected documents in the first CUTOFF
    reciprocal_rank: float  # of the first expected document within CUTOFF, else 0
    ndcg: float  # expected and partial documents, by their relevance, within CUTOFF
    success: float  # 1 when the first document is expected
    # Of the expected documents with evidence found within CUTOFF, the share whose shown
    # section holds the evidence; None when there is none such.
    section: float | None = None

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
        )


class Quoted(Record):
    """How ask's first answer serves one question, or many on average."""

    found: float  # Found@ask: the share of the expected documents among its passages
    # Evidence@ask: of the expected documents with evidence, the share whose evidence
    # their passage holds; None when none has evidence.
    evidence: float | None

    @classmethod
    def mean(cls, many: Sequence[Quoted]) -> Quoted:
        """Average over questions; Evidence@ask over those that have evidence."""
        evidence = [each.evidence for each in many if each.evidence is not None]
        return cls(
            found=fmean(each.found for each in many), evidence=fmean(evidence) if evidence else None
        )


class Scored(Record):
    """What a chunking scored in hybrid mode, question by question, and what it costs."""

    reciprocal_ranks: tuple[float, ...]  # MRR@10 of each question
    evidence: tuple[float, ...]  # Evidence@ask of each question with evidence
    tokens: int  # of the texts that its index embeds, at the characters of a token


class Choice(Record):
    """The default chunking that the rule gives, and the tests that it read.

    Each test is a challenger's against the control, on ``mrr`` or ``evidence``.
    """

    chunking: str
    pvalues: dict[str, dict[str, float]]
    adjusted: dict[str, dict[str, float]]  # by Holm, over every test


def plain(text: str) -> str:
    """Write text as evidence is compared: links as their words, no marks, one case, spaced."""
    return " ".join(MARKS.sub("", LINK.sub(r"\1", text)).casefold().split())


def measure(
    ranked: Sequence[str], question: Question, shown: Mapping[str, str] | None = None
) -> Measures:
    """Measure one ranking against the documents of one question.

    nDCG takes each document's relevance as its gain, discounted by the logarithm of
    its rank, over the best ordering of the question's documents. ``shown`` gives the
    text of the section shown for each ranked document, for Section@10.
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
        plain(question.evidence[path]) in plain(texts.get(path, ""))
        for path in top
        if path in expected and path in question.evidence
    ]
    return Measures(
        recall=len(expected.intersection(top)) / len(expected),
        reciprocal_rank=0.0 if first is None else 1 / first,
        ndcg=found / best,
        success=1.0 if top[:1] and top[0] in expected else 0.0,
        section=fmean(held) if held else None,
    )


def quoting(passages: Sequence[tuple[str, str]], question: Question) -> Quoted:
    """Measure the passages of ask's first answer, each a path and its text, for a question."""
    texts = dict(passages)
    held = [
        plain(phrase) in plain(texts.get(path, ""))
        for path, phrase in question.evidence.items()
        if path in question.expected
    ]
    found = sum(path in texts for path in question.expected) / len(question.expected)
    return Quoted(found=found, evidence=fmean(held) if held else None)


def default_chunking(scored: Mapping[str, Scored]) -> Choice:
    """Choose the default chunking among those scored, the control among them, by the rule.

    A challenger qualifies when it beats the control on Evidence@ask, with a p-value
    below ALPHA once adjusted by Holm over every test of every challenger, on MRR@10
    and on Evidence@ask; loses at most MRR_LOSS of MRR@10; and costs at most COST times
    the control's tokens. The best Evidence@ask wins, and within TIE of it the cheapest;
    else the control stays.
    """
    control = scored[CONTROL]
    pvalues = {
        name: {
            "mrr": paired_test(control.reciprocal_ranks, each.reciprocal_ranks),
            "evidence": paired_test(control.evidence, each.evidence),
        }
        for name, each in scored.items()
        if name != CONTROL
    }
    tests = [(name, measure) for name, tested in pvalues.items() for measure in tested]
    adjusted: dict[str, dict[str, float]] = {name: {} for name in pvalues}
    for (name, measure), value in zip(
        tests, holm([pvalues[name][measure] for name, measure in tests]), strict=True
    ):
        adjusted[name][measure] = value
    evidence = {name: fmean(each.evidence or (0.0,)) for name, each in scored.items()}
    mrr = {name: fmean(each.reciprocal_ranks or (0.0,)) for name, each in scored.items()}
    qualified = [
        name
        for name in adjusted
        if evidence[name] > evidence[CONTROL]
        and adjusted[name]["evidence"] < ALPHA
        and mrr[CONTROL] - mrr[name] <= MRR_LOSS
        and scored[name].tokens <= COST * control.tokens
    ]
    best = max((evidence[name] for name in qualified), default=0.0)
    close = [name for name in qualified if best - evidence[name] <= TIE]
    chosen = min(close, key=lambda name: scored[name].tokens, default=CONTROL)
    return Choice(chunking=chosen, pvalues=pvalues, adjusted=adjusted)


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
