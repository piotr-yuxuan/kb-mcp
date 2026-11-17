"""``fetch`` and ``prepare``: a recorded run of one stage per source, a row per source taken."""

from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING

from kb_mcp.cli.commands._runs import recorded
from kb_mcp.cli.commands._stages import planned
from kb_mcp.cli.domain.command import FETCH
from kb_mcp.cli.domain.echo import values_of
from kb_mcp.cli.domain.rows import Ran, Row
from kb_mcp.cli.domain.runs import Configuration
from kb_mcp.cli.domain.sources import chosen, fetch_options
from kb_mcp.config.domain.settings import without_secrets

if TYPE_CHECKING:
    import argparse
    from datetime import datetime

    from kb_mcp.config.domain.settings import Loaded
    from kb_mcp.kernel.exit_status import ExitStatus
    from kb_mcp.kernel.output import Detail


def run(
    arguments: argparse.Namespace, loaded: Loaded, run: str, started: datetime
) -> tuple[ExitStatus, Ran | None]:
    """Run each source taken in this stage, as a run recorded; exit as its units' endings fold.

    The entry refused what it could before asking. The configuration resolved as of the
    run's start, ``started``, the sources taken in their order and, in a fetch, its
    options as of then, is recorded, then run from its record (``recorded``), exit 2 when
    refused. What a ``preflight`` refuses, such as a site not set of a source taken by
    default, an --until before --since, or a work log that is not a folder, fails its
    unit alone. Each unit's problems are said as it runs, by place and reason, never
    content.
    """
    stage = arguments.command.name
    taken, _ = chosen(arguments, values_of(loaded.settings))
    configuration = Configuration(
        run=run,
        command=stage,
        started=started,
        stages=(stage,),
        dry_run=arguments.dry_run,
        sources={stage: tuple(each.name for each in taken)},
        options={FETCH: fetch_options(arguments, taken, started)} if stage == FETCH else {},
        settings=without_secrets(loaded.settings),
    )
    status, done = recorded(loaded, run, started, configuration, partial(planned, arguments))
    if done is None:
        return status, None
    rows = tuple(
        Row(source=str(unit.source), **dict(outcome)) for unit, outcome in done.outcomes.items()
    )
    return status, Ran(run=run, exit_status=status, sources=rows, recorded=done.recorded)


def text(ran: Ran, detail: Detail) -> str:
    """Write the run's id, then a row per source, how it ended, its outcome's own text, indented.

    A run not recorded, a dry run, says so after its id, which no resume takes.
    """
    written = [f"run {ran.run}{'' if ran.recorded else ', not recorded'}\n"]
    for row in ran.sources:
        written.append(f"{row.source}: {row.ending}\n")
        written.extend(f"  {line}\n" for line in row.text(detail).splitlines())
    return "".join(written)
