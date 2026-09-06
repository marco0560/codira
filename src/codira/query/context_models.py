"""Focused context-query responsibility module."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

from codira.config import DEFAULT_EMBEDDING_INDEX_MAX_SOURCE_FILE_BYTES
from codira.types import ChannelBundle, ChannelName, ReferenceRow, SymbolRow

if TYPE_CHECKING:
    from pathlib import Path

    from codira.contracts import (
        BackendQueryConnection,
        SimilarityResolvedCandidate,
        SimilaritySearchResult,
    )
    from codira.query.classifier import QueryIntent, RetrievalPlan
    from codira.query.signals import (
        RetrievalSignal,
        RetrievalSignalFamily,
        RetrievalSignalKind,
    )

SCHEMA_VERSION = "2.0"
# Minimum accepted score
_MIN_SCORE = 1
# Maximum number of rows inspected by the symbol fallback scan.
SYMBOL_FALLBACK_SCAN_LIMIT = 200
# Maximum number of rows retrieved for a token search term.
SYMBOL_TERM_MATCH_LIMIT = 50
# Maximum number of rows inspected by the semantic channel.
SEMANTIC_SCAN_LIMIT = 500
# Maximum number of semantic results returned.
SEMANTIC_RESULT_LIMIT = 50
# Maximum number of embedding results returned.
EMBEDDING_RESULT_LIMIT = 50
DOCUMENTATION_RESULT_LIMIT = 50


class SimilarityContextResults(list[tuple[float, SymbolRow]]):
    """List-compatible context rows retaining aligned similarity sidecars.

    Parameters
    ----------
    search_result : SimilaritySearchResult
        Typed selected-index result before structural filtering.
    resolved : tuple[SimilarityResolvedCandidate, ...]
        Structurally resolved candidates aligned to the context rows.
    rows : list[tuple[float, SymbolRow]]
        Context-ready symbol rows derived from the resolved records.
    """

    def __init__(
        self,
        search_result: SimilaritySearchResult,
        resolved: tuple[SimilarityResolvedCandidate, ...],
        rows: list[tuple[float, SymbolRow]],
    ) -> None:
        """Initialize the stable list view and immutable provenance sidecar.

        Parameters
        ----------
        search_result : SimilaritySearchResult
            Typed query and candidate provenance.
        resolved : tuple[SimilarityResolvedCandidate, ...]
            Post-filter candidates in row-aligned order.
        rows : list[tuple[float, SymbolRow]]
            Context-ready score and symbol pairs.

        Returns
        -------
        None
            The list and provenance sidecar are initialized deterministically.

        Raises
        ------
        ValueError
            If structural transformation loses candidate alignment.
        """

        if len(resolved) != len(rows):
            message = "Similarity context rows must retain candidate alignment."
            raise ValueError(message)
        super().__init__(rows)
        self.search_result = search_result
        self.resolved = resolved


# Maximum number of merged symbols returned.
MERGE_RESULT_LIMIT = 10
MERGE_MAX_PER_FILE = 1
MERGE_ROLE_CAPS: dict[FileRole, int] = {
    "implementation": 6,
    "interface": 3,
    "test": 2,
    "tooling": 1,
    "other": 2,
}
MERGE_LANGUAGE_CAPS: dict[str, int] = {
    "python": 4,
    "c": 4,
    "other": 2,
}
# --- token-capped context construction ---
MAX_TOKENS = 1200
# Number of source lines to include in extracted snippets.
SNIPPET_LINE_LIMIT = 6
# Maximum number of lines shown for extracted docstrings in code context.
DOCSTRING_PREVIEW_LINE_LIMIT = 10
# Maximum number of displayed docstring lines in enriched symbol blocks.
DISPLAY_DOCSTRING_LINE_LIMIT = 12
# Maximum number of enriched symbols rendered in text and prompt output.
ENRICHED_CONTEXT_LIMIT = 5
# --- cap doc issues to avoid prompt bloat ---
MAX_ISSUES = 20
# --- weight for semantic consolidation
SEMANTIC_WEIGHT = 0.3
# Minimum accepted embedding similarity.
EMBEDDING_MIN_SCORE = 0.2
CHANNEL_WEIGHTS: dict[ChannelName, float] = {
    "symbol": 1.0,
    "embedding": 1.0,
    "semantic": 1.0,
    "docs": 0.4,
    "test": 1.0,
    "script": 1.0,
    "overloads": 0.2,
    "call_graph": 0.35,
    "references": 0.3,
    "include_graph": 0.25,
}
MERGE_CROSS_FAMILY_BONUS = 0.15
DOCUMENTATION_DOCS_PATH_BONUS = 0.10
DOCUMENTATION_SPECIAL_PATH_BONUS = 0.20
DOCUMENTATION_NAMED_DOC_BONUS = 0.18
GRAPH_RETRIEVAL_LIMIT_PER_PRODUCER = 5
OVERLOAD_RETRIEVAL_LIMIT = 5
OVERLOAD_MATCH_HINTS = frozenset(
    {
        "arg",
        "args",
        "argument",
        "arguments",
        "keyword",
        "keywords",
        "kwargs",
        "overload",
        "overloads",
        "parameter",
        "parameters",
        "return",
        "returns",
        "signature",
        "signatures",
        "typed",
        "type",
        "types",
    }
)
OVERLOAD_QUERY_STOPWORDS = frozenset(
    {
        "api",
        "callable",
        "callables",
        "class",
        "classes",
        "function",
        "functions",
        "method",
        "methods",
        "public",
        "symbol",
        "symbols",
    }
)
FileRole = Literal["implementation", "interface", "test", "tooling", "other"]
SelectionStage = Literal["primary", "deferred"]
DeferralReason = Literal["file_cap", "role_cap", "language_cap", "docs_code_quota"]
DiversityEntry = dict[str, object]
DiversityDiagnostics = dict[str, list[DiversityEntry]]
MergeDiagnosticsEntry = dict[str, object]
MergeDiagnostics = dict[SymbolRow, MergeDiagnosticsEntry]
ExpansionDiagnostics = dict[str, list[dict[str, object]]]
ProducerDiagnosticsEntry = dict[str, object]
SignalCollectionDiagnostics = dict[str, object]


@dataclass
class _DiversitySelectionState:
    """
    Mutable selection state for merged-result diversity.

    Parameters
    ----------
    selected : list[codira.types.SymbolRow]
        Selected result rows in final display order.
    seen_files : dict[str, int]
        Number of selected rows per source file.
    role_counts : dict[str, int]
        Number of selected rows per classified file role.
    language_counts : dict[str, int]
        Number of selected rows per language family.
    selected_code_count : int
        Number of selected non-documentation rows.
    selected_docs_count : int
        Number of selected documentation rows.
    deferred : list[tuple[codira.types.SymbolRow, str]]
        Primary-stage rows deferred by diversity caps.
    selected_entries : list[dict[str, object]]
        Explain diagnostics for selected rows.
    """

    selected: list[SymbolRow] = field(default_factory=list)
    seen_files: dict[str, int] = field(default_factory=dict)
    role_counts: dict[FileRole, int] = field(default_factory=dict)
    language_counts: dict[str, int] = field(default_factory=dict)
    selected_code_count: int = 0
    selected_docs_count: int = 0
    deferred: list[tuple[SymbolRow, DeferralReason]] = field(default_factory=list)
    selected_entries: list[DiversityEntry] = field(default_factory=list)


@dataclass(frozen=True)
class _DiversitySelectionPolicy:
    """
    Immutable policy inputs for one diversity selection pass.

    Parameters
    ----------
    enforce_docs_code_quota : bool
        Whether docs/code parity is active for the current query intent.
    code_candidate_count : int
        Total non-documentation candidates available in ranked input.
    available_language_count : int
        Number of distinct language families available in ranked input.
    """

    enforce_docs_code_quota: bool
    code_candidate_count: int
    available_language_count: int


@dataclass(frozen=True)
class GraphRetrievalRequest:
    """
    Request parameters for graph-derived retrieval signals.

    Parameters
    ----------
    root : pathlib.Path
        Repository root containing the index database.
    top_matches : list[codira.types.SymbolRow]
        Current retrieval winners used as bounded graph-expansion seeds.
    conn : object
        Open database connection reused for exact graph lookups.
    include_include_graph : bool
        Whether include-graph evidence is enabled by the retrieval plan.
    include_references : bool
        Whether callable-reference evidence is enabled by the retrieval plan.
    prefix : str | None
        Absolute normalized prefix used to restrict owner files and symbols.
    """

    root: Path
    top_matches: list[SymbolRow]
    conn: BackendQueryConnection
    include_include_graph: bool
    include_references: bool
    prefix: str | None


@dataclass(frozen=True)
class ChannelBundleRequest:
    """
    Request parameters for executing enabled retrieval channels.

    Parameters
    ----------
    root : pathlib.Path
        Repository root containing indexed files.
    query : str
        User query string.
    conn : object
        Open database connection.
    intent : codira.query.classifier.QueryIntent
        Structured query classification.
    plan : codira.query.classifier.RetrievalPlan
        Deterministic retrieval plan derived from the query intent.
    prefix : str | None
        Absolute normalized prefix used to restrict candidate files.
    search_profile : str | None
        Named similarity-index runtime profile for semantic retrieval channels.
    """

    root: Path
    query: str
    conn: BackendQueryConnection
    intent: QueryIntent
    plan: RetrievalPlan
    prefix: str | None
    search_profile: str | None


@dataclass(frozen=True)
class _ReferenceScanFile:
    """
    Cached reference-scan view for one project file.

    Parameters
    ----------
    file_path : str
        Absolute file path reused in emitted reference rows.
    text : str
        Full decoded file text used for fast whole-file miss checks.
    searchable_lines : tuple[tuple[int, str], ...]
        Non-import source lines as ``(lineno, text)`` pairs reused across
        multiple symbol-name scans.
    """

    file_path: str
    text: str
    searchable_lines: tuple[tuple[int, str], ...]


@dataclass(frozen=True)
class PromptRenderRequest:
    """
    Request parameters for prompt-oriented context rendering.

    Parameters
    ----------
    root : pathlib.Path
        Repository root used to relativize paths.
    query : str
        Original user query.
    top_matches : list[codira.types.SymbolRow]
        Primary ranked matches.
    doc_issues : list[tuple[str, str]]
        Related docstring issues.
    expanded : list[codira.types.SymbolRow]
        Secondary symbols collected by module expansion.
    unique_refs : list[codira.types.ReferenceRow]
        Cross-reference locations for the selected symbols.
    max_source_file_bytes : int, optional
        Command-scoped source-ingestion byte ceiling.
    """

    root: Path
    query: str
    top_matches: list[SymbolRow]
    doc_issues: list[tuple[str, str]]
    expanded: list[SymbolRow]
    unique_refs: list[ReferenceRow]
    max_source_file_bytes: int = DEFAULT_EMBEDDING_INDEX_MAX_SOURCE_FILE_BYTES


@dataclass(frozen=True)
class ContextJsonRenderRequest:
    """
    Request parameters for JSON context rendering.

    Parameters
    ----------
    root : pathlib.Path
        Repository root used to format file paths.
    top_matches : list[codira.types.SymbolRow]
        Primary ranked symbols.
    doc_issues : list[tuple[str, str]]
        Related docstring issues.
    expanded : list[codira.types.SymbolRow]
        Secondary symbols collected by module expansion.
    unique_refs : list[codira.types.ReferenceRow]
        Cross-reference locations for selected symbols.
    confidence_map : dict[codira.types.SymbolRow, float] | None, optional
        Confidence values keyed by symbol.
    max_source_file_bytes : int, optional
        Command-scoped source-ingestion byte ceiling.
    explain : bool, optional
        Whether explain metadata should be included.
    intent : codira.query.classifier.QueryIntent | None, optional
        Structured query classification.
    plan : codira.query.classifier.RetrievalPlan | None, optional
        Deterministic retrieval plan derived from query intent.
    enabled_channels : set[codira.types.ChannelName] | None, optional
        Channels enabled for the query.
    channel_priority : dict[codira.types.ChannelName, int] | None, optional
        Channel priority mapping.
    ordered_channels : list[codira.types.ChannelName] | None, optional
        Ordered channel names.
    producers : list[ProducerDiagnosticsEntry] | None, optional
        Retrieval-producer diagnostics synthesized from query producer specs.
    signal_collection : SignalCollectionDiagnostics | None, optional
        Compact diagnostics describing capability-gated signal collection.
    signal_preview : list[dict[str, object]] | None, optional
        Compact preview of normalized retrieval signals.
    signal_merge : list[dict[str, object]] | None, optional
        Per-top-match signal attribution summaries.
    bundles : list[codira.types.ChannelBundle] | None, optional
        Raw channel results.
    provenance : codira.query.context.MergeDiagnostics | None, optional
        Merge diagnostics for ranked symbols.
    diversity : codira.query.context.DiversityDiagnostics | None, optional
        Diversity-selection diagnostics for merged symbols.
    expansion : codira.query.context.ExpansionDiagnostics | None, optional
        Expansion diagnostics for graph-derived module expansion.
    """

    root: Path
    top_matches: list[SymbolRow]
    doc_issues: list[tuple[str, str]]
    expanded: list[SymbolRow]
    unique_refs: list[ReferenceRow]
    confidence_map: dict[SymbolRow, float] | None = None
    explain: bool = False
    intent: QueryIntent | None = None
    plan: RetrievalPlan | None = None
    enabled_channels: set[ChannelName] | None = None
    channel_priority: dict[ChannelName, int] | None = None
    ordered_channels: list[ChannelName] | None = None
    producers: list[ProducerDiagnosticsEntry] | None = None
    signal_collection: SignalCollectionDiagnostics | None = None
    signal_preview: list[dict[str, object]] | None = None
    signal_merge: list[dict[str, object]] | None = None
    bundles: list[ChannelBundle] | None = None
    provenance: MergeDiagnostics | None = None
    diversity: DiversityDiagnostics | None = None
    expansion: ExpansionDiagnostics | None = None
    max_source_file_bytes: int = DEFAULT_EMBEDDING_INDEX_MAX_SOURCE_FILE_BYTES


@dataclass(frozen=True)
class ExplainSectionsRequest:
    """
    Request parameters for plain-text explain-section rendering.

    Parameters
    ----------
    lines : list[str]
        Mutable output buffer.
    explain : bool
        Whether explain sections should be rendered.
    intent : codira.query.classifier.QueryIntent | None
        Structured query classification.
    plan : codira.query.classifier.RetrievalPlan | None
        Deterministic retrieval plan derived from query intent.
    enabled_channels : set[codira.types.ChannelName] | None
        Channels enabled for the query.
    channel_priority : dict[codira.types.ChannelName, int] | None
        Channel priority mapping.
    ordered_channels : list[codira.types.ChannelName] | None
        Ordered channel names.
    producers : list[ProducerDiagnosticsEntry] | None
        Retrieval-producer diagnostics synthesized from query producer specs.
    signal_collection : SignalCollectionDiagnostics | None
        Compact diagnostics describing capability-gated signal collection.
    signal_preview : list[dict[str, object]] | None
        Compact preview of normalized retrieval signals.
    signal_merge : list[dict[str, object]] | None
        Per-top-match signal attribution summaries.
    bundles : list[codira.types.ChannelBundle] | None
        Raw channel results.
    provenance : codira.query.context.MergeDiagnostics | None
        Merge diagnostics for ranked symbols.
    diversity : codira.query.context.DiversityDiagnostics | None
        Diversity-selection diagnostics for merged symbols.
    expansion : codira.query.context.ExpansionDiagnostics | None
        Expansion diagnostics for graph-derived module expansion.
    top_matches : list[codira.types.SymbolRow]
        Primary merged symbols to explain.
    root : pathlib.Path
        Repository root whose repo-local embedding configuration should be
        reported.
    """

    lines: list[str]
    explain: bool
    intent: QueryIntent | None
    plan: RetrievalPlan | None
    enabled_channels: set[ChannelName] | None
    channel_priority: dict[ChannelName, int] | None
    ordered_channels: list[ChannelName] | None
    producers: list[ProducerDiagnosticsEntry] | None
    signal_collection: SignalCollectionDiagnostics | None
    signal_preview: list[dict[str, object]] | None
    signal_merge: list[dict[str, object]] | None
    bundles: list[ChannelBundle] | None
    provenance: MergeDiagnostics | None
    diversity: DiversityDiagnostics | None
    expansion: ExpansionDiagnostics | None
    top_matches: list[SymbolRow]
    root: Path


@dataclass(frozen=True)
class MainContextSectionsRequest:
    """
    Request parameters for the main plain-text context sections.

    Parameters
    ----------
    lines : list[str]
        Mutable output buffer.
    root : pathlib.Path
        Repository root used to relativize paths.
    top_matches : list[codira.types.SymbolRow]
        Primary ranked symbols.
    doc_issues : list[tuple[str, str]]
        Related docstring issues.
    expanded : list[codira.types.SymbolRow]
        Secondary symbols collected by module expansion.
    unique_refs : list[codira.types.ReferenceRow]
        Cross-reference locations for selected symbols.
    max_source_file_bytes : int, optional
        Command-scoped source-ingestion byte ceiling.
    """

    lines: list[str]
    root: Path
    top_matches: list[SymbolRow]
    doc_issues: list[tuple[str, str]]
    expanded: list[SymbolRow]
    unique_refs: list[ReferenceRow]
    max_source_file_bytes: int = DEFAULT_EMBEDDING_INDEX_MAX_SOURCE_FILE_BYTES


@dataclass(frozen=True)
class ContextRenderRequest:
    """
    Request parameters for final context rendering.

    Parameters
    ----------
    root : pathlib.Path
        Repository root used to relativize paths.
    query : str
        Original user query.
    top_matches : list[codira.types.SymbolRow]
        Primary ranked symbols.
    doc_issues : list[tuple[str, str]]
        Related docstring issues.
    expanded : list[codira.types.SymbolRow]
        Secondary symbols collected by module expansion.
    unique_refs : list[codira.types.ReferenceRow]
        Cross-reference locations for selected symbols.
    confidence_map : dict[codira.types.SymbolRow, float] | None, optional
        Confidence values keyed by symbol.
    as_json : bool, optional
        Whether to render JSON output.
    as_prompt : bool, optional
        Whether to render prompt output.
    explain : bool, optional
        Whether to include explain metadata.
    intent : codira.query.classifier.QueryIntent | None, optional
        Structured query classification.
    plan : codira.query.classifier.RetrievalPlan | None, optional
        Deterministic retrieval plan derived from query intent.
    enabled_channels : set[codira.types.ChannelName] | None, optional
        Channels enabled for the query.
    channel_priority : dict[codira.types.ChannelName, int] | None, optional
        Channel priority mapping.
    ordered_channels : list[codira.types.ChannelName] | None, optional
        Ordered channel names.
    producers : list[ProducerDiagnosticsEntry] | None, optional
        Retrieval-producer diagnostics synthesized from query producer specs.
    signal_collection : SignalCollectionDiagnostics | None, optional
        Compact diagnostics describing capability-gated signal collection.
    signal_preview : list[dict[str, object]] | None, optional
        Compact preview of normalized retrieval signals.
    signal_merge : list[dict[str, object]] | None, optional
        Per-top-match signal attribution summaries.
    bundles : list[codira.types.ChannelBundle] | None, optional
        Raw channel results.
    provenance : codira.query.context.MergeDiagnostics | None, optional
        Merge diagnostics for ranked symbols.
    diversity : codira.query.context.DiversityDiagnostics | None, optional
        Diversity-selection diagnostics for merged symbols.
    expansion : codira.query.context.ExpansionDiagnostics | None, optional
        Expansion diagnostics for graph-derived module expansion.
    max_source_file_bytes : int, optional
        Command-scoped source-ingestion byte ceiling.
    """

    root: Path
    query: str
    top_matches: list[SymbolRow]
    doc_issues: list[tuple[str, str]]
    expanded: list[SymbolRow]
    unique_refs: list[ReferenceRow]
    confidence_map: dict[SymbolRow, float] | None = None
    as_json: bool = False
    as_prompt: bool = False
    explain: bool = False
    intent: QueryIntent | None = None
    plan: RetrievalPlan | None = None
    enabled_channels: set[ChannelName] | None = None
    channel_priority: dict[ChannelName, int] | None = None
    ordered_channels: list[ChannelName] | None = None
    producers: list[ProducerDiagnosticsEntry] | None = None
    signal_collection: SignalCollectionDiagnostics | None = None
    signal_preview: list[dict[str, object]] | None = None
    signal_merge: list[dict[str, object]] | None = None
    bundles: list[ChannelBundle] | None = None
    provenance: MergeDiagnostics | None = None
    diversity: DiversityDiagnostics | None = None
    expansion: ExpansionDiagnostics | None = None
    max_source_file_bytes: int = DEFAULT_EMBEDDING_INDEX_MAX_SOURCE_FILE_BYTES


@dataclass(frozen=True)
class ContextRequest:
    """
    Request parameters for end-to-end context retrieval.

    Parameters
    ----------
    root : pathlib.Path
        Root directory of the indexed repository.
    query : str
        Query string used to retrieve relevant symbols and context.
    prefix : str | None, optional
        Repo-root-relative path prefix used to restrict files and references.
    as_json : bool, optional
        Whether to emit the JSON representation.
    as_prompt : bool, optional
        Whether to emit the prompt-oriented representation.
    explain : bool, optional
        Whether to include retrieval diagnostics.
    search_profile : str | None, optional
        Named similarity-index runtime profile for embedding and documentation
        retrieval channels. ``None`` selects ``default``.
    conn : codira.contracts.BackendQueryConnection | None, optional
        Existing read connection to reuse. When omitted, context retrieval owns
        and closes a direct backend connection.
    max_source_file_bytes : int, optional
        Command-scoped source-ingestion byte ceiling used for context rereads.
    """

    root: Path
    query: str
    prefix: str | None = None
    as_json: bool = False
    as_prompt: bool = False
    explain: bool = False
    search_profile: str | None = None
    conn: BackendQueryConnection | None = None
    max_source_file_bytes: int = DEFAULT_EMBEDDING_INDEX_MAX_SOURCE_FILE_BYTES


@dataclass(frozen=True)
class ExpansionCollectionRequest:
    """
    Request parameters for module expansion and reference collection.

    Parameters
    ----------
    root : pathlib.Path
        Repository root used for file discovery and path normalization.
    top_matches : list[codira.types.SymbolRow]
        Primary ranked symbols for the query.
    conn : object
        Open database connection reused for graph lookups and symbol expansion.
    include_include_graph : bool
        Whether include-graph expansion is enabled by the retrieval plan.
    include_references : bool
        Whether cross-module reference collection is enabled by the retrieval
        plan.
    prefix : str | None, optional
        Absolute normalized prefix used to restrict owner files, expanded
        symbols, and scanned references.
    graph_signals : list[codira.query.signals.RetrievalSignal] | None, optional
        Mutable signal buffer that receives normalized graph evidence when
        supplied.
    """

    root: Path
    top_matches: list[SymbolRow]
    conn: BackendQueryConnection
    include_include_graph: bool
    include_references: bool
    prefix: str | None = None
    graph_signals: list[RetrievalSignal] | None = None


@dataclass(frozen=True)
class GraphRelatedExpansionRequest:
    """
    Request parameters for graph-based related-symbol expansion.

    Parameters
    ----------
    root : pathlib.Path
        Repository root containing the index database.
    top_matches : list[codira.types.SymbolRow]
        Primary ranked symbols for the query.
    conn : object
        Open database connection reused for exact graph lookups.
    include_include_graph : bool
        Whether include-graph expansion is enabled.
    include_references : bool
        Whether callable-reference expansion is enabled.
    prefix : str | None, optional
        Absolute normalized prefix used to restrict owner files and symbols.
    expanded : list[codira.types.SymbolRow]
        Pending expanded symbols collected for the query.
    seen_symbols : set[codira.types.SymbolRow]
        Symbols already admitted to the expanded result set.
    graph_signals : list[codira.query.signals.RetrievalSignal] | None, optional
        Mutable signal buffer that receives normalized graph evidence when
        supplied.
    """

    root: Path
    top_matches: list[SymbolRow]
    conn: BackendQueryConnection
    include_include_graph: bool
    include_references: bool
    prefix: str | None
    expanded: list[SymbolRow]
    seen_symbols: set[SymbolRow]
    graph_signals: list[RetrievalSignal] | None = None


@dataclass
class ContextExecutionState:
    """
    Mutable state threaded through end-to-end context retrieval.

    Parameters
    ----------
    normalized_prefix : str | None
        Absolute normalized prefix used to restrict files and references.
    intent : codira.query.classifier.QueryIntent
        Structured query classification.
    plan : codira.query.classifier.RetrievalPlan
        Deterministic retrieval plan derived from the query intent.
    bundles : list[codira.types.ChannelBundle]
        Channel bundles collected for the query.
    ordered_channels : list[codira.types.ChannelName] | None
        Ordered channel names when explain metadata is retained.
    enabled : set[codira.types.ChannelName] | None
        Channels enabled for the query when explain output is requested.
    priority : dict[codira.types.ChannelName, int] | None
        Channel priority mapping when explain output is requested.
    producer_diagnostics : list[ProducerDiagnosticsEntry] | None
        Retrieval-producer diagnostics synthesized from query producer specs.
    signal_collection : SignalCollectionDiagnostics | None
        Compact diagnostics describing capability-gated signal collection.
    retrieval_signals : list[codira.query.signals.RetrievalSignal]
        Normalized retrieval signals collected for ranking.
    provenance : codira.query.context.MergeDiagnostics | None
        Merge diagnostics for ranked symbols.
    top_matches : list[codira.types.SymbolRow]
        Current ranked symbol winners.
    diversity : codira.query.context.DiversityDiagnostics | None
        Diversity-selection diagnostics for merged symbols.
    expansion : codira.query.context.ExpansionDiagnostics | None
        Expansion diagnostics for graph-derived module expansion.
    signal_preview : list[dict[str, object]] | None
        Compact preview of normalized retrieval signals.
    signal_merge : list[dict[str, object]] | None
        Per-top-match signal attribution summaries.
    """

    normalized_prefix: str | None
    intent: QueryIntent
    plan: RetrievalPlan
    bundles: list[ChannelBundle]
    ordered_channels: list[ChannelName] | None
    enabled: set[ChannelName] | None
    priority: dict[ChannelName, int] | None
    producer_diagnostics: list[ProducerDiagnosticsEntry] | None
    signal_collection: SignalCollectionDiagnostics | None
    retrieval_signals: list[RetrievalSignal]
    provenance: MergeDiagnostics | None
    top_matches: list[SymbolRow]
    diversity: DiversityDiagnostics | None = None
    expansion: ExpansionDiagnostics | None = None
    signal_preview: list[dict[str, object]] | None = None
    signal_merge: list[dict[str, object]] | None = None


@dataclass(frozen=True)
class SignalAggregationRule:
    """
    Declarative weight applied to one normalized candidate signal.

    Parameters
    ----------
    evidence_detail : str
        Stable signal evidence detail to aggregate.
    weight : int
        Signed contribution multiplier applied to signal strength.
    """

    evidence_detail: str
    weight: int


@dataclass(frozen=True)
class CandidateSignalValue:
    """
    Raw value used to build one symbol-candidate retrieval signal.

    Parameters
    ----------
    evidence_detail : str
        Stable signal detail that identifies the ranking evidence.
    value : int
        Integer evidence magnitude before core aggregation applies policy.
    kind : codira.query.signals.RetrievalSignalKind
        Signal kind assigned to this evidence.
    family : codira.query.signals.RetrievalSignalFamily
        Signal family assigned to this evidence.
    """

    evidence_detail: str
    value: int
    kind: RetrievalSignalKind
    family: RetrievalSignalFamily


PRIMARY_SYMBOL_AGGREGATION_RULES: tuple[SignalAggregationRule, ...] = (
    SignalAggregationRule("exact_name_match", 100),
    SignalAggregationRule("substring_name_match", 50),
    SignalAggregationRule("name_token_overlap_count", 10),
    SignalAggregationRule("module_token_overlap_count", 3),
    SignalAggregationRule("is_function", 5),
    SignalAggregationRule("is_private", -20),
    SignalAggregationRule("path_bias", 1),
    SignalAggregationRule("query_targets_module_as_module", 120),
    SignalAggregationRule("query_targets_module_as_non_module", -40),
    SignalAggregationRule("module_depth_penalty_count", -5),
    SignalAggregationRule("exact_target_symbol_match", 10),
    SignalAggregationRule("exact_raw_query_match", 5),
    SignalAggregationRule("lexical_frequency_count", 2),
    SignalAggregationRule("implementation_module_bonus", 2),
    SignalAggregationRule("lowered_module_penalty", -2),
    SignalAggregationRule("identifier_exact_match", 25),
    SignalAggregationRule("identifier_module_suffix_match", 8),
    SignalAggregationRule("multi_term_module_bonus", 1),
)

FALLBACK_SYMBOL_AGGREGATION_RULES: tuple[SignalAggregationRule, ...] = (
    SignalAggregationRule("exact_name_match", 100),
    SignalAggregationRule("substring_name_match", 50),
    SignalAggregationRule("name_token_overlap_count", 10),
    SignalAggregationRule("module_token_overlap_count", 3),
    SignalAggregationRule("is_function", 5),
    SignalAggregationRule("is_private", -20),
    SignalAggregationRule("path_bias", 1),
    SignalAggregationRule("query_targets_module_as_module", 120),
    SignalAggregationRule("query_targets_module_as_non_module", -40),
    SignalAggregationRule("module_depth_penalty_count", -5),
    SignalAggregationRule("identifier_exact_match", 25),
    SignalAggregationRule("identifier_module_suffix_match", 8),
    SignalAggregationRule("multi_term_module_bonus", 1),
)
