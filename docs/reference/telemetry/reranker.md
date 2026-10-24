# reranker

What `reranker check` records, besides what every command does ([README](README.md)). A
run is one trace: its root `reranker`, the server's list of models, then a reranking of
the probe, then one of `rerank.depth` texts, timed.

## Events

| Event | Level | Fields | When |
|---|---|---|---|
| `reranker.not_ready` | error | `reason` | The server does not answer, is not a reranker, or ranks an unrelated passage as high as the answer: exit 1 |
| `http.get` | debug | `url`, `status`, `error`, `seconds` | Each request for the server's list of models |
| `http.post` | debug | `url`, `status`, `error`, `seconds` | Each request for a reranking |

## Spans

| Span | Kind | Attributes | What |
|---|---|---|---|
| `GET` | client | `http.request.method`, `server.address`, `server.port`, `url.full`, `http.response.status_code`, `error.type` | The server's list of models, by the HTTP conventions |
| `POST` | client | `http.request.method`, `server.address`, `server.port`, `url.full`, `http.response.status_code`, `error.type` | Each attempt at a reranking, by the HTTP conventions |

## Instruments

| Instrument | Kind | Unit | Attributes | What |
|---|---|---|---|---|
| `http.client.request.duration` | histogram | `s` | `http.request.method`, `server.address`, `server.port`, `http.response.status_code`, `error.type` | Each request, by the HTTP conventions |
