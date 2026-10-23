"""Secrets kept out of what a run logs: what a key naming one holds is redacted.

A key names a secret when its words, in lower case and split at ``_``, ``-`` and ``.``,
hold ``authorization``, ``cookie``, ``token``, ``password`` or ``secret``, or ``api``
then ``key``. A word matches whole: ``Set-Cookie`` and ``x-api-key`` name a secret,
``max_tokens`` none.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from itertools import pairwise
from typing import cast

REDACTED = "[redacted]"
# The words that name a secret on their own; ``api`` names one only before ``key``.
SECRET_WORDS = frozenset({"authorization", "cookie", "token", "password", "secret"})
WORD_SEPARATORS = re.compile(r"[-_.]+")


def redacted(value: object) -> object:
    """Give a value back with what each key naming a secret holds, at any depth, redacted.

    A mapping comes back as a new dict, a list as a new list and a tuple as a new tuple,
    so that an exception's ``exc_info`` stays one and the value given is left as it was;
    any other value comes back as it is.
    """
    if isinstance(value, Mapping):
        kept: dict[object, object] = {}
        for key, item in value.items():
            words = WORD_SEPARATORS.split(str(key).lower())
            secret = not SECRET_WORDS.isdisjoint(words) or ("api", "key") in pairwise(words)
            kept[key] = REDACTED if secret else redacted(item)
        return kept
    if isinstance(value, list):
        return [redacted(item) for item in value]
    if isinstance(value, tuple):
        return tuple(redacted(item) for item in value)
    return value


def redact_secrets(
    _logger: object, _method_name: str, event_dict: Mapping[str, object]
) -> dict[str, object]:
    """Redact an event's secrets: a structlog processor, placed before every sink."""
    return cast("dict[str, object]", redacted(event_dict))
