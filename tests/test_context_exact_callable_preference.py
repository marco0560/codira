"""Public context regressions for unique qualified callable queries.

Responsibilities
-----------------
- Keep an explicitly requested callable ahead of same-file container symbols.
- Preserve broad-query diversity and ambiguous-name behavior on each backend.

Design principles
-----------------
- Persist the same normalized symbol rows through both first-party backends.
- Do not require a native compiler or infer language-specific name syntax.

Architectural role
------------------
- Verify context orchestration from exact lookup through final diversity
  selection and rendering.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from typing import TYPE_CHECKING, cast

import pytest
from codira_backend_duckdb import DuckDBIndexBackend
from codira_backend_sqlite import SQLiteIndexBackend

from codira.contracts import BackendPersistAnalysisRequest, EmbeddingIndexingPolicy
from codira.models import (
    AnalysisResult,
    ClassArtifact,
    DeclarationArtifact,
    FileMetadataSnapshot,
    FunctionArtifact,
    ModuleArtifact,
)
from codira.query.context import ContextRequest, context_for
from codira.query.context_scoring import _unique_exact_callable_target
from codira.registry import reset_plugin_registry_caches

if TYPE_CHECKING:
    from pathlib import Path

    from codira.contracts import BackendQueryConnection


def _function(name: str, *, line: int, stable_id: str) -> FunctionArtifact:
    """Build one normalized callable row for the backend parity fixture.

    Parameters
    ----------
    name : str
        Stored logical callable name.
    line : int
        One-based source line for this callable row.
    stable_id : str
        Unique stable identity for the callable artifact.

    Returns
    -------
    codira.models.FunctionArtifact
        Minimal callable artifact suitable for backend persistence.
    """
    return FunctionArtifact(
        name=name,
        stable_id=stable_id,
        lineno=line,
        end_lineno=line,
        signature=f"double {name}(double value)",
        docstring="Behavior implementation for indexed context tests.",
        has_docstring=1,
        is_method=0,
        is_public=1,
        parameters=("value",),
        returns_value=1,
        yields_value=0,
        raises=0,
        has_asserts=0,
        decorators=(),
        calls=(),
        callable_refs=(),
    )


def _persist_analysis(
    backend_name: str,
    root: Path,
    source_path: Path,
    *,
    module_name: str,
    namespace: str,
    namespace_line: int,
    functions: tuple[FunctionArtifact, ...],
    full: bool,
    classes: tuple[ClassArtifact, ...] = (),
) -> None:
    """Persist one normalized source snapshot through a selected backend.

    Parameters
    ----------
    backend_name : str
        First-party backend name, either ``sqlite`` or ``duckdb``.
    root : pathlib.Path
        Repository root owning the index.
    source_path : pathlib.Path
        Source file represented by the analysis.
    module_name : str
        Indexed module name for the source file.
    namespace : str
        Namespace declaration to persist beside the callable rows.
    namespace_line : int
        One-based source line for the namespace row.
    functions : tuple[codira.models.FunctionArtifact, ...]
        Callable artifacts owned by the source file.
    full : bool
        Whether this first-party backend session starts a full replacement.
    classes : tuple[codira.models.ClassArtifact, ...], optional
        Class and method artifacts owned by the source file.

    Returns
    -------
    None
        The source analysis is committed to the selected backend.
    """
    backend = SQLiteIndexBackend() if backend_name == "sqlite" else DuckDBIndexBackend()
    backend.initialize(root)
    session = backend.begin_index_session(root)
    source_bytes = source_path.read_bytes()
    analysis = AnalysisResult(
        source_path=source_path,
        module=ModuleArtifact(
            name=module_name,
            stable_id=f"fixture:module:{module_name}",
            docstring=None,
            has_docstring=0,
        ),
        classes=classes,
        functions=functions,
        declarations=(
            DeclarationArtifact(
                name=namespace,
                stable_id=f"fixture:namespace:{module_name}:{namespace}",
                kind="namespace",
                lineno=namespace_line,
                signature=f"namespace {namespace}",
            ),
        ),
        imports=(),
    )
    metadata = FileMetadataSnapshot(
        path=source_path,
        sha256=hashlib.sha256(source_bytes).hexdigest(),
        mtime=source_path.stat().st_mtime,
        size=len(source_bytes),
        analyzer_name="context-preference-fixture",
        analyzer_version="1",
    )
    try:
        session.prepare(
            full=full,
            indexed_paths=[str(source_path)],
            deleted_paths=[],
        )
        session.persist_analysis(
            BackendPersistAnalysisRequest(
                root=root,
                file_metadata=metadata,
                analysis=analysis,
                embedding_indexing=EmbeddingIndexingPolicy(object_types=frozenset()),
                defer_embeddings=True,
            )
        )
        session.rebuild_derived_indexes()
        session.commit()
    except BaseException:
        session.abort()
        raise
    finally:
        session.close()
        if backend_name == "duckdb":
            cast("DuckDBIndexBackend", backend)._close_cached_connections()


def _write_fixture_sources(root: Path) -> tuple[Path, Path, Path, Path]:
    """Create source files whose exact rows compete with enclosing symbols.

    Parameters
    ----------
    root : pathlib.Path
        Temporary source repository root.

    Returns
    -------
    tuple[pathlib.Path, pathlib.Path, pathlib.Path, pathlib.Path]
        Generated-alias-shaped, ordinary, overloaded, and cross-kind source
        paths in that order.
    """
    generated = root / "generated_alias.cpp"
    generated.parent.mkdir(parents=True, exist_ok=True)
    generated.write_text(
        "\n" * 9
        + "namespace alias_case {\n"
        + "WRAP(double, f, (double value)) { return value + 1.0; }\n"
        + "}\n",
        encoding="utf-8",
    )
    ordinary = root / "ordinary.cpp"
    ordinary.write_text(
        "namespace ordinary {\n"
        "double run(double value) { return value + 2.0; }\n"
        "class Widget {\n"
        "double act(double value) { return value + 3.0; }\n"
        "};\n"
        "}\n",
        encoding="utf-8",
    )
    overloaded = root / "overloaded.cpp"
    overloaded.write_text(
        "namespace overload {\n"
        "double choose(double value);\n"
        "double choose(int value);\n"
        "}\n",
        encoding="utf-8",
    )
    cross_kind = root / "cross_kind.cpp"
    cross_kind.write_text(
        "namespace collision { }\ndouble collision(double value) { return value; }\n",
        encoding="utf-8",
    )
    return generated, ordinary, overloaded, cross_kind


@pytest.mark.parametrize("backend_name", ["sqlite", "duckdb"])
def test_context_keeps_unique_exact_qualified_callable_ahead_of_container(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    backend_name: str,
) -> None:
    """Select exact ordinary and generated-name callables before file caps.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Disposable source repository and backend index root.
    monkeypatch : pytest.MonkeyPatch
        Scoped environment and cache control for backend selection.
    backend_name : str
        First-party structural backend under test.

    Returns
    -------
    None
        Exact callable queries render their target while the per-file cap
        remains active.
    """
    root = tmp_path
    codira_dir = root / ".codira"
    codira_dir.mkdir()
    (codira_dir / "config.toml").write_text(
        f'[backend]\nname = "{backend_name}"\n\n[embeddings]\nenabled = false\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("CODIRA_INDEX_BACKEND", backend_name)
    reset_plugin_registry_caches()
    generated, ordinary, overloaded, cross_kind = _write_fixture_sources(root)

    _persist_analysis(
        backend_name,
        root,
        generated,
        module_name="generated_alias",
        namespace="alias_case",
        namespace_line=10,
        functions=(
            replace(
                _function("alias_case::f", line=11, stable_id="fixture:alias:f"),
                end_lineno=None,
            ),
            _function("alias_case::impl_f", line=11, stable_id="fixture:alias:impl-f"),
        ),
        full=True,
    )
    _persist_analysis(
        backend_name,
        root,
        ordinary,
        module_name="ordinary_cpp",
        namespace="ordinary",
        namespace_line=1,
        functions=(
            _function("ordinary::run", line=2, stable_id="fixture:ordinary:run"),
        ),
        full=False,
        classes=(
            ClassArtifact(
                name="ordinary::Widget",
                stable_id="fixture:ordinary:widget",
                lineno=3,
                end_lineno=5,
                docstring=None,
                has_docstring=0,
                methods=(
                    replace(
                        _function(
                            "act",
                            line=4,
                            stable_id="fixture:ordinary:widget:act",
                        ),
                        is_method=1,
                        owner_name="ordinary::Widget",
                        owner_stable_id="fixture:ordinary:widget",
                    ),
                ),
            ),
        ),
    )
    _persist_analysis(
        backend_name,
        root,
        overloaded,
        module_name="overloaded_cpp",
        namespace="overload",
        namespace_line=1,
        functions=(
            _function("overload::choose", line=2, stable_id="fixture:choose:double"),
            _function("overload::choose", line=3, stable_id="fixture:choose:int"),
        ),
        full=False,
    )
    _persist_analysis(
        backend_name,
        root,
        cross_kind,
        module_name="cross_kind_cpp",
        namespace="collision",
        namespace_line=1,
        functions=(
            _function("collision", line=2, stable_id="fixture:collision:function"),
        ),
        full=False,
    )

    backend = SQLiteIndexBackend() if backend_name == "sqlite" else DuckDBIndexBackend()
    conn = cast("BackendQueryConnection", backend.open_connection(root))
    try:
        assert _unique_exact_callable_target(root, "alias_case::f", conn, None) == (
            "function",
            "generated_alias",
            "alias_case::f",
            str(generated),
            11,
        )
        assert _unique_exact_callable_target(
            root, "alias_case::impl_f", conn, None
        ) == (
            "function",
            "generated_alias",
            "alias_case::impl_f",
            str(generated),
            11,
        )
        assert _unique_exact_callable_target(root, "ordinary::run", conn, None) == (
            "function",
            "ordinary_cpp",
            "ordinary::run",
            str(ordinary),
            2,
        )
        assert _unique_exact_callable_target(
            root, "ordinary::Widget.act", conn, None
        ) == (
            "method",
            "ordinary_cpp",
            "act",
            str(ordinary),
            4,
        )
        assert _unique_exact_callable_target(root, "run", conn, None) is None
        assert (
            _unique_exact_callable_target(root, "overload::choose", conn, None) is None
        )
        assert (
            _unique_exact_callable_target(root, "cross_kind_cpp.collision", conn, None)
            is None
        )
    finally:
        conn.close()

    for query, expected in (
        ("alias_case::f", "alias_case::f"),
        ("alias_case::impl_f", "alias_case::impl_f"),
        ("ordinary::run", "ordinary::run"),
        ("ordinary::Widget.act", "act"),
    ):
        payload = json.loads(
            context_for(
                ContextRequest(root=root, query=query, as_json=True, explain=True)
            )
        )
        assert payload["top_matches"][0]["name"] == expected
        assert payload["explain"]["diversity"]["selected"][0]["name"] == expected
        assert any(
            row["reason"] == "file_cap"
            for row in payload["explain"]["diversity"]["deferred"]
        )
        if query == "alias_case::f":
            assert any("WRAP(double, f" in line for line in payload["context"][0])

    prefixed = json.loads(
        context_for(
            ContextRequest(
                root=root,
                query="alias_case::f",
                prefix="generated_alias.cpp",
                as_json=True,
                explain=True,
            )
        )
    )
    assert prefixed["top_matches"][0]["name"] == "alias_case::f"
    assert prefixed["top_matches"][0]["file"].endswith("generated_alias.cpp")

    broad = json.loads(
        context_for(
            ContextRequest(
                root=root,
                query="behavior implementation overview",
                result_limit=20,
                as_json=True,
            )
        )
    )
    broad_files = [row["file"] for row in broad["top_matches"]]
    assert len(broad_files) >= 2
    assert len(broad_files) == len(set(broad_files))
