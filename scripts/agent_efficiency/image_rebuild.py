"""Preserve credential-free image recipes without retaining container layers.

Parameters
----------
None

Returns
-------
None
    Helpers for durable build contexts and verified reconstruction.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import tarfile
from pathlib import Path
from typing import TYPE_CHECKING

from scripts.agent_efficiency import phase0

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

REBUILD_ROOT = Path(".artifacts/agent-efficiency/image-rebuilds")
INVENTORY_PROGRAM = Path(__file__).with_name("image_rebuild_inventory.py")


def record_path(tag: str) -> Path:
    """Return the default durable record path for a fresh image tag.

    Parameters
    ----------
    tag : str
        New image tag, including its local repository name.

    Returns
    -------
    pathlib.Path
        Readable path with a hash suffix preventing sanitized-name collisions.
    """
    name = re.sub(r"[^a-zA-Z0-9_.-]", "_", tag)[:100]
    return REBUILD_ROOT / f"{name}-{hashlib.sha256(tag.encode()).hexdigest()[:12]}"


def file_sha256(path: Path) -> str:
    """Hash a retained file without loading its complete contents into memory.

    Parameters
    ----------
    path : pathlib.Path
        Regular file to fingerprint.

    Returns
    -------
    str
        Lowercase SHA-256 digest.
    """
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def write_document(path: Path, document: Mapping[str, object]) -> None:
    """Atomically replace a document inside a newly owned rebuild record.

    Parameters
    ----------
    path : pathlib.Path
        Destination in a record owned by the current operation.
    document : collections.abc.Mapping[str, object]
        Credential-free reconstruction metadata.

    Returns
    -------
    None
        The previous document is replaced only after the new content is written.
    """
    temporary = path.with_suffix(".new")
    with temporary.open("x", encoding="utf-8") as handle:
        handle.write(json.dumps(document, indent=2, sort_keys=True) + "\n")
    temporary.replace(path)


def preserve_context(
    context: Path, destination: Path, build_arguments: Sequence[str]
) -> dict[str, object]:
    """Archive exact generated inputs before starting a network-enabled build.

    Parameters
    ----------
    context : pathlib.Path
        Curated, credential-free context produced by the benchmark builder.
    destination : pathlib.Path
        Fresh durable record directory; existing records are never overwritten.
    build_arguments : collections.abc.Sequence[str]
        Build options without the runtime executable or disposable context path.

    Returns
    -------
    dict[str, object]
        Prepared record with a verified archive digest and explicit limitations.

    Raises
    ------
    FileExistsError
        If the destination already exists.
    ValueError
        If context links escape the context or contain unsupported file types.
    """
    root = context.resolve()
    for path in context.rglob("*"):
        if path.is_symlink():
            if not path.resolve().is_relative_to(root):
                message = "image context contains an external symlink"
                raise ValueError(message)
        elif not (path.is_file() or path.is_dir()):
            message = "image context contains an unsupported file type"
            raise ValueError(message)
    destination.mkdir(parents=True, mode=0o700, exist_ok=False)
    archive = destination / "context.tar.gz"
    with tarfile.open(archive, "x:gz", dereference=False, compresslevel=1) as handle:
        handle.add(context, arcname="context")
    (destination / "Containerfile").write_bytes(
        (context / "Containerfile").read_bytes()
    )
    record: dict[str, object] = {
        "schema_version": 1,
        "policy": "recipe-only",
        "status": "prepared",
        "exact_image_recovery": False,
        "build_arguments": list(build_arguments),
        "files": {
            name: file_sha256(destination / name)
            for name in ("context.tar.gz", "Containerfile")
        },
        "limitations": [
            "Rebuilding can produce a different image digest and dependency resolution.",
            "Parent images must remain retrievable or have their own rebuild records.",
            "External package repositories and binary downloads must remain available.",
            "Historical campaign digests must never be replaced by a rebuilt digest.",
        ],
    }
    write_document(destination / "record.json", record)
    return record


def capture_inventory(runtime: str, image: str, destination: Path) -> Path:
    """Record installed versions and generated locks without caches or secrets.

    Parameters
    ----------
    runtime : str
        Supported container executable.
    image : str
        Immutable image reference or local image ID selected by the caller.
    destination : pathlib.Path
        Existing owned reconstruction-record directory.

    Returns
    -------
    pathlib.Path
        Inventory containing package versions and embedded npm lockfiles.

    Raises
    ------
    ValueError
        If the runtime is unsupported or the inventory shape is invalid.
    TypeError
        If the inventory is not a JSON object.
    subprocess.CalledProcessError
        If the read-only, network-disabled inspection fails.
    """
    if runtime not in phase0.SUPPORTED_CONTAINER_RUNTIMES:
        message = "unsupported reconstruction runtime"
        raise ValueError(message)
    completed = subprocess.run(
        (
            runtime,
            "run",
            "--rm",
            "--network=none",
            "--read-only",
            "--cap-drop=ALL",
            "--security-opt=no-new-privileges",
            "--user=0",
            "--entrypoint=python",
            image,
            "-c",
            INVENTORY_PROGRAM.read_text(encoding="utf-8"),
        ),
        check=True,
        capture_output=True,
        text=True,
    )
    document = json.loads(completed.stdout)
    if not isinstance(document, dict):
        message = "image reconstruction inventory must be an object"
        raise TypeError(message)
    path = destination / "inventory.json"
    write_document(path, document)
    return path


def verified_record(source: Path) -> dict[str, object]:
    """Load a supported record after checking every retained payload checksum.

    Parameters
    ----------
    source : pathlib.Path
        Durable reconstruction-record directory.

    Returns
    -------
    dict[str, object]
        Validated recipe metadata; successful rebuilding is not implied.

    Raises
    ------
    ValueError
        If metadata, payload paths, or checksums are invalid.
    """
    document = json.loads((source / "record.json").read_text(encoding="utf-8"))
    if not isinstance(document, dict) or document.get("schema_version") != 1:
        message = "unsupported image reconstruction record"
        raise ValueError(message)
    files = document.get("files")
    if (
        not isinstance(files, dict)
        or not {"context.tar.gz", "Containerfile"} <= files.keys()
    ):
        message = "image reconstruction payloads are missing"
        raise ValueError(message)
    for name, expected in files.items():
        if not isinstance(name, str) or Path(name).name != name:
            message = "invalid image reconstruction payload path"
            raise ValueError(message)
        path = source / name
        if path.is_symlink() or file_sha256(path) != expected:
            message = "image reconstruction payload checksum mismatch"
            raise ValueError(message)
    return document


def restore_context(source: Path, destination: Path) -> Path:
    """Restore a verified recipe into fresh disposable storage.

    Parameters
    ----------
    source : pathlib.Path
        Supported record with intact retained payloads.
    destination : pathlib.Path
        Absent scratch directory for the archived context.

    Returns
    -------
    pathlib.Path
        Extracted build context with its original Containerfile.

    Raises
    ------
    ValueError
        If archive contents do not match the retained recipe.
    tarfile.FilterError
        If archive members escape the destination or contain unsafe file types.
    """
    verified_record(source)
    destination.mkdir(parents=True, exist_ok=False)
    with tarfile.open(source / "context.tar.gz", "r:gz") as handle:
        handle.extractall(destination, filter="data")
    context = destination / "context"
    if (context / "Containerfile").read_bytes() != (
        source / "Containerfile"
    ).read_bytes():
        message = "restored Containerfile differs from the retained recipe"
        raise ValueError(message)
    return context
