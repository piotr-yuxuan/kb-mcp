"""Evaluating the strategies on golden questions, with the tiny model (plans 011, 018)."""

from __future__ import annotations

import json
import os
import re
from datetime import UTC, datetime
from itertools import count
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
import yaml
from structlog.testing import capture_logs

from atlassian_offline_mcp.cli.main import main
from atlassian_offline_mcp.config.domain.settings import Settings
from atlassian_offline_mcp.evaluation.app import evaluation
from atlassian_offline_mcp.evaluation.app.evaluation import (
    ASK_HEADER,
    HEADER,
    EvaluationError,
    GoldenError,
    Target,
    evaluate,
    read_golden,
    record,
    table,
)
from atlassian_offline_mcp.evaluation.domain.evaluation import Question, Quoted, holm
from atlassian_offline_mcp.kernel.chunking import CHUNKINGS
from atlassian_offline_mcp.mcp.app.tools import Library
from atlassian_offline_mcp.search.adapters.embedding import ModelError
from atlassian_offline_mcp.search.adapters.sqlite_index import reading
from atlassian_offline_mcp.search.app.indexing import build_index
from atlassian_offline_mcp.search.app.meaning import Meaning
from tests.endpoint import DIGEST, Scripted, nothing_listening, serving, tiny
from tests.mirrors import MOMENT, fillers, issue, page, write
from tests.test_cli import logged_as
from tests.test_observed import said

if TYPE_CHECKING:
    from collections.abc import Callable

    from _pytest.capture import CaptureFixture
    from _pytest.monkeypatch import MonkeyPatch

    from atlassian_offline_mcp.search.adapters.embedding import Embedder
    from tests.conftest import InMemory

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
# Plan 002's golden set, whose keys a golden file takes as refs.
SANDBOX_SET = Path(__file__).parents[1] / "sandbox" / "golden.yaml"
# Seconds that connecting takes in the test of timing: beyond any query's.
LOADING = 1000


@pytest.fixture
def data(tmp_path: Path, monkeypatch: MonkeyPatch) -> Path:
    """Give a data directory with a mirror and its index."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    docs = tmp_path / "data" / "docs"
    fillers(docs)
    write(docs, page("4002", "Holiday canteen"), "# Holiday canteen\n\nLeave for a **meal**.\n")
    write(docs, page("4003", "Words"), "revert release\n")
    write(docs, issue("PROJ-7", "Kafka upgrade"))
    build_index(docs, tmp_path / "data" / "index.sqlite", MOMENT)
    return tmp_path / "data"


def options(data: Path, url: str = "http://127.0.0.1:11434/v1") -> list[str]:
    """Write settings naming the tiny model and an endpoint; give the options to read them."""
    config = data.parent / "config.toml"
    config.write_text(f'model = "tiny"\nembedding_url = "{url}"\n', encoding="utf-8")
    return ["--config", str(config), "--data-dir", str(data)]


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
        ("- {id: q1, question: x, expected: ['4002'], 7: x}", r"golden\[0\]: unknown field 7"),
        (
            "- {id: q1, question: x, expected: ['4002'], evidence: {'4002': '**'}}",
            r"evidence: a phrase of a word or more",
        ),
        (
            "- {id: q1, question: x, expected: ['4002'], evidence: {'4002': '.'}}",
            r"evidence: a phrase of a word or more",
        ),
        (
            "- {id: q1, question: x, expected: ['4002'], evidence: {4002: a phrase}}",
            r"evidence: refs as text, in quotes",
        ),
        ("{id: q1}", "golden: expected a list"),
        ("- [unclosed", "not a golden file"),
        ("- {id: 1, question: x, expected: ['4002']}", r"golden\[0\]\.id: expected a string"),
        ("- 3", r"golden\[0\]: expected an object"),
        (
            "- {id: q1, question: x, expected: ['4002'], partial: null}",
            r"golden\[0\]\.partial: expected a list",
        ),
        (
            "- {id: q1, question: x, expected: ['4002'], evidence: {'4002': 3}}",
            r"golden\[0\]\.evidence\.4002: expected a string",
        ),
        ("- {id: q1}", r"golden\[0\]\.question: missing; golden\[0\]\.expected: missing"),
    ],
)
def test_a_golden_file_is_refused_by_name(data: Path, text: str, named: str) -> None:
    """Each fault names where it is; nothing is half-read."""
    with pytest.raises(GoldenError, match=named):
        golden(data, text)


def test_the_sandbox_s_golden_set_reads_as_written() -> None:
    """Plan 002's set as a golden file, its overlap and language as groups, reads whole.

    Each question keeps its id, its text, its groups, and its refs and evidence, each
    ref as the path that the mirror gives it.
    """

    def path(ref: str) -> str:
        return f"mirror/{ref}.md"

    items = yaml.safe_load(SANDBOX_SET.read_text("utf-8"))
    written = [
        {
            "id": item["id"],
            "question": item["question"],
            "expected": item["expected"],
            "partial": item["partial"],
            "groups": [item["overlap"], item["lang"]],
            "evidence": item["evidence"],
        }
        for item in items
    ]
    assert read_golden(yaml.safe_dump(written, allow_unicode=True), path) == [
        Question(
            item["id"],
            item["question"],
            expected=tuple(path(ref) for ref in item["expected"]),
            partial=tuple(path(ref) for ref in item["partial"]),
            groups=(item["overlap"], item["lang"]),
            evidence={path(ref): phrase for ref, phrase in item["evidence"].items()},
        )
        for item in items
    ]


def test_refs_resolve_as_read_takes_them(data: Path) -> None:
    """A page id, an address and an issue key all name their mirrored path."""
    q1, q2, q3 = golden(data)
    assert q1.expected == ("confluence/ENG/4002-holiday-canteen.md",)
    assert q2.partial == q1.expected
    assert q3.expected == ("jira/PROJ/PROJ-7.md",)
    assert q1.evidence == {q1.expected[0]: "leave for a meal"}


def test_meaning_answers_the_paraphrase_that_words_miss(data: Path) -> None:
    """Measured as search ranks: the paraphrase found by meaning only; the key first in all."""
    settings = Settings(data_dir=data, model="tiny")
    ticks = count()
    [run] = evaluate(settings, golden(data), targets(tiny()), lambda: float(next(ticks)), MOMENT)
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
    with serving(Scripted()) as url:
        assert main(["eval", "--yes", str(data / "golden.yaml"), *options(data, url)]) == 0
        out = capsys.readouterr().out
        assert "## tiny" in out
        [results] = (data / "eval" / "results").glob("*.json")
        kept = results.read_text(encoding="utf-8")
        assert "vacation" not in kept
        assert "release" not in kept
        assert json.loads(kept)["runs"][0]["ranks"]["semantic"]["q1"] == [1]
        assert main(["eval", "--yes", str(data / "golden.yaml"), *options(data, url)]) == 0
    second = max((data / "eval" / "results").glob("*.json"))
    assert json.loads(second.read_text(encoding="utf-8"))["runs"][0]["embedded"] == 0


def test_the_command_in_short_shows_each_mode_on_all_questions_then_the_results_file(
    data: Path, capsys: CaptureFixture[str]
) -> None:
    """Under each run's model and chunking, search's and ask's rows of the group all alone.

    Lexical search, which ignores the chunking, comes with the first run alone; then each
    model's default chunking by the rule, and the results file.
    """
    (data / "golden.yaml").write_text(GOLDEN, encoding="utf-8")
    two = ["--chunking", "sections", "--chunking", "windows"]
    with serving(Scripted()) as url:
        assert main(["eval", "--yes", str(data / "golden.yaml"), *options(data, url), *two]) == 0
    [results] = (data / "eval" / "results").glob("*.json")
    out = capsys.readouterr().out
    lines = out.splitlines()
    assert lines[:2] == ["## tiny, sections", ""]
    assert lines[2].startswith("Index built in ")
    assert [line for line in lines if line.startswith("| Mode")] == [HEADER, ASK_HEADER] * 2
    rows = [line.split(" | ")[:2] for line in lines if re.match(r"\| [a-z]+ \| all", line)]
    modes = [["| lexical", "all"], ["| semantic", "all"], ["| hybrid", "all"]]
    assert rows == [*modes, *modes, *modes[1:], *modes[1:]]
    assert "\n## tiny, windows\n" in out
    assert "Default chunking for tiny, by the rule: " in out
    assert "  windows, evidence against sections: p = " in out
    assert out.endswith(f"Results: {results}\n")


def test_the_command_in_detail_shows_every_group_how_the_index_was_built_and_the_tests(
    data: Path, capsys: CaptureFixture[str]
) -> None:
    """The model's whole table, as ``table`` writes it, then the results file."""
    (data / "golden.yaml").write_text(GOLDEN, encoding="utf-8")
    with serving(Scripted()) as url:
        options_given = [*options(data, url), "--summary", "detailed"]
        assert main(["eval", "--yes", str(data / "golden.yaml"), *options_given]) == 0
    [results] = (data / "eval" / "results").glob("*.json")
    out = capsys.readouterr().out
    assert "Index built in " in out
    assert "| semantic | paraphrase | 1.000 | 1.000 |" in out
    assert "MRR@10, semantic against lexical: p = " in out
    assert out.endswith(f"\nResults: {results}\n")


def test_the_command_gives_each_model_s_run_and_the_results_file_as_json(
    data: Path, capsys: CaptureFixture[str]
) -> None:
    """One document, of ids and numbers: no question's text, as in the results file."""
    (data / "golden.yaml").write_text(GOLDEN, encoding="utf-8")
    with serving(Scripted()) as url:
        options_given = [*options(data, url), "--format", "json"]
        assert main(["eval", "--yes", str(data / "golden.yaml"), *options_given]) == 0
    [results] = (data / "eval" / "results").glob("*.json")
    out = capsys.readouterr().out
    assert "vacation" not in out
    assert "release" not in out
    document = json.loads(out)
    assert document["results"] == str(results)
    assert [run["chunking"] for run in document["runs"]] == list(CHUNKINGS)
    run = document["runs"][0]
    assert run["model"] == "tiny"
    assert run["ranks"]["semantic"]["q1"] == [1]
    assert document["choices"]["tiny"]["chunking"] in CHUNKINGS


def test_a_refused_golden_file_exits_2(data: Path, capsys: CaptureFixture[str]) -> None:
    """The command names the fault, by the error eval.refused, and evaluates nothing.

    The run's log file holds the error and its reason.
    """
    (data / "golden.yaml").write_text("- {id: q1}", encoding="utf-8")
    assert main(["eval", "--yes", str(data / "golden.yaml"), *options(data)]) == REFUSED
    err = capsys.readouterr().err
    assert ("error", "eval.refused") in said(err)
    assert "golden[0].expected: missing" in err
    (refused,) = logged_as(data.parent / "home", "eval.refused")
    assert refused["level"] == "error"
    assert "golden[0].expected: missing" in str(refused["reason"])
    assert not (data / "eval").exists()


def test_an_endpoint_that_does_not_answer_evaluates_nothing(
    data: Path, capsys: CaptureFixture[str]
) -> None:
    """Ollama not started: exit 1, the error eval.not_evaluated saying what to run.

    The run's log file holds it too, and no results are written.
    """
    (data / "golden.yaml").write_text(GOLDEN, encoding="utf-8")
    with nothing_listening() as url:
        assert main(["eval", "--yes", str(data / "golden.yaml"), *options(data, url)]) == 1
    err = capsys.readouterr().err
    assert ("error", "eval.not_evaluated") in said(err)
    assert "ollama serve" in err
    (failed,) = logged_as(data.parent / "home", "eval.not_evaluated")
    assert failed["level"] == "error"
    assert "ollama serve" in str(failed["reason"])
    assert not (data / "eval").exists()


def test_a_golden_file_is_read_from_a_pipe(data: Path, capsys: CaptureFixture[str]) -> None:
    """As a process substitution gives one, such as ``<(sops -d golden.sops.yaml)``.

    It is no regular file, yet the reader reads it, and names the fault it holds.
    """
    read, write = os.pipe()
    os.write(write, b"- {id: q1}")
    os.close(write)
    try:
        assert main(["eval", "--yes", f"/dev/fd/{read}", *options(data)]) == REFUSED
    finally:
        os.close(read)
    assert "golden[0].expected: missing" in capsys.readouterr().err


def test_an_endpoint_elsewhere_without_the_flag_exits_2(
    data: Path, capsys: CaptureFixture[str]
) -> None:
    """``eval`` always embeds: an endpoint off this machine needs the run's word."""
    (data / "golden.yaml").write_text(GOLDEN, encoding="utf-8")
    remote = options(data, "https://embeddings.example/v1")
    assert main(["eval", "--yes", str(data / "golden.yaml"), *remote]) == REFUSED
    err = capsys.readouterr().err
    assert said(err) == [("error", "run.refused")]
    assert "embedding_url: not an address of this machine" in err
    assert not (data / "eval").exists()


def test_the_record_names_its_test_and_golden_file() -> None:
    """The seed and samples of the test, and the golden file by hash, are kept."""
    kept = record([], "golden text", datetime(2026, 10, 21, tzinfo=UTC), {})
    assert kept["test"] == {
        "kind": "paired randomisation, two-sided",
        "samples": 10_000,
        "seed": 11,
    }
    assert re.fullmatch(r"[0-9a-f]{64}", str(kept["golden_sha256"]))


def targets(*embedders: Embedder) -> list[Target]:
    """Evaluate each model with the chunking of sections alone."""
    return [Target(embedder, "sections") for embedder in embedders]


def ticking() -> Callable[[], float]:
    """Return a clock that moves one second at each reading."""
    ticks = count()
    return lambda: float(next(ticks))


def test_a_model_reports_its_index_s_tasks_then_every_question_in_every_mode(
    data: Path,
) -> None:
    """Its files, its texts to embed, then the questions asked by words, meaning and both."""
    questions = golden(data)
    with capture_logs() as events:
        evaluate(
            Settings(data_dir=data, model="tiny"), questions, targets(tiny()), ticking(), MOMENT
        )
    reported = [(each["task"], each["done"], each["total"]) for each in events if "task" in each]
    assert [task for task, _, _ in reported] == ["files", "texts to embed", "questions"]
    assert all(done == total for _, done, total in reported)
    assert reported[-1][1] == 3 * len(questions)  # lexical, semantic and hybrid


def test_a_ref_missing_from_the_index_evaluated_is_refused(data: Path) -> None:
    """Read against an index that holds a page, measured against one that lost it: refused."""
    questions = golden(data)
    (data / "docs" / "confluence" / "ENG" / "4003-words.md").unlink()
    settings = Settings(data_dir=data, model="tiny")
    with pytest.raises(EvaluationError, match=r"tiny: q2: confluence/ENG/4003-words\.md is not"):
        evaluate(settings, questions, targets(tiny()), ticking(), MOMENT)


def test_a_mode_by_meaning_that_falls_back_is_refused(data: Path, monkeypatch: MonkeyPatch) -> None:
    """Measuring words twice under another name would mislead: the run stops, naming why."""

    def broken(name: str) -> Embedder:
        message = f"{name}: no answer from the embedding endpoint (ConnectError)"
        raise ModelError(message)

    monkeypatch.setattr(evaluation, "Meaning", lambda _connect: Meaning(broken))
    settings = Settings(data_dir=data, model="tiny")
    with pytest.raises(EvaluationError, match="tiny, semantic: Ranked by words alone"):
        evaluate(settings, golden(data), targets(tiny()), ticking(), MOMENT)


def test_holm_adjusts_every_test_of_the_run(data: Path, monkeypatch: MonkeyPatch) -> None:
    """Two models, two modes each against lexical: four tests, adjusted together.

    The tests' p-values are set, small and distinct, so that adjusting per model (0.02,
    0.04, 0.06, 0.06) differs from adjusting the run (0.04, 0.06, 0.06, 0.06).
    """
    answers = Scripted({"tiny:latest": DIGEST, "tiny2:latest": DIGEST})
    given = iter([1.0, 0.01, 0.02, 1.0, 0.03, 0.04])  # lexical, semantic, hybrid, twice
    monkeypatch.setattr(evaluation, "paired_test", lambda *_: next(given))
    settings = Settings(data_dir=data, model="tiny")
    embedders = targets(tiny(answers), tiny(answers, "tiny2"))
    runs = evaluate(settings, golden(data), embedders, ticking(), MOMENT)
    raw = [run.pvalues[mode] for run in runs for mode in ("semantic", "hybrid")]
    adjusted = [run.adjusted[mode] for run in runs for mode in ("semantic", "hybrid")]
    assert raw == [0.01, 0.02, 0.03, 0.04]
    assert adjusted == holm(raw) == pytest.approx([0.04, 0.06, 0.06, 0.06])


def test_a_partial_ref_missing_from_the_index_evaluated_is_refused(data: Path) -> None:
    """A document that only helps counts in nDCG: missing, it would lower it unseen."""
    write(data / "docs", page("4004", "Helper"), "revert\n")
    build_index(data / "docs", data / "index.sqlite", MOMENT)
    questions = golden(data, "- {id: q1, question: x, expected: ['4003'], partial: ['4004']}")
    (data / "docs" / "confluence" / "ENG" / "4004-helper.md").unlink()
    settings = Settings(data_dir=data, model="tiny")
    with pytest.raises(EvaluationError, match=r"q1: confluence/ENG/4004-helper\.md is not"):
        evaluate(settings, questions, targets(tiny()), ticking(), MOMENT)


def test_the_first_search_by_meaning_is_not_timed_as_a_query(
    data: Path, monkeypatch: MonkeyPatch
) -> None:
    """A thousand seconds of connecting land on the untimed first query, not the measures."""
    now = [0.0]

    def clock() -> float:
        now[0] += 1.0
        return now[0]

    def slow(name: str) -> Embedder:
        now[0] += 1000.0
        return tiny(model=name)

    monkeypatch.setattr(evaluation, "Meaning", lambda _connect: Meaning(slow))
    settings = Settings(data_dir=data, model="tiny")
    [run] = evaluate(settings, golden(data), targets(tiny()), clock, MOMENT)
    assert all(tail < LOADING for _, tail in run.times.values())


def test_evaluation_leaves_the_served_index_and_builds_its_own(data: Path) -> None:
    """The server's index stays; the model's is in <data>/eval/indexes/<chunking>/.

    Its name's ``:`` and ``/`` are written ``_``, so that it stays one file there.
    """
    before = (data / "index.sqlite").read_bytes()
    settings = Settings(data_dir=data, model="tiny")
    answers = Scripted({"tiny:latest": DIGEST, "hf.co/someone/tiny:latest": DIGEST})
    embedders = targets(tiny(answers, "tiny:latest"), tiny(answers, "hf.co/someone/tiny"))
    evaluate(settings, golden(data), embedders, ticking(), MOMENT)
    assert (data / "index.sqlite").read_bytes() == before
    indexes = data / "eval" / "indexes" / "sections"
    assert sorted(path.name for path in indexes.iterdir()) == [
        "hf.co_someone_tiny.sqlite",
        "tiny_latest.sqlite",
    ]
    with reading(indexes / "tiny_latest.sqlite") as reader:
        assert reader.embedded() is not None


def test_documents_are_measured_to_the_tenth_and_tested_on_mrr(
    data: Path, monkeypatch: MonkeyPatch
) -> None:
    """Tenth by words still counts within ten; the tests compare reciprocal ranks.

    Each mode is tested against lexical, question by question, on MRR@10's ranks.
    """
    for number in range(9):
        write(data / "docs", page(str(4100 + number), f"Zebra {number} zebra"), "zebra\n")
    write(data / "docs", page("4200", "Stripes"), "Some text, and zebra once.\n")
    build_index(data / "docs", data / "index.sqlite", MOMENT)
    questions = golden(data, GOLDEN + "- {id: q4, question: zebra, expected: ['4200']}\n")
    tested: list[tuple[list[float], list[float]]] = []

    def recorded(before: list[float], after: list[float]) -> float:
        tested.append((list(before), list(after)))
        return 0.5

    monkeypatch.setattr(evaluation, "paired_test", recorded)
    settings = Settings(data_dir=data, model="tiny")
    [run] = evaluate(settings, questions, targets(tiny()), ticking(), MOMENT)
    assert run.per["lexical"]["q4"].recall == 1.0
    assert run.per["lexical"]["q4"].reciprocal_rank == pytest.approx(1 / 10)
    ranks = {
        mode: [run.per[mode][each.id].reciprocal_rank for each in questions] for mode in run.per
    }
    assert tested[1:] == [
        (ranks["lexical"], ranks["semantic"]),
        (ranks["lexical"], ranks["hybrid"]),
    ]
    assert ranks["semantic"] != ranks["lexical"]


def test_ask_is_measured_beside_search_in_each_mode(data: Path) -> None:
    """The paraphrase: quoted with its evidence by meaning, missed by words; costs counted."""
    settings = Settings(data_dir=data, model="tiny")
    [run] = evaluate(settings, golden(data), targets(tiny()), ticking(), MOMENT)
    assert run.asked["semantic"]["q1"] == Quoted(1.0, 1.0)
    assert run.asked["lexical"]["q1"] == Quoted(0.0, 0.0)
    assert run.asked["lexical"]["q3"].found == 1.0
    assert set(run.ask_times) == {"lexical", "semantic", "hybrid"}
    assert run.costs.pieces > 0
    assert run.costs.estimated == run.costs.characters // 4
    assert (
        run.costs.bytes == (data / "eval" / "indexes" / "sections" / "tiny.sqlite").stat().st_size
    )


def test_the_characters_embedded_are_the_same_with_the_store_warm_or_cold(data: Path) -> None:
    """Read from what the index embeds, not from what this run had to embed."""
    settings = Settings(data_dir=data, model="tiny")
    built = [evaluate(settings, golden(data), targets(tiny()), ticking(), MOMENT)[0]]
    built += [evaluate(settings, golden(data), targets(tiny()), ticking(), MOMENT)[0]]
    (data / "vectors.sqlite").unlink()
    built += [evaluate(settings, golden(data), targets(tiny()), ticking(), MOMENT)[0]]
    assert [run.embedded > 0 for run in built] == [True, False, True]
    assert len({run.costs.characters for run in built}) == 1


def test_a_chunking_not_named_exits_2_offering_the_kernel_s(
    data: Path, capsys: CaptureFixture[str]
) -> None:
    """``--chunking window``: the parser refuses it, naming every chunking."""
    (data / "golden.yaml").write_text(GOLDEN, encoding="utf-8")
    with pytest.raises(SystemExit) as stopped:
        main(["eval", "--yes", str(data / "golden.yaml"), "--chunking", "window"])
    assert stopped.value.code == REFUSED
    assert ", ".join(f"'{name}'" for name in CHUNKINGS) in capsys.readouterr().err


def test_each_target_s_scores_are_measured_by_its_chunking_ask_s_among_them(
    data: Path, telemetry: InMemory
) -> None:
    """One model, two chunkings: each mode's measures as the results have them.

    One question of three has evidence, so that Evidence@ask is measured too.
    """
    settings = Settings(data_dir=data, model="tiny")
    targets = [Target(tiny(), "sections"), Target(tiny(), "windows")]
    runs = evaluate(settings, golden(data), targets, ticking(), MOMENT)
    points = {
        tuple(
            str(point.attributes[key]) for key in ("aom.chunking", "aom.mode", "aom.measure")
        ): point.value
        for point in telemetry.measured()["aom.eval.score"].data.data_points
        if point.attributes
    }
    expected = {
        (run.chunking, mode, measure): value
        for run in runs
        for mode in ("lexical", "semantic", "hybrid")
        for measure, value in {
            "recall@10": run.groups[mode]["all"].recall,
            "mrr@10": run.groups[mode]["all"].reciprocal_rank,
            "ndcg@10": run.groups[mode]["all"].ndcg,
            "success@1": run.groups[mode]["all"].success,
            "found@ask": run.asked_groups[mode]["all"].found,
            "evidence@ask": run.asked_groups[mode]["all"].evidence,
        }.items()
    }
    assert points == pytest.approx(expected)
