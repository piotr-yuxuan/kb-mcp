"""What a subcommand declares apart from its run, standard library only."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import argparse
    from collections.abc import Callable, Mapping

# The program's name, as pyproject.toml names its script.
PROGRAM = "atlassian-offline-mcp"
# What a run does not apply of the values given, by setting, and why: a pure function of
# the arguments and of every setting's value, by its path joined by dots.
type Unapplied = Callable[[argparse.Namespace, Mapping[str, object]], Mapping[str, str]]
# What a run will do, in lines of the summary written before it acts: a pure function of
# the same.
type Described = Callable[[argparse.Namespace, Mapping[str, object]], tuple[str, ...]]
# Why a run cannot go on, said before anything is asked, or None when it can: a pure
# function of the same.
type Refused = Callable[[argparse.Namespace, Mapping[str, object]], str | None]


@dataclass(frozen=True)
class Command:
    """A subcommand as its parser declares it, by ``set_defaults(command=...)``.

    ``name`` is the subcommand as typed, which its run's module need not match: ``eval``
    is run by ``cli.commands.evaluate``. ``run`` names the module whose
    ``run(arguments, loaded)`` runs it, imported only once it is chosen. ``reads`` names
    each setting that the run reads, by its path, its names joined by dots
    (``sources.confluence.spaces``); a command that reads none gets ``None`` for its
    settings, and so runs whatever the settings file holds. ``flags`` maps each option
    that overrides a setting, by the option's ``dest``, to that setting's path.
    ``actions`` are the options and positionals as ``add_argument`` returned them, those
    of the output aside: each flag among them is named by its option, and the command to
    copy carries them. A command that ``writes`` under the data directory shows its
    summary and that command, then asks before it acts, unless given --yes, which it
    then takes, or --dry-run, if it takes one (``dry_run``).

    ``unapplied``, if any, names what the run does not apply of the settings it reads,
    such as the model of an index built by words alone; ``described``, if any, gives the
    lines that the summary ends with; ``refused``, if any, says why the run cannot go
    on, such as a download without a site, which exits 2 before the summary. Each lives
    in the command's own declaration and names no type of ``config``, so that declaring
    the command stays light. ``programs`` names those that the run needs on PATH, such
    as pandoc, without which it is refused alike.
    """

    name: str
    run: str
    reads: tuple[str, ...] = ()
    flags: Mapping[str, str] = field(default_factory=dict)
    actions: tuple[argparse.Action, ...] = ()
    writes: bool = False
    dry_run: bool = False
    unapplied: Unapplied | None = None
    described: Described | None = None
    refused: Refused | None = None
    programs: tuple[str, ...] = ()

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
