"""The exit statuses of every command, defined once for the commands and their use cases."""

from __future__ import annotations

from enum import IntEnum


class ExitStatus(IntEnum):
    """How a run ended, as the shell reads it; ``MEANINGS`` says what each means."""

    OK = 0
    FAILED = 1
    REFUSED = 2
    SIGN_IN_AGAIN = 3
    INTERRUPTED = 130


# What each status means, as the program's --help lists them.
MEANINGS = {
    ExitStatus.OK: "done",
    ExitStatus.FAILED: "something failed (a document, a file, a check, the endpoint), or the"
    " question was declined",
    ExitStatus.REFUSED: "refused before acting: settings, options or input, or no terminal to"
    " ask on",
    ExitStatus.SIGN_IN_AGAIN: "sign in again: no session saved, it no longer holds, or the"
    " site refused the API token",
    ExitStatus.INTERRUPTED: "stopped by Ctrl-C",
}
