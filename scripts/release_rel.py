#!/usr/bin/env python3
"""Run the guarded release push path."""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

if any(arg in {"-h", "--help"} for arg in sys.argv[1:]):
    print(
        "Usage: python scripts/release_rel.py [-h|--help]\n\n"
        "Run the guarded release push path used by git rel."
    )
    raise SystemExit(0)

from scripts.scriptlib import output, resolve_python, run


def main() -> int:
    """
    Run the release pipeline.

    Parameters
    ----------
    None

    Returns
    -------
    int
        Process exit status.
    """

    print("== Release pipeline ==")
    python = resolve_python()
    print("[0] Checking uv-managed Python environment...")
    check = run(
        [
            python,
            "-c",
            "import pathlib, sys; raise SystemExit(0 if (pathlib.Path(sys.prefix) / 'pyvenv.cfg').exists() else 1)",
        ]
    )
    if check.returncode:
        return check.returncode

    steps = (
        ("[1] Sync with remote...", ["git", "fetch"]),
        ("[1] Sync with remote...", ["git", "pull", "--ff-only"]),
        ("[2] Running release audit...", [python, "-m", "scripts.release_audit"]),
    )
    for label, command in steps:
        print(label)
        status = run(command).returncode
        if status:
            return status

    env = dict(os.environ)
    env["SKIP_RELEASE_AUDIT"] = "1"
    env["ALLOW_MAIN_PUSH"] = "1"
    status = run(["git", "push"], env=env).returncode
    if status:
        return status

    print("[3] Waiting for CI/tag propagation...")
    run([python, "-c", "import time; time.sleep(30)"])

    print("[4] Sync again...")
    for command in (["git", "fetch", "-q"], ["git", "pull", "--ff-only", "-q"]):
        status = run(command).returncode
        if status:
            return status

    print("[5] Cleaning build artifacts...")
    shutil.rmtree("dist", ignore_errors=True)
    shutil.rmtree("build", ignore_errors=True)
    for path in os.scandir("."):
        if path.is_dir() and path.name.endswith(".egg-info"):
            shutil.rmtree(path.path)

    print("[6] Checking build backend availability...")
    if run([python, "-c", "import build"], stdout=-3, stderr=-3).returncode:
        print(
            "ERROR: Python package 'build' is not installed in the uv-managed environment"
        )
        return 1

    print("[7] Building package...")
    status = run(
        [python, "-m", "build", "--wheel", "--no-isolation"], stdout=-3
    ).returncode
    if status:
        return status

    print("[8] Installing latest wheel...")
    wheels = sorted(
        os.scandir("dist"), key=lambda entry: entry.stat().st_mtime, reverse=True
    )
    wheel = next((entry.path for entry in wheels if entry.name.endswith(".whl")), "")
    if not wheel:
        print("ERROR: no wheel found in dist/")
        return 1
    status = run(
        [python, "-m", "pip", "install", "--force-reinstall", "--no-deps", "-q", wheel]
    ).returncode
    if status:
        return status

    print("[9] Verifying version...")
    codira = (
        shutil.which("codira")
        or output(
            [python, "-c", "import shutil; print(shutil.which('codira') or '')"]
        ).strip()
    )
    status = run([codira or "codira", "-V"]).returncode
    if status:
        return status
    print("== Release pipeline completed ==")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
