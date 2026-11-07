"""Contract checks for the isolated Clang frontend pilot adapter."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from pathlib import Path
from typing import cast

import pytest

from scripts.clang_frontend_pilot.adapter import adapt_selection
from scripts.clang_frontend_pilot.build_helper import build_helper
from scripts.clang_frontend_pilot.contract import SCHEMA_VERSION, JSONValue
from scripts.clang_frontend_pilot.run import run_batch

_LLVM_ROOT = Path("/usr/lib/llvm/22")


def _source_hash(path: Path) -> str:
    """Hash a fixture file.

    Parameters
    ----------
    path : pathlib.Path
        Source file.

    Returns
    -------
    str
        SHA-256 digest.
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture(scope="module")
def native_helper(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Build the optional LLVM22 helper once when development libraries exist.

    Parameters
    ----------
    tmp_path_factory : pytest.TempPathFactory
        Pytest factory for disposable test artifacts.

    Returns
    -------
    pathlib.Path
        Built LibTooling executable.

    Raises
    ------
    pytest.skip.Exception
        If this host does not provide the optional LLVM22 SDK.
    """
    compiler = shutil.which("clang++-22")
    if (
        compiler is None
        or not (_LLVM_ROOT / "include/clang/Tooling/Tooling.h").is_file()
        or not (_LLVM_ROOT / "lib64/libclang-cpp.so").is_file()
    ):
        pytest.skip("LLVM22 LibTooling development files are optional")
    directory = tmp_path_factory.mktemp("clang-front-end-build")
    output = directory / "clang_frontend_helper"
    build_helper(
        Path(__file__).parents[1] / "scripts/clang_frontend_pilot/clang_frontend.cpp",
        output,
        compiler,
        _LLVM_ROOT,
    )
    return output


def _selection(source: Path, language: str = "cpp") -> dict[str, JSONValue]:
    """Build a minimal reproducible-profile manifest row for one fixture.

    Parameters
    ----------
    source : pathlib.Path
        Translation unit path.
    language : str, optional
        Fixture language.

    Returns
    -------
    dict[str, JSONValue]
        Typed-compatible selection row.
    """
    root = source.parent.resolve()
    return cast(
        "dict[str, JSONValue]",
        {
            "selection_id": "CFP-TEST-001",
            "population_class": "nonllvm",
            "language": language,
            "repository_id": "fixture",
            "repository_checkout": str(root),
            "repository_revision": "synthetic-test-revision",
            "repository_relative_path": source.name,
            "source_path": str(source.resolve()),
            "source_sha256": _source_hash(source),
            "classification_disposition": "investigate_and_fix",
            "feature_family": "preprocessor_context",
            "family_evidence": {"interpretation": "synthetic test input"},
            "profile_context_status": "reproducible_profile",
            "profile_evidence": {"kind": "synthetic compile command"},
            "context_limitations": [],
        },
    )


def _run_frontend(
    helper: Path,
    root: Path,
    source: Path,
    row: dict[str, JSONValue],
    extra_arguments: list[str] | None = None,
    capture_mode: str = "source_relevant",
) -> dict[str, JSONValue]:
    """Invoke the adapter with one exact compile database command.

    Parameters
    ----------
    helper : pathlib.Path
        Built native helper.
    root : pathlib.Path
        Synthetic repository root.
    source : pathlib.Path
        Translation unit path.
    row : dict[str, JSONValue]
        Source identity row.
    extra_arguments : list[str] or None, optional
        Compiler driver arguments to forward unchanged.
    capture_mode : str, optional
        Frontend output projection scope.

    Returns
    -------
    dict[str, JSONValue]
        Versioned frontend envelope.
    """
    compiler_name = "clang-22" if row.get("language") == "c" else "clang++-22"
    standard = "c17" if row.get("language") == "c" else "c++20"
    compile_row: dict[str, JSONValue] = {
        "directory": str(root.resolve()),
        "file": str(source.resolve()),
        "arguments": [
            str(shutil.which(compiler_name)),
            f"-std={standard}",
            "-DSELECT_THIS=1",
            "-I",
            str(root.resolve()),
            *(extra_arguments or []),
            "-c",
            str(source.resolve()),
            "-o",
            str(root / "ignored.o"),
        ],
    }
    return adapt_selection(
        row,
        {
            "path": "synthetic-manifest.json",
            "sha256": "a" * 64,
            "schema_version": "test",
        },
        [compile_row],
        root,
        helper,
        stderr_path=root / "raw" / f"{source.stem}.{capture_mode}.helper.stderr",
        stdout_path=root / "raw" / f"{source.stem}.{capture_mode}.helper.stdout",
        capture_mode=capture_mode,
    )


def test_libtooling_retains_generated_identities_calls_and_physical_coordinates(
    native_helper: Path, tmp_path: Path
) -> None:
    """Check AST, macro, include, conditional, and coordinate evidence.

    Parameters
    ----------
    native_helper : pathlib.Path
        Built LibTooling helper.
    tmp_path : pathlib.Path
        Disposable repository fixture root.

    Returns
    -------
    None
        Assertions validate the frontend envelope.
    """
    header = tmp_path / "fixture.hpp"
    header.write_text(
        "inline int header_plus(int value) { return value + 1; }\n",
        encoding="utf-8",
    )
    source = tmp_path / "fixture.cpp"
    source_text = (
        "// λ checks byte offsets\n"
        '#include "fixture.hpp"\n'
        "#define DEFINE_FUNCTION(name) int name(int value) { return header_plus(value); }\n"
        "#define CALL_HELPER(value) header_plus(value)\n"
        "namespace demo {\n"
        "DEFINE_FUNCTION(generated_function)\n"
        "}\n"
        "#if defined(SELECT_THIS)\n"
        "int selected_branch(int value) { return value; }\n"
        "#else\n"
        "int unselected_branch(int value) { return value; }\n"
        "#endif\n"
        "template <class T> T identity_template(T value) { return value; }\n"
        "template <class T> T explicit_template(T value);\n"
        "template <> int explicit_template<int>(int value) { return value; }\n"
        "struct Qualified { int method(int value) const & noexcept; };\n"
        "int pilot_calls() { return CALL_HELPER(demo::generated_function(3)) + identity_template(4); }\n"
        "int physical_call() { return demo::generated_function(5); }\n"
    )
    physical_source_text = source_text.replace("\n", "\r\n")
    source.write_bytes(physical_source_text.encode("utf-8"))
    result = _run_frontend(native_helper, tmp_path, source, _selection(source))

    assert result["schema_version"] == SCHEMA_VERSION
    assert result["status"] in {"complete", "partial"}
    frontend = cast("dict[str, JSONValue]", result["frontend"])
    declarations = cast("list[dict[str, JSONValue]]", frontend["declarations"])
    calls = cast("list[dict[str, JSONValue]]", frontend["calls"])
    preprocessing = cast("list[dict[str, JSONValue]]", frontend["preprocessing"])
    includes = cast("list[dict[str, JSONValue]]", frontend["includes"])

    generated = next(
        item
        for item in declarations
        if item["qualified_name"] == "demo::generated_function"
    )
    assert cast("dict[str, JSONValue]", generated["identity"])["kind"] == "written"
    assert generated["signature"] == "int demo::generated_function(int value)"
    generated_location = cast("dict[str, JSONValue]", generated["location"])
    spelling = cast("dict[str, JSONValue]", generated_location["spelling"])
    expansion = cast("dict[str, JSONValue]", generated_location["expansion"])
    assert spelling["path"] == str(source)
    assert expansion["path"] == str(source)
    source_bytes = physical_source_text.encode("utf-8")
    assert b"generated_function" in source_bytes[cast("int", spelling["offset"]) :]

    assert not any(item["name"] == "header_plus" for item in declarations)
    assert any(item["qualified_name"] == "selected_branch" for item in declarations)
    assert not any(
        item["qualified_name"] == "unselected_branch" for item in declarations
    )
    assert any(
        cast("dict[str, JSONValue]", item["identity"])["kind"]
        == "template_instantiation"
        and item["name"] == "identity_template"
        for item in declarations
    )
    specialization = next(
        item
        for item in declarations
        if item["qualified_name"] == "explicit_template"
        and cast("dict[str, JSONValue]", item["identity"])["kind"] == "written"
    )
    assert specialization["decl_kind"] == "function"
    qualified_method = next(
        item for item in declarations if item["qualified_name"] == "Qualified::method"
    )
    assert qualified_method["function_type"]
    assert cast("dict[str, JSONValue]", qualified_method["method_qualifiers"]) == {
        "is_method": True,
        "is_const": True,
        "is_volatile": False,
        "is_static": False,
        "is_virtual": False,
        "is_pure_virtual": False,
        "ref_qualifier": "lvalue",
    }
    assert any(item["spelled_path"] == "fixture.hpp" for item in includes)
    assert any(
        item["kind"] == "conditional" or item["kind"] == "if" for item in preprocessing
    )
    assert any(item["origin"] == "macro_replacement" for item in calls)
    assert any(item["origin"] == "source_written" for item in calls)
    assert any(
        "demo::generated_function" in cast("str", item["source_text"])
        for call in calls
        for item in cast("list[dict[str, JSONValue]]", call["arguments"])
    )
    source_call = next(item for item in calls if item["origin"] == "source_written")
    source_call = next(
        item
        for item in calls
        if item["origin"] == "source_written"
        and cast("dict[str, JSONValue]", item["callee"] or {}).get("qualified_name")
        == "demo::generated_function"
    )
    source_call_location = cast("dict[str, JSONValue]", source_call["location"])
    source_call_spelling = cast(
        "dict[str, JSONValue]", source_call_location["spelling"]
    )
    offset = cast("int", source_call_spelling["offset"])
    assert source_bytes.startswith(b"demo::generated_function", offset)
    prefix = source_bytes[:offset]
    assert source_call_spelling["line"] == prefix.count(b"\n") + 1
    assert source_call_spelling["column"] == offset - (prefix.rfind(b"\n") + 1) + 1
    replacement_call = next(
        item for item in calls if item["origin"] == "macro_replacement"
    )
    replacement_location = cast("dict[str, JSONValue]", replacement_call["location"])
    replacement_spelling = cast(
        "dict[str, JSONValue]", replacement_location["spelling"]
    )
    replacement_expansion = cast(
        "dict[str, JSONValue]", replacement_location["expansion"]
    )
    assert replacement_spelling["offset"] != replacement_expansion["offset"]
    closure = cast("dict[str, JSONValue]", result["dependency_closure"])
    assert any(
        cast("dict[str, JSONValue]", item)["path"] == str(header)
        for item in cast("list[JSONValue]", closure["files"])
    )


def test_missing_context_and_unsupported_flags_are_terminal_holds(
    native_helper: Path, tmp_path: Path
) -> None:
    """Ensure missing profiles and unsafe driver flags stay out of Clang.

    Parameters
    ----------
    native_helper : pathlib.Path
        Built helper that must not run for held inputs.
    tmp_path : pathlib.Path
        Disposable fixture root.

    Returns
    -------
    None
        Assertions validate terminal held outcomes.
    """
    source = tmp_path / "minimal.c"
    source.write_text("int value(void) { return 1; }\n", encoding="utf-8")
    row = _selection(source, "c")
    row["profile_context_status"] = "no_profile"
    held = adapt_selection(
        row,
        {
            "path": "manifest",
            "sha256": "b" * 64,
            "schema_version": "test",
            "compile_commands_sha256": None,
        },
        [],
        tmp_path,
        native_helper,
    )
    assert held["status"] == "held"
    assert held["hold_reasons"] == ["compile_database_missing"]

    row["profile_context_status"] = "reproducible_profile"
    row["original_compile_command"] = None
    bad_command: dict[str, JSONValue] = {
        "directory": str(tmp_path),
        "file": str(source),
        "arguments": [
            str(shutil.which("clang++-22")),
            "-fplugin=/must/not/load.so",
            str(source),
        ],
    }
    unsupported = adapt_selection(
        row,
        {"path": "manifest", "sha256": "c" * 64, "schema_version": "test"},
        [bad_command],
        tmp_path,
        native_helper,
    )
    assert unsupported["status"] == "held"
    assert unsupported["hold_reasons"] == ["unsupported_compile_arguments"]


def test_invalid_syntax_and_missing_include_keep_diagnostics_and_holds(
    native_helper: Path, tmp_path: Path
) -> None:
    """Retain Clang errors and missing include dependency status.

    Parameters
    ----------
    native_helper : pathlib.Path
        Built LibTooling helper.
    tmp_path : pathlib.Path
        Disposable fixture root.

    Returns
    -------
    None
        Assertions verify explicit partial results.
    """
    source = tmp_path / "broken.cpp"
    source.write_text('#include "absent.hpp"\nint broken( {\n', encoding="utf-8")
    result = _run_frontend(native_helper, tmp_path, source, _selection(source))
    assert result["status"] == "partial"
    reasons = cast("list[str]", result["hold_reasons"])
    assert (
        "clang_frontend_reported_errors" in reasons
        or "dependency_closure_incomplete" in reasons
    )
    frontend = cast("dict[str, JSONValue]", result["frontend"])
    diagnostics = cast("list[dict[str, JSONValue]]", frontend["diagnostics"])
    assert any(item["severity"] == "error" for item in diagnostics)
    closure = cast("dict[str, JSONValue]", result["dependency_closure"])
    assert closure["status"] == "incomplete"


def test_checkpoint_keeps_missing_compile_database_in_denominator(
    tmp_path: Path,
) -> None:
    """Checkpoint and resume an explicit missing-context held row.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Disposable repository and evidence root.

    Returns
    -------
    None
        Assertions validate resume identity and source rechecking.
    """
    root = tmp_path / "repo"
    root.mkdir()
    source = root / "source.c"
    source.write_text("int f(void) { return 0; }\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(root), "init", "-q"], check=True, shell=False)
    subprocess.run(["git", "-C", str(root), "add", "source.c"], check=True, shell=False)
    subprocess.run(
        [
            "git",
            "-C",
            str(root),
            "-c",
            "user.name=Codira test",
            "-c",
            "user.email=codira-test@example.invalid",
            "commit",
            "-q",
            "-m",
            "fixture",
        ],
        check=True,
        shell=False,
    )
    revision = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
        shell=False,
    ).stdout.strip()
    row: dict[str, JSONValue] = {
        "selection_id": "CFP-CHECKPOINT",
        "population_class": "nonllvm",
        "language": "c",
        "repository_id": "fixture",
        "repository_checkout": str(root.resolve()),
        "repository_revision": revision,
        "repository_relative_path": "source.c",
        "source_path": str(source.resolve()),
        "source_sha256": _source_hash(source),
        "classification_disposition": "investigate_and_fix",
        "feature_family": "unclassified_open_input",
        "family_evidence": {},
        "profile_context_status": "no_profile",
        "profile_evidence": None,
        "context_limitations": ["No compile profile"],
        "original_compile_command": None,
    }
    manifest: dict[str, JSONValue] = {
        "schema_version": "codira.clang-frontend-pilot-cohort/1",
        "pilot_id": "test",
        "source_snapshot": {"path": "snapshot.jsonl", "sha256": "1" * 64},
        "repositories": {
            "fixture": {"checkout": str(root.resolve()), "pinned_revision": revision}
        },
        "rows": [row],
    }
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    missing_database = tmp_path / "missing-compile_commands.json"
    missing_helper = tmp_path / "missing-helper"
    output = tmp_path / "attempt" / "result.ndjson"
    checkpoint = tmp_path / "attempt" / "checkpoint.json"

    first = run_batch(
        manifest_path, missing_database, root, missing_helper, output, checkpoint
    )
    second = run_batch(
        manifest_path, missing_database, root, missing_helper, output, checkpoint
    )
    assert first["held_count"] == second["held_count"] == 1
    record = json.loads(output.read_text(encoding="utf-8"))
    assert record["status"] == "held"
    assert record["capture_mode"] == "source_relevant"
    assert record["hold_reasons"] == ["compile_database_missing"]
    checkpoint_record = json.loads(checkpoint.read_text(encoding="utf-8"))
    assert checkpoint_record["input_binding"]["capture_mode"] == "source_relevant"
    with pytest.raises(ValueError, match="checkpoint input/producer identity differs"):
        run_batch(
            manifest_path,
            missing_database,
            root,
            missing_helper,
            output,
            checkpoint,
            capture_mode="full",
        )

    source.write_text("int f(void) { return 1; }\n", encoding="utf-8")
    with pytest.raises(ValueError, match="source identity changed"):
        run_batch(
            manifest_path, missing_database, root, missing_helper, output, checkpoint
        )


def test_helper_receipt_cannot_invent_compiler_identity(
    native_helper: Path, tmp_path: Path
) -> None:
    """Hold execution when a helper receipt claims a false compiler hash.

    Parameters
    ----------
    native_helper : pathlib.Path
        Built LibTooling executable with a valid receipt.
    tmp_path : pathlib.Path
        Disposable fixture root.

    Returns
    -------
    None
        The envelope must hold before invoking the helper.
    """
    helper = tmp_path / "helper"
    shutil.copy2(native_helper, helper)
    receipt_path = native_helper.with_name(native_helper.name + ".build.json")
    receipt = cast("dict[str, JSONValue]", json.loads(receipt_path.read_text()))
    receipt["helper_path"] = str(helper.resolve())
    receipt["compiler_sha256"] = "0" * 64
    helper.with_name(helper.name + ".build.json").write_text(
        json.dumps(receipt), encoding="utf-8"
    )
    source = tmp_path / "receipt.cpp"
    source.write_text("int receipt_probe() { return 0; }\n", encoding="utf-8")

    envelope = _run_frontend(helper, tmp_path, source, _selection(source))

    assert envelope["status"] == "held"
    assert envelope["hold_reasons"] == ["helper_build_receipt_toolchain_mismatch"]


def test_c_function_types_preserve_prototype_distinction(
    native_helper: Path, tmp_path: Path
) -> None:
    """Keep C prototype and old-style declarations distinguishable.

    Parameters
    ----------
    native_helper : pathlib.Path
        Built LibTooling executable.
    tmp_path : pathlib.Path
        Disposable C translation unit root.

    Returns
    -------
    None
        Assertions validate exact Clang function types.
    """
    source = tmp_path / "prototype.c"
    source.write_text(
        "int with_prototype(void);\nint old_style();\n",
        encoding="utf-8",
    )
    envelope = _run_frontend(native_helper, tmp_path, source, _selection(source, "c"))
    frontend = cast("dict[str, JSONValue]", envelope["frontend"])
    declarations = cast("list[dict[str, JSONValue]]", frontend["declarations"])
    with_prototype = next(
        item for item in declarations if item["name"] == "with_prototype"
    )
    old_style = next(item for item in declarations if item["name"] == "old_style")
    assert with_prototype["has_prototype"] is True
    assert old_style["has_prototype"] is False
    assert with_prototype["function_type"] != old_style["function_type"]
    assert with_prototype["signature_kind"] == "derived_display_only"


@pytest.mark.parametrize("language", ["c", "cpp"])
def test_generic_common_driver_flags_reach_clang(
    native_helper: Path, tmp_path: Path, language: str
) -> None:
    """Forward common C/C++ warning and codegen flags to the Clang frontend.

    Parameters
    ----------
    native_helper : pathlib.Path
        Built LibTooling executable.
    tmp_path : pathlib.Path
        Disposable fixture root.
    language : str
        Source language under test.

    Returns
    -------
    None
        Assertions verify generic flag forwarding and frontend execution.
    """
    extension = ".c" if language == "c" else ".cpp"
    source = tmp_path / f"common_flags{extension}"
    source.write_text(
        "#include <stddef.h>\nint common_flags_probe(void) { return 1; }\n",
        encoding="utf-8",
    )
    common_flags = [
        "-Wall",
        "-Wextra",
        "-pedantic",
        "-ffunction-sections",
        "-fdata-sections",
        "-w",
        "-fno-common",
        "-O2",
        "-g",
        "-fPIC",
        "-pthread",
        "-openmp",
    ]
    removed_actions = [
        "-MD",
        "-MF",
        str(tmp_path / "deps.d"),
        f"-serialize-diagnostics={tmp_path / 'diagnostics.dia'}",
        f"-foptimization-record-file={tmp_path / 'optimization.yaml'}",
        "-Wl,-z,now",
    ]

    envelope = _run_frontend(
        native_helper,
        tmp_path,
        source,
        _selection(source, language),
        [*common_flags, f"-o{tmp_path / 'ignored-output.o'}", *removed_actions],
    )

    adaptation = cast("dict[str, JSONValue]", envelope["clang_adaptation"])
    argv = cast("list[str]", adaptation["argv"])
    toolchain = cast("dict[str, JSONValue]", adaptation["toolchain"])
    resource_dir = cast("str", toolchain["resource_dir"])
    assert toolchain["resource_query_argv"] == [
        toolchain["compiler_invocation"],
        "-print-resource-dir",
    ]
    assert Path(cast("str", toolchain["resource_probe"])).is_file()
    assert "-resource-dir" in argv
    assert resource_dir in argv
    assert all(flag in argv for flag in common_flags)
    assert f"-o{tmp_path / 'ignored-output.o'}" in argv
    assert not (tmp_path / "ignored-output.o").exists()
    assert all(action not in argv for action in removed_actions)
    ledger = cast("list[dict[str, JSONValue]]", adaptation["transformations"])
    assert any(item["operation"] == "strip_non_frontend_action" for item in ledger)
    assert adaptation["unsupported_context"] == []
    assert (
        cast("dict[str, JSONValue]", envelope["native_execution"])["status"]
        == "completed"
    )
    frontend = cast("dict[str, JSONValue]", envelope["frontend"])
    diagnostics = cast("list[dict[str, JSONValue]]", frontend["diagnostics"])
    closure = cast("dict[str, JSONValue]", envelope["dependency_closure"])
    dependency_rows = cast("list[dict[str, JSONValue]]", closure["files"])
    assert not any(item.get("severity") == "error" for item in diagnostics)
    assert any(
        str(item.get("path")).endswith("/include/stddef.h") for item in dependency_rows
    )


def test_clang_reports_unsupported_ordinary_option_natively(
    native_helper: Path, tmp_path: Path
) -> None:
    """Let Clang diagnose an unsupported ordinary option after AST invocation.

    Parameters
    ----------
    native_helper : pathlib.Path
        Built LibTooling executable.
    tmp_path : pathlib.Path
        Disposable fixture root.

    Returns
    -------
    None
        The option must reach Clang and its diagnostic must be retained.
    """
    source = tmp_path / "unsupported.cpp"
    source.write_text("int unsupported_probe() { return 0; }\n", encoding="utf-8")
    unsupported = "-fthis-option-is-not-supported-by-clang"

    envelope = _run_frontend(
        native_helper, tmp_path, source, _selection(source), [unsupported]
    )

    adaptation = cast("dict[str, JSONValue]", envelope["clang_adaptation"])
    argv = cast("list[str]", adaptation["argv"])
    assert unsupported in argv
    assert adaptation["unsupported_context"] == []
    assert envelope["status"] == "partial"
    frontend = cast("dict[str, JSONValue]", envelope["frontend"])
    diagnostics = cast("list[dict[str, JSONValue]]", frontend["diagnostics"])
    assert any(unsupported in str(item.get("message")) for item in diagnostics)


def test_source_relevant_capture_matches_full_main_facts(
    native_helper: Path, tmp_path: Path
) -> None:
    """Project main-file facts while preserving include and dependency closure.

    Parameters
    ----------
    native_helper : pathlib.Path
        Built LibTooling executable.
    tmp_path : pathlib.Path
        Disposable source/header fixture root.

    Returns
    -------
    None
        Compact and full records must agree on main facts and dependencies.
    """
    header = tmp_path / "projection.hpp"
    header.write_text(
        "#define DECLARE_FROM_HEADER(name) int name(void) { return 2; }\n"
        "#define HEADER_VALUE(value) ((value) + 3)\n"
        "inline int header_only_function(void) { return 1; }\n",
        encoding="utf-8",
    )
    source = tmp_path / "projection.cpp"
    source.write_text(
        '#include "projection.hpp"\n'
        "DECLARE_FROM_HEADER(generated_in_main)\n"
        "int use_header_macro(void) { return HEADER_VALUE(4); }\n",
        encoding="utf-8",
    )
    row = _selection(source)
    compact = _run_frontend(native_helper, tmp_path, source, row)
    full = _run_frontend(native_helper, tmp_path, source, row, capture_mode="full")
    compact_frontend = cast("dict[str, JSONValue]", compact["frontend"])
    full_frontend = cast("dict[str, JSONValue]", full["frontend"])
    compact_declarations = cast(
        "list[dict[str, JSONValue]]", compact_frontend["declarations"]
    )
    full_declarations = cast(
        "list[dict[str, JSONValue]]", full_frontend["declarations"]
    )

    def main_declarations(
        items: list[dict[str, JSONValue]],
    ) -> list[dict[str, JSONValue]]:
        """Select declaration records whose expansion belongs to the main TU.

        Parameters
        ----------
        items : list[dict[str, JSONValue]]
            Captured declaration records.

        Returns
        -------
        list[dict[str, JSONValue]]
            Main-file declaration projection.
        """
        selected = []
        for item in items:
            location_value = cast("dict[str, JSONValue]", item["location"])
            expansion = cast("dict[str, JSONValue]", location_value["expansion"])
            if expansion.get("path") == str(source):
                selected.append(item)
        return selected

    assert compact["capture_mode"] == "source_relevant"
    assert full["capture_mode"] == "full"
    compact_projection = cast(
        "dict[str, JSONValue]", compact_frontend["capture_projection"]
    )
    omitted_declarations = compact_projection["omitted_header_function_declarations"]
    assert isinstance(omitted_declarations, int) and omitted_declarations > 0
    assert main_declarations(compact_declarations) == main_declarations(
        full_declarations
    )
    assert not any(
        item["name"] == "header_only_function" for item in compact_declarations
    )
    assert any(item["name"] == "header_only_function" for item in full_declarations)
    assert compact_frontend["calls"] == full_frontend["calls"]
    compact_includes = cast("list[JSONValue]", compact_frontend["includes"])
    full_includes = cast("list[JSONValue]", full_frontend["includes"])
    assert compact_includes == full_includes
    compact_closure = cast("dict[str, JSONValue]", compact["dependency_closure"])
    full_closure = cast("dict[str, JSONValue]", full["dependency_closure"])
    assert compact_closure == full_closure
    compact_pp = cast("list[dict[str, JSONValue]]", compact_frontend["preprocessing"])
    assert any(
        item.get("kind") == "macro_definition"
        and item.get("name") == "DECLARE_FROM_HEADER"
        for item in compact_pp
    )
    assert any(
        item.get("kind") == "macro_expansion" and item.get("name") == "HEADER_VALUE"
        for item in compact_pp
    )


def test_original_custom_resource_directory_is_held(
    native_helper: Path, tmp_path: Path
) -> None:
    """Do not silently replace an explicit profile resource directory.

    Parameters
    ----------
    native_helper : pathlib.Path
        Built LibTooling executable.
    tmp_path : pathlib.Path
        Disposable fixture root.

    Returns
    -------
    None
        The row must be held before helper execution.
    """
    source = tmp_path / "custom_resource.cpp"
    source.write_text("int custom_resource_probe() { return 0; }\n", encoding="utf-8")

    envelope = _run_frontend(
        native_helper,
        tmp_path,
        source,
        _selection(source),
        ["-resource-dir", "/tmp/custom-clang-resource"],
    )

    assert envelope["status"] == "held"
    assert envelope["hold_reasons"] == [
        "original_resource_directory_differs_from_clang_toolchain"
    ]
    assert not (tmp_path / "raw" / "custom_resource.helper.stdout").exists()


@pytest.mark.parametrize(
    "hazard",
    [
        ["-fplugin=/tmp/codira-pilot-malicious.so"],
        ["-fpass-plugin=/tmp/codira-pilot-malicious.so"],
        ["-Xclang", "-load", "-Xclang", "/tmp/codira-pilot-malicious.so"],
        ["@/tmp/codira-pilot-response.rsp"],
    ],
)
def test_executable_plugins_and_response_files_are_held(
    native_helper: Path, tmp_path: Path, hazard: list[str]
) -> None:
    """Reject executable plugin and response-file command inputs.

    Parameters
    ----------
    native_helper : pathlib.Path
        Built LibTooling executable, which must not be invoked.
    tmp_path : pathlib.Path
        Disposable fixture root.
    hazard : list[str]
        Denied compile arguments.

    Returns
    -------
    None
        The envelope must hold before helper invocation.
    """
    source = tmp_path / "hazard.cpp"
    source.write_text("int hazard_probe() { return 0; }\n", encoding="utf-8")

    envelope = _run_frontend(
        native_helper, tmp_path, source, _selection(source), hazard
    )

    assert envelope["status"] == "held"
    assert envelope["hold_reasons"] == ["unsupported_compile_arguments"]
    assert not (tmp_path / "raw" / "hazard.helper.stdout").exists()
