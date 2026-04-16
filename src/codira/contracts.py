"""Core pluggable contracts introduced for ADR-004 Phase 3.

Responsibilities
----------------
- Define the `LanguageAnalyzer` and `IndexBackend` protocols that decouple parsing from persistence.
- Describe expectations for analyzer discovery, file support, and normalized `AnalysisResult` production.
- Specify backend responsibilities such as initialization, hash loading, deletion, and persistence operations.

Design principles
-----------------
Contracts stay explicit, minimal, and runtime-checkable so custom analyzers or backends can plug into the ADR-004 stack deterministically.

Architectural role
------------------
This module belongs to the **contract definition layer** that governs pluggable language analysis and storage backends.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, Protocol, runtime_checkable

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from pathlib import Path

    from codira.models import AnalysisResult, FileMetadataSnapshot
    from codira.semantic.embeddings import EmbeddingBackendSpec
    from codira.types import (
        ChannelResults,
        DocstringIssueRow,
        IncludeEdgeRow,
        SymbolRow,
    )


class BackendError(RuntimeError):
    """
    Backend-neutral persistence failure.

    Parameters
    ----------
    None

    Returns
    -------
    None
        Instances carry the backend failure message through ``RuntimeError``.
    """


@runtime_checkable
class LanguageAnalyzer(Protocol):
    """
    Contract for file analyzers participating in one indexing run.

    Implementations are responsible only for language-specific analysis and
    normalized artifact production. They must not own storage policy.
    """

    name: str
    version: str
    discovery_globs: tuple[str, ...]

    def supports_path(self, path: Path) -> bool:
        """
        Decide whether the analyzer can process a source path.

        Parameters
        ----------
        path : pathlib.Path
            Candidate repository file.

        Returns
        -------
        bool
            ``True`` when the analyzer accepts the file.
        """

    def analyze_file(self, path: Path, root: Path) -> AnalysisResult:
        """
        Analyze one source file and emit normalized artifacts.

        Parameters
        ----------
        path : pathlib.Path
            Source file to analyze.
        root : pathlib.Path
            Repository root used for relative resolution.

        Returns
        -------
        codira.models.AnalysisResult
            Normalized artifacts for the file.
        """


RetrievalCapabilityName = Literal[
    "symbol_lookup",
    "semantic_text",
    "embedding_similarity",
    "task_specialization",
    "graph_relations",
    "issue_annotations",
    "diagnostics_metadata",
]

KNOWN_RETRIEVAL_CAPABILITIES: tuple[RetrievalCapabilityName, ...] = (
    "symbol_lookup",
    "semantic_text",
    "embedding_similarity",
    "task_specialization",
    "graph_relations",
    "issue_annotations",
    "diagnostics_metadata",
)


@dataclass(frozen=True)
class RetrievalProducerInfo:
    """
    Versioned identity for one retrieval-facing producer.

    Parameters
    ----------
    producer_name : str
        Stable producer identifier used in diagnostics and explain output.
    producer_version : str
        Producer implementation version.
    capability_version : str
        Version of the capability contract understood by the producer.
    """

    producer_name: str
    producer_version: str
    capability_version: str


@runtime_checkable
class RetrievalProducer(Protocol):
    """
    Contract for retrieval-facing producers that declare scoring capabilities.

    This protocol is layered beside ``LanguageAnalyzer`` so retrieval
    participation can evolve without overloading file-analysis contracts.
    """

    def retrieval_producer_info(self) -> RetrievalProducerInfo:
        """
        Return versioned identity metadata for one retrieval producer.

        Parameters
        ----------
        None

        Returns
        -------
        codira.contracts.RetrievalProducerInfo
            Producer identity and capability-version metadata.
        """

    def retrieval_capabilities(self) -> tuple[str, ...]:
        """
        Return declared retrieval capabilities for one producer.

        Parameters
        ----------
        None

        Returns
        -------
        tuple[str, ...]
            Declared capability names in deterministic order.
        """


def split_declared_retrieval_capabilities(
    capabilities: Sequence[str],
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """
    Partition declared retrieval capabilities into known and unknown values.

    Parameters
    ----------
    capabilities : collections.abc.Sequence[str]
        Raw capability names declared by a retrieval producer.

    Returns
    -------
    tuple[tuple[str, ...], tuple[str, ...]]
        Known and unknown capability names in deterministic declaration order
        with duplicates removed.
    """
    known_set = set(KNOWN_RETRIEVAL_CAPABILITIES)
    seen: set[str] = set()
    known: list[str] = []
    unknown: list[str] = []

    for capability in capabilities:
        normalized = str(capability).strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        if normalized in known_set:
            known.append(normalized)
        else:
            unknown.append(normalized)

    return tuple(known), tuple(unknown)


@runtime_checkable
class IndexBackend(Protocol):
    """
    Contract for the single active persistence backend of one repository index.

    Backends own storage and query persistence concerns but must not perform
    language-specific parsing.
    """

    name: str
    version: str

    def open_connection(self, root: Path) -> object:
        """
        Open a backend connection for one repository index.

        Parameters
        ----------
        root : pathlib.Path
            Repository root whose backend connection should be opened.

        Returns
        -------
        object
            Open backend connection handle.
        """

    def load_runtime_inventory(
        self,
        root: Path,
        *,
        conn: object | None = None,
    ) -> tuple[str, str, int] | None:
        """
        Return persisted backend and coverage metadata for the last index run.

        Parameters
        ----------
        root : pathlib.Path
            Repository root whose backend state should be queried.
        conn : object | None, optional
            Existing backend connection to reuse.

        Returns
        -------
        tuple[str, str, int] | None
            Stored ``(backend_name, backend_version, coverage_complete)``
            tuple, or ``None`` when no runtime inventory is available.
        """

    def load_analyzer_inventory(
        self,
        root: Path,
        *,
        conn: object | None = None,
    ) -> list[tuple[str, str, str]]:
        """
        Return persisted analyzer inventory for the last index run.

        Parameters
        ----------
        root : pathlib.Path
            Repository root whose backend state should be queried.
        conn : object | None, optional
            Existing backend connection to reuse.

        Returns
        -------
        list[tuple[str, str, str]]
            Stored analyzer rows as ``(name, version, discovery_globs_json)``.
        """

    def initialize(self, root: Path) -> None:
        """
        Prepare persistent backend state for a repository root.

        Parameters
        ----------
        root : pathlib.Path
            Repository root whose index should be prepared.

        Returns
        -------
        None
            Backend state is created or refreshed in place.
        """

    def load_existing_file_hashes(
        self,
        root: Path,
        *,
        conn: object | None = None,
    ) -> dict[str, str]:
        """
        Load indexed file hashes used for incremental reuse decisions.

        Parameters
        ----------
        root : pathlib.Path
            Repository root whose backend state should be queried.
        conn : object | None, optional
            Existing backend connection to reuse.

        Returns
        -------
        dict[str, str]
            Indexed file hashes keyed by absolute file path.
        """

    def load_existing_file_ownership(
        self,
        root: Path,
        *,
        conn: object | None = None,
    ) -> dict[str, tuple[str, str]]:
        """
        Load persisted analyzer ownership keyed by absolute path.

        Parameters
        ----------
        root : pathlib.Path
            Repository root whose backend state should be queried.
        conn : object | None, optional
            Existing backend connection to reuse.

        Returns
        -------
        dict[str, tuple[str, str]]
            Indexed analyzer ownership keyed by absolute file path.
        """

    def delete_paths(
        self,
        root: Path,
        *,
        paths: Sequence[str],
        conn: object | None = None,
    ) -> None:
        """
        Remove persisted artifacts owned by the supplied file paths.

        Parameters
        ----------
        root : pathlib.Path
            Repository root whose backend state should be updated.
        paths : collections.abc.Sequence[str]
            Absolute file paths to remove from backend state.
        conn : object | None, optional
            Existing backend connection to reuse.

        Returns
        -------
        None
            Matching persisted artifacts are removed in place.
        """

    def clear_index(self, root: Path, *, conn: object | None = None) -> None:
        """
        Remove all indexed artifacts from backend state.

        Parameters
        ----------
        root : pathlib.Path
            Repository root whose backend state should be cleared.
        conn : object | None, optional
            Existing backend connection to reuse.

        Returns
        -------
        None
            Indexed artifacts are removed in place.
        """

    def purge_skipped_docstring_issues(
        self,
        root: Path,
        *,
        conn: object | None = None,
    ) -> None:
        """
        Remove backend-owned legacy docstring diagnostics skipped by policy.

        Parameters
        ----------
        root : pathlib.Path
            Repository root whose backend state should be cleaned.
        conn : object | None, optional
            Existing backend connection to reuse.

        Returns
        -------
        None
            Matching diagnostics are removed in place.
        """

    def load_previous_embeddings_by_path(
        self,
        root: Path,
        *,
        paths: Sequence[str],
        embedding_backend: EmbeddingBackendSpec,
        conn: object | None = None,
    ) -> dict[str, dict[str, object]]:
        """
        Load reusable semantic artifacts for paths that will be replaced.

        Parameters
        ----------
        root : pathlib.Path
            Repository root whose backend state should be queried.
        paths : collections.abc.Sequence[str]
            Absolute file paths selected for replacement.
        embedding_backend : codira.semantic.embeddings.EmbeddingBackendSpec
            Active semantic backend metadata used to filter reusable artifacts.
        conn : object | None, optional
            Existing backend connection to reuse.

        Returns
        -------
        dict[str, dict[str, object]]
            Previous semantic artifacts grouped by absolute file path.
        """

    def persist_analysis(
        self,
        root: Path,
        *,
        file_metadata: FileMetadataSnapshot,
        analysis: AnalysisResult,
        embedding_backend: EmbeddingBackendSpec | None = None,
        previous_embeddings: Mapping[str, object] | None = None,
        conn: object | None = None,
    ) -> tuple[int, int]:
        """
        Persist normalized artifacts for one analyzed file snapshot.

        Parameters
        ----------
        root : pathlib.Path
            Repository root whose backend state should be updated.
        file_metadata : codira.models.FileMetadataSnapshot
            Stable file metadata captured during scanning.
        analysis : codira.models.AnalysisResult
            Normalized analyzer output for the file.
        embedding_backend : codira.contracts.EmbeddingBackendSpec | None, optional
            Optional semantic embedding backend used during persistence.
        previous_embeddings : collections.abc.Mapping[str, object] | None, optional
            Previously persisted semantic artifacts eligible for reuse.
        conn : object | None, optional
            Existing backend connection to reuse.

        Returns
        -------
        tuple[int, int]
            ``(recomputed, reused)`` semantic-artifact counts for the file.
        """

    def count_reusable_embeddings(
        self,
        root: Path,
        *,
        paths: Sequence[str],
        conn: object | None = None,
    ) -> int:
        """
        Count semantic artifacts that remain reusable for unchanged files.

        Parameters
        ----------
        root : pathlib.Path
            Repository root whose backend state should be queried.
        paths : collections.abc.Sequence[str]
            Absolute file paths considered reusable.
        conn : object | None, optional
            Existing backend connection to reuse.

        Returns
        -------
        int
            Number of reusable semantic artifacts retained by the backend.
        """

    def rebuild_derived_indexes(
        self,
        root: Path,
        *,
        conn: object | None = None,
    ) -> None:
        """
        Rebuild derived backend state after raw artifact persistence.

        Parameters
        ----------
        root : pathlib.Path
            Repository root whose backend state should be finalized.
        conn : object | None, optional
            Existing backend connection to reuse.

        Returns
        -------
        None
            Derived backend indexes are refreshed in place.
        """

    def persist_runtime_inventory(
        self,
        root: Path,
        *,
        backend_name: str,
        backend_version: str,
        coverage_complete: bool,
        analyzers: Sequence[LanguageAnalyzer],
        conn: object | None = None,
    ) -> None:
        """
        Persist backend and analyzer inventory for a completed index run.

        Parameters
        ----------
        root : pathlib.Path
            Repository root whose backend state should be updated.
        backend_name : str
            Active backend name.
        backend_version : str
            Active backend version.
        coverage_complete : bool
            Whether canonical-directory coverage had no gaps.
        analyzers : collections.abc.Sequence[codira.contracts.LanguageAnalyzer]
            Active analyzers for the run.
        conn : object | None, optional
            Existing backend connection to reuse.

        Returns
        -------
        None
            Runtime inventory rows are replaced in place.
        """

    def commit(self, root: Path, *, conn: object) -> None:
        """
        Commit pending backend writes on an open connection.

        Parameters
        ----------
        root : pathlib.Path
            Repository root whose backend connection is being committed.
        conn : object
            Backend-owned connection handle.

        Returns
        -------
        None
            Pending backend writes are committed.
        """

    def close_connection(self, conn: object) -> None:
        """
        Close an open backend connection handle.

        Parameters
        ----------
        conn : object
            Backend-owned connection handle.

        Returns
        -------
        None
            The backend handle is closed or released.
        """

    def find_include_edges(
        self,
        root: Path,
        name: str,
        *,
        module: str | None = None,
        incoming: bool = False,
        prefix: str | None = None,
        conn: object | None = None,
    ) -> list[IncludeEdgeRow]:
        """
        Find exact include-like edges for an owner module or included target.

        Parameters
        ----------
        root : pathlib.Path
            Repository root whose index should be queried.
        name : str
            Exact owner module name or include target path to search for.
        module : str | None, optional
            Optional owner-module qualifier used to restrict incoming results.
        incoming : bool, optional
            Whether to return incoming edges for the included target.
        prefix : str | None, optional
            Repo-root-relative path prefix used to restrict owner files.
        conn : object | None, optional
            Existing backend connection to reuse.

        Returns
        -------
        list[codira.types.IncludeEdgeRow]
            Matching include-edge rows ordered deterministically as
            ``(owner_module, target_name, kind, lineno)`` tuples.
        """

    def find_logical_symbols(
        self,
        root: Path,
        module_name: str,
        logical_name: str,
        *,
        prefix: str | None = None,
        conn: object | None = None,
    ) -> list[SymbolRow]:
        """
        Resolve a logical callable name back to indexed symbol rows.

        Parameters
        ----------
        root : pathlib.Path
            Repository root whose index should be queried.
        module_name : str
            Dotted module that owns the logical symbol.
        logical_name : str
            Logical symbol identity such as ``helper`` or ``Class.method``.
        prefix : str | None, optional
            Repo-root-relative path prefix used to restrict symbol files.
        conn : object | None, optional
            Existing backend connection to reuse.

        Returns
        -------
        list[codira.types.SymbolRow]
            Matching indexed symbol rows ordered deterministically.
        """

    def logical_symbol_name(
        self,
        root: Path,
        symbol: SymbolRow,
        *,
        conn: object | None = None,
    ) -> str:
        """
        Return the logical graph identity for one indexed symbol row.

        Parameters
        ----------
        root : pathlib.Path
            Repository root whose index should be queried.
        symbol : codira.types.SymbolRow
            Indexed symbol row whose logical identity should be resolved.
        conn : object | None, optional
            Existing backend connection to reuse.

        Returns
        -------
        str
            Logical symbol identity used by graph edges.
        """

    def embedding_inventory(
        self,
        root: Path,
        *,
        conn: object | None = None,
    ) -> list[tuple[str, str, int, int]]:
        """
        Return stored embedding inventory grouped by backend metadata.

        Parameters
        ----------
        root : pathlib.Path
            Repository root whose index should be queried.
        conn : object | None, optional
            Existing backend connection to reuse.

        Returns
        -------
        list[tuple[str, str, int, int]]
            Rows as ``(backend, version, dim, count)`` ordered deterministically.
        """

    def embedding_candidates(
        self,
        root: Path,
        query: str,
        *,
        limit: int,
        min_score: float,
        prefix: str | None = None,
        conn: object | None = None,
    ) -> ChannelResults:
        """
        Return ranked symbol candidates using stored embedding similarity.

        Parameters
        ----------
        root : pathlib.Path
            Repository root whose index should be queried.
        query : str
            User query string.
        limit : int
            Maximum number of ranked results to return.
        min_score : float
            Minimum similarity threshold for emitted results.
        prefix : str | None, optional
            Repo-root-relative path prefix used to restrict matched symbol files.
        conn : object | None, optional
            Existing backend connection to reuse.

        Returns
        -------
        codira.types.ChannelResults
            Ranked symbol candidates ordered deterministically.
        """

    def prune_orphaned_embeddings(
        self,
        root: Path,
        *,
        conn: object | None = None,
    ) -> None:
        """
        Remove embedding rows whose owning symbol no longer exists.

        Parameters
        ----------
        root : pathlib.Path
            Repository root whose index should be cleaned.
        conn : object | None, optional
            Existing backend connection to reuse.

        Returns
        -------
        None
            Orphaned embedding rows are removed in place.
        """

    def current_embedding_state_matches(
        self,
        root: Path,
        *,
        embedding_backend: EmbeddingBackendSpec,
        conn: object | None = None,
    ) -> bool:
        """
        Check whether persisted embeddings match the active embedding backend.

        Parameters
        ----------
        root : pathlib.Path
            Repository root whose index should be queried.
        embedding_backend : codira.semantic.embeddings.EmbeddingBackendSpec
            Active embedding backend metadata.
        conn : object | None, optional
            Existing backend connection to reuse.

        Returns
        -------
        bool
            ``True`` when the persisted embedding metadata matches.
        """

    def list_symbols_in_module(
        self,
        root: Path,
        module: str,
        *,
        prefix: str | None = None,
        limit: int = 20,
        conn: object | None = None,
    ) -> list[SymbolRow]:
        """
        Return indexed symbols belonging to one module.

        Parameters
        ----------
        root : pathlib.Path
            Repository root whose index should be queried.
        module : str
            Dotted module name to expand.
        prefix : str | None, optional
            Repo-root-relative path prefix used to restrict symbol files.
        limit : int, optional
            Maximum number of symbol rows to return.
        conn : object | None, optional
            Existing backend connection to reuse.

        Returns
        -------
        list[codira.types.SymbolRow]
            Indexed symbols belonging to the requested module.
        """

    def find_symbol(
        self,
        root: Path,
        name: str,
        *,
        prefix: str | None = None,
        conn: object | None = None,
    ) -> list[SymbolRow]:
        """
        Find exact symbol-name matches in the index.

        Parameters
        ----------
        root : pathlib.Path
            Repository root whose index should be queried.
        name : str
            Exact symbol name to search for.
        prefix : str | None, optional
            Repo-root-relative path prefix used to restrict symbol files.
        conn : object | None, optional
            Existing backend connection to reuse.

        Returns
        -------
        list[codira.types.SymbolRow]
            Matching symbol rows ordered deterministically.
        """

    def docstring_issues(
        self,
        root: Path,
        *,
        prefix: str | None = None,
        conn: object | None = None,
    ) -> list[DocstringIssueRow]:
        """
        Return indexed docstring validation issues.

        Parameters
        ----------
        root : pathlib.Path
            Repository root whose index should be queried.
        prefix : str | None, optional
            Repo-root-relative path prefix used to restrict issue ownership.
        conn : object | None, optional
            Existing backend connection to reuse.

        Returns
        -------
        list[codira.types.DocstringIssueRow]
            Indexed docstring issue rows ordered deterministically.
        """

    def find_call_edges(
        self,
        root: Path,
        name: str,
        *,
        module: str | None = None,
        incoming: bool = False,
        prefix: str | None = None,
        conn: object | None = None,
    ) -> list[tuple[str, str, str | None, str | None, int]]:
        """
        Find exact call edges for a caller or callee logical name.

        Parameters
        ----------
        root : pathlib.Path
            Repository root whose index should be queried.
        name : str
            Exact logical caller or callee name to search for.
        module : str | None, optional
            Optional module qualifier used to restrict the result set.
        incoming : bool, optional
            Whether to return incoming edges for the callee.
        prefix : str | None, optional
            Repo-root-relative path prefix used to restrict caller files.
        conn : object | None, optional
            Existing backend connection to reuse.

        Returns
        -------
        list[tuple[str, str, str | None, str | None, int]]
            Matching call-edge rows ordered deterministically.
        """

    def find_callable_refs(
        self,
        root: Path,
        name: str,
        *,
        module: str | None = None,
        incoming: bool = False,
        prefix: str | None = None,
        conn: object | None = None,
    ) -> list[tuple[str, str, str | None, str | None, int]]:
        """
        Find exact callable-object references for an owner or target.

        Parameters
        ----------
        root : pathlib.Path
            Repository root whose index should be queried.
        name : str
            Exact logical owner or referenced target name to search for.
        module : str | None, optional
            Optional module qualifier used to restrict the result set.
        incoming : bool, optional
            Whether to return incoming references for the target.
        prefix : str | None, optional
            Repo-root-relative path prefix used to restrict owner files.
        conn : object | None, optional
            Existing backend connection to reuse.

        Returns
        -------
        list[tuple[str, str, str | None, str | None, int]]
            Matching callable-reference rows ordered deterministically.
        """
