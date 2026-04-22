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
from pathlib import Path
from typing import TYPE_CHECKING, cast

import pytest
from codira_backend_sqlite import SQLiteIndexBackend

import codira.registry as registry_module
from codira.analyzers import PythonAnalyzer
from codira.cli import (
    IndexRebuildRequest,
    _ensure_index,
    _read_index_metadata,
    _write_index_metadata,
    main,
)
from codira.contracts import BackendPersistAnalysisRequest
from codira.indexer import audit_repo_coverage, index_repo
from codira.models import (
    AnalysisResult,
    CallableReference,
    CallSite,
    FileMetadataSnapshot,
    FunctionArtifact,
    ModuleArtifact,
)
from codira.query.exact import docstring_issues, find_symbol
from codira.scanner import file_metadata
from codira.schema import SCHEMA_VERSION
from codira.semantic.embeddings import (
    EMBEDDING_BACKEND,
    EMBEDDING_DIM,
    EmbeddingBackendSpec,
)
from codira.storage import acquire_index_lock, get_db_path, init_db

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


class _PythonAnalyzerV4:
    """
    Python analyzer stub with a bumped version for staleness tests.

    Parameters
    ----------
    None
    """

    name = "python"
    version = "4"
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


class _SQLiteBackendV14(SQLiteIndexBackend):
    """SQLite backend stub with a bumped version for runtime tests."""

    version = 14


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
                (shell_path.as_posix(),),
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

    assert first.embeddings_recomputed == 3
    assert report.indexed == 1
    assert report.embeddings_reused == 2
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
        lambda: [_PythonAnalyzerV4()],
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
    assert owners == [("python", "4")]


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
            reason="no registered analyzer covers this canonical file",
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
        "no registered analyzer covers this canonical file)"
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
        "no registered analyzer covers this canonical file)"
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
    assert "Coverage issues: 2" in captured.out
    assert (
        "coverage: .json x2 in "
        "src, tests (.json, no registered analyzer covers this canonical file)"
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
        The test asserts the JSON coverage envelope includes analyzer and
        issue metadata.
    """
    rust_module = tmp_path / "src" / "lib.rs"
    rust_module.parent.mkdir(parents=True, exist_ok=True)
    rust_module.write_text("pub fn helper() {}\n", encoding="utf-8")

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["codira", "cov", "--json"])

    assert main() == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["command"] == "cov"
    assert payload["status"] == "incomplete"
    assert payload["query"]["canonical_directories"] == ["src", "tests", "scripts"]
    assert payload["results"] == [
        {
            "path": str(rust_module),
            "directory": "src",
            "suffix": ".rs",
            "reason": "no registered analyzer covers this canonical file",
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
    }
    assert payload["results"] == []
    assert payload["summary"] == {
        "indexed": 1,
        "reused": 0,
        "deleted": 0,
        "failed": 0,
        "embeddings_recomputed": 2,
        "embeddings_reused": 0,
    }
    assert payload["coverage_issues"] == [
        {
            "path": str(config_file),
            "directory": "scripts",
            "suffix": ".json",
            "reason": "no registered analyzer covers this canonical file",
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
    }
    assert payload["summary"] == {
        "indexed": 0,
        "reused": 0,
        "deleted": 0,
        "failed": 0,
        "embeddings_recomputed": 0,
        "embeddings_reused": 0,
    }
    assert payload["coverage_issues"] == [
        {
            "path": str(rust_module),
            "directory": "src",
            "suffix": ".rs",
            "reason": "no registered analyzer covers this canonical file",
        }
    ]
    assert payload["warnings"] == []
    assert payload["failures"] == []
    assert payload["decisions"] == []
    assert not get_db_path(tmp_path).exists()


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
        lambda: [_PythonAnalyzerV4()],
    )
    monkeypatch.setattr(
        "codira.indexer.active_language_analyzers",
        lambda: [_PythonAnalyzerV4()],
    )

    _ensure_index(tmp_path)
    captured = capsys.readouterr()
    backend = SQLiteIndexBackend()

    assert "Index stale (analyzer plugin inventory changed)" in captured.err
    assert backend.load_analyzer_inventory(tmp_path) == [("python", "4", '["*.py"]')]


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
        lambda: _SQLiteBackendV14(),
    )
    monkeypatch.setattr(
        "codira.indexer.active_index_backend",
        lambda: _SQLiteBackendV14(),
    )

    _ensure_index(tmp_path)
    captured = capsys.readouterr()
    backend = SQLiteIndexBackend()

    assert "Index stale (backend plugin changed)" in captured.err
    assert backend.load_runtime_inventory(tmp_path) == ("sqlite", "14", 1)


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
        "commit": "abc123",
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
        "commit": "abc123",
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
