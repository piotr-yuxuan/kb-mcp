"""Grafana's LGTM container and its dashboards, as files: nothing is pulled or run.

The compose file pins the image, publishes two ports on the loopback address only, sets
what turns away other host names and keeps the stack from calling home, and keeps no data.
Each dashboard, found in its folder, draws on the image's own data sources only, and
charts no metric but those of the reference, ``docs/reference/telemetry/``, named as
Prometheus names what it receives over OTLP.
"""

from __future__ import annotations

import json
import re
from pathlib import Path, PurePosixPath

import pytest
import yaml

from tests.reference import README, documented, operations

LGTM = Path(__file__).parents[1] / "deploy" / "lgtm"
COMPOSE = LGTM / "compose.yaml"
DASHBOARDS = LGTM / "dashboards"
# 0.37.0, as Docker Hub's tag API gave it on 2026-10-21 and again on 2026-10-22.
IMAGE = (
    "docker.io/grafana/otel-lgtm:0.37.0"
    "@sha256:57b5ab1ca6619beb180174e2fccce04762470750669d043f544b4726d0582d07"
)
# Grafana, and OTLP over HTTP, on the loopback address only.
PORTS = ["127.0.0.1:3000:3000", "127.0.0.1:4318:4318"]
# Against DNS rebinding, then against calling home.
VARIABLES = {
    "GF_SERVER_DOMAIN": "127.0.0.1",
    "GF_SERVER_ENFORCE_DOMAIN": "true",
    "GF_ANALYTICS_REPORTING_ENABLED": "false",
    "GF_ANALYTICS_CHECK_FOR_UPDATES": "false",
    "GF_ANALYTICS_CHECK_FOR_PLUGIN_UPDATES": "false",
    "GF_PLUGINS_PREINSTALL_DISABLED": "true",
    "LOKI_EXTRA_ARGS": "-reporting.enabled=false",
    "TEMPO_EXTRA_ARGS": "-reporting.enabled=false",
    "PYROSCOPE_EXTRA_ARGS": "-usage-stats.enabled=false",
}
# Where the image's Grafana reads its providers of dashboards.
PROVIDERS = PurePosixPath("/otel-lgtm/grafana/conf/provisioning/dashboards")
# The data sources that the image provisions: each one's uid and type.
SOURCES = {("prometheus", "prometheus"), ("loki", "loki"), ("tempo", "tempo")}
# The overview, then one dashboard per operation; a later plan adds its own beside them.
NAMES = {"overview", "download", "mirror", "index", "serve", "eval"}
# Grafana's longest uid.
UID_LENGTH = 40
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


def test_the_image_is_pinned_by_its_digest_with_the_registry_written_out() -> None:
    """Podman would ask which registry a short name means."""
    services = yaml.safe_load(COMPOSE.read_text("utf-8"))["services"]
    assert [service["image"] for service in services.values()] == [IMAGE]


def test_only_grafana_and_otlp_over_http_are_published_on_the_loopback_address() -> None:
    """No other port, nor the host's network, which would publish every port."""
    services = yaml.safe_load(COMPOSE.read_text("utf-8"))["services"].values()
    assert [port for service in services for port in service.get("ports", [])] == PORTS
    assert all("network_mode" not in service for service in services)


def test_each_variable_against_dns_rebinding_and_calling_home_is_set() -> None:
    """Each a string, passed on as written: compose tools differ over a YAML boolean."""
    (service,) = yaml.safe_load(COMPOSE.read_text("utf-8"))["services"].values()
    assert {name: service["environment"].get(name) for name in VARIABLES} == VARIABLES


def test_no_volume_keeps_data_and_the_dashboards_folder_is_mounted_whole_read_only() -> None:
    """``down`` discards the data; Grafana's provider reads the folder that is mounted."""
    compose = yaml.safe_load(COMPOSE.read_text("utf-8"))
    assert "volumes" not in compose
    (service,) = compose["services"].values()
    mounts = [mount.split(":") for mount in service["volumes"]]
    assert all(mode == "ro" for _, _, mode in mounts)
    targets = {source: PurePosixPath(target) for source, target, _ in mounts}
    assert set(targets) == {"./dashboards", "./dashboards.yaml"}
    assert targets["./dashboards.yaml"].parent == PROVIDERS
    (provider,) = yaml.safe_load((LGTM / "dashboards.yaml").read_text("utf-8"))["providers"]
    assert PurePosixPath(provider["options"]["path"]) == targets["./dashboards"]
    assert provider["allowUiUpdates"] is False


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
    """Every name of a metric in every Prometheus query is one that an instrument gives.

    The instruments, each with its kind and unit, are those that the reference lists,
    every command's and each command's, its pages found in their folder.
    """
    pages = [documented(page) for page in (README, *operations())]
    instruments = {
        name: (kind, unit) for page in pages for name, (kind, unit, _) in page.instruments.items()
    }
    known = set()
    for name, (kind, unit) in instruments.items():
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
