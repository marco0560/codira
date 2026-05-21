"""DuckDB query and maintenance helpers for the production DuckDB backend.

Responsibilities
----------------
- Keep the production DuckDB backend self-contained at the package boundary.
- Provide the query, inventory, and maintenance surface used by the
  production backend implementation.
- Keep backend-local query logic out of codira-core.

Design principles
-----------------
The helper stays local to the DuckDB package so backend-specific query logic
remains package-owned and codira-core stays backend agnostic.

Architectural role
------------------
This module belongs to the **DuckDB backend plugin layer** and provides the
production query/maintenance helper surface used by the DuckDB backend.
"""

from __future__ import annotations

from collections.abc import Sequence
import importlib
import json
import re
from typing import TYPE_CHECKING, Protocol, cast

from codira.contracts import (
    BackendEmbeddingCandidatesRequest,
    BackendError,
    BackendGraphMetric,
    BackendQueryValue,
    BackendPersistAnalysisRequest,
    BackendRelationQueryRequest,
    BackendRuntimeInventoryRequest,
    BackendSymbolInventoryItem,
    StoredEmbeddingRow,
)
from codira.prefix import normalize_prefix, prefix_clause
from codira.schema import SCHEMA_VERSION
from codira.semantic.embeddings import (
    EmbeddingBackendSpec,
    deserialize_vector,
    embed_text,
    get_embedding_backend,
)
from .duckdb_support import (
    _DuckDBPersistenceConnection,
    _clear_index_tables,
    _count_reused_embeddings,
    _current_embedding_state_matches,
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

if TYPE_CHECKING:
    from pathlib import Path

    from codira.types import (
        ChannelResults,
        DocstringIssueRow,
        EnumMemberRow,
        IncludeEdgeRow,
        OverloadRow,
        ReferenceSearchRow,
        SymbolRow,
    )

CallEdgeRow = tuple[str, str, str | None, str | None, int]
CallableRefRow = tuple[str, str, str | None, str | None, int]
EmbeddingInventoryRow = tuple[str, str, int, int]

__all__ = ["DuckDBQueryBackend"]

_SAFE_GRAPH_IDENTIFIER_PATTERN = re.compile(r"^[a-z_][a-z0-9_]*$", re.IGNORECASE)
_ALLOWED_GRAPH_TABLES = frozenset({"call_edges", "callable_refs"})
_ALLOWED_GRAPH_COLUMNS = frozenset(
    {
        "caller_module",
        "caller_name",
        "callee_module",
        "callee_name",
        "owner_module",
        "owner_name",
        "target_module",
        "target_name",
    }
)


class _BackendCompatibleCursor(Protocol):
    """Cursor surface shared by backend-compatible connection adapters."""

    def execute(
        self,
        statement: str,
        parameters: Sequence[object] | None = None,
    ) -> _BackendCompatibleCursor:
        """
        Execute one statement and keep the cursor positioned on its result.

        Parameters
        ----------
        statement : str
            SQL statement to execute.
        parameters : collections.abc.Sequence[object] | None, optional
            Positional parameters bound to ``statement``.

        Returns
        -------
        _BackendCompatibleCursor
            The active cursor positioned on the statement result.
        """

    def fetchone(self) -> tuple[BackendQueryValue, ...] | None:
        """
        Return the next available row from the active result set.

        Parameters
        ----------
        None

        Returns
        -------
        tuple[codira.contracts.BackendQueryValue, ...] | None
            Next available row, or ``None`` when the result is exhausted.
        """

    def fetchall(self) -> list[tuple[BackendQueryValue, ...]]:
        """
        Return every remaining row from the active result set.

        Parameters
        ----------
        None

        Returns
        -------
        list[tuple[codira.contracts.BackendQueryValue, ...]]
            Remaining rows from the active result set.
        """


def _validated_graph_identifier(identifier: str, *, kind: str) -> str:
    """
    Validate one internal DuckDB graph identifier before SQL interpolation.

    Parameters
    ----------
    identifier : str
        Internal table or column identifier interpolated into SQL text.
    kind : str
        Human-readable identifier class used in error messages.

    Returns
    -------
    str
        The validated identifier.

    Raises
    ------
    ValueError
        Raised when ``identifier`` is not one of the repository-owned graph
        identifiers expected by the backend query helpers.
    """
    if not _SAFE_GRAPH_IDENTIFIER_PATTERN.fullmatch(identifier):
        msg = f"Unsafe DuckDB graph {kind} identifier: {identifier!r}"
        raise ValueError(msg)
    if kind == "table" and identifier not in _ALLOWED_GRAPH_TABLES:
        msg = f"Unsupported DuckDB graph table identifier: {identifier!r}"
        raise ValueError(msg)
    if kind == "column" and identifier not in _ALLOWED_GRAPH_COLUMNS:
        msg = f"Unsupported DuckDB graph column identifier: {identifier!r}"
        raise ValueError(msg)
    return identifier


class _BackendCompatibleConnectionAdapter(Protocol):
    """Connection surface shared by backend-compatible connection adapters."""

    def execute(
        self,
        statement: str,
        parameters: Sequence[object] | None = None,
    ) -> _BackendCompatibleCursor:
        """
        Execute one statement on the active backend connection.

        Parameters
        ----------
        statement : str
            SQL statement to execute.
        parameters : collections.abc.Sequence[object] | None, optional
            Positional parameters bound to ``statement``.

        Returns
        -------
        _BackendCompatibleCursor
            Cursor-like result wrapper for the executed statement.
        """

    def executemany(
        self,
        statement: str,
        parameters: Sequence[Sequence[object]],
    ) -> _BackendCompatibleCursor:
        """
        Execute one statement against multiple parameter rows.

        Parameters
        ----------
        statement : str
            SQL statement to execute repeatedly.
        parameters : collections.abc.Sequence[collections.abc.Sequence[object]]
            Parameter rows bound to ``statement``.

        Returns
        -------
        _BackendCompatibleCursor
            Cursor-like result wrapper for the most recent execution.
        """

    def cursor(self) -> _BackendCompatibleCursor:
        """
        Return a cursor-like object bound to the active connection.

        Parameters
        ----------
        None

        Returns
        -------
        _BackendCompatibleCursor
            Cursor-like object bound to the active backend connection.
        """

    def commit(self) -> None:
        """
        Commit pending writes on the active connection.

        Parameters
        ----------
        None

        Returns
        -------
        None
            Pending writes are committed in place.
        """

    def close(self) -> None:
        """
        Close the active backend connection.

        Parameters
        ----------
        None

        Returns
        -------
        None
            The active backend connection is closed.
        """


class _DuckDBModuleWithError(Protocol):
    """Minimal DuckDB module surface needed for error translation."""

    Error: type[BaseException]


_BackendCompatibleConnection = _BackendCompatibleConnectionAdapter


def _backend_int(value: BackendQueryValue) -> int:
    """
    Coerce one backend-compatible scalar into an integer.

    Parameters
    ----------
    value : BackendQueryValue
        Scalar value returned from one backend query row.

    Returns
    -------
    int
        Integer form of ``value``.
    """

    return int(cast("str | bytes | bytearray | int | float", value))


def _backend_bytes(value: BackendQueryValue) -> bytes:
    """
    Coerce one backend-compatible scalar into raw bytes.

    Parameters
    ----------
    value : BackendQueryValue
        Scalar value returned from one backend query row.

    Returns
    -------
    bytes
        Raw byte representation of ``value``.
    """

    return bytes(cast("bytes | bytearray", value))


def _duckdb_error_type() -> type[BaseException]:
    """
    Return the active DuckDB driver error base class.

    Parameters
    ----------
    None

    Returns
    -------
    type[BaseException]
        Base exception type exported by the active DuckDB driver module.
    """

    module = importlib.import_module("duckdb")
    return cast("_DuckDBModuleWithError", module).Error


class DuckDBQueryBackend:
    """
    DuckDB-local query and maintenance surface for the production backend.

    This helper keeps the query and maintenance semantics package-owned while
    the production DuckDB backend owns connection bootstrap and persistence
    behavior separately.
    """

    name = "duckdb-query-backend"
    version = SCHEMA_VERSION

    def load_runtime_inventory(
        self,
        root: Path,
        *,
        conn: _BackendCompatibleConnection | None = None,
    ) -> tuple[str, str, int] | None:
        """
        Return persisted backend and coverage metadata for the last index run.

        Parameters
        ----------
        root : pathlib.Path
            Repository root whose index should be queried.
        conn : _BackendCompatibleConnection | None, optional
            Existing backend-compatible connection to reuse.

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
            return (str(row[0]), str(row[1]), _backend_int(row[2]))
        finally:
            if owns_connection:
                conn.close()

    def load_analyzer_inventory(
        self,
        root: Path,
        *,
        conn: _BackendCompatibleConnection | None = None,
    ) -> list[tuple[str, str, str]]:
        """
        Return persisted analyzer inventory for the last index run.

        Parameters
        ----------
        root : pathlib.Path
            Repository root whose index should be queried.
        conn : _BackendCompatibleConnection | None, optional
            Existing backend-compatible connection to reuse.

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

    def needs_maintenance(
        self,
        root: Path,
        *,
        conn: _BackendCompatibleConnection | None = None,
    ) -> bool:
        """
        Report whether warm-index maintenance still needs one write session.

        Parameters
        ----------
        root : pathlib.Path
            Repository root whose index should be checked.
        conn : _BackendCompatibleConnection | None, optional
            Existing backend-compatible connection to reuse.

        Returns
        -------
        bool
            ``True`` when stale shell docstring issues or orphaned embeddings
            still require mutation work.
        """
        owns_connection = conn is None
        if conn is None:
            conn = self.open_connection(root)
        try:
            row = conn.execute(
                """
                SELECT
                    EXISTS(
                        SELECT 1
                        FROM docstring_issues di
                        JOIN files f ON f.id = di.file_id
                        WHERE f.analyzer_name = 'bash'
                           OR f.path LIKE '%.sh'
                           OR f.path LIKE '%.bash'
                    ),
                    EXISTS(
                        SELECT 1
                        FROM embeddings e
                        WHERE e.object_type = 'symbol'
                          AND NOT EXISTS (
                              SELECT 1
                              FROM symbol_index s
                              WHERE s.id = e.object_id
                          )
                    )
                """
            ).fetchone()
            assert row is not None
            return bool(_backend_int(row[0])) or bool(_backend_int(row[1]))
        finally:
            if owns_connection:
                conn.close()

    def initialize(self, root: Path) -> None:
        """
        Prepare backend-owned persistent state for one repository root.

        Parameters
        ----------
        root : pathlib.Path
            Repository root whose backend state should exist.

        Returns
        -------
        None
            Concrete subclasses provide the storage bootstrap behavior.

        Raises
        ------
        NotImplementedError
            Raised when one concrete backend does not override the bootstrap
            hook.
        """
        del root
        msg = "DuckDBQueryBackend requires a concrete initialize override."
        raise NotImplementedError(msg)

    def open_connection(self, root: Path) -> _BackendCompatibleConnection:
        """
        Open a backend-compatible connection for one repository index.

        Parameters
        ----------
        root : pathlib.Path
            Repository root whose index database should be opened.

        Returns
        -------
        _BackendCompatibleConnection
            Concrete subclasses provide the backend-compatible connection.

        Raises
        ------
        NotImplementedError
            Raised when one concrete backend does not override the connection
            bootstrap hook.
        """
        del root
        msg = "DuckDBQueryBackend requires a concrete open_connection override."
        raise NotImplementedError(msg)

    def list_symbols_in_module(
        self,
        root: Path,
        module: str,
        *,
        prefix: str | None = None,
        limit: int = 20,
        conn: _BackendCompatibleConnection | None = None,
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
        conn : _BackendCompatibleConnection | None, optional
            Existing backend-compatible connection to reuse.

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
            # nosemgrep: python.sqlalchemy.security.sqlalchemy-execute-raw-query.sqlalchemy-execute-raw-query
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
                (str(t), str(m), str(n), str(f), _backend_int(lineno))
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
        conn: _BackendCompatibleConnection | None = None,
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
        conn : _BackendCompatibleConnection | None, optional
            Existing backend-compatible connection to reuse.

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
            # nosemgrep: python.sqlalchemy.security.sqlalchemy-execute-raw-query.sqlalchemy-execute-raw-query
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
                (str(t), str(m), str(n), str(f), _backend_int(lineno))
                for t, m, n, f, lineno in rows
            ]
        finally:
            if owns_connection:
                conn.close()

    def symbol_inventory(
        self,
        root: Path,
        *,
        prefix: str | None = None,
        include_tests: bool = False,
        limit: int = 1000,
        conn: _BackendCompatibleConnection | None = None,
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
        conn : _BackendCompatibleConnection | None, optional
            Existing backend-compatible connection to reuse.

        Returns
        -------
        list[codira.contracts.BackendSymbolInventoryItem]
            Symbol inventory rows ordered deterministically.

        Raises
        ------
        ValueError
            If ``limit`` is negative.
        """
        if limit < 0:
            msg = "Limit must be non-negative."
            raise ValueError(msg)

        owns_connection = conn is None
        normalized_prefix = normalize_prefix(root, prefix)
        if conn is None:
            conn = self.open_connection(root)
        try:
            prefix_sql, prefix_params = prefix_clause(normalized_prefix, "f.path")
            test_sql = (
                ""
                if include_tests
                else "AND s.module_name != 'tests' AND s.module_name NOT LIKE 'tests.%'"
            )
            # nosemgrep: python.sqlalchemy.security.sqlalchemy-execute-raw-query.sqlalchemy-execute-raw-query
            rows = conn.execute(
                f"""
                SELECT s.type, s.module_name, s.name, f.path, s.lineno
                FROM symbol_index s
                JOIN files f
                  ON s.file_id = f.id
                WHERE 1 = 1
                {prefix_sql}
                {test_sql}
                ORDER BY s.module_name, s.name, s.type, f.path, s.lineno
                """,
                tuple(prefix_params),
            ).fetchall()
            symbols: list[tuple[str, str, str, str, int]] = []
            seen_identities: set[tuple[str, str]] = set()
            for symbol_type, module_name, symbol_name, file_path, lineno in rows:
                identity = (str(module_name), str(symbol_name))
                if identity in seen_identities:
                    continue
                seen_identities.add(identity)
                symbols.append(
                    (
                        str(symbol_type),
                        identity[0],
                        identity[1],
                        str(file_path),
                        _backend_int(lineno),
                    )
                )

            limited_symbols = symbols[:limit]
            return [
                BackendSymbolInventoryItem(
                    symbol_type=symbol_type,
                    module=module_name,
                    name=symbol_name,
                    file=file_path,
                    lineno=lineno,
                    calls_out=self._symbol_metric(
                        conn,
                        "call_edges",
                        "caller_module",
                        "caller_name",
                        (module_name, symbol_name),
                    ),
                    calls_in=self._symbol_metric(
                        conn,
                        "call_edges",
                        "callee_module",
                        "callee_name",
                        (module_name, symbol_name),
                    ),
                    refs_out=self._symbol_metric(
                        conn,
                        "callable_refs",
                        "owner_module",
                        "owner_name",
                        (module_name, symbol_name),
                    ),
                    refs_in=self._symbol_metric(
                        conn,
                        "callable_refs",
                        "target_module",
                        "target_name",
                        (module_name, symbol_name),
                    ),
                )
                for symbol_type, module_name, symbol_name, file_path, lineno in limited_symbols
            ]
        finally:
            if owns_connection:
                conn.close()

    def _symbol_metric(
        self,
        conn: _BackendCompatibleConnection,
        table: str,
        module_column: str,
        name_column: str,
        symbol_identity: tuple[str, str],
    ) -> BackendGraphMetric:
        """
        Count graph edges for one symbol identity.

        Parameters
        ----------
        conn : _BackendCompatibleConnection
            Open backend connection.
        table : {"call_edges", "callable_refs"}
            Graph table to aggregate.
        module_column : str
            Column storing the selected relation endpoint module.
        name_column : str
            Column storing the selected relation endpoint name.
        symbol_identity : tuple[str, str]
            Module and name components of the symbol identity.

        Returns
        -------
        codira.contracts.BackendGraphMetric
            Total and unresolved counts for the selected relation direction.
        """
        module_name, symbol_name = symbol_identity
        safe_table = _validated_graph_identifier(table, kind="table")
        safe_module_column = _validated_graph_identifier(module_column, kind="column")
        safe_name_column = _validated_graph_identifier(name_column, kind="column")
        # nosemgrep: python.sqlalchemy.security.sqlalchemy-execute-raw-query.sqlalchemy-execute-raw-query
        row = conn.execute(
            f"""
            SELECT COUNT(*), COALESCE(SUM(CASE WHEN resolved = 0 THEN 1 ELSE 0 END), 0)
            FROM {safe_table}
            WHERE {safe_module_column} = ?
              AND {safe_name_column} = ?
            """,
            (module_name, symbol_name),
        ).fetchone()
        if row is None:
            return BackendGraphMetric(total=0, unresolved=0)
        return BackendGraphMetric(
            total=_backend_int(row[0]), unresolved=_backend_int(row[1])
        )

    def find_symbol_overloads(
        self,
        root: Path,
        symbol: SymbolRow,
        *,
        conn: _BackendCompatibleConnection | None = None,
    ) -> list[OverloadRow]:
        """
        Return overload metadata attached to one canonical callable symbol.

        Parameters
        ----------
        root : pathlib.Path
            Repository root whose index should be queried.
        symbol : codira.types.SymbolRow
            Canonical function or method symbol row.
        conn : _BackendCompatibleConnection | None, optional
            Existing backend-compatible connection to reuse.

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
                    _backend_int(ordinal),
                    str(signature),
                    _backend_int(overload_lineno),
                    None if end_lineno is None else _backend_int(end_lineno),
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
        conn: _BackendCompatibleConnection | None = None,
    ) -> list[EnumMemberRow]:
        """
        Return enum-member metadata attached to one canonical enum symbol.

        Parameters
        ----------
        root : pathlib.Path
            Repository root whose index should be queried.
        symbol : codira.types.SymbolRow
            Canonical enum symbol row.
        conn : _BackendCompatibleConnection | None, optional
            Existing backend-compatible connection to reuse.

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
                    _backend_int(ordinal),
                    str(member_name),
                    str(signature),
                    _backend_int(member_lineno),
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
        conn: _BackendCompatibleConnection | None = None,
    ) -> list[DocstringIssueRow]:
        """
        Return indexed docstring validation issues.

        Parameters
        ----------
        root : pathlib.Path
            Repository root whose index should be queried.
        prefix : str | None, optional
            Repo-root-relative path prefix used to restrict issue ownership.
        conn : _BackendCompatibleConnection | None, optional
            Existing backend-compatible connection to reuse.

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
            # nosemgrep: python.sqlalchemy.security.sqlalchemy-execute-raw-query.sqlalchemy-execute-raw-query
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
                    _backend_int(lineno),
                    None if end_lineno is None else _backend_int(end_lineno),
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
        conn = cast("_BackendCompatibleConnection | None", request.conn)
        owns_connection = conn is None
        normalized_prefix = normalize_prefix(root, prefix)
        if conn is None:
            conn = self.open_connection(root)

        direction_column = "callee_name" if incoming else "caller_name"
        module_column = "callee_module" if incoming else "caller_module"
        safe_direction_column = _validated_graph_identifier(
            direction_column,
            kind="column",
        )
        safe_module_column = _validated_graph_identifier(module_column, kind="column")
        prefix_sql, prefix_params = prefix_clause(normalized_prefix, "f.path")

        # nosemgrep: python.django.security.injection.tainted-sql-string.tainted-sql-string
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
            WHERE {safe_direction_column} = ?
            {prefix_sql}
        """
        params: list[str] = [name, *prefix_params]

        if module is not None:
            query += f" AND {safe_module_column} = ?"
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
            rows = conn.execute(  # nosemgrep: python.sqlalchemy.security.sqlalchemy-execute-raw-query.sqlalchemy-execute-raw-query
                query,
                tuple(params),
            ).fetchall()
            return [
                (
                    str(caller_module),
                    str(caller_name),
                    None if callee_module is None else str(callee_module),
                    None if callee_name is None else str(callee_name),
                    _backend_int(resolved),
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
        conn = cast("_BackendCompatibleConnection | None", request.conn)
        owns_connection = conn is None
        normalized_prefix = normalize_prefix(root, prefix)
        if conn is None:
            conn = self.open_connection(root)

        direction_column = "target_name" if incoming else "owner_name"
        module_column = "target_module" if incoming else "owner_module"
        safe_direction_column = _validated_graph_identifier(
            direction_column,
            kind="column",
        )
        safe_module_column = _validated_graph_identifier(module_column, kind="column")
        prefix_sql, prefix_params = prefix_clause(normalized_prefix, "f.path")

        # nosemgrep: python.django.security.injection.tainted-sql-string.tainted-sql-string
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
            WHERE {safe_direction_column} = ?
            {prefix_sql}
        """
        params: list[str] = [name, *prefix_params]

        if module is not None:
            query += f" AND {safe_module_column} = ?"
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
            rows = conn.execute(  # nosemgrep: python.sqlalchemy.security.sqlalchemy-execute-raw-query.sqlalchemy-execute-raw-query
                query,
                tuple(params),
            ).fetchall()
            return [
                (
                    str(owner_module),
                    str(owner_name),
                    None if target_module is None else str(target_module),
                    None if target_name is None else str(target_name),
                    _backend_int(resolved),
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
        conn = cast("_BackendCompatibleConnection | None", request.conn)
        owns_connection = conn is None
        normalized_prefix = normalize_prefix(root, prefix)
        if conn is None:
            conn = self.open_connection(root)

        prefix_sql, prefix_params = prefix_clause(normalized_prefix, "f.path")
        # nosemgrep: python.django.security.injection.tainted-sql-string.tainted-sql-string
        # nosemgrep: python.sqlalchemy.security.sqlalchemy-execute-raw-query.sqlalchemy-execute-raw-query
        # nosemgrep: python.lang.security.audit.formatted-sql-query.formatted-sql-query
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
            rows = conn.execute(  # nosemgrep: python.sqlalchemy.security.sqlalchemy-execute-raw-query.sqlalchemy-execute-raw-query
                query,
                tuple(params),
            ).fetchall()
            return [
                (str(owner_module), str(target_name), str(kind), _backend_int(lineno))
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
        conn: _BackendCompatibleConnection | None = None,
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
        conn : _BackendCompatibleConnection | None, optional
            Existing backend-compatible connection to reuse.

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
                # nosemgrep: python.sqlalchemy.security.sqlalchemy-execute-raw-query.sqlalchemy-execute-raw-query
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
                # nosemgrep: python.sqlalchemy.security.sqlalchemy-execute-raw-query.sqlalchemy-execute-raw-query
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
                (str(t), str(m), str(n), str(f), _backend_int(lineno))
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
        conn: _BackendCompatibleConnection | None = None,
    ) -> str:
        """
        Return the logical graph identity for one indexed symbol row.

        Parameters
        ----------
        root : pathlib.Path
            Repository root whose index should be queried.
        symbol : codira.types.SymbolRow
            Indexed symbol row whose logical identity should be resolved.
        conn : _BackendCompatibleConnection | None, optional
            Existing backend-compatible connection to reuse.

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
        conn: _BackendCompatibleConnection | None = None,
    ) -> list[EmbeddingInventoryRow]:
        """
        Return stored embedding inventory grouped by backend metadata.

        Parameters
        ----------
        root : pathlib.Path
            Repository root whose index should be queried.
        conn : _BackendCompatibleConnection | None, optional
            Existing backend-compatible connection to reuse.

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
                (str(backend), str(version), _backend_int(dim), _backend_int(count))
                for backend, version, dim, count in rows
            ]
        finally:
            if owns_connection:
                conn.close()

    def find_reference_rows(
        self,
        root: Path,
        name: str,
        *,
        prefix: str | None = None,
        conn: _BackendCompatibleConnection | None = None,
    ) -> list[ReferenceSearchRow]:
        """
        Return stored non-import lines containing one symbol name.

        Parameters
        ----------
        root : pathlib.Path
            Repository root whose index should be queried.
        name : str
            Symbol name to search as a simple substring.
        prefix : str | None, optional
            Repo-root-relative path prefix used to restrict candidate files.
        conn : _BackendCompatibleConnection | None, optional
            Existing backend-compatible connection to reuse.

        Returns
        -------
        list[codira.types.ReferenceSearchRow]
            Matching stored rows ordered by file path and line number.
        """
        owns_connection = conn is None
        normalized_prefix = normalize_prefix(root, prefix)
        if conn is None:
            conn = self.open_connection(root)

        try:
            prefix_sql, prefix_params = prefix_clause(normalized_prefix, "f.path")
            # nosemgrep: python.django.security.injection.tainted-sql-string.tainted-sql-string
            # nosemgrep: python.sqlalchemy.security.sqlalchemy-execute-raw-query.sqlalchemy-execute-raw-query
            rows = conn.execute(
                f"""
                SELECT f.path, rsl.lineno, rsl.line_text
                FROM reference_scan_lines rsl
                JOIN files f
                  ON rsl.file_id = f.id
                WHERE instr(rsl.line_text, ?) > 0
                {prefix_sql}
                ORDER BY f.path, rsl.lineno
                LIMIT 50
                """,
                (name, *prefix_params),
            ).fetchall()
            return [
                (str(file_path), _backend_int(lineno), str(line_text))
                for file_path, lineno, line_text in rows
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
        conn = cast("_BackendCompatibleConnection | None", request.conn)
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
            # nosemgrep: python.sqlalchemy.security.sqlalchemy-execute-raw-query.sqlalchemy-execute-raw-query
            # nosemgrep: python.lang.security.audit.formatted-sql-query.formatted-sql-query
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
                    _backend_int(row[4]),
                )
                version = str(row[5])
                dim = _backend_int(row[6])
                blob = _backend_bytes(row[7])
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
        conn: _BackendCompatibleConnection | None = None,
    ) -> None:
        """
        Remove embedding rows whose owning symbol no longer exists.

        Parameters
        ----------
        root : pathlib.Path
            Repository root whose index should be cleaned.
        conn : _BackendCompatibleConnection | None, optional
            Existing backend-compatible connection to reuse.

        Returns
        -------
        None
            Orphaned embedding rows are removed in place.
        """
        owns_connection = conn is None
        if conn is None:
            conn = self.open_connection(root)
        try:
            _prune_orphaned_embeddings(cast("_DuckDBPersistenceConnection", conn))
            if owns_connection:
                conn.commit()
        finally:
            if owns_connection:
                conn.close()

    def load_existing_file_hashes(
        self,
        root: Path,
        *,
        conn: _BackendCompatibleConnection | None = None,
    ) -> dict[str, str]:
        """
        Load indexed file hashes used for incremental reuse decisions.

        Parameters
        ----------
        root : pathlib.Path
            Repository root whose index should be queried.
        conn : _BackendCompatibleConnection | None, optional
            Existing backend-compatible connection to reuse.

        Returns
        -------
        dict[str, str]
            Indexed file hashes keyed by absolute file path.
        """
        owns_connection = conn is None
        if conn is None:
            conn = self.open_connection(root)
        try:
            return _load_existing_file_hashes(
                cast("_DuckDBPersistenceConnection", conn)
            )
        finally:
            if owns_connection:
                conn.close()

    def load_existing_file_ownership(
        self,
        root: Path,
        *,
        conn: _BackendCompatibleConnection | None = None,
    ) -> dict[str, tuple[str, str]]:
        """
        Load analyzer ownership for indexed files.

        Parameters
        ----------
        root : pathlib.Path
            Repository root whose index should be queried.
        conn : _BackendCompatibleConnection | None, optional
            Existing backend-compatible connection to reuse.

        Returns
        -------
        dict[str, tuple[str, str]]
            Persisted analyzer ownership keyed by absolute file path.
        """
        owns_connection = conn is None
        if conn is None:
            conn = self.open_connection(root)
        try:
            return _load_existing_file_ownership(
                cast("_DuckDBPersistenceConnection", conn)
            )
        finally:
            if owns_connection:
                conn.close()

    def current_embedding_state_matches(
        self,
        root: Path,
        *,
        embedding_backend: EmbeddingBackendSpec,
        conn: _BackendCompatibleConnection | None = None,
    ) -> bool:
        """
        Check whether persisted embeddings match the active embedding backend.

        Parameters
        ----------
        root : pathlib.Path
            Repository root whose index should be queried.
        embedding_backend : EmbeddingBackendSpec
            Active embedding backend metadata.
        conn : _BackendCompatibleConnection | None, optional
            Existing backend-compatible connection to reuse.

        Returns
        -------
        bool
            ``True`` when the persisted embedding metadata matches.
        """
        owns_connection = conn is None
        if conn is None:
            conn = self.open_connection(root)
        try:
            return _current_embedding_state_matches(
                cast("_DuckDBPersistenceConnection", conn),
                embedding_backend,
            )
        finally:
            if owns_connection:
                conn.close()

    def delete_paths(
        self,
        root: Path,
        *,
        paths: list[str],
        conn: _BackendCompatibleConnection | None = None,
    ) -> None:
        """
        Remove persisted rows owned by the supplied file paths.

        Parameters
        ----------
        root : pathlib.Path
            Repository root whose index should be updated.
        paths : list[str]
            Absolute file paths to remove.
        conn : _BackendCompatibleConnection | None, optional
            Existing backend-compatible connection to reuse.

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
                _delete_indexed_file_data(
                    cast("_DuckDBPersistenceConnection", conn),
                    path,
                )
            if owns_connection:
                conn.commit()
        finally:
            if owns_connection:
                conn.close()

    def clear_index(
        self,
        root: Path,
        *,
        conn: _BackendCompatibleConnection | None = None,
    ) -> None:
        """
        Remove all indexed artifacts from DuckDB storage.

        Parameters
        ----------
        root : pathlib.Path
            Repository root whose index should be cleared.
        conn : _BackendCompatibleConnection | None, optional
            Existing backend-compatible connection to reuse.

        Returns
        -------
        None
            Indexed rows are deleted in place.
        """
        owns_connection = conn is None
        if conn is None:
            conn = self.open_connection(root)
        try:
            _clear_index_tables(cast("_DuckDBPersistenceConnection", conn))
            if owns_connection:
                conn.commit()
        finally:
            if owns_connection:
                conn.close()

    def purge_skipped_docstring_issues(
        self,
        root: Path,
        *,
        conn: _BackendCompatibleConnection | None = None,
    ) -> None:
        """
        Remove legacy docstring issues for files excluded from audit policy.

        Parameters
        ----------
        root : pathlib.Path
            Repository root whose index should be cleaned.
        conn : _BackendCompatibleConnection | None, optional
            Existing backend-compatible connection to reuse.

        Returns
        -------
        None
            Matching issue rows are deleted in place.
        """
        owns_connection = conn is None
        if conn is None:
            conn = self.open_connection(root)
        try:
            _purge_skipped_docstring_issues(cast("_DuckDBPersistenceConnection", conn))
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
        conn: _BackendCompatibleConnection | None = None,
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
        conn : _BackendCompatibleConnection | None, optional
            Existing backend-compatible connection to reuse.

        Returns
        -------
        dict[str, dict[str, codira.contracts.StoredEmbeddingRow]]
            Stored embeddings grouped by absolute file path.
        """
        owns_connection = conn is None
        if conn is None:
            conn = self.open_connection(root)
        try:
            return _load_previous_embeddings_by_path(
                cast("_DuckDBPersistenceConnection", conn),
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
        conn: _BackendCompatibleConnection | None = None,
    ) -> int:
        """
        Count semantic artifacts reused for unchanged paths.

        Parameters
        ----------
        root : pathlib.Path
            Repository root whose index should be queried.
        paths : list[str]
            Absolute file paths considered reusable.
        conn : _BackendCompatibleConnection | None, optional
            Existing backend-compatible connection to reuse.

        Returns
        -------
        int
            Number of reusable embedding rows.
        """
        owns_connection = conn is None
        if conn is None:
            conn = self.open_connection(root)
        try:
            return _count_reused_embeddings(
                cast("_DuckDBPersistenceConnection", conn),
                paths,
            )
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
        codira.contracts.BackendError
            If DuckDB rejects the persistence operation or transaction
            boundaries.
        RuntimeError
            If embedding persistence cannot complete for the analyzed file.
        ValueError
            If validated persistence inputs are semantically inconsistent.
        """
        root = request.root
        conn = cast("_BackendCompatibleConnection | None", request.conn)
        owns_connection = conn is None
        if conn is None:
            conn = self.open_connection(root)
        active_backend = (
            get_embedding_backend()
            if request.embedding_backend is None
            else request.embedding_backend
        )
        duckdb_error = _duckdb_error_type()
        try:
            if owns_connection:
                written = _store_analysis(
                    cast("_DuckDBPersistenceConnection", conn),
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
                        cast("_DuckDBPersistenceConnection", conn),
                        request.file_metadata,
                        request.analysis,
                        backend=active_backend,
                        previous_embeddings=cast(
                            "dict[str, StoredEmbeddingRow] | None",
                            request.previous_embeddings,
                        ),
                    )
                except (OSError, duckdb_error, RuntimeError, ValueError):
                    conn.execute("ROLLBACK TO SAVEPOINT persist_analysis")
                    conn.execute("RELEASE SAVEPOINT persist_analysis")
                    raise
                else:
                    conn.execute("RELEASE SAVEPOINT persist_analysis")
        except duckdb_error as exc:
            msg = str(exc)
            raise BackendError(msg) from exc
        else:
            if owns_connection:
                conn.commit()
            return written
        finally:
            if owns_connection:
                conn.close()

    def rebuild_derived_indexes(
        self,
        root: Path,
        *,
        conn: _BackendCompatibleConnection | None = None,
    ) -> None:
        """
        Rebuild derived graph tables after raw persistence.

        Parameters
        ----------
        root : pathlib.Path
            Repository root whose index should be finalized.
        conn : _BackendCompatibleConnection | None, optional
            Existing backend-compatible connection to reuse.

        Returns
        -------
        None
            Derived DuckDB tables are refreshed in place.
        """
        owns_connection = conn is None
        if conn is None:
            conn = self.open_connection(root)
        try:
            _rebuild_graph_indexes(cast("_DuckDBPersistenceConnection", conn))
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
            If DuckDB rejects the inventory update.
        """
        root = request.root
        backend_name = request.backend_name
        backend_version = request.backend_version
        coverage_complete = request.coverage_complete
        analyzers = request.analyzers
        conn = cast("_BackendCompatibleConnection | None", request.conn)
        owns_connection = conn is None
        if conn is None:
            conn = self.open_connection(root)
        duckdb_error = _duckdb_error_type()
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
        except duckdb_error as exc:
            msg = str(exc)
            raise BackendError(msg) from exc
        finally:
            if owns_connection:
                conn.close()

    def commit(self, root: Path, *, conn: _BackendCompatibleConnection) -> None:
        """
        Commit pending writes on an open backend connection.

        Parameters
        ----------
        root : pathlib.Path
            Repository root associated with the connection.
        conn : _BackendCompatibleConnection
            Open backend-compatible connection.

        Returns
        -------
        None
            Pending writes are committed.
        """
        del root
        conn.commit()

    def close_connection(self, conn: _BackendCompatibleConnection) -> None:
        """
        Close an open backend connection.

        Parameters
        ----------
        conn : _BackendCompatibleConnection
            Open backend-compatible connection.

        Returns
        -------
        None
            The connection is closed.
        """
        conn.close()
