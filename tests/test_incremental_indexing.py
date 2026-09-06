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
from codira_analyzer_python import PythonAnalyzer
from codira_backend_sqlite import SQLiteIndexBackend
from codira_backend_sqlite.schema import SCHEMA_VERSION
from codira_backend_sqlite.sqlite_storage import get_db_path, init_db
from incremental_indexing_backends import (
    _PythonAnalyzerV12,
    _SQLiteBackendVNext,
    _TrackingSQLiteBackend,
)

import codira.indexer as indexer_module
import codira.registry as registry_module
import codira.storage as storage_module
from codira.cli import (
    IndexCommandRequest,
    IndexRebuildRequest,
    _ensure_index,
    _read_index_metadata,
    _render_coverage_issues,
    _write_index_metadata,
    main,
)
from codira.contracts import (
    BackendPersistAnalysisRequest,
    BackendResolveDocumentationScoresRequest,
    BackendResolveEmbeddingScoresRequest,
    BackendRuntimeInventoryRequest,
    LanguageAnalyzer,
    SimilarityCandidate,
    StoredEmbeddingRow,
)
from codira.index_generation import IndexGenerationStore
from codira.indexer import CoverageIssue, audit_repo_coverage, index_repo
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
from codira.semantic.embeddings import (
    EMBEDDING_BACKEND,
    EMBEDDING_DIM,
    EmbeddingBackendSpec,
)
from codira.storage import acquire_index_lock

if TYPE_CHECKING:
    from codira.types import DocumentationRow, SymbolRow


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


def _insert_score_resolution_fixture(
    root: Path,
    *,
    count: int,
) -> None:
    """
    Insert symbol and documentation rows for score-resolution tests.

    Parameters
    ----------
    root : pathlib.Path
        Repository root containing an initialized SQLite backend database.
    count : int
        Number of symbol and documentation stable IDs to create.

    Returns
    -------
    None
        The fixture rows are committed to the backend database.
    """

    conn = sqlite3.connect(get_db_path(root))
    try:
        cursor = conn.execute(
            """
            INSERT INTO files(path, hash, mtime, size, analyzer_name, analyzer_version)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            ("pkg/mod.py", "hash", 1.0, 1, "python", "1"),
        )
        assert cursor.lastrowid is not None
        file_id = int(cursor.lastrowid)
        conn.executemany(
            """
            INSERT INTO symbol_index(name, stable_id, type, module_name, file_id, lineno)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                (
                    f"symbol_{index}",
                    f"symbol:{index}",
                    "function",
                    "pkg.mod",
                    file_id,
                    index + 1,
                )
                for index in range(count)
            ),
        )
        conn.executemany(
            """
            INSERT INTO documentation_artifacts(
                file_id,
                stable_id,
                kind,
                source_format,
                lineno,
                end_lineno,
                title,
                heading_path,
                text,
                owner_stable_id,
                owner_kind,
                attachment_confidence
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                (
                    file_id,
                    f"doc:{index}",
                    "module_docstring",
                    "python",
                    index + 1,
                    None,
                    f"Doc {index}",
                    json.dumps(("pkg", "mod")),
                    f"Documentation {index}",
                    None,
                    None,
                    None,
                )
                for index in range(count)
            ),
        )
        conn.commit()
    finally:
        conn.close()


def _load_workspace_cli_module() -> types.ModuleType:
    """
    Return the index-command implementation module.

    Parameters
    ----------
    None

    Returns
    -------
    types.ModuleType
        Index command-family module under test.

    Raises
    ------
    AssertionError
        Raised when the command-family module cannot be loaded.
    """
    import codira.cli_index as cli_index_module

    return cli_index_module


def test_sqlite_resolve_embedding_scores_chunks_large_score_sets(
    tmp_path: Path,
) -> None:
    """
    Resolve symbol vector scores without exceeding SQLite parameter limits.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository root.

    Returns
    -------
    None
        The test asserts large vector-store score batches are chunked before
        querying structural symbol rows.
    """

    init_db(tmp_path)
    _insert_score_resolution_fixture(tmp_path, count=950)
    backend = SQLiteIndexBackend()

    results = backend.resolve_embedding_scores(
        BackendResolveEmbeddingScoresRequest(
            root=tmp_path,
            candidates=[
                SimilarityCandidate(stable_id=f"symbol:{index}", score=float(index))
                for index in range(950)
            ],
            limit=3,
        )
    )

    assert [cast("SymbolRow", row.record)[2] for row in results] == [
        "symbol_949",
        "symbol_948",
        "symbol_947",
    ]


def test_sqlite_resolve_documentation_scores_chunks_large_score_sets(
    tmp_path: Path,
) -> None:
    """
    Resolve documentation vector scores without exceeding SQLite parameter limits.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository root.

    Returns
    -------
    None
        The test asserts large vector-store score batches are chunked before
        querying structural documentation rows.
    """

    init_db(tmp_path)
    _insert_score_resolution_fixture(tmp_path, count=950)
    backend = SQLiteIndexBackend()

    results = backend.resolve_documentation_scores(
        BackendResolveDocumentationScoresRequest(
            root=tmp_path,
            candidates=[
                SimilarityCandidate(stable_id=f"doc:{index}", score=float(index))
                for index in range(950)
            ],
            limit=3,
        )
    )

    assert [cast("DocumentationRow", row.record)[6] for row in results] == [
        "Doc 949",
        "Doc 948",
        "Doc 947",
    ]


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
            "schema_version": str(backend.version),
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
            "schema_version": str(backend.version),
            "backend_name": "duckdb",
            "backend_version": str(backend.version),
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


def test_git_dirty_indexable_paths_filters_to_tracked_sources(tmp_path: Path) -> None:
    """
    Return only tracked Git-dirty paths accepted by active analyzers.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository root provided by pytest.

    Returns
    -------
    None
        The test asserts untracked scratch files and non-source files do not
        force index refreshes.
    """
    cli_module = _load_workspace_cli_module()
    module = tmp_path / "pkg" / "sample.py"
    notes = tmp_path / "notes.tmp"
    scratch = tmp_path / "scratch.py"
    _write_module(
        module,
        'def demo():\n    """Return a constant."""\n    return 1\n',
    )
    notes.write_text("tracked but unsupported\n", encoding="utf-8")
    scratch.write_text("def ignored():\n    return 2\n", encoding="utf-8")
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "add", "pkg/sample.py", "notes.tmp"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        [
            "git",
            "-c",
            "user.email=codira@example.invalid",
            "-c",
            "user.name=Codira Test",
            "commit",
            "-m",
            "seed",
        ],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )

    module.write_text(
        'def demo():\n    """Return an updated constant."""\n    return 2\n',
        encoding="utf-8",
    )
    notes.write_text("changed but unsupported\n", encoding="utf-8")

    assert cli_module._git_dirty_indexable_paths(tmp_path) == ("pkg/sample.py",)


def test_inspect_index_rebuild_request_detects_dirty_tracked_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Request incremental refresh when a tracked source file is dirty.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository root provided by pytest.
    monkeypatch : pytest.MonkeyPatch
        Fixture used to stub backend state.

    Returns
    -------
    None
        The test asserts a modified tracked source bypasses the complete
        metadata fast path and asks for an incremental rebuild.
    """
    cli_module = _load_workspace_cli_module()
    module = tmp_path / "pkg" / "sample.py"
    _write_module(
        module,
        'def demo():\n    """Return a constant."""\n    return 1\n',
    )
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "add", "pkg/sample.py"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        [
            "git",
            "-c",
            "user.email=codira@example.invalid",
            "-c",
            "user.name=Codira Test",
            "commit",
            "-m",
            "seed",
        ],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    python_inventory = [_analyzer_inventory_row(PythonAnalyzer())]
    backend = _RecordingBackend(
        analyzer_inventory=python_inventory,
        file_hashes={str(module): "abc123"},
    )
    cli_module._write_index_metadata(
        tmp_path,
        {
            "schema_version": str(backend.version),
            "backend_name": "duckdb",
            "backend_version": str(backend.version),
            "analyzer_inventory": json.dumps(python_inventory),
            "indexed_file_count": "1",
            "commit": commit,
        },
    )
    monkeypatch.setattr(
        cli_module,
        "active_index_backend",
        lambda *, root=None: backend,
    )
    module.write_text(
        'def demo():\n    """Return an updated constant."""\n    return 2\n',
        encoding="utf-8",
    )

    request = cli_module._inspect_index_rebuild_request(tmp_path)

    assert request == cli_module.IndexRebuildRequest(
        message="[codira] Index stale (working tree changed) — rebuilding...",
        reset_db=False,
        stderr=True,
    )
    assert backend.opened == [tmp_path]
    assert backend.count_indexed_file_calls == []
    assert backend.load_existing_file_hash_calls == [tmp_path]


def test_inspect_index_rebuild_request_accepts_indexed_dirty_content(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Avoid repeated refreshes when the index already reflects dirty content.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository root provided by pytest.
    monkeypatch : pytest.MonkeyPatch
        Fixture used to stub backend state.

    Returns
    -------
    None
        The test asserts Git-dirty source paths do not rebuild when their
        current hashes match the persisted index rows.
    """
    cli_module = _load_workspace_cli_module()
    module = tmp_path / "pkg" / "sample.py"
    _write_module(
        module,
        'def demo():\n    """Return a constant."""\n    return 1\n',
    )
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "add", "pkg/sample.py"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        [
            "git",
            "-c",
            "user.email=codira@example.invalid",
            "-c",
            "user.name=Codira Test",
            "commit",
            "-m",
            "seed",
        ],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    module.write_text(
        'def demo():\n    """Return an updated constant."""\n    return 2\n',
        encoding="utf-8",
    )
    python_inventory = [_analyzer_inventory_row(PythonAnalyzer())]
    backend = _RecordingBackend(
        analyzer_inventory=python_inventory,
        file_hashes={str(module): cast("str", file_metadata(module)["hash"])},
    )
    cli_module._write_index_metadata(
        tmp_path,
        {
            "schema_version": str(backend.version),
            "backend_name": "duckdb",
            "backend_version": str(backend.version),
            "analyzer_inventory": json.dumps(python_inventory),
            "indexed_file_count": "1",
            "commit": commit,
        },
    )
    monkeypatch.setattr(
        cli_module,
        "active_index_backend",
        lambda *, root=None: backend,
    )
    monkeypatch.setattr(
        cli_module,
        "active_language_analyzers",
        lambda *, root=None: [PythonAnalyzer()],
    )

    assert cli_module._inspect_index_rebuild_request(tmp_path) is None
    assert backend.opened == [tmp_path]
    assert backend.count_indexed_file_calls == []
    assert backend.load_existing_file_hash_calls == [tmp_path]


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
    generation = IndexGenerationStore(tmp_path).read()
    assert generation is not None
    assert generation.state == "ready"
    assert generation.partial is True
    assert generation.failed_file_count == 1

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
    uncovered_module = tmp_path / "src" / "main.swift"
    _write_module(
        python_module,
        'def py_helper():\n    """Return a constant."""\n    return 1\n',
    )
    uncovered_module.parent.mkdir(parents=True, exist_ok=True)
    uncovered_module.write_text("func helper() {}\n", encoding="utf-8")

    init_db(tmp_path)
    report = index_repo(tmp_path)

    assert report.indexed == 1
    assert report.coverage_issues == [
        type(report.coverage_issues[0])(
            path=str(uncovered_module),
            directory="src",
            suffix=".swift",
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


def test_index_repo_indexes_generic_manifest_facts(tmp_path: Path) -> None:
    """
    Persist bounded generic-manifest facts through the normal query path.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository root.

    Returns
    -------
    None
        The test asserts generic JSON facts become exact-query symbols.
    """
    source = tmp_path / "config" / "service-manifest.json"
    source.parent.mkdir(parents=True)
    source.write_text(
        json.dumps(
            {
                "services": {"api": {"path": "src/api"}},
                "deployments": [{"name": "production"}],
                "homepage": "https://example.invalid/service",
            }
        ),
        encoding="utf-8",
    )

    init_db(tmp_path)
    report = index_repo(tmp_path)

    assert report.coverage_issues == []
    assert find_symbol(tmp_path, "services.api.path") == [
        (
            "json_manifest_path",
            "config.service_manifest",
            "services.api.path",
            str(source),
            1,
        )
    ]


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
    vector_binding_count = vector_conn.execute(
        "SELECT COUNT(*) FROM vector_bindings"
    ).fetchone()
    vector_payload_count = vector_conn.execute(
        "SELECT COUNT(*) FROM vector_payloads"
    ).fetchone()
    vector_conn.close()
    assert vector_pending_count == (0,)
    assert vector_binding_count == (2,)
    assert vector_payload_count == (2,)


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
        vector_binding_count = vector_conn.execute(
            "SELECT COUNT(*) FROM vector_bindings"
        ).fetchone()
        vector_payload_count = vector_conn.execute(
            "SELECT COUNT(*) FROM vector_payloads"
        ).fetchone()
        pending_count = vector_conn.execute(
            "SELECT COUNT(*) FROM pending_vectors"
        ).fetchone()
    finally:
        vector_conn.close()

    assert report.embeddings_recomputed == 2
    assert vector_binding_count == (2,)
    assert vector_payload_count == (2,)
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
    _write_index_metadata(
        tmp_path,
        {"schema_version": str(SCHEMA_VERSION)},
    )

    monkeypatch.setattr("codira.cli_index._get_head_commit", lambda root: None)
    monkeypatch.setattr(
        "codira.cli_index.active_language_analyzers",
        lambda *, root=None: [_PythonAnalyzerV12()],
    )
    monkeypatch.setattr(
        "codira.indexer.active_language_analyzers",
        lambda *, root=None: [_PythonAnalyzerV12()],
    )

    _ensure_index(tmp_path)
    captured = capsys.readouterr()
    backend = SQLiteIndexBackend()

    assert "Index stale (analyzer plugin inventory changed)" in captured.err
    assert backend.load_analyzer_inventory(tmp_path) == [
        _analyzer_inventory_row(_PythonAnalyzerV12())
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
    _write_index_metadata(
        tmp_path,
        {"schema_version": str(_SQLiteBackendVNext.version)},
    )

    monkeypatch.setattr("codira.cli_index._get_head_commit", lambda root: None)
    monkeypatch.setattr(
        "codira.cli_index.active_index_backend",
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


def test_index_persists_degraded_python_analysis_without_symbols(
    tmp_path: Path,
) -> None:
    """Persist grammar provenance while leaving unrelated files queryable.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository root.

    Returns
    -------
    None
        The test asserts partial analysis is a coverage issue, not a run abort.
    """
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname = 'sample'\nrequires-python = '>=3.9,<3.10'\n",
        encoding="utf-8",
    )
    _write_module(tmp_path / "pkg" / "valid.py", "def answer():\n    return 42\n")
    _write_module(tmp_path / "pkg" / "broken.py", "def broken(:\n    pass\n")

    init_db(tmp_path)
    report = index_repo(tmp_path)

    conn = sqlite3.connect(get_db_path(tmp_path))
    try:
        status = conn.execute(
            "SELECT coverage_state, diagnostics, reliable_categories "
            "FROM analysis_status WHERE path = ?",
            (str(tmp_path / "pkg" / "broken.py"),),
        ).fetchone()
        symbols = conn.execute("SELECT name FROM functions ORDER BY name").fetchall()
    finally:
        conn.close()

    assert report.failed == 0
    assert len(report.coverage_issues) == 1
    assert status is not None
    assert status[0] == "partial"
    assert "grammar_error" in status[1]
    assert status[2] == "[]"
    assert symbols == [("answer",)]

    (tmp_path / "pkg" / "broken.py").unlink()
    index_repo(tmp_path)
    conn = sqlite3.connect(get_db_path(tmp_path))
    try:
        remaining_statuses = conn.execute(
            "SELECT COUNT(*) FROM analysis_status"
        ).fetchone()
    finally:
        conn.close()
    assert remaining_statuses == (1,)


@pytest.mark.parametrize(
    ("relative_path", "contents"),
    [
        ("src/oversized.py", b"def large():\n    return 1\n"),
        ("docs/oversized.md", b"\x00binary-like markdown payload\n"),
    ],
)
def test_index_skips_sources_over_configured_ingestion_limit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    relative_path: str,
    contents: bytes,
) -> None:
    """Report oversized supported files without reading them for metadata.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository root containing the oversized source fixture.
    monkeypatch : pytest.MonkeyPatch
        Fixture used to fail the test if metadata hashing is attempted.
    relative_path : str
        Repository-relative supported source path to exclude.
    contents : bytes
        Text or binary-like fixture contents exceeding the configured ceiling.

    Returns
    -------
    None
        The assertions verify deterministic coverage reporting without a read.
    """

    source = tmp_path / relative_path
    source.parent.mkdir(parents=True)
    source.write_bytes(contents)
    config = tmp_path / ".codira" / "config.toml"
    config.parent.mkdir()
    config.write_text(
        "[embeddings.indexing]\nmax_source_file_bytes = 1\n",
        encoding="utf-8",
    )

    error_message = "oversized source must not be hashed"

    def _unexpected_metadata_read(_path: Path) -> dict[str, object]:
        raise AssertionError(error_message)

    monkeypatch.setattr(indexer_module, "file_metadata", _unexpected_metadata_read)

    report = index_repo(tmp_path)

    assert report.failed == 0
    assert report.coverage_issues == [
        CoverageIssue(
            path=str(source),
            directory=source.parent.name,
            suffix=source.suffix,
            reason="source file exceeds configured 1-byte ingestion limit",
        )
    ]


def test_strict_index_coverage_rejects_persisted_partial_analysis(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Return strict-coverage failure after persisting degraded provenance.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository root.
    monkeypatch : pytest.MonkeyPatch
        Fixture used to isolate CLI process arguments and the current root.

    Returns
    -------
    None
        The test asserts unrelated files are indexed before strict failure.
    """
    _write_module(tmp_path / "pkg" / "valid.py", "def answer():\n    return 42\n")
    _write_module(tmp_path / "pkg" / "broken.py", "def broken(:\n    pass\n")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["codira", "index", "--require-full-coverage"])

    assert main() == 2

    conn = sqlite3.connect(get_db_path(tmp_path))
    try:
        functions = conn.execute("SELECT name FROM functions ORDER BY name").fetchall()
    finally:
        conn.close()
    assert functions == [("answer",)]


__all__ = [
    "AnalysisResult",
    "BackendPersistAnalysisRequest",
    "BackendResolveDocumentationScoresRequest",
    "BackendResolveEmbeddingScoresRequest",
    "BackendRuntimeInventoryRequest",
    "CallSite",
    "CallableReference",
    "CoverageIssue",
    "DocumentationArtifact",
    "EMBEDDING_BACKEND",
    "EMBEDDING_DIM",
    "EmbeddingBackendSpec",
    "FileMetadataSnapshot",
    "FunctionArtifact",
    "IndexCommandRequest",
    "IndexGenerationStore",
    "IndexRebuildRequest",
    "LanguageAnalyzer",
    "ModuleArtifact",
    "Path",
    "PythonAnalyzer",
    "SCHEMA_VERSION",
    "SQLiteIndexBackend",
    "SimilarityCandidate",
    "StoredEmbeddingRow",
    "TYPE_CHECKING",
    "_PythonAnalyzerV12",
    "_SQLiteBackendVNext",
    "_TrackingSQLiteBackend",
    "_ensure_index",
    "_read_index_metadata",
    "_render_coverage_issues",
    "_write_index_metadata",
    "acquire_index_lock",
    "analyzer_inventory_discovery_json",
    "audit_repo_coverage",
    "cast",
    "contextlib",
    "docstring_issues",
    "file_metadata",
    "find_symbol",
    "get_db_path",
    "index_repo",
    "indexer_module",
    "init_db",
    "json",
    "main",
    "os",
    "pytest",
    "registry_module",
    "sqlite3",
    "storage_module",
    "subprocess",
    "sys",
    "time",
    "types",
]
