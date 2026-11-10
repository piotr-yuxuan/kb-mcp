"""Names spelt once mean the same everywhere, and copies that a contract keeps apart agree.

``sources.atlassian.fetch.domain.names`` names the connectors and their document and scope
types, which the declarations, the fetch and the prepare read. Where a contract forbids an
import, the copy stays and is held here, as plan 052 settled; the server, the index, the
mirror and the command, which read no source (contract E), spell no source's name, as plan
056 settled; and
search, which the site's HTML is above (contract A), reads a page's id in its address. No
two classes or ``type`` aliases at the top of the package's modules share a name, so that
each entity has one name in the code.
"""

from __future__ import annotations

import ast
import re
from collections import Counter
from pathlib import Path
from urllib.parse import parse_qs

import pytest

from kb_mcp.search.domain.search import ID_IN_ADDRESS
from kb_mcp.sources.atlassian.prepare.adapters.site_html import (
    DOCUMENT_ADDRESSES,
    VIEW_PAGE,
    VIEW_PAGE_ID,
)
from kb_mcp.sources.registry import SOURCES

PACKAGE = Path(__file__).parents[1] / "src" / "kb_mcp"


@pytest.mark.parametrize("context", ["search", "mcp", "mirror", "cli"])
def test_past_the_mirror_no_code_spells_a_source_s_name(context: str) -> None:
    """Plan 056: a source is the user's to name; what reads documents tests a property.

    Not one of the registry's sources' names, quoted, in the code of these contexts.
    """
    names = "|".join(each.name for each in SOURCES)
    quoted = re.compile(rf"""(['"])({names})\1""")
    spelt = [
        f"{path.relative_to(PACKAGE)}:{number}"
        for path in sorted((PACKAGE / context).rglob("*.py"))
        for number, line in enumerate(path.read_text("utf-8").splitlines(), 1)
        if quoted.search(line)
    ]
    assert spelt == []


# Not a blog post's address without its date, /wiki/spaces/MFS/blog/40, which the site's
# HTML reads and search does not: a difference that plan 052 found and left, as its fix
# would change what search finds.
@pytest.mark.parametrize(
    "address",
    [
        "/wiki/spaces/MFS/pages/196845/Probe+complex",
        "/wiki/spaces/MFS/pages/196845",
        "/wiki/spaces/MFS/blog/2026/10/20/40/News",
        "/wiki/pages/viewpage.action?pageId=196845",
    ],
)
def test_search_reads_a_document_s_id_in_its_address_as_the_site_s_html_does(address: str) -> None:
    """A page's or a blog post's address on the site gives one id, to both alike."""
    page, _, query = address.partition("?")
    found = [match["id"] for pattern in DOCUMENT_ADDRESSES if (match := pattern.fullmatch(address))]
    found += parse_qs(query).get(VIEW_PAGE_ID, []) if page == VIEW_PAGE else []
    assert len(found) == 1
    assert ID_IN_ADDRESS.findall(address) == found


def test_no_two_classes_or_type_aliases_of_the_package_share_a_name() -> None:
    """At the top of the package's modules, each class and ``type`` alias has its own name."""
    defined: Counter[str] = Counter()
    for path in PACKAGE.rglob("*.py"):
        for node in ast.parse(path.read_bytes(), path).body:
            match node:
                case ast.ClassDef(name=name) | ast.TypeAlias(name=ast.Name(id=name)):
                    defined[name] += 1
    shared = {name for name, count in defined.items() if count > 1}
    assert [f"{name}: shared by two modules or more" for name in sorted(shared)] == []
