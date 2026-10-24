"""Aggregate one fixed cohort with the same independent grader for every row.

Parameters
----------
None

Returns
-------
None

Notes
-----
The report keeps whole-file frontend completion, native acceptance, source
coordinate checks, context readiness, and fixture semantic verification as
separate measures. An ordinary corpus record without an independent oracle
never contributes to fully verified semantic facts.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

from .identity import CaseIdentity
from .qualification import ExpectedFact, RecordGrade, grade_record


def grade_cohort(  # noqa: PLR0913 -- expose each independent cohort input explicitly
    manifest_path: Path,
    attempt_root: Path,
    repository_roots: Mapping[str, Path],
    expected_facts: Mapping[str, Sequence[ExpectedFact]] | None = None,
    default_baseline_root: Path | None = None,
    configured_baseline_root: Path | None = None,
    selected_ids: Sequence[str] | None = None,
) -> dict[str, object]:
    """Grade raw records against one manifest without dropping held rows.

    Parameters
    ----------
    manifest_path : pathlib.Path
        Versioned immutable cohort manifest.
    attempt_root : pathlib.Path
        One batch attempt directory containing raw envelopes.
    repository_roots : Mapping[str, pathlib.Path]
        Checkout path for each repository ID.
    expected_facts : Mapping[str, Sequence[ExpectedFact]] or None, optional
        Hand-written independent facts for fixture rows only.
    default_baseline_root : pathlib.Path or None, optional
        Attempt directory containing default C23/CPP42 result DTOs.
    configured_baseline_root : pathlib.Path or None, optional
        Attempt directory containing historical configured result DTOs. Rows
        count as comparable only when source, producer, configuration, and
        input-profile identities are present and match exactly.
    selected_ids : Sequence[str] or None, optional
        Manifest row IDs included in a bounded smoke attempt. Unselected rows
        remain in the full cohort denominator and are not graded as missing.

    Returns
    -------
    dict[str, object]
        Cohort report with all selected manifest rows represented, raw hashes,
        whole-file coverage, status/readiness counts, and separate verification
        counts.

    Raises
    ------
    OSError
        If the manifest, raw records, source files, or dependencies cannot be read.
    ValueError
        If manifest rows or raw records violate the pinned JSON contracts.
    """

    manifest_bytes = manifest_path.read_bytes()
    manifest = _read_object(manifest_path)
    rows = _object_rows(manifest.get("rows"), "manifest rows")
    rows_by_id = {_required_string(row, "selection_id"): row for row in rows}
    if len(rows_by_id) != len(rows):
        message = "manifest contains duplicate selection_id values"
        raise ValueError(message)
    selected = list(selected_ids) if selected_ids is not None else list(rows_by_id)
    unknown_selected = sorted(set(selected) - rows_by_id.keys())
    if unknown_selected:
        message = (
            f"selected IDs are absent from the cohort manifest: {unknown_selected}"
        )
        raise ValueError(message)
    selected_rows_by_id = {
        selection_id: rows_by_id[selection_id] for selection_id in selected
    }
    roots = {key: value.resolve() for key, value in repository_roots.items()}
    raw_paths = _index_record_paths(attempt_root)

    runner_identity = _read_optional_object(attempt_root / "run-identity.json")
    manifest_sha256 = hashlib.sha256(manifest_bytes).hexdigest()
    issue_counts: Counter[str] = Counter()
    context_counts: Counter[str] = Counter()
    status_counts: Counter[str] = Counter()
    acceptance_counts: Counter[str] = Counter()
    major_failures: Counter[str] = Counter()
    fact_owner_counts: Counter[str] = Counter()
    spelling_owner_counts: Counter[str] = Counter()
    expansion_owner_counts: Counter[str] = Counter()
    record_grades: dict[str, RecordGrade] = {}
    rows_complete = 0
    extracted_count = 0
    coordinates_checked = 0
    fully_verified_facts = 0
    fixture_rows = 0
    report_rows: list[dict[str, object]] = []

    for selection_id, cohort_row in selected_rows_by_id.items():
        profile_status = _string_or(cohort_row.get("profile_context_status"), "missing")
        context_counts[profile_status] += 1
        raw_path = raw_paths.get(selection_id)
        if raw_path is None:
            progress_row = _find_progress_row(attempt_root, selection_id)
            status = _string_or(progress_row.get("status"), "unobserved")
            hold_reasons = _string_list(progress_row.get("hold_reasons"))
            not_invoked = (
                status == "held"
                and "repository checkout or compilation database not supplied"
                in hold_reasons
                and progress_row.get("raw_artifact") is None
            )
            native_acceptance = "not_invoked" if not_invoked else "not_established"
            raw_output_state = (
                "not_invoked_no_native_output_expected"
                if not_invoked
                else "missing_after_invocation"
                if status != "unobserved"
                else "not_observed"
            )
            status_counts[status] += 1
            major_failures[f"record:{status}"] += 1
            acceptance_counts[native_acceptance] += 1
            for reason in hold_reasons:
                major_failures[f"hold:{reason}"] += 1
            missing_issues = (
                []
                if not_invoked
                else [
                    {
                        "category": "missing",
                        "fact": (
                            "no raw terminal envelope after adapter invocation"
                            if status != "unobserved"
                            else "no raw terminal envelope or terminal progress row"
                        ),
                    }
                ]
            )
            issue_counts.update(issue["category"] for issue in missing_issues)
            report_rows.append(
                {
                    "selection_id": selection_id,
                    "population_class": cohort_row.get("population_class"),
                    "language": cohort_row.get("language"),
                    "repository_id": cohort_row.get("repository_id"),
                    "repository_relative_path": cohort_row.get(
                        "repository_relative_path"
                    ),
                    "profile_context_status": profile_status,
                    "record_status": status,
                    "native_acceptance": native_acceptance,
                    "raw_output_state": raw_output_state,
                    "semantic_completeness": "not_independently_graded",
                    "fully_verified_fact_count": 0,
                    "issues": missing_issues,
                    "raw_artifact": progress_row.get("raw_artifact"),
                }
            )
            continue

        record = _read_raw_envelope(raw_path)
        if _required_string(record, "selection_id") != selection_id:
            message = f"raw envelope identity does not match path for {selection_id}"
            raise ValueError(message)
        status = _string_or(record.get("status"), "missing")
        status_counts[status] += 1
        identity_issues = _record_identity_issues(
            record,
            cohort_row,
            manifest_sha256,
            str(manifest_path.resolve()),
            manifest.get("schema_version"),
            roots.get(_string_or(cohort_row.get("repository_id"), "")),
        )
        repository_id = _string_or(cohort_row.get("repository_id"), "")
        source_path = roots.get(repository_id)
        source_relative = _string_or(cohort_row.get("repository_relative_path"), "")
        if source_path is not None:
            source_path = source_path / source_relative
        dependencies = _dependency_paths(record)
        if source_path is not None and source_path.is_file():
            record_grade = grade_record(
                record,
                source_path,
                expected=(expected_facts or {}).get(selection_id),
                dependency_paths=dependencies,
                repository_root=roots.get(repository_id),
            )
            record_grades[selection_id] = record_grade
            extracted_count += record_grade.extracted_fact_count
            coordinates_checked += record_grade.coordinate_checked_count
            fact_owner_counts.update(record_grade.fact_owner_counts)
            spelling_owner_counts.update(record_grade.spelling_owner_counts)
            expansion_owner_counts.update(record_grade.expansion_owner_counts)
            acceptance_counts[record_grade.native_acceptance] += 1
            fully_verified_facts += record_grade.fully_verified_fact_count
            if selection_id in (expected_facts or {}):
                fixture_rows += 1
            major_failures.update(record_grade.major_failure_counts)
            record_issues = [
                {"category": issue.category, "fact": issue.fact}
                for issue in record_grade.issues
            ]
        else:
            record_grade = None
            record_issues = [
                {
                    "category": "source",
                    "fact": "source checkout or source file unavailable",
                }
            ]
            acceptance_counts["not_established"] += 1
            major_failures["source:unavailable"] += 1

        record_issues.extend(
            {"category": "identity", "fact": issue} for issue in identity_issues
        )
        issue_counts.update(issue["category"] for issue in record_issues)
        for reason in _string_list(record.get("hold_reasons")):
            major_failures[f"hold:{reason}"] += 1
        valid_complete = (
            status == "complete" and not identity_issues and record_grade is not None
        )
        rows_complete += int(valid_complete)
        case_identity = _identity_digest(record, runner_identity)
        report_rows.append(
            {
                "selection_id": selection_id,
                "population_class": cohort_row.get("population_class"),
                "language": cohort_row.get("language"),
                "repository_id": repository_id,
                "repository_relative_path": source_relative,
                "profile_context_status": profile_status,
                "record_status": status,
                "raw_output_state": "captured",
                "native_acceptance": (
                    record_grade.native_acceptance
                    if record_grade
                    else "not_established"
                ),
                "semantic_completeness": (
                    record_grade.semantic_completeness
                    if record_grade
                    else "not_independently_graded"
                ),
                "extracted_fact_count": record_grade.extracted_fact_count
                if record_grade
                else 0,
                "fact_owner_counts": (
                    dict(record_grade.fact_owner_counts) if record_grade else {}
                ),
                "spelling_owner_counts": (
                    dict(record_grade.spelling_owner_counts) if record_grade else {}
                ),
                "expansion_owner_counts": (
                    dict(record_grade.expansion_owner_counts) if record_grade else {}
                ),
                "coordinate_checked_count": (
                    record_grade.coordinate_checked_count if record_grade else 0
                ),
                "fully_verified_fact_count": (
                    record_grade.fully_verified_fact_count if record_grade else 0
                ),
                "case_identity_sha256": case_identity,
                "identity_complete": case_identity is not None,
                "raw_artifact": str(raw_path),
                "raw_sha256": _sha256_file(raw_path),
                "issues": record_issues,
            }
        )

    unselected_raw = sorted(set(raw_paths) - set(rows_by_id))
    for _selection_id in unselected_raw:
        issue_counts["unknown_record"] += 1
        major_failures["record:unknown_selection_id"] += 1

    default_comparison = _compare_default_baseline(
        selected_rows_by_id,
        raw_paths,
        default_baseline_root,
        roots,
        record_grades,
    )
    configured_comparison = _compare_configured_baseline(
        selected_rows_by_id,
        raw_paths,
        configured_baseline_root,
    )
    return {
        "schema_version": "codira.clang-frontend-pilot-qualification/1",
        "pilot_id": manifest.get("pilot_id"),
        "manifest": {
            "path": str(manifest_path.resolve()),
            "sha256": manifest_sha256,
            "schema_version": manifest.get("schema_version"),
            "cohort_denominator": len(rows),
        },
        "attempt_root": str(attempt_root.resolve()),
        "summary": {
            "whole_file_supported_artifact_coverage": {
                "complete_files": rows_complete,
                "selected_files": len(selected_rows_by_id),
                "cohort_files": len(rows),
                "fraction_within_selected": (
                    rows_complete / len(selected_rows_by_id)
                    if selected_rows_by_id
                    else 0.0
                ),
                "fraction_of_cohort": rows_complete / len(rows) if rows else 0.0,
            },
            "selected_count": len(selected_rows_by_id),
            "unselected_count": len(rows) - len(selected_rows_by_id),
            "selected_ids": selected,
            "record_status_counts": dict(sorted(status_counts.items())),
            "native_acceptance_counts": dict(sorted(acceptance_counts.items())),
            "input_context_readiness_counts": dict(sorted(context_counts.items())),
            "source_coordinate_coverage": {
                "coordinate_checked_facts": coordinates_checked,
                "extracted_facts": extracted_count,
                "fraction": coordinates_checked / extracted_count
                if extracted_count
                else 0.0,
            },
            "fact_location_ownership": {
                "physical_fact_owner_counts": dict(sorted(fact_owner_counts.items())),
                "spelling_coordinate_owner_counts": dict(
                    sorted(spelling_owner_counts.items())
                ),
                "expansion_coordinate_owner_counts": dict(
                    sorted(expansion_owner_counts.items())
                ),
            },
            "fully_verified_semantic_facts": fully_verified_facts,
            "independently_graded_fixture_rows": fixture_rows,
            "semantic_completeness_claims": "fixture facts only; other cohort rows are not independently graded",
            "major_failure_counts": dict(sorted(major_failures.items())),
            "issue_counts": dict(sorted(issue_counts.items())),
            "unknown_raw_selection_ids": unselected_raw,
            "baseline_comparison": {
                "default_c23_cpp42": default_comparison,
                "historical_configured": configured_comparison,
            },
        },
        "rows": report_rows,
    }


def _record_identity_issues(  # noqa: PLR0913 -- each pinned producer identity dimension stays explicit
    record: Mapping[str, object],
    row: Mapping[str, object],
    manifest_sha256: str,
    manifest_path: str,
    manifest_schema_version: object,
    repository_root: Path | None,
) -> list[str]:
    """Compare one raw envelope's source and profile bindings to the manifest.

    Parameters
    ----------
    record : Mapping[str, object]
        Raw Clang envelope.
    row : Mapping[str, object]
        Expected immutable cohort row.
    manifest_sha256 : str
        Current cohort manifest digest.
    manifest_path : str
        Absolute path of the current cohort manifest.
    manifest_schema_version : object
        Manifest schema version.
    repository_root : pathlib.Path or None
        Current checkout for the row's repository.

    Returns
    -------
    list[str]
        Stable descriptions of mismatched or unavailable identities.
    """

    issues: list[str] = []
    for key in (
        "selection_id",
        "population_class",
        "language",
        "repository_id",
        "repository_revision",
        "repository_relative_path",
        "source_sha256",
        "classification_disposition",
        "feature_family",
        "family_evidence",
        "profile_context_status",
        "profile_evidence",
        "context_limitations",
    ):
        if record.get(key) != row.get(key):
            issues.append(f"manifest field mismatch:{key}")
    manifest_source = _object(record.get("manifest_source"))
    if manifest_source.get("sha256") != manifest_sha256:
        issues.append("manifest source digest mismatch")
    if manifest_source.get("path") != manifest_path:
        issues.append("manifest source path mismatch")
    if manifest_source.get("schema_version") != manifest_schema_version:
        issues.append("manifest source schema version mismatch")
    if record.get("selection_row") != dict(row):
        issues.append("full manifest selection row mismatch")
    if record.get("context_status") != row.get("profile_context_status"):
        issues.append("context readiness mismatch")
    if repository_root is not None:
        relative_path = _string_or(row.get("repository_relative_path"), "")
        source_path = (repository_root / relative_path).resolve()
        if not source_path.is_relative_to(repository_root.resolve()):
            issues.append("manifest source path escapes repository checkout")
        elif not source_path.is_file() or _sha256_file(source_path) != row.get(
            "source_sha256"
        ):
            issues.append("current source bytes do not match manifest source digest")
        if record.get("source_path") is not None:
            record_path = Path(_string_or(record.get("source_path"), "")).resolve()
            if record_path != source_path:
                issues.append("envelope source path mismatch")
    else:
        issues.append("repository checkout mapping missing")
    return issues


def _identity_digest(
    record: Mapping[str, object],
    run_identity: Mapping[str, object],
) -> str | None:
    """Build a complete reusable identity from the envelope and batch producer.

    Parameters
    ----------
    record : Mapping[str, object]
        Raw Clang envelope.
    run_identity : Mapping[str, object]
        Batch-level producer, helper, configuration, and CDB identities.

    Returns
    -------
    str or None
        Case identity digest, or None when any required identity is absent.
    """

    original = _object(record.get("original_compile_command"))
    adaptation = _object(record.get("clang_adaptation"))
    dependency = _object(record.get("dependency_closure"))
    driver = _object(original.get("driver"))
    toolchain = _object(adaptation.get("toolchain"))
    helper_sha = _string_or(toolchain.get("helper_sha256"), "")
    clang_compiler_sha = _string_or(toolchain.get("compiler_sha256"), "")
    compiler_hashes = [
        _string_or(driver.get("binary_sha256"), ""),
        clang_compiler_sha,
    ]
    dependency_sha = _string_or(dependency.get("sha256"), "")
    producer_hashes = [
        _string_or(run_identity.get("adapter_runner_sha256"), ""),
        _string_or(run_identity.get("adapter_module_sha256"), ""),
        helper_sha or _string_or(run_identity.get("helper_sha256"), ""),
    ]
    profile_fields = {
        "original_compile_command": original,
        "clang_argv": adaptation.get("argv"),
        "transformations": adaptation.get("transformations"),
        "unsupported_context": adaptation.get("unsupported_context"),
    }
    config_sha = _string_or(run_identity.get("configuration_sha256"), "")
    if not (
        record.get("source_sha256")
        and dependency_sha
        and all(compiler_hashes)
        and all(producer_hashes)
        and config_sha
    ):
        return None
    return CaseIdentity(
        source_sha256=_string_or(record.get("source_sha256"), ""),
        profile_sha256=_sha256_json(profile_fields),
        dependency_sha256=dependency_sha,
        compiler_sha256=_sha256_json(compiler_hashes),
        producer_sha256=_sha256_json(producer_hashes),
        configuration_sha256=config_sha,
    ).digest()


def _compare_default_baseline(  # noqa: PLR0913 -- owner-attribution data accompanies baseline identities
    cohort_rows: Mapping[str, Mapping[str, object]],
    raw_paths: Mapping[str, Path],
    baseline_root: Path | None,
    repository_roots: Mapping[str, Path],
    record_grades: Mapping[str, RecordGrade],
) -> dict[str, object]:
    """Compare default TS DTO counts beside Clang counts without claiming parity.

    Parameters
    ----------
    cohort_rows : Mapping[str, Mapping[str, object]]
        Frozen cohort manifest rows by selection ID.
    raw_paths : Mapping[str, pathlib.Path]
        Retained raw envelope path by selection ID; only one case is decoded at a time.
    baseline_root : pathlib.Path or None
        Default analyzer attempt root containing ``cases/<selection_id>.json``.

    Returns
    -------
    dict[str, object]
        Per-case count comparisons with manifest-bound source identity and
        explicit input-context mismatch labels.
    """

    if baseline_root is None:
        return {
            "status": "not_supplied",
            "comparison": "descriptive_only_different_input_contexts",
            "reason": "no default C23/CPP42 DTO attempt root was supplied",
            "paired_rows": 0,
            "rows": [],
        }
    baseline_records: dict[str, Mapping[str, object]] = {}
    for path in sorted((baseline_root / "cases").glob("*.json")):
        record = _read_json_object(path)
        selection_id = _string_or(record.get("selection_id"), "")
        if not selection_id or selection_id in baseline_records:
            message = f"default baseline has missing or duplicate ID in {path}"
            raise ValueError(message)
        baseline_records[selection_id] = record

    pairs: list[dict[str, object]] = []
    baseline_mismatch = 0
    missing_baseline = 0
    missing_clang = 0
    for selection_id, manifest_row in cohort_rows.items():
        baseline = baseline_records.get(selection_id)
        raw_path = raw_paths.get(selection_id)
        clang = _read_raw_envelope(raw_path) if raw_path is not None else None
        if baseline is None:
            missing_baseline += 1
            continue
        source_matches = baseline.get("source_sha256_observed") == manifest_row.get(
            "source_sha256"
        )
        if not source_matches:
            baseline_mismatch += 1
            continue
        if clang is None:
            missing_clang += 1
        analysis = _object(baseline.get("analysis_result"))
        frontend = _object(clang.get("frontend")) if clang is not None else {}
        baseline_facts = _object(baseline.get("fact_counts"))
        clang_facts = {
            "declarations": len(_sequence(frontend.get("declarations"))),
            "calls": len(_sequence(frontend.get("calls"))),
            "preprocessing_events": _preprocessing_event_count(
                frontend.get("preprocessing")
            ),
            "includes": len(_sequence(frontend.get("includes"))),
        }
        baseline_status = _object(analysis.get("status"))
        repository_id = _string_or(manifest_row.get("repository_id"), "")
        repository_root = repository_roots.get(repository_id)
        source_relative = _string_or(manifest_row.get("repository_relative_path"), "")
        source_path = (
            repository_root / source_relative if repository_root is not None else None
        )
        baseline_owners = _baseline_owner_counts(analysis, source_path, repository_root)
        clang_grade = record_grades.get(selection_id)
        pairs.append(
            {
                "selection_id": selection_id,
                "source_sha256": manifest_row.get("source_sha256"),
                "input_context_relation": "different",
                "input_context_reason": (
                    "default analyzer uses empty configuration and repository-contained literal includes; "
                    "Clang uses the manifest command profile or is held for missing context"
                ),
                "baseline": {
                    "tier": baseline.get("baseline_tier"),
                    "analyzer": baseline.get("analyzer_name"),
                    "version": baseline.get("analyzer_version"),
                    "configuration_sha256": baseline.get("configuration_sha256"),
                    "module_identity": _object(baseline.get("runtime_identity")),
                    "run_status": baseline.get("run_status"),
                    "analysis_coverage_state": baseline_status.get("coverage_state"),
                    "index_symbols": analysis.get("index_symbols"),
                    "fact_counts": baseline_facts,
                    "fact_owner_counts": baseline_owners,
                },
                "clang": {
                    "status": clang.get("status")
                    if clang is not None
                    else "missing_record",
                    "context_status": clang.get("context_status")
                    if clang is not None
                    else None,
                    "fact_counts": clang_facts if clang is not None else None,
                    "raw_sha256": _sha256_file(raw_paths[selection_id])
                    if clang is not None
                    else None,
                    "physical_fact_owner_counts": (
                        dict(clang_grade.fact_owner_counts) if clang_grade else {}
                    ),
                    "spelling_coordinate_owner_counts": (
                        dict(clang_grade.spelling_owner_counts) if clang_grade else {}
                    ),
                    "expansion_coordinate_owner_counts": (
                        dict(clang_grade.expansion_owner_counts) if clang_grade else {}
                    ),
                },
                "file_ownership_comparison": {
                    "baseline_dto_artifacts": baseline_owners,
                    "clang_physical_facts": (
                        dict(clang_grade.fact_owner_counts) if clang_grade else {}
                    ),
                    "comparison_basis": (
                        "main file, repository headers, other repository files, and unlocated DTOs "
                        "remain separate; no semantic equivalence is claimed"
                    ),
                },
                "interpretation": "side_by_side_measurement_only; fact sets are not semantically equated",
            }
        )
    return {
        "status": "available",
        "comparison": "descriptive_only_different_input_contexts",
        "baseline_attempt_root": str(baseline_root.resolve()),
        "paired_rows": len(pairs) - missing_clang,
        "source_matched_baseline_rows": len(pairs),
        "baseline_source_mismatches": baseline_mismatch,
        "missing_baseline_rows": missing_baseline,
        "missing_clang_rows": missing_clang,
        "semantic_agreement_claim": "none",
        "rows": pairs,
    }


def _baseline_owner_counts(
    analysis: Mapping[str, object],
    source_path: Path | None,
    repository_root: Path | None,
) -> dict[str, int]:
    """Count baseline result DTOs by main-file or stable-ID file owner.

    Parameters
    ----------
    analysis : Mapping[str, object]
        Serialized default analyzer result.
    source_path : pathlib.Path or None
        Main translation unit source.
    repository_root : pathlib.Path or None
        Pinned repository checkout.

    Returns
    -------
    dict[str, int]
        Counts for main-file, repository-header, other repository, and
        unlocated artifacts. Calls inherit the owning function's stable ID.
    """

    counts: Counter[str] = Counter()
    module = _object(analysis.get("module"))
    module_path = _string_or(module.get("source_path"), "")
    counts[_path_owner(module_path, source_path, repository_root)] += 1
    functions = _object_sequence(analysis.get("functions"))
    classes = _object_sequence(analysis.get("classes"))
    for row in (
        *functions,
        *_object_sequence(analysis.get("declarations")),
        *_object_sequence(analysis.get("imports")),
        *_object_sequence(analysis.get("documentation")),
    ):
        owner = _stable_id_owner(row, source_path, repository_root)
        counts[owner] += 1
    for class_row in classes:
        counts[_stable_id_owner(class_row, source_path, repository_root)] += 1
        for method in _object_sequence(class_row.get("methods")):
            counts[_stable_id_owner(method, source_path, repository_root)] += 1
            for _call in _object_sequence(method.get("calls")):
                counts[_stable_id_owner(method, source_path, repository_root)] += 1
    for function in functions:
        owner = _stable_id_owner(function, source_path, repository_root)
        for _call in _object_sequence(function.get("calls")):
            counts[owner] += 1
    return dict(sorted(counts.items()))


def _stable_id_owner(
    row: Mapping[str, object],
    source_path: Path | None,
    repository_root: Path | None,
) -> str:
    """Resolve a Codira artifact's stable-ID path without line heuristics.

    Parameters
    ----------
    row : Mapping[str, object]
        Serialized analyzer artifact.
    source_path : pathlib.Path or None
        Main translation unit.
    repository_root : pathlib.Path or None
        Pinned repository checkout.

    Returns
    -------
    str
        Owner category or ``unlocated`` if the ID has no resolvable file.
    """

    stable_id = _string_or(row.get("stable_id"), "")
    segments = stable_id.split(":", 2)
    if len(segments) != 3 or repository_root is None:
        return "unlocated"
    relative_path = segments[2].rsplit(":", 1)[0]
    candidate = (repository_root / relative_path).resolve()
    if source_path is not None and candidate == source_path.resolve():
        return "main_file"
    if candidate.is_file() and candidate.is_relative_to(repository_root.resolve()):
        return _file_owner_suffix(candidate)
    return "unlocated"


def _path_owner(
    path_value: str,
    source_path: Path | None,
    repository_root: Path | None,
) -> str:
    """Classify a DTO path while preserving unresolved ownership.

    Parameters
    ----------
    path_value : str
        Absolute or repository-relative path.
    source_path : pathlib.Path or None
        Main translation unit.
    repository_root : pathlib.Path or None
        Pinned checkout.

    Returns
    -------
    str
        Owner category or ``unlocated``.
    """

    if not path_value:
        return "unlocated"
    candidate = Path(path_value)
    if not candidate.is_absolute() and repository_root is not None:
        candidate = repository_root / candidate
    candidate = candidate.resolve()
    if source_path is not None and candidate == source_path.resolve():
        return "main_file"
    if (
        repository_root is not None
        and candidate.is_file()
        and candidate.is_relative_to(repository_root.resolve())
    ):
        return _file_owner_suffix(candidate)
    return "unlocated"


def _file_owner_suffix(path: Path) -> str:
    """Return header or other-source ownership from a resolved repository file.

    Parameters
    ----------
    path : pathlib.Path
        Existing repository-owned file.

    Returns
    -------
    str
        ``repository_header`` for known header/include suffixes, otherwise
        ``other_repository_file``.
    """

    if path.suffix.lower() in {".h", ".hh", ".hpp", ".hxx", ".inc", ".def"}:
        return "repository_header"
    return "other_repository_file"


def _object_sequence(value: object) -> list[Mapping[str, object]]:
    """Filter serialized DTO arrays to mapping rows.

    Parameters
    ----------
    value : object
        Potential JSON array.

    Returns
    -------
    list[Mapping[str, object]]
        Mapping items in the input sequence.
    """

    return [_object(item) for item in value] if isinstance(value, list) else []


def _compare_configured_baseline(
    cohort_rows: Mapping[str, Mapping[str, object]],
    raw_paths: Mapping[str, Path],
    baseline_root: Path | None,
) -> dict[str, object]:
    """Admit historical configured DTOs only when exact identities are present.

    Parameters
    ----------
    cohort_rows : Mapping[str, Mapping[str, object]]
        Frozen cohort rows by selection ID.
    raw_paths : Mapping[str, pathlib.Path]
        Retained raw envelope path by selection ID; only one case is decoded at a time.
    baseline_root : pathlib.Path or None
        Optional historical configured baseline attempt root.

    Returns
    -------
    dict[str, object]
        Exact-match eligibility and counts; unavailable cases remain explicit.
    """

    if baseline_root is None:
        return {
            "status": "not_supplied",
            "eligible_rows": 0,
            "unavailable_rows": len(cohort_rows),
            "reason": "historical DTO source, producer, configuration, and compile-profile identities were not supplied",
        }
    eligible = 0
    unavailable: Counter[str] = Counter()
    for selection_id, manifest_row in cohort_rows.items():
        path = baseline_root / "cases" / f"{selection_id}.json"
        record = _read_json_object(path) if path.is_file() else {}
        raw_path = raw_paths.get(selection_id)
        clang = _read_raw_envelope(raw_path) if raw_path is not None else None
        if not record:
            unavailable["missing_historical_row"] += 1
        elif record.get("source_sha256_observed") != manifest_row.get("source_sha256"):
            unavailable["source_sha_mismatch"] += 1
        elif record.get("baseline_tier") != "configured_historical":
            unavailable["not_configured_historical_tier"] += 1
        elif clang is None:
            unavailable["missing_clang_row"] += 1
        elif not _configured_profile_exact_match(record, clang):
            unavailable["producer_config_or_profile_identity_mismatch"] += 1
        else:
            eligible += 1
    return {
        "status": "available" if eligible else "no_exact_matches",
        "baseline_attempt_root": str(baseline_root.resolve()),
        "eligible_rows": eligible,
        "unavailable_rows": len(cohort_rows) - eligible,
        "unavailable_reasons": dict(sorted(unavailable.items())),
        "semantic_agreement_claim": "none; matching source/profile does not itself grade DTO semantics",
    }


def _configured_profile_exact_match(
    historical: Mapping[str, object], clang: Mapping[str, object]
) -> bool:
    """Check all identity fields required to reuse a configured historical DTO.

    Parameters
    ----------
    historical : Mapping[str, object]
        Historical baseline row.
    clang : Mapping[str, object]
        Current Clang row.

    Returns
    -------
    bool
        True only when source, profile, analyzer producer, and configuration
        identity values are all explicitly equal.
    """

    required_pairs = (
        (historical.get("source_sha256_observed"), clang.get("source_sha256")),
        (historical.get("input_profile_sha256"), _clang_profile_sha256(clang)),
        (historical.get("configuration_sha256"), _clang_configuration_sha256(clang)),
    )
    producer = _object(historical.get("producer_identity"))
    clang_producer = _object(clang.get("producer_identity"))
    producer_matches = bool(producer) and producer == clang_producer
    return producer_matches and all(
        left is not None and left == right for left, right in required_pairs
    )


def _clang_profile_sha256(clang: Mapping[str, object]) -> str:
    """Hash the exact source compile command and Clang transformation fields.

    Parameters
    ----------
    clang : Mapping[str, object]
        Clang envelope.

    Returns
    -------
    str
        Canonical profile digest.
    """

    adaptation = _object(clang.get("clang_adaptation"))
    return _sha256_json(
        {
            "original_compile_command": clang.get("original_compile_command"),
            "clang_argv": adaptation.get("argv"),
            "transformations": adaptation.get("transformations"),
            "unsupported_context": adaptation.get("unsupported_context"),
        }
    )


def _clang_configuration_sha256(clang: Mapping[str, object]) -> object:
    """Read the adapter's effective configuration digest if recorded.

    Parameters
    ----------
    clang : Mapping[str, object]
        Clang envelope.

    Returns
    -------
    object
        Configuration digest or None when unavailable.
    """

    return clang.get("configuration_sha256")


def _read_json_object(path: Path) -> Mapping[str, object]:
    """Read and validate an object from one JSON artifact.

    Parameters
    ----------
    path : pathlib.Path
        Input JSON path.

    Returns
    -------
    Mapping[str, object]
        Decoded object.

    Raises
    ------
    ValueError
        If the JSON top-level value is not an object.
    OSError, json.JSONDecodeError
        If the file cannot be read or decoded.
    """

    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        message = f"expected JSON object in {path}"
        raise TypeError(message)
    return value


def _dependency_paths(record: Mapping[str, object]) -> list[Path]:
    """Read only dependencies whose current bytes match the envelope hash.

    Parameters
    ----------
    record : Mapping[str, object]
        Raw Clang envelope.

    Returns
    -------
    list[pathlib.Path]
        Existing hash-verified dependency paths, preserving file order.
    """

    closure = _object(record.get("dependency_closure"))
    files = closure.get("files")
    if not isinstance(files, list):
        return []
    paths: list[Path] = []
    for item in files:
        if not isinstance(item, dict):
            continue
        dependency = _object(item)
        path_value = _string_or(dependency.get("path"), "")
        expected_hash = _string_or(dependency.get("sha256"), "")
        if not path_value or len(expected_hash) != 64:
            continue
        path = Path(path_value)
        if path.is_file():
            stat = path.stat()
            if _dependency_sha_matches(
                str(path.resolve()), expected_hash, stat.st_size, stat.st_mtime_ns
            ):
                paths.append(path)
    return paths


@lru_cache(maxsize=100_000)
def _dependency_sha_matches(
    path_value: str,
    expected_sha256: str,
    size_bytes: int,
    modified_ns: int,
) -> bool:
    """Check a dependency digest once per path and current file signature.

    Parameters
    ----------
    path_value : str
        Resolved dependency path.
    expected_sha256 : str
        SHA-256 retained in the Clang envelope.
    size_bytes : int
        Current dependency byte count used to invalidate stale cache entries.
    modified_ns : int
        Current nanosecond modification time used to invalidate stale entries.

    Returns
    -------
    bool
        Whether current bytes match the captured digest.

    Notes
    -----
    The cache key includes file size and modification time. The capture's
    immutable artifact digest remains the source of the expected value.
    """

    del size_bytes, modified_ns
    path = Path(path_value)
    return path.is_file() and _sha256_file(path) == expected_sha256


def _index_record_paths(attempt_root: Path) -> dict[str, Path]:
    """Index raw artifact paths without decoding large frontend records.

    Parameters
    ----------
    attempt_root : pathlib.Path
        Batch attempt directory.

    Returns
    -------
    dict[str, pathlib.Path]
        Selection ID to raw path mapping using the immutable case directory.

    Raises
    ------
    ValueError
        If a raw file contains invalid JSON or multiple records.
    OSError
        If raw artifacts cannot be read.
    """

    paths: dict[str, Path] = {}
    for path in sorted(attempt_root.glob("*/*/raw.ndjson")):
        selection_id = path.parent.name
        if selection_id in paths:
            message = f"duplicate raw envelope path for {selection_id}"
            raise ValueError(message)
        paths[selection_id] = path
    return paths


def _read_raw_envelope(path: Path) -> Mapping[str, object]:
    """Decode one NDJSON envelope while keeping the batch memory bounded.

    Parameters
    ----------
    path : pathlib.Path
        One immutable raw case artifact.

    Returns
    -------
    Mapping[str, object]
        Decoded envelope for a single case.

    Raises
    ------
    ValueError
        If the artifact does not contain exactly one JSON object record.
    OSError, json.JSONDecodeError
        If the artifact cannot be read or decoded.
    """

    with path.open(encoding="utf-8") as stream:
        first_line = stream.readline()
        if not first_line.strip():
            message = f"expected one non-empty raw envelope line in {path}"
            raise ValueError(message)
        if any(line.strip() for line in stream):
            message = f"expected exactly one raw envelope in {path}"
            raise ValueError(message)
    value = json.loads(first_line)
    if not isinstance(value, dict):
        message = f"raw envelope is not an object in {path}"
        raise TypeError(message)
    return value


def _find_progress_row(attempt_root: Path, selection_id: str) -> Mapping[str, object]:
    """Find an explicit held/failure row in the batch progress ledger.

    Parameters
    ----------
    attempt_root : pathlib.Path
        Batch attempt directory.
    selection_id : str
        Cohort identity to retrieve.

    Returns
    -------
    Mapping[str, object]
        Progress row or an empty mapping if no result has been recorded.
    """

    path = attempt_root / "progress.json"
    if not path.is_file():
        return {}
    progress = _read_optional_object(path)
    rows = progress.get("results")
    if isinstance(rows, list):
        for item in rows:
            if isinstance(item, dict) and item.get("selection_id") == selection_id:
                return item
    return {}


def _read_object(path: Path) -> Mapping[str, object]:
    """Read a JSON object from disk.

    Parameters
    ----------
    path : pathlib.Path
        JSON input path.

    Returns
    -------
    Mapping[str, object]
        Decoded object.

    Raises
    ------
    ValueError
        If the input is not a JSON object.
    OSError, json.JSONDecodeError
        If the file cannot be read or decoded.
    """

    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        message = f"expected a JSON object in {path}"
        raise TypeError(message)
    return value


def _read_optional_object(path: Path) -> Mapping[str, object]:
    """Read a JSON object when present, otherwise return an empty mapping.

    Parameters
    ----------
    path : pathlib.Path
        Optional JSON path.

    Returns
    -------
    Mapping[str, object]
        Decoded object or an empty mapping.
    """

    return _read_object(path) if path.is_file() else {}


def _object_rows(value: object, label: str) -> list[Mapping[str, object]]:
    """Validate one JSON array of objects.

    Parameters
    ----------
    value : object
        Potential list of JSON objects.
    label : str
        Field label used in errors.

    Returns
    -------
    list[Mapping[str, object]]
        Validated object rows.

    Raises
    ------
    ValueError
        If the value is not a list of objects.
    """

    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        message = f"{label} must be an array of objects"
        raise TypeError(message)
    return value


def _object(value: object) -> Mapping[str, object]:
    """Return a safe object mapping for decoded JSON.

    Parameters
    ----------
    value : object
        Potential JSON object.

    Returns
    -------
    Mapping[str, object]
        Input mapping or an empty mapping.
    """

    return value if isinstance(value, dict) else {}


def _preprocessing_event_count(value: object) -> int | None:
    """Count preprocessing events in either supported envelope shape.

    Parameters
    ----------
    value : object
        Preprocessing event array or an object containing an ``events`` array.

    Returns
    -------
    int or None
        Number of retained event rows, or None when the envelope shape is
        unknown rather than silently treating it as an empty event list.
    """

    if isinstance(value, (list, tuple)):
        return len(value)
    events = _object(value).get("events")
    return len(events) if isinstance(events, (list, tuple)) else None


def _sequence(value: object) -> Sequence[object]:
    """Return a list or tuple from an untrusted JSON value.

    Parameters
    ----------
    value : object
        Potential JSON array.

    Returns
    -------
    Sequence[object]
        The input list or tuple, or an empty sequence.
    """

    return value if isinstance(value, (list, tuple)) else ()


def _required_string(mapping: Mapping[str, object], field: str) -> str:
    """Read a required nonempty string.

    Parameters
    ----------
    mapping : Mapping[str, object]
        JSON object.
    field : str
        Field name.

    Returns
    -------
    str
        Required string.

    Raises
    ------
    ValueError
        If the field is missing or invalid.
    """

    value = mapping.get(field)
    if not isinstance(value, str) or not value:
        message = f"required nonempty string field: {field}"
        raise TypeError(message)
    return value


def _string_or(value: object, fallback: str) -> str:
    """Return a string or a stable fallback label.

    Parameters
    ----------
    value : object
        Potential string value.
    fallback : str
        Value returned for non-string or empty input.

    Returns
    -------
    str
        Input string or fallback.
    """

    return value if isinstance(value, str) and value else fallback


def _string_list(value: object) -> list[str]:
    """Return string values from a JSON list.

    Parameters
    ----------
    value : object
        Potential JSON list.

    Returns
    -------
    list[str]
        Nonempty strings only.
    """

    return (
        [item for item in value if isinstance(item, str) and item]
        if isinstance(value, list)
        else []
    )


def _sha256_file(path: Path) -> str:
    """Compute the SHA-256 digest of a file.

    Parameters
    ----------
    path : pathlib.Path
        File to hash.

    Returns
    -------
    str
        Lowercase hexadecimal digest.
    """

    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _sha256_json(value: object) -> str:
    """Compute a canonical JSON digest for nested identity fields.

    Parameters
    ----------
    value : object
        JSON-serializable identity structure.

    Returns
    -------
    str
        Lowercase hexadecimal digest.
    """

    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
