"""Strict reading of decoded JSON: a failure names the field's path, never the value found."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime
from typing import TYPE_CHECKING, cast

from kb_mcp.kernel.names import RefusedError

if TYPE_CHECKING:
    from collections.abc import Iterator

KIND_NAMES = {
    str: "a string",
    int: "an integer",
    bool: "a boolean",
    dict: "an object",
    list: "a list",
}


class RepresentationError(ValueError):
    """A response without the shape that its adapter expects."""


class Fields:
    """A JSON object read by type, each field present; ``optional_`` takes null, absent if told."""

    def __init__(self, value: object, path: str) -> None:
        """Wrap a decoded JSON object, which ``path`` names in errors."""
        if type(value) is not dict:
            message = f"{path}: expected an object"
            raise RepresentationError(message)
        self.value = cast("dict[str, object]", value)
        self.path = path

    @classmethod
    def each(cls, value: object, path: str) -> list[Fields]:
        """Read a JSON list of objects."""
        if type(value) is not list:
            message = f"{path}: expected a list"
            raise RepresentationError(message)
        return [cls(item, f"{path}[{index}]") for index, item in enumerate(value)]

    @contextmanager
    def refusals(self) -> Iterator[None]:
        """Raise a domain type's refusal of what was read as a refusal of this object."""
        try:
            yield
        except RefusedError as error:
            message = f"{self.path}: {error}"
            raise RepresentationError(message) from None

    def _typed(self, key: str, kind: type, *, nullable: bool, absent: bool = False) -> object:
        if key not in self.value:
            if absent:
                return None
            message = f"{self.path}.{key}: missing"
            raise RepresentationError(message)
        value = self.value[key]
        if value is None and nullable:
            return None
        if type(value) is not kind:
            message = f"{self.path}.{key}: expected {KIND_NAMES[kind]}"
            raise RepresentationError(message)
        return value

    def text(self, key: str) -> str:
        """Read a string."""
        return cast("str", self._typed(key, str, nullable=False))

    def optional_text(self, key: str, *, absent: bool = False) -> str | None:
        """Read a string, or None."""
        return cast("str | None", self._typed(key, str, nullable=True, absent=absent))

    def integer(self, key: str) -> int:
        """Read an integer; a boolean is not one."""
        return cast("int", self._typed(key, int, nullable=False))

    def flag(self, key: str) -> bool:
        """Read a boolean."""
        return cast("bool", self._typed(key, bool, nullable=False))

    def optional_integer(self, key: str) -> int | None:
        """Read an integer, or None."""
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
            message = f"{self.path}.{key}: expected an ISO 8601 time with an offset"
            raise RepresentationError(message)
        return moment

    def texts(self, key: str) -> tuple[str, ...]:
        """Read a list of strings."""
        values = cast("list[object]", self._typed(key, list, nullable=False))
        if not all(type(value) is str for value in values):
            message = f"{self.path}.{key}: expected a list of strings"
            raise RepresentationError(message)
        return cast("tuple[str, ...]", tuple(values))

    def object(self, key: str) -> Fields:
        """Read a nested object."""
        return Fields(self._typed(key, dict, nullable=False), f"{self.path}.{key}")

    def optional_object(self, key: str, *, absent: bool = False) -> Fields | None:
        """Read a nested object, or None."""
        value = self._typed(key, dict, nullable=True, absent=absent)
        return None if value is None else Fields(value, f"{self.path}.{key}")

    def objects(self, key: str) -> list[Fields]:
        """Read a list of objects."""
        return Fields.each(self._typed(key, list, nullable=False), f"{self.path}.{key}")
