# Chunking

An index by meaning holds a vector per piece of each document, and a search by meaning
finds the pieces nearest the question. How documents are cut into pieces, and what text
each vector stands for, is the chunking: the setting `chunking`, which `index` cuts by
and records in the index, so that `search`, `ask` and `status` follow the index, not the
setting. Plan 019 compared four, on plan 002's sandbox questions, and chose the default
by a rule set before the run.

## The four chunkings

| Chunking | The pieces | The text embedded | What `ask` quotes of a piece found |
|---|---|---|---|
| `sections` | each section's body, its paragraphs packed up to 1,200 characters | the title, the section's heading, the piece | the piece |
| `windows` | the whole body, 300 tokens a window, each starting 240 after the last one's start, cut back to a white space in its last tenth | the title, the window | the window |
| `section-paths` | as `sections` | the title, the breadcrumb, the heading path (`A > B`), each cut to 200 characters, the piece | the piece |
| `small-to-big` | as `sections`, up to 128 tokens | as `section-paths` | its section, whole up to 2,400 characters, else 2,400 of it centred on the piece |

- **`sections`** is plan 011's, the control: every other is measured against it.
- **`windows`** ignores the headings: 300 tokens is the user's figure and a fifth of
  overlap the usual one; Chroma found 200 to 400 tokens strong even without overlap
  ([chroma]). Two windows in a row share 200 to 240 characters when no word passes 40,
  since a window ends at its last white space in its last tenth; a window starts
  exactly 240 tokens after the last one's start, inside a word if one is there, the
  window before holding that word whole. Across 1,080 characters of white space alone
  the next window starts at the next word instead, so that none is blank.
- **`section-paths`** keeps 011's pieces, and says where each sits: the page's place in
  its space and the headings above it, the sense of "hierarchical" that tells the model
  the context. The heading of level 1 at the body's start is the title, as the mirror
  writes it, and is not said twice.
- **`small-to-big`** finds by small pieces, 128 tokens as LlamaIndex's hierarchical
  leaves are ([automerge]), and returns a larger unit, the other sense of
  "hierarchical": the passage that `ask` quotes is the piece's section, or 2,400
  characters of it.

A piece belongs to the section that holds its middle, with a span relative to that
section's body, so that a window across sections needs no other schema; an index built
before plan 019 has no chunking recorded, and was cut by `sections`.

## Tokens without a tokeniser

Cuts are made in characters, at four a token, the same for every model: plan 018 dropped
`tokenizers`, `tiktoken` holds another model's vocabulary ([tiktoken]), and neither the
OpenAI API nor Ollama's tokenises on request. Ollama reports the tokens of each answer
(`usage.prompt_tokens`, [ollama-usage]), which the adapter reads and sums, refusing an
answer whose count is no count. If a run's characters per reported token fell outside
3.2 to 4.8, the constant would be set once from that ratio, before the run that decides.

## How they are compared

`eval` builds an index per chunking and measures each, in every mode, as an agent's
first call meets it ([golden questions](../how-to/golden-questions.md)): `search` by
011's measures, and `ask` by Found@ask and Evidence@ask, the share of expected
documents among its passages and the share whose evidence their passage holds, within
its fixed budget. The costs are the characters of the texts that each index embeds,
whatever the vector store held, and their tokens; the texts embedded in the run, its
seconds and the tokens reported; the index's bytes; and the times of `search` and `ask`.
Vectors are kept by model and text, so a text that two chunkings share is embedded once.

The default is chosen in hybrid mode with the setting's model: a challenger qualifies
when it beats `sections` on Evidence@ask with a p-value below 0.05 once adjusted by Holm
over the six tests of three challengers on MRR@10 and Evidence@ask, loses at most 0.02
of MRR@10, and costs at most three times `sections`' tokens; the best Evidence@ask wins,
and within 0.01 the cheaper; else `sections` stays. Three times, because
`small-to-big` repeats each piece's context, about 2.1 times `sections`' tokens; only a
cold build three times as long is refused. The work set should decide again.

## Not compared

Contextual chunks, a summary of the document written before each piece by a chat model
(35% fewer retrieval failures in Anthropic's measure, [contextual]), and a reranker
both need a model that the embedding endpoint does not reach: later plans, measured by
this `eval`.

[chroma]: https://www.trychroma.com/research/evaluating-chunking
[automerge]: https://developers.llamaindex.ai/python/framework/integrations/retrievers/auto_merging_retriever/
[tiktoken]: https://github.com/openai/tiktoken/blob/main/tiktoken_ext/openai_public.py
[ollama-usage]: https://github.com/ollama/ollama/blob/main/openai/openai.go
[contextual]: https://www.anthropic.com/engineering/contextual-retrieval
