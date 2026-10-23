"""``eval-agents``' declaration; ``cli.commands.evaluate_agents`` runs each of its steps.

Its output options come before the step, which has options of its own:
``eval-agents --format json grade DIR``.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from argcomplete.completers import DirectoriesCompleter, FilesCompleter

from atlassian_offline_mcp.cli.domain.command import Command
from atlassian_offline_mcp.cli.domain.eval_agents import MODELS, SEED, described
from atlassian_offline_mcp.cli.options._common import (
    add_embedding_options,
    add_output_options,
    add_settings_options,
    add_yes_option,
)

RUN = "atlassian_offline_mcp.cli.commands.evaluate_agents"


def positive(value: str) -> int:
    """Read a count of one or more."""
    if not value.isdigit() or int(value) < 1:
        message = "a count of one or more"
        raise argparse.ArgumentTypeError(message)
    return int(value)


def register(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """Add ``eval-agents`` and its four steps to the command."""
    parser = subparsers.add_parser(
        "eval-agents",
        help="evaluate ask through agents: prepare their runs, bridge their calls, grade",
        epilog=(
            "Its options of output come before the step. With --format json: prepare, the"
            " runs written; call, the answer; answer, the answer kept; grade, each run's"
            " outcome, the verdict on ask and the runs counted."
        ),
    )
    add_output_options(parser)
    # The steps' own declarations replace this one, which says that some write.
    parser.set_defaults(command=Command("eval-agents", RUN, writes=True))
    steps = parser.add_subparsers(required=True, metavar="step")

    prepare = steps.add_parser("prepare", help="write each run's prompt, and runs.json")
    actions, flags = add_settings_options(prepare)
    add_yes_option(prepare)
    remote = add_embedding_options(prepare)
    golden = prepare.add_argument("golden", type=Path, help="a YAML file of golden questions")
    golden.completer = FilesCompleter(["yaml", "yml"])
    out = prepare.add_argument(
        "--out", type=Path, required=True, help="the runs' directory, new or empty"
    )
    out.completer = DirectoriesCompleter()
    model = prepare.add_argument(
        "--model", choices=MODELS, required=True, help="the agents' model, by its alias"
    )
    sample = prepare.add_argument(
        "--sample", type=positive, help="this many questions, chosen by the seed; else all"
    )
    seed = prepare.add_argument("--seed", type=int, default=SEED, help="the sample's seed")
    prepare.add_argument(
        "--dry-run", action="store_true", help="say what would be prepared, and write nothing"
    )
    prepare.set_defaults(
        step="prepare",
        command=Command(
            "eval-agents prepare",
            RUN,
            reads=("data_dir",),
            flags=flags,
            actions=(*actions, remote, golden, out, model, sample, seed),
            writes=True,
            dry_run=True,
            described=described,
            files=("golden",),
        ),
    )

    # call and answer read no setting but where their own logs and telemetry go; the
    # server that call starts reads the settings that prepare named.
    call = steps.add_parser("call", help="call a tool for a run, and print its answer")
    called_actions, called_flags = add_settings_options(call)
    call.add_argument("directory", type=Path, help="the runs' directory")
    call.add_argument("run", help="the run's id")
    call.add_argument("tool", help="the tool's name")
    call.add_argument("arguments", help="the tool's arguments, as one JSON object")
    call.set_defaults(
        step="call",
        command=Command("eval-agents call", RUN, flags=called_flags, actions=called_actions),
    )

    answer = steps.add_parser("answer", help="keep a run's answer, once")
    answered_actions, answered_flags = add_settings_options(answer)
    answer.add_argument("directory", type=Path, help="the runs' directory")
    answer.add_argument("run", help="the run's id")
    answer.add_argument("answer", help="the answer, as one JSON object")
    answer.set_defaults(
        step="answer",
        command=Command(
            "eval-agents answer",
            RUN,
            flags=answered_flags,
            actions=answered_actions,
            unlogged=("answer",),
        ),
    )

    grade = steps.add_parser("grade", help="grade the runs, and judge ask; keep the results")
    graded_actions, graded_flags = add_settings_options(grade)
    add_yes_option(grade)
    directory = grade.add_argument("directory", type=Path, help="the runs' directory")
    grade.set_defaults(
        step="grade",
        command=Command(
            "eval-agents grade",
            RUN,
            reads=("data_dir",),
            flags=graded_flags,
            actions=(*graded_actions, directory),
            writes=True,
        ),
    )
