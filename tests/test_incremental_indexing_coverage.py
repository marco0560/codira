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
from typing import cast

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
        "coverage: .json x1 in src "
        "(.json, no registered analyzer accepts this file type/content combination)"
    ) in captured.out


def test_coverage_renderer_groups_distinct_reasons_separately(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Preserve distinct coverage causes in human-readable output.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Repository root used for relative report paths.
    capsys : pytest.CaptureFixture[str]
        Fixture used to capture rendered coverage output.

    Returns
    -------
    None
        The test asserts each suffix-and-reason group is rendered accurately.
    """
    _render_coverage_issues(
        tmp_path,
        [
            CoverageIssue(
                path=str(tmp_path / "src" / "partial.py"),
                directory="src",
                suffix=".py",
                reason="template_string requires Python 3.14 but the declared target includes older versions",
            ),
            CoverageIssue(
                path=str(tmp_path / "tests" / "unclaimed.py"),
                directory="tests",
                suffix=".py",
                reason="no registered analyzer accepts this file type/content combination",
            ),
        ],
    )

    captured = capsys.readouterr()
    assert (
        "coverage: .py x1 in src (.py, template_string requires Python 3.14"
        in captured.out
    )
    assert (
        "coverage: .py x1 in tests (.py, no registered analyzer accepts" in captured.out
    )


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
    uncovered_module = tmp_path / "src" / "main.swift"
    uncovered_module.parent.mkdir(parents=True, exist_ok=True)
    uncovered_module.write_text("func helper() {}\n", encoding="utf-8")

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["codira", "cov", "--json"])

    assert main() == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["command"] == "cov"
    assert payload["status"] == "incomplete"
    assert payload["query"]["coverage"] == {
        "source": "analyzer-defaults",
        "patterns": [
            ".github",
            "app",
            "benches",
            "cmd",
            "config",
            "docs",
            "examples",
            "include",
            "internal",
            "lib",
            "pages",
            "pkg",
            "scripts",
            "src",
            "test",
            "tests",
        ],
        "exclude_suffixes": [],
        "resolved_roots": ["src"],
    }
    assert payload["results"] == [
        {
            "path": str(uncovered_module),
            "directory": "src",
            "suffix": ".swift",
            "reason": "no registered analyzer accepts this file type/content combination",
        }
    ]
    assert payload["analyzers"]


def test_coverage_config_can_disable_auditing(tmp_path: Path) -> None:
    """Honor the explicit coverage-audit opt-out sentinel.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository root.

    Returns
    -------
    None
        The assertion verifies disabled auditing emits no gaps.
    """

    source = tmp_path / "src" / "unclaimed.swift"
    source.parent.mkdir(parents=True)
    source.write_text("func main() {}\n", encoding="utf-8")
    config = tmp_path / ".codira" / "config.toml"
    config.parent.mkdir()
    config.write_text('[index.coverage]\nroots = ["-"]\n', encoding="utf-8")

    assert audit_repo_coverage(tmp_path) == []


def test_coverage_config_overrides_analyzer_defaults(tmp_path: Path) -> None:
    """Restrict coverage auditing to configured root patterns.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository root.

    Returns
    -------
    None
        The assertion verifies only configured roots are audited.
    """

    covered = tmp_path / "custom" / "unclaimed.swift"
    ignored = tmp_path / "src" / "unclaimed.swift"
    covered.parent.mkdir(parents=True)
    ignored.parent.mkdir(parents=True)
    covered.write_text("func main() {}\n", encoding="utf-8")
    ignored.write_text("func main() {}\n", encoding="utf-8")
    config = tmp_path / ".codira" / "config.toml"
    config.parent.mkdir()
    config.write_text('[index.coverage]\nroots = ["custom/**"]\n', encoding="utf-8")

    assert [issue.path for issue in audit_repo_coverage(tmp_path)] == [str(covered)]


def test_coverage_config_excludes_uncovered_suffixes(tmp_path: Path) -> None:
    """Silence known uncovered file types without narrowing coverage roots.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository root.

    Returns
    -------
    None
        The assertion verifies configured suffix exclusions suppress matching
        coverage diagnostics only.
    """

    uncovered_file = tmp_path / "src" / "unclaimed.swift"
    yaml_file = tmp_path / "src" / "workflow.yml"
    uncovered_file.parent.mkdir(parents=True)
    uncovered_file.write_text("func main() {}\n", encoding="utf-8")
    yaml_file.write_text("name: demo\n", encoding="utf-8")
    config = tmp_path / ".codira" / "config.toml"
    config.parent.mkdir()
    config.write_text(
        '[index.coverage]\nroots = ["src"]\nexclude_suffixes = [".yml"]\n',
        encoding="utf-8",
    )

    assert [issue.path for issue in audit_repo_coverage(tmp_path)] == [
        str(uncovered_file)
    ]


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
    uncovered_module = tmp_path / "src" / "main.swift"
    _write_module(
        python_module,
        'def demo():\n    """Return a constant."""\n    return 1\n',
    )
    uncovered_module.parent.mkdir(parents=True, exist_ok=True)
    uncovered_module.write_text("func helper() {}\n", encoding="utf-8")

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
        "analysis_concurrency": {
            "requested_strategy": "auto",
            "effective_strategy": "off",
            "workers": 1,
            "reason": None,
        },
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
    uncovered_module = tmp_path / "src" / "main.swift"
    uncovered_module.parent.mkdir(parents=True, exist_ok=True)
    uncovered_module.write_text("func helper() {}\n", encoding="utf-8")

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
        "analysis_concurrency": {
            "requested_strategy": "unknown",
            "effective_strategy": "unknown",
            "workers": 0,
            "reason": None,
        },
    }
    assert payload["coverage_issues"] == [
        {
            "path": str(uncovered_module),
            "directory": "src",
            "suffix": ".swift",
            "reason": "no registered analyzer accepts this file type/content combination",
        }
    ]
    assert payload["warnings"] == []
    assert payload["failures"] == []
    assert payload["decisions"] == []
    assert not get_db_path(tmp_path).exists()


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
