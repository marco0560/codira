"""Deterministic tests for incremental indexing behavior.

Responsibilities
----------------
- Exercise repository rebuild logic, metadata serialization, and analyzer/backend version handling for incremental runs.
- Verify file reuse, staleness detection, and coverage auditing steps as source trees or analyzers change.
- Confirm embedding backend expectations and CLI metadata reporting remain stable across repeated indexes.

Design principles
-----------------
Tests stay deterministic by using explicit metadata hooks, temporary roots, and stub analyzers/backends for predictable behavior.

Architectural role
------------------
This module belongs to the **indexing verification layer** that guards incremental-run guarantees for codira.
"""

from __future__ import annotations

import contextlib
import importlib.util
import json
import os
import sqlite3
import subprocess
import sys
import time
import types
from pathlib import Path
from typing import TYPE_CHECKING, cast

import pytest
from codira_backend_sqlite import SQLiteIndexBackend
from codira_backend_sqlite.sqlite_storage import get_db_path, init_db

import codira.indexer as indexer_module
import codira.registry as registry_module
import codira.storage as storage_module
from codira.analyzers import PythonAnalyzer
from codira.cli import (
    IndexCommandRequest,
    IndexRebuildRequest,
    _ensure_index,
    _read_index_metadata,
    _write_index_metadata,
    main,
)
from codira.contracts import (
    BackendPersistAnalysisRequest,
    BackendRuntimeInventoryRequest,
    IndexWriteSession,
    LanguageAnalyzer,
    StoredEmbeddingRow,
)
from codira.indexer import audit_repo_coverage, index_repo
from codira.models import (
    AnalysisResult,
    CallableReference,
    CallSite,
    DocumentationArtifact,
    FileMetadataSnapshot,
    FunctionArtifact,
    ModuleArtifact,
)
from codira.plugin_config import analyzer_inventory_discovery_json
from codira.query.exact import docstring_issues, find_symbol
from codira.scanner import file_metadata
from codira.schema import SCHEMA_VERSION
from codira.semantic.embeddings import (
    EMBEDDING_BACKEND,
    EMBEDDING_DIM,
    EmbeddingBackendSpec,
)
from codira.storage import acquire_index_lock

if TYPE_CHECKING:
    from collections.abc import Iterator


def _write_module(path: Path, source: str) -> None:
    """
    Write one Python module fixture.

    Parameters
    ----------
    path : pathlib.Path
        Module path to create or replace.
    source : str
        Python source code written to ``path``.

    Returns
    -------
    None
        The file is written in place.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")


def _analyzer_inventory_row(analyzer: LanguageAnalyzer) -> tuple[str, str, str]:
    """
    Return one analyzer inventory row in persisted comparison form.

    Parameters
    ----------
    analyzer : codira.contracts.LanguageAnalyzer
        Analyzer instance to serialize.

    Returns
    -------
    tuple[str, str, str]
        Persisted analyzer inventory row.
    """

    return (
        str(analyzer.name),
        str(analyzer.version),
        analyzer_inventory_discovery_json(analyzer),
    )


def _default_analyzer_inventory_json() -> str:
    """
    Return the default analyzer inventory encoded like CLI metadata.

    Parameters
    ----------
    None

    Returns
    -------
    str
        JSON-encoded analyzer inventory for the active test environment.
    """
    return json.dumps(
        [
            _analyzer_inventory_row(analyzer)
            for analyzer in sorted(
                registry_module.active_language_analyzers(),
                key=lambda item: str(item.name),
            )
        ]
    )


def _load_workspace_cli_module() -> types.ModuleType:
    """
    Load the workspace `src/codira/cli.py` module under a unique name.

    Parameters
    ----------
    None

    Returns
    -------
    types.ModuleType
        Freshly loaded workspace CLI module.

    Raises
    ------
    AssertionError
        Raised when the workspace CLI module cannot be loaded.
    """
    module_path = Path(__file__).resolve().parents[1] / "src" / "codira" / "cli.py"
    spec = importlib.util.spec_from_file_location(
        f"workspace_codira_cli_{time.monotonic_ns()}",
        module_path,
    )
    if spec is None or spec.loader is None:
        msg = f"failed to load workspace codira cli module from {module_path}"
        raise AssertionError(msg)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class _PythonAnalyzerV7:
    """
    Python analyzer stub with a bumped version for staleness tests.

    Parameters
    ----------
    None
    """

    name = "python"
    version = "7"
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


class _RecordingBackendConnection:
    """Opaque fake backend connection used for CLI integration tests."""


class _RecordingIndexWriteSession:
    """
    Recording write session used by CLI integration tests.

    Parameters
    ----------
    backend : _RecordingBackend
        Backend that owns the session.
    root : pathlib.Path
        Repository root associated with the session.
    """

    def __init__(self, backend: _RecordingBackend, root: Path) -> None:
        self._backend = backend
        self._root = root
        self._conn = backend.open_connection(root)

    def purge_skipped_docstring_issues(self) -> None:
        """
        Perform no-op cleanup for skipped docstring diagnostics.

        Parameters
        ----------
        None

        Returns
        -------
        None
            The recording session performs no additional work beyond delegation.
        """
        self._backend.purge_skipped_docstring_issues(self._root, conn=self._conn)

    def prune_orphaned_embeddings(self) -> None:
        """
        Perform no-op cleanup for orphaned embeddings.

        Parameters
        ----------
        None

        Returns
        -------
        None
            The recording session performs no additional work beyond delegation.
        """
        self._backend.prune_orphaned_embeddings(self._root, conn=self._conn)

    def load_existing_file_hashes(self) -> dict[str, str]:
        """
        Return the configured indexed file hashes.

        Parameters
        ----------
        None

        Returns
        -------
        dict[str, str]
            Indexed file hashes keyed by absolute path.
        """
        return self._backend.load_existing_file_hashes(self._root, conn=self._conn)

    def load_existing_file_ownership(self) -> dict[str, tuple[str, str]]:
        """
        Return the configured analyzer ownership mapping.

        Parameters
        ----------
        None

        Returns
        -------
        dict[str, tuple[str, str]]
            Analyzer name and version keyed by absolute path.
        """
        return self._backend.load_existing_file_ownership(self._root, conn=self._conn)

    def current_embedding_state_matches(self, embedding_backend: object) -> bool:
        """
        Report whether the recording embedding state matches the active backend.

        Parameters
        ----------
        embedding_backend : object
            Opaque embedding-backend descriptor supplied by the caller.

        Returns
        -------
        bool
            ``True`` when the recording backend reports a matching state.
        """
        return self._backend.current_embedding_state_matches(
            self._root,
            embedding_backend=embedding_backend,
            conn=self._conn,
        )

    def load_previous_embeddings_by_path(
        self,
        *,
        paths: list[str],
        embedding_backend: object,
    ) -> dict[str, dict[str, StoredEmbeddingRow]]:
        """
        Return reusable embeddings for the requested replacement paths.

        Parameters
        ----------
        paths : list[str]
            Absolute file paths selected for replacement.
        embedding_backend : object
            Opaque embedding-backend descriptor supplied by the caller.

        Returns
        -------
        dict[str, dict[str, StoredEmbeddingRow]]
            Reusable embeddings grouped by absolute path.
        """
        return self._backend.load_previous_embeddings_by_path(
            self._root,
            paths=paths,
            embedding_backend=embedding_backend,
            conn=self._conn,
        )

    def count_reusable_embeddings(self, *, paths: list[str]) -> int:
        """
        Count embeddings preserved for unchanged files.

        Parameters
        ----------
        paths : list[str]
            Absolute file paths reused without reparsing.

        Returns
        -------
        int
            Number of reusable embedding rows.
        """
        return self._backend.count_reusable_embeddings(
            self._root,
            paths=paths,
            conn=self._conn,
        )

    def prepare(
        self,
        *,
        full: bool,
        indexed_paths: list[str],
        deleted_paths: list[str],
    ) -> None:
        """
        Perform no-op storage preparation for recording tests.

        Parameters
        ----------
        full : bool
            Whether the current run is a full rebuild.
        indexed_paths : list[str]
            Absolute file paths selected for reindexing.
        deleted_paths : list[str]
            Absolute file paths removed from the repository.

        Returns
        -------
        None
            The recording session does not mutate storage during preparation.
        """
        del full, indexed_paths, deleted_paths

    def persist_analysis(
        self,
        request: BackendPersistAnalysisRequest,
    ) -> tuple[int, int]:
        """
        Record no analyzed-file persistence work.

        Parameters
        ----------
        request : BackendPersistAnalysisRequest
            Persistence request supplied by the caller.

        Returns
        -------
        tuple[int, int]
            ``(0, 0)`` for the recording backend.
        """
        return self._backend.persist_analysis(request)

    def rebuild_derived_indexes(self) -> None:
        """
        Perform no-op derived-index rebuilding.

        Parameters
        ----------
        None

        Returns
        -------
        None
            The recording session performs no additional work beyond delegation.
        """
        self._backend.rebuild_derived_indexes(self._root, conn=self._conn)

    def persist_runtime_inventory(
        self,
        request: BackendRuntimeInventoryRequest,
    ) -> None:
        """
        Record runtime inventory for the test backend.

        Parameters
        ----------
        request : BackendRuntimeInventoryRequest
            Runtime inventory request supplied by the caller.

        Returns
        -------
        None
            The recording session forwards the inventory request to the backend.
        """
        self._backend.persist_runtime_inventory(request)

    def commit(self) -> None:
        """
        Perform no-op commit handling for recording tests.

        Parameters
        ----------
        None

        Returns
        -------
        None
            The recording session delegates to the backend commit hook.
        """
        self._backend.commit(self._root, conn=self._conn)

    def abort(self) -> None:
        """
        Perform no-op abort handling for recording tests.

        Parameters
        ----------
        None

        Returns
        -------
        None
            The recording session does not perform rollback work.
        """

    def close(self) -> None:
        """
        Close the recorded backend connection.

        Parameters
        ----------
        None

        Returns
        -------
        None
            The recorded connection is closed once per session.
        """
        self._backend.close_connection(self._conn)


class _RecordingBackend:
    """
    Backend stub that records CLI integration calls without SQLite semantics.

    Parameters
    ----------
    runtime_inventory : tuple[str, str, int] | None, optional
        Runtime inventory returned by ``load_runtime_inventory``.
    analyzer_inventory : list[tuple[str, str, str]] | None, optional
        Analyzer inventory returned by ``load_analyzer_inventory``.
    file_hashes : dict[str, str] | None, optional
        Indexed file hashes returned by ``load_existing_file_hashes``.
    """

    name = "duckdb"
    version = "1.5.3"

    def __init__(
        self,
        *,
        runtime_inventory: tuple[str, str, int] | None = ("duckdb", "1.5.3", 1),
        analyzer_inventory: list[tuple[str, str, str]] | None = None,
        file_hashes: dict[str, str] | None = None,
    ) -> None:
        self.runtime_inventory = runtime_inventory
        self.analyzer_inventory = (
            [] if analyzer_inventory is None else analyzer_inventory
        )
        self.file_hashes = {} if file_hashes is None else file_hashes
        self.initialize_calls: list[Path] = []
        self.opened: list[Path] = []
        self.closed: list[_RecordingBackendConnection] = []
        self.count_indexed_file_calls: list[Path] = []
        self.load_existing_file_hash_calls: list[Path] = []

    def begin_index_session(self, root: Path) -> _RecordingIndexWriteSession:
        """
        Return one recording write session.

        Parameters
        ----------
        root : pathlib.Path
            Repository root whose backend state may be mutated.

        Returns
        -------
        _RecordingIndexWriteSession
            Recording write session for test assertions.
        """
        return _RecordingIndexWriteSession(self, root)

    def initialize(self, root: Path) -> None:
        """
        Record backend initialization for one repository root.

        Parameters
        ----------
        root : pathlib.Path
            Repository root passed to the backend initializer.

        Returns
        -------
        None
            The root is appended to the recorded initialization list.
        """
        self.initialize_calls.append(root)

    def open_connection(self, root: Path) -> _RecordingBackendConnection:
        """
        Return one opaque connection handle.

        Parameters
        ----------
        root : pathlib.Path
            Repository root passed to the backend connection opener.

        Returns
        -------
        _RecordingBackendConnection
            Fresh opaque connection handle for test assertions.
        """
        self.opened.append(root)
        return _RecordingBackendConnection()

    def close_connection(self, conn: object) -> None:
        """
        Record one closed connection handle.

        Parameters
        ----------
        conn : object
            Connection object supplied by the CLI integration path.

        Returns
        -------
        None
            The validated connection handle is appended to the closed list.
        """
        assert isinstance(conn, _RecordingBackendConnection)
        self.closed.append(conn)

    def load_runtime_inventory(
        self,
        root: Path,
        *,
        conn: object | None = None,
    ) -> tuple[str, str, int] | None:
        """
        Return the configured runtime inventory.

        Parameters
        ----------
        root : pathlib.Path
            Repository root associated with the lookup.
        conn : object | None, optional
            Opaque backend connection handle reused by the caller.

        Returns
        -------
        tuple[str, str, int] | None
            Recorded runtime inventory, or ``None`` when unavailable.
        """
        del root, conn
        return self.runtime_inventory

    def load_analyzer_inventory(
        self,
        root: Path,
        *,
        conn: object | None = None,
    ) -> list[tuple[str, str, str]]:
        """
        Return the configured analyzer inventory.

        Parameters
        ----------
        root : pathlib.Path
            Repository root associated with the lookup.
        conn : object | None, optional
            Opaque backend connection handle reused by the caller.

        Returns
        -------
        list[tuple[str, str, str]]
            Recorded analyzer inventory rows.
        """
        del root, conn
        return list(self.analyzer_inventory)

    def load_existing_file_hashes(
        self,
        root: Path,
        *,
        conn: object | None = None,
    ) -> dict[str, str]:
        """
        Return the configured indexed file hashes.

        Parameters
        ----------
        root : pathlib.Path
            Repository root associated with the lookup.
        conn : object | None, optional
            Opaque backend connection handle reused by the caller.

        Returns
        -------
        dict[str, str]
            Recorded file-hash mapping for the backend snapshot.
        """
        del conn
        self.load_existing_file_hash_calls.append(root)
        return dict(self.file_hashes)

    def count_indexed_files(
        self,
        root: Path,
        *,
        conn: object | None = None,
    ) -> int:
        """
        Return the number of configured indexed files.

        Parameters
        ----------
        root : pathlib.Path
            Repository root associated with the lookup.
        conn : object | None, optional
            Opaque backend connection handle reused by the caller.

        Returns
        -------
        int
            Count of indexed file rows for freshness checks.
        """
        del conn
        self.count_indexed_file_calls.append(root)
        return len(self.file_hashes)

    def load_existing_file_ownership(
        self,
        root: Path,
        *,
        conn: object | None = None,
    ) -> dict[str, tuple[str, str]]:
        """
        Return no persisted analyzer ownership.

        Parameters
        ----------
        root : pathlib.Path
            Repository root associated with the lookup.
        conn : object | None, optional
            Opaque backend connection handle reused by the caller.

        Returns
        -------
        dict[str, tuple[str, str]]
            Empty analyzer-ownership mapping for the stub backend.
        """
        del root, conn
        return {}

    def current_embedding_state_matches(
        self,
        root: Path,
        *,
        embedding_backend: object,
        conn: object | None = None,
    ) -> bool:
        """
        Report a matching embedding backend state.

        Parameters
        ----------
        root : pathlib.Path
            Repository root associated with the lookup.
        embedding_backend : object
            Opaque embedding-backend descriptor supplied by the caller.
        conn : object | None, optional
            Opaque backend connection handle reused by the caller.

        Returns
        -------
        bool
            Always ``True`` for the recording stub.
        """
        del root, embedding_backend, conn
        return True

    def load_previous_embeddings_by_path(
        self,
        root: Path,
        *,
        paths: list[str],
        embedding_backend: object,
        conn: object | None = None,
    ) -> dict[str, dict[str, StoredEmbeddingRow]]:
        """
        Return no reusable embeddings for the supplied paths.

        Parameters
        ----------
        root : pathlib.Path
            Repository root associated with the lookup.
        paths : list[str]
            Indexed file paths selected for replacement.
        embedding_backend : object
            Opaque embedding-backend descriptor supplied by the caller.
        conn : object | None, optional
            Opaque backend connection handle reused by the caller.

        Returns
        -------
        dict[str, dict[str, StoredEmbeddingRow]]
            Empty reusable-embedding mapping for the stub backend.
        """
        del root, paths, embedding_backend, conn
        return {}

    def count_reusable_embeddings(
        self,
        root: Path,
        *,
        paths: list[str],
        conn: object | None = None,
    ) -> int:
        """
        Return zero reusable embeddings.

        Parameters
        ----------
        root : pathlib.Path
            Repository root associated with the lookup.
        paths : list[str]
            Indexed file paths considered reusable.
        conn : object | None, optional
            Opaque backend connection handle reused by the caller.

        Returns
        -------
        int
            Always ``0`` for the recording stub.
        """
        del root, paths, conn
        return 0

    def purge_skipped_docstring_issues(
        self,
        root: Path,
        *,
        conn: object | None = None,
    ) -> None:
        """
        Perform no-op skipped-docstring cleanup.

        Parameters
        ----------
        root : pathlib.Path
            Repository root associated with the cleanup.
        conn : object | None, optional
            Opaque backend connection handle reused by the caller.

        Returns
        -------
        None
            The recording backend performs no mutation.
        """
        del root, conn

    def prune_orphaned_embeddings(
        self,
        root: Path,
        *,
        conn: object | None = None,
    ) -> None:
        """
        Perform no-op orphaned-embedding cleanup.

        Parameters
        ----------
        root : pathlib.Path
            Repository root associated with the cleanup.
        conn : object | None, optional
            Opaque backend connection handle reused by the caller.

        Returns
        -------
        None
            The recording backend performs no mutation.
        """
        del root, conn

    def persist_analysis(
        self,
        request: BackendPersistAnalysisRequest,
    ) -> tuple[int, int]:
        """
        Record no analyzed-file persistence work.

        Parameters
        ----------
        request : BackendPersistAnalysisRequest
            Persistence request supplied by the caller.

        Returns
        -------
        tuple[int, int]
            Always ``(0, 0)`` for the recording stub.
        """
        del request
        return (0, 0)

    def rebuild_derived_indexes(
        self,
        root: Path,
        *,
        conn: object | None = None,
    ) -> None:
        """
        Perform no-op derived-index rebuilding.

        Parameters
        ----------
        root : pathlib.Path
            Repository root associated with the rebuild.
        conn : object | None, optional
            Opaque backend connection handle reused by the caller.

        Returns
        -------
        None
            The recording backend performs no mutation.
        """
        del root, conn

    def persist_runtime_inventory(
        self,
        request: BackendRuntimeInventoryRequest,
    ) -> None:
        """
        Record runtime inventory without mutating storage.

        Parameters
        ----------
        request : BackendRuntimeInventoryRequest
            Runtime inventory request supplied by the caller.

        Returns
        -------
        None
            The in-memory inventory tuple is updated in place.
        """
        self.runtime_inventory = (
            str(request.backend_name),
            str(request.backend_version),
            int(request.coverage_complete),
        )

    def commit(self, root: Path, *, conn: object) -> None:
        """
        Perform no-op commit handling.

        Parameters
        ----------
        root : pathlib.Path
            Repository root associated with the commit.
        conn : object
            Opaque backend connection handle reused by the caller.

        Returns
        -------
        None
            The recording backend performs no mutation.
        """
        del root, conn


def test_run_index_initializes_the_active_backend(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Initialize the configured backend before indexing from the CLI path.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository root provided by pytest.
    monkeypatch : pytest.MonkeyPatch
        Fixture used to stub backend selection and indexing side effects.

    Returns
    -------
    None
        The test asserts ``codira index`` initialization uses the active
        backend contract instead of calling SQLite storage helpers directly.
    """
    backend = _RecordingBackend()
    cli_module = _load_workspace_cli_module()

    monkeypatch.setattr(
        cli_module, "active_index_backend", lambda *, root=None: backend
    )
    monkeypatch.setattr(cli_module, "audit_repo_coverage", lambda root: [])
    monkeypatch.setattr(
        cli_module,
        "index_repo",
        lambda root, full=False, embedding_index_mode=None: types.SimpleNamespace(
            coverage_issues=[],
            decisions=[],
            indexed=[],
            reused=[],
            deleted=[],
            failed=[],
            embedding_recomputed=0,
            embedding_reused=0,
        ),
    )
    monkeypatch.setattr(
        cli_module,
        "_write_index_head_metadata",
        lambda root, *, indexed_file_count=None: None,
    )
    monkeypatch.setattr(cli_module, "_render_index_report", lambda root, report: None)

    assert (
        cli_module._run_index(
            IndexCommandRequest(
                root=tmp_path,
                full=False,
                explain=False,
                require_full_coverage=False,
                defer_embeddings=False,
                embeddings_only=False,
                as_json=False,
            )
        )
        == 0
    )
    assert backend.initialize_calls == [tmp_path]


def test_inspect_index_rebuild_request_uses_backend_connection_contract(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Inspect freshness through backend hooks without SQLite-specific connection use.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository root provided by pytest.
    monkeypatch : pytest.MonkeyPatch
        Fixture used to stub backend state and Git metadata.

    Returns
    -------
    None
        The test asserts freshness inspection reuses backend hooks and closes
        the opaque connection handle.
    """
    module = tmp_path / "pkg" / "sample.py"
    cli_module = _load_workspace_cli_module()
    _write_module(
        module,
        'def demo():\n    """Return a constant."""\n    return 1\n',
    )
    python_inventory = [_analyzer_inventory_row(PythonAnalyzer())]
    backend = _RecordingBackend(
        analyzer_inventory=python_inventory,
        file_hashes={str(module): "abc123"},
    )
    cli_module._write_index_metadata(
        tmp_path,
        {
            "schema_version": str(SCHEMA_VERSION),
        },
    )

    monkeypatch.setattr(cli_module, "_get_head_commit", lambda root: None)
    monkeypatch.setattr(
        cli_module, "active_index_backend", lambda *, root=None: backend
    )
    monkeypatch.setattr(
        cli_module,
        "active_language_analyzers",
        lambda *, root=None: [PythonAnalyzer()],
    )

    assert cli_module._inspect_index_rebuild_request(tmp_path) is None
    assert backend.opened == [tmp_path]
    assert len(backend.closed) == 1
    assert backend.count_indexed_file_calls == [tmp_path]
    assert backend.load_existing_file_hash_calls == []


def test_inspect_index_rebuild_request_uses_complete_metadata_fast_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Avoid opening the backend when persisted freshness metadata is complete.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository root provided by pytest.
    monkeypatch : pytest.MonkeyPatch
        Fixture used to stub backend state and Git metadata.

    Returns
    -------
    None
        The test asserts metadata-only checks can prove freshness without one
        backend connection.
    """
    module = tmp_path / "pkg" / "sample.py"
    cli_module = _load_workspace_cli_module()
    _write_module(
        module,
        'def demo():\n    """Return a constant."""\n    return 1\n',
    )
    python_inventory = [_analyzer_inventory_row(PythonAnalyzer())]
    backend = _RecordingBackend(
        analyzer_inventory=python_inventory,
        file_hashes={str(module): "abc123"},
    )
    cli_module._write_index_metadata(
        tmp_path,
        {
            "schema_version": str(SCHEMA_VERSION),
            "backend_name": "duckdb",
            "backend_version": "1.5.3",
            "analyzer_inventory": json.dumps(python_inventory),
            "indexed_file_count": "1",
        },
    )

    monkeypatch.setattr(cli_module, "_get_head_commit", lambda root: None)
    monkeypatch.setattr(
        cli_module, "active_index_backend", lambda *, root=None: backend
    )
    monkeypatch.setattr(
        cli_module,
        "active_language_analyzers",
        lambda *, root=None: [PythonAnalyzer()],
    )

    assert cli_module._inspect_index_rebuild_request(tmp_path) is None
    assert backend.opened == []
    assert backend.count_indexed_file_calls == []
    assert backend.load_existing_file_hash_calls == []


def test_cli_reports_unexpected_index_errors_without_traceback(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """
    Collapse unexpected index failures into concise CLI stderr output.

    Parameters
    ----------
    monkeypatch : pytest.MonkeyPatch
        Fixture used to force one indexing failure.
    capsys : pytest.CaptureFixture[str]
        Fixture used to capture CLI output.

    Returns
    -------
    None
        The test asserts the CLI reports the failure without a traceback.
    """
    monkeypatch.setattr(
        "codira.cli._run_index",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            ValueError(
                "duplicate stable_id(s) in native/annotated.c: "
                "c:function:native.annotated:PRINTF_FORMAT"
            )
        ),
    )
    monkeypatch.setattr(sys, "argv", ["codira", "index"])

    assert main() == 2
    captured = capsys.readouterr()
    assert "native/annotated.c" in captured.err
    assert "Traceback" not in captured.err
    assert captured.out == ""


def test_cli_reports_missing_path_without_traceback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """
    Collapse invalid ``--path`` resolution into concise parser stderr.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary directory used to construct a missing target path.
    monkeypatch : pytest.MonkeyPatch
        Fixture used to control CLI arguments.
    capsys : pytest.CaptureFixture[str]
        Fixture used to capture CLI output.

    Returns
    -------
    None
        The test asserts a missing target path reports an argparse error
        without exposing a traceback.
    """
    missing_path = tmp_path / "missing-repo"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "codira",
            "calls",
            "main",
            "--module",
            "codira.cli",
            "--tree",
            "--dot",
            "--path",
            str(missing_path),
        ],
    )

    with pytest.raises(SystemExit) as exc:
        main()

    captured = capsys.readouterr()
    assert exc.value.code == 2
    assert str(missing_path) in captured.err
    assert "Target directory cannot be resolved:" in captured.err
    assert "Traceback" not in captured.err
    assert captured.out == ""


def test_index_cli_fails_gracefully_when_no_language_analyzers_are_registered(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """
    Fail with concise stderr when no language analyzers are available.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository root used as the CLI working directory.
    monkeypatch : pytest.MonkeyPatch
        Fixture used to patch plugin discovery and argv.
    capsys : pytest.CaptureFixture[str]
        Fixture used to capture CLI output.

    Returns
    -------
    None
        The test asserts the CLI returns a stable failure code and message.
    """
    original_entry_points = registry_module._entry_points_for_group

    def _entry_points_without_analyzers(group: str) -> list[object]:
        if group == registry_module.ANALYZER_ENTRY_POINT_GROUP:
            return []
        return cast("list[object]", original_entry_points(group))

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["codira", "index"])
    monkeypatch.setattr(
        registry_module,
        "_entry_points_for_group",
        _entry_points_without_analyzers,
    )

    assert main() == 2
    captured = capsys.readouterr()

    assert "No language analyzers are registered for codira" in captured.err
    assert captured.out == ""


def test_index_cli_fails_gracefully_when_no_backend_plugins_are_registered(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """
    Fail with concise stderr when the configured backend plugin is unavailable.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository root used as the CLI working directory.
    monkeypatch : pytest.MonkeyPatch
        Fixture used to patch plugin discovery and argv.
    capsys : pytest.CaptureFixture[str]
        Fixture used to capture CLI output.

    Returns
    -------
    None
        The test asserts the CLI returns a stable failure code and install hint.
    """
    original_entry_points = registry_module._entry_points_for_group

    def _entry_points_without_backends(group: str) -> list[object]:
        if group == registry_module.BACKEND_ENTRY_POINT_GROUP:
            return []
        return cast("list[object]", original_entry_points(group))

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["codira", "index"])
    monkeypatch.setenv(registry_module.INDEX_BACKEND_ENV_VAR, "sqlite")
    monkeypatch.setattr(
        registry_module,
        "_entry_points_for_group",
        _entry_points_without_backends,
    )

    assert main() == 2
    captured = capsys.readouterr()

    assert "Unsupported codira backend 'sqlite'" in captured.err
    assert "codira-backend-sqlite" in captured.err
    assert captured.out == ""


def test_index_repo_reuses_unchanged_files(tmp_path: Path) -> None:
    """
    Ensure an unchanged repository is not reparsed on the second run.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary directory provided by pytest.

    Returns
    -------
    None
        The test asserts deterministic reuse counts and preserved embeddings.
    """
    module = tmp_path / "pkg" / "sample.py"
    _write_module(
        module,
        '"""Module doc."""\n'
        "\n"
        "def demo():\n"
        '    """Return a constant."""\n'
        "    return 1\n",
    )

    init_db(tmp_path)
    first = index_repo(tmp_path)
    second = index_repo(tmp_path)

    assert first.indexed == 1
    assert first.reused == 0
    assert first.deleted == 0
    assert first.embeddings_recomputed > 0

    assert second.indexed == 0
    assert second.reused == 1
    assert second.deleted == 0
    assert second.embeddings_recomputed == 0
    assert second.embeddings_reused == first.embeddings_recomputed


def test_index_repo_skips_write_session_for_unchanged_repository(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Avoid opening a write session when the repository index is already warm.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary directory provided by pytest.
    monkeypatch : pytest.MonkeyPatch
        Fixture used to patch backend selection for the indexer.

    Returns
    -------
    None
        The test asserts unchanged repositories reuse metadata through the
        read path without entering writer setup.
    """
    module = tmp_path / "pkg" / "sample.py"
    _write_module(
        module,
        '"""Module doc."""\n'
        "\n"
        "def demo():\n"
        '    """Return a constant."""\n'
        "    return 1\n",
    )
    backend = _TrackingSQLiteBackend()
    monkeypatch.setattr(
        indexer_module,
        "active_index_backend",
        lambda *, root=None: backend,
    )

    first = index_repo(tmp_path)
    assert first.indexed == 1
    assert backend.begin_index_session_calls == 1

    backend.begin_index_session_calls = 0
    backend.open_connection_calls = 0
    backend.close_connection_calls = 0
    second = index_repo(tmp_path)

    assert second.indexed == 0
    assert second.reused == 1
    assert backend.begin_index_session_calls == 0
    assert backend.open_connection_calls == 1
    assert backend.close_connection_calls == 1


def test_index_repo_accepts_pep_263_encoded_python_sources(tmp_path: Path) -> None:
    """
    Index Python files that declare a non-UTF-8 source encoding.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary directory provided by pytest.

    Returns
    -------
    None
        The test asserts encoding-cookie-aware Python analysis avoids file
        failures during indexing.
    """
    module = tmp_path / "pkg" / "encoded_sample.py"
    module.parent.mkdir(parents=True, exist_ok=True)
    module.write_bytes('# coding: latin-1\nTITLE = "café"\n'.encode("latin-1"))

    init_db(tmp_path)
    report = index_repo(tmp_path)

    assert report.indexed == 1
    assert report.failed == 0
    assert report.failures == []


def test_index_repo_purges_stale_shell_docstring_issues(tmp_path: Path) -> None:
    """
    Remove stale shell docstring issues during a normal incremental index run.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary directory provided by pytest.

    Returns
    -------
    None
        The test asserts shell-owned docstring issues disappear without
        reindexing unchanged files.
    """
    script_dir = tmp_path / "scripts"
    script_dir.mkdir()
    shell_path = script_dir / "build.sh"
    shell_path.write_text("build() {\n    echo hello\n}\n", encoding="utf-8")

    init_db(tmp_path)
    first = index_repo(tmp_path)
    assert first.indexed == 1
    assert docstring_issues(tmp_path) == []

    conn = sqlite3.connect(get_db_path(tmp_path))
    try:
        file_id = int(
            conn.execute(
                "SELECT id FROM files WHERE path = ?",
                (str(shell_path),),
            ).fetchone()[0]
        )
        conn.execute(
            "INSERT INTO docstring_issues"
            "(file_id, function_id, class_id, module_id, issue_type, message) "
            "VALUES (?, NULL, NULL, NULL, ?, ?)",
            (
                file_id,
                "missing",
                "Function build: Missing docstring",
            ),
        )
        conn.commit()
    finally:
        conn.close()

    assert [issue[1] for issue in docstring_issues(tmp_path)] == [
        "Function build: Missing docstring"
    ]

    second = index_repo(tmp_path)

    assert second.indexed == 0
    assert second.reused == 1
    assert docstring_issues(tmp_path) == []


def test_index_repo_reports_duplicate_stable_ids_as_file_failures(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Report duplicate stable IDs as file-scoped failures instead of aborting.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary directory provided by pytest.
    monkeypatch : pytest.MonkeyPatch
        Fixture used to force one duplicate-stable-id diagnostic.

    Returns
    -------
    None
        The test asserts the run completes and records one failed file.
    """
    module = tmp_path / "pkg" / "sample.py"
    _write_module(
        module,
        '"""Module doc."""\n'
        "\n"
        "def demo():\n"
        '    """Return a constant."""\n'
        "    return 1\n",
    )

    monkeypatch.setattr(
        "codira.indexer._duplicate_analysis_stable_ids",
        lambda analysis: ["python:function:pkg.sample:demo"],
    )

    report = index_repo(tmp_path)

    assert report.indexed == 0
    assert report.failed == 1
    assert report.failures[0].path == str(module)
    assert "duplicate stable_id(s)" in report.failures[0].reason


def test_duplicate_analysis_stable_ids_include_documentation_artifacts(
    tmp_path: Path,
) -> None:
    """
    Include documentation artifacts in per-file stable-ID validation.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary directory provided by pytest.

    Returns
    -------
    None
        The test asserts duplicate documentation identities are reported
        before backend persistence.
    """
    document = tmp_path / "docs" / "guide.md"
    duplicate_id = "doc:section:docs/guide.md:section:1:line-1"
    analysis = AnalysisResult(
        source_path=document,
        module=ModuleArtifact(
            name="docs.guide",
            stable_id="markdown:module:docs/guide.md",
            docstring=None,
            has_docstring=0,
        ),
        classes=(),
        functions=(),
        declarations=(),
        imports=(),
        documentation=(
            DocumentationArtifact(
                stable_id=duplicate_id,
                kind="section",
                source_format="markdown_section",
                source_path=document,
                lineno=1,
                end_lineno=2,
                title="One",
                heading_path=("One",),
                text="One",
            ),
            DocumentationArtifact(
                stable_id=duplicate_id,
                kind="section",
                source_format="markdown_section",
                source_path=document,
                lineno=3,
                end_lineno=4,
                title="Two",
                heading_path=("Two",),
                text="Two",
            ),
        ),
        index_symbols=False,
    )

    assert indexer_module._duplicate_analysis_stable_ids(analysis) == [duplicate_id]


def test_index_repo_indexes_python_module_file_shadowed_by_package(
    tmp_path: Path,
) -> None:
    """
    Index valid Python module files shadowed by sibling packages.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary directory provided by pytest.

    Returns
    -------
    None
        The test asserts shadowed module files receive path-qualified stable
        IDs while package ``__init__`` files keep canonical import identities.
    """
    module_file = tmp_path / "pkg" / "mod.py"
    package_init = tmp_path / "pkg" / "mod" / "__init__.py"
    _write_module(
        module_file,
        '"""Module file."""\n'
        "\n"
        "def from_file():\n"
        '    """Return file value."""\n'
        "    return 1\n",
    )
    _write_module(
        package_init,
        '"""Package module."""\n'
        "\n"
        "def from_package():\n"
        '    """Return package value."""\n'
        "    return 2\n",
    )

    report = index_repo(tmp_path)

    conn = sqlite3.connect(get_db_path(tmp_path))
    try:
        rows = conn.execute(
            """
            SELECT name, stable_id, type
            FROM symbol_index
            WHERE module_name = 'pkg.mod'
            ORDER BY stable_id
            """
        ).fetchall()
    finally:
        conn.close()

    stable_ids = [str(row[1]) for row in rows]

    assert report.indexed == 2
    assert report.failed == 0
    assert len(stable_ids) == len(set(stable_ids))
    assert ("pkg.mod", "python:module:pkg.mod", "module") in rows
    assert (
        "pkg.mod",
        "python:module:pkg.mod:path:pkg/mod.py",
        "module",
    ) in rows
    assert "python:function:pkg.mod:path:pkg/mod.py:from_file" in stable_ids
    assert "python:function:pkg.mod:from_package" in stable_ids


def test_persist_analysis_deduplicates_identical_call_and_ref_rows(
    tmp_path: Path,
) -> None:
    """
    Deduplicate identical normalized call and callable-reference rows.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary directory provided by pytest.

    Returns
    -------
    None
        The test asserts persistence stores one row for each duplicate record.
    """
    module = tmp_path / "pkg" / "sample.py"
    _write_module(module, "def demo():\n    return 1\n")

    duplicate_call = CallSite(
        kind="name",
        target="helper",
        lineno=1,
        col_offset=4,
    )
    duplicate_ref = CallableReference(
        kind="name",
        target="helper",
        lineno=1,
        col_offset=6,
        ref_kind="return_value",
    )
    analysis = AnalysisResult(
        source_path=module,
        module=ModuleArtifact(
            name="pkg.sample",
            stable_id="python:module:pkg.sample",
            docstring=None,
            has_docstring=0,
        ),
        classes=(),
        functions=(
            FunctionArtifact(
                name="demo",
                stable_id="python:function:pkg.sample:demo",
                lineno=1,
                end_lineno=2,
                signature="def demo()",
                docstring=None,
                has_docstring=0,
                is_method=0,
                is_public=1,
                parameters=(),
                returns_value=1,
                yields_value=0,
                raises=0,
                has_asserts=0,
                decorators=(),
                calls=(duplicate_call, duplicate_call),
                callable_refs=(duplicate_ref, duplicate_ref),
            ),
        ),
        declarations=(),
        imports=(),
    )
    metadata = file_metadata(module)

    init_db(tmp_path)
    backend = SQLiteIndexBackend()
    backend.persist_analysis(
        BackendPersistAnalysisRequest(
            root=tmp_path,
            file_metadata=FileMetadataSnapshot(
                path=module,
                sha256=cast("str", metadata["hash"]),
                mtime=cast("float", metadata["mtime"]),
                size=cast("int", metadata["size"]),
                analyzer_name="python",
                analyzer_version="1",
            ),
            analysis=analysis,
        )
    )

    conn = sqlite3.connect(get_db_path(tmp_path))
    try:
        call_count = conn.execute(
            "SELECT COUNT(*) FROM call_records WHERE owner_name = 'demo'"
        ).fetchone()[0]
        ref_count = conn.execute(
            "SELECT COUNT(*) FROM callable_ref_records WHERE owner_name = 'demo'"
        ).fetchone()[0]
    finally:
        conn.close()

    assert call_count == 1
    assert ref_count == 1


def test_index_repo_reindexes_changed_files(tmp_path: Path) -> None:
    """
    Ensure content changes trigger reparsing for the modified file only.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary directory provided by pytest.

    Returns
    -------
    None
        The test asserts changed-file reindexing and updated symbol contents.
    """
    module = tmp_path / "pkg" / "sample.py"
    _write_module(
        module,
        '"""Module doc."""\n'
        "\n"
        "def demo():\n"
        '    """Return a constant."""\n'
        "    return 1\n",
    )

    init_db(tmp_path)
    first_meta = file_metadata(module)
    index_repo(tmp_path)

    _write_module(
        module,
        '"""Module doc."""\n'
        "\n"
        "def demo():\n"
        '    """Return a constant."""\n'
        "    return 1\n"
        "\n"
        "def extra():\n"
        '    """Return another constant."""\n'
        "    return 2\n",
    )

    second_meta = file_metadata(module)
    report = index_repo(tmp_path)

    assert second_meta["hash"] != first_meta["hash"]
    assert report.indexed == 1
    assert report.reused == 0
    assert report.deleted == 0
    assert report.embeddings_recomputed > 0
    assert find_symbol(tmp_path, "extra")


def test_index_repo_refreshes_stored_reference_scan_rows(tmp_path: Path) -> None:
    """
    Keep stored query-time reference rows aligned with file changes and deletes.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary directory provided by pytest.

    Returns
    -------
    None
        The test asserts stored non-import scan rows are replaced and removed
        with their owning file.
    """
    module = tmp_path / "pkg" / "sample.py"
    _write_module(
        module,
        "import helper\nfrom pkg import thing\nvalue = helper\nhelper()\n",
    )

    init_db(tmp_path)
    index_repo(tmp_path)

    conn = sqlite3.connect(get_db_path(tmp_path))
    try:
        first_count = conn.execute(
            """
            SELECT COUNT(*)
            FROM reference_scan_lines rsl
            JOIN files f
              ON rsl.file_id = f.id
            WHERE f.path = ?
            """,
            (str(module),),
        ).fetchone()[0]
    finally:
        conn.close()

    _write_module(
        module,
        "import helper\nhelper()\n",
    )
    index_repo(tmp_path)

    conn = sqlite3.connect(get_db_path(tmp_path))
    try:
        second_count = conn.execute(
            """
            SELECT COUNT(*)
            FROM reference_scan_lines rsl
            JOIN files f
              ON rsl.file_id = f.id
            WHERE f.path = ?
            """,
            (str(module),),
        ).fetchone()[0]
    finally:
        conn.close()

    module.unlink()
    index_repo(tmp_path)

    conn = sqlite3.connect(get_db_path(tmp_path))
    try:
        final_count = conn.execute(
            """
            SELECT COUNT(*)
            FROM reference_scan_lines rsl
            JOIN files f
              ON rsl.file_id = f.id
            WHERE f.path = ?
            """,
            (str(module),),
        ).fetchone()[0]
    finally:
        conn.close()

    assert first_count == 2
    assert second_count == 1
    assert final_count == 0


def test_index_repo_reuses_unchanged_symbol_embeddings_in_changed_file(
    tmp_path: Path,
) -> None:
    """
    Reuse stable symbol embeddings when unrelated edits touch the same file.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary directory provided by pytest.

    Returns
    -------
    None
        The test asserts stable-id matching preserves unchanged symbol
        embeddings inside a changed file.
    """
    module = tmp_path / "pkg" / "sample.py"
    _write_module(
        module,
        '"""Module doc."""\n'
        "\n"
        "def keep_me():\n"
        '    """Stay semantically unchanged."""\n'
        "    return 1\n"
        "\n"
        "def change_me():\n"
        '    """Old semantic text."""\n'
        "    return 2\n",
    )

    init_db(tmp_path)
    first = index_repo(tmp_path)

    conn = sqlite3.connect(get_db_path(tmp_path))
    try:
        before = conn.execute(
            """
            SELECT e.content_hash, e.vector
            FROM embeddings e
            JOIN symbol_index s
              ON e.object_type = 'symbol'
             AND e.object_id = s.id
            WHERE s.stable_id = ?
            """,
            ("python:function:pkg.sample:keep_me",),
        ).fetchone()
    finally:
        conn.close()

    _write_module(
        module,
        '"""Module doc."""\n'
        "\n"
        "def keep_me():\n"
        '    """Stay semantically unchanged."""\n'
        "    return 1\n"
        "\n"
        "def change_me():\n"
        '    """New semantic text for recomputation."""\n'
        "    return 2\n"
        "\n"
        "# unrelated trailing comment\n",
    )

    report = index_repo(tmp_path)

    conn = sqlite3.connect(get_db_path(tmp_path))
    try:
        after = conn.execute(
            """
            SELECT e.content_hash, e.vector
            FROM embeddings e
            JOIN symbol_index s
              ON e.object_type = 'symbol'
             AND e.object_id = s.id
            WHERE s.stable_id = ?
            """,
            ("python:function:pkg.sample:keep_me",),
        ).fetchone()
    finally:
        conn.close()

    assert first.embeddings_recomputed == 4
    assert report.indexed == 1
    assert report.embeddings_reused == 3
    assert report.embeddings_recomputed == 1
    assert before == after


def test_index_repo_removes_deleted_files(tmp_path: Path) -> None:
    """
    Ensure deleted files are removed while unchanged files are reused.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary directory provided by pytest.

    Returns
    -------
    None
        The test asserts deleted-file cleanup and retained reused rows.
    """
    keep_module = tmp_path / "pkg" / "keep.py"
    drop_module = tmp_path / "pkg" / "drop.py"
    _write_module(
        keep_module,
        'def keep():\n    """Stay indexed."""\n    return 1\n',
    )
    _write_module(
        drop_module,
        'def drop_me():\n    """Disappear from the index."""\n    return 1\n',
    )

    init_db(tmp_path)
    index_repo(tmp_path)

    drop_module.unlink()
    report = index_repo(tmp_path)

    assert report.indexed == 0
    assert report.reused == 1
    assert report.deleted == 1
    assert find_symbol(tmp_path, "drop_me") == []
    assert find_symbol(tmp_path, "keep")


def test_index_repo_removes_unstaged_deleted_tracked_files(tmp_path: Path) -> None:
    """
    Remove tracked files that disappeared from the working tree before staging.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary directory provided by pytest.

    Returns
    -------
    None
        The test asserts Git-backed discovery tolerates unstaged deletions and
        still removes the missing file from the index.
    """
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    keep_module = tmp_path / "pkg" / "keep.py"
    drop_module = tmp_path / "pkg" / "drop.py"
    _write_module(
        keep_module,
        'def keep():\n    """Stay indexed."""\n    return 1\n',
    )
    _write_module(
        drop_module,
        'def drop_me():\n    """Disappear from the index."""\n    return 1\n',
    )
    subprocess.run(
        ["git", "add", "pkg/keep.py", "pkg/drop.py"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )

    init_db(tmp_path)
    index_repo(tmp_path)

    drop_module.unlink()
    report = index_repo(tmp_path)

    assert report.indexed == 0
    assert report.reused == 1
    assert report.deleted == 1
    assert find_symbol(tmp_path, "drop_me") == []
    assert find_symbol(tmp_path, "keep")


def test_index_repo_recomputes_embeddings_when_backend_changes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Ensure backend-version changes invalidate reused embeddings explicitly.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary directory provided by pytest.
    monkeypatch : pytest.MonkeyPatch
        Fixture used to replace the active backend metadata.

    Returns
    -------
    None
        The test asserts backend invalidation triggers reparsing and storage
        of the new backend version.
    """
    module = tmp_path / "pkg" / "sample.py"
    _write_module(
        module,
        'def demo():\n    """Return a constant."""\n    return 1\n',
    )

    init_db(tmp_path)
    index_repo(tmp_path)

    monkeypatch.setattr(
        "codira.indexer.get_embedding_backend",
        lambda: EmbeddingBackendSpec(
            name=EMBEDDING_BACKEND,
            version="2",
            dim=EMBEDDING_DIM,
        ),
    )
    report = index_repo(tmp_path)

    conn = sqlite3.connect(get_db_path(tmp_path))
    try:
        versions = conn.execute(
            "SELECT DISTINCT version FROM embeddings ORDER BY version"
        ).fetchall()
    finally:
        conn.close()

    assert report.indexed == 1
    assert report.reused == 0
    assert report.embeddings_recomputed > 0
    assert versions == [("2",)]


def test_index_repo_reindexes_unchanged_files_when_analyzer_changes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Ensure analyzer-version changes invalidate unchanged files explicitly.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary directory provided by pytest.
    monkeypatch : pytest.MonkeyPatch
        Fixture used to replace the active analyzer set.

    Returns
    -------
    None
        The test asserts unchanged files are reparsed when their owning
        analyzer version changes.
    """
    module = tmp_path / "pkg" / "sample.py"
    _write_module(
        module,
        'def demo():\n    """Return a constant."""\n    return 1\n',
    )

    init_db(tmp_path)
    index_repo(tmp_path)

    monkeypatch.setattr(
        "codira.indexer.active_language_analyzers",
        lambda *, root=None: [_PythonAnalyzerV7()],
    )
    report = index_repo(tmp_path)

    conn = sqlite3.connect(get_db_path(tmp_path))
    try:
        owners = conn.execute(
            "SELECT analyzer_name, analyzer_version FROM files"
        ).fetchall()
    finally:
        conn.close()

    assert report.indexed == 1
    assert report.reused == 0
    assert any(
        decision.path == str(module)
        and decision.action == "indexed"
        and decision.reason == "analyzer plugin or version changed"
        for decision in report.decisions
    )
    assert owners == [("python", "7")]


def test_index_cli_reports_summary_and_decisions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """
    Ensure the CLI prints incremental summary lines and explain decisions.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary directory provided by pytest.
    monkeypatch : pytest.MonkeyPatch
        Fixture used to control process state.
    capsys : pytest.CaptureFixture[str]
        Fixture used to capture CLI output.

    Returns
    -------
    None
        The test asserts summary output and per-file explain lines.
    """
    module = tmp_path / "pkg" / "sample.py"
    _write_module(
        module,
        'def demo():\n    """Return a constant."""\n    return 1\n',
    )

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["codira", "index", "--explain"])

    assert main() == 0
    captured = capsys.readouterr()
    assert "Indexed: 1" in captured.out
    assert "Reused: 0" in captured.out
    assert "Deleted: 0" in captured.out
    assert "Failed: 0" in captured.out
    assert "Embeddings recomputed:" in captured.out
    assert "indexed: pkg/sample.py" in captured.out


def test_index_repo_skips_python_files_with_syntax_errors(tmp_path: Path) -> None:
    """
    Continue indexing when one Python file fails under the primary parser.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary directory provided by pytest.

    Returns
    -------
    None
        The test asserts valid files are indexed while syntax-invalid files are
        reported as failures without aborting the run.
    """
    valid_module = tmp_path / "pkg" / "valid.py"
    legacy_module = tmp_path / "pkg" / "legacy.py"
    _write_module(
        valid_module,
        'def demo():\n    """Return a constant."""\n    return 1\n',
    )
    _write_module(legacy_module, 'print "hi"\n')

    init_db(tmp_path)
    report = index_repo(tmp_path)

    assert report.indexed == 1
    assert report.failed == 1
    assert report.reused == 0
    assert report.deleted == 0
    assert report.warnings == []
    assert len(report.failures) == 1
    assert report.failures[0].path == str(legacy_module)
    assert report.failures[0].analyzer_name == "python"
    assert report.failures[0].error_type == "SyntaxError"

    conn = sqlite3.connect(get_db_path(tmp_path))
    try:
        indexed_paths = [
            row[0] for row in conn.execute("SELECT path FROM files ORDER BY path")
        ]
    finally:
        conn.close()

    assert indexed_paths == [str(valid_module)]


def test_index_repo_skips_rebuild_for_new_failed_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Avoid rebuilding graph indexes when only new files fail analysis.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary directory provided by pytest.
    monkeypatch : pytest.MonkeyPatch
        Fixture used to patch backend selection for the indexer.

    Returns
    -------
    None
        The test asserts a syntax-invalid new file is reported without
        rebuilding derived graph indexes when no stored graph rows changed.
    """
    valid_module = tmp_path / "pkg" / "valid.py"
    legacy_module = tmp_path / "pkg" / "legacy.py"
    _write_module(
        valid_module,
        'def demo():\n    """Return a constant."""\n    return 1\n',
    )

    backend = _TrackingSQLiteBackend()
    monkeypatch.setattr(
        indexer_module,
        "active_index_backend",
        lambda *, root=None: backend,
    )
    first = index_repo(tmp_path)
    assert first.indexed == 1
    assert backend.rebuild_derived_indexes_calls == 1

    _write_module(legacy_module, 'print "hi"\n')
    backend.rebuild_derived_indexes_calls = 0
    second = index_repo(tmp_path)

    assert second.indexed == 0
    assert second.failed == 1
    assert second.failures[0].path == str(legacy_module)
    assert backend.rebuild_derived_indexes_calls == 0


def test_index_cli_reports_failures_without_aborting(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """
    Render per-file failures while keeping the CLI exit status successful.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary directory provided by pytest.
    monkeypatch : pytest.MonkeyPatch
        Fixture used to control process state.
    capsys : pytest.CaptureFixture[str]
        Fixture used to capture CLI output.

    Returns
    -------
    None
        The test asserts index failures are reported without aborting indexing.
    """
    valid_module = tmp_path / "pkg" / "valid.py"
    legacy_module = tmp_path / "pkg" / "legacy.py"
    _write_module(
        valid_module,
        'def demo():\n    """Return a constant."""\n    return 1\n',
    )
    _write_module(legacy_module, 'print "hi"\n')

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["codira", "index"])

    assert main() == 0
    captured = capsys.readouterr()
    assert "Indexed: 1" in captured.out
    assert "Failed: 1" in captured.out
    assert "failure: pkg/legacy.py (python, SyntaxError," in captured.out


def test_index_repo_suppresses_python_syntax_warnings(tmp_path: Path) -> None:
    """
    Ignore non-fatal Python syntax warnings during indexing.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary directory provided by pytest.

    Returns
    -------
    None
        The test asserts invalid escape warnings do not clutter index output.
    """
    warned_module = tmp_path / "pkg" / "warned.py"
    _write_module(warned_module, 'value = "\\$"\n')

    init_db(tmp_path)
    report = index_repo(tmp_path)

    assert report.indexed == 1
    assert report.failed == 0
    assert report.warnings == []


def test_index_cli_omits_python_syntax_warnings(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """
    Omit non-fatal Python syntax warnings from CLI output.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary directory provided by pytest.
    monkeypatch : pytest.MonkeyPatch
        Fixture used to control process state.
    capsys : pytest.CaptureFixture[str]
        Fixture used to capture CLI output.

    Returns
    -------
    None
        The test asserts invalid escape warnings are suppressed.
    """
    warned_module = tmp_path / "pkg" / "warned.py"
    _write_module(warned_module, 'value = "\\$"\n')

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["codira", "index"])

    assert main() == 0
    captured = capsys.readouterr()
    assert "<unknown>:" not in captured.out
    assert "warning: pkg/warned.py" not in captured.out


def test_index_repo_indexes_mixed_python_and_c_sources(tmp_path: Path) -> None:
    """
    Ensure the Phase 9 analyzer registry indexes mixed-language repositories.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary directory provided by pytest.

    Returns
    -------
    None
        The test asserts deterministic indexing for Python and C sources.
    """
    python_module = tmp_path / "pkg" / "sample.py"
    c_module = tmp_path / "native" / "sample.c"
    _write_module(
        python_module,
        'def py_helper():\n    """Return a constant."""\n    return 1\n',
    )
    _write_module(
        c_module,
        '#include "native/sample.h"\n'
        "\n"
        "int c_helper(int value) {\n"
        "    return value;\n"
        "}\n",
    )

    init_db(tmp_path)
    report = index_repo(tmp_path)

    assert report.indexed == 2
    assert report.reused == 0
    assert report.deleted == 0
    assert find_symbol(tmp_path, "py_helper") == [
        ("function", "pkg.sample", "py_helper", str(python_module), 1)
    ]
    assert find_symbol(tmp_path, "c_helper") == [
        ("function", "native.sample", "c_helper", str(c_module), 3)
    ]
    assert report.coverage_issues == []


def test_index_repo_reports_uncovered_canonical_files(tmp_path: Path) -> None:
    """
    Audit canonical directories for files not covered by active analyzers.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary directory provided by pytest.

    Returns
    -------
    None
        The test asserts uncovered canonical files are surfaced in the index
        report without blocking covered-file indexing.
    """
    python_module = tmp_path / "src" / "sample.py"
    rust_module = tmp_path / "src" / "lib.rs"
    _write_module(
        python_module,
        'def py_helper():\n    """Return a constant."""\n    return 1\n',
    )
    rust_module.parent.mkdir(parents=True, exist_ok=True)
    rust_module.write_text("pub fn helper() {}\n", encoding="utf-8")

    init_db(tmp_path)
    report = index_repo(tmp_path)

    assert report.indexed == 1
    assert report.coverage_issues == [
        type(report.coverage_issues[0])(
            path=str(rust_module),
            directory="src",
            suffix=".rs",
            reason="no registered analyzer accepts this file type/content combination",
        )
    ]


def test_index_repo_covers_json_schema_documents_in_canonical_directories(
    tmp_path: Path,
) -> None:
    """
    Treat recognized JSON Schema documents as covered canonical sources.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary directory provided by pytest.

    Returns
    -------
    None
        The test asserts supported JSON Schema files index cleanly.
    """
    schema_file = tmp_path / "src" / "codira" / "schema" / "context.schema.json"
    schema_file.parent.mkdir(parents=True, exist_ok=True)
    schema_file.write_text(
        json.dumps(
            {
                "$schema": "http://json-schema.org/draft-07/schema#",
                "title": "demo schema",
                "type": "object",
            }
        ),
        encoding="utf-8",
    )

    init_db(tmp_path)
    report = index_repo(tmp_path)

    assert report.coverage_issues == []
    assert report.indexed == 1
    assert find_symbol(tmp_path, "src.codira.schema.context_schema") == [
        (
            "module",
            "src.codira.schema.context_schema",
            "src.codira.schema.context_schema",
            str(schema_file),
            1,
        )
    ]


def test_index_repo_indexes_package_and_release_json_families(tmp_path: Path) -> None:
    """
    Index supported non-schema JSON families through the main indexing path.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary directory provided by pytest.

    Returns
    -------
    None
        The test asserts manifest and release-config declarations become queryable.
    """
    package_file = tmp_path / "package.json"
    release_file = tmp_path / ".releaserc.json"
    package_file.write_text(
        json.dumps(
            {
                "name": "codira-release",
                "devDependencies": {"semantic-release": "^23.0.0"},
            }
        ),
        encoding="utf-8",
    )
    release_file.write_text(
        json.dumps(
            {
                "branches": ["main"],
                "plugins": ["@semantic-release/commit-analyzer"],
            }
        ),
        encoding="utf-8",
    )

    init_db(tmp_path)
    report = index_repo(tmp_path)

    assert report.coverage_issues == []
    assert report.indexed == 2
    assert find_symbol(tmp_path, "codira-release") == [
        (
            "json_manifest_name",
            "package",
            "codira-release",
            str(package_file),
            1,
        )
    ]
    assert find_symbol(tmp_path, "@semantic-release/commit-analyzer") == [
        (
            "json_release_plugin",
            "releaserc",
            "@semantic-release/commit-analyzer",
            str(release_file),
            1,
        )
    ]


def test_index_cli_prints_coverage_issues(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Render canonical-directory coverage gaps in CLI index output.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary directory provided by pytest.
    capsys : pytest.CaptureFixture[str]
        Fixture used to capture CLI output.
    monkeypatch : pytest.MonkeyPatch
        Fixture used to patch argv and cwd.

    Returns
    -------
    None
        The test asserts uncovered canonical files are printed in the summary.
    """
    python_module = tmp_path / "src" / "sample.py"
    config_file = tmp_path / "scripts" / "build.json"
    _write_module(
        python_module,
        'def demo():\n    """Return a constant."""\n    return 1\n',
    )
    config_file.parent.mkdir(parents=True, exist_ok=True)
    config_file.write_text('{"task": "demo"}\n', encoding="utf-8")

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["codira", "index"])

    assert main() == 0
    captured = capsys.readouterr()
    assert "Coverage issues: 1" in captured.out
    assert (
        "coverage: .json x1 in scripts "
        "(.json, "
        "no registered analyzer accepts this file type/content combination)"
    ) in captured.out


def test_coverage_cli_reports_uncovered_canonical_files(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Render canonical coverage gaps without building the index.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary directory provided by pytest.
    capsys : pytest.CaptureFixture[str]
        Fixture used to capture CLI output.
    monkeypatch : pytest.MonkeyPatch
        Fixture used to patch argv and cwd.

    Returns
    -------
    None
        The test asserts the dedicated coverage command reports uncovered
        canonical files and exits non-zero for incomplete coverage.
    """
    python_module = tmp_path / "src" / "sample.py"
    config_file = tmp_path / "scripts" / "build.json"
    _write_module(
        python_module,
        'def demo():\n    """Return a constant."""\n    return 1\n',
    )
    config_file.parent.mkdir(parents=True, exist_ok=True)
    config_file.write_text('{"task": "demo"}\n', encoding="utf-8")

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["codira", "cov"])

    assert main() == 1
    captured = capsys.readouterr()
    assert "Coverage complete: no" in captured.out
    assert "Active analyzers:" in captured.out
    assert (
        "coverage: .json x1 in scripts "
        "(.json, "
        "no registered analyzer accepts this file type/content combination)"
    ) in captured.out
    assert not get_db_path(tmp_path).exists()


def test_coverage_cli_groups_text_output_by_suffix_and_directory(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Group human-readable coverage diagnostics by suffix and top-level directory.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary directory provided by pytest.
    capsys : pytest.CaptureFixture[str]
        Fixture used to capture CLI output.
    monkeypatch : pytest.MonkeyPatch
        Fixture used to patch argv and cwd.

    Returns
    -------
    None
        The test asserts text coverage output summarizes repeated suffixes
        across canonical directories.
    """
    src_json = tmp_path / "src" / "schema.json"
    tests_json = tmp_path / "tests" / "fixtures" / "sample.json"
    src_json.parent.mkdir(parents=True, exist_ok=True)
    tests_json.parent.mkdir(parents=True, exist_ok=True)
    src_json.write_text('{"name": "demo"}\n', encoding="utf-8")
    tests_json.write_text('{"name": "fixture"}\n', encoding="utf-8")

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["codira", "cov"])

    assert main() == 1
    captured = capsys.readouterr()
    assert "Coverage issues: 1" in captured.out
    assert (
        "coverage: .json x1 in "
        "src (.json, no registered analyzer accepts this file type/content combination)"
    ) in captured.out


def test_audit_repo_coverage_ignores_suppressed_suffixes(tmp_path: Path) -> None:
    """
    Exclude configured non-source suffixes from canonical coverage gaps.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary directory provided by pytest.

    Returns
    -------
    None
        The test asserts ignored suffix classes do not produce diagnostics.
    """
    markdown_file = tmp_path / "src" / "notes.md"
    text_file = tmp_path / "tests" / "fixture.txt"
    typed_file = tmp_path / "src" / "pkg" / "py.typed"
    suffixless_file = tmp_path / "scripts" / "runner"
    markdown_file.parent.mkdir(parents=True, exist_ok=True)
    text_file.parent.mkdir(parents=True, exist_ok=True)
    typed_file.parent.mkdir(parents=True, exist_ok=True)
    suffixless_file.parent.mkdir(parents=True, exist_ok=True)
    markdown_file.write_text("# Notes\n", encoding="utf-8")
    text_file.write_text("fixture\n", encoding="utf-8")
    typed_file.write_text("", encoding="utf-8")
    suffixless_file.write_text("echo demo\n", encoding="utf-8")

    assert audit_repo_coverage(tmp_path) == []


def test_audit_repo_coverage_ignores_binary_files(tmp_path: Path) -> None:
    """
    Exclude obvious binary files from canonical coverage gaps.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary directory provided by pytest.

    Returns
    -------
    None
        The test asserts files containing NUL bytes are ignored.
    """
    binary_file = tmp_path / "tests" / "fixture.rdb"
    binary_file.parent.mkdir(parents=True, exist_ok=True)
    binary_file.write_bytes(b"REDIS\x00DATA")

    assert audit_repo_coverage(tmp_path) == []


def test_coverage_cli_emits_json(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Emit structured JSON for canonical coverage diagnostics.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary directory provided by pytest.
    capsys : pytest.CaptureFixture[str]
        Fixture used to capture CLI output.
    monkeypatch : pytest.MonkeyPatch
        Fixture used to patch argv and cwd.

    Returns
    -------
    None
        The test asserts the JSON coverage envelope includes analyzer and issue
        metadata without making coverage findings a command failure.
    """
    rust_module = tmp_path / "src" / "lib.rs"
    rust_module.parent.mkdir(parents=True, exist_ok=True)
    rust_module.write_text("pub fn helper() {}\n", encoding="utf-8")

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["codira", "cov", "--json"])

    assert main() == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["command"] == "cov"
    assert payload["status"] == "incomplete"
    assert payload["query"]["canonical_directories"] == ["src", "tests", "scripts"]
    assert payload["results"] == [
        {
            "path": str(rust_module),
            "directory": "src",
            "suffix": ".rs",
            "reason": "no registered analyzer accepts this file type/content combination",
        }
    ]
    assert payload["analyzers"]


def test_index_cli_can_require_full_coverage(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Fail before indexing when strict canonical coverage is required.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary directory provided by pytest.
    capsys : pytest.CaptureFixture[str]
        Fixture used to capture CLI output.
    monkeypatch : pytest.MonkeyPatch
        Fixture used to patch argv and cwd.

    Returns
    -------
    None
        The test asserts strict coverage mode exits before creating the index.
    """
    python_module = tmp_path / "src" / "sample.py"
    rust_module = tmp_path / "src" / "lib.rs"
    _write_module(
        python_module,
        'def demo():\n    """Return a constant."""\n    return 1\n',
    )
    rust_module.parent.mkdir(parents=True, exist_ok=True)
    rust_module.write_text("pub fn helper() {}\n", encoding="utf-8")

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        sys,
        "argv",
        ["codira", "index", "--require-full-coverage"],
    )

    assert main() == 2
    captured = capsys.readouterr()
    assert "Coverage incomplete" in captured.err
    assert "Coverage issues: 1" in captured.out
    assert not get_db_path(tmp_path).exists()


def test_index_cli_emits_json(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Emit structured JSON for one successful index run.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary directory provided by pytest.
    capsys : pytest.CaptureFixture[str]
        Fixture used to capture CLI output.
    monkeypatch : pytest.MonkeyPatch
        Fixture used to patch argv and cwd.

    Returns
    -------
    None
        The test asserts the JSON payload includes the index summary,
        canonical coverage issues, and per-file decisions when explain mode is
        enabled.
    """
    python_module = tmp_path / "src" / "sample.py"
    config_file = tmp_path / "scripts" / "build.json"
    _write_module(
        python_module,
        'def demo():\n    """Return a constant."""\n    return 1\n',
    )
    config_file.parent.mkdir(parents=True, exist_ok=True)
    config_file.write_text('{"task": "demo"}\n', encoding="utf-8")

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["codira", "index", "--json", "--explain"])

    assert main() == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["command"] == "index"
    assert payload["status"] == "ok"
    assert payload["query"] == {
        "full": False,
        "explain": True,
        "require_full_coverage": False,
        "defer_embeddings": False,
        "embeddings_only": False,
    }
    assert payload["results"] == []
    assert payload["summary"] == {
        "indexed": 1,
        "reused": 0,
        "deleted": 0,
        "failed": 0,
        "embeddings_recomputed": 2,
        "embeddings_reused": 0,
        "embeddings_skipped": 0,
        "embeddings_pending": 0,
        "embedding_index_mode": "immediate",
        "embedding_complete": True,
    }
    assert payload["coverage_issues"] == [
        {
            "path": str(config_file),
            "directory": "scripts",
            "suffix": ".json",
            "reason": "no registered analyzer accepts this file type/content combination",
        }
    ]
    assert payload["warnings"] == []
    assert payload["failures"] == []
    assert payload["decisions"] == [
        {
            "path": str(python_module),
            "action": "indexed",
            "reason": "new file",
        }
    ]


def test_index_cli_emits_json_for_required_coverage_failure(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Emit structured JSON when strict canonical coverage blocks indexing.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary directory provided by pytest.
    capsys : pytest.CaptureFixture[str]
        Fixture used to capture CLI output.
    monkeypatch : pytest.MonkeyPatch
        Fixture used to patch argv and cwd.

    Returns
    -------
    None
        The test asserts strict coverage mode returns JSON without creating the
        index when uncovered canonical files are present.
    """
    rust_module = tmp_path / "src" / "lib.rs"
    rust_module.parent.mkdir(parents=True, exist_ok=True)
    rust_module.write_text("pub fn helper() {}\n", encoding="utf-8")

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        sys,
        "argv",
        ["codira", "index", "--json", "--require-full-coverage"],
    )

    assert main() == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["command"] == "index"
    assert payload["status"] == "coverage_incomplete"
    assert payload["query"] == {
        "full": False,
        "explain": False,
        "require_full_coverage": True,
        "defer_embeddings": False,
        "embeddings_only": False,
    }
    assert payload["summary"] == {
        "indexed": 0,
        "reused": 0,
        "deleted": 0,
        "failed": 0,
        "embeddings_recomputed": 0,
        "embeddings_reused": 0,
        "embeddings_skipped": 0,
        "embeddings_pending": 0,
        "embedding_index_mode": "unknown",
        "embedding_complete": False,
    }
    assert payload["coverage_issues"] == [
        {
            "path": str(rust_module),
            "directory": "src",
            "suffix": ".rs",
            "reason": "no registered analyzer accepts this file type/content combination",
        }
    ]
    assert payload["warnings"] == []
    assert payload["failures"] == []
    assert payload["decisions"] == []
    assert not get_db_path(tmp_path).exists()


def test_index_cli_defers_and_processes_pending_embeddings(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Defer embedding work and process it in a later embeddings-only pass.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary directory provided by pytest.
    capsys : pytest.CaptureFixture[str]
        Fixture used to capture CLI output.
    monkeypatch : pytest.MonkeyPatch
        Fixture used to patch argv and cwd.

    Returns
    -------
    None
        The test asserts structural indexing succeeds first and pending
        embeddings are materialized by the follow-up command.
    """

    module = tmp_path / "src" / "sample.py"
    _write_module(
        module,
        'def demo():\n    """Return a constant."""\n    return 1\n',
    )

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        sys,
        "argv",
        ["codira", "index", "--json", "--full", "--defer-embeddings"],
    )

    assert main() == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "ok"
    assert payload["summary"]["indexed"] == 1
    assert payload["summary"]["embeddings_recomputed"] == 0
    assert payload["summary"]["embeddings_reused"] == 0
    assert payload["summary"]["embeddings_pending"] == 2
    assert payload["summary"]["embedding_index_mode"] == "deferred"
    assert payload["summary"]["embedding_complete"] is False

    conn = sqlite3.connect(get_db_path(tmp_path))
    pending_count = conn.execute("SELECT COUNT(*) FROM pending_embeddings").fetchone()
    embedding_count = conn.execute("SELECT COUNT(*) FROM embeddings").fetchone()
    conn.close()
    assert pending_count == (2,)
    assert embedding_count == (0,)
    vector_db_path = tmp_path / ".codira" / "embeddings.db"
    assert vector_db_path.exists()
    vector_conn = sqlite3.connect(vector_db_path)
    vector_pending_count = vector_conn.execute(
        "SELECT COUNT(*) FROM pending_vectors"
    ).fetchone()
    vector_conn.close()
    assert vector_pending_count == (2,)

    monkeypatch.setattr(
        sys,
        "argv",
        ["codira", "index", "--json", "--embeddings-only"],
    )

    assert main() == 0
    drain_payload = json.loads(capsys.readouterr().out)
    assert drain_payload["status"] == "ok"
    assert drain_payload["summary"]["indexed"] == 0
    assert drain_payload["summary"]["embeddings_recomputed"] == 2
    assert drain_payload["summary"]["embeddings_reused"] == 0
    assert drain_payload["summary"]["embeddings_pending"] == 0
    assert drain_payload["summary"]["embedding_complete"] is True
    vector_conn = sqlite3.connect(vector_db_path)
    vector_pending_count = vector_conn.execute(
        "SELECT COUNT(*) FROM pending_vectors"
    ).fetchone()
    vector_count = vector_conn.execute("SELECT COUNT(*) FROM vectors").fetchone()
    vector_conn.close()
    assert vector_pending_count == (0,)
    assert vector_count == (2,)


def test_index_repo_stores_immediate_vectors_in_vector_store(tmp_path: Path) -> None:
    """
    Store immediate embedding rows in the separated vector store.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary directory provided by pytest.

    Returns
    -------
    None
        The test asserts immediate indexing materializes separated vectors.
    """
    module = tmp_path / "src" / "sample.py"
    _write_module(
        module,
        'def demo():\n    """Return a constant."""\n    return 1\n',
    )

    report = index_repo(tmp_path)

    vector_db_path = tmp_path / ".codira" / "embeddings.db"
    vector_conn = sqlite3.connect(vector_db_path)
    try:
        vector_count = vector_conn.execute("SELECT COUNT(*) FROM vectors").fetchone()
        cache_count = vector_conn.execute(
            "SELECT COUNT(*) FROM vector_cache"
        ).fetchone()
        pending_count = vector_conn.execute(
            "SELECT COUNT(*) FROM pending_vectors"
        ).fetchone()
    finally:
        vector_conn.close()

    assert report.embeddings_recomputed == 2
    assert vector_count == (2,)
    assert cache_count == (2,)
    assert pending_count == (0,)


def test_index_cli_embedding_mode_flags_do_not_override_disabled_embeddings(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Keep embedding mode flags blocked when embeddings are disabled.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary directory provided by pytest.
    capsys : pytest.CaptureFixture[str]
        Fixture used to capture CLI output.
    monkeypatch : pytest.MonkeyPatch
        Fixture used to patch argv and cwd.

    Returns
    -------
    None
        The test asserts ``embeddings.enabled = false`` is a hard gate for
        explicit embedding execution flags.
    """

    config_path = tmp_path / ".codira" / "config.toml"
    config_path.parent.mkdir(parents=True)
    config_path.write_text("[embeddings]\nenabled = false\n", encoding="utf-8")

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        sys,
        "argv",
        ["codira", "index", "--json", "--embeddings-only"],
    )

    assert main() == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "embeddings_disabled"
    assert payload["query"] == {
        "full": False,
        "explain": False,
        "require_full_coverage": False,
        "defer_embeddings": False,
        "embeddings_only": True,
    }


def test_index_cli_reports_embedding_rows_skipped_by_volume_controls(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Report embedding candidates skipped by configured object-type controls.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary directory provided by pytest.
    capsys : pytest.CaptureFixture[str]
        Fixture used to capture CLI output.
    monkeypatch : pytest.MonkeyPatch
        Fixture used to patch argv and cwd.

    Returns
    -------
    None
        The test asserts structural indexing still succeeds while embedding
        rows are filtered out by ``embeddings.indexing.object_types``.
    """

    module = tmp_path / "src" / "sample.py"
    _write_module(
        module,
        'def demo():\n    """Return a constant."""\n    return 1\n',
    )
    config_path = tmp_path / ".codira" / "config.toml"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(
        "[embeddings.indexing]\nobject_types = []\n",
        encoding="utf-8",
    )

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["codira", "index", "--json", "--full"])

    assert main() == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "ok"
    assert payload["summary"]["indexed"] == 1
    assert payload["summary"]["embeddings_recomputed"] == 0
    assert payload["summary"]["embeddings_reused"] == 0
    assert payload["summary"]["embeddings_skipped"] == 2
    assert payload["summary"]["embeddings_pending"] == 0
    assert payload["summary"]["embedding_index_mode"] == "immediate"
    assert payload["summary"]["embedding_complete"] is True


def test_index_cli_uses_repo_configured_duckdb_backend(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Select DuckDB from repo-local config when running the index CLI.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository root.
    capsys : pytest.CaptureFixture[str]
        Fixture used to capture CLI output.
    monkeypatch : pytest.MonkeyPatch
        Fixture used to patch argv and cwd.

    Returns
    -------
    None
        The test asserts repo-local backend config creates a DuckDB database
        artifact instead of falling back to SQLite.
    """
    pytest.importorskip("duckdb")
    from codira_backend_duckdb import _duckdb_db_path

    module = tmp_path / "src" / "sample.py"
    _write_module(module, "def demo() -> int:\n    return 1\n")
    config_path = tmp_path / ".codira" / "config.toml"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(
        '[backend]\nname = "duckdb"\n\n[embeddings]\nenabled = false\n',
        encoding="utf-8",
    )

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["codira", "index", "--json", "--full"])

    assert main() == 0
    payload = json.loads(capsys.readouterr().out)

    assert payload["status"] == "ok"
    assert payload["summary"]["indexed"] == 1
    assert _duckdb_db_path(tmp_path).exists()
    assert not get_db_path(tmp_path).exists()
    assert _read_index_metadata(tmp_path)["backend_name"] == "duckdb"


def test_index_cli_supports_target_and_output_directory_overrides(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Build and query an index with separate target and output directories.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary directory provided by pytest.
    capsys : pytest.CaptureFixture[str]
        Fixture used to capture CLI output.
    monkeypatch : pytest.MonkeyPatch
        Fixture used to patch argv and cwd.

    Returns
    -------
    None
        The test asserts reads come from the target tree while ``.codira``
        state is written under the separate output root.
    """
    target = tmp_path / "readonly-target"
    output = tmp_path / "cli-output"
    module = target / "src" / "sample.py"
    _write_module(
        module,
        'def demo():\n    """Return a constant."""\n    return 1\n',
    )

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "codira",
            "index",
            "--path",
            str(target),
            "--output-dir",
            str(output),
            "--json",
        ],
    )

    assert main() == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "ok"
    assert get_db_path(output).exists()
    assert not get_db_path(target).exists()

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "codira",
            "sym",
            "demo",
            "--path",
            str(target),
            "--output-dir",
            str(output),
            "--json",
        ],
    )

    assert main() == 0
    query_payload = json.loads(capsys.readouterr().out)
    assert query_payload["results"] == [
        {
            "type": "function",
            "module": "sample",
            "name": "demo",
            "file": str(module),
            "lineno": 1,
        }
    ]


def test_index_cli_uses_environment_target_and_output_directories(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Resolve target and output directories from environment variables.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary directory provided by pytest.
    capsys : pytest.CaptureFixture[str]
        Fixture used to capture CLI output.
    monkeypatch : pytest.MonkeyPatch
        Fixture used to patch argv, cwd, and environment variables.

    Returns
    -------
    None
        The test asserts environment-driven path resolution uses the selected
        target and output roots.
    """
    target = tmp_path / "env-target"
    output = tmp_path / "env-output"
    module = target / "src" / "env_sample.py"
    _write_module(
        module,
        'def env_demo():\n    """Return a constant."""\n    return 1\n',
    )

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("CODIRA_TARGET_DIR", str(target))
    monkeypatch.setenv("CODIRA_OUTPUT_DIR", str(output))
    monkeypatch.setattr(sys, "argv", ["codira", "index", "--json"])

    assert main() == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "ok"
    assert get_db_path(output).exists()
    assert not get_db_path(target).exists()


def test_index_cli_flags_override_environment_target_and_output_directories(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Prefer CLI target/output overrides over environment variables.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary directory provided by pytest.
    capsys : pytest.CaptureFixture[str]
        Fixture used to capture CLI output.
    monkeypatch : pytest.MonkeyPatch
        Fixture used to patch argv, cwd, and environment variables.

    Returns
    -------
    None
        The test asserts CLI flags win over environment-provided roots.
    """
    env_target = tmp_path / "env-target"
    env_output = tmp_path / "env-output"
    cli_target = tmp_path / "cli-target"
    cli_output = tmp_path / "cli-output"
    _write_module(
        env_target / "src" / "env_module.py",
        'def env_symbol():\n    """Return a constant."""\n    return 1\n',
    )
    cli_module = cli_target / "src" / "cli_module.py"
    _write_module(
        cli_module,
        'def cli_symbol():\n    """Return a constant."""\n    return 1\n',
    )

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("CODIRA_TARGET_DIR", str(env_target))
    monkeypatch.setenv("CODIRA_OUTPUT_DIR", str(env_output))
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "codira",
            "index",
            "--path",
            str(cli_target),
            "--output-dir",
            str(cli_output),
            "--json",
        ],
    )

    assert main() == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "ok"
    assert get_db_path(cli_output).exists()
    assert not get_db_path(env_output).exists()
    assert not get_db_path(cli_target).exists()

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "codira",
            "sym",
            "cli_symbol",
            "--path",
            str(cli_target),
            "--output-dir",
            str(cli_output),
            "--json",
        ],
    )

    assert main() == 0
    query_payload = json.loads(capsys.readouterr().out)
    assert query_payload["results"][0]["file"] == str(cli_module)


def test_index_cli_supports_read_only_target_with_separate_output_directory(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Index a read-only target tree when ``.codira`` is redirected elsewhere.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary directory provided by pytest.
    capsys : pytest.CaptureFixture[str]
        Fixture used to capture CLI output.
    monkeypatch : pytest.MonkeyPatch
        Fixture used to patch argv and cwd.

    Returns
    -------
    None
        The test asserts indexing succeeds without writing into the target
        tree.
    """
    if os.name == "nt":
        pytest.skip("POSIX permission semantics are required for this test")

    target = tmp_path / "readonly-target"
    output = tmp_path / "writable-output"
    module = target / "src" / "sample.py"
    src_dir = module.parent
    _write_module(
        module,
        'def readonly_demo():\n    """Return a constant."""\n    return 1\n',
    )
    target.chmod(0o555)
    src_dir.chmod(0o555)
    module.chmod(0o444)
    try:
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(
            sys,
            "argv",
            [
                "codira",
                "index",
                "--path",
                str(target),
                "--output-dir",
                str(output),
                "--json",
            ],
        )

        assert main() == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["status"] == "ok"
        assert get_db_path(output).exists()
        assert not get_db_path(target).exists()
        assert (output / ".codira" / "embeddings.db").exists()
        assert not (target / ".codira" / "embeddings.db").exists()
    finally:
        module.chmod(0o644)
        src_dir.chmod(0o755)
        target.chmod(0o755)


def test_ensure_index_rebuilds_when_analyzer_inventory_changes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """
    Rebuild automatically when the persisted analyzer inventory is stale.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary directory provided by pytest.
    monkeypatch : pytest.MonkeyPatch
        Fixture used to patch active analyzers and Git state.
    capsys : pytest.CaptureFixture[str]
        Fixture used to capture rebuild diagnostics.

    Returns
    -------
    None
        The test asserts plugin-aware analyzer staleness triggers a rebuild.
    """
    module = tmp_path / "pkg" / "sample.py"
    _write_module(
        module,
        'def demo():\n    """Return a constant."""\n    return 1\n',
    )

    init_db(tmp_path)
    index_repo(tmp_path)
    _write_index_metadata(tmp_path, {"schema_version": str(SCHEMA_VERSION)})

    monkeypatch.setattr("codira.cli._get_head_commit", lambda root: None)
    monkeypatch.setattr(
        "codira.cli.active_language_analyzers",
        lambda *, root=None: [_PythonAnalyzerV7()],
    )
    monkeypatch.setattr(
        "codira.indexer.active_language_analyzers",
        lambda *, root=None: [_PythonAnalyzerV7()],
    )

    _ensure_index(tmp_path)
    captured = capsys.readouterr()
    backend = SQLiteIndexBackend()

    assert "Index stale (analyzer plugin inventory changed)" in captured.err
    assert backend.load_analyzer_inventory(tmp_path) == [
        _analyzer_inventory_row(_PythonAnalyzerV7())
    ]


def test_ensure_index_rebuilds_when_backend_inventory_changes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """
    Rebuild automatically when the persisted backend inventory is stale.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary directory provided by pytest.
    monkeypatch : pytest.MonkeyPatch
        Fixture used to patch the active backend and Git state.
    capsys : pytest.CaptureFixture[str]
        Fixture used to capture rebuild diagnostics.

    Returns
    -------
    None
        The test asserts plugin-aware backend staleness triggers a rebuild.
    """
    module = tmp_path / "pkg" / "sample.py"
    _write_module(
        module,
        'def demo():\n    """Return a constant."""\n    return 1\n',
    )

    init_db(tmp_path)
    index_repo(tmp_path)
    _write_index_metadata(tmp_path, {"schema_version": str(SCHEMA_VERSION)})

    monkeypatch.setattr("codira.cli._get_head_commit", lambda root: None)
    monkeypatch.setattr(
        "codira.cli.active_index_backend",
        lambda *, root=None: _SQLiteBackendVNext(),
    )
    monkeypatch.setattr(
        "codira.indexer.active_index_backend",
        lambda *, root=None: _SQLiteBackendVNext(),
    )

    _ensure_index(tmp_path)
    captured = capsys.readouterr()
    backend = SQLiteIndexBackend()

    assert "Index stale (backend plugin changed)" in captured.err
    assert backend.load_runtime_inventory(tmp_path) == (
        "sqlite",
        str(SCHEMA_VERSION + 1),
        1,
    )


def test_init_db_preserves_existing_commit_metadata(tmp_path: Path) -> None:
    """
    Preserve the indexed commit when refreshing the schema in place.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary directory provided by pytest.

    Returns
    -------
    None
        The test asserts ``init_db`` keeps existing freshness metadata.
    """
    init_db(tmp_path)
    _write_index_metadata(
        tmp_path,
        {
            "commit": "abc123",
            "schema_version": str(SCHEMA_VERSION),
        },
    )

    init_db(tmp_path)

    assert _read_index_metadata(tmp_path) == {
        "commit": "abc123",
        "schema_version": str(SCHEMA_VERSION),
    }


def test_ensure_index_missing_db_writes_schema_and_commit_metadata(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Persist complete freshness metadata after auto-building a missing index.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary directory provided by pytest.
    monkeypatch : pytest.MonkeyPatch
        Fixture used to patch the Git commit probe.

    Returns
    -------
    None
        The test asserts missing-index bootstrap stores both schema and
        commit metadata.
    """
    module = tmp_path / "pkg" / "sample.py"
    _write_module(
        module,
        'def demo():\n    """Return a constant."""\n    return 1\n',
    )
    monkeypatch.setattr(
        "codira.cli._get_head_commit",
        lambda root: "abc123",
    )

    _ensure_index(tmp_path)

    assert _read_index_metadata(tmp_path) == {
        "analyzer_inventory": _default_analyzer_inventory_json(),
        "backend_name": "sqlite",
        "backend_version": str(SCHEMA_VERSION),
        "commit": "abc123",
        "indexed_file_count": "1",
        "schema_version": str(SCHEMA_VERSION),
    }


def test_open_connection_does_not_clear_commit_metadata(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Avoid clearing freshness metadata during ordinary query connections.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary directory provided by pytest.
    monkeypatch : pytest.MonkeyPatch
        Fixture used to patch the Git commit probe.

    Returns
    -------
    None
        The test asserts repeated query opens leave the indexed commit intact.
    """
    module = tmp_path / "pkg" / "sample.py"
    _write_module(
        module,
        'def demo():\n    """Return a constant."""\n    return 1\n',
    )
    monkeypatch.setattr(
        "codira.cli._get_head_commit",
        lambda root: "abc123",
    )

    _ensure_index(tmp_path)

    first = SQLiteIndexBackend().open_connection(tmp_path)
    first.close()
    second = SQLiteIndexBackend().open_connection(tmp_path)
    second.close()

    assert _read_index_metadata(tmp_path) == {
        "analyzer_inventory": _default_analyzer_inventory_json(),
        "backend_name": "sqlite",
        "backend_version": str(SCHEMA_VERSION),
        "commit": "abc123",
        "indexed_file_count": "1",
        "schema_version": str(SCHEMA_VERSION),
    }


def test_ensure_index_rechecks_after_waiting_for_lock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Skip a duplicate rebuild when another process refreshed the index first.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary directory provided by pytest.
    monkeypatch : pytest.MonkeyPatch
        Fixture used to stub the lock and rebuild inspection flow.

    Returns
    -------
    None
        The test asserts the locked recheck suppresses a redundant rebuild.
    """
    request = IndexRebuildRequest(
        message="[codira] Index stale — rebuilding...",
        reset_db=True,
        stderr=True,
    )
    inspections = iter([request, None])

    @contextlib.contextmanager
    def _dummy_lock(root: Path) -> Iterator[None]:
        del root
        yield

    monkeypatch.setattr("codira.cli.acquire_index_lock", _dummy_lock)
    monkeypatch.setattr(
        "codira.cli._inspect_index_rebuild_request",
        lambda root: next(inspections),
    )

    def _unexpected_refresh(root: Path, current: IndexRebuildRequest) -> None:
        del root, current
        msg = "duplicate rebuild should have been skipped"
        raise AssertionError(msg)

    monkeypatch.setattr(
        "codira.cli._run_locked_index_refresh",
        _unexpected_refresh,
    )

    _ensure_index(tmp_path)


def test_acquire_index_lock_blocks_other_processes(tmp_path: Path) -> None:
    """
    Serialize cross-process index mutations through the advisory lock file.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary directory provided by pytest.

    Returns
    -------
    None
        The test asserts another process cannot acquire the lock early.
    """
    if os.name == "nt":
        pytest.skip("fcntl.flock is unavailable on Windows")

    acquired_marker = tmp_path / "acquired.txt"
    release_marker = tmp_path / "release.txt"
    source_root = Path(__file__).resolve().parents[1] / "src"
    child_source = (
        "import sys\n"
        "import time\n"
        "from pathlib import Path\n"
        f"sys.path.insert(0, {str(source_root)!r})\n"
        "from codira.storage import acquire_index_lock\n"
        f"root = Path({str(tmp_path)!r})\n"
        f"acquired = Path({str(acquired_marker)!r})\n"
        f"release = Path({str(release_marker)!r})\n"
        "with acquire_index_lock(root):\n"
        "    acquired.write_text('locked\\n', encoding='utf-8')\n"
        "    while not release.exists():\n"
        "        time.sleep(0.05)\n"
    )

    with acquire_index_lock(tmp_path):
        proc = subprocess.Popen(
            [sys.executable, "-c", child_source],
            cwd=tmp_path,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            time.sleep(0.3)
            assert not acquired_marker.exists()
        finally:
            release_marker.write_text("release\n", encoding="utf-8")

    stdout, stderr = proc.communicate(timeout=5)
    assert proc.returncode == 0, (stdout, stderr)
    assert acquired_marker.exists()


def test_lock_file_handle_uses_windows_locking_api(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Route advisory locking through ``msvcrt`` on Windows.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary directory provided by pytest.
    monkeypatch : pytest.MonkeyPatch
        Fixture used to simulate the Windows-specific module surface.

    Returns
    -------
    None
        The test asserts the Windows lock and unlock calls cover the first byte
        of the lock file without requiring a Windows host.
    """

    calls: list[tuple[int, int]] = []
    fake_msvcrt = types.SimpleNamespace(
        LK_LOCK=1,
        LK_UNLCK=2,
        locking=lambda _fd, mode, size: calls.append((mode, size)),
    )
    monkeypatch.setattr(os, "name", "nt")
    monkeypatch.setitem(sys.modules, "msvcrt", fake_msvcrt)

    lock_path = tmp_path / "index.lock"
    with lock_path.open("w+", encoding="utf-8") as handle:
        handle.write("0")
        handle.flush()
        storage_module._lock_file_handle(handle)
        storage_module._unlock_file_handle(handle)

    assert calls == [(1, 1), (2, 1)]
