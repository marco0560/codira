"""Qualify native C file-scope macro declarations through persistent queries.

Parameters
----------
None

Returns
-------
None
    Pytest exercises source-bound compiler evidence in both structural stores.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import cast

import pytest

from codira_analyzer_c import CAnalyzer
from codira.models import DeclarationArtifact
from tests_support.clang_macro_declaration_qualification import (
    BackendQualificationRequest,
    NativeQualificationCase,
    load_native_case,
    plugin_configuration,
    run_index_and_query,
    write_qualification_receipt,
)


@pytest.fixture(scope="module")
def c_macro_case() -> NativeQualificationCase:
    """Load the durable C source and native profile bound to this fixture.

    Parameters
    ----------
    None

    Returns
    -------
    NativeQualificationCase
        Verified C fixture, profile, helper, and build-receipt binding.

    Raises
    ------
    pytest.skip.Exception
        If explicit native qualification inputs were not supplied.
    OSError
        If a required native artifact cannot be read.
    ValueError
        If source, profile, helper, or receipt bindings are stale.
    """
    return load_native_case("c")


def _assert_observed_declaration(
    case: NativeQualificationCase,
    artifact: DeclarationArtifact,
    *,
    expected_kind: str,
    expected_name: str,
    expected_line: int,
    expected_type: str,
    expected_invocation: str,
    context_identity: str,
) -> dict[str, object]:
    """Check source-authored facts against the native receipt and DTO.

    Parameters
    ----------
    case : NativeQualificationCase
        Verified C source/profile identity.
    artifact : DeclarationArtifact
        Production C analyzer declaration artifact.
    expected_kind, expected_name : str
        Source-authored logical declaration facts.
    expected_line : int
        Macro invocation line in the fixture source.
    expected_type : str
        Compiler-reported exact type spelling expected from this fixture.
    expected_invocation : str
        Exact source-authored macro invocation bytes decoded as text.
    context_identity : str
        Current analyzer input identity used for the native result.

    Returns
    -------
    dict[str, object]
        Parsed compiler declaration receipt after all source-bound checks pass.

    Raises
    ------
    AssertionError
        If compiler facts differ from the source-bound expected declaration.
    KeyError
        If the native receipt lacks a required fact.
    OSError
        If the fixture source cannot be read.
    json.JSONDecodeError
        If the native declaration receipt is malformed.
    """
    assert artifact.kind == expected_kind
    assert artifact.name == expected_name
    assert artifact.lineno == expected_line
    assert artifact.type_text == expected_type
    assert artifact.stable_id
    assert artifact.owner_name is None
    assert artifact.owner_stable_id is None
    assert artifact.access is None
    assert isinstance(artifact.stable_id, str) and artifact.stable_id
    provenance = artifact.generated
    assert provenance is not None
    assert provenance.variant == "compiler_observed_declaration"
    assert provenance.declaration_kind == expected_kind
    assert provenance.source_sha256 == case.capture["source_sha256"]
    assert provenance.context_identity == context_identity
    assert provenance.receipt_namespace == "clang.frontend.declaration-observation.v1"
    assert provenance.invocation.text == expected_invocation
    assert provenance.invocation.path == "src/c_case.c"
    assert provenance.expansion_location.path == "src/c_case.c"
    assert (
        provenance.expansion_location.byte_offset == provenance.invocation.byte_range[0]
    )
    source = case.source.read_bytes()
    start, end = provenance.invocation.byte_range
    assert source[start:end] == expected_invocation.encode("utf-8")
    assert source[:start].count(b"\n") + 1 == expected_line
    receipt = cast("dict[str, object]", json.loads(provenance.receipt_json))
    declaration = cast("dict[str, object]", receipt["declaration"])
    context = cast("dict[str, object]", receipt["context"])
    invocation = cast("dict[str, object]", receipt["macro_expansion"])
    assert receipt["schema"] == provenance.receipt_namespace
    assert declaration["entity_kind"] == expected_kind
    assert declaration["name"] == expected_name
    assert declaration["type_text"] == expected_type
    native_rows = cast("list[dict[str, object]]", case.capture["declarations"])
    native = [item for item in native_rows if item["name"] == expected_name]
    assert len(native) == 1
    assert declaration["usr"] == native[0]["usr"]
    assert declaration["owner_usr"] is None
    assert declaration["owner_name"] is None
    assert declaration["access"] is None
    assert declaration["is_file_scope"] is True
    assert context["source_sha256"] == case.capture["source_sha256"]
    assert context["analyzer_context_identity"] == context_identity
    assert invocation["invocation"] == expected_invocation
    assert invocation["byte_range"] == [start, end]
    return receipt


@pytest.mark.parametrize("backend_name", ["sqlite", "duckdb"])
def test_c_file_scope_macro_variables_persist_and_query(
    c_macro_case: NativeQualificationCase,
    tmp_path: Path,
    backend_name: str,
) -> None:
    """Qualify C file-scope macro variables/constants through both backends.

    Parameters
    ----------
    c_macro_case : NativeQualificationCase
        Durable source and native helper profile.
    tmp_path : pathlib.Path
        Disposable backend database workspace under the configured pytest temp root.
    backend_name : str
        First-party structural index backend under test.

    Returns
    -------
    None
        Native facts survive production analysis, persistence, and evidence query.
    """
    case = c_macro_case
    attempt_root = case.qualification_output / "attempts" / "c" / backend_name
    attempt_root.mkdir(parents=True, exist_ok=True)
    analyzer = CAnalyzer()
    config = plugin_configuration(case, attempt_root)
    analyzer.configure(config)
    analysis = analyzer.analyze_file(case.source, case.root)
    assert analysis.status is not None
    assert analysis.status.coverage_state.value == "complete"
    assert "generated_declaration" not in analysis.status.omitted_categories
    declarations = {
        artifact.name: artifact
        for artifact in analysis.declarations
        if artifact.kind in {"variable", "constant"}
    }
    assert "c_local_counter" not in declarations
    expected = {
        "c_macro_counter": (
            "variable",
            6,
            "int",
            "C_DECLARE_FILE_VARIABLE(c_macro_counter, 17)",
        ),
        "c_macro_limit": (
            "constant",
            7,
            "const unsigned int",
            "C_DECLARE_FILE_CONSTANT(c_macro_limit, 23U)",
        ),
    }
    context_identity = analyzer.analysis_input_fingerprint(case.source, case.root)
    receipts: dict[str, dict[str, object]] = {}
    for name, (kind, line, type_text, invocation) in expected.items():
        receipts[name] = _assert_observed_declaration(
            case,
            declarations[name],
            expected_kind=kind,
            expected_name=name,
            expected_line=line,
            expected_type=type_text,
            expected_invocation=invocation,
            context_identity=context_identity,
        )

    indexed = run_index_and_query(
        BackendQualificationRequest(
            case=case,
            backend_name=backend_name,
            analyzer_table="analyzer-c",
            symbol_names=("c_macro_counter", "c_macro_limit"),
            storage_root=tmp_path / backend_name,
            attempt_root=attempt_root,
        )
    )
    queried = cast("dict[str, dict[str, object]]", indexed["queried_symbols"])
    evidence = cast("dict[str, object]", queried["c_macro_counter"]["evidence"])
    symbol = cast("dict[str, object]", queried["c_macro_counter"]["symbol"])
    provenance = cast("dict[str, object]", evidence["generated_provenance"])
    observed = cast("dict[str, object]", evidence["compiler_observed_declaration"])
    assert evidence["source_kind"] == "compiler_generated"
    assert evidence["identity"] == symbol["identity"]
    assert observed["declaration_kind"] == "variable"
    assert provenance["source_sha256"] == case.capture["source_sha256"]
    assert provenance["context_identity"] == context_identity
    assert (
        provenance["receipt_namespace"] == "clang.frontend.declaration-observation.v1"
    )
    assert (
        json.loads(cast("str", provenance["receipt_json"]))
        == receipts["c_macro_counter"]
    )
    observed_invocation = cast(
        "dict[str, object]", evidence["compiler_observed_invocation"]
    )
    assert observed_invocation["text"] == "C_DECLARE_FILE_VARIABLE(c_macro_counter, 17)"
    constant = cast("dict[str, object]", queried["c_macro_limit"]["evidence"])
    assert constant["source_kind"] == "compiler_generated"
    constant_declaration = cast(
        "dict[str, object]", constant["compiler_observed_declaration"]
    )
    constant_provenance = cast("dict[str, object]", constant["generated_provenance"])
    assert constant_declaration["declaration_kind"] == "constant"
    assert constant_provenance["source_sha256"] == case.capture["source_sha256"]
    assert (
        json.loads(cast("str", constant_provenance["receipt_json"]))
        == receipts["c_macro_limit"]
    )
    receipt = {
        "schema": "codira.clang-macro-declaration-backend-qualification/1",
        "language": "c",
        "backend": backend_name,
        "source_sha256": case.capture["source_sha256"],
        "profile_sha256": case.capture["profile_sha256"],
        "helper_sha256": hashlib.sha256(case.helper.read_bytes()).hexdigest(),
        "analysis_coverage_state": analysis.status.coverage_state.value,
        "declarations": [
            {
                "name": name,
                "kind": values[0],
                "line": values[1],
                "type_text": values[2],
                "native_receipt": receipts[name],
            }
            for name, values in expected.items()
        ],
        "index": {
            key: value for key, value in indexed.items() if key != "queried_symbols"
        },
        "queried_symbol_evidence": queried,
        "database_retained": False,
        "database_digest": indexed["database_sha256"],
    }
    assert str(tmp_path) not in json.dumps(receipt, sort_keys=True)
    write_qualification_receipt(
        case.qualification_output / f"c-{backend_name}-qualification-r1.json",
        receipt,
    )
