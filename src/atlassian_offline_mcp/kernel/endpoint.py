"""A model server's address: its host, whether it is this machine, and the run's rule.

Standard library only, and light, since the settings and the command's declarations
check an address alike.
"""

from __future__ import annotations

import ipaddress
from dataclasses import dataclass
from urllib.parse import urlsplit


@dataclass(frozen=True)
class Service:
    """A server that a run sends the mirror's text to, as the messages about it name it."""

    name: str  # what it is, as a sentence names it
    setting: str  # the setting that holds its address
    flag: str  # the option that lets a run reach one off this machine
    start: str  # how to start it, said when it does not answer


EMBEDDINGS = Service(
    "the embedding endpoint",
    "embedding_url",
    "--allow-remote-embeddings",
    "With Ollama: ollama serve",
)


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


def refused_endpoint(url: str, service: Service, *, remote_allowed: bool) -> str | None:
    """Say why a run may not send the mirror's text to a service, or None when it may.

    An address that is not a literal one of this machine needs the run's word,
    ``remote_allowed``, and https even then. The message names the service's setting.
    """
    if loopback(url):
        return None
    if not remote_allowed:
        return (
            f"{service.setting}: not an address of this machine, where the mirror's text"
            f" would go; write 127.0.0.1 for this one, or pass {service.flag}"
        )
    if not url.startswith("https://"):
        return f"{service.setting}: an endpoint off this machine is reached over https only"
    return None
