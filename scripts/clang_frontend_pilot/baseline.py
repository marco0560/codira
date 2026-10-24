"""Measure current default C and C++ analyzers on the fixed source cohort.

Parameters
----------
None

Returns
-------
None

Notes
-----
This script invokes only the committed analyzer APIs with their constructor
defaults. It does not configure new extraction behavior or execute compilers.
Each DTO, status, source/dependency snapshot, producer identity, and failed
attempt is retained per case.
"""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import importlib
import importlib.metadata
import inspect
import json
import os
import platform
import shutil
import subprocess
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from enum import Enum
from pathlib import Path
from typing import Protocol, cast


def run_baseline(
    manifest_path: Path,
    output_root: Path,
    attempt_id: str,
    repository_roots: Mapping[str, Path] | None = None,
    selection_ids: Sequence[str] | None = None,
) -> dict[str, object]:
    """Run committed C23 and C++42 analyzer defaults for each cohort row.

    Parameters
    ----------
    manifest_path : pathlib.Path
        Immutable frozen cohort manifest.
    output_root : pathlib.Path
        Durable default-baseline evidence directory.
    attempt_id : str
        Immutable, path-safe baseline attempt identity.
    repository_roots : Mapping[str, pathlib.Path] or None, optional
        Explicit checkout paths overriding the manifest's repository map.
    selection_ids : Sequence[str] or None, optional
        Optional subset for resuming a bounded baseline; all rows by default.

    Returns
    -------
    dict[str, object]
        Per-case baseline results and distinct run/analysis status counts.

    Raises
    ------
    OSError
        If input sources, producer files, or evidence cannot be read/written.
    ValueError
        If source/profile/producer identity differs from a retained attempt.
    subprocess.SubprocessError
        If revision inspection cannot be executed.
    """

    if not attempt_id or any(
        character
        not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.-"
        for character in attempt_id
    ):
        message = "attempt_id must be path-safe"
        raise ValueError(message)
    manifest_bytes = manifest_path.read_bytes()
    manifest = _load_object(manifest_bytes, "cohort manifest")
    rows = _object_rows(manifest.get("rows"))
    rows_by_id = {_required_string(row, "selection_id"): row for row in rows}
    if len(rows_by_id) != len(rows):
        message = "cohort manifest contains duplicate selection_id values"
        raise ValueError(message)
    selected = list(selection_ids) if selection_ids is not None else list(rows_by_id)
    if set(selected) - rows_by_id.keys():
        message = "selection contains an ID absent from the frozen manifest"
        raise ValueError(message)

    manifest_repositories = _object(manifest.get("repositories"))
    roots: dict[str, Path] = {}
    for repository_id, value in manifest_repositories.items():
        checkout = _object(value).get("checkout")
        if isinstance(checkout, str) and checkout:
            roots[repository_id] = Path(checkout).resolve()
    if repository_roots:
        roots.update({key: value.resolve() for key, value in repository_roots.items()})

    runtime_identity = _load_runtime_identity()
    manifest_sha256 = hashlib.sha256(manifest_bytes).hexdigest()
    attempt_root = output_root / "attempts" / attempt_id
    attempt_root.mkdir(parents=True, exist_ok=True)
    batch_identity = {
        "schema_version": "codira.clang-frontend-pilot-default-baseline/1",
        "attempt_id": attempt_id,
        "manifest_path": str(manifest_path.resolve()),
        "manifest_sha256": manifest_sha256,
        "runtime": runtime_identity,
        "repository_roots": {key: str(value) for key, value in sorted(roots.items())},
        "analyzer_defaults": {
            "configuration": {},
            "mode": "constructor defaults; configure() is not called",
        },
    }
    _bind_identity(attempt_root / "run-identity.json", batch_identity)
    checkpoint_path = attempt_root / "checkpoint.json"
    checkpoint = _load_optional(checkpoint_path)
    _validate_checkpoint(checkpoint, batch_identity)
    if not checkpoint:
        checkpoint = {
            "schema_version": "codira.clang-frontend-pilot-baseline-checkpoint/1",
            "batch_identity": batch_identity,
            "rows": {},
        }
        _write_atomic_json(checkpoint_path, checkpoint)
    results: list[dict[str, object]] = []

    for selection_id in selected:
        row = rows_by_id[selection_id]
        repository_id = _required_string(row, "repository_id")
        repository_root = roots.get(repository_id)
        record_path = attempt_root / "cases" / f"{selection_id}.json"
        previous = _checkpoint_row(checkpoint, selection_id)
        if record_path.is_file():
            retained = _load_object(
                record_path.read_bytes(), f"retained result {selection_id}"
            )
            current_identity = _current_case_identity(
                row, repository_root, runtime_identity
            )
            if current_identity is None and retained.get("run_status") == "held":
                current_identity = _case_identity(retained)
            if current_identity != previous.get("identity_sha256"):
                message = f"source, dependency, producer, or config changed for {selection_id}; use a fresh attempt_id"
                raise ValueError(message)
            if retained.get("run_status") not in {
                "complete",
                "held",
            } or not _artifact_matches(record_path, previous):
                message = f"retained failed or incomplete result for {selection_id}; use a fresh attempt_id"
                raise ValueError(message)
            results.append(dict(retained))
            continue

        result = _analyze_row(row, repository_root, runtime_identity, manifest_sha256)
        case_identity = _case_identity(result)
        result["case_identity_sha256"] = case_identity
        _write_new_json(record_path, result)
        attempt = {
            "selection_id": selection_id,
            "identity_sha256": case_identity,
            "status": result.get("run_status"),
            "artifact_relpath": str(record_path.relative_to(attempt_root)),
            "artifact_sha256": _sha256_file(record_path),
        }
        checkpoint = _append_checkpoint(checkpoint, selection_id, attempt)
        _write_atomic_json(checkpoint_path, checkpoint)
        results.append(result)
        _write_progress(attempt_root, results, len(rows))

    summary = {
        **batch_identity,
        "cohort_denominator": len(rows),
        "selected_count": len(selected),
        "results": [
            {
                "selection_id": item.get("selection_id"),
                "run_status": item.get("run_status"),
                "analyzer_status": item.get("analysis_status"),
                "artifact_relpath": item.get("artifact_relpath"),
                "case_identity_sha256": item.get("case_identity_sha256"),
            }
            for item in results
        ],
        "run_status_counts": _count(results, "run_status"),
        "analyzer_coverage_counts": _count(results, "analysis_coverage_state"),
    }
    summary_path = _next_revision(attempt_root / "baseline-summary.json")
    _write_new_json(summary_path, summary)
    return summary


def _analyze_row(
    row: Mapping[str, object],
    repository_root: Path | None,
    runtime_identity: Mapping[str, object],
    manifest_sha256: str,
) -> dict[str, object]:
    """Analyze one source row and retain DTO, context, and failure evidence.

    Parameters
    ----------
    row : Mapping[str, object]
        Frozen cohort row.
    repository_root : pathlib.Path or None
        Pinned checkout for the row's repository.
    runtime_identity : Mapping[str, object]
        Imported module, source, package, and DTO schema identity.
    manifest_sha256 : str
        SHA-256 digest of the exact cohort manifest.

    Returns
    -------
    dict[str, object]
        Result record with raw DTO when available, and explicit holds/failures.
    """

    language = _required_string(row, "language")
    analyzer_class, context_reader, analyzer_name = _load_analyzer(language)
    analyzer = analyzer_class()
    configuration_fingerprint = _string_or(
        getattr(analyzer, "configuration_fingerprint", None), ""
    )
    record: dict[str, object] = {
        **_manifest_identity(row),
        "schema_version": "codira.clang-frontend-pilot-default-baseline-record/1",
        "manifest_sha256": manifest_sha256,
        "baseline_tier": "default_analyzer_mode",
        "analyzer_name": analyzer_name,
        "analyzer_version": _string_or(getattr(analyzer, "version", None), "unknown"),
        "configuration": {},
        "configuration_sha256": _sha256_json(
            {
                "configuration": {},
                "configuration_fingerprint": configuration_fingerprint,
            }
        ),
        "configuration_fingerprint": configuration_fingerprint,
        "runtime_identity": runtime_identity,
        "native_acceptance": "not_applicable",
        "analysis_status": "not_run",
        "analysis_coverage_state": "not_run",
        "run_status": "held",
        "hold_reasons": [],
    }
    if repository_root is None:
        record["hold_reasons"] = ["repository checkout mapping unavailable"]
        return record

    relative_path = _required_string(row, "repository_relative_path")
    source_path = (repository_root / relative_path).resolve()
    record["source_path"] = str(source_path)
    if not source_path.is_relative_to(repository_root.resolve()):
        record["hold_reasons"] = ["source path escapes pinned repository checkout"]
        return record
    if not source_path.is_file():
        record["hold_reasons"] = ["source file unavailable"]
        return record
    source_sha_before = _sha256_file(source_path)
    record["source_sha256_observed"] = source_sha_before
    if source_sha_before != row.get("source_sha256"):
        record["hold_reasons"] = ["source bytes differ from frozen manifest"]
        return record

    try:
        revision = subprocess.run(
            [_git_executable(), "rev-parse", "HEAD"],
            cwd=repository_root,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        ).stdout.strip()
        record["repository_head"] = revision
        if revision != row.get("repository_revision"):
            record["hold_reasons"] = [
                "repository checkout revision differs from frozen manifest"
            ]
            return record
        context_before = context_reader(source_path, repository_root, include_paths=())
        analysis_started = time.perf_counter()
        try:
            analysis = analyzer.analyze_file(source_path, repository_root)
        finally:
            record["analysis_elapsed_seconds"] = time.perf_counter() - analysis_started
        context_after = context_reader(source_path, repository_root, include_paths=())
        source_sha_after = _sha256_file(source_path)
        dependencies_before = _dependency_identity(context_before, source_path)
        dependencies_after = _dependency_identity(context_after, source_path)
        record["dependency_context"] = {
            "before": dependencies_before,
            "after": dependencies_after,
            "stable": dependencies_before["sha256"] == dependencies_after["sha256"],
        }
        record["source_sha256_after"] = source_sha_after
        result_json = _json_value(analysis)
        record["analysis_result"] = result_json
        record["fact_counts"] = _fact_counts(analysis)
        record["coordinate_counts"] = _coordinate_counts(result_json)
        analysis_status = getattr(analysis, "status", None)
        record["analysis_status"] = _status_json(analysis_status)
        record["analysis_coverage_state"] = _string_or(
            getattr(getattr(analysis_status, "coverage_state", None), "value", None),
            "unknown",
        )
        record["run_status"] = (
            "complete"
            if source_sha_after == source_sha_before
            and dependencies_before["sha256"] == dependencies_after["sha256"]
            else "partial"
        )
        if record["run_status"] == "partial":
            record["hold_reasons"] = [
                "source or include dependency changed during analysis"
            ]
    except Exception as error:  # noqa: BLE001 -- retain every analyzer failure as case evidence
        record["run_status"] = "failed"
        record["failure"] = {
            "exception_type": type(error).__name__,
            "message": str(error),
        }
    return record


class _Analyzer(Protocol):
    """Describe the first-party default analyzer interface used here.

    Parameters
    ----------
    None

    Returns
    -------
    None
    """

    name: str
    version: str
    configuration_fingerprint: str

    def analyze_file(self, path: Path, root: Path) -> object:
        """Analyze one file using the current analyzer's default settings.

        Parameters
        ----------
        path : pathlib.Path
            Translation unit to analyze.
        root : pathlib.Path
            Repository boundary for source and literal includes.

        Returns
        -------
        object
            Pure analyzer result DTO.
        """


ContextReader = Callable[..., object]


def _load_analyzer(language: str) -> tuple[type[_Analyzer], ContextReader, str]:
    """Load the committed analyzer class and matching dependency reader.

    Parameters
    ----------
    language : str
        Manifest language, ``c`` or ``cpp``.

    Returns
    -------
    tuple[type[object], object, str]
        Analyzer class, include-context reader, and canonical analyzer name.

    Raises
    ------
    ValueError
        If the source language is not C or C++.
    ImportError
        If the first-party analyzer package is unavailable.
    """

    if language == "c":
        package_name = "codira_analyzer_c"
        context_name = "codira_analyzer_c.c_include_context"
        class_name = "CAnalyzer"
        analyzer_name = "c"
    elif language == "cpp":
        package_name = "codira_analyzer_cpp"
        context_name = "codira_analyzer_cpp.cpp_include_context"
        class_name = "CppAnalyzer"
        analyzer_name = "cpp"
    else:
        message = f"unsupported source language {language!r}"
        raise ValueError(message)
    package = importlib.import_module(package_name)
    context_module = importlib.import_module(context_name)
    analyzer_class = getattr(package, class_name)
    context_reader = context_module.read_include_context
    if not isinstance(analyzer_class, type) or not callable(context_reader):
        message = f"required default analyzer API has invalid types for {language}"
        raise TypeError(message)
    return (
        cast("type[_Analyzer]", analyzer_class),
        cast("ContextReader", context_reader),
        analyzer_name,
    )


def _current_case_identity(
    row: Mapping[str, object],
    repository_root: Path | None,
    runtime_identity: Mapping[str, object],
) -> str | None:
    """Recompute source and parser dependencies before checkpoint reuse.

    Parameters
    ----------
    row : Mapping[str, object]
        Frozen cohort row.
    repository_root : pathlib.Path or None
        Current checkout for this source.
    runtime_identity : Mapping[str, object]
        Current analyzer package and DTO source identity.

    Returns
    -------
    str or None
        Full current case identity, or None when source context is unavailable.
    """

    if repository_root is None:
        return None
    analyzer_class, context_reader, analyzer_name = _load_analyzer(
        _required_string(row, "language")
    )
    analyzer = analyzer_class()
    source_path = (
        repository_root / _required_string(row, "repository_relative_path")
    ).resolve()
    if not source_path.is_file() or not source_path.is_relative_to(
        repository_root.resolve()
    ):
        return None
    context = context_reader(source_path, repository_root, include_paths=())
    dependencies = _dependency_identity(context, source_path)
    return _case_identity(
        {
            "source_sha256_observed": _sha256_file(source_path),
            "dependency_context": {"after": dependencies},
            "analyzer_name": analyzer_name,
            "analyzer_version": analyzer.version,
            "configuration_sha256": _sha256_json(
                {
                    "configuration": {},
                    "configuration_fingerprint": analyzer.configuration_fingerprint,
                }
            ),
            "runtime_identity": runtime_identity,
            "baseline_tier": "default_analyzer_mode",
        }
    )


def _load_runtime_identity() -> dict[str, object]:
    """Bind imported analyzer packages and core DTO implementation bytes.

    Parameters
    ----------
    None

    Returns
    -------
    dict[str, object]
        Python runtime, package versions/source hashes, and DTO source hash.

    Raises
    ------
    ImportError
        If required committed analyzer or Codira DTO modules are unavailable.
    OSError
        If any imported module source cannot be read.
    """

    codira_root = Path(__file__).resolve().parents[2]
    expected_analyzer_revision = "11dcedac3179c62ed526eaa6222fb3535e141e26"
    revision = subprocess.run(
        [_git_executable(), "rev-parse", "HEAD"],
        cwd=codira_root,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout.strip()
    source_check = subprocess.run(
        [
            _git_executable(),
            "diff",
            "--quiet",
            expected_analyzer_revision,
            "--",
            "packages/codira-analyzer-c",
            "packages/codira-analyzer-cpp",
            "src/codira/models.py",
        ],
        cwd=codira_root,
        check=False,
    )
    if source_check.returncode != 0:
        message = "C23/CPP42 analyzer or DTO sources differ from the approved 11dcedac revision"
        raise ValueError(message)
    packages: dict[str, dict[str, object]] = {}
    for import_name, distribution_name in (
        ("codira_analyzer_c", "codira-analyzer-c"),
        ("codira_analyzer_cpp", "codira-analyzer-cpp"),
    ):
        module = importlib.import_module(import_name)
        module_path = Path(inspect.getfile(module)).resolve()
        package_root = module_path.parent
        packages[import_name] = {
            "module_path": str(module_path),
            "module_sha256": _sha256_file(module_path),
            "package_sha256": _tree_sha256(package_root),
            "distribution_version": importlib.metadata.version(distribution_name),
        }
    grammar_packages: dict[str, str] = {}
    for distribution_name in ("tree-sitter", "tree-sitter-c", "tree-sitter-cpp"):
        try:
            grammar_packages[distribution_name] = importlib.metadata.version(
                distribution_name
            )
        except importlib.metadata.PackageNotFoundError:
            grammar_packages[distribution_name] = "not-installed"
    models = importlib.import_module("codira.models")
    models_path = Path(inspect.getfile(models)).resolve()
    return {
        "codira_head": revision,
        "analyzer_source_revision": expected_analyzer_revision,
        "analyzer_source_match": True,
        "python": platform.python_version(),
        "executable": str(Path(sys.executable).resolve()),
        "grammar_packages": grammar_packages,
        "packages": packages,
        "dto_module_path": str(models_path),
        "dto_module_sha256": _sha256_file(models_path),
    }


def _dependency_identity(context: object, source_path: Path) -> dict[str, object]:
    """Hash exact parser-visible source and included header snapshots.

    Parameters
    ----------
    context : object
        IncludeContext returned by the committed analyzer's own reader.
    source_path : pathlib.Path
        Translation unit excluded from the header list.

    Returns
    -------
    dict[str, object]
        Context fingerprint and sorted path/hash rows.
    """

    headers = getattr(context, "headers", ())
    files: list[dict[str, str]] = []
    for header in headers:
        path = Path(header.path).resolve()
        content = header.source
        if not isinstance(content, bytes):
            continue
        files.append(
            {
                "path": str(path),
                "sha256": hashlib.sha256(content).hexdigest(),
            }
        )
    files.sort(key=lambda item: item["path"])
    return {
        "source_path": str(source_path.resolve()),
        "context_fingerprint": _string_or(getattr(context, "fingerprint", None), ""),
        "unresolved": _json_value(getattr(context, "unresolved", ())),
        "files": files,
        "sha256": _sha256_json(
            {
                "context_fingerprint": getattr(context, "fingerprint", ""),
                "files": files,
                "unresolved": getattr(context, "unresolved", ()),
            }
        ),
    }


def _fact_counts(analysis: object) -> dict[str, int]:
    """Count normalized DTO facts by exposed analysis-result collections.

    Parameters
    ----------
    analysis : object
        AnalysisResult returned by a first-party analyzer.

    Returns
    -------
    dict[str, int]
        Module, class, callable, declaration, import, documentation, and call
        counts from the exact result DTO.
    """

    iter_calls = getattr(analysis, "iter_call_sites", None)
    return {
        "modules": 1,
        "classes": len(getattr(analysis, "classes", ())),
        "functions": len(getattr(analysis, "functions", ())),
        "declarations": len(getattr(analysis, "declarations", ())),
        "imports": len(getattr(analysis, "imports", ())),
        "documentation": len(getattr(analysis, "documentation", ())),
        "calls": len(iter_calls()) if callable(iter_calls) else 0,
    }


def _coordinate_counts(value: object) -> dict[str, int]:
    """Count DTO artifacts carrying source line and token-column fields.

    Parameters
    ----------
    value : object
        JSON-compatible full result DTO.

    Returns
    -------
    dict[str, int]
        Number of serialized source objects with a line, token column, or end
        line. Codira DTOs use ``lineno`` and zero-based ``col_offset`` rather
        than Clang's one-based line/column and byte-offset shape.
    """

    totals = {
        "source_line_objects": 0,
        "source_column_objects": 0,
        "source_end_line_objects": 0,
    }
    pending = [value]
    while pending:
        current = pending.pop()
        if isinstance(current, dict):
            if isinstance(current.get("lineno"), int):
                totals["source_line_objects"] += 1
            if isinstance(current.get("col_offset"), int):
                totals["source_column_objects"] += 1
            if isinstance(current.get("end_lineno"), int):
                totals["source_end_line_objects"] += 1
            pending.extend(item for key, item in current.items() if key != "status")
        elif isinstance(current, list):
            pending.extend(current)
    return totals


def _status_json(value: object) -> object:
    """Serialize analyzer status without changing its enum or dataclass fields.

    Parameters
    ----------
    value : object
        Status object returned in AnalysisResult.

    Returns
    -------
    object
        JSON-compatible status structure.
    """

    return _json_value(value)


def _json_value(value: object) -> object:
    """Convert pure API DTO values to JSON-compatible data recursively.

    Parameters
    ----------
    value : object
        Dataclass, enum, path, mapping, sequence, or scalar.

    Returns
    -------
    object
        JSON-compatible representation retaining DTO field names and order.
    """

    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {
            field.name: _json_value(getattr(value, field.name))
            for field in dataclasses.fields(value)
        }
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_value(item) for item in value]
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    return repr(value)


def _manifest_identity(row: Mapping[str, object]) -> dict[str, object]:
    """Copy exact source and cohort labels into one baseline record.

    Parameters
    ----------
    row : Mapping[str, object]
        Frozen cohort row.

    Returns
    -------
    dict[str, object]
        Source identity fields shared with the Clang record schema.
    """

    return {
        key: row.get(key)
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
        )
    }


def _case_identity(record: Mapping[str, object]) -> str:
    """Hash source, input context, analyzer producer, and configuration inputs.

    Parameters
    ----------
    record : Mapping[str, object]
        Baseline result envelope.

    Returns
    -------
    str
        Stable lowercase SHA-256 identity.
    """

    dependencies = _object(record.get("dependency_context"))
    runtime = _object(record.get("runtime_identity"))
    return _sha256_json(
        {
            "source_sha256": record.get(
                "source_sha256_observed", record.get("source_sha256")
            ),
            "dependency_sha256": dependencies.get("after"),
            "analyzer_name": record.get("analyzer_name"),
            "analyzer_version": record.get("analyzer_version"),
            "configuration_sha256": record.get("configuration_sha256"),
            "runtime_identity": runtime,
            "baseline_tier": record.get("baseline_tier"),
        }
    )


def _load_optional(path: Path) -> Mapping[str, object]:
    """Read an optional checkpoint JSON object.

    Parameters
    ----------
    path : pathlib.Path
        Checkpoint path.

    Returns
    -------
    Mapping[str, object]
        Decoded mapping, or empty mapping if absent.
    """

    return _load_object(path.read_bytes(), str(path)) if path.is_file() else {}


def _load_object(data: bytes, label: str) -> Mapping[str, object]:
    """Decode and validate a top-level JSON object.

    Parameters
    ----------
    data : bytes
        JSON bytes.
    label : str
        Input name for any raised error.

    Returns
    -------
    Mapping[str, object]
        Decoded JSON object.

    Raises
    ------
    ValueError
        If the data is invalid JSON or is not an object.
    """

    try:
        value = json.loads(data)
    except json.JSONDecodeError as error:
        message = f"invalid JSON in {label}: {error}"
        raise ValueError(message) from error
    if not isinstance(value, dict):
        message = f"expected JSON object in {label}"
        raise TypeError(message)
    return value


def _object(value: object) -> Mapping[str, object]:
    """Return a safe mapping for a decoded JSON value.

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


def _object_rows(value: object) -> list[Mapping[str, object]]:
    """Validate cohort rows as an array of JSON objects.

    Parameters
    ----------
    value : object
        Potential rows array.

    Returns
    -------
    list[Mapping[str, object]]
        Valid row objects.

    Raises
    ------
    ValueError
        If the input is not an array of objects.
    """

    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        message = "cohort manifest rows must be an array of objects"
        raise ValueError(message)
    return value


def _required_string(row: Mapping[str, object], key: str) -> str:
    """Read one required nonempty string from a JSON object.

    Parameters
    ----------
    row : Mapping[str, object]
        Input object.
    key : str
        Field name.

    Returns
    -------
    str
        Nonempty string value.

    Raises
    ------
    ValueError
        If the field is missing or has another type.
    """

    value = row.get(key)
    if not isinstance(value, str) or not value:
        message = f"required nonempty string: {key}"
        raise ValueError(message)
    return value


def _string_or(value: object, fallback: str) -> str:
    """Return a string or a stable fallback.

    Parameters
    ----------
    value : object
        Potential string.
    fallback : str
        Fallback for non-string or empty input.

    Returns
    -------
    str
        Input or fallback.
    """

    return value if isinstance(value, str) and value else fallback


def _tree_sha256(root: Path) -> str:
    """Hash every regular package file outside Python cache directories.

    Parameters
    ----------
    root : pathlib.Path
        Imported analyzer package directory.

    Returns
    -------
    str
        Aggregate SHA-256 of sorted relative file paths and file digests.
    """

    files = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or "__pycache__" in path.parts or path.suffix == ".pyc":
            continue
        files.append(
            {"path": path.relative_to(root).as_posix(), "sha256": _sha256_file(path)}
        )
    return _sha256_json(files)


def _count(results: Sequence[Mapping[str, object]], field: str) -> dict[str, int]:
    """Count one categorical result field.

    Parameters
    ----------
    results : Sequence[Mapping[str, object]]
        Per-case result rows.
    field : str
        Field to count.

    Returns
    -------
    dict[str, int]
        Sorted category counts.
    """

    counts: dict[str, int] = {}
    for result in results:
        value = result.get(field)
        key = value if isinstance(value, str) and value else "missing"
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def _append_checkpoint(
    checkpoint: Mapping[str, object], selection_id: str, attempt: Mapping[str, object]
) -> dict[str, object]:
    """Append one baseline case to its durable attempt ledger.

    Parameters
    ----------
    checkpoint : Mapping[str, object]
        Existing checkpoint state.
    selection_id : str
        Cohort row identifier.
    attempt : Mapping[str, object]
        Immutable case status and output identity.

    Returns
    -------
    dict[str, object]
        Updated checkpoint without discarding earlier rows.
    """

    result = dict(checkpoint)
    rows = dict(_object(checkpoint.get("rows")))
    rows[selection_id] = dict(attempt)
    result["schema_version"] = "codira.clang-frontend-pilot-baseline-checkpoint/1"
    result["rows"] = rows
    return result


def _checkpoint_row(
    checkpoint: Mapping[str, object], selection_id: str
) -> Mapping[str, object]:
    """Get a saved case identity from baseline checkpoint state.

    Parameters
    ----------
    checkpoint : Mapping[str, object]
        Existing checkpoint.
    selection_id : str
        Cohort row key.

    Returns
    -------
    Mapping[str, object]
        Saved attempt row or an empty mapping.
    """

    return _object(_object(checkpoint.get("rows")).get(selection_id))


def _validate_checkpoint(
    checkpoint: Mapping[str, object], batch_identity: Mapping[str, object]
) -> None:
    """Reject a baseline checkpoint created from other source or producer inputs.

    Parameters
    ----------
    checkpoint : Mapping[str, object]
        Existing checkpoint state.
    batch_identity : Mapping[str, object]
        Current manifest, producer, and default configuration identity.

    Returns
    -------
    None

    Raises
    ------
    ValueError
        If an existing checkpoint belongs to other inputs.
    """

    if checkpoint and checkpoint.get("batch_identity") != batch_identity:
        message = "baseline checkpoint identity mismatch; use a fresh attempt_id"
        raise ValueError(message)


def _artifact_matches(path: Path, row: Mapping[str, object]) -> bool:
    """Check that a retained case artifact still matches its checkpoint digest.

    Parameters
    ----------
    path : pathlib.Path
        Retained result path.
    row : Mapping[str, object]
        Checkpoint row containing an artifact digest.

    Returns
    -------
    bool
        True when the digest matches.
    """

    return row.get("artifact_sha256") == _sha256_file(path)


def _bind_identity(path: Path, identity: Mapping[str, object]) -> None:
    """Bind an immutable attempt directory to its batch-level identities.

    Parameters
    ----------
    path : pathlib.Path
        Identity record path.
    identity : Mapping[str, object]
        Current batch identity.

    Returns
    -------
    None

    Raises
    ------
    ValueError
        If an existing attempt ID has different input identities.
    OSError
        If the identity record cannot be read or written.
    """

    encoded = json.dumps(identity, sort_keys=True, indent=2) + "\n"
    if path.is_file():
        if path.read_text(encoding="utf-8") != encoded:
            message = "baseline attempt ID is already bound to different inputs"
            raise ValueError(message)
        return
    _write_new_text(path, encoded)


def _write_progress(
    attempt_root: Path, results: Sequence[Mapping[str, object]], denominator: int
) -> None:
    """Atomically update per-attempt progress after each source file.

    Parameters
    ----------
    attempt_root : pathlib.Path
        Baseline attempt directory.
    results : Sequence[Mapping[str, object]]
        Cases observed so far.
    denominator : int
        Full cohort size.

    Returns
    -------
    None
    """

    _write_atomic_json(
        attempt_root / "progress.json",
        {
            "schema_version": "codira.clang-frontend-pilot-baseline-progress/1",
            "cohort_denominator": denominator,
            "observed_count": len(results),
            "rows": [
                {
                    "selection_id": row.get("selection_id"),
                    "run_status": row.get("run_status"),
                }
                for row in results
            ],
        },
    )


def _write_atomic_json(path: Path, value: Mapping[str, object]) -> None:
    """Atomically replace a mutable JSON checkpoint or progress file.

    Parameters
    ----------
    path : pathlib.Path
        Mutable JSON target.
    value : Mapping[str, object]
        JSON data.

    Returns
    -------
    None

    Raises
    ------
    OSError, TypeError
        If the file cannot be serialized or replaced.
    """

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        temporary.write_text(
            json.dumps(value, sort_keys=True, indent=2) + "\n", encoding="utf-8"
        )
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def _write_new_json(path: Path, value: Mapping[str, object]) -> None:
    """Create one immutable JSON artifact without replacement.

    Parameters
    ----------
    path : pathlib.Path
        New artifact path.
    value : Mapping[str, object]
        JSON-compatible data.

    Returns
    -------
    None

    Raises
    ------
    FileExistsError
        If the artifact path already exists.
    OSError, TypeError
        If the artifact cannot be written or serialized.
    """

    _write_new_text(path, json.dumps(value, sort_keys=True, indent=2) + "\n")


def _write_new_text(path: Path, value: str) -> None:
    """Create a new immutable UTF-8 text artifact.

    Parameters
    ----------
    path : pathlib.Path
        New artifact path.
    value : str
        Text payload.

    Returns
    -------
    None

    Raises
    ------
    FileExistsError
        If the target exists.
    OSError
        If the file cannot be created.
    """

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        stream.write(value)


def _next_revision(path: Path) -> Path:
    """Return the next unused immutable revision path.

    Parameters
    ----------
    path : pathlib.Path
        Base filename.

    Returns
    -------
    pathlib.Path
        Next ``-rN`` revision path.
    """

    revision = 1
    candidate = path.with_name(f"{path.stem}-r{revision}{path.suffix}")
    while candidate.exists():
        revision += 1
        candidate = path.with_name(f"{path.stem}-r{revision}{path.suffix}")
    return candidate


def _sha256_file(path: Path) -> str:
    """Compute a streaming SHA-256 digest.

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
    """Hash nested JSON identity values in stable key order.

    Parameters
    ----------
    value : object
        JSON-compatible identity.

    Returns
    -------
    str
        Lowercase hexadecimal digest.
    """

    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _git_executable() -> str:
    """Resolve Git for exact revision checks.

    Parameters
    ----------
    None

    Returns
    -------
    str
        Absolute Git executable path.

    Raises
    ------
    FileNotFoundError
        If Git is unavailable on PATH.
    """

    executable = shutil.which("git")
    if executable is None:
        message = "git executable is unavailable on PATH"
        raise FileNotFoundError(message)
    return executable


def main(argv: Sequence[str] | None = None) -> int:
    """Run a checkpointed default-analyzer baseline.

    Parameters
    ----------
    argv : Sequence[str] or None, optional
        CLI arguments, defaulting to process arguments.

    Returns
    -------
    int
        Zero if every selected case has a complete analyzer invocation;
        one if any case is held, partial, or failed.

    Raises
    ------
    SystemExit
        For invalid or missing CLI arguments.
    OSError, ValueError, subprocess.SubprocessError
        Operational failures propagated from :func:`run_baseline`.
    """

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--attempt-id", required=True)
    parser.add_argument(
        "--repository-root", action="append", type=_key_path, default=[]
    )
    parser.add_argument("--selection-id", action="append", default=None)
    args = parser.parse_args(argv)
    result = run_baseline(
        args.manifest,
        args.output_root,
        args.attempt_id,
        dict(args.repository_root),
        args.selection_id,
    )
    summary_path = _next_revision(
        args.output_root / "attempts" / args.attempt_id / "command-summary.json"
    )
    _write_new_json(summary_path, result)
    run_status_counts = result.get("run_status_counts")
    counts = run_status_counts if isinstance(run_status_counts, dict) else {}
    return int(any(counts.get(status, 0) for status in ("held", "partial", "failed")))


def _key_path(value: str) -> tuple[str, Path]:
    """Parse a command-line repository mapping ``ID=PATH``.

    Parameters
    ----------
    value : str
        Mapping value.

    Returns
    -------
    tuple[str, pathlib.Path]
        Key and path.

    Raises
    ------
    argparse.ArgumentTypeError
        If the mapping is malformed.
    """

    key, separator, path = value.partition("=")
    if not separator or not key or not path:
        message = "repository mapping must be ID=PATH"
        raise argparse.ArgumentTypeError(message)
    return key, Path(path)


if __name__ == "__main__":
    raise SystemExit(main())
