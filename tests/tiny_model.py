"""A tiny embedding model, built at test time and run through the real adapter.

Its graph looks each token up in a table, as the first layer of a real model does, and
its tokeniser splits words. Words of one concept share a row, so that a query without a
word of its target still finds it; every other word is unknown and shares one row
apart. The padding row is not zero, so that pooling that forgets the mask shows.
"""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING, Literal

import numpy as np
import onnx
from onnx import TensorProto, helper, numpy_helper
from tokenizers import Tokenizer, models, normalizers, pre_tokenizers

from atlassian_offline_mcp.adapters.embedding import CATALOGUE, File, Model

if TYPE_CHECKING:
    from pathlib import Path

    from _pytest.monkeypatch import MonkeyPatch

DIMENSIONS = 16
# Words of one concept mean the same to the tiny model; each concept has its own axis.
CONCEPTS = (
    ("rollback", "revert", "undo", "restore"),
    ("payout", "payouts", "seller", "sellers"),
    ("deploy", "deployment", "release", "rollout"),
    ("holiday", "holidays", "leave", "vacation"),
    ("canteen", "lunch", "cafeteria", "meal"),
    ("alpha",),
    ("beta",),
)
UNKNOWN, PAD = "[UNK]", "[PAD]"
UNKNOWN_AXIS, PAD_AXIS = 14, 15
ENCODER = ("input_ids", "attention_mask", "token_type_ids")
DECODER = ("input_ids", "attention_mask", "position_ids", "past_key_values.0.key")
PAST_HEADS, PAST_WIDTH = 2, 4


def vocabulary() -> dict[str, int]:
    """Give every token its id: padding, the unknown word, then each concept's words."""
    words = [word for concept in CONCEPTS for word in concept]
    return {PAD: 0, UNKNOWN: 1} | {word: number for number, word in enumerate(words, 2)}


def table() -> np.ndarray:
    """Give each token's row: its concept's axis, or the unknown or padding axis."""
    rows = np.zeros((len(vocabulary()), DIMENSIONS), dtype=np.float32)
    rows[0, PAD_AXIS] = 1.0
    rows[1, UNKNOWN_AXIS] = 1.0
    number = 2
    for axis, concept in enumerate(CONCEPTS):
        for _ in concept:
            rows[number, axis] = 1.0
            number += 1
    return rows


def graph(inputs: tuple[str, ...]) -> onnx.ModelProto:
    """Build the graph: a lookup of each input id in the table, for the given inputs."""
    declared = [
        helper.make_tensor_value_info(
            name, TensorProto.FLOAT, ["batch", PAST_HEADS, "past", PAST_WIDTH]
        )
        if name.startswith("past_key_values.")
        else helper.make_tensor_value_info(name, TensorProto.INT64, ["batch", "sequence"])
        for name in inputs
    ]
    output = helper.make_tensor_value_info(
        "last_hidden_state", TensorProto.FLOAT, ["batch", "sequence", DIMENSIONS]
    )
    lookup = helper.make_node("Gather", ["table", "input_ids"], ["last_hidden_state"], axis=0)
    body = helper.make_graph(
        [lookup], "tiny", declared, [output], [numpy_helper.from_array(table(), "table")]
    )
    return helper.make_model(body, opset_imports=[helper.make_opsetid("", 13)], ir_version=8)


def tokenizer() -> Tokenizer:
    """Build a tokeniser of whole words, lower-cased, unknown words as one token."""
    built = Tokenizer(models.WordLevel(vocabulary(), unk_token=UNKNOWN))
    built.normalizer = normalizers.Lowercase()
    built.pre_tokenizer = pre_tokenizers.Whitespace()
    return built


def pinned(path: Path, name: str) -> File:
    """Pin a written file by its content, as the catalogue does."""
    content = path.read_bytes()
    return File(name, hashlib.sha256(content).hexdigest(), len(content))


def tiny(
    models_folder: Path,
    name: str = "tiny",
    pooling: Literal["first", "mean", "last"] = "mean",
    inputs: tuple[str, ...] = ENCODER,
) -> Model:
    """Write a tiny model's files into ``models_folder/name``, and return its entry."""
    folder = models_folder / name
    folder.mkdir(parents=True, exist_ok=True)
    onnx.save(graph(inputs), folder / "model.onnx")
    tokenizer().save(str(folder / "tokenizer.json"))
    return Model(
        name=name,
        repository="tests/tiny",
        revision="0" * 40,
        graph=pinned(folder / "model.onnx", "model.onnx"),
        tokenizer=pinned(folder / "tokenizer.json", "tokenizer.json"),
        pooling=pooling,
        pad=PAD,
        query_prefix="",
        document_prefix="",
        dimensions=DIMENSIONS,
    )


def registered(
    models_folder: Path,
    monkeypatch: MonkeyPatch,
    name: str = "tiny",
    pooling: Literal["first", "mean", "last"] = "mean",
    inputs: tuple[str, ...] = ENCODER,
) -> Model:
    """Write a tiny model and add it to the catalogue for one test."""
    model = tiny(models_folder, name, pooling, inputs)
    monkeypatch.setitem(CATALOGUE, model.name, model)
    return model
