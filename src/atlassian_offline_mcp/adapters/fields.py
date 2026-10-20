"""Strict reading of JSON responses, so that a changed response fails where it changed."""

from __future__ import annotations

from datetime import datetime
from typing import cast

KIND_NAMES = {str: "a string", int: "an integer", dict: "an object", list: "a list"}


class RepresentationError(ValueError):
    """A response without the shape its adapter expects; the message names the field."""


class Fields:
    """A JSON object whose fields are read by type, each failure naming the field's path.

    A field that is absent and one that is null are the same to every reader.
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
        """Read a JSON list of objects; null stands for an empty list."""
        if value is None:
            return []
        if type(value) is not list:
            message = f"{path}: expected a list"
            raise RepresentationError(message)
        return [cls(item, f"{path}[{index}]") for index, item in enumerate(value)]

    def _typed(self, key: str, kind: type, *, required: bool) -> object:
        value = self._value.get(key)
        if value is None and not required:
            return None
        if type(value) is not kind:
            message = f"{self._path}.{key}: expected {KIND_NAMES[kind]}"
            raise RepresentationError(message)
        return value

    def text(self, key: str) -> str:
        """Read a string."""
        return cast("str", self._typed(key, str, required=True))

    def optional_text(self, key: str) -> str | None:
        """Read a string, or None when it is absent."""
        return cast("str | None", self._typed(key, str, required=False))

    def integer(self, key: str) -> int:
        """Read an integer; a boolean is not one."""
        return cast("int", self._typed(key, int, required=True))

    def time(self, key: str) -> datetime:
        """Read an ISO 8601 time with its offset from UTC."""
        text = self.text(key)
        try:
            moment = datetime.fromisoformat(text)
        except ValueError:
            moment = None
        if moment is None or moment.tzinfo is None:
            message = f"{self._path}.{key}: expected an ISO 8601 time with an offset"
            raise RepresentationError(message)
        return moment

    def texts(self, key: str) -> tuple[str, ...]:
        """Read a list of strings; absent stands for an empty list."""
        values = cast("list[object]", self._typed(key, list, required=False) or [])
        if not all(type(value) is str for value in values):
            message = f"{self._path}.{key}: expected a list of strings"
            raise RepresentationError(message)
        return cast("tuple[str, ...]", tuple(values))

    def object(self, key: str) -> Fields:
        """Read a nested object."""
        return Fields(self._typed(key, dict, required=True), f"{self._path}.{key}")

    def optional_object(self, key: str) -> Fields | None:
        """Read a nested object, or None when it is absent."""
        value = self._typed(key, dict, required=False)
        return None if value is None else Fields(value, f"{self._path}.{key}")

    def objects(self, key: str) -> list[Fields]:
        """Read a list of objects; absent stands for an empty list."""
        return Fields.each(self._value.get(key), f"{self._path}.{key}")
