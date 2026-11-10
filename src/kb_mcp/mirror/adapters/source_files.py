"""Each source's file of the mirror beside its documents: ``<source>/_source.json``.

A source's prepare writes its file with ``dumped``, and ``index`` reads every source's
with ``source_files``, so that what a connector declares reaches the index through the
mirror alone. Its name begins with ``_``, so that no reader takes it for a document.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from kb_mcp.kernel.fields import Fields, RepresentationError
from kb_mcp.mirror.domain.mirror import SourceFile

if TYPE_CHECKING:
    from pathlib import Path

SOURCE_FILE = "_source.json"
KEYS = list(SourceFile.model_fields)


def dumped(source_file: SourceFile) -> bytes:
    """Write a source's file: JSON, indented, its keys in order, so that it reads in a diff."""
    return (json.dumps(source_file.model_dump(mode="json"), indent=2) + "\n").encode()


def source_files(docs: Path) -> dict[str, SourceFile]:
    """Read the file of each source of the mirror at ``docs``, by the source's name, its folder.

    A source without one is left out. Raises RepresentationError for a file that is not
    JSON, or holds other keys or values than ``SourceFile``'s, naming the file and
    ``kb-mcp prepare``, which writes it again; and OSError for one that cannot be read.
    """
    found: dict[str, SourceFile] = {}
    for file in sorted(docs.glob(f"*/{SOURCE_FILE}")):
        path = file.relative_to(docs).as_posix()
        try:
            fields = Fields(json.loads(file.read_bytes()), path)
            if list(fields.value) != KEYS:
                message = f"{path}: keys other than {', '.join(KEYS)}"
                raise RepresentationError(message)
            roles = fields.object("roles")
            with fields.refusals():
                found[file.parent.name] = SourceFile(
                    roles={name: roles.texts(name) for name in roles.value}
                )
        except ValueError as error:
            # Not UTF-8 or not JSON, whose messages may quote the file; or its own refusal.
            reason = str(error) if isinstance(error, RepresentationError) else f"{path}: not JSON"
            message = f"{reason}; `kb-mcp prepare` writes it again"
            raise RepresentationError(message) from None
    return found
