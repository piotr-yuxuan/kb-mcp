"""Strict reading of JSON responses, so that a changed response fails where it changed."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime
from typing import TYPE_CHECKING, cast

from atlassian_offline_mcp.domain.content import RefusedError

if TYPE_CHECKING:
    from collections.abc import Iterator

KIND_NAMES = {str: "a string", int: "an integer", dict: "an object", list: "a list"}


class RepresentationError(ValueError):
    """A response without the shape its adapter expects.

    The message names the field's path and what was expected, never the value found,
    so that it can be reported without carrying content.
    """


class Fields:
    """A JSON object whose fields are read by type, each failure naming the field's path.

    Every field must be present. The ``optional_`` readers also accept null, and accept
    absence only when told ``absent=True``: a field that a response always carries, even
    as null, is then refused when the site stops sending it.
    """

    def __init__(self, value: object, path: str) -> None:
        """Wrap a decoded JSON object; ``path`` names it in error messages."""
        if type(value) is not dict:
            message = f"{path}: expected an object"
            raise RepresentationError(message)
        self._value = cast("dict[str, object]", value)
        self._path = path

    @classmethod
    def each(cls, value: object, path: str) -> list[Fields]:
        """Read a JSON list of objects."""
        if type(value) is not list:
            message = f"{path}: expected a list"
            raise RepresentationError(message)
        return [cls(item, f"{path}[{index}]") for index, item in enumerate(value)]

    @property
    def path(self) -> str:
        """Name this object, as error messages do."""
        return self._path

    @contextmanager
    def refusals(self) -> Iterator[None]:
        """Report a domain type's refusal of what was read as a refusal of this object.

        Only the domain's own refusals are caught: their messages name the field and the
        rule, never the value. Any other error is a fault of the program, and passes.
        """
        try:
            yield
        except RefusedError as error:
            message = f"{self._path}: {error}"
            raise RepresentationError(message) from None

    def _typed(self, key: str, kind: type, *, nullable: bool, absent: bool = False) -> object:
        if key not in self._value:
            if absent:
                return None
            message = f"{self._path}.{key}: missing"
            raise RepresentationError(message)
        value = self._value[key]
        if value is None and nullable:
            return None
        if type(value) is not kind:
            message = f"{self._path}.{key}: expected {KIND_NAMES[kind]}"
            raise RepresentationError(message)
        return value

    def text(self, key: str) -> str:
        """Read a string."""
        return cast("str", self._typed(key, str, nullable=False))

    def optional_text(self, key: str, *, absent: bool = False) -> str | None:
        """Read a string, or None when it is null (or absent, when that is allowed)."""
        return cast("str | None", self._typed(key, str, nullable=True, absent=absent))

    def integer(self, key: str) -> int:
        """Read an integer; a boolean is not one."""
        return cast("int", self._typed(key, int, nullable=False))

    def optional_integer(self, key: str) -> int | None:
        """Read an integer, or None when it is null."""
        return cast("int | None", self._typed(key, int, nullable=True))

    def time(self, key: str) -> datetime:
        """Read an ISO 8601 time with its offset from UTC."""
        text = self.text(key)
        try:
            moment = datetime.fromisoformat(text)
            moment.astimezone(UTC)  # an offset can carry a time off the calendar
        except ValueError, OverflowError:
            moment = None
        if moment is None or moment.tzinfo is None:
            message = f"{self._path}.{key}: expected an ISO 8601 time with an offset"
            raise RepresentationError(message)
        return moment

    def texts(self, key: str) -> tuple[str, ...]:
        """Read a list of strings."""
        values = cast("list[object]", self._typed(key, list, nullable=False))
        if not all(type(value) is str for value in values):
            message = f"{self._path}.{key}: expected a list of strings"
            raise RepresentationError(message)
        return cast("tuple[str, ...]", tuple(values))

    def object(self, key: str) -> Fields:
        """Read a nested object."""
        return Fields(self._typed(key, dict, nullable=False), f"{self._path}.{key}")

    def optional_object(self, key: str, *, absent: bool = False) -> Fields | None:
        """Read a nested object, or None when it is null (or absent, when allowed)."""
        value = self._typed(key, dict, nullable=True, absent=absent)
        return None if value is None else Fields(value, f"{self._path}.{key}")

    def objects(self, key: str) -> list[Fields]:
        """Read a list of objects."""
        return Fields.each(self._typed(key, list, nullable=False), f"{self._path}.{key}")
