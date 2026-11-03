"""Grade complete source-authored facts against retained original-file snapshots.

This runner is intentionally fail-closed. It accepts only a complete,
source-authored inventory with an explicit assessment for every fact category,
checks snapshot/source/context bindings, and compares both persisted backends.
Clang AST rows are candidate evidence only when bound to original source bytes;
the final result remains Clang parity rather than compiler-independent truth.

Parameters
----------
None

Returns
-------
None
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import shlex
import sqlite3
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, NoReturn, cast

from scripts.clang_parity_qualification import (
    FACT_CATEGORIES,
    JSONValue,
    OracleCase,
    OracleFormatError,
    _object,
    _string,
    export_database_snapshot,
    grade_snapshot,
    load_oracle,
)
from scripts.clang_reference_facts import (
    REQUIRED_CATEGORIES as REQUIRED_REFERENCE_CATEGORIES,
)

GRADE_SCHEMA = "codira.clang-original-whole-file-grade/1"
if TYPE_CHECKING:
    from codira_clang_frontend.contracts import CompileProfile
    from codira_clang_frontend.frontend import ClangFrontend
SOURCE_FACT_CATEGORIES = frozenset(
    {
        "includes",
        "declarations",
        "fields",
        "enum_members",
        "types",
        "callables",
        "documentation",
        "calls",
        "external_owners",
        "generated_declarations",
    }
)
# Persisted analysis-status checks independently validate coverage only. There
# is currently no machine evaluator that proves the source semantics of any
# authored fact category.
MACHINE_VALIDATED_CATEGORIES = frozenset({"coverage"})


@dataclass(frozen=True)
class SnapshotBindingInput:
    """Inputs needed to validate one exported snapshot's identity."""

    snapshot: dict[str, JSONValue]
    backend: str
    source_key: str
    source_hash: str
    database_binding: dict[str, JSONValue]
    profile_document_hash: str


@dataclass(frozen=True)
class SnapshotExportRequest:
    """All immutable inputs for a two-backend snapshot export."""

    oracle_path: Path
    fixture_root: Path
    database_root: Path
    profile_document: Path
    source_key: str
    database_paths: dict[str, Path]
    receipt_paths: dict[str, Path]
    output_directory: Path


@dataclass(frozen=True)
class AnalysisReceiptRequest:
    """Identity bindings for one persisted per-file status receipt."""

    receipt_path: Path
    backend: str
    source_key: str
    source_hash: str
    source_path: Path
    bindings: dict[str, JSONValue]
    database_binding: dict[str, JSONValue]


@dataclass(frozen=True)
class GradeRequest:
    """Paths and identities required for one complete whole-file grade."""

    contract_path: Path
    oracle_path: Path
    fixture_root: Path
    snapshot_paths: dict[str, Path]
    receipt_paths: dict[str, Path]
    database_bindings: dict[str, dict[str, JSONValue]]
    profile_document: Path


def _fail(context: str, requirement: str) -> NoReturn:
    """Raise a consistently labeled contract error.

    Parameters
    ----------
    context : str
        Contract field or artifact being validated.
    requirement : str
        Required condition that was not met.

    Returns
    -------
    NoReturn
        This function always raises.
    """
    raise OracleFormatError(context, requirement)


def _read_json_object(path: Path, context: str) -> dict[str, JSONValue]:
    """Read one UTF-8 JSON object from a durable input file.

    Parameters
    ----------
    path : pathlib.Path
        JSON input path.
    context : str
        Human-readable input role.

    Returns
    -------
    dict[str, JSONValue]
        Parsed JSON object.
    """
    try:
        value: JSONValue = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        _fail(context, f"cannot read valid JSON: {error}")
    return _object(value, context)


def _sha256(path: Path) -> str:
    """Return the SHA-256 digest of one file.

    Parameters
    ----------
    path : pathlib.Path
        File to hash.

    Returns
    -------
    str
        Lowercase SHA-256 digest.
    """
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _canonical(value: JSONValue) -> str:
    """Serialize a JSON value for deterministic backend parity checks.

    Parameters
    ----------
    value : JSONValue
        Value to encode.

    Returns
    -------
    str
        Stable compact JSON representation.
    """
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _validate_contract(
    contract: dict[str, JSONValue],
    oracle_path: Path,
    fixture_root: Path,
    selected_source: str,
) -> tuple[dict[str, str], dict[str, JSONValue], dict[str, JSONValue]]:
    """Validate a source-authored whole-file contract and its frozen inputs.

    Parameters
    ----------
    contract : dict[str, JSONValue]
        Grade contract document.
    oracle_path : pathlib.Path
        Existing source-fact oracle path.
    fixture_root : pathlib.Path
        Root used to validate source coordinates in that oracle.
    selected_source : str
        Exact relative source path selected for this grade.

    Returns
    -------
    tuple[dict[str, str], dict[str, JSONValue], dict[str, JSONValue]]
        Category states, binding metadata, and the selected source-authored case.
    """
    _validate_contract_header(contract)
    source = _validate_source_binding(
        contract, oracle_path, fixture_root, selected_source
    )
    oracle = load_oracle(oracle_path, fixture_root)
    case = oracle.cases.get(selected_source)
    if case is None:
        _fail("oracle case", f"does not contain {selected_source!r}")
    raw_oracle = _read_json_object(oracle_path, "source-authored oracle")
    raw_cases = _object(raw_oracle.get("cases"), "oracle.cases")
    _validate_controls_against_oracle(contract, raw_cases, fixture_root)
    raw_case = _object(raw_cases.get(selected_source), f"oracle.case.{selected_source}")
    category_states = _validate_category_contract(
        contract, raw_case, case, selected_source
    )
    bindings = _validate_context_bindings(contract)
    _validate_source_fact_accounting(contract, raw_case)
    return category_states, bindings, source


def _validate_controls_against_oracle(
    contract: dict[str, JSONValue],
    raw_cases: dict[str, JSONValue],
    fixture_root: Path,
) -> None:
    """Bind authored positive/negative controls to exact oracle outcomes.

    Positive assertions must be exact source-oracle facts. Negative assertions
    must identify a concrete absent fact in that control's oracle case. A
    separate negative-control pass checks that fact against each persisted
    backend snapshot.

    Parameters
    ----------
    contract : dict[str, JSONValue]
        Whole-file contract with source-authored controls.
    raw_cases : dict[str, JSONValue]
        Serialized source-oracle cases.
    fixture_root : pathlib.Path
        Root of exact oracle source bytes.

    Returns
    -------
    None
    """
    controls_value = contract.get("source_authored_controls")
    if not isinstance(controls_value, list):
        _fail("source_authored_controls", "must be an array")
    for control_index, control_value in enumerate(controls_value):
        control = _object(control_value, f"source_authored_controls[{control_index}]")
        relative_path = _string(control.get("relative_path"), "control.relative_path")
        case_value = raw_cases.get(relative_path)
        if not isinstance(case_value, dict):
            _fail(
                f"source_authored_controls[{control_index}]",
                "control source must have its own oracle case",
            )
        case = case_value
        control_path = Path(_string(control.get("path"), "control.path"))
        fixture_path = (fixture_root / relative_path).resolve()
        if (
            not fixture_path.is_file()
            or fixture_path.read_bytes() != control_path.read_bytes()
        ):
            _fail(
                f"source_authored_controls[{control_index}]",
                "control oracle bytes differ from the bound control file",
            )
        control_cases = control.get("cases")
        if not isinstance(control_cases, list):
            _fail(
                f"source_authored_controls[{control_index}].cases", "must be an array"
            )
        for case_index, value in enumerate(control_cases):
            row = _object(value, f"control[{control_index}].cases[{case_index}]")
            category = _string(row.get("category"), "control case.category")
            polarity = _string(row.get("polarity"), "control case.polarity")
            facts_value = case.get(category)
            if not isinstance(facts_value, list):
                _fail(
                    f"control[{control_index}].cases[{case_index}]",
                    "oracle category must be an explicit array",
                )
            facts = facts_value
            assertion_key = (
                "expected_fact" if polarity == "positive" else "expected_absence"
            )
            assertion = _object(
                row.get(assertion_key),
                f"control[{control_index}].cases[{case_index}].{assertion_key}",
            )
            if assertion.get("category") != category:
                _fail(
                    f"control[{control_index}].cases[{case_index}]",
                    "assertion category differs from its case category",
                )
            if polarity == "positive":
                if assertion not in facts:
                    _fail(
                        f"control[{control_index}].cases[{case_index}]",
                        "positive assertion is not an exact oracle fact",
                    )
                if assertion.get("line") != _object(
                    row.get("source_site"), "control source_site"
                ).get("line"):
                    _fail(
                        f"control[{control_index}].cases[{case_index}]",
                        "positive fact line differs from its physical source site",
                    )
            elif any(
                isinstance(fact, dict)
                and all(
                    fact.get(key) == expected
                    for key, expected in assertion.items()
                    if key != "category"
                )
                for fact in facts
            ):
                _fail(
                    f"control[{control_index}].cases[{case_index}]",
                    "negative assertion is present in the source oracle",
                )


def _negative_control_snapshot_failures(
    contract: dict[str, JSONValue], snapshot: dict[str, JSONValue]
) -> list[dict[str, JSONValue]]:
    """Reject persisted rows that violate source-authored negative controls.

    Parameters
    ----------
    contract : dict[str, JSONValue]
        Validated contract containing source-authored controls.
    snapshot : dict[str, JSONValue]
        One backend's persisted snapshot.

    Returns
    -------
    list[dict[str, JSONValue]]
        Negative control failures observed in this backend snapshot.
    """
    snapshot_cases = _object(snapshot.get("cases"), "snapshot.cases")
    failures: list[dict[str, JSONValue]] = []
    controls = contract.get("source_authored_controls")
    if not isinstance(controls, list):
        _fail("source_authored_controls", "must be an array")
    call_fields = {
        "caller": "caller_qualified_name",
        "definition_line": "callee_definition_line",
        "defined_in": "callee_source",
    }
    for control_index, control_value in enumerate(controls):
        control = _object(control_value, f"source_authored_controls[{control_index}]")
        relative_path = _string(control.get("relative_path"), "control.relative_path")
        control_case = _object(
            snapshot_cases.get(relative_path), f"snapshot.cases.{relative_path}"
        )
        cases = control.get("cases")
        if not isinstance(cases, list):
            _fail(
                f"source_authored_controls[{control_index}].cases", "must be an array"
            )
        for case_index, case_value in enumerate(cases):
            control_case_row = _object(
                case_value, f"control[{control_index}].cases[{case_index}]"
            )
            if control_case_row.get("polarity") != "negative":
                continue
            category = _string(
                control_case_row.get("category"), "control case.category"
            )
            assertion = _object(
                control_case_row.get("expected_absence"),
                f"control[{control_index}].cases[{case_index}].expected_absence",
            )
            rows_value = control_case.get(category, [])
            rows = _as_rows(rows_value, f"snapshot.{relative_path}.{category}")
            for observed in rows:
                matches = True
                for key, expected in assertion.items():
                    if key == "category":
                        continue
                    persisted_key = call_fields.get(key, key)
                    if category == "calls" and key == "target":
                        persisted_key = (
                            "unresolved_target_qualified_name"
                            if observed.get("resolved") is False
                            else "callee_qualified_name"
                        )
                    if observed.get(persisted_key) != expected:
                        matches = False
                        break
                if matches:
                    failures.append(
                        {
                            "case": relative_path,
                            "category": category,
                            "reason": "persisted row violates a source-authored negative control",
                            "expected_absence": assertion,
                        }
                    )
    return failures


def _validate_contract_header(contract: dict[str, JSONValue]) -> None:  # noqa: C901 -- explicit evidence/control contract
    """Validate the independent-oracle contract marker fields.

    Parameters
    ----------
    contract : dict[str, JSONValue]
        Grade contract document.

    Returns
    -------
    None
    """
    if contract.get("schema") != GRADE_SCHEMA:
        _fail("contract.schema", f"must equal {GRADE_SCHEMA!r}")
    if contract.get("source_authored") is not True:
        _fail("contract.source_authored", "must be true")
    method = contract.get("oracle_method")
    if method not in {"manual_source_review", "source_bound_clang_ast_and_controls"}:
        _fail(
            "contract.oracle_method",
            "must be manual source review or source-bound Clang AST plus controls",
        )
    if contract.get("derived_from_helper_output") is not False:
        _fail("contract.derived_from_helper_output", "must be false")
    controls = contract.get("source_authored_controls")
    if not isinstance(controls, list) or not controls:
        _fail(
            "contract.source_authored_controls",
            "must bind at least one authored control",
        )
    controlled_categories: set[str] = set()
    controlled_polarities: dict[str, set[str]] = {
        category: set() for category in SOURCE_FACT_CATEGORIES
    }
    for index, control_value in enumerate(controls):
        control = _object(control_value, f"source_authored_controls[{index}]")
        control_path = Path(_string(control.get("path"), "control.path"))
        _string(
            control.get("relative_path"),
            f"source_authored_controls[{index}].relative_path",
        )
        control_bytes = control_path.read_bytes() if control_path.is_file() else b""
        if control.get("source_authored") is not True:
            _fail(f"source_authored_controls[{index}]", "must be source-authored")
        if not control_path.is_file() or _sha256(control_path) != control.get("sha256"):
            _fail(
                f"source_authored_controls[{index}]",
                "control file is absent or changed",
            )
        categories = control.get("categories")
        if (
            not isinstance(categories, list)
            or not categories
            or not all(
                isinstance(category, str) and category in SOURCE_FACT_CATEGORIES
                for category in categories
            )
        ):
            _fail(
                f"source_authored_controls[{index}].categories",
                "must identify covered fact categories",
            )
        if len(set(categories)) != len(categories):
            _fail(
                f"source_authored_controls[{index}].categories",
                "must not duplicate categories",
            )
        controlled_categories.update(cast("list[str]", categories))
        cases = control.get("cases")
        if not isinstance(cases, list) or not cases:
            _fail(
                f"source_authored_controls[{index}].cases",
                "must contain source-addressed positive and negative assertions",
            )
        for case_index, case_value in enumerate(cases):
            case = _object(
                case_value, f"source_authored_controls[{index}].cases[{case_index}]"
            )
            category = _string(case.get("category"), "control case.category")
            polarity = _string(case.get("polarity"), "control case.polarity")
            if category not in categories or polarity not in {"positive", "negative"}:
                _fail(
                    f"source_authored_controls[{index}].cases[{case_index}]",
                    "case category must be declared and polarity positive or negative",
                )
            site = _object(case.get("source_site"), "control case.source_site")
            _validate_physical_site(
                control_bytes,
                site,
                f"source_authored_controls[{index}].cases[{case_index}].source_site",
            )
            assertion_key = (
                "expected_fact" if polarity == "positive" else "expected_absence"
            )
            assertion = case.get(assertion_key)
            if not isinstance(assertion, dict) or not assertion:
                _fail(
                    f"source_authored_controls[{index}].cases[{case_index}].{assertion_key}",
                    "must contain an explicit authored assertion",
                )
            if polarity == "negative" and len(assertion) < 2:
                _fail(
                    f"source_authored_controls[{index}].cases[{case_index}].expected_absence",
                    "must identify a concrete absent fact",
                )
            controlled_polarities[category].add(polarity)
    if controlled_categories != set(SOURCE_FACT_CATEGORIES):
        _fail(
            "contract.source_authored_controls",
            f"controls must cover every source-fact category; missing={sorted(set(SOURCE_FACT_CATEGORIES) - controlled_categories)}",
        )
    incomplete_controls = sorted(
        category
        for category, polarities in controlled_polarities.items()
        if polarities != {"positive", "negative"}
    )
    if incomplete_controls:
        _fail(
            "contract.source_authored_controls",
            f"each category needs source-addressed positive and negative assertions; incomplete={incomplete_controls}",
        )
    if method == "source_bound_clang_ast_and_controls":
        _validate_reference_capture(contract)


def _validate_reference_capture(contract: dict[str, JSONValue]) -> None:
    """Validate independent Clang AST attempt and raw source bytes.

    Parameters
    ----------
    contract : dict[str, JSONValue]
        Whole-file contract containing the capture binding.

    Returns
    -------
    None
    """
    capture = _object(contract.get("reference_capture"), "contract.reference_capture")
    terminal_path = Path(
        _string(capture.get("terminal_path"), "reference_capture.terminal_path")
    )
    raw_path = Path(
        _string(capture.get("raw_ast_path"), "reference_capture.raw_ast_path")
    )
    stderr_path = Path(
        _string(capture.get("raw_stderr_path"), "reference_capture.raw_stderr_path")
    )
    exit_path = Path(
        _string(capture.get("exit_status_path"), "reference_capture.exit_status_path")
    )
    preflight_path = Path(
        _string(capture.get("preflight_path"), "reference_capture.preflight_path")
    )
    if not terminal_path.is_file() or _sha256(terminal_path) != capture.get(
        "terminal_sha256"
    ):
        _fail("reference_capture.terminal", "terminal record is absent or changed")
    if not raw_path.is_file() or _sha256(raw_path) != capture.get("raw_ast_sha256"):
        _fail("reference_capture.raw_ast", "raw AST bytes are absent or changed")
    if not stderr_path.is_file() or _sha256(stderr_path) != capture.get(
        "raw_stderr_sha256"
    ):
        _fail("reference_capture.raw_stderr", "raw stderr is absent or changed")
    if not exit_path.is_file() or _sha256(exit_path) != capture.get(
        "exit_status_sha256"
    ):
        _fail(
            "reference_capture.exit_status", "terminal exit record is absent or changed"
        )
    if not preflight_path.is_file() or _sha256(preflight_path) != capture.get(
        "preflight_sha256"
    ):
        _fail(
            "reference_capture.preflight",
            "profile adaptation preflight is absent or changed",
        )
    terminal = _read_json_object(terminal_path, "reference capture terminal")
    if (
        terminal.get("capture_kind") != "independent_clang_cli_ast_dump"
        or terminal.get("interpretation")
        != "clang_parity_only_same_compiler_not_compiler_independent_truth"
        or terminal.get("return_code") != 0
        or terminal.get("timed_out") is not False
        or terminal.get("launch_error") is not None
        or terminal.get("raw_stdout_sha256") != capture.get("raw_ast_sha256")
        or terminal.get("raw_stdout_path") != str(raw_path)
        or terminal.get("raw_stdout_bytes") != raw_path.stat().st_size
        or terminal.get("raw_stderr_sha256") != capture.get("raw_stderr_sha256")
        or terminal.get("raw_stderr_path") != str(stderr_path)
        or terminal.get("raw_stderr_bytes") != stderr_path.stat().st_size
        or terminal.get("exit_status_path") != str(exit_path)
        or exit_path.read_text(encoding="utf-8").strip() != "0"
    ):
        _fail(
            "reference_capture",
            "is not a successful, correctly labeled raw Clang AST capture",
        )
    captured_extractor = _object(
        capture.get("captured_extractor"), "reference_capture.captured_extractor"
    )
    captured_extractor_path = _string(
        captured_extractor.get("path"), "captured_extractor.path"
    )
    captured_extractor_hash = _string(
        captured_extractor.get("sha256"), "captured_extractor.sha256"
    )
    if (
        terminal.get("reference_extractor_path") != captured_extractor_path
        or terminal.get("reference_extractor_sha256") != captured_extractor_hash
        or terminal.get("reference_extractor_sha256_after_capture")
        != captured_extractor_hash
        or terminal.get("reference_extractor_changed_during_capture") is not False
    ):
        _fail(
            "reference_capture.captured_extractor",
            "does not match the historical terminal receipt",
        )
    source = _object(contract.get("source"), "contract.source")
    if terminal.get("source_path") != source.get("path") or terminal.get(
        "source_sha256"
    ) != source.get("sha256"):
        _fail("reference_capture", "source identity differs from the selected original")


def _validate_source_binding(
    contract: dict[str, JSONValue],
    oracle_path: Path,
    fixture_root: Path,
    selected_source: str,
) -> dict[str, JSONValue]:
    """Validate source bytes and their source-authored fact oracle binding.

    Parameters
    ----------
    contract : dict[str, JSONValue]
        Grade contract document.
    oracle_path : pathlib.Path
        Source-fact oracle path.
    fixture_root : pathlib.Path
        Root used to validate oracle source coordinates.
    selected_source : str
        Exact source key selected for this grade.

    Returns
    -------
    dict[str, JSONValue]
        Validated source binding.
    """
    source = _object(contract.get("source"), "contract.source")
    if source.get("relative_path") != selected_source:
        _fail("contract.source.relative_path", "does not match selected case")
    source_path = Path(_string(source.get("path"), "contract.source.path"))
    source_hash = _string(source.get("sha256"), "contract.source.sha256")
    if not source_path.is_file() or _sha256(source_path) != source_hash:
        _fail("contract.source", "source file is absent or its digest changed")
    if not (fixture_root / selected_source).is_file():
        _fail("oracle source", "selected source is missing from the oracle root")
    if (fixture_root / selected_source).read_bytes() != source_path.read_bytes():
        _fail("oracle source", "case bytes differ from the independently bound source")
    return source


def _validate_category_contract(
    contract: dict[str, JSONValue],
    raw_case: dict[str, JSONValue],
    case: OracleCase,
    selected_source: str,
) -> dict[str, str]:
    """Validate explicit completeness and applicability for every category.

    Parameters
    ----------
    contract : dict[str, JSONValue]
        Whole-file grade contract.
    raw_case : dict[str, JSONValue]
        Serialized source-authored case, preserving explicit empty arrays.
    case : OracleCase
        Parsed source-authored expected facts.
    selected_source : str
        Source key used in diagnostics.

    Returns
    -------
    dict[str, str]
        Category assessment states.
    """
    category_values = _object(contract.get("categories"), "contract.categories")
    if set(category_values) != set(FACT_CATEGORIES):
        missing = sorted(set(FACT_CATEGORIES) - set(category_values))
        extra = sorted(set(category_values) - set(FACT_CATEGORIES))
        _fail("contract.categories", f"missing={missing}; extra={extra}")
    category_states: dict[str, str] = {}
    for category in FACT_CATEGORIES:
        entry = _object(category_values[category], f"contract.categories.{category}")
        state = _string(entry.get("state"), f"{category}.state")
        _validate_category_state(category, state, entry, raw_case, selected_source)
        category_states[category] = state
    for category, state in category_states.items():
        if (
            category in SOURCE_FACT_CATEGORIES
            and state == "not_applicable"
            and case.facts.get(category)
        ):
            _fail(category, "cannot be not_applicable while source facts are authored")
        if (
            category in SOURCE_FACT_CATEGORIES
            and state == "graded"
            and case.pending_facts.get(category)
        ):
            _fail(category, "contains pending source assertions")
    return category_states


def _validate_category_state(
    category: str,
    state: str,
    entry: dict[str, JSONValue],
    raw_case: dict[str, JSONValue],
    selected_source: str,
) -> None:
    """Validate one category's evidence and fail-closed state.

    Parameters
    ----------
    category : str
        Fact category.
    state : str
        Grade state.
    entry : dict[str, JSONValue]
        Category contract details.
    raw_case : dict[str, JSONValue]
        Serialized source-authored facts.
    selected_source : str
        Source key used in diagnostics.

    Returns
    -------
    None
    """
    basis = entry.get("independent_basis")
    if not isinstance(basis, str) or not basis.strip():
        _fail(
            f"{category}.independent_basis",
            "must explain the independent scope decision",
        )
    if state not in {"graded", "not_applicable", "held"}:
        _fail(f"{category}.state", "must be graded, not_applicable, or held")
    if category == "coverage" and state == "not_applicable":
        _fail("coverage.state", "persisted analysis status is always applicable")
    if category == "forbidden_artifacts" and state == "not_applicable":
        _fail("forbidden_artifacts.state", "negative assertions must be graded or held")
    if category in SOURCE_FACT_CATEGORIES and state != "held":
        if entry.get("inventory_complete") is not True:
            _fail(
                f"{category}.inventory_complete",
                "must be true for a complete inventory",
            )
        if not isinstance(raw_case.get(category), list):
            _fail(
                f"oracle.case.{selected_source}.{category}",
                "must be explicitly listed, including an intentionally empty inventory",
            )
    if state == "held" and not isinstance(entry.get("reason"), str):
        _fail(f"{category}.reason", "is required for a held category")


def _validate_context_bindings(contract: dict[str, JSONValue]) -> dict[str, JSONValue]:
    """Validate compiler, frontend, profile and native-input fingerprints.

    Parameters
    ----------
    contract : dict[str, JSONValue]
        Whole-file grade contract.

    Returns
    -------
    dict[str, JSONValue]
        Validated context binding map.
    """
    bindings = _object(contract.get("bindings"), "contract.bindings")
    required = (
        "profile_path",
        "profile_sha256",
        "compile_database_path",
        "compile_database_sha256",
        "helper_path",
        "helper_sha256",
        "build_receipt_path",
        "build_receipt_sha256",
        "compiler_identity",
        "compiler_argv_sha256",
        "frontend_version",
        "analyzer_version",
        "analysis_context_identity",
        "profile_identity",
        "compiler_version",
        "profile_collection_path",
        "profile_collection_sha256",
    )
    for key in required:
        _string(bindings.get(key), f"contract.bindings.{key}")
    for path_key, digest_key in (
        ("profile_path", "profile_sha256"),
        ("compile_database_path", "compile_database_sha256"),
        ("helper_path", "helper_sha256"),
        ("build_receipt_path", "build_receipt_sha256"),
        ("profile_collection_path", "profile_collection_sha256"),
    ):
        path = Path(cast("str", bindings[path_key]))
        if not path.is_file() or _sha256(path) != bindings[digest_key]:
            _fail(
                f"contract.bindings.{path_key}", "input is absent or its digest changed"
            )
    source = _object(contract.get("source"), "contract.source")
    source_path = Path(_string(source.get("path"), "contract.source.path")).resolve()
    repository_root = Path(
        _string(source.get("repository_root"), "contract.source.repository_root")
    ).resolve()
    if _sha256(source_path) != source.get("sha256"):
        _fail("contract.source.sha256", "source changed before profile validation")
    frontend, profile = _load_bound_frontend_profile(
        bindings, source, source_path, repository_root
    )
    profile_argv = list(profile.argv)
    argv_hash = hashlib.sha256(
        json.dumps(profile_argv, ensure_ascii=False, separators=(",", ":")).encode()
    ).hexdigest()
    if profile_argv[0] != bindings.get("compiler_identity"):
        _fail("contract.bindings.compiler_identity", "does not match captured argv[0]")
    if argv_hash != bindings.get("compiler_argv_sha256"):
        _fail("contract.bindings.compiler_argv_sha256", "does not match profile argv")
    profile_source = Path(profile.source_path).resolve()
    if profile_source != source_path or profile.source_sha256 != source.get("sha256"):
        _fail(
            "contract.bindings.profile",
            "source path or bytes do not match the selected original",
        )
    _validate_compile_database_row(
        Path(cast("str", bindings["compile_database_path"])), profile, source_path
    )
    _validate_composite_profile(
        Path(cast("str", bindings["profile_collection_path"])),
        Path(cast("str", bindings["profile_path"])),
        source_path,
    )
    _validate_loaded_profile_identities(bindings, frontend, profile)
    if contract.get("oracle_method") == "source_bound_clang_ast_and_controls":
        _validate_reference_profile_binding(contract, bindings, profile, source_path)
    return bindings


def _load_bound_frontend_profile(
    bindings: dict[str, JSONValue],
    source: dict[str, JSONValue],
    source_path: Path,
    repository_root: Path,
) -> tuple[ClangFrontend, CompileProfile]:
    """Load a production profile and verify the configured SDK origin.

    Parameters
    ----------
    bindings : dict[str, JSONValue]
        Bound profile, compiler and helper paths.
    source : dict[str, JSONValue]
        Selected original source metadata.
    source_path : pathlib.Path
        Absolute source file path.
    repository_root : pathlib.Path
        Compiler input repository root.

    Returns
    -------
    tuple[object, CompileProfile]
        Frontend instance and loaded captured profile.
    """
    try:
        import codira_clang_frontend
        from codira_clang_frontend import create_frontend_profile
    except ImportError as error:
        _fail("Clang frontend SDK", f"cannot import the configured frontend: {error}")
    expected_module = (
        Path(__file__).resolve().parents[1]
        / "packages/codira-clang-frontend/src/codira_clang_frontend/__init__.py"
    ).resolve()
    if Path(codira_clang_frontend.__file__).resolve() != expected_module:
        _fail("Clang frontend SDK", "module origin does not match this Codira worktree")
    if codira_clang_frontend.__version__ != bindings.get("frontend_version"):
        _fail("contract.bindings.frontend_version", "does not match imported frontend")
    frontend, profile = create_frontend_profile(
        path=source_path,
        root=repository_root,
        language=_string(source.get("language"), "contract.source.language"),
        compile_commands=None,
        captured_profiles=Path(cast("str", bindings["profile_path"])),
        helper_path=Path(cast("str", bindings["helper_path"])),
        build_receipt_path=Path(cast("str", bindings["build_receipt_path"])),
    )
    return frontend, profile


def _validate_loaded_profile_identities(
    bindings: dict[str, JSONValue], frontend: ClangFrontend, profile: CompileProfile
) -> None:
    """Check loaded profile fingerprints against database/query identities.

    Parameters
    ----------
    bindings : dict[str, JSONValue]
        Expected frontend profile and compiler fingerprints.
    frontend : object
        Loaded production frontend.
    profile : CompileProfile
        Loaded exact profile row.

    Returns
    -------
    None
    """
    from codira_clang_frontend import frontend_profile_fingerprint

    build_receipt = Path(cast("str", bindings["build_receipt_path"]))
    receipt = _read_json_object(build_receipt, "build receipt")
    if receipt.get("compiler_version") != bindings.get("compiler_version"):
        _fail("contract.bindings.compiler_version", "does not match the build receipt")
    _validate_profile_identity_pair(
        bindings,
        profile.identity,
        frontend_profile_fingerprint(frontend, profile),
    )


def _validate_profile_identity_pair(
    bindings: dict[str, JSONValue],
    profile_identity: str,
    analysis_context_identity: str,
) -> None:
    """Keep selected profile and frontend context fingerprints distinct.

    Parameters
    ----------
    bindings : dict[str, JSONValue]
        Contract's expected profile and context identities.
    profile_identity : str
        ``CompileProfile.identity`` for the selected source row.
    analysis_context_identity : str
        Current frontend toolchain/context fingerprint.

    Returns
    -------
    None
    """
    if profile_identity != bindings.get("profile_identity"):
        _fail(
            "contract.bindings.profile_identity",
            "does not match the selected captured profile row",
        )
    if analysis_context_identity != bindings.get("analysis_context_identity"):
        _fail(
            "contract.bindings.analysis_context_identity",
            "does not match the loaded profile/toolchain",
        )


def _validate_reference_profile_binding(
    contract: dict[str, JSONValue],
    bindings: dict[str, JSONValue],
    profile: CompileProfile,
    source_path: Path,
) -> None:
    """Bind the AST capture, extractor and source-site inventory to the profile.

    Parameters
    ----------
    contract : dict[str, JSONValue]
        Whole-file contract with reference capture record.
    bindings : dict[str, JSONValue]
        Validated compiler profile bindings.
    profile : CompileProfile
        Exact captured compiler profile.
    source_path : pathlib.Path
        Bound original source path.

    Returns
    -------
    None
    """
    capture = _object(contract.get("reference_capture"), "contract.reference_capture")
    terminal = _read_json_object(
        Path(_string(capture.get("terminal_path"), "reference_capture.terminal_path")),
        "reference capture terminal",
    )
    preflight_path = Path(
        _string(capture.get("preflight_path"), "reference_capture.preflight_path")
    )
    preflight = _read_json_object(preflight_path, "reference adaptation preflight")
    terminal_bindings = {
        "profile_path": str(Path(cast("str", bindings["profile_path"])).resolve()),
        "profile_sha256": bindings["profile_sha256"],
        "compile_database_path": str(
            Path(cast("str", bindings["compile_database_path"])).resolve()
        ),
        "compile_database_sha256": bindings["compile_database_sha256"],
        "build_receipt_path": str(
            Path(cast("str", bindings["build_receipt_path"])).resolve()
        ),
        "build_receipt_sha256": bindings["build_receipt_sha256"],
        "compiler_identity": bindings["compiler_identity"],
    }
    _validate_terminal_bindings(terminal, terminal_bindings)
    _validate_terminal_argv(
        terminal,
        preflight,
        profile,
        source_path,
        _string(capture.get("selection_id"), "reference_capture.selection_id"),
    )
    build_receipt = _read_json_object(
        Path(cast("str", bindings["build_receipt_path"])), "build receipt"
    )
    if (
        Path(
            _string(
                terminal.get("effective_executable"), "terminal.effective_executable"
            )
        ).resolve()
        != Path(
            _string(build_receipt.get("compiler_path"), "build_receipt.compiler_path")
        ).resolve()
        or terminal.get("clang_binary_sha256") != build_receipt.get("compiler_sha256")
        or terminal.get("clang_version_from_receipt")
        != build_receipt.get("compiler_version")
        or terminal.get("resource_dir") != build_receipt.get("resource_dir")
        or terminal.get("resource_probe_sha256")
        != build_receipt.get("resource_probe_sha256")
    ):
        _fail(
            "reference_capture.toolchain",
            "does not match the source-matched build receipt",
        )
    _validate_normalization_and_inventory(contract)


def _validate_terminal_bindings(
    terminal: dict[str, JSONValue], expected_values: dict[str, JSONValue]
) -> None:
    """Compare AST terminal metadata with validated profile inputs.

    Parameters
    ----------
    terminal : dict[str, JSONValue]
        Captured terminal record.
    expected_values : dict[str, JSONValue]
        Exact expected path and compiler values.

    Returns
    -------
    None
    """
    for key, expected in expected_values.items():
        terminal_key = "argv0_original_driver" if key == "compiler_identity" else key
        terminal_value = terminal.get(terminal_key)
        actual = (
            str(Path(terminal_value).resolve())
            if key.endswith("_path") and isinstance(terminal_value, str)
            else terminal_value
        )
        if actual != expected:
            _fail(
                f"reference_capture.{key}",
                "does not match the validated profile/CDB context",
            )


def _validate_terminal_argv(
    terminal: dict[str, JSONValue],
    preflight: dict[str, JSONValue],
    profile: CompileProfile,
    source_path: Path,
    selection_id: str,
) -> None:
    """Check AST argv against the retained profile-adaptation preflight.

    Parameters
    ----------
    terminal : dict[str, JSONValue]
        AST capture terminal record.
    preflight : dict[str, JSONValue]
        Hashed profile API preflight containing exact adapted argv.
    profile : CompileProfile
        Loaded compiler profile.
    source_path : pathlib.Path
        Selected source file.
    selection_id : str
        Immutable source cohort row selected by the capture.

    Returns
    -------
    None
    """
    terminal_argv = terminal.get("argv")
    if not isinstance(terminal_argv, list) or not all(
        isinstance(arg, str) for arg in terminal_argv
    ):
        _fail(
            "reference_capture.argv",
            "must record the exact adapted compiler invocation",
        )
    adapted_rows = preflight.get("selected_profiles_and_exact_adaptations")
    if not isinstance(adapted_rows, list):
        _fail("reference_capture.preflight", "does not contain adapted profile rows")
    rows = [_object(row, "preflight adapted profile") for row in adapted_rows]
    matches = [row for row in rows if row.get("selection_id") == selection_id]
    if len(matches) != 1:
        _fail(
            "reference_capture.preflight", "must identify exactly one selected profile"
        )
    selected = matches[0]
    if (
        selected.get("source") != str(source_path)
        or selected.get("source_sha256") != profile.source_sha256
        or selected.get("original_argv") != list(profile.argv)
        or selected.get("profile_working_directory") != str(profile.working_directory)
    ):
        _fail(
            "reference_capture.preflight",
            "source or original command differs from the loaded profile",
        )
    adapted_argv = selected.get("adapted_clang_argv")
    if not isinstance(adapted_argv, list) or not all(
        isinstance(arg, str) for arg in adapted_argv
    ):
        _fail(
            "reference_capture.preflight", "adapted argv must be an exact string array"
        )
    expected_argv = [
        profile.argv[0],
        *adapted_argv,
        "-Xclang",
        "-ast-dump=json",
        str(source_path),
    ]
    if terminal_argv != expected_argv:
        _fail("reference_capture.argv", "differs from the hashed production preflight")


def _validate_normalization_and_inventory(contract: dict[str, JSONValue]) -> None:
    """Verify the separate, reproducible normalizer and source-site inventory.

    Parameters
    ----------
    contract : dict[str, JSONValue]
        Whole-file grade contract with raw capture and normalization bindings.

    Returns
    -------
    None
    """
    capture = _object(contract.get("reference_capture"), "contract.reference_capture")
    normalization = _object(contract.get("normalization"), "contract.normalization")
    extractor_path = Path(
        _string(normalization.get("extractor_path"), "normalization.extractor_path")
    )
    extractor_hash = _string(
        normalization.get("extractor_sha256"), "normalization.extractor_sha256"
    )
    if not extractor_path.is_file() or _sha256(extractor_path) != extractor_hash:
        _fail("normalization.extractor", "frozen extractor copy is absent or changed")
    normalized_path = Path(
        _string(normalization.get("normalized_path"), "normalization.normalized_path")
    )
    if not normalized_path.is_file() or _sha256(normalized_path) != normalization.get(
        "normalized_sha256"
    ):
        _fail("normalization.output", "normalized facts are absent or changed")
    normalization_record_path = Path(
        _string(normalization.get("record_path"), "normalization.record_path")
    )
    if not normalization_record_path.is_file() or _sha256(
        normalization_record_path
    ) != normalization.get("record_sha256"):
        _fail(
            "normalization.record", "source/raw/extractor binding is absent or changed"
        )
    inventory = _object(
        contract.get("source_site_inventory"), "contract.source_site_inventory"
    )
    inventory_path = Path(_string(inventory.get("path"), "source_site_inventory.path"))
    if not inventory_path.is_file() or _sha256(inventory_path) != inventory.get(
        "sha256"
    ):
        _fail("source_site_inventory", "is absent or changed")
    inventory_receipt = _read_json_object(inventory_path, "source-site inventory")
    source = _object(contract.get("source"), "contract.source")
    bindings = _object(contract.get("bindings"), "contract.bindings")
    _validate_extractor_domain(
        _string(
            _object(capture.get("captured_extractor"), "captured extractor").get(
                "sha256"
            ),
            "captured extractor.sha256",
        ),
        extractor_hash,
        _string(
            inventory_receipt.get("extractor_sha256"), "inventory.extractor_sha256"
        ),
    )
    expected = {
        "source_sha256": source.get("sha256"),
        "raw_ast_sha256": capture.get("raw_ast_sha256"),
        "extractor_sha256": extractor_hash,
        "profile_sha256": bindings.get("profile_sha256"),
        "compile_database_sha256": bindings.get("compile_database_sha256"),
        "normalized_sha256": normalization.get("normalized_sha256"),
        "normalization_record_sha256": normalization.get("record_sha256"),
    }
    for key, expected_value in expected.items():
        if inventory_receipt.get(key) != expected_value:
            _fail(
                f"source_site_inventory.{key}",
                "does not bind this source/capture/context",
            )
    normalization_record = _read_json_object(
        normalization_record_path, "normalization record"
    )
    for key, expected_value in (
        ("source_sha256", source.get("sha256")),
        ("raw_ast_sha256", capture.get("raw_ast_sha256")),
        ("extractor_sha256", extractor_hash),
        ("normalized_sha256", normalization.get("normalized_sha256")),
    ):
        if normalization_record.get(key) != expected_value:
            _fail(
                f"normalization.record.{key}",
                "does not bind this original/capture/extractor",
            )

    normalized = _read_json_object(normalized_path, "normalized reference")
    if normalized.get("whole_file_parity") is not True:
        _fail(
            "normalized reference", "does not establish whole-file source-site parity"
        )
    coverage = _object(
        normalized.get("required_category_coverage"),
        "normalized.required_category_coverage",
    )
    _validate_required_reference_coverage(coverage)
    _validate_normalized_site_accounting(inventory_receipt, normalized)


def _validate_required_reference_coverage(coverage: dict[str, JSONValue]) -> None:
    """Require exact known categories and complete accepted statuses.

    Parameters
    ----------
    coverage : dict[str, JSONValue]
        Normalizer's required-category coverage map.

    Returns
    -------
    None
    """
    if set(coverage) != set(REQUIRED_REFERENCE_CATEGORIES):
        _fail(
            "required_category_coverage",
            "must explicitly cover every required reference category",
        )
    for category, value in coverage.items():
        entry = _object(value, f"required_category_coverage.{category}")
        status = entry.get("status")
        accepted_statuses = (
            {"accepted", "accepted_with_diagnostics"}
            if category == "native_parse_and_diagnostics"
            else {"accepted"}
        )
        if status not in accepted_statuses:
            _fail(f"required_category_coverage.{category}", "remains incomplete")


def _validate_normalized_site_accounting(  # noqa: C901, PLR0912 -- exhaustive reconciliation gates
    inventory: dict[str, JSONValue], normalized: dict[str, JSONValue]
) -> None:
    """Require a one-to-one disposition for every normalized source-site row.

    The normalized capture is partial evidence, so this check does not make it
    independent truth. It prevents an inventory from silently dropping,
    duplicating, or inventing any row the normalizer did emit. Omitted AST
    classes remain held through the separate ungraded-count reconciliation.

    Parameters
    ----------
    inventory : dict[str, JSONValue]
        Source-site inventory receipt bound to this normalized output.
    normalized : dict[str, JSONValue]
        Retained normalized Clang evidence.

    Returns
    -------
    None
    """
    facts = _object(normalized.get("facts"), "normalized.facts")
    declared_categories = {
        key: value for key, value in facts.items() if isinstance(value, list)
    }
    accounting = _object(
        inventory.get("normalized_site_accounting"),
        "source_site_inventory.normalized_site_accounting",
    )
    rows_value = accounting.get("rows")
    if not isinstance(rows_value, list):
        _fail(
            "normalized_site_accounting.rows",
            "must explicitly disposition every normalized row",
        )
    indexed: dict[tuple[str, int], dict[str, JSONValue]] = {}
    source_facts_value = inventory.get("source_fact_accounting")
    if not isinstance(source_facts_value, list):
        _fail(
            "source_fact_accounting",
            "normalized rows need links to source-authored facts",
        )
    source_facts: dict[tuple[str, int], dict[str, JSONValue]] = {}
    for index, value in enumerate(source_facts_value):
        row = _object(value, f"source_fact_accounting[{index}]")
        category = _string(
            row.get("category"), f"source_fact_accounting[{index}].category"
        )
        ordinal = row.get("ordinal")
        if not isinstance(ordinal, int) or isinstance(ordinal, bool) or ordinal < 0:
            _fail(
                f"source_fact_accounting[{index}].ordinal",
                "must be a nonnegative integer",
            )
        key = (category, ordinal)
        if key in source_facts:
            _fail(
                "source_fact_accounting",
                f"duplicate source fact link {category}[{ordinal}]",
            )
        source_facts[key] = row
    for index, value in enumerate(rows_value):
        row = _object(value, f"normalized_site_accounting.rows[{index}]")
        category = _string(row.get("category"), f"site_accounting[{index}].category")
        ordinal_value = row.get("ordinal")
        if (
            not isinstance(ordinal_value, int)
            or isinstance(ordinal_value, bool)
            or ordinal_value < 0
        ):
            _fail(
                f"site_accounting[{index}].ordinal", "must be a nonnegative array index"
            )
        site_id = _string(row.get("site_id"), f"site_accounting[{index}].site_id")
        if row.get("disposition") != "expected":
            _fail(
                f"site_accounting[{index}].disposition",
                "must map to an independently authored source fact; exclusions and holds cannot qualify",
            )
        basis = row.get("basis")
        if not isinstance(basis, str) or not basis.strip():
            _fail(
                f"site_accounting[{index}].basis", "must explain this row disposition"
            )
        key = (category, ordinal_value)
        if key in indexed:
            _fail(
                "normalized_site_accounting",
                f"duplicate normalized row {category}[{ordinal_value}]",
            )
        link = _object(
            row.get("source_fact_link"), f"site_accounting[{index}].source_fact_link"
        )
        source_category = _string(
            link.get("category"), f"site_accounting[{index}].source_fact_link.category"
        )
        normalized_to_oracle_category = {
            "callables": "callables",
            "calls": "calls",
            "declarations": "declarations",
            "fields": "fields",
            "source_call_sites": "calls",
            "types": "types",
        }
        if normalized_to_oracle_category.get(category) != source_category:
            _fail(
                f"site_accounting[{index}].source_fact_link",
                "oracle category does not correspond to the normalized fact category",
            )
        source_ordinal = link.get("ordinal")
        if (
            not isinstance(source_ordinal, int)
            or isinstance(source_ordinal, bool)
            or source_ordinal < 0
        ):
            _fail(
                f"site_accounting[{index}].source_fact_link.ordinal",
                "must be a nonnegative integer",
            )
        source_fact = source_facts.get((source_category, source_ordinal))
        if source_fact is None or source_fact.get("site_id") != site_id:
            _fail(
                f"site_accounting[{index}].source_fact_link",
                "does not resolve to the same inventoried physical source site",
            )
        if link.get("fact_sha256") != source_fact.get("fact_sha256"):
            _fail(
                f"site_accounting[{index}].source_fact_link",
                "source fact digest differs from its inventory row",
            )
        indexed[key] = row

    expected_keys: set[tuple[str, int]] = set()
    for category, category_rows in declared_categories.items():
        for ordinal, fact in enumerate(category_rows):
            key = (category, ordinal)
            expected_keys.add(key)
            row_value = indexed.get(key)
            if row_value is None:
                _fail(
                    "normalized_site_accounting",
                    f"missing disposition for {category}[{ordinal}]",
                )
            row = row_value
            actual_digest = hashlib.sha256(_canonical(fact).encode("utf-8")).hexdigest()
            if row.get("fact_sha256") != actual_digest:
                _fail(
                    f"normalized_site_accounting.{category}[{ordinal}]",
                    "fact digest differs from normalized output",
                )
    extra = sorted(set(indexed) - expected_keys)
    if extra:
        _fail("normalized_site_accounting", f"unmapped inventory rows: {extra[:8]}")

    _validate_ungraded_site_accounting(accounting, indexed, normalized)


def _validate_ungraded_site_accounting(
    accounting: dict[str, JSONValue],
    indexed: dict[tuple[str, int], dict[str, JSONValue]],
    normalized: dict[str, JSONValue],
) -> None:
    """Require every ungraded AST counter to remain an explicit blocker.

    Parameters
    ----------
    accounting : dict[str, JSONValue]
        Normalized site-accounting section.
    indexed : dict[tuple[str, int], dict[str, JSONValue]]
        One-to-one map of normalized facts to inventory rows.
    normalized : dict[str, JSONValue]
        Retained normalized Clang evidence.

    Returns
    -------
    None
    """
    ungraded_counts = _object(
        normalized.get("ungraded_counts"), "normalized.ungraded_counts"
    )
    ungraded_rows_value = accounting.get("ungraded_dispositions")
    if not isinstance(ungraded_rows_value, list):
        _fail(
            "normalized_site_accounting.ungraded_dispositions",
            "must account for every ungraded counter",
        )
    dispositions: dict[str, dict[str, JSONValue]] = {}
    for index, value in enumerate(ungraded_rows_value):
        row = _object(value, f"ungraded_dispositions[{index}]")
        reason = _string(row.get("reason"), f"ungraded_dispositions[{index}].reason")
        if reason in dispositions:
            _fail("ungraded_dispositions", f"duplicate reason {reason!r}")
        count = row.get("count")
        if not isinstance(count, int) or isinstance(count, bool) or count < 0:
            _fail(
                f"ungraded_dispositions[{index}].count", "must be a nonnegative integer"
            )
        if row.get("disposition") not in {"reconciled", "held"}:
            _fail(
                f"ungraded_dispositions[{index}].disposition",
                "must be reconciled or held",
            )
        basis = row.get("basis")
        if not isinstance(basis, str) or not basis.strip():
            _fail(
                f"ungraded_dispositions[{index}].basis",
                "must explain this counter disposition",
            )
        dispositions[reason] = row
    if set(dispositions) != set(ungraded_counts):
        _fail(
            "ungraded_dispositions",
            f"reason set differs; missing={sorted(set(ungraded_counts) - set(dispositions))}; "
            f"extra={sorted(set(dispositions) - set(ungraded_counts))}",
        )
    for reason, count in ungraded_counts.items():
        row_count = dispositions[reason].get("count")
        if row_count != count:
            _fail(
                f"ungraded_dispositions.{reason}",
                "count differs from the normalized receipt",
            )
        if count and dispositions[reason].get("disposition") != "held":
            _fail(
                f"ungraded_dispositions.{reason}",
                "ungraded evidence cannot be marked reconciled",
            )
        if count:
            _fail(
                f"ungraded_dispositions.{reason}",
                "nonzero ungraded evidence keeps AST-based whole-file grading held",
            )
    for key, row in indexed.items():
        if row.get("disposition") == "held":
            _fail("normalized_site_accounting", f"{key[0]}[{key[1]}] remains held")


def _validate_source_fact_accounting(  # noqa: C901, PLR0912 -- exhaustive source binding gates
    contract: dict[str, JSONValue], raw_case: dict[str, JSONValue]
) -> None:
    """Reconcile every authored oracle fact with one inventory site row.

    This verifies internal set equality between the inventory and source oracle;
    independent source review and controls remain necessary to establish that
    the oracle itself is complete.

    Parameters
    ----------
    contract : dict[str, JSONValue]
        Whole-file contract with a hash-bound source-site inventory.
    raw_case : dict[str, JSONValue]
        Serialized selected source facts from the independent oracle.

    Returns
    -------
    None
    """
    inventory_binding = _object(
        contract.get("source_site_inventory"), "contract.source_site_inventory"
    )
    inventory_path = Path(
        _string(inventory_binding.get("path"), "source_site_inventory.path")
    )
    if not inventory_path.is_file() or _sha256(inventory_path) != inventory_binding.get(
        "sha256"
    ):
        _fail("source_site_inventory", "is absent or changed")
    inventory = _read_json_object(inventory_path, "source-site inventory")
    source_binding = _object(contract.get("source"), "contract.source")
    source_path = Path(_string(source_binding.get("path"), "contract.source.path"))
    source_bytes = source_path.read_bytes()
    if hashlib.sha256(source_bytes).hexdigest() != source_binding.get("sha256"):
        _fail(
            "source_fact_accounting", "source changed before coordinate reconciliation"
        )
    if inventory.get("source_sha256") != source_binding.get("sha256"):
        _fail(
            "source_fact_accounting", "inventory does not bind the exact source bytes"
        )
    accounting = inventory.get("source_fact_accounting")
    if not isinstance(accounting, list):
        _fail(
            "source_fact_accounting",
            "must list every source-oracle fact and its physical source site",
        )
    expected: dict[tuple[str, int], str] = {}
    expected_lines: dict[tuple[str, int], int] = {}
    for category in SOURCE_FACT_CATEGORIES:
        values = raw_case.get(category)
        if not isinstance(values, list):
            _fail(
                f"oracle.{category}",
                "must be an explicit array for source-fact accounting",
            )
        for ordinal, value in enumerate(values):
            digest = hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()
            expected[(category, ordinal)] = digest
            if (
                isinstance(value, dict)
                and isinstance(value.get("line"), int)
                and not isinstance(value.get("line"), bool)
            ):
                expected_lines[(category, ordinal)] = cast("int", value["line"])
    observed: dict[tuple[str, int], dict[str, JSONValue]] = {}
    site_coordinates: dict[int, str] = {}
    site_id_coordinates: dict[str, int] = {}
    for index, value in enumerate(accounting):
        row = _object(value, f"source_fact_accounting[{index}]")
        category = _string(
            row.get("category"), f"source_fact_accounting[{index}].category"
        )
        ordinal_value = row.get("ordinal")
        if (
            not isinstance(ordinal_value, int)
            or isinstance(ordinal_value, bool)
            or ordinal_value < 0
        ):
            _fail(
                f"source_fact_accounting[{index}].ordinal",
                "must be a nonnegative integer",
            )
        ordinal = ordinal_value
        key = (category, ordinal)
        if key in observed:
            _fail(
                "source_fact_accounting", f"duplicate source fact {category}[{ordinal}]"
            )
        site_id = _string(
            row.get("site_id"), f"source_fact_accounting[{index}].site_id"
        )
        source_site = row.get("source_site")
        if not isinstance(source_site, dict):
            _fail(
                f"source_fact_accounting[{index}].source_site",
                "must carry the physical source location evidence",
            )
        offset, line, column = _validate_physical_site(
            source_bytes, source_site, f"source_fact_accounting[{index}].source_site"
        )
        prior_id_offset = site_id_coordinates.get(site_id)
        if prior_id_offset is not None and prior_id_offset != offset:
            _fail(
                "source_fact_accounting",
                f"site ID {site_id!r} refers to multiple source coordinates",
            )
        prior_site_id = site_coordinates.get(offset)
        if prior_site_id is not None and prior_site_id != site_id:
            _fail(
                "source_fact_accounting",
                f"different site IDs {prior_site_id!r} and {site_id!r} share one byte coordinate",
            )
        site_id_coordinates[site_id] = offset
        site_coordinates[offset] = site_id
        observed[key] = row
    missing = sorted(set(expected) - set(observed))
    extra = sorted(set(observed) - set(expected))
    if missing or extra:
        _fail("source_fact_accounting", f"missing={missing[:8]}; extra={extra[:8]}")
    for key, expected_digest in expected.items():
        if observed[key].get("fact_sha256") != expected_digest:
            _fail(
                "source_fact_accounting",
                f"{key[0]}[{key[1]}] digest differs from source oracle",
            )
        source_site = _object(
            observed[key].get("source_site"),
            f"source_fact_accounting.{key[0]}[{key[1]}].source_site",
        )
        if key in expected_lines and source_site.get("line") != expected_lines[key]:
            _fail(
                "source_fact_accounting",
                f"{key[0]}[{key[1]}] site line differs from its source fact",
            )
        offset_value = source_site.get("offset")
        if not isinstance(offset_value, int) or isinstance(offset_value, bool):
            _fail(
                "source_fact_accounting",
                f"{key[0]}[{key[1]}] has no physical byte offset",
            )
        category_facts = raw_case.get(key[0])
        if not isinstance(category_facts, list):
            _fail(
                "source_fact_accounting", f"oracle category {key[0]!r} is not an array"
            )
        fact = category_facts[key[1]]
        if isinstance(fact, dict):
            authored_name = fact.get("name")
            token = _string(
                source_site.get("token"),
                f"source_fact_accounting.{key[0]}[{key[1]}].source_site.token",
            )
            if isinstance(authored_name, str) and authored_name not in token:
                _fail(
                    "source_fact_accounting",
                    f"{key[0]}[{key[1]}] source token does not contain the authored fact name",
                )


def _validate_physical_site(
    source_bytes: bytes, site: dict[str, JSONValue], context: str
) -> tuple[int, int, int]:
    """Validate an offset, line, and byte-column against exact source bytes.

    Parameters
    ----------
    source_bytes : bytes
        Exact source bytes bound by the surrounding contract.
    site : dict[str, JSONValue]
        Physical coordinate row with zero-based byte offset and one-based line/column.
    context : str
        Error context.

    Returns
    -------
    tuple[int, int, int]
        Validated offset, line, and byte column.
    """
    offset_value = site.get("offset")
    line_value = site.get("line")
    column_value = site.get("column")
    if (
        not isinstance(offset_value, int)
        or isinstance(offset_value, bool)
        or not 0 <= offset_value < len(source_bytes)
    ):
        _fail(f"{context}.offset", "must be a byte offset inside the source")
    if (
        not isinstance(line_value, int)
        or isinstance(line_value, bool)
        or line_value < 1
    ):
        _fail(f"{context}.line", "must be a positive physical line")
    if (
        not isinstance(column_value, int)
        or isinstance(column_value, bool)
        or column_value < 1
    ):
        _fail(f"{context}.column", "must be a positive byte column")
    prefix = source_bytes[:offset_value]
    actual_line = prefix.count(b"\n") + 1
    line_start = prefix.rfind(b"\n") + 1
    actual_column = offset_value - line_start + 1
    if (line_value, column_value) != (actual_line, actual_column):
        _fail(
            context,
            f"coordinate {(line_value, column_value)} disagrees with byte offset {offset_value} "
            f"at {(actual_line, actual_column)}",
        )
    token = _string(site.get("token"), f"{context}.token")
    token_bytes = token.encode("utf-8")
    if source_bytes[offset_value : offset_value + len(token_bytes)] != token_bytes:
        _fail(
            f"{context}.token",
            "does not match original source bytes at the bound offset",
        )
    return offset_value, line_value, column_value


def _validate_extractor_domain(
    captured_extractor_sha256: str,
    normalization_extractor_sha256: str,
    inventory_extractor_sha256: str,
) -> None:
    """Keep original AST-capture and fresh-normalizer extractor identities distinct.

    Parameters
    ----------
    captured_extractor_sha256 : str
        Extractor hash recorded when the independent AST bytes were captured.
    normalization_extractor_sha256 : str
        Frozen extractor hash used to normalize those raw AST bytes.
    inventory_extractor_sha256 : str
        Extractor hash asserted by the source-site inventory.

    Returns
    -------
    None
    """
    if not captured_extractor_sha256 or not normalization_extractor_sha256:
        _fail("extractor identity", "capture and normalization hashes must be explicit")
    if inventory_extractor_sha256 != normalization_extractor_sha256:
        _fail(
            "source_site_inventory.extractor_sha256",
            "does not match the fresh normalizer",
        )


def _validate_compile_database_row(
    compile_database_path: Path, profile: CompileProfile, source_path: Path
) -> None:
    """Bind a captured profile to the exact compile-database command row.

    Parameters
    ----------
    compile_database_path : pathlib.Path
        Hashed compilation database from the grade contract.
    profile : object
        Loaded frontend profile from the production profile loader.
    source_path : pathlib.Path
        Exact translation unit selected for grading.

    Returns
    -------
    None
    """
    if not compile_database_path.is_file():
        _fail("compile database", "is absent")
    try:
        rows_value: JSONValue = json.loads(
            compile_database_path.read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError) as error:
        _fail("compile database", f"cannot read valid JSON: {error}")
    if not isinstance(rows_value, list):
        _fail("compile database", "must be an array")
    matches: list[dict[str, JSONValue]] = []
    for index, value in enumerate(rows_value):
        row = _object(value, f"compile database[{index}]")
        filename = row.get("file")
        command_directory = row.get("directory")
        if not isinstance(filename, str) or not isinstance(command_directory, str):
            continue
        resolved_file = Path(filename)
        if not resolved_file.is_absolute():
            resolved_file = Path(command_directory) / resolved_file
        if resolved_file.resolve() == source_path.resolve():
            matches.append(row)
    if len(matches) != 1:
        _fail(
            "compile database",
            "must contain exactly one command for the selected source",
        )
    row = matches[0]
    compile_directory = Path(
        _string(row.get("directory"), "compile database.directory")
    ).resolve()
    profile_directory = Path(profile.working_directory).resolve()
    if compile_directory != profile_directory:
        _fail(
            "compile database.directory",
            "does not match the captured profile working directory",
        )
    if "arguments" in row:
        command = row["arguments"]
        if not isinstance(command, list) or not all(
            isinstance(part, str) for part in command
        ):
            _fail("compile database.arguments", "must be a string array")
        argv = cast("list[str]", command)
    else:
        argv = shlex.split(_string(row.get("command"), "compile database.command"))
    profile_argv = list(profile.argv)
    if argv != profile_argv:
        _fail("compile database command", "does not match the captured profile argv")


def _validate_composite_profile(
    collection_path: Path, selected_profile_path: Path, source_path: Path
) -> None:
    """Require a combined profile collection to contain the exact selected row.

    Parameters
    ----------
    collection_path : pathlib.Path
        Combined profile document used during indexing.
    selected_profile_path : pathlib.Path
        Source-specific profile artifact used to load the profile.
    source_path : pathlib.Path
        Exact source path selected for analysis.

    Returns
    -------
    None
    """
    collection = _read_json_object(collection_path, "profile collection")
    selected_document = _read_json_object(selected_profile_path, "selected profile")
    collection_rows = collection.get("profiles")
    selected_rows = selected_document.get("profiles")
    if not isinstance(collection_rows, list) or not isinstance(selected_rows, list):
        _fail("profile collection", "must contain profile arrays")
    selected_row_matches = [
        _object(row, "selected profile row")
        for row in selected_rows
        if isinstance(row, dict) and row.get("source_path") == str(source_path)
    ]
    collection_row_matches = [
        _object(row, "profile collection row")
        for row in collection_rows
        if isinstance(row, dict) and row.get("source_path") == str(source_path)
    ]
    if len(selected_row_matches) != 1 or len(collection_row_matches) != 1:
        _fail(
            "profile collection", "must contain exactly one selected original profile"
        )
    if selected_row_matches[0] != collection_row_matches[0]:
        _fail(
            "profile collection",
            "selected original profile row differs from the indexed collection",
        )


def _validate_snapshot_binding(
    inputs: SnapshotBindingInput,
) -> dict[str, JSONValue]:
    """Require backend snapshot to contain the exact selected source bytes.

    Parameters
    ----------
    inputs : SnapshotBindingInput
        Exported snapshot and its source, generation, and profile bindings.

    Returns
    -------
    dict[str, JSONValue]
        Selected source rows from the snapshot.
    """
    snapshot = inputs.snapshot
    if (
        snapshot.get("snapshot_version") != 1
        or snapshot.get("backend") != inputs.backend
    ):
        _fail("snapshot", f"expected version 1 backend {inputs.backend}")
    cases = _object(snapshot.get("cases"), f"{inputs.backend}.cases")
    case = _object(
        cases.get(inputs.source_key), f"{inputs.backend}.case.{inputs.source_key}"
    )
    if case.get("source_sha256") != inputs.source_hash:
        _fail(
            f"{inputs.backend}.case.source_sha256",
            "does not match the source-authored binding",
        )
    if snapshot.get("database_binding") != inputs.database_binding:
        _fail(
            f"{inputs.backend}.snapshot.database_binding",
            "does not match the actual database",
        )
    if snapshot.get("profile_document_sha256") != inputs.profile_document_hash:
        _fail(
            f"{inputs.backend}.snapshot.profile_document_sha256",
            "profile document changed",
        )
    _string(
        case.get("analysis_input_fingerprint"),
        f"{inputs.backend}.case.analysis_input_fingerprint",
    )
    return case


def _database_json_value(value: object, context: str) -> JSONValue:
    """Parse one JSON-encoded analysis-status field read from a backend."""
    if isinstance(value, str):
        try:
            parsed: JSONValue = json.loads(value)
        except json.JSONDecodeError as error:
            _fail(context, f"database value is not valid JSON: {error}")
        return parsed
    if isinstance(value, (dict, list, int, float, bool)) or value is None:
        return cast("JSONValue", value)
    _fail(context, "database value has an unsupported type")


def _read_actual_analysis_status(
    database_path: Path, backend: str, source_path: Path, source_hash: str
) -> dict[str, JSONValue]:
    """Read selected analysis status directly from the persisted database.

    Parameters
    ----------
    database_path : pathlib.Path
        Exact persisted backend database.
    backend : str
        Backend name.
    source_path : pathlib.Path
        Absolute physical source path stored by the indexer.
    source_hash : str
        Expected source bytes.

    Returns
    -------
    dict[str, JSONValue]
        Persisted analyzer identity and status fields.
    """
    if backend == "sqlite":
        connection: Any = sqlite3.connect(
            f"file:{database_path.resolve()}?mode=ro", uri=True
        )
    elif backend == "duckdb":
        duckdb = importlib.import_module("duckdb")
        connection = duckdb.connect(str(database_path.resolve()), read_only=True)
    else:
        _fail("backend", "must be sqlite or duckdb")
    try:
        rows = connection.execute(
            "SELECT files.hash, files.analyzer_name, files.analyzer_version, "
            "analysis_status.grammar, analysis_status.target_contract, "
            "analysis_status.reliable_categories, analysis_status.omitted_categories, "
            "analysis_status.coverage_state "
            "FROM files JOIN analysis_status ON analysis_status.path = files.path "
            "WHERE files.path = ?",
            [str(source_path.resolve())],
        ).fetchall()
        if len(rows) != 1:
            _fail(
                f"{backend} analysis status",
                "database must contain exactly one joined source/status row",
            )
        (
            source_digest,
            analyzer_name,
            analyzer_version,
            grammar,
            target,
            reliable,
            omitted,
            coverage,
        ) = rows[0]
        if source_digest != source_hash:
            _fail(
                f"{backend} analysis status",
                "database source hash differs from the source binding",
            )
        if not all(
            isinstance(value, str) and value
            for value in (analyzer_name, analyzer_version, grammar, coverage)
        ):
            _fail(
                f"{backend} analysis status",
                "database analyzer or status identity is incomplete",
            )
        target_value = _database_json_value(target, f"{backend}.target_contract")
        reliable_value = _database_json_value(
            reliable, f"{backend}.reliable_categories"
        )
        omitted_value = _database_json_value(omitted, f"{backend}.omitted_categories")
        if (
            not isinstance(target_value, dict)
            or not isinstance(reliable_value, list)
            or not isinstance(omitted_value, list)
        ):
            _fail(
                f"{backend} analysis status",
                "database JSON status fields have invalid shapes",
            )
        return {
            "source_sha256": source_digest,
            "analyzer_name": analyzer_name,
            "analyzer_version": analyzer_version,
            "grammar": grammar,
            "target_contract": target_value,
            "reliable_categories": reliable_value,
            "omitted_categories": omitted_value,
            "coverage_state": coverage,
        }
    finally:
        connection.close()


def _read_indexed_context_identity(
    backend: str,
    database_path: Path,
    database_root: Path,
    source_key: str,
    source_hash: str,
) -> str:
    """Read the selected file's exact stored analyzer-context fingerprint.

    Parameters
    ----------
    backend : str
        Persisted structural backend name.
    database_path : pathlib.Path
        Exact SQLite or DuckDB index file.
    database_root : pathlib.Path
        Root path used by the indexer for this source repository.
    source_key : str
        Repository-relative file key.
    source_hash : str
        Source-byte digest expected from the independent source binding.

    Returns
    -------
    str
        Persisted per-file analysis-input fingerprint.
    """
    if backend == "sqlite":
        connection: Any = sqlite3.connect(
            f"file:{database_path.resolve()}?mode=ro", uri=True
        )
    elif backend == "duckdb":
        duckdb = importlib.import_module("duckdb")
        connection = duckdb.connect(str(database_path.resolve()), read_only=True)
    else:
        _fail("backend", "must be sqlite or duckdb")
    try:
        source_path = str((database_root / source_key).resolve())
        rows = connection.execute(
            "SELECT hash, analysis_input_fingerprint FROM files WHERE path = ?",
            [source_path],
        ).fetchall()
        if len(rows) != 1:
            _fail(f"{backend} target context", "must have exactly one indexed file row")
        actual_source_hash, context_identity = rows[0]
        if actual_source_hash != source_hash:
            _fail(
                f"{backend} target context",
                "indexed source hash differs from the bound original",
            )
        if not isinstance(context_identity, str) or not context_identity:
            _fail(f"{backend} target context", "indexed context fingerprint is absent")
        return context_identity
    finally:
        connection.close()


def _validate_indexed_context_identity(
    backend: str, context_identity: str, frontend_identity: str
) -> dict[str, JSONValue]:
    """Bind the persisted target fingerprint to the selected frontend profile.

    Parameters
    ----------
    backend : str
        Backend owning the target row.
    context_identity : str
        Exact ``files.analysis_input_fingerprint`` JSON value.
    frontend_identity : str
        Recomputed frontend/toolchain fingerprint for the selected profile.

    Returns
    -------
    dict[str, JSONValue]
        Parsed target context fields for the grade report.
    """
    try:
        value: JSONValue = json.loads(context_identity)
    except json.JSONDecodeError as error:
        _fail(f"{backend} target context", f"is not valid fingerprint JSON: {error}")
    context = _object(value, f"{backend} target context")
    if context.get("clang_frontend_fingerprint") != frontend_identity:
        _fail(
            f"{backend} target context",
            "frontend fingerprint differs from the selected profile",
        )
    return context


def _database_generation_binding(
    database_path: Path, backend: str
) -> dict[str, JSONValue]:
    """Read and hash the actual database, metadata and generation identity.

    Parameters
    ----------
    database_path : pathlib.Path
        Persisted SQLite or DuckDB database.
    backend : str
        Expected backend name.

    Returns
    -------
    dict[str, JSONValue]
        Exact database path/hash, metadata and generation fingerprints.
    """
    if not database_path.is_file():
        _fail(f"{backend} database", "database file is absent")
    database = database_path.resolve()
    metadata_path = database.parent / "metadata.json"
    generation_path = database.parent / "index-generation.json"
    metadata = _read_json_object(metadata_path, f"{backend} metadata")
    generation = _read_json_object(generation_path, f"{backend} generation")
    if (
        metadata.get("backend_name") != backend
        or generation.get("backend_name") != backend
    ):
        _fail(f"{backend} database", "metadata or generation names a different backend")
    analysis_fingerprint = _string(
        generation.get("analysis_fingerprint"), f"{backend}.analysis_fingerprint"
    )
    generation_number = generation.get("generation")
    if not isinstance(generation_number, int) or isinstance(generation_number, bool):
        _fail(f"{backend}.generation", "must be an integer")
    return {
        "backend": backend,
        "database_path": str(database),
        "database_sha256": _sha256(database),
        "metadata_path": str(metadata_path.resolve()),
        "metadata_sha256": _sha256(metadata_path),
        "generation_path": str(generation_path.resolve()),
        "generation_sha256": _sha256(generation_path),
        "generation": generation_number,
        "analysis_fingerprint": analysis_fingerprint,
        "analyzer_inventory": generation.get("analyzer_inventory"),
        "schema_version": metadata.get("schema_version"),
        "git_commit": _string(generation.get("git_commit"), f"{backend}.git_commit"),
    }


def _validate_receipt_database_binding(
    receipt: dict[str, JSONValue], backend: str, binding: dict[str, JSONValue]
) -> None:
    """Require the backend receipt to identify the same database generation.

    Parameters
    ----------
    receipt : dict[str, JSONValue]
        Backend qualification receipt.
    backend : str
        Expected backend.
    binding : dict[str, JSONValue]
        Filesystem-derived database and generation binding.

    Returns
    -------
    None
    """
    section_name = "index" if backend == "sqlite" else "duckdb"
    section = _object(receipt.get(section_name), f"{backend} receipt.{section_name}")
    generation = section.get("generation")
    if isinstance(generation, dict):
        generation = generation.get("generation")
    actuals = {
        "database_path": section.get("database_path"),
        "database_sha256": section.get("database_sha256"),
        "generation": generation,
    }
    for field, actual in actuals.items():
        if field == "database_path" and isinstance(actual, str):
            receipt_path = Path(actual)
            if not receipt_path.is_absolute():
                receipt_path = Path(__file__).resolve().parents[1] / receipt_path
            actual = str(receipt_path.resolve())
        if actual != binding.get(field):
            _fail(f"{backend} receipt.{field}", "does not match the opened database")
    if backend == "sqlite":
        generation_sha = section.get("generation_sha256")
    else:
        generation_sha = section.get("generation_sha256")
    if generation_sha != binding.get("generation_sha256"):
        _fail(
            f"{backend} receipt.generation_sha256", "does not match the generation file"
        )
    metadata_sha = section.get("metadata_sha256")
    if metadata_sha != binding.get("metadata_sha256"):
        _fail(
            f"{backend} receipt.metadata_sha256", "does not match the backend metadata"
        )
    generation_data = _object(section.get("generation"), f"{backend}.generation")
    for field in ("analysis_fingerprint", "analyzer_inventory", "git_commit"):
        if generation_data.get(field) != binding.get(field):
            _fail(
                f"{backend} receipt.{field}", "does not match the database generation"
            )
    if section.get("schema_version") != binding.get("schema_version"):
        _fail(f"{backend} receipt.schema_version", "does not match backend metadata")


def export_bound_database_snapshots(
    request: SnapshotExportRequest,
) -> tuple[dict[str, Path], dict[str, dict[str, JSONValue]]]:
    """Export read-only database snapshots with verified generation bindings.

    Parameters
    ----------
    request : SnapshotExportRequest
        Oracle, repository, database, profile and output path bindings.

    Returns
    -------
    tuple[dict[str, pathlib.Path], dict[str, dict[str, JSONValue]]]
        Snapshot paths and database generation bindings.
    """
    if set(request.database_paths) != {"sqlite", "duckdb"} or set(
        request.receipt_paths
    ) != {
        "sqlite",
        "duckdb",
    }:
        _fail("backend inputs", "must include exactly SQLite and DuckDB")
    profile_hash = _sha256(request.profile_document)
    oracle = load_oracle(request.oracle_path, request.fixture_root)
    request.output_directory.mkdir(parents=True, exist_ok=False)
    snapshots: dict[str, Path] = {}
    bindings: dict[str, dict[str, JSONValue]] = {}
    for backend in ("sqlite", "duckdb"):
        database_path = request.database_paths[backend]
        before = _database_generation_binding(database_path, backend)
        receipt = _read_json_object(
            request.receipt_paths[backend], f"{backend} receipt"
        )
        _validate_receipt_database_binding(receipt, backend, before)
        snapshot = export_database_snapshot(
            backend,
            database_path,
            request.database_root,
            oracle,
            request.profile_document,
        )
        target_case = _object(
            _object(snapshot.get("cases"), f"{backend} snapshot cases").get(
                request.source_key
            ),
            f"{backend} target case",
        )
        target_source_hash = _string(
            target_case.get("source_sha256"), f"{backend}.source_sha256"
        )
        target_case["analysis_input_fingerprint"] = _read_indexed_context_identity(
            backend,
            database_path,
            request.database_root,
            request.source_key,
            target_source_hash,
        )
        after = _database_generation_binding(database_path, backend)
        if before != after:
            _fail(f"{backend} database", "changed during read-only snapshot export")
        snapshot["database_binding"] = before
        snapshot["profile_document_sha256"] = profile_hash
        snapshot_path = request.output_directory / f"{backend}-snapshot.json"
        encoded = json.dumps(snapshot, indent=2, sort_keys=True) + "\n"
        with snapshot_path.open("x", encoding="utf-8") as output:
            output.write(encoded)
        snapshots[backend] = snapshot_path
        bindings[backend] = before
    return snapshots, bindings


def _validate_analysis_receipt(
    request: AnalysisReceiptRequest,
) -> dict[str, JSONValue]:
    """Read and validate the retained per-file analyzer status for a backend.

    Parameters
    ----------
    request : AnalysisReceiptRequest
        Receipt plus exact source, profile and database generation bindings.

    Returns
    -------
    dict[str, JSONValue]
        Actual retained status row for the selected source.
    """
    receipt = _read_json_object(
        request.receipt_path, f"{request.backend} analysis receipt"
    )
    _validate_receipt_database_binding(
        receipt, request.backend, request.database_binding
    )
    rows_value = _analysis_rows_from_receipt(receipt, request.backend, request.bindings)
    rows = _as_rows(rows_value, f"{request.backend} receipt files")
    matches = [row for row in rows if row.get("path") == request.source_key]
    if len(matches) != 1:
        _fail(
            f"{request.backend} analysis receipt",
            "must contain exactly one selected source row",
        )
    row = matches[0]
    database_path = Path(
        _string(
            request.database_binding.get("database_path"),
            "database_binding.database_path",
        )
    )
    persisted = _read_actual_analysis_status(
        database_path, request.backend, request.source_path, request.source_hash
    )
    if persisted.get("analyzer_name") != "cpp":
        _fail(
            f"{request.backend} source status",
            "database row is not owned by the C++ analyzer",
        )
    if (
        persisted.get("coverage_state") != "complete"
        or persisted.get("omitted_categories") != []
    ):
        _fail(
            f"{request.backend} source status",
            "persisted database status is incomplete or omits categories",
        )
    if persisted.get("analyzer_version") != request.bindings.get("analyzer_version"):
        _fail(
            f"{request.backend} analyzer version",
            "persisted database version differs from the grade contract",
        )
    _validate_persisted_clang_identity(
        persisted,
        request.bindings,
        request.source_path,
        request.source_hash,
        request.backend,
    )
    _validate_persisted_status_claims(row, persisted, request.backend)
    if row.get("attempt_status") != "parsed":
        _fail(
            f"{request.backend} source status",
            "receipt does not report a parsed attempt",
        )
    if row.get("frontend") != "clang":
        _fail(
            f"{request.backend} source status",
            "receipt does not report the Clang frontend",
        )
    if row.get("profile_identity") != request.bindings.get("profile_identity"):
        _fail(
            f"{request.backend} profile identity",
            "does not match the selected compile profile",
        )
    if row.get("analyzer_version") != request.bindings.get("analyzer_version"):
        _fail(
            f"{request.backend} analyzer version", "does not match the grade contract"
        )
    expected_compiler = request.bindings.get("compiler_version")
    actual_compiler = row.get("compiler_version")
    if actual_compiler != expected_compiler:
        _fail(
            f"{request.backend} compiler version", "does not match the grade contract"
        )
    if request.backend == "sqlite":
        if row.get("helper_sha256") != request.bindings.get("helper_sha256"):
            _fail("sqlite helper identity", "does not match the grade contract")
        if row.get("profile_sha256") != request.bindings.get("profile_sha256"):
            _fail("sqlite profile digest", "does not match the grade contract")
    return row


def _validate_persisted_status_claims(
    receipt_row: dict[str, JSONValue], persisted: dict[str, JSONValue], backend: str
) -> None:
    """Require receipt status claims to match the actual database row.

    Parameters
    ----------
    receipt_row : dict[str, JSONValue]
        Selected per-file row from the retained run receipt.
    persisted : dict[str, JSONValue]
        Selected per-file status read from SQLite or DuckDB.
    backend : str
        Backend name used in diagnostics.

    Returns
    -------
    None
    """
    for field in (
        "source_sha256",
        "coverage_state",
        "omitted_categories",
        "grammar",
        "reliable_categories",
    ):
        if receipt_row.get(field) != persisted.get(field):
            _fail(
                f"{backend} source status.{field}",
                "receipt claim differs from the persisted database row",
            )


def _hold_categories_without_machine_semantics(
    category_states: dict[str, str],
) -> set[str]:
    """Hold every category without an independent semantic evaluator.

    Source-authored assertions and backend parity establish what the contract
    claims and whether both indexes agree. They do not independently prove
    that the claimed source semantics are complete. Until a category-specific
    machine evaluator is implemented, those categories cannot be admitted.

    Parameters
    ----------
    category_states : dict[str, str]
        Validated authored category states.

    Returns
    -------
    set[str]
        Categories changed to held because no machine semantic evaluator exists.
    """
    held_categories: set[str] = set()
    for category, state in category_states.items():
        if state != "held" and category not in MACHINE_VALIDATED_CATEGORIES:
            category_states[category] = "held"
            held_categories.add(category)
    return held_categories


def _validate_persisted_clang_identity(
    persisted: dict[str, JSONValue],
    bindings: dict[str, JSONValue],
    source_path: Path,
    source_hash: str,
    backend: str,
) -> None:
    """Require the actual database row to prove the bound Clang profile.

    Parameters
    ----------
    persisted : dict[str, JSONValue]
        Actual file and analysis-status fields from the database.
    bindings : dict[str, JSONValue]
        Validated source, profile, compiler, helper, and build identities.
    source_path : pathlib.Path
        Exact physical translation-unit path.
    source_hash : str
        Exact source digest.
    backend : str
        Backend name used in diagnostics.

    Returns
    -------
    None
    """
    target = _object(persisted.get("target_contract"), f"{backend}.target_contract")
    if (
        persisted.get("grammar") != "clang-cpp-frontend"
        or target.get("language") != "cpp"
        or target.get("frontend") != "clang"
    ):
        _fail(
            f"{backend} persisted frontend",
            "actual database target is not the Clang C++ frontend",
        )
    requested_path = target.get("requested_source_path")
    if (
        not isinstance(requested_path, str)
        or Path(requested_path).resolve() != source_path.resolve()
    ):
        _fail(
            f"{backend} persisted source path",
            "Clang target contract does not name the selected original",
        )
    if target.get("requested_source_sha256") != source_hash:
        _fail(
            f"{backend} persisted source hash",
            "Clang target contract does not bind the selected original bytes",
        )
    if target.get("profile_identity") != bindings.get("profile_identity"):
        _fail(
            f"{backend} persisted profile",
            "Clang target contract does not bind the selected compile profile",
        )
    toolchain = _object(
        target.get("toolchain_identity"), f"{backend}.toolchain_identity"
    )
    build_receipt = _read_json_object(
        Path(
            _string(bindings.get("build_receipt_path"), "bindings.build_receipt_path")
        ),
        "bound Clang build receipt",
    )
    expected_fields = {
        "compiler_path": bindings.get("compiler_identity"),
        "compiler_version": bindings.get("compiler_version"),
        "compiler_sha256": build_receipt.get("compiler_sha256"),
        "resource_dir": build_receipt.get("resource_dir"),
        "resource_probe_sha256": build_receipt.get("resource_probe_sha256"),
        "helper_path": bindings.get("helper_path"),
        "helper_sha256": bindings.get("helper_sha256"),
        "build_receipt_sha256": bindings.get("build_receipt_sha256"),
    }
    for field, expected in expected_fields.items():
        actual = toolchain.get(field)
        if (
            field == "compiler_path"
            and isinstance(actual, str)
            and isinstance(expected, str)
        ):
            if Path(actual).resolve() == Path(expected).resolve():
                continue
        elif actual == expected:
            continue
        _fail(
            f"{backend}.toolchain_identity.{field}",
            "actual database identity differs from the grade contract",
        )


def _analysis_rows_from_receipt(
    receipt: dict[str, JSONValue], backend: str, bindings: dict[str, JSONValue]
) -> JSONValue:
    """Validate backend database identity and return per-file status rows.

    Parameters
    ----------
    receipt : dict[str, JSONValue]
        Backend qualification receipt.
    backend : str
        Expected database backend.
    bindings : dict[str, JSONValue]
        Expected helper and build-receipt hashes.

    Returns
    -------
    JSONValue
        Per-file analysis status rows.
    """
    if backend == "sqlite":
        index = _object(receipt.get("index"), "sqlite receipt.index")
        inputs = _object(receipt.get("inputs"), "sqlite receipt.inputs")
        row_container = _object(receipt.get("analysis"), "sqlite receipt.analysis")
        expected_database_name = "sqlite"
        actual_database_name = index.get("backend")
        database_hash = index.get("database_sha256")
        identity_container = inputs
    else:
        index = _object(receipt.get("duckdb"), "duckdb receipt.duckdb")
        row_container = index
        expected_database_name = "duckdb"
        actual_database_name = index.get("backend_name")
        database_hash = index.get("database_sha256")
        identity_container = _object(
            receipt.get("source_guards"), "duckdb receipt.source_guards"
        )
    if actual_database_name != expected_database_name or not isinstance(
        database_hash, str
    ):
        _fail(f"{backend} receipt", "must bind the actual backend database")
    for field in ("helper_sha256", "build_receipt_sha256"):
        if identity_container.get(field) != bindings.get(field):
            _fail(f"{backend} receipt {field}", "does not match the grade contract")
    if identity_container.get("profile_collection_sha256") != bindings.get(
        "profile_collection_sha256"
    ):
        _fail(
            f"{backend} receipt profile collection",
            "does not match the indexed profile collection",
        )
    if backend == "sqlite":
        compile_databases = _object(
            identity_container.get("compile_databases"), "sqlite compile databases"
        )
        profile_rows = _object(
            identity_container.get("selected_profiles"), "sqlite selected profiles"
        )
        cdb_path = str(Path(cast("str", bindings["compile_database_path"])).resolve())
        profile_path = str(Path(cast("str", bindings["profile_path"])).resolve())
        if compile_databases.get(cdb_path) != bindings.get("compile_database_sha256"):
            _fail(
                "sqlite compile database",
                "receipt does not bind the contract CDB path and hash",
            )
        if profile_rows.get(profile_path) != bindings.get("profile_sha256"):
            _fail(
                "sqlite selected profile",
                "receipt does not bind the contract profile path and hash",
            )
    return row_container.get("files")


def _validate_cross_backend_receipts(sqlite_path: Path, duckdb_path: Path) -> None:
    """Require DuckDB qualification to reference the exact SQLite receipt.

    Parameters
    ----------
    sqlite_path : pathlib.Path
        SQLite qualification receipt.
    duckdb_path : pathlib.Path
        DuckDB parity receipt.

    Returns
    -------
    None
    """
    duckdb_receipt = _read_json_object(duckdb_path, "DuckDB receipt")
    sqlite_path_binding = _string(
        duckdb_receipt.get("sqlite_receipt_path"), "DuckDB receipt.sqlite_receipt_path"
    )
    sqlite_receipt_path = Path(sqlite_path_binding)
    if not sqlite_receipt_path.is_absolute():
        sqlite_receipt_path = Path(__file__).resolve().parents[1] / sqlite_receipt_path
    if sqlite_receipt_path.resolve() != sqlite_path.resolve():
        _fail(
            "DuckDB receipt",
            "references a different SQLite source/profile analysis receipt",
        )
    if duckdb_receipt.get("sqlite_receipt_sha256") != _sha256(sqlite_path):
        _fail(
            "DuckDB receipt",
            "SQLite receipt digest differs from the referenced analysis",
        )


def grade_contract(
    request: GradeRequest,
) -> dict[str, JSONValue]:
    """Grade an original file against complete source-authored expectations.

    Parameters
    ----------
    request : GradeRequest
        Immutable source, oracle, snapshot, receipt, database and profile inputs.

    Returns
    -------
    dict[str, JSONValue]
        Complete comparison report. Held categories or any mismatch make the
        report incomplete, even when both backends agree.
    """
    contract_path = request.contract_path
    oracle_path = request.oracle_path
    fixture_root = request.fixture_root
    snapshot_paths = request.snapshot_paths
    receipt_paths = request.receipt_paths
    database_bindings = request.database_bindings
    profile_document = request.profile_document
    contract = _read_json_object(contract_path, "contract")
    source_key = _string(
        _object(contract.get("source"), "contract.source").get("relative_path"),
        "contract.source.relative_path",
    )
    states, bindings, source = _validate_contract(
        contract, oracle_path, fixture_root, source_key
    )
    semantic_holds = _hold_categories_without_machine_semantics(states)
    if Path(
        cast("str", bindings["profile_collection_path"])
    ).resolve() != request.profile_document.resolve() or _sha256(
        request.profile_document
    ) != bindings.get("profile_collection_sha256"):
        _fail(
            "profile collection",
            "does not match the source/profile context in the contract",
        )
    oracle = load_oracle(oracle_path, fixture_root)
    authored_case = oracle.cases[source_key]
    source_hash = _string(source.get("sha256"), "contract.source.sha256")
    sqlite_status = _validate_analysis_receipt(
        AnalysisReceiptRequest(
            receipt_paths["sqlite"],
            "sqlite",
            source_key,
            source_hash,
            Path(cast("str", source["path"])).resolve(),
            bindings,
            database_bindings["sqlite"],
        )
    )
    duckdb_status = _validate_analysis_receipt(
        AnalysisReceiptRequest(
            receipt_paths["duckdb"],
            "duckdb",
            source_key,
            source_hash,
            Path(cast("str", source["path"])).resolve(),
            bindings,
            database_bindings["duckdb"],
        )
    )
    _validate_cross_backend_receipts(receipt_paths["sqlite"], receipt_paths["duckdb"])
    for field in ("native_stdout_sha256", "native_stderr_sha256"):
        if sqlite_status.get(field) != duckdb_status.get(field):
            _fail(
                f"backend status {field}",
                "SQLite and DuckDB attempts are not bound to the same native evidence",
            )
    for backend, binding in database_bindings.items():
        inventory_value = binding.get("analyzer_inventory")
        if not isinstance(inventory_value, list):
            _fail(
                f"{backend}.analyzer_inventory",
                "database generation lacks analyzer inventory",
            )
        matching_analyzers = [
            item
            for item in inventory_value
            if isinstance(item, dict) and item.get("name") == "cpp"
        ]
        if len(matching_analyzers) != 1 or matching_analyzers[0].get(
            "version"
        ) != bindings.get("analyzer_version"):
            _fail(
                f"{backend}.analyzer_inventory",
                "does not match the bound C++ analyzer version",
            )
    snapshots: dict[str, dict[str, JSONValue]] = {}
    backend_rows: dict[str, dict[str, JSONValue]] = {}
    backend_failures: dict[str, JSONValue] = {}
    control_sources = {
        _string(
            _object(value, f"source_authored_controls[{index}]").get("relative_path"),
            "control.relative_path",
        )
        for index, value in enumerate(
            cast("list[JSONValue]", contract["source_authored_controls"])
        )
    }
    control_failures: dict[str, list[dict[str, JSONValue]]] = {}
    backend_contexts: dict[str, str] = {}
    for backend, path in snapshot_paths.items():
        snapshot = _read_json_object(path, f"{backend} snapshot")
        source_rows = _validate_snapshot_binding(
            SnapshotBindingInput(
                snapshot,
                backend,
                source_key,
                source_hash,
                database_bindings[backend],
                _sha256(profile_document),
            )
        )
        snapshots[backend] = snapshot
        backend_rows[backend] = source_rows
        backend_contexts[backend] = _string(
            source_rows.get("analysis_input_fingerprint"),
            f"{backend}.case.analysis_input_fingerprint",
        )
        failures = grade_snapshot(oracle, snapshot)
        backend_failures[backend] = [
            {
                "case": failure.case,
                "category": failure.category,
                "reason": failure.reason,
                "expected": failure.expected,
            }
            for failure in failures
            if failure.case == source_key
        ]
        control_failures[backend] = [
            {
                "case": failure.case,
                "category": failure.category,
                "reason": failure.reason,
                "expected": failure.expected,
            }
            for failure in failures
            if failure.case in control_sources
        ]
        control_failures[backend].extend(
            _negative_control_snapshot_failures(contract, snapshot)
        )
    backend_context_details = {
        backend: _validate_indexed_context_identity(
            backend,
            context,
            _string(
                bindings.get("analysis_context_identity"), "analysis_context_identity"
            ),
        )
        for backend, context in backend_contexts.items()
    }

    category_reports: dict[str, JSONValue] = {}
    mismatches = 0
    held = 0
    for category in FACT_CATEGORIES:
        state = states[category]
        expected_count = (
            len(authored_case.facts.get(category, ()))
            if category in SOURCE_FACT_CATEGORIES
            else 0
        )
        observed_counts = {
            backend: len(
                _as_rows(backend_rows[backend].get(category), f"{backend}.{category}")
            )
            for backend in snapshot_paths
        }
        category_parity = observed_counts["sqlite"] == observed_counts["duckdb"]
        exact_counts = {
            backend: observed_counts[backend] == expected_count
            for backend in snapshot_paths
        }
        category_failures = [
            failure
            for backend in backend_failures.values()
            for failure in cast("list[dict[str, JSONValue]]", backend)
            if failure.get("category") == category
        ]
        if state == "held":
            held += 1
        exact_count_required = (
            state in {"graded", "not_applicable"} and category in SOURCE_FACT_CATEGORIES
        )
        if (state == "graded" and category_failures) or (
            exact_count_required
            and (not category_parity or not all(exact_counts.values()))
        ):
            mismatches += 1
        category_contract = _object(contract["categories"], "contract.categories")
        category_entry = _object(category_contract[category], category)
        category_reports[category] = cast(
            "JSONValue",
            {
                "state": state,
                "independent_basis": category_entry["independent_basis"],
                "semantic_validation": (
                    "held: no independent machine evaluator is implemented"
                    if category in semantic_holds
                    else "persisted-analysis-status"
                    if category in MACHINE_VALIDATED_CATEGORIES
                    else "not-required: category was already held"
                ),
                "expected_count": expected_count,
                "observed_counts": observed_counts,
                "exact_count_by_backend": exact_counts,
                "backend_parity": category_parity,
                "grader_failures": category_failures,
            },
        )

    canonical_rows = {
        backend: {
            category: sorted(
                _canonical(row)
                for row in _as_rows(
                    backend_rows[backend].get(category), f"{backend}.{category}"
                )
            )
            for category in FACT_CATEGORIES
        }
        for backend in snapshot_paths
    }
    parity_differences = cast(
        "dict[str, JSONValue]",
        {
            category: {
                "sqlite_only": list(
                    (
                        Counter(canonical_rows["sqlite"][category])
                        - Counter(canonical_rows["duckdb"][category])
                    ).elements()
                ),
                "duckdb_only": list(
                    (
                        Counter(canonical_rows["duckdb"][category])
                        - Counter(canonical_rows["sqlite"][category])
                    ).elements()
                ),
            }
            for category in FACT_CATEGORIES
            if canonical_rows["sqlite"][category] != canonical_rows["duckdb"][category]
        },
    )
    context = bindings
    passed = (
        held == 0
        and mismatches == 0
        and not parity_differences
        and not any(control_failures.values())
    )
    return {
        "schema": GRADE_SCHEMA,
        "source": source,
        "context": context,
        "backend_snapshots": {
            key: {
                "path": str(path),
                "sha256": _sha256(path),
                "database": database_bindings[key],
            }
            for key, path in snapshot_paths.items()
        },
        "backend_status_receipts": {
            "sqlite": {
                "path": str(receipt_paths["sqlite"]),
                "sha256": _sha256(receipt_paths["sqlite"]),
                "row": sqlite_status,
            },
            "duckdb": {
                "path": str(receipt_paths["duckdb"]),
                "sha256": _sha256(receipt_paths["duckdb"]),
                "row": duckdb_status,
            },
        },
        "backend_analysis_contexts": {
            backend: {
                "analysis_input_fingerprint": backend_contexts[backend],
                "fields": backend_context_details[backend],
            }
            for backend in backend_contexts
        },
        "category_reports": category_reports,
        "backend_parity_differences": parity_differences,
        "source_authored_control_failures": cast("JSONValue", control_failures),
        "held_category_count": held,
        "categories_held_without_machine_semantics": cast(
            "JSONValue", sorted(semantic_holds)
        ),
        "mismatched_category_count": mismatches,
        "scope_complete": passed,
        "passed": passed,
        "limitations": []
        if passed
        else [
            "A backend match or parity result does not resolve held or incomplete categories.",
            "Source-authored facts remain held until category-specific machine semantic evaluators validate them.",
        ],
    }


def _as_rows(value: JSONValue | None, context: str) -> list[dict[str, JSONValue]]:
    """Validate a per-category snapshot array.

    Parameters
    ----------
    value : JSONValue or None
        Candidate snapshot value.
    context : str
        Snapshot location for diagnostics.

    Returns
    -------
    list[dict[str, JSONValue]]
        Rows with JSON object shape.
    """
    if not isinstance(value, list):
        _fail(context, "must be an array")
    return [_object(row, f"{context}[{index}]") for index, row in enumerate(value)]


def main() -> int:
    """Run a fail-closed whole-file grade from existing snapshots.

    Parameters
    ----------
    None

    Returns
    -------
    int
        Zero only when all categories are complete, exact, and backend-equal.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--oracle", type=Path, required=True)
    parser.add_argument("--fixture-root", type=Path, required=True)
    parser.add_argument("--database-root", type=Path, required=True)
    parser.add_argument("--profile-document", type=Path, required=True)
    parser.add_argument("--sqlite-database", type=Path, required=True)
    parser.add_argument("--duckdb-database", type=Path, required=True)
    parser.add_argument("--sqlite-receipt", type=Path, required=True)
    parser.add_argument("--duckdb-receipt", type=Path, required=True)
    parser.add_argument("--snapshot-output-directory", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        snapshot_paths, database_bindings = export_bound_database_snapshots(
            SnapshotExportRequest(
                args.oracle,
                args.fixture_root,
                args.database_root,
                args.profile_document,
                _string(
                    _object(
                        _read_json_object(args.contract, "contract").get("source"),
                        "contract.source",
                    ).get("relative_path"),
                    "contract.source.relative_path",
                ),
                {"sqlite": args.sqlite_database, "duckdb": args.duckdb_database},
                {"sqlite": args.sqlite_receipt, "duckdb": args.duckdb_receipt},
                args.snapshot_output_directory,
            )
        )
        report = grade_contract(
            GradeRequest(
                args.contract,
                args.oracle,
                args.fixture_root,
                snapshot_paths,
                {"sqlite": args.sqlite_receipt, "duckdb": args.duckdb_receipt},
                database_bindings,
                args.profile_document,
            )
        )
    except (OracleFormatError, OSError, json.JSONDecodeError) as error:
        parser.error(str(error))
    encoded = json.dumps(report, indent=2, sort_keys=True) + "\n"
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as output:
        output.write(encoded)
    return 0 if report["passed"] is True else 1


if __name__ == "__main__":
    sys.exit(main())
