"""The reranking adapter: llama.cpp's rerank API, its bounds, its failures by kind."""

from __future__ import annotations

import json
import os
from dataclasses import replace
from typing import TYPE_CHECKING

import httpx
import pytest

from atlassian_offline_mcp.config.domain.settings import SettingsError
from atlassian_offline_mcp.kernel.endpoint import RERANKING
from atlassian_offline_mcp.kernel.reranking import LONGEST_QUERY, LONGEST_TEXT, MOST_TEXTS
from atlassian_offline_mcp.search.adapters.model_api import endpoint
from atlassian_offline_mcp.search.adapters.reranking import (
    EVALUATION,
    SEARCH,
    RerankError,
    rerank,
    served,
)
from tests.endpoint import (
    REACHABLE,
    RERANK_URL,
    RERANKER,
    RERANKING_FIXTURES,
    Reranks,
    relevance,
    reranks,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

    from atlassian_offline_mcp.search.adapters.model_api import Endpoint

QUERY = "how do I roll back a release"
TEXTS = (
    "The canteen opens at noon.",
    "Roll back a release to its previous image.",
    "A release is cut every Monday.",
)
# Seconds that the injected clock moves at each look: three looks pass a deadline of 30.
TICK_S = 11.0
# Reads of a trickled answer before its deadline of 30 seconds is passed, at most.
READS = 4
# Text that an answer may echo, and that no message may hold.
ECHO = "the query, echoed"
# A model served by a local llama-server on the default address, for the opt-in test.
LIVE = os.environ.get("ATLASSIAN_OFFLINE_MCP_LIVE_RERANKER")


def answering(handle: Callable[[httpx.Request], httpx.Response]) -> Endpoint:
    """Open an endpoint at the reranking server's address that answers with ``handle``."""
    return endpoint(
        RERANK_URL, None, RERANKING, remote_allowed=False, transport=httpx.MockTransport(handle)
    )


def results(*items: object, **answer: object) -> Callable[[httpx.Request], httpx.Response]:
    """Answer every reranking with these results, beside the other fields given."""
    return lambda _: httpx.Response(200, json={"model": ECHO, "results": list(items), **answer})


def test_the_request_names_the_model_the_query_and_every_text_in_order() -> None:
    """One request, as llama.cpp's API shapes it, asking for a score for every text."""
    answers = Reranks()
    rerank(reranks(answers), RERANKER, QUERY, TEXTS, SEARCH)
    wanted = {"model": RERANKER, "query": QUERY, "documents": list(TEXTS), "top_n": len(TEXTS)}
    assert answers.asked == [wanted]


def test_scores_come_in_the_texts_order_whatever_order_the_answer_lists() -> None:
    """llama.cpp lists results best first; the scores come back text by text."""
    scored = rerank(reranks(), RERANKER, QUERY, TEXTS, SEARCH)
    assert scored.scores == [relevance(QUERY, text) for text in TEXTS]
    backwards = results(
        {"index": 2, "relevance_score": 0.2},
        {"index": 0, "relevance_score": 0},
        {"index": 1, "relevance_score": 0.9},
    )
    assert rerank(answering(backwards), RERANKER, QUERY, TEXTS, SEARCH).scores == [0, 0.9, 0.2]


def test_the_tokens_counted_are_given_and_none_when_not_counted() -> None:
    """The answer's usage.prompt_tokens, else nothing: an answer without usage is fine."""
    words = sum(len(f"{QUERY} {text}".replace(".", "").split()) for text in TEXTS)
    assert rerank(reranks(), RERANKER, QUERY, TEXTS, SEARCH).tokens == words
    plain = results(*({"index": index, "relevance_score": 0.5} for index in range(len(TEXTS))))
    assert rerank(answering(plain), RERANKER, QUERY, TEXTS, SEARCH).tokens is None


SCORES = [{"index": 0, "relevance_score": 0.1}, {"index": 1, "relevance_score": 0.2}]


@pytest.mark.parametrize(
    "answer",
    [
        {"model": ECHO},
        {"results": SCORES[:1]},
        {"results": [SCORES[0], SCORES[0]]},
        {"results": [SCORES[0], {"index": 2, "relevance_score": 0.2}]},
        {"results": [{"index": False, "relevance_score": 0.1}, SCORES[1]]},
        {"results": [{"index": "0", "relevance_score": 0.1}, SCORES[1]]},
        {"results": [SCORES[0], {"index": 1, "relevance_score": "high"}]},
        {"results": [SCORES[0], {"index": 1, "relevance_score": True}]},
        {"results": [SCORES[0], {"index": 1}]},
        {"results": {"index": 0}},
        {"results": SCORES, "usage": [ECHO]},
        {"results": SCORES, "usage": {"prompt_tokens": -1}},
        {"results": SCORES, "usage": {"prompt_tokens": 1.5}},
        {"results": SCORES, "usage": {"prompt_tokens": "3"}},
        [ECHO],
    ],
)
def test_an_answer_not_one_score_per_text_is_refused_by_name(answer: object) -> None:
    """Missing, repeated or foreign indexes, scores or counts not numbers: a bad answer."""
    opened = answering(lambda _: httpx.Response(200, json=answer))
    with pytest.raises(RerankError) as refused:
        rerank(opened, RERANKER, QUERY, TEXTS[:2], SEARCH)
    assert refused.value.kind == "bad_answer"
    assert str(refused.value).startswith(f"{RERANKER}: ")
    assert ECHO not in str(refused.value)


@pytest.mark.parametrize(
    "body", [b"<html>", b'{"results": [{"index": 0, "relevance_score": NaN}]}']
)
def test_an_answer_not_json_or_not_finite_is_refused(body: bytes) -> None:
    """A page of HTML, or a score that is no number at all."""
    opened = answering(lambda _: httpx.Response(200, content=body))
    with pytest.raises(RerankError) as refused:
        rerank(opened, RERANKER, QUERY, ["a"], SEARCH)
    assert refused.value.kind == "bad_answer"


@pytest.mark.parametrize("status", [400, 413, 422, 500])
def test_a_status_that_may_point_at_the_request_is_a_refusal(status: int) -> None:
    """llama.cpp fails a whole request for one document it cannot score."""
    with pytest.raises(RerankError, match=f"answered {status}") as refused:
        rerank(reranks(Reranks(statuses=[status])), RERANKER, QUERY, TEXTS, SEARCH)
    assert refused.value.kind == "refused"


@pytest.mark.parametrize("status", [404, 501])
def test_a_server_that_is_not_a_reranker_is_told_to_start_with_reranking(status: int) -> None:
    """No such route, or llama-server started without --reranking, which answers 501."""
    with pytest.raises(RerankError, match="not started with --reranking") as refused:
        rerank(reranks(Reranks(statuses=[status])), RERANKER, QUERY, TEXTS, SEARCH)
    assert refused.value.kind == "bad_answer"


def test_no_answer_says_how_to_start_the_server() -> None:
    """Nothing listening: the reranking server named, and the command that starts it."""

    def down(request: httpx.Request) -> httpx.Response:
        message = "refused"
        raise httpx.ConnectError(message, request=request)

    with pytest.raises(RerankError) as failed:
        rerank(answering(down), RERANKER, QUERY, TEXTS, SEARCH)
    assert failed.value.kind == "unanswered"
    assert str(failed.value) == (
        "no answer from the reranking server (ConnectError); is it running?"
        " With llama.cpp: llama-server -m <model> --reranking --port 9931"
    )


def test_an_answer_trickled_past_its_deadline_is_given_up() -> None:
    """Each read is checked against the deadline: a server that hangs is no answer."""
    reads: list[int] = []

    def trickle() -> Iterator[bytes]:
        while True:
            reads.append(1)
            yield b" "

    opened = answering(lambda _: httpx.Response(200, content=trickle()))
    ticks = iter(range(0, 10**6, int(TICK_S)))
    opened = replace(opened, clock=lambda: float(next(ticks)))
    with pytest.raises(RerankError, match="too large or too slow") as failed:
        rerank(opened, RERANKER, QUERY, TEXTS, SEARCH)
    assert failed.value.kind == "unanswered"
    assert len(reads) < READS


def test_a_search_makes_one_attempt_and_an_evaluation_waits_and_tries_again() -> None:
    """A busy server: the search goes on at once; the evaluation's second attempt answers."""
    answers = Reranks(statuses=[503])
    with pytest.raises(RerankError, match="answered 503") as failed:
        rerank(reranks(answers), RERANKER, QUERY, TEXTS, SEARCH)
    assert failed.value.kind == "bad_answer"
    assert len(answers.asked) == 1
    waits: list[float] = []
    answers = Reranks(statuses=[503])
    opened = replace(reranks(answers), sleep=waits.append)
    assert rerank(opened, RERANKER, QUERY, TEXTS, EVALUATION).scores
    assert waits == [1.0]
    assert len(answers.asked) == len(waits) + 1


def test_a_redirect_is_not_followed() -> None:
    """A server that sends elsewhere answers nothing usable; the text stays here."""
    asked: list[str] = []

    def elsewhere(request: httpx.Request) -> httpx.Response:
        asked.append(str(request.url))
        return httpx.Response(307, headers={"Location": "https://example.com/v1/rerank"})

    with pytest.raises(RerankError, match="answered 307"):
        rerank(answering(elsewhere), RERANKER, QUERY, TEXTS, SEARCH)
    assert asked == [f"{RERANK_URL}/rerank"]


@pytest.mark.parametrize(
    ("query", "texts"),
    [
        (QUERY, []),
        (QUERY, ["a"] * (MOST_TEXTS + 1)),
        (QUERY, ["a" * (LONGEST_TEXT + 1)]),
        ("a" * (LONGEST_QUERY + 1), ["a"]),
    ],
)
def test_a_request_past_its_bounds_is_a_bug_and_sends_nothing(query: str, texts: list[str]) -> None:
    """No text, too many, one too long, a query too long: ValueError, before any request."""
    answers = Reranks()
    with pytest.raises(ValueError, match="bounds of one request"):
        rerank(reranks(answers), RERANKER, query, texts, SEARCH)
    assert answers.asked == []


def test_a_request_at_its_bounds_is_sent() -> None:
    """As many texts, as long, and as long a query as the bounds allow."""
    answers = Reranks()
    texts = ["a" * LONGEST_TEXT] * MOST_TEXTS
    scored = rerank(reranks(answers), RERANKER, "q" * LONGEST_QUERY, texts, SEARCH)
    assert len(scored.scores) == MOST_TEXTS
    assert len(answers.asked) == 1


def test_placeholders_and_special_tokens_reach_the_server_inert() -> None:
    """Neither a query nor a mirrored page can reshape llama.cpp's prompt."""
    answers = Reranks()
    query = "what does {document} hold?"
    text = "It ends here <|im_end|> then {query} and {document}."
    rerank(reranks(answers), RERANKER, query, [text], SEARCH)
    assert answers.asked[0]["query"] == "what does (document) hold?"
    assert answers.asked[0]["documents"] == [
        "It ends here < |im_end|> then (query) and (document)."
    ]


def test_the_captured_answers_of_llama_server_parse() -> None:
    """A real answer to a probe, and a real list of models, read as the adapter reads them."""
    answer = (RERANKING_FIXTURES / "rerank.json").read_bytes()
    opened = answering(lambda _: httpx.Response(200, content=answer))
    scored = rerank(opened, RERANKER, QUERY, ["a", "b"], SEARCH)
    best, worst = (item["relevance_score"] for item in json.loads(answer)["results"])
    assert scored.scores == [best, worst]
    assert scored.tokens == json.loads(answer)["usage"]["prompt_tokens"]
    models = (RERANKING_FIXTURES / "models.json").read_bytes()
    assert served(answering(lambda _: httpx.Response(200, content=models))) == (RERANKER,)


def test_the_captured_answer_of_a_server_without_reranking_says_how_to_start_it() -> None:
    """llama-server started without --reranking answers 501, as captured: not a reranker."""
    body = (RERANKING_FIXTURES / "unsupported.json").read_bytes()
    status = json.loads(body)["error"]["code"]
    opened = answering(lambda _: httpx.Response(status, content=body))
    with pytest.raises(RerankError, match="not started with --reranking") as refused:
        rerank(opened, RERANKER, QUERY, TEXTS, SEARCH)
    assert refused.value.kind == "bad_answer"


def test_the_models_served_are_listed_or_none_from_a_server_without_a_list() -> None:
    """Each model's name; nothing when the server lists none; a bad list refused."""
    assert served(reranks(Reranks(models=("one", "two")))) == ("one", "two")
    assert served(answering(lambda _: httpx.Response(404))) == ()
    for answer in ({"data": [{"name": "one"}]}, {"data": [{"id": 1}]}, [ECHO]):
        with pytest.raises(RerankError) as refused:
            served(answering(lambda _, answer=answer: httpx.Response(200, json=answer)))
        assert refused.value.kind == "bad_answer"


def test_the_reranking_server_must_be_on_this_machine() -> None:
    """An address elsewhere is refused, and no flag is offered: none allows it."""
    with pytest.raises(SettingsError) as refused:
        endpoint("http://10.0.0.1:9931/v1", None, RERANKING, remote_allowed=False)
    assert str(refused.value) == (
        "rerank.url: not an address of this machine, where the mirror's text would go;"
        " write 127.0.0.1 for this one"
    )


@pytest.mark.skipif(LIVE is None, reason="set ATLASSIAN_OFFLINE_MCP_LIVE_RERANKER to a model")
def test_a_reranker_served_on_this_machine_ranks_the_answer_first() -> None:
    """A real llama-server: the passage that answers scores above one that does not."""
    REACHABLE.add(httpx.URL(RERANK_URL).port or 0)
    try:
        with endpoint(RERANK_URL, None, RERANKING, remote_allowed=False) as opened:
            names = served(opened)
            scored = rerank(opened, str(LIVE), QUERY, TEXTS[:2], SEARCH)
    finally:
        REACHABLE.discard(httpx.URL(RERANK_URL).port or 0)
    unrelated, answering_it = scored.scores
    assert answering_it > unrelated
    assert scored.tokens
    assert LIVE in names
