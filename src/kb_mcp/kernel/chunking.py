"""The chunkings that an index's chunks may be cut by, named once for every context.

Standard library only, so that the settings, search's table of cuts and the command
line's choices all take their names from here.
"""

from __future__ import annotations

from typing import Literal

# Characters a token counts for, the same for every model: cuts are made in characters,
# since neither the OpenAI API nor Ollama's tokenises and no tokeniser is a dependency.
CHARACTERS_PER_TOKEN = 4

type Chunking = Literal["sections", "windows", "section-paths", "small-to-big"]
# The chunkings in their order, the control first.
CHUNKINGS: tuple[Chunking, ...] = ("sections", "windows", "section-paths", "small-to-big")
