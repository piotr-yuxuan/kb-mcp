"""Pandoc, which writes the mirror's plain HTML as GitHub-flavoured Markdown.

``--sandbox`` keeps pandoc from reading any file but its input, or fetching anything,
such as the source of a frame. Without native divisions and spans, pandoc writes a
``div`` or a ``span`` as its content rather than as raw HTML.
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass

ARGUMENTS = (
    "--sandbox",
    "--from=html-native_divs-native_spans",
    "--to=gfm",
    "--wrap=none",
)
TIMEOUT = 120  # seconds for one document


class PandocMissingError(RuntimeError):
    """Pandoc is not on PATH."""


class PandocFailedError(RuntimeError):
    """Pandoc did not convert a document; the message holds no content."""


@dataclass(frozen=True)
class Pandoc:
    """The pandoc found on PATH."""

    path: str

    @classmethod
    def find(cls) -> Pandoc:
        """Find pandoc on PATH, or raise ``PandocMissingError`` naming it."""
        path = shutil.which("pandoc")
        if path is None:
            message = "pandoc: not found on PATH; install pandoc 3"
            raise PandocMissingError(message)
        return cls(path)

    def markdown(self, html: str) -> str:
        """Write one document's HTML as Markdown.

        Raises ``PandocFailedError`` with the exit status or the timeout; pandoc's own
        messages may quote the document, so they are left out.
        """
        try:
            done = subprocess.run(  # noqa: S603 pandoc found on PATH, fixed arguments
                [self.path, *ARGUMENTS],
                input=html,
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=TIMEOUT,
                check=False,
            )
        except subprocess.TimeoutExpired:
            message = f"pandoc: no result within {TIMEOUT} seconds"
            raise PandocFailedError(message) from None
        except OSError as error:
            message = f"pandoc: not run ({type(error).__name__})"
            raise PandocFailedError(message) from None
        if done.returncode != 0:
            message = f"pandoc: exit status {done.returncode}"
            raise PandocFailedError(message)
        return done.stdout
