# Evaluating search

How this project decides how to search: which embedding model to use, and whether to
rank by words, by meaning, or by both. It explains the reasoning, the measures and the
statistics, and what the runs so far do and do not show, so that the next decision,
on your own content, can be made the same way.

Two questions need two kinds of evidence:

1. **Which embedding model?** Published benchmarks answer this best: they test each
   model on thousands of queries over many collections, which no project can afford to
   repeat. Plan 018 chose its model this way.
2. **Which way of searching, on this content, for these questions?** Only our own
   corpus can answer that, with golden questions whose answers are known. Plans 011,
   018 and 019 measured this on a sandbox corpus; your work set is the next step.

## Choosing a model from published results

### What the leaderboard measures

The [Massive Text Embedding Benchmark](https://arxiv.org/abs/2210.07316) (MTEB) runs
embedding models on many tasks of several types: retrieval (find the passages that
answer a query), classification, clustering, semantic similarity of sentence pairs,
reranking, pair classification and bitext mining. Its multilingual extension,
[MMTEB](https://arxiv.org/abs/2502.13595), covers more than 250 languages. The
[leaderboard](https://huggingface.co/spaces/mteb/leaderboard) shows, for each model, a
mean over every task and a mean per task type.

**The overall mean is the wrong number for us.** It averages unlike tasks: a model can
lead it thanks to classification and clustering while being ordinary at retrieval. Our
use is retrieval and nothing else: short queries from coding agents against passages
of internal documentation. So the column that matters is the **Retrieval** task type,
whose tasks are scored by nDCG@10 (defined below), the same family of measure as our
own evaluation.

**Language matters too.** The leaderboard has an English benchmark (`MTEB(eng, v2)`)
and a multilingual one (`MTEB(Multilingual, v2)`), and filters by language: with
`fra-Latn`, only the tasks with French data count. Our content was in English and
French; once the maintainer said that French was not needed for now, English retrieval
decided.

### How the numbers were read

The leaderboard's site is a front end over an API, which returns each model's scores
by task type (about a megabyte of JSON per benchmark). This prints each model's
Retrieval score on the English benchmark; `MTEB(Multilingual,%20v2)` gives the
multilingual one, and adding `?languages=fra-Latn` keeps only the tasks with French
data:

```bash
curl -s 'https://mteb-leaderboard-backend.hf.space/v1/benchmarks/MTEB(eng,%20v2)/scores' | python3 -c 'import json, sys; [print(row["model"]["name"], row["scoresByTaskType"].get("Retrieval")) for row in json.load(sys.stdin)["rows"]]'
```

The program asks any OpenAI-compatible embeddings API, Ollama by default, so the
candidates were those that Ollama's library offers. On 2026-10-21, their Retrieval
scores, out of 100 (the last column is a rough proxy for the compute per token, the
parameters outside the embedding table):

| Model, Ollama tag | Multilingual v2 | English v2 | French subsets | Non-embedding parameters |
|---|---|---|---|---|
| Qwen3-Embedding-0.6B, `qwen3-embedding:0.6b` | **64.65** | **61.83** | 58.07 | 0.44 B |
| EmbeddingGemma, `embeddinggemma:300m` | 62.49 | 55.69 | **65.28** | 0.106 B |
| EmbeddingGemma 2, `embeddinggemma-2:270m` | 60.60 | 51.33 | 61.39 | 0.137 B |
| nomic-embed-text-v2-moe | 57.21 | 54.81 | 59.42 | 0.142 B |
| bge-m3 | 54.59 | no aggregate | 56.30 | 0.312 B |
| snowflake-arctic-embed-l-v2.0 | 58.36 | 58.56 | 54.35 | 0.303 B |
| granite-embedding-278m-multilingual | 52.20 | 51.45 | 56.31 | 0.086 B |
| bge-small-en-v1.5 (plan 011's default) | 36.26 | 53.86 | 30.36 | |

Qwen3-Embedding-0.6B led in English and multilingual retrieval, at about four times
EmbeddingGemma's compute; EmbeddingGemma led in French. The maintainer chose Qwen3,
also for its 32,768-token window, which leaves room for the chunking strategies to be
compared next.

### What to distrust in a leaderboard

- **Self-reported against reproduced.** A model card's numbers are its authors'. For
  EmbeddingGemma 2, Google's card gave only overall means; Google's per-task submission
  to MTEB was withdrawn unmerged
  ([results#745](https://github.com/embeddings-benchmark/results/pull/745)), and the
  leaderboard shows the maintainers' own rerun
  ([results#793](https://github.com/embeddings-benchmark/results/pull/793)). Both
  agreed on retrieval, which put EmbeddingGemma 2 below its predecessor there, despite
  a slightly higher overall mean on the card.
- **Versions.** `v1` and `v2` of a benchmark hold different tasks; numbers from
  different versions do not compare. Compare models within one benchmark, read on one
  day.
- **Training on the test.** A model trained on a benchmark's own data scores better
  there than it would on yours. The leaderboard shows each model's share of
  zero-shot tasks (tasks whose data it did not train on); a low share is a warning.
- **Not our documents.** The benchmarks are Wikipedia, web questions, science,
  finance and the like, not a company's runbooks and tickets. A ranking between models
  transfers better than the size of their gaps.
- **Not our settings.** Scores assume the model's own prompts (Qwen3 wants an
  instruction before each query, nothing before a document) and full precision; Ollama
  serves an 8-bit quantisation (`Q8_0`). The adapter adds each known model's prompts
  from its card; quantisation costs a little, unmeasured here.

### Why not benchmark the candidates ourselves?

Because our own question set is too small to tell good models apart. With 105
questions, the smallest difference in MRR@10 that a test detects four times out of five
is about 0.07 to 0.12 (see *Power*, below), while the candidates differ on the
leaderboard by a few points over thousands of queries. A home-made comparison would
mostly measure noise, cost a download and a cold embedding per candidate, and tune the
choice to questions that we wrote ourselves. Our own runs serve another purpose: to
check that the chosen model works in our pipeline (prompts, pieces, fusion) and to
choose the way of searching.

## Measuring on our own corpus

### The golden questions

Plan 002 wrote a sandbox: Confluence pages and Jira issues of an invented payments
company, with no real data, on the project's free Atlassian site. With it came 105
golden questions (`sandbox/golden.yaml`), each with:

- the documents that answer it (`expected`, relevance 2) and those that help
  (`partial`, relevance 1);
- groups: how its words relate to its answers' (`identifier` when it quotes a code or
  a name, `keyword` when it shares ordinary words, `paraphrase` when it shares no word
  of four letters or more with their titles and headings) and its language (`en`, `fr`);
- `evidence`: a phrase of each expected document that states the answer.

There are 32 identifier, 34 keyword and 39 paraphrase questions; 90 in English, 15 in
French. `spikes/golden_refs.py` turns them into a golden file that `eval` reads, with
each document named as the mirror holds it.

`eval` runs every question through `Library.ranked`, the code that answers agents'
`search`, once per mode, and keeps the first ten documents.

### The measures, on one worked example

Take one question whose answers are documents A and B, with P helping, and a ranking
whose first five documents are X, A, P, Y, B. The section shown for A holds its
evidence phrase; the one shown for B does not.

- **Recall@10**: the share of the expected documents in the first ten. A and B are both
  there: 2 of 2 = **1.0**. Had B come twelfth, 0.5. It says whether the answers are
  found at all.
- **MRR@10** (mean reciprocal rank): one over the rank of the first expected document in
  the first ten, else 0; averaged over questions. A is second: 1/2 = **0.5**. It says
  how soon the first answer comes, which matters most to an agent that reads the top
  results. A move from rank 1 to 2 costs 0.5; from 5 to 6, 0.03.
- **Success@1**: 1 when the first document is expected, else 0. X is not: **0**.
- **nDCG@10** (normalised discounted cumulative gain, after
  [Järvelin and Kekäläinen, 2002](https://doi.org/10.1145/582415.582418)): each
  document's relevance is its gain, divided by log2(rank + 1), summed over the first
  ten, then divided by the same sum for the best possible ordering:

  ```
  DCG   = 2/log2(3) + 1/log2(4) + 2/log2(6) = 1.262 + 0.500 + 0.774 = 2.536
  ideal = 2/log2(2) + 2/log2(3) + 1/log2(4) = 2.000 + 1.262 + 0.500 = 3.762
  nDCG  = 2.536 / 3.762 = 0.674
  ```

  It rewards every answer, and helpful documents too, the more the higher they come.
- **Section@10**: of the expected documents found in the first ten that have an
  evidence phrase, the share whose shown section holds it (case, spacing and Markdown
  marks ignored). A's does, B's does not: **0.5**. It says whether the agent is shown
  the right part of a long page, not merely the page.

`eval` averages each measure over all questions, and over each group.

### Paired tests

Questions differ far more from one another than strategies do: a hard question is hard
in every mode. So the modes are compared **question by question**: for each question,
the difference between its MRR@10 in one mode and in the other. Under the hypothesis
that the modes are alike, each difference is as likely to be positive as negative.
The **randomisation test** flips the signs of the differences at random, 10,000 times,
and counts how often the mean of the flipped differences is at least as far from zero
as the mean observed; that share is the p-value. On retrieval experiments, Smucker,
Allan and Carterette ([2007](https://doi.org/10.1145/1321440.1321528)) found the
randomisation test, the bootstrap and the paired t-test in close agreement, and the
Wilcoxon and sign tests unreliable; the randomisation test assumes the least about how
the differences are distributed.

A worked example, with four questions:

| Question | Lexical | Hybrid | Difference |
|---|---|---|---|
| 1 | 0 | 0.5 | +0.5 |
| 2 | 0.5 | 1 | +0.5 |
| 3 | 1 | 1 | 0 |
| 4 | 0.25 | 0.5 | +0.25 |

The mean difference is 0.3125. Of the 16 equally likely sign patterns, the mean stays
that far from zero only when the three non-zero signs agree: 4 patterns of 16, p =
0.25. Three consistent improvements cannot be significant: with n questions that all
improve, the smallest possible p is 2/2^n, so it takes at least six to fall below 0.05.

### Several tests at once: Holm's correction

Each run tests several comparisons (semantic against lexical, hybrid against lexical,
for each model). At 0.05 each, the chance that at least one of them is a false alarm
grows with their number. [Holm's step-down method](https://www.jstor.org/stable/4615733)
(1979) adjusts the p-values: sort them, multiply the i-th smallest of m by m - i + 1,
keep each no smaller than the one before, cap at 1. In plan 018's run, p = 0.1526 and
0.1968: the smaller becomes 0.1526 × 2 = 0.3052, and the larger, 0.1968 × 1, is raised to
0.3052 so as not to fall below it. A decision rests on the adjusted values.

### Effect size, significance and power

A p-value says how surprising a difference would be if there were none, not how large
it is. `eval` reports each mode's MRR@10, so their difference, and its adjusted p; read
both. Counting the questions that each mode wins helps too: in plan 018's run, hybrid
did better than lexical on 32 questions, worse on 14, and the same on 59.

**Power** is the chance that a test detects a real difference. It grows with the
number of questions and falls with the spread s of the per-question differences (their
standard deviation). With n questions, a two-sided test at 0.05 detects about four
times out of five a difference of 2.8 s / √n (1.96 for the test, plus 0.84 for the
four times in five). In our runs s was 0.24 to 0.43, so with 105 questions the
detectable difference in MRR@10 was **0.065 to 0.12**. Plan 011's hybrid gain with its
model, 0.067, was at that edge, and significant; plan 018's, 0.039, was below it, and
not. "Not significant" means "not shown", not "no difference".

`eval` does not print the counts or the spread, but its results file holds what they
need: for each model, mode and question, the ranks of the question's expected documents
within the first ten (`null` beyond). This prints them for hybrid against lexical, with
the test that `eval` runs; two results files of the same golden file compare two models
the same way, as the comparison with plan 011's model below was made:

```python
import json, math, statistics, sys

from kb_mcp.evaluation.domain.evaluation import paired_test


def reciprocal(ranks):  # MRR@10 of one question: 1 over its best rank, else 0
    found = [rank for rank in ranks if rank is not None]
    return 1 / min(found) if found else 0.0


run = json.load(open(sys.argv[1]))["runs"][0]
ids = sorted(run["ranks"]["lexical"])
before = [reciprocal(run["ranks"]["lexical"][each]) for each in ids]
after = [reciprocal(run["ranks"]["hybrid"][each]) for each in ids]
differences = [b - a for a, b in zip(before, after)]
spread = statistics.stdev(differences)
print(
    "difference",
    statistics.fmean(differences),
    "better",
    sum(d > 0 for d in differences),
    "worse",
    sum(d < 0 for d in differences),
    "p",
    paired_test(before, after),
    "detectable",
    2.8 * spread / math.sqrt(len(differences)),
)
```

Run it with `uv run python <script> <data>/eval/results/<time>.json`.

### Deciding before measuring

Plan 011 wrote its rule for the default mode before any run: hybrid becomes the
default only if it beats lexical on MRR@10 with an adjusted p < 0.05, and loses at most
0.02 of MRR@10 on the identifier and keyword groups (questions that agents send as
keywords and names, where words are strong). It set apart a speed gate for choosing
the model, queries within 200 ms at the 95th percentile among them. Plan 018 wrote,
again before its run, one bar of all three for keeping hybrid the default. Writing the bar first keeps the decision
from bending to the numbers once they are known: a set that favours meaning (39
paraphrases, written so that words cannot find their answers) would otherwise tempt a
reading in meaning's favour. Plan 019 wrote one for the chunking the same way
([chunking](chunking.md)).

A rule written first binds the reading of the numbers, not the maintainer's choice.
Once the numbers are known, the maintainer may weigh what the rule left out, such as
ranking against speed, provided the rule's verdict stays on record and the choice is
said to be theirs; plan 018's bar said as much, leaving the decision to the maintainer
if it failed.
The defaults since plan 025 are such a choice (below).

### Query time

`eval` times every query and reports the median and the **95th percentile** (by
nearest rank: the time that 95 % of queries do not exceed). The tail, not the average,
is what an agent feels when a search stalls. The first query by meaning is run untimed
beforehand, since it reads the index's vectors.

## The results

### Plan 011: models in process

Two small models, run in process with onnxruntime on this laptop (x86_64, 16 threads):

| Model | Mode | Recall@10 | MRR@10 | nDCG@10 | Success@1 | Section@10 | Query, 95th |
|---|---|---|---|---|---|---|---|
| (any) | lexical | 0.776 | 0.539 | 0.583 | 0.410 | 0.363 | 15 ms |
| bge-small-en-v1.5 | semantic | 0.862 | 0.572 | 0.626 | 0.371 | 0.362 | 68 ms |
| bge-small-en-v1.5 | hybrid | 0.829 | 0.606 | 0.642 | 0.467 | 0.328 | 80 ms |
| multilingual-e5-small | semantic | 0.810 | 0.547 | 0.602 | 0.410 | 0.455 | 52 ms |
| multilingual-e5-small | hybrid | 0.814 | 0.601 | 0.644 | 0.467 | 0.386 | 68 ms |

Hybrid beat lexical with both models (adjusted p = 0.015 and 0.025) and lost nothing
on identifier and keyword questions: hybrid became the default. The cold embedding of
6,729 pieces took 142 and 161 seconds. The full tables per group are in
`docs/work/changelog/011-search-strategies.md`.

### Plan 018: Qwen3 through Ollama

The same 105 questions and the same mirror (1,474 documents, 7,344 sections, 6,729
pieces), with `qwen3-embedding:0.6b` through Ollama 0.40.3 on the same laptop, on its
CPU (Ollama does not use its integrated GPU):

| Mode | Group | Recall@10 | MRR@10 | nDCG@10 | Success@1 | Section@10 | Query, median | Query, 95th |
|---|---|---|---|---|---|---|---|---|
| lexical | all | 0.776 | 0.539 | 0.583 | 0.410 | 0.363 | 7 ms | 14 ms |
| lexical | identifier | 0.938 | 0.616 | 0.676 | 0.469 | 0.548 | 7 ms | 14 ms |
| lexical | keyword | 0.941 | 0.812 | 0.815 | 0.706 | 0.288 | 7 ms | 14 ms |
| lexical | paraphrase | 0.500 | 0.237 | 0.305 | 0.103 | 0.200 | 7 ms | 14 ms |
| lexical | fr | 0.800 | 0.453 | 0.491 | 0.333 | 0.292 | 7 ms | 14 ms |
| semantic | all | 0.871 | 0.592 | 0.647 | 0.438 | 0.420 | 164 ms | 202 ms |
| semantic | identifier | 0.906 | 0.501 | 0.586 | 0.312 | 0.367 | 164 ms | 202 ms |
| semantic | keyword | 0.926 | 0.801 | 0.807 | 0.676 | 0.470 | 164 ms | 202 ms |
| semantic | paraphrase | 0.795 | 0.486 | 0.559 | 0.333 | 0.419 | 164 ms | 202 ms |
| semantic | fr | 1.000 | 0.737 | 0.751 | 0.600 | 0.533 | 164 ms | 202 ms |
| hybrid | all | 0.862 | 0.578 | 0.648 | 0.429 | 0.387 | 165 ms | 212 ms |
| hybrid | identifier | 0.953 | 0.556 | 0.656 | 0.375 | 0.516 | 165 ms | 212 ms |
| hybrid | keyword | 0.941 | 0.793 | 0.808 | 0.647 | 0.294 | 165 ms | 212 ms |
| hybrid | paraphrase | 0.718 | 0.410 | 0.502 | 0.282 | 0.357 | 165 ms | 212 ms |
| hybrid | fr | 0.933 | 0.596 | 0.648 | 0.467 | 0.429 | 165 ms | 212 ms |

MRR@10 against lexical: semantic +0.054 (p = 0.197, adjusted 0.305), hybrid +0.039
(p = 0.153, adjusted 0.305).

Against the bar, hybrid failed on all three counts: its gain was not significant; it
lost 0.061 on identifier questions (keyword: 0.019, within the bar); and its 95th
percentile was 212 ms on this CPU. **Words became the default again**, by the
maintainer's word on that rule, until plan 025 (below).

Against plan 011's bge-small, question by question on the same set (from the two
results files, with the script above): semantic +0.020 (p = 0.57; 31 questions better,
31 worse), hybrid -0.028 (p = 0.28; 16 better, 24 worse). Neither is significant. Plan
011's results file is kept on the development laptop only, and its in-process model is
gone, so this comparison cannot be run again from the repository.

### Plan 019: four chunkings, and the defaults since

The same questions, mirror and model, on 2026-10-22 and 23, with the index cut four
ways; [chunking](chunking.md) holds every table, cost and test. `windows` ranked best of
the four, by meaning alone and in hybrid mode. Over `windows`, hybrid search reached
MRR@10 0.639, against 0.578 over `sections` (adjusted p 0.0114) and 0.539 by words alone
(adjusted p 0.0008), with 0.674 against words' 0.616 on identifier questions and 0.855
against 0.812 on keyword questions; its 95th percentile of query time was 266 ms on this
laptop's CPU. Semantic search over `windows` scored higher still (MRR@10 0.674,
Evidence@ask 0.500 against 0.357), at 256 ms. On MRR@10 alone, `eval`'s paired
randomisation test, run afterwards on the ranks that the results file keeps (10,000
samples, seed 11), found the difference, 0.035, not significant (p 0.27): meaning alone
did better on 25 questions, hybrid on 22, and 58 tied. The difference in Evidence@ask
was not tested, since the results file keeps `ask`'s measures by group alone; [comparing
chunkings and modes](#comparing-chunkings-and-modes) gives the lines of the test.

Neither rule chose `windows` and hybrid search. Plan 019's rule, which decides the
chunking by the evidence that `ask` quotes, kept `sections`. Plan 018's bar, applied to
`windows`, was met on the gain and on identifier and keyword questions but not on
speed, so words would have stayed.
Knowing these numbers, the maintainer made `windows` and hybrid search the defaults
(plan 025), as ranking matters more to them than speed. The rules and their verdicts
above stay as written: what changed is the choice made after them, the maintainer's.

### Plan 022: reranking, on a laptop

The same questions and defaults, hybrid search over `windows`, on 2026-10-26, reranked
by Qwen3-Reranker-0.6B through llama.cpp 0.6.0 on this laptop's CPU, one depth a run
as the machine was shared ([reranking](reranking.md) explains the bar):

| Depth | MRR@10 | Identifier | Keyword | Success@1 | Evidence@ask | Search, median | Search, 95th |
|---|---|---|---|---|---|---|---|
| none | 0.639 | 0.674 | 0.855 | 0.505 | 0.357 | 173 ms | 244 ms |
| 10 | 0.542 | 0.664 | 0.650 | 0.362 | 0.357 | 28,956 ms | 41,276 ms |
| 20 | 0.557 | 0.643 | 0.665 | 0.390 | 0.386 | 36,514 ms | 60,373 ms |
| 30 | 0.554 | 0.636 | 0.664 | 0.390 | 0.395 | 36,257 ms | 77,230 ms |

Every depth measured ranked worse than the order not reranked: MRR@10 fell by 0.082 to
0.097, with paired tests' p of 0.013, 0.0569 and 0.0526 at depths 10, 20 and 30,
before Holm's correction over the four depths. Keyword questions lost most, about 0.2:
their words had already put the answer first. Looking at questions whose answer lost
first place, the order follows the scores, and a text scores the same alone as beside
another, so neither the program nor batching is at fault: the model scores many
passages on the subject near 1 without their answering, such as an incident report at
0.9996 above the page that answers at 0.9985. Evidence@ask rose a little at 20 and 30
(0.386 and 0.395 against 0.357), untested. Depth 50 could not be measured: after 50
questions, a request passed the run's deadline of 300 seconds three times.

So no depth met the bar here: clauses 1 and 2, which hold for any machine, failed at
10, 20 and 30, and clause 3, by this laptop's times, at every depth. Reranking is off by
default, as the maintainer chose the more accurate results; a measure on the machine that
serves agents, with its own questions, tells whether to turn it on there: a GPU, a
later llama.cpp or another model may change the times, the scores of another corpus
the ranks.

### What these runs show, and what they do not

- **Meaning finds more.** In every run, search by meaning raised recall (from 0.78 to
  between 0.81 and 0.87) and lifted paraphrase questions most (MRR@10 from 0.24 to 0.49
  with Qwen3).
  With Qwen3, searching by meaning also did far better than words on French (0.74
  against 0.45). This run did not test EmbeddingGemma, which the leaderboard puts ahead
  of Qwen3 on French; and 15 questions are too few to read much into either way.
- **Fusion is not free.** Reciprocal rank fusion
  ([Cormack, Clarke and Büttcher, 2009](https://doi.org/10.1145/1571941.1572114))
  weighs the two rankings equally. With Qwen3, whose ranking was weaker than words' on
  identifiers (0.501 against 0.616), fusion pulled hybrid below words there, and below
  semantic search overall. Over `windows` (plan 019), meaning held identifiers itself
  (0.673 against 0.616), and so did hybrid search (0.674), but fusion still left hybrid
  below semantic search overall (MRR@10 0.639 against 0.674). Tuning the fusion on these
  same questions would fit it to them; it waits for more questions.
- **The leaderboard's English lead did not show here.** On the 90 English questions,
  Qwen3's semantic MRR@10 (0.568) was no better than bge-small's (0.587). The sandbox's
  documents are invented, written by the same plan as the questions, and small; the
  public benchmarks are none of these. Neither result overrides the other: they answer
  different questions, with different power.
- **Times are this laptop's.** Ollama ran on its CPU. The cold embedding of the 6,729
  pieces took 1,516 seconds (4.4 pieces a second, about 75 minutes for 20,000 pieces,
  past the gate of 30 minutes); plan 011's in-process int8 Qwen3 took 892 seconds on the
  same machine. A laptop's GPU should be faster, by an estimate of 15 to 45
  minutes for 20,000 pieces; nothing measured it yet. Later builds embed only what
  changed. A hybrid query, which embeds the question, took 266 ms at the 95th
  percentile over `windows` on this CPU; the user's machine's time is for the next run to
  say.
- **The work set decides.** Everything here rests on one invented corpus and the
  questions written with it. Your own documents and the questions agents really send
  are the evidence that should settle the default.

## Reproducing it

Every step runs from a checkout of this repository, with `uv`, on any machine: this
laptop, or another such as the user's machine, whose GPU should change the times. The
sandbox's commands name `--config <missing-file>`, a path where no file is, so that the
machine's settings file changes nothing: otherwise `prepare` would write its account's
site into the mirror's addresses, and `embed`, `model check` and `eval` would take its model and
endpoint, `embed` its chunking too. The variables `KB_MCP_…`
still apply: leave them unset, but where a command sets them. On your own corpus, your
settings are the point: leave the flag out. Two things come first:

- **Ollama on the host**, running, with the model pulled: `eval` searches by meaning,
  and `embed` asks for its vectors. Install Ollama on the host, not in a container (a
  container on macOS cannot use the Mac's GPU), and start it (the Ollama app, `brew
  services start ollama`, or `ollama serve`). Then pull the model and check it:

  ```bash
  ollama pull qwen3-embedding:0.6b
  ```

  ```bash
  uv run kb-mcp model check --config <missing-file>
  ```

  `model check` says the model's dimensions and digest, or what to run when the
  endpoint or the model is missing.
- **A mirror and a golden file**: the sandbox's, built next, or your own corpus's (the
  last section).

### The sandbox run

With the sandbox's credentials (the project's own test site) and pandoc installed,
from a checkout, into a data directory outside any synchronised folder or git tree. The
corpus's pages are in the space `QM`, its tickets in the project `ENG`, its ideas in
`PRB`; plan 011's mirror also held the 13 probe pages of plan 001 in `MFS`:

```bash
sops exec-env <primary checkout>/atlassian-test-credientials.sops.json 'KB_MCP_ACCOUNTS__ATLASSIAN__SITE="$ATLASSIAN_SITE" KB_MCP_ACCOUNTS__ATLASSIAN__EMAIL="$ATLASSIAN_EMAIL" KB_MCP_ACCOUNTS__ATLASSIAN__API_TOKEN="$ATLASSIAN_API_TOKEN" uv run kb-mcp fetch --yes --config <missing-file> --data-dir <data> --since 1y --space MFS --space QM --project ENG --project PRB'
```

The credentials file lies at the root of the checkout that made it, never in git
(`.gitignore` excludes `*.sops*`), and only the keys it was encrypted for open it. On
another machine, bring the file and a key; or make a file of your own for the sandbox's
account, with a new token, by [the sops how-to](../how-to/api-token-with-sops.md), under
the same generic names; or skip `fetch` and `prepare`: copy `<data>/docs` (7 MB)
from a machine that has it into the new data directory, and go on from `index`.

```bash
uv run kb-mcp prepare confluence jira --config <missing-file> --data-dir <data>
```

```bash
uv run kb-mcp index --config <missing-file> --data-dir <data>
```

```bash
uv run kb-mcp embed --config <missing-file> --data-dir <data>
```

`index` should report 1,474 documents (263 pages and 1,211 issues), as in plans 011 and
018; without `ENG`, 31 questions name tickets that the mirror lacks, which `eval`
refuses by name. `embed` then embeds the mirror's windows, which `eval` then
finds in `<data>/vectors.sqlite` and does not embed again.

```bash
uv run python spikes/golden_refs.py --data <data> --out <data>/eval/sandbox.yaml
```

Then measure every chunking in every mode:

```bash
uv run kb-mcp eval <data>/eval/sandbox.yaml --config <missing-file> --data-dir <data> --model qwen3-embedding:0.6b
```

### Comparing chunkings and modes

`eval` builds its own index per model and chunking under `<data>/eval/indexes/`,
measures the three modes on each, embeds only what `<data>/vectors.sqlite` lacks,
prints the tables, and writes the numbers (never the questions) to
`<data>/eval/results/`. It measures every chunking, whatever the setting `chunking`
says, unless `--chunking` names some; and the setting's model unless `--model` names
others, several to compare them in one run. `--summary detailed` adds every group and
the tests of each mode against words. To compare the defaults with the chunking that
plan 019's rule kept:

```bash
uv run kb-mcp eval <data>/eval/sandbox.yaml --config <missing-file> --data-dir <data> --model qwen3-embedding:0.6b --chunking sections --chunking windows --summary detailed
```

The first run embeds each chunking's pieces that the vector store lacks, which took 31
minutes for `sections` on this laptop's CPU; a later run embeds only what changed, and
the sandbox run of all four chunkings took 6 minutes once every vector was kept.

For each model and chunking, the output has a part headed `## <model>, <chunking>`:

- In its table of `search`, the row of a mode and the group `all` gives MRR@10 and the
  other measures, then `Query, median` and `Query, 95th`: the median and the 95th
  percentile of the time to rank one question, in milliseconds (see *Query time*,
  above). The row `hybrid` is the defaults' when the chunking is `windows`. Plan 018's
  bar asked for 200 ms at most; this laptop's CPU took 266 ms there.
- With `--summary detailed`, `MRR@10, hybrid against lexical: p = ..., adjusted (Holm)
  ...` tests hybrid search against words on that chunking. The rows of `lexical` come
  with the first chunking alone, since words ignore the chunking.
- At the end, `Default chunking for <model>, by the rule: ...`, with each challenger's
  tests against `sections`: the verdict of plan 019's rule on these questions, which is
  not the setting.

Holm's correction adjusts the tests of one run together, so its adjusted p-values depend
on how many chunkings and models the run measures: a run of two chunkings adjusts less
than the sandbox run of four. Compare runs of the same shape, or read the raw p-values
beside them.

The results file keeps each run's times in seconds, `[median, 95th]` by mode under
`times` (and under `ask_times` for `ask`). This prints the 95th percentiles in
milliseconds:

```bash
uv run python -c 'import json, sys; [print(run["model"], run["chunking"], mode, round(times[1] * 1000), "ms") for run in json.load(open(sys.argv[1]))["runs"] for mode, times in run["times"].items()]' <data>/eval/results/<time>.json
```

`eval` tests each mode against words alone, never two modes against each other. The
results file keeps, under `ranks`, each question's rank of each expected document by
mode, `null` past the tenth, from which each question's MRR@10 follows. These lines run
`eval`'s own paired test of semantic search against hybrid search over `windows` (the
first model's run, if there are several), and print the difference in MRR@10 and the
p-value, then the questions where meaning alone did better, worse and the same; on plan
019's file, `20261023T001258Z.json`, they print `0.035 0.27`, then `25 22 58`:

```bash
uv run python - <data>/eval/results/<time>.json <<'EOF'
import json, sys
from statistics import fmean
from kb_mcp.evaluation.domain.evaluation import paired_test
runs = json.load(open(sys.argv[1]))["runs"]
ranks = next(run["ranks"] for run in runs if run["chunking"] == "windows")
mrr = {
    mode: [max((1 / rank for rank in each if rank), default=0.0) for each in by_question.values()]
    for mode, by_question in ranks.items()
}
gains = [after - before for before, after in zip(mrr["hybrid"], mrr["semantic"])]
print(round(fmean(gains), 3), round(paired_test(mrr["hybrid"], mrr["semantic"]), 2))
print(sum(gain > 0 for gain in gains), sum(gain < 0 for gain in gains), gains.count(0))
EOF
```

`ask`'s measures, Found@ask and Evidence@ask, are kept by group alone, so no such test
can be run on them.

### Measuring reranking

Plan 022's bar says whether reranking is worth turning on on a machine, and at which
depth ([reranking](reranking.md#the-bar-fixed-before-the-run)); it is off by default.
With the sandbox's data directory as above, Ollama running with the model, and
the reranking server started as [the how-to](../how-to/reranking.md#start-the-server)
starts it, at its address and under its alias, which are the settings' defaults:

```bash
uv run kb-mcp reranker check --config <missing-file>
```

```bash
uv run kb-mcp eval-rerank <data>/eval/sandbox.yaml --config <missing-file> --data-dir <data>
```

It measures the defaults, hybrid search over `windows` with `qwen3-embedding:0.6b`,
first not reranked, then reranked at depths 10, 20, 30 and 50: 110 texts scored for
each of the 105 questions, 2.6 to 4.6 million tokens. By the estimate in
[reranking](reranking.md#why-only-the-first-documents), that takes about 20 to 35
minutes on the user's machine; on a laptop's CPU with llama.cpp 0.6.0, depths 10, 20 and 30
took 50, 64 and 74 minutes, a run each, and depth 50 could not end. The output has a
table with a row per depth, `none` the order not reranked, the first ranking's Recall@N,
a line per depth with each clause's verdict and each group's loss, each qualifying
depth's p-value against the best, and the bar's last line, `By the bar, with this
machine's times: turn reranking on, at depth N.` or `...: leave reranking off.` Its
third clause reads the times of the machine that ran it: only the user's machine's run tells
whether to turn reranking on there.
[The how-to](../how-to/reranking.md#measure-it) also gives a short measure, one depth
on a sample of the questions, and what to check in each.

On another machine, copy the data directory there: the sandbox's content is invented.
Its `vectors.sqlite` spares the embedding when Ollama there lists the same digest for
the model; otherwise the first run embeds the windows again.

### On another corpus, such as your work set

1. Write golden questions as agents ask them: keywords and names as often as
   sentences, in the languages you use. Thirty is a start; a hundred or more is needed
   to see differences of 0.05 in MRR@10.
2. For each, find the documents that answer it by hand, and a phrase of each that
   states the answer. The guide shows the file's format.
3. Write the bar before the first run, as above.
4. Keep the golden file in `<data>/eval/`, never in a repository: it holds your
   company's content.
5. Run `eval` as in [comparing chunkings and modes](#comparing-chunkings-and-modes),
   on your golden file and without `--config`; read the groups as well as the totals,
   and the query time in `Query, 95th` against the 200 ms of plan 018's bar; keep the
   results files to compare later runs.

## Sources

- Muennighoff, Tazi, Magne and Reimers, [MTEB: Massive Text Embedding
  Benchmark](https://arxiv.org/abs/2210.07316), EACL 2023.
- Enevoldsen et al., [MMTEB: Massive Multilingual Text Embedding
  Benchmark](https://arxiv.org/abs/2502.13595), ICLR 2025.
- The [MTEB leaderboard](https://huggingface.co/spaces/mteb/leaderboard), read on
  2026-10-21 through its backend, and the model cards of
  [Qwen3-Embedding-0.6B](https://huggingface.co/Qwen/Qwen3-Embedding-0.6B),
  [EmbeddingGemma](https://huggingface.co/google/embeddinggemma-300m) and
  [EmbeddingGemma 2](https://huggingface.co/google/embeddinggemma-2).
- Järvelin and Kekäläinen, [Cumulated gain-based evaluation of IR
  techniques](https://doi.org/10.1145/582415.582418), ACM TOIS 20(4), 2002.
- Holm, [A simple sequentially rejective multiple test
  procedure](https://www.jstor.org/stable/4615733), Scandinavian Journal of Statistics
  6(2), 1979.
- Smucker, Allan and Carterette, [A comparison of statistical significance tests for
  information retrieval evaluation](https://doi.org/10.1145/1321440.1321528), CIKM 2007.
- Cormack, Clarke and Büttcher, [Reciprocal rank fusion outperforms Condorcet and
  individual rank learning methods](https://doi.org/10.1145/1571941.1572114), SIGIR 2009.
- Plans 011 and 018, in `docs/work/changelog/`, for every run's full tables, its
  decisions and its reviews.
