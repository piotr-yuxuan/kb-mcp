"""The guides' command lines: each that runs the program parses as the program reads it.

Plan 015 checks its two how-tos, ``AGENTS.md`` and the guides it changed, plan 017 its
two; plan 020 is to check every page.
"""

from __future__ import annotations

import inspect
import re
import shlex
from pathlib import Path

import pytest

from atlassian_offline_mcp.cli.main import parser
from atlassian_offline_mcp.kernel.tools import TOOLS
from atlassian_offline_mcp.mcp.app.surface import surface
from atlassian_offline_mcp.mcp.app.tools import Library

ROOT = Path(__file__).parents[1]
PAGES = (
    "AGENTS.md",
    "docs/how-to/agents.md",
    "docs/how-to/api-token-with-sops.md",
    "docs/how-to/evaluate-with-agents.md",
    "docs/how-to/first-download.md",
    "docs/how-to/golden-questions.md",
    "docs/how-to/shell-completions.md",
    "docs/how-to/sync.md",
    "docs/how-to/work-log.md",
)
# A block of shell commands in Markdown.
BASH = re.compile(r"^```bash\n(.*?)^```", re.MULTILINE | re.DOTALL)
# The program's name as a word of its own, not part of a path or of another name.
PROGRAM = re.compile(r"(?<![\w/.~-])atlassian-offline-mcp(?![\w/.-])")
# What ends the arguments of a command: a quote, as around the command that sops runs, a
# parenthesis, a pipe, a list, a redirection.
END = re.compile(r"['\")|;&>]")


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


def test_the_reference_names_each_tool_and_prompt_served_and_each_of_their_parameters() -> None:
    """Its headings under Tools and Prompts are those served, each parameter in code below.

    The headings come in the server's order, as plan 020's check of every page reads them.
    """
    text = (ROOT / "docs" / "reference" / "mcp-tools.md").read_text("utf-8")
    tools = text.split("\n## Tools\n")[1].split("\n## Prompts\n")[0]
    prompts = text.split("\n## Prompts\n")[1]
    library = Library(ROOT / "index.sqlite", ROOT / "docs")
    sections = {
        name: body
        for part in (tools, prompts)
        for name, body in re.findall(
            r"^### (\S+)\n(.*?)(?=^### |\Z)", part, re.MULTILINE | re.DOTALL
        )
    }
    assert re.findall(r"^### (\S+)$", tools, re.MULTILINE) == list(TOOLS)
    guides = surface(library, TOOLS).guides
    assert re.findall(r"^### (\S+)$", prompts, re.MULTILINE) == [guide.name for guide in guides]
    for tool in TOOLS:
        named = list(inspect.signature(getattr(library, tool)).parameters)
        assert all(f"`{name}`" in sections[tool] for name in named), tool
    for guide in guides:
        assert all(f"`{name}`" in sections[guide.name] for name, _ in guide.arguments), guide.name
