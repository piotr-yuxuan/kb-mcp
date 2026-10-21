"""Tests of the golden set against the corpus (plan 002, criterion 4)."""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass

import pypandoc
import pytest

from sandbox.seed_corpus import (
    MAX_HOPS,
    OVERLAPS,
    TRAPS,
    Question,
    read_corpus,
    read_golden,
    read_ideas,
    read_tickets,
)

QUESTIONS = range(90, 111)
PER_OVERLAP = 25
FRENCH_QUESTIONS = 12
ENGLISH_ON_FRENCH = 6
TWO_HOPS = 12
ON_TICKETS = 15
ON_IDEAS = 3
PER_TRAP = 3
HEADING = re.compile(r"^#+\s+(.*)$", re.MULTILINE)
WORD = re.compile(r"[^\W\d_]{4,}")


@dataclass(frozen=True)
class Document:
    """A document's searchable text, and the names it is known by: title and headings."""

    text: str
    lang: str
    names: str


def flat(text: str) -> str:
    """Lower-case a text and collapse its white space, as the evidence rule compares."""
    return " ".join(text.lower().split())


def stems(text: str) -> set[str]:
    """Take the words of four letters or more, lower-cased, without a final s, ed or ing."""
    return {re.sub(r"(ing|ed|s)$", "", word) for word in WORD.findall(text.lower())}


@pytest.fixture(scope="module")
def documents() -> dict[str, Document]:
    """Every page, ticket and idea, keyed as the golden set names them."""
    found = {}
    for key, page in read_corpus().items():
        plain = pypandoc.convert_text(page.markdown, "plain", format="gfm-task_lists")
        names = " ".join([page.title, *HEADING.findall(page.markdown)])
        found[key] = Document(flat(plain), page.lang, names)
    for ticket in read_tickets():
        text = "\n".join([ticket.summary, ticket.markdown, *ticket.comments])
        names = " ".join([ticket.summary, *HEADING.findall(ticket.markdown)])
        found[ticket.key] = Document(flat(text), "en", names)
    for key, idea in read_ideas().items():
        names = " ".join([idea.summary, *HEADING.findall(idea.markdown)])
        found[key] = Document(flat(f"{idea.summary}\n{idea.markdown}"), "en", names)
    return found


@pytest.fixture(scope="module")
def golden() -> list[Question]:
    """Read the golden set once."""
    return read_golden()


def test_the_set_has_its_size_and_unique_ids(golden: list[Question]) -> None:
    """Ninety to 110 questions, each with its own id."""
    assert len(golden) in QUESTIONS
    assert len({question.id for question in golden}) == len(golden)


def test_every_named_document_exists(
    golden: list[Question], documents: dict[str, Document]
) -> None:
    """Expected, partial, outdated and distractor keys all name a page, ticket or idea."""
    unknown = {
        (question.id, key) for question in golden for key in question.documents - set(documents)
    }
    assert unknown == set()


def test_the_quotas_of_each_kind_are_met(
    golden: list[Question], documents: dict[str, Document]
) -> None:
    """Each overlap, language, hop count, source and trap is represented enough."""
    overlaps = Counter(question.overlap for question in golden)
    assert all(overlaps[overlap] >= PER_OVERLAP for overlap in OVERLAPS)
    assert sum(question.lang == "fr" for question in golden) >= FRENCH_QUESTIONS
    english_on_french = [
        question
        for question in golden
        if question.lang == "en"
        and any(documents[key].lang == "fr" for key in question.expected if key in documents)
    ]
    assert len(english_on_french) >= ENGLISH_ON_FRENCH
    assert sum(len(question.expected) == MAX_HOPS for question in golden) >= TWO_HOPS
    assert sum(any(key.startswith("ENG-") for key in q.expected) for q in golden) >= ON_TICKETS
    assert sum(any(key.startswith("jira/") for key in q.expected) for q in golden) >= ON_IDEAS
    traps = Counter(trap for question in golden for trap in question.traps)
    assert all(traps[trap] >= PER_TRAP for trap in TRAPS)


def test_evidence_is_in_its_document_and_nowhere_it_should_not_be(
    golden: list[Question], documents: dict[str, Document]
) -> None:
    """The phrase is in the expected document, not in the question or a look-alike."""
    problems = []
    for question in golden:
        elsewhere = [*question.distractors, *question.outdated]
        for key, phrase in question.evidence.items():
            wanted = flat(phrase)
            if key not in documents or wanted not in documents[key].text:
                problems.append(f"{question.id}: not in {key}")
            if wanted in flat(question.question):
                problems.append(f"{question.id}: in the question")
            problems += [
                f"{question.id}: in {other}"
                for other in elsewhere
                if other in documents and wanted in documents[other].text
            ]
    assert problems == []


def test_paraphrase_questions_share_no_word_with_titles_and_headings(
    golden: list[Question], documents: dict[str, Document]
) -> None:
    """A paraphrase question cannot be matched on its expected documents' names."""
    shared = {
        (question.id, key): stems(question.question) & stems(documents[key].names)
        for question in golden
        if question.overlap == "paraphrase"
        for key in question.expected
        if key in documents
    }
    assert {pair: words for pair, words in shared.items() if words} == {}
