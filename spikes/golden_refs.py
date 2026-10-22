"""Write plan 002's golden questions as a golden file for ``eval``, through a mirror's index.

Plan 002's set (``sandbox/golden.yaml``) names a page by its corpus key, a ticket by its
key, and an idea as ``jira/<name>``. This maps each to a ref that the mirror holds: a
page to the id of the mirrored page of that title in the space ``QM``, an idea to the
issue of that summary in the project ``PRB``, a ticket to its key. Each question's
groups are its overlap and its language; its evidence is carried over. It refuses to
write when a key does not map, so that no question is measured against a hole::

    uv run python spikes/golden_refs.py --data <data dir> --out <data dir>/eval/sandbox.yaml
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import yaml

from atlassian_offline_mcp.kernel.fields import Fields
from atlassian_offline_mcp.search.adapters.sqlite_index import reading
from atlassian_offline_mcp.search.domain.search import Filters

if TYPE_CHECKING:
    from collections.abc import Mapping

SANDBOX = Path(__file__).parents[1] / "sandbox"
SPACE, PROJECT = "QM", "PRB"


class UnmappedError(ValueError):
    """A key of the golden set that names nothing in the mirror."""


def front_matter(path: Path) -> dict[str, object]:
    """Read the YAML front matter of a corpus file."""
    head = path.read_text(encoding="utf-8").removeprefix("---\n").partition("\n---\n")[0]
    return yaml.safe_load(head)


def refs(
    questions: object, names: Mapping[str, str], found: Mapping[str, str]
) -> list[dict[str, object]]:
    """Map each question's keys to refs: by their corpus name, to what the mirror holds.

    ``names`` gives a page or idea key's title or summary; ``found`` gives the ref of the
    mirrored document of that title. A ticket key maps to itself. Raises UnmappedError,
    naming the key, when one does not map.
    """

    def ref(key: str) -> str:
        if key.startswith("ENG-"):
            return key
        if key not in names or names[key] not in found:
            message = f"{key}: not in the mirror"
            raise UnmappedError(message)
        return found[names[key]]

    return [
        {
            "id": item.text("id"),
            "question": item.text("question"),
            "expected": [ref(key) for key in item.texts("expected")],
            "partial": [ref(key) for key in item.texts("partial")],
            "groups": [item.text("overlap"), item.text("lang")],
            "evidence": {ref(key): evidence.text(key) for key in evidence.value},
        }
        for item in Fields.each(questions, "golden")
        for evidence in [item.object("evidence")]
    ]


def main() -> None:
    """Write the golden file for the mirror whose index is in ``--data``."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--data", type=Path, required=True, help="the data directory")
    parser.add_argument("--out", type=Path, required=True, help="the golden file to write")
    arguments = parser.parse_args()
    names = {
        path.relative_to(SANDBOX / "corpus").with_suffix("").as_posix(): str(
            front_matter(path)["title"]
        )
        for path in sorted((SANDBOX / "corpus").rglob("*.md"))
    }
    names |= {
        f"jira/{path.stem}": str(front_matter(path)["summary"])
        for path in sorted((SANDBOX / "jira" / "ideas").glob("*.md"))
    }
    with reading(arguments.data / "index.sqlite") as reader:
        pages = reader.listing(Filters(space=SPACE))
        found = {entry.front.title: entry.front.id for entry in pages}
        found |= {
            entry.front.title: str(entry.front.key)
            for entry in reader.listing(Filters(project=PROJECT))
        }
    questions = yaml.safe_load((SANDBOX / "golden.yaml").read_text(encoding="utf-8"))
    try:
        written = refs(questions, names, found)
    except UnmappedError as error:
        sys.stderr.write(f"not written: {error}\n")
        raise SystemExit(1) from None
    arguments.out.parent.mkdir(parents=True, exist_ok=True)
    arguments.out.write_text(yaml.safe_dump(written, allow_unicode=True, sort_keys=False), "utf-8")
    sys.stdout.write(f"{len(written)} questions written to {arguments.out}\n")


if __name__ == "__main__":
    main()
