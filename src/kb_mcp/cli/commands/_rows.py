"""The rows that ``sync`` and ``mirror`` write as text: each row, then its result."""

from __future__ import annotations

from typing import TYPE_CHECKING

from kb_mcp.cli.domain.sync import label

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    from kb_mcp.cli.app.sync import Synced
    from kb_mcp.kernel.output import Summary


def rows_text(synced: Synced, summary: Summary, texts: Mapping[str, Callable[..., str]]) -> str:
    """Write each row, by its step and source, and how it ended; then its result, indented.

    A result is written as ``texts`` writes its step's, as that step's command does.
    """
    written: list[str] = []
    for row in synced.steps:
        written.append(f"{label(row.step, row.source)}: {row.outcome}\n")
        if row.result is not None:
            shown = texts[row.step](row.result, summary).splitlines()
            written.extend(f"  {line}\n" for line in shown)
    return "".join(written)
