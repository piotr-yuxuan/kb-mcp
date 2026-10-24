# Embeddings

How to give search its sense of meaning: an embedding model served on this machine,
by Ollama or by any other OpenAI-compatible API, and the settings that choose the
model, the endpoint and the chunking. The [coding agents](agents.md) guide links here.

## Search by meaning

`search` ranks by the setting `search_mode`: `hybrid`, the default, fuses the ranking
by words with the ranking by meaning; `semantic` ranks by meaning alone; `lexical` by
words alone, and needs no model. Meaning comes from an embedding model that this
program does not run itself: it asks any OpenAI-compatible embeddings API, by default
[Ollama](https://ollama.com) on this machine. So by default `index` and the server need
Ollama: without it, `index` stops and names `search_mode = "lexical"`, and the server
answers by words, saying why.

Why hybrid search over windows: on plan 002's sandbox questions it ranked better than
hybrid search over sections or words alone, significantly (MRR@10 0.639, against 0.578
and 0.539), at 266 ms for the 95th percentile of a query on the development laptop's
CPU. Semantic search over windows ranked higher still there (0.674), but not
significantly: p 0.27 against hybrid, in a paired test made afterwards. The rules
written before those measures kept words and sections, for want of speed and of evidence
quoted; the user chose these defaults knowing that, as ranking matters more to them than
speed.
[Evaluating search](../explanation/search-evaluation.md) and
[chunking](../explanation/chunking.md) explain the measures, the rules and the choice.

To set up search by meaning, install Ollama on the host, not in a container (a
container on macOS cannot use the Mac's GPU), start it (the Ollama app, `brew services
start ollama`, or `ollama serve`), then pull the model, check it and build the index:

```bash
ollama pull qwen3-embedding:0.6b
```

```bash
atlassian-offline-mcp model check
```

```bash
atlassian-offline-mcp index
```

`model check` connects to the endpoint and says the model's dimensions, its digest and
whether its prefixes are known, or what to run when something is missing; it never
downloads a model. The first `index` with a model embeds every piece of the mirror,
then keeps the vectors in `<data>/vectors.sqlite`, so later builds embed only what
changed. Run `index` again after `ollama pull` of a new version of the model: its
vectors change. Until then a server started after the pull says that the index is
stale and answers by words, while one already running goes on with the new weights
against the old vectors until the index is rebuilt. When the endpoint does not
answer, `index` fails and leaves the index in place; the server answers by words,
saying why, and tries again 30 seconds later. Ollama unloads a model five minutes
after its last use, so the first search after a pause waits for it to load;
`OLLAMA_KEEP_ALIVE` (for instance `1h`) keeps it longer. An index built by an earlier
version names a model of its own, which Ollama does not have: run `index`, rather
than pull that model. A folder `<data>/models/` left by an earlier version can be
deleted.

The default model, `qwen3-embedding:0.6b` (639 MB), retrieves English best among the
small models of Ollama's library compared on the MTEB leaderboard. For French content,
or a faster cold build, set `model = "embeddinggemma:300m"` (622 MB): best on French,
and about a quarter of the compute. Any model the endpoint serves can be named; the
prefixes of `qwen3-embedding`, `embeddinggemma`, `embeddinggemma-2`,
`nomic-embed-text`, `nomic-embed-text-v2-moe` and `snowflake-arctic-embed2` are known,
and texts for any other model are embedded as they are.

Any other OpenAI-compatible server works the same way (LM Studio, llama.cpp's server,
vLLM, a hosted API): set `embedding_url` to its base address, the one that ends before
`/embeddings`, and, if it needs a key, put the key in the environment variable
`ATLASSIAN_OFFLINE_MCP_EMBEDDING_API_KEY` (the settings file refuses it). Such a server
lists no digest as Ollama does, so the vectors follow the model's name alone: after
changing the weights behind a name, delete `<data>/vectors.sqlite` and run `index`.

```toml
search_mode = "hybrid"
model = "qwen3-embedding:0.6b"
embedding_url = "http://127.0.0.1:11434/v1"
```

The text sent to the endpoint is your company's content, so the endpoint must be on
this machine: a literal loopback address, `127.0.0.1` or `[::1]` (not a name, not even
`localhost`, which resolves as the system says). Any other address is refused unless
the command is given `--allow-remote-embeddings`, on every run, and then only over
https; for the MCP server, that means registering it as `atlassian-offline-mcp serve
--allow-remote-embeddings`. A model that Ollama serves from its cloud (such as a
`:cloud` tag) is refused the same way, since Ollama would forward the text. A tunnel or
a forwarded port to another machine defeats the check: do not point `embedding_url` at
one. By words alone (`search_mode = "lexical"`), no endpoint is asked at all.

How an index cuts documents into the pieces it embeds is the setting `chunking`:
`windows` by default, overlapping windows of 300 tokens across each document's body, or
`sections`, 011's pieces of each section, `section-paths` or `small-to-big`, which
[chunking](../explanation/chunking.md) compares. Run `index` after changing it;
`search`, `ask` and `status` follow the index, whatever the setting says.

`windows` is the default by the user's choice. Plan 019's rule, set before the
measures, kept `sections`: it asked a chunking to quote the evidence significantly
more often than `sections` (adjusted p below 0.05) to replace it, and none did. On the
sandbox, `windows` ranked better, significantly (hybrid MRR@10 0.639 against 0.578),
with half the pieces and a tenth more tokens to embed; an edit re-embeds more windows
than sections, as later windows shift.

The first `index` after upgrading to these defaults embeds every window of the mirror,
since vectors are kept by text and no window's text is a section's (unless an `eval`
of `windows` with the same model embedded them already): on the sandbox, 1.11 times
the tokens of a first build by sections, with Ollama running throughout. The sections'
vectors stay in `<data>/vectors.sqlite`, which only grows. To keep an earlier
version's behaviour instead, set either of these, then run `index`:

```toml
search_mode = "lexical"  # words alone, as earlier versions searched: no model
```

```toml
chunking = "sections"  # hybrid search over the pieces of earlier versions
```

To check which mode, model and chunking fit your own content, write [golden
questions](golden-questions.md) and run `eval`.

## Sources

Checked on 2026-10-21 and 2026-10-22:

- Ollama: [OpenAI compatibility](https://docs.ollama.com/api/openai-compatibility),
  [embeddings](https://docs.ollama.com/capabilities/embeddings),
  [list models](https://docs.ollama.com/api/tags),
  [qwen3-embedding](https://ollama.com/library/qwen3-embedding),
  [embeddinggemma](https://ollama.com/library/embeddinggemma); the
  [MTEB leaderboard](https://huggingface.co/spaces/mteb/leaderboard).
