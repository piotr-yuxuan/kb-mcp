"""Pruning the vector store to what the indexes on disk read (plan 023)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from atlassian_offline_mcp.search.adapters.sqlite_index import indexes_in

if TYPE_CHECKING:
    from pathlib import Path


def test_the_indexes_under_a_folder_leave_builds_out(tmp_path: Path) -> None:
    """Indexes at any depth, in order; a build's empty file, a WAL and others are not."""
    folder = tmp_path / "indexes"
    wanted = [folder / "sections" / "tiny.sqlite", folder / "tiny.sqlite"]
    others = [folder / "windows" / ".index-1234.sqlite", folder / "windows" / "tiny.sqlite-wal"]
    for path in [*wanted, *others, folder / "notes.txt"]:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"")
    assert indexes_in(folder) == sorted(wanted)
    assert indexes_in(tmp_path / "missing") == []
