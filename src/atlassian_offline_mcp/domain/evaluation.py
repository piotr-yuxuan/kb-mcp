"""How well a ranking answers golden questions, and whether one ranking beats another.

Pure: rankings come in as lists of document paths, best first, and questions name the
paths that answer them. Nothing here runs a search.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
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


@dataclass(frozen=True)
class Question:
    """A golden question, with the documents that answer it and those that help."""

    id: str
    text: str
    expected: tuple[str, ...]  # paths, relevance 2
    partial: tuple[str, ...] = ()  # paths, relevance 1
    group: str | None = None  # such as the kind of wording: identifier, keyword, paraphrase


@dataclass(frozen=True)
class Measures:
    """How one ranking answers one question, or many on average."""

    recall: float  # share of the expected documents in the first CUTOFF
    reciprocal_rank: float  # of the first expected document within CUTOFF, else 0
    ndcg: float  # expected and partial documents, by their relevance, within CUTOFF
    success: float  # 1 when the first document is expected

    @classmethod
    def mean(cls, many: Sequence[Measures]) -> Measures:
        """Average measures over questions."""
        return cls(
            fmean(each.recall for each in many),
            fmean(each.reciprocal_rank for each in many),
            fmean(each.ndcg for each in many),
            fmean(each.success for each in many),
        )


def measure(ranked: Sequence[str], question: Question) -> Measures:
    """Measure one ranking against the documents of one question.

    nDCG takes each document's relevance as its gain, discounted by the logarithm of
    its rank, over the best ordering of the question's documents.
    """
    top = list(ranked[:CUTOFF])
    expected = set(question.expected)
    gains = dict.fromkeys(question.partial, PARTIAL) | dict.fromkeys(expected, EXPECTED)
    first = next((rank for rank, path in enumerate(top, 1) if path in expected), None)
    found = sum(gains.get(path, 0) / math.log2(rank + 1) for rank, path in enumerate(top, 1))
    ideal = sorted(gains.values(), reverse=True)[:CUTOFF]
    best = sum(gain / math.log2(rank + 1) for rank, gain in enumerate(ideal, 1))
    return Measures(
        recall=len(expected.intersection(top)) / len(expected),
        reciprocal_rank=0.0 if first is None else 1 / first,
        ndcg=found / best,
        success=1.0 if top[:1] and top[0] in expected else 0.0,
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


def averages(
    rankings: Mapping[str, Sequence[str]], questions: Sequence[Question]
) -> dict[str | None, Measures]:
    """Average the measures over every question (under None) and over each group."""
    per = {question.id: measure(rankings[question.id], question) for question in questions}
    groups: dict[str | None, list[Measures]] = {None: list(per.values())}
    for question in questions:
        if question.group is not None:
            groups.setdefault(question.group, []).append(per[question.id])
    return {group: Measures.mean(each) for group, each in groups.items()}
