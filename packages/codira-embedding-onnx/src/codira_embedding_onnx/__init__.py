"""Native ONNX Runtime embedding engine for codira."""

from __future__ import annotations

import math
from importlib import import_module
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from codira.config import DEFAULT_EMBEDDING_BATCH_SIZE, load_effective_config
from codira.contracts import EmbeddingEngineError, EmbeddingEngineSpec
from codira.plugin_config import plugin_json_schema

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from codira.contracts import EmbeddingEngine

__all__ = ["OnnxEmbeddingEngine", "build_engine"]

PACKAGE_VERSION = "1.0.2"
DEFAULT_PROVIDER = "CPUExecutionProvider"
DEFAULT_PRECISION = "float32"
DEFAULT_MAX_TOKENS = 512


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
    max_tokens : int
        Maximum tokenizer sequence length, or ``0`` to disable truncation.
    batch_size : int
        Maximum number of texts to pass to one ONNX Runtime invocation.
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
    max_tokens: int = DEFAULT_MAX_TOKENS
    batch_size: int = DEFAULT_EMBEDDING_BATCH_SIZE
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

    Raises
    ------
    codira.contracts.EmbeddingEngineError
        Raised when the configured value is not a string or a required value
        is empty.
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

    Raises
    ------
    codira.contracts.EmbeddingEngineError
        Raised when the configured value is not a non-negative integer.
    """
    value = config.get(key, default)
    if not isinstance(value, int) or value < 0:
        msg = f"plugins.embedding-onnx.{key} must be a non-negative integer."
        raise EmbeddingEngineError(msg)
    return value


def _runtime_batch_size(config: Mapping[str, object]) -> int:
    """
    Return the effective ONNX runtime batch size.

    Parameters
    ----------
    config : collections.abc.Mapping[str, object]
        Plugin configuration table enriched by core runtime metadata.

    Returns
    -------
    int
        Positive runtime batch size.

    Raises
    ------
    codira.contracts.EmbeddingEngineError
        Raised when the injected runtime batch size is not positive.
    """
    value = config.get("_codira_batch_size", DEFAULT_EMBEDDING_BATCH_SIZE)
    if not isinstance(value, int) or value <= 0:
        msg = "plugins.embedding-onnx._codira_batch_size must be a positive integer."
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

    Raises
    ------
    codira.contracts.EmbeddingEngineError
        Raised when the configured value is not boolean.
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
        max_tokens=_int_config(config, "max_tokens", default=DEFAULT_MAX_TOKENS),
        batch_size=_runtime_batch_size(config),
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


def _enable_tokenizer_truncation(tokenizer: object, max_tokens: int) -> None:
    """
    Enable tokenizer-side truncation when supported.

    Parameters
    ----------
    tokenizer : object
        Tokenizers tokenizer instance.
    max_tokens : int
        Maximum sequence length accepted by the ONNX model.

    Returns
    -------
    None
        The tokenizer is configured in place.

    Raises
    ------
    codira.contracts.EmbeddingEngineError
        Raised when the tokenizer cannot be configured for truncation.
    """
    if max_tokens <= 0:
        return
    try:
        cast("Any", tokenizer).enable_truncation(max_length=max_tokens)
    except TypeError:
        cast("Any", tokenizer).enable_truncation(max_tokens)
    except AttributeError as exc:
        msg = "The configured ONNX tokenizer does not support truncation."
        raise EmbeddingEngineError(msg) from exc


def _truncate_encoding(encoding: object, max_tokens: int) -> object:
    """
    Truncate one encoded sequence when tokenizer-side truncation was insufficient.

    Parameters
    ----------
    encoding : object
        Tokenizers encoding object.
    max_tokens : int
        Maximum sequence length accepted by the ONNX model.

    Returns
    -------
    object
        The original encoding, possibly truncated in place.

    Raises
    ------
    codira.contracts.EmbeddingEngineError
        Raised when an over-limit encoding cannot be truncated.
    """
    if max_tokens <= 0:
        return encoding
    token_count = len(cast("Any", encoding).ids)
    if token_count <= max_tokens:
        return encoding
    try:
        cast("Any", encoding).truncate(max_tokens)
    except TypeError:
        cast("Any", encoding).truncate(max_tokens, 0)
    except AttributeError as exc:
        msg = (
            "The configured ONNX tokenizer produced "
            f"{token_count} tokens, exceeding max_tokens={max_tokens}, "
            "but its encoding object does not support truncation."
        )
        raise EmbeddingEngineError(msg) from exc
    return encoding


def _encode_texts(
    tokenizer: object,
    texts: Sequence[str],
    *,
    max_tokens: int,
) -> Sequence[object]:
    """
    Encode texts with an explicit sequence-length cap.

    Parameters
    ----------
    tokenizer : object
        Tokenizers tokenizer instance.
    texts : collections.abc.Sequence[str]
        Text payloads to encode.
    max_tokens : int
        Maximum sequence length accepted by the ONNX model, or ``0`` to disable
        truncation.

    Returns
    -------
    collections.abc.Sequence[object]
        Tokenizer encodings safe to pass to ONNX Runtime.
    """
    _enable_tokenizer_truncation(tokenizer, max_tokens)
    encoded = cast("Sequence[object]", cast("Any", tokenizer).encode_batch(list(texts)))
    if max_tokens <= 0:
        return encoded
    return [_truncate_encoding(item, max_tokens) for item in encoded]


def _chunked_texts(texts: Sequence[str], batch_size: int) -> list[Sequence[str]]:
    """
    Split text payloads into bounded ONNX Runtime batches.

    Parameters
    ----------
    texts : collections.abc.Sequence[str]
        Text payloads to embed.
    batch_size : int
        Maximum number of texts per runtime invocation.

    Returns
    -------
    list[collections.abc.Sequence[str]]
        Ordered text batches.
    """
    return [
        texts[index : index + batch_size] for index in range(0, len(texts), batch_size)
    ]


def _runtime_input_feed(
    session: object, encoded: Sequence[object]
) -> Mapping[str, object]:
    """
    Build the ONNX input feed required by one session.

    Parameters
    ----------
    session : object
        Loaded ONNX Runtime inference session.
    encoded : collections.abc.Sequence[object]
        Tokenizer encodings for one batch.

    Returns
    -------
    collections.abc.Mapping[str, object]
        Input arrays keyed by ONNX graph input name.

    Raises
    ------
    EmbeddingEngineError
        Raised when the model requires an unsupported input tensor.
    """
    try:
        import numpy as np
    except ImportError as exc:
        msg = "Install codira with the ONNX embedding engine dependencies."
        raise EmbeddingEngineError(msg) from exc

    input_ids = [list(cast("Any", item).ids) for item in encoded]
    max_tokens = max((len(ids) for ids in input_ids), default=0)
    input_ids = [ids + [0] * (max_tokens - len(ids)) for ids in input_ids]
    attention_mask = [
        list(cast("Any", item).attention_mask)
        + [0] * (max_tokens - len(cast("Any", item).attention_mask))
        for item in encoded
    ]
    type_ids = []
    for item in encoded:
        item_type_ids = list(
            getattr(item, "type_ids", None) or [0] * len(cast("Any", item).ids)
        )
        type_ids.append(item_type_ids + [0] * (max_tokens - len(item_type_ids)))
    available_inputs = {
        cast("Any", input_info).name for input_info in cast("Any", session).get_inputs()
    }
    prepared_inputs: dict[str, object] = {
        "input_ids": np.asarray(input_ids, dtype=np.int64),
        "attention_mask": np.asarray(attention_mask, dtype=np.int64),
        "token_type_ids": np.asarray(type_ids, dtype=np.int64),
    }
    unsupported_inputs = sorted(available_inputs.difference(prepared_inputs))
    if unsupported_inputs:
        joined = ", ".join(unsupported_inputs)
        msg = f"Unsupported ONNX embedding model inputs: {joined}"
        raise EmbeddingEngineError(msg)
    return {
        name: value
        for name, value in prepared_inputs.items()
        if name in available_inputs
    }


class OnnxEmbeddingEngine:
    """
    Native ONNX Runtime embedding engine.

    Parameters
    ----------
    None
    """

    name = "onnx"
    version = PACKAGE_VERSION

    def configuration_json_schema(self) -> Mapping[str, object]:
        """
        Return the ONNX embedding plugin configuration schema.

        Parameters
        ----------
        None

        Returns
        -------
        collections.abc.Mapping[str, object]
            Strict JSON Schema for plugin-specific ONNX Runtime options.
        """
        return plugin_json_schema(
            {
                "model_path": {
                    "type": "string",
                    "default": "",
                    "description": "Path to the local ONNX model artifact.",
                },
                "tokenizer_path": {
                    "type": "string",
                    "default": "",
                    "description": "Path to the local tokenizer JSON artifact.",
                },
                "provider": {
                    "type": "string",
                    "default": DEFAULT_PROVIDER,
                    "description": "ONNX Runtime execution provider name.",
                },
                "precision": {
                    "type": "string",
                    "default": DEFAULT_PRECISION,
                    "description": "Vector precision label used in embedding identity.",
                },
                "normalize": {
                    "type": "boolean",
                    "default": True,
                    "description": "Whether pooled vectors should be L2-normalized.",
                },
                "max_tokens": {
                    "type": "integer",
                    "minimum": 0,
                    "default": DEFAULT_MAX_TOKENS,
                    "description": "Tokenizer truncation limit; zero disables truncation.",
                },
                "intra_op_num_threads": {
                    "type": "integer",
                    "minimum": 0,
                    "default": 0,
                    "description": "ONNX Runtime intra-op thread override; zero leaves default.",
                },
                "inter_op_num_threads": {
                    "type": "integer",
                    "minimum": 0,
                    "default": 0,
                    "description": "ONNX Runtime inter-op thread override; zero leaves default.",
                },
            }
        )

    def configure(self, config: Mapping[str, object]) -> None:
        """
        Apply ONNX embedding configuration.

        Parameters
        ----------
        config : collections.abc.Mapping[str, object]
            Namespaced embedding plugin configuration table.

        Returns
        -------
        None
            Runtime calls receive the effective plugin config explicitly.
        """

        del config

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

        Raises
        ------
        TypeError
            Raised when core-injected identity metadata has an invalid type.
        """
        onnx_config = _engine_config(config)
        embeddings = load_effective_config().embeddings
        model = config.get("_codira_model", embeddings.model)
        model_version = config.get("_codira_model_version", embeddings.version)
        dimension = config.get("_codira_dimension", embeddings.dimension)
        if not isinstance(model, str):
            msg = "plugins.embedding-onnx._codira_model must be a string."
            raise TypeError(msg)
        if not isinstance(model_version, str):
            msg = "plugins.embedding-onnx._codira_model_version must be a string."
            raise TypeError(msg)
        if not isinstance(dimension, int):
            msg = "plugins.embedding-onnx._codira_dimension must be an integer."
            raise TypeError(msg)
        return EmbeddingEngineSpec(
            engine=self.name,
            engine_version=self.version,
            model=model,
            model_version=model_version,
            dimension=dimension,
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

        Raises
        ------
        codira.contracts.EmbeddingEngineError
            Raised when configured ONNX artifacts are missing.
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
        vectors: list[list[float]] = []
        for batch in _chunked_texts(texts, onnx_config.batch_size):
            encoded = _encode_texts(
                tokenizer,
                batch,
                max_tokens=onnx_config.max_tokens,
            )
            input_feed = _runtime_input_feed(session, encoded)
            attention_mask = cast("Any", input_feed["attention_mask"]).tolist()
            outputs = session.run(None, input_feed)
            vectors.extend(
                _pool_outputs(
                    outputs[0],
                    attention_mask=attention_mask,
                    normalize=onnx_config.normalize,
                )
            )
        return vectors

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

    Raises
    ------
    codira.contracts.EmbeddingEngineError
        Raised when ONNX Runtime or tokenizer dependencies are missing.
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

    Raises
    ------
    codira.contracts.EmbeddingEngineError
        Raised when NumPy is unavailable.
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
