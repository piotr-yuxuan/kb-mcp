"""Search by meaning and by both, through the tools, on the tiny model (plan 011).

The tiny model knows a few concepts: a query of one concept's words finds a document
written with others of that concept, which lexical search cannot.
"""

from __future__ import annotations

import re
from dataclasses import replace
from typing import TYPE_CHECKING

import pytest

from atlassian_offline_mcp.adapters.embedding import CATALOGUE, ModelError, load
from atlassian_offline_mcp.app.indexing import Embedding, build_index
from atlassian_offline_mcp.app.meaning import DEPTH, Meaning
from atlassian_offline_mcp.app.tools import Library
from tests.answers import parts
from tests.mirrors import MOMENT, fillers, issue, page, write
from tests.tiny_model import registered

if TYPE_CHECKING:
    from pathlib import Path

    from _pytest.monkeypatch import MonkeyPatch
    from numpy.typing import NDArray

    from atlassian_offline_mcp.domain.settings import SearchMode

DECOYS = DEPTH + 5
TARGET = "Holiday canteen"
FAILURE = "tiny: does not embed (Fail)"
MIXED = "Mixed notes"
# Its title's unknown words put it far from any query by meaning, near by words.
WORDS = "Words of many other kinds"
# Only its perks are near "holidays", a word that no document holds.
HANDBOOK = (
    "# Handbook\n\n## Intro\n\nwelcome to the company\n\n## Perks\n\n"
    "leave leave leave\n\n## Other\n\nsecret words here\n"
)


@pytest.fixture
def data(tmp_path: Path, monkeypatch: MonkeyPatch) -> Path:
    """Give a mirror of more than 100 documents, indexed with the tiny model.

    Decoys in ENG are all nearer "revert seller" than the runbook in OPS; the holiday
    page shares no word with "vacation lunch"; "Mixed notes" holds "revert" in one
    section and, in another, "rollback deploy", near "revert release" by meaning.
    """
    docs = tmp_path / "data" / "docs"
    fillers(docs)
    for number in range(DECOYS):
        write(docs, page(str(5000 + number), f"Decoy {number}"), "undo seller undo seller\n")
    write(docs, page("4001", "Rollback runbook", space="OPS"), "How to restore payouts.\n")
    write(docs, page("4002", TARGET), "Leave for a meal.\n")
    write(docs, page("4003", WORDS, space="OPS"), "revert release\n")
    mixed = "# Mixed notes\n\n## Notes\n\nrevert\n\n## Plan\n\nrollback deploy rollback deploy\n"
    write(docs, page("4004", MIXED, space="OPS"), mixed)
    write(docs, issue("PROJ-7", "Kafka upgrade"))
    write(docs, page("4005", "Handbook"), HANDBOOK)
    registered(tmp_path / "data" / "models", monkeypatch)
    embedding = Embedding(load("tiny", tmp_path / "data" / "models"), tmp_path / "data" / "v.db")
    build_index(docs, tmp_path / "data" / "index.sqlite", MOMENT, embedding)
    return tmp_path / "data"


def library(data: Path, mode: SearchMode, meaning: Meaning | None = None) -> Library:
    """Return the tools over the data directory's index, ranking in ``mode``."""
    meaning = meaning or Meaning(data / "models")
    return Library(data / "index.sqlite", data / "docs", meaning, mode)


def titles(answer: str) -> list[str]:
    """List the titles of a search's hits, in order."""
    return re.findall(r"^\d+\. (.+)$", parts(answer)[1], re.MULTILINE)


def hits(answer: str) -> list[str]:
    """Give each hit of a search, its lines together, in order."""
    return re.split(r"\n(?=\d+\. )", parts(answer)[1])


@pytest.mark.parametrize("mode", ["semantic", "hybrid"])
def test_a_query_without_a_word_of_its_target_finds_it_by_meaning(
    data: Path, mode: SearchMode
) -> None:
    """Nothing in common but meaning: first by meaning, and nowhere by words."""
    assert titles(library(data, mode).search("vacation lunch"))[0] == TARGET
    lexical = library(data, "lexical").search("vacation lunch")
    assert TARGET not in lexical
    assert lexical.startswith("Documents found: 0")


def test_status_names_the_model_and_its_pieces(data: Path) -> None:
    """What the server can search by meaning is said where the agent looks."""
    assert re.search(r"search by meaning: tiny, \d+ pieces", library(data, "lexical").status())


def test_a_search_by_meaning_counts_the_nearest(data: Path) -> None:
    """The count line says the documents are the nearest, at most DEPTH of them."""
    answer = library(data, "semantic").search("vacation lunch")
    assert answer.startswith(f"Documents nearest in meaning: {DEPTH};")


def test_a_filter_applies_before_the_nearest_are_cut(data: Path) -> None:
    """Over a hundred decoys are nearer, but only the runbook is in OPS's space."""
    semantic = library(data, "semantic")
    assert "Rollback runbook" not in semantic.search("revert seller", limit=50)
    assert titles(semantic.search("revert seller", filters={"space": "OPS"}))[0] == (
        "Rollback runbook"
    )


@pytest.mark.parametrize("mode", ["lexical", "semantic", "hybrid"])
def test_an_issue_key_comes_first_in_every_mode(data: Path, mode: SearchMode) -> None:
    """Identifiers pin their documents, whatever ranks the rest."""
    assert titles(library(data, mode).search("PROJ-7 vacation lunch"))[0] == "Kafka upgrade"


def test_hybrid_shows_the_section_that_meaning_ranks_higher(data: Path) -> None:
    """Words rank "Mixed notes" second, meaning first: its plan is shown, not its notes."""
    hybrid = hits(library(data, "hybrid").search("revert release"))
    assert "section 3 Plan" in next(hit for hit in hybrid if MIXED in hit)
    lexical = hits(library(data, "lexical").search("revert release"))
    assert "section 2 Notes" in next(hit for hit in lexical if MIXED in hit)


def test_hybrid_shows_by_meaning_a_document_that_only_meaning_finds(data: Path) -> None:
    """No word found: the perks are shown, and their snippet stops where their piece does."""
    answer = library(data, "hybrid").search("holidays")
    assert answer.startswith("Documents found by words or meaning:")
    first = hits(answer)[0]
    assert first.startswith("1. Handbook")
    assert "section 3 Perks" in first
    assert "> leave leave leave" in first
    assert "secret" not in first


def test_hybrid_shows_by_words_a_document_both_rank_first(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """A tie between the lists goes to words: the section that holds the query's word."""
    docs = tmp_path / "docs"
    fillers(docs)
    tied = "# Tied\n\n## First\n\nrevert revert revert\n\n## Second\n\nundo undo undo rollback\n"
    write(docs, page("4006", "Tied"), tied)
    registered(tmp_path / "models", monkeypatch)
    embedding = Embedding(load("tiny", tmp_path / "models"), tmp_path / "v.db")
    build_index(docs, tmp_path / "index.sqlite", MOMENT, embedding)
    semantic = Library(tmp_path / "index.sqlite", docs, Meaning(tmp_path / "models"), "semantic")
    assert "section 3 Second" in hits(semantic.search("revert"))[0]
    hybrid = Library(tmp_path / "index.sqlite", docs, Meaning(tmp_path / "models"), "hybrid")
    assert "section 2 First" in hits(hybrid.search("revert"))[0]


def test_without_vectors_meaning_falls_back_to_words_and_says_why(tmp_path: Path) -> None:
    """An index built without a model: words alone, and the command that adds meaning."""
    docs = tmp_path / "docs"
    fillers(docs)
    write(docs, page("4002", TARGET), "Leave for a meal.\n")
    build_index(docs, tmp_path / "index.sqlite", MOMENT)
    answer = Library(tmp_path / "index.sqlite", docs, Meaning(tmp_path), "hybrid").search("meal")
    assert titles(answer) == [TARGET]
    assert "Ranked by words alone: the index holds no vectors; pull a model" in parts(answer)[0]


def test_a_model_removed_or_changed_since_the_build_falls_back(
    data: Path, monkeypatch: MonkeyPatch
) -> None:
    """Files gone: pull it again. Another version in the catalogue: index again."""
    moved = data.parent / "elsewhere"
    (data / "models").rename(moved)
    answer = library(data, "semantic").search("vacation lunch")
    assert "Ranked by words alone: tiny: not pulled; atlassian-offline-mcp model pull" in answer
    moved.rename(data / "models")
    monkeypatch.setitem(CATALOGUE, "tiny", replace(CATALOGUE["tiny"], query_prefix="alpha "))
    answer = library(data, "hybrid").search("vacation lunch")
    assert "tiny: the index was built with another version of it" in parts(answer)[0]


class Failing:
    """An embedder whose model fails at every query, as a broken runtime would."""

    name = "tiny"
    dimensions = 16

    def __init__(self, fingerprint: str) -> None:
        """Answer to the tiny model's fingerprint."""
        self.fingerprint = fingerprint

    def documents(self, texts: list[str]) -> NDArray:
        """Fail, whatever the texts."""
        del texts
        raise ModelError(FAILURE)

    def query(self, text: str) -> NDArray:
        """Fail, whatever the query."""
        del text
        raise ModelError(FAILURE)


def test_a_failing_model_falls_back_to_words(data: Path) -> None:
    """The search still answers, by words, and says the model failed by its error's class."""
    failing = Failing(CATALOGUE["tiny"].fingerprint)
    meaning = Meaning(data / "models", load=lambda _name, _models: failing)
    answer = library(data, "hybrid", meaning).search("revert release")
    assert "Ranked by words alone: tiny: does not embed (Fail)" in parts(answer)[0]
    assert titles(answer)[0] == WORDS


def test_the_ranking_for_an_evaluation_is_the_search_s(data: Path) -> None:
    """``ranked`` gives the documents search shows, with their sections and texts."""
    tools = library(data, "hybrid")
    shown, note = tools.ranked("revert release", "hybrid", limit=3)
    assert note == ""
    searched = titles(tools.search("revert release", limit=3))
    assert [one.path.split("/")[-1].split("-", 1)[1] for one in shown] == [
        title.lower().replace(" ", "-") + ".md" for title in searched
    ]
    mixed = next(one for one in shown if "mixed" in one.path)
    assert (mixed.section, mixed.text) == (3, "## Plan\n\nrollback deploy rollback deploy\n")
