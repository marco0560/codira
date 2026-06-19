"""Native ONNX Runtime embedding engine for codira."""

from __future__ import annotations

import math
from importlib import import_module
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from codira.config import load_effective_config
from codira.contracts import EmbeddingEngineError, EmbeddingEngineSpec

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from codira.contracts import EmbeddingEngine

__all__ = ["OnnxEmbeddingEngine", "build_engine"]

PACKAGE_VERSION = "1.0.0"
DEFAULT_PROVIDER = "CPUExecutionProvider"
DEFAULT_PRECISION = "float32"


@dataclass(frozen=True)
class _OnnxEngineConfig:
    """
    Normalized ONNX engine configuration.

    Parameters
    ----------
    model_path : pathlib.Path
        Local ONNX model file.
    tokenizer_path : pathlib.Path
        Local tokenizer JSON file.
    provider : str
        ONNX Runtime execution provider.
    precision : str
        Vector precision or quantization label.
    normalize : bool
        Whether returned vectors are L2-normalized.
    intra_op_num_threads : int
        ONNX Runtime intra-op thread count, or ``0`` for default.
    inter_op_num_threads : int
        ONNX Runtime inter-op thread count, or ``0`` for default.
    """

    model_path: Path
    tokenizer_path: Path
    provider: str = DEFAULT_PROVIDER
    precision: str = DEFAULT_PRECISION
    normalize: bool = True
    intra_op_num_threads: int = 0
    inter_op_num_threads: int = 0


def _string_config(
    config: Mapping[str, object],
    key: str,
    *,
    required: bool = False,
    default: str = "",
) -> str:
    """
    Return one string plugin configuration value.

    Parameters
    ----------
    config : collections.abc.Mapping[str, object]
        Plugin configuration table.
    key : str
        Key to read.
    required : bool, optional
        Whether an empty value should raise.
    default : str, optional
        Default value used when the key is absent.

    Returns
    -------
    str
        Normalized string value.
    """
    value = config.get(key, default)
    if not isinstance(value, str):
        msg = f"plugins.embedding-onnx.{key} must be a string."
        raise EmbeddingEngineError(msg)
    normalized = value.strip()
    if required and not normalized:
        msg = f"plugins.embedding-onnx.{key} must be configured."
        raise EmbeddingEngineError(msg)
    return normalized


def _int_config(
    config: Mapping[str, object],
    key: str,
    *,
    default: int = 0,
) -> int:
    """
    Return one non-negative integer plugin configuration value.

    Parameters
    ----------
    config : collections.abc.Mapping[str, object]
        Plugin configuration table.
    key : str
        Key to read.
    default : int, optional
        Default value used when the key is absent.

    Returns
    -------
    int
        Non-negative integer value.
    """
    value = config.get(key, default)
    if not isinstance(value, int) or value < 0:
        msg = f"plugins.embedding-onnx.{key} must be a non-negative integer."
        raise EmbeddingEngineError(msg)
    return value


def _bool_config(
    config: Mapping[str, object],
    key: str,
    *,
    default: bool,
) -> bool:
    """
    Return one boolean plugin configuration value.

    Parameters
    ----------
    config : collections.abc.Mapping[str, object]
        Plugin configuration table.
    key : str
        Key to read.
    default : bool
        Default value used when the key is absent.

    Returns
    -------
    bool
        Boolean value.
    """
    value = config.get(key, default)
    if not isinstance(value, bool):
        msg = f"plugins.embedding-onnx.{key} must be a boolean."
        raise EmbeddingEngineError(msg)
    return value


def _engine_config(config: Mapping[str, object]) -> _OnnxEngineConfig:
    """
    Normalize ONNX plugin configuration.

    Parameters
    ----------
    config : collections.abc.Mapping[str, object]
        Plugin configuration table.

    Returns
    -------
    _OnnxEngineConfig
        Normalized ONNX runtime settings.
    """
    return _OnnxEngineConfig(
        model_path=Path(_string_config(config, "model_path", required=True)),
        tokenizer_path=Path(_string_config(config, "tokenizer_path", required=True)),
        provider=_string_config(config, "provider", default=DEFAULT_PROVIDER),
        precision=_string_config(config, "precision", default=DEFAULT_PRECISION),
        normalize=_bool_config(config, "normalize", default=True),
        intra_op_num_threads=_int_config(config, "intra_op_num_threads"),
        inter_op_num_threads=_int_config(config, "inter_op_num_threads"),
    )


def _l2_normalize(vector: list[float]) -> list[float]:
    """
    L2-normalize one vector.

    Parameters
    ----------
    vector : list[float]
        Dense vector values.

    Returns
    -------
    list[float]
        Normalized vector, or the original zero vector.
    """
    norm = math.sqrt(sum(value * value for value in vector))
    if norm == 0.0:
        return vector
    return [value / norm for value in vector]


class OnnxEmbeddingEngine:
    """
    Native ONNX Runtime embedding engine.

    Parameters
    ----------
    None
    """

    name = "onnx"
    version = PACKAGE_VERSION

    def spec(self, config: Mapping[str, object]) -> EmbeddingEngineSpec:
        """
        Return the active ONNX vector identity.

        Parameters
        ----------
        config : collections.abc.Mapping[str, object]
            Engine-specific configuration table.

        Returns
        -------
        codira.contracts.EmbeddingEngineSpec
            ONNX engine vector identity.
        """
        onnx_config = _engine_config(config)
        embeddings = load_effective_config().embeddings
        return EmbeddingEngineSpec(
            engine=self.name,
            engine_version=self.version,
            model=embeddings.model,
            model_version=embeddings.version,
            dimension=embeddings.dimension,
            precision=onnx_config.precision,
        )

    def provision(self, config: Mapping[str, object], *, quiet: bool = False) -> None:
        """
        Verify configured ONNX artifacts exist locally.

        Parameters
        ----------
        config : collections.abc.Mapping[str, object]
            Engine-specific configuration table.
        quiet : bool, optional
            Whether operator-facing output should be suppressed.

        Returns
        -------
        None
            Artifact paths exist or an engine error is raised.
        """
        del quiet
        onnx_config = _engine_config(config)
        missing = [
            str(path)
            for path in (onnx_config.model_path, onnx_config.tokenizer_path)
            if not path.exists()
        ]
        if missing:
            joined = ", ".join(missing)
            msg = f"Missing ONNX embedding artifacts: {joined}"
            raise EmbeddingEngineError(msg)

    def embed_texts(
        self,
        texts: Sequence[str],
        config: Mapping[str, object],
    ) -> list[list[float]]:
        """
        Embed texts with native ONNX Runtime.

        Parameters
        ----------
        texts : collections.abc.Sequence[str]
            Text payloads to embed.
        config : collections.abc.Mapping[str, object]
            Engine-specific configuration table.

        Returns
        -------
        list[list[float]]
            One vector per input payload.
        """
        onnx_config = _engine_config(config)
        if not texts:
            return []
        session, tokenizer = _load_runtime(onnx_config)
        encoded = tokenizer.encode_batch(list(texts))
        input_ids = [item.ids for item in encoded]
        attention_mask = [item.attention_mask for item in encoded]
        outputs = session.run(
            None,
            {
                "input_ids": input_ids,
                "attention_mask": attention_mask,
            },
        )
        return _pool_outputs(
            outputs[0],
            attention_mask=attention_mask,
            normalize=onnx_config.normalize,
        )

    def reset_runtime_caches(self) -> None:
        """
        Clear process-local ONNX Runtime caches.

        Parameters
        ----------
        None

        Returns
        -------
        None
            Cached sessions and tokenizers are discarded.
        """
        _load_runtime.cache_clear()


@lru_cache(maxsize=4)
def _load_runtime(config: _OnnxEngineConfig) -> tuple[Any, Any]:
    """
    Load an ONNX Runtime session and tokenizer.

    Parameters
    ----------
    config : _OnnxEngineConfig
        Normalized ONNX runtime configuration.

    Returns
    -------
    tuple[typing.Any, typing.Any]
        ONNX Runtime session and tokenizer.
    """
    try:
        onnxruntime = import_module("onnxruntime")
        tokenizer_module = import_module("tokenizers")
    except ImportError as exc:
        msg = "Install codira with the ONNX embedding engine dependencies."
        raise EmbeddingEngineError(msg) from exc

    options = onnxruntime.SessionOptions()
    if config.intra_op_num_threads:
        options.intra_op_num_threads = config.intra_op_num_threads
    if config.inter_op_num_threads:
        options.inter_op_num_threads = config.inter_op_num_threads
    session = onnxruntime.InferenceSession(
        str(config.model_path),
        sess_options=options,
        providers=[config.provider],
    )
    Tokenizer = tokenizer_module.Tokenizer
    tokenizer = Tokenizer.from_file(str(config.tokenizer_path))
    return session, tokenizer


def _pool_outputs(
    token_embeddings: object,
    *,
    attention_mask: list[list[int]],
    normalize: bool,
) -> list[list[float]]:
    """
    Mean-pool token embeddings with the attention mask.

    Parameters
    ----------
    token_embeddings : object
        ONNX output shaped as batch x tokens x dimension.
    attention_mask : list[list[int]]
        Token attention masks.
    normalize : bool
        Whether vectors should be L2-normalized.

    Returns
    -------
    list[list[float]]
        One pooled vector per input text.
    """
    try:
        import numpy as np
    except ImportError as exc:
        msg = "Install codira with the ONNX embedding engine dependencies."
        raise EmbeddingEngineError(msg) from exc

    embeddings = np.asarray(token_embeddings, dtype=np.float32)
    mask = np.asarray(attention_mask, dtype=np.float32)
    while mask.ndim < embeddings.ndim:
        mask = np.expand_dims(mask, axis=-1)
    summed = (embeddings * mask).sum(axis=1)
    counts = np.maximum(mask.sum(axis=1), 1.0)
    pooled = summed / counts
    vectors = cast("list[list[float]]", pooled.astype(float).tolist())
    if not normalize:
        return vectors
    return [_l2_normalize(vector) for vector in vectors]


def build_engine() -> EmbeddingEngine:
    """
    Build the native ONNX Runtime embedding engine.

    Parameters
    ----------
    None

    Returns
    -------
    codira.contracts.EmbeddingEngine
        ONNX embedding engine instance.
    """
    return OnnxEmbeddingEngine()
