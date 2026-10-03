"""Bind preparation evidence and reject incomplete or stale campaign readiness.

Parameters
----------
None

Returns
-------
None
    Receipts are local immutable admission evidence, never model results.
"""
# ruff: noqa: EM101, EM102, TRY003

from __future__ import annotations

import hashlib
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import TYPE_CHECKING

from codira.runtime_identity import runtime_identity
from scripts.agent_efficiency.contracts import canonical_fingerprint
from scripts.agent_efficiency.full_campaign import harness_fingerprint
from scripts.agent_efficiency.runner import PROJECT_TEMP_ROOT

if TYPE_CHECKING:
    from scripts.launch_agent_efficiency_pilot import PilotLaunch

READINESS_VERSION = "1.0"
MAX_READINESS_AGE_SECONDS = 15 * 60
REQUIRED_CHECKS = frozenset(
    {
        "host-context",
        "factory-inputs",
        "image-runtime",
        "fixture-freshness",
        "native-tool-dispatch",
        "model-requested-mcp",
        "rubric-calibration",
        "complete-patch-pipeline",
        "repository-gate",
        "authenticated-route",
        "authenticated-route-after-canary",
    }
)


def file_digest(path: Path) -> str:
    """Digest one non-secret evidence or executable file.

    Parameters
    ----------
    path : pathlib.Path
        Existing non-secret file.

    Returns
    -------
    str
        SHA-256 digest.
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validation_identity() -> str:
    """Fingerprint tracked and new source inputs covered by the repository gate.

    Parameters
    ----------
    None

    Returns
    -------
    str
        Identity of Git-visible repository files, excluding generated state.
    """
    result = subprocess.run(
        [
            shutil.which("git") or "/usr/bin/git",
            "ls-files",
            "-z",
            "--cached",
            "--others",
            "--exclude-standard",
        ],
        check=True,
        capture_output=True,
    )
    files = {Path(os.fsdecode(name)) for name in result.stdout.split(b"\0") if name}
    return canonical_fingerprint(
        {str(path): file_digest(path) for path in sorted(files) if path.is_file()}
    )


def readiness_identity(launch: PilotLaunch) -> dict[str, object]:
    """Resolve every launch binding and current qualification dependency.

    Parameters
    ----------
    launch : PilotLaunch
        Factory-validated campaign and local execution bindings.

    Returns
    -------
    dict[str, object]
        Complete local identity; managed credential bytes are never read.

    Raises
    ------
    ValueError
        If the required preparation boundary fails.
    """
    from scripts.launch_agent_efficiency_pilot import _receipt

    runtime_path = shutil.which(launch.runtime)
    tmux_path = shutil.which("tmux")
    if runtime_path is None or tmux_path is None:
        raise ValueError("container runtime or tmux executable is missing")
    return {
        "launch": _receipt(launch),
        "repository": str(Path.cwd().resolve()),
        "validation_inputs": validation_identity(),
        "harness": harness_fingerprint(),
        "product": runtime_identity(),
        "python": str(Path(sys.executable).absolute()),
        "python_sha256": file_digest(Path(sys.executable)),
        "runtime_executable": str(Path(runtime_path).resolve()),
        "runtime_sha256": file_digest(Path(runtime_path)),
        "tmux_executable": str(Path(tmux_path).resolve()),
        "tmux_sha256": file_digest(Path(tmux_path)),
        "uid": os.getuid(),
        "environment": {
            name: os.environ.get(name, "")
            for name in ("PYTHONPATH", "PATH", "XDG_RUNTIME_DIR")
        },
    }


def write_evidence(path: Path, document: dict[str, object]) -> None:
    """Create immutable private JSON evidence without replacement.

    Parameters
    ----------
    path : pathlib.Path
        Absent durable destination.
    document : dict[str, object]
        Non-secret local evidence.

    Returns
    -------
    None
        An existing receipt cannot be replaced.
    """
    with path.open("x", encoding="utf-8") as handle:
        json.dump(document, handle, sort_keys=True, indent=2)
        handle.write("\n")
    path.chmod(0o600)


def publish_readiness(
    launch: PilotLaunch,
    identity: dict[str, object],
    checks: dict[str, object],
    *,
    authenticated_at: float,
) -> Path:
    """Publish readiness only after all checks and stable identities pass.

    Parameters
    ----------
    launch : PilotLaunch
        Campaign whose execution root holds preparation evidence.
    identity : dict[str, object]
        Identity captured before qualification.
    checks : dict[str, object]
        Exact required checks with immutable evidence paths and digests.
    authenticated_at : float
        Time of successful authenticated route admission.

    Returns
    -------
    pathlib.Path
        Newly created launch-enforced readiness receipt.

    Raises
    ------
    ValueError
        If a check is missing, failed, stale or dependencies changed.
    """
    if identity != readiness_identity(launch):
        raise ValueError("preparation inputs changed during qualification")
    root = launch.execution_root
    receipt: dict[str, object] = {
        "schema_version": READINESS_VERSION,
        "status": "ready",
        "identity": identity,
        "checks": checks,
        "authenticated_at": authenticated_at,
        "created_at": time.time(),
    }
    _validate_checks(root, receipt)
    receipt["receipt_fingerprint"] = canonical_fingerprint(receipt)
    path = root / "readiness-receipt.json"
    write_evidence(path, receipt)
    return path


def _validate_checks(root: Path, receipt: dict[str, object]) -> None:
    """Reject absent, failed, altered or expired preparation evidence.

    Parameters
    ----------
    root : pathlib.Path
        Durable execution root.
    receipt : dict[str, object]
        Parsed readiness payload.

    Returns
    -------
    None
        Success requires all required evidence to match its digest.

    Raises
    ------
    ValueError
        If the required preparation boundary fails.
    """
    checks = receipt.get("checks")
    if not isinstance(checks, dict) or set(checks) != REQUIRED_CHECKS:
        raise ValueError("readiness checks are missing or unknown")
    timestamp = receipt.get("authenticated_at")
    if (
        not isinstance(timestamp, (int, float))
        or isinstance(timestamp, bool)
        or not 0 <= time.time() - timestamp <= MAX_READINESS_AGE_SECONDS
    ):
        raise ValueError("authenticated readiness is stale or has an invalid timestamp")
    for name, check in checks.items():
        if not isinstance(check, dict) or check.get("status") != "passed":
            raise ValueError(f"readiness check failed: {name}")
        evidence = check.get("evidence")
        if not isinstance(evidence, dict) or not evidence:
            raise ValueError(f"readiness evidence is missing: {name}")
        for relative, digest in evidence.items():
            path = root / str(relative)
            if root.resolve() not in path.resolve().parents or not path.is_file():
                raise ValueError(f"readiness evidence is unavailable: {name}")
            if file_digest(path) != digest:
                raise ValueError(f"readiness evidence changed: {name}")


def verify_readiness(launch: PilotLaunch) -> Path:
    """Enforce readiness at launch and inside the generated tmux child.

    Parameters
    ----------
    launch : PilotLaunch
        Current resolved local campaign inputs.

    Returns
    -------
    pathlib.Path
        Immutable valid readiness receipt.

    Raises
    ------
    ValueError
        If the receipt or its evidence, controls, code or time is invalid.
    """
    path = launch.execution_root / "readiness-receipt.json"
    try:
        receipt = json.loads(path.read_text())
    except (OSError, ValueError) as error:
        raise ValueError("machine-validated readiness receipt is required") from error
    if not isinstance(receipt, dict):
        raise TypeError("readiness receipt is malformed")
    fingerprint = receipt.pop("receipt_fingerprint", None)
    if (
        receipt.get("schema_version") != READINESS_VERSION
        or receipt.get("status") != "ready"
        or fingerprint != canonical_fingerprint(receipt)
        or receipt.get("identity") != readiness_identity(launch)
    ):
        raise ValueError("readiness receipt or dependencies are stale")
    _validate_checks(launch.execution_root, receipt)
    return path


def qualify_host_context(runtime: str) -> dict[str, object]:
    """Fail early on host-only requirements before invoking runtime tools.

    Parameters
    ----------
    runtime : str
        Container runtime command.

    Returns
    -------
    dict[str, object]
        Host runtime, tmux and short writable socket observations.

    Raises
    ------
    ValueError
        If the preparation process is in an incompatible outer sandbox.
    """
    runtime_root = Path(os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}"))
    if runtime_root.exists() and os.statvfs(runtime_root).f_flag & os.ST_RDONLY:
        raise ValueError(
            "host execution required: rootless runtime directory is read-only"
        )
    if any(shutil.which(tool) is None for tool in (runtime, "tmux", "git")):
        raise ValueError("required host runtime, tmux or Git is missing")
    PROJECT_TEMP_ROOT.mkdir(parents=True, exist_ok=True)
    with (
        tempfile.TemporaryDirectory(
            prefix="ae-host-", dir=PROJECT_TEMP_ROOT
        ) as temporary,
        socket.socket(socket.AF_UNIX) as listener,
    ):
        listener.bind(str(Path(temporary) / "p.sock"))
    for command in (
        [runtime, "info", "--format", "json"],
        ["tmux", "display-message", "-p", "#{pid}"],
    ):
        result = subprocess.run(command, check=False, capture_output=True, timeout=30)
        if result.returncode != 0:
            raise ValueError("host execution required: runtime or tmux access failed")
    return {
        "status": "passed",
        "execution_context": "authorized-host",
        "uid": os.getuid(),
        "runtime": runtime,
        "short_socket": "passed",
    }


def evidence_check(root: Path, directory: Path) -> dict[str, object]:
    """Bind a completed check to every non-secret evidence file it produced.

    Parameters
    ----------
    root : pathlib.Path
        Execution root.
    directory : pathlib.Path
        Completed check directory.

    Returns
    -------
    dict[str, object]
        Passed check with complete relative evidence digests.

    Raises
    ------
    ValueError
        If the required preparation boundary fails.
    """
    evidence = {
        str(path.relative_to(root)): file_digest(path)
        for path in sorted(directory.rglob("*"))
        if path.is_file()
    }
    if not evidence:
        raise ValueError("completed preparation check produced no evidence")
    return {"status": "passed", "evidence": evidence}
