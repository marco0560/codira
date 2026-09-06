"""Analyzer and SQLite backend stubs for incremental-indexing tests.

The stubs model version changes and record backend lifecycle calls while
delegating the actual SQLite behavior to first-party implementations.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from codira_analyzer_python import PythonAnalyzer
from codira_backend_sqlite import SQLiteIndexBackend
from codira_backend_sqlite.schema import SCHEMA_VERSION

if TYPE_CHECKING:
    import sqlite3
    from pathlib import Path

    from codira.contracts import IndexWriteSession
    from codira.models import AnalysisResult


class _PythonAnalyzerV12:
    """
    Python analyzer stub with a bumped version for staleness tests.

    Parameters
    ----------
    None
    """

    name = "python"
    version = "12"
    discovery_globs: tuple[str, ...] = ("*.py",)

    def supports_path(self, path: Path) -> bool:
        """
        Delegate Python path support to the installed Python analyzer.

        Parameters
        ----------
        path : pathlib.Path
            Candidate repository path.

        Returns
        -------
        bool
            ``True`` when the path is accepted by the Python analyzer.
        """
        return PythonAnalyzer().supports_path(path)

    def analyze_file(self, path: Path, root: Path) -> AnalysisResult:
        """
        Delegate Python analysis while exposing a bumped analyzer version.

        Parameters
        ----------
        path : pathlib.Path
            Python source file to analyze.
        root : pathlib.Path
            Repository root used for module derivation.

        Returns
        -------
        codira.models.AnalysisResult
            Normalized analysis result from the installed Python analyzer.
        """
        return PythonAnalyzer().analyze_file(path, root)


class _SQLiteBackendVNext(SQLiteIndexBackend):
    """SQLite backend stub with a bumped version for runtime tests."""

    version = SCHEMA_VERSION + 1


class _TrackingSQLiteBackend(SQLiteIndexBackend):
    """SQLite backend wrapper that records write-session starts."""

    def __init__(self) -> None:
        super().__init__()
        self.begin_index_session_calls = 0
        self.open_connection_calls = 0
        self.close_connection_calls = 0
        self.rebuild_derived_indexes_calls = 0

    def begin_index_session(self, root: Path) -> IndexWriteSession:
        """
        Record one write-session start before delegating to SQLite.

        Parameters
        ----------
        root : pathlib.Path
            Repository root whose backend state may be mutated.

        Returns
        -------
        object
            Concrete SQLite write session created by the parent backend.
        """
        self.begin_index_session_calls += 1
        return super().begin_index_session(root)

    def open_connection(self, root: Path) -> sqlite3.Connection:
        """
        Record one backend connection open before delegating to SQLite.

        Parameters
        ----------
        root : pathlib.Path
            Repository root whose backend state should be queried or mutated.

        Returns
        -------
        sqlite3.Connection
            Concrete SQLite connection created by the parent backend.
        """
        self.open_connection_calls += 1
        return super().open_connection(root)

    def close_connection(self, conn: sqlite3.Connection) -> None:
        """
        Record one backend connection close before delegating to SQLite.

        Parameters
        ----------
        conn : sqlite3.Connection
            Backend-owned connection handle to close.

        Returns
        -------
        None
            The connection is closed by the parent backend.
        """
        self.close_connection_calls += 1
        super().close_connection(conn)

    def rebuild_derived_indexes(
        self,
        root: Path,
        *,
        conn: sqlite3.Connection | None = None,
    ) -> None:
        """
        Record one derived-index rebuild before delegating to SQLite.

        Parameters
        ----------
        root : pathlib.Path
            Repository root whose derived indexes should be rebuilt.
        conn : sqlite3.Connection | None, optional
            Existing SQLite connection to reuse.

        Returns
        -------
        None
            Derived indexes are rebuilt by the parent backend.
        """
        self.rebuild_derived_indexes_calls += 1
        super().rebuild_derived_indexes(root, conn=conn)
