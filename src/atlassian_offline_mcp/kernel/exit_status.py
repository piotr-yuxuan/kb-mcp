"""The exit statuses of every command, defined once for the commands and their use cases."""

from __future__ import annotations

from enum import IntEnum


class ExitStatus(IntEnum):
    """How a run ended, as the shell reads it."""

    OK = 0
    # Something failed: a document, a file, a check or the endpoint.
    FAILED = 1
    # Settings, options or input refused before anything was done.
    REFUSED = 2
    # No session saved, or it no longer holds.
    SIGN_IN_AGAIN = 3
    # The shell's own status for a run stopped by Ctrl-C.
    INTERRUPTED = 130
