"""Search and ask reranked: the first documents reordered, the rest kept, pages followed."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

import pytest

from atlassian_offline_mcp.kernel.reranking import LONGEST_TEXT, MOST_TEXTS
from atlassian_offline_mcp.mcp.app.tools import Library, UnanswerableError
from atlassian_offline_mcp.search.adapters.reranking import Reranked, RerankError
from atlassian_offline_mcp.search.app.reranking import Reranking
from atlassian_offline_mcp.search.domain.reranking import PLACES, split_order, written
from tests.answers import built, continuation, follow, parts
from tests.mirrors import issue, page

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    from _pytest.tempdir import TempPathFactory

QUERY = "release rollback"
DEPTH = 4
# Each page: the more of the query's words, the higher words rank it; the more "zeta",
# the higher the scripted reranker scores it.
PAGES = 6
LONG = "Lorem ipsum dolor sit amet. " * 160  # 4,480 characters
DOWN = "no answer from the reranking server (ConnectError); is it running?"
REFUSED = "qwen3-reranker-0.6b: the reranking server answered 400"


def body(number: int) -> str:
    """Write a page whose words rank it ``number``-th and whose reranking score is ``number``."""
    return f"# Release {number}\n\n" + "release rollback " * (PAGES - number) + "zeta " * number


class Scripted:
    """A reranker that scores a text by its count of "zeta", or fails as told; it records."""

    def __init__(self) -> None:
        """Answer every request, until told to fail."""
        self.asked: list[list[str]] = []
        self.failing: RerankError | None = None

    def __call__(self, _query: str, texts: Sequence[str]) -> Reranked:
        """Score the texts, or raise the failure set."""
        self.asked.append(list(texts))
        if self.failing:
            raise self.failing
        return Reranked([float(text.count("zeta")) for text in texts], None)


@pytest.fixture(scope="module")
def root(tmp_path_factory: TempPathFactory) -> Path:
    """Index a mirror of pages ranked by words in one order, by zeta in the other."""
    folder = tmp_path_factory.mktemp("reranked")
    documents = [
        *(
            (page(str(910000 + number), f"Release {number}"), body(number))
            for number in range(PAGES)
        ),
        (issue("PROJ-9", "Release zeta"), "# Release zeta\n\nrelease rollback " + "zeta " * 9),
        (page("910100", "Deep"), "# Deep\n\n" + LONG + "release rollback zeta.\n\n" + LONG),
        (page("910200", "Single"), "# Single\n\nquasar\n"),
    ]
    built(folder, documents)
    return folder


def library(root: Path, reranking: Reranking | None) -> Library:
    """Serve the index by words alone, reranked through ``reranking`` if any."""
    return Library(root / "index.sqlite", root / "docs", None, "lexical", reranking)


def order(served: Library, query: str = QUERY) -> list[str]:
    """Give the paths in the order that search ranks them, as eval reads it."""
    return [shown.path for shown in served.ranked(query, "lexical", limit=50)[0]]


def titles(answer: str) -> list[str]:
    """List the titles of an answer's documents, in order."""
    return re.findall(r"^\d+\. (.+)$", parts(answer)[1], re.MULTILINE)


def zeta(root: Path, path: str) -> int:
    """Count the document's zetas, as it was written, title aside."""
    return (root / "docs" / path).read_text("utf-8").split("---", 2)[2].count("zeta")


def title(root: Path, path: str) -> str:
    """Read a document's title from its front matter, as the mirror wrote it."""
    text = (root / "docs" / path).read_text("utf-8")
    found = re.search(r"^title: (.+)$", text, re.MULTILINE)
    assert found is not None
    return found[1].strip("'\"")


def expected(root: Path, before: list[str], pinned: int = 0) -> list[str]:
    """Reorder the DEPTH documents after those pinned by their zetas, ties as they were."""
    moved = before[pinned : pinned + DEPTH]
    reordered = sorted(moved, key=lambda path: -zeta(root, path))
    return [*before[:pinned], *reordered, *before[pinned + DEPTH :]]


def test_the_first_documents_follow_the_scores_and_the_rest_keep_their_order(root: Path) -> None:
    """DEPTH documents reordered, highest score first; those after them as words ranked."""
    before = order(library(root, None))
    scorer = Scripted()
    after = order(library(root, Reranking(scorer, DEPTH)))
    assert after == expected(root, before)
    assert after != before
    assert len(scorer.asked) == 1
    assert len(scorer.asked[0]) == DEPTH


def test_a_document_named_stays_first_and_is_not_scored(root: Path) -> None:
    """PROJ-9 named: first, as words put it, though its zetas would have it first anyway."""
    query = f"PROJ-9 {QUERY}"
    before = order(library(root, None), query)
    scorer = Scripted()
    after = order(library(root, Reranking(scorer, DEPTH)), query)
    assert before[0] == after[0] == "jira/PROJ/PROJ-9.md"
    assert after == expected(root, before, pinned=1)
    assert not any("PROJ-9" in text or "Release zeta" in text for text in scorer.asked[0])


def test_search_and_ask_show_the_order_reranked(root: Path) -> None:
    """Both tools list the documents as reranked; ask as many as fit its budget."""
    wanted = [title(root, path) for path in expected(root, order(library(root, None)))]
    reranked = library(root, Reranking(Scripted(), DEPTH))
    assert titles(reranked.search(QUERY, limit=50)) == wanted
    asked = [line.split(" | ")[0] for line in titles(reranked.ask(QUERY))]
    assert asked == wanted[: len(asked)]
    assert len(asked) > DEPTH


def test_nothing_is_asked_sorted_by_update_or_for_fewer_than_two(root: Path) -> None:
    """Sorted by update, no relevance to reorder; one document found, no order to change."""
    scorer = Scripted()
    served = library(root, Reranking(scorer, DEPTH))
    served.search(QUERY, sort="updated")
    served.search("quasar")
    assert scorer.asked == []


def test_the_text_scored_is_the_title_the_heading_and_the_words_place(root: Path) -> None:
    """At most LONGEST_TEXT; a match deep in a long section is what the reranker reads."""
    scorer = Scripted()
    order(library(root, Reranking(scorer, 64)), QUERY)
    texts = scorer.asked[0]
    assert all(len(text) <= LONGEST_TEXT for text in texts)
    (deep,) = [text for text in texts if text.startswith("Deep\n")]
    assert "release rollback zeta" in deep
    assert all(text.split("\n")[0].startswith(("Release", "Deep")) for text in texts)


def test_a_failure_keeps_the_order_and_says_why_then_waits_30_seconds(root: Path) -> None:
    """The earlier order and its note; no request within 30 seconds; one after them."""
    now = [0.0]
    scorer = Scripted()
    scorer.failing = RerankError(DOWN, "unanswered")
    served = library(root, Reranking(scorer, DEPTH, clock=lambda: now[0]))
    answer = served.search(QUERY)
    assert f" Not reranked: {DOWN}." in parts(answer)[0]
    assert titles(answer) == titles(library(root, None).search(QUERY))
    served.search(QUERY)
    assert len(scorer.asked) == 1
    now[0] = 31.0
    scorer.failing = None
    assert order(served) == expected(root, order(library(root, None)))
    assert [len(texts) for texts in scorer.asked] == [DEPTH, DEPTH]


def test_a_refusal_is_the_request_s_and_the_next_search_asks_again(root: Path) -> None:
    """A refused request falls back for that search alone."""
    scorer = Scripted()
    scorer.failing = RerankError(REFUSED, "refused")
    served = library(root, Reranking(scorer, DEPTH))
    assert "Not reranked: " in parts(served.search(QUERY))[0]
    scorer.failing = None
    assert order(served) == expected(root, order(library(root, None)))


def pages(served: Library, answer: str) -> list[str]:
    """Follow an answer's cursors to its end; give every title, in order."""
    found = titles(answer)
    while (answer := follow(served, answer) or "") and titles(answer):
        found += titles(answer)
    return found


def test_a_cursor_carries_the_order_and_its_pages_ask_nothing(root: Path) -> None:
    """Pages of two: the reranked order, none twice, one request, the reranker down after it."""
    scorer = Scripted()
    served = library(root, Reranking(scorer, DEPTH))
    first = served.search(QUERY, limit=2)
    scorer.failing = RerankError(DOWN, "unanswered")
    every = pages(served, first)
    assert every == titles(library(root, Reranking(Scripted(), DEPTH)).search(QUERY, limit=50))
    assert len(every) == len(set(every))
    assert len(scorer.asked) == 1


def test_a_first_page_not_reranked_continues_unreranked(root: Path) -> None:
    """Fallen back first: its cursor carries no order, so its pages follow words."""
    scorer = Scripted()
    scorer.failing = RerankError(REFUSED, "refused")
    served = library(root, Reranking(scorer, DEPTH))
    first = served.search(QUERY, limit=2)
    scorer.failing = None
    assert pages(served, first) == titles(library(root, None).search(QUERY, limit=50))
    assert len(scorer.asked) == 1


def cursor_of(answer: str) -> str:
    """Give the cursor that an answer's continuing call carries."""
    found = continuation(answer)
    assert found is not None
    return str(found[1]["cursor"])


@pytest.mark.parametrize(
    ("order_written", "said"),
    [
        (".AA", "give the one that the previous answer ended with"),
        (".A!", "give the one that the previous answer ended with"),
        (".AC", "give the one that the previous answer ended with"),
        ("." + "".join(chr(ord("A") + place) for place in range(26)), "ranking changed since"),
    ],
)
def test_a_cursor_whose_order_is_none_or_too_long_is_refused(
    root: Path, order_written: str, said: str
) -> None:
    """A place repeated, not one, or past the others; an order longer than the documents."""
    served = library(root, Reranking(Scripted(), DEPTH))
    base = cursor_of(served.search(QUERY, limit=2)).partition(".")[0]
    with pytest.raises(UnanswerableError, match=said):
        served.search(QUERY, limit=2, cursor=base + order_written)


def test_a_browse_cursor_carrying_an_order_is_refused(root: Path) -> None:
    """The cursors of browse carry no order: one that does is not one of its own."""
    served = library(root, Reranking(Scripted(), DEPTH))
    base = cursor_of(served.search(QUERY, limit=2)).partition(".")[0]
    with pytest.raises(UnanswerableError, match="cursor: "):
        served.browse(space="ENG", cursor=f"{base}.BA")


def test_a_cursor_writes_the_deepest_order_and_reads_it_back() -> None:
    """MOST_TEXTS places, each a character of the alphabet; read as written."""
    deepest = tuple(reversed(range(MOST_TEXTS)))
    assert len(PLACES) >= MOST_TEXTS
    assert split_order(f"8@x{written(deepest)}") == ("8@x", deepest)
    assert split_order("8@x") == ("8@x", ())
    assert split_order(None) == (None, None)
