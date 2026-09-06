"""Focused context-query responsibility module."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING, Literal, cast

from codira.contracts import (
    BackendQueryConnection,
    split_declared_retrieval_capabilities,
)
from codira.prefix import prefix_clause
from codira.query.context_models import (
    DOCUMENTATION_RESULT_LIMIT,
    EMBEDDING_MIN_SCORE,
    EMBEDDING_RESULT_LIMIT,
    GRAPH_RETRIEVAL_LIMIT_PER_PRODUCER,
    OVERLOAD_MATCH_HINTS,
    OVERLOAD_QUERY_STOPWORDS,
    OVERLOAD_RETRIEVAL_LIMIT,
    SEMANTIC_RESULT_LIMIT,
    SEMANTIC_SCAN_LIMIT,
    SEMANTIC_WEIGHT,
    ChannelBundleRequest,
    GraphRetrievalRequest,
    ProducerDiagnosticsEntry,
    SignalCollectionDiagnostics,
    SimilarityContextResults,
)
from codira.query.context_scoring import (
    _backend_row_int,
    _classify_file_language,
    _documentation_symbol,
    _include_target_module_name,
    _retrieve_script_candidates,
    _retrieve_symbol_candidates,
    _retrieve_test_candidates,
)
from codira.query.context_source import (
    _classify_file_role,
    _dedupe_channel_results,
    _scored_symbol_sort_key,
    _symbol_sort_key,
    _symbols_in_module,
    _tokenize,
)
from codira.query.exact import find_symbol_overloads
from codira.query.graph_enrichment import (
    GraphExpansionRequest,
    expand_graph_related_symbols,
)
from codira.query.producers import (
    CHANNEL_PRODUCER_SPECS,
    EMBEDDING_RETRIEVAL_PRODUCER,
    OVERLOAD_RETRIEVAL_PRODUCER,
    EmbeddingRetrievalRequest,
    QueryChannelSpec,
    QueryProducerSpec,
    channel_producer_specs,
)
from codira.query.signals import RetrievalSignal, signal_sort_key
from codira.semantic.search import (
    DocumentationCandidatesRequest,
    SimilaritySymbolResults,
    documentation_candidates,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from codira.query.classifier import QueryIntent, RetrievalPlan
    from codira.types import ChannelBundle, ChannelName, ChannelResults, SymbolRow


def _channel_order() -> list[ChannelName]:
    """
    Return the default channel evaluation order.

    Parameters
    ----------
    None

    Returns
    -------
    list[codira.types.ChannelName]
        Channel names in evaluation order.
    """
    return ["symbol", "embedding", "semantic", "test", "script"]


def _build_channel_bundles(
    request: ChannelBundleRequest,
) -> list[ChannelBundle]:
    """
    Execute the enabled retrieval channels for a query.

    Parameters
    ----------
    request : ChannelBundleRequest
        Retrieval-channel execution request.

    Returns
    -------
    list[codira.types.ChannelBundle]
        Channel names paired with their ranked results.
    """
    channel_fns = _get_channel_functions(request.plan)

    return [
        (
            name,
            fn(
                request.root,
                request.query,
                request.conn,
                request.intent,
                request.prefix,
                request.search_profile,
            ),
        )
        for name, fn in channel_fns
    ]


def _channel_retrieval_producers(
    ordered_channels: list[ChannelName] | None,
) -> list[QueryProducerSpec]:
    """
    Build query producer specs for channel-only aggregation paths.

    Parameters
    ----------
    ordered_channels : list[codira.types.ChannelName] | None
        Channel order active for the query. When ``None``, no channel
        producers are emitted.

    Returns
    -------
    list[codira.query.producers.QueryProducerSpec]
        Channel producers without enrichment-specific entries.
    """
    if ordered_channels is None:
        return []
    return channel_producer_specs(ordered_channels)


def _producer_diagnostics(
    producers: list[QueryProducerSpec],
) -> list[ProducerDiagnosticsEntry]:
    """
    Render explain diagnostics for one list of retrieval producers.

    Parameters
    ----------
    producers : list[codira.query.producers.QueryProducerSpec]
        Query-layer retrieval producers for the current runtime.

    Returns
    -------
    list[dict[str, object]]
        Deterministic diagnostics for explain JSON and text rendering.
    """
    diagnostics: list[ProducerDiagnosticsEntry] = []

    for producer in producers:
        declared = producer.capabilities
        known, unknown = split_declared_retrieval_capabilities(declared)
        diagnostics.append(
            {
                "producer_name": producer.producer_name,
                "producer_version": producer.producer_version,
                "capability_version": producer.capability_version,
                "source_kind": producer.source_kind,
                "source_name": producer.source_name,
                "declared_capabilities": list(declared),
                "known_capabilities": list(known),
                "unknown_capabilities": list(unknown),
            }
        )

    return diagnostics


def _signal_kind_for_channel(channel_name: ChannelName) -> str:
    """
    Return the normalized signal kind for one legacy retrieval channel.

    Parameters
    ----------
    channel_name : codira.types.ChannelName
        Legacy retrieval channel name.

    Returns
    -------
    str
        Stable signal kind derived from the query channel.
    """
    if channel_name == "symbol":
        return "exact_symbol"
    if channel_name == "embedding":
        return "embedding_similarity"
    if channel_name == "docs":
        return "embedding_similarity"
    return "text_match"


def _signal_family_for_channel(channel_name: ChannelName) -> str:
    """
    Return the normalized signal family for one legacy retrieval channel.

    Parameters
    ----------
    channel_name : codira.types.ChannelName
        Legacy retrieval channel name.

    Returns
    -------
    str
        Stable signal family derived from the query channel.
    """
    if channel_name == "symbol":
        return "lexical"
    if channel_name in {"embedding", "semantic", "docs"}:
        return "semantic"
    return "task"


def _signal_capability_for_channel(channel_name: ChannelName) -> str:
    """
    Return the primary capability that explains one query channel signal.

    Parameters
    ----------
    channel_name : codira.types.ChannelName
        Legacy retrieval channel name.

    Returns
    -------
    str
        Capability name attributed to signals emitted by the channel.
    """
    if channel_name == "symbol":
        return "symbol_lookup"
    if channel_name == "embedding":
        return "embedding_similarity"
    if channel_name == "semantic":
        return "semantic_text"
    if channel_name == "docs":
        return "embedding_similarity"
    return "task_specialization"


def _signals_from_channel_bundles(
    bundles: list[ChannelBundle],
    *,
    producers: list[QueryProducerSpec],
) -> list[RetrievalSignal]:
    """
    Convert current channel results into normalized retrieval signals.

    Parameters
    ----------
    bundles : list[codira.types.ChannelBundle]
        Ranked channel bundles for the current query.
    producers : list[codira.query.producers.QueryProducerSpec]
        Query-layer retrieval producers synthesized for the same query.

    Returns
    -------
    list[codira.query.signals.RetrievalSignal]
        Deterministically ordered signals representing the current channel
        evidence without changing merge behavior.
    """
    producer_by_channel = {
        producer.source_name: producer
        for producer in producers
        if producer.source_kind == "channel"
    }
    signals: list[RetrievalSignal] = []

    for channel_name, channel in sorted(bundles, key=lambda item: item[0]):
        producer = producer_by_channel.get(channel_name)
        if producer is None:
            continue

        capability_name = _signal_capability_for_channel(channel_name)

        for rank, (strength, symbol) in enumerate(
            _dedupe_channel_results(channel), start=1
        ):
            signals.append(
                RetrievalSignal(
                    kind=cast(
                        "Literal['exact_symbol', 'text_match', 'embedding_similarity', 'relation', 'proximity', 'repeated_evidence']",
                        _signal_kind_for_channel(channel_name),
                    ),
                    family=cast(
                        "Literal['lexical', 'semantic', 'task', 'graph', 'issue']",
                        _signal_family_for_channel(channel_name),
                    ),
                    target=symbol,
                    producer_name=producer.producer_name,
                    producer_version=producer.producer_version,
                    capability_name=capability_name,
                    capability_version=producer.capability_version,
                    channel_name=channel_name,
                    rank=rank,
                    strength=strength,
                )
            )

    return sorted(signals, key=signal_sort_key)


def _signals_from_channel_producer(
    producer: QueryProducerSpec,
    *,
    channel: ChannelResults,
) -> list[RetrievalSignal]:
    """
    Convert one query channel producer into normalized retrieval signals.

    Parameters
    ----------
    producer : codira.query.producers.QueryProducerSpec
        Query-layer producer for one retrieval channel.
    channel : codira.types.ChannelResults
        Ranked results emitted by the producer's channel.

    Returns
    -------
    list[codira.query.signals.RetrievalSignal]
        Deterministically ordered signals contributed by the producer.
    """
    channel_name = producer.source_name
    capability_name = _signal_capability_for_channel(channel_name)
    signals: list[RetrievalSignal] = []

    for rank, (strength, symbol) in enumerate(
        _dedupe_channel_results(channel), start=1
    ):
        signals.append(
            RetrievalSignal(
                kind=cast(
                    "Literal['exact_symbol', 'text_match', 'embedding_similarity', 'relation', 'proximity', 'repeated_evidence']",
                    _signal_kind_for_channel(channel_name),
                ),
                family=cast(
                    "Literal['lexical', 'semantic', 'task', 'graph', 'issue']",
                    _signal_family_for_channel(channel_name),
                ),
                target=symbol,
                producer_name=producer.producer_name,
                producer_version=producer.producer_version,
                capability_name=capability_name,
                capability_version=producer.capability_version,
                channel_name=channel_name,
                rank=rank,
                strength=strength,
            )
        )

    return signals


def _graph_channel_name_for_signal(signal: RetrievalSignal) -> ChannelName | None:
    """
    Map one graph producer signal onto a bounded ranking pseudo-channel.

    Parameters
    ----------
    signal : codira.query.signals.RetrievalSignal
        Graph-derived signal emitted by one enrichment producer.

    Returns
    -------
    codira.types.ChannelName | None
        Stable pseudo-channel name used during bounded graph ranking, or
        ``None`` when the signal should not influence retrieval-time ranking.
    """
    producer_to_channel: dict[str, ChannelName] = {
        "query-enrichment-call-graph": "call_graph",
        "query-enrichment-references": "references",
        "query-enrichment-include-graph": "include_graph",
    }
    return producer_to_channel.get(signal.producer_name)


def _strength_for_graph_signal(distance: int, support_count: int) -> float:
    """
    Compute a bounded retrieval strength for one graph-supported target.

    Parameters
    ----------
    distance : int
        Best graph distance observed for the target.
    support_count : int
        Number of raw graph relations supporting the same target.

    Returns
    -------
    float
        Deterministic bounded strength that rewards direct and repeated graph
        evidence without overwhelming stronger primary channels.
    """
    repeat_bonus = min(float(max(support_count - 1, 0)) * 0.1, 0.3)
    return (1.0 / float(max(distance, 1))) + repeat_bonus


def _bounded_graph_retrieval_signals(
    raw_graph_signals: list[RetrievalSignal],
) -> list[RetrievalSignal]:
    """
    Convert raw graph expansion evidence into bounded ranking signals.

    Parameters
    ----------
    raw_graph_signals : list[codira.query.signals.RetrievalSignal]
        Raw graph-derived signals collected around current top matches.

    Returns
    -------
    list[codira.query.signals.RetrievalSignal]
        Deterministically ranked graph signals that can participate in the
        normal retrieval merge path.
    """
    grouped: dict[
        tuple[ChannelName, SymbolRow],
        tuple[RetrievalSignal, int, int],
    ] = {}

    for signal in sorted(raw_graph_signals, key=signal_sort_key):
        channel_name = _graph_channel_name_for_signal(signal)
        if channel_name is None:
            continue
        distance = signal.distance if signal.distance is not None else 1
        key = (channel_name, signal.target)
        if key not in grouped:
            grouped[key] = (signal, distance, 1)
            continue

        representative, best_distance, support_count = grouped[key]
        if distance < best_distance:
            representative = signal
            best_distance = distance
        grouped[key] = (representative, best_distance, support_count + 1)

    ranked_signals: list[RetrievalSignal] = []
    grouped_by_channel: dict[
        ChannelName,
        list[tuple[RetrievalSignal, int, int]],
    ] = {}
    for (channel_name, _target), value in grouped.items():
        grouped_by_channel.setdefault(channel_name, []).append(value)

    for channel_name, items in sorted(grouped_by_channel.items()):
        ranked_items = sorted(
            items,
            key=lambda item: (
                -_strength_for_graph_signal(item[1], item[2]),
                item[1],
                *_symbol_sort_key(item[0].target),
            ),
        )
        for rank, (signal, distance, support_count) in enumerate(
            ranked_items[:GRAPH_RETRIEVAL_LIMIT_PER_PRODUCER], start=1
        ):
            ranked_signals.append(
                replace(
                    signal,
                    channel_name=channel_name,
                    rank=rank,
                    strength=_strength_for_graph_signal(distance, support_count),
                    distance=distance,
                )
            )

    return sorted(ranked_signals, key=signal_sort_key)


def _collect_graph_retrieval_signals(
    request: GraphRetrievalRequest,
) -> list[RetrievalSignal]:
    """
    Collect bounded graph-derived retrieval signals around current top matches.

    Parameters
    ----------
    request : GraphRetrievalRequest
        Graph retrieval request carrying current matches and enabled graph
        expansion channels.

    Returns
    -------
    list[codira.query.signals.RetrievalSignal]
        Bounded graph-derived retrieval signals eligible for merged ranking.
    """
    raw_graph_signals: list[RetrievalSignal] = []
    expand_graph_related_symbols(
        GraphExpansionRequest(
            root=request.root,
            top_matches=request.top_matches,
            conn=request.conn,
            include_include_graph=request.include_include_graph,
            include_references=request.include_references,
            prefix=request.prefix,
            expanded=[],
            seen_symbols=set(request.top_matches),
            graph_signals=raw_graph_signals,
            classify_file_language=_classify_file_language,
            classify_file_role=_classify_file_role,
            include_target_module_name=_include_target_module_name,
            symbols_in_module=_symbols_in_module,
        )
    )
    return _bounded_graph_retrieval_signals(raw_graph_signals)


def _collect_retrieval_signals(
    bundles: list[ChannelBundle],
    *,
    producers: list[QueryProducerSpec],
) -> tuple[list[RetrievalSignal], SignalCollectionDiagnostics]:
    """
    Collect normalized retrieval signals through capability-aware producers.

    Parameters
    ----------
    bundles : list[codira.types.ChannelBundle]
        Ranked channel bundles for the current query.
    producers : list[codira.query.producers.QueryProducerSpec]
        Query-layer retrieval producers synthesized for the same query.

    Returns
    -------
    tuple[list[codira.query.signals.RetrievalSignal], dict[str, object]]
        Deterministically ordered signals plus compact collection diagnostics.
    """
    bundles_by_channel = {channel_name: channel for channel_name, channel in bundles}
    signals: list[RetrievalSignal] = []
    used_producers: list[str] = []
    ignored_producers: list[str] = []

    for producer in producers:
        known_capabilities, _unknown_capabilities = (
            split_declared_retrieval_capabilities(producer.capabilities)
        )

        if producer.source_kind != "channel":
            ignored_producers.append(producer.producer_name)
            continue

        channel = bundles_by_channel.get(producer.source_name)
        if channel is None:
            ignored_producers.append(producer.producer_name)
            continue

        if not known_capabilities:
            ignored_producers.append(producer.producer_name)
            continue

        used_producers.append(producer.producer_name)
        signals.extend(_signals_from_channel_producer(producer, channel=channel))

    ordered_signals = sorted(signals, key=signal_sort_key)
    diagnostics = _signal_collection_diagnostics(
        ordered_signals,
        used_producers=used_producers,
        ignored_producers=ignored_producers,
    )
    return ordered_signals, diagnostics


def _query_prefers_overload_evidence(
    query: str,
    *,
    intent: QueryIntent,
) -> bool:
    """
    Return whether overload-signature evidence should participate in ranking.

    Parameters
    ----------
    query : str
        Raw user query text.
    intent : codira.query.classifier.QueryIntent
        Deterministic query classification for the same query.

    Returns
    -------
    bool
        ``True`` when the query is API-surface oriented and contains typed or
        signature-oriented hints that justify bounded overload evidence.
    """
    if intent.primary_intent != "api_surface":
        return False

    lowered = query.lower()
    query_tokens = _tokenize(lowered)
    return any(token in OVERLOAD_MATCH_HINTS for token in query_tokens) or any(
        char in lowered for char in "(),[]"
    )


def _overload_query_tokens(
    query: str,
) -> set[str]:
    """
    Return normalized query tokens that can match overload signature detail.

    Parameters
    ----------
    query : str
        Raw user query text.

    Returns
    -------
    set[str]
        Signature-relevant query tokens with generic API-surface words
        removed.
    """
    return {
        token
        for token in _tokenize(query)
        if token not in OVERLOAD_QUERY_STOPWORDS and token not in OVERLOAD_MATCH_HINTS
    }


def _bounded_overload_strength(
    overlap_count: int,
) -> float:
    """
    Convert overload token overlap into a bounded auxiliary signal strength.

    Parameters
    ----------
    overlap_count : int
        Number of signature-relevant tokens shared with the query.

    Returns
    -------
    float
        Bounded overload evidence strength that can support ranking without
        overwhelming primary retrieval channels.
    """
    return min(0.6, 0.2 + (0.15 * float(overlap_count)))


def _collect_overload_retrieval_signals(
    *,
    root: Path,
    query: str,
    intent: QueryIntent,
    conn: BackendQueryConnection,
    candidate_signals: list[RetrievalSignal],
) -> list[RetrievalSignal]:
    """
    Convert overload metadata into bounded retrieval signals for callables.

    Parameters
    ----------
    root : pathlib.Path
        Repository root containing the active index.
    query : str
        Raw user query text.
    intent : codira.query.classifier.QueryIntent
        Deterministic query classification for the same query.
    conn : object
        Open backend connection used for overload lookups.
    candidate_signals : list[codira.query.signals.RetrievalSignal]
        Current normalized retrieval signals whose exact-symbol-backed
        callables are eligible for overload support.

    Returns
    -------
    list[codira.query.signals.RetrievalSignal]
        Deterministically ordered overload-derived signals limited to current
        callable candidates.
    """
    if not _query_prefers_overload_evidence(query, intent=intent):
        return []

    query_tokens = _overload_query_tokens(query)
    if not query_tokens:
        return []

    exact_symbol_candidates = sorted(
        {
            signal.target
            for signal in candidate_signals
            if signal.channel_name == "symbol"
            and signal.target[0] in {"function", "method"}
        },
        key=_symbol_sort_key,
    )
    if not exact_symbol_candidates:
        return []

    best_matches: list[tuple[float, SymbolRow, str]] = []

    for symbol in exact_symbol_candidates:
        if symbol[0] not in {"function", "method"}:
            continue
        overloads = find_symbol_overloads(root, symbol, conn=conn)
        if not overloads:
            continue

        callable_name = symbol[2].lower()
        best_signature: str | None = None
        best_overlap = 0

        for (
            _stable_id,
            _parent_id,
            _ordinal,
            signature,
            _lineno,
            _end_lineno,
            _doc,
        ) in overloads:
            signature_tokens = {
                token
                for token in _tokenize(signature)
                if token != callable_name and token not in OVERLOAD_MATCH_HINTS
            }
            overlap = len(query_tokens & signature_tokens)
            if overlap > best_overlap:
                best_overlap = overlap
                best_signature = signature

        if best_signature is None or best_overlap <= 0:
            continue

        best_matches.append(
            (_bounded_overload_strength(best_overlap), symbol, best_signature)
        )

    if not best_matches:
        return []

    ranked_matches = sorted(
        best_matches,
        key=lambda item: (-item[0], *_symbol_sort_key(item[1]), item[2]),
    )[:OVERLOAD_RETRIEVAL_LIMIT]

    signals = [
        RetrievalSignal(
            kind="text_match",
            family="semantic",
            target=symbol,
            producer_name=OVERLOAD_RETRIEVAL_PRODUCER.producer_name,
            producer_version=OVERLOAD_RETRIEVAL_PRODUCER.producer_version,
            capability_name="semantic_text",
            capability_version=OVERLOAD_RETRIEVAL_PRODUCER.capability_version,
            evidence_detail=f"overload_signature:{signature}",
            channel_name="overloads",
            rank=rank,
            strength=strength,
        )
        for rank, (strength, symbol, signature) in enumerate(ranked_matches, start=1)
    ]
    return sorted(signals, key=signal_sort_key)


def _signal_collection_diagnostics(
    signals: list[RetrievalSignal],
    *,
    used_producers: list[str],
    ignored_producers: list[str],
) -> SignalCollectionDiagnostics:
    """
    Summarize one normalized signal set for explain diagnostics.

    Parameters
    ----------
    signals : list[codira.query.signals.RetrievalSignal]
        Normalized signals to summarize.
    used_producers : list[str]
        Producer identifiers that contributed at least one signal.
    ignored_producers : list[str]
        Producer identifiers that were available but did not contribute.

    Returns
    -------
    dict[str, object]
        Compact deterministic signal-collection diagnostics.
    """
    families: dict[str, int] = {}
    capabilities: dict[str, int] = {}

    for signal in signals:
        families[signal.family] = families.get(signal.family, 0) + 1
        capabilities[signal.capability_name] = (
            capabilities.get(signal.capability_name, 0) + 1
        )

    diagnostics: SignalCollectionDiagnostics = {
        "total_signals": len(signals),
        "families": dict(sorted(families.items())),
        "capabilities": dict(sorted(capabilities.items())),
        "used_producers": sorted(used_producers),
        "ignored_producers": sorted(ignored_producers),
    }
    return diagnostics


def _signal_preview(
    signals: list[RetrievalSignal],
    *,
    limit: int = 12,
) -> list[dict[str, object]]:
    """
    Build a compact explain preview for normalized retrieval signals.

    Parameters
    ----------
    signals : list[codira.query.signals.RetrievalSignal]
        Normalized signals collected for the current query.
    limit : int, optional
        Maximum number of preview entries to emit.

    Returns
    -------
    list[dict[str, object]]
        Compact deterministic signal preview entries.
    """
    preview: list[dict[str, object]] = []

    for signal in sorted(signals, key=signal_sort_key)[:limit]:
        symbol_type, module_name, name, _file_path, lineno = signal.target
        entry: dict[str, object] = {
            "kind": signal.kind,
            "family": signal.family,
            "producer_name": signal.producer_name,
            "capability_name": signal.capability_name,
            "type": symbol_type,
            "module": module_name,
            "name": name,
            "lineno": lineno,
        }
        if signal.channel_name is not None:
            entry["channel_name"] = signal.channel_name
        if signal.evidence_detail is not None:
            entry["evidence_detail"] = signal.evidence_detail
        if signal.rank is not None:
            entry["rank"] = signal.rank
        if signal.strength is not None:
            entry["strength"] = round(signal.strength, 4)
        if signal.distance is not None:
            entry["distance"] = signal.distance
        if signal.source_symbol is not None:
            source_type, source_module, source_name, _source_file, source_lineno = (
                signal.source_symbol
            )
            entry["source"] = {
                "type": source_type,
                "module": source_module,
                "name": source_name,
                "lineno": source_lineno,
            }
        preview.append(entry)

    return preview


def _signal_summary_by_symbol(
    signals: list[RetrievalSignal],
    top_matches: list[SymbolRow],
) -> list[dict[str, object]]:
    """
    Summarize signal support for the current top matches.

    Parameters
    ----------
    signals : list[codira.query.signals.RetrievalSignal]
        Normalized signals collected for the current query.
    top_matches : list[codira.types.SymbolRow]
        Ranked top matches for the query.

    Returns
    -------
    list[dict[str, object]]
        Per-symbol signal summaries for explain output.
    """
    by_symbol: dict[SymbolRow, list[RetrievalSignal]] = {}
    for signal in signals:
        by_symbol.setdefault(signal.target, []).append(signal)

    entries: list[dict[str, object]] = []
    for symbol in top_matches:
        symbol_signals = sorted(by_symbol.get(symbol, []), key=signal_sort_key)
        if not symbol_signals:
            continue
        symbol_type, module_name, name, _file_path, lineno = symbol
        families: dict[str, int] = {}
        capabilities: dict[str, int] = {}
        evidence: dict[str, int] = {}
        producers: set[str] = set()

        for signal in symbol_signals:
            families[signal.family] = families.get(signal.family, 0) + 1
            capabilities[signal.capability_name] = (
                capabilities.get(signal.capability_name, 0) + 1
            )
            if signal.evidence_detail is not None:
                evidence_kind = signal.evidence_detail.split(":", 1)[0]
                evidence[evidence_kind] = evidence.get(evidence_kind, 0) + 1
            producers.add(signal.producer_name)

        entry = {
            "type": symbol_type,
            "module": module_name,
            "name": name,
            "lineno": lineno,
            "signal_count": len(symbol_signals),
            "families": dict(sorted(families.items())),
            "capabilities": dict(sorted(capabilities.items())),
            "producers": sorted(producers),
        }
        if evidence:
            entry["evidence"] = dict(sorted(evidence.items()))
        entries.append(entry)

    return entries


def _get_channel_functions(
    plan: RetrievalPlan,
) -> list[
    tuple[
        ChannelName,
        Callable[
            [Path, str, BackendQueryConnection, QueryIntent, str | None, str | None],
            ChannelResults,
        ],
    ]
]:
    """
    Resolve enabled channel functions for a query intent.

    Parameters
    ----------
    plan : codira.query.classifier.RetrievalPlan
        Deterministic retrieval plan derived from query intent.

    Returns
    -------
    list[
        tuple[
            codira.types.ChannelName,
            collections.abc.Callable[
                [
                    pathlib.Path,
                    str,
                    object,
                    codira.query.classifier.QueryIntent,
                    str | None,
                    str | None,
                ],
                codira.types.ChannelResults,
            ],
        ]
    ]
        Ordered channel names and their retrieval callables.
    """
    registry = _channel_registry()
    return [
        (name, registry[name].retrieve) for name in plan.channels if name in registry
    ]


def _retrieve_semantic_candidates(  # noqa: PLR0913
    root: Path,
    query: str,
    conn: BackendQueryConnection,
    intent: QueryIntent,
    prefix: str | None,
    search_profile: str | None,
) -> ChannelResults:
    """
    Deterministic semantic channel with independent candidate retrieval.

    Parameters
    ----------
    root : pathlib.Path
        Repository root containing indexed files. The current implementation
        does not need it directly.
    query : str
        User query string.
    conn : object
        Open database connection.
    intent : codira.query.classifier.QueryIntent
        Structured query classification. The current implementation does not
        use it directly.
    prefix : str | None
        Absolute normalized prefix used to restrict candidate files.
    search_profile : str | None
        Unused similarity-index runtime profile.

    Returns
    -------
    codira.types.ChannelResults
        Ranked semantic candidates for the query.

    Notes
    -----
    The channel is deterministic and independent from the symbol channel. It
    scores token overlap against symbol names and module names without
    consulting legacy auxiliary compatibility tables.
    """

    del root, search_profile

    tokens = [t.lower() for t in _tokenize(query) if len(t) >= 3]
    if not tokens:
        return []

    prefix_sql, prefix_params = prefix_clause(prefix, "f.path")
    rows = conn.execute(  # nosemgrep: python.sqlalchemy.security.sqlalchemy-execute-raw-query.sqlalchemy-execute-raw-query
        f"""
        SELECT s.type, s.module_name, s.name, f.path, s.lineno
        FROM symbol_index s
        JOIN files f
          ON s.file_id = f.id
        WHERE 1 = 1
        {prefix_sql}
        ORDER BY s.module_name, s.name, f.path, s.lineno
        LIMIT ?
        """,
        (*prefix_params, SEMANTIC_SCAN_LIMIT),
    ).fetchall()

    results: ChannelResults = []

    for row in rows:
        symbol = (
            str(row[0]),
            str(row[1]),
            str(row[2]),
            str(row[3]),
            _backend_row_int(row[4]),
        )

        symbol_type, module_name, name, _file_path, _lineno = symbol

        text_parts = [module_name.lower(), name.lower()]

        semantic_score = 0.0

        for token in tokens:
            if token in name.lower():
                semantic_score += 3.0
            elif token in module_name.lower():
                semantic_score += 2.0
            elif any(token in part for part in text_parts):
                semantic_score += 1.0

        if semantic_score == 0.0:
            continue

        if symbol_type == "function":
            semantic_score += 0.5

        if name.startswith("_"):
            semantic_score -= 1.0

        if semantic_score >= SEMANTIC_WEIGHT:
            results.append((semantic_score, symbol))

    results.sort(key=_scored_symbol_sort_key)

    return results[:SEMANTIC_RESULT_LIMIT]


def _retrieve_embedding_candidates(  # noqa: PLR0913
    root: Path,
    query: str,
    conn: BackendQueryConnection,
    intent: QueryIntent,
    prefix: str | None,
    search_profile: str | None,
) -> ChannelResults:
    """
    Retrieve ranked candidates from the stored embedding channel.

    Parameters
    ----------
    root : pathlib.Path
        Repository root containing the index database.
    query : str
        User query string.
    conn : object
        Open database connection.
    intent : codira.query.classifier.QueryIntent
        Structured query classification used to apply role-aware ranking bias.
    prefix : str | None
        Absolute normalized prefix used to restrict candidate files.
    search_profile : str | None
        Named similarity-index runtime profile.

    Returns
    -------
    codira.types.ChannelResults
        Ranked embedding-channel candidates for the query.
    """
    results = EMBEDDING_RETRIEVAL_PRODUCER.retrieve_candidates(
        EmbeddingRetrievalRequest(
            root=root,
            query=query,
            limit=EMBEDDING_RESULT_LIMIT,
            min_score=EMBEDDING_MIN_SCORE,
            prefix=prefix,
            search_profile=search_profile,
            conn=conn,
        )
    )
    if isinstance(results, SimilaritySymbolResults):
        aligned = list(zip(results, results.resolved, strict=True))
        aligned.sort(key=lambda item: _scored_symbol_sort_key(item[0]))
        return SimilarityContextResults(
            results.search_result,
            tuple(item[1] for item in aligned),
            [item[0] for item in aligned],
        )
    sorted_results = list(results)
    sorted_results.sort(key=_scored_symbol_sort_key)
    return sorted_results


def _retrieve_documentation_candidates(  # noqa: PLR0913
    root: Path,
    query: str,
    conn: BackendQueryConnection,
    intent: QueryIntent,
    prefix: str | None,
    search_profile: str | None,
) -> ChannelResults:
    """
    Retrieve ranked candidates from the documentation channel.

    Parameters
    ----------
    root : pathlib.Path
        Repository root containing the index database.
    query : str
        User query string.
    conn : object
        Open database connection.
    intent : codira.query.classifier.QueryIntent
        Structured query classification used to weight documentation results.
    prefix : str | None
        Absolute normalized prefix used to restrict candidate files.
    search_profile : str | None
        Named similarity-index runtime profile.

    Returns
    -------
    codira.types.ChannelResults
        Ranked documentation candidates converted to top-match rows.
    """
    del intent
    rows = documentation_candidates(
        DocumentationCandidatesRequest(
            root=root,
            query=query,
            limit=DOCUMENTATION_RESULT_LIMIT,
            min_score=EMBEDDING_MIN_SCORE,
            prefix=prefix,
            search_profile=search_profile,
            conn=conn,
        )
    )
    results: ChannelResults = [
        (score, _documentation_symbol(documentation)) for score, documentation in rows
    ]
    results.sort(key=_scored_symbol_sort_key)
    if hasattr(rows, "search_result") and hasattr(rows, "resolved"):
        resolved_by_score = {
            (item.candidate.score, item.candidate.stable_id): item
            for item in rows.resolved
        }
        aligned = [
            resolved_by_score[(score, documentation[0])]
            for score, documentation in rows
        ]
        by_symbol = {
            _documentation_symbol(documentation): resolved_item
            for (_, documentation), resolved_item in zip(rows, aligned, strict=True)
        }
        return SimilarityContextResults(
            rows.search_result,
            tuple(by_symbol[symbol] for _score, symbol in results),
            results,
        )
    return results


def _channel_registry() -> dict[ChannelName, QueryChannelSpec]:
    """
    Return query-channel specs keyed by channel name.

    Parameters
    ----------
    None

    Returns
    -------
    dict[codira.types.ChannelName, codira.query.producers.QueryChannelSpec]
        Mapping from channel names to retrieval functions and producer metadata.
    """
    return {
        "symbol": QueryChannelSpec(
            name="symbol",
            retrieve=_retrieve_symbol_candidates,
            producer=CHANNEL_PRODUCER_SPECS["symbol"],
        ),
        "embedding": QueryChannelSpec(
            name="embedding",
            retrieve=_retrieve_embedding_candidates,
            producer=CHANNEL_PRODUCER_SPECS["embedding"],
        ),
        "test": QueryChannelSpec(
            name="test",
            retrieve=_retrieve_test_candidates,
            producer=CHANNEL_PRODUCER_SPECS["test"],
        ),
        "script": QueryChannelSpec(
            name="script",
            retrieve=_retrieve_script_candidates,
            producer=CHANNEL_PRODUCER_SPECS["script"],
        ),
        "semantic": QueryChannelSpec(
            name="semantic",
            retrieve=_retrieve_semantic_candidates,
            producer=CHANNEL_PRODUCER_SPECS["semantic"],
        ),
        "docs": QueryChannelSpec(
            name="docs",
            retrieve=_retrieve_documentation_candidates,
            producer=CHANNEL_PRODUCER_SPECS["docs"],
        ),
    }
