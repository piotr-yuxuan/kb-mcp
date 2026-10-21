"""``model``: pull an embedding model into the data directory, or list the known ones.

This is the only command that downloads a model; ``index``, ``serve`` and ``eval`` read
what it pulled, and never reach the network for a model.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING

import httpx

from atlassian_offline_mcp.adapters.embedding import CATALOGUE, ModelError, known, pulled
from atlassian_offline_mcp.adapters.model_pull import copy_from, download_client, pull
from atlassian_offline_mcp.commands._options import add_settings_options, settings_of
from atlassian_offline_mcp.domain.settings import SettingsError

if TYPE_CHECKING:
    import argparse

SOME_FAILED = 1
BAD_SETTINGS = 2
MEGABYTE = 1_000_000


def register(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """Add ``model`` to the command."""
    parser = subparsers.add_parser("model", help="pull an embedding model, or list them")
    add_settings_options(parser)
    parser.add_argument("action", choices=("pull", "list"))
    parser.add_argument("name", nargs="?", help="the model to pull; by default, the setting")
    parser.add_argument(
        "--from", dest="source", type=Path, help="a folder holding the files, as the hub does"
    )
    parser.set_defaults(run=run)


def run(arguments: argparse.Namespace) -> int:
    """Pull or list; exit 1 when a download failed, 2 for bad settings or an unknown model."""
    try:
        settings = settings_of(arguments)
    except SettingsError as error:
        sys.stderr.write(f"refused: {error}\n")
        return BAD_SETTINGS
    if arguments.action == "list":
        for name, each in sorted(CATALOGUE.items()):
            state = "pulled" if pulled(each, settings.models) else "not pulled"
            size = sum(file.size for file in each.files) // MEGABYTE
            chosen = ", the setting" if name == settings.model else ""
            sys.stdout.write(f"{name}: {each.repository}, {size} MB, {state}{chosen}\n")
        return 0
    try:
        model = known(arguments.name or settings.model)
    except ModelError as error:
        sys.stderr.write(f"refused: {error}\n")
        return BAD_SETTINGS
    try:
        if arguments.source is not None:
            fetched = copy_from(model, settings.models, arguments.source)
        else:
            with download_client() as client:
                fetched = pull(model, settings.models, client)
    except (ModelError, httpx.HTTPError, OSError) as error:
        reason = str(error) if isinstance(error, ModelError) else type(error).__name__
        sys.stderr.write(f"not pulled: {reason}\n")
        return SOME_FAILED
    sys.stdout.write(
        f"{model.name}: {len(fetched)} files fetched, into {settings.models / model.name}\n"
    )
    return 0
