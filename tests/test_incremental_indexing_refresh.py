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


def test_index_repo_coordinates_public_mutations_with_the_index_lock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Acquire the shared mutation lock through the public indexing API.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary directory provided by pytest.
    monkeypatch : pytest.MonkeyPatch
        Fixture used to record lock acquisition without platform I/O.

    Returns
    -------
    None
        The test asserts direct and future daemon callers share one public
        coordination boundary.
    """
    acquired_roots: list[Path] = []

    @contextlib.contextmanager
    def _recording_lock(root: Path) -> Iterator[None]:
        acquired_roots.append(root)
        yield

    _write_module(tmp_path / "pkg" / "sample.py", "def demo() -> int:\n    return 1\n")
    init_db(tmp_path)
    monkeypatch.setattr(indexer_module, "acquire_index_lock", _recording_lock)

    report = index_repo(tmp_path)

    assert report.indexed == 1
    assert acquired_roots == [tmp_path]


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
            "("
            "file_id, function_id, class_id, module_id, issue_type, message, "
            "audit_language, audit_plugin_name, audit_plugin_version, "
            "convention_name, convention_version, rule_id, severity"
            ") "
            "VALUES (?, NULL, NULL, NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                file_id,
                "missing",
                "Function build: Missing docstring",
                "python",
                "numpy",
                "1",
                "numpy",
                "1",
                "missing",
                "warning",
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
        lambda root=None: EmbeddingBackendSpec(
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
    assert report.embeddings_recomputed == 0
    assert report.embeddings_reused == 2
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
        lambda *, root=None: [_PythonAnalyzerV12()],
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
    assert owners == [("python", "12")]


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
