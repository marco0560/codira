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
import contextvars
import io
import os
import struct
import sys
from dataclasses import dataclass
from functools import lru_cache
from importlib import import_module
from typing import TYPE_CHECKING, Protocol, cast

from codira.config import (
    DEFAULT_EMBEDDING_BATCH_SIZE as CONFIG_DEFAULT_EMBEDDING_BATCH_SIZE,
    DEFAULT_EMBEDDING_DEVICE,
    DEFAULT_EMBEDDING_DIMENSION,
    DEFAULT_EMBEDDING_MODEL,
    DEFAULT_EMBEDDING_VERSION,
    load_effective_config,
)
from codira.registry import active_embedding_engine

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

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
            trust_remote_code: bool,
        ) -> _EmbeddingModel: ...

    class _TransformersLogging(Protocol):
        def set_verbosity_error(self) -> None: ...


EMBEDDING_BACKEND = DEFAULT_EMBEDDING_MODEL
EMBEDDING_VERSION = DEFAULT_EMBEDDING_VERSION
EMBEDDING_DIM = DEFAULT_EMBEDDING_DIMENSION
DEFAULT_EMBEDDING_BATCH_SIZE = CONFIG_DEFAULT_EMBEDDING_BATCH_SIZE
EMBEDDING_BATCH_SIZE_ENV_VAR = "CODIRA_EMBED_BATCH_SIZE"
EMBEDDING_DEVICE_ENV_VAR = "CODIRA_EMBED_DEVICE"
TORCH_NUM_THREADS_ENV_VAR = "CODIRA_TORCH_NUM_THREADS"
TORCH_NUM_INTEROP_THREADS_ENV_VAR = "CODIRA_TORCH_NUM_INTEROP_THREADS"
_DEPENDENCY_INSTALL_HINT = (
    "Install codira with the 'semantic' extra. "
    "For editable installs from another repository, use "
    "'pip install -e ../codira[semantic]'."
)
_ACTIVE_EMBEDDING_ROOT: contextvars.ContextVar[Path | None] = contextvars.ContextVar(
    "codira_active_embedding_root", default=None
)


def _effective_root(root: Path | None = None) -> Path | None:
    """
    Return the explicit or context-local embedding configuration root.

    Parameters
    ----------
    root : pathlib.Path | None, optional
        Explicit repository root supplied by the caller.

    Returns
    -------
    pathlib.Path | None
        Repository root to use for config resolution, or ``None`` for the
        process/default config path.
    """
    if root is not None:
        return root
    return _ACTIVE_EMBEDDING_ROOT.get()


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


def get_embedding_backend(root: Path | None = None) -> EmbeddingBackendSpec:
    """
    Return the active embedding backend specification.

    Parameters
    ----------
    root : pathlib.Path | None, optional
        Repository root whose repo-local embedding configuration should be
        used.

    Returns
    -------
    EmbeddingBackendSpec
        Stable backend metadata used by indexing and retrieval.
    """
    effective_root = _effective_root(root)
    config = load_effective_config(root=effective_root).embeddings
    return EmbeddingBackendSpec(
        name=config.model,
        version=config.version,
        dim=config.dimension,
    )


def embeddings_enabled(root: Path | None = None) -> bool:
    """
    Return whether embedding computation and retrieval are enabled.

    Parameters
    ----------
    root : pathlib.Path | None, optional
        Repository root whose repo-local embedding configuration should be
        used.

    Returns
    -------
    bool
        ``True`` when effective configuration enables embeddings.
    """

    return load_effective_config(root=_effective_root(root)).embeddings.enabled


def _dependency_error(
    message: str,
    *,
    root: Path | None = None,
) -> EmbeddingBackendError:
    """
    Build a stable runtime error for embedding backend provisioning failures.

    Parameters
    ----------
    message : str
        Specific failure reason to append.
    root : pathlib.Path | None, optional
        Repository root whose embedding backend identity should be reported.

    Returns
    -------
    EmbeddingBackendError
        Provisioning error with a repository-specific remediation hint.
    """
    return EmbeddingBackendError(
        "The semantic embedding backend requires the optional 'semantic' "
        "dependency set and a locally available model artifact for "
        f"{get_embedding_backend(root=_effective_root(root)).name}. {message}"
    )


def _wrap_load_error(
    exc: OSError | RuntimeError,
    *,
    root: Path | None = None,
) -> EmbeddingBackendError:
    """
    Convert low-level model-loading failures into a stable operator error.

    Parameters
    ----------
    exc : OSError | RuntimeError
        Original model-loading exception.
    root : pathlib.Path | None, optional
        Repository root whose embedding backend identity should be reported.

    Returns
    -------
    EmbeddingBackendError
        Concise error suitable for CLI reporting.
    """
    return _dependency_error(
        "Automatic model provisioning failed. "
        "Check network access or prefetch the artifact with "
        "'python ../codira/scripts/provision_embedding_model.py'. "
        f"Loader details: {exc}",
        root=root,
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


def _configured_embedding_batch_size(root: Path | None = None) -> int:
    """
    Return the configured batch size for embedding generation.

    Parameters
    ----------
    root : pathlib.Path | None, optional
        Repository root whose repo-local embedding configuration should be
        used.

    Returns
    -------
    int
        Batch size used for sentence-transformers encode calls.
    """
    return load_effective_config(root=_effective_root(root)).embeddings.batch_size


def _configured_embedding_device(root: Path | None = None) -> str:
    """
    Return the configured sentence-transformers device string.

    Parameters
    ----------
    root : pathlib.Path | None, optional
        Repository root whose repo-local embedding configuration should be
        used.

    Returns
    -------
    str
        Device string passed to the model loader.
    """
    configured = load_effective_config(
        root=_effective_root(root)
    ).embeddings.device.strip()
    if configured:
        return configured
    return DEFAULT_EMBEDDING_DEVICE


def _configured_trust_remote_code(root: Path | None = None) -> bool:
    """
    Return whether SentenceTransformers should trust remote model code.

    Parameters
    ----------
    root : pathlib.Path | None, optional
        Repository root whose repo-local plugin configuration should be used.

    Returns
    -------
    bool
        Configured ``trust_remote_code`` value for the sentence-transformers
        embedding plugin.
    """
    config = load_effective_config(root=_effective_root(root))
    plugin_config = (config.plugins.configs or {}).get(
        "embedding-sentence-transformers",
        {},
    )
    value = plugin_config.get("trust_remote_code", False)
    return bool(value) if isinstance(value, bool) else False


def _configure_torch_runtime(root: Path | None = None) -> None:
    """
    Apply optional Torch thread overrides before model inference begins.

    Parameters
    ----------
    root : pathlib.Path | None, optional
        Repository root whose repo-local Torch runtime configuration should be
        used.

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

    config = load_effective_config(root=_effective_root(root)).embeddings
    num_threads = config.torch_num_threads or None
    num_interop_threads = config.torch_num_interop_threads or None

    try:
        if num_threads is not None:
            torch.set_num_threads(num_threads)
        if num_interop_threads is not None:
            torch.set_num_interop_threads(num_interop_threads)
    except RuntimeError as exc:
        msg = f"Failed to apply configured Torch runtime settings. Details: {exc}"
        raise EmbeddingBackendError(msg) from exc


@lru_cache(maxsize=16)
def _configure_torch_runtime_once(root: Path | None = None) -> None:
    """
    Apply Torch runtime configuration at most once per process.

    Parameters
    ----------
    root : pathlib.Path | None, optional
        Repository root whose repo-local Torch runtime configuration should be
        used.

    Returns
    -------
    None
        Torch runtime settings are configured once and then reused.
    """
    _configure_torch_runtime(root=root)


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
    root: Path | None = None,
) -> _EmbeddingModel:
    """
    Load the configured model with optional offline-only behavior.

    Parameters
    ----------
    sentence_transformer : object
        Imported ``SentenceTransformer`` constructor or compatible callable.
    offline : bool
        Whether model loading should require a local artifact.
    root : pathlib.Path | None, optional
        Repository root whose repo-local embedding configuration should be
        used.

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
            get_embedding_backend(root=_effective_root(root)).name,
            device=_configured_embedding_device(root=_effective_root(root)),
            local_files_only=offline,
            trust_remote_code=_configured_trust_remote_code(root),
        )


def _sentence_transformer_provision_embedding_model(
    *,
    quiet: bool = False,
    root: Path | None = None,
) -> None:
    """
    Ensure the configured local embedding model artifact is available.

    Parameters
    ----------
    quiet : bool, optional
        Whether to suppress the operator-facing provisioning message.
    root : pathlib.Path | None, optional
        Repository root whose repo-local embedding configuration should be
        used.

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
            f"[codira] Provisioning local embedding model {get_embedding_backend(root=_effective_root(root)).name}...",
            file=sys.stderr,
        )

    try:
        _load_sentence_transformer(
            _sentence_transformer_factory(),
            offline=False,
            root=root,
        )
    except (OSError, RuntimeError) as exc:
        raise _wrap_load_error(exc, root=root) from exc


@lru_cache(maxsize=16)
def _load_model(root: Path | None = None) -> _EmbeddingModel:
    """
    Load the configured local sentence-transformers model.

    Parameters
    ----------
    root : pathlib.Path | None, optional
        Repository root whose repo-local embedding configuration should be
        used.

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
    _configure_torch_runtime_once(root=root)

    try:
        model = _load_sentence_transformer(
            sentence_transformer,
            offline=True,
            root=root,
        )
    except OSError:
        provision_embedding_model(root=root)
        try:
            model = _load_sentence_transformer(
                sentence_transformer,
                offline=True,
                root=root,
            )
        except (OSError, RuntimeError) as exc:
            raise _wrap_load_error(exc, root=root) from exc
    except RuntimeError as exc:
        raise _wrap_load_error(exc, root=root) from exc

    if hasattr(model, "get_embedding_dimension"):
        dimension = model.get_embedding_dimension()
    else:
        dimension = model.get_sentence_embedding_dimension()
    expected_dimension = get_embedding_backend(root=root).dim
    if dimension != expected_dimension:
        msg = (
            "Loaded embedding model dimension "
            f"{dimension} does not match the configured contract "
            f"{expected_dimension}."
        )
        raise EmbeddingBackendError(msg)

    return model


def _sentence_transformer_reset_runtime_caches() -> None:
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


def reset_embedding_runtime_caches() -> None:
    """
    Clear cached embedding startup state for the active engine.

    Parameters
    ----------
    None

    Returns
    -------
    None
        Cached embedding runtime state is discarded.
    """
    active_embedding_engine().reset_runtime_caches()


def provision_embedding_model(
    *,
    quiet: bool = False,
    root: Path | None = None,
) -> None:
    """
    Ensure the configured local embedding model artifact is available.

    Parameters
    ----------
    quiet : bool, optional
        Whether to suppress operator-facing provisioning output.
    root : pathlib.Path | None, optional
        Repository root whose repo-local embedding configuration should be
        used.

    Returns
    -------
    None
        The active engine verifies or provisions required local artifacts.
    """
    effective_root = _effective_root(root)
    config = load_effective_config(root=effective_root)
    engine_config = (config.plugins.configs or {}).get(
        f"embedding-{config.embeddings.engine}",
        {},
    )
    token = _ACTIVE_EMBEDDING_ROOT.set(effective_root)
    try:
        active_embedding_engine(root=effective_root).provision(
            engine_config,
            quiet=quiet,
        )
    finally:
        _ACTIVE_EMBEDDING_ROOT.reset(token)


def _sentence_transformer_embed_texts(
    texts: Sequence[str],
    *,
    root: Path | None = None,
) -> list[list[float]]:
    """
    Embed text payloads in deterministic batches.

    Parameters
    ----------
    texts : collections.abc.Sequence[str]
        Text payloads to embed.
    root : pathlib.Path | None, optional
        Repository root whose repo-local embedding configuration should be
        used.

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
    effective_root = _effective_root(root)
    dimension = get_embedding_backend(root=effective_root).dim
    if not texts_list:
        return []
    if not embeddings_enabled(root=effective_root):
        return [[0.0] * dimension for _ in texts_list]

    vectors: list[list[float]] = [[0.0] * dimension for _ in texts_list]
    positions_by_text: dict[str, list[int]] = {}

    for index, text in enumerate(texts_list):
        if not text.strip():
            continue
        positions_by_text.setdefault(text, []).append(index)

    if not positions_by_text:
        return vectors

    model = _load_model(root=effective_root)
    unique_texts = list(positions_by_text)
    encoded = model.encode(
        unique_texts,
        batch_size=_configured_embedding_batch_size(root=effective_root),
        convert_to_numpy=True,
        normalize_embeddings=True,
        show_progress_bar=False,
    )
    if len(encoded) != len(unique_texts):
        msg = (
            "Embedding backend returned an unexpected vector count. "
            f"Expected {len(unique_texts)}, received {len(encoded)}."
        )
        raise EmbeddingBackendError(msg)

    for output_index, text in enumerate(unique_texts):
        vector = [float(value) for value in encoded[output_index].tolist()]
        for position in positions_by_text[text]:
            vectors[position] = vector

    return vectors


def embed_texts(
    texts: Sequence[str],
    *,
    root: Path | None = None,
) -> list[list[float]]:
    """
    Embed text payloads through the active embedding engine.

    Parameters
    ----------
    texts : collections.abc.Sequence[str]
        Text payloads to embed.
    root : pathlib.Path | None, optional
        Repository root whose repo-local embedding configuration should be
        used.

    Returns
    -------
    list[list[float]]
        One L2-normalized embedding vector per input payload.

    Raises
    ------
    EmbeddingBackendError
        Raised when the active semantic engine cannot be loaded.
    """
    effective_root = _effective_root(root)
    config = load_effective_config(root=effective_root)
    engine_config = (config.plugins.configs or {}).get(
        f"embedding-{config.embeddings.engine}",
        {},
    )
    token = _ACTIVE_EMBEDDING_ROOT.set(effective_root)
    try:
        return active_embedding_engine(root=effective_root).embed_texts(
            texts,
            engine_config,
        )
    finally:
        _ACTIVE_EMBEDDING_ROOT.reset(token)


def embed_text(text: str, *, root: Path | None = None) -> list[float]:
    """
    Embed text using the deterministic local sentence-transformers backend.

    Parameters
    ----------
    text : str
        Text payload to embed.
    root : pathlib.Path | None, optional
        Repository root whose repo-local embedding configuration should be
        used.

    Returns
    -------
    list[float]
        L2-normalized embedding vector with fixed dimensionality.

    Raises
    ------
    EmbeddingBackendError
        Raised when the local semantic backend cannot be loaded.
    """
    return embed_texts([text], root=root)[0]


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
