# Serve the mirror to a local model

How to have a language model that runs on this machine, offline, answer from the
mirror. Two programs work together: a server of models runs the model, Ollama or any
other OpenAI-compatible server; an MCP host, the application you talk to, starts
`atlassian-offline-mcp` and gives its tools to the model. Neither your questions nor the
mirror's text then leave the machine. Why the model below, what it costs, and what to
choose with more memory or less, is in [local models](../explanation/local-models.md).

## Before you start

- The command is installed, and the mirror and its index are built, as [coding
  agents](agents.md#before-you-start) says.
- The machine has 16 GB of memory or more, and 8 GB of disk free for the model.
- With the default `search_mode`, every search embeds its question through the model of
  [embeddings](embeddings.md), which then stays in memory beside the language model:
  about 0.6 GB more. `search_mode = "lexical"` frees it, at the cost of search by
  meaning.

## 1. Choose the model

| Model | Ollama's name | Download | When |
|---|---|---|---|
| Qwen3.5 9B | `qwen3.5:9b` | 6.6 GB | the default: the best caller of tools that fits |
| Qwen3.5 4B | `qwen3.5:4b` | 3.3 GB | twice as fast, for short lookups |

Both are Apache 2.0, call tools natively, and read up to 262,144 tokens. For a machine
with more memory or less, [the
explanation](../explanation/local-models.md#with-more-memory-or-less) names others.

## 2. Choose the tools to serve

A small model chooses better among fewer tools, and reads fewer tokens before it
answers. `ask` gives the passages that answer a question in one call, and `read` opens a
section that a passage cites, so serve those two, as `atlassian-offline-mcp serve
--tools ask,read`. Add `search` to list what changed in a space, `browse` to walk its
tree, `status` to say what the mirror holds; or leave `--tools` out to serve all five.
Each host below starts the server itself: the command line goes into its settings, not
into a terminal.

## 3. Give the model room for the answers

A model's context holds the whole conversation: the host's instructions, the server's
instructions and tools (2,200 estimated tokens at most), each question, and each tool's
answer, 4,000 estimated tokens by default and 10,000 at most. One question that `ask`
answers, then two `read` calls, puts about 12,000 tokens of the mirror in it.

| Host | Context to set |
|---|---|
| LM Studio, llama.cpp's web UI | 32,768 tokens |
| Codex, Claude Code | 65,536 tokens, as Ollama advises for both |

Codex and Claude Code bring long instructions and tools of their own. Ollama gives a
model 4,096 tokens unless told otherwise, when the GPU has less than 24 GiB of memory:
the first answer would not fit.

## 4. Register the server in a host

Choose one host. LM Studio and llama.cpp run the model themselves; Codex and Claude
Code ask Ollama, which already serves the embeddings.

### LM Studio, an application

LM Studio is an MCP host from version 0.3.17. It is free, though not open source, and
sends no telemetry.

1. In Discover, search for `qwen3.5 9b` and download the GGUF build at `Q4_K_M`
   (5.7 GB). LM Studio also offers MLX builds for Apple silicon, which may be faster;
   mlx-lm, which they are built on, has had a report of Qwen3.5's tool calls going
   unseen (below), so try the GGUF first.
2. In My Models, open the model's settings and set its context length to 32768.
3. Open `~/.lmstudio/mcp.json`: in the right-hand sidebar, the Program tab, Install,
   then Edit mcp.json. Give the command's absolute path, as `which
   atlassian-offline-mcp` prints it, since an application started from the Dock does
   not read your shell's `PATH`:

   ```json
   {
     "mcpServers": {
       "atlassian-offline-mcp": {
         "command": "/Users/<you>/.local/bin/atlassian-offline-mcp",
         "args": ["serve", "--tools", "ask,read"]
       }
     }
   }
   ```

4. When the model calls a tool, LM Studio shows its arguments and asks before running
   it. Every tool of the server is read-only, so allowing them always changes nothing on
   disk.

Qwen3.5 thinks before it answers, by default. Where LM Studio shows a switch for
reasoning beside the message box, turning it off answers sooner; [the
explanation](../explanation/local-models.md#thinking) says what it costs.

### llama.cpp's web UI, open source

`llama-server`, which [reranking](reranking.md) uses too, is an MCP host in its recent
builds: `llama-server --help` lists `--mcp-servers-config`. It starts stdio servers
only, which this one is. Write `~/.config/llama.cpp/mcp.json`:

```json
{
  "mcpServers": {
    "atlassian-offline-mcp": {
      "command": "atlassian-offline-mcp",
      "args": ["serve", "--tools", "ask,read"]
    }
  }
}
```

Then start the server in a terminal of its own; `-hf` downloads the model from Hugging
Face the first time, into llama.cpp's cache:

```bash
llama-server -hf unsloth/Qwen3.5-9B-GGUF:Q4_K_M --host 127.0.0.1 --port 8080 -c 32768 --chat-template-kwargs '{"enable_thinking": false}' --mcp-servers-config ~/.config/llama.cpp/mcp.json
```

- `--port 8080`: the reranking server, when it runs, holds 9931.
- `-c 32768`: the context. Without it, the server reserves the model's whole window,
  which does not fit.
- `--chat-template-kwargs '{"enable_thinking": false}'`: Qwen3.5's own switch for
  thinking; leave it out to let the model think first.

Open `http://127.0.0.1:8080`: the web UI lists the server's tools, named
`atlassian-offline-mcp_ask` and `atlassian-offline-mcp_read`.

### Ollama, for Codex and Claude Code

Pull the model:

```bash
ollama pull qwen3.5:9b
```

Then give it a name of its own that carries the context, so that the embedding model
keeps its own. In a file named `Modelfile`:

```text
FROM qwen3.5:9b
PARAMETER num_ctx 65536
```

```bash
ollama create qwen3.5-9b-64k -f Modelfile
```

The context could instead be set for every model, by the slider in the Ollama app's
settings or by `OLLAMA_CONTEXT_LENGTH`; the embedding model would then reserve memory
for a context it never uses.

At 65,536 tokens, keep the model's cache at 8 bits, which halves it: set
`OLLAMA_KV_CACHE_TYPE=q8_0` where Ollama starts, then restart it. For the macOS
application:

```bash
launchctl setenv OLLAMA_KV_CACHE_TYPE q8_0
```

For `ollama serve` in a terminal, start it as `OLLAMA_KV_CACHE_TYPE=q8_0 ollama serve`;
for the systemd service of Linux, add `Environment="OLLAMA_KV_CACHE_TYPE=q8_0"` under
`[Service]` with `systemctl edit ollama.service`. The setting applies to every model and
needs flash attention, which Ollama turns on by itself where the GPU supports it.

### Codex, in a terminal

Codex is open source, under Apache 2.0. `--oss` runs it against a server of models on
this machine. In `~/.codex/config.toml`:

```toml
oss_provider = "ollama"

[mcp_servers.atlassian-offline-mcp]
command = "atlassian-offline-mcp"
args = ["serve", "--tools", "ask,read"]
```

```bash
codex --oss -m qwen3.5-9b-64k
```

### Claude Code, in a terminal

Ollama answers Anthropic's API too, so Claude Code can run against the local model, and
the server that [coding agents](agents.md#claude-code) registered serves it unchanged.
Behind an address other than Anthropic's, Claude Code defers MCP tools until the model
searches for them, which Ollama does not fully support; `ENABLE_TOOL_SEARCH=false` gives
the model every tool from the start:

```bash
ANTHROPIC_BASE_URL=http://127.0.0.1:11434 ANTHROPIC_AUTH_TOKEN=ollama ANTHROPIC_API_KEY="" ENABLE_TOOL_SEARCH=false claude --model qwen3.5-9b-64k
```

Claude Code's own instructions and tools are long, and the model reads them all before
its first answer of a session, which can take minutes on a laptop. LM Studio or
llama.cpp's web UI answer sooner.

### Other hosts

These take a stdio server too, in settings of their own: Goose, its `extensions` of type
`stdio`; opencode, its `mcp` servers of type `local`; Zed, its `context_servers`, with
the model's `max_tokens` raised, since Zed asks Ollama for 4,096 tokens; Continue, its
`mcpServers`, in agent mode only. Open WebUI takes only MCP over HTTP, so a stdio server
needs a proxy such as mcpo before it.

## 5. Check it

Ask a question whose answer you know the mirror holds. The host shows a call to `ask`,
then an answer that names its documents' refs; follow one to check it. While the model
answers, in another terminal:

```bash
ollama ps
```

for a model that Ollama serves: `CONTEXT` says the context it was given, and
`PROCESSOR` should say `100% GPU`. If it names the CPU, the model does not fit beside
the rest: give it a shorter context, close other applications, or take the 4B.

If an answer seems to miss documents, `ask` says in its answer when it searched by
words alone, and why; this says whether the embedding model answers:

```bash
atlassian-offline-mcp model check
```

## Keep it on this machine

The server of models reads every question and every passage, so it must listen on this
machine alone. Ollama binds `127.0.0.1:11434` by default, and `llama-server` binds
`127.0.0.1`: do not set `OLLAMA_HOST` or `--host` to another address. A model that
Ollama serves from its cloud, such as a `:cloud` tag, would send them away;
`OLLAMA_NO_CLOUD=1`, where Ollama starts, turns its cloud off. For Claude Code,
`CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1` turns off its telemetry and updates. The
embedding endpoint stays on this machine as [embeddings](embeddings.md) says.

## When it goes wrong

- **The model answers without calling a tool.** A small model answers from what it
  remembers, which for a 9B model is little and often wrong. Ask it to use `ask`.
- **It forgets the question, or ignores what a tool said.** The context is too short for
  the conversation: check `CONTEXT` in `ollama ps`, raise it, or serve fewer tools.
- **Each answer takes minutes.** The model reads every tool's answer before it writes:
  about half a minute for 4,000 tokens on a laptop's GPU. Take the 4B, turn thinking
  off, or keep to `ask`.
- **The host cannot start the server.** Give the command's absolute path.

## Sources

Checked on 2026-10-28:

- Models: [Qwen3.5 9B](https://huggingface.co/Qwen/Qwen3.5-9B), its
  [GGUF builds](https://huggingface.co/unsloth/Qwen3.5-9B-GGUF), and Ollama's
  [qwen3.5](https://ollama.com/library/qwen3.5).
- Ollama: [context length](https://docs.ollama.com/context-length),
  [FAQ](https://docs.ollama.com/faq),
  [OpenAI compatibility](https://docs.ollama.com/api/openai-compatibility),
  [thinking](https://docs.ollama.com/capabilities/thinking),
  [Claude Code](https://docs.ollama.com/integrations/claude-code),
  [Codex](https://docs.ollama.com/integrations/codex).
- LM Studio: [MCP](https://lmstudio.ai/docs/app/mcp), and
  [its announcement](https://lmstudio.ai/blog/mcp) of 2025-06-25;
  [privacy](https://lmstudio.ai/app-privacy); mlx-lm's
  [report on Qwen3.5's tool calls](https://github.com/ml-explore/mlx-lm/issues/1293).
- llama.cpp: [the server](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md).
- Codex: [sample configuration](https://developers.openai.com/codex/config-sample),
  [advanced configuration](https://developers.openai.com/codex/config-advanced).
- Claude Code: [MCP and tool search](https://code.claude.com/docs/en/mcp),
  [environment variables](https://code.claude.com/docs/en/env-vars).
- Other hosts: [Goose](https://goose-docs.ai/docs/guides/config-files),
  [opencode](https://opencode.ai/docs/mcp-servers),
  [Zed](https://zed.dev/docs/ai/mcp) and
  [its local models](https://zed.dev/docs/ai/use-a-local-model),
  [Continue](https://docs.continue.dev/customize/deep-dives/mcp),
  [Open WebUI](https://docs.openwebui.com/features/extensibility/mcp/) and
  [mcpo](https://github.com/open-webui/mcpo).
