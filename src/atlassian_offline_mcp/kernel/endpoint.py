"""An embedding endpoint's address: its host, and whether it is this machine.

Standard library only, and light, since the settings and the command's declarations
check an address alike.
"""

from __future__ import annotations

import ipaddress
from urllib.parse import urlsplit


def endpoint_host(value: object) -> str | None:
    """Give the host of an embedding endpoint's address, or None when it is not one.

    An address is http or https, with a host and a valid port if any, and no user,
    query or fragment.
    """
    if not isinstance(value, str):
        return None
    try:
        parts = urlsplit(value)
        usable = (
            parts.scheme in {"http", "https"}
            and bool(parts.hostname)
            and "@" not in parts.netloc
            and not parts.query
            and not parts.fragment
            and parts.port != 0
        )
    except ValueError:  # an unclosed [ in the host, or a port that is not a number
        return None
    return parts.hostname if usable else None


def loopback(url: str) -> bool:
    """Say whether an endpoint's address is a literal address of this machine.

    A name, ``localhost`` included, is not: what it resolves to is the resolver's to say.
    """
    try:
        return ipaddress.ip_address(endpoint_host(url) or "").is_loopback
    except ValueError:
        return False


def refused_endpoint(url: str, *, remote_allowed: bool) -> str | None:
    """Say why a run may not send the mirror's text to an endpoint, or None when it may.

    An address that is not a literal one of this machine needs the run's word,
    ``remote_allowed``, and https even then.
    """
    if loopback(url):
        return None
    if not remote_allowed:
        return (
            "embedding_url: not an address of this machine, where the mirror's text would"
            " go; write 127.0.0.1 for this one, or pass --allow-remote-embeddings"
        )
    if not url.startswith("https://"):
        return "embedding_url: an endpoint off this machine is reached over https only"
    return None
