"""What an agent answered, read strictly, and how it is graded against a golden question.

Pure: the answer comes in as JSON from the agent, untrusted, and the documents as the
mirror holds them; refs are resolved by a function given, as ``read`` resolves them.
``ask_verdict`` holds plan 019's rule on whether ``ask`` stays among the default tools.
A refusal names the field at fault, never what was found there.
"""

from __future__ import annotations

from dataclasses import dataclass
from statistics import fmean
from typing import TYPE_CHECKING, Literal

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from kb_mcp.evaluation.domain.evaluation import (
    ALPHA,
    SEED,
    holm,
    paired_test,
    plain,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence

    from kb_mcp.evaluation.domain.evaluation import Question

LONGEST_ANSWER = 4_000
LONGEST_REF = 300
MOST = 10  # sources, and quotes, in one answer
# Resamples of the bootstrap interval of a difference, and its coverage.
RESAMPLES = 10_000
COVERAGE = 0.95
STRICT = ConfigDict(strict=True, extra="forbid", frozen=True, hide_input_in_errors=True)


class Quote(BaseModel):
    """A passage that the agent quotes, with the ref of the document it quotes."""

    model_config = STRICT

    ref: str = Field(min_length=1, max_length=LONGEST_REF)
    text: str = Field(min_length=1, max_length=LONGEST_ANSWER)


class Answer(BaseModel):
    """An agent's answer: whether the base holds it, the answer, its sources and quotes."""

    model_config = STRICT

    found: bool
    answer: str = Field(max_length=LONGEST_ANSWER)
    sources: tuple[str, ...] = Field(default=(), max_length=MOST)
    quotes: tuple[Quote, ...] = Field(default=(), max_length=MOST)


class Harness(BaseModel):
    """What the orchestrator says of a run: returned, failed or invalid; model and tokens.

    ``invalid`` is a run whose agent did more than read its prompt and run the bridge;
    the model and the tokens are the harness's, when it reports them.
    """

    model_config = STRICT

    status: Literal["returned", "failed", "invalid"]
    model: str | None = Field(default=None, max_length=LONGEST_REF)
    tokens: int | None = Field(default=None, ge=0)


def refusal(error: ValidationError) -> str:
    """Say what a strict reading refused: each field at fault, never its value."""
    return "; ".join(
        f"{'.'.join(str(part) for part in each['loc']) or 'the whole'}: {each['msg']}"
        for each in error.errors(include_input=False, include_url=False)
    )


@dataclass(frozen=True)
class Graded:
    """How an answer serves its question."""

    found: bool  # the agent said that the base holds the answer
    recall: float  # the share of the expected documents cited, as source or quote
    precision: float | None  # of the documents cited, the share expected or helping
    grounded: bool  # every quote is in the document its ref names, spacing aside
    evidence: bool  # each expected document's evidence is within a quote of it

    @property
    def success(self) -> bool:
        """Found, every quote grounded, and every expected document's evidence quoted."""
        return self.found and self.grounded and self.evidence


def grade(
    answer: Answer,
    question: Question,
    resolve: Callable[[str], str | None],
    body: Callable[[str], str],
) -> Graded:
    """Grade an answer: ``resolve`` gives the path a ref names, ``body`` a path's text.

    A quote is grounded when its words, spacing aside, are in the body of the document
    its ref names; a ref that names none grounds nothing. Evidence is compared as
    Section@10 compares it: marks and links aside, without regard to case.
    """
    quoted = [(resolve(quote.ref), quote.text) for quote in answer.quotes]
    cited = {resolve(ref) for ref in answer.sources} | {path for path, _ in quoted}
    cited.discard(None)
    known = {*question.expected, *question.partial}
    grounded = all(
        path is not None and " ".join(text.split()) in " ".join(body(path).split())
        for path, text in quoted
    )
    evidence = all(
        any(path == expected and plain(phrase) in plain(text) for path, text in quoted)
        for expected, phrase in question.evidence.items()
    )
    return Graded(
        found=answer.found,
        recall=len(cited & set(question.expected)) / len(question.expected),
        precision=len(cited & known) / len(cited) if cited else None,
        grounded=grounded,
        evidence=evidence,
    )


@dataclass(frozen=True)
class Difference:
    """B's mean less A's on one measure, its seeded bootstrap interval, and its tests."""

    difference: float
    interval: tuple[float, float]
    pvalue: float
    adjusted: float  # by Holm, over the measures compared


@dataclass(frozen=True)
class Verdict:
    """Whether ``ask`` stays among the default tools, and each measure's difference."""

    keeps_ask: bool
    differences: dict[str, Difference]


def interval(differences: Sequence[float], seed: int = SEED) -> tuple[float, float]:
    """Give the seeded bootstrap interval of a mean difference, at COVERAGE."""
    if not differences:
        return 0.0, 0.0
    values = np.array(differences, dtype=float)
    chosen = np.random.default_rng(seed).integers(0, len(values), (RESAMPLES, len(values)))
    means = values[chosen].mean(axis=1)
    tail = (1 - COVERAGE) / 2
    return float(np.quantile(means, tail)), float(np.quantile(means, 1 - tail))


def ask_verdict(pairs: Mapping[str, Sequence[tuple[float, float]]]) -> Verdict:
    """Judge surface B, with ``ask``, against A, without, from paired runs.

    ``pairs`` gives, for each measure (``success``, ``calls``, ``tokens``), A's and B's
    value question by question. Each is tested by ``paired_test``, Holm-adjusted over
    the measures. ``ask`` leaves the default tools only when B's success is lower with
    an adjusted p-value below ALPHA.
    """
    pvalues = {
        name: paired_test([a for a, _ in each], [b for _, b in each])
        for name, each in pairs.items()
    }
    adjusted = dict(zip(pvalues, holm(list(pvalues.values())), strict=True))
    differences = {
        name: Difference(
            difference=fmean(b - a for a, b in each) if each else 0.0,
            interval=interval([b - a for a, b in each]),
            pvalue=pvalues[name],
            adjusted=adjusted[name],
        )
        for name, each in pairs.items()
    }
    success = differences["success"]
    return Verdict(
        keeps_ask=not (success.difference < 0 and success.adjusted < ALPHA), differences=differences
    )
