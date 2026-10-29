"""Pandoc, which writes the mirror's plain HTML and the work log's org as Markdown.

``--sandbox`` keeps pandoc from reading any file but its input, or fetching anything,
such as the source of a frame. Without native divisions and spans, pandoc writes a
``div`` or a ``span`` as its content rather than as raw HTML. Org is written without raw
HTML, so that a span of org's, such as a keyword's, is its content too.
"""

from __future__ import annotations

import shutil
import subprocess
from typing import TYPE_CHECKING

from kb_mcp.kernel.record import Record

if TYPE_CHECKING:
    from collections.abc import Sequence

ARGUMENTS = (
    "--sandbox",
    "--from=html-native_divs-native_spans",
    "--to=gfm",
    "--wrap=none",
)
# A transcript's lines stay its own, one speaker's turn to a line.
ORG = ("--sandbox", "--from=org", "--to=gfm-raw_html", "--wrap=preserve")
VERSION = ("--version",)
TIMEOUT = 120  # seconds for one document


class PandocMissingError(RuntimeError):
    """Pandoc is not on PATH."""


class PandocFailedError(RuntimeError):
    """Pandoc did not convert a document; the message holds no content."""


class Pandoc(Record):
    """The pandoc found on PATH."""

    path: str

    @classmethod
    def find(cls) -> Pandoc:
        """Find pandoc on PATH, or raise ``PandocMissingError`` naming it."""
        path = shutil.which("pandoc")
        if path is None:
            message = "pandoc: not found on PATH; install pandoc 3"
            raise PandocMissingError(message)
        return cls(path=path)

    def markdown(self, html: str) -> str:
        """Write one document's HTML as Markdown."""
        return self.run(ARGUMENTS, html)

    def org_markdown(self, org: str) -> str:
        """Write one document's org as Markdown."""
        return self.run(ORG, org)

    def version(self) -> str:
        """Return the first line of pandoc's version, such as ``pandoc 3.7.0.2``."""
        return self.run(VERSION, "").partition("\n")[0]

    def org_converter(self) -> str:
        """Name how org is converted: pandoc's version, then the arguments, one a line."""
        return "\n".join([self.version(), *ORG])

    def html_converter(self) -> str:
        """Name how HTML is converted: pandoc's version, then the arguments, one a line."""
        return "\n".join([self.version(), *ARGUMENTS])

    def run(self, arguments: Sequence[str], text: str) -> str:
        """Run pandoc with fixed arguments on ``text``, and return its output.

        Raises ``PandocFailedError`` with the exit status or the timeout; pandoc's own
        messages may quote the document, so they are left out.
        """
        try:
            done = subprocess.run(  # noqa: S603 pandoc found on PATH, fixed arguments
                [self.path, *arguments],
                input=text,
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
