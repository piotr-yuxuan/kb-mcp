# Golden questions

To check which search mode, model and chunking fit your own content, write golden
questions and measure them with `eval`. Keep them in `<data>/eval/`, which stays on this
machine: a YAML list where each question has an `id`, the `question`, the `expected`
refs that answer it (page ids, issue keys, or mirror paths, as `read` takes them), and
optionally `partial` refs that help, `groups` to break the measures down, and
`evidence`, a phrase of each expected document's text. Quote page ids, which YAML would
read as numbers:

```yaml
- id: q1
  question: How do I roll back a release of the payments service?
  expected: ["196845", PAY-142]
  partial: ["197012"]
  groups: [paraphrase, en]
  evidence: {"196845": "Pause, drain, then roll back."}
```

Then run:

```bash
kb-mcp eval ~/kb-mcp/eval/golden.yaml
```

It builds an index per model and chunking under `<data>/eval/indexes/`, embedding only
what `<data>/vectors.sqlite` lacks, and measures every mode on each:

- `search` as an agent's first call gets it: Recall@10, MRR@10, nDCG@10, Success@1,
  Section@10 (the share of expected documents found whose shown section holds the
  evidence, over the questions whose expected document every index and mode found), and
  the tokens of its first answer as the server writes it;
- `ask`'s first answer: Found@ask, the share of the expected documents among its
  passages; Evidence@ask, the share whose evidence their passage holds; the tokens of
  the answer; and E/kT, the evidence held per thousand of them;
- each index's costs: its chunks, the characters of the texts that it embeds and their
  tokens at four characters each, the texts embedded in this run, the seconds it took,
  the tokens that the endpoint reported, its bytes, and the times of `search` and
  `ask`.

In the table of `search`, `Query, median` and `Query, 95th` give each mode's time to
answer one question's `search` as the server does, in milliseconds. [Evaluating
search](../explanation/search-evaluation.md#reading-mrr10-with-success1-and-recall10)
says how to read MRR@10 beside Success@1 and Recall@10, and [comparing chunkings and
modes](../explanation/search-evaluation.md#comparing-chunkings-and-modes) how to compare
runs.

Lexical search ignores the model and the chunking, so its rows come once. The output
then says how many questions Section@10 reads, and gives the default rules' verdicts,
each in a line with its challengers' clauses below it
([the default rules](../explanation/search-evaluation.md#the-default-rules)):

- the search mode's, for each model and chunking: another mode replaces the setting
  `search_mode` when it beats it on MRR@10 with a p-value below 0.05 once multiplied by
  two, the other modes, loses at most 0.05 of MRR@10 on `identifier` and on `keyword`,
  and answers within 500 ms at the 95th percentile;
- the chunking's, for each model, in hybrid mode: another chunking replaces the setting
  `chunking` when it beats it on Evidence@ask with a p-value below 0.05 once multiplied
  by three, the other chunkings, loses at most 0.02 of MRR@10 over all the questions and
  0.05 on `identifier`, `keyword` and `paraphrase`, and embeds at most three times its
  tokens;
- the embedding model's, for each chunking over which `--model` names two models or
  more: another model, in its best mode by meaning, replaces the setting `model`, in the
  setting's mode when that mode reads a model, else in its best mode by meaning, when it
  loses at most 0.03 of MRR@10 over all the questions and 0.05 on `identifier`,
  `keyword` and `paraphrase`, and searches faster at the 95th percentile, both timed in
  the setting's model's mode; it need not rank better.

Of the challengers that qualify, those within 0.01 of the best are as good, and the
cheapest is kept: words, then meaning, then hybrid search for the mode, the chunking
that embeds the fewest tokens, and the model that searches fastest. A verdict is the
rule's on your questions, and changes no setting. It says `no verdict, since` and why
when the run did not measure the setting's value, as `--chunking` without the setting's
chunking does, or any challenger, or when no question has the evidence that Evidence@ask
reads.

A question whose expected ref names no document of the index is skipped, and the output
names each, then what to do:

```
Skipped q7, for 'PAY-999': an expected ref that names no document of the index.
An index older than the mirror misses documents; kb-mcp index brings it up to date.
```

A helping ref that names no document is dropped, and two refs of one document count
once. Only a golden file of which no question is left is refused, exit 2. The numbers go
to `<data>/eval/results/`: each question's measures and the refs of the documents that
its answers showed, by its id, never its text ([evaluation
results](../reference/data-layout.md#evaluation-results)); look them over before
sharing them.

`--model` names models to measure, the setting's by default, all served by the
endpoint; `--chunking` names chunkings, every one by default:

```bash
kb-mcp eval ~/kb-mcp/eval/golden.yaml --chunking sections --chunking windows
```

`--detail detailed` gives every group. [Evaluating
search](../explanation/search-evaluation.md) explains each measure, the tests, the
default rules and how the defaults were chosen; [chunking](../explanation/chunking.md),
the chunkings and how they compared. To measure whether `ask` helps agents, see
[evaluating with agents](evaluate-with-agents.md).
