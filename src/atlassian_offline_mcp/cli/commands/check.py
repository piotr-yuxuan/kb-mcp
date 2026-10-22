"""``check``: validate the settings and the data directory, and show them."""

from __future__ import annotations

from typing import TYPE_CHECKING

from atlassian_offline_mcp.kernel.exit_status import ExitStatus

if TYPE_CHECKING:
    import argparse

    from atlassian_offline_mcp.config.domain.settings import Loaded
    from atlassian_offline_mcp.kernel.output import Summary


def run(_arguments: argparse.Namespace, loaded: Loaded) -> tuple[ExitStatus, Loaded]:
    """Give the effective settings, which the entry checked, the data directory included.

    With them come the layer of each and the values ignored.
    """
    return ExitStatus.OK, loaded


def text(loaded: Loaded, _summary: Summary) -> str:
    """Write the effective settings, each followed by the layer that gave it.

    The layer is the settings file's name, a variable's, a flag, or default.
    """
    settings = loaded.settings
    return (
        f"site: {settings.site or '(not set)'} [{loaded.layer('site')}]\n"
        f"data directory: {settings.data_dir} [{loaded.layer('data_dir')}]\n"
        f"spaces: {', '.join(settings.sources.confluence.spaces) or '(none)'}"
        f" [{loaded.layer('sources.confluence.spaces')}]\n"
        f"projects: {', '.join(settings.sources.jira.projects) or '(none)'}"
        f" [{loaded.layer('sources.jira.projects')}]\n"
    )
