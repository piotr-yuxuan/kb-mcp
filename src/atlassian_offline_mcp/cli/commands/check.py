"""``check``: validate the settings and the data directory, and show them."""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

from atlassian_offline_mcp.kernel.exit_status import ExitStatus

if TYPE_CHECKING:
    import argparse

    from atlassian_offline_mcp.config.domain.settings import Settings


def run(_arguments: argparse.Namespace, settings: Settings) -> ExitStatus:
    """Print the effective settings, which the entry checked, the data directory included."""
    sys.stdout.write(
        f"site: {settings.site or '(not set)'}\n"
        f"data directory: {settings.data_dir}\n"
        f"spaces: {', '.join(settings.spaces) or '(none)'}\n"
        f"projects: {', '.join(settings.projects) or '(none)'}\n"
    )
    return ExitStatus.OK
