"""Every test runs without the network: only ports of this machine that a test opened.

An audit hook refuses any connection, and any name looked up, other than a loopback
address and a port in ``tests.endpoint.REACHABLE``, so that no test reaches the network,
or a real Ollama on this machine, by mistake.
"""

from __future__ import annotations

import ipaddress
import sys

from tests.endpoint import REACHABLE


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
