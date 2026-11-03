"""Tests for independent Clang AST reference normalization.

Parameters
----------
None

Returns
-------
None
"""

from __future__ import annotations

import hashlib
import json
from types import SimpleNamespace
from typing import TYPE_CHECKING
from unittest.mock import patch

from scripts.clang_reference_facts import (
    _direct_callee,
    _source_name_match,
    _validate_scope_rows,
    _walk_with_file_context,
    capture_one,
    normalize_ast,
    reference_invocation,
)

if TYPE_CHECKING:
    from pathlib import Path
    from typing import BinaryIO


def test_normalize_source_owned_function_and_direct_call(tmp_path: Path) -> None:
    """Retain facts only when AST ownership and source bytes agree.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary directory supplied by pytest.

    Returns
    -------
    None
        Assertions validate the normalized source-owned facts.
    """
    source = b"namespace n { int run(int x) { return helper(x); } }\n"
    path = tmp_path / "sample.cpp"
    path.write_bytes(source)
    run_offset = source.index(b"run")
    call_offset = source.index(b"helper")
    call_end = source.index(b")", call_offset)
    ast: dict[str, object] = {
        "kind": "TranslationUnitDecl",
        "inner": [
            {
                "kind": "NamespaceDecl",
                "name": "n",
                "loc": {"file": str(path), "offset": source.index(b"n")},
                "inner": [
                    {
                        "kind": "FunctionDecl",
                        "name": "run",
                        "loc": {"file": str(path), "offset": run_offset},
                        "type": {"qualType": "int (int)"},
                        "inner": [
                            {
                                "kind": "CompoundStmt",
                                "inner": [
                                    {
                                        "kind": "CallExpr",
                                        "range": {
                                            "begin": {
                                                "file": str(path),
                                                "offset": call_offset,
                                            },
                                            "end": {
                                                "file": str(path),
                                                "offset": call_end,
                                            },
                                        },
                                        "inner": [
                                            {
                                                "kind": "DeclRefExpr",
                                                "referencedDecl": {
                                                    "kind": "FunctionDecl",
                                                    "name": "helper",
                                                    "type": {"qualType": "int (int)"},
                                                },
                                            }
                                        ],
                                    }
                                ],
                            }
                        ],
                    }
                ],
            }
        ],
    }

    result = normalize_ast(ast, path, source, tmp_path)

    facts = result["facts"]
    assert isinstance(facts, dict)
    callables = facts["callables"]
    calls = facts["calls"]
    assert isinstance(callables, list)
    assert isinstance(calls, list)
    assert callables[0]["name"] == "run"
    assert callables[0]["owner_chain"] == ["n"]
    assert callables[0]["type"] == "int (int)"
    assert calls[0]["direct_target"] == {
        "kind": "FunctionDecl",
        "name": "helper",
        "type": "int (int)",
    }
    assert result["whole_file_parity"] is False


def test_explicit_external_file_is_not_misattributed_by_matching_offset(
    tmp_path: Path,
) -> None:
    """Reject a header declaration based on offset coincidence.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary directory supplied by pytest.

    Returns
    -------
    None
        Assertions verify the declaration is excluded.
    """
    source = b"int shared_name();\n"
    path = tmp_path / "sample.c"
    header = tmp_path / "shared.h"
    path.write_bytes(source)
    header.write_text("int shared_name();\n", encoding="utf-8")
    offset = source.index(b"shared_name")
    ast: dict[str, object] = {
        "kind": "TranslationUnitDecl",
        "inner": [
            {
                "kind": "FunctionDecl",
                "name": "shared_name",
                "loc": {"file": str(header), "offset": offset},
                "type": {"qualType": "int ()"},
            }
        ],
    }

    result = normalize_ast(ast, path, source, tmp_path)

    facts = result["facts"]
    assert isinstance(facts, dict)
    assert facts["declarations"] == []


def test_location_context_is_carried_in_ast_serialization_order(
    tmp_path: Path,
) -> None:
    """Follow Clang's versioned global state for elided file names.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary directory supplied by pytest.

    Returns
    -------
    None
        Assertions verify inherited location ownership.
    """
    source = b"int first();\nint second();\n"
    path = tmp_path / "sample.c"
    path.write_bytes(source)
    ast: dict[str, object] = {
        "kind": "TranslationUnitDecl",
        "inner": [
            {
                "kind": "FunctionDecl",
                "name": "first",
                "loc": {"file": str(path), "offset": source.index(b"first")},
            },
            {
                "kind": "FunctionDecl",
                "name": "second",
                "loc": {"offset": source.index(b"second")},
            },
        ],
    }

    result = normalize_ast(ast, path, source, tmp_path)

    facts = result["facts"]
    assert isinstance(facts, dict)
    callables = facts["callables"]
    assert isinstance(callables, list)
    assert [item["name"] for item in callables] == ["first", "second"]
    assert callables[1]["file_binding"] == "inherited_json_file_context"


def test_reference_invocation_preserves_driver_mode_and_effective_binary() -> None:
    """Keep driver spelling while using the receipt-bound Clang binary.

    Parameters
    ----------
    None

    Returns
    -------
    None
        Assertions verify the constructed invocation.
    """
    identity: dict[str, object] = {
        "original_driver_argv0": "/usr/bin/cc",
        "adapted_argv": ["-std=gnu99", "-fsyntax-only", "-Iinclude"],
        "source_path": "/src/file.c",
        "effective_compiler_path": "/receipt/clang-22",
    }

    argv, executable = reference_invocation(identity)

    assert argv == [
        "/usr/bin/cc",
        "-std=gnu99",
        "-fsyntax-only",
        "-Iinclude",
        "-Xclang",
        "-ast-dump=json",
        "/src/file.c",
    ]
    assert executable == "/receipt/clang-22"
    assert "-x" not in argv


def test_declaration_location_must_match_physical_source_line(
    tmp_path: Path,
) -> None:
    """Reject a token offset paired with an incorrect physical line.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary directory supplied by pytest.

    Returns
    -------
    None
        Assertions verify the declaration is not retained.
    """
    source = b"int selected();\n"
    path = tmp_path / "sample.c"
    path.write_bytes(source)
    offset = source.index(b"selected")
    ast: dict[str, object] = {
        "kind": "TranslationUnitDecl",
        "inner": [
            {
                "kind": "FunctionDecl",
                "name": "selected",
                "loc": {
                    "file": str(path),
                    "offset": offset,
                    "line": 99,
                    "col": 9,
                },
                "type": {"qualType": "int ()"},
            }
        ],
    }

    result = normalize_ast(ast, path, source, tmp_path)

    facts = result["facts"]
    ungraded_counts = result["ungraded_counts"]
    assert isinstance(facts, dict)
    assert isinstance(ungraded_counts, dict)
    assert facts["callables"] == []
    assert ungraded_counts["declaration_location_or_name_unproven"] == 1


def test_source_name_match_requires_complete_identifier_and_operator_tokens() -> None:
    """Reject identifier prefixes, suffixes, and uncertain Unicode boundaries.

    Parameters
    ----------
    None

    Returns
    -------
    None
        Assertions distinguish exact identifiers and punctuation names from
        neighboring identifier bytes.
    """
    source = (
        b"int run; int runner; int prerun; int run$next; "
        b"void operator()(); struct S { ~S(); }; int run\\u0065r;"
    )
    assert _source_name_match(source, source.index(b"run;"), "run")
    assert not _source_name_match(source, source.index(b"runner"), "run")
    assert not _source_name_match(source, source.index(b"prerun") + 3, "run")
    assert not _source_name_match(source, source.index(b"run$next"), "run")
    assert _source_name_match(source, source.index(b"run$next"), "run$next")
    assert _source_name_match(source, source.index(b"operator()"), "operator()")
    assert _source_name_match(source, source.index(b"~S"), "~S")
    assert not _source_name_match(source, source.rindex(b"run\\u0065r"), "run")

    unicode_source = "int runé;".encode()
    assert not _source_name_match(unicode_source, unicode_source.index(b"run"), "run")
    assert _source_name_match(
        unicode_source, unicode_source.index("runé".encode()), "runé"
    )


def test_presumed_line_and_column_do_not_override_physical_source_position(
    tmp_path: Path,
) -> None:
    """Keep physical offsets when Clang emits presumed coordinates.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary directory supplied by pytest.

    Returns
    -------
    None
        Assertions compare physical and presumed location fields.
    """
    source = b'#line 200 "virtual.h"\nint selected();\n'
    path = tmp_path / "sample.c"
    path.write_bytes(source)
    offset = source.index(b"selected")
    ast: dict[str, object] = {
        "kind": "TranslationUnitDecl",
        "inner": [
            {
                "kind": "FunctionDecl",
                "name": "selected",
                "loc": {
                    "file": str(path),
                    "offset": offset,
                    "line": 2,
                    "presumedFile": "virtual.h",
                    "presumedLine": 200,
                    "col": 47,
                },
                "type": {"qualType": "int ()"},
            }
        ],
    }

    result = normalize_ast(ast, path, source, tmp_path)

    facts = result["facts"]
    assert isinstance(facts, dict)
    callables = facts["callables"]
    assert isinstance(callables, list)
    assert callables[0]["name"] == "selected"
    assert callables[0]["line"] == 2


def test_macro_location_order_and_included_from_do_not_change_actual_file(
    tmp_path: Path,
) -> None:
    """Apply spelling then expansion context, excluding include-stack files.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary directory supplied by pytest.

    Returns
    -------
    None
        Assertions verify the emitted location context order.
    """
    source = tmp_path / "sample.c"
    header = tmp_path / "sample.h"
    ast: dict[str, object] = {
        "kind": "TranslationUnitDecl",
        "loc": {
            "spellingLoc": {
                "file": str(header),
                "offset": 12,
                "includedFrom": {"file": str(tmp_path / "driver.c")},
            },
            "expansionLoc": {"file": str(source), "offset": 4},
        },
        "next": {"offset": 8},
    }

    locations = list(_walk_with_file_context(ast, tmp_path))

    assert [path for _, path, _ in locations] == [
        header.resolve(),
        source.resolve(),
        source.resolve(),
    ]
    assert [origin for _, _, origin in locations] == [
        "explicit",
        "explicit",
        "inherited_json_file_context",
    ]


def test_overlapping_ast_call_nodes_are_one_ungraded_source_site(
    tmp_path: Path,
) -> None:
    """Keep overlapping semantic AST nodes under one written source site.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary directory supplied by pytest.

    Returns
    -------
    None
        Assertions verify the ambiguous group remains ungraded.
    """
    source = b"invoke();\n"
    path = tmp_path / "sample.c"
    path.write_bytes(source)
    begin = source.index(b"invoke")
    end = source.index(b")", begin)
    bounds = {
        "begin": {"file": str(path), "offset": begin},
        "end": {"file": str(path), "offset": end},
    }
    call: dict[str, object] = {
        "kind": "CallExpr",
        "range": bounds,
        "inner": [
            {
                "kind": "DeclRefExpr",
                "referencedDecl": {
                    "kind": "FunctionDecl",
                    "name": "invoke",
                    "type": {"qualType": "void ()"},
                },
            }
        ],
    }
    ast: dict[str, object] = {
        "kind": "TranslationUnitDecl",
        "inner": [call, {**call, "kind": "CXXOperatorCallExpr"}],
    }

    result = normalize_ast(ast, path, source, tmp_path)

    facts = result["facts"]
    assert isinstance(facts, dict)
    call_sites = facts["source_call_sites"]
    assert isinstance(call_sites, list)
    assert len(call_sites) == 1
    assert call_sites[0]["ast_candidate_count"] == 2
    assert call_sites[0]["direct_target"] is None
    assert call_sites[0]["status"] == "multiple_ast_nodes_at_source_span_ungraded"


def test_physical_call_site_groups_different_caller_contexts_without_dropping_candidates(
    tmp_path: Path,
) -> None:
    """Keep caller variants under one authored physical site.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary directory supplied by pytest.

    Returns
    -------
    None
        Assertions verify both candidate contexts and targets remain.
    """
    source = b"invoke();\n"
    path = tmp_path / "sample.cpp"
    path.write_bytes(source)
    begin = source.index(b"invoke")
    end = source.index(b")", begin)
    call: dict[str, object] = {
        "kind": "CallExpr",
        "range": {
            "begin": {"file": str(path), "offset": begin},
            "end": {"file": str(path), "offset": end},
        },
        "inner": [
            {
                "kind": "DeclRefExpr",
                "referencedDecl": {
                    "kind": "FunctionDecl",
                    "name": "invoke",
                    "type": {"qualType": "void ()"},
                },
            }
        ],
    }
    ast: dict[str, object] = {
        "kind": "TranslationUnitDecl",
        "inner": [
            {
                "kind": "FunctionDecl",
                "name": "instantiation_a",
                "inner": [{"kind": "CompoundStmt", "inner": [call]}],
            },
            {
                "kind": "FunctionDecl",
                "name": "instantiation_b",
                "inner": [{"kind": "CompoundStmt", "inner": [call]}],
            },
        ],
    }

    result = normalize_ast(ast, path, source, tmp_path)

    facts = result["facts"]
    assert isinstance(facts, dict)
    assert len(facts["calls"]) == 2
    call_sites = facts["source_call_sites"]
    assert isinstance(call_sites, list)
    assert len(call_sites) == 1
    site = call_sites[0]
    assert site["caller_contexts"] == [["instantiation_a"], ["instantiation_b"]]
    assert site["ast_candidate_count"] == 2
    assert site["direct_target"] is None
    assert site["status"] == "multiple_caller_contexts_at_source_span_ungraded"
    candidates = site["candidates"]
    assert isinstance(candidates, list)
    assert [candidate["caller_chain"] for candidate in candidates] == [
        ["instantiation_a"],
        ["instantiation_b"],
    ]
    assert [candidate["direct_target"]["name"] for candidate in candidates] == [
        "invoke",
        "invoke",
    ]


def test_ownership_diagnostics_split_declaration_holds_and_bound_samples(
    tmp_path: Path,
) -> None:
    """Separate root holds, external exclusions, and unknown declarations.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary directory supplied by pytest.

    Returns
    -------
    None
        Assertions verify exact counters and the per-class sample cap.
    """
    source = b"int root_name;\n"
    path = tmp_path / "sample.c"
    header = tmp_path / "external.h"
    path.write_bytes(source)
    header.write_text("int external_name;\n", encoding="utf-8")
    root_offset = source.index(b"root_name")
    declarations: list[dict[str, object]] = [
        {"kind": "VarDecl", "name": "unknown_name", "loc": {"offset": 0}}
    ]
    declarations.extend(
        {
            "kind": "VarDecl",
            "name": f"mismatch_{index}",
            "loc": {"file": str(path), "offset": root_offset},
        }
        for index in range(40)
    )
    declarations.extend(
        [
            {
                "kind": "VarDecl",
                "name": "external_name",
                "loc": {"file": str(header), "offset": 4},
            },
        ]
    )
    result = normalize_ast(
        {"kind": "TranslationUnitDecl", "inner": declarations},
        path,
        source,
        tmp_path,
    )

    diagnostics = result["ownership_diagnostics"]
    counts = result["ungraded_counts"]
    assert isinstance(diagnostics, dict)
    assert isinstance(counts, dict)
    groups = diagnostics["declarations"]
    assert isinstance(groups, dict)
    root_group = groups["root_intersecting"]
    external_group = groups["proved_external"]
    unknown_group = groups["unknown"]
    assert isinstance(root_group, dict)
    assert isinstance(external_group, dict)
    assert isinstance(unknown_group, dict)
    assert root_group["counts_by_reason"] == {"source_name_token_mismatch": 40}
    assert len(root_group["samples"]) == 32
    assert external_group["counts_by_reason"] == {"outside_translation_unit": 1}
    assert unknown_group["counts_by_reason"] == {"file_context_unknown": 1}
    assert counts["declaration_location_or_name_unproven"] == 41


def test_ownership_diagnostics_classify_call_ranges_without_weakening_holds(
    tmp_path: Path,
) -> None:
    """Report root, external, and unknown call range failures separately.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary directory supplied by pytest.

    Returns
    -------
    None
        Assertions verify range reasons and legacy aggregate compatibility.
    """
    source = b"root_call();\n"
    path = tmp_path / "sample.c"
    header = tmp_path / "external.h"
    path.write_bytes(source)
    header.write_text("external_call();\n", encoding="utf-8")
    root_begin = source.index(b"root_call")
    root_end = source.index(b")", root_begin)
    external_begin = 0
    external_end = len(b"external_call")
    calls: list[dict[str, object]] = [
        {
            "kind": "CallExpr",
            "range": {"begin": {"offset": 0}, "end": {"offset": 2}},
        },
        {
            "kind": "CallExpr",
            "range": {
                "begin": {"file": str(path), "offset": root_begin, "line": 99},
                "end": {"file": str(path), "offset": root_end},
            },
        },
        {
            "kind": "CallExpr",
            "range": {
                "begin": {"file": str(path), "offset": root_begin},
                "end": {"file": str(header), "offset": external_end},
            },
        },
        {
            "kind": "CallExpr",
            "range": {
                "begin": {"file": str(header), "offset": external_begin},
                "end": {"file": str(header), "offset": external_end},
            },
        },
    ]
    result = normalize_ast(
        {"kind": "TranslationUnitDecl", "inner": calls}, path, source, tmp_path
    )

    diagnostics = result["ownership_diagnostics"]
    counts = result["ungraded_counts"]
    assert isinstance(diagnostics, dict)
    assert isinstance(counts, dict)
    groups = diagnostics["calls"]
    assert isinstance(groups, dict)
    root_group = groups["root_intersecting"]
    external_group = groups["proved_external"]
    unknown_group = groups["unknown"]
    assert isinstance(root_group, dict)
    assert isinstance(external_group, dict)
    assert isinstance(unknown_group, dict)
    assert root_group["counts_by_reason"] == {
        "cross_file_range": 1,
        "source_line_or_offset_invalid": 1,
    }
    assert external_group["counts_by_reason"] == {"outside_translation_unit": 1}
    assert unknown_group["counts_by_reason"] == {"file_context_unknown": 1}
    assert counts["call_physical_ownership_unproven"] == 3


def test_lambda_operator_locations_remain_held_but_written_operator_is_retained(
    tmp_path: Path,
) -> None:
    """Do not treat lambda capture brackets as written operator names.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary directory supplied by pytest.

    Returns
    -------
    None
        Assertions retain only the explicitly written operator declaration.
    """
    source = (
        b"auto captureless = [] { return 1; };\n"
        b"int captured_value = 2;\n"
        b"auto captured = [captured_value] { return captured_value; };\n"
        b"auto nested = [captured_value] { auto inner = [captured_value] { "
        b"return captured_value; }; return inner(); };\n"
        b"struct Callable { ~Callable() {} void operator()() const {} };\n"
    )
    path = tmp_path / "lambda.cpp"
    path.write_bytes(source)
    lambda_offsets = [
        source.index(b"[]"),
        source.index(b"[captured_value]"),
        source.index(b"[captured_value]", source.index(b"auto nested")),
        source.index(b"[captured_value]", source.index(b"auto inner")),
    ]
    written_operator = source.index(b"operator()")
    written_destructor = source.index(b"~Callable")
    ast: dict[str, object] = {
        "kind": "TranslationUnitDecl",
        "inner": [
            {
                "kind": "CXXMethodDecl",
                "name": "operator()",
                "loc": {"file": str(path), "offset": offset},
            }
            for offset in lambda_offsets
        ]
        + [
            {
                "kind": "CXXDestructorDecl",
                "name": "~Callable",
                "loc": {"file": str(path), "offset": written_destructor},
                "type": {"qualType": "void ()"},
                "inner": [{"kind": "CompoundStmt", "inner": []}],
            },
            {
                "kind": "CXXMethodDecl",
                "name": "operator()",
                "loc": {"file": str(path), "offset": written_operator},
            },
        ],
    }

    result = normalize_ast(ast, path, source, tmp_path)

    facts = result["facts"]
    diagnostics = result["ownership_diagnostics"]
    assert isinstance(facts, dict)
    assert isinstance(diagnostics, dict)
    assert [fact["offset"] for fact in facts["callables"]] == [
        written_destructor,
        written_operator,
    ]
    declaration_groups = diagnostics["declarations"]
    assert isinstance(declaration_groups, dict)
    root_group = declaration_groups["root_intersecting"]
    assert isinstance(root_group, dict)
    assert root_group["counts_by_reason"] == {"source_name_token_mismatch": 4}


def _call_ast_node(path: Path, source: bytes, name: bytes) -> dict[str, object]:
    """Build one source-bounded direct call node for lambda mapping controls.

    Parameters
    ----------
    path : pathlib.Path
        Translation-unit path bound to the synthetic AST.
    source : bytes
        Coordinate-aligned source bytes.
    name : bytes
        Exact call-name token appearing in ``source``.

    Returns
    -------
    dict[str, object]
        CallExpr with explicit source-file locations for both range endpoints.
    """
    begin = source.index(name)
    end = source.index(b")", begin)
    return {
        "kind": "CallExpr",
        "range": {
            "begin": {"file": str(path), "offset": begin},
            "end": {"file": str(path), "offset": end},
        },
    }


def _lambda_ast_node(
    path: Path,
    source: bytes,
    capture_offset: int,
    body_children: list[dict[str, object]],
    *,
    implicit_record: bool = True,
    operator_implicit: bool | None = True,
) -> dict[str, object]:
    """Build the compiler-shaped implicit record/operator wrapper for a lambda.

    Parameters
    ----------
    path : pathlib.Path
        Translation-unit path bound to the synthetic AST.
    source : bytes
        Coordinate-aligned source bytes.
    capture_offset : int
        Byte offset of the lambda capture introducer.
    body_children : list[dict[str, object]]
        AST nodes placed in the synthesized operator body.
    implicit_record : bool, optional
        Whether the closure record supplies proof for product-owner mapping.
    operator_implicit : bool or None, optional
        Explicit operator marker; ``None`` models Clang JSON omission.

    Returns
    -------
    dict[str, object]
        LambdaExpr with an implicit closure record and call operator.
    """
    location = {"file": str(path), "offset": capture_offset}
    operator: dict[str, object] = {
        "kind": "CXXMethodDecl",
        "name": "operator()",
        "loc": dict(location),
        "inner": [{"kind": "CompoundStmt", "inner": body_children}],
    }
    if operator_implicit is not None:
        operator["isImplicit"] = operator_implicit
    return {
        "kind": "LambdaExpr",
        "range": {
            "begin": dict(location),
            "end": {"file": str(path), "offset": len(source) - 1},
        },
        "inner": [
            {
                "kind": "CXXRecordDecl",
                "isImplicit": implicit_record,
                "loc": dict(location),
                "inner": [operator],
            }
        ],
    }


def test_lambda_calls_keep_compiler_chain_and_map_only_proven_product_owner(
    tmp_path: Path,
) -> None:
    """Map nested captureless/captured lambdas without altering raw callers.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary directory supplied by pytest.

    Returns
    -------
    None
        Assertions compare compiler and product caller chains for each call.
    """
    source = (
        b"void entry() { auto plain = [] { first(); }; int value = 1; "
        b"auto capture = [value] { second(); }; auto nested = [value] { "
        b"auto inner = [value] { third(); }; }; }\n"
        b"struct Callable { void operator()() { explicit_call(); } };\n"
    )
    path = tmp_path / "lambda-caller.cpp"
    path.write_bytes(source)
    first_lambda = _lambda_ast_node(
        path, source, source.index(b"[]"), [_call_ast_node(path, source, b"first")]
    )
    captured_lambda = _lambda_ast_node(
        path,
        source,
        source.index(b"[value]"),
        [_call_ast_node(path, source, b"second")],
    )
    inner_lambda = _lambda_ast_node(
        path,
        source,
        source.index(b"[value]", source.index(b"auto inner")),
        [_call_ast_node(path, source, b"third")],
    )
    nested_lambda = _lambda_ast_node(
        path,
        source,
        source.index(b"[value]", source.index(b"auto nested")),
        [inner_lambda],
    )
    entry = {
        "kind": "FunctionDecl",
        "name": "entry",
        "loc": {"file": str(path), "offset": source.index(b"entry")},
        "type": {"qualType": "void ()"},
        "inner": [
            {
                "kind": "CompoundStmt",
                "inner": [first_lambda, captured_lambda, nested_lambda],
            }
        ],
    }
    operator_offset = source.index(b"operator()")
    callable_record = {
        "kind": "CXXRecordDecl",
        "name": "Callable",
        "loc": {"file": str(path), "offset": source.index(b"Callable")},
        "inner": [
            {
                "kind": "CXXMethodDecl",
                "name": "operator()",
                "loc": {"file": str(path), "offset": operator_offset},
                "type": {"qualType": "void ()"},
                "inner": [
                    {
                        "kind": "CompoundStmt",
                        "inner": [_call_ast_node(path, source, b"explicit_call")],
                    }
                ],
            }
        ],
    }

    result = normalize_ast(
        {"kind": "TranslationUnitDecl", "inner": [entry, callable_record]},
        path,
        source,
        tmp_path,
    )

    facts = result["facts"]
    counts = result["ungraded_counts"]
    assert isinstance(facts, dict)
    assert isinstance(counts, dict)
    calls = facts["calls"]
    assert isinstance(calls, list)
    call_rows = {
        source[row["begin_offset"] : row["end_offset"] + row["end_token_length"]]
        .decode("ascii")
        .removesuffix("()")
        for row in calls
    }
    assert call_rows == {"first", "second", "third", "explicit_call"}
    by_name = {
        source[row["begin_offset"] : row["end_offset"] + row["end_token_length"]]
        .decode("ascii")
        .removesuffix("()"): row
        for row in calls
    }
    assert by_name["first"]["caller_chain"] == ["entry", "operator()"]
    assert by_name["second"]["caller_chain"] == ["entry", "operator()"]
    assert by_name["third"]["caller_chain"] == [
        "entry",
        "operator()",
        "operator()",
    ]
    for name in ("first", "second", "third"):
        assert by_name[name]["product_caller_chain"] == ["entry"]
        assert (
            by_name[name]["product_owner_mapping_status"]
            == "proven_enclosing_authored_callable"
        )
    assert by_name["explicit_call"]["caller_chain"] == ["operator()"]
    assert by_name["explicit_call"]["product_caller_chain"] == ["operator()"]
    assert counts.get("lambda_product_owner_unproven", 0) == 0


def test_lambda_operator_without_implicit_marker_uses_parent_and_location_proof(
    tmp_path: Path,
) -> None:
    """Accept Clang's omitted operator marker only under a proven closure record.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary directory supplied by pytest.

    Returns
    -------
    None
        Assertions accept the observed Clang shape and reject explicit false.
    """
    source = b"void entry() { auto fn = [] { held(); }; }\n"
    path = tmp_path / "clang-omitted-lambda-marker.cpp"
    path.write_bytes(source)
    capture_offset = source.index(b"[]")

    def normalized(
        operator_implicit: bool | None, operator_offset: int = capture_offset
    ) -> dict[str, object]:
        lambda_node = _lambda_ast_node(
            path,
            source,
            capture_offset,
            [_call_ast_node(path, source, b"held")],
            operator_implicit=operator_implicit,
        )
        lambda_children = lambda_node["inner"]
        assert isinstance(lambda_children, list)
        closure_record = lambda_children[0]
        assert isinstance(closure_record, dict)
        closure_children = closure_record["inner"]
        assert isinstance(closure_children, list)
        operator = closure_children[0]
        assert isinstance(operator, dict)
        operator_location = operator["loc"]
        assert isinstance(operator_location, dict)
        operator_location["offset"] = operator_offset
        ast: dict[str, object] = {
            "kind": "TranslationUnitDecl",
            "inner": [
                {
                    "kind": "FunctionDecl",
                    "name": "entry",
                    "loc": {"file": str(path), "offset": source.index(b"entry")},
                    "inner": [{"kind": "CompoundStmt", "inner": [lambda_node]}],
                }
            ],
        }
        return normalize_ast(ast, path, source, tmp_path)

    omitted = normalized(None)
    omitted_facts = omitted["facts"]
    assert isinstance(omitted_facts, dict)
    omitted_calls = omitted_facts["calls"]
    assert isinstance(omitted_calls, list)
    assert omitted_calls[0]["product_caller_chain"] == ["entry"]
    assert omitted_calls[0]["product_owner_mapping_status"] == (
        "proven_enclosing_authored_callable"
    )

    for operator_implicit, operator_offset in (
        (False, capture_offset),
        (None, capture_offset + 1),
    ):
        unproven = normalized(operator_implicit, operator_offset)
        unproven_facts = unproven["facts"]
        unproven_counts = unproven["ungraded_counts"]
        assert isinstance(unproven_facts, dict)
        assert isinstance(unproven_counts, dict)
        unproven_calls = unproven_facts["calls"]
        assert isinstance(unproven_calls, list)
        assert unproven_calls[0]["product_caller_chain"] is None
        assert unproven_counts["lambda_product_owner_unproven"] == 1


def test_unproven_lambda_keeps_call_and_raw_caller_chain(tmp_path: Path) -> None:
    """Retain calls when a lambda wrapper cannot prove a product owner.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary directory supplied by pytest.

    Returns
    -------
    None
        Assertions keep the raw call while recording unresolved product ownership.
    """
    source = b"void entry() { auto fn = [&] { held(); }; }\n"
    path = tmp_path / "unproven-lambda.cpp"
    path.write_bytes(source)
    lambda_node = _lambda_ast_node(
        path,
        source,
        source.index(b"[&]"),
        [_call_ast_node(path, source, b"held")],
        implicit_record=False,
    )
    ast: dict[str, object] = {
        "kind": "TranslationUnitDecl",
        "inner": [
            {
                "kind": "FunctionDecl",
                "name": "entry",
                "loc": {"file": str(path), "offset": source.index(b"entry")},
                "inner": [{"kind": "CompoundStmt", "inner": [lambda_node]}],
            }
        ],
    }

    result = normalize_ast(ast, path, source, tmp_path)

    facts = result["facts"]
    counts = result["ungraded_counts"]
    assert isinstance(facts, dict)
    assert isinstance(counts, dict)
    calls = facts["calls"]
    assert isinstance(calls, list)
    assert len(calls) == 1
    assert calls[0]["caller_chain"] == ["entry", "operator()"]
    assert calls[0]["product_caller_chain"] is None
    assert calls[0]["product_owner_mapping_status"] == "lambda_product_owner_unproven"
    assert counts["lambda_product_owner_unproven"] == 1


def test_macro_expansion_location_does_not_prove_lambda_product_owner(
    tmp_path: Path,
) -> None:
    """Keep macro-expanded lambda calls when physical spelling is unproven.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary directory supplied by pytest.

    Returns
    -------
    None
        Assertions retain raw caller evidence and reject the product mapping.
    """
    source = b"void entry() { auto fn = [&] { expanded(); }; }\n"
    path = tmp_path / "macro-lambda.cpp"
    path.write_bytes(source)
    capture_offset = source.index(b"[&]")
    lambda_node = _lambda_ast_node(
        path,
        source,
        capture_offset,
        [_call_ast_node(path, source, b"expanded")],
    )
    lambda_range = lambda_node["range"]
    assert isinstance(lambda_range, dict)
    raw_begin = lambda_range["begin"]
    assert isinstance(raw_begin, dict)
    lambda_range["begin"] = {"expansionLoc": raw_begin}
    ast: dict[str, object] = {
        "kind": "TranslationUnitDecl",
        "inner": [
            {
                "kind": "FunctionDecl",
                "name": "entry",
                "loc": {"file": str(path), "offset": source.index(b"entry")},
                "inner": [{"kind": "CompoundStmt", "inner": [lambda_node]}],
            }
        ],
    }

    result = normalize_ast(ast, path, source, tmp_path)

    facts = result["facts"]
    counts = result["ungraded_counts"]
    assert isinstance(facts, dict)
    assert isinstance(counts, dict)
    calls = facts["calls"]
    assert isinstance(calls, list)
    assert len(calls) == 1
    assert calls[0]["caller_chain"] == ["entry", "operator()"]
    assert calls[0]["product_caller_chain"] is None
    assert counts["lambda_product_owner_unproven"] == 1


def test_direct_callee_does_not_resolve_function_pointer_variable() -> None:
    """A variable reference does not prove a direct function target.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The assertion verifies the pointer target remains unresolved.
    """
    call: dict[str, object] = {
        "kind": "CallExpr",
        "inner": [
            {
                "kind": "ImplicitCastExpr",
                "inner": [
                    {
                        "kind": "DeclRefExpr",
                        "referencedDecl": {
                            "kind": "VarDecl",
                            "name": "callback",
                            "type": {"qualType": "void (*)()"},
                        },
                    }
                ],
            }
        ],
    }

    assert _direct_callee(call, {}) is None


def test_direct_callee_does_not_resolve_returned_function_pointer_call() -> None:
    """Do not inherit an inner target for an outer indirect call.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The assertion verifies the outer target remains unresolved.
    """
    outer_call: dict[str, object] = {
        "kind": "CallExpr",
        "inner": [
            {
                "kind": "CallExpr",
                "inner": [
                    {
                        "kind": "DeclRefExpr",
                        "referencedDecl": {
                            "kind": "FunctionDecl",
                            "name": "get_callback",
                            "type": {"qualType": "void (*)()"},
                        },
                    }
                ],
            }
        ],
    }

    assert _direct_callee(outer_call, {}) is None


def test_direct_member_call_uses_member_not_base_object_reference() -> None:
    """Resolve the member method and ignore its base declaration.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The assertion verifies the method declaration is selected.
    """
    call: dict[str, object] = {
        "kind": "CXXMemberCallExpr",
        "inner": [
            {
                "kind": "MemberExpr",
                "referencedMemberDecl": "method-id",
                "inner": [
                    {
                        "kind": "DeclRefExpr",
                        "referencedDecl": {
                            "kind": "VarDecl",
                            "name": "object",
                            "type": {"qualType": "Widget"},
                        },
                    }
                ],
            }
        ],
    }
    declarations: dict[str, dict[str, object]] = {
        "method-id": {
            "kind": "CXXMethodDecl",
            "name": "run",
            "type": "void ()",
        }
    }

    assert _direct_callee(call, declarations) == declarations["method-id"]


def test_capture_streams_raw_bytes_to_exclusive_files_before_normalizing(
    tmp_path: Path,
) -> None:
    """Persist subprocess output before normalizing it.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary directory supplied by pytest.

    Returns
    -------
    None
        Assertions validate captured bytes and extractor identity.
    """
    source = b"\n"
    source_path = tmp_path / "sample.c"
    source_path.write_bytes(source)
    stdout_bytes = b'{"kind":"TranslationUnitDecl","inner":[]}'
    stderr_bytes = b""
    identity: dict[str, object] = {
        "selection_id": "TEST-1",
        "original_driver_argv0": "/usr/bin/cc",
        "adapted_argv": ["-std=gnu99", "-fsyntax-only"],
        "source_path": str(source_path),
        "source": source,
        "source_sha256": hashlib.sha256(source).hexdigest(),
        "effective_compiler_path": "/receipt/clang",
        "working_directory": str(tmp_path),
        "profile_path": "/profiles/test.json",
        "profile_sha256": "profile-sha",
        "compile_database_path": "/compile_commands.json",
        "compile_database_sha256": "compile-db-sha",
        "build_receipt_path": "/receipt/build.json",
        "build_receipt_sha256": "receipt-sha",
        "effective_compiler_sha256": "clang-sha",
        "effective_compiler_version": "clang version 22.1.8",
        "resource_dir": "/receipt/resource",
        "resource_probe": "/receipt/resource/stddef.h",
        "resource_probe_sha256": "resource-sha",
        "dependency_count": 1,
        "dependency_closure_status": "complete",
        "coverage_state": "complete",
    }

    def write_result(
        args: list[str],
        *,
        executable: str,
        cwd: str,
        stdout: BinaryIO,
        stderr: BinaryIO,
        check: bool,
        timeout: int,
    ) -> SimpleNamespace:
        """Write test output through the file-backed subprocess interface.

        Parameters
        ----------
        args : list[str]
            Mock command arguments.
        executable : str
            Effective executable supplied to the subprocess.
        cwd : str
            Working directory supplied to the subprocess.
        stdout : typing.BinaryIO
            Stream receiving mocked standard output.
        stderr : typing.BinaryIO
            Stream receiving mocked standard error.
        check : bool
            Whether subprocess errors are configured to raise.
        timeout : int
            Mock execution timeout.

        Returns
        -------
        types.SimpleNamespace
            Mock subprocess result with a successful status.
        """
        assert args[0] == "/usr/bin/cc"
        assert executable == "/receipt/clang"
        assert cwd == str(tmp_path)
        assert check is False
        assert timeout == 900
        stdout.write(stdout_bytes)
        stderr.write(stderr_bytes)
        return SimpleNamespace(returncode=0)

    output_directory = tmp_path / "capture"
    with patch(
        "scripts.clang_reference_facts.subprocess.run", side_effect=write_result
    ) as run:
        result = capture_one(identity, output_directory)

    terminal = result["terminal"]
    assert isinstance(terminal, dict)
    assert run.call_args is not None
    assert "capture_output" not in run.call_args.kwargs
    assert "stdout" in run.call_args.kwargs
    assert "stderr" in run.call_args.kwargs
    raw_stdout = output_directory / "clang-ast.stdout.bin"
    raw_stderr = output_directory / "clang-ast.stderr.bin"
    assert raw_stdout.read_bytes() == stdout_bytes
    assert raw_stderr.read_bytes() == stderr_bytes
    assert terminal["raw_stdout_sha256"] == hashlib.sha256(stdout_bytes).hexdigest()
    assert terminal["raw_stderr_sha256"] == hashlib.sha256(stderr_bytes).hexdigest()
    assert isinstance(terminal["native_duration_seconds"], float)
    terminal_on_disk = json.loads(
        (output_directory / "terminal-record.json").read_text()
    )
    assert terminal_on_disk["reference_extractor_sha256"]
    assert (output_directory / "clang-ast.exit-status.txt").read_text() == "0\n"


def test_capture_launch_error_preserves_terminal_and_status_records(
    tmp_path: Path,
) -> None:
    """Preserve raw files and terminal evidence after launch failure.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary directory supplied by pytest.

    Returns
    -------
    None
        Assertions validate the launch-failure receipt.
    """
    source = b"\n"
    source_path = tmp_path / "sample.c"
    source_path.write_bytes(source)
    identity: dict[str, object] = {
        "selection_id": "TEST-LAUNCH-ERROR",
        "original_driver_argv0": "/usr/bin/cc",
        "adapted_argv": ["-std=gnu99", "-fsyntax-only"],
        "source_path": str(source_path),
        "source": source,
        "source_sha256": hashlib.sha256(source).hexdigest(),
        "effective_compiler_path": "/missing/clang",
        "working_directory": str(tmp_path),
        "profile_path": "/profiles/test.json",
        "profile_sha256": "profile-sha",
        "compile_database_path": "/compile_commands.json",
        "compile_database_sha256": "compile-db-sha",
        "build_receipt_path": "/receipt/build.json",
        "build_receipt_sha256": "receipt-sha",
        "effective_compiler_sha256": "clang-sha",
        "effective_compiler_version": "clang version 22.1.8",
        "resource_dir": "/receipt/resource",
        "resource_probe": "/receipt/resource/stddef.h",
        "resource_probe_sha256": "resource-sha",
        "dependency_count": 1,
        "dependency_closure_status": "complete",
        "coverage_state": "complete",
    }
    output_directory = tmp_path / "launch-error"

    with patch(
        "scripts.clang_reference_facts.subprocess.run",
        side_effect=FileNotFoundError("receipt-bound compiler is unavailable"),
    ):
        result = capture_one(identity, output_directory)

    terminal = result["terminal"]
    assert isinstance(terminal, dict)
    assert terminal["return_code"] is None
    assert terminal["launch_error"] == (
        "FileNotFoundError: receipt-bound compiler is unavailable"
    )
    assert (output_directory / "clang-ast.stdout.bin").read_bytes() == b""
    assert (
        b"receipt-bound compiler is unavailable"
        in (output_directory / "clang-ast.stderr.bin").read_bytes()
    )
    assert (output_directory / "clang-ast.exit-status.txt").read_text() == (
        "launch_error\n"
    )
    assert (output_directory / "terminal-record.json").is_file()
    assert result["normalized"] is None


def test_scope_denominator_is_derived_from_source_joined_rows() -> None:
    """Derive language counts from source-joined scope rows.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The assertion verifies both language strata are counted.
    """
    pilot_rows: list[dict[str, object]] = [
        {
            "selection_id": "C-1",
            "source_path": "/repo/one.c",
            "source_sha256": "c-sha",
            "repository_relative_path": "one.c",
        },
        {
            "selection_id": "CPP-1",
            "source_path": "/repo/two.cpp",
            "source_sha256": "cpp-sha",
            "repository_relative_path": "two.cpp",
        },
    ]
    scope_manifest: dict[str, object] = {
        "cohort_rows": [
            {
                **pilot_rows[0],
                "classification": {"analyzer": "c"},
                "repository": "example",
            },
            {
                **pilot_rows[1],
                "classification": {"analyzer": "cpp"},
                "repository": "example",
            },
        ],
        "cohort_summary": {
            "cohort_rows": 2,
            "language_counts": {"c": 1, "cpp": 1},
        },
    }

    assert _validate_scope_rows(scope_manifest, pilot_rows) == {"c": 1, "cpp": 1}
