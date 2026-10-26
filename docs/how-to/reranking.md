# Rerank search with a local server

Reranking reorders the first documents that `search` and `ask` find: a cross-encoder
reads the question with each document and scores how well it answers, which ranks the
best answer first more often than words or meaning alone (the
[explanation](../explanation/reranking.md) says why and at what cost). The model never
runs in this program: it runs in llama.cpp's `llama-server`, a dependency of its own,
which you install and start, as you do Ollama or whichever OpenAI-compatible API serves
the embeddings, and which this program reaches on this machine alone, never elsewhere.

Reranking is on by default, by the user's choice: without the server, searches still
answer, in their own order, and say why; it can be turned off, and measured (below).

## Install llama.cpp

On macOS, Homebrew's build uses the GPU through Metal:

```bash
brew install llama.cpp
```

With nix-darwin and Home Manager, install it and keep the server running at login, the
model pinned by its SHA-256 (see below). In a module of Home Manager:

```nix
{ config, pkgs, ... }: let
  llama-cpp = pkgs.llama-cpp;
  reranker = pkgs.fetchurl {
    url = "https://huggingface.co/ggml-org/Qwen3-Reranker-0.6B-Q8_0-GGUF/resolve/a02f48bb4f057028298c21fa033da2b30d7742d5/qwen3-reranker-0.6b-q8_0.gguf";
    sha256 = "22c9979ce4fbcdc5acdc310c6641c32797eff1aa980b8f7a2db8a8ea23429a48";
  };
  log = "${config.home.homeDirectory}/Library/Logs/llama-reranker.log";
in {
  home.packages = [ llama-cpp ];
  launchd.agents.llama-reranker = {
    enable = true;
    config = {
      ProgramArguments = [
        "${llama-cpp}/bin/llama-server" "-m" "${reranker}" "--reranking"
        "--host" "127.0.0.1" "--port" "9931"
        "--alias" "qwen3-reranker-0.6b" "-c" "8192"
      ];
      RunAtLoad = true;
      KeepAlive = true;
      StandardOutPath = log;
      StandardErrorPath = log;
    };
  };
}
```

nixpkgs' `llama-cpp` was at 0.6.0 on 2026-10-25; it reranks, but more slowly
than 0.7.0, which skips the model's output layer when it only scores. For 0.7.0, add
llama.cpp's own flake at its tag, `github:ggml-org/llama.cpp/v0.7.0`, to your flake's
inputs and take its package `default` (Metal on Apple Silicon), or `vulkan` for an
integrated GPU on Linux.

## Fetch the model, pinned

Qwen3-Reranker-0.6B, 639 MB, at one revision, its SHA-256 checked:

```bash
curl -L --fail --create-dirs -o ~/.local/share/llama.cpp/qwen3-reranker-0.6b-q8_0.gguf https://huggingface.co/ggml-org/Qwen3-Reranker-0.6B-Q8_0-GGUF/resolve/a02f48bb4f057028298c21fa033da2b30d7742d5/qwen3-reranker-0.6b-q8_0.gguf
```

```bash
echo "22c9979ce4fbcdc5acdc310c6641c32797eff1aa980b8f7a2db8a8ea23429a48  $HOME/.local/share/llama.cpp/qwen3-reranker-0.6b-q8_0.gguf" | shasum -a 256 -c
```

## Start the server

In a terminal of its own, unless an agent of launchd or systemd runs it:

```bash
llama-server -m ~/.local/share/llama.cpp/qwen3-reranker-0.6b-q8_0.gguf --reranking --host 127.0.0.1 --port 9931 --alias qwen3-reranker-0.6b -c 8192
```

- `--reranking` serves `/v1/rerank`; without it, the server answers 501.
- `--host 127.0.0.1 --port 9931` is the address that the setting `rerank.url` takes by
  default; another address of this machine works, set there.
- `--alias` names the model as the setting `rerank.model` does by default; without it,
  the server lists the file's name, and the check below says so.
- `-c 8192` keeps the server's cache near 0.9 GiB, beside Ollama on a Mac that may have
  8 GB; at the model's own 40,960 tokens it would take 4.4 GiB.

## Check it

```bash
atlassian-offline-mcp reranker check
```

It scores a question against a passage that answers it and one that does not, then
times one request of `rerank.depth` texts as long as any that a search sends. With
nixpkgs' 0.6.0 on a laptop's CPU, it wrote:

```
qwen3-reranker-0.6b, at http://127.0.0.1:9931/v1: the answer scores 0.9997, an unrelated passage 0.0001
30 texts of 1502 characters: 148.6 s
slower than 5 s, the bound on a search: lower rerank.depth
```

The last line comes when the request takes over 5 seconds, the bound on a search; a
line also comes when the server lists another name than `rerank.model`. It exits 1,
saying what to run, when nothing answers, when the server is not a reranker, or when
the unrelated passage scores as high as the answer.

## On by default, and how to turn it off

Reranking is on by default, by the user's choice (`rerank.enabled`, true). The MCP
server reads the setting when it starts: restart your agent's server after a change.
Searches and asks rerank the `rerank.depth` documents, 30 by default, that follow those
that a query names by key or id, which stay first.

Without the server, nothing fails, as without Ollama a search by meaning answers by
words and says why. When llama-server is not running, the connection is refused at
once: a search or an ask answers in its own order, and its header ends with why:

```
Not reranked: no answer from the reranking server (ConnectError); is it running? With llama.cpp: llama-server -m <model> --reranking --port 9931.
```

For the next 30 seconds, searches do not ask the server again, and answer at once with
the same note. A server that is running but slow costs one search up to 30 seconds,
then the same 30 seconds without asking. A refusal of one request (400, 413, 422 or
500) is that request's: the next search asks again.

To turn it off, in the settings file:

```toml
[rerank]
enabled = false
```

Or `ATLASSIAN_OFFLINE_MCP_RERANK__ENABLED=false` in the server's environment, or
`--no-rerank` on the command that starts the server, which wins over both:

```bash
atlassian-offline-mcp serve --no-rerank
```

Off, the server never connects to the reranking server, and says when it starts that
`rerank.url`, `rerank.model` or `rerank.depth`, if set, are not applied.

`rerank.url` takes an address of this machine alone: any other is refused, and no flag
allows one, so that the mirror's text stays here.

## Measure it

Plan 022 fixed a bar before any run: reranking at a depth is worth it if it
significantly improves the first answer (MRR@10), loses little on questions that name
things, and keeps a search within 5 seconds at the 95th percentile on the machine that
serves agents. The [explanation](../explanation/reranking.md#the-bar-fixed-before-the-run)
gives the bar in full, and
[evaluating search](../explanation/search-evaluation.md#the-measures-on-one-worked-example)
what each measure means. Two measures, of different cost, tell how reranking does on
your machine and your questions.

Both need [golden questions](golden-questions.md), the index built, Ollama serving the
embedding model and the reranking server running. Check both servers first; each check
says what to run when one does not answer:

```bash
atlassian-offline-mcp model check
```

```bash
atlassian-offline-mcp reranker check
```

Each measure is then one command, which asks before it runs (`--yes` runs it at once,
as a script does). It measures the settings' model, chunking and search mode, first
not reranked, then reranked, and stops with exit 1, saying why, when a server does not
answer or a search falls back, since a search not reranked would measure something
else; a golden file or a sample refused exits 2. It writes a table to stdout and its
results, ids and numbers only, never a question's text, to
`<data>/eval/results/<UTC time>-rerank.json`: keep them to compare later runs. With
`--format json`, the same comes as one JSON document, whose `decision.depth` is the
bar's depth, or null when none qualifies.

### Short: one depth, on a sample

After changing the model, the server, its version or `rerank.depth`, to see whether
reranking still helps and how long it takes here:

```bash
atlassian-offline-mcp eval-rerank ~/atlassian-offline-mcp/eval/golden.yaml --depth 30 --sample 20
```

It asks 20 questions, chosen by a fixed seed (`--seed` chooses another sample): each
once in the order not reranked, then reranked at depth 30, 600 texts scored in all.
One to two minutes on the user's machine by the estimate in the
[explanation](../explanation/reranking.md#why-only-the-first-documents); on a laptop's
CPU with llama.cpp 0.6.0, about 12 minutes, at 36 seconds a search.

In its table, compare the row of depth 30 with the row `none`, group `all`, and with
`--summary detailed` each group:

- `Search, 95th`: within 5,000 ms, the bar's bound, on the machine that serves agents.
  Past 30,000 ms, searches would give up on the server and answer in their own order:
  lower `rerank.depth`, or turn reranking off.
- `MRR@10` and `Success@1`: reranking should raise them. On 20 questions, a difference
  smaller than about 0.12 may be chance either way; a larger fall is the sign to run
  the long measure.
- The rows of the groups `identifier` and `keyword`: a loss past 0.05 of MRR@10 is what
  the bar refuses.
- The line `Recall of the order not reranked`: at `@30`, the share of the expected
  documents within the first 30 found, the most that reranking 30 can bring into the
  first ten.

It ends `No verdict: the bar decides on depths 10, 20, 30, 50 alone.`: only the long
measure applies the bar.

### Long: four depths, and the bar's verdict

To decide, on this machine, whether reranking stays on, and at which depth:

```bash
atlassian-offline-mcp eval-rerank ~/atlassian-offline-mcp/eval/golden.yaml
```

Every question, not reranked, then reranked at depths 10, 20, 30 and 50, 110 texts
scored for each question: 20 to 35 minutes for 105 questions on the user's machine by the
estimate. On a laptop's CPU with llama.cpp 0.6.0, each depth took about an hour, and
depth 50 could not end, one request passing the run's deadline of 300 seconds: the
long measure is for the machine that serves agents.

Under the table, a line for each depth gives each clause of the bar:

```
Depth <N>: MRR@10 adjusted p = <p>; gains <yes or no>; groups lose identifier <loss>, keyword <loss>, hold <yes or no>; within 5 s here <yes or no>
```

`gains` is clause 1, the MRR@10 higher with a Holm-adjusted p below 0.05; `hold`,
clause 2, each group losing 0.05 at most; `within 5 s here`, clause 3, by this
machine's times. Then, for the depths that qualify, each one's p-value against the
best, and the last line, which says what to do:

- `By the bar, with this machine's times: rerank N documents.`: set `rerank.depth` to
  N, and keep reranking on.
- `By the bar, with this machine's times: turn reranking off.`: no depth qualifies;
  set `enabled = false`, unless you keep it on knowing that the bar was not met.

The verdict holds for the model, the server's version, the golden questions and the
machine it was measured with: measure again when one of them changes.

## Change the model

Nothing that this program stores depends on the reranker, so no index is rebuilt: start
`llama-server` with another file and its alias, set `rerank.model`, and measure again,
short then long, since the bar's verdict belongs to a model.

Any server that answers llama.cpp's rerank request at `/v1/rerank`, on this machine,
should work; only `llama-server` is tested. Text Embeddings Inference answers another
shape, and is not supported.
