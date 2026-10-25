# reranker

What `reranker check` records, besides what every command does ([README](README.md)). A
run is one trace: its root `reranker`, the server's list of models, then a reranking of
the probe, then one of `rerank.depth` texts, timed, each a reranking span.

## Events

| Event | Level | Fields | When |
|---|---|---|---|
| `reranker.not_ready` | error | `reason` | The server does not answer, is not a reranker, or ranks an unrelated passage as high as the answer: exit 1 |
| `rerank.request` | debug | `model`, `texts`, `characters`, `tokens` | A reranking: how many texts, how long in all, the tokens that the server counted; never their text |
| `http.get` | debug | `url`, `status`, `error`, `seconds` | Each request for the server's list of models |
| `http.post` | debug | `url`, `status`, `error`, `seconds` | Each request for a reranking |

## Spans

| Span | Kind | Attributes | What |
|---|---|---|---|
| `rerank <model>` | client | `gen_ai.operation.name`, `gen_ai.provider.name`, `gen_ai.request.model`, `server.address`, `server.port`, `error.type`, `gen_ai.usage.input_tokens`, `aom.rerank.texts`, `aom.rerank.characters` | A reranking, its operation `rerank`, a name of this project's, as the GenAI conventions name none for reranking; how many texts, how long in all, and the tokens that the server counted, if it did |
| `GET` | client | `http.request.method`, `server.address`, `server.port`, `url.full`, `http.response.status_code`, `error.type` | The server's list of models, by the HTTP conventions |
| `POST` | client | `http.request.method`, `server.address`, `server.port`, `url.full`, `http.response.status_code`, `error.type` | Each attempt at a reranking, by the HTTP conventions |

## Instruments

| Instrument | Kind | Unit | Attributes | What |
|---|---|---|---|---|
| `gen_ai.client.operation.duration` | histogram | `s` | `gen_ai.operation.name`, `gen_ai.provider.name`, `gen_ai.request.model`, `server.address`, `server.port`, `error.type` | Each reranking, its attempts and waits included, by the GenAI conventions |
| `gen_ai.client.token.usage` | histogram | `{token}` | `gen_ai.operation.name`, `gen_ai.provider.name`, `gen_ai.request.model`, `server.address`, `server.port`, `gen_ai.token.type` | The tokens that each reranking's answer counted, `input` by type, when the server counts them, by the GenAI conventions |
| `http.client.request.duration` | histogram | `s` | `http.request.method`, `server.address`, `server.port`, `http.response.status_code`, `error.type` | Each request, by the HTTP conventions |
