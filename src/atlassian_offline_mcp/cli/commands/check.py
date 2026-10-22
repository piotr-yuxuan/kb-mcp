"""``check``: validate the settings and the data directory, and show them."""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

from atlassian_offline_mcp.kernel.exit_status import ExitStatus

if TYPE_CHECKING:
    import argparse

    from atlassian_offline_mcp.config.domain.settings import Loaded


def run(_arguments: argparse.Namespace, loaded: Loaded) -> ExitStatus:
    """Print the effective settings, which the entry checked, the data directory included.

    Each is followed by the layer that gave it: the settings file's name, a variable's,
    a flag, or default.
    """
    settings = loaded.settings
    sys.stdout.write(
        f"site: {settings.site or '(not set)'} [{loaded.layer('site')}]\n"
        f"data directory: {settings.data_dir} [{loaded.layer('data_dir')}]\n"
        f"spaces: {', '.join(settings.sources.confluence.spaces) or '(none)'}"
        f" [{loaded.layer('sources.confluence.spaces')}]\n"
        f"projects: {', '.join(settings.sources.jira.projects) or '(none)'}"
        f" [{loaded.layer('sources.jira.projects')}]\n"
    )
    return ExitStatus.OK
