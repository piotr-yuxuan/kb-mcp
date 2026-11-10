"""``fetch`` and ``prepare``: each source taken, its part in the stage in turn, a row each."""

from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import structlog

from kb_mcp.cli.app.sources import SourcesRefusedError, run_each
from kb_mcp.cli.domain.echo import values_of
from kb_mcp.cli.domain.sources import FETCH, PREPARE, chosen, given
from kb_mcp.kernel.exit_status import ExitStatus
from kb_mcp.sources.stages import SourceRun

if TYPE_CHECKING:
    import argparse

    from kb_mcp.cli.domain.rows import Ran
    from kb_mcp.config.domain.settings import Loaded
    from kb_mcp.kernel.output import Detail

# What each command's refusal is called, written out as every event's name is.
REFUSED = {FETCH: "fetch.refused", PREPARE: "prepare.refused"}


def run(arguments: argparse.Namespace, loaded: Loaded) -> tuple[ExitStatus, Ran | None]:
    """Run each source taken in this stage; exit as the rows' endings fold, 2 when refused.

    The entry refused what it could before asking. Each source taken is run with its
    table, its account's, and, in a fetch, its options' values by flag. A fetcher or a
    preparer that does not load, or what its ``preflight`` refuses, such as an --until
    before --since, or a work log that is not a folder, is refused here, before any row
    runs, an error, ``fetch.refused`` or ``prepare.refused``. Each row's problems are said
    as it runs, by place and reason, never content.
    """
    settings = loaded.settings
    stage = arguments.command.name
    taken, _ = chosen(arguments, values_of(loaded))
    runs = [
        SourceRun(
            source=declared,
            settings=settings,
            source_table=getattr(settings.sources, declared.name),
            account_table=(
                None
                if declared.connector.account is None
                else getattr(settings.accounts, declared.connector.account.name)
            ),
            options=given(arguments, declared.connector.flags) if stage == FETCH else {},
            now=lambda: datetime.now(UTC),
            sleep=time.sleep,
            dry_run=arguments.dry_run,
        )
        for declared in taken
    ]
    try:
        ran = run_each(stage, runs)
    except SourcesRefusedError as error:
        structlog.get_logger().error(REFUSED[stage], reason=str(error))
        return ExitStatus.REFUSED, None
    return ran.exit_status, ran


def text(ran: Ran, detail: Detail) -> str:
    """Write a row per source, how it ended, then its outcome's own text, indented."""
    written: list[str] = []
    for row in ran.sources:
        written.append(f"{row.source}: {row.ending}\n")
        written.extend(f"  {line}\n" for line in row.text(detail).splitlines())
    return "".join(written)
