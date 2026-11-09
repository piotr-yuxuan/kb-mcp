"""``eval-agents``' figures, and what ``prepare`` says before it asks: standard library only.

A run is bounded: CALLS calls of CALL_S seconds each, at most. What a run costs is
estimated from 006's budget and plan 019's reckoning, to be set once from the pilot's
results; ``grade`` fails a set of runs that spends past twice its estimate.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import argparse
    from collections.abc import Mapping

CALLS = 12
CALL_S = 60
# Estimated for one run: its calls, the tokens that they hand over, and the model's
# tokens in and out, most of those in being cache reads.
ESTIMATED_CALLS = 4
HANDED = 16_000
INPUT = 70_000
OUTPUT = 1_000
# A run spends past its estimate when it spends more than this many times it.
PAST = 2
SURFACES = ("A", "B")  # without ask, and with it
# The agents' models, by the aliases that Claude Code's subagents take.
MODELS = ("haiku", "sonnet")
SAMPLE_SEED = 11  # the sample's, unless given


def described(arguments: argparse.Namespace, _settings: Mapping[str, object]) -> tuple[str, ...]:
    """Say the runs that ``prepare`` writes, their bound, and what they are estimated to cost.

    With --sample, the totals too; without, the golden file, not read yet, sets them.
    """
    sample: int | None = arguments.sample
    said = (
        (
            "runs: two per question, each on one surface, A without ask and B with, for"
            f" subagents of the model {arguments.model}"
        ),
        f"bound: {CALLS} calls of {CALL_S} s at most per run",
        (
            f"estimated per run: {ESTIMATED_CALLS} calls handing over {HANDED:,} tokens at"
            f" most; model tokens {INPUT:,} in, {OUTPUT:,} out"
        ),
    )
    if not sample:
        return said
    runs = len(SURFACES) * sample
    return (
        *said,
        (
            f"in all: {runs} runs, {CALLS * runs:,} calls at most; estimated {HANDED * runs:,}"
            f" tokens handed over, model tokens {INPUT * runs:,} in, {OUTPUT * runs:,} out"
        ),
    )
