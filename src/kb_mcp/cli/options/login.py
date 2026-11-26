"""``login``'s declaration, from the sources that sign in; ``cli.commands.login`` runs it."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from kb_mcp.cli.domain.command import Command
from kb_mcp.cli.options._common import add_run_options

if TYPE_CHECKING:
    import argparse
    from collections.abc import Iterable, Mapping, Sequence

    from kb_mcp.sources.declaration import Source


# The sign-in that ``login`` named before each source signed in apart, whose sources it signed in.
FORMER = "atlassian"


def signing(arguments: argparse.Namespace, settings: Mapping[str, object]) -> tuple[Source, ...]:
    """Give the sources that ``login`` takes: the one named, else each one in use.

    Each of a connector that signs in, in the sources' order; one is in use when its
    first setting, what it covers, or its location is set. ``to_sign_in`` gives those
    that it signs in.
    """
    return tuple(
        each
        for each in arguments.sources
        if each.connector.login is not None
        and (
            each.name == arguments.source
            if arguments.source
            else settings[each.paths[0]] or settings[each.path(each.connector.location)]
        )
    )


def in_the_browser(arguments: argparse.Namespace, settings: Mapping[str, object]) -> dict[str, str]:
    """``login`` signs in in a browser, whatever a source's other settings say.

    Those of a source signed in, but its location, go unused; the location of another
    is not read.
    """
    taken = signing(arguments, settings)
    unused: dict[str, str] = {}
    for each in (each for each in arguments.sources if each.connector.login is not None):
        location = each.path(each.connector.location)
        if each in taken:
            browser = "login signs in in a browser"
            unused |= {path: browser for path in each.paths[1:] if path != location}
        else:
            unused[location] = f"{each.name} not signed in by this login"
    return unused


def to_sign_in(arguments: argparse.Namespace, settings: Mapping[str, object]) -> tuple[Source, ...]:
    """Give the sources that ``login`` signs in, or would but for their location.

    Those that ``signing`` takes but, when none is named, each that its connector's login
    leaves (``Connector.left_by_login``), such as one that signs in by an API token.
    """
    return tuple(
        each
        for each in signing(arguments, settings)
        if arguments.source
        or (left := each.connector.left_by_login) is None
        or not left(each, settings)
    )


def unlocated(sources: Iterable[Source], settings: Mapping[str, object]) -> dict[str, str]:
    """Give why each of ``sources`` cannot be signed in, by its name.

    Its location not set, such as its site, where it would sign in (``Source.unlocated``).
    Asked of those that ``login`` would sign in (``to_sign_in``), not of one that it
    leaves, as that one is not signed in either way.
    """
    return {each.name: why for each in sources if (why := each.unlocated(settings)) is not None}


def described(arguments: argparse.Namespace, settings: Mapping[str, object]) -> tuple[str, ...]:
    """Say each source that ``login`` would sign in that it will not, and why (``unlocated``)."""
    return tuple(
        f"source {name}: will not be signed in, {why}"
        for name, why in unlocated(to_sign_in(arguments, settings), settings).items()
    )


def nothing_to_sign_in(arguments: argparse.Namespace, settings: Mapping[str, object]) -> str | None:
    """Refuse a sign-in of no source, or of the one named whose location is not set: the first.

    First of all ``atlassian``, the sign-in that ``login`` named before each source signed in
    apart, unless a source takes that name: refused, naming the sources that sign in. A source
    taken by default whose location is not set is no refusal: the run signs in the others.
    """
    taken = signing(arguments, settings)
    names = [each.name for each in arguments.sources if each.connector.login is not None]
    gone = arguments.source == FORMER and FORMER not in names
    faults = [
        f"{FORMER}: gone; name a source, login {' or login '.join(names)}, or none"
        if gone
        else None,
        *(unlocated(taken, settings).values() if arguments.source else ()),
    ]
    faults.append(
        None
        if taken
        else "nothing to sign in: no source that signs in has what it covers or where it is"
        " set; set them, or name one: kb-mcp login <source>"
    )
    return next((fault for fault in faults if fault is not None), None)


def register(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
    sources: Sequence[Source],
) -> None:
    """Add ``login`` to the command, naming a source whose connector signs in, or none.

    It reads the data directory, and the location and first setting of each source of a
    connector that signs in, which say where and whether it is signed in to.
    """
    parser = subparsers.add_parser(
        "login",
        help="sign in once, in a Chrome window, for a source or each one configured",
        epilog=(
            "With --format json: a list, a row per site signed in to: site, the site; session,"
            " the folder that keeps its session."
        ),
    )
    actions, flags = add_run_options(parser, yes=True)
    signed = [each for each in sources if each.connector.login is not None]
    names = [each.name for each in signed]
    source = parser.add_argument(
        "source",
        nargs="?",
        choices=list(dict.fromkeys((*names, FORMER))),
        metavar=f"{{{','.join(names)}}}",
        help="the source whose site to sign in to; by default each one in use",
    )
    chrome = parser.add_argument(
        "--chrome", type=Path, help="Chrome's executable, where the chrome channel fails"
    )
    extensions = parser.add_argument(
        "--keep-extensions", action="store_true", help="let Chrome load extensions, for SSO"
    )
    parser.set_defaults(
        command=Command(
            "login",
            "kb_mcp.cli.commands.login",
            reads=(
                *(
                    path
                    for each in signed
                    for path in dict.fromkeys(
                        (
                            each.paths[0],
                            *(
                                []
                                if each.connector.location is None
                                else [each.path(each.connector.location)]
                            ),
                        )
                    )
                ),
                "data_dir",
            ),
            flags=flags,
            actions=(*actions, chrome, extensions, source),
            writes=True,
            unapplied=in_the_browser,
            described=described,
            refused=nothing_to_sign_in,
        )
    )
