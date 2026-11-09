"""A record: built by keyword, checked at construction, frozen, its errors without values."""

from __future__ import annotations

from typing import Self

import numpy as np
import pytest
from pydantic import ConfigDict, ValidationError, model_validator

from kb_mcp.kernel.names import RefusedError
from kb_mcp.kernel.record import Record
from kb_mcp.search.domain.search import ChunkVectors

# A value that no message may hold.
UNSHOWN = "a-value-never-shown"


class Sample(Record):
    """A record whose check refuses a negative count, as a domain type refuses a value."""

    name: str
    count: int = 0

    @model_validator(mode="after")
    def check_sample(self) -> Self:
        """Refuse a negative count."""
        if self.count < 0:
            message = "count: must not be negative"
            raise RefusedError(message)
        return self


class Pair(Record):
    """A record of two, each built from what it is given."""

    first: Sample
    second: Sample


class Tally(Record):
    """A record that accumulates."""

    model_config = ConfigDict(frozen=False)

    count: int = 0


class Keyed(Tally):
    """A record that accumulates, hashed by identity as its own ``__hash__`` says."""

    def __hash__(self) -> int:
        """Hash by identity."""
        return id(self)


def test_a_misspelt_keyword_is_refused() -> None:
    """A keyword that names no field fails, as a dataclass's did, never taken for a default."""
    with pytest.raises(ValidationError, match="cuont"):
        Sample(name="first", cuont=3)


def test_a_value_of_the_wrong_type_is_refused_without_the_value() -> None:
    """The error names the field, never the value given."""
    with pytest.raises(ValidationError, match="count") as caught:
        Sample(name="first", count=UNSHOWN)
    assert UNSHOWN not in str(caught.value)


def test_a_record_cannot_be_changed() -> None:
    """A record is frozen: a field is not assigned."""
    sample = Sample(name="first")
    with pytest.raises(ValidationError, match="frozen"):
        sample.count = 1
    assert sample.count == 0


def test_a_record_that_accumulates_is_unhashable_and_a_frozen_one_hashes_by_value() -> None:
    """As a dataclass: what changes has no hash unless it defines one; a value, by fields."""
    with pytest.raises(TypeError, match="unhashable"):
        hash(Tally())
    keyed = Keyed()
    assert hash(keyed) == id(keyed)
    assert hash(Sample(name="first", count=1)) == hash(Sample(name="first", count=1))
    assert hash(Sample(name="first", count=1)) != hash(Sample(name="first", count=2))


def test_a_refusal_is_raised_as_the_domain_s_own() -> None:
    """A check's RefusedError reaches the caller as it was raised, not wrapped."""
    with pytest.raises(RefusedError, match=r"^count: must not be negative$"):
        Sample(name="first", count=-1)
    with pytest.raises(RefusedError, match=r"^count: must not be negative$"):
        Pair(first={"name": "first", "count": -1}, second={"name": "second"})


def test_a_refusal_among_other_errors_stays_pydantic_s_error() -> None:
    """When not every error is a refusal, the whole is a fault of the program, as it is."""
    with pytest.raises(ValidationError) as caught:
        Pair(first={"name": "first", "count": -1}, second={"name": "second", "count": UNSHOWN})
    assert [error["loc"] for error in caught.value.errors()] == [("first",), ("second", "count")]
    assert UNSHOWN not in str(caught.value)


def test_chunks_compare_by_identity() -> None:
    """Two indexes' chunks are never equal: an array has no truth value to compare by."""
    matrix = np.zeros((1, 2), dtype=np.float32)
    fields = {
        "documents": (1,),
        "paths": {1: "jira/PRB/PRB-1.md"},
        "updated": {},
        "sections": (1,),
        "offsets": (0,),
        "ends": (4,),
    }
    first, second = ChunkVectors(**fields, matrix=matrix), ChunkVectors(**fields, matrix=matrix)
    assert first != second
    by_chunks = {first: "first", second: "second"}
    assert (by_chunks[first], by_chunks[second]) == ("first", "second")
