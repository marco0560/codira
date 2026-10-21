"""Verify real C++ dependency changes through the indexing coordinator.

Parameters
----------
None

Returns
-------
None
    Behavioral proofs for reuse, negative lookups, failures and worker races.
"""

from __future__ import annotations

import hashlib
import os
from typing import TYPE_CHECKING, cast

import pytest
from codira_analyzer_cpp import CppAnalyzer, cpp_include_context

from codira.cli_index import _inspect_index_rebuild_request
from codira.config import IndexConcurrencyConfig
from codira.index_generation import IndexGenerationStore
from codira.indexer import index_repo
from codira.registry import active_index_backend

if TYPE_CHECKING:
    from pathlib import Path

    from codira_backend_duckdb import DuckDBIndexBackend
    from codira_backend_sqlite import SQLiteIndexBackend

    from codira.contracts import IndexBackend
    from codira.models import AnalysisResult


def _repository(root: Path, backend_name: str) -> tuple[Path, IndexBackend]:
    """Create two C++ sources depending on an unindexed include file.

    Parameters
    ----------
    root : pathlib.Path
        Disposable repository root.
    backend_name : str
        Real structural backend selected in repository configuration.

    Returns
    -------
    tuple[pathlib.Path, codira.contracts.IndexBackend]
        Dependency path and initialized backend.
    """
    (root / ".codira").mkdir()
    (root / ".codira/config.toml").write_text(
        f'[backend]\nname = "{backend_name}"\n[embeddings]\nenabled = false\n',
        encoding="utf-8",
    )
    for filename, function in (("first.cpp", "answer"), ("second.cpp", "second")):
        (root / filename).write_text(
            f'#include "marker.inc"\nAPI int {function}() {{ return 42; }}\n',
            encoding="utf-8",
        )
    header = root / "marker.inc"
    header.write_bytes(b"#define API __declspec(dllexport)\n")
    backend = active_index_backend(root=root)
    backend.initialize(root)
    return header, backend


@pytest.mark.parametrize("backend_name", ["sqlite", "duckdb"])
@pytest.mark.parametrize("strategy", ["off", "process"])
def test_header_only_changes_reindex_sources_and_match_full_rebuild(
    tmp_path: Path, backend_name: str, strategy: str
) -> None:
    """Reparse unchanged sources when their unindexed header bytes change.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Disposable repository.
    backend_name : str
        Real backend used for writes and structural queries.
    strategy : str
        Serial or isolated process-worker scheduling.

    Returns
    -------
    None
        Header edits invalidate reuse and reader freshness without changing SHA.
    """
    header, backend = _repository(tmp_path, backend_name)
    concurrency = IndexConcurrencyConfig(strategy=strategy, max_workers=2, min_files=1)
    first = index_repo(tmp_path, analysis_concurrency=concurrency)
    assert first.failed == 0 and first.indexed == 2
    assert first.analysis_concurrency.effective_strategy == strategy
    assert backend.find_symbol(tmp_path, "answer")
    original_hashes = backend.load_existing_file_hashes(tmp_path)
    assert _inspect_index_rebuild_request(tmp_path) is None
    unchanged = index_repo(tmp_path, analysis_concurrency=concurrency)
    assert unchanged.indexed == 0 and unchanged.reused == 2
    stamp = header.stat()
    replacement = b"#define API Widget".ljust(len(header.read_bytes()) - 1) + b"\n"
    header.write_bytes(replacement)
    os.utime(header, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
    request = _inspect_index_rebuild_request(tmp_path)
    assert request is not None and not request.reset_db
    changed = index_repo(tmp_path, analysis_concurrency=concurrency)
    assert changed.indexed == 2 and changed.reused == 0
    assert changed.analysis_concurrency.effective_strategy == strategy
    assert any(
        d.reason == "external analysis inputs changed" for d in changed.decisions
    )
    assert not backend.find_symbol(tmp_path, "answer")
    assert backend.load_existing_file_hashes(tmp_path) == original_hashes
    header.write_bytes(b"#define API __declspec(dllexport)\n")
    restored = index_repo(tmp_path, analysis_concurrency=concurrency)
    assert restored.indexed == 2 and restored.failed == 0
    incremental_symbols = backend.find_symbol(tmp_path, "answer")
    assert incremental_symbols
    rebuilt = index_repo(tmp_path, full=True, analysis_concurrency=concurrency)
    assert rebuilt.failed == 0
    assert backend.find_symbol(tmp_path, "answer") == incremental_symbols
    assert backend.load_existing_file_hashes(tmp_path) == original_hashes


@pytest.mark.parametrize("backend_name", ["sqlite", "duckdb"])
def test_header_creation_deletion_and_transitive_edits_change_freshness(
    tmp_path: Path, backend_name: str
) -> None:
    """Track negative lookups and transitive bytes outside source discovery.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Disposable repository.
    backend_name : str
        Real structural backend.

    Returns
    -------
    None
        Include creation, deletion and transitive edits reindex the source.
    """
    header, backend = _repository(tmp_path, backend_name)
    header.unlink()
    first = index_repo(tmp_path)
    assert first.failed == 0 and not backend.find_symbol(tmp_path, "answer")
    original_hashes = backend.load_existing_file_hashes(tmp_path)
    header.write_bytes(b'#include "base.inc"\n')
    base = tmp_path / "base.inc"
    base.write_bytes(b"#define API __declspec(dllexport)\n")
    assert _inspect_index_rebuild_request(tmp_path) is not None
    assert index_repo(tmp_path).indexed == 2
    assert backend.find_symbol(tmp_path, "answer")
    base.write_bytes(b"#define API int\n")
    assert _inspect_index_rebuild_request(tmp_path) is not None
    assert index_repo(tmp_path).indexed == 2
    assert not backend.find_symbol(tmp_path, "answer")
    base.write_bytes(b"#define API __declspec(dllexport)\n")
    assert index_repo(tmp_path).indexed == 2
    assert backend.find_symbol(tmp_path, "answer")
    header.unlink()
    assert _inspect_index_rebuild_request(tmp_path) is not None
    assert index_repo(tmp_path).indexed == 2
    assert not backend.find_symbol(tmp_path, "answer")
    assert backend.load_existing_file_hashes(tmp_path) == original_hashes


@pytest.mark.parametrize("backend_name", ["sqlite", "duckdb"])
def test_changed_header_retries_retained_analysis_failure(
    tmp_path: Path, backend_name: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Bind an injected analyzer failure to its observed external inputs.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Disposable repository.
    backend_name : str
        Real structural backend.
    monkeypatch : pytest.MonkeyPatch
        Injects an analyzer exception to exercise failure-cache orchestration.

    Returns
    -------
    None
        Unchanged failures are reused; changed dependency bytes trigger retries.

    Notes
    -----
    Exception injection grades coordinator failure reuse, not parser semantics.
    """
    header, _ = _repository(tmp_path, backend_name)
    (tmp_path / "good.py").write_text("VALUE = 1\n", encoding="utf-8")
    original = CppAnalyzer.analyze_file
    attempts: list[str] = []

    def injected(self: CppAnalyzer, path: Path, root: Path) -> AnalysisResult:
        """Fail while a dependency marker is present.

        Parameters
        ----------
        self : CppAnalyzer
            Configured owner.
        path : pathlib.Path
            Source path.
        root : pathlib.Path
            Repository context.

        Returns
        -------
        AnalysisResult
            Real C++ artifacts after the failure marker is removed.

        Raises
        ------
        ValueError
            While the dependency contains the injected failure marker.
        """
        attempts.append(path.name)
        if b"FAIL" in header.read_bytes():
            message = "injected dependency-bound analyzer failure"
            raise ValueError(message)
        return original(self, path, root)

    monkeypatch.setattr(CppAnalyzer, "analyze_file", injected)
    header.write_bytes(b"#define API\n// FAIL\n")
    first = index_repo(tmp_path)
    assert first.failed == 2
    record = IndexGenerationStore(tmp_path).read()
    assert record is not None and record.failed_files
    assert all(row["analysis_input_fingerprint"] for row in record.failed_files)
    assert len(attempts) == 2
    assert index_repo(tmp_path, retry_failed_files=False).failed == 2
    assert len(attempts) == 2
    header.write_bytes(b"#define API\n")
    assert _inspect_index_rebuild_request(tmp_path) is not None
    recovered = index_repo(tmp_path, retry_failed_files=False)
    assert recovered.failed == 0 and recovered.indexed == 2
    assert len(attempts) == 4
    for path, digest in recovered.file_hashes.items():
        assert hashlib.sha256((tmp_path / path).read_bytes()).hexdigest() == digest


@pytest.mark.parametrize("backend_name", ["sqlite", "duckdb"])
@pytest.mark.parametrize("mutation", ["header", "source", "new_header"])
def test_worker_rejects_inputs_changed_during_analysis(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    backend_name: str,
    mutation: str,
) -> None:
    """Reject raced source bytes, header bytes and newly resolved includes.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Disposable repository.
    monkeypatch : pytest.MonkeyPatch
        Injects a write after real parsing and before worker validation.
    backend_name : str
        Real structural backend used to check that no stale symbols publish.
    mutation : str
        Source, captured header or previously missing include to change.

    Returns
    -------
    None
        Raced analysis becomes a failure and its stale symbols are absent.
    """
    header, backend = _repository(tmp_path, backend_name)
    if mutation == "new_header":
        for source in tmp_path.glob("*.cpp"):
            source.write_bytes(b'#include "new_marker.inc"\n' + source.read_bytes())
    original = CppAnalyzer.analyze_file

    def raced(self: CppAnalyzer, path: Path, root: Path) -> AnalysisResult:
        """Change observed inputs after producing real source artifacts.

        Parameters
        ----------
        self : CppAnalyzer
            Configured owner.
        path : pathlib.Path
            Source path.
        root : pathlib.Path
            Repository context.

        Returns
        -------
        AnalysisResult
            Artifacts bound to the preceding header state.
        """
        result = original(self, path, root)
        target = (
            path
            if mutation == "source"
            else root / "new_marker.inc"
            if mutation == "new_header"
            else header
        )
        stamp = target.stat() if target.exists() else None
        replacement = (
            target.read_bytes().replace(b"42", b"43")
            if mutation == "source"
            else b"#define NEW_MARKER 1\n"
            if mutation == "new_header"
            else target.read_bytes().replace(b"dllexport", b"dllimport")
        )
        target.write_bytes(replacement)
        if stamp is not None:
            os.utime(target, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
        return result

    monkeypatch.setattr(CppAnalyzer, "analyze_file", raced)
    report = index_repo(tmp_path)
    assert report.failed == 2
    assert all("inputs changed" in failure.reason for failure in report.failures)
    assert not backend.find_symbol(tmp_path, "answer")


@pytest.mark.parametrize("backend_name", ["sqlite", "duckdb"])
@pytest.mark.parametrize("strategy", ["off", "thread"])
def test_worker_validates_unchanged_inputs_without_recomputing_fingerprints(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    backend_name: str,
    strategy: str,
) -> None:
    """Keep worker race checks without repeating successful input captures.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Disposable repository with real C++ include dependencies.
    monkeypatch : pytest.MonkeyPatch
        Allows planning captures but rejects subsequent full recomputation.
    backend_name : str
        Real structural backend receiving complete artifacts.
    strategy : str
        Serial or shared-memory thread scheduling.

    Returns
    -------
    None
        Real indexing publishes both files after content-based verification.
    """
    _, backend = _repository(tmp_path, backend_name)
    original = CppAnalyzer.analysis_input_fingerprint
    captures: dict[Path, int] = {}

    def capture_once(self: CppAnalyzer, path: Path, root: Path) -> str:
        """Permit each planning capture without repeating it in workers.

        Parameters
        ----------
        self : CppAnalyzer
            Configured source owner.
        path : pathlib.Path
            Original source path.
        root : pathlib.Path
            Repository context.

        Returns
        -------
        str
            Actual source-bound include identity.

        Raises
        ------
        AssertionError
            If worker validation rebuilds a previously captured identity.
        """
        captures[path] = captures.get(path, 0) + 1
        assert captures[path] == 1
        return original(self, path, root)

    monkeypatch.setattr(CppAnalyzer, "analysis_input_fingerprint", capture_once)
    concurrency = IndexConcurrencyConfig(strategy=strategy, max_workers=2, min_files=1)
    report = index_repo(tmp_path, analysis_concurrency=concurrency)
    assert report.failed == 0 and report.indexed == 2
    assert len(captures) == 2 and set(captures.values()) == {1}
    assert backend.find_symbol(tmp_path, "answer")


@pytest.mark.parametrize("backend_name", ["sqlite", "duckdb"])
def test_unchanged_inputs_validate_without_reparsing_cpp(
    tmp_path: Path, backend_name: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Use persisted resolution data rather than reparsing unchanged includes.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Disposable repository.
    backend_name : str
        Real structural backend.
    monkeypatch : pytest.MonkeyPatch
        Rejects any subsequent include parsing.

    Returns
    -------
    None
        Both reader freshness and incremental reuse avoid the syntax parser.
    """
    _repository(tmp_path, backend_name)
    assert index_repo(tmp_path).failed == 0

    def reject_parse(source: bytes) -> list[tuple[str, bool | None, int]]:
        """Reject syntax work after a captured manifest is available.

        Parameters
        ----------
        source : bytes
            Source that should not need parsing.

        Returns
        -------
        list[tuple[str, bool | None, int]]
            This boundary must not be reached.

        Raises
        ------
        AssertionError
            If reuse reparses unchanged input syntax.
        """
        del source
        message = "unchanged input validation must not parse C++"
        raise AssertionError(message)

    monkeypatch.setattr(cpp_include_context, "_includes", reject_parse)
    assert _inspect_index_rebuild_request(tmp_path) is None
    report = index_repo(tmp_path)
    assert report.indexed == 0 and report.reused == 2


def test_cpp_configuration_changes_invalidate_captured_input_identity(
    tmp_path: Path,
) -> None:
    """Bind input reuse to the configured analyzer behavior as well as bytes.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Disposable repository.

    Returns
    -------
    None
        Configuration changes reanalyze unchanged sources and update symbols.
    """
    _, backend = _repository(tmp_path, "sqlite")
    source = tmp_path / "first.cpp"
    source.write_bytes(b"#define LOCAL 1\n" + source.read_bytes())
    assert index_repo(tmp_path).failed == 0
    assert backend.find_symbol(tmp_path, "LOCAL")
    hashes = backend.load_existing_file_hashes(tmp_path)
    config = tmp_path / ".codira/config.toml"
    config.write_text(
        config.read_text() + "\n[plugins.analyzer-cpp]\nemit_macros = false\n",
        encoding="utf-8",
    )
    report = index_repo(tmp_path)
    assert report.indexed == 2 and report.failed == 0
    assert not backend.find_symbol(tmp_path, "LOCAL")
    assert backend.load_existing_file_hashes(tmp_path) == hashes


@pytest.mark.parametrize("backend_name", ["sqlite", "duckdb"])
@pytest.mark.parametrize("header_first", [True, False])
def test_external_methods_link_to_real_header_class_without_duplicate_declaration(
    tmp_path: Path, backend_name: str, header_first: bool
) -> None:
    """Preserve method kind, owner and source locations across file boundaries.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Disposable repository.
    backend_name : str
        Real structural backend.
    header_first : bool
        Exercises both source-before-header insertion and header-first deletion.

    Returns
    -------
    None
        Method owners bind after persistence; class declarations remain in headers.
    """
    _, backend = _repository(tmp_path, backend_name)
    for filename in ("first.cpp", "second.cpp", "marker.inc"):
        (tmp_path / filename).unlink()
    header = tmp_path / ("a_widget.h" if header_first else "z_widget.h")
    source = tmp_path / ("z_impl.cpp" if header_first else "a_impl.cpp")
    header.write_bytes(
        b"#define API __declspec(dllexport)\n"
        b"class Widget { public: API int run() const; private: int helper() const; };\n"
    )
    source.write_text(
        f'#include "{header.name}"\n'
        "API int Widget::run() const { return helper(); }\n"
        "int Widget::helper() const { return 42; }\n",
        encoding="utf-8",
    )
    analyzed = CppAnalyzer().analyze_file(source, tmp_path)
    assert analyzed.index_symbols and not analyzed.classes
    assert {fn.name for fn in analyzed.functions} == {"run", "helper"}
    assert all(fn.is_method and fn.owner_name == "Widget" for fn in analyzed.functions)
    assert all(fn.owner_stable_id for fn in analyzed.functions)
    assert next(fn for fn in analyzed.functions if fn.name == "helper").is_public == 0
    report = index_repo(tmp_path)
    assert report.failed == 0
    symbols = backend.find_symbol(tmp_path, "run")
    assert len(symbols) == 2 and all(row[0] == "method" for row in symbols)
    assert {row[3] for row in backend.find_symbol(tmp_path, "Widget")} == {str(header)}
    owned_backend = cast("SQLiteIndexBackend | DuckDBIndexBackend", backend)
    conn = owned_backend.open_connection(tmp_path)
    try:
        owners = conn.execute(
            "SELECT f.name, c.name, origin.path FROM functions f "
            "JOIN classes c ON c.id = f.class_id "
            "JOIN modules m ON m.id = c.module_id JOIN files origin ON origin.id = m.file_id "
            "WHERE f.owner_stable_id IS NOT NULL ORDER BY f.name"
        ).fetchall()
        assert owners == [
            ("helper", "Widget", str(header)),
            ("run", "Widget", str(header)),
        ]
        assert conn.execute(
            "SELECT caller_name, callee_name, resolved FROM call_edges "
            "WHERE caller_name = 'Widget.run'"
        ).fetchall() == [("Widget.run", "Widget.helper", 1)]
    finally:
        conn.close()
    header.write_bytes(header.read_bytes().replace(b"private:", b"public:"))
    updated = index_repo(tmp_path)
    assert updated.failed == 0 and updated.indexed == 2
    assert {row[3] for row in backend.find_symbol(tmp_path, "Widget")} == {str(header)}
    assert backend.find_symbol(tmp_path, "run") == symbols
    assert index_repo(tmp_path, full=True).failed == 0
    assert backend.find_symbol(tmp_path, "run") == symbols


@pytest.mark.parametrize(
    ("parameters", "body", "expected_kind", "expected_base"),
    [
        ("", "return helper();", "attribute", "Widget"),
        ("", "int value = helper(); return value;", "attribute", "Widget"),
        ("", "return this->helper();", "attribute", "Widget"),
        ("int (*helper)()", "return helper();", "name", ""),
        ("", "int (*helper)() = nullptr; return helper();", "name", ""),
        ("", "auto helper = [] { return 7; }; return helper();", "name", ""),
        ("", "return ::helper();", "name", ""),
    ],
)
def test_external_member_call_bindings_preserve_shadowed_and_qualified_names(
    tmp_path: Path, parameters: str, body: str, expected_kind: str, expected_base: str
) -> None:
    """Infer member lookup only when captured declarations prove the receiver.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Disposable repository.
    parameters : str
        Method parameters including a possible shadowing callable.
    body : str
        Method body with a member, local or explicitly global call.
    expected_kind : str
        Expected normalized call kind.
    expected_base : str
        Expected explicit owner, or the original empty base.

    Returns
    -------
    None
        Shadowed and explicitly qualified names retain their original records.
    """
    (tmp_path / "widget.h").write_text(
        "class Widget { public: int run(); int helper(); };\n", encoding="utf-8"
    )
    source = tmp_path / "widget.cpp"
    source.write_text(
        f'#include "widget.h"\nint Widget::run({parameters}) {{ {body} }}\n',
        encoding="utf-8",
    )
    result = CppAnalyzer().analyze_file(source, tmp_path)
    assert result.index_symbols
    calls = tuple(call for call in result.functions[0].calls if call.target == "helper")
    assert len(calls) == 1
    assert (calls[0].kind, calls[0].base) == (expected_kind, expected_base)
