"""What the runs that build the index share, how it is built, and those that embed: the endpoint.

Apart from the entry, so that a run that builds no index loads none of this.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from kb_mcp.kernel.endpoint import EMBEDDINGS
from kb_mcp.search.adapters.embedding import prefixes
from kb_mcp.search.adapters.model_api import Endpoint, endpoint
from kb_mcp.search.app.indexing import Indexing

if TYPE_CHECKING:
    import argparse
    from collections.abc import Callable

    from kb_mcp.config.domain.settings import Settings


def open_endpoint(arguments: argparse.Namespace, settings: Settings) -> Endpoint:
    """Open the setting's embedding endpoint as this run allows; raise SettingsError if not.

    The API key, if any, is the secret setting, which the environment alone gives.
    """
    key = settings.embedding_api_key
    return endpoint(
        settings.embedding_url,
        key.get_secret_value() if key else None,
        EMBEDDINGS,
        remote_allowed=arguments.allow_remote_embeddings,
    )


def indexing_of(settings: Settings, opening: Callable[[], Endpoint] | None) -> Indexing:
    """Say how a run builds the index, from its settings.

    By words alone when ``opening`` is None; else with the setting's model, through the
    endpoint that ``opening`` opens once the build begins.
    """
    return Indexing(
        docs=settings.docs,
        index=settings.index,
        vectors=settings.vectors,
        evaluation_indexes=settings.evaluation_indexes,
        aliases=settings.aliases,
        model=settings.model,
        chunking=settings.chunking,
        endpoint=opening,
    )


def prefixes_said(model: str) -> str:
    """Say whether the prefixes that a model's card asks for are known here."""
    return "its prefixes known" if prefixes(model) else "no prefixes known: texts as they are"
