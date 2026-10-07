"""Replay answer examples in an isolated, credential-free offline container.

Parameters
----------
None

Returns
-------
None
    Module definitions for benchmark tooling and validation.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from scripts.agent_efficiency.temporary import PROJECT_TEMP_ROOT as PROJECT_TEMP


def replay_examples(
    answer: str, runtime: str, image: str, fixture: Path, destination: Path
) -> dict[str, object]:
    """Retain complete execution evidence for recognized fenced examples.

    Parameters
    ----------
    answer : str
        Exact answer artifact; never executed on the host.
    runtime : str
        Qualified container runtime.
    image : str
        Digest-qualified tool and dependency image.
    fixture : pathlib.Path
        Protected frozen source to copy into a disposable example workspace.
    destination : pathlib.Path
        New private durable trace directory.

    Returns
    -------
    dict[str, object]
        Per-example status, command and trace hashes. Expected-output accuracy
        remains a blinded semantic check against this actual output.
    """
    destination.mkdir(mode=0o700, parents=True, exist_ok=False)
    blocks = re.findall(
        r"^```(python|python3|javascript|js|typescript|ts|bash|sh)\s*\n(.*?)^```",
        answer,
        flags=re.MULTILINE | re.DOTALL,
    )
    commands = {
        "python": ("python", "example.py"),
        "python3": ("python", "example.py"),
        "js": ("node", "example.js"),
        "javascript": ("node", "example.js"),
        "ts": ("node", "--experimental-strip-types", "example.ts"),
        "typescript": ("node", "--experimental-strip-types", "example.ts"),
        "bash": ("bash", "example.sh"),
        "sh": ("sh", "example.sh"),
    }
    results: list[dict[str, object]] = []
    for index, (language, source) in enumerate(blocks):
        command = commands[language]
        with tempfile.TemporaryDirectory(
            prefix="ae-example-", dir=PROJECT_TEMP
        ) as temporary:
            root = Path(temporary)
            workspace = root / "workspace"
            shutil.copytree(
                fixture,
                workspace,
                symlinks=True,
                ignore=shutil.ignore_patterns(".git", ".codira", "__pycache__"),
            )
            example_path = workspace / command[-1]
            if example_path.is_symlink():
                example_path.unlink()
            example_path.write_text(source)
            if language in {"python", "python3"} and (
                (workspace / ".venv/bin/python").exists()
                or (workspace / ".venv/bin/python").is_symlink()
            ):
                command = ("/workspace/.venv/bin/python", command[-1])
            argv = [
                runtime,
                "run",
                "--rm",
                "--network=none",
                "--read-only",
                "--cap-drop=ALL",
                "--security-opt=no-new-privileges",
                "--pids-limit=128",
                "--memory=512m",
                "--cpus=1",
                "--tmpfs=/tmp:rw,mode=1777,size=128m",
                f"--mount=type=bind,src={workspace},dst=/workspace,rw",
                "--workdir=/workspace",
                "--env=PYTHONPATH=/workspace/src:/workspace",
                "--env=GOTOOLCHAIN=local",
                "--env=GOPROXY=off",
                "--env=GOSUMDB=off",
                "--env=GOCACHE=/tmp/go-build",
                "--env=GOMODCACHE=/tmp/go-mod",
                image,
                *command,
            ]
            try:
                completed = subprocess.run(
                    argv, capture_output=True, check=False, timeout=60
                )
                status, stdout, stderr = (
                    completed.returncode,
                    completed.stdout,
                    completed.stderr,
                )
            except subprocess.TimeoutExpired as error:
                status, stdout, stderr = None, error.stdout or b"", error.stderr or b""
        for stream, content in (("stdout", stdout), ("stderr", stderr)):
            with (destination / f"example-{index}.{stream}").open("xb") as handle:
                handle.write(content)
        results.append(
            {
                "index": index,
                "language": language,
                "command": list(command),
                "returncode": status,
                "source_sha256": hashlib.sha256(source.encode()).hexdigest(),
                "stdout_sha256": hashlib.sha256(stdout).hexdigest(),
                "stderr_sha256": hashlib.sha256(stderr).hexdigest(),
            }
        )
    report: dict[str, object] = {
        "answer_sha256": hashlib.sha256(answer.encode()).hexdigest(),
        "examples": results,
        "status": "review_required"
        if not results
        else "executed"
        if all(item["returncode"] == 0 for item in results)
        else "execution_failed",
        "expected_output_accuracy": "review_required",
    }
    with (destination / "manifest.json").open("x") as handle:
        json.dump(report, handle, sort_keys=True, indent=2)
    return report
