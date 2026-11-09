"""Grading an agent's answer, and the rule on ask, worked by hand (plan 019)."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest
from pydantic import ValidationError

from kb_mcp.evaluation.domain.evaluation import Question
from kb_mcp.evaluation.domain.grading import (
    AgentAnswer,
    Harness,
    ask_verdict,
    grade,
    refusal,
)

if TYPE_CHECKING:
    from kb_mcp.evaluation.domain.grading import Graded

BODIES = {
    "kafka.md": "# Kafka\n\nKafka keeps logs\nfor **seven days**, then drops them.\n",
    "upgrade.md": "# Upgrade\n\nThe brokers move to 4.0 in May.\n",
    "ops.md": "# Rota\n\nWho is on call.\n",
}
# Each ref that names a document, as read takes them: id, key, address, path.
REFS = {
    "196845": "kafka.md",
    "PROJ-7": "upgrade.md",
    "https://example.atlassian.net/wiki/spaces/ENG/pages/196845/Kafka": "kafka.md",
    "kafka.md": "kafka.md",
    "OPS-1": "ops.md",
}
QUESTION = Question(
    id="q1",
    text="",
    expected=("kafka.md",),
    partial=("upgrade.md",),
    evidence={"kafka.md": "logs for seven days"},
)
SENTINEL = "value-sentinel-81f2"
QUESTIONS = 20
HALF = 0.5


def answered(**fields: object) -> AgentAnswer:
    """Give an answer, found and citing nothing unless told otherwise."""
    return AgentAnswer.model_validate_json(
        json.dumps({"found": True, "answer": "Seven days.", **fields})
    )


def graded(answer: AgentAnswer) -> Graded:
    """Grade an answer to the question, refs and bodies as above."""
    return grade(answer, QUESTION, REFS.get, BODIES.__getitem__)


@pytest.mark.parametrize("ref", sorted(set(REFS) - {"OPS-1"}))
def test_a_ref_resolves_by_id_key_address_or_path(ref: str) -> None:
    """A quote grounded in the document that the ref names, however the ref is written."""
    text = "Kafka keeps logs" if REFS[ref] == "kafka.md" else "The brokers move to 4.0"
    found = graded(answered(quotes=({"ref": ref, "text": text},)))
    assert found.grounded


def test_evidence_in_a_longer_quote_across_lines_and_marks_is_found() -> None:
    """The quote spans a line break; the evidence is compared without marks or case."""
    quote = {"ref": "196845", "text": "Kafka keeps logs for **seven days**, then drops them."}
    found = graded(answered(sources=("196845",), quotes=(quote,)))
    assert (found.grounded, found.evidence, found.success) == (True, True, True)
    assert (found.recall, found.precision) == (1.0, 1.0)


@pytest.mark.parametrize(
    "quote",
    [
        {"ref": "196845", "text": "Kafka keeps logs for thirty days"},  # fabricated
        {"ref": "PROJ-7", "text": "Kafka keeps logs"},  # misattributed
        {"ref": "999999", "text": "Kafka keeps logs"},  # a ref that names nothing
    ],
)
def test_a_quote_not_in_the_document_its_ref_names_is_not_grounded(quote: dict[str, str]) -> None:
    """Fabricated, or put to another document: no success, whatever else holds."""
    good = {"ref": "196845", "text": "Kafka keeps logs for seven days"}
    found = graded(answered(quotes=(good, quote)))
    assert not found.grounded
    assert not found.success


def test_an_expected_document_cited_without_its_evidence_is_no_success() -> None:
    """Cited as a source, quoted elsewhere: recall full, evidence missing."""
    quote = {"ref": "196845", "text": "then drops them"}
    found = graded(answered(sources=("196845", "PROJ-7"), quotes=(quote,)))
    assert (found.recall, found.precision, found.grounded) == (1.0, 1.0, True)
    assert not found.evidence
    assert not found.success


def test_precision_counts_the_documents_cited_that_answer_or_help() -> None:
    """One of two cited neither answers nor helps: a half; a ref naming nothing is no document."""
    assert graded(answered(sources=("196845", "OPS-1"))).precision == HALF
    assert graded(answered(sources=("196845", "999999"))).precision == 1.0
    assert graded(answered(sources=("PROJ-7",))).recall == 0.0
    assert graded(answered()).precision is None


def test_an_answer_not_found_is_no_success() -> None:
    """Saying the base does not hold it fails a question that it holds."""
    quote = {"ref": "196845", "text": "Kafka keeps logs for seven days"}
    assert not graded(answered(found=False, quotes=(quote,))).success


@pytest.mark.parametrize(
    ("given", "named"),
    [
        (f'{{"found": "{SENTINEL}", "answer": "x"}}', "found:"),
        (f'{{"found": true, "answer": "{SENTINEL}", "extra": 1}}', "extra:"),
        ('{"found": true, "answer": "' + "x" * 4001 + '"}', "answer:"),
        (
            '{"found": true, "answer": "x", "sources": ' + str(["196845"] * 11) + "}",
            "sources:",
        ),
        (f'{{"found": true, "answer": "x", "quotes": [{{"ref": "{SENTINEL}"}}]}}', "quotes.0"),
        (SENTINEL, "the whole:"),
    ],
)
def test_a_malformed_answer_is_refused_naming_the_field_never_the_value(
    given: str, named: str
) -> None:
    """Strict: a string is no boolean, no field unknown, bounds kept; the value never said."""
    with pytest.raises(ValidationError) as refused:
        AgentAnswer.model_validate_json(given.replace("'", '"'))
    said = refusal(refused.value)
    assert said.startswith(named)
    assert SENTINEL not in said


def test_a_harness_file_is_read_strictly() -> None:
    """Its status of three, a model's id, and tokens of 0 or more."""
    assert Harness.model_validate_json('{"status": "returned", "tokens": 0}').tokens == 0
    for given in ('{"status": "done"}', '{"status": "failed", "tokens": -1}', '{"x": 1}'):
        with pytest.raises(ValidationError):
            Harness.model_validate_json(given)


def pairs(a: float, b: float, *, b_last: float | None = None) -> list[tuple[float, float]]:
    """Give QUESTIONS pairs alike, the last of B set apart when asked."""
    return [(a, b)] * (QUESTIONS - 1) + [(a, b if b_last is None else b_last)]


def test_b_s_success_lower_with_an_adjusted_p_below_005_drops_ask() -> None:
    """Every question succeeds on A and fails on B: significant after Holm over three."""
    verdict = ask_verdict(
        {"success": pairs(1.0, 0.0), "calls": pairs(3.0, 1.0), "tokens": pairs(900, 800)}
    )
    assert not verdict.keeps_ask
    assert verdict.differences["success"].difference == -1.0
    assert verdict.differences["success"].adjusted < HALF / 10
    assert verdict.differences["calls"].interval == (-2.0, -2.0)


@pytest.mark.parametrize(
    "success",
    [
        pairs(1.0, 1.0, b_last=0.0),  # lower, by one question: not significant
        pairs(0.0, 1.0),  # higher
        pairs(1.0, 1.0),  # equal
    ],
)
def test_otherwise_ask_stays(success: list[tuple[float, float]]) -> None:
    """No measured harm, which is no proof of help: ask stays among the default tools."""
    verdict = ask_verdict({"success": success, "calls": pairs(2, 2), "tokens": pairs(1, 1)})
    assert verdict.keeps_ask
    low, high = verdict.differences["success"].interval
    assert low <= verdict.differences["success"].difference <= high
