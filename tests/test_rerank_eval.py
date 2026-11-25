"""Reranking measured: plan 022's bar on hand-built numbers, and eval-rerank end to end."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from kb_mcp.cli.main import main
from kb_mcp.evaluation.app import reranked as measuring
from kb_mcp.evaluation.app.evaluation import read_golden
from kb_mcp.evaluation.app.reranked import Counted
from kb_mcp.evaluation.domain import evaluation as rules
from kb_mcp.evaluation.domain.evaluation import RULES, Verdict, verdict
from kb_mcp.kernel.names import ExitStatus
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
# Plan 022's family, and the level of an adjusted p-value.
FAMILY = ["10", "20", "30", "50"]
ALPHA_LEVEL = 0.05
# An arm as the default rule reads it: MRR@10 question by question, by group, and its time.
type Arm = tuple[tuple[float, ...], dict[str, float], int]


def arm(score: float, tail_ms: int = 900, **groups: float) -> Arm:
    """Make an arm whose every question scores ``score``, its groups as given or as GROUPS."""
    return (score,) * QUESTIONS, GROUPS | groups, tail_ms


PLAIN = arm(0.0)


def decided(plain: Arm, **arms: Arm) -> Verdict:
    """Apply the bar to the order not reranked and to depths given as ``d10=...``."""
    depths = {"none": plain, **{name[1:]: each for name, each in arms.items()}}
    return verdict(RULES["reranking depth"], "none", depths, {})


def test_every_depth_gaining_on_every_question_qualifies_and_the_smallest_is_kept() -> None:
    """A gain on all 30 questions is significant, times four; equal means: the smallest."""
    gaining = arm(1.0)
    found = decided(PLAIN, d10=gaining, d20=gaining, d30=gaining, d50=gaining)
    assert found.failed == dict.fromkeys(FAMILY, ())
    assert found.kept == "10"


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
    found = decided(arm(0.0, **{group: before}), d10=lost, d20=lost, d30=lost, d50=lost)
    assert [found.losses[depth][group] for depth in FAMILY] == [loss] * 4
    assert [("guards" in found.failed[depth]) for depth in FAMILY] == [not holding] * 4
    assert found.kept == ("10" if holding else "none")


def test_a_depth_shown_lower_does_not_gain() -> None:
    """Significantly different, but worse at every depth: no gain, so no depth."""
    found = decided(arm(1.0), d10=PLAIN, d20=PLAIN, d30=PLAIN, d50=PLAIN)
    assert all(round(each, 4) < ALPHA_LEVEL for each in found.adjusted.values())
    assert [found.failed[depth] for depth in FAMILY] == [("gain",)] * 4
    assert found.kept == "none"


@pytest.mark.parametrize(("tail_ms", "kept"), [(5000, "10"), (5001, "none")])
def test_a_search_may_take_5_seconds_at_the_95th_percentile(tail_ms: int, kept: str) -> None:
    """The user's bound, in whole milliseconds; slower at every depth, no depth is kept."""
    timed = arm(1.0, tail_ms)
    found = decided(PLAIN, d10=timed, d20=timed, d30=timed, d50=timed)
    assert [("bound" in found.failed[depth]) for depth in FAMILY] == [kept == "none"] * 4
    assert found.kept == kept


def scripted_tests(monkeypatch: MonkeyPatch, pvalues: dict[tuple[float, float], float]) -> None:
    """Have the bar's paired test give these p-values, by the two arms' first scores."""

    def test(before: Sequence[float], after: Sequence[float]) -> float:
        return pvalues.get((before[0], after[0]), 1.0)

    monkeypatch.setattr(rules, "paired_test", test)


@pytest.mark.parametrize(("pvalue", "gains"), [(0.0125, False), (0.0124, True)])
def test_an_adjusted_p_of_0_05_is_no_gain(
    monkeypatch: MonkeyPatch, pvalue: float, *, gains: bool
) -> None:
    """Bonferroni multiplies each of the four by 4: 0.05 is no gain, 0.0496 is one."""
    scripted_tests(monkeypatch, {(0.0, 0.4): pvalue})
    found = decided(PLAIN, d10=arm(0.4), d20=arm(0.0), d30=arm(0.0), d50=arm(0.0))
    assert round(found.adjusted["10"], 4) == round(pvalue * len(FAMILY), 4)
    assert ("gain" not in found.failed["10"]) is gains
    assert found.kept == ("10" if gains else "none")


def test_a_depth_that_does_not_qualify_is_neither_the_best_nor_kept() -> None:
    """10 ranks highest and gains, but is too slow: 20, the best qualifying, is kept."""
    found = decided(PLAIN, d10=arm(0.7, 5001), d20=arm(0.6), d30=arm(0.55), d50=arm(0.52))
    assert [depth for depth in FAMILY if not found.failed[depth]] == ["20", "30", "50"]
    assert found.kept == "20"


def test_a_gain_too_small_to_show_is_no_gain(monkeypatch: MonkeyPatch) -> None:
    """Means of 0.0004 and 0 both read 0.000: no gain, however small the p-value."""
    scripted_tests(monkeypatch, {(0.0, 0.0004): 0.001})
    small = arm(0.0004)
    found = decided(PLAIN, d10=small, d20=small, d30=small, d50=small)
    assert [found.failed[depth] for depth in FAMILY] == [("gain",)] * 4


@pytest.mark.parametrize(
    ("run", "kept", "untested"),
    [
        (("10", "20", "30"), "10", ("50",)),
        (("20",), "20", ("10", "30", "50")),
        (("30", "50"), "30", ("10", "20")),
        (("10", "20", "30", "40", "50"), "10", ()),
    ],
)
def test_a_subset_of_depths_gets_a_verdict(
    run: tuple[str, ...], kept: str, untested: tuple[str, ...]
) -> None:
    """E1: the depths of the family run are weighed, any of them; one outside it is left out.

    Every depth run gains alike: the smallest of the family run is kept, and the depths
    of the family not run are named.
    """
    found = decided(PLAIN, **{f"d{depth}": arm(1.0) for depth in run})
    assert found.kept == kept
    assert found.untested == untested
    assert set(found.means) == {"none", *run} - {"40"}


def test_with_no_depth_qualifying_reranking_stays_off_each_clause_said() -> None:
    """No gain anywhere: every depth's clauses given, none qualifying; none is kept."""
    found = decided(PLAIN, d10=PLAIN, d20=PLAIN, d30=PLAIN, d50=PLAIN)
    assert list(found.failed) == FAMILY
    assert [found.failed[depth] for depth in FAMILY] == [("gain",)] * 4
    assert found.kept == "none"


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
    assert (
        "Reranking depth, by the default rule: no verdict, since no challenger of its family"
        " was run.\n  10, 20, 30, 50: not run, so cannot qualify\n"
    ) in out
    sizes = [len(request["documents"]) for request in answers.asked]
    assert sizes == [2, 2, 2, 3, 3, 3]
    [results] = (data / "eval" / "results").glob("*-rerank.json")
    kept = results.read_text(encoding="utf-8")
    assert "vacation" not in kept
    assert "release" not in kept
    record = json.loads(kept)
    assert [each["depth"] for each in record["arms"]] == [0, 2, 3]
    assert record["served"] == ["qwen3-reranker-0.6b"]
    assert "decision" not in record
    assert [verdict["kept"] for verdict in record["verdicts"]] == [None]
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
    ("kept", "said"), [("20", "20, in place of none."), ("none", "none stays.")]
)
def test_eval_rerank_prints_and_records_the_verdict(
    data: Path, capsys: CaptureFixture[str], monkeypatch: MonkeyPatch, kept: str, said: str
) -> None:
    """The depth kept; each depth's clauses, a group's loss or n/a; the depths not run.

    The results file and the output as JSON keep the verdict as given, among the verdicts.
    """
    decision = Verdict(
        rule="reranking depth",
        fixed={},
        control="none",
        kept=kept,
        untested=("30", "50"),
        means={"none": 0.5, "10": 0.7, "20": 0.6},
        adjusted={"10": 0.004, "20": 0.004},
        losses={"10": {"keyword": 0.051}, "20": {"identifier": 0.0, "keyword": -0.012}},
        spent={"none": 300, "10": 5001, "20": 4200},
        failed={"10": ("guards", "bound"), "20": ()},
    )
    monkeypatch.setattr(measuring, "verdict", lambda *_: decision)
    with serving(Scripted()) as url, serving(Reranks()) as rerank_url:
        assert evaluated(data, url, rerank_url) == 0
    expected = [
        f"Reranking depth, by the default rule: {said}",
        (
            "  10: MRR@10 0.700 against 0.500, adjusted p = 0.0040, gains yes; MRR@10 lost:"
            " identifier n/a, keyword 0.051, holds no; 95th percentile 5,001 ms, at most"
            " 5,000 ms, within no"
        ),
        (
            "  20: MRR@10 0.600 against 0.500, adjusted p = 0.0040, gains yes; MRR@10 lost:"
            " identifier 0.000, keyword -0.012, holds yes; 95th percentile 4,200 ms, at most"
            " 5,000 ms, within yes"
        ),
        "  30, 50: not run, so cannot qualify",
    ]
    lines = capsys.readouterr().out.splitlines()
    assert lines[lines.index(expected[0]) :][: len(expected)] == expected
    [results] = (data / "eval" / "results").glob("*-rerank.json")
    kept_as = json.loads(results.read_text(encoding="utf-8"))["verdicts"]
    assert kept_as == [decision.model_dump(mode="json")]
    with serving(Scripted()) as url, serving(Reranks()) as rerank_url:
        assert evaluated(data, url, rerank_url, "--format", "json") == 0
    document = json.loads(capsys.readouterr().out)
    assert "decision" not in document
    assert document["verdicts"] == [decision.model_dump(mode="json")]


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
