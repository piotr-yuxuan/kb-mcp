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

- `search` as an agent's first call gets it: Recall@10, MRR@10, nDCG@10, Success@1 and
  Section@10 (the share of expected documents found whose shown section holds the
  evidence), with the paired tests of each mode against words;
- `ask`'s first answer: Found@ask, the share of the expected documents among its
  passages, and Evidence@ask, the share whose evidence their passage holds. Its budget
  is fixed, so this is evidence per token handed over;
- each index's costs: its chunks, the characters of the texts that it embeds and their
  tokens at four characters each, the texts embedded in this run, the seconds it took,
  the tokens that the endpoint reported, its bytes, and the times of `search` and
  `ask`.

In the table of `search`, `Query, median` and `Query, 95th` give each mode's time to
rank one question, in milliseconds; plan 018's bar asked 200 ms at most of the 95th
percentile. [Evaluating
search](../explanation/search-evaluation.md#comparing-chunkings-and-modes) says how to
read them and compare runs.

Lexical search ignores the model and the chunking, so its rows come once. By plan 019's
rule, the output then names each model's default chunking: in hybrid mode, a challenger
replaces `sections` when it beats it on Evidence@ask with an adjusted p-value below
0.05 (Holm, over every challenger's tests on MRR@10 and Evidence@ask), loses at most
0.02 of MRR@10, and costs at most three times its tokens; the best Evidence@ask wins,
within 0.01 the cheapest. That line is the rule's verdict on your questions, not the
setting: `chunking` defaults to `windows`, chosen knowing that the rule kept `sections`
on the sandbox. The numbers, never the questions, go to `<data>/eval/results/`.

`--model` names models to measure, the setting's by default, all served by the
endpoint; `--chunking` names chunkings, every one by default:

```bash
kb-mcp eval ~/kb-mcp/eval/golden.yaml --chunking sections --chunking windows
```

`--summary detailed` gives every group and every test. [Evaluating
search](../explanation/search-evaluation.md) explains each measure of `search`, the
tests, and how the defaults were chosen; [chunking](../explanation/chunking.md), the
chunkings and how they compared. To measure whether `ask` helps agents, see
[evaluating with agents](evaluate-with-agents.md).
