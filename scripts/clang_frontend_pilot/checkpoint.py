"""Retain immutable qualification attempts and verify reusable results.

Parameters
----------
None

Returns
-------
None

Notes
-----
Only completed or held rows with a matching identity and intact output bytes
can be skipped. Failed and incomplete attempts remain in history and are never
treated as successful measurements.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Mapping
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

_REUSABLE_STATUSES = {"complete", "held"}


def output_sha256(path: Path) -> str:
    """Hash an immutable result artifact.

    Parameters
    ----------
    path : pathlib.Path
        Result artifact path.

    Returns
    -------
    str
        Lowercase SHA-256 digest of the complete file.

    Raises
    ------
    OSError
        If the artifact cannot be read.
    """

    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def can_skip_attempt(
    attempt: Mapping[str, object],
    identity_sha256: str,
    artifact_root: Path,
) -> bool:
    """Check whether a prior attempt is complete, identical, and intact.

    Parameters
    ----------
    attempt : Mapping[str, object]
        Checkpoint record containing identity, status, artifact path, and digest.
    identity_sha256 : str
        Current source/profile/dependency/compiler/producer/config identity.
    artifact_root : pathlib.Path
        Directory against which the recorded relative artifact path is resolved.

    Returns
    -------
    bool
        True only for an intact completed or held artifact with matching input
        identity. Failed, partial, or incomplete results are retained for
        analysis but never qualify for reuse.
    """

    if attempt.get("status") not in _REUSABLE_STATUSES:
        return False
    if attempt.get("identity_sha256") != identity_sha256:
        return False
    artifact_relpath = attempt.get("artifact_relpath")
    artifact_digest = attempt.get("artifact_sha256")
    if not isinstance(artifact_relpath, str) or not isinstance(artifact_digest, str):
        return False
    artifact = (artifact_root / artifact_relpath).resolve()
    if not artifact.is_relative_to(artifact_root.resolve()) or not artifact.is_file():
        return False
    try:
        return output_sha256(artifact) == artifact_digest
    except OSError:
        return False


def append_attempt(
    checkpoint: Mapping[str, object],
    selection_id: str,
    attempt: Mapping[str, object],
) -> dict[str, object]:
    """Return checkpoint state with one attempt appended without discarding history.

    Parameters
    ----------
    checkpoint : Mapping[str, object]
        Existing versioned checkpoint state.
    selection_id : str
        Stable cohort row identity.
    attempt : Mapping[str, object]
        New immutable attempt record.

    Returns
    -------
    dict[str, object]
        Copy of checkpoint with the new attempt appended to its row history.

    Raises
    ------
    ValueError
        If the attempt lacks a status, identity, artifact path, or artifact digest.
    """

    required = ("status", "identity_sha256", "artifact_relpath", "artifact_sha256")
    if any(
        not isinstance(attempt.get(key), str) or not attempt.get(key)
        for key in required
    ):
        message = (
            "attempt requires status, identity, artifact path, and artifact digest"
        )
        raise ValueError(message)
    result = dict(checkpoint)
    raw_rows = checkpoint.get("rows")
    rows = dict(raw_rows) if isinstance(raw_rows, Mapping) else {}
    raw_history = rows.get(selection_id)
    history = list(raw_history) if isinstance(raw_history, list) else []
    history.append(dict(attempt))
    rows[selection_id] = history
    result["schema_version"] = "codira.clang-frontend-pilot-checkpoint/1"
    result["rows"] = rows
    return result


def write_checkpoint(path: Path, checkpoint: Mapping[str, object]) -> None:
    """Atomically persist checkpoint state while retaining the previous file on failure.

    Parameters
    ----------
    path : pathlib.Path
        Durable checkpoint JSON path.
    checkpoint : Mapping[str, object]
        Complete checkpoint state to serialize.

    Returns
    -------
    None

    Raises
    ------
    OSError
        If the checkpoint cannot be written or atomically replaced.
    TypeError
        If the checkpoint contains values that JSON cannot serialize.
    """

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    payload = json.dumps(checkpoint, sort_keys=True, indent=2).encode("utf-8") + b"\n"
    try:
        with temporary.open("wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
