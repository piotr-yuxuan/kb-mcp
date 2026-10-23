"""Search by meaning and by both, through the tools, on the tiny model (plans 011, 018).

The tiny model, behind a scripted endpoint, knows a few concepts: a query of one
concept's words finds a document written with others of that concept, which lexical
search cannot.
"""

from __future__ import annotations

import re
import threading
import time
from datetime import timedelta
from typing import TYPE_CHECKING

import httpx
import pytest

from atlassian_offline_mcp.kernel.endpoint import EMBEDDINGS
from atlassian_offline_mcp.mcp.app.tools import Library
from atlassian_offline_mcp.search.adapters.embedding import connect
from atlassian_offline_mcp.search.adapters.model_api import ModelError, endpoint
from atlassian_offline_mcp.search.adapters.sqlite_index import reading
from atlassian_offline_mcp.search.app.indexing import Embedding, build_index
from atlassian_offline_mcp.search.app.meaning import Meaning, Nearest
from atlassian_offline_mcp.search.domain.search import Filters, Score
from tests.answers import parts
from tests.endpoint import DIGEST, URL, Scripted, connector, scripted, tiny
from tests.mirrors import MOMENT, fillers, issue, page, write

if TYPE_CHECKING:
    from pathlib import Path

    from numpy.typing import NDArray

    from atlassian_offline_mcp.config.domain.settings import SearchMode
    from atlassian_offline_mcp.search.adapters.embedding import Embedder
    from atlassian_offline_mcp.search.adapters.sqlite_index import Reader

# Where "Mixed notes" comes by words for "4002 revert release": after the issue and
# the page holding both words.
WORDS_PLACE = 2
# The documents a search by meaning gives at most, as the plan says.
NEAREST = 100
DECOYS = NEAREST + 5
TARGET = "Holiday canteen"
FAILURE = "tiny: the endpoint answered 500"
# Seconds that a failed connection stands, as the plan says.
QUIET_S = 30
MIXED = "Mixed notes"
# Its title's unknown words put it far from any query by meaning, near by words.
WORDS = "Words of many other kinds"
# Only its perks are near "holidays", a word that no document holds.
HANDBOOK = (
    "# Handbook\n\n## Intro\n\nwelcome to the company\n\n## Perks\n\n"
    "leave leave leave\n\n## Other\n\nsecret words here\n"
)


@pytest.fixture
def data(tmp_path: Path) -> Path:
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
    embedding = Embedding(tiny(), tmp_path / "data" / "v.db")
    build_index(docs, tmp_path / "data" / "index.sqlite", MOMENT, embedding)
    return tmp_path / "data"


def library(data: Path, mode: SearchMode, meaning: Meaning | None = None) -> Library:
    """Return the tools over the data directory's index, ranking in ``mode``."""
    meaning = meaning or Meaning(connector())
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


def test_hybrid_shows_by_words_a_document_both_rank_first(tmp_path: Path) -> None:
    """A tie between the lists goes to words: the section that holds the query's word."""
    docs = tmp_path / "docs"
    fillers(docs)
    tied = "# Tied\n\n## First\n\nrevert revert revert\n\n## Second\n\nundo undo undo rollback\n"
    write(docs, page("4006", "Tied"), tied)
    build_index(docs, tmp_path / "index.sqlite", MOMENT, Embedding(tiny(), tmp_path / "v.db"))
    semantic = Library(tmp_path / "index.sqlite", docs, Meaning(connector()), "semantic")
    assert "section 3 Second" in hits(semantic.search("revert"))[0]
    hybrid = Library(tmp_path / "index.sqlite", docs, Meaning(connector()), "hybrid")
    assert "section 2 First" in hits(hybrid.search("revert"))[0]


def test_without_vectors_meaning_falls_back_to_words_and_says_why(tmp_path: Path) -> None:
    """An index built without a model: words alone, and the commands that add meaning."""
    docs = tmp_path / "docs"
    fillers(docs)
    write(docs, page("4002", TARGET), "Leave for a meal.\n")
    build_index(docs, tmp_path / "index.sqlite", MOMENT)
    tools = Library(tmp_path / "index.sqlite", docs, Meaning(connector()), "hybrid")
    answer = tools.search("meal")
    assert titles(answer) == [TARGET]
    assert (
        "Ranked by words alone: the index holds no vectors; check the embedding model"
        in (parts(answer)[0])
    )


def test_a_model_gone_or_pulled_again_since_the_build_falls_back(data: Path) -> None:
    """Gone from the endpoint: pull it. Other weights under its name: index again."""
    gone = library(data, "semantic", Meaning(connector(Scripted({})))).search("vacation lunch")
    assert "Ranked by words alone: tiny: not in Ollama's list of models" in gone
    assert "with Ollama: ollama pull tiny" in gone
    pulled = Meaning(connector(Scripted({"tiny:latest": "d2" * 32})))
    answer = library(data, "hybrid", pulled).search("vacation lunch")
    assert "tiny: the index was built with other weights of it" in parts(answer)[0]


class Failing:
    """An embedder whose every query fails, as an endpoint failing for a while would."""

    name = "tiny"
    dimensions = 16

    def __init__(self, fingerprint: str) -> None:
        """Answer to the tiny model's fingerprint."""
        self.fingerprint = fingerprint

    def documents(self, texts: list[str]) -> list[NDArray | None]:
        """Fail, whatever the texts."""
        del texts
        raise ModelError(FAILURE)

    def query(self, text: str) -> NDArray:
        """Fail, whatever the query."""
        del text
        raise ModelError(FAILURE)


def test_a_failing_query_falls_back_to_words(data: Path) -> None:
    """The search still answers, by words, and says what the endpoint answered."""
    failing = Failing(tiny().fingerprint)
    answer = library(data, "hybrid", Meaning(lambda _name: failing)).search("revert release")
    assert f"Ranked by words alone: {FAILURE}" in parts(answer)[0]
    assert titles(answer)[0] == WORDS


def test_a_query_refused_failing_or_not_answered_as_embeddings_falls_back(data: Path) -> None:
    """A 400 or a 500 for the query, or an answer that is not embeddings: words, and why."""
    refused = Meaning(connector(Scripted(refused={"revert release"})))
    answer = library(data, "hybrid", refused).search("revert release")
    assert "Ranked by words alone: tiny: the endpoint answered 400" in parts(answer)[0]
    failing = Scripted()
    tools = library(data, "hybrid", Meaning(connector(failing)))
    assert "Ranked by words alone" not in tools.search("revert release")
    failing.statuses = [500]
    answer = tools.search("revert release")
    assert "Ranked by words alone: tiny: the endpoint answered 500" in parts(answer)[0]
    answers = Scripted()

    def garbled(request: httpx.Request) -> httpx.Response:
        if b"revert release" in request.content:
            return httpx.Response(200, content=b"<html>")
        return answers(request)

    opened = endpoint(
        URL, None, EMBEDDINGS, remote_allowed=False, transport=httpx.MockTransport(garbled)
    )
    answer = library(data, "hybrid", Meaning(lambda name: connect(opened, name))).search(
        "revert release"
    )
    assert "Ranked by words alone: tiny: the endpoint's answer is not embeddings" in answer


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


class Connects:
    """What connects to a model, recording each connection, waiting or failing as told."""

    def __init__(
        self, answers: Scripted | None = None, *, wait: float = 0.0, fail: bool = False
    ) -> None:
        """Connect to the scripted models, after ``wait`` seconds, or fail every time."""
        self.names: list[str] = []
        self.opened = scripted(answers)
        self.wait = wait
        self.fail = fail

    def __call__(self, name: str) -> Embedder:
        """Record the connection, then connect, or fail as an endpoint not answering would."""
        self.names.append(name)
        time.sleep(self.wait)
        if self.fail:
            raise ModelError(FAILURE)
        return connect(self.opened, name)


TWO = {"tiny:latest": DIGEST, "tiny2:latest": DIGEST}


def rebuild(data: Path, model: str) -> None:
    """Build the data directory's index again, at the same moment, with ``model``."""
    embedding = Embedding(tiny(Scripted(TWO), model), data / "v.db")
    build_index(data / "docs", data / "index.sqlite", MOMENT, embedding)


def test_a_rebuilt_index_is_searched_with_its_own_vectors(data: Path) -> None:
    """Built again in the same second with a nearer page: the next search finds it."""
    tools = library(data, "semantic")
    assert titles(tools.search("holidays"))[0] == "Handbook"
    write(data / "docs", page("4010", "Vacation"), "vacation vacation vacation vacation\n")
    rebuild(data, "tiny")
    assert titles(tools.search("holidays"))[0] == "Vacation"


def test_an_index_built_with_another_model_connects_to_that_model(data: Path) -> None:
    """The model follows the index, never the one connected before; once a build."""
    connects = Connects(Scripted(TWO))
    tools = library(data, "hybrid", Meaning(connects))
    tools.search("holidays")
    tools.search("holidays")
    rebuild(data, "tiny2")
    tools.search("holidays")
    tools.search("holidays")
    assert connects.names == ["tiny", "tiny2"]


def test_a_failed_connection_stands_for_a_while_then_is_tried_again(data: Path) -> None:
    """Within 30 seconds, searches answer by words at once; the first after, connects."""
    now = [0.0]
    connects = Connects(fail=True)
    tools = library(data, "hybrid", Meaning(connects, clock=lambda: now[0]))
    for moment in (0.0, 10.0, QUIET_S - 1.0):
        now[0] = moment
        assert FAILURE in tools.search("holidays")
    assert connects.names == ["tiny"]
    now[0] = QUIET_S + 1.0
    connects.fail = False
    assert titles(tools.search("holidays"))[0] == "Handbook"
    assert connects.names == ["tiny", "tiny"]


def test_a_rebuilt_index_connects_at_once_after_a_failure(data: Path) -> None:
    """A failure stands for its build alone: the next build connects without waiting."""
    now = [0.0]
    connects = Connects(fail=True)
    tools = library(data, "hybrid", Meaning(connects, clock=lambda: now[0]))
    assert FAILURE in tools.search("holidays")
    connects.fail = False
    now[0] = 10.0
    rebuild(data, "tiny")
    assert titles(tools.search("holidays"))[0] == "Handbook"
    assert connects.names == ["tiny", "tiny"]


def test_a_stale_index_connects_no_more_while_its_build_lasts(data: Path) -> None:
    """Other weights since the build: the stale note, without a connection per search."""
    connects = Connects(Scripted({"tiny:latest": "d2" * 32}))
    tools = library(data, "hybrid", Meaning(connects))
    for _ in range(3):
        assert "the index was built with other weights of it" in tools.search("holidays")
    assert connects.names == ["tiny"]


@pytest.mark.parametrize("fail", [False, True])
def test_searches_at_once_wait_for_one_connection(data: Path, *, fail: bool) -> None:
    """The SDK runs tools in worker threads: one connects, and the others wait for it.

    Then they use its connection, or answer by words at once: never one connection each.
    """
    connects = Connects(wait=0.2, fail=fail)
    tools = library(data, "hybrid", Meaning(connects))
    answers: list[str] = []
    threads = [
        threading.Thread(target=lambda: answers.append(tools.search("holidays"))) for _ in range(3)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert connects.names == ["tiny"]
    if fail:
        assert all(FAILURE in answer for answer in answers)
    else:
        assert [titles(answer)[0] for answer in answers] == ["Handbook"] * 3


def test_a_long_section_is_shown_at_the_piece_that_meaning_found(tmp_path: Path) -> None:
    """The second piece of a section matches: the snippet starts there, not at the section."""
    docs = tmp_path / "docs"
    fillers(docs)
    body = "# Guide\n\n## Long\n\n" + "opening words " * 72 + "\n\n" + "leave " * 50 + "\n"
    write(docs, page("4007", "Guide"), body)
    build_index(docs, tmp_path / "index.sqlite", MOMENT, Embedding(tiny(), tmp_path / "v.db"))
    meaning = Meaning(connector())
    answer = Library(tmp_path / "index.sqlite", docs, meaning, "semantic").search("holidays")
    first = hits(answer)[0]
    assert "section 2 Long" in first
    assert "> leave leave leave" in first


def test_ties_by_meaning_keep_the_newest_before_the_cut(tmp_path: Path) -> None:
    """A hundred and five documents of one text tie: the hundred newest are kept, newest first."""
    docs = tmp_path / "docs"
    fillers(docs)
    # The newest has the highest id, so the order of pieces, by path, is oldest first.
    for number in range(105):
        updated = MOMENT - timedelta(days=105 - number)
        write(docs, page(str(7000 + number), "Recurring", updated=updated), "leave\n")
    build_index(docs, tmp_path / "index.sqlite", MOMENT, Embedding(tiny(), tmp_path / "v.db"))
    meaning = Meaning(connector())
    for mode in ("semantic", "hybrid"):
        tools = Library(tmp_path / "index.sqlite", docs, meaning, mode)
        shown, _ = tools.ranked("holidays", mode, limit=500)
        assert [each.path.split("/")[-1][:4] for each in shown] == [
            str(7104 - number) for number in range(100)
        ]


class Ordered(Meaning):
    """A search by meaning that ranks the documents it is given in that order."""

    def __init__(self, order: list[tuple[str, int, int, int]]) -> None:
        """Rank these paths, each with its section number and its span in the body."""
        super().__init__(connector())
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
    ordered = Ordered([(path, 3, start, end)])
    tools = Library(data / "index.sqlite", data / "docs", ordered, "hybrid")
    shown = next(hit for hit in hits(tools.search("PROJ-7 notes")) if MIXED in hit)
    assert "section 2 Notes" in shown


def test_with_an_identifier_a_place_higher_by_meaning_shows_meaning(data: Path) -> None:
    """Third by words, second by meaning, after the page named: its plan is shown."""
    path, start, end = plan_of(data)
    order = [
        each.path for each in library(data, "lexical").ranked("4002 revert release", "lexical")[0]
    ]
    assert order.index(path) == WORDS_PLACE
    ordered = Ordered([(path, 3, start, end)])
    tools = Library(data / "index.sqlite", data / "docs", ordered, "hybrid")
    shown = next(hit for hit in hits(tools.search("4002 revert release")) if MIXED in hit)
    assert "section 3 Plan" in shown
