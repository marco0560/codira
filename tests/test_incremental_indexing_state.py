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
        "codira.indexer.read_head_commit",
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


def test_noop_index_refreshes_commit_metadata_without_publishing_generation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Refresh freshness metadata when a completed index reuses every file.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary directory provided by pytest.
    monkeypatch : pytest.MonkeyPatch
        Fixture used to change the observed Git commit between index passes.

    Returns
    -------
    None
        The test asserts a no-op updates commit metadata without notifying
        generation-based readers of a content change.
    """
    module = tmp_path / "pkg" / "sample.py"
    _write_module(
        module,
        'def demo():\n    """Return a constant."""\n    return 1\n',
    )
    head = "first"
    monkeypatch.setattr("codira.indexer.read_head_commit", lambda root: head)

    index_repo(tmp_path)
    first_generation = IndexGenerationStore(tmp_path).read()
    assert first_generation is not None
    assert first_generation.git_commit == "first"

    head = "second"
    report = index_repo(tmp_path)

    assert report.indexed == 0
    assert report.reused == 1
    assert _read_index_metadata(tmp_path)["commit"] == "second"
    assert IndexGenerationStore(tmp_path).read() == first_generation


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
        "codira.indexer.read_head_commit",
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

    monkeypatch.setattr("codira.cli_index.acquire_index_lock", _dummy_lock)
    monkeypatch.setattr(
        "codira.cli_index._inspect_index_rebuild_request",
        lambda root: next(inspections),
    )

    def _unexpected_refresh(root: Path, current: IndexRebuildRequest) -> None:
        del root, current
        msg = "duplicate rebuild should have been skipped"
        raise AssertionError(msg)

    monkeypatch.setattr(
        "codira.cli_index._run_locked_index_refresh",
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


def test_acquire_index_lock_reenters_without_relocking_same_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Avoid reacquiring an operating-system lock inside one mutation transaction.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary directory provided by pytest.
    monkeypatch : pytest.MonkeyPatch
        Fixture used to record low-level lock operations.

    Returns
    -------
    None
        The test asserts nested same-root coordination acquires and releases
        the underlying advisory lock exactly once.
    """
    operations: list[str] = []
    monkeypatch.setattr(
        storage_module,
        "_lock_file_handle",
        lambda handle: operations.append("lock"),
    )
    monkeypatch.setattr(
        storage_module,
        "_unlock_file_handle",
        lambda handle: operations.append("unlock"),
    )

    with acquire_index_lock(tmp_path), acquire_index_lock(tmp_path.resolve()):
        assert operations == ["lock"]

    assert operations == ["lock", "unlock"]


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
