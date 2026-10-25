# Rerank search with a local server

Reranking reorders the first documents that `search` and `ask` find: a cross-encoder
reads the question with each document and scores how well it answers, which ranks the
best answer first more often than words or meaning alone (the
[explanation](../explanation/reranking.md) says why and at what cost). The model never
runs in this program: it runs in llama.cpp's `llama-server`, a dependency of its own,
which you install and start, as you do Ollama or whichever OpenAI-compatible API serves
the embeddings, and which this program reaches on this machine alone, never elsewhere.

Reranking is off by default until its measure on the user's machine says otherwise (below).

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

## Turn it on

In the settings file:

```toml
[rerank]
enabled = true
depth = 30
```

Or for one run, `ATLASSIAN_OFFLINE_MCP_RERANK__ENABLED=true`. The MCP server reads it
when it starts: restart your agent's server. Searches and asks then rerank the `depth`
documents that follow those that a query names by key or id, which stay first. When the
server fails, a search keeps its order and its answer says why ("Not reranked: ...");
when the server itself failed, searches do not ask it again for 30 seconds.

`rerank.url` takes an address of this machine alone: any other is refused, and no flag
allows one, so that the mirror's text stays here.

## Measure it

Plan 022 fixed a bar before any run: reranking turns on by default, at the depth it
gives, only if it significantly improves the first answer (MRR@10), loses little on
questions that name things, and keeps a search within 5 seconds at the 95th percentile
on the user's machine. The [explanation](../explanation/reranking.md) gives the bar in full.

With [golden questions](golden-questions.md), Ollama serving the embeddings and the
reranking server running:

```bash
atlassian-offline-mcp eval-rerank ~/atlassian-offline-mcp/eval/golden.yaml
```

It measures the setting's model, chunking and search mode, first not reranked, then
reranked at depths 10, 20, 30 and 50, and writes a table, the bar's verdict on each
depth and the results file (`<data>/eval/results/<time>-rerank.json`, numbers and ids
only). `--depth`, repeated, measures other depths, on which the bar gives no verdict.
The times are this machine's, so the run that decides is made on the machine that
serves agents. [Evaluating search](../explanation/search-evaluation.md#measuring-reranking)
gives the sandbox's run, the one that sets the defaults.

## Change the model

Nothing that this program stores depends on the reranker, so no index is rebuilt: start
`llama-server` with another file and its alias, set `rerank.model`, and run
`eval-rerank` again, since the bar's verdict belongs to a model.

Any server that answers llama.cpp's rerank request at `/v1/rerank`, on this machine,
should work; only `llama-server` is tested. Text Embeddings Inference answers another
shape, and is not supported.
