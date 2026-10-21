"""Options that every command taking settings shares, and their loading."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from atlassian_offline_mcp.app.settings import SETTINGS_PATH, load_settings

if TYPE_CHECKING:
    import argparse

    from atlassian_offline_mcp.domain.settings import Settings


def add_settings_options(parser: argparse.ArgumentParser) -> None:
    """Add --config, --data-dir and --site, which override the settings file."""
    parser.add_argument("--config", type=Path, default=SETTINGS_PATH, help="the settings file")
    parser.add_argument("--data-dir", help="the data directory, overriding the settings")
    parser.add_argument("--site", help="the site, as https://<name>.atlassian.net")


def settings_of(arguments: argparse.Namespace) -> Settings:
    """Load the settings with the options given; raise SettingsError when refused."""
    return load_settings(arguments.config, {"data_dir": arguments.data_dir, "site": arguments.site})
