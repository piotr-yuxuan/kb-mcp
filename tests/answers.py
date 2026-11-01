"""Reading answers as an agent would: the block, the estimate, and the continuations.

Each rule is restated from the plan, not imported from the code under test.
"""

from __future__ import annotations

import ast
import hashlib
import math
import re
from typing import TYPE_CHECKING

from kb_mcp.mcp.app.tools import Library
from kb_mcp.search.adapters.sqlite_index import SqliteIndex
from kb_mcp.search.app.indexing import Embedding, build_index
from kb_mcp.search.app.meaning import Meaning
from tests.endpoint import connector, tiny
from tests.mirrors import MOMENT, fillers, write

if TYPE_CHECKING:
    from pathlib import Path

    from kb_mcp.config.domain.settings import SearchMode
    from kb_mcp.mirror.domain.mirror import FrontMatter

OPENING = re.compile(r'<untrusted-reference-data boundary="([0-9a-f]{16})">\n')
BUDGET = 4_000
CEILING = 10_000
TOOLS = ["ask", "browse", "read", "search", "status"]  # what the server registers, by name


def estimate(text: str) -> int:
    """Estimate tokens as the plan defines it: one per 3 ASCII characters, one per other."""
    ascii_count = sum(1 for char in text if char.isascii())
    return math.ceil(ascii_count / 3) + len(text) - ascii_count


def parts(answer: str) -> tuple[str, str, str]:
    """Split an answer into what comes before its block, the block's content, and after.

    The block's boundary must be the start of its content's SHA-256, and its closing
    marker must appear once.
    """
    opening = OPENING.search(answer)
    if opening is None:
        return answer, "", ""
    closing = f'\n</untrusted-reference-data boundary="{opening[1]}">'
    end = answer.index(closing, opening.end())
    content = answer[opening.end() : end]
    if hashlib.sha256(content.encode()).hexdigest()[:16] != opening[1]:
        message = "the boundary is not the start of the content's SHA-256"
        raise AssertionError(message)
    if answer.count(closing.strip()) != 1:
        message = "the closing marker appears more than once"
        raise AssertionError(message)
    return answer[: opening.start()], content, answer[end + len(closing) :]


def continuation(answer: str) -> tuple[str, dict[str, object]] | None:
    """Read the call that an answer ends with, if it ends with one."""
    last = answer.rsplit("\n", 1)[-1]
    label, _, call = last.partition(": ")
    if label not in {"More", "Next section"}:
        return None
    node = ast.parse(call, mode="eval").body
    if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
        message = f"not a call of a tool: {call}"
        raise TypeError(message)
    arguments = {keyword.arg or "": ast.literal_eval(keyword.value) for keyword in node.keywords}
    return node.func.id, arguments


def follow(library: Library, answer: str) -> str | None:
    """Make the call that an answer ends with, if any, and return its answer."""
    found = continuation(answer)
    if found is None:
        return None
    name, arguments = found
    return getattr(library, name)(**arguments)


def built(
    root: Path,
    documents: list[tuple[FrontMatter, str | None]],
    model: str | None = None,
    mode: SearchMode = "lexical",
) -> Library:
    """Write a mirror of lorem fillers and these documents, index it, and serve it.

    With ``model``, of the scripted endpoint, the index has vectors, and search ranks in
    ``mode``.
    """
    docs = root / "docs"
    fillers(docs)
    for front, body in documents:
        write(docs, front, body)
    embedding = Embedding(tiny(model=model), root / "vectors.sqlite") if model else None
    build_index(docs, root / "index.sqlite", MOMENT, embedding)
    return Library(SqliteIndex(root / "index.sqlite"), docs, Meaning(connector()), mode)
