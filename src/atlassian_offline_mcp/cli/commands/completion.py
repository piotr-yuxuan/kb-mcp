"""``completion``: print the code that completes the command in bash and zsh."""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

import argcomplete

from atlassian_offline_mcp.cli.domain.command import PROGRAM
from atlassian_offline_mcp.kernel.exit_status import ExitStatus

if TYPE_CHECKING:
    import argparse


def run(_arguments: argparse.Namespace, _settings: None) -> ExitStatus:
    """Print argcomplete's script, one for both shells, which runs the command at each Tab.

    It registers the command by name, as installed tools have no executable of
    argcomplete's own on the path.
    """
    sys.stdout.write(argcomplete.shellcode([PROGRAM]))
    return ExitStatus.OK
