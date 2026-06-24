"""Package-local tests for the first-party ONNX embedding engine."""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any, cast

import pytest

from codira.contracts import EmbeddingEngine, EmbeddingEngineError
from codira_embedding_onnx import OnnxEmbeddingEngine, _runtime_input_feed, build_engine


def test_onnx_package_declares_expected_entry_point() -> None:
    """
    Keep package metadata aligned to the embedding engine entry-point contract.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test asserts the package advertises the expected engine factory.
    """
    pyproject_path = Path(__file__).resolve().parents[1] / "pyproject.toml"
    project = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))

    assert project["project"]["version"] == "1.0.0"
    assert project["project"]["entry-points"]["codira.embedding_engines"] == {
        "onnx": "codira_embedding_onnx:build_engine"
    }


def test_onnx_package_builds_expected_engine() -> None:
    """
    Keep the package-local factory aligned to the published engine name.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test asserts the factory returns the expected engine type and name.
    """
    engine = build_engine()

    assert isinstance(engine, OnnxEmbeddingEngine)
    assert isinstance(engine, EmbeddingEngine)
    assert engine.name == "onnx"


def test_onnx_engine_requires_explicit_artifact_paths() -> None:
    """
    Reject native ONNX runtime use without explicit local artifacts.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test asserts hidden downloads are not attempted.
    """
    engine = OnnxEmbeddingEngine()

    with pytest.raises(EmbeddingEngineError, match="model_path"):
        engine.provision({})


def test_onnx_runtime_input_feed_supplies_token_type_ids() -> None:
    """
    Supply token type IDs when an ONNX graph declares that input.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test asserts BGE/Nomic-style input signatures receive all required
        integer tensors.
    """

    class _Input:
        """
        Minimal ONNX input descriptor test double.

        Parameters
        ----------
        name : str
            Input tensor name.
        """

        def __init__(self, name: str) -> None:
            self.name = name

    class _Session:
        """
        Minimal ONNX session test double.

        Parameters
        ----------
        None
        """

        def get_inputs(self) -> list[_Input]:
            """
            Return a BGE/Nomic-style input signature.

            Parameters
            ----------
            None

            Returns
            -------
            list[_Input]
                Declared ONNX input descriptors.
            """
            return [
                _Input("input_ids"),
                _Input("attention_mask"),
                _Input("token_type_ids"),
            ]

    class _Encoding:
        """
        Minimal tokenizer encoding test double.

        Parameters
        ----------
        None
        """

        def __init__(
            self,
            ids: list[int],
            attention_mask: list[int],
            type_ids: list[int],
        ) -> None:
            self.ids = ids
            self.attention_mask = attention_mask
            self.type_ids = type_ids

    feed = _runtime_input_feed(
        _Session(),
        [
            _Encoding([101, 102], [1, 1], [0, 0]),
            _Encoding([101], [1], [0]),
        ],
    )

    assert sorted(feed) == ["attention_mask", "input_ids", "token_type_ids"]
    assert cast(Any, feed["input_ids"]).tolist() == [[101, 102], [101, 0]]
    assert cast(Any, feed["attention_mask"]).tolist() == [[1, 1], [1, 0]]
    assert cast(Any, feed["token_type_ids"]).tolist() == [[0, 0], [0, 0]]


def test_onnx_engine_batches_runtime_invocations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Keep native ONNX inference bounded by the configured embedding batch size.

    Parameters
    ----------
    monkeypatch : pytest.MonkeyPatch
        Fixture used to replace the expensive ONNX Runtime session.

    Returns
    -------
    None
        The test asserts a large text list is split before session execution.
    """
    import numpy as np
    import codira_embedding_onnx as onnx_module

    class _Input:
        def __init__(self, name: str) -> None:
            self.name = name

    class _Session:
        def __init__(self) -> None:
            self.batch_sizes: list[int] = []

        def get_inputs(self) -> list[_Input]:
            return [_Input("input_ids"), _Input("attention_mask")]

        def run(
            self,
            output_names: object,
            input_feed: dict[str, object],
        ) -> list[object]:
            del output_names
            input_ids = cast(Any, input_feed["input_ids"])
            batch_size = int(input_ids.shape[0])
            token_count = int(input_ids.shape[1])
            self.batch_sizes.append(batch_size)
            assert batch_size <= 2
            return [np.ones((batch_size, token_count, 3), dtype=np.float32)]

    class _Encoding:
        def __init__(self, token_count: int) -> None:
            self.ids = list(range(token_count))
            self.attention_mask = [1] * token_count
            self.type_ids = [0] * token_count

        def truncate(self, max_tokens: int, stride: int = 0) -> None:
            del stride
            self.ids = self.ids[:max_tokens]
            self.attention_mask = self.attention_mask[:max_tokens]
            self.type_ids = self.type_ids[:max_tokens]

    class _Tokenizer:
        def enable_truncation(self, max_length: int) -> None:
            self.max_length = max_length

        def encode_batch(self, texts: list[str]) -> list[_Encoding]:
            return [_Encoding(len(text.split())) for text in texts]

    session = _Session()
    tokenizer = _Tokenizer()
    monkeypatch.setattr(
        onnx_module,
        "_load_runtime",
        lambda config: (session, tokenizer),
    )

    engine = OnnxEmbeddingEngine()
    vectors = engine.embed_texts(
        ["one two three"] * 5,
        {
            "model_path": "model.onnx",
            "tokenizer_path": "tokenizer.json",
            "normalize": False,
            "max_tokens": 512,
            "_codira_batch_size": 2,
        },
    )

    assert session.batch_sizes == [2, 2, 1]
    assert len(vectors) == 5
    assert all(vector == [1.0, 1.0, 1.0] for vector in vectors)
