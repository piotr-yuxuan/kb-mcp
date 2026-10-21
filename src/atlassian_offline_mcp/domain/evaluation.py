"""How well a ranking answers golden questions, and whether one ranking beats another.

Pure: rankings come in as lists of document paths, best first, and questions name the
paths that answer them. Nothing here runs a search.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from statistics import fmean
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

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


@dataclass(frozen=True)
class Question:
    """A golden question, with the documents that answer it and those that help."""

    id: str
    text: str
    expected: tuple[str, ...]  # paths, relevance 2
    partial: tuple[str, ...] = ()  # paths, relevance 1
    groups: tuple[str, ...] = ()  # such as the kind of wording, or the language
    evidence: Mapping[str, str] = field(default_factory=dict)  # a phrase of an expected path

    @property
    def paths(self) -> tuple[str, ...]:
        """Every document the question names, expected or partial."""
        return (*self.expected, *self.partial)


@dataclass(frozen=True)
class Measures:
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
            fmean(each.recall for each in many),
            fmean(each.reciprocal_rank for each in many),
            fmean(each.ndcg for each in many),
            fmean(each.success for each in many),
            fmean(sections) if sections else None,
        )


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


def paired_test(
    before: Sequence[float], after: Sequence[float], samples: int = SAMPLES, seed: int = SEED
) -> float:
    """Give the two-sided p-value that ``after`` differs from ``before``, question by question.

    A paired randomisation test: under the hypothesis of no difference, each question's
    difference is as likely to have either sign, so the observed mean difference is
    compared with the means of ``samples`` random sign flips. The same seed gives the
    same p-value; two equal runs give 1.
    """
    differences = [b - a for a, b in zip(before, after, strict=True)]
    observed = abs(fmean(differences)) if differences else 0.0
    if observed == 0.0:
        return 1.0
    signs = np.random.default_rng(seed).choice((-1.0, 1.0), size=(samples, len(differences)))
    flipped = np.abs((signs * np.array(differences)).mean(axis=1))
    beyond = int((flipped >= observed * (1 - 1e-12)).sum())
    return (beyond + 1) / (samples + 1)


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


def averages(per: Mapping[str, Measures], questions: Sequence[Question]) -> dict[str, Measures]:
    """Average each question's measures over all of them (under "all") and per group."""
    groups: dict[str, list[Measures]] = {"all": [per[question.id] for question in questions]}
    for question in questions:
        for group in question.groups:
            groups.setdefault(group, []).append(per[question.id])
    return {group: Measures.mean(each) for group, each in groups.items()}
