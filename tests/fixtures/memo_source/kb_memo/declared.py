"""The memo source's declaration: what it reads in place, its table, and its preparer.

Read in place, it has no fetcher and no account. Standard library alone, as every
declaration is: ``--help`` imports it.
"""

from __future__ import annotations

from kb_mcp.sources.declaration import Declared, ResourceType

MEMO = Declared(
    name="memo",
    summary="Notes: a folder's text files, read in place, never written",
    types=(ResourceType(name="notes", summary="the folder's *.txt files", read="in place"),),
    settings=("folder",),
    table="kb_memo.settings:MemoSource",
    preparers=("kb_memo.prepare.app.preparer",),
)
