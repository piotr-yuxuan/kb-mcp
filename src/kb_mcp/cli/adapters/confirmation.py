"""The question before a command writes, asked on stderr and answered on stdin."""

from __future__ import annotations

from typing import TYPE_CHECKING

from kb_mcp.kernel.exit_status import ENDED, ExitStatus

if TYPE_CHECKING:
    from typing import TextIO

    from kb_mcp.cli.domain.preview import Then

QUESTION = "Proceed? [y/N] "
# The answers that let a run go on, in any case.
AGREED = {"y", "yes"}


def ask(then: Then, stdin: TextIO, stderr: TextIO) -> ExitStatus | None:
    """Do what follows the preview: give None for the run to go on, else its exit status.

    A refusal tells to pass --yes and ends the run refused. The question reads one line:
    y or yes lets the run go on; any other answer, or the end of input, does nothing and
    ends it declined; Ctrl-C, interrupted. Nothing is read from stdin unless the question is asked.
    """
    if then == "run":
        return None
    if then == "refuse":
        stderr.write("refused: no terminal to ask on; pass --yes to run without the question\n")
        return ENDED["refused"]
    stderr.write(QUESTION)
    stderr.flush()
    try:
        answer = stdin.readline()
    except KeyboardInterrupt:
        stderr.write("\n")
        return ENDED["interrupted"]
    if answer.strip().lower() in AGREED:
        return None
    # The end of input leaves the cursor after the question, which a newline ends.
    stderr.write(("" if answer.endswith("\n") else "\n") + "Nothing done.\n")
    return ENDED["declined"]
