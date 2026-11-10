"""``login``: sign in once in a Chrome window, and keep the session for later runs."""

from __future__ import annotations

import pkgutil
from typing import TYPE_CHECKING

from kb_mcp.cli.domain.echo import values_of
from kb_mcp.cli.options.login import signing
from kb_mcp.kernel.exit_status import ExitStatus

if TYPE_CHECKING:
    import argparse

    from kb_mcp.config.domain.settings import Loaded
    from kb_mcp.kernel.output import Detail
    from kb_mcp.kernel.record import Record
    from kb_mcp.sources.declaration import Source


def run(
    arguments: argparse.Namespace, loaded: Loaded
) -> tuple[ExitStatus, tuple[Record, ...] | None]:
    """Sign in each source that ``signing`` gives; exit 3 when a sign-in does not complete.

    The sources of one connector's login are signed in by the run that it names, loaded by
    that path, so that this module imports neither the browser's adapter nor Playwright,
    in the order of their first source; the run says why a sign-in did not complete, and
    none after it is tried.
    """
    taken = signing(arguments, values_of(loaded))
    logins: dict[str, list[Source]] = {}
    for each in taken:
        logins.setdefault(str(each.connector.login), []).append(each)
    signed: list[Record] = []
    for path, sources in logins.items():
        done = pkgutil.resolve_name(path)(
            loaded.settings,
            tuple(sources),
            arguments.chrome,
            extensions=arguments.keep_extensions,
            named=arguments.source is not None,
        )
        if done is None:
            return ExitStatus.SIGN_IN_AGAIN, None
        signed += done
    return ExitStatus.OK, tuple(signed)


def text(signed: tuple[Record, ...], _detail: Detail) -> str:
    """Say each site signed in to, whose session is saved, or that none was."""
    return "".join(f"Signed in to {each.site}; the session is saved.\n" for each in signed) or (
        "Signed in to no site: each source signs in otherwise.\n"
    )
