# Shell completions

How to have bash or zsh complete `kb-mcp`'s subcommands, options and
their values when you press Tab.

## 1. Put the command on your PATH

The shell runs the command by its name at each Tab, so it must be on your `PATH`, not
only runnable by `uv run` in a checkout. From a checkout of the repository:

```bash
uv tool install --force .
```

uv puts the command in its tools' folder, `~/.local/bin` unless `uv tool dir --bin`
says otherwise. If your shell does not find it there, `uv tool update-shell` adds that
folder to your `PATH`, from the next shell on. `command -v kb-mcp` says
where it is. After an upgrade, the same `uv tool install --force .` replaces it.

## 2. Load the completion

`kb-mcp completion` prints the code that completes the command, one
script for both shells. Write it once where your shell loads completions when first
needed, and again after each upgrade. In bash, with bash-completion:

```bash
mkdir -p ~/.local/share/bash-completion/completions
kb-mcp completion > ~/.local/share/bash-completion/completions/kb-mcp
```

In zsh, write it to a file named `_kb-mcp` in a folder of `$fpath`,
before `compinit` runs. Then open a new shell.

Or load it at each start of a shell, which is simpler, but runs the command each time,
for about as long as `--help`, some 60 ms: it reads no settings and logs nothing. In
bash, add this line to `~/.bashrc`:

```bash
eval "$(kb-mcp completion)"
```

In zsh, add it to `~/.zshrc` after `compinit`, which starts zsh's completion system:

```zsh
autoload -Uz compinit && compinit
eval "$(kb-mcp completion)"
```

argcomplete's own `register-python-argcomplete` and its global completion are not
needed, and `uv tool install` puts neither on your `PATH`: the command prints the
script itself. fish is not supported.

## What it completes

- The subcommands: `dow` gives `download`.
- Each subcommand's options and their choices: `download --sp` gives `--space`, `check
  --format ` gives `text` and `json`.
- Files where an option takes one: TOML files for `--config`, folders for
  `--data-dir`, YAML files for `eval`'s golden questions.

Space and project keys are not completed, since only the site knows them. At each Tab
the command reads its declarations alone, not the code of its runs, so that it answers
quickly.
