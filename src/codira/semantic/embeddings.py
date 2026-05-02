"""Deterministic local embedding backend for codira.

Responsibilities
----------------
- Define backend metadata such as model name, version, and vector dimension.
- Load and provision sentence-transformers models, applying offline and dependency checks.
- Normalize embedding vectors, serialize/deserialize them, and register provisioning helpers.

Design principles
-----------------
Backend logic keeps provisioning deterministic, caches models locally, and surfaces actionable errors with remediation hints.

Architectural role
------------------
This module belongs to the **semantic backend layer** that powers embedding storage and retrieval across codira.
"""

from __future__ import annotations

import contextlib
import io
import os
import struct
import sys
from dataclasses import dataclass
from functools import lru_cache
from importlib import import_module
from typing import TYPE_CHECKING, Protocol, cast

if TYPE_CHECKING:
    from collections.abc import Sequence

    class _EmbeddingVector(Protocol):
        def tolist(self) -> list[float]: ...

    class _EmbeddingArray(Protocol):
        def __getitem__(self, index: int) -> _EmbeddingVector: ...

        def __len__(self) -> int: ...

    class _EmbeddingModel(Protocol):
        def get_sentence_embedding_dimension(self) -> int: ...
        def get_embedding_dimension(self) -> int: ...

        def encode(
            self,
            sentences: Sequence[str],
            *,
            batch_size: int,
            convert_to_numpy: bool,
            normalize_embeddings: bool,
            show_progress_bar: bool,
        ) -> _EmbeddingArray: ...

    class _SentenceTransformerFactory(Protocol):
        def __call__(
            self,
            model_name: str,
            *,
            device: str,
            local_files_only: bool,
        ) -> _EmbeddingModel: ...

    class _TransformersLogging(Protocol):
        def set_verbosity_error(self) -> None: ...


EMBEDDING_BACKEND = "sentence-transformers/all-MiniLM-L6-v2"
EMBEDDING_VERSION = "1"
EMBEDDING_DIM = 384
DEFAULT_EMBEDDING_BATCH_SIZE = 32
EMBEDDING_BATCH_SIZE_ENV_VAR = "CODIRA_EMBED_BATCH_SIZE"
EMBEDDING_DEVICE_ENV_VAR = "CODIRA_EMBED_DEVICE"
TORCH_NUM_THREADS_ENV_VAR = "CODIRA_TORCH_NUM_THREADS"
TORCH_NUM_INTEROP_THREADS_ENV_VAR = "CODIRA_TORCH_NUM_INTEROP_THREADS"
_DEPENDENCY_INSTALL_HINT = (
    "Install codira with the 'semantic' extra. "
    "For editable installs from another repository, use "
    "'pip install -e ../codira[semantic]'."
)


class EmbeddingBackendError(RuntimeError):
    """
    Stable operator-facing error raised by the embedding backend.

    Parameters
    ----------
    message : str
        Human-readable provisioning or dependency error.
    """


@dataclass(frozen=True)
class EmbeddingBackendSpec:
    """
    Stable metadata describing the active embedding backend.

    Parameters
    ----------
    name : str
        Backend identifier stored in the index.
    version : str
        Backend-specific version used for explicit invalidation.
    dim : int
        Fixed vector dimensionality.
    """

    name: str
    version: str
    dim: int


def get_embedding_backend() -> EmbeddingBackendSpec:
    """
    Return the active embedding backend specification.

    Parameters
    ----------
    None

    Returns
    -------
    EmbeddingBackendSpec
        Stable backend metadata used by indexing and retrieval.
    """
    return EmbeddingBackendSpec(
        name=EMBEDDING_BACKEND,
        version=EMBEDDING_VERSION,
        dim=EMBEDDING_DIM,
    )


def _dependency_error(message: str) -> EmbeddingBackendError:
    """
    Build a stable runtime error for embedding backend provisioning failures.

    Parameters
    ----------
    message : str
        Specific failure reason to append.

    Returns
    -------
    EmbeddingBackendError
        Provisioning error with a repository-specific remediation hint.
    """
    return EmbeddingBackendError(
        "The semantic embedding backend requires the optional 'semantic' "
        "dependency set and a locally available model artifact for "
        f"{EMBEDDING_BACKEND}. {message}"
    )


def _wrap_load_error(exc: OSError | RuntimeError) -> EmbeddingBackendError:
    """
    Convert low-level model-loading failures into a stable operator error.

    Parameters
    ----------
    exc : OSError | RuntimeError
        Original model-loading exception.

    Returns
    -------
    EmbeddingBackendError
        Concise error suitable for CLI reporting.
    """
    return _dependency_error(
        "Automatic model provisioning failed. "
        "Check network access or prefetch the artifact with "
        "'python ../codira/scripts/provision_embedding_model.py'. "
        f"Loader details: {exc}"
    )


def _configure_embedding_environment(*, offline: bool) -> None:
    """
    Configure process-local environment variables for model loading.

    Parameters
    ----------
    offline : bool
        Whether model loading should require local artifacts only.

    Returns
    -------
    None
        Environment variables are updated in place for the current process.
    """
    os.environ["HF_HUB_OFFLINE"] = "1" if offline else "0"
    os.environ["TRANSFORMERS_OFFLINE"] = "1" if offline else "0"
    os.environ.setdefault("TRANSFORMERS_VERBOSITY", "error")
    os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
    os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")


def _environment_int(name: str, *, minimum: int) -> int | None:
    """
    Read one positive integer environment variable deterministically.

    Parameters
    ----------
    name : str
        Environment variable name to inspect.
    minimum : int
        Lowest accepted integer value.

    Returns
    -------
    int | None
        Parsed integer value, or ``None`` when the variable is unset.

    Raises
    ------
    EmbeddingBackendError
        If the configured value is not a valid integer within range.
    """
    raw_value = os.getenv(name)
    if raw_value is None:
        return None

    stripped = raw_value.strip()
    if not stripped:
        return None

    try:
        parsed = int(stripped)
    except ValueError as exc:
        msg = f"{name} must be an integer greater than or equal to {minimum}."
        raise EmbeddingBackendError(msg) from exc

    if parsed < minimum:
        msg = f"{name} must be an integer greater than or equal to {minimum}."
        raise EmbeddingBackendError(msg)

    return parsed


def _configured_embedding_batch_size() -> int:
    """
    Return the configured batch size for embedding generation.

    Parameters
    ----------
    None

    Returns
    -------
    int
        Batch size used for sentence-transformers encode calls.
    """
    configured = _environment_int(EMBEDDING_BATCH_SIZE_ENV_VAR, minimum=1)
    if configured is None:
        return DEFAULT_EMBEDDING_BATCH_SIZE
    return configured


def _configured_embedding_device() -> str:
    """
    Return the configured sentence-transformers device string.

    Parameters
    ----------
    None

    Returns
    -------
    str
        Device string passed to the model loader.
    """
    configured = os.getenv(EMBEDDING_DEVICE_ENV_VAR, "").strip()
    if configured:
        return configured
    return "cpu"


def _configure_torch_runtime() -> None:
    """
    Apply optional Torch thread overrides before model inference begins.

    Parameters
    ----------
    None

    Returns
    -------
    None
        Torch runtime settings are updated in place when configured.

    Raises
    ------
    EmbeddingBackendError
        If Torch rejects the configured threading values.
    """
    try:
        import torch
    except ImportError:
        return

    num_threads = _environment_int(TORCH_NUM_THREADS_ENV_VAR, minimum=1)
    num_interop_threads = _environment_int(
        TORCH_NUM_INTEROP_THREADS_ENV_VAR,
        minimum=1,
    )

    try:
        if num_threads is not None:
            torch.set_num_threads(num_threads)
        if num_interop_threads is not None:
            torch.set_num_interop_threads(num_interop_threads)
    except RuntimeError as exc:
        msg = f"Failed to apply configured Torch runtime settings. Details: {exc}"
        raise EmbeddingBackendError(msg) from exc


@lru_cache(maxsize=1)
def _configure_torch_runtime_once() -> None:
    """
    Apply Torch runtime configuration at most once per process.

    Parameters
    ----------
    None

    Returns
    -------
    None
        Torch runtime settings are configured once and then reused.
    """
    _configure_torch_runtime()


@lru_cache(maxsize=1)
def _sentence_transformer_factory() -> _SentenceTransformerFactory:
    """
    Return the cached sentence-transformers factory for this process.

    Parameters
    ----------
    None

    Returns
    -------
    _SentenceTransformerFactory
        Imported ``SentenceTransformer`` constructor cached for reuse.

    Raises
    ------
    EmbeddingBackendError
        Raised when the optional semantic dependency stack is unavailable.
    """
    try:
        module = import_module("sentence_transformers")
    except ImportError as exc:
        raise _dependency_error(_DEPENDENCY_INSTALL_HINT) from exc
    factory = getattr(module, "SentenceTransformer", None)
    if factory is None:
        raise _dependency_error(_DEPENDENCY_INSTALL_HINT)
    return cast("_SentenceTransformerFactory", factory)


@lru_cache(maxsize=1)
def _configure_transformers_logging_once() -> None:
    """
    Silence transformers logging at most once per process.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The optional transformers logger is configured once and then reused.
    """
    try:
        utils_module = import_module("transformers.utils")
    except ImportError:
        return
    logging_module = getattr(utils_module, "logging", None)
    if logging_module is None:
        return
    cast("_TransformersLogging", logging_module).set_verbosity_error()


def _load_sentence_transformer(
    sentence_transformer: object,
    *,
    offline: bool,
) -> _EmbeddingModel:
    """
    Load the configured model with optional offline-only behavior.

    Parameters
    ----------
    sentence_transformer : object
        Imported ``SentenceTransformer`` constructor or compatible callable.
    offline : bool
        Whether model loading should require a local artifact.

    Returns
    -------
    _EmbeddingModel
        Loaded embedding model instance.
    """
    _configure_embedding_environment(offline=offline)
    factory = cast("_SentenceTransformerFactory", sentence_transformer)
    with (
        contextlib.redirect_stdout(io.StringIO()),
        contextlib.redirect_stderr(io.StringIO()),
    ):
        return factory(
            EMBEDDING_BACKEND,
            device=_configured_embedding_device(),
            local_files_only=offline,
        )


def provision_embedding_model(*, quiet: bool = False) -> None:
    """
    Ensure the configured local embedding model artifact is available.

    Parameters
    ----------
    quiet : bool, optional
        Whether to suppress the operator-facing provisioning message.

    Returns
    -------
    None
        The model artifact is downloaded or verified in the local cache.

    Raises
    ------
    EmbeddingBackendError
        Raised when the semantic dependency stack is missing or the model
        artifact cannot be provisioned.
    """
    if not quiet:
        print(
            f"[codira] Provisioning local embedding model {EMBEDDING_BACKEND}...",
            file=sys.stderr,
        )

    try:
        _load_sentence_transformer(_sentence_transformer_factory(), offline=False)
    except (OSError, RuntimeError) as exc:
        raise _wrap_load_error(exc) from exc


@lru_cache(maxsize=1)
def _load_model() -> _EmbeddingModel:
    """
    Load the configured local sentence-transformers model.

    Parameters
    ----------
    None

    Returns
    -------
    _EmbeddingModel
        Loaded ``SentenceTransformer`` model instance cached for reuse.

    Raises
    ------
    EmbeddingBackendError
        Raised when the optional dependency or local model artifact is missing.
    """
    sentence_transformer = _sentence_transformer_factory()
    _configure_transformers_logging_once()
    _configure_torch_runtime_once()

    try:
        model = _load_sentence_transformer(sentence_transformer, offline=True)
    except OSError:
        provision_embedding_model()
        try:
            model = _load_sentence_transformer(sentence_transformer, offline=True)
        except (OSError, RuntimeError) as exc:
            raise _wrap_load_error(exc) from exc
    except RuntimeError as exc:
        raise _wrap_load_error(exc) from exc

    if hasattr(model, "get_embedding_dimension"):
        dimension = model.get_embedding_dimension()
    else:
        dimension = model.get_sentence_embedding_dimension()
    if dimension != EMBEDDING_DIM:
        msg = (
            "Loaded embedding model dimension "
            f"{dimension} does not match the repository contract {EMBEDDING_DIM}."
        )
        raise EmbeddingBackendError(msg)

    return model


def reset_embedding_runtime_caches() -> None:
    """
    Clear cached embedding startup state for the current process.

    Parameters
    ----------
    None

    Returns
    -------
    None
        Cached model, import, and runtime setup state is discarded.
    """
    _sentence_transformer_factory.cache_clear()
    _configure_transformers_logging_once.cache_clear()
    _configure_torch_runtime_once.cache_clear()
    _load_model.cache_clear()


def embed_texts(texts: Sequence[str]) -> list[list[float]]:
    """
    Embed text payloads in deterministic batches.

    Parameters
    ----------
    texts : collections.abc.Sequence[str]
        Text payloads to embed.

    Returns
    -------
    list[list[float]]
        One L2-normalized embedding vector per input payload.

    Raises
    ------
    EmbeddingBackendError
        Raised when the local semantic backend cannot be loaded.
    """
    texts_list = list(texts)
    if not texts_list:
        return []

    vectors: list[list[float]] = [[0.0] * EMBEDDING_DIM for _ in texts_list]
    non_blank_positions: list[int] = []
    non_blank_texts: list[str] = []

    for index, text in enumerate(texts_list):
        if not text.strip():
            continue
        non_blank_positions.append(index)
        non_blank_texts.append(text)

    if not non_blank_texts:
        return vectors

    model = _load_model()
    encoded = model.encode(
        non_blank_texts,
        batch_size=_configured_embedding_batch_size(),
        convert_to_numpy=True,
        normalize_embeddings=True,
        show_progress_bar=False,
    )
    if len(encoded) != len(non_blank_positions):
        msg = (
            "Embedding backend returned an unexpected vector count. "
            f"Expected {len(non_blank_positions)}, received {len(encoded)}."
        )
        raise EmbeddingBackendError(msg)

    for output_index, position in enumerate(non_blank_positions):
        vectors[position] = [float(value) for value in encoded[output_index].tolist()]

    return vectors


def embed_text(text: str) -> list[float]:
    """
    Embed text using the deterministic local sentence-transformers backend.

    Parameters
    ----------
    text : str
        Text payload to embed.

    Returns
    -------
    list[float]
        L2-normalized embedding vector with fixed dimensionality.

    Raises
    ------
    EmbeddingBackendError
        Raised when the local semantic backend cannot be loaded.
    """
    return embed_texts([text])[0]


def serialize_vector(vector: list[float]) -> bytes:
    """
    Serialize a dense embedding vector for SQLite storage.

    Parameters
    ----------
    vector : list[float]
        Dense embedding vector.

    Returns
    -------
    bytes
        Binary float32 representation of the vector.
    """
    return struct.pack(f"<{len(vector)}f", *vector)


def deserialize_vector(blob: bytes, *, dim: int) -> list[float]:
    """
    Deserialize a dense embedding vector from SQLite storage.

    Parameters
    ----------
    blob : bytes
        Stored binary vector payload.
    dim : int
        Expected vector dimensionality.

    Returns
    -------
    list[float]
        Dense embedding vector.
    """
    return list(struct.unpack(f"<{dim}f", blob))
