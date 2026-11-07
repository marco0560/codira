"""Summarize default-analyzer evidence without equating execution and correctness.

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
import json
import math
from collections import Counter
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence


def summarize_baseline(manifest_path: Path, attempt_root: Path) -> dict[str, object]:
    """Build a deterministic analysis-outcome report from retained DTO records.

    Parameters
    ----------
    manifest_path : pathlib.Path
        Frozen cohort manifest used by the baseline.
    attempt_root : pathlib.Path
        Default TS baseline attempt directory.

    Returns
    -------
    dict[str, object]
        Counts for run completion, analyzer DTO status, context readiness,
        diagnostics, extracted artifact types, source coordinates, and source
        identity checks.

    Raises
    ------
    OSError
        If source or retained evidence cannot be read.
    ValueError
        If an artifact is malformed or duplicated.
    """

    manifest_bytes = manifest_path.read_bytes()
    manifest = _object(json.loads(manifest_bytes))
    manifest_rows = _objects(manifest.get("rows"))
    expected = {_string(row.get("selection_id")): row for row in manifest_rows}
    if len(expected) != len(manifest_rows):
        message = "manifest selection IDs must be unique"
        raise ValueError(message)
    raw_records: dict[str, tuple[Path, Mapping[str, object]]] = {}
    for path in sorted((attempt_root / "cases").glob("*.json")):
        record = _object(json.loads(path.read_text(encoding="utf-8")))
        selection_id = _string(record.get("selection_id"))
        if not selection_id or selection_id in raw_records:
            message = f"missing or duplicate baseline selection ID in {path}"
            raise ValueError(message)
        raw_records[selection_id] = (path, record)

    capture_counts: Counter[str] = Counter()
    analysis_coverage: Counter[str] = Counter()
    analysis_grammar: Counter[str] = Counter()
    index_symbols: Counter[str] = Counter()
    context_status: Counter[str] = Counter()
    diagnostics: Counter[str] = Counter()
    diagnostic_messages: Counter[str] = Counter()
    reliable_categories: Counter[str] = Counter()
    omitted_categories: Counter[str] = Counter()
    fact_totals: Counter[str] = Counter()
    coordinate_totals: Counter[str] = Counter()
    source_matches = 0
    revision_matches = 0
    case_durations: list[float] = []
    report_rows: list[dict[str, object]] = []

    for selection_id, row in expected.items():
        pair = raw_records.get(selection_id)
        context_status[_string(row.get("profile_context_status")) or "missing"] += 1
        if pair is None:
            capture_counts["missing_record"] += 1
            report_rows.append(
                {"selection_id": selection_id, "run_status": "missing_record"}
            )
            continue
        path, record = pair
        run_status = _string(record.get("run_status")) or "missing"
        duration_value = record.get("analysis_elapsed_seconds")
        duration = (
            float(duration_value)
            if isinstance(duration_value, (int, float))
            and not isinstance(duration_value, bool)
            and math.isfinite(float(duration_value))
            and float(duration_value) >= 0.0
            else None
        )
        if duration is not None:
            case_durations.append(duration)
        capture_counts[run_status] += 1
        source_matches += int(
            record.get("source_sha256_observed") == row.get("source_sha256")
        )
        revision_matches += int(
            record.get("repository_head") == row.get("repository_revision")
        )
        result = _object(record.get("analysis_result"))
        status = _object(result.get("status"))
        coverage_value = status.get("coverage_state")
        coverage = _string(coverage_value) or "status_missing"
        analysis_coverage[coverage] += 1
        analysis_grammar[_string(status.get("grammar")) or "status_missing"] += 1
        index_symbols[str(result.get("index_symbols", "missing"))] += 1
        diagnostic_rows = _objects(status.get("diagnostics"))
        for diagnostic in diagnostic_rows:
            diagnostics[_string(diagnostic.get("category")) or "unknown"] += 1
            diagnostic_messages[_string(diagnostic.get("message")) or "unknown"] += 1
        for category in _string_items(status.get("reliable_categories")):
            reliable_categories[category] += 1
        for category in _string_items(status.get("omitted_categories")):
            omitted_categories[category] += 1
        row_facts = _fact_counts_from_dto(result)
        row_coordinates = _coordinate_counts_from_dto(result)
        fact_totals.update(row_facts)
        coordinate_totals.update(row_coordinates)
        report_rows.append(
            {
                "selection_id": selection_id,
                "run_status": run_status,
                "analysis_coverage_state": coverage,
                "index_symbols": result.get("index_symbols"),
                "diagnostic_categories": sorted(
                    _string(diagnostic.get("category")) or "unknown"
                    for diagnostic in diagnostic_rows
                ),
                "fact_counts": row_facts,
                "coordinate_counts": row_coordinates,
                "source_sha256_observed": record.get("source_sha256_observed"),
                "repository_head": record.get("repository_head"),
                "case_identity_sha256": record.get("case_identity_sha256"),
                "analysis_elapsed_seconds": duration,
                "raw_artifact": str(path),
                "raw_sha256": _sha256_file(path),
            }
        )

    unselected = sorted(set(raw_records) - set(expected))
    if unselected:
        message = f"baseline output contains IDs absent from cohort: {unselected}"
        raise ValueError(message)
    run_identity = _optional_object(attempt_root / "run-identity.json")
    ordered_durations = sorted(case_durations)
    p95_index = max(0, math.ceil(0.95 * len(ordered_durations)) - 1)
    return {
        "schema_version": "codira.clang-frontend-pilot-default-baseline-analysis/1",
        "baseline_tier": "default_analyzer_mode",
        "manifest": {
            "path": str(manifest_path.resolve()),
            "sha256": hashlib.sha256(manifest_bytes).hexdigest(),
            "cohort_denominator": len(expected),
        },
        "attempt_root": str(attempt_root.resolve()),
        "producer_identity": run_identity,
        "summary": {
            "runner_capture_status_counts": dict(sorted(capture_counts.items())),
            "analysis_coverage_state_counts": dict(sorted(analysis_coverage.items())),
            "analysis_grammar_counts": dict(sorted(analysis_grammar.items())),
            "index_symbols_counts": dict(sorted(index_symbols.items())),
            "input_context_readiness_counts": dict(sorted(context_status.items())),
            "diagnostic_category_counts": dict(sorted(diagnostics.items())),
            "diagnostic_message_counts": dict(sorted(diagnostic_messages.items())),
            "reliable_category_counts": dict(sorted(reliable_categories.items())),
            "omitted_category_counts": dict(sorted(omitted_categories.items())),
            "fact_count_totals": dict(sorted(fact_totals.items())),
            "source_coordinate_totals": dict(sorted(coordinate_totals.items())),
            "source_hash_matches": source_matches,
            "repository_revision_matches": revision_matches,
            "timed_case_count": len(ordered_durations),
            "case_analysis_elapsed_seconds_total": sum(ordered_durations),
            "case_analysis_elapsed_seconds_median": (
                ordered_durations[len(ordered_durations) // 2]
                if ordered_durations
                else None
            ),
            "case_analysis_elapsed_seconds_p95": (
                ordered_durations[p95_index] if ordered_durations else None
            ),
            "timing_basis": "monotonic timer around analyzer.analyze_file only; excludes context snapshots and serialization",
            "semantic_grade": "not_independently_graded",
            "native_compiler_acceptance": "not_applicable_to_tree_sitter_baseline",
            "per_file_timing": (
                "captured_for_timed_cases_only"
                if ordered_durations
                else "not_captured_in_this_baseline_attempt"
            ),
            "per_file_rss": "not_measured; process high-water cannot be attributed per case",
            "comparison_limit": "descriptive comparison with Clang uses different default and compile-profile input contexts",
        },
        "rows": report_rows,
    }


def main(argv: Sequence[str] | None = None) -> int:
    """Write one immutable default-baseline analysis report.

    Parameters
    ----------
    argv : Sequence[str] or None, optional
        CLI arguments, defaulting to process arguments.

    Returns
    -------
    int
        Zero when every cohort row has one source-bound baseline record, one
        otherwise.

    Raises
    ------
    SystemExit
        For invalid or missing arguments.
    OSError, ValueError
        When report inputs fail their contract.
    """

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--attempt-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    report = summarize_baseline(args.manifest, args.attempt_root)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(report, sort_keys=True, indent=2) + "\n")
    summary = _object(report.get("summary"))
    capture = _object(summary.get("runner_capture_status_counts"))
    manifest = _object(report.get("manifest"))
    return int(capture.get("complete") != manifest.get("cohort_denominator"))


def _optional_object(path: Path) -> Mapping[str, object]:
    """Read a JSON file when available, otherwise return an empty mapping.

    Parameters
    ----------
    path : pathlib.Path
        Optional input path.

    Returns
    -------
    Mapping[str, object]
        Decoded mapping or empty mapping.
    """

    return (
        _object(json.loads(path.read_text(encoding="utf-8"))) if path.is_file() else {}
    )


def _object(value: object) -> Mapping[str, object]:
    """Return a safe mapping for a decoded JSON value.

    Parameters
    ----------
    value : object
        Potential JSON object.

    Returns
    -------
    Mapping[str, object]
        The input object or an empty mapping.
    """

    return value if isinstance(value, dict) else {}


def _objects(value: object) -> list[Mapping[str, object]]:
    """Validate an array of JSON objects.

    Parameters
    ----------
    value : object
        Potential JSON object array.

    Returns
    -------
    list[Mapping[str, object]]
        Valid object rows.

    Raises
    ------
    ValueError
        If the input is not a list of objects.
    """

    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        message = "expected array of JSON objects"
        raise ValueError(message)
    return value


def _string(value: object) -> str:
    """Return a string or an empty value for category aggregation.

    Parameters
    ----------
    value : object
        Potential string.

    Returns
    -------
    str
        Input string or empty string.
    """

    return value if isinstance(value, str) else ""


def _string_items(value: object) -> list[str]:
    """Read string values from an optional JSON list.

    Parameters
    ----------
    value : object
        Potential array.

    Returns
    -------
    list[str]
        Nonempty strings in input order.
    """

    return (
        [item for item in value if isinstance(item, str) and item]
        if isinstance(value, list)
        else []
    )


def _fact_counts_from_dto(result: Mapping[str, object]) -> dict[str, int]:
    """Count fact collections from the full normalized result DTO.

    Parameters
    ----------
    result : Mapping[str, object]
        Serialized AnalysisResult excluding no status or provenance fields.

    Returns
    -------
    dict[str, int]
        Counts for top-level and method callables, declarations, imports,
        documentation, and physical call-site DTOs.
    """

    functions = _object_items(result.get("functions"))
    classes = _object_items(result.get("classes"))
    methods = [
        method
        for class_row in classes
        for method in _object_items(class_row.get("methods"))
    ]
    all_functions = [*functions, *methods]
    calls = sum(len(_object_items(function.get("calls"))) for function in all_functions)
    return {
        "modules": 1,
        "classes": len(classes),
        "functions_and_methods": len(all_functions),
        "declarations": len(_object_items(result.get("declarations"))),
        "imports": len(_object_items(result.get("imports"))),
        "documentation": len(_object_items(result.get("documentation"))),
        "calls": calls,
    }


def _coordinate_counts_from_dto(result: Mapping[str, object]) -> dict[str, int]:
    """Count source span fields in artifact DTOs, excluding diagnostics.

    Parameters
    ----------
    result : Mapping[str, object]
        Serialized AnalysisResult.

    Returns
    -------
    dict[str, int]
        Count of source objects with one-based line fields, zero-based token
        columns, and inclusive end lines. Codira does not emit Clang byte offsets.
    """

    counts = {
        "source_line_objects": 0,
        "source_column_objects": 0,
        "source_end_line_objects": 0,
    }
    pending = [
        value
        for key, value in result.items()
        if key not in {"status", "source_path", "index_symbols"}
    ]
    while pending:
        value = pending.pop()
        if isinstance(value, dict):
            if isinstance(value.get("lineno"), int):
                counts["source_line_objects"] += 1
            if isinstance(value.get("col_offset"), int):
                counts["source_column_objects"] += 1
            if isinstance(value.get("end_lineno"), int):
                counts["source_end_line_objects"] += 1
            pending.extend(value.values())
        elif isinstance(value, list):
            pending.extend(value)
    return counts


def _object_items(value: object) -> list[Mapping[str, object]]:
    """Read an array of JSON objects without coercing malformed values.

    Parameters
    ----------
    value : object
        Potential list of result objects.

    Returns
    -------
    list[Mapping[str, object]]
        Valid object items.
    """

    return (
        [item for item in value if isinstance(item, dict)]
        if isinstance(value, list)
        else []
    )


def _sha256_file(path: Path) -> str:
    """Hash one retained baseline artifact.

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


if __name__ == "__main__":
    raise SystemExit(main())
