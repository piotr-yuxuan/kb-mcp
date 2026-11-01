"""``fetch`` and ``prepare``: each source taken, its role in turn, a row each."""

from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import structlog

from kb_mcp.cli.app.sources import SourcesRefusedError, run_each
from kb_mcp.cli.domain.sources import FETCH, PREPARE, chosen, given
from kb_mcp.cli.domain.summary import values_of
from kb_mcp.kernel.exit_status import ExitStatus
from kb_mcp.sources.roles import Run

if TYPE_CHECKING:
    import argparse

    from kb_mcp.cli.domain.rows import Ran
    from kb_mcp.config.domain.settings import Loaded
    from kb_mcp.kernel.output import Summary

# What each command's refusal is called, written out as every event's name is.
REFUSED = {FETCH: "fetch.refused", PREPARE: "prepare.refused"}


def run(arguments: argparse.Namespace, loaded: Loaded) -> tuple[ExitStatus, Ran | None]:
    """Run the role of each source taken; exit as the rows rank, 2 when refused.

    The entry refused what it could before asking. Each source taken is run with its
    table, its account's, and, in a fetch, its options' values by flag. A role that does
    not load, or what a role's ``preflight`` refuses, such as an --until before --since, or
    a work log that is not a folder, is refused here, before any row runs, an error,
    ``fetch.refused`` or ``prepare.refused``. Each row's problems are said as it runs, by
    place and reason, never content.
    """
    settings = loaded.settings
    step = arguments.command.name
    taken, _ = chosen(arguments, values_of(loaded))
    runs = [
        Run(
            declared=declared,
            settings=settings,
            table=getattr(settings.sources, declared.name),
            account=(
                None
                if declared.account is None
                else getattr(settings.accounts, declared.account.name)
            ),
            options=given(arguments, declared.options) if step == FETCH else {},
            now=lambda: datetime.now(UTC),
            sleep=time.sleep,
            dry_run=arguments.dry_run,
        )
        for declared in taken
    ]
    try:
        ran = run_each(step, runs, dry_run=arguments.dry_run)
    except SourcesRefusedError as error:
        structlog.get_logger().error(REFUSED[step], reason=str(error))
        return ExitStatus.REFUSED, None
    return ran.exit_status, ran


def text(ran: Ran, summary: Summary) -> str:
    """Write a row per source, how it ended, then its result's own text, indented."""
    written: list[str] = []
    for row in ran.sources:
        written.append(f"{row.source}: {row.outcome}\n")
        if row.result is not None:
            written.extend(f"  {line}\n" for line in row.result.text(summary).splitlines())
    return "".join(written)
