"""What the runs that embed share: the embedding endpoint and its model's prefixes.

Apart from the entry, so that a run that embeds nothing loads none of this.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from atlassian_offline_mcp.search.adapters.embedding import Endpoint, endpoint, prefixes

if TYPE_CHECKING:
    import argparse

    from atlassian_offline_mcp.config.domain.settings import Settings


def open_endpoint(arguments: argparse.Namespace, settings: Settings) -> Endpoint:
    """Open the setting's embedding endpoint as this run allows; raise SettingsError if not.

    The API key, if any, is the secret setting, which the environment alone gives.
    """
    key = settings.embedding_api_key
    return endpoint(
        settings.embedding_url,
        key.get_secret_value() if key else None,
        remote_allowed=arguments.allow_remote_embeddings,
    )


def prefixes_said(model: str) -> str:
    """Say whether the prefixes that a model's card asks for are known here."""
    return "its prefixes known" if prefixes(model) else "no prefixes known: texts as they are"
