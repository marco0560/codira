"""First-party SQLite backend plugin package for codira.

Responsibilities
----------------
- Publish the canonical SQLite backend through the `codira.backends` entry-point group.
- Own the concrete SQLite backend implementation at the package boundary.
- Keep the package-facing backend factory explicit and deterministic.

Design principles
-----------------
The package owns the runtime backend implementation while reusing stable
storage and indexing helpers from core during the Phase 2 migration.

Architectural role
------------------
This module belongs to the **first-party backend plugin layer** introduced by
ADR-012.
"""

from __future__ import annotations

import json
import sqlite3
from typing import TYPE_CHECKING, cast

from codira.contracts import (
    BackendEmbeddingCandidatesRequest,
    BackendError,
    BackendPersistAnalysisRequest,
    BackendRelationQueryRequest,
    BackendRuntimeInventoryRequest,
)
from codira.prefix import normalize_prefix, prefix_clause
from codira.schema import SCHEMA_VERSION
from codira.semantic.embeddings import (
    EmbeddingBackendSpec,
    deserialize_vector,
    embed_text,
    get_embedding_backend,
)
from codira.sqlite_backend_support import (
    _count_reused_embeddings,
    _current_embedding_state_matches,
    _clear_index_tables,
    _delete_indexed_file_data,
    _dot_similarity,
    _load_existing_file_hashes,
    _load_existing_file_ownership,
    _load_previous_embeddings_by_path,
    _prune_orphaned_embeddings,
    _purge_skipped_docstring_issues,
    _rebuild_graph_indexes,
    _store_analysis,
)
from codira.storage import get_db_path, init_db

if TYPE_CHECKING:
    from pathlib import Path

    from codira.contracts import IndexBackend
    from codira.sqlite_backend_support import StoredEmbeddingRow
    from codira.types import (
        ChannelResults,
        DocstringIssueRow,
        EnumMemberRow,
        IncludeEdgeRow,
        OverloadRow,
        SymbolRow,
    )

CallEdgeRow = tuple[str, str, str | None, str | None, int]
CallableRefRow = tuple[str, str, str | None, str | None, int]
EmbeddingInventoryRow = tuple[str, str, int, int]

__all__ = ["SQLiteIndexBackend", "build_backend"]


class SQLiteIndexBackend:
    """
    Concrete SQLite backend exposed from the package boundary.

    This backend keeps the existing SQLite schema and query semantics stable
    while concentrating indexing-side persistence behind the package-owned
    implementation.
    """

    name = "sqlite"
    version = SCHEMA_VERSION

    def load_runtime_inventory(
        self,
        root: Path,
        *,
        conn: sqlite3.Connection | None = None,
    ) -> tuple[str, str, int] | None:
        """
        Return persisted backend and coverage metadata for the last index run.

        Parameters
        ----------
        root : pathlib.Path
            Repository root whose index should be queried.
        conn : sqlite3.Connection | None, optional
            Existing SQLite connection to reuse.

        Returns
        -------
        tuple[str, str, int] | None
            Stored ``(backend_name, backend_version, coverage_complete)``
            tuple, or ``None`` when no runtime inventory has been recorded.
        """
        owns_connection = conn is None
        if conn is None:
            conn = self.open_connection(root)
        try:
            row = conn.execute("""
                SELECT backend_name, backend_version, coverage_complete
                FROM index_runtime
                WHERE singleton = 1
                """).fetchone()
            if row is None:
                return None
            return (str(row[0]), str(row[1]), int(row[2]))
        finally:
            if owns_connection:
                conn.close()

    def load_analyzer_inventory(
        self,
        root: Path,
        *,
        conn: sqlite3.Connection | None = None,
    ) -> list[tuple[str, str, str]]:
        """
        Return persisted analyzer inventory for the last index run.

        Parameters
        ----------
        root : pathlib.Path
            Repository root whose index should be queried.
        conn : sqlite3.Connection | None, optional
            Existing SQLite connection to reuse.

        Returns
        -------
        list[tuple[str, str, str]]
            Stored analyzer rows as ``(name, version, discovery_globs_json)``
            ordered by analyzer name.
        """
        owns_connection = conn is None
        if conn is None:
            conn = self.open_connection(root)
        try:
            rows = conn.execute("""
                SELECT name, version, discovery_globs
                FROM index_analyzers
                ORDER BY name
                """).fetchall()
            return [
                (str(name), str(version), str(globs)) for name, version, globs in rows
            ]
        finally:
            if owns_connection:
                conn.close()

    def initialize(self, root: Path) -> None:
        """
        Prepare the repository-local SQLite database.

        Parameters
        ----------
        root : pathlib.Path
            Repository root whose backend state should exist.

        Returns
        -------
        None
            The SQLite schema is created or refreshed in place.
        """
        init_db(root)

    def open_connection(self, root: Path) -> sqlite3.Connection:
        """
        Open a SQLite connection for one repository index.

        Parameters
        ----------
        root : pathlib.Path
            Repository root whose index database should be opened.

        Returns
        -------
        sqlite3.Connection
            Open SQLite connection.
        """
        if not get_db_path(root).exists():
            self.initialize(root)
        return sqlite3.connect(get_db_path(root))

    def list_symbols_in_module(
        self,
        root: Path,
        module: str,
        *,
        prefix: str | None = None,
        limit: int = 20,
        conn: sqlite3.Connection | None = None,
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
        conn : sqlite3.Connection | None, optional
            Existing SQLite connection to reuse.

        Returns
        -------
        list[codira.types.SymbolRow]
            Indexed symbols belonging to the requested module.
        """
        owns_connection = conn is None
        if conn is None:
            conn = self.open_connection(root)
        try:
            normalized_prefix = normalize_prefix(root, prefix)
            prefix_sql, prefix_params = prefix_clause(normalized_prefix, "f.path")
            rows = conn.execute(
                f"""
                SELECT s.type, s.module_name, s.name, f.path, s.lineno
                FROM symbol_index s
                JOIN files f
                  ON s.file_id = f.id
                WHERE s.module_name = ?
                {prefix_sql}
                LIMIT ?
                """,
                (module, *prefix_params, limit),
            ).fetchall()
            return [
                (str(t), str(m), str(n), str(f), int(lineno))
                for t, m, n, f, lineno in rows
            ]
        finally:
            if owns_connection:
                conn.close()

    def find_symbol(
        self,
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
            Repository root whose index should be queried.
        name : str
            Exact symbol name to search for.
        prefix : str | None, optional
            Repo-root-relative path prefix used to restrict symbol files.
        conn : sqlite3.Connection | None, optional
            Existing SQLite connection to reuse.

        Returns
        -------
        list[codira.types.SymbolRow]
            Matching symbol rows ordered deterministically.
        """
        owns_connection = conn is None
        normalized_prefix = normalize_prefix(root, prefix)
        if conn is None:
            conn = self.open_connection(root)
        try:
            prefix_sql, prefix_params = prefix_clause(normalized_prefix, "f.path")
            rows = conn.execute(
                f"""
                SELECT s.type, s.module_name, s.name, f.path, s.lineno
                FROM symbol_index s
                JOIN files f
                  ON s.file_id = f.id
                WHERE s.name = ?
                {prefix_sql}
                ORDER BY s.type, s.module_name, f.path, s.lineno
                """,
                (name, *prefix_params),
            ).fetchall()
            return [
                (str(t), str(m), str(n), str(f), int(lineno))
                for t, m, n, f, lineno in rows
            ]
        finally:
            if owns_connection:
                conn.close()

    def find_symbol_overloads(
        self,
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
            Repository root whose index should be queried.
        symbol : codira.types.SymbolRow
            Canonical function or method symbol row.
        conn : sqlite3.Connection | None, optional
            Existing SQLite connection to reuse.

        Returns
        -------
        list[codira.types.OverloadRow]
            Ordered overload metadata rows for the symbol.
        """
        symbol_type, module_name, symbol_name, file_path, lineno = symbol
        if symbol_type not in {"function", "method"}:
            return []

        owns_connection = conn is None
        if conn is None:
            conn = self.open_connection(root)
        try:
            rows = conn.execute(
                """
                SELECT
                    o.stable_id,
                    o.parent_stable_id,
                    o.ordinal,
                    o.signature,
                    o.lineno,
                    o.end_lineno,
                    o.docstring
                FROM overloads o
                JOIN functions fn
                  ON o.function_id = fn.id
                JOIN modules m
                  ON fn.module_id = m.id
                JOIN files f
                  ON m.file_id = f.id
                WHERE f.path = ?
                  AND m.name = ?
                  AND fn.name = ?
                  AND fn.lineno = ?
                  AND fn.is_method = ?
                ORDER BY o.lineno, o.ordinal
                """,
                (
                    file_path,
                    module_name,
                    symbol_name,
                    lineno,
                    1 if symbol_type == "method" else 0,
                ),
            ).fetchall()
            return [
                (
                    str(stable_id),
                    str(parent_stable_id),
                    int(ordinal),
                    str(signature),
                    int(overload_lineno),
                    None if end_lineno is None else int(end_lineno),
                    None if docstring is None else str(docstring),
                )
                for (
                    stable_id,
                    parent_stable_id,
                    ordinal,
                    signature,
                    overload_lineno,
                    end_lineno,
                    docstring,
                ) in rows
            ]
        finally:
            if owns_connection:
                conn.close()

    def find_symbol_enum_members(
        self,
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
            Repository root whose index should be queried.
        symbol : codira.types.SymbolRow
            Canonical enum symbol row.
        conn : sqlite3.Connection | None, optional
            Existing SQLite connection to reuse.

        Returns
        -------
        list[codira.types.EnumMemberRow]
            Ordered enum-member metadata rows for the symbol.
        """
        symbol_type, module_name, symbol_name, file_path, lineno = symbol
        if symbol_type != "enum":
            return []

        owns_connection = conn is None
        if conn is None:
            conn = self.open_connection(root)
        try:
            rows = conn.execute(
                """
                SELECT
                    stable_id,
                    parent_stable_id,
                    ordinal,
                    name,
                    signature,
                    lineno
                FROM enum_members
                WHERE file_id = (
                    SELECT id
                    FROM files
                    WHERE path = ?
                )
                  AND module_name = ?
                  AND symbol_name = ?
                  AND symbol_lineno = ?
                ORDER BY ordinal, lineno, name
                """,
                (
                    file_path,
                    module_name,
                    symbol_name,
                    lineno,
                ),
            ).fetchall()
            return [
                (
                    str(stable_id),
                    str(parent_stable_id),
                    int(ordinal),
                    str(member_name),
                    str(signature),
                    int(member_lineno),
                )
                for (
                    stable_id,
                    parent_stable_id,
                    ordinal,
                    member_name,
                    signature,
                    member_lineno,
                ) in rows
            ]
        finally:
            if owns_connection:
                conn.close()

    def docstring_issues(
        self,
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
            Repository root whose index should be queried.
        prefix : str | None, optional
            Repo-root-relative path prefix used to restrict issue ownership.
        conn : sqlite3.Connection | None, optional
            Existing SQLite connection to reuse.

        Returns
        -------
        list[codira.types.DocstringIssueRow]
            Issue rows with issue text, stable identity, and defining
            location metadata.
        """
        owns_connection = conn is None
        normalized_prefix = normalize_prefix(root, prefix)
        if conn is None:
            conn = self.open_connection(root)
        try:
            prefix_sql, prefix_params = prefix_clause(normalized_prefix, "f.path")
            rows = conn.execute(
                f"""
                SELECT
                    di.issue_type,
                    di.message,
                    COALESCE(si_fn.stable_id, si_cls.stable_id, si_mod.stable_id, '') AS stable_id,
                    CASE
                        WHEN di.function_id IS NOT NULL AND fn.is_method = 1 THEN 'method'
                        WHEN di.function_id IS NOT NULL THEN 'function'
                        WHEN di.class_id IS NOT NULL THEN 'class'
                        ELSE 'module'
                    END AS symbol_type,
                    COALESCE(fn_mod.name, cls_mod.name, mod.name, '') AS module_name,
                    CASE
                        WHEN di.function_id IS NOT NULL AND fn.is_method = 1
                            THEN cls.name || '.' || fn.name
                        WHEN di.function_id IS NOT NULL THEN fn.name
                        WHEN di.class_id IS NOT NULL THEN cls.name
                        ELSE COALESCE(mod.name, '')
                    END AS symbol_name,
                    f.path,
                    CASE
                        WHEN di.function_id IS NOT NULL THEN fn.lineno
                        WHEN di.class_id IS NOT NULL THEN cls.lineno
                        ELSE 1
                    END AS lineno,
                    CASE
                        WHEN di.function_id IS NOT NULL THEN fn.end_lineno
                        WHEN di.class_id IS NOT NULL THEN cls.end_lineno
                        ELSE NULL
                    END AS end_lineno
                FROM docstring_issues di
                JOIN files f
                  ON di.file_id = f.id
                LEFT JOIN functions fn
                  ON di.function_id = fn.id
                LEFT JOIN classes cls
                  ON cls.id = COALESCE(di.class_id, fn.class_id)
                LEFT JOIN modules fn_mod
                  ON fn.module_id = fn_mod.id
                LEFT JOIN modules cls_mod
                  ON cls.module_id = cls_mod.id
                LEFT JOIN modules mod
                  ON di.module_id = mod.id
                LEFT JOIN symbol_index si_fn
                  ON di.function_id IS NOT NULL
                 AND si_fn.file_id = di.file_id
                 AND si_fn.type = CASE
                     WHEN fn.is_method = 1 THEN 'method'
                     ELSE 'function'
                 END
                 AND si_fn.module_name = fn_mod.name
                 AND si_fn.name = fn.name
                 AND si_fn.lineno = fn.lineno
                LEFT JOIN symbol_index si_cls
                  ON di.class_id IS NOT NULL
                 AND si_cls.file_id = di.file_id
                 AND si_cls.type = 'class'
                 AND si_cls.module_name = cls_mod.name
                 AND si_cls.name = cls.name
                 AND si_cls.lineno = cls.lineno
                LEFT JOIN symbol_index si_mod
                  ON di.module_id IS NOT NULL
                 AND si_mod.file_id = di.file_id
                 AND si_mod.type = 'module'
                 AND si_mod.module_name = mod.name
                 AND si_mod.name = mod.name
                 AND si_mod.lineno = 1
                WHERE 1 = 1
                {prefix_sql}
                ORDER BY di.issue_type, f.path, lineno, di.message
                """,
                tuple(prefix_params),
            ).fetchall()
            return [
                (
                    str(issue_type),
                    str(message),
                    str(stable_id),
                    str(symbol_type),
                    str(module_name),
                    str(symbol_name),
                    str(file_path),
                    int(lineno),
                    None if end_lineno is None else int(end_lineno),
                )
                for (
                    issue_type,
                    message,
                    stable_id,
                    symbol_type,
                    module_name,
                    symbol_name,
                    file_path,
                    lineno,
                    end_lineno,
                ) in rows
            ]
        finally:
            if owns_connection:
                conn.close()

    def find_call_edges(
        self,
        request: BackendRelationQueryRequest,
    ) -> list[CallEdgeRow]:
        """
        Find exact call edges for a caller or callee logical name.

        Parameters
        ----------
        request : BackendRelationQueryRequest
            Exact relation lookup request.

        Returns
        -------
        list[tuple[str, str, str | None, str | None, int]]
            Matching call-edge rows ordered deterministically.
        """
        root = request.root
        name = request.name
        module = request.module
        incoming = request.incoming
        prefix = request.prefix
        conn = cast("sqlite3.Connection | None", request.conn)
        owns_connection = conn is None
        normalized_prefix = normalize_prefix(root, prefix)
        if conn is None:
            conn = self.open_connection(root)

        direction_column = "callee_name" if incoming else "caller_name"
        module_column = "callee_module" if incoming else "caller_module"
        prefix_sql, prefix_params = prefix_clause(normalized_prefix, "f.path")

        query = f"""
            SELECT
                ce.caller_module,
                ce.caller_name,
                ce.callee_module,
                ce.callee_name,
                ce.resolved
            FROM call_edges ce
            JOIN files f
              ON ce.caller_file_id = f.id
            WHERE {direction_column} = ?
            {prefix_sql}
        """
        params: list[str] = [name, *prefix_params]

        if module is not None:
            query += f" AND {module_column} = ?"
            params.append(module)

        query += """
            ORDER BY
                caller_module,
                caller_name,
                COALESCE(callee_module, ''),
                COALESCE(callee_name, ''),
                resolved
        """

        try:
            rows = conn.execute(query, tuple(params)).fetchall()
            return [
                (
                    str(caller_module),
                    str(caller_name),
                    None if callee_module is None else str(callee_module),
                    None if callee_name is None else str(callee_name),
                    int(resolved),
                )
                for (
                    caller_module,
                    caller_name,
                    callee_module,
                    callee_name,
                    resolved,
                ) in rows
            ]
        finally:
            if owns_connection:
                conn.close()

    def find_callable_refs(
        self,
        request: BackendRelationQueryRequest,
    ) -> list[CallableRefRow]:
        """
        Find exact callable-object references for an owner or target.

        Parameters
        ----------
        request : BackendRelationQueryRequest
            Exact relation lookup request.

        Returns
        -------
        list[tuple[str, str, str | None, str | None, int]]
            Matching callable-reference rows ordered deterministically.
        """
        root = request.root
        name = request.name
        module = request.module
        incoming = request.incoming
        prefix = request.prefix
        conn = cast("sqlite3.Connection | None", request.conn)
        owns_connection = conn is None
        normalized_prefix = normalize_prefix(root, prefix)
        if conn is None:
            conn = self.open_connection(root)

        direction_column = "target_name" if incoming else "owner_name"
        module_column = "target_module" if incoming else "owner_module"
        prefix_sql, prefix_params = prefix_clause(normalized_prefix, "f.path")

        query = f"""
            SELECT
                cr.owner_module,
                cr.owner_name,
                cr.target_module,
                cr.target_name,
                cr.resolved
            FROM callable_refs cr
            JOIN files f
              ON cr.owner_file_id = f.id
            WHERE {direction_column} = ?
            {prefix_sql}
        """
        params: list[str] = [name, *prefix_params]

        if module is not None:
            query += f" AND {module_column} = ?"
            params.append(module)

        query += """
            ORDER BY
                owner_module,
                owner_name,
                COALESCE(target_module, ''),
                COALESCE(target_name, ''),
                resolved
        """

        try:
            rows = conn.execute(query, tuple(params)).fetchall()
            return [
                (
                    str(owner_module),
                    str(owner_name),
                    None if target_module is None else str(target_module),
                    None if target_name is None else str(target_name),
                    int(resolved),
                )
                for (
                    owner_module,
                    owner_name,
                    target_module,
                    target_name,
                    resolved,
                ) in rows
            ]
        finally:
            if owns_connection:
                conn.close()

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
        root = request.root
        name = request.name
        module = request.module
        incoming = request.incoming
        prefix = request.prefix
        conn = cast("sqlite3.Connection | None", request.conn)
        owns_connection = conn is None
        normalized_prefix = normalize_prefix(root, prefix)
        if conn is None:
            conn = self.open_connection(root)

        prefix_sql, prefix_params = prefix_clause(normalized_prefix, "f.path")
        query = f"""
            SELECT
                m.name,
                i.name,
                i.kind,
                i.lineno
            FROM imports i
            JOIN modules m
              ON i.module_id = m.id
            JOIN files f
              ON m.file_id = f.id
            WHERE i.kind IN ('include_local', 'include_system')
            {prefix_sql}
        """
        params: list[str] = [*prefix_params]

        if incoming:
            query += " AND i.name = ?"
            params.append(name)
            if module is not None:
                query += " AND m.name = ?"
                params.append(module)
        else:
            query += " AND m.name = ?"
            params.append(name)

        query += """
            ORDER BY
                m.name,
                i.lineno,
                i.name,
                i.kind
        """

        try:
            rows = conn.execute(query, tuple(params)).fetchall()
            return [
                (str(owner_module), str(target_name), str(kind), int(lineno))
                for owner_module, target_name, kind, lineno in rows
            ]
        finally:
            if owns_connection:
                conn.close()

    def find_logical_symbols(
        self,
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
            Repository root whose index should be queried.
        module_name : str
            Dotted module that owns the logical symbol.
        logical_name : str
            Logical symbol identity such as ``helper`` or ``Class.method``.
        prefix : str | None, optional
            Repo-root-relative path prefix used to restrict symbol files.
        conn : sqlite3.Connection | None, optional
            Existing SQLite connection to reuse.

        Returns
        -------
        list[codira.types.SymbolRow]
            Matching indexed symbol rows ordered deterministically.
        """
        owns_connection = conn is None
        normalized_prefix = normalize_prefix(root, prefix)
        if conn is None:
            conn = self.open_connection(root)

        try:
            if "." in logical_name:
                class_name, method_name = logical_name.rsplit(".", 1)
                prefix_sql, prefix_params = prefix_clause(normalized_prefix, "fp.path")
                rows = conn.execute(
                    f"""
                    SELECT
                        s.type,
                        s.module_name,
                        s.name,
                        fp.path,
                        s.lineno
                    FROM functions fn
                    JOIN classes c
                      ON fn.class_id = c.id
                    JOIN modules m
                      ON fn.module_id = m.id
                    JOIN symbol_index s
                      ON s.type = 'method'
                     AND s.module_name = m.name
                     AND s.name = fn.name
                     AND s.lineno = fn.lineno
                    JOIN files fp
                      ON s.file_id = fp.id
                    WHERE m.name = ? AND c.name = ? AND fn.name = ?
                    {prefix_sql}
                    ORDER BY fp.path, s.lineno, s.name
                    """,
                    (module_name, class_name, method_name, *prefix_params),
                ).fetchall()
            else:
                prefix_sql, prefix_params = prefix_clause(normalized_prefix, "f.path")
                rows = conn.execute(
                    f"""
                    SELECT s.type, s.module_name, s.name, f.path, s.lineno
                    FROM symbol_index s
                    JOIN files f
                      ON s.file_id = f.id
                    WHERE s.module_name = ?
                      AND (s.name = ? OR (s.type = 'module' AND s.module_name = ?))
                    {prefix_sql}
                    ORDER BY s.type, s.module_name, f.path, s.lineno
                    """,
                    (module_name, logical_name, logical_name, *prefix_params),
                ).fetchall()

            return [
                (str(t), str(m), str(n), str(f), int(lineno))
                for t, m, n, f, lineno in rows
            ]
        finally:
            if owns_connection:
                conn.close()

    def logical_symbol_name(
        self,
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
            Repository root whose index should be queried.
        symbol : codira.types.SymbolRow
            Indexed symbol row whose logical identity should be resolved.
        conn : sqlite3.Connection | None, optional
            Existing SQLite connection to reuse.

        Returns
        -------
        str
            Logical symbol identity used by call edges and callable references.
        """
        symbol_type, module_name, name, _file_path, lineno = symbol
        if symbol_type != "method":
            return module_name if symbol_type == "module" else name

        owns_connection = conn is None
        if conn is None:
            conn = self.open_connection(root)

        try:
            row = conn.execute(
                """
                SELECT c.name
                FROM functions f
                JOIN classes c
                  ON f.class_id = c.id
                JOIN modules m
                  ON f.module_id = m.id
                WHERE m.name = ? AND f.name = ? AND f.lineno = ?
                ORDER BY c.name
                LIMIT 1
                """,
                (module_name, name, lineno),
            ).fetchone()
            if row is None:
                return name
            return f"{str(row[0])}.{name}"
        finally:
            if owns_connection:
                conn.close()

    def embedding_inventory(
        self,
        root: Path,
        *,
        conn: sqlite3.Connection | None = None,
    ) -> list[EmbeddingInventoryRow]:
        """
        Return stored embedding inventory grouped by backend metadata.

        Parameters
        ----------
        root : pathlib.Path
            Repository root whose index should be queried.
        conn : sqlite3.Connection | None, optional
            Existing SQLite connection to reuse.

        Returns
        -------
        list[tuple[str, str, int, int]]
            Rows as ``(backend, version, dim, count)`` ordered deterministically.
        """
        owns_connection = conn is None
        if conn is None:
            conn = self.open_connection(root)
        try:
            rows = conn.execute("""
                SELECT backend, version, dim, COUNT(*)
                FROM embeddings
                GROUP BY backend, version, dim
                ORDER BY backend, version, dim
                """).fetchall()
            return [
                (str(backend), str(version), int(dim), int(count))
                for backend, version, dim, count in rows
            ]
        finally:
            if owns_connection:
                conn.close()

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
            Ranked symbol candidates ordered by descending similarity and stable
            symbol identity.
        """
        root = request.root
        query = request.query
        limit = request.limit
        min_score = request.min_score
        prefix = request.prefix
        conn = cast("sqlite3.Connection | None", request.conn)
        owns_connection = conn is None
        normalized_prefix = normalize_prefix(root, prefix)
        if conn is None:
            conn = self.open_connection(root)

        backend = get_embedding_backend()
        query_vector = embed_text(query)
        if not any(query_vector):
            return []

        try:
            prefix_sql, prefix_params = prefix_clause(normalized_prefix, "f.path")
            rows = conn.execute(
                f"""
                SELECT
                    s.type,
                    s.module_name,
                    s.name,
                    f.path,
                    s.lineno,
                    e.version,
                    e.dim,
                    e.vector
                FROM embeddings e
                JOIN symbol_index s
                  ON e.object_type = 'symbol'
                 AND e.object_id = s.id
                JOIN files f
                  ON s.file_id = f.id
                WHERE e.backend = ? AND e.version = ?
                {prefix_sql}
                ORDER BY s.module_name, s.name, f.path, s.lineno, s.type
                """,
                (backend.name, backend.version, *prefix_params),
            ).fetchall()

            results: ChannelResults = []

            for row in rows:
                symbol: SymbolRow = (
                    str(row[0]),
                    str(row[1]),
                    str(row[2]),
                    str(row[3]),
                    int(row[4]),
                )
                version = str(row[5])
                dim = int(row[6])
                blob = bytes(row[7])
                if version != backend.version or dim != backend.dim:
                    continue

                score = _dot_similarity(query_vector, deserialize_vector(blob, dim=dim))
                if score < min_score:
                    continue

                results.append((score, symbol))

            results.sort(
                key=lambda item: (
                    -item[0],
                    item[1][1],
                    item[1][2],
                    item[1][3],
                    item[1][4],
                    item[1][0],
                )
            )
            return results[:limit]
        finally:
            if owns_connection:
                conn.close()

    def prune_orphaned_embeddings(
        self,
        root: Path,
        *,
        conn: sqlite3.Connection | None = None,
    ) -> None:
        """
        Remove embedding rows whose owning symbol no longer exists.

        Parameters
        ----------
        root : pathlib.Path
            Repository root whose index should be cleaned.
        conn : sqlite3.Connection | None, optional
            Existing SQLite connection to reuse.

        Returns
        -------
        None
            Orphaned embedding rows are removed in place.
        """
        owns_connection = conn is None
        if conn is None:
            conn = self.open_connection(root)
        try:
            _prune_orphaned_embeddings(conn)
            if owns_connection:
                conn.commit()
        finally:
            if owns_connection:
                conn.close()

    def load_existing_file_hashes(
        self,
        root: Path,
        *,
        conn: sqlite3.Connection | None = None,
    ) -> dict[str, str]:
        """
        Load indexed file hashes used for incremental reuse decisions.

        Parameters
        ----------
        root : pathlib.Path
            Repository root whose index should be queried.
        conn : sqlite3.Connection | None, optional
            Existing SQLite connection to reuse.

        Returns
        -------
        dict[str, str]
            Indexed file hashes keyed by absolute file path.
        """
        owns_connection = conn is None
        if conn is None:
            conn = self.open_connection(root)
        try:
            return _load_existing_file_hashes(conn)
        finally:
            if owns_connection:
                conn.close()

    def load_existing_file_ownership(
        self,
        root: Path,
        *,
        conn: sqlite3.Connection | None = None,
    ) -> dict[str, tuple[str, str]]:
        """
        Load analyzer ownership for indexed files.

        Parameters
        ----------
        root : pathlib.Path
            Repository root whose index should be queried.
        conn : sqlite3.Connection | None, optional
            Existing SQLite connection to reuse.

        Returns
        -------
        dict[str, tuple[str, str]]
            Persisted analyzer ownership keyed by absolute file path.
        """
        owns_connection = conn is None
        if conn is None:
            conn = self.open_connection(root)
        try:
            return _load_existing_file_ownership(conn)
        finally:
            if owns_connection:
                conn.close()

    def current_embedding_state_matches(
        self,
        root: Path,
        *,
        embedding_backend: EmbeddingBackendSpec,
        conn: sqlite3.Connection | None = None,
    ) -> bool:
        """
        Check whether persisted embeddings match the active embedding backend.

        Parameters
        ----------
        root : pathlib.Path
            Repository root whose index should be queried.
        embedding_backend : EmbeddingBackendSpec
            Active embedding backend metadata.
        conn : sqlite3.Connection | None, optional
            Existing SQLite connection to reuse.

        Returns
        -------
        bool
            ``True`` when the persisted embedding metadata matches.
        """
        owns_connection = conn is None
        if conn is None:
            conn = self.open_connection(root)
        try:
            return _current_embedding_state_matches(conn, embedding_backend)
        finally:
            if owns_connection:
                conn.close()

    def delete_paths(
        self,
        root: Path,
        *,
        paths: list[str],
        conn: sqlite3.Connection | None = None,
    ) -> None:
        """
        Remove persisted rows owned by the supplied file paths.

        Parameters
        ----------
        root : pathlib.Path
            Repository root whose index should be updated.
        paths : list[str]
            Absolute file paths to remove.
        conn : sqlite3.Connection | None, optional
            Existing SQLite connection to reuse.

        Returns
        -------
        None
            Matching persisted rows are removed in place.
        """
        owns_connection = conn is None
        if conn is None:
            conn = self.open_connection(root)
        try:
            for path in sorted(paths):
                _delete_indexed_file_data(conn, path)
            if owns_connection:
                conn.commit()
        finally:
            if owns_connection:
                conn.close()

    def clear_index(
        self,
        root: Path,
        *,
        conn: sqlite3.Connection | None = None,
    ) -> None:
        """
        Remove all indexed artifacts from SQLite storage.

        Parameters
        ----------
        root : pathlib.Path
            Repository root whose index should be cleared.
        conn : sqlite3.Connection | None, optional
            Existing SQLite connection to reuse.

        Returns
        -------
        None
            Indexed rows are deleted in place.
        """
        owns_connection = conn is None
        if conn is None:
            conn = self.open_connection(root)
        try:
            _clear_index_tables(conn)
            if owns_connection:
                conn.commit()
        finally:
            if owns_connection:
                conn.close()

    def purge_skipped_docstring_issues(
        self,
        root: Path,
        *,
        conn: sqlite3.Connection | None = None,
    ) -> None:
        """
        Remove legacy docstring issues for files excluded from audit policy.

        Parameters
        ----------
        root : pathlib.Path
            Repository root whose index should be cleaned.
        conn : sqlite3.Connection | None, optional
            Existing SQLite connection to reuse.

        Returns
        -------
        None
            Matching issue rows are deleted in place.
        """
        owns_connection = conn is None
        if conn is None:
            conn = self.open_connection(root)
        try:
            _purge_skipped_docstring_issues(conn)
            if owns_connection:
                conn.commit()
        finally:
            if owns_connection:
                conn.close()

    def load_previous_embeddings_by_path(
        self,
        root: Path,
        *,
        paths: list[str],
        embedding_backend: EmbeddingBackendSpec,
        conn: sqlite3.Connection | None = None,
    ) -> dict[str, dict[str, StoredEmbeddingRow]]:
        """
        Load reusable stored symbol embeddings for paths being replaced.

        Parameters
        ----------
        root : pathlib.Path
            Repository root whose index should be queried.
        paths : list[str]
            Absolute file paths selected for replacement.
        embedding_backend : EmbeddingBackendSpec
            Active embedding backend metadata.
        conn : sqlite3.Connection | None, optional
            Existing SQLite connection to reuse.

        Returns
        -------
        dict[str, dict[str, codira.sqlite_backend_support.StoredEmbeddingRow]]
            Stored embeddings grouped by absolute file path.
        """
        owns_connection = conn is None
        if conn is None:
            conn = self.open_connection(root)
        try:
            return _load_previous_embeddings_by_path(
                conn,
                list(paths),
                backend=embedding_backend,
            )
        finally:
            if owns_connection:
                conn.close()

    def count_reusable_embeddings(
        self,
        root: Path,
        *,
        paths: list[str],
        conn: sqlite3.Connection | None = None,
    ) -> int:
        """
        Count semantic artifacts reused for unchanged paths.

        Parameters
        ----------
        root : pathlib.Path
            Repository root whose index should be queried.
        paths : list[str]
            Absolute file paths considered reusable.
        conn : sqlite3.Connection | None, optional
            Existing SQLite connection to reuse.

        Returns
        -------
        int
            Number of reusable embedding rows.
        """
        owns_connection = conn is None
        if conn is None:
            conn = self.open_connection(root)
        try:
            return _count_reused_embeddings(conn, paths)
        finally:
            if owns_connection:
                conn.close()

    def persist_analysis(
        self,
        request: BackendPersistAnalysisRequest,
    ) -> tuple[int, int]:
        """
        Persist normalized artifacts for one analyzed file.

        Parameters
        ----------
        request : BackendPersistAnalysisRequest
            Persistence request carrying file metadata, normalized analysis,
            embedding backend metadata, reusable embeddings, and optional
            connection reuse.

        Returns
        -------
        tuple[int, int]
            ``(recomputed, reused)`` embedding counts for the file.

        Raises
        ------
        OSError
            If file-backed persistence fails while storing analyzed artifacts.
        sqlite3.Error
            If SQLite rejects the persistence operation or transaction
            boundaries.
        RuntimeError
            If embedding persistence cannot complete for the analyzed file.
        ValueError
            If validated persistence inputs are semantically inconsistent.
        """
        root = request.root
        conn = cast("sqlite3.Connection | None", request.conn)
        owns_connection = conn is None
        if conn is None:
            conn = self.open_connection(root)
        active_backend = (
            get_embedding_backend()
            if request.embedding_backend is None
            else request.embedding_backend
        )
        try:
            if owns_connection:
                written = _store_analysis(
                    conn,
                    request.file_metadata,
                    request.analysis,
                    backend=active_backend,
                    previous_embeddings=cast(
                        "dict[str, StoredEmbeddingRow] | None",
                        request.previous_embeddings,
                    ),
                )
            else:
                conn.execute("SAVEPOINT persist_analysis")
                try:
                    written = _store_analysis(
                        conn,
                        request.file_metadata,
                        request.analysis,
                        backend=active_backend,
                        previous_embeddings=cast(
                            "dict[str, StoredEmbeddingRow] | None",
                            request.previous_embeddings,
                        ),
                    )
                except (OSError, sqlite3.Error, RuntimeError, ValueError):
                    conn.execute("ROLLBACK TO SAVEPOINT persist_analysis")
                    conn.execute("RELEASE SAVEPOINT persist_analysis")
                    raise
                conn.execute("RELEASE SAVEPOINT persist_analysis")
            if owns_connection:
                conn.commit()
            return written
        except sqlite3.Error as exc:
            msg = str(exc)
            raise BackendError(msg) from exc
        finally:
            if owns_connection:
                conn.close()

    def rebuild_derived_indexes(
        self,
        root: Path,
        *,
        conn: sqlite3.Connection | None = None,
    ) -> None:
        """
        Rebuild derived graph tables after raw persistence.

        Parameters
        ----------
        root : pathlib.Path
            Repository root whose index should be finalized.
        conn : sqlite3.Connection | None, optional
            Existing SQLite connection to reuse.

        Returns
        -------
        None
            Derived SQLite tables are refreshed in place.
        """
        owns_connection = conn is None
        if conn is None:
            conn = self.open_connection(root)
        try:
            _rebuild_graph_indexes(conn)
            if owns_connection:
                conn.commit()
        finally:
            if owns_connection:
                conn.close()

    def persist_runtime_inventory(
        self,
        request: BackendRuntimeInventoryRequest,
    ) -> None:
        """
        Persist backend and analyzer inventory for one successful index run.

        Parameters
        ----------
        request : BackendRuntimeInventoryRequest
            Runtime inventory persistence request.

        Returns
        -------
        None
            Runtime inventory rows are replaced in place.

        Raises
        ------
        BackendError
            If SQLite rejects the inventory update.
        """
        root = request.root
        backend_name = request.backend_name
        backend_version = request.backend_version
        coverage_complete = request.coverage_complete
        analyzers = request.analyzers
        conn = cast("sqlite3.Connection | None", request.conn)
        owns_connection = conn is None
        if conn is None:
            conn = self.open_connection(root)
        try:
            conn.execute("DELETE FROM index_runtime")
            conn.execute("DELETE FROM index_analyzers")
            conn.execute(
                """
                INSERT INTO index_runtime(
                    singleton,
                    backend_name,
                    backend_version,
                    coverage_complete
                ) VALUES (?, ?, ?, ?)
                """,
                (1, backend_name, backend_version, int(coverage_complete)),
            )

            for analyzer in sorted(analyzers, key=lambda item: str(item.name)):
                conn.execute(
                    """
                    INSERT INTO index_analyzers(name, version, discovery_globs)
                    VALUES (?, ?, ?)
                    """,
                    (
                        str(analyzer.name),
                        str(analyzer.version),
                        json.dumps(tuple(analyzer.discovery_globs)),
                    ),
                )
            if owns_connection:
                conn.commit()
        except sqlite3.Error as exc:
            msg = str(exc)
            raise BackendError(msg) from exc
        finally:
            if owns_connection:
                conn.close()

    def commit(self, root: Path, *, conn: sqlite3.Connection) -> None:
        """
        Commit pending writes on an open SQLite connection.

        Parameters
        ----------
        root : pathlib.Path
            Repository root associated with the connection.
        conn : sqlite3.Connection
            Open SQLite connection.

        Returns
        -------
        None
            Pending writes are committed.
        """
        del root
        conn.commit()

    def close_connection(self, conn: sqlite3.Connection) -> None:
        """
        Close an open SQLite connection.

        Parameters
        ----------
        conn : sqlite3.Connection
            Open SQLite connection.

        Returns
        -------
        None
            The connection is closed.
        """
        conn.close()


def build_backend() -> IndexBackend:
    """
    Build the first-party SQLite backend plugin instance.

    Parameters
    ----------
    None

    Returns
    -------
    codira.contracts.IndexBackend
        Active SQLite backend instance.
    """
    return cast("IndexBackend", SQLiteIndexBackend())
