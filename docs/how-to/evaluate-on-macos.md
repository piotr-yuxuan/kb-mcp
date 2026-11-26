# Evaluate search on a Mac in one click

`scripts/evaluate.command`, opened from Finder, runs every evaluation of search on your
own golden questions, one after another, in the order of the default rules: the search
mode, the chunking, the reranking depth, then the embedding model. It readies what they
need, Ollama and the models before the steps, a reranking server before the reranking;
shows each run's progress and running results; says in a few lines what each found;
and packs the logs, the
results and the analyses into one archive in `~/Downloads`, to keep or to share. It
runs on macOS alone; elsewhere, run `eval` and `eval-rerank` as
[golden questions](golden-questions.md) and [reranking](reranking.md#measure-it) say.

## What it needs

- **uv**, which runs the script and gives it its one dependency, Rich, for the colours
  and the tables.
- **kb-mcp 0.1.14 or later**, on the `PATH` of a login shell, installed from your
  checkout with `uv tool install`. An older one is refused, saying how to upgrade.
- **The golden file** at `<data>/eval/golden.yaml`, `<data>` being the setting
  `data_dir`, written as [golden questions](golden-questions.md) says.
- **Ollama**, the app and its `ollama` command: kb-mcp asks any OpenAI-compatible API for
  its embeddings, and this script readies Ollama, the default, opening it when the
  setting `embedding_url` does not answer and pulling each model that it lacks.
- **llama-server**, only if no reranking server answers at the setting `rerank.url`:
  `brew install llama.cpp`, as [reranking](reranking.md#install-llamacpp) says. The
  script downloads the model if missing, at its pinned revision, checked by its SHA-256.

`caffeinate`, `curl`, `less`, `open` and `uname` come with macOS. The script reads the
settings as kb-mcp resolves them, by `kb-mcp check --format json`, never assuming the
defaults: the data directory, the embedding model and its address, the search mode, the
chunking, and the reranking server's address.

## Run it

In Finder, open the checkout's `scripts` folder and double-click `evaluate.command`.
Terminal opens and runs it; when it ends, the window waits for a key before it closes,
so that you can read what it said. From a terminal, the same, with the options below:

```bash
scripts/evaluate.command --chunking windows --chunking small-to-big
```

It takes as long as its steps do: minutes on a Mac's GPU for a hundred questions once
the vectors are kept, but hours for a chunking or a model whose vectors the vector
cache lacks, since its first run embeds the whole mirror. The Mac stays awake while a
step runs.

## The steps

Before the steps, it checks the system and kb-mcp's version, reads the settings, finds
the golden file, makes Ollama answer and pulls the models, each check a green, yellow or
red line, and logs the outputs of `kb-mcp doctor --detail detailed` and
`kb-mcp model check`. Then, each step logged, the next one run after a failure:

1. **search-mode**: `eval` of the setting's model and chunking, every mode measured; the
   search mode's default rule weighs them against the setting `search_mode`.
2. **chunking**: `eval` of `sections` and `windows`, or of the chunkings that
   `--chunking` names; the chunking's default rule weighs them against the setting
   `chunking`, which must be among them for a verdict.
3. **reranking**: `eval-rerank` at depths 10, 20, 30 and 50, whose default rule weighs
   them against the order not reranked. A reranking server that answers is left alone;
   else the script starts llama-server at the setting's address with the pinned model,
   waits for it, and stops it once the step ends, however it ends. Ollama stays
   running. The step is skipped, saying why, when llama-server is missing, the model
   cannot be downloaded, the server does not answer in time, or `kb-mcp reranker check`
   fails.
4. **embedding-model**: `eval` of the setting's model and of `embeddinggemma:300m`, or
   of the models that `--compare` names, over the setting's chunking. No rule decides
   the model: published benchmarks choose it, as
   [evaluating search](../explanation/search-evaluation.md#choosing-a-model-from-published-results)
   says, and the step reports their measures side by side.

`eval-agents` is not run: it needs agents' runs, which call a model.

## What it shows

On a terminal, each step begins with a rule, `Step 2 of 4: chunking`, then its command
and how long the same step took last time, read from the last archive. The commands'
own progress bars follow, each question named with the running results of those done,
such as `hybrid q12: MRR@10 0.712, Evidence@ask 0.455`. Once a step ends, its analysis,
read from the results file that it wrote:

- each default rule's verdict, in a sentence;
- for each arm, MRR@10 by group, each read on the ladder of
  [reading MRR@10](../explanation/search-evaluation.md#reading-mrr10-with-success1-and-recall10):
  excellent from 0.85, good from 0.70, fair from 0.50, poor from 0.30, failing below;
- where the first expected document lands: at rank 1, 2 to 3, 4 to 10, or missed;
- for `eval`'s arms, the tokens of `search`'s and `ask`'s answers and E/kT, and the
  share of the questions that a reader of the hits answers within 2,000, 4,000 and 8,000
  tokens, with the median, a question never answered counting as beyond any budget. The
  reader reads `search`'s first answer, then, unless a snippet holds the evidence, the
  section of each hit in turn until one does;
- the questions skipped, each with its ref;
- against the last results of the same command on the same golden file, the change of
  each arm's MRR@10 and Evidence@ask, with the reminder that differences under 0.07 are
  noise at 100 questions.

At the end, a table of the steps, with each one's status, minutes and verdict, then the
archive's path. Enter then opens the measures' tables in `less -RS`, which scrolls both
ways with the arrows and leaves on `q`: a table per step, an arm a row, with MRR@10,
Recall@10, Success@1, Evidence@ask, E/kT, the tokens of `search` and `ask` and a
search's 95th percentile, the best of each column in bold and the control's row marked.
In a pipe, or with `NO_COLOR` set, it writes plain text, the commands' output as logged,
and the tables at the end, without a pager.

## Options

| Option | Default | What it changes |
|---|---|---|
| `--ollama-wait SECONDS` | 60 | how long Ollama may take to answer once opened |
| `--reranker-wait SECONDS` | 120 | how long llama-server may take to answer once started |
| `--chunking NAME` | `sections` and `windows` | a chunking that the chunking step measures, once for each; others' first run embeds the whole mirror anew, for hours |
| `--compare MODEL` | `embeddinggemma:300m` | a model that the last step measures beside the setting's, once for each, pulled if Ollama lacks it |

A pull and the download may take 30 minutes each; a download stopped short is resumed
by the next run.

## Logs and the archive

Each run has a stamp, its start in UTC, such as `20261126T093000Z`. Its logs go to
`<data>/eval/logs/`, outside the checkout, without escape codes: `<stamp>-readiness.log`,
the version and the outputs of `doctor` and `model check`; `<stamp>-<step>.log`, each
step's output; and, when the reranking ran, `<stamp>-reranker-check.log` and
`<stamp>-llama-server.log`, the server's own, when the script started it. The results
files are those that `eval` and `eval-rerank` write under `<data>/eval/results/`, which
[evaluation results](../reference/data-layout.md#evaluation-results) lists.

The archive is `~/Downloads/kb-mcp evals <stamp>.zip`:

| Path | What it holds |
|---|---|
| `manifest.json` | the stamp; the versions of kb-mcp, macOS, Python, Ollama and llama-server; the settings read; each step's status, seconds, verdict and results file |
| `logs/` | the run's logs |
| `results/` | each step's results file |
| `analyses/<step>.txt` | each step's analysis, as it was shown |
| `analyses/summary.txt` | the steps' table and the measures' tables, without colour |

It never holds the golden file, nor a question's text.

## When it stops

| Exit status | When |
|---|---|
| 0 | every step that ran succeeded; a step skipped is no failure |
| 1 | a step failed: its command exited non-zero or wrote no results; the others ran |
| 2 | it refused to begin, saying what to do: not macOS; kb-mcp missing or older than 0.1.14; `kb-mcp check` gave no settings; no golden file at `<data>/eval/golden.yaml`; or Ollama silent past `--ollama-wait` |
| 128 plus the signal | Control-C, closing the window, or a `TERM`: a llama-server that it started is stopped, and no archive is made |

To upgrade an older kb-mcp, as the refusal says: in kb-mcp's checkout, `git pull`, then
`uv tool install --force .`, then the script again.

## Before you share the archive

Look it over first. The readiness log holds what `doctor` says, which may name your
site and your sources; the manifest names your data directory, whose path may hold your
login name; the results hold the refs of the documents that the answers showed, page ids
and issue keys, and your golden file's ids and group names. None holds a question's text
or a document's content, but the refs and the names are yours: remove what you would not
send.
