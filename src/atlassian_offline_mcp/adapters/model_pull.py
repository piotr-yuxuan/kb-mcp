"""Pulling a model's pinned files into the models folder: the only code that downloads one.

An import contract keeps the server, the index and the evaluation from importing this
module: they read what it pulled, and cannot reach the network for a model.
"""

from __future__ import annotations

import hashlib
import os
import ssl
import tempfile
import time
from pathlib import Path
from typing import TYPE_CHECKING

import httpx
import truststore

from atlassian_offline_mcp.adapters.embedding import CHUNK_BYTES, ModelError, matches
from atlassian_offline_mcp.adapters.http import SiteError, refuse_plain_http

if TYPE_CHECKING:
    from collections.abc import Iterator

    from atlassian_offline_mcp.adapters.embedding import File, Model

HUB = "https://huggingface.co"
# How long one file may take to arrive, in seconds; how long between two reads.
FILE_DEADLINE_S = 3600
READ_TIMEOUT_S = 60
MAX_REDIRECTS = 5


def download_client(transport: httpx.BaseTransport | None = None) -> httpx.Client:
    """Return a client for the hub: the OS trust store, https only, few redirects.

    The hub sends files from a content network, hence redirects; the proxy, if any,
    comes from the environment. ``transport`` replaces the network, for tests.
    """
    return httpx.Client(
        verify=truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT),
        timeout=httpx.Timeout(READ_TIMEOUT_S),
        follow_redirects=True,
        max_redirects=MAX_REDIRECTS,
        event_hooks={"request": [refuse_plain_http]},
        transport=transport,
    )


def place(model: Model, file: File, target: Path, chunks: Iterator[bytes]) -> None:
    """Write a file from its chunks beside its place, and rename it there once it matches.

    Raises ModelError when it grows past its pinned size, takes too long, or does not
    match its SHA-256; nothing of it is left then.
    """
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix=".pull-", dir=target.parent)
    temporary = Path(name)
    try:
        digest, size = hashlib.sha256(), 0
        deadline = time.monotonic() + FILE_DEADLINE_S
        with os.fdopen(descriptor, "wb") as out:
            for chunk in chunks:
                size += len(chunk)
                if size > file.size or time.monotonic() > deadline:
                    message = f"{model.name}: {file.path}: larger or slower than pinned"
                    raise ModelError(message)
                digest.update(chunk)
                out.write(chunk)
        if size != file.size or digest.hexdigest() != file.sha256:
            message = f"{model.name}: {file.path}: not the file pinned (size or SHA-256)"
            raise ModelError(message)
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)


def pull(model: Model, models: Path, client: httpx.Client) -> list[str]:
    """Download the files of a model that its folder lacks; return the paths fetched.

    A file in place is kept when it matches its pin, and fetched again otherwise. One
    attempt per file: a file that fails is named, and those done stay for the next run.
    """
    fetched: list[str] = []
    for file in model.files:
        target = models / model.name / file.path
        if matches(target, file):
            continue
        address = f"{HUB}/{model.repository}/resolve/{model.revision}/{file.path}"
        try:
            with client.stream("GET", address) as response:
                if response.status_code != httpx.codes.OK:
                    message = f"{model.name}: {file.path}: the hub answered {response.status_code}"
                    raise ModelError(message)
                # Every read as it comes, so that a file trickled in is given up on time.
                place(model, file, target, response.iter_bytes())
        except (httpx.HTTPError, SiteError) as error:
            message = f"{model.name}: {file.path}: {type(error).__name__}"
            raise ModelError(message) from error
        fetched.append(file.path)
    return fetched


def copy_from(model: Model, models: Path, source: Path) -> list[str]:
    """Take the files of a model from a folder laid out as its repository, checked as pulled.

    For a machine that cannot reach the hub; return the paths copied.
    """
    copied: list[str] = []
    for file in model.files:
        target = models / model.name / file.path
        if matches(target, file):
            continue
        origin = source / file.path
        if not origin.is_file():
            message = f"{model.name}: {file.path}: not in {source}"
            raise ModelError(message)
        with origin.open("rb") as stream:
            place(model, file, target, iter(lambda: stream.read(CHUNK_BYTES), b""))
        copied.append(file.path)
    return copied
