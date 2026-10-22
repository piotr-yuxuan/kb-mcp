"""What a subcommand declares apart from its run, standard library only."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import argparse
    from collections.abc import Mapping

# The program's name, as pyproject.toml names its script.
PROGRAM = "atlassian-offline-mcp"


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
    of the output aside: each flag among them is named by its option.
    """

    name: str
    run: str
    reads: tuple[str, ...] = ()
    flags: Mapping[str, str] = field(default_factory=dict)
    actions: tuple[argparse.Action, ...] = ()

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
