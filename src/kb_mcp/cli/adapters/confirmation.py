"""The question before a command writes, asked on stderr and answered on stdin."""

from __future__ import annotations

from typing import TYPE_CHECKING

from kb_mcp.kernel.exit_status import ExitStatus

if TYPE_CHECKING:
    from typing import TextIO

    from kb_mcp.cli.domain.preview import Then

QUESTION = "Proceed? [y/N] "
# The answers that let a run go on, in any case.
AGREED = {"y", "yes"}


def ask(then: Then, stdin: TextIO, stderr: TextIO) -> ExitStatus | None:
    """Do what follows the summary: give None for the run to go on, else its exit status.

    A refusal tells to pass --yes and exits 2. The question reads one line: y or yes
    lets the run go on; any other answer, or the end of input, does nothing and exits 1;
    Ctrl-C exits 130. Nothing is read from stdin unless the question is asked.
    """
    if then == "run":
        return None
    if then == "refuse":
        stderr.write("refused: no terminal to ask on; pass --yes to run without the question\n")
        return ExitStatus.REFUSED
    stderr.write(QUESTION)
    stderr.flush()
    try:
        answer = stdin.readline()
    except KeyboardInterrupt:
        stderr.write("\n")
        return ExitStatus.INTERRUPTED
    if answer.strip().lower() in AGREED:
        return None
    # The end of input leaves the cursor after the question, which a newline ends.
    stderr.write(("" if answer.endswith("\n") else "\n") + "Nothing done.\n")
    return ExitStatus.FAILED
