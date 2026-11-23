"""``login``: sign in once in a Chrome window, and keep the session for later runs."""

from __future__ import annotations

import pkgutil
from typing import TYPE_CHECKING

import structlog

from kb_mcp.cli.options.login import to_sign_in, unlocated
from kb_mcp.config.domain.settings import values_of
from kb_mcp.kernel.names import ExitStatus, folded

if TYPE_CHECKING:
    import argparse

    from kb_mcp.config.domain.settings import Loaded
    from kb_mcp.kernel.names import Detail, Ending
    from kb_mcp.kernel.records import Record
    from kb_mcp.sources.declaration import Source


def run(
    arguments: argparse.Namespace, loaded: Loaded
) -> tuple[ExitStatus, tuple[Record, ...] | None]:
    """Sign in each source that ``to_sign_in`` gives; exit as their endings fold: 3, then 1.

    A source whose location is not set (``unlocated``), which the entry refused when it
    is named, is not signed in: an error, ``login.refused``, names it and why, and the
    run exits 1 at least. The sources of one connector's login are signed in by the run
    that it names, loaded by that path, so that this module imports neither the browser's
    adapter nor Playwright, in the order of their first source; the run says why a
    sign-in did not complete, the next is tried, and the run exits 3. The result holds
    the places signed in: none when the run exits 1 or 3 having signed in none.
    """
    values = values_of(loaded.settings)
    taken = to_sign_in(arguments, values)
    refused = unlocated(taken, values)
    for name, why in refused.items():
        structlog.get_logger().error("login.refused", source=name, reason=why)
    logins: dict[str, list[Source]] = {}
    for each in (each for each in taken if each.name not in refused):
        logins.setdefault(str(each.connector.login), []).append(each)
    signed: list[Record] = []
    endings: list[Ending] = ["failed" for _ in refused]
    for path, sources in logins.items():
        done, complete = pkgutil.resolve_name(path)(
            loaded.settings,
            tuple(sources),
            arguments.chrome,
            extensions=arguments.keep_extensions,
        )
        signed += done
        endings.append("done" if complete else "sign in again")
    status = folded(endings)
    return status, tuple(signed) if status == ExitStatus.OK else (tuple(signed) or None)


def text(signed: tuple[Record, ...], _detail: Detail) -> str:
    """Say each site signed in to, whose session is saved, or that none was."""
    return "".join(f"Signed in to {each.site}; the session is saved.\n" for each in signed) or (
        "Signed in to no site: each source signs in otherwise.\n"
    )
