"""The setup guide: its snippets parse, start the package's command, allow its tools."""

from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path

from tests.answers import TOOLS

ROOT = Path(__file__).resolve().parent.parent
GUIDE = (ROOT / "docs" / "guides" / "agents.md").read_text(encoding="utf-8")
SNIPPETS = [json.loads(text) for text in re.findall(r"```json\n(.*?)```", GUIDE, re.DOTALL)]
SERVER = "atlassian-offline-mcp"  # the name each client knows the server by


def test_every_registration_starts_the_console_script() -> None:
    """The command line and both clients' entries run the command the package installs."""
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    (script,) = project["scripts"]
    entries = []
    for snippet in SNIPPETS:
        for key in ("mcpServers", "servers"):
            if isinstance(servers := snippet.get(key), dict):
                entries += [(name, one["command"], one["args"]) for name, one in servers.items()]
    assert entries == [(SERVER, script, []), (SERVER, script, [])]
    assert f"claude mcp add --scope user --transport stdio {SERVER} -- {script}\n" in GUIDE


def test_the_allowed_tools_are_those_the_server_registers() -> None:
    """Claude Code's allow list names the four tools, as Claude Code names them."""
    allowed = [
        snippet["permissions"]["allow"]
        for snippet in SNIPPETS
        if "allow" in snippet.get("permissions", {})
    ]
    assert len(allowed) == 1
    assert sorted(allowed[0]) == [f"mcp__{SERVER}__{tool}" for tool in TOOLS]
