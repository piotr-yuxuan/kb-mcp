"""``download``: fetch the documents of spaces and projects updated in a period."""

from __future__ import annotations

import argparse
import sys
import time
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from atlassian_offline_mcp.cli.commands._options import add_settings_options, settings_of
from atlassian_offline_mcp.config.domain.settings import SettingsError
from atlassian_offline_mcp.kernel.content import PROJECT_KEY, SPACE_KEY
from atlassian_offline_mcp.kernel.exit_status import ExitStatus
from atlassian_offline_mcp.kernel.fields import RepresentationError
from atlassian_offline_mcp.sources.atlassian.adapters.raw_store import StoreBusyError
from atlassian_offline_mcp.sources.atlassian.app.download import Targets, download, plan
from atlassian_offline_mcp.sources.atlassian.domain.period import PeriodError, length, moment

if TYPE_CHECKING:
    from collections.abc import Callable

    from atlassian_offline_mcp.config.domain.settings import Settings

MEBIBYTE = 1024 * 1024
DEFAULT_MAX_FILE_MB = 50


def key_of(pattern_name: str) -> Callable[[str], str]:
    """Return an argparse type that accepts a space key or a project key."""
    pattern = SPACE_KEY if pattern_name == "space" else PROJECT_KEY

    def check(text: str) -> str:
        if not pattern.fullmatch(text):
            message = f"not a {pattern_name} key: {text!r}"
            raise argparse.ArgumentTypeError(message)
        return text

    return check


def register(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """Add ``download`` to the command."""
    parser = subparsers.add_parser(
        "download", help="download what changed in a period, with its files"
    )
    add_settings_options(parser)
    parser.add_argument(
        "--space", action="append", type=key_of("space"), help="a space key; repeat for more"
    )
    parser.add_argument(
        "--project", action="append", type=key_of("project"), help="a project key; repeat"
    )
    parser.add_argument(
        "--since", help="7d, 6mo, or an ISO date; by default, the start of what is covered"
    )
    parser.add_argument("--back", help="reach this much further back (6mo, 1y), or all")
    parser.add_argument("--until", help="an ISO date or time, excluded; by default, now")
    parser.add_argument(
        "--plan", action="store_true", help="say what a run would fetch, and fetch nothing"
    )
    parser.add_argument(
        "--max-file-mb", type=int, default=DEFAULT_MAX_FILE_MB, help="the largest file kept"
    )
    parser.set_defaults(run=run)


class RefusedOptionsError(ValueError):
    """Options that cannot make a run; the message names the option or setting."""


def targets_of(arguments: argparse.Namespace, settings: Settings, now: datetime) -> Targets:
    """Read what a run downloads from the options, else the settings; refuse what cannot run.

    Raises RefusedOptionsError or PeriodError, naming the option at fault.
    """
    spaces = arguments.space or list(settings.spaces)
    projects = arguments.project or list(settings.projects)
    for problem, refused in (
        ("site: not set; add it to the settings or pass --site", settings.site is None),
        ("nothing to download: name a --space or a --project", not (spaces or projects)),
        ("--max-file-mb: at least 1", arguments.max_file_mb < 1),
    ):
        if refused:
            raise RefusedOptionsError(problem)
    return Targets(
        spaces,
        projects,
        arguments.max_file_mb * MEBIBYTE,
        since=moment(arguments.since, now, "--since") if arguments.since else None,
        back=length(arguments.back, "--back") if arguments.back else None,
        until=moment(arguments.until, now, "--until") if arguments.until else None,
    )


def run(arguments: argparse.Namespace) -> ExitStatus:
    """Download; exit 0, 1 when something failed, 2 for bad input, 3 to sign in again.

    Spaces and projects not named on the command line come from the settings; without
    --since, each catches up from the start of what earlier runs covered.
    """
    try:
        settings = settings_of(arguments)
        targets = targets_of(arguments, settings, datetime.now(UTC))
        act = plan if arguments.plan else download
        outcome = act(settings, targets, lambda: datetime.now(UTC), time.sleep)
    except (SettingsError, PeriodError, RefusedOptionsError, RepresentationError) as error:
        sys.stderr.write(f"refused: {error}\n")
        return ExitStatus.REFUSED
    except StoreBusyError:
        sys.stderr.write("another run is writing the raw store; try again once it ends\n")
        return ExitStatus.FAILED
    except KeyboardInterrupt:
        sys.stderr.write(f"interrupted; the counts so far are in {settings.runs}\n")
        return ExitStatus.INTERRUPTED
    for what, number in sorted(outcome.report.counts.items()):
        sys.stdout.write(f"{what}: {number}\n")
    for target in outcome.failed_targets:
        sys.stderr.write(f"{target}\n")
    if outcome.status == ExitStatus.SIGN_IN_AGAIN:
        sys.stderr.write("sign-in needed: run atlassian-offline-mcp login\n")
    return outcome.status or ExitStatus.OK
