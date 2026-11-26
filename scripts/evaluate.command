#!/bin/zsh -l
# Opened from Finder: run the evaluations, then keep this window open until a key.
uv run --script "${0:A:h}/evaluate.py" "$@"
code=$?
print -n "Press a key to close this window. "
read -sk 1
exit $code
