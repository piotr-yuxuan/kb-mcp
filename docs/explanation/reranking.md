# Reranking

Search finds documents in two stages when reranking is on. The first is this program's
own, by words, by meaning or both; the second sends the first documents it found, with
the question, to a reranking server on this machine, and shows them in the order of the
server's scores. Plan 022 added it, with a bar for turning it on by default written
before any run. It stays off until the run on the user's machine, the machine that serves
agents, says otherwise. [The how-to](../how-to/reranking.md) sets it up.

## Two ways a model can read a question

An index by meaning holds a vector per piece of each document, made once when `index`
runs; a search embeds the question alone, about ten words, and finds the nearest
vectors. The model that made them, a **bi-encoder**, never reads the question and a
document together: each is reduced to a vector of its own, before the other is known.
That is what makes it cheap, and also what it misses: a word of the question that
matters only next to a word of the document.

A **cross-encoder** reads the question and one document together, in one pass, and
gives the pair a score: how well this text answers this question. Every word of the
question can weigh every word of the document. Nothing can be computed in advance, so
each search costs one pass per document scored. Nogueira and Cho's reranking of a
first stage by words with such a model topped MS MARCO's passage ranking in 2019
([nogueira]); across BEIR's eighteen datasets, a first stage by words reranked by a
cross-encoder was the strongest zero-shot method compared, and among the slowest
([beir]).

Qwen3-Reranker, the default model, is a small language model asked whether the
document meets the question, to which it answers "yes" or "no": the score is the
probability of "yes", from 0 to 1 ([qwen3]). The server writes that prompt around each
pair, about 80 tokens. Only the order of the scores is used: they are not calibrated
across questions, so no threshold drops a document, and no fusion mixes them with the
first stage's.

## Why only the first documents

Scoring every document of the mirror for each question would take hours. So the first
stage chooses, and the reranker reorders the first `rerank.depth` documents it found,
30 until the bar decides; the rest follow in their order.

- **The first stage sets the ceiling.** A document that the first stage puts past the
  depth is never scored, so reranking cannot bring it into the first ten. Recall@N, the
  share of the expected documents within the first stage's first N, is the most that
  reranking N documents can reach; `eval-rerank` reports it for each depth measured.
- **Documents named stay first.** A question naming `ENG-123`, or a page's id, wants
  that document: it stays first, as plan 006 put it, and is not scored. Plan 018 found
  identifiers the weak point of a model by meaning, and the reranker is a model too.
- **A short text for each.** The reranker reads at most 1,502 characters a document:
  its title and the heading of the section that `search` shows, each cut to 150
  characters, then 1,200 characters of that section about the place the first stage
  chose, by meaning its best piece, by words where the question's words gather (the
  place `ask` quotes). 1,200 is plan 011's piece, and plan 019's 300-token window at
  four characters a token, so a search costs at most N such pairs whatever the
  chunking. With the prompt and the question, a pair is 225 to 400 tokens.
- **The cost grows with N.** On the user's machine, by an estimate scaled from published
  figures, as no measure existed: about 2,450 tokens a second, so a search reranking
  10 documents would take 0.9 to 1.6 seconds, 30 about 2.8 to 4.9, 50 about 4.6 to
  8.2. On a laptop's CPU with nixpkgs' llama.cpp 0.6.0, 30 texts as long as any took
  147 to 151 seconds, some 85 tokens a second: before 0.7.0, the server ran the model's
  output layer for every token where scoring needs none, a slowdown of about six times
  reported upstream ([lc-30445]).
- **The next page keeps the order.** A cursor carries the order the first page gave,
  one character per document reranked, so a next page asks nothing: a second request
  would cost the time again, could fail where the first did not, and near-ties may come
  back swapped. A cursor names the index's build, so a rebuilt index refuses it, as it
  refuses any cursor; within one build, the order applies to as many documents as it
  holds, and one longer than the documents now found is refused: the agent searches
  again.

## When the server fails

A search never fails for the reranker: it keeps the first stage's order, and its
answer ends its header with " Not reranked:" and why, as a search by meaning says why
it fell back to words. No answer, or none within 30 seconds, a server that is not a
reranker, or an answer that does not parse is remembered for 30 seconds, during which
searches do not ask; a refusal (400, 413, 422 or 500) is the request's, not the
server's, so the next search asks again. [Telemetry](../reference/telemetry/serve.md)
counts each search not reranked, by why.

## The bar, fixed before the run

"Data-driven inspires me confidence", the user said: the defaults follow a rule
written before any measure, applied by `eval-rerank` on the golden questions to depths
10, 20, 30 and 50 exactly. A depth qualifies if:

1. it beats the order not reranked on MRR@10, with an adjusted p below 0.05, by the
   paired randomisation test of [evaluating search](search-evaluation.md#paired-tests),
   Holm's correction over the four depths;
2. it loses at most 0.05 of MRR@10 on the questions of the groups `identifier` and
   `keyword`;
3. on the user's machine, a search with it takes at most 5 seconds at the 95th percentile.

Among the depths that qualify, the smallest whose MRR@10 is not shown lower than the
best's (the same test, p of 0.05 or more) becomes `rerank.depth`, and
`rerank.enabled` turns true. If none qualifies, reranking stays off by default. Values
compare as reported: means to three decimals, a group's loss as the difference of its
two means so shown, p-values to four decimals, times in whole milliseconds. A loss of
0.050 qualifies, 0.051 does not; a group that the golden questions do not name has no
loss to show, and `eval-rerank` says `n/a`.

- **Clause 1** is the test of plans 011 and 018, its family of four fixed in advance.
- **Clause 2** allows more than plans 011 and 018 did (0.02), by the arithmetic of
  small groups. The sandbox has 32 identifier questions and 34 keyword ones; with the
  spread of per-question differences seen in plan 018 (0.281), the standard error of a
  group's mean difference is about 0.05. A reranker with no true effect on a group's
  mean would then show, by chance, a loss past 0.02 about one time in three, and past
  0.05 about one time in six; and a real loss like hybrid's 0.061 on identifiers in
  plan 018 would still be caught more often than not.
- **Clause 3** is the user's figure ("Happy to wait 5s"), within the 10 seconds or so
  for which a person keeps attention ([nielsen]). A query by meaning was asked 200 ms
  in plan 018, but it embeds ten words where a reranker reads N passages, and an
  agent's own turn takes seconds. By the estimate above, it admits a depth of about 30.
- **Ties go to the cheaper depth** unless it is shown worse.
- **Power.** With 105 questions, the runs of plans 011 and 018 could detect
  differences of MRR@10 of 0.065 to 0.12 ([power](search-evaluation.md#effect-size-significance-and-power)).
  Published gains of rerankers are of that order ([qwen3], [beir]), but the sandbox is
  small and written with its questions. "Not significant" means not shown.
- **Which machine decides.** Ranks are the same on every machine; times are not. A run
  elsewhere reads clause 3 by its own times, and says so: its clauses 1 and 2 hold for
  every machine, its verdict for that machine alone. The user's machine's run sets the
  defaults.

Evidence@ask is reported beside, not a clause: under `ask`'s fixed budget it follows
the order that MRR@10 measures, and a further noisy clause would refuse more harmless
rerankers.

## The model

Chosen from published results, as plan 018 chose its embedding model, not by
benchmarking candidates here:

| Source | First stage | Qwen3-Reranker-0.6B | bge-reranker-v2-m3 | First stage alone |
|---|---|---|---|---|
| Qwen3 paper, MTEB(eng, v2) retrieval ([qwen3]) | `qwen3-embedding:0.6b`, this program's | **65.80** | 57.03 | 61.82 |
| Qwen3 paper, MMTEB retrieval | the same | **66.36** | 58.36 | 64.64 |
| Jina v3 paper, BEIR ([jina-v3]) | jina-embeddings-v3 | 56.28 | **56.51** | 55.81 |
| Jina v3 paper, MIRACL (18 languages) | jina-embeddings-v3 | 57.70 | **69.32** | 58.90 |
| Hugging Face, MTEB(eng, v2) retrieval ([ettin]) | six models, mean | **0.5940** | 0.5526 | |

- **Qwen3-Reranker-0.6B** (Apache 2.0), in the conversion that llama.cpp's maintainer
  published as correct ([lc-16407]), 639 MB. The only published run over this
  program's own first stage puts it 4 points above that stage in English, where
  bge-reranker-v2-m3 falls 5 below; an independent run in English agrees on the order.
  Jina's run, over another first stage, ties them in English and puts bge far ahead
  across languages: French content waits, as plan 018 decided.
- **Caveats.** All runs but Hugging Face's are by interested authors; none is on
  documentation like this, identifiers or French; the server gives the model its
  generic instruction for web search, a custom one waiting on an open change
  ([lc-20009]); both small rerankers lowered code retrieval.
- **Larger is better, and slower.** Qwen3-Reranker-4B scores best in English (69.76 in
  Qwen's run, 0.6367 in Hugging Face's), but does about eight times the work per token:
  even 10 documents would take some 7 to 13 seconds on the user's machine, past the 5. Within
  the bound, the best is the 0.6B.
- **Changing it** costs a server command and a setting, and a run of `eval-rerank`,
  since the bar's verdict belongs to a model; nothing stored depends on the reranker.

## Why a server of its own

The user wanted the model "on the side as a separate (local-only) component of the
system", never inside this program. llama.cpp's `llama-server` answers a rerank
request of the shape that Jina's API made common, and applies Qwen3-Reranker's prompt;
Ollama, which serves the embeddings by default, as any OpenAI-compatible API may, has
no rerank route ([ollama-3368]), and OpenAI's API has none to be compatible with; Text
Embeddings Inference answers another shape, cannot run the chosen model, and listens on
every interface by default. The server's address must be this machine's: the text it
reads is the mirror's, and no flag allows another ("No remote reranker.").

## Not done

- **Scoring several pieces of a document** and keeping the best ([maxp]): N times the
  cost again, where the first stage already chose the place.
- **Fusing the scores** with the first stage's, or a threshold on them: they are not
  calibrated across questions, and a fusion tuned on the sandbox's 105 questions would
  fit them.
- **Shorter texts**: 600 characters would about halve the time; if the bar fails on
  time alone, a later plan measures them.
- **Reranking `browse`**, sorted by update, or the documents named.

## Sources

- Nogueira and Cho, [Passage Re-ranking with BERT][nogueira], 2019.
- Thakur, Reimers, Rücklé, Srivastava and Gurevych, [BEIR: A Heterogeneous Benchmark
  for Zero-shot Evaluation of Information Retrieval Models][beir], NeurIPS 2021.
- Dai and Callan, [Deeper Text Understanding for IR with Contextual Neural Language
  Modeling][maxp], SIGIR 2019.
- Zhang et al., [Qwen3 Embedding: Advancing Text Embedding and Reranking Through
  Foundation Models][qwen3], 2025.
- Jina AI, [jina-reranker-v3][jina-v3], 2025.
- Hugging Face's blog, [the Ettin rerankers][ettin].
- Nielsen, [Response Times: The 3 Important Limits][nielsen].
- llama.cpp: [the server's README][lc-server], [the right conversion of
  Qwen3-Reranker][lc-16407], [a custom instruction][lc-20009], [skipping the output
  layer when pooling][lc-30445].
- Ollama, [a rerank route, requested][ollama-3368].

[nogueira]: https://arxiv.org/abs/1901.04085
[beir]: https://arxiv.org/abs/2104.08663
[maxp]: https://arxiv.org/abs/1905.09217
[qwen3]: https://arxiv.org/abs/2506.05176
[jina-v3]: https://arxiv.org/abs/2509.25085
[ettin]: https://huggingface.co/blog/ettin-reranker
[nielsen]: https://www.nngroup.com/articles/response-times-3-important-limits/
[lc-server]: https://github.com/ggml-org/llama.cpp/blob/a08ab75ae74c36c15accc6c682a989a9e98dbfd2/tools/server/README.md
[lc-16407]: https://github.com/ggml-org/llama.cpp/issues/16407
[lc-20009]: https://github.com/ggml-org/llama.cpp/pull/20009
[lc-30445]: https://github.com/ggml-org/llama.cpp/pull/30445
[ollama-3368]: https://github.com/ollama/ollama/issues/3368
