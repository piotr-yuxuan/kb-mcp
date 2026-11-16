"""Each source's file of the mirror beside its documents: ``<source>/_source.json``.

A source's prepare writes its file with ``dumped``, and ``index`` reads every source's
with ``source_files``, so that what a connector declares reaches the index through the
mirror alone; a work log's fetch reads its own with ``source_file`` as its copy store
begins. Its name begins with ``_``, so that no reader takes it for a document.
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
# The keys of a file written before plan 061, which names no container.
FORMER_KEYS = [key for key in KEYS if key != "containers"]


def dumped(source_file: SourceFile) -> bytes:
    """Write a source's file: JSON, indented, its keys in order, so that it reads in a diff."""
    return (json.dumps(source_file.model_dump(mode="json"), indent=2) + "\n").encode()


def source_file(docs: Path, source: str) -> SourceFile | None:
    """Read the file of ``source`` of the mirror at ``docs``, None when it has none.

    A file without ``containers``, written before plan 061, names none. Raises
    RepresentationError for a file that is not JSON, or holds other keys or values than
    ``SourceFile``'s, naming the file and ``kb-mcp prepare``, which writes it again; and
    OSError for one that cannot be read.
    """
    path = f"{source}/{SOURCE_FILE}"
    try:
        data = (docs / path).read_bytes()
    except FileNotFoundError:
        return None
    try:
        fields = Fields(json.loads(data), path)
        if list(fields.value) not in (KEYS, FORMER_KEYS):
            message = f"{path}: keys other than {', '.join(KEYS)}"
            raise RepresentationError(message)
        roles, as_of = fields.object("roles"), fields.object("as_of")
        containers = fields.texts("containers") if "containers" in fields.value else ()
        with fields.refusals():
            return SourceFile(
                roles={name: roles.texts(name) for name in roles.value},
                containers=containers,
                as_of={scope: as_of.time(scope) for scope in as_of.value},
            )
    except ValueError as error:
        # Not UTF-8 or not JSON, whose messages may quote the file; or its own refusal.
        reason = str(error) if isinstance(error, RepresentationError) else f"{path}: not JSON"
        message = f"{reason}; `kb-mcp prepare` writes it again"
        raise RepresentationError(message) from None


def source_files(docs: Path) -> dict[str, SourceFile]:
    """Read the file of each source of the mirror at ``docs``, by the source's name, its folder.

    A source without one is left out; each is read, or refused, as ``source_file`` says.
    """
    names = [file.parent.name for file in sorted(docs.glob(f"*/{SOURCE_FILE}"))]
    found = {name: source_file(docs, name) for name in names}
    return {name: each for name, each in found.items() if each is not None}
