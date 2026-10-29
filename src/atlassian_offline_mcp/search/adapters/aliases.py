"""The alias file: names as some source writes them, each with the person it means.

The user may write ``<data>/aliases.toml``, each line a name, then a name or a person's
id; the program never writes it. Each build of the index reads it again, so a change
takes effect at the next. Only this module reads the file, and only to check it:
``people.joined`` decides what each alias joins, and which change nothing.
"""

from __future__ import annotations

import tomllib
from typing import TYPE_CHECKING

from atlassian_offline_mcp.search.domain.people import name_key

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

# The most characters of a name or a target: a name, never a text.
LONGEST = 200
# What makes a name or a target unusable, each with what a refusal says of it. A line
# break is any of str.splitlines' line boundaries, as the front matter refuses them.
REFUSED: tuple[tuple[Callable[[str], bool], str], ...] = (
    (lambda text: not text.strip(), "is empty"),
    (lambda text: text.splitlines() != [text], "holds a line break"),
    (lambda text: len(text) > LONGEST, f"is longer than {LONGEST} characters"),
)


class AliasFileError(ValueError):
    """An alias file that cannot be read as aliases: the message names it and the alias."""


def read_aliases(path: Path) -> dict[str, str]:
    """Read each alias's name and target as the file writes them, in its order.

    No file holds no alias. Raises AliasFileError, naming the file and the alias, for a
    file that is not UTF-8 TOML; a target that is a table, or not text; a name or a
    target that is empty, white space alone, holds a line break or is longer than
    LONGEST; and two names of one key, which the join would take for one name. Raises
    OSError for a file that cannot be read, such as a folder. A name is quoted as
    Python writes it, so that a refusal is one line.
    """
    try:
        values = tomllib.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as error:
        message = f"{path}: not UTF-8 TOML ({error})"
        raise AliasFileError(message) from error
    names: dict[str, str] = {}  # each name's key, and the name as written
    for name, target in values.items():
        if not isinstance(target, str):
            what = "a table" if isinstance(target, dict) else "not text"
            message = f"{path}: {name!r}: its target is {what}; write a name or an id in quotes"
            raise AliasFileError(message)
        said = [
            f"{side} {problem}"
            for side, text in (("the name", name), ("its target", target))
            for refused, problem in REFUSED
            if refused(text)
        ]
        if said:
            message = f"{path}: {name!r}: {said[0]}"
            raise AliasFileError(message)
        key = name_key(name)
        if key in names:
            message = f"{path}: {names[key]!r} and {name!r} are one name: keep one alias"
            raise AliasFileError(message)
        names[key] = name
    return values
