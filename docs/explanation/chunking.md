# Chunking

An index by meaning holds a vector per piece of each document, and a search by meaning
finds the pieces nearest the question. How documents are cut into pieces, and what text
each vector stands for, is the chunking: the setting `chunking`, which `index` cuts by
and records in the index, so that `search`, `ask` and `status` follow the index, not the
setting. Plan 019 compared four, on plan 002's sandbox questions, and chose the default
by a rule set before the run: `sections` stays.

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

## On the sandbox

Plan 002's mirror (1,474 documents, 7,344 sections) and its 105 questions, with
`qwen3-embedding:0.6b` through Ollama on this laptop's CPU, on 2026-10-22 and 23
(results `20261023T001258Z.json`). The cold build of `sections` reported 663,854 tokens
for 2,628,524 characters, 3.96 a token: within 3.2 to 4.8, so the constant stays at 4.
Lexical search, which ignores the chunking, is the same for every one: MRR@10 0.539,
Found@ask 0.795, Evidence@ask 0.276.

| Chunking | Mode | Recall@10 | MRR@10 | nDCG@10 | Success@1 | Found@ask | Evidence@ask |
|---|---|---|---|---|---|---|---|
| `sections` | semantic | 0.871 | 0.592 | 0.647 | 0.438 | 0.933 | 0.329 |
| `sections` | hybrid | 0.862 | 0.578 | 0.648 | 0.429 | 0.914 | 0.333 |
| `windows` | semantic | 0.905 | 0.674 | 0.712 | 0.533 | 0.910 | 0.500 |
| `windows` | hybrid | 0.857 | 0.639 | 0.684 | 0.505 | 0.852 | 0.357 |
| `section-paths` | semantic | 0.867 | 0.619 | 0.653 | 0.467 | 0.943 | 0.352 |
| `section-paths` | hybrid | 0.871 | 0.599 | 0.654 | 0.457 | 0.914 | 0.338 |
| `small-to-big` | semantic | 0.905 | 0.594 | 0.658 | 0.410 | 0.933 | 0.362 |
| `small-to-big` | hybrid | 0.852 | 0.579 | 0.650 | 0.419 | 0.890 | 0.324 |

| Chunking | Pieces | Characters embedded | Tokens, at 4 | Index | `search`, median by meaning |
|---|---|---|---|---|---|
| `sections` | 6,729 | 2,628,524 | 657,131 | 38 MB | 178 ms |
| `windows` | 2,974 | 2,920,227 | 730,056 | 21 MB | 201 ms |
| `section-paths` | 6,729 | 2,815,916 | 703,979 | 38 MB | 206 ms |
| `small-to-big` | 9,149 | 3,039,022 | 759,755 | 50 MB | 219 ms |

The tests of the rule, in hybrid mode, each challenger against `sections`, adjusted by
Holm over the six:

| Challenger | MRR@10, p (adjusted) | Evidence@ask, p (adjusted) |
|---|---|---|
| `windows` | 0.0019 (0.0114) | 0.5846 (1.0000) |
| `section-paths` | 0.3044 (1.0000) | 1.0000 (1.0000) |
| `small-to-big` | 0.9571 (1.0000) | 0.8629 (1.0000) |

**The rule keeps `sections`**: no challenger beat it on Evidence@ask in hybrid mode.
`windows` ranked better, significantly once adjusted (MRR@10 0.639 against 0.578),
with half the pieces, a smaller index and 1.11 times the tokens, and by meaning alone
its passages held the evidence more often (0.500 against 0.329); in hybrid mode the
evidence quoted barely moved (0.357 against 0.333), perhaps because a document that
words rank higher there gets its section, not its window. With `windows`, hybrid search
also beat words significantly (MRR@10 0.639 against 0.539, adjusted p 0.0008), on
identifiers too (0.674 against 0.616): two of the three counts of plan 018's bar for
hybrid as the default, its 95th percentile (266 ms here) being the third. The rule set
before this run decides the chunking alone, so the defaults stay `sections` and
`lexical`: they are the rule's, not the best measured, and [the agents'
guide](../how-to/agents.md) says how to set the best measured. The cold builds took 31 minutes for `sections` and 52
for `section-paths`, and 27 for the part of `small-to-big` that the others had not
embedded; `windows` were embedded across two runs, the machine being busy.

## When pages change

`index` rebuilds the whole index from the mirror each time, but embeds only the texts
that `<data>/vectors.sqlite` lacks: vectors are kept by model and text, never by page.
So what a change costs is the number of texts it makes new, and that depends on the
chunking:

- **A cut that shifts re-embeds more than what changed.** `sections`, `section-paths`
  and `small-to-big` cut each section on its own, so an edit re-embeds the pieces of
  the section it touches. `windows` cut the whole body at fixed steps: an edit shifts
  every window after it, which are all new texts.
- **A name in the embedded text re-embeds everything under it.** A title that changes
  re-embeds every piece of the page, by any chunking; a heading renamed re-embeds the
  pieces under it by `section-paths` and `small-to-big`, whose texts carry the heading
  path, its section's alone by `sections`, and the windows after it by `windows`.
- **`small-to-big`'s unit costs nothing to embed**: the section that `ask` returns is
  read from the index when asked, never embedded.
- **A text that two chunkings share is embedded once**, and what an evaluation embeds
  for the chunkings not in use stays in `vectors.sqlite`, which only grows: deleting it
  costs a full embedding of the chunking in use, and nothing else.

Counted on the sandbox's mirror, offline, with the tests' scripted model (the counts
depend on the cuts alone, not on the model), after editing one page of 17 sections,
`code-review-guidelines`:

| Chunking | Pieces of the mirror | A sentence added mid-section | A heading renamed, its body empty, two sections under it |
|---|---|---|---|
| `sections` | 6,729 | 1 | 0 |
| `windows` | 2,974 | 7 | 13 |
| `section-paths` | 6,729 | 1 | 2 |
| `small-to-big` | 9,149 | 2 | 4 |

A vector stays in the store when its text leaves the mirror, and is read by nothing; an
index never holds a vector whose text the mirror no longer has, since it is rebuilt.

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
