"""Options that commands share, declared without importing what runs them."""

from __future__ import annotations

import argparse
from pathlib import Path

from atlassian_offline_mcp.config.adapters.settings_file import SETTINGS_PATH
from atlassian_offline_mcp.kernel.content import MODEL_NAME


def add_settings_options(parser: argparse.ArgumentParser) -> dict[str, str]:
    """Add --config, --data-dir and --site; return the setting that each flag overrides."""
    parser.add_argument("--config", type=Path, default=SETTINGS_PATH, help="the settings file")
    parser.add_argument("--data-dir", help="the data directory, overriding the settings")
    parser.add_argument("--site", help="the site, as https://<name>.atlassian.net")
    return {"data_dir": "data_dir", "site": "site"}


def add_embedding_options(parser: argparse.ArgumentParser) -> None:
    """Add --allow-remote-embeddings: never a setting, so that it is given on every run."""
    parser.add_argument(
        "--allow-remote-embeddings",
        action="store_true",
        help="let this run send the mirror's text to an embedding endpoint off this machine",
    )


def model_name(value: str) -> str:
    """Take a model's name given on the command line as the setting takes it."""
    if not MODEL_NAME.fullmatch(value):
        message = "the name of an embedding model, such as qwen3-embedding:0.6b"
        raise argparse.ArgumentTypeError(message)
    return value
