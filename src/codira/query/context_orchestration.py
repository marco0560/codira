"""Focused context-query responsibility module."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from codira.config import with_effective_config_cache
from codira.prefix import normalize_prefix
from codira.query.classifier import build_retrieval_plan, classify_query
from codira.query.context_channels import (
    _build_channel_bundles,
    _channel_retrieval_producers,
    _collect_graph_retrieval_signals,
    _collect_overload_retrieval_signals,
    _collect_retrieval_signals,
    _get_channel_functions,
    _producer_diagnostics,
    _query_prefers_overload_evidence,
    _signal_collection_diagnostics,
    _signal_preview,
    _signal_summary_by_symbol,
)
from codira.query.context_expansion import (
    _channel_priority,
    _collect_doc_issues_and_related,
    _enabled_channels,
    _expand_and_collect_references,
    _is_issue_query,
    _issue_driven_symbols,
)
from codira.query.context_models import (
    MAX_ISSUES,
    ChannelBundleRequest,
    ContextExecutionState,
    ContextRenderRequest,
    ContextRequest,
    ExpansionCollectionRequest,
    GraphRetrievalRequest,
)
from codira.query.context_render import (
    _render_context,
)
from codira.query.context_scoring import (
    _diversify_merged_symbols,
    _diversify_merged_symbols_explain,
    _is_documentation_symbol,
    _rank_signals_with_provenance,
)
from codira.query.context_source import (
    _tokenize,
)
from codira.query.producers import selected_enrichment_producers
from codira.query.signals import signal_sort_key
from codira.registry import active_index_backend, with_active_plugin_instance_cache

if TYPE_CHECKING:
    from pathlib import Path

    from codira.contracts import BackendQueryConnection
    from codira.types import ChannelName, SymbolRow


def _initial_context_state(
    request: ContextRequest,
    conn: BackendQueryConnection,
) -> ContextExecutionState:
    """
    Build the initial retrieval state from channel execution.

    Parameters
    ----------
    request : ContextRequest
        End-to-end context retrieval request.
    conn : object
        Open backend connection used for query execution.

    Returns
    -------
    ContextExecutionState
        Initial retrieval state after channel execution and first ranking pass.
    """
    normalized_prefix = normalize_prefix(request.root, request.prefix)
    intent = classify_query(request.query)
    plan = build_retrieval_plan(intent)
    bundles = _build_channel_bundles(
        ChannelBundleRequest(
            root=request.root,
            query=request.query,
            conn=conn,
            intent=intent,
            plan=plan,
            prefix=normalized_prefix,
            search_profile=request.search_profile,
        )
    )
    ordered_channels: list[ChannelName] | None = [
        name for name, _channel in _get_channel_functions(plan)
    ]
    channel_producers = _channel_retrieval_producers(ordered_channels)
    include_overloads = _query_prefers_overload_evidence(request.query, intent=intent)

    if request.explain:
        enabled = _enabled_channels(plan)
        priority = _channel_priority(plan)
        retrieval_producers = channel_producers + selected_enrichment_producers(
            include_issue_annotations=(
                _is_issue_query(request.query) or plan.include_doc_issues
            ),
            include_references=plan.include_references,
            include_include_graph=plan.include_include_graph,
            include_overloads=include_overloads,
        )
        producer_diagnostics = _producer_diagnostics(retrieval_producers)
        retrieval_signals, signal_collection = _collect_retrieval_signals(
            bundles,
            producers=retrieval_producers,
        )
    else:
        enabled = None
        priority = None
        producer_diagnostics = None
        retrieval_signals, signal_collection = _collect_retrieval_signals(
            bundles,
            producers=channel_producers,
        )
    overload_retrieval_signals = _collect_overload_retrieval_signals(
        root=request.root,
        query=request.query,
        intent=intent,
        conn=conn,
        candidate_signals=retrieval_signals,
    )
    if overload_retrieval_signals:
        retrieval_signals = sorted(
            [*retrieval_signals, *overload_retrieval_signals],
            key=signal_sort_key,
        )

    ranked_merged, provenance = _rank_signals_with_provenance(
        retrieval_signals,
        intent=intent,
    )
    if request.explain:
        top_matches, diversity = _diversify_merged_symbols_explain(
            [symbol for symbol, _score in ranked_merged],
            intent=intent,
        )
    else:
        top_matches = _diversify_merged_symbols(
            [symbol for symbol, _score in ranked_merged],
            intent=intent,
        )
        diversity = None
        ordered_channels = None

    return ContextExecutionState(
        normalized_prefix=normalized_prefix,
        intent=intent,
        plan=plan,
        bundles=bundles,
        ordered_channels=ordered_channels,
        enabled=enabled,
        priority=priority,
        producer_diagnostics=producer_diagnostics,
        signal_collection=signal_collection,
        retrieval_signals=retrieval_signals,
        provenance=provenance,
        top_matches=top_matches[:10],
        diversity=diversity,
    )


def _append_issue_driven_matches(
    request: ContextRequest,
    state: ContextExecutionState,
    conn: BackendQueryConnection,
) -> None:
    """
    Append issue-driven symbols to the current top-match list.

    Parameters
    ----------
    request : ContextRequest
        End-to-end context retrieval request.
    state : ContextExecutionState
        Mutable retrieval state.
    conn : object
        Open backend connection used for query execution.

    Returns
    -------
    None
        Issue-driven symbols are appended to ``state.top_matches`` in place.
    """
    if not _is_issue_query(request.query):
        return
    for symbol in _issue_driven_symbols(
        request.root,
        request.query,
        conn,
        prefix=state.normalized_prefix,
    ):
        if symbol not in state.top_matches:
            state.top_matches.append(symbol)
    state.top_matches = state.top_matches[:10]


def _filter_redundant_module_matches(
    top_matches: list[SymbolRow],
) -> list[SymbolRow]:
    """
    Remove module rows duplicated by more specific symbol matches.

    Parameters
    ----------
    top_matches : list[codira.types.SymbolRow]
        Current ranked symbol winners.

    Returns
    -------
    list[codira.types.SymbolRow]
        Filtered ranked symbols with redundant module rows removed.
    """
    modules_with_functions = {
        module_name
        for symbol_type, module_name, _name, _file_path, _lineno in top_matches
        if symbol_type not in {"module", "documentation"}
    }
    return [
        symbol
        for symbol in top_matches
        if not (symbol[0] == "module" and symbol[1] in modules_with_functions)
    ]


def _empty_context_result(
    request: ContextRequest,
    state: ContextExecutionState,
) -> str:
    """
    Render the empty-result response for one context query.

    Parameters
    ----------
    request : ContextRequest
        End-to-end context retrieval request.
    state : ContextExecutionState
        Mutable retrieval state.

    Returns
    -------
    str
        Empty-result context payload in the requested output mode.
    """
    if request.as_json or request.as_prompt:
        return _render_context(
            ContextRenderRequest(
                root=request.root,
                query=request.query,
                top_matches=[],
                doc_issues=[],
                expanded=[],
                unique_refs=[],
                as_json=request.as_json,
                as_prompt=request.as_prompt,
                explain=request.explain,
                plan=state.plan,
                producers=state.producer_diagnostics,
                signal_collection=state.signal_collection,
                signal_preview=state.signal_preview,
                signal_merge=state.signal_merge,
                diversity=state.diversity,
                expansion=state.expansion,
            )
        )
    return "No relevant matches found."


def _apply_graph_signal_rerank(
    state: ContextExecutionState,
    conn: BackendQueryConnection,
    root: Path,
) -> None:
    """
    Collect graph signals and rerank top matches when graph evidence exists.

    Parameters
    ----------
    state : ContextExecutionState
        Mutable retrieval state.
    conn : object
        Open backend connection used for graph lookups.
    root : pathlib.Path
        Repository root containing the index.

    Returns
    -------
    None
        ``state.top_matches``, ``state.retrieval_signals``, ``state.provenance``,
        and optional diversity diagnostics are updated in place.
    """
    graph_retrieval_signals = _collect_graph_retrieval_signals(
        GraphRetrievalRequest(
            root=root,
            top_matches=[
                symbol
                for symbol in state.top_matches
                if not _is_documentation_symbol(symbol)
            ],
            conn=conn,
            include_include_graph=state.plan.include_include_graph,
            include_references=state.plan.include_references,
            prefix=state.normalized_prefix,
        )
    )
    if not graph_retrieval_signals:
        return
    state.retrieval_signals = sorted(
        [*state.retrieval_signals, *graph_retrieval_signals],
        key=signal_sort_key,
    )
    ranked_merged, state.provenance = _rank_signals_with_provenance(
        state.retrieval_signals,
        intent=state.intent,
    )
    if state.enabled is not None:
        state.top_matches, state.diversity = _diversify_merged_symbols_explain(
            [symbol for symbol, _score in ranked_merged],
            intent=state.intent,
        )
    else:
        state.top_matches = _diversify_merged_symbols(
            [symbol for symbol, _score in ranked_merged],
            intent=state.intent,
        )


def _confidence_map_for_matches(
    query: str,
    top_matches: list[SymbolRow],
) -> dict[SymbolRow, float]:
    """
    Build lightweight deterministic confidence estimates for top matches.

    Parameters
    ----------
    query : str
        Original user query.
    top_matches : list[codira.types.SymbolRow]
        Current ranked symbol winners.

    Returns
    -------
    dict[codira.types.SymbolRow, float]
        Confidence values keyed by symbol.
    """
    confidence_map: dict[SymbolRow, float] = {}
    query_tokens = list(_tokenize(query))

    for rank, symbol in enumerate(top_matches):
        base = 1.0 - (rank / max(len(top_matches), 1))
        overlap = sum(1 for token in query_tokens if token in symbol[2].lower())
        confidence_map[symbol] = min(base + (0.1 * overlap), 1.0)

    return confidence_map


def _finalize_signal_diagnostics(
    state: ContextExecutionState,
) -> None:
    """
    Finalize explain-mode signal diagnostics after all retrieval stages.

    Parameters
    ----------
    state : ContextExecutionState
        Mutable retrieval state.

    Returns
    -------
    None
        Explain-mode signal diagnostics are updated in place.
    """
    if state.signal_collection is None:
        return
    used_producers = list(cast("list[str]", state.signal_collection["used_producers"]))
    ignored_producers = list(
        cast("list[str]", state.signal_collection["ignored_producers"])
    )
    used_set = set(used_producers)
    ignored_set = set(ignored_producers)
    active_signal_producers = sorted(
        {signal.producer_name for signal in state.retrieval_signals}
    )
    for producer_name in active_signal_producers:
        used_set.add(producer_name)
        ignored_set.discard(producer_name)
    state.signal_collection = _signal_collection_diagnostics(
        sorted(state.retrieval_signals, key=signal_sort_key),
        used_producers=sorted(used_set),
        ignored_producers=sorted(ignored_set),
    )
    state.signal_preview = _signal_preview(state.retrieval_signals)
    state.signal_merge = _signal_summary_by_symbol(
        state.retrieval_signals,
        state.top_matches,
    )


@with_effective_config_cache
@with_active_plugin_instance_cache
def context_for(
    request: ContextRequest,
) -> str:
    """
    Build a structured context block for a given query.

    Parameters
    ----------
    request : ContextRequest
        End-to-end context retrieval request.

    Returns
    -------
    str
        Structured text block containing:
        - top symbol matches
        - related docstring issues
        - enriched code context
        - module expansion
        - cross-module references

    Notes
    -----
    The output is optimized for LLM consumption and follows a
    deterministic section-based layout. Query classification is
    performed before retrieval and passed into the scoring phase.

    Raises
    ------
    codira.contracts.BackendError
        If the active backend cannot open or query the repository index.
    """
    conn = request.conn or cast(
        "BackendQueryConnection",
        active_index_backend(root=request.root).open_connection(request.root),
    )
    owns_connection = request.conn is None
    try:
        state = _initial_context_state(request, conn)
        _append_issue_driven_matches(request, state, conn)
        state.top_matches = _filter_redundant_module_matches(state.top_matches)

        if not state.top_matches:
            return _empty_context_result(request, state)

        _apply_graph_signal_rerank(state, conn, request.root)
        confidence_map = _confidence_map_for_matches(
            request.query,
            state.top_matches,
        )

        if state.plan.include_doc_issues:
            doc_issues, related_symbols = _collect_doc_issues_and_related(
                request.root,
                request.query,
                state.top_matches,
                conn,
                prefix=state.normalized_prefix,
            )
        else:
            doc_issues, related_symbols = [], []

        doc_issues = doc_issues[:MAX_ISSUES]
        for match in related_symbols:
            if match not in state.top_matches:
                state.top_matches.append(match)
        state.top_matches = state.top_matches[:10]

        expanded, unique_refs, state.expansion = _expand_and_collect_references(
            ExpansionCollectionRequest(
                root=request.root,
                top_matches=state.top_matches,
                conn=conn,
                include_include_graph=state.plan.include_include_graph,
                include_references=state.plan.include_references,
                prefix=state.normalized_prefix,
            )
        )

        if request.explain:
            _finalize_signal_diagnostics(state)

        return _render_context(
            ContextRenderRequest(
                root=request.root,
                query=request.query,
                top_matches=state.top_matches,
                doc_issues=doc_issues,
                expanded=expanded,
                unique_refs=unique_refs,
                confidence_map=confidence_map,
                as_json=request.as_json,
                as_prompt=request.as_prompt,
                explain=request.explain,
                intent=state.intent,
                plan=state.plan,
                enabled_channels=state.enabled,
                channel_priority=state.priority,
                ordered_channels=state.ordered_channels,
                producers=state.producer_diagnostics,
                signal_collection=state.signal_collection,
                signal_preview=state.signal_preview,
                signal_merge=state.signal_merge,
                bundles=state.bundles if request.explain else None,
                provenance=state.provenance if request.explain else None,
                diversity=state.diversity if request.explain else None,
                expansion=state.expansion if request.explain else None,
                max_source_file_bytes=request.max_source_file_bytes,
            )
        )
    finally:
        if owns_connection:
            conn.close()
