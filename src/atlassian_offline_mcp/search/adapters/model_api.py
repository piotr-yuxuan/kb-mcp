"""What clients of model servers share: the rule of this machine, bounds and errors.

``endpoint`` is the only way to a client, and refuses an address that the run may not
reach; ``send`` makes a request within its bounds.
"""

from __future__ import annotations

import ssl
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Self

import httpx
import truststore
from opentelemetry import metrics

from atlassian_offline_mcp.config.domain.settings import SettingsError
from atlassian_offline_mcp.kernel.endpoint import loopback, refused_endpoint
from atlassian_offline_mcp.observability.adapters.http import Recorded

if TYPE_CHECKING:
    from collections.abc import Callable

    from atlassian_offline_mcp.kernel.endpoint import Service

MAX_ANSWER_BYTES = 64 * 1024 * 1024
# The buckets of an operation's duration, in seconds, that the GenAI conventions advise.
BUCKETS_S = (0.01, 0.02, 0.04, 0.08, 0.16, 0.32, 0.64, 1.28, 2.56, 5.12, 10.24, 20.48, 40.96, 81.92)
# How long each operation of a model server took, an embedding or a reranking, its
# attempts and waits included, as the GenAI conventions measure an operation.
OPERATION_DURATION = metrics.get_meter(__name__).create_histogram(
    "gen_ai.client.operation.duration",
    unit="s",
    description="GenAI operation duration.",
    explicit_bucket_boundaries_advisory=BUCKETS_S,
)
# The tokens that each answer of a model server counted, in the buckets that the GenAI
# conventions advise, when the server counts them.
TOKEN_BUCKETS = tuple(4**power for power in range(14))  # 1 to 67,108,864
TOKEN_USAGE = metrics.get_meter(__name__).create_histogram(
    "gen_ai.client.token.usage",
    unit="{token}",
    description="Number of input and output tokens used.",
    explicit_bucket_boundaries_advisory=TOKEN_BUCKETS,
)
# Statuses worth another attempt: the endpoint busy, or failing for a while.
RETRIED = frozenset({429, 500, 502, 503, 504})
# Seconds waited before the second attempt, and before the third.
WAITS_S = (1.0, 4.0)


@dataclass(frozen=True)
class Bounds:
    """How long one attempt may take, in seconds, and how many attempts a request gets."""

    deadline_s: float
    attempts: int


class ModelError(Exception):
    """An answer that a model server did not give; the message says why and what to do."""


@dataclass(frozen=True)
class Endpoint:
    """An open client to a model server, the service it is, what this run allows, its clock.

    Closed after use, as a context manager.
    """

    http: httpx.Client
    service: Service
    remote_allowed: bool
    sleep: Callable[[float], None] = field(default=time.sleep)
    clock: Callable[[], float] = field(default=time.monotonic)

    def __enter__(self) -> Self:
        """Use the endpoint."""
        return self

    def __exit__(self, *_: object) -> None:
        """Close its client."""
        self.http.close()


def endpoint(
    url: str,
    key: str | None,
    service: Service,
    *,
    remote_allowed: bool,
    transport: httpx.BaseTransport | None = None,
) -> Endpoint:
    """Open a client to the service's API at ``url``, with ``key`` as its bearer token, if any.

    Raises SettingsError for an address that is not a literal address of this machine,
    unless ``remote_allowed``, and for plain http to one even then. On this machine the
    environment's proxies are ignored, since one would carry the text away; redirects
    are never followed. Each request sent is observed, as ``Recorded`` has it.
    ``transport`` replaces the network, for tests.
    """
    refusal = refused_endpoint(url, service, remote_allowed=remote_allowed)
    if refusal is not None:
        raise SettingsError(refusal)
    here = loopback(url)
    network = httpx.Client(
        verify=truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT),
        trust_env=not here,
        transport=transport,
    )
    http = httpx.Client(
        base_url=url,
        headers={"Authorization": f"Bearer {key}"} if key else {},
        follow_redirects=False,
        transport=Recorded(network, httpx.URL(url).host),
    )
    return Endpoint(http, service, remote_allowed)


def send(
    endpoint: Endpoint, method: str, url: str, bounds: Bounds, payload: object = None
) -> tuple[int, bytes]:
    """Make a request within its bounds; give the status and body of its last answer.

    httpx bounds each phase of an attempt by the deadline (connecting, sending, the
    answer's first byte), and the body must end by the deadline itself, checked at every
    read, within MAX_ANSWER_BYTES. A transport error, a passed deadline, an answer too
    large or a status of RETRIED is tried again, after a wait, while attempts remain.
    Raises ModelError when no attempt got a whole answer.
    """
    reason = "no attempt"
    for attempt in range(bounds.attempts):
        if attempt:
            endpoint.sleep(WAITS_S[attempt - 1])
        deadline = endpoint.clock() + bounds.deadline_s
        answer = None
        try:
            with endpoint.http.stream(
                method, url, json=payload, timeout=bounds.deadline_s
            ) as response:
                body = bytearray()
                for chunk in response.iter_bytes():
                    body += chunk
                    if len(body) > MAX_ANSWER_BYTES or endpoint.clock() > deadline:
                        reason = "an answer too large or too slow"
                        break
                else:
                    answer = (response.status_code, bytes(body))
        except httpx.HTTPError as error:
            reason = type(error).__name__
        if answer is not None and (answer[0] not in RETRIED or attempt + 1 == bounds.attempts):
            return answer
    message = (
        f"no answer from {endpoint.service.name} ({reason}); is it running?"
        f" {endpoint.service.start}"
    )
    raise ModelError(message)
