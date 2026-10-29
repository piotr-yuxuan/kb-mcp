# Embeddings

How to give search its sense of meaning: an embedding model served on this machine, by
Ollama or by any other OpenAI-compatible API, and the settings that choose the model,
the endpoint and the chunking; or how to search by words alone. The
[coding agents](agents.md) guide links here. What `index` does with the vectors is in
[the internals](../explanation/internals.md), and why the program asks a server rather
than run a model, in [the trade-offs](../explanation/trade-offs.md).

The setting `search_mode` says how `search` and `ask` rank:

| `search_mode` | Ranks by | Needs |
|---|---|---|
| `hybrid`, the default | words and meaning, fused | an embedding endpoint, for `index` and the server |
| `semantic` | meaning alone | the same |
| `lexical` | words alone | nothing more |

So by default `index` and the server ask an embedding model. This program runs none
itself: it asks any OpenAI-compatible embeddings API, by default Ollama at
`http://127.0.0.1:11434/v1`. Without one, `index` stops and names
`search_mode = "lexical"`, and the server answers by words, saying why.

Hybrid search over windows is the default by the maintainer's choice
([plan 025](../work/changelog/025-windows-and-hybrid.md)): on plan 002's sandbox
questions it ranked better than hybrid search over sections or words alone, and ranking
mattered more than speed.
[The defaults](../explanation/chunking.md#the-defaults-the-maintainers-choice) give the
measures, and the rules written before them that kept words and sections;
[evaluating search](../explanation/search-evaluation.md), how they were made.

## 1. Run Ollama on the host

Install [Ollama](https://ollama.com) on the host, not in a container: a container on
macOS cannot use the Mac's GPU. Start it with the Ollama app, `brew services start
ollama`, or `ollama serve`.

## 2. Pull the model and check it

```bash
ollama pull qwen3-embedding:0.6b
```

```bash
kb-mcp model check
```

`model check` connects to the endpoint and says the model's dimensions, its digest and
whether its prefixes are known, or what to run when something is missing. It never
downloads a model.

## 3. Build the index

```bash
kb-mcp index
```

The first `index` with a model embeds every piece of the mirror and keeps the vectors in
`<data>/vectors.sqlite`, so later builds embed only the texts that changed. A running
server reads the new index from its next call on.

Ollama unloads a model five minutes after its last use, so the first search after a
pause waits for it to load; `OLLAMA_KEEP_ALIVE` (for instance `1h`) keeps it longer.

## After pulling new weights

Run `index` again after `ollama pull` of a new version of the model: its vectors change.
Until then, a server started after the pull says that the index is stale and answers by
words, while one already running goes on with the new weights against the old vectors
until the index is rebuilt.

An index built by an earlier version of this program names a model of its own, which
Ollama does not have: run `index`, rather than pull that model. A folder
`<data>/models/` left by an earlier version can be deleted.

## After upgrading to hybrid search over windows

The first `index` after upgrading to these defaults embeds every window of the mirror,
since vectors are kept by text and no window's text is a section's (unless an `eval`
of `windows` with the same model embedded them already): on the sandbox, 1.11 times
the tokens of a first build by sections, with Ollama running throughout. The prune
after it deletes the sections' vectors from `<data>/vectors.sqlite`, unless an
evaluation's index cut by `sections` keeps them, so that going back embeds them again.
To keep an earlier version's behaviour instead, set either of these, then run `index`:

```toml
search_mode = "lexical"  # words alone, as earlier versions searched: no model
```

```toml
chunking = "sections"  # hybrid search over the pieces of earlier versions
```

## Choose another model

The default model, `qwen3-embedding:0.6b` (639 MB), retrieves English best among the
small models of Ollama's library compared on the MTEB leaderboard. For French content,
or a faster first build, use `embeddinggemma:300m` (622 MB): best on French, and about a
quarter of the compute.

```toml
model = "embeddinggemma:300m"
```

Then pull it, check it and run `index`, which embeds every piece again for the new
model. Any model the endpoint serves can be named. The prefixes of `qwen3-embedding`,
`embeddinggemma`, `embeddinggemma-2`, `nomic-embed-text`, `nomic-embed-text-v2-moe` and
`snowflake-arctic-embed2` are known; texts for any other model are embedded as they are.

## Use another OpenAI-compatible API

Any other OpenAI-compatible server works the same way: LM Studio, llama.cpp's server,
vLLM, or a hosted API. Set `embedding_url` to its base address, the one that ends before
`/embeddings`, and `model` to the name that server gives the model:

```toml
embedding_url = "http://127.0.0.1:8080/v1"
model = "<the model, as that server names it>"
```

If the server needs a key, put it in the environment variable
`KB_MCP_EMBEDDING_API_KEY`; the settings file refuses it. Such a server
lists no digest of its models as Ollama does, so the vectors follow the model's name
alone: after changing the weights behind a name, delete `<data>/vectors.sqlite` and run
`index`.

## Reach an endpoint off this machine

The text sent to the endpoint is your company's content, so the endpoint must be on this
machine: a literal loopback address, `127.0.0.1` or `[::1]`, not a name, not even
`localhost`, which resolves as the system says. Any other address is refused unless the
command is given `--allow-remote-embeddings`, on every run, and then only over https:

```bash
kb-mcp index --allow-remote-embeddings
```

For the MCP server, that means registering it with the flag:

```bash
claude mcp add --scope user --transport stdio kb-mcp -- kb-mcp serve --allow-remote-embeddings
```

A model that Ollama serves from its cloud, such as a `:cloud` tag, is refused the same
way, since Ollama would forward the text. A tunnel or a forwarded port to another
machine defeats the check: do not point `embedding_url` at one.

## Choose the chunking

How an index cuts documents into the pieces it embeds is the setting `chunking`:
`windows` by default, overlapping windows of 300 tokens across each document's body, or
`sections`, 011's pieces of each section, `section-paths` or `small-to-big`, which
[chunking](../explanation/chunking.md) compares.

`windows` is the default by the maintainer's choice: on the sandbox it ranked better
than `sections`, with half the pieces, where plan 019's rule, set before the measures,
kept `sections`
([the defaults](../explanation/chunking.md#the-defaults-the-maintainers-choice)). An
edit re-embeds more windows than sections, as later windows shift.

```toml
chunking = "sections"
```

Run `index` after changing it: a chunking cuts other texts, so the first build embeds
every piece again. `search`, `ask` and `status` follow the index, whatever the setting
says.

## Search by words alone

```toml
search_mode = "lexical"
```

Then neither `index` nor the server asks any endpoint, and the index holds no vectors.

## When the endpoint does not answer

`index` stops and leaves the index in place, with its vectors. The server answers by
words, saying why, and tries the endpoint again 30 seconds later.

## Measure on your own content

To check which mode, model and chunking fit your own content, write
[golden questions](golden-questions.md) and run `eval`.

## Sources

Checked on 2026-10-21 and 2026-10-22:

- Ollama: [OpenAI compatibility](https://docs.ollama.com/api/openai-compatibility),
  [embeddings](https://docs.ollama.com/capabilities/embeddings),
  [list models](https://docs.ollama.com/api/tags),
  [qwen3-embedding](https://ollama.com/library/qwen3-embedding),
  [embeddinggemma](https://ollama.com/library/embeddinggemma); the
  [MTEB leaderboard](https://huggingface.co/spaces/mteb/leaderboard).
