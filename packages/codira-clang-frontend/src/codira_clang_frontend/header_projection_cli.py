"""Prepare captured translation-unit contexts and header projections.

Parameters
----------
None

Returns
-------
None
    Module namespace for explicit, resumable header preparation.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import cast
import uuid

from . import __version__
from .contracts import CompileProfile, HeaderProjectionResolution
from .frontend import ClangFrontend
from .profile import (
    PROFILE_SCHEMA,
    from_captured_profile_json,
    from_compile_commands,
    resolve_header_projection,
)

REQUEST_SCHEMA = "codira.clang-header-preparation-request/1"
RUN_SCHEMA = "codira.clang-header-preparation-run/1"


def _sha256(path: Path) -> str:
    """Hash a file using bounded memory.

    Parameters
    ----------
    path : pathlib.Path
        Existing file to hash.

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


def _write_new(path: Path, value: object) -> None:
    """Write one immutable canonical JSON record.

    Parameters
    ----------
    path : pathlib.Path
        New output path that must not already exist.
    value : object
        JSON-compatible record.

    Returns
    -------
    None

    Raises
    ------
    FileExistsError
        If an output identity already exists.
    OSError
        If the record cannot be persisted.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("xb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        temporary.unlink(missing_ok=True)


def _object(value: object, label: str) -> dict[str, object]:
    """Require a JSON object at a named request boundary.

    Parameters
    ----------
    value : object
        Parsed JSON value.
    label : str
        Human-readable input field name.

    Returns
    -------
    dict[str, object]
        Object with string keys.

    Raises
    ------
    ValueError
        If the value is not an object with string keys.
    """
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise ValueError(f"{label} must be an object")
    return cast("dict[str, object]", value)


def _absolute_path(value: object, label: str) -> Path:
    """Require an explicit absolute path in the request document.

    Parameters
    ----------
    value : object
        Untrusted JSON field.
    label : str
        Human-readable input field name.

    Returns
    -------
    pathlib.Path
        Canonical resolved path.

    Raises
    ------
    ValueError
        If the field is not an absolute path.
    """
    if not isinstance(value, str) or not Path(value).is_absolute():
        raise ValueError(f"{label} must be an explicit absolute path")
    return Path(value).resolve()


def _load_profile(row: dict[str, object], root: Path) -> CompileProfile:
    """Load one explicitly selected compile database or captured profile row.

    Parameters
    ----------
    row : dict[str, object]
        One translation-unit selection from the request document.
    root : pathlib.Path
        Explicit source repository root.

    Returns
    -------
    CompileProfile
        Exact compile profile without inferred compiler arguments.

    Raises
    ------
    ValueError
        If selection fields are incomplete or ambiguous.
    OSError
        If source or profile evidence cannot be read.
    """
    source = _absolute_path(row.get("source_path"), "translation_units.source_path")
    language = row.get("language")
    if language not in {"c", "cpp"}:
        raise ValueError("translation_units.language must be c or cpp")
    compile_commands = row.get("compile_commands")
    captured_profiles = row.get("captured_profiles")
    if (compile_commands is None) == (captured_profiles is None):
        raise ValueError(
            "each translation unit must select exactly one compile_commands "
            "or captured_profiles file"
        )
    if compile_commands is not None:
        database = _absolute_path(compile_commands, "compile_commands")
        return from_compile_commands(database, source, root, language)
    evidence = _absolute_path(captured_profiles, "captured_profiles")
    return from_captured_profile_json(evidence, source, root, _sha256(source))


def _resolution_record(resolution: HeaderProjectionResolution) -> dict[str, object]:
    """Serialize owner discovery without discarding held states.

    Parameters
    ----------
    resolution : HeaderProjectionResolution
        Captured dependency owner discovery result.

    Returns
    -------
    dict[str, object]
        JSON-compatible result record.
    """
    return {
        "status": resolution.status,
        "requested_header_path": str(resolution.requested_header_path),
        "candidate_profile_identities": list(resolution.candidate_profile_identities),
        "candidate_profiles": [
            {
                "profile_identity": candidate.profile_identity,
                "translation_unit_path": str(candidate.translation_unit_path),
                "language": candidate.language,
            }
            for candidate in resolution.candidates
        ],
        "request_identity": (
            resolution.request.identity if resolution.request is not None else None
        ),
        "owner_profile_identity": (
            resolution.request.owner_profile.identity
            if resolution.request is not None
            else None
        ),
        "owner_translation_unit": (
            str(resolution.request.owner_profile.source_path)
            if resolution.request is not None
            else None
        ),
    }


def _write_captured_profiles_manifest(
    profile_paths: list[Path], output_dir: Path
) -> Path:
    """Persist all ready owner profiles in one exact collection manifest.

    Parameters
    ----------
    profile_paths : list[pathlib.Path]
        Single-profile manifests produced by this preparation run.
    output_dir : pathlib.Path
        Durable output directory for the immutable collection manifest.

    Returns
    -------
    pathlib.Path
        Combined manifest path at ``captured_profiles.json``.

    Raises
    ------
    ValueError
        If a prepared profile has no retained single-profile evidence or the
        existing collection differs from the current profile rows.
    OSError
        If profile evidence cannot be read or the manifest cannot be written.
    """
    records: list[dict[str, object]] = []
    for profile_path in profile_paths:
        single_profile = _object(
            json.loads(profile_path.read_text(encoding="utf-8")),
            "prepared profile evidence",
        )
        if single_profile.get("schema_version") != PROFILE_SCHEMA:
            raise ValueError("prepared owner profile has an unsupported schema")
        rows = single_profile.get("profiles")
        if not isinstance(rows, list) or len(rows) != 1:
            raise ValueError("prepared owner profile evidence must contain one row")
        records.append(_object(rows[0], "prepared owner profile row"))

    path = output_dir / "captured_profiles.json"
    collection = {"schema_version": PROFILE_SCHEMA, "profiles": records}
    if path.exists():
        current = _object(
            json.loads(path.read_text(encoding="utf-8")), "profile collection"
        )
        if current != collection:
            raise ValueError("existing owner profile collection differs from this run")
    else:
        _write_new(path, collection)
    return path


def prepare_headers(
    request_path: Path,
    output_dir: Path,
    *,
    resume: bool = False,
) -> dict[str, object]:
    """Prepare explicit owner profiles and project requested physical headers.

    Parameters
    ----------
    request_path : pathlib.Path
        Immutable JSON request naming profiles and headers explicitly.
    output_dir : pathlib.Path
        New durable run directory, or the exact directory selected for resume.
    resume : bool, optional
        Reuse only checkpoints whose exact request and toolchain identities
        match this run.

    Returns
    -------
    dict[str, object]
        Run summary with every completed, held, or failed header row.

    Raises
    ------
    FileExistsError
        If a new run targets an existing directory.
    ValueError
        If a resumed run has changed inputs or request structure.
    OSError
        If request or durable artifact paths cannot be read or written.
    """
    request_file = request_path.resolve(strict=True)
    request_bytes = request_file.read_bytes()
    request_digest = hashlib.sha256(request_bytes).hexdigest()
    document = _object(json.loads(request_bytes), "request")
    if document.get("schema_version") != REQUEST_SCHEMA:
        raise ValueError("unsupported header preparation request schema")
    root = _absolute_path(document.get("repository_root"), "repository_root")
    helper = _absolute_path(document.get("helper_path"), "helper_path")
    receipt = _absolute_path(document.get("build_receipt_path"), "build_receipt_path")
    raw_units = document.get("translation_units")
    raw_headers = document.get("headers")
    if not isinstance(raw_units, list) or not isinstance(raw_headers, list):
        raise ValueError("request requires translation_units and headers arrays")
    bound_paths: set[Path] = set()
    for raw_unit in raw_units:
        unit = _object(raw_unit, "translation_units entry")
        bound_paths.add(_absolute_path(unit.get("source_path"), "source_path"))
        for field in ("compile_commands", "captured_profiles"):
            value = unit.get(field)
            if value is not None:
                bound_paths.add(_absolute_path(value, field))
    for raw_header in raw_headers:
        bound_paths.add(_absolute_path(raw_header, "headers entry"))
    bound_input_digests = [
        {
            "path": str(path),
            "sha256": _sha256(path) if path.is_file() else None,
        }
        for path in sorted(bound_paths)
    ]
    helper_digest = _sha256(helper)
    receipt_digest = _sha256(receipt)
    output = output_dir.resolve()
    run_record = {
        "schema_version": RUN_SCHEMA,
        "request_path": str(request_file),
        "request_sha256": request_digest,
        "helper_path": str(helper),
        "helper_sha256": helper_digest,
        "build_receipt_path": str(receipt),
        "build_receipt_sha256": receipt_digest,
        "bound_input_digests": bound_input_digests,
        "package_version": __version__,
    }
    if resume:
        existing = _object(json.loads((output / "run.json").read_text()), "run")
        if existing != run_record:
            mismatch = output / f"resume-rejected-{request_digest[:16]}.json"
            if not mismatch.exists():
                _write_new(
                    mismatch,
                    {
                        "status": "held_changed_input_identity",
                        "expected_run": existing,
                        "requested_run": run_record,
                    },
                )
            raise ValueError("resume inputs changed; start a new output identity")
        if next(output.glob("resume-rejected-*.json"), None) is not None:
            raise ValueError(
                "this run already rejected changed inputs; start a new run"
            )
    else:
        output.mkdir(parents=True, exist_ok=False)
        _write_new(output / "run.json", run_record)

    frontend = ClangFrontend(helper, receipt, package_version=__version__)
    profiles: list[CompileProfile] = []
    profile_paths: list[Path] = []
    unit_failures: list[dict[str, object]] = []
    for raw_unit in raw_units:
        failure_key = hashlib.sha256(
            json.dumps(raw_unit, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()[:20]
        failure_path = output / "checkpoints" / f"tu-failure-{failure_key}.json"
        if failure_path.exists():
            unit_failures.append(
                _object(json.loads(failure_path.read_text()), "TU failure checkpoint")
            )
            continue
        try:
            unit_row = _object(raw_unit, "translation_units entry")
            profile = _load_profile(unit_row, root)
            unit_key = hashlib.sha256(profile.identity.encode()).hexdigest()[:20]
            checkpoint = output / "checkpoints" / f"tu-{unit_key}.json"
            prepared_path = output / "profiles" / f"{unit_key}.json"
            if checkpoint.exists():
                saved = _object(json.loads(checkpoint.read_text()), "TU checkpoint")
                if saved.get("input_profile_identity") != profile.identity:
                    raise ValueError(
                        "translation-unit profile identity changed on resume"
                    )
                if saved.get("status") == "complete":
                    prepared = from_captured_profile_json(
                        prepared_path,
                        profile.source_path,
                        root,
                        _sha256(profile.source_path),
                    )
                    if prepared.identity != saved.get("prepared_profile_identity"):
                        raise ValueError("prepared profile identity changed on resume")
                    frontend.toolchain_fingerprint(prepared)
                    profiles.append(prepared)
                    profile_paths.append(prepared_path)
                    continue
                unit_failures.append(saved)
                continue
            if profile.status == "complete" and profile.compilation_context is not None:
                # Preserve the exact captured profile as an immutable stage input.
                from .profile import write_prepared_profile

                prepared = write_prepared_profile(
                    profile,
                    profile.dependencies,
                    profile.include_directories,
                    profile.environment,
                    profile.environment_mode,
                    profile.compilation_context,
                    prepared_path,
                )
                checkpoint_record: dict[str, object] = {
                    "status": "complete",
                    "input_profile_identity": profile.identity,
                    "prepared_profile_identity": prepared.identity,
                    "prepared_profile_path": str(prepared_path),
                    "source_sha256": prepared.source_sha256,
                    "preparation": "reused_complete_captured_profile",
                }
            else:
                preparation, prepared = frontend.prepare_profile(
                    profile,
                    attempt_dir=output / "attempts" / f"tu-{unit_key}",
                    profile_output_path=prepared_path,
                    attempt_id=f"prepare-{unit_key}",
                )
                checkpoint_record = {
                    "status": (
                        "complete"
                        if prepared.status == "complete"
                        and preparation.status in {"parsed", "diagnostics"}
                        else "held"
                    ),
                    "input_profile_identity": profile.identity,
                    "prepared_profile_identity": prepared.identity,
                    "prepared_profile_path": str(prepared_path),
                    "source_sha256": prepared.source_sha256,
                    "frontend_status": preparation.status,
                    "frontend_reasons": list(preparation.reasons),
                    "stdout_path": (
                        str(preparation.stdout_path)
                        if preparation.stdout_path is not None
                        else None
                    ),
                    "stdout_sha256": preparation.stdout_sha256,
                    "stderr_path": (
                        str(preparation.stderr_path)
                        if preparation.stderr_path is not None
                        else None
                    ),
                    "stderr_sha256": preparation.stderr_sha256,
                }
            _write_new(checkpoint, checkpoint_record)
            if checkpoint_record["status"] == "complete":
                profiles.append(prepared)
                profile_paths.append(prepared_path)
            else:
                unit_failures.append(checkpoint_record)
        except (OSError, ValueError, TypeError) as error:
            failure: dict[str, object] = {
                "status": "failed",
                "error_type": type(error).__name__,
                "error": str(error),
            }
            if not failure_path.exists():
                _write_new(failure_path, failure)
            unit_failures.append(failure)
            if resume:
                rejection_path = output / f"resume-rejected-profile-{failure_key}.json"
                if not rejection_path.exists():
                    _write_new(
                        rejection_path,
                        {
                            "status": "held_changed_owner_profile_identity",
                            "request_sha256": request_digest,
                            "error_type": type(error).__name__,
                            "error": str(error),
                        },
                    )
                raise ValueError(
                    "captured owner profile inputs changed; start a new output identity"
                ) from error

    _write_captured_profiles_manifest(profile_paths, output)

    headers: list[dict[str, object]] = []
    selected_owners = document.get("selected_owner_profile_identities", {})
    if not isinstance(selected_owners, dict):
        raise ValueError("selected_owner_profile_identities must be an object")
    for raw_header in raw_headers:
        header_path = _absolute_path(raw_header, "headers entry")
        header_key = hashlib.sha256(str(header_path).encode()).hexdigest()[:20]
        checkpoint = output / "checkpoints" / f"header-{header_key}.json"
        try:
            current_header_digest = _sha256(header_path)
        except OSError:
            held_record: dict[str, object] = {
                "status": "held_missing_generated_header",
                "requested_header_path": str(header_path),
                "owner_context_discovery": "not_run",
                "requested_header_projection": "not_run",
            }
            if not checkpoint.exists():
                _write_new(checkpoint, held_record)
            headers.append(held_record)
            continue
        if checkpoint.exists():
            saved = _object(json.loads(checkpoint.read_text()), "header checkpoint")
            if saved.get("requested_header_sha256") != current_header_digest:
                raise ValueError("header bytes changed on resume; start a new run")
            headers.append(saved)
            continue
        selected = selected_owners.get(str(header_path))
        resolution = resolve_header_projection(
            header_path,
            tuple(profiles),
            selected_owner_identity=(selected if isinstance(selected, str) else None),
        )
        record = _resolution_record(resolution)
        record["requested_header_sha256"] = current_header_digest
        record["owner_context_discovery"] = resolution.status
        record["requested_header_projection"] = "not_run"
        if resolution.request is not None:
            projection = frontend.analyze_header(
                resolution.request,
                attempt_dir=output / "attempts" / f"header-{header_key}",
                attempt_id=f"project-{header_key}",
            )
            record.update(
                {
                    "requested_header_projection": projection.status,
                    "projection_reasons": list(projection.reasons),
                    "cache_fingerprint": projection.cache_fingerprint,
                    "stdout_path": (
                        str(projection.stdout_path)
                        if projection.stdout_path is not None
                        else None
                    ),
                    "stdout_sha256": projection.stdout_sha256,
                    "stderr_path": (
                        str(projection.stderr_path)
                        if projection.stderr_path is not None
                        else None
                    ),
                    "stderr_sha256": projection.stderr_sha256,
                    "declaration_count": len(projection.declarations),
                    "callable_count": len(projection.callables),
                    "include_count": len(projection.includes),
                    "preprocessing_event_count": len(projection.preprocessing),
                    "documentation_comment_count": len(
                        projection.documentation_comments
                    ),
                    "translation_unit_path": str(
                        resolution.request.owner_profile.source_path
                    ),
                }
            )
        _write_new(checkpoint, record)
        headers.append(record)

    summary = {
        "schema_version": "codira.clang-header-preparation-summary/1",
        "run_identity": request_digest,
        "translation_unit_profiles_ready": len(profiles),
        "translation_unit_failures": unit_failures,
        "headers": headers,
        "preparation_complete": all(
            row.get("owner_context_discovery") == "ready"
            and row.get("requested_header_projection") in {"parsed", "diagnostics"}
            for row in headers
        )
        and not unit_failures,
    }
    summary_path = output / "summary.json"
    if not summary_path.exists():
        _write_new(summary_path, summary)
    elif json.loads(summary_path.read_text()) != summary:
        raise ValueError("existing run summary differs from resumed checkpoints")
    return summary


def main() -> int:
    """Run the explicit header preparation CLI.

    Parameters
    ----------
    None

    Returns
    -------
    int
        Process status, zero when the preparation command completed.

    Raises
    ------
    SystemExit
        If CLI arguments are invalid or a run is held by changed inputs.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--resume", action="store_true")
    arguments = parser.parse_args()
    summary = prepare_headers(
        arguments.request, arguments.output_dir, resume=arguments.resume
    )
    print(json.dumps(summary, sort_keys=True, separators=(",", ":")))
    return 0 if summary["preparation_complete"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
