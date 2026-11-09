"""The memo source's declaration: what it reads in place, its table, and its preparer.

Read in place, it has no fetcher and no account. Standard library alone, as every
declaration is: ``--help`` imports it.
"""

from __future__ import annotations

from kb_mcp.sources.declaration import ResourceType, Source

MEMO = Source(
    name="memo",
    help="Notes: a folder's text files, read in place, never written",
    resource_types=(ResourceType(name="notes", help="the folder's *.txt files", read="in place"),),
    settings=("folder",),
    table_path="kb_memo.settings:MemoTable",
    preparers=("kb_memo.prepare.app.preparer",),
)
