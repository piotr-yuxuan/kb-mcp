"""Nothing that the manifest of what the program offers holds is lost.

``tests/fixtures/parity.json``, which ``tests.parity`` writes, holds every command,
option, setting, MCP tool and prompt, and telemetry name that the program offered when it
was written. An entry that the code no longer offers fails, named with its kind; one that
the code adds does not. An entry leaves the manifest only by a decision that the user
approves, in the plan that edits it.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from tests import parity

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from pathlib import Path


def lost(held: Mapping[str, Sequence[str]], offered: Mapping[str, Sequence[str]]) -> list[str]:
    """Name each entry that the manifest holds and the code does not offer, after its kind."""
    return [
        f"{kind}: {entry}"
        for kind, entries in held.items()
        for entry in sorted(set(entries) - set(offered.get(kind, ())))
    ]


def test_an_entry_the_code_lacks_is_lost() -> None:
    """An entry held and not offered is lost, a kind not offered whole; one added is not."""
    held = {"commands": ["fetch", "gone"], "options": ["fetch --space"], "mcp": ["tool ask"]}
    offered = {"commands": ["added", "fetch"], "options": ["fetch --new", "fetch --space"]}
    assert lost(held, offered) == ["commands: gone", "mcp: tool ask"]


def test_nothing_the_manifest_holds_is_lost(tmp_path: Path) -> None:
    """The code offers each entry of the manifest; the server starts in a scratch home."""
    held = json.loads(parity.MANIFEST.read_text("utf-8"))
    assert lost(held, parity.offered(tmp_path)) == []
