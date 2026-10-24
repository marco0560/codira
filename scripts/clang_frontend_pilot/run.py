"""Run or resume a source-bound Clang frontend pilot cohort."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import uuid
from pathlib import Path
from typing import cast

from .adapter import adapt_selection, sha256_file
from .contract import (
    CAPTURE_MODES,
    DEFAULT_CAPTURE_MODE,
    PILOT_ID,
    SCHEMA_VERSION,
    JSONValue,
    raise_input_error,
)


def _read_json(path: Path) -> object:
    """Read one UTF-8 JSON file.

    Parameters
    ----------
    path : pathlib.Path
        JSON file path.

    Returns
    -------
    object
        Decoded JSON value.
    """
    return json.loads(path.read_text(encoding="utf-8"))


def _object(value: object, label: str) -> dict[str, JSONValue]:
    """Validate a JSON object.

    Parameters
    ----------
    value : object
        Value to validate.
    label : str
        Human-readable object name for errors.

    Returns
    -------
    dict[str, JSONValue]
        Validated JSON object.

    Raises
    ------
    ValueError
        If ``value`` is not a JSON object with string keys.
    """
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise_input_error(f"{label} must be a JSON object")
    return cast("dict[str, JSONValue]", value)


def _atomic_write(path: Path, content: bytes) -> None:
    """Atomically replace a derived checkpoint or NDJSON view.

    Parameters
    ----------
    path : pathlib.Path
        Target file path.
    content : bytes
        Exact new file contents.

    Returns
    -------
    None
        This function writes the requested artifact.

    Raises
    ------
    OSError
        If the temporary or target file cannot be written.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    with temporary.open("xb") as stream:
        stream.write(content)
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


def _write_new(path: Path, content: bytes) -> None:
    """Create an immutable evidence record without replacing prior evidence.

    Parameters
    ----------
    path : pathlib.Path
        New record path.
    content : bytes
        JSON bytes to persist.

    Returns
    -------
    None
        This function persists the immutable record.

    Raises
    ------
    FileExistsError
        If the record path already exists.
    OSError
        If the record cannot be written.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(content)
        stream.flush()
        os.fsync(stream.fileno())


def _canonical_hash(value: JSONValue) -> str:
    """Hash a JSON value using sorted, compact UTF-8 serialization.

    Parameters
    ----------
    value : JSONValue
        JSON-compatible value.

    Returns
    -------
    str
        Lowercase hexadecimal SHA-256 digest.
    """
    payload = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _verify_record(  # noqa: C901, PLR0912
    record: dict[str, JSONValue],
    helper: Path,
    receipt: Path,
    producer_sha: str,
    manifest_sha: str,
) -> None:
    """Revalidate persisted source, dependencies, and toolchain before reuse.

    Parameters
    ----------
    record : dict[str, JSONValue]
        Previously produced terminal envelope.
    helper : pathlib.Path
        Current helper executable path.
    receipt : pathlib.Path
        Current compiler/helper build receipt.
    producer_sha : str
        Current adapter/configuration source identity.
    manifest_sha : str
        Current cohort manifest digest.

    Returns
    -------
    None
        This function returns only after every available identity is current.

    Raises
    ------
    ValueError
        If any persisted identity no longer matches its source or binary.
    OSError
        If an identity file cannot be read.
    """
    if record.get("producer_config_sha256") != producer_sha:
        raise_input_error(
            f"producer configuration changed for {record.get('selection_id')}"
        )
    manifest_source = record.get("manifest_source")
    if (
        not isinstance(manifest_source, dict)
        or manifest_source.get("sha256") != manifest_sha
    ):
        raise_input_error("retained envelope manifest identity differs")
    for key in ("raw_stdout", "raw_stderr"):
        artifact = record.get(key)
        if isinstance(artifact, dict):
            artifact_path = artifact.get("path")
            artifact_digest = artifact.get("sha256")
            if isinstance(artifact_path, str) and isinstance(artifact_digest, str):
                path = Path(artifact_path)
                if not path.is_file() or sha256_file(path) != artifact_digest:
                    raise_input_error(f"raw helper evidence changed or missing: {path}")
    source_path = record.get("source_path")
    source_digest = record.get("source_sha256")
    if (
        isinstance(source_path, str)
        and isinstance(source_digest, str)
        and (
            not Path(source_path).is_file()
            or sha256_file(Path(source_path)) != source_digest
        )
    ):
        raise_input_error(f"source identity changed for {record.get('selection_id')}")
    closure = record.get("dependency_closure")
    if isinstance(closure, dict):
        files = closure.get("files")
        if isinstance(files, list):
            for dependency in files:
                if not isinstance(dependency, dict):
                    raise_input_error("malformed dependency record in checkpoint")
                dependency_path_value = dependency.get("path")
                digest = dependency.get("sha256")
                if isinstance(dependency_path_value, str) and isinstance(digest, str):
                    dependency_path = Path(dependency_path_value)
                    if (
                        not dependency_path.is_file()
                        or sha256_file(dependency_path) != digest
                    ):
                        raise_input_error(
                            f"dependency identity changed: {dependency_path_value}"
                        )
    original = record.get("original_compile_command")
    if isinstance(original, dict):
        driver = original.get("driver")
        if isinstance(driver, dict):
            driver_path_value = driver.get("resolved_path")
            digest = driver.get("binary_sha256")
            if (
                isinstance(driver_path_value, str)
                and isinstance(digest, str)
                and (
                    not Path(driver_path_value).is_file()
                    or sha256_file(Path(driver_path_value)) != digest
                )
            ):
                raise_input_error(
                    f"original compiler binary identity changed: {driver_path_value}"
                )
    adaptation = record.get("clang_adaptation")
    if isinstance(adaptation, dict):
        toolchain = adaptation.get("toolchain")
        if isinstance(toolchain, dict):
            compiler_path = toolchain.get("compiler_path")
            compiler_digest = toolchain.get("compiler_sha256")
            if (
                isinstance(compiler_path, str)
                and isinstance(compiler_digest, str)
                and (
                    not Path(compiler_path).is_file()
                    or sha256_file(Path(compiler_path)) != compiler_digest
                )
            ):
                raise_input_error(
                    f"Clang compiler binary identity changed: {compiler_path}"
                )
            helper_path = toolchain.get("helper_path")
            helper_digest = toolchain.get("helper_sha256")
            if (
                isinstance(helper_path, str)
                and isinstance(helper_digest, str)
                and (
                    Path(helper_path).resolve() != helper.resolve()
                    or sha256_file(helper) != helper_digest
                )
            ):
                raise_input_error("LibTooling helper identity changed")
            receipt_path = toolchain.get("build_receipt_path")
            receipt_digest = toolchain.get("build_receipt_sha256")
            if (
                isinstance(receipt_path, str)
                and isinstance(receipt_digest, str)
                and (
                    Path(receipt_path).resolve() != receipt.resolve()
                    or sha256_file(receipt) != receipt_digest
                )
            ):
                raise_input_error("compiler/helper build receipt identity changed")


def _materialize_output(path: Path, ordered_records: list[dict[str, JSONValue]]) -> str:
    """Write the deterministic NDJSON view and return its SHA-256 digest.

    Parameters
    ----------
    path : pathlib.Path
        Output NDJSON path.
    ordered_records : list[dict[str, JSONValue]]
        Envelopes in cohort manifest order.

    Returns
    -------
    str
        Digest of the materialized bytes.
    """
    payload = b"".join(
        json.dumps(record, sort_keys=True, separators=(",", ":")).encode("utf-8")
        + b"\n"
        for record in ordered_records
    )
    _atomic_write(path, payload)
    return hashlib.sha256(payload).hexdigest()


def run_batch(  # noqa: C901, PLR0913, PLR0912
    manifest_path: Path,
    compile_commands_path: Path,
    repository_root: Path,
    helper_path: Path,
    output_path: Path,
    checkpoint_path: Path,
    selection_id: str | None = None,
    capture_mode: str = DEFAULT_CAPTURE_MODE,
) -> dict[str, JSONValue]:
    """Run selected manifest rows and checkpoint one immutable result per row.

    Parameters
    ----------
    manifest_path : pathlib.Path
        Versioned cohort manifest.
    compile_commands_path : pathlib.Path
        Repository compilation database JSON file.
    repository_root : pathlib.Path
        Checkout corresponding to the selected repository rows.
    helper_path : pathlib.Path
        Explicit LibTooling helper executable.
    output_path : pathlib.Path
        Durable NDJSON materialized view.
    checkpoint_path : pathlib.Path
        Durable checkpoint bound to all input and producer identities.
    selection_id : str or None, optional
        Restrict processing to exactly one row when supplied.
    capture_mode : str, optional
        Projection scope (`source_relevant` or legacy-compatible `full`).

    Returns
    -------
    dict[str, JSONValue]
        Batch summary with counts and bound input hashes.

    Raises
    ------
    FileExistsError
        If only one of the output/checkpoint identity pair exists.
    ValueError
        If inputs are malformed, differ from a resume identity, or any retained
        source/dependency/toolchain binding has changed.
    OSError
        If an input or artifact cannot be read or written.
    """
    if capture_mode not in CAPTURE_MODES:
        raise_input_error(f"unsupported capture mode: {capture_mode}")
    manifest = _object(_read_json(manifest_path), "manifest")
    if manifest.get("schema_version") != "codira.clang-frontend-pilot-cohort/1":
        raise_input_error("unsupported cohort manifest schema")
    rows_value = manifest.get("rows")
    if not isinstance(rows_value, list):
        raise_input_error("cohort manifest rows must be an array")
    rows = [_object(value, "cohort row") for value in rows_value]
    identities = [row.get("selection_id") for row in rows]
    if any(not isinstance(value, str) or not value for value in identities):
        raise_input_error("every cohort row requires a selection_id")
    if len(set(identities)) != len(identities):
        raise_input_error("selection_id values must be unique")
    repositories = manifest.get("repositories")
    if not isinstance(repositories, dict):
        raise_input_error(
            "manifest repositories must map repository IDs to checkout identities"
        )
    repository = repository_root.resolve()
    if selection_id is None:
        selected = []
        for row in rows:
            repository_id = row.get("repository_id")
            if not isinstance(repository_id, str):
                continue
            repository_value = repositories.get(repository_id)
            if isinstance(repository_value, dict):
                checkout = repository_value.get("checkout")
                if isinstance(checkout, str) and Path(checkout).resolve() == repository:
                    selected.append(row)
    else:
        selected = [row for row in rows if row.get("selection_id") == selection_id]
    if selection_id is not None and len(selected) != 1:
        raise_input_error(f"selection_id is absent or ambiguous: {selection_id}")
    if not selected:
        raise_input_error(
            f"manifest has no selections for repository root {repository}"
        )
    if compile_commands_path.is_file():
        database_value = _read_json(compile_commands_path)
        if not isinstance(database_value, list):
            raise_input_error("compile_commands.json must be a JSON array")
        database = [_object(value, "compile command") for value in database_value]
        database_sha: str | None = sha256_file(compile_commands_path)
    else:
        database = []
        database_sha = None
    for index, command in enumerate(database):
        command["database_file"] = str(compile_commands_path.resolve())
        command["database_path"] = str(compile_commands_path.resolve())
        command["database_sha256"] = database_sha
        command["command_index"] = index
    helper = helper_path.resolve()
    receipt_path = helper.with_name(helper.name + ".build.json")
    if output_path.resolve() == checkpoint_path.resolve():
        raise_input_error("output and checkpoint paths must be different")
    protected_paths = {
        manifest_path.resolve(),
        compile_commands_path.resolve(),
        helper,
        receipt_path,
    }
    if (
        output_path.resolve() in protected_paths
        or checkpoint_path.resolve() in protected_paths
    ):
        raise_input_error(
            "output and checkpoint paths must not replace an input or toolchain artifact"
        )
    receipt_sha = sha256_file(receipt_path) if receipt_path.is_file() else None
    helper_sha = sha256_file(helper) if helper.is_file() else None
    code_sources = [
        Path(__file__),
        Path(__file__).with_name("adapter.py"),
        Path(__file__).with_name("contract.py"),
    ]
    producer_sha = _canonical_hash([sha256_file(path) for path in code_sources])
    manifest_sha = sha256_file(manifest_path)
    repository_holds: dict[str, str] = {}
    revision_cache: dict[str, str | None] = {}
    for row in selected:
        repository_id = row.get("repository_id")
        pinned_revision = row.get("repository_revision")
        if not isinstance(repository_id, str) or not isinstance(pinned_revision, str):
            raise_input_error("selection row lacks repository ID or pinned revision")
        repository_record = _object(
            repositories.get(repository_id), f"repository {repository_id}"
        )
        checkout_value = repository_record.get("checkout")
        if (
            not isinstance(checkout_value, str)
            or Path(checkout_value).resolve() != repository
        ):
            repository_holds[str(row["selection_id"])] = "repository_root_mismatch"
            continue
        if str(repository) not in revision_cache:
            git_executable = shutil.which("git")
            revision = subprocess.run(
                [git_executable or "git", "-C", str(repository), "rev-parse", "HEAD"],
                capture_output=True,
                text=True,
                check=False,
                shell=False,
            )
            revision_cache[str(repository)] = (
                revision.stdout.strip()
                if git_executable is not None and revision.returncode == 0
                else None
            )
        if revision_cache[str(repository)] != pinned_revision:
            repository_holds[str(row["selection_id"])] = "repository_revision_mismatch"
    input_binding: dict[str, JSONValue] = {
        "pilot_id": PILOT_ID,
        "manifest_path": str(manifest_path.resolve()),
        "manifest_sha256": manifest_sha,
        "compile_commands_path": str(compile_commands_path.resolve()),
        "compile_commands_sha256": database_sha,
        "repository_root": str(repository_root.resolve()),
        "helper_path": str(helper),
        "helper_sha256": helper_sha,
        "build_receipt_path": str(receipt_path),
        "build_receipt_sha256": receipt_sha,
        "producer_code_sha256": producer_sha,
        "capture_mode": capture_mode,
        "selection_ids": [str(row["selection_id"]) for row in selected],
    }
    records_dir = output_path.with_name(output_path.name + ".records")
    raw_dir = output_path.with_name(output_path.name + ".raw")
    if output_path.exists() != checkpoint_path.exists():
        message = "output and checkpoint must both exist for resume"
        raise FileExistsError(message)
    records: dict[str, dict[str, JSONValue]] = {}
    record_paths: dict[str, str] = {}
    if checkpoint_path.exists():
        checkpoint = _object(_read_json(checkpoint_path), "checkpoint")
        if checkpoint.get("input_binding") != input_binding:
            raise_input_error(
                "checkpoint input/producer identity differs; use a fresh attempt path"
            )
        checkpoint_records = checkpoint.get("records")
        if not isinstance(checkpoint_records, dict):
            raise_input_error("checkpoint records must be an object")
        for key, value in checkpoint_records.items():
            if not isinstance(value, dict):
                raise_input_error("malformed checkpoint record pointer")
            path_value = value.get("path")
            digest_value = value.get("sha256")
            if not isinstance(path_value, str) or not isinstance(digest_value, str):
                raise_input_error("malformed checkpoint record path or digest")
            record_path = Path(path_value)
            if not record_path.is_file() or sha256_file(record_path) != digest_value:
                raise_input_error(
                    f"immutable row record missing or changed: {record_path}"
                )
            record = _object(_read_json(record_path), "row envelope")
            if record.get("selection_id") != key:
                raise_input_error("checkpoint record selection identity mismatch")
            _verify_record(record, helper, receipt_path, producer_sha, manifest_sha)
            records[key] = record
            record_paths[key] = str(record_path.resolve())
    else:
        if records_dir.exists():
            # Old orphaned records are preserved; a fresh attempt uses unique names.
            pass
        initial_checkpoint_value: dict[str, JSONValue] = {
            "schema_version": "codira.clang-frontend-pilot-checkpoint/1",
            "input_binding": input_binding,
            "records": {},
        }
        _atomic_write(
            checkpoint_path,
            json.dumps(
                initial_checkpoint_value, sort_keys=True, separators=(",", ":")
            ).encode("utf-8")
            + b"\n",
        )
        _materialize_output(output_path, [])
    attempt_id = uuid.uuid4().hex
    manifest_source: dict[str, JSONValue] = {
        "path": str(manifest_path.resolve()),
        "sha256": manifest_sha,
        "schema_version": str(manifest.get("schema_version")),
        "cohort_metadata": {
            key: value
            for key, value in manifest.items()
            if key not in {"rows", "repositories"}
        },
    }
    for row in selected:
        key = str(row["selection_id"])
        if key in records:
            continue
        safe_key = hashlib.sha256(key.encode("utf-8")).hexdigest()
        stderr_path = raw_dir / f"{safe_key}.{attempt_id}.stderr"
        stdout_path = raw_dir / f"{safe_key}.{attempt_id}.stdout"
        row_manifest_source = {
            **manifest_source,
            "compile_commands_path": str(compile_commands_path.resolve()),
            "compile_commands_sha256": database_sha,
        }
        record = adapt_selection(
            row,
            row_manifest_source,
            cast("list[JSONValue]", database),
            repository_root,
            helper,
            stderr_path=stderr_path,
            stdout_path=stdout_path,
            force_hold_reason=repository_holds.get(key),
            capture_mode=capture_mode,
        )
        record["producer_config_sha256"] = producer_sha
        record_path = records_dir / f"{safe_key}.{attempt_id}.json"
        content = (
            json.dumps(record, sort_keys=True, separators=(",", ":")).encode("utf-8")
            + b"\n"
        )
        _write_new(record_path, content)
        records[key] = record
        record_paths[key] = str(record_path.resolve())
        checkpoint_record_map: dict[str, JSONValue] = {
            record_key: {
                "path": record_paths[record_key],
                "sha256": sha256_file(Path(record_paths[record_key])),
            }
            for record_key in records
        }
        checkpoint_value: dict[str, JSONValue] = {
            "schema_version": "codira.clang-frontend-pilot-checkpoint/1",
            "input_binding": input_binding,
            "records": checkpoint_record_map,
        }
        checkpoint_bytes = (
            json.dumps(checkpoint_value, sort_keys=True, separators=(",", ":")).encode(
                "utf-8"
            )
            + b"\n"
        )
        _atomic_write(checkpoint_path, checkpoint_bytes)
        ordered_records = [
            records[str(candidate["selection_id"])]
            for candidate in selected
            if str(candidate["selection_id"]) in records
        ]
        _materialize_output(output_path, ordered_records)
    ordered_records = [
        records[str(row["selection_id"])]
        for row in selected
        if str(row["selection_id"]) in records
    ]
    output_sha = _materialize_output(output_path, ordered_records)
    summary: dict[str, JSONValue] = {
        "schema_version": SCHEMA_VERSION,
        "status": "ok",
        "selected_count": len(selected),
        "completed_count": len(ordered_records),
        "complete_count": sum(
            record.get("status") == "complete" for record in ordered_records
        ),
        "partial_count": sum(
            record.get("status") == "partial" for record in ordered_records
        ),
        "held_count": sum(record.get("status") == "held" for record in ordered_records),
        "output_path": str(output_path.resolve()),
        "output_sha256": output_sha,
        "checkpoint_path": str(checkpoint_path.resolve()),
        "input_binding": input_binding,
    }
    return summary


def main() -> int:
    """Parse the runner arguments and print a concise JSON completion record.

    Parameters
    ----------
    None

    Returns
    -------
    int
        Process exit status.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--compile-commands", type=Path, required=True)
    parser.add_argument("--repository-root", type=Path, required=True)
    parser.add_argument("--helper", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--selection-id")
    parser.add_argument(
        "--capture-mode",
        choices=sorted(CAPTURE_MODES),
        default=DEFAULT_CAPTURE_MODE,
        help="source-relevant default projection or legacy full record capture",
    )
    arguments = parser.parse_args()
    summary = run_batch(
        arguments.manifest,
        arguments.compile_commands,
        arguments.repository_root,
        arguments.helper,
        arguments.output,
        arguments.checkpoint,
        arguments.selection_id,
        arguments.capture_mode,
    )
    print(json.dumps(summary, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
