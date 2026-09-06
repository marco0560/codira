"""Focused context-query responsibility module."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from codira.query.context_models import (
    ExpansionCollectionRequest,
    ExpansionDiagnostics,
    GraphRelatedExpansionRequest,
)
from codira.query.context_scoring import (
    _classify_file_language,
    _include_target_module_name,
    _is_documentation_symbol,
)
from codira.query.context_source import (
    _classify_file_role,
    _find_references,
    _symbols_in_module,
    _tokenize,
)
from codira.query.exact import (
    EdgeQueryRequest,
    docstring_issues,
    find_include_edges,
    find_symbol,
)
from codira.query.graph_enrichment import (
    GraphExpansionRequest,
    expand_graph_related_symbols,
)
from codira.query.producers import INCLUDE_GRAPH_RETRIEVAL_PRODUCER
from codira.registry import active_index_backend

if TYPE_CHECKING:
    from codira.contracts import BackendQueryConnection
    from codira.query.classifier import RetrievalPlan
    from codira.query.signals import RetrievalSignal
    from codira.types import ChannelName, IncludeEdgeRow, ReferenceRow, SymbolRow


def _enabled_channels(plan: RetrievalPlan) -> set[ChannelName]:
    """
    Return the set of channels enabled for an intent.

    Parameters
    ----------
    plan : codira.query.classifier.RetrievalPlan
        Deterministic retrieval plan.

    Returns
    -------
    set[codira.types.ChannelName]
        Enabled retrieval channels.
    """
    return set(plan.channels)


def _channel_priority(plan: RetrievalPlan) -> dict[ChannelName, int]:
    """
    Return channel priority values for an intent.

    Parameters
    ----------
    plan : codira.query.classifier.RetrievalPlan
        Deterministic retrieval plan.

    Returns
    -------
    dict[codira.types.ChannelName, int]
        Lower values indicate higher routing priority.
    """
    return {channel: index for index, channel in enumerate(plan.channels)}


def _is_issue_query(query: str) -> bool:
    """
    Check whether a query targets documentation issues.

    Parameters
    ----------
    query : str
        User query string.

    Returns
    -------
    bool
        ``True`` when the query mentions issue-oriented documentation terms.
    """
    query_tokens = _tokenize(query)
    issue_tokens = {
        "doc",
        "docstring",
        "docs",
        "issue",
        "issues",
        "missing",
        "numpy",
        "section",
        "returns",
        "parameters",
    }
    return any(token in issue_tokens for token in query_tokens)


def _issue_driven_symbols(
    root: Path,
    query: str,
    conn: BackendQueryConnection,
    *,
    prefix: str | None = None,
) -> list[SymbolRow]:
    """
    Rank symbols that are implicated by matching docstring issues.

    Parameters
    ----------
    root : pathlib.Path
        Repository root containing the index database.
    query : str
        User query string.
    conn : object
        Open database connection.
    prefix : str | None, optional
        Absolute normalized prefix used to restrict issue ownership and symbol
        files.

    Returns
    -------
    list[codira.types.SymbolRow]
        Small set of issue-related symbols ordered by heuristic score.
    """
    issue_rows = docstring_issues(root, prefix=prefix, conn=conn)
    query_tokens = _tokenize(query)
    scored: dict[SymbolRow, int] = {}

    GENERIC_NAMES = {"main", "__init__", "run"}

    for issue in issue_rows:
        issue_type = issue[0]
        message = issue[1]
        message_lower = message.lower()

        if not any(token in message_lower for token in query_tokens):
            continue

        head = message.split(":", 1)[0]

        # Extract symbol name deterministically
        symbol_name: str | None = None

        if head.startswith("Function "):
            symbol_name = head[len("Function ") :]

        elif head.startswith("Module "):
            symbol_name = head[len("Module ") :].split(".")[-1]

        elif head.startswith("Method "):
            parts = head[len("Method ") :].split(".")
            if len(parts) == 2:
                symbol_name = parts[1]

        if not symbol_name:
            continue

        if symbol_name in GENERIC_NAMES:
            continue

        for symbol in find_symbol(root, symbol_name, prefix=prefix, conn=conn):
            module_name = symbol[1]

            # Reject obvious noise
            role = _classify_file_role(symbol[3], module_name)
            if role in {"test", "tooling"} or module_name.startswith("."):
                continue

            bonus = 3 if issue_type == "missing" else 1

            if symbol in scored:
                scored[symbol] += bonus
            else:
                scored[symbol] = bonus

    ranked = sorted(
        scored,
        key=lambda symbol: (
            -scored[symbol],
            symbol[3],
            symbol[4],
            symbol[2],
        ),
    )

    return ranked[:5]


def _collect_doc_issues_and_related(
    root: Path,
    query: str,
    top_matches: list[SymbolRow],
    conn: BackendQueryConnection,
    *,
    prefix: str | None = None,
) -> tuple[list[tuple[str, str]], list[SymbolRow]]:
    """
    Collect related docstring issues and derive additional related symbols.

    Parameters
    ----------
    root : pathlib.Path
        Repository root containing the index database.
    query : str
        Original user query.
    top_matches : list[codira.types.SymbolRow]
        Primary ranked symbols for the query.
    conn : object
        Open database connection.
    prefix : str | None, optional
        Absolute normalized prefix used to restrict issue ownership and symbol
        files.

    Returns
    -------
    tuple[list[tuple[str, str]], list[codira.types.SymbolRow]]
        Related docstring issue rows and derived related symbols.
    """
    issue_rows_filtered: list[tuple[str, str]] = []

    symbol_names = {
        name
        for symbol_type, _module_name, name, _file_path, _lineno in top_matches
        if name and symbol_type != "documentation"
    }
    issue_rows = docstring_issues(
        root,
        prefix=prefix,
        symbol_names=tuple(sorted(symbol_names)),
        conn=conn,
    )

    for issue in issue_rows:
        issue_type = issue[0]
        message = issue[1]
        if not any(name in message for name in symbol_names):
            continue

        # --- FILTER NOISE: skip tests and scripts ---
        if "tests." in message or "scripts." in message:
            continue

        issue_rows_filtered.append((issue_type, message))

    doc_issues: list[tuple[str, str]] = issue_rows_filtered[:20]

    related_symbols: list[SymbolRow] = []

    for _, message in doc_issues:
        parts = message.split(":")[0].split()
        if len(parts) >= 2:
            symbol_name = parts[-1]
            related_symbols.extend(
                find_symbol(root, symbol_name, prefix=prefix, conn=conn)
            )

    return doc_issues, related_symbols


def _is_test_file(path: str) -> bool:
    """
    Check whether a path looks like a test file.

    Parameters
    ----------
    path : str
        File path to classify.

    Returns
    -------
    bool
        ``True`` when the path looks like a pytest-style test module.
    """
    return _classify_file_role(path, "") == "test"


def _dedupe_and_cap_references(
    refs: list[ReferenceRow],
    *,
    max_per_file: int = 3,
    min_line_gap: int = 5,
) -> list[ReferenceRow]:
    """
    Dedupe reference hits and cap density per file.

    Parameters
    ----------
    refs : list[codira.types.ReferenceRow]
        Raw reference hits to reduce.
    max_per_file : int, optional
        Maximum number of references retained per file.
    min_line_gap : int, optional
        Minimum spacing between retained references in the same file.

    Returns
    -------
    list[codira.types.ReferenceRow]
        Reduced reference hits ordered by file and line number.
    """
    # group by file
    by_file: dict[str, list[int]] = {}

    for file_path, lineno in refs:
        by_file.setdefault(file_path, []).append(lineno)

    result: list[ReferenceRow] = []

    for file_path in sorted(by_file):
        lines = sorted(by_file[file_path])

        kept: list[int] = []
        last_kept: int | None = None

        for ln in lines:
            if last_kept is None or abs(ln - last_kept) >= min_line_gap:
                kept.append(ln)
                last_kept = ln

            if len(kept) >= max_per_file:
                break

        for ln in kept:
            result.append((file_path, ln))

    return result


def _expand_include_graph_neighbors(
    root: Path,
    symbol: SymbolRow,
    conn: BackendQueryConnection,
    *,
    prefix: str | None,
    graph_signals: list[RetrievalSignal] | None = None,
) -> tuple[list[SymbolRow], list[dict[str, object]]]:
    """
    Expand one symbol through direct local C include relationships.

    Parameters
    ----------
    root : pathlib.Path
        Repository root containing the index database.
    symbol : codira.types.SymbolRow
        Seed symbol whose owning module should be expanded.
    conn : object
        Open database connection reused for exact graph lookups.
    prefix : str | None
        Absolute normalized prefix used to restrict owner files and symbols.
    graph_signals : list[codira.query.signals.RetrievalSignal] | None, optional
        Mutable signal buffer that receives normalized include-proximity
        evidence when supplied.

    Returns
    -------
    tuple[list[codira.types.SymbolRow], list[dict[str, object]]]
        Related symbols discovered through direct include edges plus
        deterministic include-expansion diagnostics.
    """
    module_name = symbol[1]
    file_language = _classify_file_language(symbol[3])
    if file_language != "c":
        return [], []

    related: list[SymbolRow] = []
    seen: set[tuple[str, str]] = set()
    diagnostics: list[dict[str, object]] = []

    def _append_symbols(
        target_module: str,
        *,
        via_module: str,
        target_name: str,
        kind: str,
        direction: str,
    ) -> None:
        for candidate in _symbols_in_module(root, target_module, prefix=prefix):
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
            EdgeQueryRequest(
                root=root,
                name=current_module,
                prefix=prefix,
                conn=conn,
            )
        )
        for _owner_module, target_name, kind, _lineno in outgoing_edges:
            target_module = _include_target_module_name(target_name, kind)
            if target_module is None:
                continue
            _append_symbols(
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
            root=root,
            name=current_target_name,
            incoming=True,
            prefix=prefix,
            conn=conn,
        )
    )
    for owner_module, _target_name, _kind, _lineno in incoming_edges:
        _append_symbols(
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
    role = _classify_file_role(symbol[3], module_name)
    if symbol_type == "module" and role in {"test", "tooling"}:
        return
    if role in {"test", "tooling"}:
        return
    seen_symbols.add(symbol)
    expanded.append(symbol)


def _expand_graph_related_symbols(
    request: GraphRelatedExpansionRequest,
) -> ExpansionDiagnostics:
    """
    Expand top matches through include, call, and callable-reference graphs.

    Parameters
    ----------
    request : GraphRelatedExpansionRequest
        Graph-expansion request carrying ranked matches, expansion toggles,
        prefix filtering, and mutable expansion buffers.

    Returns
    -------
    codira.query.context.ExpansionDiagnostics
        Deterministic seed-selection and include-graph diagnostics collected
        during graph expansion.
    """
    return expand_graph_related_symbols(
        GraphExpansionRequest(
            root=request.root,
            top_matches=request.top_matches,
            conn=request.conn,
            include_include_graph=request.include_include_graph,
            include_references=request.include_references,
            prefix=request.prefix,
            expanded=request.expanded,
            seen_symbols=request.seen_symbols,
            graph_signals=request.graph_signals,
            classify_file_language=_classify_file_language,
            classify_file_role=_classify_file_role,
            include_target_module_name=_include_target_module_name,
            symbols_in_module=lambda module_root, module_name: _symbols_in_module(
                module_root,
                module_name,
                prefix=request.prefix,
            ),
        )
    )


def _expand_module_related_symbols(
    root: Path,
    top_matches: list[SymbolRow],
    *,
    prefix: str | None,
    expanded: list[SymbolRow],
    seen_symbols: set[SymbolRow],
) -> None:
    """
    Expand top matches to other public symbols in the same modules.

    Parameters
    ----------
    root : pathlib.Path
        Repository root used for exact module lookups.
    top_matches : list[codira.types.SymbolRow]
        Primary ranked symbols for the query.
    prefix : str | None
        Absolute normalized prefix used to restrict module symbols.
    expanded : list[codira.types.SymbolRow]
        Pending expanded symbols collected for the query.
    seen_symbols : set[codira.types.SymbolRow]
        Symbols already admitted to the expanded result set.

    Returns
    -------
    None
        Related module-local symbols are appended in place.
    """
    seen_modules: set[str] = set()

    for symbol_type, module_name, _, _, _ in top_matches:
        if symbol_type == "documentation":
            continue
        if module_name in seen_modules:
            continue
        seen_modules.add(module_name)
        for symbol in _symbols_in_module(root, module_name, prefix=prefix):
            if symbol[2].startswith("_"):
                continue
            _add_related_symbol(expanded, seen_symbols, symbol)


def _finalize_expanded_symbols(expanded: list[SymbolRow]) -> list[SymbolRow]:
    """
    Dedupe expanded symbols by module and name and cap the final result.

    Parameters
    ----------
    expanded : list[codira.types.SymbolRow]
        Pending expanded symbols collected for the query.

    Returns
    -------
    list[codira.types.SymbolRow]
        Deduplicated and capped expanded symbols.
    """
    seen_keys: set[tuple[str, str]] = set()
    deduped: list[SymbolRow] = []

    for symbol_type, module_name, name, file_path, lineno in expanded:
        key = (module_name, name)
        if key in seen_keys:
            continue
        seen_keys.add(key)
        deduped.append((symbol_type, module_name, name, file_path, lineno))

    return deduped[:20]


def _collect_reference_rows(
    root: Path,
    top_matches: list[SymbolRow],
    *,
    include_references: bool,
    prefix: str | None,
    conn: BackendQueryConnection,
) -> list[ReferenceRow]:
    """
    Collect cross-module reference rows for the primary top matches.

    Parameters
    ----------
    root : pathlib.Path
        Repository root used for project-file scans.
    top_matches : list[codira.types.SymbolRow]
        Primary ranked symbols for the query.
    include_references : bool
        Whether reference collection is enabled.
    prefix : str | None
        Absolute normalized prefix used to restrict scanned files.
    conn : codira.contracts.BackendQueryConnection
        Existing backend connection reused for the batched reference lookup.

    Returns
    -------
    list[codira.types.ReferenceRow]
        Deduplicated and capped reference rows in deterministic order.
    """
    if not include_references:
        return []

    backend = active_index_backend(root=root)
    code_matches = [
        symbol for symbol in top_matches if not _is_documentation_symbol(symbol)
    ]
    symbol_names = tuple(sorted({name for _, _, name, _, _ in code_matches if name}))
    top_files = {file_path for _, _, _, file_path, _ in top_matches}
    test_refs: list[ReferenceRow] = []
    other_refs: list[ReferenceRow] = []

    stored_rows = backend.find_reference_rows_for_names(
        root,
        symbol_names,
        prefix=prefix,
        conn=conn,
    )
    for name in symbol_names:
        for file_path, lineno in _find_references(name, stored_rows):
            if file_path in top_files:
                continue
            ref = (file_path, lineno)
            if _is_test_file(file_path):
                test_refs.append(ref)
            else:
                other_refs.append(ref)

    unique_refs: list[ReferenceRow] = []
    seen_refs: set[ReferenceRow] = set()
    for ref in test_refs + other_refs:
        if ref in seen_refs:
            continue
        seen_refs.add(ref)
        unique_refs.append(ref)

    return _dedupe_and_cap_references(unique_refs)[:20]


def _expand_and_collect_references(
    request: ExpansionCollectionRequest,
) -> tuple[list[SymbolRow], list[ReferenceRow], ExpansionDiagnostics]:
    """
    Perform module expansion and collect cross-module references.

    Parameters
    ----------
    request : ExpansionCollectionRequest
        Module-expansion and reference-collection request.

    Returns
    -------
    tuple[
        list[codira.types.SymbolRow],
        list[codira.types.ReferenceRow],
        codira.query.context.ExpansionDiagnostics,
    ]
        Expanded related symbols, cross-module reference locations, and
        deterministic expansion diagnostics.

    Notes
    -----
    Expansion excludes private helpers and removes test or script modules to
    keep the final context focused on reusable project code. It also uses
    stored call edges and callable references to pull in cross-module related
    symbols around the primary matches.
    """
    expanded: list[SymbolRow] = []
    seen_symbols: set[SymbolRow] = set(request.top_matches)
    expansion_diagnostics = _expand_graph_related_symbols(
        GraphRelatedExpansionRequest(
            root=request.root,
            top_matches=request.top_matches,
            conn=request.conn,
            include_include_graph=request.include_include_graph,
            include_references=request.include_references,
            prefix=request.prefix,
            expanded=expanded,
            seen_symbols=seen_symbols,
            graph_signals=request.graph_signals,
        )
    )
    _expand_module_related_symbols(
        request.root,
        request.top_matches,
        prefix=request.prefix,
        expanded=expanded,
        seen_symbols=seen_symbols,
    )
    expanded = _finalize_expanded_symbols(expanded)
    unique_refs = _collect_reference_rows(
        request.root,
        request.top_matches,
        include_references=request.include_references,
        prefix=request.prefix,
        conn=request.conn,
    )
    return expanded, unique_refs, expansion_diagnostics
