#!/usr/bin/env python3
"""Rehearse installed-wheel validation for the core and first-party packages.

Responsibilities
----------------
- Build the deterministic installed-wheel rehearsal commands for the release path.
- Validate that `codira` and the first-party plugin packages can be installed
  together from local wheel artifacts.
- Exercise plugin discovery from installed artifacts outside the repository checkout.

Design principles
-----------------
The helper reuses the existing wheel-build workflow, avoids shell indirection,
and keeps the validation probe explicit so release rehearsals stay reviewable.

Architectural role
------------------
This script belongs to the **developer tooling layer** and supports Phase 5
release rehearsals for the packaging migration.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_WHEEL_DIR = REPO_ROOT / ".artifacts" / "release-wheels"
DEFAULT_INSTALL_DIR = REPO_ROOT / ".artifacts" / "release-site-packages"


def _path_text(path: Path) -> str:
    """
    Render a path with deterministic forward-slash separators.

    Parameters
    ----------
    path : pathlib.Path
        Path to render for command arguments.

    Returns
    -------
    str
        POSIX-style path text.
    """
    text = str(path)
    if text.startswith("\\") and not text.startswith("\\\\"):
        return path.as_posix()
    return text


def build_first_party_wheels_argv(
    *,
    python: str,
    repo_root: Path,
    wheel_dir: Path,
) -> tuple[str, ...]:
    """
    Build the command that creates first-party plugin wheels.

    Parameters
    ----------
    python : str
        Python interpreter used to run the helper.
    repo_root : pathlib.Path
        Repository root containing the first-party build helper.
    wheel_dir : pathlib.Path
        Directory receiving built wheel artifacts.

    Returns
    -------
    tuple[str, ...]
        Deterministic command arguments for the first-party wheel build step.
    """
    return (
        python,
        _path_text(repo_root / "scripts" / "build_first_party_packages.py"),
        "--wheel-dir",
        _path_text(wheel_dir),
    )


def build_root_wheel_argv(
    *,
    python: str,
    repo_root: Path,
    wheel_dir: Path,
) -> tuple[str, ...]:
    """
    Build the command that creates the core `codira` wheel artifact.

    Parameters
    ----------
    python : str
        Python interpreter used to build the wheel.
    repo_root : pathlib.Path
        Repository root containing the core package.
    wheel_dir : pathlib.Path
        Directory receiving built wheel artifacts.

    Returns
    -------
    tuple[str, ...]
        Deterministic command arguments for the core wheel build step.
    """
    return (
        "uv",
        "build",
        "--python",
        python,
        "--wheel",
        "--out-dir",
        _path_text(wheel_dir),
        "--no-build-isolation",
        _path_text(repo_root),
    )


def discover_wheel_paths(wheel_dir: Path) -> tuple[Path, ...]:
    """
    Return built wheel artifacts in deterministic install order.

    Parameters
    ----------
    wheel_dir : pathlib.Path
        Directory containing built wheel artifacts.

    Returns
    -------
    tuple[pathlib.Path, ...]
        Wheel artifact paths sorted lexicographically.
    """
    return tuple(sorted(wheel_dir.glob("*.whl")))


def build_install_wheels_argv(
    *,
    python: str,
    install_dir: Path,
    wheel_paths: tuple[Path, ...],
) -> tuple[str, ...]:
    """
    Build the command that installs the wheel set into an isolated target directory.

    Parameters
    ----------
    python : str
        Python interpreter targeted by ``uv pip``.
    install_dir : pathlib.Path
        Target directory receiving the installed wheel contents.
    wheel_paths : tuple[pathlib.Path, ...]
        Built wheel artifact paths to install.

    Returns
    -------
    tuple[str, ...]
        Deterministic command arguments for the wheel install step.
    """
    return (
        "uv",
        "pip",
        "install",
        "--python",
        python,
        "--no-deps",
        "--target",
        _path_text(install_dir),
        *(_path_text(path) for path in wheel_paths),
    )


def build_probe_argv(*, python: str) -> tuple[str, ...]:
    """
    Build the command that probes installed-wheel plugin discovery.

    Parameters
    ----------
    python : str
        Python interpreter used to run the probe.

    Returns
    -------
    tuple[str, ...]
        Deterministic command arguments for the discovery probe.
    """
    return (
        python,
        "-c",
        (
            "import json, codira, codira.registry as registry; "
            "backend = registry.active_index_backend(); "
            "analyzers = registry.active_language_analyzers(); "
            "print(json.dumps({"
            "'codira_file': codira.__file__, "
            "'backend_module': type(backend).__module__, "
            "'analyzers': [analyzer.name for analyzer in analyzers]"
            "}))"
        ),
    )


def _root_build_artifact_paths(repo_root: Path) -> set[Path]:
    """
    Return transient root-package build artifacts created by wheel builds.

    Parameters
    ----------
    repo_root : pathlib.Path
        Repository root whose transient build artifacts should be tracked.

    Returns
    -------
    set[pathlib.Path]
        Build and egg-info paths currently present for the root package.
    """
    paths: set[Path] = set()
    build_dir = repo_root / "build"
    if build_dir.exists():
        paths.add(build_dir)
    for egg_info_dir in sorted((repo_root / "src").glob("*.egg-info")):
        paths.add(egg_info_dir)
    return paths


def _cleanup_root_build_artifacts(
    repo_root: Path,
    *,
    before_paths: set[Path],
) -> None:
    """
    Remove transient root-package build artifacts created during one rehearsal.

    Parameters
    ----------
    repo_root : pathlib.Path
        Repository root whose transient build artifacts should be cleaned.
    before_paths : set[pathlib.Path]
        Artifact paths that existed before the rehearsal started.

    Returns
    -------
    None
        Newly created build artifacts are removed in place.
    """
    for path in sorted(_root_build_artifact_paths(repo_root) - before_paths):
        shutil.rmtree(path, ignore_errors=True)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """
    Parse command-line arguments for the release install rehearsal helper.

    Parameters
    ----------
    argv : list[str] | None, optional
        Optional argument override.

    Returns
    -------
    argparse.Namespace
        Parsed helper arguments.
    """
    parser = argparse.ArgumentParser(
        description=(
            "Build local wheel artifacts and rehearse installed-wheel plugin "
            "discovery for codira."
        )
    )
    parser.add_argument(
        "--python",
        default=sys.executable,
        help="Python interpreter used for the rehearsal.",
    )
    parser.add_argument(
        "--wheel-dir",
        type=Path,
        default=DEFAULT_WHEEL_DIR,
        help="Directory receiving built wheel artifacts.",
    )
    parser.add_argument(
        "--install-dir",
        type=Path,
        default=DEFAULT_INSTALL_DIR,
        help="Isolated target directory receiving installed wheel contents.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the rehearsal commands without executing them.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """
    Run the installed-wheel release rehearsal.

    Parameters
    ----------
    argv : list[str] | None, optional
        Optional argument override.

    Returns
    -------
    int
        Process exit code.

    Raises
    ------
    FileNotFoundError
        Raised when no wheel artifacts are produced.
    subprocess.CalledProcessError
        Raised when build, install, or probe subprocesses fail.
    json.JSONDecodeError
        Raised when the installed package probe emits invalid JSON.
    """
    args = parse_args(argv)
    args.wheel_dir.mkdir(parents=True, exist_ok=True)
    args.install_dir.mkdir(parents=True, exist_ok=True)

    first_party_command = build_first_party_wheels_argv(
        python=args.python,
        repo_root=REPO_ROOT,
        wheel_dir=args.wheel_dir,
    )
    root_command = build_root_wheel_argv(
        python=args.python,
        repo_root=REPO_ROOT,
        wheel_dir=args.wheel_dir,
    )
    for command in (first_party_command, root_command):
        print(" ".join(command))
    if args.dry_run:
        return 0

    build_artifacts_before = _root_build_artifact_paths(REPO_ROOT)
    try:
        subprocess.run(first_party_command, cwd=REPO_ROOT, check=True)
        subprocess.run(root_command, cwd=REPO_ROOT, check=True)
    finally:
        _cleanup_root_build_artifacts(REPO_ROOT, before_paths=build_artifacts_before)

    wheel_paths = discover_wheel_paths(args.wheel_dir)
    if not wheel_paths:
        message = f"No wheel artifacts were built in {args.wheel_dir}"
        raise FileNotFoundError(message)

    install_command = build_install_wheels_argv(
        python=args.python,
        install_dir=args.install_dir,
        wheel_paths=wheel_paths,
    )
    print(" ".join(install_command))
    subprocess.run(install_command, check=True)

    probe_command = build_probe_argv(python=args.python)
    print(" ".join(probe_command))
    env = os.environ.copy()
    env["PYTHONPATH"] = str(args.install_dir)
    env["PYTHONNOUSERSITE"] = "1"
    result = subprocess.run(
        probe_command,
        cwd=args.install_dir,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(result.stdout)
    print(json.dumps(payload, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
