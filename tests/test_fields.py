"""The strict reader of responses: each type read as itself, or refused by its path."""

from __future__ import annotations

import pytest

from atlassian_offline_mcp.kernel.fields import Fields, RepresentationError


def test_a_boolean_is_read_as_itself_and_nothing_else_is_one() -> None:
    """A flag such as isLast is true or false, never 1, never "true"."""
    assert Fields({"isLast": True}, "search").flag("isLast") is True
    for value in (1, "true", None):
        with pytest.raises(RepresentationError, match=r"^search\.isLast: expected a boolean"):
            Fields({"isLast": value}, "search").flag("isLast")


def test_the_object_read_is_given_back_as_decoded() -> None:
    """What is stored as received is the very object that was read."""
    decoded = {"id": "1", "extra": [1, 2]}
    assert Fields(decoded, "entry").value is decoded


def test_absence_is_accepted_only_where_it_is_allowed() -> None:
    """A field that a response may leave out reads as None; any other must be there."""
    fields = Fields({"present": None}, "entry")
    assert fields.optional_text("present") is None
    assert fields.optional_text("absent", absent=True) is None
    with pytest.raises(RepresentationError, match=r"^entry\.absent: missing"):
        fields.optional_text("absent")
