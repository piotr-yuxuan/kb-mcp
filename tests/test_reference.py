"""The reference of commands and settings is what the code generates, and names src's variables.

Plan 020: ``tests.reference_pages`` writes ``docs/reference/commands.md`` from the
parser and ``docs/reference/settings.md`` from the settings' model; each page must be,
byte for byte, what it gives now. A variable that a run reads besides the settings is
written there by hand, so each all-capitals text of ``src/`` with an underscore, which
may name one, must be on the settings page, or below with why it names none. The
variables that libraries read are not found so: the page names by hand those that change
a run.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from tests.reference_pages import PAGES, REGENERATE

ROOT = Path(__file__).parents[1]
SETTINGS_PAGE = "docs/reference/settings.md"
# Text that may name an environment variable: capitals and digits, with an underscore.
CAPITALS = re.compile(r"[A-Z][A-Z0-9]*_[A-Z0-9_]*")
# Such texts of src/ that name no variable a run reads, each with why.
NON_VARIABLES = {
    "API_TOKEN": "the end of KB_MCP_API_TOKEN, written after its prefix",
    "ARCHIVE_OLPATH": "a property that org writes when it archives a subtree, the work log reads",
    "EXCLUDE_TAGS": "a setting of an org file, #+EXCLUDE_TAGS:, that the work log reads",
    "SELECT_TAGS": "a setting of an org file, #+SELECT_TAGS:, that the work log reads",
    "SEQ_TODO": "a setting of an org file, #+SEQ_TODO:, that the work log reads",
    "TYP_TODO": "a setting of an org file, #+TYP_TODO:, that the work log reads",
}


@pytest.mark.parametrize("name", list(PAGES))
def test_each_reference_page_is_what_the_code_generates(name: str) -> None:
    """The page on disk is the generated one; else it says how to regenerate it."""
    page = f"docs/reference/{name}"
    written = (ROOT / page).read_text("utf-8")
    assert written == PAGES[name](), f"{page} is not what the code generates: run {REGENERATE}"


def test_the_settings_page_names_each_variable_that_the_code_may_read() -> None:
    """Each all-capitals text of ``src/`` with an underscore is a variable on the page.

    Or a prefix of some, such as ``OTEL_``; else it is one of ``NON_VARIABLES``.
    """
    page = (ROOT / SETTINGS_PAGE).read_text("utf-8")
    found = {
        node.value: module.relative_to(ROOT).as_posix()
        for module in sorted((ROOT / "src").rglob("*.py"))
        for node in ast.walk(ast.parse(module.read_bytes(), module))
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and CAPITALS.fullmatch(node.value)
    }
    unnamed = [
        f"{module}: {text} is not on {SETTINGS_PAGE}: add it to OTHER_VARIABLES in"
        f" tests/reference_pages.py, then run {REGENERATE}; or, naming no variable, to"
        " NON_VARIABLES with why"
        for text, module in sorted(found.items())
        if f"`{text}`" not in page and text not in NON_VARIABLES
    ]
    assert unnamed == []
