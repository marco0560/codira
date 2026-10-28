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
