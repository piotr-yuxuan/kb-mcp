# Observe runs with Grafana

How to see what the command's runs do, as traces, metrics and logs, in Grafana's LGTM
container on this machine: with podman, or with Docker just as well. Telemetry is off
until an endpoint is set; without it, each run still writes its log file, as
[the reference](../reference/telemetry/README.md) describes.

## 1. Start the container

From a checkout of the repository, with podman and a compose provider for it
(`podman compose version` names the one it runs, podman-compose or docker-compose):

```bash
podman compose -f deploy/lgtm/compose.yaml up -d
```

With Docker and its compose plugin, the same file serves:

```bash
docker compose -f deploy/lgtm/compose.yaml up -d
```

On macOS, podman runs containers in a virtual machine: `podman machine init` once, then
`podman machine start` before `up`. The first start pulls the image, about 2.75 GB,
pinned by its digest in `deploy/lgtm/compose.yaml`. Grafana answers within a minute at
<http://127.0.0.1:3000>, without signing in: anonymous users are Admin there, so the
container publishes its two ports on the loopback address alone, 3000 for Grafana and
4318 for OTLP over HTTP, and Grafana turns away any other host name, `localhost`
included, with a redirect to `127.0.0.1`, against DNS rebinding. Nothing in it calls
home, and it has no volume.

## 2. Send the runs' telemetry

Set the endpoint in the settings file:

```toml
[telemetry]
endpoint = "http://127.0.0.1:4318"
```

or for one run, in its environment, `ATLASSIAN_OFFLINE_MCP_TELEMETRY__ENDPOINT`, or
`OTEL_EXPORTER_OTLP_ENDPOINT`, which other programs read too and the settings file
outweighs. The endpoint is plain http to a literal address of this machine, with a
port and no path: `localhost` is refused, since a name could lead elsewhere. `check`
shows the endpoint that a run would use, and its layer:

```bash
atlassian-offline-mcp check --summary detailed
```

A run then sends its traces, metrics and logs from INFO as it goes, metrics every 15
seconds. If the container is not running, a run says `telemetry.undelivered` once, at
its start, and goes on without it; if the container stops answering, a run's end
waits 5 seconds for it at most. `OTEL_SDK_DISABLED=true` turns telemetry off for a run,
whatever sets the endpoint.

## 3. Read the dashboards

Under Dashboards, the folder `atlassian-offline-mcp` holds an overview and one
dashboard each for `download`, `mirror`, `index`, `serve` and `eval`, read-only, from
`deploy/lgtm/dashboards/`:

- **Overview**: the runs of each command, those that failed by their exit status, the
  time spent, the requests to the site by status, the warnings and errors of every run
  from the logs, and the runs as traces.
- **download, mirror, index, eval**: over the last 24 hours, the runs, the time spent,
  the documents, files, bytes or pieces by outcome, the time of requests, embeddings or
  conversions at the 95th percentile, then the runs' warnings and errors and their
  traces. Each panel sums each run's last value, so a run counts once, whenever it
  ended.
- **serve**: over the last hour, rates: tool calls per second by tool, their time and
  the answers' size at the 95th percentile, the searches that fell back to words, the
  queries' embedding time, then the warnings and the calls as traces.

A panel whose title begins with "Failed" shows failures alone, and stays empty after a
sound run. Each panel opens its query in Explore, under its menu.

## 4. Search the traces in Tempo

A run is one trace, named after its command; each document that `download` fetches is a
trace of its own, linked to the run's, and each message of `serve`'s protocol is one
too. In Explore, choose the source `tempo` and TraceQL; for instance:

| To find | TraceQL |
|---|---|
| The runs of a command | `{ resource.service.name = "atlassian-offline-mcp" && span.aom.command = "download" }` |
| The runs that failed | `{ span.aom.exit_status != 0 }` |
| One run, by the `run` of its log file | `{ resource.service.instance.id = "<run>" }` |
| The issues that a download fetched | `{ name = "download.document" && span.aom.document.kind = "jira issues" }` |
| The requests refused or failed | `{ span.http.response.status_code >= 400 }` |
| The slow requests and embeddings | `{ kind = client && duration > 500ms }` |
| The searches that fell back to words | `{ span.mcp.method.name = "tools/call" && span.aom.fallback = true }` |
| Anything that failed | `{ status = error }` |

The spans, their attributes and the instruments are listed in
[the reference](../reference/telemetry/README.md), a page per command. A line of a log
file in a span carries its `trace_id`, which Tempo's search by trace id opens.

## 5. Check the dashboards

Once the container has received a run of each command, the opt-in test asks Grafana for
every dashboard of the folder and every query of their panels: each must answer without
error, and each panel but those of failures must have data; Loki must hold the runs'
records; another host name must be turned away:

```bash
ATLASSIAN_OFFLINE_MCP_GRAFANA=http://127.0.0.1:3000 uv run pytest tests/test_grafana.py
```

`serve`'s panels are rates, which need two exports within their interval, a minute:
keep the server running for half a minute or more, with calls on both sides of its
first export, 15 seconds after it starts. If Loki holds no record, look at the disk:
Loki stops taking logs once the disk that holds the container is 90% full.

## 6. Stop, discard, upgrade

`stop` keeps what the container received until `start`; `down` removes the container,
and with it everything it received, since it has no volume:

```bash
podman compose -f deploy/lgtm/compose.yaml stop
podman compose -f deploy/lgtm/compose.yaml start
podman compose -f deploy/lgtm/compose.yaml down
```

With Docker, `docker compose` takes the same words. The image stays on the disk after
`down`; `podman image rm` or `docker image rm`, with the image as `compose.yaml` names
it, frees its 2.75 GB.

To upgrade, read the digest of the new tag from Docker Hub's tag API, here for 0.37.0:

```bash
curl -s https://hub.docker.com/v2/repositories/grafana/otel-lgtm/tags/0.37.0 | python3 -c 'import json, sys; tag = json.load(sys.stdin); print(tag["name"], tag["digest"], tag["tag_last_pushed"])'
```

then write the tag and the digest in `deploy/lgtm/compose.yaml` and in `IMAGE` of
`tests/test_lgtm.py`, read the image's release notes for its variables, run
`uv run pytest tests/test_lgtm.py`, and `down` then `up -d` again. Pinning by digest
keeps a tag that is pushed again from changing what runs.
