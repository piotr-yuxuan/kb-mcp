"""``download``: fetch the documents of spaces and projects updated in a period."""

from __future__ import annotations

import argparse
import sys
import time
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from atlassian_offline_mcp.adapters.raw_store import StoreBusyError
from atlassian_offline_mcp.app.download import SIGN_IN_NEEDED, SOME_FAILED, Targets, download
from atlassian_offline_mcp.commands._options import add_settings_options, settings_of
from atlassian_offline_mcp.domain.content import PROJECT_KEY, SPACE_KEY
from atlassian_offline_mcp.domain.period import PeriodError, period
from atlassian_offline_mcp.domain.settings import SettingsError

if TYPE_CHECKING:
    from collections.abc import Callable

BAD_ARGUMENTS = 2
# The shell's own status for a run stopped by Ctrl-C.
INTERRUPTED = 130
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
    parser.add_argument("--since", required=True, help="7d, 2w, or an ISO date or time")
    parser.add_argument("--until", help="an ISO date or time, excluded; by default, now")
    parser.add_argument(
        "--max-file-mb", type=int, default=DEFAULT_MAX_FILE_MB, help="the largest file kept"
    )
    parser.set_defaults(run=run)


def run(arguments: argparse.Namespace) -> int:
    """Download; exit 0, 1 when something failed, 2 for bad input, 3 to sign in again.

    Spaces and projects not named on the command line come from the settings.
    """
    try:
        settings = settings_of(arguments)
        span = period(arguments.since, arguments.until, datetime.now(UTC))
    except (SettingsError, PeriodError) as error:
        sys.stderr.write(f"refused: {error}\n")
        return BAD_ARGUMENTS
    spaces = arguments.space or list(settings.spaces)
    projects = arguments.project or list(settings.projects)
    problems = [
        "site: not set; add it to the settings or pass --site" if settings.site is None else "",
        "nothing to download: name a --space or a --project" if not (spaces or projects) else "",
        "--max-file-mb: at least 1" if arguments.max_file_mb < 1 else "",
    ]
    for problem in filter(None, problems):
        sys.stderr.write(f"refused: {problem}\n")
        return BAD_ARGUMENTS
    targets = Targets(spaces, projects, span, arguments.max_file_mb * MEBIBYTE)
    try:
        outcome = download(settings, targets, lambda: datetime.now(UTC), time.sleep)
    except StoreBusyError:
        sys.stderr.write("another run is writing the raw store; try again once it ends\n")
        return SOME_FAILED
    except KeyboardInterrupt:
        sys.stderr.write(f"interrupted; the counts so far are in {settings.runs}\n")
        return INTERRUPTED
    for what, number in sorted(outcome.report.counts.items()):
        sys.stdout.write(f"{what}: {number}\n")
    for target in outcome.failed_targets:
        sys.stderr.write(f"{target}\n")
    if outcome.status == SIGN_IN_NEEDED:
        sys.stderr.write("sign-in needed: run atlassian-offline-mcp login\n")
    return outcome.status
