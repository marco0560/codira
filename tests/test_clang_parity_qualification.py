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
    _validate_v3_alias_identity,
    audit_freeze,
    capture_freeze,
    export_database_snapshot,
    grade_snapshot,
    load_oracle,
    load_public_constant,
)
from scripts.grade_clang_native_linkage import grade_native_linkage

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


def test_generated_alias_oracle_binds_labels_and_alias_target_to_source() -> None:
    """Keep asm labels, alias operands, and generated declaration roles separate.

    Parameters
    ----------
    None

    Returns
    -------
    None
        Source-authored facts preserve physical spelling and qualified names.
    """
    oracle = load_oracle(FIXTURE_ROOT / "source-oracle.json", FIXTURE_ROOT)
    case = oracle.cases["generated_alias.cpp"]
    declarations = case.facts["generated_declarations"]
    by_role = {str(row["role"]): row for row in declarations}

    assert by_role["prototype"]["name"] == "alias_case::impl_f"
    assert by_role["definition"]["linkage_name"] == "f"
    assert by_role["prototype"]["has_body"] is False
    assert by_role["definition"]["has_body"] is True
    assert by_role["definition"]["explicit_linkage_label"] == "f"
    assert by_role["definition"]["linkage_label_inherited"] is True
    assert by_role["alias"]["has_body"] is False
    assert by_role["alias"]["name"] == "alias_case::f"
    assert by_role["alias"]["alias_target_symbol"] == "f"
    assert by_role["alias"]["alias_target_identity_reference"] == (
        "generated_alias::alias target"
    )
    assert by_role["alias"].get("linkage_name") is None
    assert any(
        invariant.get("equal")
        == [
            "generated_alias::implementation prototype compiler identity",
            "generated_alias::implementation definition compiler identity",
        ]
        for invariant in oracle.identity_invariants
    )


def test_grader_checks_v3_alias_target_identity_without_name_inference() -> None:
    """Require exact alias identity relations even when names look compatible.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The grader accepts unique compiler identities and rejects missing or
        conflicting alias-target identities without deriving one from spelling.
    """
    loaded = load_oracle(FIXTURE_ROOT / "source-oracle.json", FIXTURE_ROOT)
    case = loaded.cases["generated_alias.cpp"]
    expected_rows = case.facts["generated_declarations"]
    observations = []
    implementation_identity: dict[str, JSONValue] = {
        "namespace": "clang.usr.v1",
        "value": "raw-impl-usr",
    }
    alias_identity: dict[str, JSONValue] = {
        "namespace": "clang.usr.v1",
        "value": "raw-alias-usr",
    }
    for expected in expected_rows:
        observed = {
            key: value
            for key, value in expected.items()
            if key
            not in {
                "source_evidence",
                "identity_reference",
                "alias_target_identity_reference",
            }
        }
        role = observed["role"]
        observed["semantic_identity"] = (
            alias_identity if role == "alias" else implementation_identity
        )
        observed["compiler_identity"] = implementation_identity
        if role == "alias":
            observed["alias_target_identity"] = implementation_identity
        if role == "prototype":
            observed["semantic_identity"] = None
        observations.append(observed)
    declaration_only_case = OracleCase(
        source=case.source,
        language=case.language,
        facts={"generated_declarations": expected_rows},
    )
    oracle = OracleDocument(
        {"generated_alias.cpp": declaration_only_case},
        identity_invariants=(
            {
                "equal": [
                    "generated_alias::implementation prototype compiler identity",
                    "generated_alias::implementation definition compiler identity",
                ],
                "reason": "the compiler assigns one identity to prototype and definition",
            },
            {
                "equal": [
                    "generated_alias::alias target",
                    "generated_alias::implementation semantic identity",
                ],
                "reason": "the exact alias target resolves to the implementation",
            },
            {
                "equal": [
                    "generated_alias::implementation definition compiler identity",
                    "generated_alias::implementation semantic identity",
                ],
                "reason": "the implementation native identity is persisted without rewriting",
            },
        ),
    )
    snapshot: dict[str, JSONValue] = cast(
        "dict[str, JSONValue]",
        {
            "snapshot_version": 1,
            "backend": "sqlite",
            "cases": {"generated_alias.cpp": {"generated_declarations": observations}},
            "header_context": [],
        },
    )

    assert grade_snapshot(oracle, snapshot) == ()

    snapshot_cases = cast("dict[str, JSONValue]", snapshot["cases"])
    case_snapshot = cast("dict[str, JSONValue]", snapshot_cases["generated_alias.cpp"])
    observed_rows = cast("list[JSONValue]", case_snapshot["generated_declarations"])
    alias_row = next(
        cast("dict[str, JSONValue]", row)
        for row in observed_rows
        if cast("dict[str, JSONValue]", row).get("role") == "alias"
    )
    for binding_status in ("unresolved", "ambiguous", None):
        alias_row["alias_binding_status"] = binding_status
        alias_row["alias_target_identity"] = None
        failures = grade_snapshot(oracle, snapshot)
        assert any(failure.category == "generated_declarations" for failure in failures)
        assert any(failure.category == "identity_invariants" for failure in failures)
    alias_row["alias_binding_status"] = "resolved"
    alias_row["alias_target_identity"] = {
        "namespace": "clang.usr.v1",
        "value": "display-name-derived-target-is-not-the-compiler-identity",
    }
    failures = grade_snapshot(oracle, snapshot)
    assert any(failure.category == "identity_invariants" for failure in failures)


def test_v3_alias_identity_must_match_raw_compiler_target_usr() -> None:
    """Bind normalized alias identity to the opaque native target observation.

    Parameters
    ----------
    None

    Returns
    -------
    None
        Mismatched compiler evidence is rejected even when the linker spelling
        remains identical.
    """
    target_usr = "c:@N@alias_case@F@impl_f#d#"
    _validate_v3_alias_identity(
        {
            "role": "alias",
            "alias_target_identity": {
                "namespace": "clang.usr.v1",
                "value": target_usr,
            },
        },
        {
            "alias_binding_status": "resolved",
            "alias_target_usr": target_usr,
            "alias_target_symbol": "f",
        },
        "alias-stable-id",
    )
    with pytest.raises(ValueError, match="raw compiler target USR"):
        _validate_v3_alias_identity(
            {
                "role": "alias",
                "alias_target_identity": {
                    "namespace": "clang.usr.v1",
                    "value": "different-usr",
                },
            },
            {
                "alias_binding_status": "resolved",
                "alias_target_usr": target_usr,
                "alias_target_symbol": "f",
            },
            "alias-stable-id",
        )
    for status in ("unresolved", "ambiguous"):
        _validate_v3_alias_identity(
            {"role": "alias", "alias_target_identity": None},
            {
                "alias_binding_status": status,
                "alias_target_usr": None,
                "alias_target_symbol": "missing",
            },
            "alias-stable-id",
        )


def test_translation_unit_identity_oracles_keep_scoping_and_linkage_distinct() -> None:
    """Keep internal and UniqueExternal identities scoped by full TU path.

    Parameters
    ----------
    None

    Returns
    -------
    None
        Source facts request the collision fix and ordinary external control.
    """
    oracle = load_oracle(FIXTURE_ROOT / "source-oracle.json", FIXTURE_ROOT)
    anonymous_invariant = next(
        row
        for row in oracle.identity_invariants
        if row.get("distinct")
        and row["distinct"]
        == ["anonymous_a.cpp:local_target", "anonymous_b.cpp:local_target"]
    )
    assert "translation-unit local" in str(anonymous_invariant["reason"])
    unique_external_invariant = next(
        row
        for row in oracle.identity_invariants
        if row.get("distinct")
        == [
            "same-name-a/foo.cpp:unique_external_collision",
            "same-name-b/foo.cpp:unique_external_collision",
        ]
    )
    shared_external_invariant = next(
        row
        for row in oracle.identity_invariants
        if row.get("equal")
        == [
            "same-name-a/foo.cpp:external_shared",
            "same-name-b/foo.cpp:external_shared",
        ]
    )
    assert "full main translation-unit path" in str(unique_external_invariant["reason"])
    assert "ordinary external linkage" in str(shared_external_invariant["reason"])
    anonymous_cases = [
        oracle.cases[source] for source in ("anonymous_a.cpp", "anonymous_b.cpp")
    ]
    assert all(
        "linkage" not in callable_fact
        for case in anonymous_cases
        for callable_fact in case.facts["callables"]
        if callable_fact["name"] == "(anonymous namespace)::local_target"
    )
    oracle_payload = json.loads(
        (FIXTURE_ROOT / "source-oracle.json").read_text(encoding="utf-8")
    )
    assert len(oracle_payload["native_linkage_requests"]) == 2
    unique_external_references = cast(
        "list[JSONValue]", unique_external_invariant["distinct"]
    )
    assert {
        request["source"]
        for request in oracle.identity_observation_requests
        if request["reference"] in unique_external_references
    } == {"same-name-a/foo.cpp", "same-name-b/foo.cpp"}


def test_native_linkage_supplement_joins_exact_db_identity(
    tmp_path: Path,
) -> None:
    """Join raw internal linkage to the independently exported DB identity.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary directory for source, native-response, and backend evidence.

    Returns
    -------
    None
        The test passes when native identity and both persisted identities match.
    """
    requests: list[dict[str, object]] = []
    profiles: list[dict[str, object]] = []
    identities: dict[str, str] = {}
    namespaces: dict[str, str] = {}
    for suffix, value in (("a", "usr-a"), ("b", "usr-b")):
        source = tmp_path / f"anonymous_{suffix}.cpp"
        source.write_text("void local_target() {}\n", encoding="utf-8")
        source_path = str(source.resolve())
        source_sha256 = hashlib.sha256(source.read_bytes()).hexdigest()
        reference = f"anonymous_{suffix}.cpp:local_target"
        stdout = tmp_path / f"{suffix}.stdout"
        response = {
            "capture_mode": "source_relevant",
            "tool_return_code": 0,
            "translation_unit_file": source_path,
            "declarations": [
                {
                    "qualified_name": "(anonymous namespace)::local_target",
                    "is_definition": True,
                    "linkage_kind": "internal",
                    "identity": {"usr": value},
                    "location": {"expansion": {"line": 1, "path": source_path}},
                }
            ],
        }
        stdout.write_text(json.dumps(response), encoding="utf-8")
        profiles.append(
            {
                "source": f"anonymous_{suffix}.cpp",
                "source_path": source_path,
                "source_sha256": source_sha256,
                "stdout_path": str(stdout),
                "stdout_sha256": hashlib.sha256(stdout.read_bytes()).hexdigest(),
            }
        )
        requests.append(
            {
                "reference": reference,
                "source": f"anonymous_{suffix}.cpp",
                "name": "(anonymous namespace)::local_target",
                "definition_line": 1,
                "linkage_kind": "internal",
                "identity_observation_reference": reference,
            }
        )
        identities[reference] = value
        namespaces[reference] = "clang.usr.v1"
    report = grade_native_linkage(
        {"native_linkage_requests": requests},
        {"profiles": profiles},
        [
            {
                "backend": backend,
                "cases": {
                    profile["source"]: {"source_sha256": profile["source_sha256"]}
                    for profile in profiles
                },
                "identity_observations": identities,
                "identity_namespace_observations": namespaces,
            }
            for backend in ("sqlite", "duckdb")
        ],
        tmp_path,
    )
    assert report["result"] == "passed"
    assert report["assertion_count"] == 2


def test_native_linkage_supplement_rejects_identity_from_another_target(
    tmp_path: Path,
) -> None:
    """Reject native evidence whose USR differs from persisted DB identity.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary directory holding authored source and raw compiler responses.

    Returns
    -------
    None
        The test passes when the supplement rejects a mismatched identity.
    """
    source = tmp_path / "anonymous_a.cpp"
    source.write_text("void local_target() {}\n", encoding="utf-8")
    source_path = str(source.resolve())
    stdout = tmp_path / "a.stdout"
    stdout.write_text(
        json.dumps(
            {
                "capture_mode": "source_relevant",
                "tool_return_code": 0,
                "translation_unit_file": source_path,
                "declarations": [
                    {
                        "qualified_name": "(anonymous namespace)::local_target",
                        "is_definition": True,
                        "linkage_kind": "internal",
                        "identity": {"usr": "native-usr"},
                        "location": {"expansion": {"line": 1, "path": source_path}},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    reference = "anonymous_a.cpp:local_target"
    request = {
        "reference": reference,
        "source": "anonymous_a.cpp",
        "name": "(anonymous namespace)::local_target",
        "definition_line": 1,
        "linkage_kind": "internal",
        "identity_observation_reference": reference,
    }
    profile = {
        "source": "anonymous_a.cpp",
        "source_path": source_path,
        "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "stdout_path": str(stdout),
        "stdout_sha256": hashlib.sha256(stdout.read_bytes()).hexdigest(),
    }
    snapshots = [
        {
            "backend": backend,
            "cases": {"anonymous_a.cpp": {"source_sha256": profile["source_sha256"]}},
            "identity_observations": {reference: "different-usr"},
            "identity_namespace_observations": {reference: "clang.usr.v1"},
        }
        for backend in ("sqlite", "duckdb")
    ]
    with pytest.raises(ValueError, match="does not equal persisted DB identity"):
        grade_native_linkage(
            {"native_linkage_requests": [request]},
            {"profiles": [profile]},
            snapshots,
            tmp_path,
        )

    snapshot_cases = cast("dict[str, dict[str, str]]", snapshots[0]["cases"])
    snapshot_cases["anonymous_a.cpp"]["source_sha256"] = "wrong-source"
    with pytest.raises(ValueError, match="snapshot source digest differs"):
        grade_native_linkage(
            {"native_linkage_requests": [request]},
            {"profiles": [profile]},
            snapshots,
            tmp_path,
        )

    source_a = (FIXTURE_ROOT / "same-name-a/foo.cpp").read_bytes()
    source_b = (FIXTURE_ROOT / "same-name-b/foo.cpp").read_bytes()
    assert source_a == (
        b"namespace { struct HiddenType {}; }\n"
        b"void unique_external_collision(HiddenType value) { (void)value; }\n"
        b"int external_shared(void) { return 11; }\n"
    )
    assert source_b == source_a.replace(b"return 11", b"return 22")


def test_generated_declaration_oracle_rejects_changed_asm_source(
    tmp_path: Path,
) -> None:
    """Detect a changed asm label expression before grading analyzer output.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Disposable copy of the source-authored oracle and fixture tree.

    Returns
    -------
    None
        A changed macro expression invalidates the authored expectation.
    """
    import shutil

    fixture_root = tmp_path / "fixture"
    shutil.copytree(FIXTURE_ROOT, fixture_root)
    source = fixture_root / "generated_alias.cpp"
    source.write_text(
        source.read_text(encoding="utf-8").replace("asm(#N)", "asm(#M)"),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="expression differs from source"):
        load_oracle(fixture_root / "source-oracle.json", fixture_root)


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
    generated_rows = cast("list[JSONValue]", case_snapshot["generated_declarations"])
    assert len(generated_rows) == 1
    generated_definition = cast("dict[str, JSONValue]", generated_rows[0])
    assert generated_definition["role"] == "definition"
    assert generated_definition["compiler_identity"] == {
        "namespace": "clang.usr.v1",
        "value": usr,
    }


@pytest.mark.parametrize("backend_name", ["sqlite", "duckdb"])
def test_v3_alias_database_row_is_callable_without_a_body(
    tmp_path: Path, backend_name: str
) -> None:
    """Project a persisted V3 alias declaration as a bodyless callable.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Disposable source repository and backend index root.
    backend_name : str
        First-party structural backend under test.

    Returns
    -------
    None
        The database alias is visible as a callable and does not imply a body.
    """
    import sqlite3

    import duckdb

    source = b"#define ALIAS(name) int name(int value)\nALIAS(alias)\n"
    path = tmp_path / "sample.cpp"
    path.write_bytes(source)
    source_sha = hashlib.sha256(source).hexdigest()
    source_path = str(path.resolve())
    context_identity = json.dumps(
        {"source_sha256": source_sha, "configuration": "alias-fixture"},
        sort_keys=True,
        separators=(",", ":"),
    )
    invocation = "ALIAS(alias)"
    invocation_start = source.index(invocation.encode("utf-8"))
    invocation_end = invocation_start + len(invocation.encode("utf-8"))
    alias_usr = "c:@F@alias#I#"
    target_usr = "c:@F@target#I#"
    stdout_sha = "a" * 64
    receipt = {
        "schema": "clang.frontend.callable-observation.v1",
        "context": {
            "profile_identity": "alias-profile",
            "cache_fingerprint": "alias-cache",
            "analyzer_context_identity": context_identity,
            "source_sha256": source_sha,
            "stdout_sha256": stdout_sha,
        },
        "callable": {
            "usr": alias_usr,
            "kind": "function",
            "name": "alias",
            "qualified_name": "alias",
            "decl_kind": "Function",
            "signature": "int alias(int value)",
            "function_type": "int (int)",
            "provenance": "macro_argument",
            "is_definition": True,
            "native_observation": {
                "alias_binding_status": "resolved",
                "alias_target_symbol": "target",
                "alias_target_usr": target_usr,
                "explicit_linkage_label": None,
                "has_body": False,
                "linkage_kind": "external",
                "linkage_label_inherited": None,
                "linker_symbol": "alias",
                "signature_kind": "derived_display_only",
            },
        },
        "macro_expansion": {
            "name": "ALIAS",
            "invocation": invocation,
            "byte_range": [invocation_start, invocation_end],
        },
    }
    receipt_json = json.dumps(receipt, sort_keys=True, separators=(",", ":"))
    payload = {
        "variant": "compiler_observed",
        "format_version": 3,
        "origin": "macro_argument",
        "role": "alias",
        "source_sha256": source_sha,
        "context_identity": context_identity,
        "spelling_location": {
            "path": "sample.cpp",
            "byte_offset": invocation_start + len("ALIAS("),
        },
        "expansion_location": {
            "path": "sample.cpp",
            "byte_offset": invocation_start,
        },
        "invocation": {
            "name": "ALIAS",
            "path": "sample.cpp",
            "byte_range": [invocation_start, invocation_end],
            "text": invocation,
        },
        "receipt_namespace": "clang.frontend.callable-observation.v1",
        "receipt_json": receipt_json,
        "alias_target_identity": {
            "namespace": "clang.usr.v1",
            "value": target_usr,
        },
        "linkage_name": "alias",
    }
    function = FunctionArtifact(
        name="alias",
        stable_id="cpp:function:sample.cpp:alias",
        lineno=2,
        end_lineno=None,
        signature="int alias(int value)",
        docstring=None,
        has_docstring=0,
        is_method=0,
        is_public=1,
        parameters=("value",),
        returns_value=0,
        yields_value=0,
        raises=0,
        has_asserts=0,
        decorators=(),
        calls=(),
        callable_refs=(),
        semantic_identity=SemanticIdentity("clang.usr.v1", alias_usr),
    )
    analysis = AnalysisResult(
        source_path=path,
        module=ModuleArtifact("sample", "cpp:module:sample.cpp", None, 0),
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
                    analysis_input_fingerprint=context_identity,
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

    database_path = (
        tmp_path
        / ".codira"
        / ("index.db" if backend_name == "sqlite" else "index.duckdb")
    )
    connection = (
        sqlite3.connect(database_path)
        if backend_name == "sqlite"
        else duckdb.connect(str(database_path))
    )
    try:
        file_row = connection.execute(
            "SELECT id FROM files WHERE path = ?", [source_path]
        ).fetchone()
        assert file_row is not None
        file_id = file_row[0]
        connection.execute(
            "INSERT INTO artifact_provenance(file_id, stable_id, payload) "
            "VALUES (?, ?, ?)",
            [file_id, function.stable_id, json.dumps(payload, sort_keys=True)],
        )
        connection.commit()
    finally:
        connection.close()

    profile_document = tmp_path / "profiles.json"
    profile_document.write_text('{"profiles": []}', encoding="utf-8")
    (tmp_path / ".codira" / "metadata.json").write_text(
        json.dumps({"backend_name": backend_name}), encoding="utf-8"
    )
    oracle = OracleDocument(
        {"sample.cpp": OracleCase(source="sample.cpp", language="cpp", facts={})}
    )
    snapshot = export_database_snapshot(
        backend_name, database_path, tmp_path, oracle, profile_document
    )
    cases = cast("dict[str, JSONValue]", snapshot["cases"])
    case_snapshot = cast("dict[str, JSONValue]", cases["sample.cpp"])
    callables = cast("list[JSONValue]", case_snapshot["callables"])
    assert len(callables) == 1
    alias = cast("dict[str, JSONValue]", callables[0])
    assert alias["name"] == "alias"
    assert alias["returns_value"] is False
    generated_rows = cast("list[JSONValue]", case_snapshot["generated_declarations"])
    assert len(generated_rows) == 1
    assert cast("dict[str, JSONValue]", generated_rows[0])["role"] == "alias"
