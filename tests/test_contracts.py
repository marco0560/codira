"""Tests for ADR-004 Phase 3 contract and normalization models.

Responsibilities
----------------
- Verify analyzer and backend contracts using fake implementations that hook into the existing registry.
- Ensure normalization from parser output produces the expected AnalysisResult artifacts and deterministic module data.
- Validate registry discovery, analyzer selection, and backend initialization invariants.

Design principles
-----------------
Tests rely on stub analyzers/backends and explicit fixtures so contract violations surface as deterministic failures.

Architectural role
------------------
This module belongs to the **contract verification layer** and enforces the ADR-004 Phase 3 language analyzer and backend APIs.
"""

from __future__ import annotations

import importlib.util
import json
import sqlite3
import sys
import tomllib
from pathlib import Path
from typing import TYPE_CHECKING

from codira_analyzer_c import CAnalyzer
from codira_analyzer_cpp import CppAnalyzer
from codira_analyzer_python import PythonAnalyzer
from codira_analyzer_rust import RustAnalyzer
from codira_backend_sqlite import SQLiteIndexBackend

import codira.contracts_backend_requests as backend_requests_module
import codira.indexer as indexer_module
import codira.registry as registry_module
from codira.cli import _run_symbol
from codira.contracts import (
    KNOWN_RETRIEVAL_CAPABILITIES,
    BackendDocumentationCandidatesRequest,
    BackendEmbeddingCandidatesRequest,
    BackendPersistAnalysisRequest,
    BackendRelationQueryRequest,
    BackendResolveDocumentationScoresRequest,
    BackendResolveEmbeddingScoresRequest,
    BackendRuntimeInventoryRequest,
    BackendSymbolInventoryItem,
    EmbeddingEngine,
    EmbeddingEngineSpec,
    IndexBackend,
    LanguageAnalyzer,
    PreparedVectorRow,
    RetrievalProducer,
    RetrievalProducerInfo,
    VectorSetIdentity,
    VectorSimilarityRequest,
    VectorSimilarityScore,
    VectorSnapshot,
    VectorSnapshotRequest,
    VectorStore,
    VectorStorePurgeRequest,
    VectorStorePurgeResult,
    VectorStoreResetRequest,
    VectorStoreResetResult,
    VectorStoreSpec,
    split_declared_retrieval_capabilities,
)
from codira.indexer import _duplicate_analysis_stable_ids
from codira.models import AnalysisResult, FileMetadataSnapshot
from codira.query.producers import (
    CALL_GRAPH_RETRIEVAL_PRODUCER,
    CHANNEL_PRODUCER_SPECS,
    EMBEDDING_RETRIEVAL_PRODUCER,
    INCLUDE_GRAPH_RETRIEVAL_PRODUCER,
    REFERENCE_RETRIEVAL_PRODUCER,
)
from codira.registry import active_index_backend, active_language_analyzers

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from types import ModuleType

    from pytest import CaptureFixture, MonkeyPatch

    from codira.types import ChannelResults, DocumentationChannelResults


def _load_workspace_registry_module() -> ModuleType:
    """
    Load the workspace `src/codira/registry.py` module under a unique name.

    Parameters
    ----------
    None

    Returns
    -------
    types.ModuleType
        Freshly loaded workspace registry module.

    Raises
    ------
    AssertionError
        Raised when the workspace registry module cannot be loaded.
    """
    module_path = Path(__file__).resolve().parents[1] / "src" / "codira" / "registry.py"
    spec = importlib.util.spec_from_file_location(
        f"workspace_codira_registry_{id(module_path)}",
        module_path,
    )
    if spec is None or spec.loader is None:
        msg = f"failed to load workspace codira registry module from {module_path}"
        raise AssertionError(msg)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_backend_request_records_remain_available_from_contracts_facade() -> None:
    """
    Preserve backend request imports while isolating their record family.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test asserts the contracts facade re-exports the extracted records.
    """
    assert (
        BackendRelationQueryRequest
        is backend_requests_module.BackendRelationQueryRequest
    )
    assert (
        BackendEmbeddingCandidatesRequest
        is backend_requests_module.BackendEmbeddingCandidatesRequest
    )
    assert (
        BackendDocumentationCandidatesRequest
        is backend_requests_module.BackendDocumentationCandidatesRequest
    )
    assert (
        BackendResolveEmbeddingScoresRequest
        is backend_requests_module.BackendResolveEmbeddingScoresRequest
    )
    assert (
        BackendResolveDocumentationScoresRequest
        is backend_requests_module.BackendResolveDocumentationScoresRequest
    )
    assert (
        BackendRuntimeInventoryRequest
        is backend_requests_module.BackendRuntimeInventoryRequest
    )


class _FakeAnalyzer:
    """Small analyzer stub used to validate the protocol surface."""

    name = "fake-python"
    version = "1"
    discovery_globs: tuple[str, ...] = ("*.py",)

    def supports_path(self, path: Path) -> bool:
        """
        Report support for Python files.

        Parameters
        ----------
        path : pathlib.Path
            Candidate source path.

        Returns
        -------
        bool
            ``True`` for Python files.
        """
        return path.suffix == ".py"

    def analyze_file(self, path: Path, root: Path) -> AnalysisResult:
        """
        Analyze one file through the existing Python parser path.

        Parameters
        ----------
        path : pathlib.Path
            Source file to analyze.
        root : pathlib.Path
            Repository root used for module resolution.

        Returns
        -------
        codira.models.AnalysisResult
            Normalized analysis result for the file.
        """
        return PythonAnalyzer().analyze_file(path, root)


class _FakeEmbeddingEngine:
    """Small embedding-engine stub used to validate the protocol surface."""

    name = "fake-engine"
    version = "1"

    def spec(self, config: dict[str, object]) -> EmbeddingEngineSpec:
        """
        Return deterministic fake engine identity metadata.

        Parameters
        ----------
        config : dict[str, object]
            Engine-specific configuration table.

        Returns
        -------
        codira.contracts.EmbeddingEngineSpec
            Stable fake engine identity.
        """
        del config
        return EmbeddingEngineSpec(
            engine=self.name,
            engine_version=self.version,
            model="fake-model",
            model_version="1",
            dimension=3,
        )

    def provision(self, config: dict[str, object], *, quiet: bool = False) -> None:
        """
        Perform no-op local artifact provisioning.

        Parameters
        ----------
        config : dict[str, object]
            Engine-specific configuration table.
        quiet : bool, optional
            Whether operator-facing output should be suppressed.

        Returns
        -------
        None
            The fake engine has no external artifacts.
        """
        del config, quiet

    def embed_texts(
        self,
        texts: Sequence[str],
        config: dict[str, object],
    ) -> list[list[float]]:
        """
        Return deterministic fake vectors for protocol validation.

        Parameters
        ----------
        texts : collections.abc.Sequence[str]
            Text payloads to embed.
        config : dict[str, object]
            Engine-specific configuration table.

        Returns
        -------
        list[list[float]]
            One fixed-size vector per input payload.
        """
        del config
        return [[float(index), 0.0, 0.0] for index, _text in enumerate(texts)]

    def calibration_runner(self, config: dict[str, object]) -> object:
        """
        Return a placeholder runner for protocol-surface validation.

        Parameters
        ----------
        config : dict[str, object]
            Engine-specific configuration table.

        Returns
        -------
        object
            The runtime-checkable protocol only verifies the capability is
            exposed; benchmark execution is not part of this fixture.
        """

        del config
        return object()

    def reset_runtime_caches(self) -> None:
        """Perform no-op runtime cache reset.

        Parameters
        ----------
        None

        Returns
        -------
        None
            The fake engine has no process-local caches.
        """


class _FakeVectorStore:
    """Small vector-store stub used to validate the protocol surface."""

    name = "fake-vector-store"
    version = "1"

    def spec(self, config: dict[str, object]) -> VectorStoreSpec:
        """
        Return deterministic fake vector-store identity metadata.

        Parameters
        ----------
        config : dict[str, object]
            Vector-store-specific configuration table.

        Returns
        -------
        codira.contracts.VectorStoreSpec
            Stable fake vector-store identity.
        """
        del config
        return VectorStoreSpec(
            store=self.name,
            store_version=self.version,
            format_version="1",
        )

    def initialize(self, root: Path, config: dict[str, object]) -> None:
        """
        Perform no-op vector-store initialization.

        Parameters
        ----------
        root : pathlib.Path
            Repository root.
        config : dict[str, object]
            Vector-store-specific configuration table.

        Returns
        -------
        None
            The fake vector store has no persisted state.
        """
        del root, config

    def ensure_vector_set(
        self,
        root: Path,
        identity: VectorSetIdentity,
        config: dict[str, object],
    ) -> int:
        """
        Return a deterministic fake vector-set identifier.

        Parameters
        ----------
        root : pathlib.Path
            Repository root.
        identity : codira.contracts.VectorSetIdentity
            Complete vector-set identity.
        config : dict[str, object]
            Vector-store-specific configuration table.

        Returns
        -------
        int
            Fixed vector-set identifier.
        """
        del root, identity, config
        return 1

    def load_cached_vectors(
        self,
        root: Path,
        identity: VectorSetIdentity,
        content_hashes: Sequence[str],
        config: dict[str, object],
    ) -> dict[str, bytes]:
        """
        Return no cached fake vectors.

        Parameters
        ----------
        root : pathlib.Path
            Repository root.
        identity : codira.contracts.VectorSetIdentity
            Complete vector-set identity.
        content_hashes : collections.abc.Sequence[str]
            Candidate content hashes.
        config : dict[str, object]
            Vector-store-specific configuration table.

        Returns
        -------
        dict[str, bytes]
            Empty cache result.
        """
        del root, identity, content_hashes, config
        return {}

    def store_cached_vectors(
        self,
        root: Path,
        identity: VectorSetIdentity,
        vectors: Mapping[str, bytes],
        config: dict[str, object],
    ) -> None:
        """
        Perform no-op fake cache persistence.

        Parameters
        ----------
        root : pathlib.Path
            Repository root.
        identity : codira.contracts.VectorSetIdentity
            Complete vector-set identity.
        vectors : collections.abc.Mapping[str, bytes]
            Serialized vectors keyed by content hash.
        config : dict[str, object]
            Vector-store-specific configuration table.

        Returns
        -------
        None
            The fake vector store has no persisted cache.
        """
        del root, identity, vectors, config

    def store_pending_vectors(
        self,
        root: Path,
        identity: VectorSetIdentity,
        rows: Sequence[PreparedVectorRow],
        config: dict[str, object],
    ) -> None:
        """
        Perform no-op fake pending-row persistence.

        Parameters
        ----------
        root : pathlib.Path
            Repository root.
        identity : codira.contracts.VectorSetIdentity
            Complete vector-set identity.
        rows : collections.abc.Sequence[codira.contracts.PreparedVectorRow]
            Prepared rows to persist.
        config : dict[str, object]
            Vector-store-specific configuration table.

        Returns
        -------
        None
            The fake vector store has no pending queue.
        """
        del root, identity, rows, config

    def delete_pending_vectors(
        self,
        root: Path,
        identity: VectorSetIdentity,
        rows: Sequence[PreparedVectorRow],
        config: dict[str, object],
    ) -> None:
        """
        Perform no-op fake pending-row deletion.

        Parameters
        ----------
        root : pathlib.Path
            Repository root.
        identity : codira.contracts.VectorSetIdentity
            Complete vector-set identity.
        rows : collections.abc.Sequence[codira.contracts.PreparedVectorRow]
            Prepared rows identifying pending entries.
        config : dict[str, object]
            Vector-store-specific configuration table.

        Returns
        -------
        None
            The fake vector store has no pending queue.
        """
        del root, identity, rows, config

    def clear_pending_vectors(
        self,
        root: Path,
        identity: VectorSetIdentity,
        config: dict[str, object],
    ) -> None:
        """
        Perform no-op fake pending-row cleanup.

        Parameters
        ----------
        root : pathlib.Path
            Repository root.
        identity : codira.contracts.VectorSetIdentity
            Complete vector-set identity.
        config : dict[str, object]
            Vector-store-specific configuration table.

        Returns
        -------
        None
            The fake vector store has no pending queue.
        """
        del root, identity, config

    def store_vectors(
        self,
        root: Path,
        identity: VectorSetIdentity,
        rows: Sequence[PreparedVectorRow],
        config: dict[str, object],
    ) -> None:
        """
        Perform no-op fake materialized-vector persistence.

        Parameters
        ----------
        root : pathlib.Path
            Repository root.
        identity : codira.contracts.VectorSetIdentity
            Complete vector-set identity.
        rows : collections.abc.Sequence[codira.contracts.PreparedVectorRow]
            Prepared rows carrying serialized vectors.
        config : dict[str, object]
            Vector-store-specific configuration table.

        Returns
        -------
        None
            The fake vector store has no materialized vectors.
        """
        del root, identity, rows, config

    def vector_snapshot(self, request: VectorSnapshotRequest) -> VectorSnapshot:
        """Reject snapshots because this fake only supports indexing tests.

        Parameters
        ----------
        request : codira.contracts.VectorSnapshotRequest
            Ignored snapshot request.

        Returns
        -------
        codira.contracts.VectorSnapshot
            This method never returns a snapshot.

        Raises
        ------
        RuntimeError
            Always raised because snapshots are not exercised by this fake.
        """

        del request
        message = "snapshot not configured"
        raise RuntimeError(message)

    def similarity_scores(
        self,
        request: VectorSimilarityRequest,
    ) -> list[VectorSimilarityScore]:
        """
        Return no fake vector-store similarity scores.

        Parameters
        ----------
        request : codira.contracts.VectorSimilarityRequest
            Vector-store similarity request.

        Returns
        -------
        list[codira.contracts.VectorSimilarityScore]
            Empty score list.
        """
        del request
        return []

    def purge_vector_sets(
        self,
        request: VectorStorePurgeRequest,
    ) -> VectorStorePurgeResult:
        """
        Return an empty fake purge result.

        Parameters
        ----------
        request : codira.contracts.VectorStorePurgeRequest
            Purge request.

        Returns
        -------
        codira.contracts.VectorStorePurgeResult
            Empty purge result.
        """
        del request
        return VectorStorePurgeResult(
            store=self.name,
            mode="stale",
            dry_run=True,
            active_vector_set_id=None,
            stale_vector_sets=0,
            kept_stale_vector_sets=0,
            deleted_vectors=0,
            deleted_cached_vectors=0,
            deleted_pending_vectors=0,
            deleted_vector_sets=0,
        )

    def reset_runtime_caches(self) -> None:
        """Perform no-op vector-store cache reset.

        Parameters
        ----------
        None

        Returns
        -------
        None
            The fake vector store has no process-local caches.
        """

    def reset_persistent_state(
        self,
        request: VectorStoreResetRequest,
    ) -> VectorStoreResetResult:
        """Return no removed state for the protocol-only fake store.

        Parameters
        ----------
        request : codira.contracts.VectorStoreResetRequest
            Reset request ignored by the protocol-only fake.

        Returns
        -------
        codira.contracts.VectorStoreResetResult
            Empty removal result for the fake store.
        """

        del request
        return VectorStoreResetResult(self.name)


class _FakeBackend:
    """Small backend stub used to validate the protocol surface."""

    name = "fake-backend"
    version = "1"

    def begin_index_session(self, root: Path) -> _FakeIndexWriteSession:
        """
        Return a no-op write session for protocol validation.

        Parameters
        ----------
        root : pathlib.Path
            Repository root.

        Returns
        -------
        _FakeIndexWriteSession
            No-op write session.
        """
        return _FakeIndexWriteSession(self, root)

    def open_connection(self, root: Path) -> sqlite3.Connection:
        """
        Open an in-memory SQLite connection for protocol validation.

        Parameters
        ----------
        root : pathlib.Path
            Repository root.

        Returns
        -------
        sqlite3.Connection
            In-memory SQLite connection handle.
        """
        del root
        return sqlite3.connect(":memory:")

    def load_runtime_inventory(
        self,
        root: Path,
        *,
        conn: sqlite3.Connection | None = None,
    ) -> tuple[str, str, int] | None:
        """
        Return no persisted runtime inventory for the fake backend.

        Parameters
        ----------
        root : pathlib.Path
            Repository root.
        conn : sqlite3.Connection | None, optional
            Optional SQLite connection.

        Returns
        -------
        tuple[str, str, int] | None
            ``None`` for protocol validation.
        """
        del root, conn
        return None

    def load_analyzer_inventory(
        self,
        root: Path,
        *,
        conn: sqlite3.Connection | None = None,
    ) -> list[tuple[str, str, str]]:
        """
        Return no persisted analyzer inventory for the fake backend.

        Parameters
        ----------
        root : pathlib.Path
            Repository root.
        conn : sqlite3.Connection | None, optional
            Optional SQLite connection.

        Returns
        -------
        list[tuple[str, str, str]]
            Empty analyzer inventory for protocol validation.
        """
        del root, conn
        return []

    def initialize(self, root: Path) -> None:
        """
        Perform no-op initialization for the fake backend.

        Parameters
        ----------
        root : pathlib.Path
            Repository root.

        Returns
        -------
        None
            This fake backend keeps no state.
        """
        return

    def load_existing_file_hashes(
        self,
        root: Path,
        *,
        conn: sqlite3.Connection | None = None,
    ) -> dict[str, str]:
        """
        Return an empty file-hash mapping.

        Parameters
        ----------
        root : pathlib.Path
            Repository root.
        conn : sqlite3.Connection | None, optional
            Optional SQLite connection.

        Returns
        -------
        dict[str, str]
            Empty mapping for protocol validation.
        """
        del conn
        return {}

    def load_existing_file_ownership(
        self,
        root: Path,
        *,
        conn: sqlite3.Connection | None = None,
    ) -> dict[str, tuple[str, str]]:
        """
        Return an empty analyzer-ownership mapping.

        Parameters
        ----------
        root : pathlib.Path
            Repository root.
        conn : sqlite3.Connection | None, optional
            Optional SQLite connection.

        Returns
        -------
        dict[str, tuple[str, str]]
            Empty ownership mapping for protocol validation.
        """
        del root, conn
        return {}

    def delete_paths(
        self,
        root: Path,
        *,
        paths: list[str],
        conn: sqlite3.Connection | None = None,
    ) -> None:
        """
        Perform no-op path deletion for the fake backend.

        Parameters
        ----------
        root : pathlib.Path
            Repository root.
        paths : list[str]
            Paths that would be deleted.
        conn : sqlite3.Connection | None, optional
            Optional SQLite connection.

        Returns
        -------
        None
            This fake backend keeps no state.
        """
        del conn
        return

    def clear_index(
        self,
        root: Path,
        *,
        conn: object | None = None,
    ) -> None:
        """
        Perform no-op index clearing for the fake backend.

        Parameters
        ----------
        root : pathlib.Path
            Repository root.
        conn : object | None, optional
            Optional backend connection.

        Returns
        -------
        None
            This fake backend keeps no state.
        """
        del root, conn
        return

    def purge_skipped_docstring_issues(
        self,
        root: Path,
        *,
        conn: object | None = None,
    ) -> None:
        """
        Perform no-op skipped-docstring cleanup for the fake backend.

        Parameters
        ----------
        root : pathlib.Path
            Repository root.
        conn : object | None, optional
            Optional backend connection.

        Returns
        -------
        None
            This fake backend keeps no state.
        """
        del root, conn
        return

    def load_previous_embeddings_by_path(
        self,
        root: Path,
        *,
        paths: list[str],
        embedding_backend: object,
        conn: object | None = None,
    ) -> dict[str, dict[str, object]]:
        """
        Return no reusable semantic artifacts for the fake backend.

        Parameters
        ----------
        root : pathlib.Path
            Repository root.
        paths : list[str]
            Paths selected for replacement.
        embedding_backend : object
            Active embedding backend placeholder.
        conn : object | None, optional
            Optional backend connection.

        Returns
        -------
        dict[str, dict[str, object]]
            Empty reusable-artifact mapping.
        """
        del root, paths, embedding_backend, conn
        return {}

    def persist_analysis(
        self,
        request: BackendPersistAnalysisRequest,
    ) -> tuple[int, int]:
        """
        Count normalized functions as a stand-in for persisted artifacts.

        Parameters
        ----------
        request : BackendPersistAnalysisRequest
            Persistence request carrying metadata, normalized analysis, and
            optional backend state placeholders.

        Returns
        -------
        tuple[int, int]
            Recomputed and reused semantic-artifact counts.
        """
        return (len(request.analysis.iter_functions()), 0)

    def process_pending_embeddings(
        self,
        root: Path,
        *,
        embedding_backend: object,
        vector_store: VectorStore | None = None,
        vector_set_identity: VectorSetIdentity | None = None,
        vector_store_config: Mapping[str, object] | None = None,
        conn: object | None = None,
    ) -> tuple[int, int]:
        """
        Return no pending semantic artifacts for the fake backend.

        Parameters
        ----------
        root : pathlib.Path
            Repository root.
        embedding_backend : object
            Active embedding backend placeholder.
        vector_store : codira.contracts.VectorStore | None, optional
            Ignored separated vector store.
        vector_set_identity : codira.contracts.VectorSetIdentity | None, optional
            Ignored active vector-set identity.
        vector_store_config : collections.abc.Mapping[str, object] | None, optional
            Ignored vector-store-specific configuration.
        conn : object | None, optional
            Optional backend connection.

        Returns
        -------
        tuple[int, int]
            Zero recomputed and reused pending-artifact counts.
        """
        del root, embedding_backend, vector_store, vector_set_identity
        del vector_store_config, conn
        return (0, 0)

    def count_reusable_embeddings(
        self,
        root: Path,
        *,
        paths: list[str],
        conn: sqlite3.Connection | None = None,
    ) -> int:
        """
        Count supplied paths as a stand-in reusable-artifact metric.

        Parameters
        ----------
        root : pathlib.Path
            Repository root.
        paths : list[str]
            Reusable paths.
        conn : sqlite3.Connection | None, optional
            Optional SQLite connection.

        Returns
        -------
        int
            Number of reusable paths.
        """
        del root, conn
        return len(paths)

    def rebuild_derived_indexes(
        self,
        root: Path,
        *,
        conn: sqlite3.Connection | None = None,
    ) -> None:
        """
        Perform no-op derived-index rebuilding.

        Parameters
        ----------
        root : pathlib.Path
            Repository root.
        conn : sqlite3.Connection | None, optional
            Optional SQLite connection.

        Returns
        -------
        None
            This fake backend keeps no state.
        """
        del conn
        return

    def list_symbols_in_module(
        self,
        root: Path,
        module: str,
        *,
        prefix: str | None = None,
        limit: int = 20,
        conn: sqlite3.Connection | None = None,
    ) -> list[tuple[str, str, str, str, int]]:
        """
        Return no symbol rows for protocol validation.

        Parameters
        ----------
        root : pathlib.Path
            Repository root.
        module : str
            Dotted module name.
        prefix : str | None, optional
            Optional path filter.
        limit : int, optional
            Maximum result count.
        conn : sqlite3.Connection | None, optional
            Optional SQLite connection.

        Returns
        -------
        list[tuple[str, str, str, str, int]]
            Empty symbol rows for protocol validation.
        """
        del root, module, prefix, limit, conn
        return []

    def find_symbol(
        self,
        root: Path,
        name: str,
        *,
        prefix: str | None = None,
        conn: sqlite3.Connection | None = None,
    ) -> list[tuple[str, str, str, str, int]]:
        """
        Return no symbol matches for protocol validation.

        Parameters
        ----------
        root : pathlib.Path
            Repository root.
        name : str
            Exact symbol name.
        prefix : str | None, optional
            Optional path filter.
        conn : sqlite3.Connection | None, optional
            Optional SQLite connection.

        Returns
        -------
        list[tuple[str, str, str, str, int]]
            Empty symbol rows for protocol validation.
        """
        del root, name, prefix, conn
        return []

    def symbol_inventory(
        self,
        root: Path,
        *,
        prefix: str | None = None,
        include_tests: bool = False,
        limit: int = 1000,
        conn: sqlite3.Connection | None = None,
    ) -> list[BackendSymbolInventoryItem]:
        """
        Return no inventory rows for protocol validation.

        Parameters
        ----------
        root : pathlib.Path
            Repository root.
        prefix : str | None, optional
            Optional path filter.
        include_tests : bool, optional
            Whether test modules are included.
        limit : int, optional
            Maximum result count.
        conn : sqlite3.Connection | None, optional
            Optional SQLite connection.

        Returns
        -------
        list[codira.contracts.BackendSymbolInventoryItem]
            Empty symbol inventory rows for protocol validation.
        """
        del root, prefix, include_tests, limit, conn
        return []

    def module_imports(
        self,
        root: Path,
        module: str,
        *,
        conn: sqlite3.Connection | None = None,
    ) -> list[tuple[str, str, int]]:
        """Return no imports for protocol validation.

        Parameters
        ----------
        root : pathlib.Path
            Repository root.
        module : str
            Indexed module name.
        conn : sqlite3.Connection | None, optional
            Optional SQLite connection.

        Returns
        -------
        list[tuple[str, str, int]]
            Empty import rows for protocol validation.
        """
        del root, module, conn
        return []

    def find_symbol_overloads(
        self,
        root: Path,
        symbol: tuple[str, str, str, str, int],
        *,
        conn: sqlite3.Connection | None = None,
    ) -> list[tuple[str, str, int, str, int, int | None, str | None]]:
        """
        Return no overload metadata for protocol validation.

        Parameters
        ----------
        root : pathlib.Path
            Repository root.
        symbol : tuple[str, str, str, str, int]
            Canonical symbol row.
        conn : sqlite3.Connection | None, optional
            Optional SQLite connection.

        Returns
        -------
        list[tuple[str, str, int, str, int, int | None, str | None]]
            Empty overload rows for protocol validation.
        """
        del root, symbol, conn
        return []

    def find_symbol_enum_members(
        self,
        root: Path,
        symbol: tuple[str, str, str, str, int],
        *,
        conn: sqlite3.Connection | None = None,
    ) -> list[tuple[str, str, int, str, str, int]]:
        """
        Return no enum-member metadata for protocol validation.

        Parameters
        ----------
        root : pathlib.Path
            Repository root.
        symbol : tuple[str, str, str, str, int]
            Canonical symbol row.
        conn : sqlite3.Connection | None, optional
            Optional SQLite connection.

        Returns
        -------
        list[tuple[str, str, int, str, str, int]]
            Empty enum-member rows for protocol validation.
        """
        del root, symbol, conn
        return []

    def docstring_issues(
        self,
        root: Path,
        *,
        prefix: str | None = None,
        symbol_names: Sequence[str] | None = None,
        conn: sqlite3.Connection | None = None,
    ) -> list[tuple[str, str, str, str, str, str, str, int, int | None]]:
        """
        Return no docstring issues for protocol validation.

        Parameters
        ----------
        root : pathlib.Path
            Repository root.
        prefix : str | None, optional
            Optional path filter.
        symbol_names : collections.abc.Sequence[str] | None, optional
            Optional symbol-name filter.
        conn : sqlite3.Connection | None, optional
            Optional SQLite connection.

        Returns
        -------
        list[tuple[str, str, str, str, str, str, str, int, int | None]]
            Empty docstring issue rows for protocol validation.
        """
        del root, prefix, symbol_names, conn
        return []

    def find_call_edges(
        self,
        request: BackendRelationQueryRequest,
    ) -> list[tuple[str, str, str | None, str | None, str | None, str | None, int]]:
        """
        Return no call edges for protocol validation.

        Parameters
        ----------
        request : BackendRelationQueryRequest
            Exact relation lookup request.

        Returns
        -------
        list[tuple[str, str, str | None, str | None, str | None, str | None, int]]
            Empty call-edge rows for protocol validation.
        """
        del request
        return []

    def find_callable_refs(
        self,
        request: BackendRelationQueryRequest,
    ) -> list[tuple[str, str, str | None, str | None, str | None, str | None, int]]:
        """
        Return no callable references for protocol validation.

        Parameters
        ----------
        request : BackendRelationQueryRequest
            Exact relation lookup request.

        Returns
        -------
        list[tuple[str, str, str | None, str | None, str | None, str | None, int]]
            Empty callable-reference rows for protocol validation.
        """
        del request
        return []

    def find_include_edges(
        self,
        request: BackendRelationQueryRequest,
    ) -> list[tuple[str, str, str, int]]:
        """
        Return no include edges for protocol validation.

        Parameters
        ----------
        request : BackendRelationQueryRequest
            Exact relation lookup request.

        Returns
        -------
        list[tuple[str, str, str, int]]
            Empty include-edge rows for protocol validation.
        """
        del request
        return []

    def find_logical_symbols(
        self,
        root: Path,
        module_name: str,
        logical_name: str,
        *,
        prefix: str | None = None,
        conn: sqlite3.Connection | None = None,
    ) -> list[tuple[str, str, str, str, int]]:
        """
        Return no logical-symbol rows for protocol validation.

        Parameters
        ----------
        root : pathlib.Path
            Repository root.
        module_name : str
            Owning module name.
        logical_name : str
            Logical callable name.
        prefix : str | None, optional
            Optional path filter.
        conn : sqlite3.Connection | None, optional
            Optional SQLite connection.

        Returns
        -------
        list[tuple[str, str, str, str, int]]
            Empty symbol rows for protocol validation.
        """
        del root, module_name, logical_name, prefix, conn
        return []

    def logical_symbol_name(
        self,
        root: Path,
        symbol: tuple[str, str, str, str, int],
        *,
        conn: sqlite3.Connection | None = None,
    ) -> str:
        """
        Return the symbol name as a stand-in logical identity.

        Parameters
        ----------
        root : pathlib.Path
            Repository root.
        symbol : tuple[str, str, str, str, int]
            Indexed symbol row.
        conn : sqlite3.Connection | None, optional
            Optional SQLite connection.

        Returns
        -------
        str
            Symbol name extracted from the supplied row.
        """
        del root, conn
        return symbol[2]

    def embedding_inventory(
        self,
        root: Path,
        *,
        conn: sqlite3.Connection | None = None,
    ) -> list[tuple[str, str, int, int]]:
        """
        Return no embedding inventory rows for protocol validation.

        Parameters
        ----------
        root : pathlib.Path
            Repository root.
        conn : sqlite3.Connection | None, optional
            Optional SQLite connection.

        Returns
        -------
        list[tuple[str, str, int, int]]
            Empty inventory rows for protocol validation.
        """
        del root, conn
        return []

    def find_reference_rows(
        self,
        root: Path,
        name: str,
        *,
        prefix: str | None = None,
        conn: sqlite3.Connection | None = None,
    ) -> list[tuple[str, int, str]]:
        """
        Return no stored reference-search rows for protocol validation.

        Parameters
        ----------
        root : pathlib.Path
            Repository root.
        name : str
            Symbol name to search.
        prefix : str | None, optional
            Optional file prefix restriction.
        conn : sqlite3.Connection | None, optional
            Optional SQLite connection.

        Returns
        -------
        list[tuple[str, int, str]]
            Empty stored rows for protocol validation.
        """
        del root, name, prefix, conn
        return []

    def find_reference_rows_for_names(
        self,
        root: Path,
        names: Sequence[str],
        *,
        prefix: str | None = None,
        conn: sqlite3.Connection | None = None,
    ) -> list[tuple[str, int, str]]:
        """Return no batched reference-search rows for protocol validation.

        Parameters
        ----------
        root : pathlib.Path
            Repository root.
        names : collections.abc.Sequence[str]
            Symbol names to search.
        prefix : str | None, optional
            Optional file prefix restriction.
        conn : sqlite3.Connection | None, optional
            Optional SQLite connection.

        Returns
        -------
        list[tuple[str, int, str]]
            Empty stored rows for protocol validation.
        """
        del root, names, prefix, conn
        return []

    def embedding_candidates(
        self,
        request: BackendEmbeddingCandidatesRequest,
    ) -> list[tuple[float, tuple[str, str, str, str, int]]]:
        """
        Return no embedding candidates for protocol validation.

        Parameters
        ----------
        request : BackendEmbeddingCandidatesRequest
            Embedding candidate lookup request.

        Returns
        -------
        list[tuple[float, tuple[str, str, str, str, int]]]
            Empty candidate rows for protocol validation.
        """
        del request
        return []

    def documentation_candidates(
        self,
        request: BackendDocumentationCandidatesRequest,
    ) -> list[
        tuple[
            float, tuple[str, str, str, str, int, int | None, str, tuple[str, ...], str]
        ]
    ]:
        """
        Return no documentation candidates for protocol validation.

        Parameters
        ----------
        request : BackendDocumentationCandidatesRequest
            Documentation candidate lookup request.

        Returns
        -------
        list[tuple[float, tuple[str, str, str, str, int, int | None, str, tuple[str, ...], str]]]
            Empty candidate rows for protocol validation.
        """
        del request
        return []

    def resolve_embedding_scores(
        self,
        request: BackendResolveEmbeddingScoresRequest,
    ) -> ChannelResults:
        """
        Return no resolved symbol scores for the fake backend.

        Parameters
        ----------
        request : codira.contracts.BackendResolveEmbeddingScoresRequest
            Resolution request carrying vector-store scores.

        Returns
        -------
        codira.types.ChannelResults
            Empty resolved result set.
        """
        del request
        return []

    def resolve_documentation_scores(
        self,
        request: BackendResolveDocumentationScoresRequest,
    ) -> DocumentationChannelResults:
        """
        Return no resolved documentation scores for the fake backend.

        Parameters
        ----------
        request : codira.contracts.BackendResolveDocumentationScoresRequest
            Resolution request carrying vector-store scores.

        Returns
        -------
        codira.types.DocumentationChannelResults
            Empty resolved result set.
        """
        del request
        return []

    def prune_orphaned_embeddings(
        self,
        root: Path,
        *,
        conn: sqlite3.Connection | None = None,
    ) -> None:
        """
        Perform no-op orphaned-embedding cleanup for protocol validation.

        Parameters
        ----------
        root : pathlib.Path
            Repository root.
        conn : sqlite3.Connection | None, optional
            Optional SQLite connection.

        Returns
        -------
        None
            This fake backend keeps no state.
        """
        del root, conn
        return

    def persist_runtime_inventory(
        self,
        request: BackendRuntimeInventoryRequest,
    ) -> None:
        """
        Perform no-op runtime inventory persistence for the fake backend.

        Parameters
        ----------
        request : BackendRuntimeInventoryRequest
            Runtime inventory persistence request.

        Returns
        -------
        None
            This fake backend keeps no state.
        """
        del request
        return

    def commit(self, root: Path, *, conn: object) -> None:
        """
        Perform no-op commit for the fake backend.

        Parameters
        ----------
        root : pathlib.Path
            Repository root.
        conn : object
            Backend connection placeholder.

        Returns
        -------
        None
            This fake backend keeps no state.
        """
        del root, conn
        return

    def close_connection(self, conn: object) -> None:
        """
        Perform no-op connection close for the fake backend.

        Parameters
        ----------
        conn : object
            Backend connection placeholder.

        Returns
        -------
        None
            This fake backend keeps no state.
        """
        del conn
        return

    def current_embedding_state_matches(
        self,
        root: Path,
        *,
        embedding_backend: object,
        conn: sqlite3.Connection | None = None,
    ) -> bool:
        """
        Report a matching embedding state for protocol validation.

        Parameters
        ----------
        root : pathlib.Path
            Repository root.
        embedding_backend : object
            Backend metadata placeholder.
        conn : sqlite3.Connection | None, optional
            Optional SQLite connection.

        Returns
        -------
        bool
            Always ``True`` for protocol validation.
        """
        del root, embedding_backend, conn
        return True


class _FakeIndexWriteSession:
    """
    No-op write session used to validate the protocol surface.

    Parameters
    ----------
    backend : _FakeBackend
        Fake backend that owns the session.
    root : pathlib.Path
        Repository root.
    """

    def __init__(self, backend: _FakeBackend, root: Path) -> None:
        self._backend = backend
        self._root = root

    def purge_skipped_docstring_issues(self) -> None:
        """
        Perform no-op cleanup for skipped docstring diagnostics.

        Parameters
        ----------
        None

        Returns
        -------
        None
            The fake session performs no additional work beyond delegation.
        """
        self._backend.purge_skipped_docstring_issues(self._root)

    def prune_orphaned_embeddings(self) -> None:
        """
        Perform no-op cleanup for orphaned embeddings.

        Parameters
        ----------
        None

        Returns
        -------
        None
            The fake session performs no additional work beyond delegation.
        """
        self._backend.prune_orphaned_embeddings(self._root)

    def load_existing_file_hashes(self) -> dict[str, str]:
        """
        Return the configured indexed file hashes.

        Parameters
        ----------
        None

        Returns
        -------
        dict[str, str]
            Indexed file hashes keyed by absolute path.
        """
        return self._backend.load_existing_file_hashes(self._root)

    def load_existing_file_ownership(self) -> dict[str, tuple[str, str]]:
        """
        Return the configured analyzer ownership mapping.

        Parameters
        ----------
        None

        Returns
        -------
        dict[str, tuple[str, str]]
            Analyzer name and version keyed by absolute path.
        """
        return self._backend.load_existing_file_ownership(self._root)

    def current_embedding_state_matches(self, embedding_backend: object) -> bool:
        """
        Report whether the fake embedding state matches the active backend.

        Parameters
        ----------
        embedding_backend : object
            Opaque embedding-backend descriptor supplied by the caller.

        Returns
        -------
        bool
            ``True`` when the fake backend reports a matching state.
        """
        return self._backend.current_embedding_state_matches(
            self._root,
            embedding_backend=embedding_backend,
        )

    def load_previous_embeddings_by_path(
        self,
        *,
        paths: list[str],
        embedding_backend: object,
    ) -> dict[str, dict[str, object]]:
        """
        Return reusable embeddings for the requested replacement paths.

        Parameters
        ----------
        paths : list[str]
            Absolute file paths selected for replacement.
        embedding_backend : object
            Opaque embedding-backend descriptor supplied by the caller.

        Returns
        -------
        dict[str, dict[str, object]]
            Reusable embeddings grouped by absolute path.
        """
        return self._backend.load_previous_embeddings_by_path(
            self._root,
            paths=paths,
            embedding_backend=embedding_backend,
        )

    def count_reusable_embeddings(self, *, paths: list[str]) -> int:
        """
        Count embeddings preserved for unchanged files.

        Parameters
        ----------
        paths : list[str]
            Absolute file paths reused without reparsing.

        Returns
        -------
        int
            Number of reusable embedding rows.
        """
        return self._backend.count_reusable_embeddings(self._root, paths=paths)

    def prepare(
        self,
        *,
        full: bool,
        indexed_paths: list[str],
        deleted_paths: list[str],
    ) -> None:
        """
        Perform no-op storage preparation for protocol validation.

        Parameters
        ----------
        full : bool
            Whether the current run is a full rebuild.
        indexed_paths : list[str]
            Absolute file paths selected for reindexing.
        deleted_paths : list[str]
            Absolute file paths removed from the repository.

        Returns
        -------
        None
            The fake session does not mutate storage during preparation.
        """
        del full, indexed_paths, deleted_paths

    def persist_analysis(
        self,
        request: BackendPersistAnalysisRequest,
    ) -> tuple[int, int]:
        """
        Record no analyzed-file persistence work.

        Parameters
        ----------
        request : BackendPersistAnalysisRequest
            Persistence request supplied by the caller.

        Returns
        -------
        tuple[int, int]
            ``(0, 0)`` for the fake protocol-validation backend.
        """
        return self._backend.persist_analysis(request)

    def rebuild_derived_indexes(self) -> None:
        """
        Perform no-op derived-index rebuilding.

        Parameters
        ----------
        None

        Returns
        -------
        None
            The fake session performs no additional work beyond delegation.
        """
        self._backend.rebuild_derived_indexes(self._root)

    def persist_runtime_inventory(
        self,
        request: BackendRuntimeInventoryRequest,
    ) -> None:
        """
        Perform no-op runtime inventory persistence.

        Parameters
        ----------
        request : BackendRuntimeInventoryRequest
            Runtime inventory request supplied by the caller.

        Returns
        -------
        None
            The fake session performs no additional work beyond delegation.
        """
        self._backend.persist_runtime_inventory(request)

    def commit(self) -> None:
        """
        Perform no-op commit handling for protocol validation.

        Parameters
        ----------
        None

        Returns
        -------
        None
            The fake session delegates to the backend commit hook.
        """
        self._backend.commit(self._root, conn=object())

    def abort(self) -> None:
        """
        Perform no-op abort handling for protocol validation.

        Parameters
        ----------
        None

        Returns
        -------
        None
            The fake session does not perform rollback work.
        """

    def close(self) -> None:
        """
        Perform no-op close handling for protocol validation.

        Parameters
        ----------
        None

        Returns
        -------
        None
            The fake session does not own external resources.
        """


class _FakeRetrievalProducer:
    """Small retrieval-producer stub used to validate the protocol surface."""

    def retrieval_producer_info(self) -> RetrievalProducerInfo:
        """
        Return deterministic producer identity metadata.

        Parameters
        ----------
        None

        Returns
        -------
        codira.contracts.RetrievalProducerInfo
            Producer and capability-version metadata.
        """
        return RetrievalProducerInfo(
            producer_name="fake-producer",
            producer_version="1",
            capability_version="1",
        )

    def retrieval_capabilities(self) -> tuple[str, ...]:
        """
        Return deterministic capability declarations.

        Parameters
        ----------
        None

        Returns
        -------
        tuple[str, ...]
            Declared capability names.
        """
        return ("symbol_lookup", "graph_relations", "future_extension")


def test_analysis_result_from_parsed_normalizes_python_artifacts(
    tmp_path: Path,
) -> None:
    """
    Normalize current parser output into the ADR-004 artifact model.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary directory provided by pytest.

    Returns
    -------
    None
        The test asserts normalized module, function, method, call, and import
        artifacts.
    """
    module = tmp_path / "pkg" / "sample.py"
    module.parent.mkdir()
    module.write_text(
        '"""Fixture module."""\n'
        "\n"
        "from pkg.helpers import helper as external\n"
        "\n"
        "@pytest.fixture\n"
        "def sample_fixture():\n"
        '    """Build the sample payload."""\n'
        "    return 1\n"
        "\n"
        "def top_level(value):\n"
        '    """Return the direct helper call."""\n'
        "    return external(value)\n"
        "\n"
        "class Demo:\n"
        "    def method(self):\n"
        '        """Return the imported helper."""\n'
        "        assert external is not None\n"
        '        return {"helper": external}\n',
        encoding="utf-8",
    )

    result = PythonAnalyzer().analyze_file(module, tmp_path)

    assert result.module.name == "pkg.sample"
    assert tuple(import_row.name for import_row in result.imports) == (
        "pkg.helpers.helper",
    )
    assert tuple(function.name for function in result.functions) == (
        "sample_fixture",
        "top_level",
    )
    assert result.functions[0].decorators == ("pytest.fixture",)
    assert result.functions[0].has_asserts == 0
    assert tuple(class_row.name for class_row in result.classes) == ("Demo",)
    assert result.classes[0].methods[0].logical_name(class_name="Demo") == "Demo.method"
    assert result.classes[0].methods[0].has_asserts == 1
    assert tuple(call.target for call in result.iter_call_sites()) == ("external",)
    assert tuple(ref.target for ref in result.iter_callable_references()) == (
        "external",
    )


def test_analysis_result_from_parsed_ignores_python_overload_stubs(
    tmp_path: Path,
) -> None:
    """
    Ignore typing overload stubs when normalizing runtime callables.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary directory provided by pytest.

    Returns
    -------
    None
        The test asserts overload declarations do not create duplicate runtime
        function or method artifacts.
    """
    module = tmp_path / "pkg" / "sample.py"
    module.parent.mkdir()
    module.write_text(
        "import typing\n"
        "from typing import overload\n"
        "\n"
        "@overload\n"
        "def build(value: int) -> int: ...\n"
        "\n"
        "@typing.overload\n"
        "def build(value: str) -> str: ...\n"
        "\n"
        "def build(value):\n"
        "    return value\n"
        "\n"
        "class Demo:\n"
        "    @overload\n"
        "    def load(self, value: int) -> int: ...\n"
        "\n"
        "    def load(self, value):\n"
        "        return value\n",
        encoding="utf-8",
    )

    result = PythonAnalyzer().analyze_file(module, tmp_path)

    assert [(function.name, function.lineno) for function in result.functions] == [
        ("build", 10)
    ]
    assert [(method.name, method.lineno) for method in result.classes[0].methods] == [
        ("load", 17)
    ]
    assert tuple(function.stable_id for function in result.functions) == (
        "python:function:pkg.sample:build",
    )
    assert tuple(method.stable_id for method in result.classes[0].methods) == (
        "python:method:pkg.sample:Demo.load",
    )
    assert tuple(overload.stable_id for overload in result.functions[0].overloads) == (
        "python:overload:pkg.sample:build:1",
        "python:overload:pkg.sample:build:2",
    )
    assert tuple(
        overload.parent_stable_id for overload in result.functions[0].overloads
    ) == (
        "python:function:pkg.sample:build",
        "python:function:pkg.sample:build",
    )
    assert tuple(overload.ordinal for overload in result.functions[0].overloads) == (
        1,
        2,
    )
    assert tuple(overload.signature for overload in result.functions[0].overloads) == (
        "build(value)",
        "build(value)",
    )
    assert tuple(
        overload.stable_id for overload in result.classes[0].methods[0].overloads
    ) == ("python:overload:pkg.sample:Demo.load:1",)
    assert tuple(
        overload.parent_stable_id for overload in result.classes[0].methods[0].overloads
    ) == ("python:method:pkg.sample:Demo.load",)


def test_analysis_result_from_parsed_extracts_python_type_alias_declarations(
    tmp_path: Path,
) -> None:
    """
    Normalize explicit top-level Python type aliases as declarations.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary directory provided by pytest.

    Returns
    -------
    None
        The test asserts only explicit top-level type aliases become
        declaration artifacts.
    """
    module = tmp_path / "pkg" / "sample.py"
    module.parent.mkdir()
    module.write_text(
        "import typing\n"
        "from typing import Final, TypeAlias\n"
        "\n"
        "type UserId = int\n"
        "Slug: TypeAlias = str\n"
        "Metadata: typing.TypeAlias = dict[str, int]\n"
        "VALUE = 1\n"
        "TIMEOUT = (1, 2, 3)\n"
        "PORT: int = 8080\n"
        'NAME: Final[str] = "codira"\n'
        "ALIAS = VALUE + 1\n"
        "_PRIVATE = 2\n"
        "\n"
        "class Demo:\n"
        "    Alias: TypeAlias = str\n",
        encoding="utf-8",
    )

    result = PythonAnalyzer().analyze_file(module, tmp_path)

    assert [(decl.kind, decl.name, decl.lineno) for decl in result.declarations] == [
        ("type_alias", "UserId", 4),
        ("type_alias", "Slug", 5),
        ("type_alias", "Metadata", 6),
        ("constant", "VALUE", 7),
        ("constant", "TIMEOUT", 8),
        ("constant", "PORT", 9),
        ("constant", "NAME", 10),
    ]
    assert [(decl.name, decl.signature) for decl in result.declarations] == [
        ("UserId", "type UserId = int"),
        ("Slug", "Slug: TypeAlias = str"),
        ("Metadata", "Metadata: typing.TypeAlias = dict[str, int]"),
        ("VALUE", "VALUE = 1"),
        ("TIMEOUT", "TIMEOUT = (1, 2, 3)"),
        ("PORT", "PORT: int = 8080"),
        ("NAME", 'NAME: Final[str] = "codira"'),
    ]
    assert tuple(decl.stable_id for decl in result.declarations) == (
        "python:type_alias:pkg.sample:UserId",
        "python:type_alias:pkg.sample:Slug",
        "python:type_alias:pkg.sample:Metadata",
        "python:constant:pkg.sample:VALUE",
        "python:constant:pkg.sample:TIMEOUT",
        "python:constant:pkg.sample:PORT",
        "python:constant:pkg.sample:NAME",
    )


def test_sqlite_backend_persists_python_overload_metadata(
    tmp_path: Path,
) -> None:
    """
    Persist overload metadata as child rows under canonical callables.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary directory provided by pytest.

    Returns
    -------
    None
        The test asserts overload rows round-trip through the SQLite backend.
    """
    module = tmp_path / "pkg" / "sample.py"
    module.parent.mkdir()
    module.write_text(
        "from typing import overload\n"
        "\n"
        "@overload\n"
        "def build(value: int) -> int: ...\n"
        "\n"
        "@overload\n"
        "def build(value: str) -> str: ...\n"
        "\n"
        "def build(value):\n"
        "    return value\n",
        encoding="utf-8",
    )

    backend = SQLiteIndexBackend()
    backend.initialize(tmp_path)

    analysis = PythonAnalyzer().analyze_file(module, tmp_path)
    snapshot = FileMetadataSnapshot(
        path=module,
        sha256="overload123",
        mtime=1.0,
        size=module.stat().st_size,
    )

    backend.persist_analysis(
        BackendPersistAnalysisRequest(
            root=tmp_path,
            file_metadata=snapshot,
            analysis=analysis,
        )
    )

    symbol = backend.find_symbol(tmp_path, "build")[0]
    assert backend.find_symbol_overloads(tmp_path, symbol) == [
        (
            "python:overload:pkg.sample:build:1",
            "python:function:pkg.sample:build",
            1,
            "build(value)",
            4,
            4,
            None,
        ),
        (
            "python:overload:pkg.sample:build:2",
            "python:function:pkg.sample:build",
            2,
            "build(value)",
            7,
            7,
            None,
        ),
    ]


def test_run_symbol_json_includes_overload_metadata(
    tmp_path: Path,
    capsys: CaptureFixture[str],
) -> None:
    """
    Render overload metadata only in JSON symbol output.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary directory provided by pytest.
    capsys : pytest.CaptureFixture[str]
        Captured output fixture.

    Returns
    -------
    None
        The test asserts the JSON payload carries overload detail.
    """
    module = tmp_path / "pkg" / "sample.py"
    module.parent.mkdir()
    module.write_text(
        "from typing import overload\n"
        "\n"
        "@overload\n"
        "def build(value: int) -> int: ...\n"
        "\n"
        "def build(value):\n"
        "    return value\n",
        encoding="utf-8",
    )

    backend = SQLiteIndexBackend()
    backend.initialize(tmp_path)
    analysis = PythonAnalyzer().analyze_file(module, tmp_path)
    snapshot = FileMetadataSnapshot(
        path=module,
        sha256="json-overload",
        mtime=1.0,
        size=module.stat().st_size,
    )
    backend.persist_analysis(
        BackendPersistAnalysisRequest(
            root=tmp_path,
            file_metadata=snapshot,
            analysis=analysis,
        )
    )

    assert _run_symbol(tmp_path, "build", as_json=True) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["results"] == [
        {
            "type": "function",
            "module": "pkg.sample",
            "name": "build",
            "file": str(module),
            "lineno": 6,
            "overloads": [
                {
                    "kind": "overload",
                    "stable_id": "python:overload:pkg.sample:build:1",
                    "parent_stable_id": "python:function:pkg.sample:build",
                    "ordinal": 1,
                    "signature": "build(value)",
                    "lineno": 4,
                    "end_lineno": 4,
                    "docstring": None,
                }
            ],
        }
    ]


def test_run_symbol_json_includes_enum_member_metadata(
    tmp_path: Path,
    capsys: CaptureFixture[str],
) -> None:
    """
    Render enum-member metadata only in JSON symbol output.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary directory provided by pytest.
    capsys : pytest.CaptureFixture[str]
        Captured output fixture.

    Returns
    -------
    None
        The test asserts the JSON payload carries enum-member detail.
    """
    source = tmp_path / "native" / "types.h"
    source.parent.mkdir()
    source.write_text(
        "enum Color { RED, GREEN = 3, BLUE };\n",
        encoding="utf-8",
    )

    backend = SQLiteIndexBackend()
    backend.initialize(tmp_path)
    analysis = CAnalyzer().analyze_file(source, tmp_path)
    snapshot = FileMetadataSnapshot(
        path=source,
        sha256="json-enum-members",
        mtime=1.0,
        size=source.stat().st_size,
    )
    backend.persist_analysis(
        BackendPersistAnalysisRequest(
            root=tmp_path,
            file_metadata=snapshot,
            analysis=analysis,
        )
    )

    assert _run_symbol(tmp_path, "Color", as_json=True) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["results"] == [
        {
            "type": "enum",
            "module": "native.types",
            "name": "Color",
            "file": str(source),
            "lineno": 1,
            "enum_members": [
                {
                    "kind": "enum_member",
                    "stable_id": "c:enum_member:native/types.h:Color:1",
                    "parent_stable_id": "c:enum:native/types.h:Color",
                    "ordinal": 1,
                    "name": "RED",
                    "signature": "RED",
                    "lineno": 1,
                },
                {
                    "kind": "enum_member",
                    "stable_id": "c:enum_member:native/types.h:Color:2",
                    "parent_stable_id": "c:enum:native/types.h:Color",
                    "ordinal": 2,
                    "name": "GREEN",
                    "signature": "GREEN = 3",
                    "lineno": 1,
                },
                {
                    "kind": "enum_member",
                    "stable_id": "c:enum_member:native/types.h:Color:3",
                    "parent_stable_id": "c:enum:native/types.h:Color",
                    "ordinal": 3,
                    "name": "BLUE",
                    "signature": "BLUE",
                    "lineno": 1,
                },
            ],
        }
    ]


def test_run_symbol_json_includes_python_constant_detail(
    tmp_path: Path,
    capsys: CaptureFixture[str],
) -> None:
    """
    Render Python constant detail only in JSON symbol output.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary directory provided by pytest.
    capsys : pytest.CaptureFixture[str]
        Captured output fixture.

    Returns
    -------
    None
        The test asserts the JSON payload carries constant detail.
    """
    module = tmp_path / "pkg" / "sample.py"
    module.parent.mkdir()
    module.write_text(
        'NAME: str = "codira"\n',
        encoding="utf-8",
    )

    backend = SQLiteIndexBackend()
    backend.initialize(tmp_path)
    analysis = PythonAnalyzer().analyze_file(module, tmp_path)
    snapshot = FileMetadataSnapshot(
        path=module,
        sha256="json-constant",
        mtime=1.0,
        size=module.stat().st_size,
        analyzer_name="python",
        analyzer_version=PythonAnalyzer().version,
    )
    backend.persist_analysis(
        BackendPersistAnalysisRequest(
            root=tmp_path,
            file_metadata=snapshot,
            analysis=analysis,
        )
    )

    assert _run_symbol(tmp_path, "NAME", as_json=True) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["results"] == [
        {
            "type": "constant",
            "module": "pkg.sample",
            "name": "NAME",
            "file": str(module),
            "lineno": 1,
            "constant_detail": {
                "kind": "constant_detail",
                "annotation": "str",
                "value": '"codira"',
            },
        }
    ]


def test_analysis_result_from_parsed_disambiguates_property_accessors(
    tmp_path: Path,
) -> None:
    """
    Assign distinct stable IDs to Python property accessors.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary directory provided by pytest.

    Returns
    -------
    None
        The test asserts getter and setter methods do not collide.
    """
    module = tmp_path / "pkg" / "sample.py"
    module.parent.mkdir()
    module.write_text(
        "class Demo:\n"
        "    @property\n"
        "    def value(self):\n"
        "        return 1\n"
        "\n"
        "    @value.setter\n"
        "    def value(self, new_value):\n"
        "        self._value = new_value\n",
        encoding="utf-8",
    )

    result = PythonAnalyzer().analyze_file(module, tmp_path)

    methods = result.classes[0].methods
    assert tuple(method.name for method in methods) == ("value", "value")
    assert tuple(method.stable_id for method in methods) == (
        "python:method:pkg.sample:Demo.value",
        "python:method:pkg.sample:Demo.value:setter",
    )


def test_python_analyzer_reads_pep_263_encoded_sources(tmp_path: Path) -> None:
    """
    Decode Python sources according to declared encoding cookies.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary directory provided by pytest.

    Returns
    -------
    None
        The test asserts analyzer-local decoding accepts non-UTF-8 Python
        sources and preserves bounded declaration extraction.
    """
    package = tmp_path / "pkg"
    package.mkdir()

    latin1_module = package / "latin1_sample.py"
    latin1_module.write_bytes('# coding: latin-1\nTITLE = "café"\n'.encode("latin-1"))

    koi8r_module = package / "koi8r_sample.py"
    koi8r_module.write_bytes('# coding: koi8-r\nMESSAGE = "привет"\n'.encode("koi8-r"))

    latin1_result = PythonAnalyzer().analyze_file(latin1_module, tmp_path)
    koi8r_result = PythonAnalyzer().analyze_file(koi8r_module, tmp_path)

    assert [
        (declaration.name, declaration.signature)
        for declaration in latin1_result.declarations
    ] == [
        (
            "TITLE",
            'TITLE = "café"',
        ),
    ]
    assert [
        (declaration.name, declaration.signature)
        for declaration in koi8r_result.declarations
    ] == [
        (
            "MESSAGE",
            'MESSAGE = "привет"',
        ),
    ]


def test_python_analyzer_disambiguates_duplicate_stable_id_shapes(
    tmp_path: Path,
) -> None:
    """
    Rewrite colliding Python stable IDs across observed CPython shapes.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary directory provided by pytest.

    Returns
    -------
    None
        The test asserts duplicate functions, classes, methods, and constants
        are made unique before index-time validation.
    """
    module = tmp_path / "pkg" / "sample.py"
    module.parent.mkdir()
    module.write_text(
        "def _():\n"
        "    return 1\n"
        "\n"
        "def _():\n"
        "    return 2\n"
        "\n"
        "def clone():\n"
        "    return 1\n"
        "\n"
        "def clone():\n"
        "    return 2\n"
        "\n"
        "class Loader:\n"
        "    def run(self):\n"
        "        return 1\n"
        "\n"
        "class Loader:\n"
        "    def run(self):\n"
        "        return 2\n"
        "\n"
        "class Demo:\n"
        "    def value(self):\n"
        "        return 1\n"
        "\n"
        "    def value(self):\n"
        "        return 2\n"
        "\n"
        "ALIAS = 1\n"
        "ALIAS = 2\n",
        encoding="utf-8",
    )

    result = PythonAnalyzer().analyze_file(module, tmp_path)

    duplicate_functions = [
        function.stable_id
        for function in result.functions
        if function.name in {"_", "clone"}
    ]
    duplicate_classes = [
        class_artifact.stable_id
        for class_artifact in result.classes
        if class_artifact.name == "Loader"
    ]
    duplicate_methods = [
        method.stable_id
        for class_artifact in result.classes
        for method in class_artifact.methods
        if (class_artifact.name, method.name) in {("Loader", "run"), ("Demo", "value")}
    ]
    duplicate_declarations = [
        declaration.stable_id
        for declaration in result.declarations
        if declaration.name == "ALIAS"
    ]

    assert _duplicate_analysis_stable_ids(result) == []
    assert duplicate_functions == [
        "python:function:pkg.sample:_:1",
        "python:function:pkg.sample:_:2",
        "python:function:pkg.sample:clone:1",
        "python:function:pkg.sample:clone:2",
    ]
    assert duplicate_classes == [
        "python:class:pkg.sample:Loader:1",
        "python:class:pkg.sample:Loader:2",
    ]
    assert duplicate_methods == [
        "python:method:pkg.sample:Loader.run:1",
        "python:method:pkg.sample:Loader.run:2",
        "python:method:pkg.sample:Demo.value:1",
        "python:method:pkg.sample:Demo.value:2",
    ]
    assert duplicate_declarations == [
        "python:constant:pkg.sample:ALIAS:1",
        "python:constant:pkg.sample:ALIAS:2",
    ]


def test_parse_file_excludes_nested_helper_control_flow_from_outer_metadata(
    tmp_path: Path,
) -> None:
    """
    Keep nested helper control flow out of outer callable metadata.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary directory provided by pytest.

    Returns
    -------
    None
        The test asserts nested helper ``return``, ``yield``, and ``raise``
        statements do not affect the outer function flags.
    """
    module = tmp_path / "pkg" / "sample.py"
    module.parent.mkdir()
    module.write_text(
        "import contextlib\n"
        "\n"
        "def outer() -> None:\n"
        '    """Exercise nested helpers."""\n'
        "    @contextlib.contextmanager\n"
        "    def locked():\n"
        "        yield\n"
        "\n"
        "    def compute() -> int:\n"
        "        return 1\n"
        "\n"
        "    def fail() -> None:\n"
        '        raise RuntimeError("boom")\n'
        "\n"
        "    with locked():\n"
        "        pass\n",
        encoding="utf-8",
    )

    function = PythonAnalyzer().analyze_file(module, tmp_path).functions[0]

    assert function.name == "outer"
    assert function.returns_value == 0
    assert function.yields_value == 0
    assert function.raises == 0


def test_language_analyzer_index_backend_and_retrieval_protocols_are_runtime_checkable() -> (
    None
):
    """
    Ensure the Phase 3 protocol types accept conforming implementations.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test asserts runtime protocol compatibility for analyzer, backend,
        and retrieval-producer stubs.
    """
    assert isinstance(PythonAnalyzer(), LanguageAnalyzer)
    assert isinstance(CAnalyzer(), LanguageAnalyzer)
    assert isinstance(CppAnalyzer(), LanguageAnalyzer)
    assert isinstance(RustAnalyzer(), LanguageAnalyzer)
    assert isinstance(_FakeAnalyzer(), LanguageAnalyzer)
    assert isinstance(_FakeEmbeddingEngine(), EmbeddingEngine)
    assert isinstance(_FakeVectorStore(), VectorStore)
    assert isinstance(_FakeBackend(), IndexBackend)
    assert isinstance(_FakeRetrievalProducer(), RetrievalProducer)
    assert isinstance(EMBEDDING_RETRIEVAL_PRODUCER, RetrievalProducer)
    assert all(
        isinstance(producer, RetrievalProducer)
        for producer in CHANNEL_PRODUCER_SPECS.values()
    )


def test_graph_retrieval_producers_implement_contracts() -> None:
    """
    Keep graph retrieval producers aligned with the retrieval contract.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test asserts graph producer singletons satisfy the protocol.
    """
    assert isinstance(CALL_GRAPH_RETRIEVAL_PRODUCER, RetrievalProducer)
    assert isinstance(REFERENCE_RETRIEVAL_PRODUCER, RetrievalProducer)
    assert isinstance(INCLUDE_GRAPH_RETRIEVAL_PRODUCER, RetrievalProducer)


def test_split_declared_retrieval_capabilities_partitions_known_and_unknown() -> None:
    """
    Partition declared retrieval capabilities deterministically.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test asserts known capabilities remain ordered and unknown
        extensions are retained for diagnostics.
    """
    known, unknown = split_declared_retrieval_capabilities(
        (
            "symbol_lookup",
            "graph_relations",
            "symbol_lookup",
            "future_extension",
            " ",
            "embedding_similarity",
        )
    )

    assert known == (
        "symbol_lookup",
        "graph_relations",
        "embedding_similarity",
    )
    assert unknown == ("future_extension",)
    assert "symbol_lookup" in KNOWN_RETRIEVAL_CAPABILITIES


def test_root_optional_dependencies_support_monorepo_bundle_install() -> None:
    """
    Keep root extras compatible with editable installs in the current monorepo.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test asserts the root package keeps the curated bundle aligned to
        the first-party distribution set and preserves the canonical docs extra,
        including documentation navigation plugins.
    """
    with Path("pyproject.toml").open("rb") as pyproject_file:
        pyproject = tomllib.load(pyproject_file)
    project = pyproject["project"]

    optional_dependencies = project["optional-dependencies"]

    assert optional_dependencies["docs"] == [
        "mkdocs>=1.6,<2.0",
        "mkdocs-material>=9.7,<10.0",
        "mkdocs-awesome-pages-plugin>=2.10,<3.0",
        "mkdocstrings[python]>=1.0,<2.0",
    ]
    assert optional_dependencies["bundle-official"] == [
        "sentence-transformers>=5.4,<6.0",
        "einops>=0.8,<1.0",
        "codira-analyzer-python==2.0.0",
        "codira-analyzer-json==2.0.0",
        "codira-analyzer-c==2.0.0",
        "codira-analyzer-cpp==2.0.0",
        "codira-analyzer-rust==2.0.0",
        "codira-analyzer-javascript==2.0.0",
        "codira-analyzer-typescript==2.0.0",
        "codira-analyzer-go==2.0.0",
        "codira-analyzer-bash==2.0.0",
        "codira-analyzer-markdown==2.0.0",
        "codira-analyzer-text==2.0.0",
        "codira-documentation-audit-numpy==2.0.0",
        "codira-documentation-audit-google==2.0.0",
        "codira-documentation-audit-doxygen==2.0.0",
        "codira-documentation-audit-rustdoc==2.0.0",
        "codira-documentation-audit-jsdoc==2.0.0",
        "codira-documentation-audit-tsdoc==2.0.0",
        "codira-documentation-audit-go-doc-comments==2.0.0",
        "codira-backend-sqlite==2.0.0",
        "codira-backend-duckdb==2.0.0",
        "codira-embedding-sentence-transformers==2.0.0",
        "codira-embedding-onnx==2.0.0",
        "codira-vector-store-sqlite==2.0.0",
        "codira-vector-store-duckdb==2.0.0",
    ]
    assert pyproject.get("tool", {}).get("poetry") is None


def test_active_phase_8_registries_expose_default_backend_and_analyzers() -> None:
    """
    Keep the Phase 8 registry defaults explicit and runtime-checkable.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test asserts the default backend and analyzer registry instances.
    """
    backend = active_index_backend()
    analyzers = active_language_analyzers()

    assert backend.__class__.__name__ == "SQLiteIndexBackend"
    assert backend.__class__.__module__ == "codira_backend_sqlite"
    assert [analyzer.name for analyzer in analyzers] == [
        "python",
        "json",
        "c",
        "cpp",
        "rust",
        "bash",
        "markdown",
        "text",
        "go",
        "javascript",
        "typescript",
    ]


def test_indexer_keeps_sqlite_backend_symbols_out_of_core() -> None:
    """
    Keep SQLite backend symbols owned by the backend package.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test asserts core exposes no SQLite backend compatibility export.
    """
    assert "SQLiteIndexBackend" not in indexer_module.__all__
    assert not hasattr(indexer_module, "SQLiteIndexBackend")


def test_registered_index_backends_keep_core_scope_narrow() -> None:
    """
    Keep the built-in backend factory list limited to core-owned implementations.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test asserts the default SQLite backend now loads through the
        first-party backend package rather than a core factory list.
    """
    backends = registry_module._registered_index_backends()

    assert backends == {}


def test_registered_language_analyzer_factories_keep_core_scope_narrow() -> None:
    """
    Keep the built-in analyzer factory list limited to core-owned analyzers.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test asserts optional first-party analyzers are not hard-wired into
        the core factory list.
    """
    factories = registry_module._registered_language_analyzer_factories()

    assert [factory().name for factory in factories] == []


def test_active_language_analyzers_skip_optional_c_when_dependencies_missing(
    monkeypatch: MonkeyPatch,
) -> None:
    """
    Skip the optional C analyzer when its plugin package is unavailable.

    Parameters
    ----------
    monkeypatch : pytest.MonkeyPatch
        Pytest fixture used to patch entry-point discovery.

    Returns
    -------
    None
        The test asserts the registry keeps Python active and omits C.
    """
    monkeypatch.setattr(
        registry_module,
        "_entry_points_for_group",
        lambda group: [],
    )

    try:
        active_language_analyzers()
    except ValueError as exc:
        message = str(exc)
    else:
        msg = "expected ValueError when no analyzers are registered"
        raise AssertionError(msg)

    assert message == "No language analyzers are registered for codira"
