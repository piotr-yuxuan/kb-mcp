# eval-rerank

What `eval-rerank` records, besides what every command does ([README](README.md)). A run
is one trace: its root `eval-rerank`, the reranking server's list of models, the
connection to the embedding model, the whole build of its index, as the events below
list it, then the searches and answers of every question in each arm, as `serve` records
them, the reranked ones through the reranking server. A question is timed, never a span
of its own.

## Events

| Event | Level | Fields | When |
|---|---|---|---|
| `eval.refused` | error | `reason` | The golden file is refused, by the field at fault: exit 2 |
| `eval.not_evaluated` | error | `reason` | A model fails, the reranking server does not answer, or a search falls back, by words or not reranked, which would measure another arm: exit 1 |
| `index.document` | debug | `path`, `type`, `sections` | A file of the mirror is indexed for the model |
| `index.built` | info | `documents`, `sections`, `skipped`, `chunks`, `embedded`, `people` | The model's index is complete, its people joined without aliases |
| `rerank.request` | debug | `model`, `texts`, `characters`, `tokens` | A reranking: how many texts, how long in all, the tokens that the server counted; never their text |
| `rerank.fallback` | warning | `kind`, `reason` | A reranking fails, of kind `unanswered`, `refused` or `bad_answer`: the search keeps its order, which stops the evaluation |
| `http.get` | debug | `url`, `status`, `error`, `seconds` | Each request for a list of models: the embedding endpoint's, the reranking server's |
| `http.post` | debug | `url`, `status`, `error`, `seconds` | Each request for embeddings, or for a reranking |

## Spans

| Span | Kind | Attributes | What |
|---|---|---|---|
| `index.files` | internal | | The mirror's files read and indexed by words |
| `index.join` | internal | | The documents' people joined into persons, once the files are read |
| `index.embed` | internal | | The chunks by meaning: their vectors read from the vector store, or embedded |
| `search.lexical` | internal | | A search by words |
| `search.semantic` | internal | | A search by meaning |
| `embeddings <model>` | client | `gen_ai.operation.name`, `gen_ai.provider.name`, `gen_ai.request.model`, `server.address`, `server.port`, `error.type`, `gen_ai.usage.input_tokens` | An embedding by the GenAI conventions, its attempts included, and the tokens that the endpoint counted, if it did |
| `rerank <model>` | client | `gen_ai.operation.name`, `gen_ai.provider.name`, `gen_ai.request.model`, `server.address`, `server.port`, `error.type`, `gen_ai.usage.input_tokens`, `kb_mcp.rerank.texts`, `kb_mcp.rerank.characters` | A reranking, its operation `rerank`, a name of this project's, as the GenAI conventions name none for reranking; how many texts, how long in all, and the tokens that the server counted, if it did |
| `GET` | client | `http.request.method`, `server.address`, `server.port`, `url.full`, `http.response.status_code`, `error.type` | A list of models, by the HTTP conventions |
| `POST` | client | `http.request.method`, `server.address`, `server.port`, `url.full`, `http.response.status_code`, `error.type` | Each attempt at an embedding or a reranking, by the HTTP conventions |

## Instruments

| Instrument | Kind | Unit | Attributes | What |
|---|---|---|---|---|
| `kb_mcp.index.files` | counter | `{file}` | `kb_mcp.outcome` | The mirror's files, `indexed` or `skipped` |
| `kb_mcp.index.chunks` | counter | `{chunk}` | `kb_mcp.outcome` | The chunks by meaning, `indexed` with a vector or `refused` one |
| `kb_mcp.rerank.fallbacks` | counter | `{fallback}` | `kb_mcp.rerank.fallback` | The searches not reranked, by the failure's kind |
| `gen_ai.client.operation.duration` | histogram | `s` | `gen_ai.operation.name`, `gen_ai.provider.name`, `gen_ai.request.model`, `server.address`, `server.port`, `error.type` | Each embedding and each reranking, its attempts and waits included, by the GenAI conventions |
| `gen_ai.client.token.usage` | histogram | `{token}` | `gen_ai.operation.name`, `gen_ai.provider.name`, `gen_ai.request.model`, `server.address`, `server.port`, `gen_ai.token.type` | The tokens that each answer of an embedding or a reranking counted, `input` by type, when the server counts them, by the GenAI conventions |
| `http.client.request.duration` | histogram | `s` | `http.request.method`, `server.address`, `server.port`, `http.response.status_code`, `error.type` | Each request, by the HTTP conventions |
