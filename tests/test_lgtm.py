"""Grafana's LGTM dashboards, as files: each found in its folder, read as Grafana would.

Each draws on the image's own data sources only, and charts no metric but those of the
reference, named as Prometheus names what it receives over OTLP.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

DASHBOARDS = Path(__file__).parents[1] / "deploy" / "lgtm" / "dashboards"
# The data sources that the image provisions: each one's uid and type.
SOURCES = {("prometheus", "prometheus"), ("loki", "loki"), ("tempo", "tempo")}
# The overview, then one dashboard per operation; a later plan adds its own beside them.
NAMES = {"overview", "download", "mirror", "index", "serve", "eval"}
# Grafana's longest uid.
UID_LENGTH = 40
# The instruments of the reference, each one's kind and unit. Step 11 of plan 016 ties
# this list to the pages of docs/reference/telemetry/.
INSTRUMENTS = {
    "aom.run.duration": ("histogram", "s"),
    "http.client.request.duration": ("histogram", "s"),
    "gen_ai.client.operation.duration": ("histogram", "s"),
    "mcp.server.operation.duration": ("histogram", "s"),
    "aom.download.documents": ("counter", "{document}"),
    "aom.download.files": ("counter", "{file}"),
    "aom.download.bytes": ("counter", "By"),
    "aom.mirror.documents": ("counter", "{document}"),
    "aom.mirror.conversion.duration": ("histogram", "s"),
    "aom.index.files": ("counter", "{file}"),
    "aom.index.pieces": ("counter", "{piece}"),
    "aom.serve.answer.size": ("histogram", "By"),
    "aom.serve.fallbacks": ("counter", "{fallback}"),
    "aom.eval.question.duration": ("histogram", "s"),
    "aom.eval.score": ("gauge", "1"),
}
# Prometheus's names for what it receives over OTLP, by default: the name's words joined
# by underscores, then the unit's word unless there already (an annotation in braces
# adds none, unit 1 adds ``ratio`` to a gauge), then a suffix per series of the kind.
UNIT_WORDS = {"s": "seconds", "By": "bytes"}
SERIES = {"counter": ("_total",), "gauge": ("",), "histogram": ("_bucket", "_sum", "_count")}
# What in a PromQL expression names no metric: a string, label matchers, a range, the
# labels listed after ``by``, ``on`` and their kin.
NOT_METRICS = re.compile(
    r'"[^"]*"|\{[^}]*\}|\[[^\]]*\]'
    r"|\b(?:by|without|on|ignoring|group_left|group_right)\s*\([^)]*\)"
)
# A name that no parenthesis follows: a metric, or an operator written as a word.
NAME = re.compile(r"\b[a-zA-Z_:][a-zA-Z0-9_:]*\b(?!\s*\()")
OPERATORS = {"and", "or", "unless", "bool", "offset"}
PATHS = sorted(DASHBOARDS.iterdir())


def test_the_folder_holds_the_overview_and_each_operation_s_with_unique_uids() -> None:
    """Grafana keys a dashboard by its uid."""
    assert {path.stem for path in PATHS} >= NAMES
    uids = [json.loads(path.read_text("utf-8"))["uid"] for path in PATHS]
    assert all(isinstance(uid, str) and 0 < len(uid) <= UID_LENGTH for uid in uids)
    assert len(set(uids)) == len(uids)


@pytest.mark.parametrize("path", PATHS, ids=lambda path: path.name)
def test_each_dashboard_is_json_drawing_on_the_image_s_three_sources(path: Path) -> None:
    """Each panel and each query names its source, as the image provisions it.

    Together they use all three: metrics, logs and traces.
    """
    board = json.loads(path.read_text("utf-8"))
    named = [panel["datasource"] for panel in board["panels"]] + [
        target["datasource"] for panel in board["panels"] for target in panel["targets"]
    ]
    assert {(source["uid"], source["type"]) for source in named} == SOURCES


@pytest.mark.parametrize("path", PATHS, ids=lambda path: path.name)
def test_each_dashboard_charts_only_metrics_of_the_reference(path: Path) -> None:
    """Every name of a metric in every Prometheus query is one that an instrument gives."""
    known = set()
    for name, (kind, unit) in INSTRUMENTS.items():
        words = re.split(r"[^a-z0-9]+", name)
        word = "ratio" if (kind, unit) == ("gauge", "1") else UNIT_WORDS.get(unit)
        stem = "_".join([*words, word] if word and word not in words else words)
        known |= {stem + suffix for suffix in SERIES[kind]}
    board = json.loads(path.read_text("utf-8"))
    queries = [
        target["expr"]
        for panel in board["panels"]
        for target in panel["targets"]
        if target["datasource"]["uid"] == "prometheus"
    ]
    for query in queries:
        metrics = set(NAME.findall(NOT_METRICS.sub(" ", query))) - OPERATORS
        assert metrics, query
        assert metrics <= known, query
