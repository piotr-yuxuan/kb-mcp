"""Options that every command taking settings shares, and their loading."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
from typing import TYPE_CHECKING

from atlassian_offline_mcp.adapters.embedding import KEY_VARIABLE, Endpoint, endpoint, prefixes
from atlassian_offline_mcp.config.app.settings import SETTINGS_PATH, load_settings
from atlassian_offline_mcp.config.domain.settings import MODEL_NAME

if TYPE_CHECKING:
    from atlassian_offline_mcp.config.domain.settings import Settings


def add_settings_options(parser: argparse.ArgumentParser) -> None:
    """Add --config, --data-dir and --site, which override the settings file."""
    parser.add_argument("--config", type=Path, default=SETTINGS_PATH, help="the settings file")
    parser.add_argument("--data-dir", help="the data directory, overriding the settings")
    parser.add_argument("--site", help="the site, as https://<name>.atlassian.net")


def settings_of(arguments: argparse.Namespace) -> Settings:
    """Load the settings with the options given; raise SettingsError when refused."""
    return load_settings(arguments.config, {"data_dir": arguments.data_dir, "site": arguments.site})


def add_embedding_options(parser: argparse.ArgumentParser) -> None:
    """Add --allow-remote-embeddings: never a setting, so that it is given on every run."""
    parser.add_argument(
        "--allow-remote-embeddings",
        action="store_true",
        help="let this run send the mirror's text to an embedding endpoint off this machine",
    )


def open_endpoint(arguments: argparse.Namespace, settings: Settings) -> Endpoint:
    """Open the setting's embedding endpoint as this run allows; raise SettingsError if not.

    The API key, if any, comes from the environment, never from the settings.
    """
    return endpoint(
        settings.embedding_url,
        os.environ.get(KEY_VARIABLE),
        remote_allowed=arguments.allow_remote_embeddings,
    )


def model_name(value: str) -> str:
    """Take a model's name given on the command line as the setting takes it."""
    if not MODEL_NAME.fullmatch(value):
        message = "the name of an embedding model, such as qwen3-embedding:0.6b"
        raise argparse.ArgumentTypeError(message)
    return value


def prefixes_said(model: str) -> str:
    """Say whether the prefixes that a model's card asks for are known here."""
    return "its prefixes known" if prefixes(model) else "no prefixes known: texts as they are"
