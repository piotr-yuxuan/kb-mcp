"""The base of the program's records: values built by keyword, checked, frozen."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from kb_mcp.kernel.names import RefusedError
from kb_mcp.kernel.output import Detail, Format, Level


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
        """Leave a record that is not frozen unhashable, unless it defines ``__hash__``.

        Pydantic hashes a frozen model by its fields, and a subclass inherits the hash: a
        record that accumulates would hash the same whatever it holds.
        """
        super().__pydantic_init_subclass__(**kwargs)
        if not cls.model_config.get("frozen") and "__hash__" not in vars(cls):
            cls.__hash__ = None

    def __replace__(self, **changes: object) -> Self:
        """Give a copy with these fields changed, checked again as at construction.

        ``copy.replace`` calls it; Pydantic's own copies without the checks.
        """
        kept = {name: getattr(self, name) for name in type(self).model_fields}
        return type(self)(**{**kept, **changes})


class Invocation(Record):
    """One start of the program: its command, how it reports, and what ``run.start`` says.

    ``level`` is the least severe of what it says on stderr; ``detail`` and ``format``
    say how its result is written on stdout. ``quiet``, from -q alone, which sets the
    level error, leaves a result as text unwritten, and what is said before a run that
    asks nothing. ``stdin_terminal`` and ``stderr_terminal`` say whether someone can read
    a question there and answer it. One not ``traced`` is no trace of its own, such as a
    server's, each of whose requests is one. ``commands`` names those whose log files
    past 30 days it removes; ``run`` is the id of the run that it resumes, None for a new
    run.
    """

    command: str
    level: Level
    detail: Detail
    format: Format
    quiet: bool
    stdin_terminal: bool
    stderr_terminal: bool
    dry_run: bool = False
    traced: bool = True
    commands: frozenset[str] = frozenset()
    run: str | None = None
    described: Mapping[str, object] = Field(default_factory=dict)

    @model_validator(mode="after")
    def check_quiet(self) -> Self:
        """Refuse ``quiet`` at a level other than error, which -q sets."""
        if self.quiet and self.level != "error":
            message = f"quiet at the level {self.level}: -q sets the level error"
            raise RefusedError(message)
        return self


def refused_fields(error: ValidationError) -> str:
    """Name each field that a validation refused, by its path, and why; never its value.

    A path joins its names by dots; a value refused whole, at no field, is ``the whole``.
    """
    return "; ".join(
        f"{'.'.join(str(part) for part in problem['loc']) or 'the whole'}: {problem['msg']}"
        for problem in error.errors(include_input=False)
    )
