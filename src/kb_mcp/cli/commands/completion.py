"""``completion``: print the code that completes the command in bash and zsh."""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

import argcomplete

from kb_mcp.cli.domain.command import PROGRAM
from kb_mcp.kernel.exit_status import ExitStatus

if TYPE_CHECKING:
    import argparse


def run(arguments: argparse.Namespace) -> ExitStatus:
    """Write argcomplete's script, one for both shells, which runs the command at each Tab.

    It registers the command by name, as installed tools have no executable of
    argcomplete's own on the path. Shells run this at each start, so it is not observed,
    as --version is not: it writes the script itself, which is its result, left
    unwritten by -q, as any result as text is.
    """
    if not arguments.quiet:
        sys.stdout.write(argcomplete.shellcode([PROGRAM]))
    return ExitStatus.OK
