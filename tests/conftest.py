"""Every test runs without the network, and without the settings' own environment.

An audit hook refuses any connection, and any name looked up, other than a loopback
address and a port in ``tests.endpoint.REACHABLE``, so that no test reaches the network,
or a real Ollama on this machine, by mistake. The settings' variables of the user's
environment, and OpenTelemetry's, are removed for each test, which sets those it needs.
"""

from __future__ import annotations

import ipaddress
import os
import sys
from typing import TYPE_CHECKING

import pytest

from tests.endpoint import REACHABLE

if TYPE_CHECKING:
    from _pytest.monkeypatch import MonkeyPatch

PREFIX = "ATLASSIAN_OFFLINE_MCP_"
# OpenTelemetry's variables, two of which the settings read, and its SDK others.
OTEL = "OTEL_"


def guard(event: str, arguments: tuple[object, ...]) -> None:
    """Refuse a connection or a look-up other than to a port that a test opened here."""
    if event == "socket.connect":
        place = arguments[1]
    elif event == "socket.getaddrinfo":
        place = arguments[:2]
    else:
        return
    if not isinstance(place, tuple):
        return  # a Unix socket's path: not the network
    try:
        here = ipaddress.ip_address(str(place[0])).is_loopback
    except ValueError:
        here = False
    if not here or place[1] not in REACHABLE:
        message = f"a test reached for the network: {event} {place!r}"
        raise RuntimeError(message)


sys.addaudithook(guard)


@pytest.fixture(autouse=True)
def settings_environment(monkeypatch: MonkeyPatch) -> None:
    """Remove the variables that the settings read, so that none of the user's reaches a test.

    pydantic-settings reads its own without regard to case; OpenTelemetry's are read as
    written.
    """
    for name in [
        name
        for name in os.environ
        if name.lower().startswith(PREFIX.lower()) or name.startswith(OTEL)
    ]:
        monkeypatch.delenv(name)
