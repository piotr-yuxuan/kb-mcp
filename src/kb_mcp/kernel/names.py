"""What every context shares, the parser too: names, rules, choices, bounds; standard library."""

from __future__ import annotations

import ipaddress
import re
import unicodedata
from dataclasses import dataclass
from enum import IntEnum
from typing import TYPE_CHECKING, Literal
from urllib.parse import urlsplit

if TYPE_CHECKING:
    from collections.abc import Iterable

# The program's name, as pyproject.toml names its script: its command, its log folder,
# and the name by which MCP clients know its server.
PROGRAM = "kb-mcp"
# Each setting's environment variable: the prefix, then its path in capitals, joined.
PREFIX = "KB_MCP_"
NESTING = "__"
# The mirror's folder of the files that Confluence's and Jira's documents attach,
# docs/assets/: no document is under it, and no source's folder may be it.
ASSETS = "assets"
# The raw store's folder of the files that documents attach, beside each source's.
BLOBS = "blobs"
# A source's name, and a type of its documents, as the front matter names them; no
# source takes ``assets`` nor ``blobs``, folders beside the sources', nor the schemes of
# a web address, which a link to a source's document would read as.
SOURCE_NAME = re.compile(r"[a-z][a-z0-9]*")
RESERVED = (ASSETS, BLOBS, "http", "https")
# The setting of each source's table that names its connector.
CONNECTOR = "connector"
# A run's id, as a run makes it and names its record's folder: 16 lower-case hex digits.
RUN_ID = re.compile(r"[0-9a-f]{16}")
TYPE_NAME = re.compile(r"[a-z]+")
# An id names a folder of the raw store, so it must be one safe path part.
IDENTIFIER = re.compile(r"[A-Za-z0-9_-]+")
# A revision's name, whichever source names it: one token, which each source's rule
# narrows.
REVISION_NAME = re.compile(r"[A-Za-z0-9._-]+")
# A document id, as a parent and a link name a document: its source, a colon, its id.
DOCUMENT_ID = re.compile(rf"{SOURCE_NAME.pattern}:{IDENTIFIER.pattern}")
# A scope, as a document names the one that holds it: its scope type, a colon, its key,
# which each scope type's rule narrows.
SCOPE = re.compile(r"[a-z]+:[~A-Za-z0-9_-]+")
ISSUE_KEY = re.compile(r"[A-Z][A-Z0-9_]+-[0-9]+")
# A mention's identity: its issuer, a colon, then the value that the issuer gave, which
# may hold colons itself.
IDENTITY = re.compile(r"[a-z][a-z0-9-]*:.+")
# The issuer of the identities of every Atlassian cloud site, Confluence's and Jira's.
ATLASSIAN_ISSUER = "atlassian"
# The work log's one scope type, read in place, whose one scope is the whole source.
WORKLOG_SCOPE_TYPE = "folder"
# An embedding model's name, as the endpoint names it: the settings and the command
# line check it alike.
MODEL_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}")
# Characters a token counts for, the same for every model: cuts are made in characters,
# since neither the OpenAI API nor Ollama's tokenises and no tokeniser is a dependency.
CHARACTERS_PER_TOKEN = 4
# The chunkings that an index's chunks may be cut by, the control first.
type Chunking = Literal["sections", "windows", "section-paths", "small-to-big"]
CHUNKINGS: tuple[Chunking, ...] = ("sections", "windows", "section-paths", "small-to-big")
# Every tool, in the order that the server lists them: what ``serve`` serves by default.
type Tool = Literal["ask", "search", "read", "browse", "status"]
TOOLS: tuple[Tool, ...] = ("ask", "search", "read", "browse", "status")
# The most texts one reranking request scores: the deepest reranking a search may ask.
MOST_TEXTS = 64
# The longest text scored: a title and a heading of 150 characters each, a line each,
# then 1,200 characters of a section's body (a 300-token window).
LONGEST_TEXT = 1_502
# The longest query scored: the bound that ``search`` and ``ask`` put on one, from here.
LONGEST_QUERY = 500
# The depths that a reranking may have: from two documents, the fewest with an order to
# change, to the most that one request scores.
DEPTHS = range(2, MOST_TEXTS + 1)
# The user's bound on a search with reranking, at the 95th percentile on the user's
# machine ("Happy to wait 5s"), and the depths that eval-rerank measures by default.
BOUND_S = 5.0
BAR_DEPTHS = (10, 20, 30, 50)
# The levels of what a run says on stderr, as --log-level names them, least severe first;
# how much of a result is written on stdout; and how, as lines or as one JSON document.
type Level = Literal["debug", "info", "warning", "error"]
LEVELS: tuple[Level, ...] = ("debug", "info", "warning", "error")
type Detail = Literal["short", "detailed"]
DETAILS: tuple[Detail, ...] = ("short", "detailed")
type Format = Literal["text", "json"]
FORMATS: tuple[Format, ...] = ("text", "json")
# A moment in a file's name, a run's start in its log file's or an evaluation's in its
# results': UTC, to the second.
STAMP = "%Y%m%dT%H%M%SZ"
# How a unit of a run ended: done; failed; the sign-in no longer holding; not run, as a
# unit that a dry run leaves alone or that an interruption reached before it started; or
# interrupted.
type Ending = Literal["done", "failed", "sign in again", "not run", "interrupted"]
SLUG_LENGTH = 60
NOT_SLUG = re.compile(r"[^a-z0-9]+")


class RefusedError(ValueError):
    """A value that a domain type refuses; the message names the field, never the value."""


class StoreBusyError(RuntimeError):
    """Another run holds the lock of a store that this one would write."""


def require(pattern: re.Pattern[str], value: str, name: str) -> None:
    """Refuse a value that does not match its rule, naming the field and the rule."""
    if not pattern.fullmatch(value):
        message = f"{name}: does not match {pattern.pattern}"
        raise RefusedError(message)


def slug(title: str) -> str:
    """Name a title in a path: its base letters lowered and digits, runs of others one ``-``."""
    decomposed = unicodedata.normalize("NFKD", title).lower()
    kept = "".join(char for char in decomposed if not unicodedata.combining(char))
    return NOT_SLUG.sub("-", kept).strip("-")[:SLUG_LENGTH].rstrip("-")


class ExitStatus(IntEnum):
    """How a run ended, as the shell reads it; ``MEANINGS`` says what each means."""

    OK = 0
    FAILED = 1
    REFUSED = 2
    SIGN_IN_AGAIN = 3
    INTERRUPTED = 130


# What each status means, as the program's --help lists them.
MEANINGS = {
    ExitStatus.OK: "done",
    ExitStatus.FAILED: "something failed (a document, a file, a check, the endpoint), or the"
    " question was declined",
    ExitStatus.REFUSED: "refused before acting: settings, options or input, or no terminal to"
    " ask on",
    ExitStatus.SIGN_IN_AGAIN: "sign in again: no session saved, it no longer holds, or the"
    " site refused the API token",
    ExitStatus.INTERRUPTED: "stopped by Ctrl-C",
}
# The exit status of each ending, a unit's or the run's own; their numbers rank them, most
# severe highest: interrupted, then sign in again, then failed; done and not run are 0.
ENDED: dict[Ending, ExitStatus] = {
    "done": ExitStatus.OK,
    "not run": ExitStatus.OK,
    "failed": ExitStatus.FAILED,
    "sign in again": ExitStatus.SIGN_IN_AGAIN,
    "interrupted": ExitStatus.INTERRUPTED,
}


def folded(endings: Iterable[Ending]) -> ExitStatus:
    """Give the exit status of the most severe of these endings; OK for none."""
    return max((ENDED[ending] for ending in endings), default=ExitStatus.OK)


@dataclass(frozen=True)
class Service:
    """A server that a run sends text to: on this machine, or off it over https by its ``flag``."""

    name: str  # what it is, as a sentence names it
    setting: str  # the setting that holds its address
    sends: str  # what it is sent, as a refusal names it
    flag: str | None  # the option that lets a run reach one off this machine; None: none may
    start: str = ""  # how to start it, said when it does not answer
    form: str | None = None  # what its address must look like, as a refusal says it

    def __post_init__(self) -> None:
        """Refuse a form beside a flag: the form asks for http, and off this machine, https."""
        if self.form and self.flag:
            message = f"{self.name}: a form, or a flag, not both"
            raise ValueError(message)


EMBEDDINGS = Service(
    name="the embedding endpoint",
    setting="embedding_url",
    sends="the mirror's text",
    flag="--allow-remote-embeddings",
    start="With Ollama: ollama serve",
)
# Local only, by the user's word: no flag lets a run rerank off this machine.
RERANKING = Service(
    name="the reranking server",
    setting="rerank.url",
    sends="the mirror's text",
    flag=None,
    start="With llama.cpp: llama-server -m <model> --reranking --port 9931",
)
# Local only, since what a run records holds titles, queries and names of persons.
TELEMETRY = Service(
    name="the telemetry endpoint",
    setting="telemetry.endpoint",
    sends="what a run records",
    flag=None,
    form="an http address with a port and no path, such as http://127.0.0.1:4318",
)


def endpoint_host(value: object) -> str | None:
    """Give the host of an http(s) address, its port valid, no user, query or fragment; or None."""
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
    """Say whether an address's host is a literal address of this machine; a name is not."""
    try:
        return ipaddress.ip_address(endpoint_host(url) or "").is_loopback
    except ValueError:
        return False


def refused_endpoint(url: str, service: Service, *, remote_allowed: bool) -> str | None:
    """Say why a run may not send text to a service at ``url`` by its rule, naming no setting."""
    if service.form:
        parts = urlsplit(url) if endpoint_host(url) else None
        if not parts or parts.scheme != "http" or parts.port is None or parts.path not in {"", "/"}:
            return f"not {service.form}"
    if loopback(url):
        return None
    if not (remote_allowed and service.flag):
        otherwise = f", or pass {service.flag}" if service.flag else ""
        return (
            f"not an address of this machine, where {service.sends} would go;"
            f" write 127.0.0.1 for this one{otherwise}"
        )
    if not url.startswith("https://"):
        return "an endpoint off this machine is reached over https only"
    return None
