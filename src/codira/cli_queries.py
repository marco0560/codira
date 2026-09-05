"""Read-oriented query commands and deterministic CLI renderers."""

from __future__ import annotations

import contextlib
import io
import shutil
import sys
from pathlib import Path
from typing import TYPE_CHECKING, cast

from codira.architecture import (
    ArchitectureForbiddenDependencyRule,
    ArchitectureLayer,
    ArchitecturePolicy,
    analyze_architecture_policy,
    build_architecture_model_from_index,
)
from codira.architecture_report import write_architecture_artifacts
from codira.cli_index import _ensure_index, _relative_report_path
from codira.cli_render import (
    _emit_json,
    _format_bytes,
    _query_payload,
    _run_capabilities,
)
from codira.cli_requests import (
    DocumentationCommandRequest,
    EmbeddingCommandRequest,
    RelationCommandRequest,
    RelationCommandSpec,
    RelationSubcommandRequest,
    SymbolInventoryCommandRequest,
)
from codira.config import (
    ConfigError,
    ConfigOrigin,
    load_effective_config,
)
from codira.contracts import (
    VectorStorePurgeRequest,
    VectorStorePurgeResult,
    VectorStoreResetRequest,
)
from codira.query.context import ContextRequest, context_for
from codira.query.exact import (
    CallTreeNode,
    CallTreeResult,
    EdgeQueryRequest,
    TreeQueryRequest,
    build_call_tree,
    build_ref_tree,
    docstring_issues,
    embedding_inventory,
    find_call_edges,
    find_callable_refs,
    find_symbol,
    find_symbol_enum_members,
    find_symbol_overloads,
    symbol_inventory,
)
from codira.query_daemon_cli import CliRouteResult, emit_execution_mode, route_cli_read
from codira.registry import (
    active_index_backend,
)
from codira.semantic.embeddings import (
    get_embedding_backend,
)
from codira.semantic.search import (
    DocumentationCandidatesRequest,
    EmbeddingCandidatesRequest,
    documentation_candidates,
    embedding_candidates,
    similarity_candidate_provenance_payload,
    similarity_query_provenance_payload,
)
from codira.similarity_lifecycle import (
    purge_active_similarity_index,
    rebuild_active_similarity_index,
    reset_active_similarity_index,
)
from codira.storage import (
    acquire_index_lock,
)
from codira.vector_store import (
    active_vector_store_context,
    active_vector_store_reset_context,
)
from codira.version import package_version

if TYPE_CHECKING:
    import argparse
    from collections.abc import Callable
    from typing import Protocol

    from codira.contracts import (
        BackendGraphMetric,
        BackendQueryConnection,
        BackendSymbolInventoryItem,
    )
    from codira.types import DocstringIssueRow

    class _IndexedFileHashLoader(Protocol):
        """
        Backend read surface used by CLI freshness fallback checks.

        Parameters
        ----------
        None

        Returns
        -------
        None
            Protocol definitions are only evaluated by type checkers.
        """

        def load_existing_file_hashes(
            self,
            root: Path,
            *,
            conn: object | None = None,
        ) -> dict[str, str]: ...


GIT_EXE = shutil.which("git") or "git"
__version__ = package_version()

QUERY_JSON_SCHEMA_VERSION = "2.0"
INDEX_METADATA_ANALYZER_INVENTORY = "analyzer_inventory"
INDEX_METADATA_BACKEND_NAME = "backend_name"
INDEX_METADATA_BACKEND_VERSION = "backend_version"
INDEX_METADATA_FILE_COUNT = "indexed_file_count"
_REPO_PATH_COMMANDS = frozenset(
    {
        "index",
        "cov",
        "sym",
        "symlist",
        "arch",
        "emb",
        "docs",
        "calls",
        "refs",
        "audit",
        "ctx",
        "config",
        "daemon",
        "query-daemon",
        "setup",
    }
)
_CONFIG_INSPECTION_ACTIONS = frozenset({"dump", "explain", "validate"})


def _run_symbol(
    root: Path,
    name: str,
    *,
    prefix: str | None = None,
    as_json: bool = False,
    query_prefix: str | None = None,
) -> int:
    """
    Resolve and print exact symbol matches.

    Parameters
    ----------
    root : pathlib.Path
        Repository root containing the index.
    name : str
        Exact symbol name to look up.
    prefix : str | None, optional
        Repo-root-relative path prefix used to restrict symbol files.
    as_json : bool, optional
        Whether to render structured JSON output.
    query_prefix : str | None, optional
        User-facing repo-root-relative prefix echoed in JSON output.

    Returns
    -------
    int
        Zero when at least one symbol is found, otherwise one.
    """
    from codira.cli import _source_constant_json_detail

    backend = active_index_backend(root=root)
    conn = backend.open_connection(root)
    try:
        rows = find_symbol(root, name, prefix=prefix, conn=conn)

        if as_json:

            def _symbol_json_result(
                symbol_type: str,
                module_name: str,
                symbol_name: str,
                file_path: str,
                lineno: int,
            ) -> dict[str, object]:
                row: dict[str, object] = {
                    "type": symbol_type,
                    "module": module_name,
                    "name": symbol_name,
                    "file": file_path,
                    "lineno": lineno,
                }
                overloads = find_symbol_overloads(
                    root,
                    (
                        symbol_type,
                        module_name,
                        symbol_name,
                        file_path,
                        lineno,
                    ),
                    conn=conn,
                )
                if overloads:
                    row["overloads"] = [
                        {
                            "kind": "overload",
                            "stable_id": stable_id,
                            "parent_stable_id": parent_stable_id,
                            "ordinal": ordinal,
                            "signature": signature,
                            "lineno": overload_lineno,
                            "end_lineno": end_lineno,
                            "docstring": docstring,
                        }
                        for (
                            stable_id,
                            parent_stable_id,
                            ordinal,
                            signature,
                            overload_lineno,
                            end_lineno,
                            docstring,
                        ) in overloads
                    ]
                enum_members = find_symbol_enum_members(
                    root,
                    (
                        symbol_type,
                        module_name,
                        symbol_name,
                        file_path,
                        lineno,
                    ),
                    conn=conn,
                )
                if enum_members:
                    row["enum_members"] = [
                        {
                            "kind": "enum_member",
                            "stable_id": stable_id,
                            "parent_stable_id": parent_stable_id,
                            "ordinal": ordinal,
                            "name": member_name,
                            "signature": signature,
                            "lineno": member_lineno,
                        }
                        for (
                            stable_id,
                            parent_stable_id,
                            ordinal,
                            member_name,
                            signature,
                            member_lineno,
                        ) in enum_members
                    ]
                if symbol_type == "constant":
                    constant_detail = _source_constant_json_detail(
                        file_path=file_path,
                        symbol_name=symbol_name,
                        lineno=lineno,
                    )
                    if constant_detail is not None:
                        row["constant_detail"] = constant_detail
                return row

            _emit_json(
                _query_payload(
                    "sym",
                    "ok" if rows else "no_matches",
                    {"name": name, "prefix": query_prefix},
                    [
                        _symbol_json_result(
                            symbol_type,
                            module_name,
                            symbol_name,
                            file_path,
                            lineno,
                        )
                        for symbol_type, module_name, symbol_name, file_path, lineno in rows
                    ],
                )
            )
            return 0 if rows else 1

        if not rows:
            print(f"No symbol found: {name}")
            return 1

        for symbol_type, module_name, symbol_name, file_path, lineno in rows:
            if symbol_type == "module":
                print(f"{symbol_type}: {module_name} {file_path}:{lineno}")
            else:
                print(
                    f"{symbol_type}: {module_name}.{symbol_name} {file_path}:{lineno}"
                )

        return 0
    finally:
        backend.close_connection(conn)


def _graph_metric_payload(metric: BackendGraphMetric) -> dict[str, int]:
    """
    Convert one graph metric to the public JSON shape.

    Parameters
    ----------
    metric : codira.contracts.BackendGraphMetric
        Graph metric returned by the active backend.

    Returns
    -------
    dict[str, int]
        JSON-ready metric payload.
    """
    return {"total": metric.total, "unresolved": metric.unresolved}


def _symbol_inventory_payload(
    item: BackendSymbolInventoryItem,
) -> dict[str, object]:
    """
    Convert one symbol inventory row to the public JSON shape.

    Parameters
    ----------
    item : codira.contracts.BackendSymbolInventoryItem
        Backend-neutral inventory row.

    Returns
    -------
    dict[str, object]
        JSON-ready symbol inventory payload.
    """
    return {
        "id": f"{item.module}:{item.name}",
        "type": item.symbol_type,
        "module": item.module,
        "name": item.name,
        "file": item.file,
        "lineno": item.lineno,
        "calls_out": _graph_metric_payload(item.calls_out),
        "calls_in": _graph_metric_payload(item.calls_in),
        "refs_out": _graph_metric_payload(item.refs_out),
        "refs_in": _graph_metric_payload(item.refs_in),
    }


def _format_graph_metric(name: str, metric: BackendGraphMetric) -> str | None:
    """
    Render one compact human-readable graph metric.

    Parameters
    ----------
    name : str
        Metric label to render.
    metric : codira.contracts.BackendGraphMetric
        Metric values returned by the active backend.

    Returns
    -------
    str | None
        Human-readable metric fragment, or ``None`` when all values are zero.
    """
    if metric.total == 0:
        return None
    if metric.unresolved == 0:
        return f"{name}={metric.total}"
    return f"{name}={metric.total} ({metric.unresolved} unresolved)"


def _run_symbol_inventory(request: SymbolInventoryCommandRequest) -> int:
    """
    Print indexed symbols with graph connectivity metrics.

    Parameters
    ----------
    request : SymbolInventoryCommandRequest
        Runtime options for the ``symlist`` command.

    Returns
    -------
    int
        Zero after rendering the inventory.
    """
    rows = symbol_inventory(
        request.root,
        prefix=request.prefix,
        include_tests=request.include_tests,
        limit=request.limit,
    )

    if request.as_json:
        _emit_json(
            {
                "schema_version": QUERY_JSON_SCHEMA_VERSION,
                "status": "ok",
                "symbols": [_symbol_inventory_payload(item) for item in rows],
            }
        )
        return 0

    current_module: str | None = None
    for item in rows:
        if item.module != current_module:
            current_module = item.module
            print(item.module)
        metrics = " ".join(
            metric
            for metric in (
                _format_graph_metric("calls_out", item.calls_out),
                _format_graph_metric("calls_in", item.calls_in),
                _format_graph_metric("refs_out", item.refs_out),
                _format_graph_metric("refs_in", item.refs_in),
            )
            if metric is not None
        )
        suffix = f"  {metrics}" if metrics else ""
        print(f"  {item.name}{suffix}")
    return 0


def _run_audit_docstrings(
    root: Path,
    *,
    prefix: str | None = None,
    as_json: bool = False,
    query_prefix: str | None = None,
) -> int:
    """
    Print indexed docstring issues.

    Parameters
    ----------
    root : pathlib.Path
        Repository root containing the index.
    prefix : str | None, optional
        Repo-root-relative path prefix used to restrict issue ownership.
    as_json : bool, optional
        Whether to render structured JSON output.
    query_prefix : str | None, optional
        User-facing repo-root-relative prefix echoed in JSON output.

    Returns
    -------
    int
        Process exit status for the audit command.
    """
    rows = docstring_issues(root, prefix=prefix)

    if as_json:
        _emit_json(
            _query_payload(
                "audit",
                "ok" if rows else "no_matches",
                {"prefix": query_prefix},
                [
                    {
                        "type": issue_type,
                        "message": message,
                        "audit_plugin": {
                            "name": audit_plugin_name,
                            "version": audit_plugin_version,
                        },
                        "audit_convention": {
                            "name": convention_name,
                            "version": convention_version,
                        },
                        "rule_id": rule_id,
                        "severity": severity,
                        "stable_id": stable_id,
                        "symbol_type": symbol_type,
                        "module": module_name,
                        "name": symbol_name,
                        "file": file_path,
                        "lineno": lineno,
                        "end_lineno": end_lineno,
                        "audit_route": {
                            "language": audit_language,
                            "convention": convention_name,
                            "plugin": audit_plugin_name,
                        },
                    }
                    for (
                        issue_type,
                        message,
                        audit_language,
                        audit_plugin_name,
                        audit_plugin_version,
                        convention_name,
                        convention_version,
                        rule_id,
                        severity,
                        stable_id,
                        symbol_type,
                        module_name,
                        symbol_name,
                        file_path,
                        lineno,
                        end_lineno,
                    ) in rows
                ],
            )
        )
        return 0

    if not rows:
        print("No docstring issues found")
        return 0

    grouped_missing: dict[tuple[str, str, int], list[str]] = {}
    passthrough: list[DocstringIssueRow] = []

    for row in rows:
        (
            issue_type,
            message,
            _audit_language,
            _audit_plugin_name,
            _audit_plugin_version,
            _convention_name,
            _convention_version,
            _rule_id,
            _severity,
            _stable_id,
            _symbol_type,
            _module_name,
            symbol_name,
            file_path,
            lineno,
            _end_lineno,
        ) = row

        if issue_type == "missing_parameter" and "Parameter not documented:" in message:
            param = message.split("Parameter not documented:", 1)[1].strip()
            key = (symbol_name, file_path, lineno)
            grouped_missing.setdefault(key, []).append(param)
        else:
            passthrough.append(row)

    for (symbol_name, file_path, lineno), params in grouped_missing.items():
        params_str = ", ".join(sorted(params))
        print(
            f"missing_parameter: Function {symbol_name}: Parameters not documented: {params_str} "
            f"[{file_path}:{lineno}]"
        )

    for (
        issue_type,
        message,
        _audit_language,
        _audit_plugin_name,
        _audit_plugin_version,
        _convention_name,
        _convention_version,
        _rule_id,
        _severity,
        _stable_id,
        _symbol_type,
        _module_name,
        _symbol_name,
        file_path,
        lineno,
        _end_lineno,
    ) in passthrough:
        print(f"{issue_type}: {message} [{file_path}:{lineno}]")

    return 0


def _run_embeddings(
    request: EmbeddingCommandRequest,
) -> int:
    """
    Print embedding-backend metadata and top embedding matches.

    Parameters
    ----------
    request : EmbeddingCommandRequest
        Runtime options for the embedding command.

    Returns
    -------
    int
        Zero when embedding inventory exists, otherwise one.
    """
    root = request.root
    backend = get_embedding_backend(root=root)
    inventory = embedding_inventory(root)

    if not inventory:
        if request.as_json:
            _emit_json(
                _query_payload(
                    "emb",
                    "not_indexed",
                    {
                        "text": request.query,
                        "limit": request.limit,
                        "prefix": request.query_prefix,
                    },
                    [],
                    backend={
                        "name": backend.name,
                        "version": backend.version,
                        "dim": backend.dim,
                    },
                    inventory=[],
                )
            )
            return 1
        print("No stored embeddings found. Run: codira index")
        return 1

    matches = embedding_candidates(
        EmbeddingCandidatesRequest(
            root=root,
            query=request.query,
            limit=request.limit,
            min_score=0.0,
            prefix=request.prefix,
            search_profile=request.search_profile,
        )
    )
    if request.as_json:
        similarity = getattr(matches, "search_result", None)
        resolved = getattr(matches, "resolved", ())
        if similarity is None:
            resolved = tuple(None for _ in matches)
        results: list[dict[str, object]] = []
        for match, resolved_candidate in zip(matches, resolved, strict=True):
            score, (symbol_type, module_name, name, file_path, lineno) = match
            results.append(
                {
                    "score": round(score, 2),
                    "type": symbol_type,
                    "module": module_name,
                    "name": name,
                    "file": file_path,
                    "lineno": lineno,
                    "similarity": (
                        None
                        if resolved_candidate is None
                        else similarity_candidate_provenance_payload(
                            resolved_candidate.candidate
                        )
                    ),
                }
            )
        _emit_json(
            _query_payload(
                "emb",
                "ok" if matches else "no_matches",
                {
                    "text": request.query,
                    "limit": request.limit,
                    "prefix": request.query_prefix,
                },
                results,
                backend={
                    "name": backend.name,
                    "version": backend.version,
                    "dim": backend.dim,
                },
                inventory=[
                    {
                        "backend": stored_backend,
                        "version": stored_version,
                        "dim": stored_dim,
                        "rows": count,
                    }
                    for stored_backend, stored_version, stored_dim, count in inventory
                ],
                similarity=(
                    None
                    if similarity is None
                    else similarity_query_provenance_payload(similarity)
                ),
            )
        )
        return 0

    print(f"backend: {backend.name} version={backend.version} dim={backend.dim}")
    for stored_backend, stored_version, stored_dim, count in inventory:
        print(
            "stored:"
            f" {stored_backend}"
            f" version={stored_version}"
            f" dim={stored_dim}"
            f" rows={count}"
        )

    if not matches:
        print("No embedding matches found.")
        return 0

    for score, (symbol_type, module_name, name, file_path, lineno) in matches:
        print(f"{score:.2f} {symbol_type}: {module_name}.{name} {file_path}:{lineno}")

    return 0


def _run_documentation_lookup(
    request: DocumentationCommandRequest,
) -> int:
    """
    Print docs-only retrieval matches.

    Parameters
    ----------
    request : codira.cli.DocumentationCommandRequest
        Runtime options for the docs command.

    Returns
    -------
    int
        Zero when documentation retrieval completed, otherwise one when no
        stored embeddings exist.
    """
    root = request.root
    backend = get_embedding_backend(root=root)
    inventory = embedding_inventory(root)

    if not inventory:
        if request.as_json:
            _emit_json(
                _query_payload(
                    "docs",
                    "not_indexed",
                    {
                        "text": request.query,
                        "limit": request.limit,
                        "prefix": request.query_prefix,
                    },
                    [],
                    backend={
                        "name": backend.name,
                        "version": backend.version,
                        "dim": backend.dim,
                    },
                )
            )
            return 1
        print("No stored embeddings found. Run: codira index")
        return 1

    matches = documentation_candidates(
        DocumentationCandidatesRequest(
            root=root,
            query=request.query,
            limit=request.limit,
            min_score=0.0,
            prefix=request.prefix,
            search_profile=request.search_profile,
        )
    )

    if request.as_json:
        similarity = getattr(matches, "search_result", None)
        resolved = getattr(matches, "resolved", ())
        if similarity is None:
            resolved = tuple(None for _ in matches)
        results: list[dict[str, object]] = []
        for match, resolved_candidate in zip(matches, resolved, strict=True):
            (
                score,
                (
                    stable_id,
                    kind,
                    source_format,
                    file_path,
                    lineno,
                    end_lineno,
                    title,
                    heading_path,
                    text,
                ),
            ) = match
            results.append(
                {
                    "score": round(score, 2),
                    "stable_id": stable_id,
                    "kind": kind,
                    "source_format": source_format,
                    "file": file_path,
                    "lineno": lineno,
                    "end_lineno": end_lineno,
                    "title": title,
                    "heading_path": list(heading_path),
                    "text": text,
                    "similarity": (
                        None
                        if resolved_candidate is None
                        else similarity_candidate_provenance_payload(
                            resolved_candidate.candidate
                        )
                    ),
                }
            )
        _emit_json(
            _query_payload(
                "docs",
                "ok" if matches else "no_matches",
                {
                    "text": request.query,
                    "limit": request.limit,
                    "prefix": request.query_prefix,
                },
                results,
                backend={
                    "name": backend.name,
                    "version": backend.version,
                    "dim": backend.dim,
                },
                similarity=(
                    None
                    if similarity is None
                    else similarity_query_provenance_payload(similarity)
                ),
            )
        )
        return 0

    if request.explain:
        print(f"backend: {backend.name} version={backend.version} dim={backend.dim}")
        print(f"query: {request.query}")
        print(f"limit: {request.limit}")
        print(f"prefix: {request.query_prefix}")
        print(f"matches: {len(matches)}")

    if not matches:
        print("No documentation matches found.")
        return 0

    for score, (
        stable_id,
        kind,
        source_format,
        file_path,
        lineno,
        end_lineno,
        title,
        heading_path,
        text,
    ) in matches:
        rel_path = _relative_report_path(root, file_path)
        end_label = f"-{end_lineno}" if end_lineno is not None else ""
        print(
            f"{score:.2f} {kind}: {title} "
            f"{rel_path}:{lineno}{end_label} [{source_format}]"
        )
        if request.explain:
            heading = " > ".join(heading_path)
            print(f"  stable_id: {stable_id}")
            print(f"  heading_path: {heading}")
            preview = " ".join(text.split())[:160]
            print(f"  preview: {preview}")

    return 0


def _validate_relation_request(
    request: RelationCommandRequest,
) -> int | None:
    """
    Validate shared traversal limits for relation commands.

    Parameters
    ----------
    request : RelationCommandRequest
        Relation-command runtime options.

    Returns
    -------
    int | None
        Error exit code when validation fails, otherwise ``None``.
    """
    if request.max_depth < 0:
        print("--max-depth must be >= 0", file=sys.stderr)
        return 2
    if request.max_nodes < 1:
        print("--max-nodes must be >= 1", file=sys.stderr)
        return 2
    return None


def _relation_query_metadata(
    request: RelationCommandRequest,
    *,
    tree: bool,
) -> dict[str, object]:
    """
    Build the shared JSON query metadata for relation commands.

    Parameters
    ----------
    request : RelationCommandRequest
        Relation-command runtime options.
    tree : bool
        Whether the current render mode is tree traversal.

    Returns
    -------
    dict[str, object]
        Machine-readable query metadata.
    """
    query: dict[str, object] = {
        "name": request.name,
        "module": request.module,
        "incoming": request.incoming,
        "prefix": request.query_prefix,
    }
    if tree:
        query["tree"] = True
        query["max_depth"] = request.max_depth
        query["max_nodes"] = request.max_nodes
    return query


def _relation_rows_payload(
    rows: list[tuple[str, str, str | None, str | None, str | None, str | None, int]],
    spec: RelationCommandSpec,
) -> list[dict[str, object]]:
    """
    Serialize flat relation rows for JSON output.

    Parameters
    ----------
    rows : list[tuple[str, str, str | None, str | None, str | None, str | None, int]]
        Flat relation rows returned by the exact query layer.
    spec : RelationCommandSpec
        Command-specific rendering and naming hooks.

    Returns
    -------
    list[dict[str, object]]
        JSON-serializable relation rows.
    """
    return [
        {
            spec.source_module_key: source_module,
            spec.source_name_key: source_name,
            spec.target_module_key: target_module,
            spec.target_name_key: target_name,
            **(
                {"external_target_kind": external_target_kind}
                if external_target_kind is not None
                else {}
            ),
            **(
                {"external_target_name": external_target_name}
                if external_target_name is not None
                else {}
            ),
            "resolved": bool(resolved),
        }
        for (
            source_module,
            source_name,
            target_module,
            target_name,
            external_target_kind,
            external_target_name,
            resolved,
        ) in rows
    ]


def _print_relation_rows(
    rows: list[tuple[str, str, str | None, str | None, str | None, str | None, int]],
    spec: RelationCommandSpec,
) -> None:
    """
    Print flat relation rows in deterministic plain text.

    Parameters
    ----------
    rows : list[tuple[str, str, str | None, str | None, str | None, str | None, int]]
        Flat relation rows returned by the exact query layer.
    spec : RelationCommandSpec
        Command-specific rendering and naming hooks.

    Returns
    -------
    None
        Relation rows are printed to standard output.
    """
    for (
        source_module,
        source_name,
        target_module,
        target_name,
        external_target_kind,
        external_target_name,
        resolved,
    ) in rows:
        source = f"{source_module}.{source_name}"
        if resolved:
            assert target_module is not None
            assert target_name is not None
            target = f"{target_module}.{target_name}"
        elif external_target_kind is not None and external_target_name is not None:
            target = f"{external_target_kind}:{external_target_name}"
        elif external_target_name is not None:
            target = external_target_name
        else:
            target = "<unresolved>"
        print(f"{source} {spec.plain_arrow} {target}")


def _run_relation_tree(
    request: RelationCommandRequest,
    spec: RelationCommandSpec,
) -> int:
    """
    Render one relation command in bounded tree mode.

    Parameters
    ----------
    request : RelationCommandRequest
        Relation-command runtime options.
    spec : RelationCommandSpec
        Command-specific rendering and naming hooks.

    Returns
    -------
    int
        Zero when the tree exists, otherwise one.
    """
    tree = spec.tree_builder(
        TreeQueryRequest(
            root=request.root,
            name=request.name,
            module=request.module,
            incoming=request.incoming,
            prefix=request.prefix,
            max_depth=request.max_depth,
            max_nodes=request.max_nodes,
        )
    )
    if request.as_json:
        _emit_json(
            _query_payload(
                spec.command,
                "ok" if tree is not None else "no_matches",
                _relation_query_metadata(request, tree=True),
                [_call_tree_result_payload(tree)] if tree is not None else [],
                truncated=(
                    {
                        "depth": tree.truncated_by_depth,
                        "nodes": tree.truncated_by_nodes,
                    }
                    if tree is not None
                    else {"depth": False, "nodes": False}
                ),
                node_count=tree.node_count if tree is not None else 0,
                edge_count=tree.edge_count if tree is not None else 0,
            )
        )
        return 0 if tree is not None else 1

    if tree is None:
        noun = (
            spec.missing_direction_incoming
            if request.incoming
            else spec.missing_direction_outgoing
        )
        if request.module is None:
            print(f"No {spec.missing_message} found for {noun}: {request.name}")
        else:
            print(
                f"No {spec.missing_message} found for "
                f"{noun}: {request.module}.{request.name}"
            )
        return 1

    if request.as_dot:
        for line in _render_relation_tree_dot(tree, graph_name=spec.graph_name):
            print(line)
        return 0

    for line in _render_relation_tree_lines(
        tree,
        outgoing_marker=spec.outgoing_tree_marker,
        incoming_marker=spec.incoming_tree_marker,
    ):
        print(line)
    if tree.truncated_by_depth or tree.truncated_by_nodes:
        truncation_bits: list[str] = []
        if tree.truncated_by_depth:
            truncation_bits.append(f"max_depth={request.max_depth}")
        if tree.truncated_by_nodes:
            truncation_bits.append(f"max_nodes={request.max_nodes}")
        print(f"truncated: {', '.join(truncation_bits)}")
    return 0


def _run_relation_rows_mode(
    request: RelationCommandRequest,
    spec: RelationCommandSpec,
) -> int:
    """
    Render one relation command in flat-row mode.

    Parameters
    ----------
    request : RelationCommandRequest
        Relation-command runtime options.
    spec : RelationCommandSpec
        Command-specific rendering and naming hooks.

    Returns
    -------
    int
        Zero when at least one row exists, otherwise one.
    """
    rows = spec.row_fetcher(
        EdgeQueryRequest(
            root=request.root,
            name=request.name,
            module=request.module,
            incoming=request.incoming,
            prefix=request.prefix,
        )
    )

    if request.as_json:
        _emit_json(
            _query_payload(
                spec.command,
                "ok" if rows else "no_matches",
                _relation_query_metadata(request, tree=False),
                _relation_rows_payload(rows, spec),
            )
        )
        return 0 if rows else 1

    if not rows:
        noun = (
            spec.missing_direction_incoming
            if request.incoming
            else spec.missing_direction_outgoing
        )
        if request.module is None:
            print(f"No {spec.missing_message} found for {noun}: {request.name}")
        else:
            print(
                f"No {spec.missing_message} found for "
                f"{noun}: {request.module}.{request.name}"
            )
        return 1

    _print_relation_rows(rows, spec)
    return 0


def _run_relation_command(
    request: RelationCommandRequest,
    spec: RelationCommandSpec,
) -> int:
    """
    Run one relation-oriented CLI command.

    Parameters
    ----------
    request : RelationCommandRequest
        Relation-command runtime options.
    spec : RelationCommandSpec
        Command-specific rendering and naming hooks.

    Returns
    -------
    int
        Process exit status for the command.
    """
    validation_error = _validate_relation_request(request)
    if validation_error is not None:
        return validation_error
    if request.as_tree:
        return _run_relation_tree(request, spec)
    return _run_relation_rows_mode(request, spec)


def _run_calls(
    request: RelationCommandRequest,
) -> int:
    """
    Print indexed static call edges for one logical name.

    Parameters
    ----------
    request : RelationCommandRequest
        Runtime options for the calls command.

    Returns
    -------
    int
        Zero when at least one edge is found, otherwise one.
    """
    return _run_relation_command(
        request,
        RelationCommandSpec(
            command="calls",
            missing_message="call edges",
            graph_name="codira_calls",
            missing_direction_outgoing="caller",
            missing_direction_incoming="callee",
            plain_arrow="->",
            outgoing_tree_marker="-> ",
            incoming_tree_marker="<- ",
            source_module_key="caller_module",
            source_name_key="caller_name",
            target_module_key="callee_module",
            target_name_key="callee_name",
            row_fetcher=find_call_edges,
            tree_builder=build_call_tree,
        ),
    )


def _call_tree_display(module: str | None, name: str, *, resolved: bool) -> str:
    """
    Render a compact display label for one call-tree node.

    Parameters
    ----------
    module : str | None
        Owning module when the node resolves to an indexed symbol.
    name : str
        Logical symbol name or unresolved placeholder.
    resolved : bool
        Whether the node resolves to a concrete indexed symbol.

    Returns
    -------
    str
        Display label suitable for plain-text tree rendering.
    """
    if not resolved:
        return name
    if module is None:
        return name
    return f"{module}.{name}"


def _dot_node_id(index: int) -> str:
    """
    Return a deterministic DOT node identifier for one rendered tree node.

    Parameters
    ----------
    index : int
        Zero-based traversal index assigned during DOT emission.

    Returns
    -------
    str
        Stable Graphviz-safe node identifier.
    """
    return f"n{index}"


def _dot_escape(value: str) -> str:
    """
    Escape one string value for safe inclusion in DOT labels.

    Parameters
    ----------
    value : str
        Raw label value to escape.

    Returns
    -------
    str
        DOT-safe double-quoted label content.
    """
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _render_relation_tree_dot(
    tree: CallTreeResult,
    *,
    graph_name: str,
) -> list[str]:
    """
    Render a bounded relation tree as Graphviz DOT.

    Parameters
    ----------
    tree : codira.query.exact.CallTreeResult
        Traversal result to render.
    graph_name : str
        Stable graph name used in the DOT header.

    Returns
    -------
    list[str]
        Deterministic DOT lines describing the rendered bounded tree.
    """
    lines = [f"digraph {graph_name} {{", "  rankdir=LR;"]
    node_counter = 0
    root_id = _dot_node_id(node_counter)
    root_label = _dot_escape(
        _call_tree_display(tree.root_module, tree.root_name, resolved=True)
    )
    lines.append(f'  {root_id} [label="{root_label}"];')

    def append_children(
        parent_id: str,
        nodes: tuple[CallTreeNode, ...],
    ) -> None:
        nonlocal node_counter
        for node in nodes:
            node_counter += 1
            node_id = _dot_node_id(node_counter)
            node_label = _call_tree_display(
                node.module,
                node.name,
                resolved=node.resolved,
            )
            attributes = [f'label="{_dot_escape(node_label)}"']
            if not node.resolved:
                attributes.append('style="dashed"')
            if node.cycle:
                attributes.append('peripheries="2"')
            lines.append(f"  {node_id} [{', '.join(attributes)}];")
            if tree.incoming:
                lines.append(f"  {node_id} -> {parent_id};")
            else:
                lines.append(f"  {parent_id} -> {node_id};")
            append_children(node_id, node.children)

    append_children(root_id, tree.children)

    truncation_bits: list[str] = []
    if tree.truncated_by_depth:
        truncation_bits.append("max_depth")
    if tree.truncated_by_nodes:
        truncation_bits.append("max_nodes")
    if truncation_bits:
        lines.append(
            f'  graph [label="truncated by {", ".join(truncation_bits)}", labelloc="b"];'
        )
    lines.append("}")
    return lines


def _call_tree_node_payload(node: CallTreeNode) -> dict[str, object]:
    """
    Serialize one bounded call-tree node for JSON output.

    Parameters
    ----------
    node : codira.query.exact.CallTreeNode
        Tree node to serialize.

    Returns
    -------
    dict[str, object]
        JSON-serializable tree node payload.
    """
    payload: dict[str, object] = {
        "module": node.module,
        "name": node.name,
        "display": _call_tree_display(
            node.module,
            node.name,
            resolved=node.resolved,
        ),
        "resolved": node.resolved,
        "cycle": node.cycle,
        "children": [_call_tree_node_payload(child) for child in node.children],
    }
    if node.external_target_kind is not None:
        payload["external_target_kind"] = node.external_target_kind
    if node.external_target_name is not None:
        payload["external_target_name"] = node.external_target_name
    return payload


def _call_tree_result_payload(tree: CallTreeResult) -> dict[str, object]:
    """
    Serialize one bounded call-tree result for JSON output.

    Parameters
    ----------
    tree : codira.query.exact.CallTreeResult
        Traversal result to serialize.

    Returns
    -------
    dict[str, object]
        JSON-serializable root payload for the bounded tree.
    """
    return {
        "module": tree.root_module,
        "name": tree.root_name,
        "display": _call_tree_display(
            tree.root_module,
            tree.root_name,
            resolved=True,
        ),
        "resolved": True,
        "incoming": tree.incoming,
        "cycle": False,
        "children": [_call_tree_node_payload(child) for child in tree.children],
    }


def _render_call_tree_lines(tree: CallTreeResult) -> list[str]:
    """
    Render a bounded call tree as deterministic plain-text lines.

    Parameters
    ----------
    tree : codira.query.exact.CallTreeResult
        Traversal result to render.

    Returns
    -------
    list[str]
        Deterministic plain-text lines for the bounded tree.
    """
    lines = [
        _call_tree_display(
            tree.root_module,
            tree.root_name,
            resolved=True,
        )
    ]
    marker = "<- " if tree.incoming else "-> "

    def append_children(nodes: tuple[CallTreeNode, ...], *, depth: int) -> None:
        for node in nodes:
            suffix = " [cycle]" if node.cycle else ""
            lines.append(
                f"{'  ' * depth}{marker}"
                f"{_call_tree_display(node.module, node.name, resolved=node.resolved)}"
                f"{suffix}"
            )
            append_children(node.children, depth=depth + 1)

    append_children(tree.children, depth=1)
    return lines


def _render_relation_tree_lines(
    tree: CallTreeResult,
    *,
    outgoing_marker: str,
    incoming_marker: str,
) -> list[str]:
    """
    Render a bounded relation tree with caller-selected edge markers.

    Parameters
    ----------
    tree : codira.query.exact.CallTreeResult
        Traversal result to render.
    outgoing_marker : str
        Marker used for outgoing traversal edges.
    incoming_marker : str
        Marker used for incoming traversal edges.

    Returns
    -------
    list[str]
        Deterministic plain-text lines for the bounded relation tree.
    """
    lines = [
        _call_tree_display(
            tree.root_module,
            tree.root_name,
            resolved=True,
        )
    ]
    marker = incoming_marker if tree.incoming else outgoing_marker

    def append_children(nodes: tuple[CallTreeNode, ...], *, depth: int) -> None:
        for node in nodes:
            suffix = " [cycle]" if node.cycle else ""
            lines.append(
                f"{'  ' * depth}{marker}"
                f"{_call_tree_display(node.module, node.name, resolved=node.resolved)}"
                f"{suffix}"
            )
            append_children(node.children, depth=depth + 1)

    append_children(tree.children, depth=1)
    return lines


def _run_refs(
    request: RelationCommandRequest,
) -> int:
    """
    Print indexed callable-object references for one logical name.

    Parameters
    ----------
    request : RelationCommandRequest
        Runtime options for the refs command.

    Returns
    -------
    int
        Zero when at least one reference is found, otherwise one.
    """
    return _run_relation_command(
        request,
        RelationCommandSpec(
            command="refs",
            missing_message="callable references",
            graph_name="codira_refs",
            missing_direction_outgoing="owner",
            missing_direction_incoming="target",
            plain_arrow="=>",
            outgoing_tree_marker="=> ",
            incoming_tree_marker="<= ",
            source_module_key="owner_module",
            source_name_key="owner_name",
            target_module_key="target_module",
            target_name_key="target_name",
            row_fetcher=find_callable_refs,
            tree_builder=build_ref_tree,
        ),
    )


def _run_symbol_command(
    args: argparse.Namespace,
    root: Path,
    *,
    prefix: str | None,
    raw_prefix: str | None,
) -> int:
    """
    Run the ``sym`` command after index freshness checks.

    Parameters
    ----------
    args : argparse.Namespace
        Parsed command-line arguments.
    root : pathlib.Path
        Repository root containing the index.
    prefix : str | None
        Normalized absolute prefix used for backend filtering.
    raw_prefix : str | None
        User-facing repo-root-relative prefix echoed in JSON output.

    Returns
    -------
    int
        Process exit status for the symbol command.
    """
    _ensure_index(root)
    return _run_symbol(
        root,
        args.name,
        prefix=prefix,
        as_json=args.json,
        query_prefix=raw_prefix,
    )


def _run_architecture_report_command(args: argparse.Namespace, root: Path) -> int:
    """Render architecture-report artifacts from the current repository index.

    Parameters
    ----------
    args : argparse.Namespace
        Parsed architecture-report command arguments.
    root : pathlib.Path
        Repository root containing the index and default output location.

    Returns
    -------
    int
        Zero after all mandatory report artifacts are written.
    """
    _ensure_index(root)
    model = build_architecture_model_from_index(root)
    policy = _architecture_policy_from_arguments(args)
    analysis = analyze_architecture_policy(model, policy)
    output = (
        Path(args.output)
        if args.output is not None
        else root / ".codira" / "architecture-report"
    )
    result = write_architecture_artifacts(model, analysis, output)
    print(f"Wrote architecture report: {result.output_dir}")
    if result.warning is not None:
        print(f"[codira] {result.warning}", file=sys.stderr)
    return 0


def _architecture_policy_from_arguments(args: argparse.Namespace) -> ArchitecturePolicy:
    """Parse strict architecture layer policy arguments.

    Parameters
    ----------
    args : argparse.Namespace
        Parsed architecture-report command arguments.

    Returns
    -------
    codira.architecture.ArchitecturePolicy
        Ordered layers and explicit forbidden dependency rules.

    Raises
    ------
    ConfigError
        If one layer or forbidden-rule argument is malformed.
    """
    layers: list[ArchitectureLayer] = []
    for value in args.layer:
        name, separator, path_prefix = value.partition("=")
        if not separator or not name or not path_prefix:
            msg = "Architecture layers must use NAME=PATH_PREFIX."
            raise ConfigError(msg)
        layers.append(ArchitectureLayer(name=name, path_prefix=path_prefix))
    rules: list[ArchitectureForbiddenDependencyRule] = []
    for value in args.forbid:
        fields = value.split(":")
        if len(fields) != 4 or any(not field for field in fields):
            msg = (
                "Architecture forbidden rules must use "
                "RULE:SOURCE_LAYER:DESTINATION_LAYER:SEVERITY."
            )
            raise ConfigError(msg)
        rule_id, source_layer, destination_layer, severity = fields
        rules.append(
            ArchitectureForbiddenDependencyRule(
                rule_id=rule_id,
                source_layer=source_layer,
                destination_layer=destination_layer,
                severity=severity,
            )
        )
    return ArchitecturePolicy(
        layers=tuple(layers),
        forbidden_dependencies=tuple(rules),
    )


def _run_embeddings_command(
    args: argparse.Namespace,
    root: Path,
    *,
    prefix: str | None,
    raw_prefix: str | None,
) -> int:
    """
    Run the ``emb`` command after index freshness checks.

    Parameters
    ----------
    args : argparse.Namespace
        Parsed command-line arguments.
    root : pathlib.Path
        Repository root containing the index.
    prefix : str | None
        Normalized absolute prefix used for backend filtering.
    raw_prefix : str | None
        User-facing repo-root-relative prefix echoed in JSON output.

    Returns
    -------
    int
        Process exit status for the embedding command.

    Raises
    ------
    ConfigError
        If no query or maintenance submode is supplied, or if maintenance-only
        options are combined with a search query.
    """
    if args.query == "purge":
        return _run_embedding_purge_command(args, root)
    if args.query == "similarity-purge":
        return _run_similarity_purge_command(args, root)
    if args.query == "rebuild":
        return _run_embedding_rebuild_command(args, root)
    if args.query == "reset":
        return _run_embedding_reset_command(args, root)
    if args.query is None:
        msg = "codira emb requires a query, `purge`, `rebuild`, or `reset`"
        raise ConfigError(msg)
    if (
        args.stale
        or args.all_sets
        or args.dry_run
        or args.backend is not None
        or args.older_than is not None
        or args.keep
        or args.yes
    ):
        msg = "emb purge options require `codira emb purge`"
        raise ConfigError(msg)
    routing = _route_eligible_cli_read(
        root,
        "cli.emb",
        {
            "query": args.query,
            "limit": args.limit,
            "search_profile": args.search_profile,
            "as_json": args.json,
            "prefix": None if prefix is None else None,
            "query_prefix": raw_prefix,
        },
        supported=prefix is None,
    )
    if routing.stdout is not None:
        print(routing.stdout, end="")
        emit_execution_mode(routing, requested=args.execution_mode)
        return cast("int", routing.exit_code)
    _ensure_index(root)
    result = _run_embeddings(
        EmbeddingCommandRequest(
            root=root,
            query=args.query,
            limit=args.limit,
            prefix=prefix,
            as_json=args.json,
            query_prefix=raw_prefix,
            search_profile=args.search_profile,
        )
    )
    emit_execution_mode(routing, requested=args.execution_mode)
    return result


def _purge_result_payload(result: VectorStorePurgeResult) -> dict[str, object]:
    """
    Convert a vector-store purge result into JSON-compatible output.

    Parameters
    ----------
    result : codira.contracts.VectorStorePurgeResult
        Purge result from the active vector-store plugin.

    Returns
    -------
    dict[str, object]
        JSON-compatible result payload.
    """

    return {
        "store": result.store,
        "mode": result.mode,
        "dry_run": result.dry_run,
        "active_vector_set_id": result.active_vector_set_id,
        "stale_vector_sets": result.stale_vector_sets,
        "kept_stale_vector_sets": result.kept_stale_vector_sets,
        "deleted_vectors": result.deleted_vectors,
        "deleted_cached_vectors": result.deleted_cached_vectors,
        "deleted_pending_vectors": result.deleted_pending_vectors,
        "deleted_vector_sets": result.deleted_vector_sets,
        "size_before_bytes": result.size_before_bytes,
        "size_after_bytes": result.size_after_bytes,
        "note": result.note,
    }


def _run_embedding_rebuild_command(args: argparse.Namespace, root: Path) -> int:
    """Rebuild configured derived similarity state without embedding inference.

    Parameters
    ----------
    args : argparse.Namespace
        Parsed embedding command arguments.
    root : pathlib.Path
        Repository root whose derived semantic state is rebuilt.

    Returns
    -------
    int
        Zero after every authoritative snapshot was rebuilt consistently.

    Raises
    ------
    ConfigError
        If the source vector revision changes while the rebuild is running.
    """
    if (
        args.stale
        or args.all_sets
        or args.dry_run
        or args.backend
        or args.older_than
        or args.keep
        or args.yes
    ):
        msg = "emb rebuild does not accept purge options"
        raise ConfigError(msg)
    with acquire_index_lock(root):
        result = rebuild_active_similarity_index(root)
    if args.json:
        _emit_json(
            {
                "schema_version": QUERY_JSON_SCHEMA_VERSION,
                "command": "emb rebuild",
                "status": "ok",
                "index": result.index,
                "source_revisions": result.source_revisions,
            }
        )
    else:
        print(f"Rebuilt similarity index: {result.index}")
        print(f"Source revisions: {result.source_revisions}")
    return 0


def _run_embedding_reset_command(args: argparse.Namespace, root: Path) -> int:
    """Remove confirmed vector-store and selected similarity-index state.

    Parameters
    ----------
    args : argparse.Namespace
        Parsed embedding command arguments.
    root : pathlib.Path
        Repository root whose semantic state may be removed.

    Returns
    -------
    int
        Zero after confirmed plugin-owned persistent state is removed.

    Raises
    ------
    ConfigError
        If the destructive operation lacks explicit confirmation.
    """
    if not args.yes:
        msg = "codira emb reset requires --yes; semantic state is unrecoverable."
        raise ConfigError(msg)
    if (
        args.stale
        or args.all_sets
        or args.dry_run
        or args.backend
        or args.older_than
        or args.keep
    ):
        msg = "emb reset does not accept purge options"
        raise ConfigError(msg)
    with acquire_index_lock(root):
        vector_store = active_vector_store_reset_context(root)
        vector_result = vector_store.store.reset_persistent_state(
            VectorStoreResetRequest(root=root, config=vector_store.config)
        )
        similarity_result = reset_active_similarity_index(root)
    removed = vector_result.removed_artifacts
    if args.json:
        _emit_json(
            {
                "schema_version": QUERY_JSON_SCHEMA_VERSION,
                "command": "emb reset",
                "status": "ok",
                "removed": removed,
                "similarity_index": similarity_result.index,
                "removed_similarity_artifact_hashes": similarity_result.removed_artifact_hashes,
                "skipped_similarity_artifact_hashes": similarity_result.skipped_artifact_hashes,
                "next": "codira index --full",
            }
        )
    else:
        print("Removed semantic state: " + (", ".join(removed) or "none"))
        print(f"Cleaned similarity index: {similarity_result.index}")
        print("Next: codira index --full")
    return 0


def _run_similarity_purge_command(args: argparse.Namespace, root: Path) -> int:
    """Inventory or delete selected remote derived similarity-index artifacts.

    Parameters
    ----------
    args : argparse.Namespace
        Parsed embedding maintenance arguments.
    root : pathlib.Path
        Repository root owning the selected remote derived artifacts.

    Returns
    -------
    int
        Zero after a preview or explicitly confirmed cleanup.

    Raises
    ------
    ConfigError
        If vector-store purge options are mixed with remote cleanup.
    """

    if (
        args.stale
        or args.all_sets
        or args.backend is not None
        or args.older_than is not None
        or args.keep
    ):
        msg = "emb similarity-purge does not accept vector purge options"
        raise ConfigError(msg)
    preview = bool(args.dry_run or not args.yes)
    with acquire_index_lock(root):
        result = purge_active_similarity_index(root, preview=preview)
    payload = {
        "index": result.index,
        "preview": result.preview,
        "removed_artifact_hashes": result.removed_artifact_hashes,
        "skipped_artifact_hashes": result.skipped_artifact_hashes,
    }
    if args.json:
        _emit_json(
            {
                "schema_version": QUERY_JSON_SCHEMA_VERSION,
                "command": "emb similarity-purge",
                "status": "dry_run" if preview else "ok",
                "result": payload,
            }
        )
    else:
        verb = "Would delete" if preview else "Deleted"
        print(f"Similarity index: {result.index}")
        print(f"{verb} owned remote artifacts: {len(result.removed_artifact_hashes)}")
        print(f"Skipped remote artifacts: {len(result.skipped_artifact_hashes)}")
        if preview and not args.dry_run:
            print("Dry run only; pass --yes to delete.")
    return 0


def _run_embedding_purge_command(args: argparse.Namespace, root: Path) -> int:
    """
    Run ``codira emb purge`` against the active vector store.

    Parameters
    ----------
    args : argparse.Namespace
        Parsed embedding command arguments.
    root : pathlib.Path
        Repository root containing vector-store state.

    Returns
    -------
    int
        Zero after reporting or executing the purge.

    Raises
    ------
    ConfigError
        If purge retention options are invalid or incompatible.
    """

    stale = bool(args.stale)
    all_sets = bool(args.all_sets)
    dry_run = bool(args.dry_run or not args.yes)
    older_than = cast("int | None", args.older_than)
    keep = int(args.keep)
    if not stale and not all_sets:
        stale = True
    if older_than is not None and older_than < 0:
        msg = "--older-than must be >= 0"
        raise ConfigError(msg)
    if keep < 0:
        msg = "--keep must be >= 0"
        raise ConfigError(msg)
    if all_sets and (older_than is not None or keep):
        msg = "--older-than and --keep can only be used with --stale"
        raise ConfigError(msg)
    if not dry_run and not args.yes:
        msg = "codira emb purge requires --yes unless --dry-run is used"
        raise ConfigError(msg)

    context = active_vector_store_context(root, vector_store_name=args.backend)
    result = context.store.purge_vector_sets(
        VectorStorePurgeRequest(
            root=root,
            identity=context.identity,
            config=context.config,
            stale=stale,
            all_sets=all_sets,
            dry_run=dry_run,
            older_than_days=older_than,
            keep=keep,
        )
    )
    if args.json:
        _emit_json(
            {
                "schema_version": QUERY_JSON_SCHEMA_VERSION,
                "command": "emb purge",
                "status": "dry_run" if result.dry_run else "ok",
                "backend": context.store.name,
                "results": _purge_result_payload(result),
            }
        )
        return 0

    verb = "Would delete" if result.dry_run else "Deleted"
    print(f"Vector store backend: {context.store.name}")
    print(f"{verb} vector sets: {result.deleted_vector_sets}")
    print(f"{verb} materialized vectors: {result.deleted_vectors}")
    print(f"{verb} cached vectors: {result.deleted_cached_vectors}")
    print(f"{verb} pending vectors: {result.deleted_pending_vectors}")
    print(f"Kept stale vector sets: {result.kept_stale_vector_sets}")
    print(
        "Database size: "
        f"{_format_bytes(result.size_before_bytes)} -> "
        f"{_format_bytes(result.size_after_bytes)}"
    )
    if result.note:
        print(f"Note: {result.note}")
    if result.dry_run and not args.dry_run:
        print("Dry run only; pass --yes to delete.")
    return 0


def _run_docs_command(
    args: argparse.Namespace,
    root: Path,
    *,
    prefix: str | None,
    raw_prefix: str | None,
) -> int:
    """
    Run the ``docs`` command after index freshness checks.

    Parameters
    ----------
    args : argparse.Namespace
        Parsed command-line arguments.
    root : pathlib.Path
        Repository root containing the index.
    prefix : str | None
        Normalized absolute prefix used for backend filtering.
    raw_prefix : str | None
        User-facing repo-root-relative prefix echoed in JSON output.

    Returns
    -------
    int
        Process exit status for the documentation command.
    """
    _ensure_index(root)
    return _run_documentation_lookup(
        DocumentationCommandRequest(
            root=root,
            query=args.query,
            limit=args.limit,
            prefix=prefix,
            as_json=args.json,
            explain=args.explain,
            query_prefix=raw_prefix,
            search_profile=args.search_profile,
        )
    )


def _run_symbol_inventory_command(
    args: argparse.Namespace,
    root: Path,
    *,
    prefix: str | None,
    raw_prefix: str | None,
) -> int:
    """
    Run the ``symlist`` command after index freshness checks.

    Parameters
    ----------
    args : argparse.Namespace
        Parsed command-line arguments.
    root : pathlib.Path
        Repository root containing the index.
    prefix : str | None
        Normalized absolute prefix used for backend filtering.
    raw_prefix : str | None
        User-facing repo-root-relative prefix echoed in JSON output.

    Returns
    -------
    int
        Process exit status for the symbol inventory command.
    """
    _ensure_index(root)
    return _run_symbol_inventory(
        SymbolInventoryCommandRequest(
            root=root,
            prefix=prefix,
            include_tests=args.include_tests,
            limit=args.limit,
            as_json=args.json,
            query_prefix=raw_prefix,
        )
    )


def _validate_relation_output_flags(
    parser: argparse.ArgumentParser,
    *,
    command: str,
    dot: bool,
    tree: bool,
    as_json: bool,
) -> None:
    """
    Validate mutually constrained output flags for relation commands.

    Parameters
    ----------
    parser : argparse.ArgumentParser
        Active top-level parser used for error reporting.
    command : str
        Command name shown in parser errors.
    dot : bool
        Whether DOT output was requested.
    tree : bool
        Whether tree output was requested.
    as_json : bool
        Whether JSON output was requested.

    Returns
    -------
    None
        Invalid flag combinations terminate through ``parser.error``.
    """
    if dot and not tree:
        parser.error(f"--dot requires --tree for {command}")
    if dot and as_json:
        parser.error(f"--dot cannot be combined with --json for {command}")


def _run_relation_subcommand(
    request: RelationSubcommandRequest,
) -> int:
    """
    Run one relation-oriented subcommand after shared validation.

    Parameters
    ----------
    request : RelationSubcommandRequest
        Shared relation-subcommand runtime context.

    Returns
    -------
    int
        Process exit status for the relation command.
    """
    _validate_relation_output_flags(
        request.parser,
        command=request.command,
        dot=request.args.dot,
        tree=request.args.tree,
        as_json=request.args.json,
    )
    _ensure_index(request.root)
    relation_request = RelationCommandRequest(
        root=request.root,
        name=request.args.name,
        module=request.args.module,
        incoming=request.args.incoming,
        as_tree=request.args.tree,
        as_dot=request.args.dot,
        max_depth=request.args.max_depth,
        max_nodes=request.args.max_nodes,
        prefix=request.prefix,
        as_json=request.args.json,
        query_prefix=request.raw_prefix,
    )
    if request.command == "calls":
        return _run_calls(relation_request)
    return _run_refs(relation_request)


def _run_audit_command(
    args: argparse.Namespace,
    root: Path,
    *,
    prefix: str | None,
    raw_prefix: str | None,
) -> int:
    """
    Run the docstring audit command after index freshness checks.

    Parameters
    ----------
    args : argparse.Namespace
        Parsed command-line arguments.
    root : pathlib.Path
        Repository root containing the index.
    prefix : str | None
        Normalized absolute prefix used for backend filtering.
    raw_prefix : str | None
        User-facing repo-root-relative prefix echoed in JSON output.

    Returns
    -------
    int
        Process exit status for the audit command.
    """
    _ensure_index(root)
    return _run_audit_docstrings(
        root,
        prefix=prefix,
        as_json=args.json,
        query_prefix=raw_prefix,
    )


def _run_context_command(
    args: argparse.Namespace,
    root: Path,
    *,
    prefix: str | None,
) -> int:
    """
    Run the context command after index freshness checks.

    Parameters
    ----------
    args : argparse.Namespace
        Parsed command-line arguments.
    root : pathlib.Path
        Repository root containing the index.
    prefix : str | None
        Normalized absolute prefix used for backend filtering.

    Returns
    -------
    int
        Zero after printing the rendered context output.
    """
    routing = _route_eligible_cli_read(
        root,
        "cli.ctx",
        {
            "query": args.query,
            "as_json": args.json,
            "as_prompt": args.prompt,
            "explain": args.explain,
            "search_profile": args.search_profile,
        },
        supported=prefix is None,
    )
    if routing.stdout is not None:
        print(routing.stdout, end="")
        emit_execution_mode(routing, requested=args.execution_mode)
        return cast("int", routing.exit_code)
    _ensure_index(root)
    result = context_for(
        ContextRequest(
            root=root,
            query=args.query,
            prefix=prefix,
            as_json=args.json,
            as_prompt=args.prompt,
            explain=args.explain,
            search_profile=args.search_profile,
            max_source_file_bytes=(
                load_effective_config(
                    root=root
                ).embeddings.indexing.max_source_file_bytes
            ),
        )
    )
    print(result)
    emit_execution_mode(routing, requested=args.execution_mode)
    return 0


def _route_eligible_cli_read(
    root: Path,
    operation: str,
    arguments: dict[str, object],
    *,
    supported: bool = True,
) -> CliRouteResult:
    """Attempt one configuration-enabled CLI warm read without mutation.

    Parameters
    ----------
    root : pathlib.Path
        Resolved repository root for the current command.
    operation : str
        Fixed daemon CLI operation name.
    arguments : dict[str, object]
        Path-free request options.
    supported : bool, optional
        Whether this CLI invocation has a daemon-compatible option shape.

    Returns
    -------
    codira.query_daemon_cli.CliRouteResult
        Warm output when available, otherwise the direct/fallback state.
    """
    if not supported:
        return CliRouteResult(mode="direct")
    return route_cli_read(
        root,
        operation,
        arguments,
        enabled=load_effective_config(root=root).query_daemon.enabled,
    )


def build_query_daemon_cli_operations(
    root: Path,
) -> dict[
    str, Callable[[dict[str, object], BackendQueryConnection], dict[str, object]]
]:
    """Build fixed-root daemon handlers for eligible read-only CLI commands.

    Parameters
    ----------
    root : pathlib.Path
        Startup-trusted repository root.

    Returns
    -------
    dict[str, object]
        IPC operation handlers that preserve CLI stdout and exit codes.
    """
    trusted_root = root.resolve()

    def required(arguments: dict[str, object], name: str) -> str:
        """Return one required string request value.

        Parameters
        ----------
        arguments : dict[str, object]
            IPC request arguments.
        name : str
            Required argument name.

        Returns
        -------
        str
            Validated string value.

        Raises
        ------
        TypeError
            If the request value is not a string.
        """
        value = arguments.get(name)
        if not isinstance(value, str):
            msg = f"CLI daemon argument must be a string: {name}."
            raise TypeError(msg)
        return value

    def optional_bool(arguments: dict[str, object], name: str) -> bool:
        """Return one optional boolean request value.

        Parameters
        ----------
        arguments : dict[str, object]
            IPC request arguments.
        name : str
            Optional argument name.

        Returns
        -------
        bool
            Validated value or ``False``.

        Raises
        ------
        TypeError
            If the request value is not boolean.
        """
        value = arguments.get(name, False)
        if not isinstance(value, bool):
            msg = f"CLI daemon argument must be boolean: {name}."
            raise TypeError(msg)
        return value

    def capture(operation: Callable[[], int]) -> dict[str, object]:
        """Capture one existing CLI renderer without changing its output.

        Parameters
        ----------
        operation : collections.abc.Callable[[], int]
            Read-only CLI implementation to execute in the warm worker.

        Returns
        -------
        dict[str, object]
            Captured stdout and original exit code.
        """
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            exit_code = operation()
        return {"stdout": output.getvalue(), "exit_code": exit_code}

    def context_handler(
        arguments: dict[str, object], _connection: BackendQueryConnection
    ) -> dict[str, object]:
        """Execute a daemon-owned context read.

        Parameters
        ----------
        arguments : dict[str, object]
            Path-free context CLI arguments.
        _connection : object
            Active warm connection retained by the worker.

        Returns
        -------
        dict[str, object]
            Captured CLI output and exit code.
        """
        return capture(
            lambda: _run_context_without_freshness_check(
                trusted_root,
                query=required(arguments, "query"),
                as_json=optional_bool(arguments, "as_json"),
                as_prompt=optional_bool(arguments, "as_prompt"),
                explain=optional_bool(arguments, "explain"),
                search_profile=cast("str | None", arguments.get("search_profile")),
            )
        )

    def embedding_handler(
        arguments: dict[str, object], _connection: BackendQueryConnection
    ) -> dict[str, object]:
        """Execute a daemon-owned embedding-search read.

        Parameters
        ----------
        arguments : dict[str, object]
            Path-free embedding CLI arguments.
        _connection : object
            Active warm connection retained by the worker.

        Returns
        -------
        dict[str, object]
            Captured CLI output and exit code.
        """
        limit = arguments.get("limit")
        if not isinstance(limit, int) or limit <= 0:
            msg = "CLI daemon embedding limit must be positive."
            raise TypeError(msg)
        return capture(
            lambda: _run_embeddings(
                EmbeddingCommandRequest(
                    root=trusted_root,
                    query=required(arguments, "query"),
                    limit=limit,
                    prefix=None,
                    as_json=optional_bool(arguments, "as_json"),
                    query_prefix=cast("str | None", arguments.get("query_prefix")),
                    search_profile=cast("str | None", arguments.get("search_profile")),
                )
            )
        )

    def plugins_handler(
        arguments: dict[str, object], _connection: BackendQueryConnection
    ) -> dict[str, object]:
        """Execute daemon-owned plugin diagnostics.

        Parameters
        ----------
        arguments : dict[str, object]
            Path-free plugin CLI arguments.
        _connection : object
            Active warm connection retained by the worker.

        Returns
        -------
        dict[str, object]
            Captured CLI output and exit code.
        """
        from codira.cli_operations import _run_plugins

        return capture(
            lambda: _run_plugins(
                root=trusted_root, as_json=optional_bool(arguments, "as_json")
            )
        )

    def capabilities_handler(
        arguments: dict[str, object], _connection: BackendQueryConnection
    ) -> dict[str, object]:
        """Execute daemon-owned capability diagnostics.

        Parameters
        ----------
        arguments : dict[str, object]
            Path-free capability CLI arguments.
        _connection : object
            Active warm connection retained by the worker.

        Returns
        -------
        dict[str, object]
            Captured CLI output and exit code.
        """
        return capture(
            lambda: _run_capabilities(
                root=trusted_root,
                as_json=optional_bool(arguments, "as_json"),
                strict=optional_bool(arguments, "strict"),
            )
        )

    return {
        "cli.ctx": context_handler,
        "cli.emb": embedding_handler,
        "cli.plugins": plugins_handler,
        "cli.caps": capabilities_handler,
    }


def _run_context_without_freshness_check(  # noqa: PLR0913
    root: Path,
    *,
    query: str,
    as_json: bool,
    as_prompt: bool,
    explain: bool,
    search_profile: str | None,
) -> int:
    """Render context in the daemon after its generation check already passed.

    Parameters
    ----------
    root : pathlib.Path
        Startup-trusted repository root.
    query : str
        Context retrieval query.
    as_json : bool
        Whether to render structured JSON.
    as_prompt : bool
        Whether to render a prompt.
    explain : bool
        Whether to render retrieval diagnostics.
    search_profile : str | None
        Named similarity-index runtime profile for semantic retrieval channels.

    Returns
    -------
    int
        Zero after emitting the existing context rendering.
    """
    print(
        context_for(
            ContextRequest(
                root=root,
                query=query,
                prefix=None,
                as_json=as_json,
                as_prompt=as_prompt,
                explain=explain,
                search_profile=search_profile,
                max_source_file_bytes=(
                    load_effective_config(
                        root=root
                    ).embeddings.indexing.max_source_file_bytes
                ),
            )
        )
    )
    return 0


def _config_origin_payload(origin: ConfigOrigin) -> dict[str, object]:
    """
    Convert config origin metadata into a JSON-friendly mapping.

    Parameters
    ----------
    origin : object
        Origin object returned by the config layer.

    Returns
    -------
    dict[str, object]
        JSON-serializable origin payload.
    """

    return {
        "level": origin.level,
        "path": None if origin.path is None else str(origin.path),
        "detail": origin.detail,
    }
