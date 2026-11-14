"""Optional contracts for incremental full-index persistence.

Parameters
----------
None

Returns
-------
None
    Defines opt-in streaming persistence interfaces.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Mapping, Sequence
    from pathlib import Path

    from codira.contracts import (
        BackendPersistFullIndexFile,
        BackendPersistFullIndexResult,
        EmbeddingIndexingPolicy,
        LanguageAnalyzer,
        VectorSetIdentity,
        VectorStore,
    )
    from codira.semantic.embeddings import EmbeddingBackendSpec


@dataclass(frozen=True)
class BackendPersistFullIndexStreamRequest:
    """Request incremental persistence of a complete full-index snapshot.

    Parameters
    ----------
    root : pathlib.Path
        Repository root whose backend state should be replaced.
    files : collections.abc.Iterable[codira.contracts.BackendPersistFullIndexFile]
        Successfully analyzed file snapshots in deterministic order.
    embedding_backend : codira.semantic.embeddings.EmbeddingBackendSpec
        Active embedding backend metadata.
    embedding_indexing : codira.contracts.EmbeddingIndexingPolicy
        Embedding row eligibility policy.
    defer_embeddings : bool
        Whether eligible embedding rows should be queued for later computation.
    vector_store : codira.contracts.VectorStore | None
        Active separated vector store used for embedding row persistence.
    vector_set_identity : codira.contracts.VectorSetIdentity | None
        Active vector-set identity for separated vector-store writes.
    vector_store_config : collections.abc.Mapping[str, object]
        Vector-store-specific configuration.
    coverage_complete : collections.abc.Callable[[], bool]
        Late coverage check, called after the file iterable is exhausted.
    analyzers : collections.abc.Sequence[codira.contracts.LanguageAnalyzer]
        Active analyzers for the run.
    """

    root: Path
    files: Iterable[BackendPersistFullIndexFile]
    embedding_backend: EmbeddingBackendSpec
    embedding_indexing: EmbeddingIndexingPolicy
    defer_embeddings: bool
    vector_store: VectorStore | None
    vector_set_identity: VectorSetIdentity | None
    vector_store_config: Mapping[str, object]
    coverage_complete: Callable[[], bool]
    analyzers: Sequence[LanguageAnalyzer]


@runtime_checkable
class FullIndexStreamingBulkBackend(Protocol):
    """Optional backend contract for transactionally streaming full indexes."""

    def persist_full_index_stream(
        self,
        request: BackendPersistFullIndexStreamRequest,
    ) -> BackendPersistFullIndexResult:
        """Persist an ordered file stream in one backend-native transaction.

        Parameters
        ----------
        request : codira.index_stream_contracts.BackendPersistFullIndexStreamRequest
            Full-index stream and runtime metadata.

        Returns
        -------
        codira.contracts.BackendPersistFullIndexResult
            Embedding counters for the completed persistence run.
        """
        ...
