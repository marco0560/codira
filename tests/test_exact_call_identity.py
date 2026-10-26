"""Exercise persisted exact callable identities in both structural backends."""

from __future__ import annotations

import hashlib
import pickle
from typing import TYPE_CHECKING

import pytest
from codira_backend_duckdb import DuckDBIndexBackend
from codira_backend_sqlite import SQLiteIndexBackend

from codira.contracts import (
    BackendPersistAnalysisRequest,
    BackendRelationQueryRequest,
    EmbeddingIndexingPolicy,
)
from codira.models import (
    AnalysisResult,
    CallSite,
    DeclarationArtifact,
    FileMetadataSnapshot,
    FunctionArtifact,
    ModuleArtifact,
    SemanticIdentity,
)
from codira.normalization import analysis_result_from_parsed
from codira.query.exact import EdgeQueryRequest, find_call_edges

if TYPE_CHECKING:
    from pathlib import Path


def _function(
    name: str,
    stable_id: str,
    line: int,
    *,
    identity: str | None = None,
    call: CallSite | None = None,
) -> FunctionArtifact:
    """Create a minimal callable artifact for persistence tests."""
    return FunctionArtifact(
        name=name,
        stable_id=stable_id,
        lineno=line,
        end_lineno=line,
        signature=f"int {name}()",
        docstring=None,
        has_docstring=0,
        is_method=0,
        is_public=1,
        parameters=(),
        returns_value=0,
        yields_value=0,
        raises=0,
        has_asserts=0,
        decorators=(),
        calls=() if call is None else (call,),
        callable_refs=(),
        semantic_identity=(
            None if identity is None else SemanticIdentity("opaque.test.v1", identity)
        ),
    )


def _analysis(
    path: Path,
    module_name: str,
    functions: tuple[FunctionArtifact, ...],
    declarations: tuple[DeclarationArtifact, ...] = (),
) -> AnalysisResult:
    """Build a file analysis with the supplied callable declarations."""
    return AnalysisResult(
        source_path=path,
        module=ModuleArtifact(module_name, f"test:module:{module_name}", None, 0),
        classes=(),
        functions=functions,
        declarations=declarations,
        imports=(),
    )


def _request(
    root: Path, path: Path, analysis: AnalysisResult
) -> BackendPersistAnalysisRequest:
    """Bind one analysis to the exact bytes written for its source file."""
    source = path.read_bytes()
    return BackendPersistAnalysisRequest(
        root=root,
        file_metadata=FileMetadataSnapshot(
            path=path,
            sha256=hashlib.sha256(source).hexdigest(),
            mtime=path.stat().st_mtime,
            size=len(source),
            analyzer_name="fixture",
            analyzer_version="1",
        ),
        analysis=analysis,
        embedding_indexing=EmbeddingIndexingPolicy(object_types=frozenset()),
        defer_embeddings=True,
    )


def test_semantic_identity_mappings_reify_before_pickle_round_trip(
    tmp_path: Path,
) -> None:
    """Reify nested identity mappings before worker-style dataclass transfer.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Disposable source path used to construct one parsed analysis result.

    Returns
    -------
    None
        Identity DTOs survive normalization and pickle serialization.
    """
    analysis = analysis_result_from_parsed(
        tmp_path / "fixture.cpp",
        {
            "module": {"name": "fixture"},
            "functions": [
                {
                    "name": "caller",
                    "lineno": 1,
                    "signature": "int caller()",
                    "semantic_identity": {
                        "namespace": "opaque.test.v1",
                        "value": "caller-id",
                    },
                    "calls": [
                        {
                            "kind": "name",
                            "target": "callee",
                            "lineno": 2,
                            "col_offset": 4,
                            "target_identity": {
                                "namespace": "opaque.test.v1",
                                "value": "callee-id",
                            },
                            "resolution_mode": "exact",
                            "origin": "macro_replacement",
                        }
                    ],
                }
            ],
            "declarations": [
                {
                    "name": "field",
                    "kind": "variable",
                    "lineno": 3,
                    "signature": "int field",
                    "owner_name": "Record",
                    "owner_stable_id": "record-id",
                    "access": "private",
                    "type_text": "int",
                }
            ],
        },
    )

    transferred = pickle.loads(pickle.dumps(analysis))

    assert transferred.functions[0].semantic_identity == SemanticIdentity(
        "opaque.test.v1", "caller-id"
    )
    assert transferred.functions[0].calls[0].target_identity == SemanticIdentity(
        "opaque.test.v1", "callee-id"
    )
    assert transferred.functions[0].calls[0].resolution_mode == "exact"
    assert transferred.functions[0].calls[0].origin == "macro_replacement"
    assert transferred.declarations[0].access == "private"
    assert transferred.declarations[0].type_text == "int"


def test_core_query_adapts_legacy_seven_field_call_edges(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Normalize an older backend's call tuple at the core query boundary.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Root attached to the relation request.
    monkeypatch : pytest.MonkeyPatch
        Replaces active backend discovery with a minimal legacy provider.

    Returns
    -------
    None
        Old caller/name tuples become the current endpoint-identity row shape.
    """

    class LegacyBackend:
        """Expose the former seven-column call-edge result shape."""

        @staticmethod
        def open_connection(_root: Path) -> object:
            return object()

        @staticmethod
        def close_connection(_conn: object) -> None:
            return None

        @staticmethod
        def find_call_edges(_request: object) -> list[tuple[object, ...]]:
            return [
                ("caller_module", "caller", "callee_module", "callee", None, None, 1)
            ]

    backend = LegacyBackend()
    monkeypatch.setattr(
        "codira.query.exact.active_index_backend",
        lambda root: backend,
    )

    assert find_call_edges(EdgeQueryRequest(root=tmp_path, name="caller")) == [
        (
            "caller_module",
            "caller",
            None,
            "callee_module",
            "callee",
            None,
            None,
            None,
            1,
        )
    ]


@pytest.mark.parametrize("backend_name", ["sqlite", "duckdb"])
def test_exact_call_edges_keep_both_overloaded_endpoints_across_files(
    tmp_path: Path, backend_name: str
) -> None:
    """Keep overloaded callers and callees distinct in persisted graph rows.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Disposable source and database root.
    backend_name : str
        First-party structural backend tested through its real database.

    Returns
    -------
    None
        Raw and derived persisted rows retain both exact endpoint identities.
    """
    callers_path = tmp_path / "caller.cpp"
    targets_path = tmp_path / "targets.cpp"
    callers_path.write_text("int caller();\nint caller(int);\n", encoding="utf-8")
    targets_path.write_text("int target();\nint target(int);\n", encoding="utf-8")

    first_call = CallSite(
        kind="name",
        target="target",
        lineno=20,
        col_offset=8,
        target_identity=SemanticIdentity("opaque.test.v1", "target-zero"),
        resolution_mode="exact",
        origin="source_written",
    )
    second_call = CallSite(
        kind="name",
        target="target",
        lineno=20,
        col_offset=8,
        target_identity=SemanticIdentity("opaque.test.v1", "target-one"),
        resolution_mode="exact",
        origin="macro_replacement",
    )
    unknown_target_call = CallSite(
        kind="name",
        target="target",
        lineno=21,
        col_offset=8,
        resolution_mode="exact",
    )
    indirect_call = CallSite(
        kind="unresolved",
        target="function_pointer",
        lineno=22,
        col_offset=8,
        resolution_mode="exact",
        origin="source_written",
    )
    external_call = CallSite(
        kind="name",
        target="external",
        lineno=23,
        col_offset=8,
        target_identity=SemanticIdentity("opaque.test.v1", "external"),
        resolution_mode="exact",
        external_target_kind="function",
        external_target_name="external",
    )
    ambiguous_call = CallSite(
        kind="name",
        target="target",
        lineno=24,
        col_offset=8,
        target_identity=SemanticIdentity("opaque.test.v1", "duplicate"),
        resolution_mode="exact",
    )
    target_analysis = _analysis(
        targets_path,
        "target_module",
        (
            _function("target", "target-stable-0", 1, identity="target-zero"),
            _function("target", "target-stable-1", 2, identity="target-one"),
            _function("target", "target-duplicate-0", 3, identity="duplicate"),
            _function("target", "target-duplicate-1", 4, identity="duplicate"),
        ),
        (
            DeclarationArtifact(
                name="field",
                stable_id="field-stable-id",
                kind="variable",
                lineno=5,
                signature="int field",
                owner_name="Record",
                owner_stable_id="record-stable-id",
                access="private",
                type_text="int",
            ),
        ),
    )
    caller_analysis = _analysis(
        callers_path,
        "caller_module",
        (
            _function("caller", "caller-stable-0", 1, call=first_call),
            _function("caller", "caller-stable-1", 2, call=second_call),
            _function("caller", "caller-stable-2", 3, call=unknown_target_call),
            _function("caller", "caller-stable-3", 4, call=indirect_call),
            _function("caller", "caller-stable-4", 5, call=external_call),
            _function("caller", "caller-stable-5", 6, call=ambiguous_call),
        ),
    )

    backend = SQLiteIndexBackend() if backend_name == "sqlite" else DuckDBIndexBackend()
    backend.initialize(tmp_path)
    session = backend.begin_index_session(tmp_path)
    try:
        session.prepare(
            full=True,
            indexed_paths=[str(callers_path), str(targets_path)],
            deleted_paths=[],
        )
        session.persist_analysis(_request(tmp_path, targets_path, target_analysis))
        session.persist_analysis(_request(tmp_path, callers_path, caller_analysis))
        session.rebuild_derived_indexes()
        session.commit()
    except BaseException:
        session.abort()
        raise
    finally:
        session.close()

    conn = backend.open_connection(tmp_path)
    try:
        raw_calls = conn.execute(
            "SELECT owner_stable_id, target_identity_value, resolution_mode, origin "
            "FROM call_records ORDER BY owner_stable_id"
        ).fetchall()
        declaration_access = conn.execute(
            "SELECT access, owner_name, owner_stable_id, signature, type_text "
            "FROM symbol_index "
            "WHERE stable_id = 'field-stable-id'"
        ).fetchall()
        edges = conn.execute(
            "SELECT caller_stable_id, callee_stable_id, resolved "
            "FROM call_edges ORDER BY caller_stable_id"
        ).fetchall()
        queried = backend.find_call_edges(
            BackendRelationQueryRequest(
                root=tmp_path,
                name="caller",
                module="caller_module",
                conn=conn,
            )
        )
        caller_filtered = backend.find_call_edges(
            BackendRelationQueryRequest(
                root=tmp_path,
                name="caller",
                module="caller_module",
                stable_id="caller-stable-1",
                conn=conn,
            )
        )
        callee_filtered = backend.find_call_edges(
            BackendRelationQueryRequest(
                root=tmp_path,
                name="target",
                module="target_module",
                incoming=True,
                stable_id="target-stable-0",
                conn=conn,
            )
        )
    finally:
        conn.close()

    assert raw_calls == [
        ("caller-stable-0", "target-zero", "exact", "source_written"),
        ("caller-stable-1", "target-one", "exact", "macro_replacement"),
        ("caller-stable-2", None, "exact", None),
        ("caller-stable-3", None, "exact", "source_written"),
        ("caller-stable-4", "external", "exact", None),
        ("caller-stable-5", "duplicate", "exact", None),
    ]
    assert declaration_access == [
        ("private", "Record", "record-stable-id", "int field", "int")
    ]
    assert edges == [
        ("caller-stable-0", "target-stable-0", 1),
        ("caller-stable-1", "target-stable-1", 1),
        ("caller-stable-2", None, 0),
        ("caller-stable-3", None, 0),
        ("caller-stable-4", None, 0),
        ("caller-stable-5", None, 0),
    ]
    assert [row[2] for row in queried] == [
        "caller-stable-0",
        "caller-stable-1",
        "caller-stable-2",
        "caller-stable-3",
        "caller-stable-4",
        "caller-stable-5",
    ]
    assert [row[5] for row in queried] == [
        "target-stable-0",
        "target-stable-1",
        None,
        None,
        None,
        None,
    ]
    assert [row[8] for row in queried] == [1, 1, 0, 0, 0, 0]
    assert [row[2] for row in caller_filtered] == ["caller-stable-1"]
    assert [row[5] for row in callee_filtered] == ["target-stable-0"]
