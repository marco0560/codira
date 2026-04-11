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

from pathlib import Path
from typing import TYPE_CHECKING

from codira.query.exact import (
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
)

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Callable

    from codira.query.signals import RetrievalSignal
    from codira.types import IncludeEdgeRow, SymbolRow


def _expand_include_graph_neighbors(
    root: Path,
    symbol: SymbolRow,
    conn: sqlite3.Connection,
    *,
    prefix: str | None,
    graph_signals: list[RetrievalSignal] | None,
    classify_file_language: Callable[[str], str],
    include_target_module_name: Callable[[str, str], str | None],
    symbols_in_module: Callable[[Path, str], list[SymbolRow]],
) -> tuple[list[SymbolRow], list[dict[str, object]]]:
    """
    Expand one symbol through direct local C include relationships.

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
        Mutable signal buffer that receives normalized include-proximity
        evidence when supplied.
    classify_file_language : collections.abc.Callable[[str], str]
        Callback classifying one indexed file into a language family.
    include_target_module_name : collections.abc.Callable[[str, str], str | None]
        Callback resolving local include targets back to indexed module names.
    symbols_in_module : collections.abc.Callable[[pathlib.Path, str], list[codira.types.SymbolRow]]
        Callback retrieving indexed symbols for one module.

    Returns
    -------
    tuple[list[codira.types.SymbolRow], list[dict[str, object]]]
        Related symbols discovered through direct include edges plus
        deterministic include-expansion diagnostics.
    """
    module_name = symbol[1]
    if classify_file_language(symbol[3]) != "c":
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
        for candidate in symbols_in_module(root, target_module):
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
            if graph_signals is not None:
                graph_signals.append(
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
            root,
            current_module,
            prefix=prefix,
            conn=conn,
        )
        for _owner_module, target_name, kind, _lineno in outgoing_edges:
            target_module = include_target_module_name(target_name, kind)
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
        root,
        current_target_name,
        incoming=True,
        prefix=prefix,
        conn=conn,
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


def expand_graph_related_symbols(
    root: Path,
    top_matches: list[SymbolRow],
    conn: sqlite3.Connection,
    *,
    include_include_graph: bool,
    include_references: bool,
    prefix: str | None,
    expanded: list[SymbolRow],
    seen_symbols: set[SymbolRow],
    graph_signals: list[RetrievalSignal] | None = None,
    classify_file_language: Callable[[str], str],
    classify_file_role: Callable[[str, str], str],
    include_target_module_name: Callable[[str, str], str | None],
    symbols_in_module: Callable[[Path, str], list[SymbolRow]],
) -> list[dict[str, object]]:
    """
    Expand top matches through include, call, and callable-reference graphs.

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
    graph_signals : list[codira.query.signals.RetrievalSignal] | None, optional
        Mutable signal buffer that receives normalized graph evidence when
        supplied.
    classify_file_language : collections.abc.Callable[[str], str]
        Callback classifying one indexed file into a language family.
    classify_file_role : collections.abc.Callable[[str, str], str]
        Callback classifying one indexed file into a retrieval role.
    include_target_module_name : collections.abc.Callable[[str, str], str | None]
        Callback resolving local include targets back to indexed module names.
    symbols_in_module : collections.abc.Callable[[pathlib.Path, str], list[codira.types.SymbolRow]]
        Callback retrieving indexed symbols for one module.

    Returns
    -------
    list[dict[str, object]]
        Deterministic include-graph diagnostics collected during expansion.
    """
    include_expansion: list[dict[str, object]] = []

    def add_related(symbol: SymbolRow) -> None:
        _add_related_symbol(
            expanded,
            seen_symbols,
            symbol,
            classify_file_role=classify_file_role,
        )

    def module_symbols(module_name: str) -> list[SymbolRow]:
        return symbols_in_module(root, module_name)

    for symbol in top_matches:
        if include_include_graph:
            include_related, include_entries = _expand_include_graph_neighbors(
                root,
                symbol,
                conn,
                prefix=prefix,
                graph_signals=graph_signals,
                classify_file_language=classify_file_language,
                include_target_module_name=include_target_module_name,
                symbols_in_module=symbols_in_module,
            )
            for related in include_related:
                add_related(related)
            include_expansion.extend(include_entries)

        symbol_type, module_name, _name, _file_path, _lineno = symbol
        if symbol_type not in {"function", "method"}:
            continue

        logical_name = logical_symbol_name(root, symbol, conn=conn)
        outgoing_edges = find_call_edges(
            root,
            logical_name,
            module=module_name,
            prefix=prefix,
            conn=conn,
        )
        incoming_edges = find_call_edges(
            root,
            logical_name,
            module=module_name,
            incoming=True,
            prefix=prefix,
            conn=conn,
        )
        outgoing_refs = (
            find_callable_refs(
                root,
                logical_name,
                module=module_name,
                prefix=prefix,
                conn=conn,
            )
            if include_references
            else []
        )
        incoming_refs = (
            find_callable_refs(
                root,
                logical_name,
                module=module_name,
                incoming=True,
                prefix=prefix,
                conn=conn,
            )
            if include_references
            else []
        )

        for (
            _caller_module,
            _caller_name,
            callee_module,
            callee_name,
            resolved,
        ) in outgoing_edges:
            if not resolved or callee_module is None or callee_name is None:
                continue
            for related in find_logical_symbols(
                root,
                callee_module,
                callee_name,
                prefix=prefix,
                conn=conn,
            ):
                add_related(related)
                if graph_signals is not None:
                    graph_signals.append(
                        CALL_GRAPH_RETRIEVAL_PRODUCER.build_signal(
                            kind="relation",
                            target=related,
                            source_symbol=symbol,
                            distance=1,
                        )
                    )

        for (
            caller_module,
            caller_name,
            _callee_module,
            _callee_name,
            resolved,
        ) in incoming_edges:
            if not resolved:
                continue
            for related in find_logical_symbols(
                root,
                caller_module,
                caller_name,
                prefix=prefix,
                conn=conn,
            ):
                add_related(related)
                if graph_signals is not None:
                    graph_signals.append(
                        CALL_GRAPH_RETRIEVAL_PRODUCER.build_signal(
                            kind="relation",
                            target=related,
                            source_symbol=symbol,
                            distance=1,
                        )
                    )

        for (
            _owner_module,
            _owner_name,
            target_module,
            target_name,
            resolved,
        ) in outgoing_refs:
            if not resolved or target_module is None or target_name is None:
                continue
            for related in find_logical_symbols(
                root,
                target_module,
                target_name,
                prefix=prefix,
                conn=conn,
            ):
                add_related(related)
                if graph_signals is not None:
                    graph_signals.append(
                        REFERENCE_RETRIEVAL_PRODUCER.build_signal(
                            kind="relation",
                            target=related,
                            source_symbol=symbol,
                            distance=1,
                        )
                    )

        for (
            owner_module,
            owner_name,
            _target_module,
            _target_name,
            resolved,
        ) in incoming_refs:
            if not resolved:
                continue
            for related in find_logical_symbols(
                root,
                owner_module,
                owner_name,
                prefix=prefix,
                conn=conn,
            ):
                add_related(related)
                if graph_signals is not None:
                    graph_signals.append(
                        REFERENCE_RETRIEVAL_PRODUCER.build_signal(
                            kind="relation",
                            target=related,
                            source_symbol=symbol,
                            distance=1,
                        )
                    )

    return include_expansion
