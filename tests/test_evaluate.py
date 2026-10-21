"""Evaluating the strategies on golden questions, with the tiny model (plan 011)."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from itertools import count
from typing import TYPE_CHECKING

import pytest

from atlassian_offline_mcp.app.evaluation import GoldenError, evaluate, read_golden, record, table
from atlassian_offline_mcp.app.indexing import build_index
from atlassian_offline_mcp.app.tools import Library
from atlassian_offline_mcp.cli import main
from atlassian_offline_mcp.domain.settings import Settings
from tests.mirrors import MOMENT, fillers, issue, page, write
from tests.tiny_model import registered

if TYPE_CHECKING:
    from pathlib import Path

    from _pytest.capture import CaptureFixture
    from _pytest.monkeypatch import MonkeyPatch

GOLDEN = """
- id: q1
  question: "vacation lunch"
  expected: ["4002"]
  groups: [paraphrase, en]
  evidence: {"4002": "leave for a meal"}
- id: q2
  question: "revert release"
  expected: ["4003"]
  partial: ["https://example.atlassian.net/wiki/spaces/ENG/pages/4002/x"]
  groups: [keyword]
- id: q3
  question: "PROJ-7 upgrade"
  expected: [PROJ-7]
"""
REFUSED = 2


@pytest.fixture
def data(tmp_path: Path, monkeypatch: MonkeyPatch) -> Path:
    """Give a data directory with a mirror, its index, and the tiny model pulled."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    docs = tmp_path / "data" / "docs"
    fillers(docs)
    write(docs, page("4002", "Holiday canteen"), "# Holiday canteen\n\nLeave for a **meal**.\n")
    write(docs, page("4003", "Words"), "revert release\n")
    write(docs, issue("PROJ-7", "Kafka upgrade"))
    build_index(docs, tmp_path / "data" / "index.sqlite", MOMENT)
    registered(tmp_path / "data" / "models", monkeypatch)
    return tmp_path / "data"


def golden(data: Path, text: str = GOLDEN) -> list:
    """Read golden questions against the data directory's mirror."""
    return read_golden(text, Library(data / "index.sqlite", data / "docs").resolve)


@pytest.mark.parametrize(
    ("text", "named"),
    [
        ("- {id: q1, question: x, expected: ['4002'], weight: 2}", r"golden\[0\]: unknown field"),
        ("- {id: q1, question: x}", r"golden\[0\]\.expected"),
        ("- {id: q1, question: x, expected: ['9999']}", r"golden\[0\]: '9999' is not mirrored"),
        ("- {id: q1, question: x, expected: ['4002'], partial: [PROJ-8]}", "PROJ-8"),
        (f"- {{id: q1, question: {'x' * 501}, expected: ['4002']}}", r"question: at most 500"),
        ("- {id: q1, question: x, expected: ['4002']}\n" * 2, "an id is given twice"),
        ("{id: q1}", "golden: expected a list"),
        ("- [unclosed", "not a golden file"),
    ],
)
def test_a_golden_file_is_refused_by_name(data: Path, text: str, named: str) -> None:
    """Each fault names where it is; nothing is half-read."""
    with pytest.raises(GoldenError, match=named):
        golden(data, text)


def test_refs_resolve_as_read_takes_them(data: Path) -> None:
    """A page id, an address and an issue key all name their mirrored path."""
    q1, q2, q3 = golden(data)
    assert q1.expected == ("confluence/ENG/4002-holiday-canteen.md",)
    assert q2.partial == q1.expected
    assert q3.expected == ("jira/PROJ/PROJ-7.md",)
    assert q1.evidence == {q1.expected[0]: "leave for a meal"}


def test_meaning_answers_the_paraphrase_that_words_miss(data: Path) -> None:
    """Measured as search ranks: the paraphrase found by meaning only; the key first in all."""
    settings = Settings(None, data, model="tiny")
    ticks = count()
    [run] = evaluate(settings, golden(data), ["tiny"], lambda: float(next(ticks)), MOMENT)
    assert run.per["lexical"]["q1"].reciprocal_rank == 0.0
    assert run.per["semantic"]["q1"].reciprocal_rank == 1.0
    assert run.per["hybrid"]["q1"].section == 1.0
    assert all(run.per[mode]["q3"].success == 1.0 for mode in ("lexical", "semantic", "hybrid"))
    assert set(run.groups["semantic"]) == {"all", "paraphrase", "en", "keyword"}
    assert run.embedded > 0
    assert set(run.adjusted) == {"semantic", "hybrid"}
    assert "| semantic | paraphrase | 1.000 | 1.000 |" in table([run])


def test_the_command_keeps_numbers_and_ids_but_no_question(
    data: Path, capsys: CaptureFixture[str]
) -> None:
    """``eval`` prints its tables, and its results file holds no question's text."""
    (data / "golden.yaml").write_text(GOLDEN, encoding="utf-8")
    options = ["--config", str(data / "none.toml"), "--data-dir", str(data)]
    assert main(["eval", str(data / "golden.yaml"), *options]) == 0
    out = capsys.readouterr().out
    assert "## tiny" in out
    [results] = (data / "eval" / "results").glob("*.json")
    kept = results.read_text(encoding="utf-8")
    assert "vacation" not in kept
    assert "release" not in kept
    assert json.loads(kept)["runs"][0]["ranks"]["semantic"]["q1"] == [1]
    assert main(["eval", str(data / "golden.yaml"), *options]) == 0
    second = max((data / "eval" / "results").glob("*.json"))
    assert json.loads(second.read_text(encoding="utf-8"))["runs"][0]["embedded"] == 0


def test_a_refused_golden_file_exits_2(data: Path, capsys: CaptureFixture[str]) -> None:
    """The command names the fault and evaluates nothing."""
    (data / "golden.yaml").write_text("- {id: q1}", encoding="utf-8")
    options = ["--config", str(data / "none.toml"), "--data-dir", str(data)]
    assert main(["eval", str(data / "golden.yaml"), *options]) == REFUSED
    assert "golden[0].question: missing" in capsys.readouterr().err
    assert not (data / "eval").exists()


def test_the_record_names_its_test_and_golden_file() -> None:
    """The seed and samples of the test, and the golden file by hash, are kept."""
    kept = record([], "golden text", datetime(2026, 10, 21, tzinfo=UTC))
    assert kept["test"] == {
        "kind": "paired randomisation, two-sided",
        "samples": 10_000,
        "seed": 11,
    }
    assert re.fullmatch(r"[0-9a-f]{64}", str(kept["golden_sha256"]))
