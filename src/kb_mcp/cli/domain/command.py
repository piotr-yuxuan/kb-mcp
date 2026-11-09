"""What a subcommand declares apart from its run, standard library only."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import argparse
    from collections.abc import Callable, Mapping

# The program's name, as pyproject.toml names its script.
PROGRAM = "kb-mcp"
# The settings that the entry reads for every command that it observes, by path, to
# observe its run: where its log file goes and where its telemetry goes.
OBSERVING = ("logs.dir", "telemetry.endpoint")
# What a run does not apply of the values given, by setting, and why: a pure function of
# the arguments and of every setting's value, by its path joined by dots.
type CommandUnapplied = Callable[[argparse.Namespace, Mapping[str, object]], Mapping[str, str]]
# What a run will do, in lines of the summary written before it acts: a pure function of
# the same.
type CommandDescribed = Callable[[argparse.Namespace, Mapping[str, object]], tuple[str, ...]]
# Why a run cannot go on, said before anything is asked, or None when it can: a pure
# function of the same.
type CommandRefused = Callable[[argparse.Namespace, Mapping[str, object]], str | None]


@dataclass(frozen=True)
class Command:
    """A subcommand as its parser declares it, by ``set_defaults(command=...)``.

    ``name`` is the subcommand as typed, which its run's module need not match: ``eval``
    is run by ``cli.commands.evaluate``. ``run`` names the module whose
    ``run(arguments, loaded)`` runs it, imported only once it is chosen. ``reads`` names
    each setting that the run reads, by its path, its names joined by dots
    (``sources.confluence.spaces``); for every command that it observes, the entry reads
    those of ``OBSERVING`` too, which ``reads`` need not name, and so loads the settings
    even for one that reads no other. ``flags`` maps each option that overrides a
    setting, by the option's ``dest``, to that setting's path.
    ``actions`` are the options and positionals as ``add_argument`` returned them, those
    of the output aside: each flag among them is named by its option, and the command to
    copy carries them. A command that ``writes`` under the data directory shows its
    summary and that command, then asks before it acts, unless given --yes, which it
    then takes, or --dry-run, if it takes one (``dry_run``). A command whose run is not
    ``traced``, such as ``serve``, each of whose requests is a trace, is none of its own.
    One that is not ``observed``, such as ``completion``, which shells run at each start,
    is run as --version is, without the entry: its module's ``run(arguments)`` writes
    its output and gives its exit status, and nothing reads settings, logs, writes a
    log file or sends telemetry for it, so it reads none.

    ``unapplied``, if any, names what the run does not apply of the settings given, and
    why, such as the model of an index built by words alone, or the API token that
    ``login`` never reads, so that it is said once; ``described``, if any, gives the
    lines that the summary ends with; ``refused``, if any, says why the run cannot go
    on, such as a fetch without a site, which exits 2 before the summary. Each lives
    in the command's own declaration and names no type of ``config``, so that declaring
    the command stays light. ``programs`` names those that the run needs on PATH, such
    as pandoc, without which it is refused alike; ``files`` names, by their ``dest``,
    the arguments that name a file the run reads, such as ``eval``'s golden file,
    refused alike when it names nothing or a folder, though not a pipe, which a process
    substitution gives. ``unlogged`` names, by their ``dest``, the positional arguments
    of type ``str`` whose values the run's ``run.start`` does not name, each at the last
    token of the command line equal to it, such as the answer that ``eval-agents answer``
    keeps, which quotes the mirror.
    """

    name: str
    run: str
    reads: tuple[str, ...] = ()
    flags: Mapping[str, str] = field(default_factory=dict)
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

    def setting_flags(self) -> dict[str, tuple[str, str]]:
        """Map the ``dest`` of each flag among the actions to its option and its setting.

        The option is the action's longest, such as ``--data-dir``, which names the
        flag's layer.
        """
        return {
            action.dest: (max(action.option_strings, key=len), self.flags[action.dest])
            for action in self.actions
            if action.dest in self.flags
        }
