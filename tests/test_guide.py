"""The pages that set agents up: their snippets parse, start the command, allow its tools."""

from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path

from tests.answers import TOOLS

ROOT = Path(__file__).resolve().parent.parent
# The guide, which registers the server in both clients, and the tutorial, which
# registers it in Claude Code: each allows the tools.
PAGES = ("docs/how-to/agents.md", "docs/tutorials/first-mirror.md")
TEXTS = {page: (ROOT / page).read_text(encoding="utf-8") for page in PAGES}
SNIPPETS = {
    page: [json.loads(code) for code in re.findall(r"```json\n(.*?)```", text, re.DOTALL)]
    for page, text in TEXTS.items()
}
SERVER = "kb-mcp"  # the name each client knows the server by


def test_every_registration_starts_the_console_script() -> None:
    """Both clients' entries and each page's command line run the command the package installs."""
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    (script,) = project["scripts"]
    entries = []
    for snippet in SNIPPETS["docs/how-to/agents.md"]:
        for key in ("mcpServers", "servers"):
            if isinstance(servers := snippet.get(key), dict):
                entries += [(name, one["command"], one["args"]) for name, one in servers.items()]
    assert entries == [(SERVER, script, []), (SERVER, script, [])]
    line = f"claude mcp add --scope user --transport stdio {SERVER} -- {script}\n"
    assert [page for page, text in TEXTS.items() if line not in text] == []


def test_the_allowed_tools_are_those_the_server_registers() -> None:
    """Each page's allow list for Claude Code names the tools, as Claude Code names them."""
    allowed = {
        page: [
            sorted(snippet["permissions"]["allow"])
            for snippet in snippets
            if "allow" in snippet.get("permissions", {})
        ]
        for page, snippets in SNIPPETS.items()
    }
    expected = sorted(f"mcp__{SERVER}__{tool}" for tool in TOOLS)
    assert allowed == {page: [expected] for page in PAGES}
