"""What a subcommand declares apart from its run, standard library only."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping

# The program's name, as pyproject.toml names its script.
PROGRAM = "atlassian-offline-mcp"


@dataclass(frozen=True)
class Command:
    """A subcommand as its parser declares it, by ``set_defaults(command=...)``.

    ``run`` names the module whose ``run(arguments, settings)`` runs it, imported only
    once it is chosen. ``flags`` maps each option that overrides a setting, by the
    option's ``dest``, to that setting's path, its names joined by dots
    (``sources.confluence.spaces``). Without ``reads_settings``, the run gets ``None``
    for its settings, and so runs whatever the settings file holds. With
    ``with_layers``, it gets the settings with the layer of each and the values ignored
    (``config.domain.settings.Loaded``) rather than the settings alone.
    """

    run: str
    flags: Mapping[str, str] = field(default_factory=dict)
    reads_settings: bool = True
    with_layers: bool = False
