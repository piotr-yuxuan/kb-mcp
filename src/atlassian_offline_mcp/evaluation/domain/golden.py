"""A golden file as its author writes it: questions naming the refs that answer them.

Read strictly, as untrusted input: each field of its type, none unknown, and the rules
of plan 011 checked. A refusal names where it is, never what was found there.
"""

from __future__ import annotations

from typing import Self

from pydantic import BaseModel, ConfigDict, Field, RootModel, field_validator, model_validator
from pydantic_core import PydanticCustomError

from atlassian_offline_mcp.evaluation.domain.evaluation import plain
from atlassian_offline_mcp.search.domain.search import WORD

LONGEST_QUESTION = 500
# The type of every refusal of a golden file by its rules.
RULE = "golden"


class GoldenQuestion(BaseModel):
    """A golden question, with the refs that answer it and those that help, as given.

    ``evidence`` maps an expected ref to a phrase of its text; ``groups`` label the
    question, such as its kind of wording or its language.
    """

    model_config = ConfigDict(strict=True, extra="forbid", frozen=True, hide_input_in_errors=True)

    id: str
    question: str
    expected: list[str]
    partial: list[str] = Field(default_factory=list)
    groups: list[str] = Field(default_factory=list)
    evidence: dict[str, str] = Field(default_factory=dict)

    @field_validator("evidence", mode="before")
    @classmethod
    def refs_as_text(cls, value: object) -> object:
        """Refuse a ref that YAML read as a number, since it was not quoted."""
        if isinstance(value, dict) and not all(isinstance(ref, str) for ref in value):
            raise PydanticCustomError(RULE, "refs as text, in quotes")
        return value

    @model_validator(mode="after")
    def follows_the_rules(self) -> Self:
        """Refuse the first rule broken, by its field.

        A question longer than search takes, no expected ref, evidence for a ref not
        expected or without a word, a group named twice or named "all", which the
        averages use.
        """
        faults = {
            f"question: at most {LONGEST_QUESTION} characters": (
                len(self.question) > LONGEST_QUESTION
            ),
            "expected: at least one ref": not self.expected,
            "evidence: only for an expected ref": not set(self.evidence) <= set(self.expected),
            "evidence: a phrase of a word or more": not all(
                WORD.search(plain(phrase)) for phrase in self.evidence.values()
            ),
            'groups: each once, and not "all"': (
                len(set(self.groups)) != len(self.groups) or "all" in self.groups
            ),
        }
        if fault := next((name for name, found in faults.items() if found), None):
            raise PydanticCustomError(RULE, fault)
        return self


class Golden(RootModel[list[GoldenQuestion]]):
    """A golden file: a list of questions, at least one, each with an id of its own."""

    model_config = ConfigDict(strict=True, frozen=True, hide_input_in_errors=True)

    @model_validator(mode="after")
    def asks_each_once(self) -> Self:
        """Refuse a file without questions, or that gives an id twice."""
        ids = [question.id for question in self.root]
        if not ids or len(set(ids)) != len(ids):
            raise PydanticCustomError(RULE, "no question, or an id given twice")
        return self
