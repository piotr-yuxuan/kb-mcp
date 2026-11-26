# Evaluating search

How this project decides how to search: which embedding model to use, and whether to
rank by words, by meaning, or by both. It explains the reasoning, the measures and the
statistics, the default rules that weigh a challenger against a setting, how to read the
numbers, and what the runs so far do and do not show, so that the next decision, on your
own content, can be made the same way.

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
French; once the user said that French was not needed for now, English retrieval
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
EmbeddingGemma's compute; EmbeddingGemma led in French. The user chose Qwen3,
also for its 32,768-token window, which leaves room for the chunking strategies to be
compared next.

### What to distrust in a leaderboard

- **Self-reported against reproduced.** A model card's numbers are its authors'. For
  EmbeddingGemma 2, Google's card gave only overall means; Google's per-task submission
  to MTEB was withdrawn unmerged
  ([results#745](https://github.com/embeddings-benchmark/results/pull/745)), and the
  leaderboard shows the benchmark team's own rerun
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
check that the chosen model works in our pipeline (prompts, chunks, fusion) and to
choose the way of searching. The embedding model's default rule (below) is that check:
it asks a candidate no gain, only that it lose little and search faster.

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

For every question, in each mode, `eval` ranks it through `Library.ranked`, the code
that ranks agents' `search`, and keeps the first 30 documents, the first ten for the
measures; answers it through `Library.quoted`, as `ask` answers; then asks `search` and
`ask` themselves, as the server answers an agent, for what their answers cost and how
long a search takes. Refs resolve through the index that the server reads. A question
whose expected ref names no document there is skipped, and named with its ref: an index
older than the mirror misses documents, and `kb-mcp index` brings it up to date. A
helping ref that names none is dropped, and two refs of one document count once.

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
  evidence phrase, the share whose shown section holds it. A's does, B's does not:
  **0.5**. It says whether the agent is shown the right part of a long page, not merely
  the page.

Evidence is sought as a reader would find it: both texts are read without Markdown's
backslash escapes, emphasis and code marks, and table pipes, links and images as their
words, in one case and with spaces as one; then the phrase must be there as whole words,
so that "art the brokers" is not found in "Restart the brokers". One function
does it ([`holds`](../../src/kb_mcp/evaluation/domain/evaluation.py)) for Section@10,
Evidence@ask, the records of each hit, and the grading of agents' quotes.

`eval` averages each measure over all questions, and over each group, but Section@10:
it averages over the questions whose expected document, with its evidence, every arm of
the run found in its first ten, every index and every mode, and the output says how
many. Otherwise an arm that finds fewer documents would average over other questions,
perhaps easier ones, and the arms would not compare.

### What an answer costs

An agent pays for what it reads, in tokens of its context. `eval` counts, for each
question and mode, the characters of the first answer of `search` (8 hits, its default)
and of `ask`, as the server writes them to an agent, at four characters a token, the
estimate that the evaluation's costs use. The tables give their means, `Tokens` in each.

**E/kT**, the evidence per thousand tokens, says what `ask`'s answers give for what they
cost: over the questions that have evidence, the evidence that their passages hold (each
question's Evidence@ask, summed) divided by the thousands of tokens of their answers. It
is a ratio of sums, not a mean of each question's ratio. Take two questions: one answer
of 1,000 tokens holds its evidence, another of 3,000 tokens holds none. E/kT is (1 + 0)
/ (1 + 3) = 0.25: one answer in evidence for 4,000 tokens spent. The mean of the two
ratios would be (1/1 + 0/3) / 2 = 0.5, as if the short answer's luck paid for the long
one; and an answer of no token would divide by zero. While `ask`'s budget is fixed, its
answers are about the same length, and E/kT orders the arms as Evidence@ask does; it
tells them apart once answers differ in length.

The results file keeps, question by question, every measure that the tables average:
each question's measures of `search` (`per`) and of `ask` (`asked_per`), by mode, and
the raw data from which others can be computed later (`raw`): the hits of `search`'s
first answer, each with its ref, the section shown, the tokens that reading that section
costs and whether its snippet and its section hold the evidence; `ask`'s passages, each
with its ref, characters and whether it holds the evidence; and the first 30 refs of the
mode's ranking. Ranks, not scores: enough to replay a fusion of the rankings by words
and by meaning, or another cut-off, without running the search again. [The data
layout](../reference/data-layout.md#evaluation-results) lists the keys.

### Reading MRR@10 with Success@1 and Recall@10

For one question, the reciprocal rank is one over the rank of the first expected
document, and 0 if it is not in the first ten; MRR@10 is its mean over the questions.

| Rank of the first expected document | 1 | 2 | 3 | 4 | 5 | 10 | past 10 |
|---|---|---|---|---|---|---|---|
| Reciprocal rank | 1 | 0.5 | 0.333 | 0.25 | 0.2 | 0.1 | 0 |

The curve falls steeply: a document moved from rank 2 to rank 1 gains 0.5, one moved
from rank 10 to rank 5, 0.1. MRR@10 is mostly a measure of how often the first hit is
right, with a little credit for the second and the third.

A ladder for reading it, when each question expects one document, as most golden
questions do. Read it on 100 questions or more: a group of 30 moves by about 0.15 by
chance, one of 12 says nothing.

| MRR@10 | Reading | What an agent lives through |
|---|---|---|
| 0.85 and up | excellent | the first hit is right about four times in five; the rest at rank 2 |
| 0.70 to 0.85 | good | right first about two times in three, found in the first three almost always |
| 0.50 to 0.70 | fair | right first about half the time; one or two reads more on the others; some misses |
| 0.30 to 0.50 | poor | right first a third of the time; many misses; the agent rephrases |
| under 0.30 | failing | the agent cannot rely on it |

Public benchmarks score lower for strong systems (on MS MARCO, MRR@10 is about 0.19 for
words alone and about 0.4 for good retrievers by meaning) because their judgements are
sparse: many right answers are not labelled. Numbers compare only on the same questions
with the same judgements.

**The same MRR, two shapes.** MRR alone hides where the documents land. Both systems
below score MRR@10 = 0.60:

| System | First expected document at rank 1 | At rank 2 | Missed | Success@1 | MRR@10 | Recall@10 |
|---|---|---|---|---|---|---|
| A | 60% | 0% | 40% | 0.60 | 0.60 | 0.60 |
| B | 20% | 80% | 0% | 0.20 | 0.60 | 1.00 |

A is right first more often, and hopeless the rest of the time: the agent rephrases,
searches again, or answers wrongly. B is rarely right first, but always second: one read
more, never a miss. For an agent, B is often the cheaper, since a second read costs a
section, and a miss costs a rephrasing, more searches, or a wrong answer. So read three
numbers together:

| Measure | The question it answers | The cost it stands for |
|---|---|---|
| Success@1 | was the first hit right? | nothing more to read |
| MRR@10 | how high, on average? | how many hits are read before the right one |
| Recall@10 | was it anywhere in the first ten? | whether reading on can help at all |

Recall@10 less Success@1 is the share of questions where reading on pays; one less
Recall@10, the share where it cannot, and the agent must search again.

**Why MRR understates what reading costs.** An agent that reads the hits in order pays
for each one up to the right one, so its cost follows the mean rank, not the mean
reciprocal rank. One over MRR@10 is the harmonic mean of the ranks, which is never more
than their arithmetic mean: ranks 1 and 9 give an MRR@10 of 0.556, as if the mean rank
were 1.8, where the agent reads five hits on average. Two systems of the same MRR can
cost different tokens, which is why `eval` counts the tokens of the answers, and keeps,
for each hit, what reading it costs.

The other measures, with a rule of thumb for each:

| Measure | What it says | Rule of thumb |
|---|---|---|
| Recall@10 | the share of the expected documents in the first ten | with one expected document, the share of questions where it shows at all; under 0.8, the agent often searches twice |
| nDCG@10 | like MRR@10, but every expected and helping document counts, discounted by rank | close to MRR@10 when one document is expected; higher when several are and they rank well |
| Section@10 | when an expected document is in the first ten, whether the section shown holds the evidence | the share of hits whose `read` opens at the answer; under 0.6, many reads are wasted |
| Found@ask | the share of the expected documents that `ask` quotes a passage of | `ask`'s recall |
| Evidence@ask | the share of evidence phrases that `ask`'s passages hold | whether `ask` saves a `read` |
| Tokens | the mean tokens of `search`'s first answer, or of `ask`'s | what one call costs the agent |
| E/kT | the evidence that `ask` holds per thousand tokens of its answers | what `ask` gives for what it costs |

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

### Several tests at once: Bonferroni over a fixed family

A default rule that asks a gain (below) compares each challenger of its family with the
control: several tests at once. At 0.05 each, the chance that at least one challenger
that is truly no better shows a gain by chance grows with their number m: about
1 - 0.95^m, 0.10 for two tests, 0.19 for four. A correction raises each p-value so that
the chance of any false gain in the family stays near 0.05; a decision rests on the
adjusted values.

- **Bonferroni's correction** multiplies each p-value by m and caps it at 1.
- **[Holm's step-down method](https://www.jstor.org/stable/4615733)** (1979) sorts the
  p-values, multiplies the i-th smallest of m by m - i + 1, keeps each no smaller than
  the one before, and caps at 1: never stricter than Bonferroni, and less strict for all
  but the smallest. In plan 018's run, p = 0.1526 and 0.1968: the smaller becomes 0.1526
  × 2 = 0.3052, and the larger, 0.1968 × 1, is raised to 0.3052 so as not to fall below
  it.

The default rules that ask a gain correct by Bonferroni over the rule's family, its m
fixed by the rule: two search modes, three chunkings, four depths, whatever the run
measured. By Holm, one
challenger's adjusted p-value depends on the others' raw ones, so a verdict would depend
on which arms were run: a challenger alone in its run keeps its raw p-value; beside
others that score worse, it is multiplied by their number. By Bonferroni over the fixed
family, a challenger's adjusted p-value is its own raw one times m, the same whether the
run measured it alone or with all the others. For example, with `windows` as the
setting and a run of `windows` and `sections` alone, `sections`' raw p-value on
Evidence@ask of 0.02 is adjusted to 3 × 0.02 = 0.06, not below 0.05, whether or not the
two other chunkings ran; by Holm, it would stay 0.02 alone, and qualify, and become 0.06
beside two others that score worse. What Bonferroni costs: when several challengers are
truly better, Holm finds more of them; and a run of one challenger pays for the whole
family. `eval-agents` keeps Holm, over the three measures that it compares, a family
that never changes ([evaluating with agents](../how-to/evaluate-with-agents.md)).

The embedding model's default rule asks no gain: it tests nothing, and so corrects for
nothing, its family, the models that a run measures, being fixed by no list.

### Effect size, significance and power

A p-value says how surprising a difference would be if there were none, not how large
it is. Each verdict of `eval` gives each challenger's mean beside the control's, so
their difference, and its adjusted p; read both. Counting the questions that each mode
wins helps too: in plan 018's run, hybrid did better than lexical on 32 questions, worse
on 14, and the same on 59.

**Power** is the chance that a test detects a real difference. It grows with the
number of questions and falls with the spread s of the per-question differences (their
standard deviation). With n questions, a two-sided test at 0.05 detects about four
times out of five a difference of 2.8 s / √n (1.96 for the test, plus 0.84 for the
four times in five). In our runs s was 0.24 to 0.43, so with 105 questions the
detectable difference in MRR@10 was **0.065 to 0.12**. Plan 011's hybrid gain with its
model, 0.067, was at that edge, and significant; plan 018's, 0.039, was below it, and
not. "Not significant" means "not shown", not "no difference".

Rules of thumb, from the same arithmetic:

- With 100 questions, one MRR@10 is known to about ±0.08, 95 times in 100: reciprocal
  ranks lie between 0 and 1, many at 1 and many at 0, and spread by about 0.4.
- Two arms on the same 100 questions: a difference under 0.07 is noise; the paired test
  sees 0.07 to 0.12 and more four times in five, by how much the questions disagree.
- To see 0.05, a set needs some 200 to 600 questions, (2.8 s / 0.05)² at the spreads
  above; to see 0.03, more than 500.
- Per group of about 33, read only differences of 0.15 or more; per group of 12, none.
- Look at the questions that moved, too: a gain made of nearly as many questions down
  as up is churn more than progress.

`eval` does not print the counts or the spread, but its results file holds what they
need: for each model, mode and question, the ranks of the question's expected documents
within the first ten (`null` beyond), and each question's measures under `per`. This
prints them for hybrid against lexical, with `eval`'s paired test; two results files of
the same golden file compare two models the same way, as the comparison with plan 011's
model below was made. A results file written before plan 054 names its evaluated indexes
`runs`, not `indexes`: read it so in these lines and those below.

```python
import json, math, statistics, sys

from kb_mcp.evaluation.domain.evaluation import paired_test


def reciprocal(ranks):  # MRR@10 of one question: 1 over its best rank, else 0
    found = [rank for rank in ranks if rank is not None]
    return 1 / min(found) if found else 0.0


run = json.load(open(sys.argv[1]))["indexes"][0]
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

A rule written first binds the reading of the numbers, not the user's choice.
Once the numbers are known, the user may weigh what the rule left out, such as
ranking against speed, provided the rule's verdict stays on record and the choice is
said to be theirs; plan 018's bar said as much, leaving the decision to the user
if it failed.
The defaults since plan 025 are such a choice (below). Those bars, the reranking's and
the owner's bar for the embedding model are now the default rules.

### The default rules

A **default rule** keeps a setting's value unless a challenger, measured on the same
golden questions, qualifies. There is one per decision, written before the runs, as
data that `eval` and `eval-rerank` apply
([`RULES`](../../src/kb_mcp/evaluation/domain/evaluation.py),
[`verdict`](../../src/kb_mcp/evaluation/domain/evaluation.py)). Each has:

- a **control**, the value in use, and a **family**, the values that may replace it;
- a **deciding measure**, on which the rule may ask a **gain**: a challenger must then
  beat the control on it, its mean higher, with a p-value below 0.05 once multiplied by
  the size of the family (Bonferroni's correction, above);
- **guards**: groups of questions that may lose at most so much of MRR@10, so that a
  gain on average is not paid for by a kind of question that agents send often;
- a **bound** on what a challenger may spend: tokens embedded, as a multiple of the
  control's, or a search's 95th percentile on the machine measured; or, without a
  bound, less than the control spends;
- a **margin**: of the challengers that qualify, those within 0.01 of the best mean are
  as good as the best, and the cheapest of them is kept. Else the control stays.

A rule is of one of two kinds. Either it asks a gain over a family that it fixes,
whatever a run measures, as the search mode's, the chunking's and the reranking depth's
do; or it asks no gain, over the values that the run measured but the control, which
no list can name, as the embedding model's does: a challenger then qualifies by its
guards and by spending less than the control.

| Rule | Control | Family | Decides on | Gain | Guards: MRR@10 lost, at most | Bound | Margin | Cheaper |
|---|---|---|---|---|---|---|---|---|
| search mode | the setting `search_mode` | the two other modes | MRR@10 | asked | 0.05 on `identifier` and on `keyword` | a search's 95th percentile within 500 ms | 0.01 | `lexical`, then `semantic`, then `hybrid` |
| chunking | the setting `chunking` | the three other chunkings | Evidence@ask, in hybrid mode | asked | 0.02 over all the questions; 0.05 on `identifier`, `keyword` and `paraphrase`, in hybrid mode | tokens embedded within three times the control's | 0.01 | fewer tokens embedded |
| reranking depth | the order not reranked | depths 10, 20, 30 and 50 | MRR@10 | asked | 0.05 on `identifier` and on `keyword` | a search's 95th percentile within 5 s | 0.01 | a smaller depth |
| embedding model | the setting `model`, in its mode | every other model measured, in each mode by meaning | MRR@10, each arm in its mode | none asked | 0.03 over all the questions; 0.05 on `identifier`, `keyword` and `paraphrase` | a search's 95th percentile less than the control's | 0.01 | the faster search |

- **The search mode's default rule** applies to each model and chunking that `eval`
  measures, the three modes being measured on each. Words cost an index alone; meaning
  costs a model, an embedding of the question and a slower search; hybrid search costs
  both. Whichever is the setting, another mode replaces it only when shown better on
  MRR@10, and of those that are, within the margin, the cheaper. Its bound, 500 ms,
  replaces the 200 ms that the bars of the runs below asked; hybrid search over
  `windows` took 266 ms at the 95th percentile on the development laptop's processor.
- **The chunking's default rule** applies to each model, in hybrid mode. It decides on
  Evidence@ask, whether `ask`'s passages hold the evidence, which is what a chunking
  changes most directly; E/kT is reported beside, and orders the arms alike while
  `ask`'s budget is fixed. Its cost is the tokens that the index embeds, at four
  characters each: three times the control's admits `small-to-big`, which repeats each
  chunk's context, about 2.1 times `sections`', and refuses only a cold build three
  times as long. [Chunking](chunking.md#how-they-are-compared) says more.
- **The reranking depth's default rule** is applied by `eval-rerank` to the depths that
  it measures; [reranking](reranking.md#the-default-rule-fixed-before-the-run) says why
  each clause. An arm whose rerankings failed on more than 5% of the questions, measured
  in their order not reranked, gives no verdict.
- **The embedding model's default rule** applies to each chunking over which `eval`
  measures two models or more; over one, it says nothing. A leaderboard chooses the
  candidates ([choosing a model](#choosing-a-model-from-published-results)); the golden
  questions only check that one, in a mode by meaning, loses at most 0.03 of MRR@10 over
  all the questions and 0.05 on each of `identifier`, `keyword` and `paraphrase`, and
  searches faster. Each arm is a model in one mode, named `<model>, <mode>`, its scores,
  groups and search time all that mode's, so that a candidate is weighed on the quality
  and the cost of one mode together. The current model is weighed as it is served, in
  the setting `search_mode` when that reads a model, else in its best mode by meaning, a
  tie going to `semantic`; every other model gives an arm in each of `semantic` and
  `hybrid`, and may qualify in either. Lexical search reads no model. Its verdict is
  advice, as every verdict is. It leaves out the time to build an index: the vector cache that `eval`
  shares with `embed` always holds the current model's vectors, so its index would be
  timed reading the cache while a candidate's is timed embedding. A candidate truly
  equal to the current model fails the overall guard about one time in seven, at a
  standard error near 0.028 over 100 questions, and each group's about one time in six,
  near one standard error at some 33 questions: about half the time, one of the four
  refuses it.

A run need not measure the whole of a fixed family: a challenger that it did not measure
cannot qualify, and the verdict names it. There is no verdict when the control was not
run, when no challenger was, or when no question has a measure of the deciding one, such
as Evidence@ask without evidence phrases; the verdict says why. A verdict is the rule's
on these questions, on this machine: it changes no setting, which stays the user's to
set.

Values compare as reported: means to three decimals, p-values to four, times in whole
milliseconds, and a group's loss as the difference of its two means so shown. A loss of
0.050 holds, 0.051 does not; a group that the golden file does not name has no loss to
show, holds, and reads `n/a`.

**Why a margin.** Of two challengers that qualify, one 0.004 behind the best, at a third
of its cost, is as good for any purpose: 0.004 is far below what 100 questions can tell
apart. The margin says how close counts as equal; then the cheapest wins. An earlier
rule asked instead that the cheaper be "not shown lower" than the best by a second test,
which takes a lack of evidence for evidence of equality: at about 100 questions, an arm
0.08 worse is often not shown lower.

**A guard sometimes refuses a challenger that is truly equal.** A guard is a threshold
on a group's mean, not a test, and a group's mean moves by chance. With the spread of
per-question differences seen on the sandbox, about 0.28, the mean difference of a group
of 33 questions varies by about 0.28 / √33 ≈ 0.05, one standard error. A challenger
truly equal to the control would show, by chance, a loss past 0.05 on such a group about
one time in six, the share of a normal distribution past one standard deviation; with
two guarded groups, about three times in ten on one or the other. Over all of 100
questions, the standard error is about 0.028, and the chunking's guard of 0.02 refuses
an equal challenger about one time in four. A wider guard refuses fewer harmless
challengers and lets more real losses through: the guards are the user's to widen.

What a verdict looks like, the first line saying what the rule keeps, then each
challenger's clauses, then the values of the family not run:

```
Chunking for qwen3-embedding:0.6b, by the default rule: windows stays.
  sections: Evidence@ask <mean> against <control's mean>, adjusted p = <p>, gains <yes or no>; MRR@10 lost: all <loss>, identifier <loss>, keyword <loss>, paraphrase <loss>, holds <yes or no>; <tokens> tokens embedded, at most <three times the control's>, within <yes or no>
  section-paths, small-to-big: not run, so cannot qualify
```

`gains` is the deciding measure's clause, `holds` the guards', `within` the bound's. The
first line says `<value> stays` when the control is kept, `<value>, in place of
<control>` when a challenger replaces it, or `no verdict, since <why>`.

A rule that asks no gain gives no p-value nor `gains`; one without a bound gives each
cost against the control's, and `cheaper`; the embedding model's verdict names each arm,
the control's too, by its model and mode:

```
Embedding model for windows, by the default rule: qwen3-embedding:0.6b, hybrid stays.
  embeddinggemma:300m, semantic: MRR@10 <mean> against <control's mean>; MRR@10 lost: all <loss>, identifier <loss>, keyword <loss>, paraphrase <loss>, holds <yes or no>; 95th percentile <ms> ms against <control's ms> ms, cheaper <yes or no>
  embeddinggemma:300m, hybrid: MRR@10 <mean> against <control's mean>; MRR@10 lost: all <loss>, identifier <loss>, keyword <loss>, paraphrase <loss>, holds <yes or no>; 95th percentile <ms> ms against <control's ms> ms, cheaper <yes or no>
```

### Query time

`eval` times each question's `search` as the server answers an agent, its whole first
answer at the default limit of 8 hits, in each mode, and reports the median and the
**95th percentile** (by nearest rank: the time that 95 % of searches do not exceed).
The tail, not the average, is what an agent feels when a search stalls. The first query
by meaning is run untimed beforehand, since it reads the index's vectors. `eval-rerank`
times each search the same way, reranked at its arm's depth, apart from the deeper
ranking that it reads, untimed, for Recall@N.

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
6,729 chunks took 142 and 161 seconds. The full tables per group are in
plan 011's record.

### Plan 018: Qwen3 through Ollama

The same 105 questions and the same mirror (1,474 documents, 7,344 sections, 6,729
chunks), with `qwen3-embedding:0.6b` through Ollama 0.40.3 on the same laptop, on its
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
user's word on that rule, until plan 025 (below).

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
Knowing these numbers, the user made `windows` and hybrid search the defaults
(plan 025), as ranking matters more to them than speed. The rules and their verdicts
above stay as written: what changed is the choice made after them, the user's.

### Plan 022: reranking, on a laptop

The same questions and defaults, hybrid search over `windows`, on 2026-10-26, reranked
by Qwen3-Reranker-0.6B through llama.cpp 0.6.0 on this laptop's CPU, one depth a run
as the machine was shared ([reranking](reranking.md) explains the rule):

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
default, as the user chose the more accurate results; a measure on the machine that
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
  chunks took 1,516 seconds (4.4 chunks a second, about 75 minutes for 20,000 chunks,
  past the gate of 30 minutes); plan 011's in-process int8 Qwen3 took 892 seconds on the
  same machine. An laptop GPU should be faster, by an estimate of 15 to 45
  minutes for 20,000 chunks; nothing measured it yet. Later builds embed only what
  changed. A hybrid query, which embeds the question, took 266 ms at the 95th
  percentile over `windows` on this CPU; a GPU's time is for the next run to say.
- **The work set decides.** Everything here rests on one invented corpus and the
  questions written with it. Your own documents and the questions agents really send
  are the evidence that should settle the default.

## Reproducing it

Every step runs from a checkout of this repository, with `uv`, on any machine: this
laptop, or another such as one with a GPU, which should change the times. The
sandbox's commands name `--config <missing-file>`, a path where no file is, so that the
machine's settings file changes nothing: otherwise `prepare` would write its sources'
sites into the mirror's addresses, and `embed`, `model check` and `eval` would take its model and
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
sops exec-env <primary checkout>/atlassian-test-credientials.sops.json 'KB_MCP_SOURCES__CONFLUENCE__SITE="$ATLASSIAN_SITE" KB_MCP_SOURCES__CONFLUENCE__EMAIL="$ATLASSIAN_EMAIL" KB_MCP_SOURCES__CONFLUENCE__API_TOKEN="$ATLASSIAN_API_TOKEN" KB_MCP_SOURCES__JIRA__SITE="$ATLASSIAN_SITE" KB_MCP_SOURCES__JIRA__EMAIL="$ATLASSIAN_EMAIL" KB_MCP_SOURCES__JIRA__API_TOKEN="$ATLASSIAN_API_TOKEN" uv run kb-mcp fetch --yes --config <missing-file> --data-dir <data> --since 1y --space MFS --space QM --project ENG --project PRB'
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
skips, naming each. `embed` then embeds the mirror's windows, which `eval` then
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
`<data>/eval/results/`. It measures every chunking unless `--chunking` names some, the
setting `chunking` being the control of the chunking's rule; and the setting's model
unless `--model` names others, several to compare them in one run. `--detail detailed`
adds every group. To compare the defaults with the chunking that plan 019's rule kept:

```bash
uv run kb-mcp eval <data>/eval/sandbox.yaml --config <missing-file> --data-dir <data> --model qwen3-embedding:0.6b --chunking sections --chunking windows --detail detailed
```

The first run embeds each chunking's chunks that the vector cache lacks, which took 31
minutes for `sections` on this laptop's CPU; a later run embeds only what changed, and
the sandbox run of all four chunkings took 6 minutes once every vector was kept.

For each model and chunking, the output has a part headed `## <model>, <chunking>`:

- In its table of `search`, the row of a mode and the group `all` gives MRR@10 and the
  other measures, the tokens of `search`'s first answer, then `Query, median` and
  `Query, 95th`: the median and the 95th percentile of the time to answer one question's
  `search`, in milliseconds (see *Query time*, above). The row `hybrid` is the
  defaults' when the chunking is `windows`. The search mode's rule asks for 500 ms at
  most; this laptop's CPU took 266 ms there to rank.
- In its table of `ask`, Found@ask, Evidence@ask, the tokens of `ask`'s first answer and
  E/kT. The rows of `lexical` come with the first chunking alone, since words ignore the
  chunking.

At the end, the output says how many questions Section@10 reads, those whose expected
document every arm found; then the search mode's verdict for each model and chunking,
the chunking's for each model and the embedding model's for each chunking of two models
or more, each with its challengers' clauses (see *The default rules*, above); then the
questions skipped, if any, each with its ref. A verdict is the rule's on these
questions, not the setting.

Each challenger's p-value is multiplied by its rule's family, whatever the run
measured, so a run of two chunkings and the sandbox run of four give the same adjusted
p-value to the chunkings that both measure.

The results file keeps each run's times in seconds, `[median, 95th]` by mode under
`times` (and under `ask_times` for `ask`). This prints the 95th percentiles in
milliseconds:

```bash
uv run python -c 'import json, sys; [print(run["model"], run["chunking"], mode, round(times[1] * 1000), "ms") for run in json.load(open(sys.argv[1]))["indexes"] for mode, times in run["times"].items()]' <data>/eval/results/<time>.json
```

The search mode's rule tests each mode against the setting's alone, never the two
others against each other. The
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
indexes = json.load(open(sys.argv[1]))["indexes"]
ranks = next(run["ranks"] for run in indexes if run["chunking"] == "windows")
mrr = {
    mode: [max((1 / rank for rank in each if rank), default=0.0) for each in by_question.values()]
    for mode, by_question in ranks.items()
}
gains = [after - before for before, after in zip(mrr["hybrid"], mrr["semantic"])]
print(round(fmean(gains), 3), round(paired_test(mrr["hybrid"], mrr["semantic"]), 2))
print(sum(gain > 0 for gain in gains), sum(gain < 0 for gain in gains), gains.count(0))
EOF
```

`ask`'s measures, Found@ask and Evidence@ask, are kept question by question too, under
`asked_per`, by mode, so the same test runs on them: read
`run["asked_per"][mode][id]["evidence"]`, null for a question without evidence, which
leaves the test. A results file written before keeps them by group alone.

### Measuring reranking

The reranking depth's default rule says whether reranking is worth turning on on a
machine, and at which depth
([reranking](reranking.md#the-default-rule-fixed-before-the-run)); it is off by default.
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
minutes on a laptop's GPU; on a laptop's CPU with llama.cpp 0.6.0, depths 10, 20 and 30
took 50, 64 and 74 minutes, a run each, and depth 50 could not end. The output has a
table with a row per depth, `none` the order not reranked, the first ranking's Recall@N,
the questions whose reranking failed, by depth, if any, then the rule's verdict:
`Reranking depth, by the default rule: N, in place of none.` to turn reranking on at
depth N, `...: none stays.` to leave it off, or `...: no verdict, since ...`; then each
depth's clauses and each group's loss, and the depths not run. Its bound reads the times
of the machine that ran it: only a run on the machine that serves agents tells whether
to turn reranking on there.
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
3. The default rules are written already. For another decision, write its rule before
   the first run, as above.
4. Keep the golden file in `<data>/eval/`, never in a repository: it holds your
   company's content.
5. Run `eval` as in [comparing chunkings and modes](#comparing-chunkings-and-modes),
   on your golden file and without `--config`, so that the rules' controls are your
   settings; read the groups as well as the totals, Success@1 and Recall@10 beside
   MRR@10, and the query time in `Query, 95th` against the search mode's 500 ms; keep
   the results files to compare later runs.

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
- The records of plans 011 and 018, for every run's full tables, their decisions and
  their reviews.
