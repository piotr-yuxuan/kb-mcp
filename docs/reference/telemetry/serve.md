# serve

What `serve` records, besides what every command does ([README](README.md)). A server
is no trace of its own: each message of the protocol is a trace, whose root is the MCP
SDK's span, by the MCP conventions, named after its method and its tool or prompt. A
search or an ask adds its own spans below the call's: by words, then by meaning, with
the embedding of the query and its requests, then, when reranking is on, the reranking
of its first documents and its requests. The SDK records no metric; each tool call
is measured here. Its records carry no span's ids but those logged within a call.

Stdout holds the protocol alone; on a terminal, stderr shows no bar, as the server has
no task.

## Events

| Event | Level | Fields | When |
|---|---|---|---|
| `serve.call` | debug | `tool`, `arguments`, `error`, `seconds`, `size` | A tool answers: its name, the arguments, `tool_error` when it could not answer as asked, or the class of what it raised, such as `builtins.KeyError`, how long it took, the answer's bytes |
| `search.fallback` | warning | `mode`, `reason` | A search or an ask by meaning is ranked by words alone, and says why to the agent: no vectors, an endpoint that does not answer, a model of other weights |
| `rerank.request` | debug | `model`, `texts`, `characters`, `tokens` | A search's or an ask's first documents reranked: how many texts, how long in all, the tokens that the server counted; never their text |
| `rerank.fallback` | warning | `kind`, `reason` | A reranking fails, of kind `unanswered`, `refused` or `bad_answer`: the search keeps its order and says why; after a failure but a refusal, those of the next 30 seconds ask nothing and say nothing here |
| `http.get` | debug | `url`, `status`, `error`, `seconds` | Each request for the endpoint's list of models |
| `http.post` | debug | `url`, `status`, `error`, `seconds` | Each request for an embedding or a reranking |

## Spans

| Span | Kind | Attributes | What |
|---|---|---|---|
| `initialize` | server | `mcp.method.name`, `mcp.protocol.version`, `jsonrpc.request.id`, `error.type`, `rpc.response.status_code` | The SDK's: the handshake of an agent of an earlier version of the protocol |
| `notifications/initialized` | server | `mcp.method.name`, `mcp.protocol.version` | The SDK's: the agent says that the handshake is done |
| `server/discover` | server | `mcp.method.name`, `mcp.protocol.version`, `jsonrpc.request.id`, `error.type`, `rpc.response.status_code` | The SDK's: what the server offers, asked by a client of a later version |
| `tools/list` | server | `mcp.method.name`, `mcp.protocol.version`, `jsonrpc.request.id`, `error.type`, `rpc.response.status_code` | The SDK's: the list of tools |
| `tools/call <tool>` | server | `mcp.method.name`, `mcp.protocol.version`, `jsonrpc.request.id`, `gen_ai.operation.name`, `gen_ai.tool.name`, `error.type`, `rpc.response.status_code`, `aom.mode`, `aom.hits`, `aom.fallback`, `aom.reranked`, `aom.passages` | The SDK's: a call of `ask`, `search`, `read`, `browse` or `status`; `error.type` `tool_error` when it cannot be answered as asked. An ask or a search adds its mode, how many documents it found, whether it fell back, to words or by keeping its order not reranked, and whether its first documents were reranked, on a next page by the order that its cursor carries; an ask, how many passages it quoted |
| `prompts/list` | server | `mcp.method.name`, `mcp.protocol.version`, `jsonrpc.request.id`, `error.type`, `rpc.response.status_code` | The SDK's: the prompts that the tools served allow |
| `prompts/get <prompt>` | server | `mcp.method.name`, `mcp.protocol.version`, `jsonrpc.request.id`, `gen_ai.prompt.name`, `error.type`, `rpc.response.status_code` | The SDK's: a prompt written, `brief`, `changes` or `overview`; `error.type` `-32602` when an argument is refused |
| `search.lexical` | internal | | A search by words, the documents named first |
| `search.semantic` | internal | | A search by meaning: the model connected once an index, the query embedded, the nearest pieces |
| `embeddings <model>` | client | `gen_ai.operation.name`, `gen_ai.provider.name`, `gen_ai.request.model`, `server.address`, `server.port`, `error.type`, `gen_ai.usage.input_tokens` | An embedding by the GenAI conventions, its attempts included, and the tokens that the endpoint counted, if it did |
| `rerank <model>` | client | `gen_ai.operation.name`, `gen_ai.provider.name`, `gen_ai.request.model`, `server.address`, `server.port`, `error.type`, `gen_ai.usage.input_tokens`, `aom.rerank.texts`, `aom.rerank.characters` | A reranking, its operation `rerank`, a name of this project's, as the GenAI conventions name none for reranking; how many texts, how long in all, and the tokens that the server counted, if it did |
| `GET` | client | `http.request.method`, `server.address`, `server.port`, `url.full`, `http.response.status_code`, `error.type` | The endpoint's list of models, by the HTTP conventions |
| `POST` | client | `http.request.method`, `server.address`, `server.port`, `url.full`, `http.response.status_code`, `error.type` | Each attempt at an embedding or a reranking, by the HTTP conventions |

## Instruments

| Instrument | Kind | Unit | Attributes | What |
|---|---|---|---|---|
| `mcp.server.operation.duration` | histogram | `s` | `mcp.method.name`, `gen_ai.operation.name`, `gen_ai.tool.name`, `error.type` | Each tool call, from the tool's call to its answer, in the buckets that the MCP conventions advise; the SDK's validation and writing aside; a failed one with `error.type`, as `serve.call` names its error |
| `aom.serve.answer.size` | histogram | `By` | `gen_ai.tool.name` | How long each answer is |
| `aom.serve.fallbacks` | counter | `{fallback}` | `aom.mode` | The searches and asks by meaning ranked by words alone; 0 from the server's start |
| `aom.rerank.fallbacks` | counter | `{fallback}` | `aom.rerank.fallback` | The searches and asks not reranked, by why: a failure's kind, or `quiet` within 30 seconds of one |
| `gen_ai.client.operation.duration` | histogram | `s` | `gen_ai.operation.name`, `gen_ai.provider.name`, `gen_ai.request.model`, `server.address`, `server.port`, `error.type` | Each embedding and each reranking, its attempts and waits included, by the GenAI conventions |
| `gen_ai.client.token.usage` | histogram | `{token}` | `gen_ai.operation.name`, `gen_ai.provider.name`, `gen_ai.request.model`, `server.address`, `server.port`, `gen_ai.token.type` | The tokens that each answer of an embedding or a reranking counted, `input` by type, when the server counts them, by the GenAI conventions |
| `http.client.request.duration` | histogram | `s` | `http.request.method`, `server.address`, `server.port`, `http.response.status_code`, `error.type` | Each request, by the HTTP conventions |
