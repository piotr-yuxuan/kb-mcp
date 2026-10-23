"""The tools that the MCP server may serve, named once for its options and for itself.

Standard library only, so that ``serve``'s declaration offers them without loading the
server.
"""

from __future__ import annotations

from typing import Literal

type Tool = Literal["ask", "search", "read", "browse", "status"]
# Every tool, in the order that the server lists them: what ``serve`` serves by default.
TOOLS: tuple[Tool, ...] = ("ask", "search", "read", "browse", "status")
