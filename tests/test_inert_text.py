"""Inert text: what the site or the mirror wrote shows on a terminal, and does nothing."""

from __future__ import annotations

import io
import unicodedata
from itertools import product

from rich.console import Console
from rich.text import Text

from atlassian_offline_mcp.observability.domain.inert_text import printable

# Criterion 6's title: an escape sequence, a bell, a right-to-left override and markup.
TITLE = "Release \x1b[31mnotes\x07 \N{RIGHT-TO-LEFT OVERRIDE}plan [red]draft"
INERT = "Release [31mnotes plan [red]draft"
# Unicode's Bidi_Control, read from its database rather than written out: the explicit
# embeddings, overrides and isolates by their class, then the three marks by name.
EXPLICIT = frozenset({"LRE", "RLE", "LRO", "RLO", "PDF", "LRI", "RLI", "FSI", "PDI"})
MARKS = frozenset(
    map(unicodedata.lookup, ("LEFT-TO-RIGHT MARK", "RIGHT-TO-LEFT MARK", "ARABIC LETTER MARK"))
)


def test_a_title_s_escape_bell_and_override_go_and_its_markup_stays_text() -> None:
    """ESC, BEL and U+202E go; [red] is left as written."""
    assert printable(TITLE, width=80) == INERT


def test_drawn_as_rich_text_on_a_colour_terminal_it_shows_as_written() -> None:
    """Rich writes no escape sequence of its own, and colours nothing."""
    out = io.StringIO()
    console = Console(file=out, force_terminal=True, color_system="truecolor", width=80)
    console.print(Text(printable(TITLE, width=80)))
    assert out.getvalue() == f"{INERT}\n"


def test_line_breaks_and_tabs_become_one_space_between_words() -> None:
    """A title over several lines shows on one, its words apart, no space at either end."""
    title = "\tFirst line\r\n\n  second\N{LINE SEPARATOR}third\x85 "
    assert printable(title, width=80) == "First line second third"


def test_a_longer_text_is_cut_to_the_width_its_last_character_an_ellipsis() -> None:
    """What goes takes no room, so a text that fits once it has gone is not cut."""
    assert printable("abcdef", width=4) == "abc…"
    assert printable("abcd", width=4) == "abcd"
    assert printable("ab\x1b\x1b\N{RIGHT-TO-LEFT OVERRIDE}cd", width=4) == "abcd"


def test_no_control_is_left_and_every_other_character_is_in_order() -> None:
    """Over every code point: controls (Cc) and Bidi_Control go, all else stays."""
    every = "".join(map(chr, range(0x110000)))
    shown = printable(every, width=len(every))
    removed = {
        char
        for char in every
        if unicodedata.category(char) == "Cc"
        or unicodedata.bidirectional(char) in EXPLICIT
        or char in MARKS
    }
    assert removed.isdisjoint(shown)
    assert [char for char in shown if not char.isspace()] == [
        char for char in every if char not in removed and not char.isspace()
    ]


def test_a_shown_text_fits_its_width_and_shows_again_unchanged() -> None:
    """Every text of up to four characters from a mixed alphabet, at widths 1 to 5."""
    alphabet = (
        "a",
        "\N{CJK UNIFIED IDEOGRAPH-754C}",
        " ",
        "\n",
        "\x1b",
        "\N{RIGHT-TO-LEFT OVERRIDE}",
    )
    for length in range(5):
        for chars in product(alphabet, repeat=length):
            text = "".join(chars)
            for width in range(1, 6):
                shown = printable(text, width=width)
                assert len(shown) <= width, (text, width)
                assert printable(shown, width=width) == shown, (text, width)
