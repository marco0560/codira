"""Tests for portable source-authored Clang parity qualification."""

import hashlib
import json
from dataclasses import asdict
from pathlib import Path
from typing import cast

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
    SemanticIdentity,
)
from scripts.clang_parity_qualification import (
    JSONValue,
    OracleCase,
    OracleDocument,
    _assert_database_backend_identity,
    audit_freeze,
    capture_freeze,
    export_database_snapshot,
    grade_snapshot,
    load_oracle,
    load_public_constant,
)

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "clang_parity_qualification_r1"


def test_database_snapshot_rejects_mislabeled_backend(tmp_path: Path) -> None:
    """Reject a DuckDB label for a SQLite index database.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary directory for the persisted metadata and database marker.

    Returns
    -------
    None
        The test passes when mismatched persisted backend metadata is rejected.
    """
    database = tmp_path / "index.duckdb"
    database.write_bytes(b"database marker")
    (tmp_path / "metadata.json").write_text(
        json.dumps({"backend_name": "sqlite"}), encoding="utf-8"
    )

    with pytest.raises(ValueError, match="does not match persisted backend"):
        _assert_database_backend_identity("duckdb", database)


def test_source_authored_oracle_preserves_qualified_overloads() -> None:
    """Load source cases while preserving qualified C++ overload identities.

    Parameters
    ----------
    None

    Returns
    -------
    None
        Assertions fail directly when the source oracle loses an overload.
    """
    oracle = load_oracle(FIXTURE_ROOT / "source-oracle.json", FIXTURE_ROOT)

    overloads = [
        fact
        for fact in oracle.cases["parity_cpp.cpp"].facts["callables"]
        if fact.get("name") == "parity::choose"
    ]

    assert [fact["return_type"] for fact in overloads] == ["int", "double"]
    assert [fact["definition_line"] for fact in overloads] == [33, 37]
    pending_generated = oracle.cases["parity_cpp.cpp"].pending_facts["callables"][0]
    assert pending_generated["generated_invocation_span"] == [941, 982]


def test_source_authored_oracle_rejects_out_of_range_fact_line(tmp_path: Path) -> None:
    """Reject source locations that do not exist in the fixture file.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary directory for the malformed source oracle.

    Returns
    -------
    None
        The test passes when oracle loading raises the expected error.
    """
    oracle_path = tmp_path / "oracle.json"
    oracle_path.write_text(
        json.dumps(
            {
                "oracle_version": 1,
                "source_authored_oracle": True,
                "cases": {
                    "parity_c.c": {
                        "language": "c",
                        "callables": [
                            {"kind": "function", "name": "f", "definition_line": 999}
                        ],
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="outside parity_c.c"):
        load_oracle(oracle_path, FIXTURE_ROOT)


def test_grader_requires_exact_qualified_names_and_unresolved_exact_calls() -> None:
    """Keep fully qualified names and unresolved-call state in the oracle.

    Parameters
    ----------
    None

    Returns
    -------
    None
        Assertions verify exact call resolution and qualified-name behavior.
    """
    case = OracleCase(
        source="sample.cpp",
        language="cpp",
        facts={
            "callables": ({"kind": "function", "name": "ns::choose", "line": 7},),
            "calls": (
                {"target": "ns::external", "resolution": "external_or_unindexed"},
            ),
        },
    )
    oracle = OracleDocument({"sample.cpp": case})
    snapshot: dict[str, JSONValue] = cast(
        "dict[str, JSONValue]",
        {
            "snapshot_version": 1,
            "backend": "sqlite",
            "cases": {
                "sample.cpp": {
                    "callables": [
                        {"kind": "function", "name": "ns::choose", "line": 7}
                    ],
                    "calls": [
                        {
                            "unresolved_target_qualified_name": "ns::external",
                            "resolved": False,
                            "callee_stable_id": None,
                            "caller_stable_id": "caller-id",
                            "resolution_mode": "exact",
                            "target_identity_namespace": "clang.usr.v1",
                            "target_identity_value": "raw-external-usr",
                        }
                    ],
                }
            },
        },
    )

    assert grade_snapshot(oracle, snapshot) == ()

    cases = cast("dict[str, JSONValue]", snapshot["cases"])
    case_snapshot = cast("dict[str, JSONValue]", cases["sample.cpp"])
    call_rows = cast("list[JSONValue]", case_snapshot["calls"])
    call_row = cast("dict[str, JSONValue]", call_rows[0])
    call_row["callee_stable_id"] = "display-name-match-is-not-an-exact-edge"
    assert len(grade_snapshot(oracle, snapshot)) == 2
    call_row["callee_stable_id"] = None

    callable_rows = cast("list[JSONValue]", case_snapshot["callables"])
    callable_row = cast("dict[str, JSONValue]", callable_rows[0])
    callable_row["name"] = "choose"
    failures = grade_snapshot(oracle, snapshot)
    assert len(failures) == 2
    assert failures[0].expected["name"] == "ns::choose"


def test_freeze_hashes_inputs_and_reads_public_constants(tmp_path: Path) -> None:
    """Freeze bytes and runtime values, then detect changed inputs.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary directory for the frozen source fixture.

    Returns
    -------
    None
        Assertions verify digest stability and mutation detection.
    """
    source = tmp_path / "source.cpp"
    source.write_text("int value;\n", encoding="utf-8")
    expected = capture_freeze(
        {"source": source}, {"profile_schema": load_public_constant("sys:hexversion")}
    )
    assert audit_freeze(expected, expected) == ()

    source.write_text("int updated;\n", encoding="utf-8")
    actual = capture_freeze(
        {"source": source}, {"profile_schema": load_public_constant("sys:hexversion")}
    )
    differences = audit_freeze(expected, actual)
    assert len(differences) == 1
    assert differences[0].key == "files.source"


def test_grader_checks_header_context_and_distinct_identity_observations() -> None:
    """Require held ambiguous headers and distinct semantic identities.

    Parameters
    ----------
    None

    Returns
    -------
    None
        Assertions verify header ownership and identity uniqueness checks.
    """
    oracle = OracleDocument(
        {},
        header_context_requests=(
            {
                "path": "shared.hpp",
                "status": "multiple_owner_translation_units_hold",
                "owners": ["a.cpp", "b.cpp"],
            },
        ),
        identity_invariants=(
            {
                "distinct": ["a.cpp:local", "b.cpp:local"],
                "reason": "internal identities are scoped by owner TU",
            },
        ),
    )
    snapshot: dict[str, JSONValue] = cast(
        "dict[str, JSONValue]",
        {
            "snapshot_version": 1,
            "backend": "duckdb",
            "cases": {},
            "header_context": [
                {
                    "path": "shared.hpp",
                    "status": "multiple_owner_translation_units_hold",
                    "owners": ["a.cpp", "b.cpp"],
                }
            ],
            "identity_observations": {
                "a.cpp:local": "usr-internal-a",
                "b.cpp:local": "usr-internal-b",
            },
        },
    )

    assert [failure.category for failure in grade_snapshot(oracle, snapshot)] == [
        "pending:header_projection"
    ]

    observations = cast("dict[str, JSONValue]", snapshot["identity_observations"])
    observations["b.cpp:local"] = "usr-internal-a"
    failure_categories = {
        failure.category for failure in grade_snapshot(oracle, snapshot)
    }
    assert "identity_invariants" in failure_categories


def test_grader_checks_shared_external_declaration_definition_identity() -> None:
    """Require one exact identity for a declaration and its indexed definition.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The assertion verifies the equality invariant is enforced.
    """
    oracle = OracleDocument(
        {},
        identity_invariants=(
            {
                "equal": [
                    "cross_tu::transform declaration",
                    "cross_tu::transform definition",
                ],
                "reason": "a declaration and definition identify one function",
            },
        ),
    )
    snapshot: dict[str, JSONValue] = cast(
        "dict[str, JSONValue]",
        {
            "snapshot_version": 1,
            "backend": "sqlite",
            "cases": {},
            "identity_observations": {
                "cross_tu::transform declaration": "c:@N@cross_tu@F@transform#I#",
                "cross_tu::transform definition": "c:@N@cross_tu@F@transform#I#",
            },
        },
    )
    assert grade_snapshot(oracle, snapshot) == ()


def test_generated_callable_grades_only_from_validated_compiler_observations() -> None:
    """Require v2 provenance, source spelling, exact identity and receipt context.

    Parameters
    ----------
    None

    Returns
    -------
    None
        A complete compiler-observed record grades without fake provenance keys.
    """
    case = OracleCase(
        source="parity_c.c",
        language="c",
        facts={"callables": ()},
        pending_facts={
            "callables": (
                {
                    "kind": "function",
                    "name": "c_generated_from_macro",
                    "return_type": "int",
                    "parameter_types": [],
                    "returns_value": True,
                    "generated": True,
                    "generated_macro": "PARITY_C_GENERATE",
                    "generated_invocation_text": "PARITY_C_GENERATE(c_generated_from_macro)",
                    "generated_spelling_line": 31,
                    "invocation_line": 32,
                    "generated_invocation_span": [704, 745],
                },
            )
        },
    )
    source = (FIXTURE_ROOT / "parity_c.c").read_bytes()
    source_sha = hashlib.sha256(source).hexdigest()
    invocation_text = "PARITY_C_GENERATE(c_generated_from_macro)"
    context_identity = json.dumps(
        {"include_context": "x" * 600},
        sort_keys=True,
        separators=(",", ":"),
    )
    invocation = CompilerObservedMacroInvocation(
        name="PARITY_C_GENERATE",
        path="parity_c.c",
        byte_range=(704, 745),
        text=invocation_text,
    )
    receipt = {
        "schema": "clang.frontend.callable-observation.v1",
        "context": {
            "profile_identity": "captured-profile",
            "cache_fingerprint": "cache-identity",
            "analyzer_context_identity": context_identity,
            "source_sha256": source_sha,
            "stdout_sha256": "b" * 64,
        },
        "callable": {
            "usr": "c:@F@c_generated_from_macro",
            "kind": "function",
            "name": "c_generated_from_macro",
            "qualified_name": "c_generated_from_macro",
            "decl_kind": "FunctionDecl",
            "signature": "int c_generated_from_macro(void)",
            "function_type": "int (void)",
            "provenance": "macro_argument",
            "is_definition": True,
            "spelling_location": {
                "path": "parity_c.c",
                "line": 32,
                "column": 20,
                "offset": 723,
            },
            "expansion_location": {
                "path": "parity_c.c",
                "line": 32,
                "column": 1,
                "offset": 704,
            },
            "span": {
                "begin": {
                    "spelling": {
                        "path": "parity_c.c",
                        "line": 31,
                        "column": 34,
                        "offset": 672,
                    },
                    "expansion": {
                        "path": "parity_c.c",
                        "line": 32,
                        "column": 1,
                        "offset": 704,
                    },
                    "is_macro": True,
                },
                "end": None,
            },
            "owner_usr": None,
            "owner_location": None,
        },
        "macro_expansion": {
            "name": "PARITY_C_GENERATE",
            "invocation": invocation_text,
            "byte_range": [704, 745],
        },
    }
    provenance = CompilerObservedCallableProvenance(
        origin="macro_argument",
        role="definition",
        source_sha256=source_sha,
        context_identity=context_identity,
        receipt_namespace="clang.frontend.callable-observation.v1",
        receipt_json=json.dumps(receipt, sort_keys=True, separators=(",", ":")),
        spelling_location=CompilerObservedSourceCoordinate("parity_c.c", 723),
        expansion_location=CompilerObservedSourceCoordinate("parity_c.c", 704),
        invocation=invocation,
    )
    validated_provenance = generated_provenance_payload(
        json.dumps(asdict(provenance), sort_keys=True, separators=(",", ":"))
    )
    oracle = OracleDocument({"parity_c.c": case})
    snapshot: dict[str, JSONValue] = cast(
        "dict[str, JSONValue]",
        {
            "snapshot_version": 1,
            "backend": "sqlite",
            "cases": {"parity_c.c": {"source_sha256": source_sha, "callables": []}},
        },
    )

    failures = grade_snapshot(oracle, snapshot)
    assert [failure.category for failure in failures] == ["pending:callables"]

    cases = cast("dict[str, JSONValue]", snapshot["cases"])
    case_snapshot = cast("dict[str, JSONValue]", cases["parity_c.c"])
    callables = cast("list[JSONValue]", case_snapshot["callables"])
    callables.append(
        cast(
            "JSONValue",
            {
                "kind": "function",
                "name": "c_generated_from_macro",
                "return_type": "int",
                "parameter_types": [],
                "returns_value": True,
                "generated": True,
                "generated_invocation_line": 32,
                "source_sha256": source_sha,
                "source_kind": "compiler_generated",
                "outer_analysis_input_fingerprint": context_identity,
                "compiler_identity_ref": "clang.usr.v1:c:@F@c_generated_from_macro",
                "compiler_stdout_sha256": "b" * 64,
                "physical_spelling_location": {
                    "path": "parity_c.c",
                    "line": 31,
                    "column": 34,
                    "byte_offset": 672,
                },
                "generated_provenance": validated_provenance,
            },
        )
    )
    assert grade_snapshot(oracle, snapshot) == ()


@pytest.mark.parametrize("backend_name", ["sqlite", "duckdb"])
def test_backend_snapshot_exports_generated_rows_from_validated_provenance(
    tmp_path: Path, backend_name: str
) -> None:
    """Export source-bound generated evidence from real SQLite and DuckDB rows.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Disposable source repository and backend index root.
    backend_name : str
        First-party structural backend under test.

    Returns
    -------
    None
        Exported callable facts match only the actual strict-v2 payload and rows.
    """
    source = b"#define GENERATE(name) int name(void) { return 0; }\nGENERATE(foo)\n"
    path = tmp_path / "sample.c"
    path.write_bytes(source)
    source_sha = hashlib.sha256(source).hexdigest()
    invocation_text = "GENERATE(foo)"
    invocation_start = source.index(invocation_text.encode("utf-8"))
    invocation_end = invocation_start + len(invocation_text.encode("utf-8"))
    outer_context = json.dumps(
        {"captured_inputs": "x" * 600},
        sort_keys=True,
        separators=(",", ":"),
    )
    stdout_sha = "d" * 64
    usr = "c:@F@foo"
    receipt = {
        "schema": "clang.frontend.callable-observation.v1",
        "context": {
            "profile_identity": "profile-identity",
            "cache_fingerprint": "cache-fingerprint",
            "analyzer_context_identity": outer_context,
            "source_sha256": source_sha,
            "stdout_sha256": stdout_sha,
        },
        "callable": {
            "usr": usr,
            "kind": "function",
            "name": "foo",
            "qualified_name": "foo",
            "decl_kind": "FunctionDecl",
            "signature": "int foo(void)",
            "function_type": "int (void)",
            "provenance": "macro_argument",
            "is_definition": True,
            "spelling_location": {
                "path": "sample.c",
                "line": 2,
                "column": 10,
                "offset": invocation_start + len("GENERATE("),
            },
            "expansion_location": {
                "path": "sample.c",
                "line": 2,
                "column": 1,
                "offset": invocation_start,
            },
            "span": {
                "begin": {
                    "spelling": {
                        "path": "sample.c",
                        "line": 1,
                        "column": 24,
                        "offset": source.index(b"int name"),
                    },
                    "expansion": {
                        "path": "sample.c",
                        "line": 2,
                        "column": 1,
                        "offset": invocation_start,
                    },
                    "is_macro": True,
                },
                "end": None,
            },
            "owner_usr": None,
            "owner_location": None,
        },
        "macro_expansion": {
            "name": "GENERATE",
            "invocation": invocation_text,
            "byte_range": [invocation_start, invocation_end],
        },
    }
    provenance = CompilerObservedCallableProvenance(
        origin="macro_argument",
        role="definition",
        source_sha256=source_sha,
        context_identity=outer_context,
        receipt_namespace="clang.frontend.callable-observation.v1",
        receipt_json=json.dumps(receipt, sort_keys=True, separators=(",", ":")),
        spelling_location=CompilerObservedSourceCoordinate(
            "sample.c", invocation_start + len("GENERATE(")
        ),
        expansion_location=CompilerObservedSourceCoordinate(
            "sample.c", invocation_start
        ),
        invocation=CompilerObservedMacroInvocation(
            name="GENERATE",
            path="sample.c",
            byte_range=(invocation_start, invocation_end),
            text=invocation_text,
        ),
    )
    function = FunctionArtifact(
        name="foo",
        stable_id="clang-callable:foo",
        lineno=2,
        end_lineno=2,
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
        semantic_identity=SemanticIdentity("clang.usr.v1", usr),
    )
    analysis = AnalysisResult(
        source_path=path,
        module=ModuleArtifact("sample", "module:sample", None, 0),
        classes=(),
        functions=(function,),
        declarations=(),
        imports=(),
    )
    backend = SQLiteIndexBackend() if backend_name == "sqlite" else DuckDBIndexBackend()
    backend.initialize(tmp_path)
    session = backend.begin_index_session(tmp_path)
    try:
        session.prepare(full=True, indexed_paths=[str(path)], deleted_paths=[])
        session.persist_analysis(
            BackendPersistAnalysisRequest(
                root=tmp_path,
                file_metadata=FileMetadataSnapshot(
                    path=path,
                    sha256=source_sha,
                    mtime=path.stat().st_mtime,
                    size=len(source),
                    analyzer_name="clang-fixture",
                    analyzer_version="1",
                    analysis_input_fingerprint=outer_context,
                ),
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

    profile_document = tmp_path / "profiles.json"
    profile_document.write_text('{"profiles": []}', encoding="utf-8")
    metadata_path = tmp_path / ".codira" / "metadata.json"
    metadata_path.write_text(
        json.dumps({"backend_name": backend_name}), encoding="utf-8"
    )
    expected = cast(
        "dict[str, JSONValue]",
        {
            "kind": "function",
            "name": "foo",
            "return_type": "int",
            "parameter_types": [],
            "returns_value": True,
            "generated": True,
            "generated_macro": "GENERATE",
            "generated_invocation_text": invocation_text,
            "generated_spelling_line": 1,
            "invocation_line": 2,
            "generated_invocation_span": [invocation_start, invocation_end],
        },
    )
    oracle = OracleDocument(
        {
            "sample.c": OracleCase(
                source="sample.c",
                language="c",
                facts={"callables": ()},
                pending_facts={"callables": (expected,)},
            )
        }
    )
    database_path = (
        tmp_path
        / ".codira"
        / ("index.db" if backend_name == "sqlite" else "index.duckdb")
    )
    snapshot = export_database_snapshot(
        backend_name, database_path, tmp_path, oracle, profile_document
    )
    assert grade_snapshot(oracle, snapshot) == ()
    cases = cast("dict[str, JSONValue]", snapshot["cases"])
    case_snapshot = cast("dict[str, JSONValue]", cases["sample.c"])
    callables = cast("list[JSONValue]", case_snapshot["callables"])
    observed = cast("dict[str, JSONValue]", callables[0])
    assert observed["source_kind"] == "compiler_generated"
    assert observed["compiler_identity_ref"] == f"clang.usr.v1:{usr}"
    assert observed["compiler_stdout_sha256"] == stdout_sha
    stored = cast("dict[str, JSONValue]", observed["generated_provenance"])
    assert stored["context_identity"] == outer_context
    assert "tokens" not in stored
