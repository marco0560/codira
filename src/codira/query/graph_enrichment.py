"""Graph enrichment helpers for bounded query-context expansion.

Responsibilities
----------------
- Expand top-ranked symbols through stored call, callable-reference, and include-graph relations.
- Emit normalized graph retrieval signals through native enrichment producers.
- Preserve deterministic expansion diagnostics without owning final context rendering.

Design principles
-----------------
Graph enrichment stays bounded, callback-driven, and side-effect free outside the explicit expansion buffers passed in by the caller.

Architectural role
------------------
This module belongs to the **graph enrichment layer** that sits between exact graph lookups and context rendering.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, cast

from codira.query.exact import (
    EdgeQueryRequest,
    find_call_edges,
    find_callable_refs,
    find_include_edges,
    find_logical_symbols,
    logical_symbol_name,
)
from codira.query.producers import (
    CALL_GRAPH_RETRIEVAL_PRODUCER,
    INCLUDE_GRAPH_RETRIEVAL_PRODUCER,
    REFERENCE_RETRIEVAL_PRODUCER,
    GraphRetrievalProducer,
)

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Callable

    from codira.query.signals import RetrievalSignal
    from codira.types import IncludeEdgeRow, SymbolRow


@dataclass(frozen=True)
class IncludeGraphNeighborRequest:
    """
    Request parameters for include-graph neighbor expansion.

    Parameters
    ----------
    root : pathlib.Path
        Repository root containing the index database.
    symbol : codira.types.SymbolRow
        Seed symbol whose owning module should be expanded.
    conn : sqlite3.Connection
        Open database connection reused for exact graph lookups.
    prefix : str | None
        Absolute normalized prefix used to restrict owner files and symbols.
    graph_signals : list[codira.query.signals.RetrievalSignal] | None
        Mutable signal buffer that receives include-proximity evidence.
    classify_file_language : collections.abc.Callable[[str], str]
        Callback classifying one indexed file into a language family.
    include_target_module_name : collections.abc.Callable[[str, str], str | None]
        Callback resolving local include targets back to indexed module names.
    symbols_in_module : collections.abc.Callable[[pathlib.Path, str], list[codira.types.SymbolRow]]
        Callback retrieving indexed symbols for one module.
    """

    root: Path
    symbol: SymbolRow
    conn: sqlite3.Connection
    prefix: str | None
    graph_signals: list[RetrievalSignal] | None
    classify_file_language: Callable[[str], str]
    include_target_module_name: Callable[[str, str], str | None]
    symbols_in_module: Callable[[Path, str], list[SymbolRow]]


@dataclass(frozen=True)
class GraphExpansionRequest:
    """
    Request parameters for graph-related symbol expansion.

    Parameters
    ----------
    root : pathlib.Path
        Repository root containing the index database.
    top_matches : list[codira.types.SymbolRow]
        Primary ranked symbols for the query.
    conn : sqlite3.Connection
        Open database connection reused for exact graph lookups.
    include_include_graph : bool
        Whether include-graph expansion is enabled.
    include_references : bool
        Whether callable-reference expansion is enabled.
    prefix : str | None
        Absolute normalized prefix used to restrict owner files and symbols.
    expanded : list[codira.types.SymbolRow]
        Pending expanded symbols collected for the query.
    seen_symbols : set[codira.types.SymbolRow]
        Symbols already admitted to the expanded result set.
    graph_signals : list[codira.query.signals.RetrievalSignal] | None
        Mutable signal buffer that receives normalized graph evidence.
    classify_file_language : collections.abc.Callable[[str], str]
        Callback classifying one indexed file into a language family.
    classify_file_role : collections.abc.Callable[[str, str], str]
        Callback classifying one indexed file into a retrieval role.
    include_target_module_name : collections.abc.Callable[[str, str], str | None]
        Callback resolving local include targets back to indexed module names.
    symbols_in_module : collections.abc.Callable[[pathlib.Path, str], list[codira.types.SymbolRow]]
        Callback retrieving indexed symbols for one module.
    """

    root: Path
    top_matches: list[SymbolRow]
    conn: sqlite3.Connection
    include_include_graph: bool
    include_references: bool
    prefix: str | None
    expanded: list[SymbolRow]
    seen_symbols: set[SymbolRow]
    graph_signals: list[RetrievalSignal] | None
    classify_file_language: Callable[[str], str]
    classify_file_role: Callable[[str, str], str]
    include_target_module_name: Callable[[str, str], str | None]
    symbols_in_module: Callable[[Path, str], list[SymbolRow]]


@dataclass(frozen=True)
class ResolvedEdgeExpansionRequest:
    """
    Request parameters for resolved edge expansion.

    Parameters
    ----------
    edges : list[tuple[str, str, str | None, str | None, int]]
        Stored graph edge rows to expand.
    graph_request : GraphExpansionRequest
        Graph expansion request carrying storage and signal buffers.
    source_symbol : codira.types.SymbolRow
        Seed symbol that produced the edges.
    module_index : int
        Edge tuple index containing the related module.
    name_index : int
        Edge tuple index containing the related logical name.
    producer : codira.query.producers.GraphRetrievalProducer
        Retrieval producer used to build relation signals.
    add_related : collections.abc.Callable[[codira.types.SymbolRow], None]
        Callback admitting symbols into the expanded result set.
    """

    edges: list[tuple[str, str, str | None, str | None, int]]
    graph_request: GraphExpansionRequest
    source_symbol: SymbolRow
    module_index: int
    name_index: int
    producer: GraphRetrievalProducer
    add_related: Callable[[SymbolRow], None]


def _expand_include_graph_neighbors(
    request: IncludeGraphNeighborRequest,
) -> tuple[list[SymbolRow], list[dict[str, object]]]:
    """
    Expand one symbol through direct local C include relationships.

    Parameters
    ----------
    request : IncludeGraphNeighborRequest
        Include-graph neighbor expansion request.

    Returns
    -------
    tuple[list[codira.types.SymbolRow], list[dict[str, object]]]
        Related symbols discovered through direct include edges plus
        deterministic include-expansion diagnostics.
    """
    symbol = request.symbol
    module_name = symbol[1]
    if request.classify_file_language(symbol[3]) != "c":
        return [], []

    related: list[SymbolRow] = []
    seen: set[tuple[str, str]] = set()
    diagnostics: list[dict[str, object]] = []

    def append_symbols(
        target_module: str,
        *,
        via_module: str,
        target_name: str,
        kind: str,
        direction: str,
    ) -> None:
        for candidate in request.symbols_in_module(request.root, target_module):
            key = (candidate[1], candidate[2])
            if key in seen:
                continue
            seen.add(key)
            related.append(candidate)
            diagnostics.append(
                {
                    "seed_module": module_name,
                    "via_module": via_module,
                    "target_name": target_name,
                    "kind": kind,
                    "direction": direction,
                    "expanded_module": candidate[1],
                    "expanded_name": candidate[2],
                }
            )
            if request.graph_signals is not None:
                request.graph_signals.append(
                    INCLUDE_GRAPH_RETRIEVAL_PRODUCER.build_signal(
                        kind="proximity",
                        target=candidate,
                        source_symbol=symbol,
                        distance=1,
                    )
                )

    pending_modules: list[str] = [module_name]
    visited_modules: set[str] = set()

    while pending_modules:
        current_module = pending_modules.pop(0)
        if current_module in visited_modules:
            continue
        visited_modules.add(current_module)

        outgoing_edges: list[IncludeEdgeRow] = find_include_edges(
            EdgeQueryRequest(
                root=request.root,
                name=current_module,
                prefix=request.prefix,
                conn=request.conn,
            )
        )
        for _owner_module, target_name, kind, _lineno in outgoing_edges:
            target_module = request.include_target_module_name(target_name, kind)
            if target_module is None:
                continue
            append_symbols(
                target_module,
                via_module=current_module,
                target_name=target_name,
                kind=kind,
                direction="outgoing",
            )
            if target_module not in visited_modules:
                pending_modules.append(target_module)

    current_module_path = Path(*module_name.split("."))
    current_target_name = f"{current_module_path.name}.h"
    if len(current_module_path.parts) > 1:
        current_target_name = str(
            Path(*current_module_path.parts[:-1]) / current_target_name
        )

    incoming_edges: list[IncludeEdgeRow] = find_include_edges(
        EdgeQueryRequest(
            root=request.root,
            name=current_target_name,
            incoming=True,
            prefix=request.prefix,
            conn=request.conn,
        )
    )
    for owner_module, _target_name, _kind, _lineno in incoming_edges:
        append_symbols(
            owner_module,
            via_module=owner_module,
            target_name=current_target_name,
            kind="include_local",
            direction="incoming",
        )

    return related, diagnostics


def _add_related_symbol(
    expanded: list[SymbolRow],
    seen_symbols: set[SymbolRow],
    symbol: SymbolRow,
    *,
    classify_file_role: Callable[[str, str], str],
) -> None:
    """
    Add one related symbol when it survives expansion filters.

    Parameters
    ----------
    expanded : list[codira.types.SymbolRow]
        Pending expanded symbols collected for the query.
    seen_symbols : set[codira.types.SymbolRow]
        Symbols already admitted to the expanded result set.
    symbol : codira.types.SymbolRow
        Candidate related symbol discovered during expansion.
    classify_file_role : collections.abc.Callable[[str, str], str]
        Callback classifying one indexed file into a retrieval role.

    Returns
    -------
    None
        The symbol is appended in place when it passes all filters.
    """
    symbol_type, module_name, name, _file_path, _lineno = symbol
    if symbol in seen_symbols:
        return
    if name.startswith("_"):
        return
    role = classify_file_role(symbol[3], module_name)
    if symbol_type == "module" and role in {"test", "tooling"}:
        return
    if role in {"test", "tooling"}:
        return
    seen_symbols.add(symbol)
    expanded.append(symbol)


def _expand_resolved_edges(request: ResolvedEdgeExpansionRequest) -> None:
    """
    Expand resolved graph edges into related symbols and retrieval signals.

    Parameters
    ----------
    request : ResolvedEdgeExpansionRequest
        Resolved edge expansion request.

    Returns
    -------
    None
        Related symbols and optional graph signals are appended in place.
    """
    graph_request = request.graph_request
    for edge in request.edges:
        resolved = bool(edge[4])
        related_module = cast("str | None", edge[request.module_index])
        related_name = cast("str | None", edge[request.name_index])
        if not resolved or related_module is None or related_name is None:
            continue
        for related in find_logical_symbols(
            graph_request.root,
            related_module,
            related_name,
            prefix=graph_request.prefix,
            conn=graph_request.conn,
        ):
            request.add_related(related)
            if graph_request.graph_signals is not None:
                graph_request.graph_signals.append(
                    request.producer.build_signal(
                        kind="relation",
                        target=related,
                        source_symbol=request.source_symbol,
                        distance=1,
                    )
                )


def _expand_call_relations(
    request: GraphExpansionRequest,
    symbol: SymbolRow,
    logical_name: str,
    module_name: str,
    add_related: Callable[[SymbolRow], None],
) -> None:
    """
    Expand call-graph relations for one seed symbol.

    Parameters
    ----------
    request : GraphExpansionRequest
        Graph expansion request carrying storage and signal buffers.
    symbol : codira.types.SymbolRow
        Seed symbol being expanded.
    logical_name : str
        Logical graph identity of the seed symbol.
    module_name : str
        Module owning the seed symbol.
    add_related : collections.abc.Callable[[codira.types.SymbolRow], None]
        Callback admitting symbols into the expanded result set.

    Returns
    -------
    None
        Related call-graph symbols are appended in place.
    """
    outgoing_edges = find_call_edges(
        EdgeQueryRequest(
            root=request.root,
            name=logical_name,
            module=module_name,
            prefix=request.prefix,
            conn=request.conn,
        )
    )
    incoming_edges = find_call_edges(
        EdgeQueryRequest(
            root=request.root,
            name=logical_name,
            module=module_name,
            incoming=True,
            prefix=request.prefix,
            conn=request.conn,
        )
    )
    _expand_resolved_edges(
        ResolvedEdgeExpansionRequest(
            edges=outgoing_edges,
            graph_request=request,
            source_symbol=symbol,
            module_index=2,
            name_index=3,
            producer=CALL_GRAPH_RETRIEVAL_PRODUCER,
            add_related=add_related,
        )
    )
    _expand_resolved_edges(
        ResolvedEdgeExpansionRequest(
            edges=incoming_edges,
            graph_request=request,
            source_symbol=symbol,
            module_index=0,
            name_index=1,
            producer=CALL_GRAPH_RETRIEVAL_PRODUCER,
            add_related=add_related,
        )
    )


def _expand_reference_relations(
    request: GraphExpansionRequest,
    symbol: SymbolRow,
    logical_name: str,
    module_name: str,
    add_related: Callable[[SymbolRow], None],
) -> None:
    """
    Expand callable-reference relations for one seed symbol.

    Parameters
    ----------
    request : GraphExpansionRequest
        Graph expansion request carrying storage and signal buffers.
    symbol : codira.types.SymbolRow
        Seed symbol being expanded.
    logical_name : str
        Logical graph identity of the seed symbol.
    module_name : str
        Module owning the seed symbol.
    add_related : collections.abc.Callable[[codira.types.SymbolRow], None]
        Callback admitting symbols into the expanded result set.

    Returns
    -------
    None
        Related callable-reference symbols are appended in place.
    """
    if not request.include_references:
        return
    outgoing_refs = find_callable_refs(
        EdgeQueryRequest(
            root=request.root,
            name=logical_name,
            module=module_name,
            prefix=request.prefix,
            conn=request.conn,
        )
    )
    incoming_refs = find_callable_refs(
        EdgeQueryRequest(
            root=request.root,
            name=logical_name,
            module=module_name,
            incoming=True,
            prefix=request.prefix,
            conn=request.conn,
        )
    )
    _expand_resolved_edges(
        ResolvedEdgeExpansionRequest(
            edges=outgoing_refs,
            graph_request=request,
            source_symbol=symbol,
            module_index=2,
            name_index=3,
            producer=REFERENCE_RETRIEVAL_PRODUCER,
            add_related=add_related,
        )
    )
    _expand_resolved_edges(
        ResolvedEdgeExpansionRequest(
            edges=incoming_refs,
            graph_request=request,
            source_symbol=symbol,
            module_index=0,
            name_index=1,
            producer=REFERENCE_RETRIEVAL_PRODUCER,
            add_related=add_related,
        )
    )


def expand_graph_related_symbols(
    request: GraphExpansionRequest,
) -> list[dict[str, object]]:
    """
    Expand top matches through include, call, and callable-reference graphs.

    Parameters
    ----------
    request : GraphExpansionRequest
        Graph expansion request carrying seed symbols and expansion buffers.

    Returns
    -------
    list[dict[str, object]]
        Deterministic include-graph diagnostics collected during expansion.
    """
    include_expansion: list[dict[str, object]] = []

    def add_related(symbol: SymbolRow) -> None:
        _add_related_symbol(
            request.expanded,
            request.seen_symbols,
            symbol,
            classify_file_role=request.classify_file_role,
        )

    for symbol in request.top_matches:
        if request.include_include_graph:
            include_related, include_entries = _expand_include_graph_neighbors(
                IncludeGraphNeighborRequest(
                    root=request.root,
                    symbol=symbol,
                    conn=request.conn,
                    prefix=request.prefix,
                    graph_signals=request.graph_signals,
                    classify_file_language=request.classify_file_language,
                    include_target_module_name=request.include_target_module_name,
                    symbols_in_module=request.symbols_in_module,
                )
            )
            for related in include_related:
                add_related(related)
            include_expansion.extend(include_entries)

        symbol_type, module_name, _name, _file_path, _lineno = symbol
        if symbol_type not in {"function", "method"}:
            continue

        logical_name = logical_symbol_name(request.root, symbol, conn=request.conn)
        _expand_call_relations(request, symbol, logical_name, module_name, add_related)
        _expand_reference_relations(
            request,
            symbol,
            logical_name,
            module_name,
            add_related,
        )

    return include_expansion
