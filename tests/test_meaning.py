"""Search by meaning and by both, through the tools, on the tiny model (plan 011).

The tiny model knows a few concepts: a query of one concept's words finds a document
written with others of that concept, which lexical search cannot.
"""

from __future__ import annotations

import os
import re
import threading
import time
from dataclasses import replace
from datetime import timedelta
from typing import TYPE_CHECKING

import pytest

from atlassian_offline_mcp.adapters.embedding import CATALOGUE, ModelError, load
from atlassian_offline_mcp.adapters.sqlite_index import reading
from atlassian_offline_mcp.app.indexing import Embedding, build_index
from atlassian_offline_mcp.app.meaning import Meaning, Nearest
from atlassian_offline_mcp.app.tools import Library
from atlassian_offline_mcp.domain.search import Filters, Score
from tests.answers import parts
from tests.mirrors import MOMENT, fillers, issue, page, write
from tests.tiny_model import registered, tiny

if TYPE_CHECKING:
    from pathlib import Path

    from _pytest.monkeypatch import MonkeyPatch
    from numpy.typing import NDArray

    from atlassian_offline_mcp.adapters.embedding import Embedder
    from atlassian_offline_mcp.adapters.sqlite_index import Reader
    from atlassian_offline_mcp.domain.settings import SearchMode

# Where "Mixed notes" comes by words for "4002 revert release": after the issue and
# the page holding both words.
WORDS_PLACE = 2
# The documents a search by meaning gives at most, as the plan says.
NEAREST = 100
DECOYS = NEAREST + 5
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
    """The count line says the documents are the nearest, at most 100 of them."""
    answer = library(data, "semantic").search("vacation lunch")
    assert answer.startswith(f"Documents nearest in meaning: {NEAREST};")
    hybrid = library(data, "hybrid").search("vacation lunch")
    # The nearest 100, of which the one page with the words is one.
    assert hybrid.startswith(f"Documents found by words or meaning: {NEAREST};")


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


@pytest.mark.parametrize("mode", ["lexical", "semantic", "hybrid"])
def test_a_document_named_is_ranked_once(data: Path, mode: SearchMode) -> None:
    """First, and only first: the named issue is not ranked again where meaning finds it."""
    shown, _ = library(data, mode).ranked("PROJ-7 kafka upgrade holidays", mode, limit=500)
    paths = [each.path for each in shown]
    assert paths[0] == "jira/PROJ/PROJ-7.md"
    assert len(paths) == len(set(paths))


def test_sorting_by_update_is_the_same_in_every_mode(data: Path) -> None:
    """What changed last is a matter of dates: the documents matching the words, newest first."""
    answers = {
        mode: library(data, mode).search("revert", sort="updated")
        for mode in ("lexical", "semantic", "hybrid")
    }
    assert answers["semantic"] == answers["lexical"] == answers["hybrid"]


def test_hybrid_shows_the_section_that_meaning_ranks_higher(data: Path) -> None:
    """Words rank "Mixed notes" second, meaning first: its plan is shown, not its notes."""
    hybrid = hits(library(data, "hybrid").search("revert release"))
    shown = next(hit for hit in hybrid if MIXED in hit)
    assert "section 3 Plan" in shown
    assert shown.endswith("> rollback deploy rollback deploy")
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


class Loads:
    """A model loader that records each load, and may wait or fail as told."""

    def __init__(self, *, wait: float = 0.0, fail: bool = False) -> None:
        """Load for real, after ``wait`` seconds, or fail every time."""
        self.names: list[str] = []
        self.wait = wait
        self.fail = fail

    def __call__(self, name: str, models: Path) -> Embedder:
        """Record the load, then load, or fail as a broken model would."""
        self.names.append(name)
        time.sleep(self.wait)
        if self.fail:
            raise ModelError(FAILURE)
        return load(name, models)


def rebuild(data: Path, model: str) -> None:
    """Build the data directory's index again, at the same moment, with ``model``."""
    embedding = Embedding(load(model, data / "models"), data / "v.db")
    build_index(data / "docs", data / "index.sqlite", MOMENT, embedding)


def test_a_rebuilt_index_is_searched_with_its_own_vectors(data: Path) -> None:
    """Built again in the same second with a nearer page: the next search finds it."""
    tools = library(data, "semantic")
    assert titles(tools.search("holidays"))[0] == "Handbook"
    write(data / "docs", page("4010", "Vacation"), "vacation vacation vacation vacation\n")
    rebuild(data, "tiny")
    assert titles(tools.search("holidays"))[0] == "Vacation"


def test_an_index_built_with_another_model_loads_that_model(
    data: Path, monkeypatch: MonkeyPatch
) -> None:
    """The model follows the index, never the one loaded before."""
    loads = Loads()
    tools = Library(data / "index.sqlite", data / "docs", Meaning(data / "models", loads), "hybrid")
    tools.search("holidays")
    second = tiny(data / "models", name="tiny2")
    monkeypatch.setitem(CATALOGUE, "tiny2", second)
    rebuild(data, "tiny2")
    tools.search("holidays")
    tools.search("holidays")
    assert loads.names == ["tiny", "tiny2"]


def test_a_model_that_failed_is_tried_again_only_once_its_files_change(data: Path) -> None:
    """No hashing of hundreds of megabytes per search: the failure is remembered."""
    loads = Loads(fail=True)
    tools = Library(data / "index.sqlite", data / "docs", Meaning(data / "models", loads), "hybrid")
    for _ in range(3):
        assert FAILURE in tools.search("holidays")
    assert loads.names == ["tiny"]
    graph = data / "models" / "tiny" / "model.onnx"
    later = graph.stat().st_mtime_ns + 10**9
    os.utime(graph, ns=(later, later))
    tools.search("holidays")
    assert loads.names == ["tiny", "tiny"]


def test_searches_at_once_load_the_model_once(data: Path) -> None:
    """The SDK runs tools in worker threads: the model is loaded under a lock."""
    loads = Loads(wait=0.2)
    tools = Library(data / "index.sqlite", data / "docs", Meaning(data / "models", loads), "hybrid")
    answers: list[str] = []
    threads = [
        threading.Thread(target=lambda: answers.append(tools.search("holidays"))) for _ in range(3)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert loads.names == ["tiny"]
    assert [titles(answer)[0] for answer in answers] == ["Handbook"] * 3


def test_an_unreadable_model_falls_back_to_words(data: Path) -> None:
    """A file that cannot be read is no tool error: words answer, and say what to do."""
    graph = data / "models" / "tiny" / "model.onnx"
    graph.chmod(0)
    try:
        answer = library(data, "hybrid").search("revert release")
    finally:
        graph.chmod(0o644)
    assert "Ranked by words alone: tiny: files not as pinned; atlassian-offline-mcp model" in answer


def test_a_model_made_readable_again_is_loaded_again(data: Path) -> None:
    """Permissions restored, content untouched: the failure is forgotten, meaning answers."""
    tools = library(data, "hybrid")
    graph = data / "models" / "tiny" / "model.onnx"
    graph.chmod(0)
    try:
        assert "Ranked by words alone" in tools.search("holidays")
    finally:
        graph.chmod(0o644)
    assert titles(tools.search("holidays"))[0] == "Handbook"


def test_a_long_section_is_shown_at_the_piece_that_meaning_found(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """The second piece of a section matches: the snippet starts there, not at the section."""
    docs = tmp_path / "docs"
    fillers(docs)
    body = "# Guide\n\n## Long\n\n" + "opening words " * 72 + "\n\n" + "leave " * 50 + "\n"
    write(docs, page("4007", "Guide"), body)
    registered(tmp_path / "models", monkeypatch)
    embedding = Embedding(load("tiny", tmp_path / "models"), tmp_path / "v.db")
    build_index(docs, tmp_path / "index.sqlite", MOMENT, embedding)
    meaning = Meaning(tmp_path / "models")
    answer = Library(tmp_path / "index.sqlite", docs, meaning, "semantic").search("holidays")
    first = hits(answer)[0]
    assert "section 2 Long" in first
    assert "> leave leave leave" in first


def test_ties_by_meaning_keep_the_newest_before_the_cut(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """A hundred and five documents of one text tie: the hundred newest are kept, newest first."""
    docs = tmp_path / "docs"
    fillers(docs)
    # The newest has the highest id, so the order of pieces, by path, is oldest first.
    for number in range(105):
        updated = MOMENT - timedelta(days=105 - number)
        write(docs, page(str(7000 + number), "Recurring", updated=updated), "leave\n")
    registered(tmp_path / "models", monkeypatch)
    embedding = Embedding(load("tiny", tmp_path / "models"), tmp_path / "v.db")
    build_index(docs, tmp_path / "index.sqlite", MOMENT, embedding)
    meaning = Meaning(tmp_path / "models")
    for mode in ("semantic", "hybrid"):
        tools = Library(tmp_path / "index.sqlite", docs, meaning, mode)
        shown, _ = tools.ranked("holidays", mode, limit=500)
        assert [each.path.split("/")[-1][:4] for each in shown] == [
            str(7104 - number) for number in range(100)
        ]


class Scripted(Meaning):
    """A search by meaning that ranks the documents it is given in that order."""

    def __init__(self, order: list[tuple[str, int, int, int]], models: Path) -> None:
        """Rank these paths, each with its section number and its span in the body."""
        super().__init__(models)
        self.order = order

    def nearest(self, reader: Reader, query: str, filters: Filters) -> Nearest:
        """Give the scripted documents, the first nearest."""
        del reader, query, filters
        return Nearest(
            {
                path: (Score(1.0 - rank / 100, MOMENT), section, start, end)
                for rank, (path, section, start, end) in enumerate(self.order)
            }
        )


def plan_of(data: Path) -> tuple[str, int, int]:
    """Give "Mixed notes", with the span of its third section: its plan."""
    path = "confluence/OPS/4004-mixed-notes.md"
    with reading(data / "index.sqlite") as reader:
        start, end = reader.bounds(path)[2]
    return path, start, end


def test_with_an_identifier_a_tie_still_goes_to_words(data: Path) -> None:
    """Both lists begin with the issue named: the notes, next in each, are shown by words."""
    path, start, end = plan_of(data)
    order = [each.path for each in library(data, "lexical").ranked("PROJ-7 notes", "lexical")[0]]
    assert order[:2] == ["jira/PROJ/PROJ-7.md", path]
    scripted = Scripted([(path, 3, start, end)], data / "models")
    tools = Library(data / "index.sqlite", data / "docs", scripted, "hybrid")
    shown = next(hit for hit in hits(tools.search("PROJ-7 notes")) if MIXED in hit)
    assert "section 2 Notes" in shown


def test_with_an_identifier_a_place_higher_by_meaning_shows_meaning(data: Path) -> None:
    """Third by words, second by meaning, after the page named: its plan is shown."""
    path, start, end = plan_of(data)
    order = [
        each.path for each in library(data, "lexical").ranked("4002 revert release", "lexical")[0]
    ]
    assert order.index(path) == WORDS_PLACE
    scripted = Scripted([(path, 3, start, end)], data / "models")
    tools = Library(data / "index.sqlite", data / "docs", scripted, "hybrid")
    shown = next(hit for hit in hits(tools.search("4002 revert release")) if MIXED in hit)
    assert "section 3 Plan" in shown


def test_a_model_folder_that_cannot_be_searched_falls_back(data: Path) -> None:
    """Even the folder unreadable, after a pull as another account: words, never an error."""
    folder = data / "models" / "tiny"
    folder.chmod(0)
    try:
        answer = library(data, "hybrid").search("revert release")
    finally:
        folder.chmod(0o755)
    assert "Ranked by words alone" in answer
