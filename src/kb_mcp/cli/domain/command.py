"""What a subcommand declares apart from its run, standard library only."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    import argparse
    from collections.abc import Callable, Mapping

# The stages of the pipeline, in its order: fetch and prepare per source, index and embed
# over the whole.
type Stage = Literal["fetch", "prepare", "index", "embed"]
STAGES: tuple[Stage, ...] = ("fetch", "prepare", "index", "embed")
FETCH, PREPARE, INDEX, EMBED = STAGES
WHOLE: frozenset[Stage] = frozenset({INDEX, EMBED})
# The settings that the entry reads for every command that it observes, by path, to
# observe its run: where its log file goes and where its telemetry goes.
OBSERVING = ("logs.dir", "telemetry.endpoint")
# What a run does not apply of the values given, by setting, and why: a pure function of
# the arguments and of every setting's value, by its path joined by dots.
type CommandUnapplied = Callable[[argparse.Namespace, Mapping[str, object]], Mapping[str, str]]
# What a run will do, in lines of the echo written before it acts: a pure function of
# the same.
type CommandDescribed = Callable[[argparse.Namespace, Mapping[str, object]], tuple[str, ...]]
# Why a run cannot go on, said before anything is asked, or None when it can: a pure
# function of the same.
type CommandRefused = Callable[[argparse.Namespace, Mapping[str, object]], str | None]


@dataclass(frozen=True)
class Command:
    """A subcommand as its parser declares it, by ``set_defaults(command=...)``.

    ``name`` is the subcommand as typed, which its run's module need not match: ``embed``
    is run by ``cli.commands.index``. ``run`` names the module whose ``run(arguments,
    loaded)`` runs it, imported only once it is chosen. ``reads`` names each setting that
    the run reads, by its path
    (``sources.confluence.spaces``); the entry also reads those of ``OBSERVING`` for every
    command that it observes. ``flags`` maps each option that overrides a setting, by its
    ``dest``, to that setting's path; ``scoped``, each that overrides a setting of one
    source, to its path by source. ``actions``, the output's aside, are what the command
    to copy carries.

    A command that ``writes`` shows its echo and the command to copy, then asks before it
    acts, unless given --yes, or --dry-run if it takes one (``dry_run``). One not
    ``traced`` is no trace of its own. One not ``observed`` runs as --version does,
    without the entry: its module's ``run(arguments)`` writes its output and gives its
    exit status, and nothing reads settings, logs or sends telemetry for it.

    ``unapplied`` names what the run does not apply and why, said once; ``described``
    gives the lines that the echo ends with; what ``refused`` says exits 2 before the
    echo, as does a program of ``programs`` not on PATH, or an argument of ``files`` that
    names nothing or a folder, though a pipe passes. The three name no type of ``config``.
    ``unlogged`` names the positionals of type ``str`` whose values ``run.start`` never
    names, each at the last token equal to it. A command whose ``stages``, in pipeline
    order, enable any is recorded under ``runs/<run id>/``, and its run given its id.
    """

    name: str
    run: str
    reads: tuple[str, ...] = ()
    flags: Mapping[str, str] = field(default_factory=dict)
    scoped: Mapping[str, Mapping[str, str]] = field(default_factory=dict)
    actions: tuple[argparse.Action, ...] = ()
    writes: bool = False
    dry_run: bool = False
    traced: bool = True
    observed: bool = True
    unapplied: CommandUnapplied | None = None
    described: CommandDescribed | None = None
    refused: CommandRefused | None = None
    programs: tuple[str, ...] = ()
    files: tuple[str, ...] = ()
    unlogged: tuple[str, ...] = ()
    stages: tuple[Stage, ...] = ()

    def narrowed(self, arguments: argparse.Namespace) -> dict[str, dict[str, str]]:
        """Give each flag of ``scoped`` the settings that it may override, by source.

        Those of the sources named, or of every source with none named; none for a resume,
        which runs the settings that its run recorded.
        """
        if not self.scoped or getattr(arguments, "resume", None):
            return {}
        named = set(arguments.source)
        return {
            dest: {name: path for name, path in by.items() if name in named or not named}
            for dest, by in self.scoped.items()
        }

    def setting_flags(self, arguments: argparse.Namespace) -> dict[str, tuple[str, str]]:
        """Map the ``dest`` of each flag among the actions to its longest option and its setting.

        A flag of ``scoped`` overrides a setting only when ``narrowed`` leaves it one.
        """
        settings = {
            **self.flags,
            **{
                dest: next(iter(left.values()))
                for dest, left in self.narrowed(arguments).items()
                if len(left) == 1
            },
        }
        return {
            action.dest: (max(action.option_strings, key=len), settings[action.dest])
            for action in self.actions
            if action.dest in settings
        }
