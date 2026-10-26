"""Tests for portable source-authored Clang parity qualification."""

import json
from pathlib import Path
from typing import cast

import pytest

from scripts.clang_parity_qualification import (
    JSONValue,
    OracleCase,
    OracleDocument,
    _assert_database_backend_identity,
    audit_freeze,
    capture_freeze,
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


def test_pending_generated_callable_is_visible_and_can_match_provenance() -> None:
    """Report the generated-callable gap until its compiler-origin DTO exists.

    Parameters
    ----------
    None

    Returns
    -------
    None
        Assertions verify pending facts remain explicit and gradeable.
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
                    "generated_spelling_line": 31,
                    "invocation_line": 32,
                    "generated_invocation_span": [704, 745],
                },
            )
        },
    )
    source_sha = "frozen-source-sha"
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
                "generated_provenance": {
                    "origin": "compiler_macro_expansion",
                    "role": "definition",
                    "invocation_span": [704, 745],
                    "source_sha256": source_sha,
                    "context_identity": "compile-profile-identity",
                    "physical_spelling_location": {
                        "path": "parity_c.c",
                        "line": 31,
                        "column": 1,
                    },
                    "compiler_identity_ref": "clang.usr.v1:c:@F@c_generated_from_macro",
                },
            },
        )
    )
    assert grade_snapshot(oracle, snapshot) == ()
