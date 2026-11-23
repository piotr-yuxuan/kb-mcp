"""A run's record, ``<data>/runs/<run id>/``: its configuration, its units' last entries, its lock.

The layout: docs/reference/data-layout.md, section "Runs". This module alone reads and
writes it. ``configuration.json`` is written once, as the run starts; ``outcomes.json``
is replaced whole as each unit ends; each through a hidden file renamed into place, so
that a reader finds the last write whole or the one before it. One invocation at a time
holds a run, inside ``holding``. A record without a folder, a dry run's, keeps its files
in memory: a dry run reads its configuration back as any other run does, and writes
nothing.
"""

from __future__ import annotations

import fcntl
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import ValidationError

from kb_mcp.cli.domain.runs import Configuration, Outcomes, Recorded
from kb_mcp.config.domain.settings import SettingsError, with_secrets
from kb_mcp.kernel.fields import RepresentationError
from kb_mcp.kernel.names import RefusedError
from kb_mcp.kernel.records import refused_fields

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator

    from kb_mcp.config.domain.settings import Settings
    from kb_mcp.kernel.records import Record

# The record's files, and its lock, in the run's folder.
CONFIGURATION, OUTCOMES, LOCK = "configuration.json", "outcomes.json", ".lock"


class RunBusyError(RuntimeError):
    """Another invocation holds the run."""


class RunRecord:
    """One run's record: the folder ``<runs>/<run id>/``, or none for a run that records nothing."""

    def __init__(self, folder: Path | None) -> None:
        """Use ``folder``, which ``holding`` makes; None keeps the files in memory."""
        self.folder = folder
        self._kept: dict[str, bytes] = {}

    @contextmanager
    def holding(self) -> Iterator[None]:
        """Hold the run's lock, its folder made; raise ``RunBusyError`` if another holds it."""
        if self.folder is None:
            yield
            return
        self.folder.mkdir(parents=True, exist_ok=True)
        handle = os.open(self.folder / LOCK, os.O_RDWR | os.O_CREAT, 0o600)
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            os.close(handle)
            raise RunBusyError from None
        try:
            yield
        finally:
            os.close(handle)  # closing the descriptor releases the lock

    def write_configuration(self, configuration: Configuration) -> None:
        """Write the run's configuration, inside ``holding``."""
        self._write(CONFIGURATION, configuration)

    def read_configuration(self) -> Configuration:
        """Read the run's configuration.

        Raises FileNotFoundError when none was written, and RepresentationError, naming
        the file and the field, never its value, for one that cannot be read, or that
        names another run than its folder does, as a folder copied or renamed would.
        """
        configuration = self._read(CONFIGURATION, Configuration)
        if self.folder is not None and configuration.run != self.folder.name:
            message = f"{self.where(CONFIGURATION)}: run: not the id that its folder names"
            raise RepresentationError(message)
        return configuration

    def settings(self, configuration: Configuration, secrets: Settings) -> Settings:
        """Build the settings that its configuration records, each secret as ``secrets`` has it.

        Raises RepresentationError, naming the file and each setting refused, never its
        value, such as the table of a source that the settings' model no longer holds.
        """
        try:
            return with_secrets(configuration.settings, secrets)
        except SettingsError as error:
            message = f"{self.where(CONFIGURATION)}: settings: {error}"
            raise RepresentationError(message) from None

    @contextmanager
    def checking(self) -> Iterator[None]:
        """Name its configuration's file in what a check of it refuses within.

        A RefusedError raised within, naming a field of the configuration, such as a source
        no longer configured, is raised as RepresentationError naming the file and field.
        """
        try:
            yield
        except RefusedError as error:
            message = f"{self.where(CONFIGURATION)}: {error}"
            raise RepresentationError(message) from None

    def where(self, name: str) -> str:
        """Name one of its files as a refusal does: by its path from the data directory."""
        return name if self.folder is None else f"runs/{self.folder.name}/{name}"

    def write_outcomes(self, entries: Iterable[Recorded]) -> None:
        """Replace each unit's last entry, in their order, inside ``holding``."""
        self._write(OUTCOMES, Outcomes(units=tuple(entries)))

    def read_outcomes(self) -> tuple[Recorded, ...]:
        """Read each unit's last entry, none before the first unit ends.

        Raises RepresentationError as ``read_configuration`` does.
        """
        try:
            return self._read(OUTCOMES, Outcomes).units
        except FileNotFoundError:
            return ()

    def _write(self, name: str, record: Record) -> None:
        data = record.model_dump_json(indent=1).encode()
        if self.folder is None:
            self._kept[name] = data
            return
        handle, hidden = tempfile.mkstemp(prefix=f".{name}.", dir=self.folder)
        try:
            with os.fdopen(handle, "wb") as file:
                file.write(data)
                file.flush()
                os.fsync(file.fileno())
            Path(hidden).replace(self.folder / name)
        finally:
            Path(hidden).unlink(missing_ok=True)

    def _read[R: Record](self, name: str, kind: type[R]) -> R:
        where = self.where(name)
        if self.folder is None and name not in self._kept:
            raise FileNotFoundError(name)
        try:
            data = self._kept[name] if self.folder is None else (self.folder / name).read_bytes()
        except FileNotFoundError:
            raise
        except OSError as error:
            message = f"{where}: not read: {type(error).__name__}"
            raise RepresentationError(message) from None
        try:
            return kind.model_validate_json(data, strict=True)
        except ValidationError as error:
            message = f"{where}: {refused_fields(error)}"
            raise RepresentationError(message) from None
