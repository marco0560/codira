"""Collect non-secret dependency metadata inside a read-only benchmark image.

Parameters
----------
None

Returns
-------
None
    Writes versions and generated lockfiles to standard output when executed.
"""

from __future__ import annotations

import importlib.metadata
import json
import platform
import shutil
import subprocess
from pathlib import Path


def inventory() -> dict[str, object]:
    """Read installed versions and declared npm locks without inspecting secrets.

    Parameters
    ----------
    None

    Returns
    -------
    dict[str, object]
        Python and Debian versions, tool versions, and generated npm lockfiles.
    """
    tools = {}
    for name in ("uv", "node", "npm", "go", "codex"):
        executable = shutil.which(name)
        if executable is not None:
            args = (
                (executable, "version") if name == "go" else (executable, "--version")
            )
            result = subprocess.run(args, check=False, text=True, capture_output=True)
            tools[name] = {
                "exit_code": result.returncode,
                "version": result.stdout.strip(),
            }
    debian = shutil.which("dpkg-query")
    packages = ""
    if debian is not None:
        packages = subprocess.run(
            (debian, "-W", "-f=${binary:Package}\t${Version}\n"),
            check=True,
            text=True,
            capture_output=True,
        ).stdout
    lock_root = Path("/opt/codira/fixture-environments/npm-locks")
    locks = {
        path.relative_to(lock_root).as_posix(): json.loads(
            path.read_text(encoding="utf-8")
        )
        for path in sorted(lock_root.glob("*/package-lock.json"))
    }
    return {
        "python": platform.python_version(),
        "python_packages": sorted(
            [
                {"name": item.metadata["Name"], "version": item.version}
                for item in importlib.metadata.distributions()
            ],
            key=lambda item: item["name"].lower(),
        ),
        "debian_packages": packages,
        "tools": tools,
        "generated_npm_locks": locks,
    }


if __name__ == "__main__":
    print(json.dumps(inventory(), sort_keys=True))
