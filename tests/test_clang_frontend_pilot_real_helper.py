"""Exercise the real LibTooling helper against independent source facts."""

from __future__ import annotations

import hashlib
import importlib
import json
import os
from pathlib import Path
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

import pytest

from scripts.clang_frontend_pilot.qualification import ExpectedFact, grade_fixture_facts


def test_real_helper_facts_and_macro_origins_match_handwritten_expectations(
    tmp_path: Path,
) -> None:
    """Grade helper output and adverse mutations against an independent fixture.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary directory for source, CDB, and helper evidence.

    Returns
    -------
    None

    Raises
    ------
    pytest.skip.Exception
        When the external helper binary or adapter source is unavailable.
    """

    helper_value = os.environ.get("CLANG_FRONTEND_PILOT_HELPER")
    if not helper_value:
        pytest.skip("set CLANG_FRONTEND_PILOT_HELPER to the pinned pilot helper binary")
    helper_path = Path(helper_value).resolve()
    if not helper_path.is_file():
        pytest.skip("pinned Clang pilot helper binary is not available")
    adapter_directory = os.environ.get("CLANG_FRONTEND_PILOT_ADAPTER_DIR")
    if adapter_directory:
        import scripts.clang_frontend_pilot as pilot_package

        package_path = Path(adapter_directory).resolve()
        if str(package_path) not in pilot_package.__path__:
            pilot_package.__path__.append(str(package_path))
    try:
        adapter_module = importlib.import_module("scripts.clang_frontend_pilot.adapter")
    except ImportError:
        pytest.skip("adapter module has not been integrated into this source worktree")
    adapt_selection = cast(
        "Callable[..., dict[str, object]]", adapter_module.adapt_selection
    )

    source = (
        "#define WRAP(v) helper(v)\n"
        "int helper(int value) { return value; }\n"
        "int direct(int value) { return helper(value); }\n"
        "int via_macro(void) { return WRAP(3); }\n"
        "int strict_proto(void);\n"
        "int old_style();\n"
    )
    root = tmp_path / "fixture-repository"
    source_path = root / "fixture.c"
    source_path.parent.mkdir(parents=True)
    source_path.write_text(source, encoding="utf-8")
    source_bytes = source_path.read_bytes()
    source_sha256 = hashlib.sha256(source_bytes).hexdigest()
    row = {
        "selection_id": "fixture-direct-and-macro-calls",
        "population_class": "nonllvm",
        "language": "c",
        "repository_id": "fixture-repository",
        "repository_revision": "handwritten-fixture-r1",
        "repository_relative_path": "fixture.c",
        "source_path": str(source_path.resolve()),
        "source_sha256": source_sha256,
        "classification_disposition": "fixture",
        "feature_family": "declaration_call_template",
        "family_evidence": {"source": "handwritten fixture facts"},
        "profile_context_status": "reproducible_profile",
        "profile_evidence": {"source": "one exact test compile command"},
        "context_limitations": [],
    }
    manifest_source = {
        "path": "handwritten-fixture-manifest",
        "sha256": hashlib.sha256(
            json.dumps(row, sort_keys=True).encode("utf-8")
        ).hexdigest(),
        "schema_version": "handwritten-fixture/1",
    }
    compile_database: list[Mapping[str, object]] = [
        {
            "directory": str(root),
            "file": str(source_path),
            "arguments": [
                "/usr/lib/llvm/22/bin/clang-22",
                "-x",
                "c",
                "-std=c11",
                "-fsyntax-only",
                str(source_path),
            ],
        }
    ]
    envelope = adapt_selection(
        row,
        manifest_source,
        compile_database,
        root,
        helper_path,
        stderr_path=tmp_path / "helper.stderr.txt",
        stdout_path=tmp_path / "helper.stdout.json",
    )
    expected = _fixture_expectations(source)

    initial_grade = grade_fixture_facts(envelope, expected)
    frontend_debug = envelope.get("frontend")
    assert isinstance(frontend_debug, dict)
    assert initial_grade.passed, {
        "status": envelope.get("status"),
        "holds": envelope.get("hold_reasons"),
        "adaptation": envelope.get("clang_adaptation"),
        "issues": initial_grade.issues,
        "declarations": frontend_debug.get("declarations", [])[:8],
        "calls": frontend_debug.get("calls", [])[:5],
    }

    frontend = envelope.get("frontend")
    assert isinstance(frontend, dict)
    declarations = frontend.get("declarations")
    calls = frontend.get("calls")
    assert isinstance(declarations, list)
    assert isinstance(calls, list)
    expected_missing = grade_fixture_facts(
        _replace_frontend_facts(envelope, declarations=declarations[:-1]), expected
    )
    expected_invented = grade_fixture_facts(
        _replace_frontend_facts(
            envelope,
            declarations=[*declarations, _invented_declaration(declarations[0])],
        ),
        expected,
    )
    expected_duplicate = grade_fixture_facts(
        _replace_frontend_facts(
            envelope, declarations=[*declarations, declarations[0]]
        ),
        expected,
    )
    macro_call_index = next(
        index
        for index, call in enumerate(calls)
        if call.get("origin") == "macro_replacement"
    )
    macro_call = calls[macro_call_index]
    assert isinstance(macro_call, dict)
    wrong_origin_calls = list(calls)
    wrong_origin_calls[macro_call_index] = {**macro_call, "origin": "source_written"}
    wrong_origin = _replace_frontend_facts(envelope, calls=wrong_origin_calls)
    wrong_macro_origin = grade_fixture_facts(wrong_origin, expected)
    macro_location = macro_call.get("location")
    assert isinstance(macro_location, dict)
    macro_expansion = macro_location.get("expansion")
    assert isinstance(macro_expansion, dict)
    expansion_line = macro_expansion.get("line")
    assert isinstance(expansion_line, int)
    wrong_expansion_call = {
        **macro_call,
        "location": {
            **macro_location,
            "expansion": {
                **macro_expansion,
                "line": expansion_line + 1,
            },
        },
    }
    wrong_expansion_calls = list(calls)
    wrong_expansion_calls[macro_call_index] = wrong_expansion_call
    wrong_expansion = grade_fixture_facts(
        _replace_frontend_facts(envelope, calls=wrong_expansion_calls),
        expected,
    )

    assert any(issue.category == "missing" for issue in expected_missing.issues)
    assert any(issue.category == "invented" for issue in expected_invented.issues)
    assert any(issue.category == "duplicate" for issue in expected_duplicate.issues)
    assert any(issue.category == "missing" for issue in wrong_macro_origin.issues)
    assert any(issue.category == "invented" for issue in wrong_macro_origin.issues)
    assert any(issue.category == "missing" for issue in wrong_expansion.issues)
    assert any(issue.category == "invented" for issue in wrong_expansion.issues)


def _fixture_expectations(source: str) -> tuple[ExpectedFact, ...]:
    """Write declaration/call expectations from the literal fixture source.

    Parameters
    ----------
    source : str
        Handwritten translation unit supplied to Clang.

    Returns
    -------
    tuple[ExpectedFact, ...]
        Independent exact declaration and call facts.
    """

    lines = source.splitlines()
    return (
        ExpectedFact(
            "declaration",
            "helper",
            2,
            5,
            "int helper(int value)",
            function_type="int (int)",
            has_prototype=True,
            is_variadic=False,
            decl_kind="function",
        ),
        ExpectedFact(
            "declaration",
            "direct",
            3,
            5,
            "int direct(int value)",
            function_type="int (int)",
            has_prototype=True,
            is_variadic=False,
            decl_kind="function",
        ),
        ExpectedFact(
            "declaration",
            "via_macro",
            4,
            5,
            "int via_macro(void)",
            function_type="int (void)",
            has_prototype=True,
            is_variadic=False,
            decl_kind="function",
        ),
        ExpectedFact(
            "declaration",
            "strict_proto",
            5,
            5,
            "int strict_proto(void)",
            function_type="int (void)",
            has_prototype=True,
            is_variadic=False,
            decl_kind="function",
        ),
        ExpectedFact(
            "declaration",
            "old_style",
            6,
            5,
            "int old_style()",
            function_type="int ()",
            has_prototype=False,
            is_variadic=False,
            decl_kind="function",
        ),
        ExpectedFact(
            "call",
            "helper",
            3,
            lines[2].index("helper") + 1,
            origin="source_written",
            spelling_line=3,
            spelling_column=lines[2].index("helper") + 1,
            expansion_line=3,
            expansion_column=lines[2].index("helper") + 1,
        ),
        ExpectedFact(
            "call",
            "helper",
            4,
            lines[3].index("WRAP") + 1,
            origin="macro_replacement",
            spelling_line=1,
            spelling_column=lines[0].index("helper") + 1,
            expansion_line=4,
            expansion_column=lines[3].index("WRAP") + 1,
        ),
    )


def test_real_helper_preserves_written_explicit_template_specialization(
    tmp_path: Path,
) -> None:
    """Keep an explicit specialization distinct from an instantiation.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository for source and helper evidence.

    Returns
    -------
    None

    Raises
    ------
    pytest.skip.Exception
        When the pinned helper or adapter source is not configured.
    """

    helper_value = os.environ.get("CLANG_FRONTEND_PILOT_HELPER")
    adapter_directory = os.environ.get("CLANG_FRONTEND_PILOT_ADAPTER_DIR")
    if not helper_value or not adapter_directory:
        pytest.skip("set the pinned helper and adapter source paths")
    helper_path = Path(helper_value).resolve()
    if not helper_path.is_file():
        pytest.skip("pinned Clang pilot helper binary is not available")
    import scripts.clang_frontend_pilot as pilot_package

    package_path = Path(adapter_directory).resolve()
    if str(package_path) not in pilot_package.__path__:
        pilot_package.__path__.append(str(package_path))
    try:
        adapter_module = importlib.import_module("scripts.clang_frontend_pilot.adapter")
    except ImportError:
        pytest.skip("adapter module has not been integrated into this source worktree")
    adapt_selection = cast(
        "Callable[..., dict[str, object]]", adapter_module.adapt_selection
    )

    source = (
        "template <typename T> T generic(T value) { return value; }\n"
        "template <> int generic<int>(int value) { return value; }\n"
    )
    root = tmp_path / "specialization-repository"
    source_path = root / "fixture.cpp"
    source_path.parent.mkdir(parents=True)
    source_path.write_text(source, encoding="utf-8")
    source_sha256 = hashlib.sha256(source_path.read_bytes()).hexdigest()
    row = {
        "selection_id": "fixture-written-explicit-specialization",
        "population_class": "nonllvm",
        "language": "cpp",
        "repository_id": "fixture-repository",
        "repository_revision": "handwritten-fixture-r1",
        "repository_relative_path": "fixture.cpp",
        "source_path": str(source_path.resolve()),
        "source_sha256": source_sha256,
        "classification_disposition": "fixture",
        "feature_family": "template_specialization",
        "family_evidence": {"source": "handwritten specialization"},
        "profile_context_status": "reproducible_profile",
        "profile_evidence": {"source": "one exact test compile command"},
        "context_limitations": [],
    }
    manifest_source = {
        "path": "handwritten-specialization-manifest",
        "sha256": hashlib.sha256(
            json.dumps(row, sort_keys=True).encode("utf-8")
        ).hexdigest(),
        "schema_version": "handwritten-fixture/1",
    }
    compile_database: list[Mapping[str, object]] = [
        {
            "directory": str(root),
            "file": str(source_path),
            "arguments": [
                "/usr/lib/llvm/22/bin/clang-22",
                "-x",
                "c++",
                "-std=c++17",
                "-fsyntax-only",
                str(source_path),
            ],
        }
    ]
    envelope = adapt_selection(
        row,
        manifest_source,
        compile_database,
        root,
        helper_path,
        stderr_path=tmp_path / "specialization.stderr.txt",
        stdout_path=tmp_path / "specialization.stdout.json",
    )
    generic_column = source.splitlines()[1].index("generic") + 1
    expected = (
        ExpectedFact(
            "declaration",
            "generic",
            1,
            source.splitlines()[0].index("generic") + 1,
            function_type="T (T)",
            has_prototype=True,
            is_variadic=False,
            decl_kind="function",
        ),
        ExpectedFact(
            "declaration",
            "generic",
            2,
            generic_column,
            "int generic<int>(int value)",
            function_type="int (int)",
            has_prototype=True,
            is_variadic=False,
            decl_kind="function",
        ),
    )

    grade = grade_fixture_facts(envelope, expected)

    assert grade.passed, grade.issues


def _replace_frontend_facts(
    envelope: Mapping[str, object],
    declarations: object | None = None,
    calls: object | None = None,
) -> dict[str, object]:
    """Copy one raw envelope while replacing selected fact rows.

    Parameters
    ----------
    envelope : Mapping[str, object]
        Original helper output.
    declarations : object or None, optional
        Replacement declarations.
    calls : object or None, optional
        Replacement calls.

    Returns
    -------
    dict[str, object]
        Independent mutable copy for a grader mutation control.
    """

    copied = _json_object(json.dumps(envelope))
    frontend = copied.get("frontend")
    assert isinstance(frontend, dict)
    if declarations is not None:
        frontend["declarations"] = declarations
    if calls is not None:
        frontend["calls"] = calls
    return copied


def _invented_declaration(template: Mapping[str, object]) -> dict[str, object]:
    """Produce an impossible source-written declaration for an adverse control.

    Parameters
    ----------
    template : Mapping[str, object]
        Real helper declaration used only to retain the schema shape.

    Returns
    -------
    dict[str, object]
        Invented declaration fact absent from the fixture source oracle.
    """

    invented = _json_object(json.dumps(template))
    invented["qualified_name"] = "fabricated"
    invented["name"] = "fabricated"
    invented["signature"] = "int fabricated(void)"
    return invented


def _json_object(encoded: str) -> dict[str, object]:
    """Decode a JSON object and reject a value with another top-level shape.

    Parameters
    ----------
    encoded : str
        JSON text known to originate from a mapping.

    Returns
    -------
    dict[str, object]
        Decoded mapping whose nested values remain at the JSON boundary.

    Raises
    ------
    AssertionError
        If the encoded value is not a JSON object.
    """

    value = json.loads(encoded)
    assert isinstance(value, dict)
    return value
