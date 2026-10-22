"""The guides' command lines: each that runs the program parses as the program reads it.

Plan 015 checks its two how-tos, ``AGENTS.md`` and the guides it changed; plan 020 is to
check every page.
"""

from __future__ import annotations

import re
import shlex
from pathlib import Path

import pytest

from atlassian_offline_mcp.cli.main import parser

ROOT = Path(__file__).parents[1]
PAGES = (
    "AGENTS.md",
    "docs/how-to/agents.md",
    "docs/how-to/api-token-with-sops.md",
    "docs/how-to/first-download.md",
    "docs/how-to/shell-completions.md",
)
# A block of shell commands in Markdown.
BASH = re.compile(r"^```bash\n(.*?)^```", re.MULTILINE | re.DOTALL)
# The program's name as a word of its own, not part of a path or of another name.
PROGRAM = re.compile(r"(?<![\w/.~-])atlassian-offline-mcp(?![\w/.-])")
# What ends the arguments of a command: a quote, as around the command that sops runs, a
# parenthesis, a pipe, a list.
END = re.compile(r"['\")|;&]")


@pytest.mark.parametrize("page", PAGES)
def test_each_command_line_of_the_program_parses(page: str) -> None:
    """With continuations joined, the arguments of the program's last name in a line parse.

    The last, as in ``claude mcp add ... atlassian-offline-mcp -- atlassian-offline-mcp``,
    whose server bears the program's name; no arguments mean ``serve``. --help may exit 0.
    """
    text = (ROOT / page).read_text("utf-8")
    lines = [
        END.split(PROGRAM.split(line)[-1])[0]
        for block in BASH.findall(text)
        for line in block.replace("\\\n", " ").splitlines()
        if PROGRAM.search(line)
    ]
    assert lines, page
    refused = []
    for given in lines:
        try:
            parser().parse_args(shlex.split(given) or ["serve"])
        except SystemExit as stopped:
            if stopped.code != 0:
                refused.append(given)
    assert refused == []
