"""``completion``: print the code that completes the command in bash and zsh."""

from __future__ import annotations

from typing import TYPE_CHECKING

import argcomplete

from atlassian_offline_mcp.cli.domain.command import PROGRAM
from atlassian_offline_mcp.kernel.exit_status import ExitStatus

if TYPE_CHECKING:
    import argparse

    from atlassian_offline_mcp.kernel.output import Summary


def run(_arguments: argparse.Namespace, _settings: None) -> tuple[ExitStatus, str]:
    """Give argcomplete's script, one for both shells, which runs the command at each Tab.

    It registers the command by name, as installed tools have no executable of
    argcomplete's own on the path.
    """
    return ExitStatus.OK, argcomplete.shellcode([PROGRAM])


def text(script: str, _summary: Summary) -> str:
    """Write the script as it is."""
    return script
