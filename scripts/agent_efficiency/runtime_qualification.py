"""Qualify the pinned serving image before any billable agent request.

Parameters
----------
None

Returns
-------
None
    Immutable offline image receipts separate from investigated fixture source.
"""
# ruff: noqa: EM101, TRY003

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import cast

from codira.runtime_identity import runtime_identity

PROJECT_TEMP = Path("/home/marco/Personalia/Progetti/.Temp")


def qualify_image(runtime: str, image: str, evidence_root: Path) -> dict[str, object]:
    """Run isolated installed-product probes and retain their complete receipt.

    Parameters
    ----------
    runtime : str
        Admitted container runtime.
    image : str
        Immutable serving image digest.
    evidence_root : pathlib.Path
        Durable campaign state directory, separate from agent fixture source.

    Returns
    -------
    dict[str, object]
        Qualified image identity and actual registered schema evidence.

    Raises
    ------
    ValueError
        If qualification fails or a retained receipt has another identity.
    """
    installed = runtime_identity()
    expected = installed["source_sha256"]
    profile = Path("scripts/agent_efficiency/benchmark-codira.toml")
    profile_hash = hashlib.sha256(profile.read_bytes()).hexdigest()
    receipt_path = evidence_root / "runtime-qualification.json"
    if receipt_path.exists():
        receipt = cast("dict[str, object]", json.loads(receipt_path.read_text()))
        if (
            receipt.get("image") != image
            or cast("dict[str, object]", receipt.get("runtime", {})).get(
                "source_sha256"
            )
            != expected
            or cast("dict[str, object]", receipt.get("runtime", {})).get(
                "analyzer_sources"
            )
            != installed["analyzer_sources"]
            or receipt.get("profile_sha256") != profile_hash
        ):
            raise ValueError(
                "retained runtime receipt differs; use a fresh campaign identity"
            )
        return receipt
    evidence_root.mkdir(parents=True, exist_ok=True)
    git = shutil.which("git")
    if git is None:
        raise ValueError("Git is required for offline runtime qualification")
    with tempfile.TemporaryDirectory(
        prefix="ae-runtime-", dir=PROJECT_TEMP
    ) as temporary:
        scratch = Path(temporary)
        fixture = scratch / "fixture"
        fixture.mkdir()
        (fixture / "qualification.py").write_text(
            "class Qualification:\n    def probe(self):\n        return 42\n\ndef helper():\n    return Qualification().probe()\n"
        )
        (fixture / "other.py").write_text("def helper_two():\n    return 42\n")
        subprocess.run(
            (git, "init", "--quiet", str(fixture)), check=True, capture_output=True
        )
        subprocess.run(
            (git, "-C", str(fixture), "add", "--all"),
            check=True,
            capture_output=True,
        )
        completed = subprocess.run(
            (
                runtime,
                "run",
                "--rm",
                "--network=none",
                "--read-only",
                "--cap-drop=ALL",
                "--security-opt=no-new-privileges",
                "--pids-limit=512",
                f"--mount=type=bind,src={fixture},dst=/workspace,rw",
                f"--mount=type=bind,src={scratch},dst=/temporary,rw",
                "--workdir=/workspace",
                image,
                "python",
                "/opt/codira/runtime_admission.py",
                "--root",
                "/workspace",
                "--query",
                "Qualification probe helper",
                "--expected-core-sha256",
                str(expected),
            ),
            check=False,
            capture_output=True,
            text=True,
            timeout=180,
        )
    (evidence_root / "runtime-qualification.stdout").write_text(completed.stdout)
    (evidence_root / "runtime-qualification.stderr").write_text(completed.stderr)
    if completed.returncode != 0:
        raise ValueError(
            "installed runtime qualification failed; inspect retained offline trace"
        )
    receipt = cast("dict[str, object]", json.loads(completed.stdout))
    if (
        cast("dict[str, object]", receipt.get("runtime", {})).get("source_sha256")
        != expected
        or cast("dict[str, object]", receipt.get("runtime", {})).get("analyzer_sources")
        != installed["analyzer_sources"]
        or receipt.get("profile_sha256") != profile_hash
    ):
        raise ValueError(
            "installed runtime does not match approved serving source and profile"
        )
    receipt["image"] = image
    with receipt_path.open("x") as handle:
        json.dump(receipt, handle, sort_keys=True, indent=2)
        handle.write("\n")
    return receipt
