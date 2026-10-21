"""Evaluating the strategies on golden questions, with the tiny model (plan 011)."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from itertools import count
from typing import TYPE_CHECKING

import pytest

from atlassian_offline_mcp.adapters.embedding import CATALOGUE, ModelError
from atlassian_offline_mcp.app import evaluation
from atlassian_offline_mcp.app.evaluation import (
    EvaluationError,
    GoldenError,
    evaluate,
    read_golden,
    record,
    table,
)
from atlassian_offline_mcp.app.indexing import build_index
from atlassian_offline_mcp.app.meaning import Meaning
from atlassian_offline_mcp.app.tools import Library
from atlassian_offline_mcp.cli import main
from atlassian_offline_mcp.domain.evaluation import holm
from atlassian_offline_mcp.domain.settings import Settings
from tests.mirrors import MOMENT, fillers, issue, page, write
from tests.tiny_model import registered, tiny

if TYPE_CHECKING:
    from collections.abc import Callable
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
        ("- {id: q1, question: x, expected: ['4002']}\n" * 2, "an id given twice"),
        ("[]", "golden: no question"),
        ("- {id: q1, question: x, expected: []}", r"golden\[0\]: expected: at least one ref"),
        (
            "- {id: q1, question: x, expected: ['4002'], evidence: {'4003': y}}",
            r"golden\[0\]: evidence: only for an expected ref",
        ),
        ("- {id: q1, question: x, expected: ['4002'], groups: [all]}", r"groups: each once"),
        ("- {id: q1, question: x, expected: ['4002'], groups: [en, en]}", r"groups: each once"),
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
    assert "golden[0].expected: missing" in capsys.readouterr().err
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


def ticking() -> Callable[[], float]:
    """Return a clock that moves one second at each reading."""
    ticks = count()
    return lambda: float(next(ticks))


def test_a_ref_missing_from_the_index_evaluated_is_refused(data: Path) -> None:
    """Read against an index that holds a page, measured against one that lost it: refused."""
    questions = golden(data)
    (data / "docs" / "confluence" / "ENG" / "4003-words.md").unlink()
    settings = Settings(None, data, model="tiny")
    with pytest.raises(EvaluationError, match=r"tiny: q2: confluence/ENG/4003-words\.md is not"):
        evaluate(settings, questions, ["tiny"], ticking(), MOMENT)


def test_a_mode_by_meaning_that_falls_back_is_refused(data: Path, monkeypatch: MonkeyPatch) -> None:
    """Measuring words twice under another name would mislead: the run stops, naming why."""

    def broken(name: str, models: Path) -> object:
        message = f"{name}: does not load (Fail) {models.name}"
        raise ModelError(message)

    monkeypatch.setattr(evaluation, "Meaning", lambda models: Meaning(models, broken))
    settings = Settings(None, data, model="tiny")
    with pytest.raises(EvaluationError, match="tiny, semantic: Ranked by words alone"):
        evaluate(settings, golden(data), ["tiny"], ticking(), MOMENT)


def test_holm_adjusts_every_test_of_the_run(data: Path, monkeypatch: MonkeyPatch) -> None:
    """Two models, two modes each against lexical: four tests, adjusted together.

    The tests' p-values are set, small and distinct, so that adjusting per model (0.02,
    0.04, 0.06, 0.06) differs from adjusting the run (0.04, 0.06, 0.06, 0.06).
    """
    monkeypatch.setitem(CATALOGUE, "tiny2", tiny(data / "models", name="tiny2"))
    given = iter([1.0, 0.01, 0.02, 1.0, 0.03, 0.04])  # lexical, semantic, hybrid, twice
    monkeypatch.setattr(evaluation, "paired_test", lambda *_: next(given))
    settings = Settings(None, data, model="tiny")
    runs = evaluate(settings, golden(data), ["tiny", "tiny2"], ticking(), MOMENT)
    raw = [run.pvalues[mode] for run in runs for mode in ("semantic", "hybrid")]
    adjusted = [run.adjusted[mode] for run in runs for mode in ("semantic", "hybrid")]
    assert raw == [0.01, 0.02, 0.03, 0.04]
    assert adjusted == holm(raw) == pytest.approx([0.04, 0.06, 0.06, 0.06])
