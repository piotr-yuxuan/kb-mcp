"""``model check``: check that the embedding endpoint answers with a model, or say what to run.

It never downloads a model: with Ollama, ``ollama pull`` does.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from typing import TYPE_CHECKING

from atlassian_offline_mcp.cli.commands._embedding import open_endpoint, prefixes_said
from atlassian_offline_mcp.kernel.exit_status import ExitStatus
from atlassian_offline_mcp.search.adapters.embedding import ModelError, connect

if TYPE_CHECKING:
    import argparse

    from atlassian_offline_mcp.config.domain.settings import Loaded
    from atlassian_offline_mcp.kernel.output import Summary

# Characters of a digest shown, as Ollama shows them.
SHORT = 12


@dataclass(frozen=True)
class Ready:
    """A model that the endpoint embeds with: its name, its dimensions, the endpoint, its digest.

    The digest is empty when the endpoint reports none.
    """

    name: str
    dimensions: int
    url: str
    digest: str


def run(arguments: argparse.Namespace, loaded: Loaded) -> tuple[ExitStatus, Ready | None]:
    """Check; exit 1 when the endpoint or the model is not ready."""
    settings = loaded.settings
    name = arguments.name or settings.model
    with open_endpoint(arguments, settings) as opened:
        try:
            embedder = connect(opened, name)
        except ModelError as error:
            sys.stderr.write(f"not ready: {error}\n")
            return ExitStatus.FAILED, None
    return ExitStatus.OK, Ready(name, embedder.dimensions, settings.embedding_url, embedder.digest)


def text(ready: Ready, _summary: Summary) -> str:
    """Write the dimensions, the endpoint, the short digest, and whether prefixes are known."""
    return (
        f"{ready.name}: {ready.dimensions} dimensions, from {ready.url};"
        f" digest {ready.digest[:SHORT] or 'not reported'}; {prefixes_said(ready.name)}\n"
    )
