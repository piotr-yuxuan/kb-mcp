# eval

What `eval` records, besides what every command does ([README](README.md)). A run is one
trace: its root `eval`, the connections, one an evaluated index, then a span per evaluated index, a
model and a chunking, which holds the whole build of its index, as the events below list it,
and the searches and answers of every question in every mode, as `serve` records them:
those that rank and answer it for the measures, then its `search` and its `ask` as the
server answers an agent, for their tokens, the search timed. The attributes that those
two set on their call's span stay off the run's spans. A question is timed and logged,
never a span of its own. A build that waits for a prune of
the vector cache records `vectors.lock_wait`, as [embed.md](embed.md) lists it, and one
that waits past 60 s is `eval.not_evaluated`. Each build's tasks are `files`, each file
read by its path, and `texts to embed`, those that the vector cache lacks; then the task
`questions` reports every question in every mode, as the README says of tasks, each
named by its mode and id, then, once one of the mode is done, by the MRR@10 of those
done, and their Evidence@ask when one has evidence, such as `hybrid q12: MRR@10 0.712,
Evidence@ask 0.455`.

## Events

| Event | Level | Fields | When |
|---|---|---|---|
| `eval.question` | debug | `id`, `chunking`, `mode`, `seconds`, `reciprocal_rank` | A golden question is ranked in a mode, then answered as `ask` answers: its id, never its text; the seconds are those of its `search` as the server answers it |
| `eval.evaluated` | info | `model`, `chunking`, `questions`, `embedded`, `index_seconds` | An index is evaluated: the questions, the texts embedded for its index, how long the index took |
| `eval.refused` | error | `reason` | The golden file is refused, by the field at fault, or no question of it is left once those whose expected ref names no document of the index are skipped, each named: exit 2 |
| `eval.not_evaluated` | error | `reason` | A model fails, a source's file of the mirror does not read, naming it and `kb-mcp prepare`, or a mode by meaning fell back to words, which would measure words twice: exit 1 |
| `index.document` | debug | `path`, `type`, `sections` | A file of the mirror is indexed for the model |
| `index.built` | info | `documents`, `sections`, `skipped`, `chunks`, `embedded`, `persons` | The model's index is complete, its people joined into persons without aliases |
| `search.fallback` | warning | `mode`, `reason` | A search by meaning is ranked by words alone, which stops the evaluation |
| `http.get` | debug | `url`, `status`, `error`, `seconds` | Each request for the endpoint's list of models |
| `http.post` | debug | `url`, `status`, `error`, `seconds` | Each request for embeddings |

## Spans

| Span | Kind | Attributes | What |
|---|---|---|---|
| `eval.model` | internal | `gen_ai.request.model`, `kb_mcp.chunking` | An evaluated index, a model and a chunking: its index built, then every question ranked and answered in every mode |
| `index.files` | internal | | The mirror's files read and indexed by words |
| `index.join` | internal | | The documents' people joined into persons, once the files are read |
| `index.embed` | internal | | The chunks by meaning: their vectors read from the vector cache, or embedded |
| `search.lexical` | internal | | A search by words |
| `search.semantic` | internal | | A search by meaning |
| `embeddings <model>` | client | `gen_ai.operation.name`, `gen_ai.provider.name`, `gen_ai.request.model`, `server.address`, `server.port`, `error.type`, `gen_ai.usage.input_tokens` | An embedding by the GenAI conventions, its attempts included, and the tokens that the endpoint counted, if it did |
| `GET` | client | `http.request.method`, `server.address`, `server.port`, `url.full`, `http.response.status_code`, `error.type` | The endpoint's list of models, by the HTTP conventions |
| `POST` | client | `http.request.method`, `server.address`, `server.port`, `url.full`, `http.response.status_code`, `error.type` | Each attempt at an embedding, by the HTTP conventions |

## Instruments

| Instrument | Kind | Unit | Attributes | What |
|---|---|---|---|---|
| `kb_mcp.eval.question.duration` | histogram | `s` | `kb_mcp.chunking`, `kb_mcp.mode` | How long each question's `search` took, as the server answers it |
| `kb_mcp.eval.score` | gauge | `1` | `gen_ai.request.model`, `kb_mcp.chunking`, `kb_mcp.mode`, `kb_mcp.measure` | Each mode's measure on all the questions: `recall@10`, `mrr@10`, `ndcg@10`, `success@1`, `found@ask` and `evidence@ask`; Section@10, which a golden file without evidence lacks, is in the results file alone, as is Evidence@ask without evidence |
| `kb_mcp.index.files` | counter | `{file}` | `kb_mcp.outcome` | The mirror's files, `indexed` or `skipped` |
| `kb_mcp.index.chunks` | counter | `{chunk}` | `kb_mcp.outcome` | The chunks by meaning, `indexed` with a vector or `refused` one |
| `kb_mcp.serve.fallbacks` | counter | `{fallback}` | `kb_mcp.mode` | A search by meaning ranked by words alone, as a server counts it |
| `gen_ai.client.operation.duration` | histogram | `s` | `gen_ai.operation.name`, `gen_ai.provider.name`, `gen_ai.request.model`, `server.address`, `server.port`, `error.type` | Each embedding, its attempts and waits included, by the GenAI conventions |
| `gen_ai.client.token.usage` | histogram | `{token}` | `gen_ai.operation.name`, `gen_ai.provider.name`, `gen_ai.request.model`, `server.address`, `server.port`, `gen_ai.token.type` | The tokens that each embedding's answer counted, `input` by type, when the endpoint counts them, by the GenAI conventions |
| `http.client.request.duration` | histogram | `s` | `http.request.method`, `server.address`, `server.port`, `http.response.status_code`, `error.type` | Each request, by the HTTP conventions |
