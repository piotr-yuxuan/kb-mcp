"""Grafana's LGTM container, live: opt-in, by ``ATLASSIAN_OFFLINE_MCP_GRAFANA``.

The variable gives Grafana's address, ``http://127.0.0.1:3000`` as ``deploy/lgtm/``
publishes it, once the container runs and the commands have sent it their telemetry, as
plan 016's stack check does. Every dashboard of the folder is then found in Grafana,
every query of its panels answers without error, and every panel has data but those of
failures, which a sound run need not have. Under another host name, Grafana answers
nothing but a redirect to its own.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import TYPE_CHECKING

import httpx
import pytest

from tests.endpoint import REACHABLE

if TYPE_CHECKING:
    from collections.abc import Iterator

GRAFANA = os.environ.get("ATLASSIAN_OFFLINE_MCP_GRAFANA")
DASHBOARDS = Path(__file__).parents[1] / "deploy" / "lgtm" / "dashboards"
PATHS = sorted(DASHBOARDS.iterdir())
# What the title of a panel of failures begins with.
FAILURES = "Failed"
# A name that resolves to this machine as an attacker's would, by DNS rebinding.
ANOTHER_HOST = "rebound.example"
# How long Grafana has to answer each request, in seconds.
WAIT_S = 30

pytestmark = pytest.mark.skipif(
    GRAFANA is None, reason="set ATLASSIAN_OFFLINE_MCP_GRAFANA to Grafana's address"
)


@pytest.fixture
def grafana() -> Iterator[httpx.Client]:
    """Give a client of Grafana at the address given, which the network's guard lets through.

    Proxies are not read: the container is on this machine.
    """
    address = httpx.URL(str(GRAFANA))
    REACHABLE.add(address.port or 0)
    try:
        with httpx.Client(base_url=address, timeout=WAIT_S, trust_env=False) as client:
            yield client
    finally:
        REACHABLE.discard(address.port or 0)


@pytest.mark.parametrize("path", PATHS, ids=lambda path: path.name)
def test_each_dashboard_is_found_and_each_panel_but_failures_has_data(
    path: Path, grafana: httpx.Client
) -> None:
    """Each query over the dashboard's own time range, as its panel asks it.

    A panel has data when a frame of one of its queries has a row.
    """
    board = json.loads(path.read_text("utf-8"))
    found = grafana.get(f"/api/dashboards/uid/{board['uid']}")
    assert found.status_code == httpx.codes.OK
    titles = [panel["title"] for panel in board["panels"]]
    assert [panel["title"] for panel in found.json()["dashboard"]["panels"]] == titles
    empty = []
    for panel in board["panels"]:
        asked = {"queries": panel["targets"], **board["time"]}
        answered = grafana.post("/api/ds/query", json=asked)
        assert answered.status_code == httpx.codes.OK, (panel["title"], answered.text)
        results = answered.json()["results"].values()
        assert [result.get("error") for result in results] == [None] * len(results)
        frames = [frame for result in results for frame in result.get("frames", [])]
        if not any(column for frame in frames for column in frame["data"]["values"]):
            empty.append(panel["title"])
    assert [title for title in empty if not title.startswith(FAILURES)] == []


def test_grafana_turns_away_another_host_name(grafana: httpx.Client) -> None:
    """Against DNS rebinding: under another name, no dashboard, only a redirect to its own."""
    (path, *_) = PATHS
    uid = json.loads(path.read_text("utf-8"))["uid"]
    own = grafana.get(f"/api/dashboards/uid/{uid}")
    turned = grafana.get(f"/api/dashboards/uid/{uid}", headers={"Host": ANOTHER_HOST})
    assert own.status_code == httpx.codes.OK
    assert turned.is_redirect
    assert httpx.URL(turned.headers["location"]).host == grafana.base_url.host
