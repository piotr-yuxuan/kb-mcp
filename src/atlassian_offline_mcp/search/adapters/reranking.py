"""Reranking by a cross-encoder behind llama.cpp's ``llama-server`` on this machine.

Only this module knows the API: the request and answer that ``llama-server``, started
with ``--reranking``, shares with Jina's and Cohere's rerank APIs, and the quirks of its
prompt. The rest of the code sees scores: one for each text, in the order given, the
higher the more relevant; only their order means anything.

The mirror's text never leaves this machine: the server's address is a literal address
of this machine, which ``model_api.endpoint`` checks again, ``RERANKING`` allowing no
other.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

import httpx

from atlassian_offline_mcp.kernel.reranking import LONGEST_QUERY, LONGEST_TEXT, MOST_TEXTS
from atlassian_offline_mcp.search.adapters.model_api import WAITS_S, Bounds, ModelError, send

if TYPE_CHECKING:
    from collections.abc import Sequence

    from atlassian_offline_mcp.search.adapters.model_api import Endpoint

# A search makes one attempt: a server that hangs costs one deadline, and the search goes
# on in its own order. An evaluation, which stops at a failure, tries again, as the
# embeddings of documents do.
SEARCH = Bounds(30, 1)
EVALUATION = Bounds(300, len(WAITS_S) + 1)
# Statuses that may point at what was sent: llama.cpp fails a whole request for one
# document that it cannot score.
REFUSING = frozenset({400, 413, 422, 500})
# Statuses of a server that is not a reranker: no such route, or ``llama-server`` started
# without ``--reranking``.
NOT_A_RERANKER = frozenset({404, 501})
# llama.cpp fills its prompt by plain replacement of these placeholders, and reads
# special tokens in what it is sent, so that a query or a text holding one would reshape
# the prompt: each is written otherwise.
INERT = (("<|", "< |"), ("{query}", "(query)"), ("{document}", "(document)"))

type Kind = Literal["unanswered", "refused", "bad_answer"]


class RerankError(ModelError):
    """Scores that the server did not give, and the kind of failure, which callers read."""

    def __init__(self, message: str, kind: Kind) -> None:
        """Say why, and whether no answer came, the request was refused, or the answer was amiss."""
        super().__init__(message)
        self.kind: Kind = kind


@dataclass(frozen=True)
class Reranked:
    """What the server gave for texts: a score each, in their order, and the tokens it counted."""

    scores: list[float]
    tokens: int | None  # the answer's usage.prompt_tokens, None when it says none


def inert(text: str) -> str:
    """Write a text so that llama.cpp's prompt keeps it as text."""
    for found, written in INERT:
        text = text.replace(found, written)
    return text


def rerank(
    endpoint: Endpoint, model: str, query: str, texts: Sequence[str], bounds: Bounds
) -> Reranked:
    """Score each text's relevance to the query, in the order given.

    Callers keep to the bounds of one request: from 1 to MOST_TEXTS texts, none longer
    than LONGEST_TEXT, a query of at most LONGEST_QUERY; breaking one is a bug, a
    ValueError, and nothing is sent. Raises RerankError otherwise, of kind
    ``unanswered`` when no attempt got a whole answer, ``refused`` for a status that may
    point at what was sent, and ``bad_answer`` for anything else; its message names the
    model and the error, never the answer, which echoes the query.
    """
    longest = max(map(len, texts), default=0)
    if not 0 < len(texts) <= MOST_TEXTS or longest > LONGEST_TEXT or len(query) > LONGEST_QUERY:
        message = (
            f"a reranking of {len(texts)} texts of up to {longest} characters, for a query"
            f" of {len(query)}, passes the bounds of one request"
        )
        raise ValueError(message)
    documents = [inert(text) for text in texts]
    asked = {"model": model, "query": inert(query), "documents": documents, "top_n": len(texts)}
    try:
        status, body = send(endpoint, "POST", "rerank", bounds, asked)
    except ModelError as error:
        raise RerankError(str(error), "unanswered") from None
    if status in NOT_A_RERANKER:
        message = (
            f"{model}: not a reranker at this address, or a server not started with"
            f" --reranking ({status})"
        )
        raise RerankError(message, "bad_answer")
    if status != httpx.codes.OK:
        message = f"{model}: the reranking server answered {status}"
        raise RerankError(message, "refused" if status in REFUSING else "bad_answer")
    try:
        answer = json.loads(body)
        found = sorted((item["index"], item["relevance_score"]) for item in answer["results"])
        usage = answer.get("usage")
    except (ValueError, KeyError, TypeError, RecursionError) as error:
        message = f"{model}: the reranking server's answer is not scores ({type(error).__name__})"
        raise RerankError(message, "bad_answer") from None
    tokens = usage.get("prompt_tokens") if type(usage) is dict else None
    if (
        [index for index, _ in found] != list(range(len(texts)))
        or not all(type(index) is int for index, _ in found)
        or not all(type(score) in {int, float} and math.isfinite(score) for _, score in found)
        or (usage is not None and type(usage) is not dict)
        or (tokens is not None and (type(tokens) is not int or tokens < 0))
    ):
        message = f"{model}: the reranking server's answer is not one score per text"
        raise RerankError(message, "bad_answer")
    return Reranked([float(score) for _, score in found], tokens)


def served(endpoint: Endpoint) -> tuple[str, ...]:
    """Give the names of the models that the server lists; none from one that lists none.

    A single-model ``llama-server`` scores with its one model whatever a request names,
    so that a caller compares these with the name it sends. Raises RerankError when no
    answer comes, or when the list cannot be read.
    """
    try:
        status, body = send(endpoint, "GET", "models", SEARCH)
    except ModelError as error:
        raise RerankError(str(error), "unanswered") from None
    if status != httpx.codes.OK:
        return ()
    try:
        names = tuple(row["id"] for row in json.loads(body)["data"])
    except (ValueError, KeyError, TypeError, RecursionError) as error:
        message = f"the reranking server's list of models is not one ({type(error).__name__})"
        raise RerankError(message, "bad_answer") from None
    if not all(type(name) is str for name in names):
        message = "the reranking server's list of models names a model by no string"
        raise RerankError(message, "bad_answer")
    return names
