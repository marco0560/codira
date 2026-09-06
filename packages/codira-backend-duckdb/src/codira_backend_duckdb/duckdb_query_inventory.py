"""DuckDB warm-index inventory query mixin."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .duckdb_query_primitives import _BackendCompatibleConnection, _backend_int

if TYPE_CHECKING:
    from pathlib import Path


class DuckDBQueryInventoryMixin:
    """Provide persisted runtime-inventory and maintenance-read operations."""

    def open_connection(self, root: Path) -> _BackendCompatibleConnection:
        """Open a DuckDB-compatible connection.

        Parameters
        ----------
        root : pathlib.Path
            Repository root.

        Returns
        -------
        _BackendCompatibleConnection
            Open connection.

        Raises
        ------
        NotImplementedError
            Always; the concrete backend supplies this connection seam.
        """
        del root
        raise NotImplementedError

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
