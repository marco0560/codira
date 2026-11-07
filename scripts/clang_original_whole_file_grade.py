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
import importlib.util
import inspect
import json
import re
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
# Persisted analysis-status checks validate coverage. Source include semantics
# are enabled separately only when the bounded literal-directive parser accepts
# the exact source file.
MACHINE_VALIDATED_CATEGORIES = frozenset({"coverage"})
AST_MACHINE_CATEGORIES = frozenset({"declarations", "fields", "callables"})


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


@dataclass(frozen=True)
class SourceOwnedAstGradeRequest:
    """Inputs for category-only reconciliation of a retained source AST.

    Parameters
    ----------
    source_path : pathlib.Path
        Exact original source file.
    source_key : str
        Relative case key used by retained backend snapshots.
    normalized_path : pathlib.Path
        Normalized reference facts generated from the retained raw AST.
    normalization_record_path : pathlib.Path
        Receipt binding raw AST, normalizer, profile and normalized output.
    capture_summary_path : pathlib.Path
        Independent CLI capture summary with toolchain and source identity.
    prepared_inputs_path : pathlib.Path
        Hash-bound compiler profile, dependencies and toolchain inputs.
    guards_before_path : pathlib.Path
        Pre-capture dependency and include-directory guard snapshot.
    guards_after_path : pathlib.Path
        Post-capture dependency and include-directory guard snapshot.
    snapshot_paths : dict[str, pathlib.Path]
        Retained SQLite and DuckDB source snapshots.
    database_binding_paths : dict[str, pathlib.Path]
        Filesystem-derived database generation identity receipts.
    status_paths : dict[str, pathlib.Path]
        Independently exported persisted analyzer status rows.
    profile_document_path : pathlib.Path
        Exact selected profile JSON document bound by the snapshots.
    repository_root : pathlib.Path
        Compiler source repository root used to reload the captured profile.

    Returns
    -------
    None
    """

    source_path: Path
    source_key: str
    normalized_path: Path
    normalization_record_path: Path
    capture_summary_path: Path
    prepared_inputs_path: Path
    guards_before_path: Path
    guards_after_path: Path
    snapshot_paths: dict[str, Path]
    database_binding_paths: dict[str, Path]
    status_paths: dict[str, Path]
    profile_document_path: Path
    repository_root: Path


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


def _source_owned_ast_expectations(  # noqa: C901, PLR0913 -- bounded AST evidence gates
    normalized: dict[str, JSONValue],
    raw_ast: dict[str, object],
    source: bytes,
    analyzer_capabilities: dict[str, JSONValue],
    normalizer_path: Path,
    working_directory: Path,
) -> dict[str, list[dict[str, JSONValue]]]:
    """Build bounded C record, field and callable expectations from Clang AST.

    Parameters
    ----------
    normalized : dict[str, JSONValue]
        Normalized facts replayed from the retained raw AST.
    raw_ast : dict[str, object]
        Parsed independent Clang JSON AST for lexical-parent checks.
    source : bytes
        Exact source bytes used by the capture.
    analyzer_capabilities : dict[str, JSONValue]
        Explicit production analyzer support and omission declarations.
    normalizer_path : pathlib.Path
        Frozen normalizer copy used to replay the retained raw AST.
    working_directory : pathlib.Path
        Exact compile working directory used by Clang.

    Returns
    -------
    dict[str, list[dict[str, JSONValue]]]
        Expected persisted rows for declarations, fields and callables.

    Raises
    ------
    OracleFormatError
        If AST facts, physical coordinates, lexical ownership or capabilities
        fall outside the bounded supported subset.
    """
    facts = _object(normalized.get("facts"), "normalized.facts")
    declarations = _as_rows(facts.get("declarations"), "normalized.declarations")
    types = _as_rows(facts.get("types"), "normalized.types")
    fields = _as_rows(facts.get("fields"), "normalized.fields")
    callables = _as_rows(facts.get("callables"), "normalized.callables")

    def check_location(row: dict[str, JSONValue], context: str) -> None:
        offset = row.get("offset")
        line = row.get("line")
        column = row.get("column")
        name = row.get("name")
        if (
            not isinstance(offset, int)
            or isinstance(offset, bool)
            or not isinstance(line, int)
            or isinstance(line, bool)
            or not isinstance(column, int)
            or isinstance(column, bool)
            or not isinstance(name, str)
            or not name.isidentifier()
            or offset < 0
            or offset >= len(source)
            or line < 1
            or column < 1
        ):
            _fail(context, "source AST row has invalid physical coordinates or name")
        line_start = source.rfind(b"\n", 0, offset) + 1
        actual_line = source.count(b"\n", 0, offset) + 1
        if actual_line != line or offset - line_start + 1 != column:
            _fail(context, "source AST line/column do not match its byte offset")
        encoded_name = name.encode("utf-8")
        if source[offset : offset + len(encoded_name)] != encoded_name:
            _fail(context, "AST name does not occupy its bound source byte offset")
        before = source[offset - 1] if offset else None
        after_offset = offset + len(encoded_name)
        after = source[after_offset] if after_offset < len(source) else None
        if (before is not None and _is_c_identifier_byte(before)) or (
            after is not None and _is_c_identifier_byte(after)
        ):
            _fail(context, "AST name is not a complete source identifier token")

    source_path_value = normalized.get("source_path")
    if not isinstance(source_path_value, str) or not source_path_value:
        _fail("normalized.source_path", "must bind the original source path")
    source_path = Path(source_path_value)
    if normalized.get("source_sha256") != hashlib.sha256(source).hexdigest():
        _fail("normalized.source_sha256", "does not match original source bytes")
    if not normalizer_path.is_file():
        _fail("normalizer", "frozen normalizer copy is absent")
    spec = importlib.util.spec_from_file_location(
        "_frozen_clang_reference_facts", normalizer_path
    )
    if spec is None or spec.loader is None:
        _fail("normalizer", "cannot load frozen normalizer copy")
    normalizer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(normalizer)
    normalize = getattr(normalizer, "normalize_ast", None)
    if not callable(normalize):
        _fail("normalizer", "does not expose normalize_ast")
    replayed = normalize(raw_ast, source_path, source, working_directory)
    if _canonical(cast("JSONValue", replayed)) != _canonical(
        cast("JSONValue", normalized)
    ):
        _fail(
            "normalized reference",
            "does not equal a fresh replay of the retained raw AST and source",
        )
    ungraded_nodes = _as_rows(facts.get("ungraded_nodes"), "normalized.ungraded_nodes")
    ungraded_counts = _object(
        normalized.get("ungraded_counts"), "normalized.ungraded_counts"
    )
    unsupported_declaration_counts = {
        key: value
        for key, value in ungraded_counts.items()
        if key not in {"implicit_declaration", "multiple_ast_nodes_at_source_call_site"}
        and value != 0
    }
    if ungraded_nodes or unsupported_declaration_counts:
        _fail(
            "normalized.ungraded_declarations",
            "contains omitted, ambiguous or unsupported source declaration nodes",
        )

    for index, row in enumerate(declarations):
        check_location(row, f"normalized.declarations[{index}]")
    for category, rows in (
        ("types", types),
        ("fields", fields),
        ("callables", callables),
    ):
        for index, row in enumerate(rows):
            check_location(row, f"normalized.{category}[{index}]")

    declaration_kinds = Counter(
        cast("str", row.get("kind"))
        for row in declarations
        if isinstance(row.get("kind"), str)
    )
    expected_kinds = Counter(
        {
            "VarDecl": sum(row.get("kind") == "VarDecl" for row in declarations),
            "FunctionDecl": len(callables),
            "FieldDecl": len(fields),
            "RecordDecl": len(types),
        }
    )
    if declaration_kinds != expected_kinds or any(
        row.get("kind") not in {"VarDecl", "FunctionDecl", "FieldDecl", "RecordDecl"}
        for row in declarations
    ):
        _fail(
            "normalized.declarations",
            "contains an unsupported declaration class or an unprojected source declaration",
        )
    raw_expected = _reconcile_raw_source_declarations(
        raw_ast, source_path, working_directory, source, normalized
    )
    if any(row.get("kind") != "RecordDecl" for row in types):
        _fail("normalized.types", "only source-owned record definitions are supported")
    if any(row.get("kind") != "FieldDecl" for row in fields):
        _fail("normalized.fields", "contains a non-field AST row")
    if any(
        row.get("kind") != "FunctionDecl" or row.get("is_definition") is not True
        for row in callables
    ):
        _fail(
            "normalized.callables",
            "only source-owned function definitions are supported",
        )

    supported = analyzer_capabilities.get("supports")
    unsupported = analyzer_capabilities.get("does_not_support")
    if (
        not isinstance(supported, list)
        or not isinstance(unsupported, list)
        or "callable" not in supported
        or "type" not in supported
        or "variable" not in supported
        or analyzer_capabilities.get("analyzer_version") != "30"
    ):
        _fail(
            "analyzer_capabilities",
            "must bind C analyzer v30 with callable/type/variable support",
        )

    local_variable_offsets = {
        cast("int", row["offset"])
        for row in declarations
        if row.get("kind") == "VarDecl"
    }
    if not _raw_ast_var_declarations_are_function_local(
        raw_ast, local_variable_offsets
    ):
        _fail(
            "normalized.declarations.VarDecl",
            "every excluded variable must be source-owned and nested under a function definition",
        )

    records = raw_expected["declarations"]
    expected_fields = raw_expected["fields"]
    expected_callables = raw_expected["callables"]

    diagnostics = _object(
        normalized.get("ownership_diagnostics"), "normalized.ownership_diagnostics"
    )
    declaration_diagnostics = _object(
        diagnostics.get("declarations"), "ownership_diagnostics.declarations"
    )
    unknown_declarations = _object(
        declaration_diagnostics.get("unknown"),
        "ownership_diagnostics.declarations.unknown",
    )
    unknown_samples = unknown_declarations.get("samples")
    if not isinstance(unknown_samples, list):
        _fail("ownership_diagnostics.declarations.unknown", "samples must be explicit")
    unresolved_names = {
        sample.get("name")
        for sample in unknown_samples
        if isinstance(sample, dict)
        and sample.get("reason") == "implicit_declaration"
        and isinstance(sample.get("name"), str)
    }
    selected_types = [
        _string(row.get("type"), "source-owned AST type")
        for row in (*fields, *callables)
        if isinstance(row.get("type"), str)
    ]
    if any(
        re.search(
            rf"(?<![A-Za-z0-9_]){re.escape(cast('str', name))}(?![A-Za-z0-9_])",
            type_text,
        )
        for name in unresolved_names
        for type_text in selected_types
    ):
        _fail(
            "normalized.unresolved_implicit_types",
            "an unresolved implicit header type participates in a selected field or callable signature",
        )

    return {
        "declarations": records,
        "fields": expected_fields,
        "callables": expected_callables,
    }


def _reconcile_raw_source_declarations(  # noqa: C901 -- raw declaration inventory must be explicit
    ast: dict[str, object],
    source_path: Path,
    working_directory: Path,
    source: bytes,
    normalized: dict[str, JSONValue],
) -> dict[str, list[dict[str, JSONValue]]]:
    """Enumerate source declarations independently from normalized rows.

    Parameters
    ----------
    ast : dict[str, object]
        Retained raw Clang AST.
    source_path : pathlib.Path
        Exact source path bound to the profile.
    working_directory : pathlib.Path
        Compile-command directory for relative AST file paths.
    source : bytes
        Exact original source bytes.
    normalized : dict[str, JSONValue]
        Replayed normalized output checked against the raw inventory.

    Returns
    -------
    dict[str, list[dict[str, JSONValue]]]
        Raw-AST-derived category expectations.

    Raises
    ------
    OracleFormatError
        If the raw AST contains unsupported or unaccounted source declarations.
    """
    location_files: dict[int, Path | None] = {}
    active_file: list[Path | None] = [None]

    def annotate(value: object) -> None:
        if isinstance(value, list):
            for child in value:
                annotate(child)
        elif isinstance(value, dict):
            if "offset" in value:
                explicit_path = value.get("file")
                if isinstance(explicit_path, str):
                    path = Path(explicit_path)
                    active_file[0] = (
                        path.resolve()
                        if path.is_absolute()
                        else (working_directory / path).resolve()
                    )
                location_files[id(value)] = active_file[0]
            for key, child in value.items():
                if key not in {"file", "includedFrom"}:
                    annotate(child)

    annotate(ast)
    source_path = source_path.resolve()
    declarations: list[dict[str, JSONValue]] = []
    record_rows: list[dict[str, JSONValue]] = []
    field_rows: list[dict[str, JSONValue]] = []
    callable_rows: list[dict[str, JSONValue]] = []
    supported_kinds = {"RecordDecl", "FieldDecl", "FunctionDecl", "VarDecl"}
    source_declaration_kinds = supported_kinds | {
        "TypedefDecl",
        "EnumDecl",
        "EnumConstantDecl",
        "IndirectFieldDecl",
        "ObjCInterfaceDecl",
        "NamespaceDecl",
        "CXXRecordDecl",
        "CXXMethodDecl",
        "ClassTemplateDecl",
        "FunctionTemplateDecl",
    }
    seen_anchors: set[tuple[str, int]] = set()

    def visit(  # noqa: C901, PLR0912 -- bounded raw AST source ownership walk
        node: object, owners: tuple[str, ...], in_function: bool
    ) -> None:
        if not isinstance(node, dict):
            return
        kind = node.get("kind")
        location = node.get("loc")
        path = location_files.get(id(location)) if isinstance(location, dict) else None
        if isinstance(location, dict) and any(
            location_files.get(id(location.get(key))) == source_path
            for key in ("expansionLoc", "spellingLoc")
        ):
            _fail(
                "raw_ast.declarations", "source-owned macro locations are unsupported"
            )
        source_owned = path == source_path
        if (
            source_owned
            and kind in source_declaration_kinds
            and kind not in supported_kinds
        ):
            _fail(
                "raw_ast.declarations",
                f"source-owned {kind} is outside the supported category projection",
            )
        if source_owned and kind in supported_kinds:
            if not isinstance(location, dict) or any(
                key in location for key in ("expansionLoc", "spellingLoc")
            ):
                _fail("raw_ast.declarations", "macro locations are unsupported")
            offset, line, column, name = (
                location.get("offset"),
                location.get("line"),
                location.get("col"),
                node.get("name"),
            )
            if (
                not isinstance(offset, int)
                or isinstance(offset, bool)
                or (
                    line is not None
                    and (not isinstance(line, int) or isinstance(line, bool))
                )
                or not isinstance(column, int)
                or isinstance(column, bool)
                or not isinstance(name, str)
                or not name.isidentifier()
                or offset < 0
                or offset >= len(source)
            ):
                _fail(
                    "raw_ast.declarations",
                    "source declaration lacks a physical name anchor",
                )
            token = name.encode("utf-8")
            if source[offset : offset + len(token)] != token:
                _fail("raw_ast.declarations", "AST spelling differs from source bytes")
            before = source[offset - 1] if offset else None
            after_offset = offset + len(token)
            after = source[after_offset] if after_offset < len(source) else None
            if any(
                byte is not None
                and (
                    _is_c_identifier_byte(byte)
                    or byte in {ord("$"), ord("\\")}
                    or byte >= 0x80
                )
                for byte in (before, after)
            ):
                _fail(
                    "raw_ast.declarations",
                    "AST spelling is not a complete supported identifier",
                )
            actual_line = source.count(b"\n", 0, offset) + 1
            actual_column = offset - source.rfind(b"\n", 0, offset)
            if (line is not None and line != actual_line) or column != actual_column:
                _fail(
                    "raw_ast.declarations", "AST coordinates differ from source bytes"
                )
            line = actual_line
            anchor = (cast("str", kind), offset)
            if anchor in seen_anchors:
                _fail(
                    "raw_ast.declarations",
                    "multiple source AST nodes share one physical anchor",
                )
            seen_anchors.add(anchor)
            if (
                node.get("isImplicit") is True
                or node.get("isTemplateInstantiation") is True
            ):
                _fail(
                    "raw_ast.declarations",
                    "implicit/template declarations are unsupported",
                )
            node_type = node.get("type")
            type_text = (
                node_type.get("qualType")
                if isinstance(node_type, dict)
                and isinstance(node_type.get("qualType"), str)
                else None
            )
            children_value = node.get("inner")
            children = children_value if isinstance(children_value, list) else []
            definition = any(
                isinstance(child, dict)
                and child.get("kind") in {"CompoundStmt", "CXXTryStmt"}
                for child in children
            )
            fact: dict[str, JSONValue] = {
                "kind": kind,
                "name": name,
                "offset": offset,
                "line": line,
                "column": column,
                "owner_chain": list(owners),
                "type": type_text,
                "is_definition": definition,
            }
            declarations.append(fact)
            if kind == "RecordDecl":
                tag = node.get("tagUsed")
                if tag not in {"struct", "union"}:
                    _fail(
                        "raw_ast.RecordDecl",
                        "only struct and union records are supported",
                    )
                record_rows.append({"kind": tag, "line": line, "name": name})
            elif kind == "FieldDecl":
                if not owners or type_text is None:
                    _fail("raw_ast.FieldDecl", "owner and type must be source-proven")
                field_rows.append(
                    {"line": line, "name": name, "owner": owners[-1], "type": type_text}
                )
            elif kind == "FunctionDecl":
                if not definition or type_text is None:
                    _fail(
                        "raw_ast.FunctionDecl",
                        "only typed function definitions are supported",
                    )
                return_type, parameter_types = _parse_simple_function_type(type_text)
                callable_rows.append(
                    {
                        "definition_line": line,
                        "kind": "function",
                        "name": name,
                        "parameter_types": cast("JSONValue", parameter_types),
                        "return_type": return_type,
                    }
                )
            elif kind == "VarDecl" and not in_function:
                _fail("raw_ast.VarDecl", "file-scope variable is outside this proof")
        next_owners = owners
        if kind == "RecordDecl" and isinstance(node.get("name"), str):
            next_owners = (*owners, cast("str", node["name"]))
        next_function = in_function or kind == "FunctionDecl"
        child_values = node.get("inner")
        if isinstance(child_values, list):
            for child in child_values:
                visit(child, next_owners, next_function)

    visit(ast, (), False)

    def digest_rows(rows: list[dict[str, JSONValue]]) -> Counter[str]:
        return Counter(_canonical(cast("JSONValue", row)) for row in rows)

    facts = _object(normalized.get("facts"), "normalized.facts")
    normalized_declarations = _as_rows(
        facts.get("declarations"), "normalized.declarations"
    )
    declaration_keys = (
        "kind",
        "name",
        "offset",
        "line",
        "column",
        "owner_chain",
        "type",
        "is_definition",
    )
    raw_identity = [
        {key: row.get(key) for key in declaration_keys} for row in declarations
    ]
    normalized_identity = [
        {key: row.get(key) for key in declaration_keys}
        for row in normalized_declarations
    ]
    if digest_rows(raw_identity) != digest_rows(normalized_identity):
        _fail(
            "raw_ast.declarations",
            "source-owned raw declaration nodes are not exhaustively represented in normalized facts",
        )
    for fact_key, expected_kind in (
        ("types", "RecordDecl"),
        ("fields", "FieldDecl"),
        ("callables", "FunctionDecl"),
    ):
        actual = _as_rows(facts.get(fact_key), f"normalized.{fact_key}")
        expected = [row for row in declarations if row.get("kind") == expected_kind]
        actual_identity = [
            {key: row.get(key) for key in declaration_keys} for row in actual
        ]
        if digest_rows(actual_identity) != digest_rows(expected):
            _fail(
                f"normalized.{fact_key}",
                "projection differs from raw source AST inventory",
            )
    return {
        "declarations": record_rows,
        "fields": field_rows,
        "callables": callable_rows,
    }


def _raw_ast_var_declarations_are_function_local(
    ast: dict[str, object], expected_offsets: set[int]
) -> bool:
    """Verify excluded source variables have a raw AST function parent.

    Parameters
    ----------
    ast : dict[str, object]
        Raw Clang translation-unit AST.
    expected_offsets : set[int]
        Source-owned variable offsets selected by normalization.

    Returns
    -------
    bool
        Whether every selected variable appears exactly once beneath a function.
    """
    observed: Counter[int] = Counter()
    invalid: set[int] = set()

    def visit(node: object, under_function: bool) -> None:
        if not isinstance(node, dict):
            return
        kind = node.get("kind")
        current_under_function = under_function or kind == "FunctionDecl"
        if kind == "VarDecl":
            location = node.get("loc")
            offset = location.get("offset") if isinstance(location, dict) else None
            if (
                isinstance(offset, int)
                and not isinstance(offset, bool)
                and offset in expected_offsets
            ):
                observed[offset] += 1
                if not current_under_function:
                    invalid.add(offset)
        children = node.get("inner")
        if isinstance(children, list):
            for child in children:
                visit(child, current_under_function)

    visit(ast, False)
    return (
        set(observed) == expected_offsets
        and all(count == 1 for count in observed.values())
        and not invalid
    )


def _is_c_identifier_byte(value: int) -> bool:
    """Return whether one byte can continue a C identifier token.

    Parameters
    ----------
    value : int
        One source byte.

    Returns
    -------
    bool
        Whether the byte is an ASCII identifier character.
    """
    return (
        ord("a") <= value <= ord("z")
        or ord("A") <= value <= ord("Z")
        or ord("0") <= value <= ord("9")
        or value == ord("_")
    )


def _parse_simple_function_type(signature: str) -> tuple[str, list[str]]:
    """Parse a bounded Clang function type into return and parameter types.

    Parameters
    ----------
    signature : str
        Clang canonical type spelling.

    Returns
    -------
    tuple[str, list[str]]
        Return type and ordered parameter type list.

    Raises
    ------
    OracleFormatError
        If the spelling is not a supported single-level function type.
    """
    opening = signature.find("(")
    if opening <= 0 or not signature.endswith(")"):
        _fail(
            "normalized.callable.type", "is outside the bounded function-type grammar"
        )
    return_type = signature[:opening].strip()
    if not return_type:
        _fail("normalized.callable.type", "has no return type")
    parameter_text = signature[opening + 1 : -1].strip()
    if not parameter_text or parameter_text == "void":
        return return_type, []
    parts: list[str] = []
    start = 0
    depth = 0
    for index, character in enumerate(parameter_text):
        if character in "(<[":
            depth += 1
        elif character in ")>]":
            depth -= 1
            if depth < 0:
                _fail("normalized.callable.type", "has unbalanced parameter delimiters")
        elif character == "," and depth == 0:
            part = parameter_text[start:index].strip()
            if not part:
                _fail("normalized.callable.type", "contains an empty parameter type")
            parts.append(part)
            start = index + 1
    if depth != 0:
        _fail("normalized.callable.type", "has unbalanced parameter delimiters")
    final = parameter_text[start:].strip()
    if not final:
        _fail("normalized.callable.type", "contains an empty final parameter type")
    parts.append(final)
    if any(re.search(r"\b(?:auto|decltype)\b", part) for part in parts):
        _fail(
            "normalized.callable.type",
            "contains an unsupported dependent parameter type",
        )
    return return_type, parts


def _scan_c_doxygen_comment_offsets(  # noqa: C901 -- lexical inventory must skip C literals
    source: bytes,
) -> list[int]:
    """Find Doxygen comment starts outside C string and character literals.

    Parameters
    ----------
    source : bytes
        Exact captured C translation-unit bytes.

    Returns
    -------
    list[int]
        Byte offsets of lexical Doxygen comment markers.

    Raises
    ------
    OracleFormatError
        If encoding, line splices, trigraphs, strings, or comments are outside
        the supported lexical subset.
    """
    if source.startswith(b"\xef\xbb\xbf"):
        _fail("source.documentation", "UTF-8 BOM is outside the lexical subset")
    if b"??" in source or re.search(rb"\\(?:\r\n|\n|\r)", source):
        _fail(
            "source.documentation",
            "trigraphs and line splices are outside the lexical subset",
        )
    if b"\x00" in source:
        _fail("source.documentation", "NUL bytes are outside the lexical subset")

    offsets: list[int] = []
    index = 0
    while index < len(source):
        current = source[index]
        if current in {ord('"'), ord("'")}:
            delimiter = current
            index += 1
            while index < len(source) and source[index] != delimiter:
                if source[index] in {ord("\n"), ord("\r")}:
                    _fail(
                        "source.documentation",
                        "unterminated string or character literal",
                    )
                if source[index] == ord("\\"):
                    index += 1
                    if index >= len(source):
                        _fail(
                            "source.documentation",
                            "literal ends with an incomplete escape",
                        )
                index += 1
            if index >= len(source):
                _fail(
                    "source.documentation", "unterminated string or character literal"
                )
            index += 1
            continue
        if source.startswith(b"//", index):
            marker = source[index : index + 3]
            if marker in {b"///", b"//!"}:
                offsets.append(index)
            newline_positions = [
                position
                for position in (
                    source.find(b"\n", index + 2),
                    source.find(b"\r", index + 2),
                )
                if position >= 0
            ]
            newline = min(newline_positions) if newline_positions else -1
            if newline < 0:
                index = len(source)
            elif source[newline : newline + 2] == b"\r\n":
                index = newline + 2
            else:
                index = newline + 1
            continue
        if source.startswith(b"/*", index):
            marker = source[index : index + 3]
            if marker in {b"/**", b"/*!"}:
                offsets.append(index)
            close = source.find(b"*/", index + 2)
            if close < 0:
                _fail("source.documentation", "unterminated block comment")
            index = close + 2
            continue
        index += 1
    return offsets


def _source_ast_file_bindings(
    ast: dict[str, object], working_directory: Path
) -> dict[int, Path | None]:
    """Map raw AST source-location objects to their inherited physical files.

    Parameters
    ----------
    ast : dict[str, object]
        Raw Clang JSON AST.
    working_directory : pathlib.Path
        Working directory used to resolve relative location paths.

    Returns
    -------
    dict[int, pathlib.Path or None]
        AST object identities mapped to inherited resolved paths.
    """
    location_files: dict[int, Path | None] = {}
    active_file: list[Path | None] = [None]

    def annotate(value: object) -> None:
        """Annotate nested AST coordinate dictionaries with active file scope.

        Parameters
        ----------
        value : object
            One raw AST value.

        Returns
        -------
        None
        """
        if isinstance(value, list):
            for child in value:
                annotate(child)
            return
        if not isinstance(value, dict):
            return
        if "offset" in value:
            explicit_path = value.get("file")
            if isinstance(explicit_path, str):
                path = Path(explicit_path)
                active_file[0] = (
                    path.resolve()
                    if path.is_absolute()
                    else (working_directory / path).resolve()
                )
            location_files[id(value)] = active_file[0]
        for key, child in value.items():
            if key not in {"file", "includedFrom"}:
                annotate(child)

    annotate(ast)
    return location_files


def _point_file(point: object, location_files: dict[int, Path | None]) -> Path | None:
    """Return the inherited physical path for one raw source point.

    Parameters
    ----------
    point : object
        Raw Clang source-point dictionary.
    location_files : dict[int, pathlib.Path or None]
        File bindings from the raw AST traversal.

    Returns
    -------
    pathlib.Path or None
        Resolved physical file, when known.
    """
    return location_files.get(id(point)) if isinstance(point, dict) else None


def _raw_source_enum_members(  # noqa: C901 -- raw enum inventory has explicit fail-closed gates
    ast: dict[str, object],
    source: bytes,
    source_path: Path,
    working_directory: Path,
    source_key: str | None,
) -> tuple[list[dict[str, JSONValue]], dict[str, JSONValue]]:
    """Build a bounded inventory of source-written enum members from Clang AST.

    Parameters
    ----------
    ast : dict[str, object]
        Full raw Clang translation-unit AST.
    source : bytes
        Exact source bytes selected by the compile profile.
    source_path : pathlib.Path
        Physical translation-unit source path.
    working_directory : pathlib.Path
        Compiler working directory for resolving raw AST files.
    source_key : str or None
        Repository-relative stable identity key for the selected source.

    Returns
    -------
    tuple[list[dict[str, JSONValue]], dict[str, JSONValue]]
        Expected source enum-member rows and census diagnostics.
    """
    if ast.get("kind") != "TranslationUnitDecl":
        _fail("raw_ast.enum_members", "root is not a translation unit")
    location_files = _source_ast_file_bindings(ast, working_directory)
    source_path = source_path.resolve()
    expected: list[dict[str, JSONValue]] = []
    failures: list[str] = []
    source_enum_count = 0
    macro_enum_count = 0
    external_enum_count = 0
    unknown_enum_count = 0

    def location_status(point: object) -> str:
        """Classify source spelling and expansion ownership for one location.

        Parameters
        ----------
        point : object
            Raw Clang source location.

        Returns
        -------
        str
            ``source_written``, ``source_macro``, ``external``, or ``unknown``.
        """
        if not isinstance(point, dict):
            return "unknown"
        spelling = point.get("spellingLoc")
        expansion = point.get("expansionLoc")
        if isinstance(spelling, dict) or isinstance(expansion, dict):
            spelling_path = _point_file(spelling, location_files)
            expansion_path = _point_file(expansion, location_files)
            if source_path in {spelling_path, expansion_path}:
                return "source_macro"
            if spelling_path is not None or expansion_path is not None:
                return "external"
            return "unknown"
        path = _point_file(point, location_files)
        if path == source_path:
            return "source_written"
        return "external" if path is not None else "unknown"

    def physical_point(point: object, context: str) -> tuple[int, int]:
        """Validate and return one offset and token length in source bytes.

        Parameters
        ----------
        point : object
            Raw Clang point with offset and token length.
        context : str
            Error-report context for this point.

        Returns
        -------
        tuple[int, int]
            Byte offset and token length.
        """
        if not isinstance(point, dict):
            _fail(context, "source point is absent")
        offset, token_length = point.get("offset"), point.get("tokLen")
        if (
            not isinstance(offset, int)
            or isinstance(offset, bool)
            or not isinstance(token_length, int)
            or isinstance(token_length, bool)
            or token_length <= 0
            or offset < 0
            or offset + token_length > len(source)
        ):
            _fail(context, "source point is outside captured bytes")
        return offset, token_length

    def visit(  # noqa: C901, PLR0912 -- exhaustive enum ownership and origin gates
        node: object, top_level: bool
    ) -> None:
        """Traverse declarations and collect only bounded source enums.

        Parameters
        ----------
        node : object
            Raw AST node or nested value.
        top_level : bool
            Whether this enum is directly owned by the translation unit.

        Returns
        -------
        None
        """
        nonlocal source_enum_count, macro_enum_count, external_enum_count
        nonlocal unknown_enum_count
        if not isinstance(node, dict):
            return
        kind = node.get("kind")
        if kind == "EnumDecl":
            status = location_status(node.get("loc"))
            children = node.get("inner")
            enum_children = (
                [
                    child
                    for child in children
                    if isinstance(child, dict)
                    and child.get("kind") == "EnumConstantDecl"
                ]
                if isinstance(children, list)
                else []
            )
            if status == "external":
                external_enum_count += 1
            elif status == "unknown":
                unknown_enum_count += 1
                failures.append("enum declaration has no bound physical file")
            elif status == "source_macro":
                macro_enum_count += 1
                failures.append("source expansion touches an enum declaration")
            else:
                source_enum_count += 1
                enum_name = node.get("name")
                if not top_level:
                    failures.append("nested source enum is outside the bounded subset")
                if not isinstance(enum_name, str) or not enum_name:
                    failures.append(
                        "anonymous source enum is outside the bounded subset"
                    )
                else:
                    enum_offset, enum_token_length = physical_point(
                        node.get("loc"), "raw_ast.enum_decl.loc"
                    )
                    if source[
                        enum_offset : enum_offset + enum_token_length
                    ] != enum_name.encode("utf-8"):
                        failures.append("enum tag token differs from source bytes")
                if enum_children and (
                    not isinstance(enum_name, str) or source_key is None
                ):
                    failures.append("source enum member owner identity is unavailable")
                if isinstance(enum_name, str) and enum_name and source_key is not None:
                    for ordinal, member in enumerate(enum_children, start=1):
                        member_status = location_status(member.get("loc"))
                        if member_status != "source_written":
                            failures.append(
                                "enum member uses macro or unknown source origin"
                            )
                            continue
                        name = member.get("name")
                        if not isinstance(name, str) or not name:
                            failures.append("source enum member has no name")
                            continue
                        offset, token_length = physical_point(
                            member.get("loc"), "raw_ast.enum_member.loc"
                        )
                        if source[offset : offset + token_length] != name.encode(
                            "utf-8"
                        ):
                            failures.append(
                                "enum member token differs from source bytes"
                            )
                        line = source.count(b"\n", 0, offset) + 1
                        coordinate_line = (
                            member.get("loc", {}).get("line")
                            if isinstance(member.get("loc"), dict)
                            else None
                        )
                        if (
                            isinstance(coordinate_line, int)
                            and not isinstance(coordinate_line, bool)
                            and coordinate_line != line
                        ):
                            failures.append(
                                "enum member line differs from source bytes"
                            )
                        source_range = member.get("range")
                        if not isinstance(source_range, dict):
                            failures.append("enum member source range is absent")
                            continue
                        begin, end = source_range.get("begin"), source_range.get("end")
                        if (
                            location_status(begin) != "source_written"
                            or location_status(end) != "source_written"
                        ):
                            failures.append("enum member range crosses a macro origin")
                            continue
                        begin_offset, _ = physical_point(
                            begin, "raw_ast.enum_member.range.begin"
                        )
                        end_offset, end_length = physical_point(
                            end, "raw_ast.enum_member.range.end"
                        )
                        if (
                            begin_offset != offset
                            or end_offset + end_length < offset + token_length
                        ):
                            failures.append(
                                "enum member range does not cover its source token"
                            )
                        expected.append(
                            {
                                "owner": enum_name,
                                "name": name,
                                "ordinal": ordinal,
                                "line": line,
                            }
                        )
            if isinstance(children, list):
                for child in children:
                    if (
                        isinstance(child, dict)
                        and child.get("kind") != "EnumConstantDecl"
                    ):
                        visit(child, False)
            return
        if (
            kind == "EnumConstantDecl"
            and location_status(node.get("loc")) == "source_written"
        ):
            failures.append("source enum constant has no supported enum owner")
        children = node.get("inner")
        if isinstance(children, list):
            for child in children:
                visit(child, False)

    children = ast.get("inner")
    if isinstance(children, list):
        for child in children:
            visit(child, True)
    census: dict[str, JSONValue] = {
        "source_enum_declaration_count": source_enum_count,
        "macro_origin_enum_declaration_count": macro_enum_count,
        "external_enum_declaration_count": external_enum_count,
        "unbound_enum_declaration_count": unknown_enum_count,
        "source_enum_member_count": len(expected),
        "failures": cast("JSONValue", failures),
    }
    return expected, census


def _grade_source_doxygen_absence(  # noqa: C901 -- absence uses lexical and AST evidence
    source: bytes,
    ast: dict[str, object],
    source_path: Path,
    working_directory: Path,
    backend_rows: dict[str, dict[str, JSONValue]],
) -> dict[str, JSONValue]:
    """Grade only the proven absence of source-owned Doxygen documentation.

    Parameters
    ----------
    source : bytes
        Exact source bytes selected by the compile profile.
    ast : dict[str, object]
        Full raw Clang translation-unit AST.
    source_path : pathlib.Path
        Physical translation-unit source path.
    working_directory : pathlib.Path
        Compiler working directory for raw AST file references.
    backend_rows : dict[str, dict[str, JSONValue]]
        Documentation snapshot rows from SQLite and DuckDB.

    Returns
    -------
    dict[str, JSONValue]
        Absence-only documentation category report. Any source Doxygen
        candidate remains held until its semantic owner is independently bound.
    """
    offsets = _scan_c_doxygen_comment_offsets(source)
    location_files = _source_ast_file_bindings(ast, working_directory)
    source_path = source_path.resolve()
    source_comments = 0
    unbound_comments = 0

    def visit(node: object, source_owner: bool) -> None:
        """Count source-owned FullComment nodes in raw compiler AST.

        Parameters
        ----------
        node : object
            Raw AST value.
        source_owner : bool
            Whether an enclosing declaration belongs to the selected source.

        Returns
        -------
        None
        """
        nonlocal source_comments, unbound_comments
        if isinstance(node, list):
            for child in node:
                visit(child, source_owner)
            return
        if not isinstance(node, dict):
            return
        kind = node.get("kind")
        loc = node.get("loc")
        if not isinstance(loc, dict):
            source_range = node.get("range")
            loc = source_range.get("begin") if isinstance(source_range, dict) else None
        node_path = _point_file(loc, location_files)
        if kind == "FullComment":
            if node_path == source_path:
                source_comments += 1
            elif node_path is None and source_owner:
                unbound_comments += 1
        next_owner = source_owner or (
            kind in {"FunctionDecl", "RecordDecl", "EnumDecl", "EnumConstantDecl"}
            and node_path == source_path
        )
        for key, child in node.items():
            if key not in {"file", "includedFrom"}:
                visit(child, next_owner)

    visit(ast, False)
    failures: list[dict[str, JSONValue]] = []
    if offsets:
        failures.append(
            {
                "reason": "source Doxygen comments exist but owner attachment is outside this absence evaluator",
                "marker_count": len(offsets),
            }
        )
    if source_comments:
        failures.append(
            {
                "reason": "compiler AST contains source-owned FullComment nodes",
                "count": source_comments,
            }
        )
    if unbound_comments:
        failures.append(
            {
                "reason": "compiler AST FullComment source path is unbound",
                "count": unbound_comments,
            }
        )
    observed: dict[str, Counter[str]] = {}
    for backend, case in backend_rows.items():
        rows = _as_rows(case.get("documentation"), f"{backend}.documentation")
        observed[backend] = Counter(_canonical(cast("JSONValue", row)) for row in rows)
        if rows:
            failures.append(
                {
                    "backend": backend,
                    "reason": "documentation rows exist despite absence candidate evaluation",
                }
            )
    parity = observed.get("sqlite") == observed.get("duckdb") and len(observed) == 2
    if not parity:
        failures.append({"reason": "backend documentation rows differ"})
    return cast(
        "dict[str, JSONValue]",
        {
            "state": "graded" if not failures else "held",
            "semantic_validation": "source-byte-and-Clang-AST-Doxygen-absence",
            "expected_count": 0 if not offsets and not source_comments else None,
            "source_doxygen_marker_count": len(offsets),
            "compiler_ast_source_full_comment_count": source_comments,
            "compiler_ast_unbound_full_comment_count": unbound_comments,
            "observed_counts": {
                backend: sum(counter.values()) for backend, counter in observed.items()
            },
            "backend_parity": parity,
            "absence_proved": not failures,
            "failures": failures,
        },
    )


def _grade_source_enum_members(  # noqa: PLR0913 -- explicit source and backend inputs
    ast: dict[str, object],
    source: bytes,
    source_path: Path,
    working_directory: Path,
    source_key: str | None,
    backend_rows: dict[str, dict[str, JSONValue]],
) -> dict[str, JSONValue]:
    """Compare bounded source-written enum members with both backend snapshots.

    Parameters
    ----------
    ast : dict[str, object]
        Full raw Clang translation-unit AST.
    source : bytes
        Exact source bytes selected by the compile profile.
    source_path : pathlib.Path
        Physical translation-unit source path.
    working_directory : pathlib.Path
        Compiler working directory for raw AST file references.
    source_key : str or None
        Repository-relative source identity key.
    backend_rows : dict[str, dict[str, JSONValue]]
        Enum-member snapshot rows from SQLite and DuckDB.

    Returns
    -------
    dict[str, JSONValue]
        Exact enum-member category report. Macro-origin, nested, anonymous, or
        unbound source enum evidence remains held.
    """
    expected, census = _raw_source_enum_members(
        ast, source, source_path, working_directory, source_key
    )
    failures: list[dict[str, JSONValue]] = [
        {"reason": message} for message in cast("list[str]", census["failures"])
    ]
    expected_multiset = Counter(_canonical(cast("JSONValue", row)) for row in expected)
    observed: dict[str, Counter[str]] = {}
    for backend, case in backend_rows.items():
        rows = _as_rows(case.get("enum_members"), f"{backend}.enum_members")
        projected = [
            {key: row.get(key) for key in ("owner", "name", "ordinal", "line")}
            for row in rows
        ]
        observed[backend] = Counter(
            _canonical(cast("JSONValue", row)) for row in projected
        )
    parity = observed.get("sqlite") == observed.get("duckdb") and len(observed) == 2
    exact = {backend: value == expected_multiset for backend, value in observed.items()}
    if not parity:
        failures.append({"reason": "backend enum-member rows differ"})
    for backend, matches in exact.items():
        if not matches:
            failures.append(
                {
                    "backend": backend,
                    "missing": cast(
                        "JSONValue",
                        list((expected_multiset - observed[backend]).elements()),
                    ),
                    "extra": cast(
                        "JSONValue",
                        list((observed[backend] - expected_multiset).elements()),
                    ),
                }
            )
    return cast(
        "dict[str, JSONValue]",
        {
            "state": "graded" if not failures else "held",
            "semantic_validation": "source-byte-bound-Clang-enum-member-multiset",
            "expected_count": len(expected),
            "observed_counts": {
                backend: sum(counter.values()) for backend, counter in observed.items()
            },
            "exact_by_backend": exact,
            "backend_parity": parity,
            "source_enum_census": census,
            "failures": failures,
        },
    )


def grade_source_owned_ast_categories(  # noqa: PLR0913 -- explicit evidence inputs
    normalized: dict[str, JSONValue],
    raw_ast: dict[str, object],
    source: bytes,
    analyzer_capabilities: dict[str, JSONValue],
    backend_rows: dict[str, dict[str, JSONValue]],
    normalizer_path: Path,
    working_directory: Path,
    source_key: str | None = None,
) -> dict[str, JSONValue]:
    """Reconcile bounded source-owned AST facts against both backend rows.

    Parameters
    ----------
    normalized : dict[str, JSONValue]
        Replayed normalized Clang facts bound to the source and raw AST.
    raw_ast : dict[str, object]
        Raw Clang JSON AST for source-scope validation.
    source : bytes
        Exact source bytes used by the capture.
    analyzer_capabilities : dict[str, JSONValue]
        Explicit capabilities for the selected analyzer version.
    backend_rows : dict[str, dict[str, JSONValue]]
        Selected source rows from SQLite and DuckDB snapshots.
    normalizer_path : pathlib.Path
        Frozen normalizer copy bound to the capture.
    working_directory : pathlib.Path
        Exact compiler working directory bound to the profile.
    source_key : str or None, optional
        Repository-relative key used to bind stable caller identities.

    Returns
    -------
    dict[str, JSONValue]
        Category-only report. It never admits a whole file.
    """
    if set(backend_rows) != {"sqlite", "duckdb"}:
        _fail("backend_rows", "must contain exactly SQLite and DuckDB")
    expected = _source_owned_ast_expectations(
        normalized,
        raw_ast,
        source,
        analyzer_capabilities,
        normalizer_path,
        working_directory,
    )
    expected_calls = _reconcile_raw_source_call_sites(
        normalized,
        raw_ast,
        source,
        Path(_string(normalized.get("source_path"), "normalized.source_path")),
        working_directory,
        source_key,
    )
    source_path = Path(_string(normalized.get("source_path"), "normalized.source_path"))
    reports: dict[str, JSONValue] = {}
    for category, expected_rows in expected.items():
        expected_multiset = Counter(_canonical(row) for row in expected_rows)
        observed_multisets: dict[str, Counter[str]] = {}
        for backend, rows in backend_rows.items():
            values = _as_rows(rows.get(category), f"{backend}.{category}")
            if category == "declarations":
                projected = [
                    {key: row.get(key) for key in ("kind", "line", "name")}
                    for row in values
                ]
            elif category == "fields":
                projected = [
                    {key: row.get(key) for key in ("line", "name", "owner", "type")}
                    for row in values
                ]
            else:
                projected = [
                    {
                        key: row.get(key)
                        for key in (
                            "definition_line",
                            "kind",
                            "name",
                            "parameter_types",
                            "return_type",
                        )
                    }
                    for row in values
                ]
            observed_multisets[backend] = Counter(
                _canonical(cast("JSONValue", row)) for row in projected
            )
        parity = observed_multisets["sqlite"] == observed_multisets["duckdb"]
        exact = {
            backend: observed == expected_multiset
            for backend, observed in observed_multisets.items()
        }
        reports[category] = cast(
            "JSONValue",
            {
                "state": "graded" if parity and all(exact.values()) else "held",
                "semantic_validation": "source-bound-Clang-AST-exact-multiset",
                "expected_count": len(expected_rows),
                "observed_counts": {
                    backend: sum(observed.values())
                    for backend, observed in observed_multisets.items()
                },
                "exact_by_backend": exact,
                "backend_parity": parity,
                "failures": []
                if parity and all(exact.values())
                else [
                    {
                        "backend": backend,
                        "missing": list((expected_multiset - observed).elements()),
                        "extra": list((observed - expected_multiset).elements()),
                    }
                    for backend, observed in observed_multisets.items()
                    if observed != expected_multiset
                ],
            },
        )
    reports["calls"] = _grade_source_call_rows(expected_calls, backend_rows, source_key)
    reports["documentation"] = _grade_source_doxygen_absence(
        source,
        raw_ast,
        source_path,
        working_directory,
        backend_rows,
    )
    reports["enum_members"] = _grade_source_enum_members(
        raw_ast,
        source,
        source_path,
        working_directory,
        source_key,
        backend_rows,
    )
    return {
        "scope": "source-owned-records-fields-functions-calls-enum-members-and-doxygen-absence",
        "interpretation": "clang_parity_only_same_compiler_not_compiler_independent_truth",
        "whole_file_admission": False,
        "scope_complete": False,
        "categories": reports,
        "held_categories": cast(
            "JSONValue",
            sorted(
                category
                for category in set(FACT_CATEGORIES) - {"coverage"}
                if category not in reports
                or _object(
                    cast("dict[str, JSONValue]", reports[category]), category
                ).get("state")
                != "graded"
            ),
        ),
        "limitations": [
            "Calls with unresolved targets remain held; the raw CLI AST does not contain compiler USRs.",
            "The macro replacement and macro argument at the shared source expansion are separate origin-bound call occurrences.",
            "Raw CLI AST expansion locations do not independently prove the macro-definition-name edge.",
            "Doxygen documentation is graded only when both lexical source scanning and the bound Clang AST prove absence; positive source documentation remains held pending owner attachment proof.",
            "Enum members with macro, nested, anonymous, or unbound source origin remain held.",
            "The result does not establish whole-file parity or file admission.",
        ],
    }


def _reconcile_raw_source_call_sites(  # noqa: C901, PLR0913, PLR0912 -- exhaustive source call ownership and origin gates
    normalized: dict[str, JSONValue],
    ast: dict[str, object],
    source: bytes,
    source_path: Path,
    working_directory: Path,
    source_key: str | None,
) -> list[dict[str, JSONValue]]:
    """Build direct-call occurrences from raw Clang nodes and source locations.

    Parameters
    ----------
    normalized : dict[str, JSONValue]
        Replayed reference facts bound to the raw capture.
    ast : dict[str, object]
        Raw Clang JSON AST.
    source : bytes
        Exact captured translation-unit bytes.
    source_path : pathlib.Path
        Bound translation-unit path.
    working_directory : pathlib.Path
        Compile-command working directory for relative AST paths.
    source_key : str or None
        Repository-relative source key for stable caller identities.

    Returns
    -------
    list[dict[str, JSONValue]]
        One source-owned direct-call occurrence per raw CallExpr.

    Raises
    ------
    OracleFormatError
        If source calls are not exhaustive, direct, caller-bound, or physically
        anchored by a supported spelling or expansion location.
    """
    location_files: dict[int, Path | None] = {}
    active_file: list[Path | None] = [None]
    node_ids: dict[str, dict[str, object]] = {}

    def annotate(value: object) -> None:
        if isinstance(value, list):
            for child in value:
                annotate(child)
        elif isinstance(value, dict):
            node_id = value.get("id")
            kind = value.get("kind")
            if (
                isinstance(node_id, str)
                and isinstance(kind, str)
                and any(key in value for key in ("loc", "range", "inner"))
            ):
                node_ids[node_id] = value
            if "offset" in value:
                explicit_path = value.get("file")
                if isinstance(explicit_path, str):
                    raw_path = Path(explicit_path)
                    active_file[0] = (
                        raw_path.resolve()
                        if raw_path.is_absolute()
                        else (working_directory / raw_path).resolve()
                    )
                location_files[id(value)] = active_file[0]
            for key, child in value.items():
                if key not in {"file", "includedFrom"}:
                    annotate(child)

    annotate(ast)
    source_path = source_path.resolve()
    source_functions: dict[str, dict[str, JSONValue]] = {}
    expected: list[dict[str, JSONValue]] = []
    unsupported: list[str] = []
    transparent = {
        "ConstantExpr",
        "ExprWithCleanups",
        "ImplicitCastExpr",
        "ParenExpr",
        "MaterializeTemporaryExpr",
    }

    def direct_reference(call: dict[str, object]) -> dict[str, object] | None:
        children = call.get("inner")
        if not isinstance(children, list) or not children:
            return None
        current: object = children[0]
        while isinstance(current, dict):
            kind = current.get("kind")
            if kind == "DeclRefExpr":
                reference = current.get("referencedDecl")
                if (
                    isinstance(reference, dict)
                    and reference.get("kind") == "FunctionDecl"
                ):
                    return reference
                return None
            if kind not in transparent:
                return None
            nested = current.get("inner")
            if not isinstance(nested, list) or len(nested) != 1:
                return None
            current = nested[0]
        return None

    def point_location(
        value: object,
    ) -> tuple[dict[str, object] | None, Path | None]:
        if not isinstance(value, dict):
            return None, None
        file_path = location_files.get(id(value))
        return value, file_path

    def choose_source_point(
        call_begin: object, callee_begin: object
    ) -> tuple[str, dict[str, object], Path] | None:
        if not isinstance(call_begin, dict):
            return None
        spelling = call_begin.get("spellingLoc")
        expansion = call_begin.get("expansionLoc")
        if isinstance(spelling, dict) or isinstance(expansion, dict):
            spelling_point, spelling_path = point_location(spelling)
            expansion_point, expansion_path = point_location(expansion)
            if (
                expansion_point is not None
                and expansion_point.get("isMacroArgExpansion") is True
                and spelling_path == source_path
                and spelling_point is not None
            ):
                return "macro_argument", spelling_point, source_path
            if expansion_point is not None and expansion_path == source_path:
                return "macro_replacement", expansion_point, source_path
            if spelling_path == source_path and spelling_point is not None:
                unsupported.append(
                    "macro spelling is source-owned without proven argument expansion"
                )
                return None
            return None
        call_point, call_path = point_location(call_begin)
        if call_point is None or call_path != source_path:
            return None
        callee_point, callee_path = point_location(callee_begin)
        if callee_point is None or callee_path != source_path:
            unsupported.append("source-written call has no source-owned callee point")
            return None
        return "source_written", callee_point, source_path

    def source_definition(node: dict[str, object]) -> tuple[str, int, str] | None:
        location = node.get("loc")
        if (
            not isinstance(location, dict)
            or location_files.get(id(location)) != source_path
        ):
            return None
        children = node.get("inner")
        name, type_value = node.get("name"), node.get("type")
        if (
            not isinstance(children, list)
            or not any(
                isinstance(child, dict)
                and child.get("kind") in {"CompoundStmt", "CXXTryStmt"}
                for child in children
            )
            or not isinstance(name, str)
            or not isinstance(type_value, dict)
            or not isinstance(type_value.get("qualType"), str)
        ):
            return None
        offset = location.get("offset")
        if (
            not isinstance(offset, int)
            or isinstance(offset, bool)
            or not 0 <= offset < len(source)
        ):
            return None
        line = source.count(b"\n", 0, offset) + 1
        return name, line, cast("str", type_value["qualType"])

    def collect_source_definitions(value: object) -> None:
        if isinstance(value, list):
            for child in value:
                collect_source_definitions(child)
        elif isinstance(value, dict):
            if value.get("kind") == "FunctionDecl":
                definition = source_definition(value)
                node_id = value.get("id")
                if definition is not None and isinstance(node_id, str):
                    source_functions[node_id] = {
                        "name": definition[0],
                        "definition_line": definition[1],
                        "type": definition[2],
                    }
            for child in value.values():
                collect_source_definitions(child)

    collect_source_definitions(ast)

    def visit(  # noqa: C901, PLR0912 -- exhaustive raw call occurrence walk
        node: object, caller: tuple[str, int, str] | None
    ) -> None:
        if not isinstance(node, dict):
            return
        kind = node.get("kind")
        next_caller = caller
        if kind == "FunctionDecl":
            next_caller = source_definition(node)
        if kind == "CallExpr":
            call_range = node.get("range")
            call_begin = (
                call_range.get("begin") if isinstance(call_range, dict) else None
            )
            callee = direct_reference(node)
            callee_range = None
            if isinstance(node.get("inner"), list) and node["inner"]:
                first = node["inner"][0]
                while isinstance(first, dict) and first.get("kind") in transparent:
                    nested = first.get("inner")
                    first = (
                        nested[0]
                        if isinstance(nested, list) and len(nested) == 1
                        else None
                    )
                callee_range = first.get("range") if isinstance(first, dict) else None
            callee_begin = (
                callee_range.get("begin") if isinstance(callee_range, dict) else None
            )
            selected = choose_source_point(call_begin, callee_begin)
            if selected is not None:
                origin, point, _ = selected
                if callee is None or not isinstance(callee.get("id"), str):
                    unsupported.append(
                        "source call target is not a direct FunctionDecl reference"
                    )
                elif caller is None:
                    unsupported.append(
                        "source call has no source-owned caller definition"
                    )
                else:
                    offset, token_length = point.get("offset"), point.get("tokLen")
                    target_name = callee.get("name")
                    target_type = callee.get("type")
                    reference_id = cast("str", callee["id"])
                    if (
                        not isinstance(offset, int)
                        or isinstance(offset, bool)
                        or not isinstance(token_length, int)
                        or isinstance(token_length, bool)
                        or token_length <= 0
                        or not isinstance(target_name, str)
                        or not isinstance(target_type, dict)
                        or not isinstance(target_type.get("qualType"), str)
                        or offset < 0
                        or offset + token_length > len(source)
                    ):
                        unsupported.append(
                            "source call lacks a physical callee or expansion token"
                        )
                    else:
                        token = source[offset : offset + token_length]
                        if (
                            origin != "macro_replacement"
                            and token != target_name.encode("utf-8")
                        ):
                            unsupported.append(
                                "call spelling differs from the referenced callee"
                            )
                        elif origin == "macro_replacement":
                            invocation_tail = offset + token_length
                            while (
                                invocation_tail < len(source)
                                and source[invocation_tail] in b" \t\r\n"
                            ):
                                invocation_tail += 1
                            if (
                                re.fullmatch(rb"[A-Za-z_][A-Za-z0-9_]*", token) is None
                                or invocation_tail >= len(source)
                                or source[invocation_tail] != ord("(")
                            ):
                                unsupported.append(
                                    "macro replacement expansion lacks a source function-like invocation"
                                )
                        line = source.count(b"\n", 0, offset) + 1
                        column = offset - source.rfind(b"\n", 0, offset) - 1
                        target_node = node_ids.get(reference_id)
                        target_definition = None
                        seen: set[str] = set()
                        pending = [reference_id]
                        while pending:
                            current_id = pending.pop()
                            if current_id in seen:
                                continue
                            seen.add(current_id)
                            current = node_ids.get(current_id)
                            if current is None or current.get("kind") != "FunctionDecl":
                                continue
                            if current_id in source_functions:
                                candidate = source_functions[current_id]
                                if (
                                    target_definition is not None
                                    and candidate != target_definition
                                ):
                                    target_definition = None
                                    unsupported.append(
                                        "call target resolves to multiple source definitions"
                                    )
                                    break
                                target_definition = candidate
                            previous = current.get("previousDecl")
                            if isinstance(previous, str):
                                pending.append(previous)
                        if target_node is None:
                            unsupported.append(
                                "referenced FunctionDecl id is absent from raw AST"
                            )
                        else:
                            if target_definition is not None:
                                definition_type = target_definition.get("type")
                                if definition_type != target_type["qualType"]:
                                    unsupported.append(
                                        "referenced target type differs from its source definition"
                                    )
                            expected.append(
                                {
                                    "line": line,
                                    "column": column,
                                    "origin": origin,
                                    "caller_name": caller[0],
                                    "caller_definition_line": caller[1],
                                    "caller_stable_id": (
                                        f"c:function:{source_key}:{caller[0]}"
                                        if source_key is not None
                                        else None
                                    ),
                                    "target_name": target_name,
                                    "target_type": cast("str", target_type["qualType"]),
                                    "target_definition": target_definition,
                                    "resolved": target_definition is not None,
                                    "target_reference_id": reference_id,
                                }
                            )
        children = node.get("inner")
        if isinstance(children, list):
            for child in children:
                visit(child, next_caller)

    visit(ast, None)
    if expected and source_key is None:
        unsupported.append("source key is required to bind caller stable identities")
    if unsupported:
        _fail("raw_ast.calls", f"unsupported source call evidence: {unsupported[:3]}")
    facts = _object(normalized.get("facts"), "normalized.facts")
    normalized_calls = _as_rows(facts.get("calls"), "normalized.calls")

    def normalized_caller(row: dict[str, JSONValue]) -> JSONValue:
        """Return the innermost normalized caller when present.

        Parameters
        ----------
        row : dict[str, JSONValue]
            Normalized call fact.

        Returns
        -------
        JSONValue
            Last caller-chain value, or None when absent.
        """
        chain = row.get("caller_chain")
        if not isinstance(chain, list) or not chain:
            return None
        return chain[-1]

    raw_projection = Counter(
        _canonical(
            cast(
                "JSONValue",
                {
                    "caller": row["caller_name"],
                    "line": row["line"],
                    "target": row["target_name"],
                    "type": row["target_type"],
                },
            )
        )
        for row in expected
    )
    normalized_projection = Counter(
        _canonical(
            cast(
                "JSONValue",
                {
                    "caller": normalized_caller(row),
                    "line": row.get("line"),
                    "target": _object(
                        row.get("direct_target"), "normalized.call.direct_target"
                    ).get("name"),
                    "type": _object(
                        row.get("direct_target"), "normalized.call.direct_target"
                    ).get("type"),
                },
            )
        )
        for row in normalized_calls
    )
    if raw_projection != normalized_projection:
        _fail(
            "raw_ast.calls",
            "raw source calls differ from the replayed normalized multiset",
        )
    return expected


def _grade_source_call_rows(
    expected: list[dict[str, JSONValue]],
    backend_rows: dict[str, dict[str, JSONValue]],
    source_key: str | None,
) -> dict[str, JSONValue]:
    """Compare raw source call occurrences with persisted backend call rows.

    Parameters
    ----------
    expected : list[dict[str, JSONValue]]
        Raw AST occurrences with bound source coordinates and caller facts.
    backend_rows : dict[str, dict[str, JSONValue]]
        Selected call rows from SQLite and DuckDB.
    source_key : str or None
        Repository-relative source key used to derive stable source identities.

    Returns
    -------
    dict[str, JSONValue]
        Call occurrence comparison, with unresolved targets held.
    """
    expected_projection = Counter(
        _canonical(
            cast(
                "JSONValue",
                {
                    key: row[key]
                    for key in (
                        "line",
                        "column",
                        "origin",
                        "caller_name",
                        "caller_stable_id",
                        "target_name",
                        "resolved",
                    )
                },
            )
        )
        for row in expected
    )
    observed: dict[str, Counter[str]] = {}
    failures: list[dict[str, JSONValue]] = []
    unresolved_counts: dict[str, int] = {}
    resolved_counts: dict[str, int] = {}
    for backend, case in backend_rows.items():
        rows = _as_rows(case.get("calls"), f"{backend}.calls")
        projection: list[dict[str, JSONValue]] = []
        unresolved = 0
        resolved = 0
        for row in rows:
            target_name = (
                row.get("callee_qualified_name")
                if row.get("resolved") is True
                else row.get("unresolved_target_qualified_name")
            )
            projection.append(
                {
                    "line": row.get("line"),
                    "column": row.get("column"),
                    "origin": row.get("origin"),
                    "caller_name": row.get("caller_qualified_name"),
                    "caller_stable_id": row.get("caller_stable_id"),
                    "target_name": target_name,
                    "resolved": row.get("resolved"),
                }
            )
            target_usr = row.get("target_identity_value")
            if (
                row.get("target_identity_namespace") != "clang.usr.v1"
                or not isinstance(target_usr, str)
                or not target_usr
            ):
                failures.append(
                    {
                        "backend": backend,
                        "reason": "target USR field is absent or malformed",
                    }
                )
            if row.get("resolution_mode") != "exact":
                failures.append(
                    {"backend": backend, "reason": "call resolution mode is not exact"}
                )
            if row.get("resolved") is True:
                resolved += 1
                target_definition = next(
                    (
                        expected_row.get("target_definition")
                        for expected_row in expected
                        if expected_row.get("line") == row.get("line")
                        and expected_row.get("column") == row.get("column")
                        and expected_row.get("target_name") == target_name
                        and expected_row.get("origin") == row.get("origin")
                    ),
                    None,
                )
                if not isinstance(target_definition, dict):
                    failures.append(
                        {
                            "backend": backend,
                            "reason": "resolved callee lacks a source definition",
                        }
                    )
                else:
                    definition_name = target_definition.get("name")
                    definition_line = target_definition.get("definition_line")
                    definition_type = target_definition.get("type")
                    if not isinstance(definition_type, str):
                        failures.append(
                            {
                                "backend": backend,
                                "reason": "resolved target lacks a source definition type",
                            }
                        )
                        continue
                    return_type, parameter_types = _parse_simple_function_type(
                        definition_type
                    )
                    expected_stable_id = f"c:function:{source_key}:{definition_name}"
                    if (
                        row.get("callee_stable_id") != expected_stable_id
                        or row.get("callee_qualified_name") != definition_name
                        or row.get("callee_definition_line") != definition_line
                        or row.get("callee_source") != source_key
                        or row.get("return_type") != return_type
                        or row.get("parameter_types") != parameter_types
                    ):
                        failures.append(
                            {
                                "backend": backend,
                                "reason": "resolved callee identity differs from raw source definition",
                            }
                        )
            else:
                unresolved += 1
                if (
                    row.get("resolved") is not False
                    or row.get("callee_stable_id") is not None
                    or row.get("callee_qualified_name") is not None
                    or row.get("callee_source") is not None
                    or row.get("callee_definition_line") is not None
                    or row.get("parameter_types") is not None
                    or row.get("return_type") is not None
                    or row.get("unresolved_target_qualified_name") != target_name
                ):
                    failures.append(
                        {
                            "backend": backend,
                            "reason": "unresolved call row has inconsistent target state",
                        }
                    )
        observed[backend] = Counter(
            _canonical(cast("JSONValue", row)) for row in projection
        )
        unresolved_counts[backend] = unresolved
        resolved_counts[backend] = resolved
    parity = observed.get("sqlite") == observed.get("duckdb") and len(observed) == 2
    exact = {
        backend: value == expected_projection for backend, value in observed.items()
    }
    full_rows = {
        backend: Counter(
            _canonical(cast("JSONValue", row))
            for row in _as_rows(case.get("calls"), f"{backend}.calls")
        )
        for backend, case in backend_rows.items()
    }
    full_backend_parity = (
        full_rows.get("sqlite") == full_rows.get("duckdb") and len(full_rows) == 2
    )
    if not parity:
        failures.append({"reason": "backend occurrence projections differ"})
    if not full_backend_parity:
        failures.append(
            {"reason": "backend call rows differ beyond the source projection"}
        )
    for backend, matches in exact.items():
        if not matches:
            failures.append(
                {"backend": backend, "reason": "raw AST occurrence multiset differs"}
            )
    unresolved_total = max(unresolved_counts.values(), default=0)
    target_usr_proved = False
    no_calls = not expected and not any(unresolved_counts.values())
    state = "graded" if no_calls and not failures else "held"
    return cast(
        "dict[str, JSONValue]",
        {
            "state": state,
            "semantic_validation": "raw-Clang-AST-origin-aware-occurrence-multiset",
            "expected_count": len(expected),
            "observed_counts": {
                backend: sum(counter.values()) for backend, counter in observed.items()
            },
            "exact_occurrence_multiset_by_backend": exact,
            "backend_occurrence_parity": parity,
            "full_backend_row_parity": full_backend_parity,
            "source_resolved_target_count": min(resolved_counts.values(), default=0),
            "unresolved_target_count": unresolved_total,
            "target_usr_verified": target_usr_proved,
            "target_usr_limitation": (
                "Raw Clang JSON AST does not emit USRs; no USR values were inferred."
            ),
            "failures": failures,
        },
    )


def grade_source_owned_ast_evidence(  # noqa: C901, PLR0912, PLR0915 -- end-to-end evidence chain
    request: SourceOwnedAstGradeRequest,
) -> dict[str, JSONValue]:
    """Validate retained capture bindings and grade bounded source AST facts.

    Parameters
    ----------
    request : SourceOwnedAstGradeRequest
        Raw capture, normalization, profile, guard, database and snapshot paths.

    Returns
    -------
    dict[str, JSONValue]
        Category-only report with source, capture, profile and database digests.

    Raises
    ------
    OracleFormatError
        If any retained identity, guard, AST projection or backend comparison
        is incomplete or inconsistent.
    OSError
        If an evidence input cannot be read or a current guard has disappeared.
    """
    source_path = request.source_path.resolve()
    source_bytes = source_path.read_bytes()
    source_hash = hashlib.sha256(source_bytes).hexdigest()
    record_path = request.normalization_record_path
    normalization_record_hash = _sha256(record_path)
    record = _read_json_object(record_path, "normalization record")
    normalized_path = request.normalized_path
    normalized_hash = _sha256(normalized_path)
    normalized = _read_json_object(normalized_path, "normalized AST facts")
    if (
        record.get("schema") != "codira.clang-cfp017-native-cli-ast-normalization/1"
        or record.get("status") != "complete"
        or record.get("whole_file_admission") is not False
        or record.get("normalized_output_path") != str(normalized_path.resolve())
        or record.get("normalized_output_sha256") != normalized_hash
        or record.get("normalized_reference_sha256") != normalized_hash
        or record.get("normalized_reference_path") != str(normalized_path.resolve())
        or record.get("source_path") != str(source_path)
        or record.get("source_sha256") != source_hash
    ):
        _fail("normalization.record", "does not bind these source and normalized bytes")
    normalizer_path = Path(
        _string(record.get("normalizer_path"), "normalization.normalizer_path")
    )
    normalizer_hash = _string(
        record.get("normalizer_sha256"), "normalization.normalizer_sha256"
    )
    if not normalizer_path.is_file() or _sha256(normalizer_path) != normalizer_hash:
        _fail("normalization.normalizer", "frozen normalizer path or digest changed")
    raw_path = Path(_string(record.get("raw_ast_path"), "normalization.raw_ast_path"))
    raw_hash = _string(record.get("raw_ast_sha256"), "normalization.raw_ast_sha256")
    if not raw_path.is_file() or _sha256(raw_path) != raw_hash:
        _fail("normalization.raw_ast", "raw AST bytes are absent or changed")
    raw_ast_value = json.loads(raw_path.read_text(encoding="utf-8"))
    raw_ast = _object(raw_ast_value, "raw Clang AST")

    summary_path = request.capture_summary_path
    summary = _read_json_object(summary_path, "capture summary")
    repository_capture = _object(
        summary.get("llvm_source_repository"), "capture.summary.llvm_source_repository"
    )
    source_summary = _object(summary.get("source"), "capture.summary.source")
    profile_summary = _object(summary.get("profile"), "capture.summary.profile")
    if (
        record.get("capture_input_binding_path") != str(summary_path.resolve())
        or record.get("capture_input_binding_sha256") != _sha256(summary_path)
        or record.get("capture_identity") != summary.get("identity")
        or summary.get("status") != "complete"
        or repository_capture.get("pre_post_guards_equal") is not True
        or source_summary.get("path") != str(source_path)
        or source_summary.get("sha256") != source_hash
        or profile_summary.get("sha256") != record.get("profile_sha256")
    ):
        _fail(
            "capture.summary",
            "does not prove a completed matching source/profile capture",
        )
    attempt = _object(summary.get("attempt"), "capture.summary.attempt")
    if (
        attempt.get("prepared_inputs_sha256")
        != record.get("capture_prepared_inputs_sha256")
        or attempt.get("stdout_sha256") != raw_hash
        or attempt.get("return_code") != 0
    ):
        _fail("capture.summary.attempt", "raw AST or prepared-input binding differs")
    terminal_path = Path(
        _string(
            record.get("capture_terminal_path"), "normalization.capture_terminal_path"
        )
    )
    if (
        not terminal_path.is_file()
        or _sha256(terminal_path) != record.get("capture_terminal_sha256")
        or str(terminal_path.resolve()) != str(terminal_path)
    ):
        _fail("capture.terminal", "terminal record path or digest is invalid")
    terminal = _read_json_object(terminal_path, "capture terminal")
    toolchain = _object(summary.get("toolchain"), "capture.summary.toolchain")
    if (
        terminal.get("identity") != summary.get("identity")
        or terminal.get("status") != "complete"
        or terminal.get("return_code") != 0
        or terminal.get("admission") is not False
        or terminal.get("whole_file_grade") is not False
        or terminal.get("stdout_sha256") != raw_hash
        or terminal.get("source_sha256") != source_hash
        or terminal.get("profile_sha256") != record.get("profile_sha256")
        or terminal.get("compiler_sha256") != toolchain.get("compiler_sha256")
    ):
        _fail("capture.terminal", "is not the successful matching raw AST attempt")

    prepared_path = request.prepared_inputs_path
    prepared = _read_json_object(prepared_path, "capture prepared inputs")
    if (
        _sha256(prepared_path) != record.get("capture_prepared_inputs_sha256")
        or prepared.get("identity") != summary.get("identity")
        or prepared.get("profile_sha256") != record.get("profile_sha256")
        or prepared.get("source_sha256") != source_hash
        or prepared.get("working_directory") != record.get("working_directory")
    ):
        _fail("capture.prepared_inputs", "does not match normalized capture bindings")
    expected_input_hashes = _object(
        prepared.get("expected_input_hashes"), "prepared_inputs.expected_input_hashes"
    )
    cdb = _object(summary.get("compile_database"), "capture.summary.compile_database")
    paths_and_hashes = {
        "source": (source_path, source_hash),
        "profile": (
            Path(_string(profile_summary.get("path"), "profile.path")),
            record.get("profile_sha256"),
        ),
        "compile_database": (
            Path(_string(cdb.get("path"), "compile_database.path")),
            cdb.get("sha256"),
        ),
        "compiler": (
            Path(_string(toolchain.get("compiler_path"), "compiler.path")),
            toolchain.get("compiler_sha256"),
        ),
        "helper": (
            Path(_string(toolchain.get("helper_path"), "helper.path")),
            toolchain.get("helper_sha256"),
        ),
        "build_receipt": (
            Path(_string(prepared.get("build_receipt_path"), "build_receipt.path")),
            prepared.get("build_receipt_sha256"),
        ),
    }
    for label, (path, digest) in paths_and_hashes.items():
        if not isinstance(digest, str) or not path.is_file() or _sha256(path) != digest:
            _fail(f"capture.input.{label}", "bound input file is absent or has changed")
        expected_key = "compile_database" if label == "compile_database" else label
        if expected_input_hashes.get(expected_key) != digest:
            _fail(f"capture.input.{label}", "prepared-input digest differs")
    if (
        cdb.get("path") != str(paths_and_hashes["compile_database"][0])
        or cdb.get("sha256") != paths_and_hashes["compile_database"][1]
        or prepared.get("compiler_path") != str(paths_and_hashes["compiler"][0])
        or prepared.get("compiler_sha256") != paths_and_hashes["compiler"][1]
        or prepared.get("helper_path") != str(paths_and_hashes["helper"][0])
        or prepared.get("helper_sha256") != paths_and_hashes["helper"][1]
    ):
        _fail(
            "capture.inputs",
            "summary and prepared inputs identify different toolchain files",
        )

    before_path, after_path = request.guards_before_path, request.guards_after_path
    before = _read_json_object(before_path, "pre-capture guards")
    after = _read_json_object(after_path, "post-capture guards")
    before_source = _object(before.get("source"), "capture.guards.source")
    if before != after or before_source.get("sha256") != source_hash:
        _fail("capture.guards", "pre/post inputs differ or source guard changed")
    input_repository_root = Path(
        _string(before_source.get("repository"), "capture.guards.source.repository")
    ).resolve()
    if (
        source_path != input_repository_root
        and input_repository_root not in source_path.parents
    ):
        _fail(
            "capture.guards.source",
            "original source is outside the guarded repository root",
        )
    _validate_source_key(source_path, request.source_key, input_repository_root)
    if _sha256(before_path) != attempt.get("guards_before_sha256") or _sha256(
        after_path
    ) != attempt.get("guards_after_sha256"):
        _fail("capture.guards", "guard snapshot hashes differ from capture terminal")
    guard_profile = _object(before.get("profile"), "capture.guards.profile")
    for dependency_value in cast(
        "list[JSONValue]", guard_profile.get("dependencies", [])
    ):
        dependency = _object(dependency_value, "guard dependency")
        dependency_path = Path(_string(dependency.get("path"), "guard dependency.path"))
        expected_hash = _string(
            dependency.get("expected_sha256"), "guard dependency.expected_sha256"
        )
        if (
            dependency.get("actual_sha256") != expected_hash
            or not dependency_path.is_file()
            or _sha256(dependency_path) != expected_hash
        ):
            _fail("capture.guard.dependency", "dependency changed after capture")
    from codira_clang_frontend import directory_membership_sha256

    directories = guard_profile.get("include_directories")
    if not isinstance(directories, list) or len(directories) != profile_summary.get(
        "include_directory_count"
    ):
        _fail("capture.guard.include_directories", "directory inventory is incomplete")
    guarded_directory_paths: set[Path] = set()
    for directory_value in directories:
        directory = _object(directory_value, "guard include directory")
        directory_path = Path(
            _string(directory.get("path"), "include_directory.path")
        ).resolve()
        guarded_directory_paths.add(directory_path)
        membership = _string(
            directory.get("expected_membership_sha256"),
            "include_directory.expected_membership_sha256",
        )
        if (
            directory.get("actual_membership_sha256") != membership
            or directory_membership_sha256(directory_path) != membership
        ):
            _fail(
                "capture.guard.include_directory",
                "include directory membership changed",
            )
    from codira_clang_frontend import (
        __version__ as frontend_version,
        frontend_profile_fingerprint,
    )

    profile_bindings: dict[str, JSONValue] = {
        "profile_path": str(paths_and_hashes["profile"][0]),
        "helper_path": str(paths_and_hashes["helper"][0]),
        "build_receipt_path": str(paths_and_hashes["build_receipt"][0]),
        "frontend_version": frontend_version,
    }
    source_binding: dict[str, JSONValue] = {
        "path": str(source_path),
        "sha256": source_hash,
        "language": "c",
    }
    frontend, profile = _load_bound_frontend_profile(
        profile_bindings, source_binding, source_path, input_repository_root
    )
    profile_directory_paths = {
        directory.path.resolve() for directory in profile.include_directories
    }
    if guarded_directory_paths != profile_directory_paths:
        _fail(
            "capture.guard.include_directories",
            "guarded paths differ from the loaded profile",
        )
    guarded_dependencies = {
        (
            Path(_string(item.get("path"), "guard dependency.path")).resolve(),
            item.get("expected_sha256"),
        )
        for item in cast("list[JSONValue]", guard_profile.get("dependencies", []))
        if isinstance(item, dict)
    }
    profile_dependencies = {
        (dependency.path.resolve(), dependency.sha256)
        for dependency in profile.dependencies
    }
    if guarded_dependencies != profile_dependencies:
        _fail(
            "capture.guard.dependencies",
            "guarded dependency set differs from loaded profile",
        )
    if (
        Path(profile.working_directory).resolve()
        != Path(
            _string(record.get("working_directory"), "normalization.working_directory")
        ).resolve()
    ):
        _fail("capture.profile", "loaded working directory differs from normalization")
    _validate_compile_database_row(
        paths_and_hashes["compile_database"][0], profile, source_path
    )
    expected_argv = [
        Path(_string(toolchain.get("compiler_path"), "compiler.path")).as_posix()
    ]
    original_argv = list(profile.argv)
    index = 1
    while index < len(original_argv):
        argument = original_argv[index]
        if argument == "-o":
            if index + 1 >= len(original_argv):
                _fail("capture.profile.argv", "has an incomplete output argument")
            index += 2
            continue
        if argument == "-c":
            index += 1
            continue
        expected_argv.append(argument)
        index += 1
    expected_argv.extend(["-Xclang", "-ast-dump=json", "-fsyntax-only"])
    invocation_path = Path(
        _string(
            attempt.get("invocation_path"), "capture.summary.attempt.invocation_path"
        )
    )
    if not invocation_path.is_file() or _sha256(invocation_path) != attempt.get(
        "invocation_sha256"
    ):
        _fail("capture.invocation", "invocation identity is absent or changed")
    invocation = _read_json_object(invocation_path, "capture invocation")
    invocation_argv = invocation.get("compiler_argv")
    if (
        invocation.get("identity") != summary.get("identity")
        or invocation.get("working_directory") != str(profile.working_directory)
        or invocation_argv != expected_argv
        or prepared.get("compiler_argv") != expected_argv
    ):
        _fail("capture.invocation", "does not match exact adapted profile argv")

    analyzer_package = importlib.import_module("codira_analyzer_c")
    analyzer = analyzer_package.build_analyzer()
    analyzer.configure(
        {
            "frontend": "clang",
            "clang_captured_profiles": str(paths_and_hashes["profile"][0]),
            "clang_helper_path": str(paths_and_hashes["helper"][0]),
            "clang_build_receipt_path": str(paths_and_hashes["build_receipt"][0]),
        }
    )
    capability_declaration = analyzer.analyzer_capability_declaration()
    analyzer_module_path = Path(inspect.getsourcefile(analyzer_package) or "").resolve()
    package_root = analyzer_module_path.parent
    repository_root = request.repository_root.resolve()
    try:
        analyzer_module_path.relative_to(repository_root)
        package_root.relative_to(repository_root)
    except ValueError:
        _fail(
            "analyzer.implementation",
            "loaded C analyzer implementation is outside the source worktree",
        )
    if not analyzer_module_path.is_file() or not package_root.is_dir():
        _fail(
            "analyzer.implementation",
            "loaded C analyzer implementation is absent",
        )
    analyzer_implementation_hashes = {
        str(path.resolve()): _sha256(path)
        for path in sorted(package_root.rglob("*.py"))
        if path.is_file()
    }
    if not analyzer_implementation_hashes:
        _fail("analyzer.implementation", "package has no bound Python sources")
    analyzer_capabilities: dict[str, JSONValue] = {
        "analyzer_version": str(capability_declaration.analyzer_version),
        "supports": list(capability_declaration.supports),
        "does_not_support": list(capability_declaration.does_not_support),
    }

    rows_by_backend: dict[str, dict[str, JSONValue]] = {}
    context_ids: dict[str, str] = {}
    verified_database_bindings: dict[str, dict[str, JSONValue]] = {}
    receipt_file_hashes: dict[Path, str] = {}
    for backend in ("sqlite", "duckdb"):
        snapshot_path = request.snapshot_paths[backend]
        receipt_file_hashes[snapshot_path] = _sha256(snapshot_path)
        snapshot = _read_json_object(snapshot_path, f"{backend} snapshot")
        binding_path = request.database_binding_paths[backend]
        receipt_file_hashes[binding_path] = _sha256(binding_path)
        binding = _read_json_object(binding_path, f"{backend} database binding")
        database_path = Path(
            _string(binding.get("database_path"), f"{backend}.database_path")
        )
        actual_binding = _database_generation_binding(database_path, backend)
        if actual_binding != binding or snapshot.get("database_binding") != binding:
            _fail(
                f"{backend}.snapshot.database_binding",
                "does not match current database generation",
            )
        if snapshot.get("profile_document_sha256") != _sha256(
            request.profile_document_path
        ):
            _fail(f"{backend}.snapshot.profile", "profile document hash differs")
        case = _validate_snapshot_binding(
            SnapshotBindingInput(
                snapshot,
                backend,
                request.source_key,
                source_hash,
                binding,
                _sha256(request.profile_document_path),
            )
        )
        actual_context_identity = _read_indexed_context_identity(
            backend,
            database_path,
            input_repository_root,
            request.source_key,
            source_hash,
        )
        if actual_context_identity != case.get("analysis_input_fingerprint"):
            _fail(
                f"{backend}.snapshot.context",
                "snapshot differs from actual indexed database context",
            )
        context = _validate_indexed_context_identity(
            backend,
            actual_context_identity,
            frontend_profile_fingerprint(frontend, profile),
        )
        context_ids[backend] = _string(
            context.get("clang_frontend_fingerprint"),
            f"{backend}.clang_frontend_fingerprint",
        )
        persisted = _read_actual_analysis_status(
            database_path, backend, source_path, source_hash
        )
        receipt_file_hashes[request.status_paths[backend]] = _sha256(
            request.status_paths[backend]
        )
        status_document = _read_json_object(
            request.status_paths[backend], f"{backend} persisted status"
        )
        persisted_claim = {key: status_document.get(key) for key in persisted}
        if (
            _canonical(cast("JSONValue", persisted))
            != _canonical(cast("JSONValue", persisted_claim))
            or status_document.get("analysis_input_fingerprint")
            != actual_context_identity
        ):
            _fail(
                f"{backend}.persisted_status",
                "exported receipt differs from actual database row",
            )
        target = _object(persisted.get("target_contract"), f"{backend}.target_contract")
        toolchain_identity = _object(
            target.get("toolchain_identity"), f"{backend}.toolchain_identity"
        )
        dependency_closure = _object(
            target.get("dependency_closure"), f"{backend}.dependency_closure"
        )
        build_receipt = _read_json_object(
            paths_and_hashes["build_receipt"][0], "Clang build receipt"
        )
        if (
            persisted.get("analyzer_name") != "c"
            or persisted.get("analyzer_version")
            != analyzer_capabilities["analyzer_version"]
            or persisted.get("coverage_state") != "complete"
            or persisted.get("omitted_categories") != []
            or persisted.get("grammar") != "clang-c-frontend"
            or target.get("language") != "c"
            or target.get("frontend") != "clang"
            or target.get("requested_source_path") != str(source_path)
            or target.get("requested_source_sha256") != source_hash
            or target.get("profile_identity") != profile.identity
            or dependency_closure.get("file_count") != len(profile.dependencies)
            or dependency_closure.get("status") != "complete"
            or toolchain_identity.get("compiler_version")
            != toolchain.get("compiler_version")
            or toolchain_identity.get("compiler_path")
            != str(paths_and_hashes["compiler"][0])
            or toolchain_identity.get("compiler_sha256")
            != paths_and_hashes["compiler"][1]
            or toolchain_identity.get("helper_sha256") != paths_and_hashes["helper"][1]
            or toolchain_identity.get("helper_path")
            != str(paths_and_hashes["helper"][0])
            or toolchain_identity.get("build_receipt_sha256")
            != paths_and_hashes["build_receipt"][1]
            or toolchain_identity.get("resource_dir")
            != build_receipt.get("resource_dir")
            or toolchain_identity.get("resource_probe_sha256")
            != build_receipt.get("resource_probe_sha256")
        ):
            _fail(
                f"{backend}.persisted_status",
                "does not bind this C/Clang profile and toolchain",
            )
        reliable = persisted.get("reliable_categories")
        if not isinstance(reliable, list) or not {"function", "declaration"}.issubset(
            reliable
        ):
            _fail(
                f"{backend}.persisted_status",
                "does not declare the selected persisted categories reliable",
            )
        rows_by_backend[backend] = case
        verified_database_bindings[backend] = binding
        if _database_generation_binding(database_path, backend) != binding:
            _fail(
                f"{backend}.snapshot.database_binding",
                "database generation changed while evidence was read",
            )
    if len(set(context_ids.values())) != 1:
        _fail(
            "backend.profile_context",
            "SQLite and DuckDB differ in selected frontend identity",
        )
    if request.source_key not in _object(
        _read_json_object(request.snapshot_paths["sqlite"], "SQLite snapshot").get(
            "cases"
        ),
        "SQLite cases",
    ):
        _fail("snapshot.source", "selected source case is absent")

    report = grade_source_owned_ast_categories(
        normalized,
        cast("dict[str, object]", raw_ast),
        source_bytes,
        analyzer_capabilities,
        rows_by_backend,
        normalizer_path,
        profile.working_directory,
        request.source_key,
    )
    report["evidence"] = cast(
        "JSONValue",
        {
            "source_path": str(source_path),
            "source_sha256": source_hash,
            "capture_identity": summary.get("identity"),
            "capture_summary_path": str(summary_path.resolve()),
            "capture_summary_sha256": _sha256(summary_path),
            "raw_ast_path": str(raw_path.resolve()),
            "raw_ast_sha256": raw_hash,
            "normalizer_path": str(normalizer_path.resolve()),
            "normalizer_sha256": normalizer_hash,
            "normalized_path": str(normalized_path.resolve()),
            "normalized_sha256": normalized_hash,
            "profile_sha256": record.get("profile_sha256"),
            "profile_identity": profile.identity,
            "analysis_context_identity": context_ids["sqlite"],
            "analyzer_version": capability_declaration.analyzer_version,
            "analyzer_implementation_path": str(analyzer_module_path),
            "analyzer_implementation_files": analyzer_implementation_hashes,
            "backend_database_bindings": verified_database_bindings,
        },
    )
    final_identity_hashes = {
        source_path: source_hash,
        paths_and_hashes["profile"][0]: cast("str", paths_and_hashes["profile"][1]),
        paths_and_hashes["compile_database"][0]: cast(
            "str", paths_and_hashes["compile_database"][1]
        ),
        paths_and_hashes["compiler"][0]: cast("str", paths_and_hashes["compiler"][1]),
        paths_and_hashes["helper"][0]: cast("str", paths_and_hashes["helper"][1]),
        paths_and_hashes["build_receipt"][0]: cast(
            "str", paths_and_hashes["build_receipt"][1]
        ),
        record_path: normalization_record_hash,
        normalized_path: normalized_hash,
        normalizer_path: normalizer_hash,
        raw_path: raw_hash,
        summary_path: cast("str", record.get("capture_input_binding_sha256")),
        terminal_path: cast("str", record.get("capture_terminal_sha256")),
        prepared_path: cast("str", record.get("capture_prepared_inputs_sha256")),
        before_path: cast("str", attempt.get("guards_before_sha256")),
        after_path: cast("str", attempt.get("guards_after_sha256")),
        invocation_path: cast("str", attempt.get("invocation_sha256")),
        request.profile_document_path: cast("str", record.get("profile_sha256")),
    }
    for path, expected_hash in final_identity_hashes.items():
        if not path.is_file() or _sha256(path) != expected_hash:
            _fail("capture.final_recheck", "a bound input changed during grading")
    for dependency_value in cast(
        "list[JSONValue]", guard_profile.get("dependencies", [])
    ):
        dependency = _object(dependency_value, "guard dependency")
        dependency_path = Path(_string(dependency.get("path"), "guard dependency.path"))
        if _sha256(dependency_path) != dependency.get("expected_sha256"):
            _fail(
                "capture.final_recheck", "a profile dependency changed during grading"
            )
    for directory_value in directories:
        directory = _object(directory_value, "guard include directory")
        directory_path = Path(_string(directory.get("path"), "include_directory.path"))
        if directory_membership_sha256(directory_path) != directory.get(
            "expected_membership_sha256"
        ):
            _fail(
                "capture.final_recheck", "an include directory changed during grading"
            )
    for backend, binding in verified_database_bindings.items():
        database_path = Path(_string(binding.get("database_path"), "database_path"))
        if _database_generation_binding(database_path, backend) != binding:
            _fail("capture.final_recheck", "a backend database changed during grading")
    for path, expected_hash in receipt_file_hashes.items():
        if not path.is_file() or _sha256(path) != expected_hash:
            _fail("capture.final_recheck", "a backend receipt changed during grading")
    current_implementation_hashes = {
        str(path.resolve()): _sha256(path)
        for path in sorted(package_root.rglob("*.py"))
        if path.is_file()
    }
    if current_implementation_hashes != analyzer_implementation_hashes:
        _fail(
            "capture.final_recheck",
            "the analyzer implementation changed during grading",
        )
    return report


def _validate_source_key(
    source_path: Path, source_key: str, repository_root: Path
) -> None:
    """Require a snapshot case key to identify the exact guarded source path.

    Parameters
    ----------
    source_path : pathlib.Path
        Absolute original source file path.
    source_key : str
        Relative key used to select snapshot rows.
    repository_root : pathlib.Path
        Root established by the capture guard.

    Returns
    -------
    None

    Raises
    ------
    OracleFormatError
        If the key is not the source path relative to the guarded root.
    """
    try:
        expected = source_path.resolve().relative_to(repository_root.resolve())
    except ValueError:
        _fail("snapshot.source_key", "source is outside the guarded repository")
    if expected.as_posix() != source_key:
        _fail(
            "snapshot.source_key",
            "does not equal the original source path relative to the guarded root",
        )


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
    sidecars = (
        Path(f"{database}-wal"),
        Path(f"{database}-shm"),
        Path(f"{database}-journal"),
        Path(f"{database}.wal"),
    )
    if any(path.exists() for path in sidecars):
        _fail(f"{backend} database", "active database sidecars are unsupported")
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
    machine_supported_categories: frozenset[str] = MACHINE_VALIDATED_CATEGORIES,
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
    machine_supported_categories : frozenset[str]
        Categories with a complete evaluator for this source file.

    Returns
    -------
    set[str]
        Categories changed to held because no machine semantic evaluator exists.
    """
    held_categories: set[str] = set()
    for category, state in category_states.items():
        if state != "held" and category not in machine_supported_categories:
            category_states[category] = "held"
            held_categories.add(category)
    return held_categories


def _normal_c_comment_step(
    source: bytes, masked: bytearray, index: int
) -> tuple[int, str]:
    """Advance the scanner while it is outside C comments and literals.

    Parameters
    ----------
    source : bytes
        Original source bytes.
    masked : bytearray
        Mutable source copy whose comments are replaced with whitespace.
    index : int
        Current byte offset.

    Returns
    -------
    tuple[int, str]
        Next offset and scanner state.
    """
    current = source[index]
    following = source[index + 1] if index + 1 < len(source) else None
    if current == 47 and following == 42:
        masked[index : index + 2] = b"  "
        return index + 2, "block_comment"
    if current == 47 and following == 47:
        while index < len(source) and source[index] not in (10, 13):
            masked[index] = 32
            index += 1
        return index, "normal"
    if current == 34:
        return index + 1, "string"
    if current == 39:
        return index + 1, "character"
    return index + 1, "normal"


def _block_c_comment_step(
    source: bytes, masked: bytearray, index: int
) -> tuple[int, str]:
    """Advance the scanner through a C block comment.

    Parameters
    ----------
    source : bytes
        Original source bytes.
    masked : bytearray
        Mutable source copy whose comments are replaced with whitespace.
    index : int
        Current byte offset.

    Returns
    -------
    tuple[int, str]
        Next offset and scanner state.
    """
    current = source[index]
    following = source[index + 1] if index + 1 < len(source) else None
    if current not in (10, 13):
        masked[index] = 32
    if current == 42 and following == 47:
        masked[index + 1] = 32
        return index + 2, "normal"
    return index + 1, "block_comment"


def _quoted_c_literal_step(
    source: bytes, index: int, state: str
) -> tuple[int, str] | None:
    """Advance through a C string or character literal.

    Parameters
    ----------
    source : bytes
        Original source bytes.
    index : int
        Current byte offset.
    state : str
        Either ``string`` or ``character``.

    Returns
    -------
    tuple[int, str] or None
        Next offset and state, or ``None`` for a malformed literal.
    """
    current = source[index]
    following = source[index + 1] if index + 1 < len(source) else None
    quote = 34 if state == "string" else 39
    if current == 92:
        if following in (None, 10, 13):
            return None
        return index + 2, state
    if current in (10, 13):
        return None
    return (index + 1, "normal") if current == quote else (index + 1, state)


def _mask_c_comments(source: bytes) -> bytearray | None:
    """Replace C comments while preserving source line structure.

    Parameters
    ----------
    source : bytes
        Source bytes to scan.

    Returns
    -------
    bytearray or None
        Comment-masked bytes, or ``None`` for malformed strings or comments.
    """
    masked = bytearray(source)
    state = "normal"
    index = 0
    while index < len(source):
        if state == "normal":
            index, state = _normal_c_comment_step(source, masked, index)
        elif state == "block_comment":
            index, state = _block_c_comment_step(source, masked, index)
        else:
            literal_step = _quoted_c_literal_step(source, index, state)
            if literal_step is None:
                return None
            index, state = literal_step
    if state not in {"normal"}:
        return None
    return masked


def _source_literal_includes(source: bytes) -> list[dict[str, JSONValue]] | None:
    """Derive unconditional literal include rows from a bounded C source subset.

    The subset accepts only direct quoted or angle-bracket include directives
    and ordinary source lines. Conditional or macro directives, line splices,
    trigraphs, malformed comments, and non-literal include operands remain
    unsupported so callers can keep the category held.

    Parameters
    ----------
    source : bytes
        Exact source bytes whose include directives are being evaluated.

    Returns
    -------
    list[dict[str, JSONValue]] or None
        Source-derived include identities, or ``None`` for unsupported syntax.
    """
    if source.startswith(b"\xef\xbb\xbf"):
        return None
    if b"\\\n" in source or b"\\\r\n" in source:
        return None
    trigraph_final_bytes = b"=/\\'()!<>-"
    if any(
        source[index : index + 2] == b"??" and source[index + 2] in trigraph_final_bytes
        for index in range(max(0, len(source) - 2))
    ):
        return None
    raw_prefixes = (b'u8R"', b'uR"', b'UR"', b'LR"', b'R"')
    if _contains_raw_string_prefix(source, raw_prefixes):
        return None
    if any(
        current == 13 and (index + 1 >= len(source) or source[index + 1] != 10)
        for index, current in enumerate(source)
    ):
        return None
    masked = _mask_c_comments(source)
    if masked is None:
        return None

    includes: list[dict[str, JSONValue]] = []
    for line_number, line in enumerate(masked.split(b"\n"), start=1):
        if line.endswith(b"\r"):
            line = line[:-1]
        stripped = line.lstrip(b" \t\v\f")
        if stripped.startswith(b"%:"):
            return None
        if not stripped.startswith(b"#"):
            continue
        parsed = _parse_literal_include(bytes(line))
        if parsed is None:
            return None
        kind, name_bytes = parsed
        includes.append(
            {
                "kind": kind,
                "name": name_bytes.decode("ascii"),
                "line": line_number,
            }
        )
    return includes


def _contains_raw_string_prefix(source: bytes, prefixes: tuple[bytes, ...]) -> bool:
    """Detect C++ raw-string prefixes conservatively in source bytes.

    Parameters
    ----------
    source : bytes
        Source bytes to inspect.
    prefixes : tuple[bytes, ...]
        Raw-string prefixes recognized by C++.

    Returns
    -------
    bool
        Whether an unambiguous token boundary precedes a raw-string prefix.
    """
    identifier_bytes = (
        b"abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_"
    )
    for prefix in prefixes:
        start = 0
        while (offset := source.find(prefix, start)) >= 0:
            if offset == 0 or source[offset - 1] not in identifier_bytes:
                return True
            start = offset + len(prefix)
    return False


def _parse_literal_include(line: bytes) -> tuple[str, bytes] | None:
    """Parse one direct literal include directive.

    Parameters
    ----------
    line : bytes
        Comment-masked preprocessing line.

    Returns
    -------
    tuple[str, bytes] or None
        Include kind and exact operand spelling, or ``None`` if unsupported.
    """
    stripped = line.strip(b" \t\v\f")
    if not stripped.startswith(b"#"):
        return None
    directive = stripped[1:].lstrip(b" \t\v\f")
    if not directive.startswith(b"include"):
        return None
    remainder = directive[len(b"include") :]
    if not remainder or remainder[0] not in b" \t\v\f":
        return None
    operand = remainder.lstrip(b" \t\v\f")
    if not operand:
        return None
    opening, closing = (b"<", b">") if operand.startswith(b"<") else (b'"', b'"')
    if not operand.startswith(opening):
        return None
    end = operand.find(closing, 1)
    if end <= 1 or operand[end + 1 :].strip(b" \t\v\f"):
        return None
    name = operand[1:end]
    allowed_name_bytes = (
        b"abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_./+-"
    )
    if any(character not in allowed_name_bytes for character in name):
        return None
    kind = "include_system" if opening == b"<" else "include_local"
    return kind, name


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
    source_path = Path(cast("str", source["path"]))
    source_includes = _source_literal_includes(source_path.read_bytes())
    machine_categories = frozenset(
        {"coverage"} | ({"includes"} if source_includes is not None else set())
    )
    semantic_holds = _hold_categories_without_machine_semantics(
        states, machine_categories
    )
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
    source_semantic_failures: dict[str, list[dict[str, JSONValue]]] = {}
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
        if source_includes is not None:
            expected_include_rows = Counter(_canonical(row) for row in source_includes)
            observed_include_rows = Counter(
                _canonical(
                    {
                        "kind": row.get("kind"),
                        "name": row.get("name"),
                        "line": row.get("line"),
                    }
                )
                for row in _as_rows(source_rows.get("includes"), f"{backend}.includes")
            )
            source_semantic_failures[backend] = []
            if observed_include_rows != expected_include_rows:
                source_semantic_failures[backend].append(
                    {
                        "case": source_key,
                        "category": "includes",
                        "reason": "persisted include rows differ from the exhaustive source-derived literal directive inventory",
                        "expected": cast("JSONValue", source_includes),
                    }
                )
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
            and failure.category not in machine_categories
        ]
        control_failures[backend].extend(
            failure
            for failure in _negative_control_snapshot_failures(contract, snapshot)
            if failure.get("category") not in machine_categories
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
            len(source_includes)
            if category == "includes" and source_includes is not None
            else len(authored_case.facts.get(category, ()))
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
        if category == "includes" and source_includes is not None:
            category_failures = [
                failure
                for failure in category_failures
                if failure.get("reason")
                == "persisted include rows differ from the exhaustive source-derived literal directive inventory"
            ]
            category_failures.extend(
                failure
                for failures in source_semantic_failures.values()
                for failure in failures
            )
            if source_includes and state == "not_applicable":
                category_failures.append(
                    {
                        "case": source_key,
                        "category": "includes",
                        "reason": "nonempty source-derived include inventory cannot be not_applicable",
                        "expected": cast("JSONValue", source_includes),
                    }
                )
        if state == "held":
            held += 1
        exact_count_required = (
            state in {"graded", "not_applicable"} and category in SOURCE_FACT_CATEGORIES
        )
        machine_include_failure = (
            category == "includes"
            and source_includes is not None
            and bool(category_failures)
        )
        if (
            machine_include_failure
            or (state == "graded" and category_failures)
            or (
                exact_count_required
                and (not category_parity or not all(exact_counts.values()))
            )
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
                    if category == "coverage"
                    else "source-derived exhaustive literal directive inventory"
                    if category == "includes" and source_includes is not None
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
