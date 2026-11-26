"""Evaluating the strategies on golden questions, with the tiny model (plans 011, 018)."""

from __future__ import annotations

import json
import os
import re
from collections import Counter
from datetime import UTC, datetime
from itertools import count
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
import yaml
from structlog.testing import capture_logs

from kb_mcp.cli.main import main
from kb_mcp.config.settings import Settings
from kb_mcp.evaluation.app import evaluation
from kb_mcp.evaluation.app.evaluation import (
    ASK_HEADER,
    HEADER,
    EvaluatedIndex,
    EvaluationError,
    GoldenError,
    evaluate,
    read_golden,
    record,
    table,
    verdicts,
)
from kb_mcp.evaluation.domain import evaluation as rules
from kb_mcp.evaluation.domain.evaluation import Question
from kb_mcp.evaluation.domain.grading import AgentAnswer, grade
from kb_mcp.kernel.names import CHARACTERS_PER_TOKEN, CHUNKINGS
from kb_mcp.mcp.app import responses
from kb_mcp.mcp.app.tools import SEARCH_LIMIT, Library
from kb_mcp.search.adapters.model_api import ModelError
from kb_mcp.search.adapters.sqlite_index import SqliteIndex, reading
from kb_mcp.search.app.indexing import build_index
from kb_mcp.search.app.meaning import Meaning
from tests.endpoint import (
    DIGEST,
    Reranks,
    Scripted,
    connect_scripted,
    nothing_listening,
    serving,
    tiny,
)
from tests.mirrors import FILLERS, MOMENT, fillers, issue, page, write
from tests.test_cli import logged_as
from tests.test_observed import said

if TYPE_CHECKING:
    from collections.abc import Callable

    from _pytest.capture import CaptureFixture
    from _pytest.monkeypatch import MonkeyPatch

    from kb_mcp.search.adapters.embedding import Embedder
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
    """Read golden questions against the data directory's mirror, the skipped left aside."""
    return read_golden(text, Library(SqliteIndex(data / "index.sqlite"), data / "docs").resolve)[0]


@pytest.mark.parametrize(
    ("text", "named"),
    [
        ("- {id: q1, question: x, expected: ['4002'], weight: 2}", r"golden\[0\]: unknown field"),
        ("- {id: q1, question: x}", r"golden\[0\]\.expected"),
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
    assert read_golden(yaml.safe_dump(written, allow_unicode=True), path) == (
        [
            Question(
                id=item["id"],
                text=item["question"],
                expected=tuple(path(ref) for ref in item["expected"]),
                partial=tuple(path(ref) for ref in item["partial"]),
                groups=(item["overlap"], item["lang"]),
                evidence={path(ref): phrase for ref, phrase in item["evidence"].items()},
            )
            for item in items
        ],
        [],
    )


def test_refs_resolve_as_read_takes_them(data: Path) -> None:
    """A page id, an address and an issue key all name their path in the mirror."""
    q1, q2, q3 = golden(data)
    assert q1.expected == ("confluence/ENG/4002-holiday-canteen.md",)
    assert q2.partial == q1.expected
    assert q3.expected == ("jira/PROJ/PROJ-7.md",)
    assert q1.evidence == {q1.expected[0]: "leave for a meal"}


# GOLDEN, and a question whose expected ref names no document of the index.
STALE = GOLDEN + "- {id: q4, question: lost, expected: ['4003', '9999'], partial: ['4002']}\n"
# Each command that reads a golden file, and the results file that it writes, if any.
READERS = [
    (["eval", "--yes", "--chunking", "windows"], "eval/results/*.json"),
    (["eval-rerank", "--yes", "--depth", "2"], "eval/results/*-rerank.json"),
    (["eval-agents", "prepare", "--model", "haiku", "--out", "runs", "--dry-run"], None),
]


def read_by(data: Path, command: list[str], text: str) -> int:
    """Run a command on golden questions, with an endpoint of embeddings and a reranker."""
    (data / "golden.yaml").write_text(text, encoding="utf-8")
    with serving(Scripted()) as url, serving(Reranks()) as rerank_url:
        given = options(data, url)
        config = data.parent / "config.toml"
        config.write_text(f'{config.read_text("utf-8")}[rerank]\nurl = "{rerank_url}"\n', "utf-8")
        return main([*command, str(data / "golden.yaml"), *given])


@pytest.mark.parametrize(("command", "results"), READERS)
def test_a_stale_expected_ref_skips_its_question_and_names_it(
    data: Path, capsys: CaptureFixture[str], command: list[str], results: str | None
) -> None:
    """D3: q4 expects a ref that names no document; the others are measured, as alone.

    Each command names q4 by its ref and why, in its output and its results file.
    """
    resolve = Library(SqliteIndex(data / "index.sqlite"), data / "docs").resolve
    questions, skipped = read_golden(STALE, resolve)
    assert questions == read_golden(GOLDEN, resolve)[0]
    assert [(each["id"], each["ref"]) for each in skipped] == [("q4", "9999")]
    assert read_by(data, command, STALE) == 0
    [line] = [line for line in capsys.readouterr().out.splitlines() if "q4" in line]
    assert "'9999'" in line
    assert "no document" in line
    if results:
        [kept] = data.glob(results)
        assert json.loads(kept.read_text("utf-8"))["skipped"] == skipped


def test_a_stale_partial_ref_is_dropped(data: Path) -> None:
    """D3: a partial ref that names no document leaves its question, which is measured."""
    [q1] = golden(data, "- {id: q1, question: x, expected: ['4002'], partial: [PROJ-8, '4003']}")
    assert q1.partial == ("confluence/ENG/4003-words.md",)


def test_a_skipped_question_says_how_to_bring_the_index_up_to_date(
    data: Path, capsys: CaptureFixture[str]
) -> None:
    """D3: an index older than the mirror misses documents; ``kb-mcp index`` updates it."""
    assert read_by(data, READERS[-1][0], STALE) == 0
    out = capsys.readouterr().out
    assert "older than the mirror misses documents" in out
    assert "kb-mcp index brings it up to date" in out


def test_two_refs_of_one_document_count_once(data: Path) -> None:
    """D3, E16: a page's id and its address name one document, expected or helping, once.

    Found, it is all that is expected: recall is whole, for search and for an agent alike.
    """
    address = "https://example.atlassian.net/wiki/spaces/ENG/pages"
    [q1] = golden(
        data,
        f"- {{id: q1, question: x, expected: ['4002', '{address}/4002/x'],"
        f" partial: ['4003', '{address}/4003/y']}}",
    )
    assert q1.expected == ("confluence/ENG/4002-holiday-canteen.md",)
    assert q1.partial == ("confluence/ENG/4003-words.md",)
    assert rules.measure(list(q1.expected), q1).recall == 1.0
    answer = AgentAnswer(found=True, answer="x", sources=("4002",))
    assert grade(answer, q1, {"4002": q1.expected[0]}.get, lambda _: "").recall == 1.0


def test_no_question_left_refuses(data: Path, capsys: CaptureFixture[str]) -> None:
    """D3: with every question skipped, the run refuses, naming each and what to run."""
    text = "- {id: q1, question: x, expected: ['9999']}\n- {id: q2, question: y, expected: ['8']}"
    with pytest.raises(GoldenError, match=r"No question left.*q1, for '9999'.*q2, for '8'.*index"):
        golden(data, text)
    (data / "golden.yaml").write_text(text, encoding="utf-8")
    assert main(["eval", "--yes", str(data / "golden.yaml"), *options(data)]) == REFUSED
    assert "No question left to measure" in capsys.readouterr().err
    assert not (data / "eval").exists()


def test_meaning_answers_the_paraphrase_that_words_miss(data: Path) -> None:
    """Measured as search ranks: the paraphrase found by meaning only; the key first in all."""
    settings = Settings(data_dir=data, model="tiny")
    ticks = count()
    [run] = evaluate(
        settings, golden(data), evaluated_indexes(tiny()), lambda: float(next(ticks)), MOMENT
    )
    assert run.per["lexical"]["q1"].reciprocal_rank == 0.0
    assert run.per["semantic"]["q1"].reciprocal_rank == 1.0
    assert run.per["hybrid"]["q1"].section == 1.0
    assert all(run.per[mode]["q3"].success == 1.0 for mode in ("lexical", "semantic", "hybrid"))
    assert set(run.groups["semantic"]) == {"all", "paraphrase", "en", "keyword"}
    assert run.embedded > 0
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
        assert "runs" not in json.loads(kept)
        assert json.loads(kept)["indexes"][0]["ranks"]["semantic"]["q1"] == [1]
        assert main(["eval", "--yes", str(data / "golden.yaml"), *options(data, url)]) == 0
    second = max((data / "eval" / "results").glob("*.json"))
    assert json.loads(second.read_text(encoding="utf-8"))["indexes"][0]["embedded"] == 0


def test_the_command_in_short_shows_each_mode_on_all_questions_then_the_results_file(
    data: Path, capsys: CaptureFixture[str]
) -> None:
    """Under each run's model and chunking, search's and ask's rows of the group all alone.

    Lexical search, which ignores the chunking, comes with the first run alone; then the
    default rules' verdicts, and the results file.
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
    assert "Chunking for tiny, by the default rule: " in out
    assert "  sections: Evidence@ask " in out
    assert out.endswith(f"Results: {results}\n")


def test_the_command_in_detail_shows_every_group_how_the_index_was_built_and_the_tests(
    data: Path, capsys: CaptureFixture[str]
) -> None:
    """The model's whole table, as ``table`` writes it, then the verdicts and the results file.

    No mode is tested against lexical search: the search mode's rule tests each against
    the setting's.
    """
    (data / "golden.yaml").write_text(GOLDEN, encoding="utf-8")
    with serving(Scripted()) as url:
        options_given = [*options(data, url), "--detail", "detailed"]
        assert main(["eval", "--yes", str(data / "golden.yaml"), *options_given]) == 0
    [results] = (data / "eval" / "results").glob("*.json")
    out = capsys.readouterr().out
    assert "Index built in " in out
    assert "| semantic | paraphrase | 1.000 | 1.000 |" in out
    assert "against lexical" not in out
    assert "Search mode for tiny, sections, by the default rule: " in out
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
    assert "runs" not in document
    assert "choices" not in document
    assert [run["chunking"] for run in document["indexes"]] == list(CHUNKINGS)
    run = document["indexes"][0]
    assert run["model"] == "tiny"
    assert run["ranks"]["semantic"]["q1"] == [1]
    [chunking] = [each for each in document["verdicts"] if each["rule"] == "chunking"]
    assert chunking["kept"] in CHUNKINGS


# The verdicts' lines of a chunking tried against the setting's, and of a mode against
# hybrid, on GOLDEN: one question has evidence, three have ranks, and no p-value of so few
# questions is significant.
TRIED = re.compile(
    r"  sections: Evidence@ask \d\.\d{3} against \d\.\d{3}, adjusted p = 1\.0000, gains no;"
    r" MRR@10 lost: all -?\d\.\d{3}, identifier n/a, keyword -?\d\.\d{3},"
    r" paraphrase -?\d\.\d{3}, holds (yes|no); [\d,]+ tokens embedded, at most [\d,]+,"
    r" within (yes|no)"
)
MODED = re.compile(
    r"  (lexical|semantic): MRR@10 \d\.\d{3} against \d\.\d{3}, adjusted p = \d\.\d{4},"
    r" gains no; MRR@10 lost: identifier n/a, keyword -?\d\.\d{3}, holds (yes|no);"
    r" 95th percentile [\d,]+ ms, at most 500 ms, within (yes|no)"
)


def test_eval_prints_and_records_the_verdicts(data: Path, capsys: CaptureFixture[str]) -> None:
    """The search mode's verdict for each index, then the chunking's for each model.

    Each says the value kept, its challengers' clauses and the values not run. Against
    the settings, hybrid and windows by default, on three questions: each stays, since
    no gain can be shown. The results file keeps the verdicts, in the same order.
    """
    (data / "golden.yaml").write_text(GOLDEN, encoding="utf-8")
    two = ["--chunking", "sections", "--chunking", "windows"]
    with serving(Scripted()) as url:
        assert main(["eval", "--yes", str(data / "golden.yaml"), *options(data, url), *two]) == 0
    [results] = (data / "eval" / "results").glob("*.json")
    out = capsys.readouterr().out
    lines = out.splitlines()
    assert "against lexical" not in out
    for chunking in ("sections", "windows"):
        said = lines.index(f"Search mode for tiny, {chunking}, by the default rule: hybrid stays.")
        assert [bool(MODED.fullmatch(line)) for line in lines[said + 1 : said + 3]] == [True] * 2
    said = lines.index("Chunking for tiny, by the default rule: windows stays.")
    assert TRIED.fullmatch(lines[said + 1])
    assert lines[said + 2 :] == [
        "  section-paths, small-to-big: not run, so cannot qualify",
        f"Results: {results}",
    ]
    kept = json.loads(results.read_text(encoding="utf-8"))
    assert "chunking" not in kept
    assert [(each["rule"], each["fixed"], each["kept"]) for each in kept["verdicts"]] == [
        ("search mode", {"model": "tiny", "chunking": "sections"}, "hybrid"),
        ("search mode", {"model": "tiny", "chunking": "windows"}, "hybrid"),
        ("chunking", {"model": "tiny"}, "windows"),
    ]
    assert kept["verdicts"][2]["untested"] == ["section-paths", "small-to-big"]


@pytest.mark.parametrize(
    ("setting", "control"), [("", "windows"), ('chunking = "sections"\n', "sections")]
)
def test_the_chunking_control_is_the_setting(
    data: Path, capsys: CaptureFixture[str], setting: str, control: str
) -> None:
    """E2: plan 019's rule weighs the chunkings against the setting's, windows by default."""
    (data / "golden.yaml").write_text(GOLDEN, encoding="utf-8")
    two = ["--chunking", "sections", "--chunking", "windows", "--format", "json"]
    with serving(Scripted()) as url:
        given = options(data, url)
        config = data.parent / "config.toml"
        config.write_text(config.read_text("utf-8") + setting, "utf-8")
        assert main(["eval", "--yes", str(data / "golden.yaml"), *given, *two]) == 0
    document = json.loads(capsys.readouterr().out)
    [verdict] = [each for each in document["verdicts"] if each["rule"] == "chunking"]
    assert verdict["control"] == control
    assert set(verdict["means"]) == {"sections", "windows"}


# The embedding model's verdict on GOLDEN, a second model weighed in each mode by meaning
# against the setting's, tiny, in hybrid mode: its losses, and its search time against
# tiny's, each in its arm's mode.
WEIGHED = re.compile(
    r"  small, (semantic|hybrid): MRR@10 \d\.\d{3} against \d\.\d{3}; MRR@10 lost: all"
    r" -?\d\.\d{3}, identifier n/a, keyword -?\d\.\d{3}, paraphrase -?\d\.\d{3}, holds"
    r" (yes|no); 95th percentile [\d,]+ ms against [\d,]+ ms, cheaper (yes|no)"
)


def test_eval_prints_and_records_the_embedding_model_verdict(
    data: Path, capsys: CaptureFixture[str]
) -> None:
    """D3, D4: two models over a chunking: the verdicts end with the embedding model's.

    It asks no gain, so it gives no p-value; the results file and the JSON keep it, each
    arm named by its model and mode.
    """
    (data / "golden.yaml").write_text(GOLDEN, encoding="utf-8")
    answers = Scripted({"tiny:latest": DIGEST, "small:latest": DIGEST})
    two = ["--model", "tiny", "--model", "small", "--chunking", "windows"]
    with serving(answers) as url:
        given = [str(data / "golden.yaml"), *options(data, url), *two]
        assert main(["eval", "--yes", *given]) == 0
        lines = capsys.readouterr().out.splitlines()
        assert main(["eval", "--yes", *given, "--format", "json"]) == 0
    document = json.loads(capsys.readouterr().out)
    said = next(at for at, line in enumerate(lines) if line.startswith("Embedding model for"))
    assert re.fullmatch(
        r"Embedding model for windows, by the default rule: (tiny, hybrid stays|small,"
        r" (semantic|hybrid), in place of tiny, hybrid)\.",
        lines[said],
    )
    weighed_in = [WEIGHED.fullmatch(line) for line in lines[said + 1 : said + 3]]
    assert [each and each[1] for each in weighed_in] == ["semantic", "hybrid"]
    assert lines[said + 3].startswith("Results: ")
    kept = json.loads(Path(lines[said + 3].removeprefix("Results: ")).read_text("utf-8"))
    rules_run = ["search mode", "search mode", "chunking", "chunking", "embedding model"]
    for verdicts_kept in (kept["verdicts"], document["verdicts"]):
        assert [each["rule"] for each in verdicts_kept] == rules_run
        weighed = verdicts_kept[-1]
        assert weighed["fixed"] == {"chunking": "windows"}
        assert weighed["control"] == "tiny, hybrid"
        assert set(weighed["means"]) == {"tiny, hybrid", "small, semantic", "small, hybrid"}
        assert "modes" not in weighed
        assert (weighed["adjusted"], weighed["untested"]) == ({}, [])


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


def test_a_source_file_of_the_mirror_that_does_not_read_evaluates_nothing(
    data: Path, capsys: CaptureFixture[str]
) -> None:
    """As index stops on it: exit 1, the error eval.not_evaluated naming it and prepare.

    The run's log file holds it too, and no results are written.
    """
    (data / "golden.yaml").write_text(GOLDEN, encoding="utf-8")
    (data / "docs" / "confluence" / "_source.json").write_text("{not json", encoding="utf-8")
    with serving(Scripted()) as url:
        assert main(["eval", "--yes", str(data / "golden.yaml"), *options(data, url)]) == 1
    named = "confluence/_source.json: not JSON; `kb-mcp prepare` writes it again"
    err = capsys.readouterr().err
    assert ("error", "eval.not_evaluated") in said(err)
    assert named in err
    (failed,) = logged_as(data.parent / "home", "eval.not_evaluated")
    assert named in str(failed["reason"])
    assert not (data / "eval" / "results").exists()


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
    kept = record([], "golden text", datetime(2026, 10, 21, tzinfo=UTC), [], [])
    assert kept["test"] == {
        "kind": "paired randomisation, two-sided",
        "samples": 10_000,
        "seed": 11,
    }
    assert re.fullmatch(r"[0-9a-f]{64}", str(kept["golden_sha256"]))


def evaluated_indexes(*embedders: Embedder) -> list[EvaluatedIndex]:
    """Evaluate each model with the chunking of sections alone."""
    return [EvaluatedIndex(embedder, "sections") for embedder in embedders]


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
            Settings(data_dir=data, model="tiny"),
            questions,
            evaluated_indexes(tiny()),
            ticking(),
            MOMENT,
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
    with pytest.raises(
        EvaluationError,
        match=r"tiny: q2: confluence/ENG/4003-words\.md is not in its index; run embed again$",
    ):
        evaluate(settings, questions, evaluated_indexes(tiny()), ticking(), MOMENT)


def test_a_mode_by_meaning_that_falls_back_is_refused(data: Path, monkeypatch: MonkeyPatch) -> None:
    """Measuring words twice under another name would mislead: the run stops, naming why."""

    def broken(name: str) -> Embedder:
        message = f"{name}: no answer from the embedding endpoint (ConnectError)"
        raise ModelError(message)

    monkeypatch.setattr(evaluation, "Meaning", lambda _connect: Meaning(broken))
    settings = Settings(data_dir=data, model="tiny")
    with pytest.raises(EvaluationError, match="tiny, semantic: Ranked by words alone"):
        evaluate(settings, golden(data), evaluated_indexes(tiny()), ticking(), MOMENT)


def test_a_partial_ref_missing_from_the_index_evaluated_is_refused(data: Path) -> None:
    """A document that only helps counts in nDCG: missing, it would lower it unseen."""
    write(data / "docs", page("4004", "Helper"), "revert\n")
    build_index(data / "docs", data / "index.sqlite", MOMENT)
    questions = golden(data, "- {id: q1, question: x, expected: ['4003'], partial: ['4004']}")
    (data / "docs" / "confluence" / "ENG" / "4004-helper.md").unlink()
    settings = Settings(data_dir=data, model="tiny")
    with pytest.raises(EvaluationError, match=r"q1: confluence/ENG/4004-helper\.md is not"):
        evaluate(settings, questions, evaluated_indexes(tiny()), ticking(), MOMENT)


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
    [run] = evaluate(settings, golden(data), evaluated_indexes(tiny()), clock, MOMENT)
    assert all(tail < LOADING for _, tail in run.times.values())


def test_evaluation_leaves_the_served_index_and_builds_its_own(data: Path) -> None:
    """The server's index stays; the model's is in <data>/eval/indexes/<chunking>/.

    Its name's ``:`` and ``/`` are written ``_``, so that it stays one file there.
    """
    before = (data / "index.sqlite").read_bytes()
    settings = Settings(data_dir=data, model="tiny")
    answers = Scripted({"tiny:latest": DIGEST, "hf.co/someone/tiny:latest": DIGEST})
    embedders = evaluated_indexes(tiny(answers, "tiny:latest"), tiny(answers, "hf.co/someone/tiny"))
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
    """Tenth by words still counts within ten; the search mode's tests compare reciprocal ranks.

    Each other mode is tested against the setting's, hybrid, question by question, on
    MRR@10's ranks.
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

    monkeypatch.setattr(rules, "paired_test", recorded)
    settings = Settings(data_dir=data, model="tiny")
    [run] = evaluate(settings, questions, evaluated_indexes(tiny()), ticking(), MOMENT)
    assert run.per["lexical"]["q4"].recall == 1.0
    assert run.per["lexical"]["q4"].reciprocal_rank == pytest.approx(1 / 10)
    ranks = {
        mode: [run.per[mode][each.id].reciprocal_rank for each in questions] for mode in run.per
    }
    verdicts([run], questions, settings)
    assert tested == [
        (ranks["hybrid"], ranks["lexical"]),
        (ranks["hybrid"], ranks["semantic"]),
    ]
    assert ranks["semantic"] != ranks["lexical"]


# GOLDEN, its second question with evidence too: words find q2's, but not q1's.
BOTH = GOLDEN.replace(
    "  groups: [keyword]\n", '  groups: [keyword]\n  evidence: {"4003": "revert"}\n'
)
# What a results file keeps of each question, by mode: search's measures, then ask's.
PER = {"recall", "reciprocal_rank", "ndcg", "success", "section", "tokens"}
ASKED_PER = {"found", "evidence", "tokens", "per_kilotoken"}


def test_section_at_10_reads_the_questions_every_arm_found(
    data: Path, capsys: CaptureFixture[str]
) -> None:
    """D4, E7: lexical misses q1, so Section@10 reads q2 alone, in every mode, and says so.

    Each question's own Section@10 stays as it was measured.
    """
    (data / "golden.yaml").write_text(BOTH, encoding="utf-8")
    with serving(Scripted()) as url:
        command = ["eval", "--yes", str(data / "golden.yaml"), "--chunking", "windows"]
        assert main([*command, *options(data, url)]) == 0
    assert "Section@10 reads the questions whose expected document every arm found: 1." in (
        capsys.readouterr().out.splitlines()
    )
    [results] = (data / "eval" / "results").glob("*.json")
    [kept] = json.loads(results.read_text("utf-8"))["indexes"]
    assert kept["aligned"] == 1
    assert kept["per"]["lexical"]["q1"]["section"] is None
    assert kept["per"]["semantic"]["q1"]["section"] == 1.0
    for mode in ("lexical", "semantic", "hybrid"):
        assert kept["groups"][mode]["all"]["section"] == kept["per"][mode]["q2"]["section"]
        assert kept["groups"][mode]["keyword"]["section"] == kept["per"][mode]["q2"]["section"]
        assert kept["groups"][mode]["paraphrase"]["section"] is None


def test_results_hold_every_measure_per_question(data: Path, capsys: CaptureFixture[str]) -> None:
    """D4, E10: each question's measures, search's and ask's, in each mode, as averaged.

    Their means over the questions are the group all's, but Section@10's, which the
    test above reads.
    """
    (data / "golden.yaml").write_text(BOTH, encoding="utf-8")
    with serving(Scripted()) as url:
        command = ["eval", "--yes", str(data / "golden.yaml"), "--chunking", "windows"]
        assert main([*command, *options(data, url)]) == 0
    capsys.readouterr()
    [results] = (data / "eval" / "results").glob("*.json")
    [kept] = json.loads(results.read_text("utf-8"))["indexes"]
    for mode in ("lexical", "semantic", "hybrid"):
        per, asked = kept["per"][mode], kept["asked_per"][mode]
        assert set(per) == set(asked) == {"q1", "q2", "q3"}
        assert all(set(each) >= PER for each in per.values())
        assert all(set(each) >= ASKED_PER for each in asked.values())
        for measure in PER - {"section"}:
            mean = sum(each[measure] for each in per.values()) / len(per)
            assert kept["groups"][mode]["all"][measure] == pytest.approx(mean)
        for measure in ("found", "tokens"):
            mean = sum(each[measure] for each in asked.values()) / len(asked)
            assert kept["asked"][mode]["all"][measure] == pytest.approx(mean)


# BOTH, and a question that words answer with more documents than a ranking keeps.
ZEBRAS = BOTH + "- {id: q4, question: zebra, expected: ['4100']}\n"
MODES = ("lexical", "semantic", "hybrid")
# The refs of each mode's ranking that the results keep, as plan 085 says.
RANKED = 30
# The documents whose evidence each question of ZEBRAS gives.
EVIDENCED = {"q1": {"confluence:4002"}, "q2": {"confluence:4003"}}


def raw_records(data: Path, capsys: CaptureFixture[str]) -> tuple[dict, dict[str, Library]]:
    """Evaluate ZEBRAS with windows, among 35 zebra pages; give the raw records, by mode.

    And a library over the index evaluated in each mode, as a server in that mode answers.
    """
    for number in range(35):
        write(data / "docs", page(str(4100 + number), f"Zebra {number}"), "zebra\n")
    build_index(data / "docs", data / "index.sqlite", MOMENT)
    (data / "golden.yaml").write_text(ZEBRAS, encoding="utf-8")
    with serving(Scripted()) as url:
        command = ["eval", "--yes", str(data / "golden.yaml"), "--chunking", "windows"]
        assert main([*command, *options(data, url)]) == 0
    capsys.readouterr()
    [results] = (data / "eval" / "results").glob("*.json")
    [kept] = json.loads(results.read_text("utf-8"))["indexes"]
    index = SqliteIndex(data / "eval" / "indexes" / "windows" / "tiny.sqlite")
    served = {
        mode: Library(index, data / "docs", Meaning(connect_scripted()), mode) for mode in MODES
    }
    return kept["raw"], served


def test_results_hold_the_hits_of_the_first_answer_with_read_tokens_and_evidence(
    data: Path, capsys: CaptureFixture[str]
) -> None:
    """D4: each hit of search's first answer, 8 by default: its ref and section shown.

    With the tokens of reading that section as read answers, and whether its snippet and
    its section hold an expected document's evidence: q1's in 4002, q2's in 4003.
    """
    raw, served = raw_records(data, capsys)
    for mode, library in served.items():
        for question in golden(data, ZEBRAS):
            answer = library.search(question.text)
            hits = raw[mode][question.id]["hits"]
            assert len(hits) == len(re.findall(r"^\d+\. ", answer, re.MULTILINE))
            for hit in hits:
                assert (
                    responses.call(library.read, ref=hit["ref"], section=hit["section"]) in answer
                )
                read = library.read(hit["ref"], hit["section"])
                assert hit["read_tokens"] == len(read) // CHARACTERS_PER_TOKEN
            evidenced = {"q1": {"confluence:4002"}, "q2": {"confluence:4003"}}.get(
                question.id, set()
            )
            for flag in ("snippet_evidence", "section_evidence"):
                held = {hit["ref"] for hit in hits if hit[flag]}
                assert held == evidenced & {hit["ref"] for hit in hits}
    assert len(raw["semantic"]["q4"]["hits"]) == SEARCH_LIMIT
    assert {hit["ref"] for hit in raw["semantic"]["q1"]["hits"]} >= {"confluence:4002"}


def test_results_hold_the_passages_and_each_modes_first_30(
    data: Path, capsys: CaptureFixture[str]
) -> None:
    """D4: each passage of ask's first answer, by ref, with its characters and evidence.

    And the first 30 refs of each mode's ranking, which begins with the first answer's hits.
    """
    raw, served = raw_records(data, capsys)
    for mode, library in served.items():
        for question in golden(data, ZEBRAS):
            answer = library.ask(question.text)
            passages = raw[mode][question.id]["passages"]
            assert len(passages) == len(re.findall(r"^\d+\. ", answer, re.MULTILINE))
            assert all(f"| {each['ref']} | section" in answer for each in passages)
            assert all(each["characters"] > 0 for each in passages)
            held = {each["ref"] for each in passages if each["evidence"]}
            evidenced = {"q1": {"confluence:4002"}, "q2": {"confluence:4003"}}.get(
                question.id, set()
            )
            assert held == evidenced & {each["ref"] for each in passages}
            ranking = raw[mode][question.id]["ranking"]
            hits = [hit["ref"] for hit in raw[mode][question.id]["hits"]]
            assert ranking[: len(hits)] == hits
            assert len(set(ranking)) == len(ranking) <= RANKED
        assert len(raw[mode]["q4"]["ranking"]) == RANKED
    assert {each["ref"] for each in raw["semantic"]["q1"]["passages"]} >= {"confluence:4002"}


def indexed(data: Path, command: list[str], results: str) -> dict:
    """Run a command of READERS on GOLDEN; give what its results file keeps of its index."""
    assert read_by(data, command, GOLDEN) == 0
    kept = json.loads(max(data.glob(results)).read_text("utf-8"))
    return kept["indexes"][0] if "indexes" in kept else kept


@pytest.mark.parametrize(
    ("change", "same"),
    [
        (None, True),
        (("4003", "Words", "revert the release\n"), False),
        (("4004", "New", None), False),
    ],
    ids=["unchanged", "a body edited", "a document added"],
)
def test_the_digest_changes_with_one_document(
    data: Path, change: tuple[str, str, str | None] | None, *, same: bool
) -> None:
    """D5: the results keep a digest of the documents indexed, each path with its digest.

    Two runs on the same mirror keep the same digest; with one document edited or added,
    another.
    """
    command, results = READERS[0]
    before = indexed(data, command, results)["documents_sha256"]
    if change:
        page_id, title, body = change
        write(data / "docs", page(page_id, title), body)
    after = indexed(data, command, results)["documents_sha256"]
    assert re.fullmatch(r"[0-9a-f]{64}", before)
    assert (after == before) is same


@pytest.mark.parametrize(("command", "results"), READERS[:2])
def test_counts_by_source_and_type(data: Path, command: list[str], results: str) -> None:
    """D5: the results of eval and of eval-rerank count the documents indexed, by source and type.

    The mirror's fillers and two pages, a post, and two issues.
    """
    write(data / "docs", page("4005", "News", type="blogpost"), "# News\n\nA post.\n")
    write(data / "docs", issue("PROJ-8", "Kafka downgrade"))
    expected = {"confluence": {"page": FILLERS + 2, "blogpost": 1}, "jira": {"issue": 2}}
    assert indexed(data, command, results)["documents"] == expected


def test_ask_is_measured_beside_search_in_each_mode(data: Path) -> None:
    """The paraphrase: quoted with its evidence by meaning, missed by words; costs counted."""
    settings = Settings(data_dir=data, model="tiny")
    [run] = evaluate(settings, golden(data), evaluated_indexes(tiny()), ticking(), MOMENT)
    semantic, lexical = run.asked["semantic"]["q1"], run.asked["lexical"]["q1"]
    assert (semantic.found, semantic.evidence, lexical.found, lexical.evidence) == (1, 1, 0, 0)
    assert run.asked["lexical"]["q3"].found == 1.0
    assert set(run.ask_times) == {"lexical", "semantic", "hybrid"}
    assert run.costs.chunks > 0
    assert run.costs.estimated == run.costs.characters // 4
    assert (
        run.costs.bytes == (data / "eval" / "indexes" / "sections" / "tiny.sqlite").stat().st_size
    )


def test_answer_tokens_are_those_of_the_servers_answers(data: Path) -> None:
    """D4: search's and ask's first answers, as a server in each mode writes them.

    Their tokens are their characters at CHARACTERS_PER_TOKEN, the evaluation's estimate;
    a group's are their mean.
    """
    questions = golden(data)
    settings = Settings(data_dir=data, model="tiny")
    [run] = evaluate(settings, questions, evaluated_indexes(tiny()), ticking(), MOMENT)
    index = SqliteIndex(data / "eval" / "indexes" / "sections" / "tiny.sqlite")
    for mode in ("lexical", "semantic", "hybrid"):
        served = Library(index, data / "docs", Meaning(connect_scripted()), mode)
        searched = [len(served.search(each.text)) // CHARACTERS_PER_TOKEN for each in questions]
        asked = [len(served.ask(each.text)) // CHARACTERS_PER_TOKEN for each in questions]
        assert [run.per[mode][each.id].tokens for each in questions] == searched
        assert [run.asked[mode][each.id].tokens for each in questions] == asked
        assert run.groups[mode]["all"].tokens == pytest.approx(sum(searched) / len(searched))
        assert run.asked_groups[mode]["all"].tokens == pytest.approx(sum(asked) / len(asked))


def test_the_characters_embedded_are_the_same_with_the_store_warm_or_cold(data: Path) -> None:
    """Read from what the index embeds, not from what this run had to embed."""
    settings = Settings(data_dir=data, model="tiny")
    built = [evaluate(settings, golden(data), evaluated_indexes(tiny()), ticking(), MOMENT)[0]]
    built += [evaluate(settings, golden(data), evaluated_indexes(tiny()), ticking(), MOMENT)[0]]
    (data / "vectors.sqlite").unlink()
    built += [evaluate(settings, golden(data), evaluated_indexes(tiny()), ticking(), MOMENT)[0]]
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
    refusal = capsys.readouterr().err.splitlines()[-1]
    assert set(CHUNKINGS) <= set(re.findall(r"[\w-]+", refusal))


def test_each_target_s_scores_are_measured_by_its_chunking_ask_s_among_them(
    data: Path, telemetry: InMemory
) -> None:
    """One model, two chunkings: each mode's measures as the results have them.

    One question of three has evidence, so that Evidence@ask is measured too.
    """
    settings = Settings(data_dir=data, model="tiny")
    indexes = [EvaluatedIndex(tiny(), "sections"), EvaluatedIndex(tiny(), "windows")]
    runs = evaluate(settings, golden(data), indexes, ticking(), MOMENT)
    points = {
        tuple(
            str(point.attributes[key])
            for key in ("kb_mcp.chunking", "kb_mcp.mode", "kb_mcp.measure")
        ): point.value
        for point in telemetry.measured()["kb_mcp.eval.score"].data.data_points
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


def test_each_target_s_span_events_and_question_times_name_its_chunking(
    data: Path, telemetry: InMemory
) -> None:
    """Its span and its events, and its questions' times, each question once a mode."""
    indexes = [EvaluatedIndex(tiny(), "sections"), EvaluatedIndex(tiny(), "windows")]
    questions = golden(data)
    with capture_logs() as events:
        evaluate(Settings(data_dir=data, model="tiny"), questions, indexes, ticking(), MOMENT)
    every = {
        (chunking, mode): len(questions)
        for chunking in ("sections", "windows")
        for mode in ("lexical", "semantic", "hybrid")
    }
    spans = [span for span in telemetry.spans.get_finished_spans() if span.name == "eval.model"]
    assert [(span.attributes or {})["kb_mcp.chunking"] for span in spans] == ["sections", "windows"]
    timed = {
        (
            str(point.attributes["kb_mcp.chunking"]),
            str(point.attributes["kb_mcp.mode"]),
        ): point.count
        for point in telemetry.measured()["kb_mcp.eval.question.duration"].data.data_points
        if point.attributes
    }
    assert timed == every
    asked = Counter(
        (each["chunking"], each["mode"]) for each in events if each["event"] == "eval.question"
    )
    assert asked == every
    evaluated = [each["chunking"] for each in events if each["event"] == "eval.evaluated"]
    assert evaluated == ["sections", "windows"]


def test_without_evidence_found_at_ask_is_measured_and_evidence_at_ask_is_not(
    data: Path, telemetry: InMemory
) -> None:
    """A golden file whose questions have no evidence: no point of Evidence@ask."""
    without = GOLDEN.replace('  evidence: {"4002": "leave for a meal"}\n', "")
    indexes = [EvaluatedIndex(tiny(), "sections")]
    evaluate(
        Settings(data_dir=data, model="tiny"), golden(data, without), indexes, ticking(), MOMENT
    )
    measures = {
        (point.attributes or {})["kb_mcp.measure"]
        for point in telemetry.measured()["kb_mcp.eval.score"].data.data_points
    }
    assert measures == {"recall@10", "mrr@10", "ndcg@10", "success@1", "found@ask"}
