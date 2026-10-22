"""What a subcommand declares apart from its run, standard library only."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping


@dataclass(frozen=True)
class Command:
    """A subcommand as its parser declares it, by ``set_defaults(command=...)``.

    ``run`` names the module whose ``run(arguments, settings)`` runs it, imported only
    once it is chosen. ``flags`` maps each option that overrides a setting, by the
    option's ``dest``, to that setting's name.
    """

    run: str
    flags: Mapping[str, str] = field(default_factory=dict)
