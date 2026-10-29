"""The base of the program's records: values built by keyword, checked, frozen.

Every record is a ``Record``; the classes that stay dataclasses, and why, are in
``docs/explanation/code-layout.md``. A validator refuses a value by raising the domain's
``RefusedError``, which Pydantic wraps; the constructor gives it back as raised, so that
callers and messages see what they saw of a dataclass. ``copy.replace`` gives a record
with some fields changed, checked again, as ``dataclasses.replace`` gave a dataclass.
"""

from __future__ import annotations

from typing import Self

from pydantic import BaseModel, ConfigDict, ValidationError

from kb_mcp.kernel.names import RefusedError


class Record(BaseModel):
    """A value of the program: built by keyword, checked at construction, frozen."""

    model_config = ConfigDict(frozen=True, extra="forbid", hide_input_in_errors=True)

    def __init__(self, /, **fields: object) -> None:
        """Build the record; a validator's refusal is raised as the domain's own."""
        try:
            super().__init__(**fields)
        except ValidationError as error:
            causes = [each.get("ctx", {}).get("error") for each in error.errors()]
            if causes and all(isinstance(cause, RefusedError) for cause in causes):
                raise causes[0] from None
            raise

    @classmethod
    def __pydantic_init_subclass__(cls, **kwargs: object) -> None:
        """Leave a record that is not frozen unhashable, as a dataclass that was not frozen.

        Pydantic hashes a frozen model by its fields, and a subclass inherits the hash: a
        record that accumulates would hash the same whatever it holds.
        """
        super().__pydantic_init_subclass__(**kwargs)
        if not cls.model_config.get("frozen"):
            cls.__hash__ = None

    def __replace__(self, **changes: object) -> Self:
        """Give a copy with these fields changed, checked again as at construction.

        ``copy.replace`` calls it; Pydantic's own copies without the checks.
        """
        kept = {name: getattr(self, name) for name in type(self).model_fields}
        return type(self)(**{**kept, **changes})
