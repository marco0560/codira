"""Exact lookup helpers backed by the active codira index backend.

Responsibilities
----------------
- Provide APIs to find symbols, call edges, callable references, includes, docstring issues, and embedding inventory.
- Support prefix filtering, limit enforcement, and deterministic ordering for exact queries.
- Normalize query parameters and translate them into backend calls used by CLI and context rendering.

Design principles
-----------------
Helpers delegate to the active backend while keeping filtering and ordering deterministic.

Architectural role
------------------
This module belongs to the **exact query layer** used by CLI and context building when retrieving precise symbols and relations.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from codira.contracts import BackendRelationQueryRequest
from codira.registry import active_index_backend

if TYPE_CHECKING:
    import sqlite3
    from pathlib import Path

    from codira.types import (
        DocstringIssueRow,
        EnumMemberRow,
        IncludeEdgeRow,
        OverloadRow,
        SymbolRow,
    )

CallEdgeRow = tuple[str, str, str | None, str | None, int]
CallableRefRow = tuple[str, str, str | None, str | None, int]
EmbeddingInventoryRow = tuple[str, str, int, int]


@dataclass(frozen=True)
class CallTreeNode:
    """
    One bounded call-tree node rendered by the `calls` CLI traversal mode.

    Parameters
    ----------
    module : str | None
        Owning module for a resolved symbol, or ``None`` for unresolved leaves.
    name : str
        Logical symbol name or the unresolved placeholder.
    resolved : bool
        Whether the node resolves to a concrete indexed symbol.
    children : tuple[CallTreeNode, ...], optional
        Deterministically ordered child nodes for the next traversal layer.
    cycle : bool, optional
        Whether traversal stopped because this node would repeat the current
        branch path.
    """

    module: str | None
    name: str
    resolved: bool
    children: tuple[CallTreeNode, ...] = ()
    cycle: bool = False


@dataclass(frozen=True)
class CallTreeResult:
    """
    Bounded traversal result for one `calls` CLI query.

    Parameters
    ----------
    root_module : str | None
        Owning module for the root query symbol when it can be resolved
        deterministically.
    root_name : str
        Root logical symbol name requested by the user.
    children : tuple[codira.query.exact.CallTreeNode, ...]
        Deterministically ordered first-level traversal nodes.
    incoming : bool
        Whether traversal followed incoming edges instead of outgoing edges.
    truncated_by_depth : bool
        Whether at least one branch was cut by the supplied depth limit.
    truncated_by_nodes : bool
        Whether traversal stopped early because of the node cap.
    node_count : int
        Number of rendered nodes including the root.
    edge_count : int
        Number of rendered edges in the bounded traversal result.
    """

    root_module: str | None
    root_name: str
    children: tuple[CallTreeNode, ...]
    incoming: bool
    truncated_by_depth: bool
    truncated_by_nodes: bool
    node_count: int
    edge_count: int


EdgeQueryRequest = BackendRelationQueryRequest


@dataclass(frozen=True)
class TreeQueryRequest:
    """
    Request parameters for bounded exact traversal helpers.

    Parameters
    ----------
    root : pathlib.Path
        Repository root containing the index database.
    name : str
        Exact logical name to traverse around.
    module : str | None
        Optional module qualifier used to restrict the root.
    incoming : bool
        Whether traversal follows incoming edges.
    prefix : str | None
        Repo-root-relative path prefix used to restrict owner files.
    max_depth : int
        Maximum traversal depth below the root.
    max_nodes : int
        Maximum number of rendered nodes including the root.
    conn : sqlite3.Connection | None
        Existing database connection to reuse.
    """

    root: Path
    name: str
    module: str | None = None
    incoming: bool = False
    prefix: str | None = None
    max_depth: int = 2
    max_nodes: int = 20
    conn: sqlite3.Connection | None = None


def find_symbol(
    root: Path,
    name: str,
    *,
    prefix: str | None = None,
    conn: sqlite3.Connection | None = None,
) -> list[SymbolRow]:
    """
    Find exact symbol-name matches in the index.

    Parameters
    ----------
    root : pathlib.Path
        Repository root containing the index database.
    name : str
        Exact symbol name to search for.
    prefix : str | None, optional
        Repo-root-relative path prefix used to restrict symbol files.
    conn : sqlite3.Connection | None, optional
        Existing database connection to reuse. When omitted, the function
        opens and closes its own connection.

    Returns
    -------
    list[SymbolRow]
        Matching symbol rows ordered deterministically.
    """
    backend = active_index_backend()
    return backend.find_symbol(root, name, prefix=prefix, conn=conn)


def docstring_issues(
    root: Path,
    *,
    prefix: str | None = None,
    conn: sqlite3.Connection | None = None,
) -> list[DocstringIssueRow]:
    """
    Return indexed docstring validation issues.

    Parameters
    ----------
    root : pathlib.Path
        Repository root containing the index database.
    prefix : str | None, optional
        Repo-root-relative path prefix used to restrict issue ownership.
    conn : sqlite3.Connection | None, optional
        Existing database connection to reuse. When omitted, the function
        opens and closes its own connection.

    Returns
    -------
    list[codira.types.DocstringIssueRow]
        Issue rows with issue text, stable identity, and defining location
        metadata.
    """
    backend = active_index_backend()
    return backend.docstring_issues(root, prefix=prefix, conn=conn)


def find_symbol_overloads(
    root: Path,
    symbol: SymbolRow,
    *,
    conn: sqlite3.Connection | None = None,
) -> list[OverloadRow]:
    """
    Return overload metadata attached to one canonical callable symbol.

    Parameters
    ----------
    root : pathlib.Path
        Repository root containing the index database.
    symbol : codira.types.SymbolRow
        Canonical function or method symbol row.
    conn : sqlite3.Connection | None, optional
        Existing database connection to reuse. When omitted, the function
        opens and closes its own connection.

    Returns
    -------
    list[codira.types.OverloadRow]
        Ordered overload metadata rows for the symbol.
    """
    backend = active_index_backend()
    return backend.find_symbol_overloads(root, symbol, conn=conn)


def find_symbol_enum_members(
    root: Path,
    symbol: SymbolRow,
    *,
    conn: sqlite3.Connection | None = None,
) -> list[EnumMemberRow]:
    """
    Return enum-member metadata attached to one canonical enum symbol.

    Parameters
    ----------
    root : pathlib.Path
        Repository root containing the index database.
    symbol : codira.types.SymbolRow
        Canonical enum symbol row.
    conn : sqlite3.Connection | None, optional
        Existing database connection to reuse. When omitted, the function
        opens and closes its own connection.

    Returns
    -------
    list[codira.types.EnumMemberRow]
        Ordered enum-member metadata rows for the symbol.
    """
    backend = active_index_backend()
    return backend.find_symbol_enum_members(root, symbol, conn=conn)


def find_call_edges(
    request: EdgeQueryRequest,
) -> list[CallEdgeRow]:
    """
    Find exact call edges for a caller or callee logical name.

    Parameters
    ----------
    request : EdgeQueryRequest
        Exact edge lookup request.

    Returns
    -------
    list[CallEdgeRow]
        Matching call-edge rows ordered deterministically.
    """
    backend = active_index_backend()
    return backend.find_call_edges(request)


def build_call_tree(
    request: TreeQueryRequest,
) -> CallTreeResult | None:
    """
    Build a bounded traversal tree for one exact `calls` query.

    Parameters
    ----------
    request : TreeQueryRequest
        Bounded traversal request.

    Returns
    -------
    codira.query.exact.CallTreeResult | None
        Bounded traversal result, or ``None`` when the root query matches no
        call edges.
    """
    initial_rows = find_call_edges(
        EdgeQueryRequest(
            root=request.root,
            name=request.name,
            module=request.module,
            incoming=request.incoming,
            prefix=request.prefix,
            conn=request.conn,
        )
    )
    if not initial_rows:
        return None

    root_candidates: set[tuple[str | None, str]] = {
        (
            (callee_module, callee_name)
            if request.incoming
            and callee_module is not None
            and callee_name is not None
            else (caller_module, caller_name)
        )
        for caller_module, caller_name, callee_module, callee_name, _resolved in initial_rows
    }
    if len(root_candidates) == 1:
        root_module, root_name = next(iter(root_candidates))
    else:
        root_module, root_name = request.module, request.name

    rendered_nodes = 1
    rendered_edges = 0
    truncated_by_depth = False
    truncated_by_nodes = False

    def ordered_neighbors(
        rows: list[CallEdgeRow],
    ) -> list[tuple[str | None, str, bool]]:
        deduped: dict[tuple[str | None, str, bool], tuple[str | None, str, bool]] = {}
        for caller_module, caller_name, callee_module, callee_name, resolved in rows:
            key: tuple[str | None, str, bool]
            if request.incoming:
                key = (caller_module, caller_name, True)
            elif resolved and callee_module is not None and callee_name is not None:
                key = (callee_module, callee_name, True)
            else:
                key = (None, "<unresolved>", False)
            deduped.setdefault(key, key)
        return sorted(
            deduped.values(),
            key=lambda item: (
                0 if item[2] else 1,
                item[0] or "",
                item[1],
            ),
        )

    def build_children(
        current_module: str | None,
        current_name: str,
        *,
        depth: int,
        path: tuple[tuple[str | None, str], ...],
    ) -> tuple[CallTreeNode, ...]:
        nonlocal rendered_edges, rendered_nodes, truncated_by_depth, truncated_by_nodes

        rows = find_call_edges(
            EdgeQueryRequest(
                root=request.root,
                name=current_name,
                module=current_module,
                incoming=request.incoming,
                prefix=request.prefix,
                conn=request.conn,
            )
        )
        if not rows:
            return ()
        if depth >= request.max_depth:
            truncated_by_depth = True
            return ()

        children: list[CallTreeNode] = []
        for child_module, child_name, child_resolved in ordered_neighbors(rows):
            if rendered_nodes >= request.max_nodes:
                truncated_by_nodes = True
                break

            rendered_edges += 1
            rendered_nodes += 1

            if not child_resolved:
                children.append(
                    CallTreeNode(
                        module=None,
                        name=child_name,
                        resolved=False,
                    )
                )
                continue

            child_identity = (child_module, child_name)
            if child_identity in path:
                children.append(
                    CallTreeNode(
                        module=child_module,
                        name=child_name,
                        resolved=True,
                        cycle=True,
                    )
                )
                continue

            grandchildren = build_children(
                child_module,
                child_name,
                depth=depth + 1,
                path=path + (child_identity,),
            )
            children.append(
                CallTreeNode(
                    module=child_module,
                    name=child_name,
                    resolved=True,
                    children=grandchildren,
                )
            )

        return tuple(children)

    return CallTreeResult(
        root_module=root_module,
        root_name=root_name,
        children=build_children(
            root_module,
            root_name,
            depth=0,
            path=((root_module, root_name),),
        ),
        incoming=request.incoming,
        truncated_by_depth=truncated_by_depth,
        truncated_by_nodes=truncated_by_nodes,
        node_count=rendered_nodes,
        edge_count=rendered_edges,
    )


def find_callable_refs(
    request: EdgeQueryRequest,
) -> list[CallableRefRow]:
    """
    Find exact callable-object references for an owner or referenced target.

    Parameters
    ----------
    request : EdgeQueryRequest
        Exact edge lookup request.

    Returns
    -------
    list[CallableRefRow]
        Matching callable-reference rows ordered deterministically.
    """
    backend = active_index_backend()
    return backend.find_callable_refs(request)


def build_ref_tree(
    request: TreeQueryRequest,
) -> CallTreeResult | None:
    """
    Build a bounded traversal tree for one exact `refs` query.

    Parameters
    ----------
    request : TreeQueryRequest
        Bounded traversal request.

    Returns
    -------
    codira.query.exact.CallTreeResult | None
        Bounded traversal result, or ``None`` when the root query matches no
        callable references.
    """
    initial_rows = find_callable_refs(
        EdgeQueryRequest(
            root=request.root,
            name=request.name,
            module=request.module,
            incoming=request.incoming,
            prefix=request.prefix,
            conn=request.conn,
        )
    )
    if not initial_rows:
        return None

    root_candidates: set[tuple[str | None, str]] = {
        (
            (target_module, target_name)
            if request.incoming
            and target_module is not None
            and target_name is not None
            else (owner_module, owner_name)
        )
        for owner_module, owner_name, target_module, target_name, _resolved in initial_rows
    }
    if len(root_candidates) == 1:
        root_module, root_name = next(iter(root_candidates))
    else:
        root_module, root_name = request.module, request.name

    rendered_nodes = 1
    rendered_edges = 0
    truncated_by_depth = False
    truncated_by_nodes = False

    def ordered_neighbors(
        rows: list[CallableRefRow],
    ) -> list[tuple[str | None, str, bool]]:
        deduped: dict[tuple[str | None, str, bool], tuple[str | None, str, bool]] = {}
        for owner_module, owner_name, target_module, target_name, resolved in rows:
            key: tuple[str | None, str, bool]
            if request.incoming:
                key = (owner_module, owner_name, True)
            elif resolved and target_module is not None and target_name is not None:
                key = (target_module, target_name, True)
            else:
                key = (None, "<unresolved>", False)
            deduped.setdefault(key, key)
        return sorted(
            deduped.values(),
            key=lambda item: (
                0 if item[2] else 1,
                item[0] or "",
                item[1],
            ),
        )

    def build_children(
        current_module: str | None,
        current_name: str,
        *,
        depth: int,
        path: tuple[tuple[str | None, str], ...],
    ) -> tuple[CallTreeNode, ...]:
        nonlocal rendered_edges, rendered_nodes, truncated_by_depth, truncated_by_nodes

        rows = find_callable_refs(
            EdgeQueryRequest(
                root=request.root,
                name=current_name,
                module=current_module,
                incoming=request.incoming,
                prefix=request.prefix,
                conn=request.conn,
            )
        )
        if not rows:
            return ()
        if depth >= request.max_depth:
            truncated_by_depth = True
            return ()

        children: list[CallTreeNode] = []
        for child_module, child_name, child_resolved in ordered_neighbors(rows):
            if rendered_nodes >= request.max_nodes:
                truncated_by_nodes = True
                break

            rendered_edges += 1
            rendered_nodes += 1

            if not child_resolved:
                children.append(
                    CallTreeNode(module=None, name=child_name, resolved=False)
                )
                continue

            child_identity = (child_module, child_name)
            if child_identity in path:
                children.append(
                    CallTreeNode(
                        module=child_module,
                        name=child_name,
                        resolved=True,
                        cycle=True,
                    )
                )
                continue

            grandchildren = build_children(
                child_module,
                child_name,
                depth=depth + 1,
                path=path + (child_identity,),
            )
            children.append(
                CallTreeNode(
                    module=child_module,
                    name=child_name,
                    resolved=True,
                    children=grandchildren,
                )
            )

        return tuple(children)

    return CallTreeResult(
        root_module=root_module,
        root_name=root_name,
        children=build_children(
            root_module,
            root_name,
            depth=0,
            path=((root_module, root_name),),
        ),
        incoming=request.incoming,
        truncated_by_depth=truncated_by_depth,
        truncated_by_nodes=truncated_by_nodes,
        node_count=rendered_nodes,
        edge_count=rendered_edges,
    )


def find_include_edges(
    request: EdgeQueryRequest,
) -> list[IncludeEdgeRow]:
    """
    Find exact include-like edges for an owner module or included target.

    Parameters
    ----------
    request : EdgeQueryRequest
        Exact edge lookup request.

    Returns
    -------
    list[codira.types.IncludeEdgeRow]
        Matching include-edge rows ordered deterministically as
        ``(owner_module, target_name, kind, lineno)`` tuples.
    """
    backend = active_index_backend()
    return backend.find_include_edges(request)


def find_logical_symbols(
    root: Path,
    module_name: str,
    logical_name: str,
    *,
    prefix: str | None = None,
    conn: sqlite3.Connection | None = None,
) -> list[SymbolRow]:
    """
    Resolve a logical callable name back to indexed symbol rows.

    Parameters
    ----------
    root : pathlib.Path
        Repository root containing the index database.
    module_name : str
        Dotted module that owns the logical symbol.
    logical_name : str
        Logical symbol identity such as ``helper`` or ``Class.method``.
    prefix : str | None, optional
        Repo-root-relative path prefix used to restrict symbol files.
    conn : sqlite3.Connection | None, optional
        Existing database connection to reuse. When omitted, the function
        opens and closes its own connection.

    Returns
    -------
    list[codira.types.SymbolRow]
        Matching indexed symbol rows ordered deterministically.
    """
    backend = active_index_backend()
    return backend.find_logical_symbols(
        root,
        module_name,
        logical_name,
        prefix=prefix,
        conn=conn,
    )


def logical_symbol_name(
    root: Path,
    symbol: SymbolRow,
    *,
    conn: sqlite3.Connection | None = None,
) -> str:
    """
    Return the logical graph identity for one indexed symbol row.

    Parameters
    ----------
    root : pathlib.Path
        Repository root containing the index database.
    symbol : codira.types.SymbolRow
        Indexed symbol row whose logical identity should be resolved.
    conn : sqlite3.Connection | None, optional
        Existing database connection to reuse. When omitted, the function
        opens and closes its own connection.

    Returns
    -------
    str
        Logical symbol identity used by call edges and callable references.
    """
    backend = active_index_backend()
    return backend.logical_symbol_name(root, symbol, conn=conn)


def embedding_inventory(
    root: Path,
    *,
    conn: sqlite3.Connection | None = None,
) -> list[EmbeddingInventoryRow]:
    """
    Return stored embedding inventory grouped by backend metadata.

    Parameters
    ----------
    root : pathlib.Path
        Repository root containing the index database.
    conn : sqlite3.Connection | None, optional
        Existing database connection to reuse. When omitted, the function
        opens and closes its own connection.

    Returns
    -------
    list[EmbeddingInventoryRow]
        Rows as ``(backend, version, dim, count)`` ordered deterministically.
    """
    backend = active_index_backend()
    return backend.embedding_inventory(root, conn=conn)
