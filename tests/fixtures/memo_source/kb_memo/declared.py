"""The memo connector: what it reads in place, its table, and its preparer.

Read in place, it has no fetcher and no account. Standard library alone, as every
declaration is: ``--help`` imports it.
"""

from __future__ import annotations

from kb_mcp.sources.declaration import Connector, DocumentType, ScopeType

MEMO = Connector(
    name="memo",
    help="Notes: a folder's text files, read in place, never written",
    scope_types=(
        ScopeType(
            name="folder",
            key=None,
            enumeration="in place",
            document_types=(DocumentType(name="note", plural="notes"),),
        ),
    ),
    settings=("folder",),
    table_path="kb_memo.settings:MemoTable",
    preparers=("kb_memo.prepare.app.preparer",),
)
