"""Reranking measured: plan 022's bar on hand-built numbers, and eval-rerank end to end."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from kb_mcp.cli.main import main
from kb_mcp.evaluation.app import reranked as measuring
from kb_mcp.evaluation.app.evaluation import read_golden
from kb_mcp.evaluation.app.reranked import Counted
from kb_mcp.evaluation.domain import reranking as bar
from kb_mcp.evaluation.domain.reranking import (
    BarVerdict,
    Decision,
    Depthed,
    default_reranking,
)
from kb_mcp.kernel.exit_status import ExitStatus
from kb_mcp.kernel.reranking import BAR_DEPTHS
from kb_mcp.mcp.app.tools import Library
from kb_mcp.search.adapters.reranking import Reranked
from kb_mcp.search.adapters.sqlite_index import SqliteIndex
from kb_mcp.search.app.meaning import Meaning
from tests.endpoint import Reranks, Scripted, connect_scripted, serving
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
SAMPLE = 2  # of the golden file's three questions
GROUPS = {"identifier": 0.600, "keyword": 0.800}


def arm(score: float, tail_ms: int = 900, **groups: float) -> Depthed:
    """Make an arm whose every question scores ``score``, its groups as given or as GROUPS."""
    return Depthed(reciprocal=(score,) * QUESTIONS, groups=GROUPS | groups, tail_ms=tail_ms)


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


@pytest.mark.parametrize("group", sorted(GROUPS))
@pytest.mark.parametrize(
    ("before", "after", "loss", "holding"),
    [(0.6004, 0.5496, 0.050, True), (0.6006, 0.5504, 0.051, False)],
)
def test_a_group_may_lose_0_05_as_reported_and_no_more(
    group: str, before: float, after: float, loss: float, *, holding: bool
) -> None:
    """The loss between the means as the table shows them: 0.600 to 0.550, 0.601 to 0.550."""
    lost = arm(1.0, **{group: after})
    decision = default_reranking(
        arm(0.0, **{group: before}), depths(d10=lost, d20=lost, d30=lost, d50=lost)
    )
    assert decision is not None
    assert [verdict.losses[group] for verdict in decision.verdicts] == [loss] * 4
    assert [verdict.holds for verdict in decision.verdicts] == [holding] * 4
    assert [verdict.qualifies for verdict in decision.verdicts] == [holding] * 4
    assert decision.depth == (BAR_DEPTHS[0] if holding else None)


def test_a_depth_shown_lower_does_not_gain() -> None:
    """Significantly different, but worse at every depth: no gain, so no depth."""
    decision = default_reranking(arm(1.0), depths(d10=PLAIN, d20=PLAIN, d30=PLAIN, d50=PLAIN))
    assert decision is not None
    assert all(round(verdict.adjusted, 4) < bar.ALPHA for verdict in decision.verdicts)
    assert [verdict.beats for verdict in decision.verdicts] == [False] * 4
    assert decision.depth is None


@pytest.mark.parametrize(("tail_ms", "chosen"), [(5000, BAR_DEPTHS[0]), (5001, None)])
def test_a_search_may_take_5_seconds_at_the_95th_percentile(
    tail_ms: int, chosen: int | None
) -> None:
    """The user's bound, in whole milliseconds; slower at every depth, no depth is chosen."""
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


@pytest.mark.parametrize(("pvalue", "chosen"), [(0.2, 0), (0.04996, 0), (0.0499, 1)])
def test_the_smallest_depth_not_shown_worse_than_the_best_is_taken(
    monkeypatch: MonkeyPatch, pvalue: float, chosen: int
) -> None:
    """20 the best; 10, against it, not shown lower (p of 0.0500 as reported), or shown lower.

    Each qualifying depth's p-value against the best is kept.
    """
    gains = {(0.0, 0.5): 0.001, (0.0, 0.6): 0.001, (0.0, 0.55): 0.001, (0.0, 0.52): 0.001}
    arms = depths(d10=arm(0.5), d20=arm(0.6), d30=arm(0.55), d50=arm(0.52))
    scripted_tests(monkeypatch, gains | {(0.6, 0.5): pvalue})
    decision = default_reranking(PLAIN, arms)
    assert decision is not None
    assert decision.depth == BAR_DEPTHS[chosen]
    assert decision.against_best == dict(zip(BAR_DEPTHS, [pvalue, 1.0, 1.0, 1.0], strict=True))


def test_a_depth_that_does_not_qualify_is_neither_the_best_nor_taken(
    monkeypatch: MonkeyPatch,
) -> None:
    """10 ranks highest and gains, but is too slow: 20, the best qualifying, is taken."""
    gains = {(0.0, 0.7): 0.001, (0.0, 0.6): 0.001, (0.0, 0.55): 0.001, (0.0, 0.52): 0.001}
    scripted_tests(monkeypatch, gains | {(0.6, 0.55): 0.3})
    decision = default_reranking(
        PLAIN, depths(d10=arm(0.7, 5001), d20=arm(0.6), d30=arm(0.55), d50=arm(0.52))
    )
    assert decision is not None
    assert [verdict.qualifies for verdict in decision.verdicts] == [False, True, True, True]
    assert decision.against_best == {20: 1.0, 30: 0.3, 50: 1.0}
    assert decision.depth == BAR_DEPTHS[1]


def test_a_gain_too_small_to_show_is_no_gain(monkeypatch: MonkeyPatch) -> None:
    """Means of 0.0004 and 0 both read 0.000: no gain, however small the p-value."""
    scripted_tests(monkeypatch, {(0.0, 0.0004): 0.001})
    small = arm(0.0004)
    decision = default_reranking(PLAIN, depths(d10=small, d20=small, d30=small, d50=small))
    assert decision is not None
    assert [verdict.beats for verdict in decision.verdicts] == [False] * 4


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
    answers = iter(
        [
            Reranked(scores=[1.0], tokens=3),
            Reranked(scores=[1.0, 0.0], tokens=None),
            Reranked(scores=[0.5], tokens=4),
        ]
    )
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
    assert record["sample"] is None
    assert all(each["tokens"] for each in record["arms"][1:])


def test_a_sample_measures_that_many_questions_the_same_at_each_depth(
    data: Path, capsys: CaptureFixture[str]
) -> None:
    """--sample 2 of the three questions: two requests a depth, for the same two; said so."""
    answers = Reranks()
    with serving(Scripted()) as url, serving(answers) as rerank_url:
        assert evaluated(data, url, rerank_url, "--sample", str(SAMPLE), "--seed", "5") == 0
    assert f"--sample {SAMPLE}" in capsys.readouterr().err
    queries = [request["query"] for request in answers.asked]
    assert len(set(queries)) == SAMPLE
    assert queries == queries[:SAMPLE] * 2  # depths 2 and 3
    [results] = (data / "eval" / "results").glob("*-rerank.json")
    record = json.loads(results.read_text(encoding="utf-8"))
    assert record["sample"] == {"questions": 2, "seed": 5}


def test_a_sample_larger_than_the_golden_file_is_refused_before_any_request(data: Path) -> None:
    """Three questions: a sample of four exits 2, and nothing is reranked."""
    answers = Reranks()
    with serving(Scripted()) as url, serving(answers) as rerank_url:
        assert evaluated(data, url, rerank_url, "--sample", "4") == ExitStatus.REFUSED
    assert answers.asked == []


def test_recall_at_n_is_the_share_of_expected_documents_in_the_first_stage_s_first_n(
    data: Path, capsys: CaptureFixture[str]
) -> None:
    """Recall@2 and @3 of the order not reranked: the first ranking, searched again alone."""
    with serving(Scripted()) as url, serving(Reranks()) as rerank_url:
        assert evaluated(data, url, rerank_url, "--format", "json") == 0
    record = json.loads(capsys.readouterr().out)
    questions = read_golden(
        GOLDEN, Library(SqliteIndex(data / "index.sqlite"), data / "docs").resolve
    )
    index = data / "eval" / "indexes" / "windows" / "tiny.sqlite"
    plain = Library(SqliteIndex(index), data / "docs", Meaning(connect_scripted()), "hybrid")
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


@pytest.mark.parametrize(
    ("chosen", "said"), [(20, "turn reranking on, at depth 20."), (None, "leave reranking off.")]
)
def test_the_bar_s_verdicts_are_written_by_this_machine_s_times(
    data: Path, capsys: CaptureFixture[str], monkeypatch: MonkeyPatch, chosen: int | None, said: str
) -> None:
    """Each clause, a group's loss or n/a, each p-value against the best, the depth chosen."""
    verdicts = (
        BarVerdict(depth=10, adjusted=0.004, beats=True, losses={"keyword": 0.051}, fast=False),
        BarVerdict(
            depth=20,
            adjusted=0.004,
            beats=True,
            losses={"identifier": 0.0, "keyword": -0.012},
            fast=True,
        ),
    )
    decision = Decision(verdicts=verdicts, depth=chosen, against_best={20: 1.0, 30: 0.3})
    monkeypatch.setattr(measuring, "default_reranking", lambda _plain, _arms: decision)
    with serving(Scripted()) as url, serving(Reranks()) as rerank_url:
        assert evaluated(data, url, rerank_url) == 0
    lines = capsys.readouterr().out.splitlines()
    assert (
        "Depth 10: MRR@10 adjusted p = 0.0040; gains yes; groups lose identifier n/a,"
        " keyword 0.051, hold no; within 5 s here no"
    ) in lines
    assert (
        "Depth 20: MRR@10 adjusted p = 0.0040; gains yes; groups lose identifier 0.000,"
        " keyword -0.012, hold yes; within 5 s here yes"
    ) in lines
    assert "Depth 30 against the best qualifying: MRR@10 p = 0.3000" in lines
    assert f"By the bar, with this machine's times: {said}" in lines


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
