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

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field as dataclass_field
from typing import TYPE_CHECKING, Literal, Protocol, runtime_checkable

if TYPE_CHECKING:
    from pathlib import Path

    from codira.models import AnalysisResult, FileMetadataSnapshot
    from codira.semantic.embeddings import EmbeddingBackendSpec
    from codira.types import (
        ChannelResults,
        DocstringIssueRow,
        DocumentationChannelResults,
        EnumMemberRow,
        IncludeEdgeRow,
        OverloadRow,
        ReferenceSearchRow,
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


class EmbeddingEngineError(RuntimeError):
    """
    Engine-neutral embedding generation failure.

    Parameters
    ----------
    None

    Returns
    -------
    None
        Instances carry the embedding engine failure message through
        ``RuntimeError``.
    """


class VectorStoreError(RuntimeError):
    """
    Vector-store-neutral persistence or retrieval failure.

    Parameters
    ----------
    None

    Returns
    -------
    None
        Instances carry the vector-store failure message through
        ``RuntimeError``.
    """


@dataclass(frozen=True)
class EmbeddingEngineSpec:
    """
    Stable identity for one embedding engine vector contract.

    Parameters
    ----------
    engine : str
        Stable embedding engine name.
    engine_version : str
        Engine implementation version.
    model : str
        Model identifier used by the engine.
    model_version : str
        Explicit model revision or operator-managed version.
    dimension : int
        Fixed vector dimensionality.
    precision : str
        Vector precision or quantization label.
    """

    engine: str
    engine_version: str
    model: str
    model_version: str
    dimension: int
    precision: str = "float32"


@dataclass(frozen=True)
class VectorStoreSpec:
    """
    Stable identity for one vector-store serialization contract.

    Parameters
    ----------
    store : str
        Stable vector-store plugin name.
    store_version : str
        Vector-store implementation version.
    format_version : str
        Serialization and schema format version for persisted vectors.
    """

    store: str
    store_version: str
    format_version: str


@dataclass(frozen=True)
class VectorSetIdentity:
    """
    Complete identity for one persisted vector set.

    Parameters
    ----------
    engine : EmbeddingEngineSpec
        Embedding engine and model identity.
    vector_store : VectorStoreSpec
        Vector-store and serialization identity.
    """

    engine: EmbeddingEngineSpec
    vector_store: VectorStoreSpec


@dataclass(frozen=True)
class PendingEmbeddingRow:
    """
    Pending symbol embedding payload collected during persistence.

    Parameters
    ----------
    object_type : str
        Persisted embedding owner kind.
    object_id : int
        Persisted embedding owner identifier.
    stable_id : str
        Durable analyzer-owned symbol identity.
    text : str
        Exact semantic payload that will be hashed and embedded.
    """

    object_type: str
    object_id: int
    stable_id: str
    text: str


@dataclass(frozen=True)
class PreparedVectorRow:
    """
    Vector-store row prepared for deferred or materialized persistence.

    Parameters
    ----------
    row : codira.contracts.PendingEmbeddingRow
        Stable object identity and source text payload.
    content_hash : str
        Hash of the exact text payload used for vector reuse decisions.
    vector : bytes | None, optional
        Serialized vector payload when already available.
    """

    row: PendingEmbeddingRow
    content_hash: str
    vector: bytes | None = None


@dataclass(frozen=True)
class EmbeddingIndexingPolicy:
    """
    Backend-neutral embedding row eligibility policy.

    Parameters
    ----------
    object_types : frozenset[str]
        Persisted object types eligible for embedding.
    max_text_chars : int
        Maximum eligible text length, or ``0`` when text length is unlimited.
    include_paths : tuple[str, ...]
        Repo-root-relative path prefixes included in embedding generation.
        An empty tuple includes every indexed path.
    exclude_paths : tuple[str, ...]
        Repo-root-relative path prefixes excluded from embedding generation.
    """

    object_types: frozenset[str]
    max_text_chars: int = 0
    include_paths: tuple[str, ...] = ()
    exclude_paths: tuple[str, ...] = ()


@dataclass
class EmbeddingIndexingMetrics:
    """
    Mutable embedding indexing counters shared with backend persistence.

    Parameters
    ----------
    skipped : int
        Number of candidate embedding rows skipped by embedding indexing
        controls.
    pending : int
        Number of candidate embedding rows queued for deferred computation.
    """

    skipped: int = 0
    pending: int = 0


def _embedding_path_matches(prefixes: tuple[str, ...], relative_path: str) -> bool:
    """
    Return whether a relative path matches any configured prefix.

    Parameters
    ----------
    prefixes : tuple[str, ...]
        Repo-root-relative path prefixes.
    relative_path : str
        Normalized repo-root-relative path.

    Returns
    -------
    bool
        ``True`` when any prefix matches the path or one of its parent
        directories.
    """

    for prefix in prefixes:
        normalized = prefix.strip().strip("/")
        if not normalized:
            continue
        if relative_path == normalized or relative_path.startswith(f"{normalized}/"):
            return True
    return False


def embedding_policy_allows_path(
    policy: EmbeddingIndexingPolicy,
    *,
    root: Path,
    path: Path,
) -> bool:
    """
    Return whether embedding generation is enabled for one file path.

    Parameters
    ----------
    policy : EmbeddingIndexingPolicy
        Embedding indexing policy.
    root : pathlib.Path
        Repository root used to normalize ``path``.
    path : pathlib.Path
        Candidate source file path.

    Returns
    -------
    bool
        ``True`` when include and exclude path controls allow embeddings for
        the file.
    """

    try:
        relative_path = path.relative_to(root).as_posix()
    except ValueError:
        relative_path = path.as_posix()
    if policy.include_paths and not _embedding_path_matches(
        policy.include_paths,
        relative_path,
    ):
        return False
    return not _embedding_path_matches(policy.exclude_paths, relative_path)


def filter_embedding_rows_for_policy(
    rows: Sequence[PendingEmbeddingRow],
    policy: EmbeddingIndexingPolicy | None,
    *,
    root: Path,
    path: Path,
) -> tuple[list[PendingEmbeddingRow], int]:
    """
    Filter pending embedding rows through the configured eligibility policy.

    Parameters
    ----------
    rows : collections.abc.Sequence[PendingEmbeddingRow]
        Candidate embedding rows collected for a file.
    policy : EmbeddingIndexingPolicy | None
        Optional eligibility policy. ``None`` accepts all rows.
    root : pathlib.Path
        Repository root used to normalize path filters.
    path : pathlib.Path
        Source file path that owns the rows.

    Returns
    -------
    tuple[list[PendingEmbeddingRow], int]
        Accepted rows and skipped-row count.
    """

    if policy is None:
        return list(rows), 0
    if not embedding_policy_allows_path(policy, root=root, path=path):
        return [], len(rows)
    accepted: list[PendingEmbeddingRow] = []
    skipped = 0
    for row in rows:
        if row.object_type not in policy.object_types:
            skipped += 1
            continue
        if policy.max_text_chars and len(row.text) > policy.max_text_chars:
            skipped += 1
            continue
        accepted.append(row)
    return accepted, skipped


@dataclass(frozen=True)
class StoredEmbeddingRow:
    """
    Persisted embedding row captured before file-owned rows are replaced.

    Parameters
    ----------
    stable_id : str
        Durable analyzer-owned symbol identity.
    content_hash : str
        Hash of the exact semantic payload embedded previously.
    dim : int
        Stored embedding dimensionality.
    vector : bytes
        Serialized float32 vector payload.
    """

    stable_id: str
    content_hash: str
    dim: int
    vector: bytes


@runtime_checkable
class EmbeddingEngine(Protocol):
    """
    Contract for pluggable embedding engines.

    Implementations own text-to-vector inference and engine-specific local
    provisioning. They must not own structural index persistence or vector-store
    lifecycle policy.
    """

    name: str
    version: str

    def spec(self, config: Mapping[str, object]) -> EmbeddingEngineSpec:
        """
        Return the active embedding engine identity.

        Parameters
        ----------
        config : collections.abc.Mapping[str, object]
            Engine-specific configuration table.

        Returns
        -------
        EmbeddingEngineSpec
            Stable vector-generation identity used for invalidation.
        """
        ...

    def provision(
        self,
        config: Mapping[str, object],
        *,
        quiet: bool = False,
    ) -> None:
        """
        Ensure local model artifacts are available for inference.

        Parameters
        ----------
        config : collections.abc.Mapping[str, object]
            Engine-specific configuration table.
        quiet : bool, optional
            Whether operator-facing provisioning output should be suppressed.

        Returns
        -------
        None
            Required local artifacts are present or an engine error is raised.
        """
        ...

    def embed_texts(
        self,
        texts: Sequence[str],
        config: Mapping[str, object],
    ) -> list[list[float]]:
        """
        Embed text payloads in deterministic input order.

        Parameters
        ----------
        texts : collections.abc.Sequence[str]
            Text payloads to embed.
        config : collections.abc.Mapping[str, object]
            Engine-specific configuration table.

        Returns
        -------
        list[list[float]]
            One vector per input payload, in the same order as ``texts``.
        """
        ...

    def reset_runtime_caches(self) -> None:
        """
        Clear process-local engine caches.

        Parameters
        ----------
        None

        Returns
        -------
        None
            Cached engine state is discarded.
        """
        ...


@runtime_checkable
class VectorStore(Protocol):
    """
    Contract for pluggable embedding vector stores.

    Implementations own vector persistence, reusable vector-cache persistence,
    deferred embedding queue persistence, and similarity lookup. They must not
    own language analysis or text-to-vector inference.
    """

    name: str
    version: str

    def spec(self, config: Mapping[str, object]) -> VectorStoreSpec:
        """
        Return the active vector-store identity.

        Parameters
        ----------
        config : collections.abc.Mapping[str, object]
            Vector-store-specific configuration table.

        Returns
        -------
        VectorStoreSpec
            Stable vector persistence identity used for invalidation.
        """
        ...

    def initialize(self, root: Path, config: Mapping[str, object]) -> None:
        """
        Initialize vector-store state for one repository.

        Parameters
        ----------
        root : pathlib.Path
            Repository root whose vector store should be initialized.
        config : collections.abc.Mapping[str, object]
            Vector-store-specific configuration table.

        Returns
        -------
        None
            Vector-store storage is ready for reads and writes.
        """
        ...

    def ensure_vector_set(
        self,
        root: Path,
        identity: VectorSetIdentity,
        config: Mapping[str, object],
    ) -> int:
        """
        Return the persistent identifier for one vector-set identity.

        Parameters
        ----------
        root : pathlib.Path
            Repository root whose vector store should be queried.
        identity : codira.contracts.VectorSetIdentity
            Complete embedding engine and vector-store identity.
        config : collections.abc.Mapping[str, object]
            Vector-store-specific configuration table.

        Returns
        -------
        int
            Stable store-local vector-set identifier.
        """
        ...

    def load_cached_vectors(
        self,
        root: Path,
        identity: VectorSetIdentity,
        content_hashes: Sequence[str],
        config: Mapping[str, object],
    ) -> dict[str, bytes]:
        """
        Load cached vectors keyed by content hash.

        Parameters
        ----------
        root : pathlib.Path
            Repository root whose vector store should be queried.
        identity : codira.contracts.VectorSetIdentity
            Complete embedding engine and vector-store identity.
        content_hashes : collections.abc.Sequence[str]
            Candidate content hashes to load.
        config : collections.abc.Mapping[str, object]
            Vector-store-specific configuration table.

        Returns
        -------
        dict[str, bytes]
            Serialized vectors keyed by content hash.
        """
        ...

    def store_cached_vectors(
        self,
        root: Path,
        identity: VectorSetIdentity,
        vectors: Mapping[str, bytes],
        config: Mapping[str, object],
    ) -> None:
        """
        Persist reusable vectors keyed by content hash.

        Parameters
        ----------
        root : pathlib.Path
            Repository root whose vector store should be updated.
        identity : codira.contracts.VectorSetIdentity
            Complete embedding engine and vector-store identity.
        vectors : collections.abc.Mapping[str, bytes]
            Serialized vectors keyed by content hash.
        config : collections.abc.Mapping[str, object]
            Vector-store-specific configuration table.

        Returns
        -------
        None
            Cache rows are inserted or replaced in place.
        """
        ...

    def store_pending_vectors(
        self,
        root: Path,
        identity: VectorSetIdentity,
        rows: Sequence[PreparedVectorRow],
        config: Mapping[str, object],
    ) -> None:
        """
        Persist deferred embedding rows for later computation.

        Parameters
        ----------
        root : pathlib.Path
            Repository root whose vector store should be updated.
        identity : codira.contracts.VectorSetIdentity
            Complete embedding engine and vector-store identity.
        rows : collections.abc.Sequence[codira.contracts.PreparedVectorRow]
            Prepared rows whose source text should remain pending.
        config : collections.abc.Mapping[str, object]
            Vector-store-specific configuration table.

        Returns
        -------
        None
            Pending rows are inserted or replaced in place.
        """
        ...

    def delete_pending_vectors(
        self,
        root: Path,
        identity: VectorSetIdentity,
        rows: Sequence[PreparedVectorRow],
        config: Mapping[str, object],
    ) -> None:
        """
        Delete deferred rows that have been materialized.

        Parameters
        ----------
        root : pathlib.Path
            Repository root whose vector store should be updated.
        identity : codira.contracts.VectorSetIdentity
            Complete embedding engine and vector-store identity.
        rows : collections.abc.Sequence[codira.contracts.PreparedVectorRow]
            Prepared rows identifying pending entries to delete.
        config : collections.abc.Mapping[str, object]
            Vector-store-specific configuration table.

        Returns
        -------
        None
            Matching pending rows are deleted in place.
        """
        ...

    def clear_pending_vectors(
        self,
        root: Path,
        identity: VectorSetIdentity,
        config: Mapping[str, object],
    ) -> None:
        """
        Delete all deferred rows for one vector set.

        Parameters
        ----------
        root : pathlib.Path
            Repository root whose vector store should be updated.
        identity : codira.contracts.VectorSetIdentity
            Complete embedding engine and vector-store identity.
        config : collections.abc.Mapping[str, object]
            Vector-store-specific configuration table.

        Returns
        -------
        None
            Matching pending rows are deleted in place.
        """
        ...

    def store_vectors(
        self,
        root: Path,
        identity: VectorSetIdentity,
        rows: Sequence[PreparedVectorRow],
        config: Mapping[str, object],
    ) -> None:
        """
        Persist materialized vectors for indexed objects.

        Parameters
        ----------
        root : pathlib.Path
            Repository root whose vector store should be updated.
        identity : codira.contracts.VectorSetIdentity
            Complete embedding engine and vector-store identity.
        rows : collections.abc.Sequence[codira.contracts.PreparedVectorRow]
            Prepared rows carrying serialized vector payloads.
        config : collections.abc.Mapping[str, object]
            Vector-store-specific configuration table.

        Returns
        -------
        None
            Vector rows are inserted or replaced in place.
        """
        ...

    def reset_runtime_caches(self) -> None:
        """
        Clear process-local vector-store caches.

        Parameters
        ----------
        None

        Returns
        -------
        None
            Cached vector-store state is discarded.
        """
        ...


@dataclass(frozen=True)
class BackendGraphMetric:
    """
    Count one direction of graph connectivity for a symbol.

    Parameters
    ----------
    total : int
        Total number of edges in the selected direction.
    unresolved : int
        Number of edges in ``total`` whose target could not be resolved.
    """

    total: int
    unresolved: int


@dataclass(frozen=True)
class BackendSymbolInventoryItem:
    """
    Symbol inventory row with graph connectivity metrics.

    Parameters
    ----------
    symbol_type : str
        Indexed symbol kind.
    module : str
        Module that owns the symbol identity.
    name : str
        Symbol name inside ``module``.
    file : str
        Defining file path.
    lineno : int
        Defining line number.
    calls_out : BackendGraphMetric
        Outgoing static call-edge counts.
    calls_in : BackendGraphMetric
        Incoming static call-edge counts.
    refs_out : BackendGraphMetric
        Outgoing callable-reference counts.
    refs_in : BackendGraphMetric
        Incoming callable-reference counts.
    """

    symbol_type: str
    module: str
    name: str
    file: str
    lineno: int
    calls_out: BackendGraphMetric
    calls_in: BackendGraphMetric
    refs_out: BackendGraphMetric
    refs_in: BackendGraphMetric


@runtime_checkable
class LanguageAnalyzer(Protocol):
    """
    Contract for file analyzers participating in one indexing run.

    Implementations are responsible only for language-specific analysis and
    normalized artifact production. They must not own storage policy. Stable
    IDs emitted inside one returned ``AnalysisResult`` must be unique.
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
        ...

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
            Normalized artifacts for the file. Stable IDs within the returned
            analysis must already be internally unique.
        """
        ...


@runtime_checkable
class ConfigurablePlugin(Protocol):
    """
    Optional plugin contract for explicit configuration injection.

    Implementations that expose this hook receive only their own namespaced
    configuration table after the global configuration has been merged.
    """

    def configure(self, config: Mapping[str, object]) -> None:
        """
        Apply one plugin-specific configuration table.

        Parameters
        ----------
        config : collections.abc.Mapping[str, object]
            Namespaced plugin configuration values.

        Returns
        -------
        None
            The plugin mutates its own instance state when configuration is
            required.
        """
        ...


@runtime_checkable
class PluginConfigurationSchemaProvider(Protocol):
    """
    Optional plugin contract for configuration schema publication.

    Plugins that expose this hook allow the core registry to validate their
    namespaced configuration deterministically.
    """

    def configuration_json_schema(self) -> Mapping[str, object]:
        """
        Return the plugin-specific JSON Schema.

        Parameters
        ----------
        None

        Returns
        -------
        collections.abc.Mapping[str, object]
            JSON Schema for the plugin configuration table.
        """
        ...


@runtime_checkable
class PathFilteredAnalyzer(Protocol):
    """
    Optional analyzer contract for repo-relative path filtering.

    Implementations receive the repository root explicitly so include/exclude
    filters can be evaluated without hidden global state.
    """

    def allows_path(self, path: Path, root: Path) -> bool:
        """
        Decide whether a supported path is enabled for this analyzer.

        Parameters
        ----------
        path : pathlib.Path
            Candidate repository file.
        root : pathlib.Path
            Repository root used for relative path evaluation.

        Returns
        -------
        bool
            ``True`` when the analyzer should process the file.
        """
        ...


RetrievalCapabilityName = Literal[
    "symbol_lookup",
    "semantic_text",
    "embedding_similarity",
    "task_specialization",
    "graph_relations",
    "issue_annotations",
    "diagnostics_metadata",
]
OntologyObjectType = Literal[
    "module",
    "type",
    "callable",
    "import",
    "constant",
    "variable",
    "namespace",
    "documentation",
]

CANONICAL_ONTOLOGY_TYPES: tuple[OntologyObjectType, ...] = (
    "module",
    "type",
    "callable",
    "import",
    "constant",
    "variable",
    "namespace",
    "documentation",
)


@dataclass(frozen=True)
class AnalyzerCapabilityDeclaration:
    """
    Machine-readable declaration of one analyzer's ontology coverage.

    Parameters
    ----------
    analyzer_name : str
        Stable analyzer identifier.
    analyzer_version : str
        Analyzer implementation version.
    source : str
        Analyzer source class such as ``first_party`` or ``third_party``.
    entrypoint : str
        Importable factory or implementation identity.
    supports : tuple[OntologyObjectType, ...]
        Canonical ontology types the analyzer can emit.
    does_not_support : tuple[OntologyObjectType, ...]
        Canonical ontology types the analyzer explicitly does not emit.
    mappings : dict[str, OntologyObjectType]
        Analyzer-native artifact types mapped to canonical ontology types.
    checksum : str | None, optional
        Optional stable implementation checksum when available.
    """

    analyzer_name: str
    analyzer_version: str
    source: str
    entrypoint: str
    supports: tuple[OntologyObjectType, ...]
    does_not_support: tuple[OntologyObjectType, ...]
    mappings: dict[str, OntologyObjectType]
    checksum: str | None = None


@runtime_checkable
class CapabilityDeclaringAnalyzer(Protocol):
    """
    Optional analyzer-side contract for Layer 0 capability declarations.

    Implementations declare how analyzer-native artifacts map to the canonical
    ontology without changing the existing indexing behavior.
    """

    def analyzer_capability_declaration(self) -> AnalyzerCapabilityDeclaration:
        """
        Return the analyzer's explicit capability declaration.

        Parameters
        ----------
        None

        Returns
        -------
        AnalyzerCapabilityDeclaration
            Deterministic ontology declaration for this analyzer.
        """
        ...


@dataclass(frozen=True)
class BackendRelationQueryRequest:
    """
    Backend request for exact relation and include-edge lookup.

    Parameters
    ----------
    root : pathlib.Path
        Repository root whose index should be queried.
    name : str
        Exact logical or include-target name to search for.
    module : str | None, optional
        Optional module qualifier used to restrict results.
    incoming : bool, optional
        Whether to return incoming edges instead of outgoing edges.
    prefix : str | None, optional
        Repo-root-relative path prefix used to restrict owner files.
    conn : object | None, optional
        Existing backend connection to reuse.
    """

    root: Path
    name: str
    module: str | None = None
    incoming: bool = False
    prefix: str | None = None
    conn: object | None = None


@dataclass(frozen=True)
class BackendEmbeddingCandidatesRequest:
    """
    Backend request for ranked embedding candidate lookup.

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
    """

    root: Path
    query: str
    limit: int
    min_score: float
    prefix: str | None = None
    conn: object | None = None


@dataclass(frozen=True)
class BackendDocumentationCandidatesRequest:
    """
    Backend request for ranked documentation candidate lookup.

    Parameters
    ----------
    root : pathlib.Path
        Repository root whose index should be queried.
    query : str
        User query string.
    limit : int
        Maximum number of ranked documentation results to return.
    min_score : float
        Minimum similarity threshold for emitted results.
    prefix : str | None, optional
        Repo-root-relative path prefix used to restrict matched documents.
    conn : object | None, optional
        Existing backend connection to reuse.
    """

    root: Path
    query: str
    limit: int
    min_score: float
    prefix: str | None = None
    conn: object | None = None


@dataclass(frozen=True)
class BackendRuntimeInventoryRequest:
    """
    Backend request for persisting runtime inventory after indexing.

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
    """

    root: Path
    backend_name: str
    backend_version: str
    coverage_complete: bool
    analyzers: Sequence[LanguageAnalyzer]
    conn: object | None = None


@dataclass(frozen=True)
class BackendPersistAnalysisRequest:
    """
    Backend request for persisting one analyzed file snapshot.

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
    embedding_indexing : codira.contracts.EmbeddingIndexingPolicy | None, optional
        Optional embedding row eligibility policy.
    embedding_metrics : codira.contracts.EmbeddingIndexingMetrics | None, optional
        Optional mutable counters updated during embedding persistence.
    defer_embeddings : bool, optional
        Whether eligible embedding rows should be queued for later computation.
    previous_embeddings : collections.abc.Mapping[str, object] | None, optional
        Previously persisted semantic artifacts eligible for reuse.
    vector_store : codira.contracts.VectorStore | None, optional
        Active separated vector store used for embedding row persistence.
    vector_set_identity : codira.contracts.VectorSetIdentity | None, optional
        Active vector-set identity for separated vector-store writes.
    vector_store_config : collections.abc.Mapping[str, object], optional
        Vector-store-specific configuration table.
    conn : object | None, optional
        Existing backend connection to reuse.
    """

    root: Path
    file_metadata: FileMetadataSnapshot
    analysis: AnalysisResult
    embedding_backend: EmbeddingBackendSpec | None = None
    embedding_indexing: EmbeddingIndexingPolicy | None = None
    embedding_metrics: EmbeddingIndexingMetrics | None = None
    defer_embeddings: bool = False
    previous_embeddings: Mapping[str, object] | None = None
    vector_store: VectorStore | None = None
    vector_set_identity: VectorSetIdentity | None = None
    vector_store_config: Mapping[str, object] = dataclass_field(default_factory=dict)
    conn: object | None = None


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
        ...

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
        ...


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


BackendQueryValue = str | bytes | bytearray | int | float | None
BackendQueryRow = Sequence[BackendQueryValue]


@runtime_checkable
class BackendQueryCursor(Protocol):
    """
    Minimal cursor surface required by backend-agnostic query helpers.

    The contract intentionally captures only the operations used by the core
    query layer so backend plugins remain free to wrap native driver objects.
    """

    def execute(
        self,
        statement: str,
        parameters: Sequence[object] = (),
    ) -> BackendQueryCursor:
        """
        Execute one backend-native query statement.

        Parameters
        ----------
        statement : str
            Backend-native statement text.
        parameters : collections.abc.Sequence[object], optional
            Bound positional parameters for the statement.

        Returns
        -------
        BackendQueryCursor
            Cursor-like object positioned on the executed statement result.
        """
        ...

    def fetchone(self) -> object | None:
        """
        Return the next available row from the current result set.

        Parameters
        ----------
        None

        Returns
        -------
        BackendQueryRow | None
            Next result row, or ``None`` when no rows remain.
        """
        ...

    def fetchall(self) -> list[BackendQueryRow]:
        """
        Return all remaining rows from the current result set.

        Parameters
        ----------
        None

        Returns
        -------
        list[codira.contracts.BackendQueryRow]
            Materialized remaining result rows.
        """
        ...


@runtime_checkable
class BackendQueryConnection(Protocol):
    """
    Minimal connection surface required by backend-agnostic query helpers.

    The protocol keeps core query modules decoupled from concrete driver types
    while preserving deterministic method-level typing for read-only access.
    """

    def execute(
        self,
        statement: str,
        parameters: Sequence[object] = (),
    ) -> BackendQueryCursor:
        """
        Execute one backend-native query statement directly on the connection.

        Parameters
        ----------
        statement : str
            Backend-native statement text.
        parameters : collections.abc.Sequence[object], optional
            Bound positional parameters for the statement.

        Returns
        -------
        BackendQueryCursor
            Cursor-like object positioned on the executed statement result.
        """
        ...

    def cursor(self) -> BackendQueryCursor:
        """
        Create a cursor-like object for backend-native query execution.

        Parameters
        ----------
        None

        Returns
        -------
        BackendQueryCursor
            Cursor-like object for subsequent query execution.
        """
        ...

    def close(self) -> object:
        """
        Close the backend-native connection handle.

        Parameters
        ----------
        None

        Returns
        -------
        object
            Backend-defined close result.
        """
        ...


@runtime_checkable
class IndexWriteSession(Protocol):
    """
    Explicit write-side lifecycle for one indexing run.

    Implementations own mutable backend state for a single repository index
    pass. Query commands must not rely on this session surface.
    """

    def purge_skipped_docstring_issues(self) -> None:
        """
        Remove backend-owned legacy diagnostics skipped by policy.

        Parameters
        ----------
        None

        Returns
        -------
        None
            Matching diagnostics are removed in place.
        """
        ...

    def prune_orphaned_embeddings(self) -> None:
        """
        Remove embedding rows whose owning symbols no longer exist.

        Parameters
        ----------
        None

        Returns
        -------
        None
            Orphaned embedding rows are removed in place.
        """
        ...

    def load_existing_file_hashes(self) -> dict[str, str]:
        """
        Load indexed file hashes used for incremental reuse decisions.

        Parameters
        ----------
        None

        Returns
        -------
        dict[str, str]
            Indexed file hashes keyed by absolute file path.
        """
        ...

    def load_existing_file_ownership(self) -> dict[str, tuple[str, str]]:
        """
        Load persisted analyzer ownership keyed by absolute path.

        Parameters
        ----------
        None

        Returns
        -------
        dict[str, tuple[str, str]]
            Indexed analyzer ownership keyed by absolute file path.
        """
        ...

    def current_embedding_state_matches(
        self,
        embedding_backend: EmbeddingBackendSpec,
    ) -> bool:
        """
        Report whether persisted embeddings match the active embedding backend.

        Parameters
        ----------
        embedding_backend : codira.semantic.embeddings.EmbeddingBackendSpec
            Active embedding backend metadata.

        Returns
        -------
        bool
            ``True`` when the persisted embedding state can be reused.
        """
        ...

    def load_previous_embeddings_by_path(
        self,
        *,
        paths: Sequence[str],
        embedding_backend: EmbeddingBackendSpec,
    ) -> dict[str, dict[str, StoredEmbeddingRow]]:
        """
        Load reusable semantic artifacts for paths that will be replaced.

        Parameters
        ----------
        paths : collections.abc.Sequence[str]
            Absolute file paths selected for replacement.
        embedding_backend : codira.semantic.embeddings.EmbeddingBackendSpec
            Active semantic backend metadata used to filter reusable artifacts.

        Returns
        -------
        dict[str, dict[str, StoredEmbeddingRow]]
            Previous semantic artifacts grouped by absolute file path.
        """
        ...

    def count_reusable_embeddings(self, *, paths: Sequence[str]) -> int:
        """
        Count semantic artifacts that remain reusable for unchanged files.

        Parameters
        ----------
        paths : collections.abc.Sequence[str]
            Absolute file paths considered reusable.

        Returns
        -------
        int
            Number of reusable semantic artifacts retained by the backend.
        """
        ...

    def prepare(
        self,
        *,
        full: bool,
        indexed_paths: Sequence[str],
        deleted_paths: Sequence[str],
    ) -> None:
        """
        Delete persisted rows that the current index plan will replace.

        Parameters
        ----------
        full : bool
            Whether the current run is a full rebuild.
        indexed_paths : collections.abc.Sequence[str]
            Absolute file paths whose rows will be replaced.
        deleted_paths : collections.abc.Sequence[str]
            Absolute file paths whose rows will be removed.

        Returns
        -------
        None
            Persisted rows are removed in place before fresh analysis is stored.
        """
        ...

    def persist_analysis(
        self,
        request: BackendPersistAnalysisRequest,
    ) -> tuple[int, int]:
        """
        Persist normalized artifacts for one analyzed file snapshot.

        Parameters
        ----------
        request : BackendPersistAnalysisRequest
            Persistence request carrying file metadata, normalized analysis,
            embedding state, and optional reusable artifacts.

        Returns
        -------
        tuple[int, int]
            ``(recomputed, reused)`` semantic-artifact counts for the file.
        """
        ...

    def rebuild_derived_indexes(self) -> None:
        """
        Rebuild derived backend state after raw artifact persistence.

        Parameters
        ----------
        None

        Returns
        -------
        None
            Derived backend indexes are refreshed in place.
        """
        ...

    def persist_runtime_inventory(
        self,
        request: BackendRuntimeInventoryRequest,
    ) -> None:
        """
        Persist backend and analyzer inventory for a completed index run.

        Parameters
        ----------
        request : BackendRuntimeInventoryRequest
            Runtime inventory persistence request.

        Returns
        -------
        None
            Runtime inventory rows are replaced in place.
        """
        ...

    def commit(self) -> None:
        """
        Commit pending backend writes for the indexing run.

        Parameters
        ----------
        None

        Returns
        -------
        None
            Pending backend writes are committed.
        """
        ...

    def abort(self) -> None:
        """
        Abort pending backend writes for the indexing run.

        Parameters
        ----------
        None

        Returns
        -------
        None
            Pending backend writes are rolled back when possible.
        """
        ...

    def close(self) -> None:
        """
        Release resources owned by the indexing session.

        Parameters
        ----------
        None

        Returns
        -------
        None
            Session-owned resources are closed in place.
        """
        ...


@runtime_checkable
class IndexBackend(Protocol):
    """
    Contract for the single active persistence backend of one repository index.

    Backends own storage and query persistence concerns but must not perform
    language-specific parsing.
    """

    name: str
    version: str

    def begin_index_session(self, root: Path) -> IndexWriteSession:
        """
        Open the explicit write-side lifecycle for one indexing run.

        Parameters
        ----------
        root : pathlib.Path
            Repository root whose backend state will be mutated.

        Returns
        -------
        IndexWriteSession
            Mutable session object used only by indexing flows.
        """
        ...

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
        ...

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
        ...

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
        ...

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
        ...

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
        ...

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
        ...

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
        ...

    def load_previous_embeddings_by_path(
        self,
        root: Path,
        *,
        paths: Sequence[str],
        embedding_backend: EmbeddingBackendSpec,
        conn: object | None = None,
    ) -> dict[str, dict[str, StoredEmbeddingRow]]:
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
        dict[str, dict[str, StoredEmbeddingRow]]
            Previous semantic artifacts grouped by absolute file path.
        """
        ...

    def persist_analysis(
        self,
        request: BackendPersistAnalysisRequest,
    ) -> tuple[int, int]:
        """
        Persist normalized artifacts for one analyzed file snapshot.

        Parameters
        ----------
        request : BackendPersistAnalysisRequest
            Persistence request carrying file metadata, normalized analysis,
            embedding state, and optional reusable artifacts.

        Returns
        -------
        tuple[int, int]
            ``(recomputed, reused)`` semantic-artifact counts for the file.
        """
        ...

    def process_pending_embeddings(  # noqa: PLR0913
        self,
        root: Path,
        *,
        embedding_backend: EmbeddingBackendSpec,
        vector_store: VectorStore | None = None,
        vector_set_identity: VectorSetIdentity | None = None,
        vector_store_config: Mapping[str, object] | None = None,
        conn: object | None = None,
    ) -> tuple[int, int]:
        """
        Compute and persist pending embedding rows without reparsing files.

        Parameters
        ----------
        root : pathlib.Path
            Repository root whose pending embedding rows should be processed.
        embedding_backend : codira.semantic.embeddings.EmbeddingBackendSpec
            Active semantic backend metadata used to select pending rows.
        conn : object | None, optional
            Existing backend connection to reuse.

        Returns
        -------
        tuple[int, int]
            ``(recomputed, reused)`` counts for processed pending rows.
        """
        ...

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
        ...

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
        ...

    def persist_runtime_inventory(
        self,
        request: BackendRuntimeInventoryRequest,
    ) -> None:
        """
        Persist backend and analyzer inventory for a completed index run.

        Parameters
        ----------
        request : BackendRuntimeInventoryRequest
            Runtime inventory persistence request.

        Returns
        -------
        None
            Runtime inventory rows are replaced in place.
        """
        ...

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
        ...

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
        ...

    def find_include_edges(
        self,
        request: BackendRelationQueryRequest,
    ) -> list[IncludeEdgeRow]:
        """
        Find exact include-like edges for an owner module or included target.

        Parameters
        ----------
        request : BackendRelationQueryRequest
            Exact relation lookup request.

        Returns
        -------
        list[codira.types.IncludeEdgeRow]
            Matching include-edge rows ordered deterministically as
            ``(owner_module, target_name, kind, lineno)`` tuples.
        """
        ...

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
        ...

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
        ...

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
        ...

    def find_reference_rows(
        self,
        root: Path,
        name: str,
        *,
        prefix: str | None = None,
        conn: object | None = None,
    ) -> list[ReferenceSearchRow]:
        """
        Return stored non-import source lines containing one symbol name.

        Parameters
        ----------
        root : pathlib.Path
            Repository root whose index should be queried.
        name : str
            Symbol name to search as a simple substring.
        prefix : str | None, optional
            Repo-root-relative path prefix used to restrict candidate files.
        conn : object | None, optional
            Existing backend connection to reuse.

        Returns
        -------
        list[codira.types.ReferenceSearchRow]
            Matching stored rows as ``(file_path, lineno, line_text)`` ordered
            deterministically by file path and line number.
        """
        ...

    def embedding_candidates(
        self,
        request: BackendEmbeddingCandidatesRequest,
    ) -> ChannelResults:
        """
        Return ranked symbol candidates using stored embedding similarity.

        Parameters
        ----------
        request : BackendEmbeddingCandidatesRequest
            Embedding candidate lookup request.

        Returns
        -------
        codira.types.ChannelResults
            Ranked symbol candidates ordered deterministically.
        """
        ...

    def documentation_candidates(
        self,
        request: BackendDocumentationCandidatesRequest,
    ) -> DocumentationChannelResults:
        """
        Return ranked documentation candidates using stored embedding similarity.

        Parameters
        ----------
        request : BackendDocumentationCandidatesRequest
            Documentation candidate lookup request.

        Returns
        -------
        codira.types.DocumentationChannelResults
            Ranked documentation candidates ordered deterministically.
        """
        ...

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
        ...

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
        ...

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
        ...

    def symbol_inventory(
        self,
        root: Path,
        *,
        prefix: str | None = None,
        include_tests: bool = False,
        limit: int = 1000,
        conn: object | None = None,
    ) -> list[BackendSymbolInventoryItem]:
        """
        Return indexed symbols with graph connectivity metrics.

        Parameters
        ----------
        root : pathlib.Path
            Repository root whose index should be queried.
        prefix : str | None, optional
            Repo-root-relative path prefix used to restrict symbol files.
        include_tests : bool, optional
            Whether symbols from ``tests`` modules are included.
        limit : int, optional
            Maximum number of rows to return after deterministic sorting.
        conn : object | None, optional
            Existing backend connection to reuse.

        Returns
        -------
        list[codira.contracts.BackendSymbolInventoryItem]
            Symbol inventory rows ordered deterministically.
        """
        ...

    def find_symbol_overloads(
        self,
        root: Path,
        symbol: SymbolRow,
        *,
        conn: object | None = None,
    ) -> list[OverloadRow]:
        """
        Return overload metadata attached to one canonical callable symbol.

        Parameters
        ----------
        root : pathlib.Path
            Repository root whose index should be queried.
        symbol : codira.types.SymbolRow
            Canonical function or method symbol row.
        conn : object | None, optional
            Existing backend connection to reuse.

        Returns
        -------
        list[codira.types.OverloadRow]
            Ordered overload metadata rows for the symbol.
        """
        ...

    def find_symbol_enum_members(
        self,
        root: Path,
        symbol: SymbolRow,
        *,
        conn: object | None = None,
    ) -> list[EnumMemberRow]:
        """
        Return enum-member metadata attached to one canonical enum symbol.

        Parameters
        ----------
        root : pathlib.Path
            Repository root whose index should be queried.
        symbol : codira.types.SymbolRow
            Canonical enum symbol row.
        conn : object | None, optional
            Existing backend connection to reuse.

        Returns
        -------
        list[codira.types.EnumMemberRow]
            Ordered enum-member metadata rows for the symbol.
        """
        ...

    def docstring_issues(
        self,
        root: Path,
        *,
        prefix: str | None = None,
        symbol_names: Sequence[str] | None = None,
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
        symbol_names : collections.abc.Sequence[str] | None, optional
            Symbol names used to restrict issue ownership before backend row
            expansion.
        conn : object | None, optional
            Existing backend connection to reuse.

        Returns
        -------
        list[codira.types.DocstringIssueRow]
            Indexed docstring issue rows ordered deterministically.
        """
        ...

    def find_call_edges(
        self,
        request: BackendRelationQueryRequest,
    ) -> list[tuple[str, str, str | None, str | None, str | None, str | None, int]]:
        """
        Find exact call edges for a caller or callee logical name.

        Parameters
        ----------
        request : BackendRelationQueryRequest
            Exact relation lookup request.

        Returns
        -------
        list[tuple[str, str, str | None, str | None, str | None, str | None, int]]
            Matching call-edge rows ordered deterministically.
        """
        ...

    def find_callable_refs(
        self,
        request: BackendRelationQueryRequest,
    ) -> list[tuple[str, str, str | None, str | None, str | None, str | None, int]]:
        """
        Find exact callable-object references for an owner or target.

        Parameters
        ----------
        request : BackendRelationQueryRequest
            Exact relation lookup request.

        Returns
        -------
        list[tuple[str, str, str | None, str | None, str | None, str | None, int]]
            Matching callable-reference rows ordered deterministically.
        """
        ...
