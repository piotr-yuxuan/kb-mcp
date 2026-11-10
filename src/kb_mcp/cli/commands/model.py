"""``model check``: check that the embedding endpoint answers with a model, or say what to run.

It never downloads a model: with Ollama, ``ollama pull`` does.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

from kb_mcp.cli.commands._embedding import open_endpoint
from kb_mcp.kernel.exit_status import ExitStatus
from kb_mcp.kernel.record import Record
from kb_mcp.search.adapters.embedding import connect
from kb_mcp.search.adapters.model_api import ModelError
from kb_mcp.search.app.indexing import prefixes_said

if TYPE_CHECKING:
    import argparse

    from kb_mcp.config.domain.settings import Loaded
    from kb_mcp.kernel.output import Detail

# Characters of a digest shown, as Ollama shows them.
SHORT = 12


class Ready(Record):
    """A model that the endpoint embeds with: its name, its dimensions, the endpoint, its digest.

    The digest is empty when the endpoint reports none.
    """

    name: str
    dimensions: int
    url: str
    digest: str


def run(arguments: argparse.Namespace, loaded: Loaded) -> tuple[ExitStatus, Ready | None]:
    """Check; exit 1 when the endpoint or the model is not ready, an error."""
    settings = loaded.settings
    name = arguments.name or settings.model
    with open_endpoint(arguments, settings) as opened:
        try:
            embedder = connect(opened, name)
        except ModelError as error:
            structlog.get_logger().error("model.not_ready", reason=str(error))
            return ExitStatus.FAILED, None
    return ExitStatus.OK, Ready(
        name=name,
        dimensions=embedder.dimensions,
        url=settings.embedding_url,
        digest=embedder.digest,
    )


def text(ready: Ready, _detail: Detail) -> str:
    """Write the dimensions, the endpoint, the short digest, and whether prefixes are known."""
    return (
        f"{ready.name}: {ready.dimensions} dimensions, from {ready.url};"
        f" digest {ready.digest[:SHORT] or 'not reported'}; {prefixes_said(ready.name)}\n"
    )
