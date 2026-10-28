# Local models

Why [serving the mirror to a local model](../how-to/local-model.md) takes Qwen3.5 9B on
a laptop of modest memory, and how to choose another: what the model must do, what fits in
memory, what makes it fast or slow, and what the published measures say. The model
runs in Ollama or any other OpenAI-compatible server, never in this program. As for the
embedding model, the choice rests on published sources, model cards and independent
leaderboards; nothing here was measured on this project's questions.

## What the model must do

An agent over the mirror reads a question, calls `ask`, reads the passages, perhaps
calls `read` on a section, then answers, citing refs. So the model must:

- **call tools reliably**, over several turns, with arguments that the server accepts;
- **follow instructions**, the server's among them: never act on directions found in the
  mirror's text, which the server marks as untrusted;
- **answer from the passages**, not from memory. A small model knows little: on
  Artificial Analysis's questions of knowledge (AA-Omniscience), Qwen3.5 9B answered
  14.7% right, and among the questions it did not answer right, it answered wrongly
  rather than declining 82% of the time. Its value here is to read and quote, which the
  server's answers make possible;
- **hold the conversation**: each tool's answer is up to 4,000 estimated tokens by
  default, the server's instructions and tools up to 2,300, and the host adds its own.
  One `ask` and two `read` calls put about 12,000 tokens of the mirror in the context,
  hence 32,768 tokens for a host with short instructions, 65,536 for Codex or Claude
  Code.

## What fits in memory

A laptop with unified memory, as Apple silicon has, gives its GPU a share of the memory
rather than memory of its own. On macOS that share is not documented by Apple; users
measure about two thirds of the memory on machines of up to 32 GB, three quarters on
larger ones. `sudo sysctl iogpu.wired_limit_mb=<MB>` raises it
until the next restart, taking the memory from everything else that runs. A machine
with a GPU of its own has that GPU's memory instead.

Four things share it: the model's weights, the cache of its context, the embedding
model, and working buffers.

### The weights

The weights take the number of parameters times the bits kept for each. Qwen3.5 9B has
9.65 billion; at 16 bits, 19.3 GB, which no laptop of this size holds. Quantisation keeps
fewer bits a weight: `Q4_K_M`, the usual compromise, keeps most at 4 bits and some at
more, 4.7 on average for this model, so 9.65 × 4.7 / 8 ≈ 5.7 GB, which is the size of
its GGUF file. Ollama's download of it is 6.6 GB.

### The cache of the context

To write each token, a model attends to every token before it. It keeps a key and a
value for each, in each layer of attention, so as not to compute them again: the KV
cache, which grows with the context. Per token, a layer of attention keeps 2 (a key and
a value) × its KV heads × the size of a head × 2 bytes at 16 bits.

Qwen3.5 9B has 32 layers, of which only 8 attend to the whole context, with 4 KV heads
of 256 each. The other 24 are linear attention (Gated DeltaNet), whose state keeps the
same size however long the context. So:

```text
2 × 4 × 256 × 2 bytes × 8 layers = 32 KiB a token
32 KiB × 32,768 tokens = 1 GiB
```

Qwen3 8B, of the generation before, attends to the whole context in all 36 of its
layers, with 8 KV heads of 128: 144 KiB a token, 4.5 GiB at 32,768 tokens, almost as
much as its weights. Models built that way, as most dense models of about 8 billion
parameters are, spend on the context that the tools' answers need the memory that a
better model would have used. A cache kept at 8 bits (`q8_0`) halves it, at a small
cost in precision.

### The budget

For Qwen3.5 9B through Ollama, with Codex or Claude Code:

| Part | Memory |
|---|---|
| The weights, as Ollama downloads them | 6.6 GB |
| The cache, 65,536 tokens at 8 bits | 1.1 GB |
| The embedding model, `qwen3-embedding:0.6b` | 0.6 GB, and a cache of its own |
| Working buffers, an estimate | 0.5 to 1 GB |
| In all | about 9 GB, of 10.7 |

Through LM Studio or llama.cpp at 32,768 tokens: 5.7 GB of weights, 1 GB of cache at
16 bits, the embedding model, about 8 GB. Either leaves the rest of the memory to the
system, a browser and an editor.

gpt-oss-20b shows why the GPU's share is the limit, not the memory: Ollama says that it
runs "on systems with as little as 16GB memory", and its download is 14 GB. That is
more than the GPU's 10.7; raising the limit leaves about 3 GB to everything else,
including the context.

## What makes it fast or slow

A model answers in two phases.

**Reading**, the prompt and every tool's answer, is limited by computation: the GPU
processes many tokens at once. llama.cpp's table of Apple chips gives about 190 tokens
a second for a 7B model at 4 bits on the chips whose memory moves 100 GB a second; for
a 9.65B model, about 7/9.65 of that, 135. A tool's answer of 4,000 tokens then takes about half a
minute to read, before the model writes a word. On a laptop, reading dominates: an
agent that reads three answers spends a minute and a half reading. Hence `ask`, which
gives the evidence in one answer; fewer tools, whose descriptions are read at every
turn; and a host with short instructions. A server of models keeps what it has read in
its cache and reads only what was added; llama.cpp has reports of hybrid models such
as Qwen3.5 reading a conversation again that it had cached.

**Writing** is limited by the memory's bandwidth: each token written reads every active
weight once. So tokens a second can be at most the bandwidth over the bytes read per
token. For a laptop whose memory moves 100 GB a second and the 5.7 GB of Qwen3.5 9B,
at most 100 / 5.7 ≈ 17.5; llama.cpp's table shows about 80% of such a ceiling in
practice, so about 14 tokens a second. The 4B writes about twice as fast.

A mixture of experts (MoE) activates only some of its weights for each token:
gpt-oss-20b reads 3.6 of its 21 billion, so it writes fast for its size. But all its
weights must sit in memory, which is why such models suit machines of 24 GB and more.

## Thinking

Qwen3.5 thinks before it answers, by default: it writes a reasoning that the host
hides, then the answer. Those tokens are written at the speed above: 500 tokens of
thought at 14 tokens a second is 36 seconds, for each turn of the agent. Artificial
Analysis measured the thinking variants; without thinking, scores may be lower. For a
question that the passages answer directly, thinking adds time more than accuracy; for
one that compares documents or reasons across them, it may be worth the wait. The model
card names the switch, `enable_thinking`; each host exposes it in its own way, or not at
all.

## What the published measures say

The measures that bear on an agent over a search engine:

- **BFCL**, the Berkeley Function Calling Leaderboard: given functions' descriptions
  and a request, does the model call the right one with the right arguments, in single
  calls, parallel calls and conversations of several turns, and decline when none fits.
  Version 4 adds agentic tasks.
- **τ²-bench**: an agent, with tools and a policy to follow, serves a simulated user,
  both acting on a shared state; in its telecom domain the user changes the settings of
  a phone as the agent asks. A task passes when the final state is right.
- **IFBench**: whether the output keeps constraints that can be checked, such as a
  number of paragraphs or a word to avoid, of kinds not seen in training.
- **The Artificial Analysis Intelligence Index**: one score from evaluations that
  Artificial Analysis runs itself, version 4.3.2 at the time of writing.

A vendor's own figures come from its card, on its own harness; an independent
leaderboard runs every model the same way. BFCL's own leaderboard lists none of the
2026 models below, so its figures here are the vendors'. The τ²-bench Telecom figures
are those that benchmarklist.com attributes to Artificial Analysis, dated 2026-06-10,
whose own pages no longer show them.

| Model | Ollama's download | BFCL-V4, vendor | τ²-bench, vendor | τ²-bench Telecom, independent | IFBench, vendor |
|---|---|---|---|---|---|
| Qwen3.5 9B | 6.6 GB | 66.1 | 79.1 | 86.8% | 64.5 |
| Qwen3.5 4B | 3.3 GB | 50.3 | 79.9 | 92.1% | 59.2 |
| Gemma 4 12B | 7.7 GB | none | - | 36.3% | - |
| gpt-oss-20b | 14 GB | - | - | 60.2% | - |

Artificial Analysis gives Qwen3.5 9B an index of 11, against a median of 8 for models
of its size, and called it, at its release in March 2026, the most intelligent model
under 10 billion parameters.

What the measures do not show: how a model does with this server's tools, on this
mirror's questions, in a given host. τ²-bench's telecom tasks and the server's are both
conversations with tools, which is why it weighs most here; the 4B's score above the 9B
on it, and below on BFCL and IFBench, says that no single measure settles the order.

## The choice

**Qwen3.5 9B by default.** Of the models that fit, it calls tools best by every measure
found, follows instructions best, and keeps a cache small enough to leave room for
65,536 tokens. Apache 2.0, and Ollama marks it as calling tools. What it costs: about 14
tokens a second written and half a minute for each 4,000 tokens read, so an answer that
takes two tool calls takes one to two minutes.

**Qwen3.5 4B when speed matters more**: half the memory, twice the speed, as good on
τ²-bench, weaker on BFCL and IFBench.

Not chosen:

- **Gemma 4 12B** fits, 7.7 GB, Apache 2.0, with native function calling, but scores
  36.3% on τ²-bench Telecom, against 86.8%, and its weights take a gigabyte more.
- **gpt-oss-20b** does not fit the GPU's share, as above, and scores lower.
- **Dense 8B models that attend to the whole context in every layer**, such as Ministral
  3 8B and Granite 4.2 8B: by their published configurations, 4 to 5 GiB of cache at
  32,768 tokens.
- **LFM2.5 8B A1B** writes very fast, 1.5 of its 8.3 billion parameters active, but
  under a licence of its own, LFM 1.0, rather than Apache 2.0.
- **Models of 26 billion parameters and more**, Gemma 4 26B, Qwen3.5 27B and Qwen3.6
  35B A3B among them, take 16 GB or more at 4 bits.

## With more memory or less

- **24 GB**, about 16 GB for the GPU: Qwen3.5 9B at 8 bits (`Q8_0`, 9.5 GB), closer to
  the full model, with 65,536 tokens of cache at 16 bits; or gpt-oss-20b, faster to
  write, with a shorter context.
- **32 GB and more**: models of 27 to 35 billion parameters at 3 or 4 bits. Qwen3.6 35B
  A3B activates 3 billion of them a token, so writes fast; Qwen3.8 27B, dense, tops
  Artificial Analysis's list of small open models, at 34 with its most thinking.
- **8 GB**, about 5.3 GB for the GPU: Qwen3.5 4B, with a short context, and
  `search_mode = "lexical"` to free the embedding model's memory.

## Sources

Checked on 2026-10-28:

- Qwen3.5 9B: [its card](https://huggingface.co/Qwen/Qwen3.5-9B), architecture,
  thinking and the vendor's measures; [GGUF sizes](https://huggingface.co/unsloth/Qwen3.5-9B-GGUF);
  Artificial Analysis's [page](https://artificialanalysis.ai/models/qwen3-5-9b) and
  [article of 2026-03-05](https://artificialanalysis.ai/articles/qwen3-5-small-models),
  AA-Omniscience included.
- Other models: Artificial Analysis's [small open models](https://artificialanalysis.ai/models/open-source/small);
  Ollama's [qwen3.5](https://ollama.com/library/qwen3.5),
  [gemma4](https://ollama.com/library/gemma4) and
  [gpt-oss](https://ollama.com/library/gpt-oss); [Gemma 4 12B](https://huggingface.co/google/gemma-4-12B-it);
  [Granite 4.2 8B](https://huggingface.co/ibm-granite/granite-4.2-8b);
  [Ministral 3 8B](https://huggingface.co/mistralai/Ministral-3-8B-Instruct-2512);
  [LFM2.5 8B A1B](https://huggingface.co/LiquidAI/LFM2.5-8B-A1B).
- Measures: [BFCL](https://gorilla.cs.berkeley.edu/leaderboard.html);
  [τ²-bench at Artificial Analysis](https://artificialanalysis.ai/evaluations/tau2-bench);
  benchmarklist.com's pages of
  [Qwen3.5 9B](https://benchmarklist.com/models/qwen-qwen3.5-9b/),
  [Qwen3.5 4B](https://benchmarklist.com/models/qwen-qwen3.5-4b/),
  [Gemma 4 12B](https://benchmarklist.com/models/google-gemma-4-12b-it/) and
  [gpt-oss-20b](https://benchmarklist.com/models/openai-gpt-oss-20b/).
- Speed: llama.cpp's [table of Apple chips](https://github.com/ggml-org/llama.cpp/discussions/4167);
  its reports of hybrid models read again,
  [24714](https://github.com/ggml-org/llama.cpp/issues/24714) and
  [23013](https://github.com/ggml-org/llama.cpp/issues/23013).
- The GPU's share of memory on macOS, as users measured it:
  [runaihome, 2026-08-10](https://runaihome.com/blog/mps-backend-out-of-memory-fix-mac-2026/),
  [smeltcore, 2026-06-25](https://smeltcore.com/recipes/gpt-oss-20b-m2-pro/).
