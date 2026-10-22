"""The entry of every run, and what runs share: the embedding endpoint and its model."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from atlassian_offline_mcp.config.app.settings import load_settings
from atlassian_offline_mcp.config.domain.settings import SettingsError
from atlassian_offline_mcp.kernel.exit_status import ExitStatus
from atlassian_offline_mcp.search.adapters.embedding import Endpoint, endpoint, prefixes

if TYPE_CHECKING:
    import argparse

    from atlassian_offline_mcp.cli.domain.command import Command
    from atlassian_offline_mcp.config.domain.settings import Settings


def enter(arguments: argparse.Namespace) -> int:
    """Load the settings, with the flags given, then run the chosen subcommand.

    Refused settings exit 2 before the run is imported; else the run's status is
    returned. A subcommand that reads no settings gets None.
    """
    command: Command = arguments.command
    settings = None
    if command.reads_settings:
        flags = {
            f"--{dest.replace('_', '-')}": (setting, getattr(arguments, dest))
            for dest, setting in command.flags.items()
        }
        try:
            settings = load_settings(arguments.config, flags, Path.home().resolve()).settings
        except SettingsError as error:
            sys.stderr.write(f"settings refused: {error}\n")
            return ExitStatus.REFUSED
    return int(importlib.import_module(command.run).run(arguments, settings))


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
