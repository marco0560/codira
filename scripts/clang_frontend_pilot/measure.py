"""Run and resume an immutable per-case Clang pilot batch.

Parameters
----------
None

Returns
-------
None

Notes
-----
Each selected row receives its own raw envelope and adapter checkpoint. A
failed or interrupted attempt is preserved; retrying it requires a fresh
attempt ID. Reusing an existing attempt ID is allowed only through the
adapter's identity-checked checkpoint.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
import time
from collections.abc import Mapping, Sequence
from pathlib import Path

_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,79}$")


def run_batch(  # noqa: PLR0913 -- explicit inputs bind one immutable batch identity
    manifest_path: Path,
    adapter_runner: Path,
    helper_path: Path,
    output_root: Path,
    attempt_id: str,
    repository_roots: Mapping[str, Path],
    compile_databases: Mapping[str, Path],
    selection_ids: Sequence[str] | None = None,
) -> dict[str, object]:
    """Run selected manifest rows while preserving resumable raw evidence.

    Parameters
    ----------
    manifest_path : pathlib.Path
        Versioned immutable cohort manifest.
    adapter_runner : pathlib.Path
        Explicit adapter CLI script path.
    helper_path : pathlib.Path
        Explicitly built LibTooling helper executable.
    output_root : pathlib.Path
        Durable qualification evidence directory.
    attempt_id : str
        Immutable identifier for this batch attempt.
    repository_roots : Mapping[str, pathlib.Path]
        Checkout path by exact ``repository_id``.
    compile_databases : Mapping[str, pathlib.Path]
        Compilation database path by exact ``repository_id``.
    selection_ids : Sequence[str] or None, optional
        Optional cohort row IDs; omitted means all rows in manifest order.
    Returns
    -------
    dict[str, object]
        Batch summary with denominator, terminal statuses, and raw artifact
        references. Rows lacking a checkout or compilation database remain
        explicit holds rather than disappearing from the denominator.

    Raises
    ------
    OSError
        If an input or durable artifact cannot be read or written.
    ValueError
        If manifest identities are malformed or an attempt is resumed with
        different manifest, helper, adapter, configuration, or CDB identities.
    subprocess.SubprocessError
        If the adapter runner process cannot be launched.
    """

    if not _SAFE_ID.fullmatch(attempt_id):
        message = "attempt_id must be a short path-safe identifier"
        raise ValueError(message)
    manifest = _read_json(manifest_path)
    rows = _object_list(manifest.get("rows"))
    rows_by_id = {_required_string(row, "selection_id"): row for row in rows}
    if len(rows_by_id) != len(rows):
        message = "manifest contains duplicate selection_id values"
        raise ValueError(message)
    selected = list(selection_ids) if selection_ids is not None else list(rows_by_id)
    unknown = sorted(set(selected) - rows_by_id.keys())
    if unknown:
        message = f"unknown selection_id values: {', '.join(unknown)}"
        raise ValueError(message)

    manifest_digest = sha256_file(manifest_path)
    helper_digest = sha256_file(helper_path)
    runner_digest = sha256_file(adapter_runner)
    adapter_module_path = adapter_runner.with_name("adapter.py")
    adapter_digest = sha256_file(adapter_module_path)
    config_files = {
        path.name: sha256_file(path)
        for path in (
            adapter_runner.parent / "contract.py",
            adapter_runner.parent / "contract.md",
        )
        if path.is_file()
    }
    config_digest = _sha256_bytes(
        json.dumps(config_files, sort_keys=True, separators=(",", ":")).encode("utf-8")
    )
    repository_map = {key: path.resolve() for key, path in repository_roots.items()}
    compile_map = {key: path.resolve() for key, path in compile_databases.items()}
    repository_heads = _repository_heads(rows_by_id, repository_map)
    cdb_digests = {
        key: sha256_file(path) for key, path in compile_map.items() if path.is_file()
    }
    source_inputs = {
        row_id: _source_input_identity(
            row, repository_map.get(str(row.get("repository_id")))
        )
        for row_id, row in rows_by_id.items()
    }
    attempt_root = output_root / "attempts" / attempt_id
    attempt_root.mkdir(parents=True, exist_ok=True)
    run_identity = {
        "schema_version": "codira.clang-frontend-pilot-batch/1",
        "attempt_id": attempt_id,
        "manifest_path": str(manifest_path.resolve()),
        "manifest_sha256": manifest_digest,
        "helper_path": str(helper_path.resolve()),
        "helper_sha256": helper_digest,
        "adapter_runner": str(adapter_runner.resolve()),
        "adapter_runner_sha256": runner_digest,
        "adapter_module": str(adapter_module_path.resolve()),
        "adapter_module_sha256": adapter_digest,
        "measurement_script": str(Path(__file__).resolve()),
        "measurement_script_sha256": sha256_file(Path(__file__).resolve()),
        "configuration_sha256": config_digest,
        "compile_databases": {
            key: {"path": str(path), "sha256": cdb_digests.get(key)}
            for key, path in sorted(compile_map.items())
        },
        "repository_roots": {
            key: str(path) for key, path in sorted(repository_map.items())
        },
        "repository_heads": repository_heads,
        "source_inputs": source_inputs,
    }
    _verify_retained_inputs(attempt_root)
    _bind_run_identity(attempt_root / "run-identity.json", run_identity)

    case_results: list[dict[str, object]] = []
    for selection_id in selected:
        row = rows_by_id[selection_id]
        repository_id = _required_string(row, "repository_id")
        repository_root = repository_map.get(repository_id)
        compile_database = compile_map.get(repository_id)
        case_root = (
            attempt_root
            / _safe_component(repository_id)
            / _safe_component(selection_id)
        )
        case_root.mkdir(parents=True, exist_ok=True)
        raw_path = case_root / "raw.ndjson"
        checkpoint_path = case_root / "adapter-checkpoint.json"
        output_ready = raw_path.is_file()
        checkpoint_ready = checkpoint_path.is_file()
        invocation_root = case_root / "invocations"
        attempted_before = invocation_root.is_dir() and any(invocation_root.iterdir())
        if output_ready != checkpoint_ready or (attempted_before and not output_ready):
            message = f"incomplete retained case attempt for {selection_id}; use a new attempt_id"
            raise ValueError(message)
        if repository_root is None or compile_database is None:
            case_results.append(
                {
                    "selection_id": selection_id,
                    "status": "held",
                    "hold_reasons": [
                        "repository checkout or compilation database not supplied"
                    ],
                    "raw_artifact": None,
                }
            )
            _write_progress(attempt_root, case_results, len(rows))
            continue

        command = [
            sys.executable,
            "-m",
            "scripts.clang_frontend_pilot.run",
            "--manifest",
            str(manifest_path.resolve()),
            "--compile-commands",
            str(compile_database),
            "--repository-root",
            str(repository_root),
            "--helper",
            str(helper_path.resolve()),
            "--output",
            str(raw_path),
            "--checkpoint",
            str(checkpoint_path),
            "--selection-id",
            selection_id,
        ]
        invocation_started = time.perf_counter()
        completed = subprocess.run(
            command,
            cwd=adapter_runner.parents[2],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        invocation_elapsed_seconds = time.perf_counter() - invocation_started
        invocation_root = _next_invocation_directory(case_root)
        _retain_process_stream(invocation_root, "runner.stdout.txt", completed.stdout)
        _retain_process_stream(invocation_root, "runner.stderr.txt", completed.stderr)
        envelopes = _read_ndjson(raw_path) if raw_path.is_file() else []
        if len(envelopes) != 1:
            result = {
                "selection_id": selection_id,
                "status": "incomplete",
                "runner_exit_code": completed.returncode,
                "runner_elapsed_seconds": invocation_elapsed_seconds,
                "raw_artifact": str(raw_path) if raw_path.is_file() else None,
                "hold_reasons": [
                    "adapter did not produce exactly one terminal envelope"
                ],
            }
        else:
            envelope = envelopes[0]
            result = {
                "selection_id": selection_id,
                "status": envelope.get("status", "missing"),
                "context_status": envelope.get("context_status"),
                "runner_exit_code": completed.returncode,
                "runner_elapsed_seconds": invocation_elapsed_seconds,
                "raw_artifact": str(raw_path),
                "raw_sha256": sha256_file(raw_path),
                "hold_reasons": envelope.get("hold_reasons", []),
            }
        case_results.append(result)
        _write_progress(attempt_root, case_results, len(rows))

    return {
        **run_identity,
        "cohort_denominator": len(rows),
        "selected_count": len(selected),
        "results": case_results,
        "status_counts": _status_counts(case_results),
        "runner_timing": _timing_summary(case_results),
        "memory_measurement": "not_measured; no per-case isolated process RSS was collected",
    }


def main(argv: Sequence[str] | None = None) -> int:
    """Parse explicit inputs and run one immutable batch attempt.

    Parameters
    ----------
    argv : Sequence[str] or None, optional
        CLI arguments, defaulting to the process argument vector.

    Returns
    -------
    int
        Zero when the batch completed without adapter process failures;
        nonzero when at least one selected row failed or remained incomplete.

    Raises
    ------
    SystemExit
        When required CLI arguments are missing or invalid.
    OSError, ValueError, subprocess.SubprocessError
        Propagated by :func:`run_batch` for diagnosable operational failures.
    """

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--adapter-runner", type=Path, required=True)
    parser.add_argument("--helper", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--attempt-id", required=True)
    parser.add_argument(
        "--repository-root", action="append", type=_key_path, default=[]
    )
    parser.add_argument(
        "--compile-database", action="append", type=_key_path, default=[]
    )
    parser.add_argument("--selection-id", action="append", default=None)
    args = parser.parse_args(argv)
    result = run_batch(
        manifest_path=args.manifest,
        adapter_runner=args.adapter_runner,
        helper_path=args.helper,
        output_root=args.output_root,
        attempt_id=args.attempt_id,
        repository_roots=dict(args.repository_root),
        compile_databases=dict(args.compile_database),
        selection_ids=args.selection_id,
    )
    result_path = args.output_root / "attempts" / args.attempt_id / "batch-summary.json"
    _write_revisioned_json(result_path, result)
    raw_counts = result.get("status_counts")
    counts = raw_counts if isinstance(raw_counts, Mapping) else {}
    return int(
        any(counts.get(status, 0) for status in ("incomplete", "failed", "partial"))
    )


def sha256_file(path: Path) -> str:
    """Return the streaming SHA-256 digest of one evidence file.

    Parameters
    ----------
    path : pathlib.Path
        File whose bytes are hashed.

    Returns
    -------
    str
        Lowercase hexadecimal SHA-256 digest.

    Raises
    ------
    OSError
        If the file cannot be read.
    """

    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _read_json(path: Path) -> Mapping[str, object]:
    """Read a JSON object without coercing malformed top-level values.

    Parameters
    ----------
    path : pathlib.Path
        JSON input path.

    Returns
    -------
    Mapping[str, object]
        Decoded JSON object.

    Raises
    ------
    ValueError
        If the JSON top-level value is not an object.
    OSError, json.JSONDecodeError
        If the input cannot be read or decoded.
    """

    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        message = f"expected JSON object in {path}"
        raise TypeError(message)
    return value


def _object_list(value: object) -> list[Mapping[str, object]]:
    """Validate a list of JSON objects.

    Parameters
    ----------
    value : object
        Potential JSON array.

    Returns
    -------
    list[Mapping[str, object]]
        Validated object rows.

    Raises
    ------
    ValueError
        If the value is not an array of objects.
    """

    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        message = "manifest rows must be an array of objects"
        raise ValueError(message)
    return value


def _required_string(mapping: Mapping[str, object], key: str) -> str:
    """Read one required nonempty string field.

    Parameters
    ----------
    mapping : Mapping[str, object]
        Input JSON object.
    key : str
        Field name to read.

    Returns
    -------
    str
        Nonempty field value.

    Raises
    ------
    ValueError
        If the field is missing or not a nonempty string.
    """

    value = mapping.get(key)
    if not isinstance(value, str) or not value:
        message = f"manifest row requires nonempty {key}"
        raise ValueError(message)
    return value


def _bind_run_identity(path: Path, identity: Mapping[str, object]) -> None:
    """Create or verify immutable batch-level identities.

    Parameters
    ----------
    path : pathlib.Path
        Per-attempt identity record path.
    identity : Mapping[str, object]
        Current complete batch identity.

    Returns
    -------
    None

    Raises
    ------
    ValueError
        If an existing attempt ID is bound to different inputs.
    OSError
        If the identity record cannot be created or read.
    """

    encoded = json.dumps(identity, sort_keys=True, indent=2) + "\n"
    if path.exists():
        if path.read_text(encoding="utf-8") != encoded:
            message = "attempt_id is already bound to different input identities"
            raise ValueError(message)
        return
    _write_immutable_text(path, encoded)


def _write_progress(
    attempt_root: Path, results: Sequence[Mapping[str, object]], denominator: int
) -> None:
    """Atomically update the resumable batch progress ledger.

    Parameters
    ----------
    attempt_root : pathlib.Path
        Attempt directory.
    results : Sequence[Mapping[str, object]]
        Completed case observations so far.
    denominator : int
        Full cohort denominator, including unselected rows.

    Returns
    -------
    None
    """

    progress = {
        "schema_version": "codira.clang-frontend-pilot-batch-progress/1",
        "cohort_denominator": denominator,
        "observed_count": len(results),
        "results": list(results),
    }
    _write_mutable_json(attempt_root / "progress.json", progress)


def _source_input_identity(
    row: Mapping[str, object], repository_root: Path | None
) -> dict[str, object]:
    """Bind a cohort row to expected and current translation-unit source bytes.

    Parameters
    ----------
    row : Mapping[str, object]
        Cohort manifest row.
    repository_root : pathlib.Path or None
        Supplied checkout for the row repository.

    Returns
    -------
    dict[str, object]
        Source path, expected digest, and current digest when readable.
    """

    relative_path = _required_string(row, "repository_relative_path")
    expected_sha256 = _required_string(row, "source_sha256")
    source_path = (
        repository_root / relative_path if repository_root is not None else None
    )
    current_sha256 = (
        sha256_file(source_path)
        if source_path is not None and source_path.is_file()
        else None
    )
    return {
        "repository_relative_path": relative_path,
        "expected_sha256": expected_sha256,
        "source_path": str(source_path.resolve()) if source_path is not None else None,
        "current_sha256": current_sha256,
    }


def _repository_heads(
    rows_by_id: Mapping[str, Mapping[str, object]],
    repository_roots: Mapping[str, Path],
) -> dict[str, str | None]:
    """Verify each supplied checkout against the manifest's pinned revision.

    Parameters
    ----------
    rows_by_id : Mapping[str, Mapping[str, object]]
        Frozen cohort rows keyed by selection ID.
    repository_roots : Mapping[str, pathlib.Path]
        Current checkout mapping.

    Returns
    -------
    dict[str, str or None]
        Actual HEAD per supplied repository. Missing checkouts remain None and
        are recorded as holds by the batch runner.

    Raises
    ------
    ValueError
        If rows disagree on a repository's pinned revision or a supplied
        checkout is not at the frozen revision.
    subprocess.SubprocessError
        If Git cannot inspect a supplied checkout.
    """

    expected: dict[str, str] = {}
    for row in rows_by_id.values():
        repository_id = _required_string(row, "repository_id")
        revision = _required_string(row, "repository_revision")
        if repository_id in expected and expected[repository_id] != revision:
            message = f"cohort rows disagree on pinned revision for {repository_id}"
            raise ValueError(message)
        expected[repository_id] = revision
    actual: dict[str, str | None] = {}
    for repository_id, revision in sorted(expected.items()):
        checkout = repository_roots.get(repository_id)
        if checkout is None:
            actual[repository_id] = None
            continue
        completed = subprocess.run(
            [_git_executable(), "rev-parse", "HEAD"],
            cwd=checkout,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        if completed.returncode != 0:
            message = f"cannot verify Git HEAD for {repository_id}: {completed.stderr.strip()}"
            raise ValueError(message)
        actual_revision = completed.stdout.strip()
        if actual_revision != revision:
            message = f"checkout revision mismatch for {repository_id}: expected {revision}, found {actual_revision}"
            raise ValueError(message)
        actual[repository_id] = actual_revision
    return actual


def _verify_retained_inputs(attempt_root: Path) -> None:  # noqa: C901 -- validate all retained identity dimensions together
    """Reject resume when a retained source, dependency, or compiler changed.

    Parameters
    ----------
    attempt_root : pathlib.Path
        Existing attempt directory, if any.
    Returns
    -------
    None

    Raises
    ------
    ValueError
        If any retained source dependency or original compiler binary changed.
    OSError
        If retained envelope evidence cannot be read.
    """

    for raw_path in attempt_root.glob("*/*/raw.ndjson"):
        rows = _read_ndjson(raw_path)
        for record in rows:
            dependency_rows = record.get("dependency_closure")
            if isinstance(dependency_rows, dict):
                files = dependency_rows.get("files")
            else:
                files = None
            if isinstance(files, list):
                for dependency in files:
                    if not isinstance(dependency, dict):
                        message = f"malformed retained dependency in {raw_path}"
                        raise TypeError(message)
                    path_value = dependency.get("path")
                    expected = dependency.get("sha256")
                    if not isinstance(path_value, str) or not isinstance(expected, str):
                        message = f"unbound retained dependency in {raw_path}"
                        raise TypeError(message)
                    path = Path(path_value)
                    if not path.is_file() or sha256_file(path) != expected:
                        message = f"retained dependency changed; use a fresh attempt_id: {path}"
                        raise ValueError(message)
            original = record.get("original_compile_command")
            driver = original.get("driver") if isinstance(original, dict) else None
            if isinstance(driver, dict):
                compiler_path = driver.get("resolved_path")
                compiler_sha = driver.get("binary_sha256")
                if isinstance(compiler_path, str) and isinstance(compiler_sha, str):
                    path = Path(compiler_path)
                    if not path.is_file() or sha256_file(path) != compiler_sha:
                        message = (
                            f"retained compiler changed; use a fresh attempt_id: {path}"
                        )
                        raise ValueError(message)
            adaptation = record.get("clang_adaptation")
            toolchain = (
                adaptation.get("toolchain") if isinstance(adaptation, dict) else None
            )
            if isinstance(toolchain, dict):
                for path_field, digest_field, label in (
                    ("compiler_path", "compiler_sha256", "Clang compiler"),
                    ("helper_path", "helper_sha256", "LibTooling helper"),
                ):
                    tool_path = toolchain.get(path_field)
                    tool_sha = toolchain.get(digest_field)
                    if isinstance(tool_path, str) and isinstance(tool_sha, str):
                        path = Path(tool_path)
                        if not path.is_file() or sha256_file(path) != tool_sha:
                            message = f"retained {label} changed; use a fresh attempt_id: {path}"
                            raise ValueError(message)


def _next_invocation_directory(case_root: Path) -> Path:
    """Allocate a new stream directory for one adapter invocation.

    Parameters
    ----------
    case_root : pathlib.Path
        Case attempt directory.

    Returns
    -------
    pathlib.Path
        Newly created sequential invocation directory.
    """

    invocations = case_root / "invocations"
    invocations.mkdir(parents=True, exist_ok=True)
    number = 1
    while (invocations / f"run-{number:03d}").exists():
        number += 1
    path = invocations / f"run-{number:03d}"
    path.mkdir()
    return path


def _write_revisioned_json(path: Path, value: Mapping[str, object]) -> None:
    """Write an immutable batch summary revision without replacing history.

    Parameters
    ----------
    path : pathlib.Path
        Output JSON path.
    value : Mapping[str, object]
        JSON-serializable object.

    Returns
    -------
    None

    Notes
    -----
    A resumed attempt writes the next numbered summary revision, preserving
    any earlier report from an interrupted or partial execution.
    """

    revision = 1
    candidate = path.with_name(f"{path.stem}-r{revision}{path.suffix}")
    while candidate.exists():
        revision += 1
        candidate = path.with_name(f"{path.stem}-r{revision}{path.suffix}")
    _write_immutable_text(candidate, json.dumps(value, sort_keys=True, indent=2) + "\n")


def _write_mutable_json(path: Path, value: Mapping[str, object]) -> None:
    """Atomically replace a progress JSON file.

    Parameters
    ----------
    path : pathlib.Path
        Mutable progress file path.
    value : Mapping[str, object]
        JSON-serializable progress state.

    Returns
    -------
    None

    Raises
    ------
    OSError, TypeError
        If the progress file cannot be written.
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


def _write_immutable_text(path: Path, text: str) -> None:
    """Create a new text evidence file without replacement.

    Parameters
    ----------
    path : pathlib.Path
        Durable text path.
    text : str
        Text payload.

    Returns
    -------
    None

    Raises
    ------
    FileExistsError
        If the path already exists.
    OSError
        If the file cannot be created.
    """

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        stream.write(text)


def _retain_process_stream(case_root: Path, name: str, value: str) -> None:
    """Retain each adapter invocation stream exactly once.

    Parameters
    ----------
    case_root : pathlib.Path
        Case attempt artifact directory.
    name : str
        Stream filename.
    value : str
        Captured process output.

    Returns
    -------
    None

    Raises
    ------
    FileExistsError
        If a previous stream artifact already exists.
    OSError
        If output cannot be persisted.
    """

    _write_immutable_text(case_root / name, value)


def _read_ndjson(path: Path) -> list[Mapping[str, object]]:
    """Read all complete JSON objects from newline-delimited JSON evidence.

    Parameters
    ----------
    path : pathlib.Path
        NDJSON file.

    Returns
    -------
    list[Mapping[str, object]]
        Successfully decoded object rows.

    Raises
    ------
    ValueError
        If a complete line is invalid JSON or is not an object.
    OSError
        If the file cannot be read.
    """

    rows: list[Mapping[str, object]] = []
    with path.open("r", encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, start=1):
            if not line.strip():
                continue
            value = json.loads(line)
            if not isinstance(value, dict):
                message = f"NDJSON row {line_number} is not an object"
                raise TypeError(message)
            rows.append(value)
    return rows


def _status_counts(results: Sequence[Mapping[str, object]]) -> dict[str, int]:
    """Count result statuses without dropping held and failed observations.

    Parameters
    ----------
    results : Sequence[Mapping[str, object]]
        Per-case result rows.

    Returns
    -------
    dict[str, int]
        Sorted status counts.
    """

    counts: dict[str, int] = {}
    for row in results:
        status = row.get("status")
        key = status if isinstance(status, str) else "missing"
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def _timing_summary(results: Sequence[Mapping[str, object]]) -> dict[str, object]:
    """Summarize monotonic wall time around each adapter runner invocation.

    Parameters
    ----------
    results : Sequence[Mapping[str, object]]
        Batch result rows; rows without a launched process have no duration.

    Returns
    -------
    dict[str, object]
        Count, total, median, and p95 of measured runner wall durations.
    """

    durations = sorted(
        float(value)
        for row in results
        if isinstance((value := row.get("runner_elapsed_seconds")), (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
        and float(value) >= 0.0
    )
    p95_index = max(0, math.ceil(0.95 * len(durations)) - 1)
    return {
        "timed_runner_count": len(durations),
        "runner_wall_seconds_total": sum(durations),
        "runner_wall_seconds_median": durations[len(durations) // 2]
        if durations
        else None,
        "runner_wall_seconds_p95": durations[p95_index] if durations else None,
        "timing_basis": "monotonic wall time around adapter CLI subprocess; includes process startup and helper execution",
    }


def _key_path(value: str) -> tuple[str, Path]:
    """Parse a repository mapping encoded as ``ID=PATH``.

    Parameters
    ----------
    value : str
        Command-line mapping.

    Returns
    -------
    tuple[str, pathlib.Path]
        Repository identifier and path.

    Raises
    ------
    argparse.ArgumentTypeError
        If the mapping has no key or path.
    """

    key, separator, raw_path = value.partition("=")
    if not separator or not key or not raw_path:
        message = "mapping must be ID=PATH"
        raise argparse.ArgumentTypeError(message)
    return key, Path(raw_path)


def _safe_component(value: str) -> str:
    """Validate an identifier before using it as a path component.

    Parameters
    ----------
    value : str
        Identifier from the manifest.

    Returns
    -------
    str
        Validated path component.

    Raises
    ------
    ValueError
        If the value contains unsafe path syntax.
    """

    if not _SAFE_ID.fullmatch(value):
        message = f"unsafe path component: {value!r}"
        raise ValueError(message)
    return value


def _sha256_bytes(value: bytes) -> str:
    """Hash bytes with SHA-256.

    Parameters
    ----------
    value : bytes
        Input bytes.

    Returns
    -------
    str
        Lowercase hexadecimal SHA-256 digest.
    """

    return hashlib.sha256(value).hexdigest()


def _git_executable() -> str:
    """Resolve Git for immutable repository revision checks.

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


if __name__ == "__main__":
    raise SystemExit(main())
