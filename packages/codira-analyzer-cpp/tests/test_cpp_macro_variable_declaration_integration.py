"""Qualify native C++ scoped macro declarations through persistent queries.

Parameters
----------
None

Returns
-------
None
    Pytest checks namespace, record ownership, access, and duplicate anchors.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import cast

import pytest

from codira_analyzer_cpp import CppAnalyzer
from codira.generated import CompilerObservedDeclarationProvenance
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
def cpp_macro_case() -> NativeQualificationCase:
    """Load the durable C++ source and native profile bound to this fixture.

    Parameters
    ----------
    None

    Returns
    -------
    NativeQualificationCase
        Verified C++ fixture, profile, helper, and build-receipt binding.

    Raises
    ------
    pytest.skip.Exception
        If explicit native qualification inputs were not supplied.
    OSError
        If a required native artifact cannot be read.
    ValueError
        If source, profile, helper, or receipt bindings are stale.
    """
    return load_native_case("cpp")


def _assert_cpp_declaration(
    case: NativeQualificationCase,
    artifact: DeclarationArtifact,
    *,
    expected_kind: str,
    expected_name: str,
    expected_line: int,
    expected_type: str,
    expected_owner: str | None,
    expected_access: str | None,
    expected_invocation: str,
    context_identity: str,
) -> dict[str, object]:
    """Verify scoped compiler facts, invocation bytes, and receipt identity.

    Parameters
    ----------
    case : NativeQualificationCase
        Verified C++ source/profile identity.
    artifact : DeclarationArtifact
        Production C++ analyzer declaration artifact.
    expected_kind, expected_name : str
        Source-authored logical kind and qualified name.
    expected_line : int
        Physical macro invocation line.
    expected_type : str
        Exact compiler-reported declaration type.
    expected_owner : str or None
        Expected compiler owner name for namespace or record scope.
    expected_access : str or None
        Compiler-reported C++ access level, if record-owned.
    expected_invocation : str
        Exact source-authored macro invocation bytes.
    context_identity : str
        Current analyzer input identity bound to this declaration.

    Returns
    -------
    dict[str, object]
        Parsed native declaration receipt after all checks pass.

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
    assert artifact.owner_name == expected_owner
    assert (artifact.access or None) == expected_access
    assert isinstance(artifact.stable_id, str) and artifact.stable_id
    if expected_owner is None:
        assert artifact.owner_stable_id is None
    else:
        assert artifact.owner_stable_id
    provenance = artifact.generated
    assert provenance is not None
    assert provenance.variant == "compiler_observed_declaration"
    assert provenance.declaration_kind == expected_kind
    assert provenance.source_sha256 == case.capture["source_sha256"]
    assert provenance.context_identity == context_identity
    assert provenance.receipt_namespace == "clang.frontend.declaration-observation.v1"
    assert provenance.invocation.text == expected_invocation
    assert provenance.invocation.path == "src/cpp_case.cpp"
    assert provenance.expansion_location.path == "src/cpp_case.cpp"
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
    assert declaration["qualified_name"] == expected_name
    native_rows = cast("list[dict[str, object]]", case.capture["declarations"])
    native = [item for item in native_rows if item["qualified_name"] == expected_name]
    assert len(native) == 1
    assert declaration["usr"] == native[0]["usr"]
    assert declaration["type_text"] == expected_type
    assert declaration["owner_name"] == expected_owner
    assert declaration["access"] == expected_access
    assert context["source_sha256"] == case.capture["source_sha256"]
    assert context["analyzer_context_identity"] == context_identity
    assert invocation["invocation"] == expected_invocation
    assert invocation["byte_range"] == [start, end]
    return receipt


@pytest.mark.parametrize("backend_name", ["sqlite", "duckdb"])
def test_cpp_namespace_and_static_member_macros_persist_and_query(
    cpp_macro_case: NativeQualificationCase,
    tmp_path: Path,
    backend_name: str,
) -> None:
    """Qualify namespace and owned macro variables/constants in both backends.

    Parameters
    ----------
    cpp_macro_case : NativeQualificationCase
        Durable source and complete native helper profile.
    tmp_path : pathlib.Path
        Disposable backend database workspace under the configured pytest temp root.
    backend_name : str
        First-party structural index backend under test.

    Returns
    -------
    None
        Compiler facts persist and remain queryable with correct physical owners.
    """
    case = cpp_macro_case
    attempt_root = case.qualification_output / "attempts" / "cpp" / backend_name
    attempt_root.mkdir(parents=True, exist_ok=True)
    analyzer = CppAnalyzer()
    analyzer.configure(plugin_configuration(case, attempt_root))
    analysis = analyzer.analyze_file(case.source, case.root)
    assert analysis.status is not None
    declarations = [
        item for item in analysis.declarations if item.kind in {"variable", "constant"}
    ]
    by_name = {item.name: item for item in declarations}
    assert "cpp_local_counter" not in by_name
    expected = {
        "macro_context::namespace_counter": (
            "variable",
            9,
            "int",
            "macro_context",
            None,
            "CPP_DECLARE_NAMESPACE_VARIABLE(namespace_counter, 17)",
        ),
        "macro_context::namespace_limit": (
            "constant",
            10,
            "const int",
            "macro_context",
            None,
            "CPP_DECLARE_NAMESPACE_CONSTANT(namespace_limit, 23)",
        ),
        "macro_context::MacroOwner::public_counter": (
            "variable",
            14,
            "int",
            "macro_context::MacroOwner",
            "public",
            "CPP_DECLARE_STATIC_MEMBER(public_counter, 31)",
        ),
        "macro_context::MacroOwner::secret_counter": (
            "variable",
            17,
            "int",
            "macro_context::MacroOwner",
            "private",
            "CPP_DECLARE_STATIC_MEMBER(secret_counter, 37)",
        ),
        "macro_context::MacroOwner::out_of_line_counter": (
            "variable",
            23,
            "int",
            "macro_context::MacroOwner",
            "public",
            "CPP_DECLARE_OUT_OF_LINE_MEMBER(out_of_line_counter)",
        ),
    }
    context_identity = analyzer.analysis_input_fingerprint(case.source, case.root)
    receipts: dict[str, dict[str, object]] = {}
    for name, values in expected.items():
        kind, line, type_text, owner, access, invocation = values
        receipts[name] = _assert_cpp_declaration(
            case,
            by_name[name],
            expected_kind=kind,
            expected_name=name,
            expected_line=line,
            expected_type=type_text,
            expected_owner=owner,
            expected_access=access,
            expected_invocation=invocation,
            context_identity=context_identity,
        )

    out_of_line_name = "macro_context::MacroOwner::out_of_line_counter"
    out_of_line = [item for item in declarations if item.name == out_of_line_name]
    assert len(out_of_line) == 1
    assert out_of_line[0].kind == "variable"
    assert out_of_line[0].lineno == 23
    assert out_of_line[0].owner_name == "macro_context::MacroOwner"
    assert (out_of_line[0].access or None) == "public"
    assert isinstance(out_of_line[0].generated, CompilerObservedDeclarationProvenance)
    assert out_of_line[0].generated.invocation.text == (
        "CPP_DECLARE_OUT_OF_LINE_MEMBER(out_of_line_counter)"
    )
    assert analysis.status.omitted_categories == ()
    assert analysis.status.coverage_state.value == "complete"

    raw_path = Path(cast("str", case.capture["stdout_path"]))
    native = cast("dict[str, object]", json.loads(raw_path.read_text(encoding="utf-8")))
    native_rows = cast("list[dict[str, object]]", native["non_function_declarations"])
    duplicate_rows = [
        item
        for item in native_rows
        if item.get("name") == "out_of_line_counter"
        and item.get("qualified_name") == out_of_line_name
    ]
    assert len(duplicate_rows) == 2
    identities = [
        cast("dict[str, object]", item["identity"]) for item in duplicate_rows
    ]
    assert len({identity["usr"] for identity in identities}) == 1
    assert {identity["provenance"] for identity in identities} == {
        "macro_argument",
        "source_written",
    }

    symbol_names = tuple(expected)
    indexed = run_index_and_query(
        BackendQualificationRequest(
            case=case,
            backend_name=backend_name,
            analyzer_table="analyzer-cpp",
            symbol_names=symbol_names,
            storage_root=tmp_path / backend_name,
            attempt_root=attempt_root,
        )
    )
    queried = cast("dict[str, dict[str, object]]", indexed["queried_symbols"])
    for name, values in expected.items():
        evidence = cast("dict[str, object]", queried[name]["evidence"])
        symbol = cast("dict[str, object]", queried[name]["symbol"])
        provenance = cast("dict[str, object]", evidence["generated_provenance"])
        observed = cast("dict[str, object]", evidence["compiler_observed_declaration"])
        assert evidence["source_kind"] == "compiler_generated"
        assert evidence["identity"] == symbol["identity"]
        assert observed["declaration_kind"] == values[0]
        assert provenance["source_sha256"] == case.capture["source_sha256"]
        assert (
            provenance["receipt_namespace"]
            == "clang.frontend.declaration-observation.v1"
        )
        assert provenance["context_identity"] == context_identity
        assert json.loads(cast("str", provenance["receipt_json"])) == receipts[name]
        observed_invocation = cast(
            "dict[str, object]", evidence["compiler_observed_invocation"]
        )
        assert observed_invocation["text"] == values[5]
    out_of_line_evidence = cast(
        "dict[str, object]", queried[out_of_line_name]["evidence"]
    )
    out_of_line_symbol = cast("dict[str, object]", queried[out_of_line_name]["symbol"])
    assert out_of_line_evidence["source_kind"] == "compiler_generated"
    assert out_of_line_evidence["identity"] == out_of_line_symbol["identity"]
    out_of_line_provenance = cast(
        "dict[str, object]", out_of_line_evidence["generated_provenance"]
    )
    assert out_of_line_provenance["source_sha256"] == case.capture["source_sha256"]
    assert out_of_line_provenance["context_identity"] == context_identity
    out_of_line_invocation = cast(
        "dict[str, object]", out_of_line_evidence["compiler_observed_invocation"]
    )
    assert out_of_line_invocation["text"] == (
        "CPP_DECLARE_OUT_OF_LINE_MEMBER(out_of_line_counter)"
    )

    receipt = {
        "schema": "codira.clang-macro-declaration-backend-qualification/1",
        "language": "cpp",
        "backend": backend_name,
        "source_sha256": case.capture["source_sha256"],
        "profile_sha256": case.capture["profile_sha256"],
        "helper_sha256": hashlib.sha256(case.helper.read_bytes()).hexdigest(),
        "analysis_coverage_state": analysis.status.coverage_state.value,
        "omitted_categories": list(analysis.status.omitted_categories),
        "declarations": [
            {
                "name": name,
                "kind": values[0],
                "line": values[1],
                "type_text": values[2],
                "owner_name": values[3],
                "access": values[4],
                "native_receipt": receipts[name],
            }
            for name, values in expected.items()
        ],
        "out_of_line_redeclaration_pair": {
            "name": out_of_line_name,
            "line": out_of_line[0].lineno,
            "generated_provenance_attached": True,
            "native_duplicate_usr": identities[0]["usr"],
            "source_written_anchor_preserved": True,
        },
        "index": {
            key: value for key, value in indexed.items() if key != "queried_symbols"
        },
        "queried_symbol_evidence": queried,
        "database_retained": False,
        "database_digest": indexed["database_sha256"],
    }
    assert str(tmp_path) not in json.dumps(receipt, sort_keys=True)
    write_qualification_receipt(
        case.qualification_output / f"cpp-{backend_name}-qualification-r1.json",
        receipt,
    )
