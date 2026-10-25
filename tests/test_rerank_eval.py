"""Reranking measured: plan 022's bar on hand-built numbers, and eval-rerank end to end."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from atlassian_offline_mcp.cli.main import main
from atlassian_offline_mcp.evaluation.app.evaluation import read_golden
from atlassian_offline_mcp.evaluation.app.reranked import Counted
from atlassian_offline_mcp.evaluation.domain import reranking as bar
from atlassian_offline_mcp.evaluation.domain.reranking import Depthed, default_reranking
from atlassian_offline_mcp.kernel.exit_status import ExitStatus
from atlassian_offline_mcp.kernel.reranking import BAR_DEPTHS
from atlassian_offline_mcp.mcp.app.tools import Library
from atlassian_offline_mcp.search.adapters.reranking import Reranked
from atlassian_offline_mcp.search.app.meaning import Meaning
from tests.endpoint import Reranks, Scripted, connector, serving
from tests.reference import Emitted, undocumented
from tests.test_evaluate import GOLDEN, data

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    from _pytest.capture import CaptureFixture
    from _pytest.monkeypatch import MonkeyPatch

    from tests.conftest import InMemory

__all__ = ["data"]  # the fixture of test_evaluate, used here

QUESTIONS = 30
GROUPS = {"identifier": 0.600, "keyword": 0.800}


def arm(score: float, tail_ms: int = 900, **groups: float) -> Depthed:
    """Make an arm whose every question scores ``score``, its groups as given or as GROUPS."""
    return Depthed((score,) * QUESTIONS, GROUPS | groups, tail_ms)


PLAIN = arm(0.0)


def depths(**arms: Depthed) -> dict[int, Depthed]:
    """Key arms by depth, given as ``d10=...``."""
    return {int(name[1:]): each for name, each in arms.items()}


def test_every_depth_gaining_on_every_question_qualifies_and_the_smallest_is_taken() -> None:
    """A gain on all 30 questions is significant after Holm; equal arms: the cheapest."""
    gaining = arm(1.0)
    decision = default_reranking(PLAIN, depths(d10=gaining, d20=gaining, d30=gaining, d50=gaining))
    assert decision is not None
    assert [verdict.qualifies for verdict in decision.verdicts] == [True] * 4
    assert decision.depth == BAR_DEPTHS[0]


@pytest.mark.parametrize(("loss", "holding"), [(0.050, [True] * 4), (0.051, [False] * 4)])
def test_a_group_may_lose_0_05_and_no_more(loss: float, holding: list[bool]) -> None:
    """Compared as reported, to three decimals."""
    lost = arm(1.0, identifier=GROUPS["identifier"] - loss)
    decision = default_reranking(PLAIN, depths(d10=lost, d20=lost, d30=lost, d50=lost))
    assert decision is not None
    assert [verdict.holds for verdict in decision.verdicts] == holding


@pytest.mark.parametrize(("tail_ms", "chosen"), [(5000, BAR_DEPTHS[0]), (5001, None)])
def test_a_search_may_take_5_seconds_at_the_95th_percentile(
    tail_ms: int, chosen: int | None
) -> None:
    """The user's bound, in whole milliseconds; slower at every depth, reranking stays off."""
    timed = arm(1.0, tail_ms)
    decision = default_reranking(PLAIN, depths(d10=timed, d20=timed, d30=timed, d50=timed))
    assert decision is not None
    assert [verdict.fast for verdict in decision.verdicts] == [chosen is not None] * 4
    assert decision.depth == chosen


def scripted_tests(monkeypatch: MonkeyPatch, pvalues: dict[tuple[float, float], float]) -> None:
    """Have the bar's paired test give these p-values, by the two arms' first scores."""

    def test(before: Sequence[float], after: Sequence[float]) -> float:
        return pvalues.get((before[0], after[0]), 1.0)

    monkeypatch.setattr(bar, "paired_test", test)


@pytest.mark.parametrize(("pvalue", "gains"), [(0.0125, False), (0.0124, True)])
def test_an_adjusted_p_of_0_05_is_no_gain(
    monkeypatch: MonkeyPatch, pvalue: float, *, gains: bool
) -> None:
    """Holm multiplies the smallest of four by 4: 0.05 is no gain, 0.0496 is one."""
    scripted_tests(monkeypatch, {(0.0, 0.4): pvalue})
    decision = default_reranking(
        PLAIN, depths(d10=arm(0.4), d20=arm(0.0), d30=arm(0.0), d50=arm(0.0))
    )
    assert decision is not None
    first = decision.verdicts[0]
    assert round(first.adjusted, 4) == round(pvalue * len(BAR_DEPTHS), 4)
    assert first.beats is gains
    assert decision.depth == (BAR_DEPTHS[0] if gains else None)


def test_the_smallest_depth_not_shown_worse_than_the_best_is_taken(
    monkeypatch: MonkeyPatch,
) -> None:
    """20 the best; 10 not shown lower than it, taken; then 10 shown lower, 20 taken."""
    gains = {(0.0, 0.5): 0.001, (0.0, 0.6): 0.001, (0.0, 0.55): 0.001, (0.0, 0.52): 0.001}
    arms = depths(d10=arm(0.5), d20=arm(0.6), d30=arm(0.55), d50=arm(0.52))
    scripted_tests(monkeypatch, gains | {(0.6, 0.5): 0.2})
    decision = default_reranking(PLAIN, arms)
    assert decision is not None
    assert decision.depth == BAR_DEPTHS[0]
    scripted_tests(monkeypatch, gains | {(0.6, 0.5): 0.01})
    decision = default_reranking(PLAIN, arms)
    assert decision is not None
    assert decision.depth == BAR_DEPTHS[1]


def test_another_set_of_depths_gets_no_verdict() -> None:
    """The bar decides on its four depths alone."""
    assert default_reranking(PLAIN, depths(d10=arm(1.0), d20=arm(1.0))) is None


def test_with_no_depth_qualifying_reranking_stays_off_each_clause_said() -> None:
    """No gain anywhere: every verdict given, none qualifying, no depth."""
    decision = default_reranking(PLAIN, depths(d10=PLAIN, d20=PLAIN, d30=PLAIN, d50=PLAIN))
    assert decision is not None
    assert [verdict.depth for verdict in decision.verdicts] == list(BAR_DEPTHS)
    assert [verdict.beats for verdict in decision.verdicts] == [False] * 4
    assert decision.depth is None


def test_counted_asks_a_query_s_texts_once_and_sums_the_tokens() -> None:
    """Ask's request repeats search's: kept; tokens summed, None once an answer counts none."""
    answers = iter([Reranked([1.0], 3), Reranked([1.0, 0.0], None), Reranked([0.5], 4)])
    asked: list[tuple[str, ...]] = []

    def score(_query: str, texts: Sequence[str]) -> Reranked:
        asked.append(tuple(texts))
        return next(answers)

    counted = Counted(score)
    assert counted("q", ["a"]) == counted("q", ["a"])
    assert (asked, counted.tokens) == ([("a",)], 3)
    counted("q", ["a", "b"])
    counted("r", ["a"])
    assert counted.tokens is None
    assert len(asked) == len(["a", "a b", "r"])


def evaluated(data: Path, url: str, rerank_url: str, *more: str) -> int:
    """Run eval-rerank on the golden file, by meaning and words, at depths 2 and 3."""
    golden = data / "golden.yaml"
    golden.write_text(GOLDEN, encoding="utf-8")
    config = data.parent / "config.toml"
    config.write_text(
        f'model = "tiny"\nembedding_url = "{url}"\nsearch_mode = "hybrid"\n'
        f'[rerank]\nurl = "{rerank_url}"\n',
        encoding="utf-8",
    )
    options = ["--config", str(config), "--data-dir", str(data), "--depth", "2", "--depth", "3"]
    return main(["eval-rerank", "--yes", str(golden), *options, *more])


def test_each_depth_asks_once_a_question_and_the_results_keep_no_question(
    data: Path, capsys: CaptureFixture[str]
) -> None:
    """One request a question and depth, sized by it; numbers and ids kept, no text."""
    answers = Reranks()
    with serving(Scripted()) as url, serving(answers) as rerank_url:
        assert evaluated(data, url, rerank_url) == 0
    out, err = capsys.readouterr()
    assert "reranking: depths 2, 3, in the hybrid mode" in err
    assert "No verdict: the bar decides on depths 10, 20, 30, 50 alone." in out
    sizes = [len(request["documents"]) for request in answers.asked]
    assert sizes == [2, 2, 2, 3, 3, 3]
    [results] = (data / "eval" / "results").glob("*-rerank.json")
    kept = results.read_text(encoding="utf-8")
    assert "vacation" not in kept
    assert "release" not in kept
    record = json.loads(kept)
    assert [each["depth"] for each in record["arms"]] == [0, 2, 3]
    assert record["served"] == ["qwen3-reranker-0.6b"]
    assert record["decision"] is None
    assert all(each["tokens"] for each in record["arms"][1:])


def test_recall_at_n_is_the_share_of_expected_documents_in_the_first_stage_s_first_n(
    data: Path, capsys: CaptureFixture[str]
) -> None:
    """Recall@2 and @3 of the order not reranked: the first stage, searched again alone."""
    with serving(Scripted()) as url, serving(Reranks()) as rerank_url:
        assert evaluated(data, url, rerank_url, "--format", "json") == 0
    record = json.loads(capsys.readouterr().out)
    questions = read_golden(GOLDEN, Library(data / "index.sqlite", data / "docs").resolve)
    index = data / "eval" / "indexes" / "windows" / "tiny.sqlite"
    plain = Library(index, data / "docs", Meaning(connector()), "hybrid")
    found = {
        size: [
            {shown.path for shown in plain.ranked(question.text, "hybrid", size)[0]}
            for question in questions
        ]
        for size in (2, 3)
    }
    expected = {
        str(size): sum(
            len(set(question.expected) & first) / len(question.expected)
            for question, first in zip(questions, found[size], strict=True)
        )
        / len(questions)
        for size in (2, 3)
    }
    assert record["arms"][0]["recall"] == pytest.approx(expected)


def test_an_arm_that_falls_back_stops_the_run_naming_the_depth(
    data: Path, capsys: CaptureFixture[str]
) -> None:
    """A refusal, which an evaluation does not retry, leaves a search not reranked."""
    with serving(Scripted()) as url, serving(Reranks(statuses=[400])) as rerank_url:
        assert evaluated(data, url, rerank_url) == ExitStatus.FAILED
    err = capsys.readouterr().err
    assert "depth 2, q1" in err
    assert "Not reranked" in err


def test_eval_rerank_records_as_documented(telemetry: InMemory, data: Path) -> None:
    """Measured; refused by the reranking server; a golden file refused."""
    emitted = Emitted()
    with (
        serving(Scripted()) as url,
        serving(Reranks()) as rerank_url,
        emitted.gathering(telemetry, "eval-rerank"),
    ):
        assert evaluated(data, url, rerank_url) == 0
    with (
        serving(Scripted()) as url,
        serving(Reranks(statuses=[400])) as rerank_url,
        emitted.gathering(telemetry, "eval-rerank"),
    ):
        assert evaluated(data, url, rerank_url) == ExitStatus.FAILED
    (data / "golden.yaml").write_text("[]", encoding="utf-8")
    with emitted.gathering(telemetry, "eval-rerank"):
        refused = ["eval-rerank", "--yes", str(data / "golden.yaml")]
        assert main([*refused, "--data-dir", str(data)]) == ExitStatus.REFUSED
    assert undocumented("eval-rerank", emitted) == []
