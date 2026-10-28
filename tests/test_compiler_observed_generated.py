"""Exercise truthful compiler-observed generated callable and declaration evidence.

Parameters
----------
None

Returns
-------
None
    Declaration and callable evidence remain distinct from token-derived v1.
"""

from __future__ import annotations

import hashlib
import json
import pickle
from argparse import Namespace
from dataclasses import asdict, replace
from types import SimpleNamespace
from typing import TYPE_CHECKING

import pytest
from codira_backend_duckdb import DuckDBIndexBackend
from codira_backend_sqlite import SQLiteIndexBackend

from codira.config import profile_config, render_config_toml
from codira.contracts import BackendPersistAnalysisRequest, EmbeddingIndexingPolicy
from codira.generated import (
    CompilerObservedCallableProvenance,
    CompilerObservedCallableProvenanceV3,
    CompilerObservedDeclarationProvenance,
    CompilerObservedMacroInvocation,
    CompilerObservedSourceCoordinate,
    generated_provenance_payload,
    generated_provenance_rows,
)
from codira.index_generation import IndexGeneration
from codira.indexer import _AnalysisTaskResult
from codira.models import (
    AnalysisResult,
    DeclarationArtifact,
    FileMetadataSnapshot,
    FunctionArtifact,
    ModuleArtifact,
    OverloadArtifact,
    SemanticIdentity,
)
from codira.query.evidence import (
    _attach_generated_evidence,
    expand_symbol,
    symbol_identity,
)
from codira.query.exact import find_symbol

if TYPE_CHECKING:
    from pathlib import Path


def _provenance(
    source: bytes,
    *,
    invocation: bool = True,
    context_identity: str = "a" * 64,
) -> CompilerObservedCallableProvenance:
    """Create one valid compiler-observed generated callable record.

    Parameters
    ----------
    source : bytes
        Source bytes whose macro invocation is retained.
    invocation : bool, optional
        Whether to include an observed preprocessor event.
    context_identity : str, optional
        Exact opaque identity supplied by the analyzer input provider.

    Returns
    -------
    CompilerObservedCallableProvenance
        Version-two evidence with no token derivation claims.
    """
    source_text = "GENERATE(foo)"
    event = (
        CompilerObservedMacroInvocation(
            name="GENERATE",
            path="src/main.c",
            byte_range=(0, len(source_text.encode("utf-8"))),
            text=source_text,
        )
        if invocation
        else None
    )
    return CompilerObservedCallableProvenance(
        origin="macro_argument",
        role="definition",
        source_sha256=hashlib.sha256(source).hexdigest(),
        context_identity=context_identity,
        spelling_location=CompilerObservedSourceCoordinate("include/macros.h", 24),
        expansion_location=CompilerObservedSourceCoordinate("src/main.c", 9),
        invocation=event,
        receipt_namespace="example.compiler.callable.v1",
        receipt_json=json.dumps(
            {"callable": {"name": "foo", "usr": "opaque:foo"}},
            sort_keys=True,
            separators=(",", ":"),
        ),
    )


def _request(
    root: Path,
    path: Path,
    source: bytes,
    provenance: CompilerObservedCallableProvenance
    | CompilerObservedCallableProvenanceV3,
    *,
    overloads: tuple[OverloadArtifact, ...] = (),
) -> BackendPersistAnalysisRequest:
    """Build an actual backend write request containing one generated callable.

    Parameters
    ----------
    root : pathlib.Path
        Disposable repository and backend root.
    path : pathlib.Path
        Source path indexed by the backend.
    source : bytes
        Exact source bytes bound to the file metadata.
    provenance : object
        Compiler-observed generated provenance attached to the callable.
    overloads : tuple[codira.models.OverloadArtifact, ...], optional
        Generated overload declarations attached to the callable.

    Returns
    -------
    BackendPersistAnalysisRequest
        Fresh structural persistence request.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(source)
    function = FunctionArtifact(
        name="foo",
        stable_id="callable:foo",
        lineno=1,
        end_lineno=1,
        signature="int foo(void)",
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
        calls=(),
        callable_refs=(),
        overloads=overloads,
        generated=provenance,
    )
    analysis = AnalysisResult(
        source_path=path,
        module=ModuleArtifact("main", "module:main", None, 0),
        classes=(),
        functions=(function,),
        declarations=(),
        imports=(),
    )
    return BackendPersistAnalysisRequest(
        root=root,
        file_metadata=FileMetadataSnapshot(
            path=path,
            sha256=hashlib.sha256(source).hexdigest(),
            mtime=path.stat().st_mtime,
            size=len(source),
            analyzer_name="fixture",
            analyzer_version="1",
            analysis_input_fingerprint=provenance.context_identity,
        ),
        analysis=analysis,
        embedding_indexing=EmbeddingIndexingPolicy(object_types=frozenset()),
        defer_embeddings=True,
    )


def _declaration_provenance(source: bytes) -> CompilerObservedDeclarationProvenance:
    """Build one valid compiler-observed variable declaration receipt.

    Parameters
    ----------
    source : bytes
        Translation-unit bytes bound to the evidence digest.

    Returns
    -------
    CompilerObservedDeclarationProvenance
        Declaration evidence with an exact observed invocation span.
    """
    invocation_text = "OBSERVED_VALUE(foo)"
    return CompilerObservedDeclarationProvenance(
        origin="macro_argument",
        declaration_kind="variable",
        source_sha256=hashlib.sha256(source).hexdigest(),
        context_identity="b" * 64,
        receipt_namespace="clang.frontend.declaration-observation.v1",
        receipt_json=json.dumps(
            {"declaration": {"kind": "variable", "name": "foo"}},
            sort_keys=True,
            separators=(",", ":"),
        ),
        expansion_location=CompilerObservedSourceCoordinate(
            "src/main.c", invocation_text.index("foo")
        ),
        invocation=CompilerObservedMacroInvocation(
            name="OBSERVED_VALUE",
            path="src/main.c",
            byte_range=(0, len(invocation_text.encode("utf-8"))),
            text=invocation_text,
        ),
    )


def _declaration_request(
    root: Path,
    path: Path,
    source: bytes,
    provenance: CompilerObservedDeclarationProvenance,
) -> BackendPersistAnalysisRequest:
    """Build a real backend write request containing one declaration receipt.

    Parameters
    ----------
    root : pathlib.Path
        Disposable repository and backend root.
    path : pathlib.Path
        Source path indexed by the backend.
    source : bytes
        Exact source bytes bound to the declaration evidence.
    provenance : CompilerObservedDeclarationProvenance
        Compiler-observed macro origin attached to the declaration.

    Returns
    -------
    BackendPersistAnalysisRequest
        Fresh structural persistence request.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(source)
    analysis = AnalysisResult(
        source_path=path,
        module=ModuleArtifact("main", "module:main", None, 0),
        classes=(),
        functions=(),
        declarations=(
            DeclarationArtifact(
                name="foo",
                stable_id="declaration:foo",
                kind="variable",
                lineno=1,
                signature="int foo",
                generated=provenance,
            ),
        ),
        imports=(),
    )
    return BackendPersistAnalysisRequest(
        root=root,
        file_metadata=FileMetadataSnapshot(
            path=path,
            sha256=hashlib.sha256(source).hexdigest(),
            mtime=path.stat().st_mtime,
            size=len(source),
            analyzer_name="fixture",
            analyzer_version="1",
            analysis_input_fingerprint=provenance.context_identity,
        ),
        analysis=analysis,
        embedding_indexing=EmbeddingIndexingPolicy(object_types=frozenset()),
        defer_embeddings=True,
    )


def _alias_provenance(
    source: bytes,
    target: SemanticIdentity | None,
    *,
    invocation: bool = True,
) -> CompilerObservedCallableProvenanceV3:
    """Create version-three observed alias evidence.

    Parameters
    ----------
    source : bytes
        Indexed translation-unit bytes bound to the evidence digest.
    target : codira.models.SemanticIdentity | None
        Exact compiler target identity, or None for an unresolved alias.
    invocation : bool, optional
        Whether to retain a separately observed macro invocation.

    Returns
    -------
    CompilerObservedCallableProvenanceV3
        Alias record with observed linker spelling and no fabricated tokens.
    """
    invocation_text = "ALIAS(alias, implementation)"
    observed_invocation = (
        CompilerObservedMacroInvocation(
            name="ALIAS",
            path="src/main.c",
            byte_range=(0, len(invocation_text.encode("utf-8"))),
            text=invocation_text,
        )
        if invocation
        else None
    )
    return CompilerObservedCallableProvenanceV3(
        origin="macro_replacement",
        role="alias",
        source_sha256=hashlib.sha256(source).hexdigest(),
        context_identity="a" * 64,
        receipt_namespace="example.compiler.callable.v1",
        receipt_json=json.dumps(
            {"callable": {"name": "alias", "usr": "opaque:alias"}},
            sort_keys=True,
            separators=(",", ":"),
        ),
        alias_target_identity=target,
        linkage_name="f",
        invocation=observed_invocation,
        spelling_location=CompilerObservedSourceCoordinate("include/aliases.h", 8),
        expansion_location=CompilerObservedSourceCoordinate("src/main.c", 12),
    )


@pytest.mark.parametrize("backend_name", ["sqlite", "duckdb"])
def test_compiler_observed_provenance_persists_as_opaque_json(
    tmp_path: Path, backend_name: str
) -> None:
    """Persist and validate v2 evidence through each real structural backend.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Disposable repository and database root.
    backend_name : str
        Structural backend under test.

    Returns
    -------
    None
        The opaque payload survives a real write and database read.
    """
    source = b"GENERATE(foo);\n"
    path = tmp_path / "src" / "main.c"
    provenance = _provenance(source)
    backend = SQLiteIndexBackend() if backend_name == "sqlite" else DuckDBIndexBackend()
    backend.initialize(tmp_path)
    session = backend.begin_index_session(tmp_path)
    try:
        session.prepare(full=True, indexed_paths=[str(path)], deleted_paths=[])
        session.persist_analysis(_request(tmp_path, path, source, provenance))
        session.rebuild_derived_indexes()
        session.commit()
    except BaseException:
        session.abort()
        raise
    finally:
        session.close()

    if isinstance(backend, SQLiteIndexBackend):
        sqlite_conn = backend.open_connection(tmp_path)
        try:
            rows = sqlite_conn.execute(
                "SELECT payload FROM artifact_provenance WHERE stable_id = ?",
                ("callable:foo",),
            ).fetchall()
        finally:
            backend.close_connection(sqlite_conn)
    else:
        duckdb_conn = backend.open_connection(tmp_path)
        try:
            rows = duckdb_conn.execute(
                "SELECT payload FROM artifact_provenance WHERE stable_id = ?",
                ("callable:foo",),
            ).fetchall()
        finally:
            backend.close_connection(duckdb_conn)
    assert len(rows) == 1
    stored = generated_provenance_payload(str(rows[0][0]))
    assert stored["variant"] == "compiler_observed"
    assert stored["origin"] == "macro_argument"
    assert stored["source_sha256"] == hashlib.sha256(source).hexdigest()
    assert stored["invocation"] == {
        "name": "GENERATE",
        "path": "src/main.c",
        "byte_range": [0, 13],
        "text": "GENERATE(foo)",
    }
    assert "tokens" not in stored
    assert "parameter_types" not in stored


@pytest.mark.parametrize("backend_name", ["sqlite", "duckdb"])
def test_compiler_observed_declaration_persists_and_survives_worker_pickle(
    tmp_path: Path, backend_name: str
) -> None:
    """Roundtrip declaration evidence through worker and generic backend JSON.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Disposable repository and database root.
    backend_name : str
        Structural backend under test.

    Returns
    -------
    None
        Declaration DTOs survive pickle and the unchanged provenance table.
    """
    source = b"OBSERVED_VALUE(foo);\n"
    path = tmp_path / "src" / "main.c"
    provenance = _declaration_provenance(source)
    request = _declaration_request(tmp_path, path, source, provenance)
    worker_result = _AnalysisTaskResult(
        ordinal=0,
        parsed_file=(path, request.file_metadata, request.analysis),
        failure=None,
        warnings=(),
    )
    worker_roundtrip = pickle.loads(pickle.dumps(worker_result))
    assert worker_roundtrip.parsed_file is not None
    _, _, worker_analysis = worker_roundtrip.parsed_file
    assert isinstance(
        worker_analysis.declarations[0].generated,
        CompilerObservedDeclarationProvenance,
    )
    serialized_rows = generated_provenance_rows(worker_analysis)
    assert len(serialized_rows) == 1
    assert serialized_rows[0][0] == "declaration:foo"
    serialized_payload = generated_provenance_payload(serialized_rows[0][1])
    assert serialized_payload["variant"] == "compiler_observed_declaration"
    assert serialized_payload["declaration_kind"] == "variable"

    backend = SQLiteIndexBackend() if backend_name == "sqlite" else DuckDBIndexBackend()
    backend.initialize(tmp_path)
    session = backend.begin_index_session(tmp_path)
    try:
        session.prepare(full=True, indexed_paths=[str(path)], deleted_paths=[])
        session.persist_analysis(request)
        session.rebuild_derived_indexes()
        session.commit()
    except BaseException:
        session.abort()
        raise
    finally:
        session.close()

    if isinstance(backend, SQLiteIndexBackend):
        sqlite_conn = backend.open_connection(tmp_path)
        try:
            rows = sqlite_conn.execute(
                "SELECT stable_id, payload FROM artifact_provenance WHERE stable_id = ?",
                ("declaration:foo",),
            ).fetchall()
        finally:
            backend.close_connection(sqlite_conn)
    else:
        duckdb_conn = backend.open_connection(tmp_path)
        try:
            rows = duckdb_conn.execute(
                "SELECT stable_id, payload FROM artifact_provenance WHERE stable_id = ?",
                ("declaration:foo",),
            ).fetchall()
        finally:
            backend.close_connection(duckdb_conn)
    assert len(rows) == 1
    assert rows[0][0] == "declaration:foo"
    stored = generated_provenance_payload(str(rows[0][1]))
    assert stored == serialized_payload


@pytest.mark.parametrize("backend_name", ["sqlite", "duckdb"])
def test_expand_symbol_renders_compiler_observed_declaration(
    tmp_path: Path,
    backend_name: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Render declaration evidence through the public query API and real backend.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Disposable source repository and structural database root.
    backend_name : str
        SQLite or DuckDB structural backend to exercise.
    monkeypatch : pytest.MonkeyPatch
        Test-only fixture for the synthetic analyzer's freshness identity.

    Returns
    -------
    None
        Public evidence rendering exposes the physical macro invocation.
    """
    source = b"OBSERVED_VALUE(foo);\n"
    path = tmp_path / "src" / "main.c"
    request = _declaration_request(
        tmp_path,
        path,
        source,
        _declaration_provenance(source),
    )
    config = profile_config("default")
    config["backend"] = {"name": backend_name}
    config_path = tmp_path / ".codira" / "config.toml"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(render_config_toml(config), encoding="utf-8")

    backend = SQLiteIndexBackend() if backend_name == "sqlite" else DuckDBIndexBackend()
    backend.initialize(tmp_path)
    session = backend.begin_index_session(tmp_path)
    try:
        session.prepare(full=True, indexed_paths=[str(path)], deleted_paths=[])
        session.persist_analysis(request)
        session.rebuild_derived_indexes()
        session.commit()
    except BaseException:
        session.abort()
        raise
    finally:
        session.close()

    monkeypatch.setattr(
        "codira.query.evidence.IndexGenerationStore.read",
        lambda self: IndexGeneration(
            schema_version=1,
            generation=1,
            state="ready",
            last_successful_generation=1,
            timestamp="2026-10-28T00:00:00Z",
        ),
    )
    monkeypatch.setattr(
        "codira.query.evidence.active_language_analyzers",
        lambda *, root: [SimpleNamespace(name="fixture", version="1")],
    )
    monkeypatch.setattr(
        "codira.query.evidence.analysis_input_fingerprint_matches",
        lambda analyzer, path, root, expected: True,
    )
    row = find_symbol(tmp_path, "foo")[0]
    result = expand_symbol(tmp_path, symbol_identity(tmp_path, row))

    assert result["source_kind"] == "compiler_generated"
    assert result["compiler_observed_declaration"] == {
        "origin": "macro_argument",
        "declaration_kind": "variable",
        "spelling_location": None,
        "expansion_location": {"path": "src/main.c", "byte_offset": 15},
    }
    assert result["start_line"] == result["end_line"] == 1
    assert result["source"] == "OBSERVED_VALUE(foo)"


def test_declaration_provenance_kind_must_match_artifact_kind(tmp_path: Path) -> None:
    """Reject provenance attached to a different normalized declaration kind.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary root used to bind a declaration analysis result.

    Returns
    -------
    None
        Serializer validation rejects a constant/variable identity mismatch.
    """
    source = b"OBSERVED_VALUE(foo);\n"
    request = _declaration_request(
        tmp_path,
        tmp_path / "src" / "main.c",
        source,
        _declaration_provenance(source),
    )
    declaration = replace(request.analysis.declarations[0], kind="constant")
    analysis = replace(request.analysis, declarations=(declaration,))

    with pytest.raises(ValueError, match="does not match its artifact"):
        generated_provenance_rows(analysis)


@pytest.mark.parametrize(
    "mutation",
    [
        "unknown_field",
        "unsupported_kind",
        "missing_expansion",
        "missing_invocation",
        "wrong_namespace",
        "bad_source_path",
        "noncanonical_receipt",
    ],
)
def test_invalid_compiler_observed_declaration_payload_is_rejected(
    mutation: str,
) -> None:
    """Reject malformed declaration evidence without relaxing callable schemas.

    Parameters
    ----------
    mutation : str
        Invalid declaration payload mutation to apply.

    Returns
    -------
    None
        The strict declaration discriminator rejects all malformed variants.
    """
    source = b"OBSERVED_VALUE(foo);\n"
    payload = asdict(_declaration_provenance(source))
    if mutation == "unknown_field":
        payload["extra"] = True
    elif mutation == "unsupported_kind":
        payload["declaration_kind"] = "namespace"
    elif mutation == "missing_expansion":
        del payload["expansion_location"]
    elif mutation == "missing_invocation":
        payload["invocation"] = None
    elif mutation == "wrong_namespace":
        payload["receipt_namespace"] = "clang.frontend.callable-observation.v1"
    elif mutation == "bad_source_path":
        payload["expansion_location"]["path"] = "../outside.c"
    else:
        payload["receipt_json"] = '{"z":1, "a":2}'

    with pytest.raises(ValueError):
        generated_provenance_payload(
            json.dumps(payload, sort_keys=True, separators=(",", ":"))
        )


def test_compiler_observed_declaration_evidence_uses_physical_invocation_span(
    tmp_path: Path,
) -> None:
    """Render declaration provenance at the verified authored invocation.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository root containing the original invocation.

    Returns
    -------
    None
        Evidence returns the physical macro span and compiler locations.
    """
    from codira.query.evidence import _verify_observed_invocation

    invocation_text = "OBSERVED_VALUE(foo)"
    source = f"{invocation_text};\n".encode()
    path = tmp_path / "src" / "main.c"
    path.parent.mkdir()
    path.write_bytes(source)
    payload = generated_provenance_payload(
        json.dumps(
            asdict(_declaration_provenance(source)),
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    _verify_observed_invocation(tmp_path, path, payload)
    result: dict[str, object] = {
        "file": "src/main.c",
        "start_line": 1,
        "end_line": 1,
        "source": invocation_text,
    }

    _attach_generated_evidence(result, payload, [], source)

    assert result["source_kind"] == "compiler_generated"
    assert result["source"] == invocation_text
    assert result["start_line"] == 1
    assert result["end_line"] == 1
    assert result["compiler_observed_invocation"] == payload["invocation"]
    assert result["compiler_observed_declaration"] == {
        "origin": "macro_argument",
        "declaration_kind": "variable",
        "spelling_location": None,
        "expansion_location": payload["expansion_location"],
    }


@pytest.mark.parametrize("backend_name", ["sqlite", "duckdb"])
@pytest.mark.parametrize(
    "target",
    [SemanticIdentity("opaque.test.v1", "callable:implementation"), None],
)
@pytest.mark.parametrize("invocation", [True, False])
def test_compiler_observed_v3_alias_roundtrips_and_is_queryable(
    tmp_path: Path,
    backend_name: str,
    target: SemanticIdentity | None,
    invocation: bool,
) -> None:
    """Persist alias evidence without leaking an adjacent implementation body.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Disposable root and backend database directory.
    backend_name : str
        Structural backend under test.
    target : codira.models.SemanticIdentity | None
        Exact identity or unresolved target case.
    invocation : bool
        Whether a path-validated preprocessor invocation is available.

    Returns
    -------
    None
        Alias source is exactly the invocation or omitted, never an adjacent body.
    """
    source = b"ALIAS(alias, implementation) { return implementation(); }\n"
    path = tmp_path / "src" / "main.c"
    provenance = _alias_provenance(source, target, invocation=invocation)
    prototype = CompilerObservedCallableProvenanceV3(
        origin="macro_replacement",
        role="prototype",
        source_sha256=hashlib.sha256(source).hexdigest(),
        context_identity="a" * 64,
        receipt_namespace="example.compiler.callable.v1",
        receipt_json=json.dumps(
            {"callable": {"name": "foo", "usr": "opaque:foo"}},
            sort_keys=True,
            separators=(",", ":"),
        ),
    )
    overload = OverloadArtifact(
        stable_id="callable:foo:prototype:1",
        parent_stable_id="callable:foo",
        ordinal=1,
        signature="int foo(void)",
        lineno=1,
        end_lineno=None,
        docstring=None,
        generated=prototype,
    )
    backend = SQLiteIndexBackend() if backend_name == "sqlite" else DuckDBIndexBackend()
    backend.initialize(tmp_path)
    session = backend.begin_index_session(tmp_path)
    try:
        session.prepare(full=True, indexed_paths=[str(path)], deleted_paths=[])
        session.persist_analysis(
            _request(tmp_path, path, source, provenance, overloads=(overload,))
        )
        session.rebuild_derived_indexes()
        session.commit()
    except BaseException:
        session.abort()
        raise
    finally:
        session.close()

    if isinstance(backend, SQLiteIndexBackend):
        sqlite_connection = backend.open_connection(tmp_path)
        try:
            rows = sqlite_connection.execute(
                "SELECT stable_id, payload FROM artifact_provenance "
                "WHERE stable_id IN (?, ?)",
                ("callable:foo", "callable:foo:prototype:1"),
            ).fetchall()
        finally:
            backend.close_connection(sqlite_connection)
    else:
        duckdb_connection = backend.open_connection(tmp_path)
        try:
            rows = duckdb_connection.execute(
                "SELECT stable_id, payload FROM artifact_provenance "
                "WHERE stable_id IN (?, ?)",
                ("callable:foo", "callable:foo:prototype:1"),
            ).fetchall()
        finally:
            backend.close_connection(duckdb_connection)
    assert len(rows) == 2
    payloads = {
        str(stable_id): generated_provenance_payload(str(payload))
        for stable_id, payload in rows
    }
    stored = payloads["callable:foo"]
    stored_prototype = payloads["callable:foo:prototype:1"]
    expected_target = None if target is None else asdict(target)
    assert stored["format_version"] == 3
    assert stored["role"] == "alias"
    assert stored["alias_target_identity"] == expected_target
    assert stored["linkage_name"] == "f"
    assert "tokens" not in stored and "parameter_types" not in stored
    assert stored_prototype["format_version"] == 3
    assert stored_prototype["role"] == "prototype"
    assert stored_prototype["alias_target_identity"] is None

    query_result: dict[str, object] = {}
    query_result.update(
        file="src/main.c",
        start_line=1,
        end_line=1,
        source=source.decode("utf-8"),
    )
    from codira.query.evidence import _verify_observed_invocation

    _verify_observed_invocation(tmp_path, path, stored)
    _attach_generated_evidence(query_result, stored, [], source)
    assert query_result["source_kind"] == "compiler_generated"
    assert query_result["compiler_observed_alias"] == {
        "target_identity": expected_target,
        "linkage_name": "f",
    }
    assert "invocation_source" not in query_result
    if invocation:
        assert query_result["source"] == "ALIAS(alias, implementation)"
        assert query_result["start_line"] == query_result["end_line"] == 1
    else:
        assert "source" not in query_result
        assert "start_line" not in query_result
        assert "end_line" not in query_result


@pytest.mark.parametrize(
    ("mutation", "expected_message"),
    [
        ("incomplete_identity", "invalid observed alias target identity"),
        ("facts_on_definition", "alias target and linkage facts require alias role"),
        ("unknown_field", "unsupported compiler-observed provenance fields or version"),
    ],
)
def test_compiler_observed_v3_alias_rejects_malformed_contract(
    mutation: str,
    expected_message: str,
) -> None:
    """Reject malformed v3 fields without relaxing the v1/v2 contracts.

    Parameters
    ----------
    mutation : str
        Invalid payload mutation to apply.
    expected_message : str
        Stable validator diagnostic expected for the malformed field.

    Returns
    -------
    None
        Malformed alias evidence is rejected at the shared validation boundary.
    """
    payload = asdict(
        _alias_provenance(
            b"ALIAS(alias, implementation);\n",
            SemanticIdentity("opaque.test.v1", "callable:implementation"),
        )
    )
    if mutation == "incomplete_identity":
        payload["alias_target_identity"] = {"namespace": "opaque.test.v1"}
    elif mutation == "facts_on_definition":
        payload["role"] = "definition"
    else:
        payload["unknown"] = True
    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"))

    with pytest.raises(ValueError, match=expected_message):
        generated_provenance_payload(serialized)


def test_cli_and_mcp_render_alias_evidence_without_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Render an unresolved alias response when the source fields are omitted.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Existing root used for the MCP adapter envelope.
    monkeypatch : pytest.MonkeyPatch
        Replace the query boundary with an alias result lacking source fields.
    capsys : pytest.CaptureFixture[str]
        Capture the public CLI JSON response.

    Returns
    -------
    None
        CLI and MCP consumers accept the documented optional source and range.
    """
    import codira.cli_queries as cli_queries
    import codira.mcp.adapter as mcp_adapter_module
    import codira.query.evidence as evidence_module
    from codira.mcp.adapter import MCPAdapter

    result: dict[str, object] = {
        "identity": "sym:alias",
        "file": "src/main.c",
        "source_kind": "compiler_generated",
        "compiler_observed_alias": {
            "target_identity": None,
            "linkage_name": "f",
        },
    }
    assert "source" not in result
    assert "start_line" not in result
    assert "end_line" not in result
    monkeypatch.setattr(
        evidence_module, "expand_symbol", lambda *args, **kwargs: result
    )
    monkeypatch.setattr(cli_queries, "_ensure_index", lambda root: None)
    monkeypatch.setattr(
        cli_queries, "_emit_json", lambda value: print(json.dumps(value))
    )
    cli_arguments = Namespace(identity="sym:alias", limit=10)
    assert cli_queries._run_evidence_command(cli_arguments, tmp_path) == 0
    cli_result = json.loads(capsys.readouterr().out)
    assert cli_result == result

    monkeypatch.setattr(
        mcp_adapter_module, "expand_symbol", lambda *args, **kwargs: result
    )
    mcp_response = MCPAdapter(tmp_path).symbol_evidence("sym:alias")
    assert mcp_response["result"] == result
    json.dumps(mcp_response)


def test_query_evidence_checks_observed_invocation_bytes_when_available(
    tmp_path: Path,
) -> None:
    """Reject compiler invocation text that does not match the current source.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Disposable root containing the indexed source file.

    Returns
    -------
    None
        Matching event text is accepted and edited source is rejected.
    """
    from codira.query.evidence import _verify_observed_invocation

    source = b"GENERATE(foo);\n"
    path = tmp_path / "src" / "main.c"
    path.parent.mkdir()
    path.write_bytes(source)
    payload = generated_provenance_payload(
        json.dumps(asdict(_provenance(source)), sort_keys=True, separators=(",", ":"))
    )

    _verify_observed_invocation(tmp_path, path, payload)
    path.write_bytes(b"ALTERED(foo);\n")
    with pytest.raises(ValueError, match="source changed"):
        _verify_observed_invocation(
            tmp_path,
            path,
            payload,
        )
    path.write_bytes(source)
    mismatched = asdict(_provenance(source))
    mismatched["invocation"]["text"] = "GENERATE(bar)"
    mismatched_payload = generated_provenance_payload(
        json.dumps(mismatched, sort_keys=True, separators=(",", ":"))
    )
    with pytest.raises(ValueError, match="does not match source bytes"):
        _verify_observed_invocation(tmp_path, path, mismatched_payload)


def test_compiler_generated_evidence_keeps_generic_source_kind() -> None:
    """Expose compiler observations without claiming reconstructed macro source.

    Parameters
    ----------
    None

    Returns
    -------
    None
        V2 evidence is labeled compiler-generated and never source-sliced.
    """
    source = b"GENERATE(foo);\n"
    payload = generated_provenance_payload(
        json.dumps(asdict(_provenance(source)), sort_keys=True, separators=(",", ":"))
    )
    result: dict[str, object] = {"source": "int foo(void);"}

    _attach_generated_evidence(result, payload, [], source)

    assert result["source_kind"] == "compiler_generated"
    assert result["source"] == "int foo(void);"
    assert "invocation_source" not in result
    assert result["compiler_observed_invocation"] == payload["invocation"]


def test_context_identity_roundtrips_beyond_arbitrary_short_limit() -> None:
    """Preserve a full analyzer input fingerprint as an opaque JSON identity.

    Parameters
    ----------
    None

    Returns
    -------
    None
        A context longer than 512 characters remains byte-for-byte unchanged.
    """
    source = b"GENERATE(foo);\n"
    context = json.dumps(
        {"include_context": "x" * 600},
        sort_keys=True,
        separators=(",", ":"),
    )
    payload = generated_provenance_payload(
        json.dumps(
            asdict(_provenance(source, context_identity=context)),
            sort_keys=True,
            separators=(",", ":"),
        )
    )

    assert len(context) > 512
    assert payload["context_identity"] == context


@pytest.mark.parametrize(
    "mutation",
    [
        "unanchored_invocation",
        "noncanonical_receipt",
        "nonfinite_receipt",
        "deep_receipt",
        "oversized_receipt",
    ],
)
def test_invalid_compiler_observed_provenance_is_rejected(mutation: str) -> None:
    """Reject unanchored events and unsafe or noncanonical opaque receipts.

    Parameters
    ----------
    mutation : str
        Deliberately invalid compiler-observed record mutation.

    Returns
    -------
    None
        Invalid v2 evidence cannot pass the persistent-payload validator.
    """
    source = b"GENERATE(foo);\n"
    payload = asdict(_provenance(source))
    if mutation == "unanchored_invocation":
        payload["expansion_location"]["byte_offset"] = 20
    elif mutation == "noncanonical_receipt":
        payload["receipt_json"] = '{"z":1, "a":2}'
    elif mutation == "nonfinite_receipt":
        payload["receipt_json"] = '{"value":NaN}'
    elif mutation == "deep_receipt":
        value: object = None
        for _ in range(18):
            value = {"nested": value}
        payload["receipt_json"] = json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
        )
    else:
        payload["receipt_json"] = json.dumps(
            {"padding": "x" * (64 * 1024)},
            sort_keys=True,
            separators=(",", ":"),
        )
    with pytest.raises(ValueError):
        generated_provenance_payload(
            json.dumps(payload, sort_keys=True, separators=(",", ":"))
        )
