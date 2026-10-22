"""``model check``: check that the embedding endpoint answers with a model, or say what to run.

It never downloads a model: with Ollama, ``ollama pull`` does.
"""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

from atlassian_offline_mcp.cli.commands._options import (
    add_embedding_options,
    add_settings_options,
    model_name,
)
from atlassian_offline_mcp.cli.commands._shared import open_endpoint, prefixes_said
from atlassian_offline_mcp.cli.domain.command import Command
from atlassian_offline_mcp.config.domain.settings import SettingsError
from atlassian_offline_mcp.kernel.exit_status import ExitStatus
from atlassian_offline_mcp.search.adapters.embedding import ModelError, connect

if TYPE_CHECKING:
    import argparse

    from atlassian_offline_mcp.config.domain.settings import Settings

# Characters of a digest shown, as Ollama shows them.
SHORT = 12


def register(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """Add ``model`` to the command."""
    parser = subparsers.add_parser("model", help="check the embedding model and its endpoint")
    flags = add_settings_options(parser)
    add_embedding_options(parser)
    parser.add_argument("action", choices=("check",))
    parser.add_argument(
        "name", nargs="?", type=model_name, help="the model to check; by default, the setting"
    )
    parser.set_defaults(command=Command(__name__, flags))


def run(arguments: argparse.Namespace, settings: Settings) -> ExitStatus:
    """Check; exit 1 when the endpoint or the model is not ready, 2 for refused settings."""
    try:
        opened = open_endpoint(arguments, settings)
    except SettingsError as error:
        sys.stderr.write(f"refused: {error}\n")
        return ExitStatus.REFUSED
    name = arguments.name or settings.model
    with opened:
        try:
            embedder = connect(opened, name)
        except ModelError as error:
            sys.stderr.write(f"not ready: {error}\n")
            return ExitStatus.FAILED
    sys.stdout.write(
        f"{name}: {embedder.dimensions} dimensions, from {settings.embedding_url};"
        f" digest {embedder.digest[:SHORT] or 'not reported'}; {prefixes_said(name)}\n"
    )
    return ExitStatus.OK
