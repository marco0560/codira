"""Exercise truthful compiler-observed generated callable evidence.

Parameters
----------
None

Returns
-------
None
    Version-two compiler evidence remains distinct from token-derived v1 data.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from typing import TYPE_CHECKING

import pytest
from codira_backend_duckdb import DuckDBIndexBackend
from codira_backend_sqlite import SQLiteIndexBackend

from codira.contracts import BackendPersistAnalysisRequest, EmbeddingIndexingPolicy
from codira.generated import (
    CompilerObservedCallableProvenance,
    CompilerObservedMacroInvocation,
    CompilerObservedSourceCoordinate,
    generated_provenance_payload,
)
from codira.models import (
    AnalysisResult,
    FileMetadataSnapshot,
    FunctionArtifact,
    ModuleArtifact,
)
from codira.query.evidence import _attach_generated_evidence

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
    provenance: CompilerObservedCallableProvenance,
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
        Version-two generated provenance attached to the callable.

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
        ),
        analysis=analysis,
        embedding_indexing=EmbeddingIndexingPolicy(object_types=frozenset()),
        defer_embeddings=True,
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
