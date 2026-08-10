#!/usr/bin/env python3
"""Rehearse no-network installer and official-bundle wheel installations.

The rehearsal builds only the two user-facing distribution artifacts, installs
them into a disposable environment with ``--no-index --no-deps``, and exports
the four supported installer plans. It proves the standalone automation surface
does not require a monorepo checkout once the artifacts are available.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
INSTALLER_PATH = REPO_ROOT / "packages" / "codira-installer"
BUNDLE_PATH = REPO_ROOT / "packages" / "codira-bundle-official"


@dataclass(frozen=True)
class RehearsalScenario:
    """One deterministic installer plan-export scenario.

    Parameters
    ----------
    name : str
        Stable output filename stem.
    arguments : tuple[str, ...]
        Arguments passed to the installed ``codira-installer`` command.
    """

    name: str
    arguments: tuple[str, ...]


def venv_python(venv_root: Path, *, platform: str = sys.platform) -> Path:
    """Return the platform-specific interpreter path for one virtual environment.

    Parameters
    ----------
    venv_root : pathlib.Path
        Virtual-environment directory.
    platform : str, optional
        Platform identifier used to select the executable layout.

    Returns
    -------
    pathlib.Path
        Python executable within the requested environment.
    """
    executable = "Scripts/python.exe" if platform == "win32" else "bin/python"
    return venv_root / executable


def build_wheel_argv(
    *, python: str, package_path: Path, wheel_dir: Path
) -> tuple[str, ...]:
    """Build one user-facing wheel without build isolation.

    Parameters
    ----------
    python : str
        Python interpreter supplied to ``uv build``.
    package_path : pathlib.Path
        Package source directory.
    wheel_dir : pathlib.Path
        Directory receiving the wheel artifact.

    Returns
    -------
    tuple[str, ...]
        Shell-free wheel-build command vector.
    """
    return (
        "uv",
        "build",
        "--python",
        python,
        "--wheel",
        "--out-dir",
        str(wheel_dir),
        "--no-build-isolation",
        str(package_path),
    )


def build_venv_argv(*, python: str, venv_root: Path) -> tuple[str, ...]:
    """Build the offline temporary-environment creation command.

    Parameters
    ----------
    python : str
        Python version or executable accepted by ``uv venv``.
    venv_root : pathlib.Path
        New virtual-environment directory.

    Returns
    -------
    tuple[str, ...]
        Shell-free virtual-environment command vector.
    """
    return ("uv", "venv", "--python", python, str(venv_root))


def build_offline_install_argv(*, python: Path, wheel_path: Path) -> tuple[str, ...]:
    """Build the network-disabled install command for a local wheel.

    Parameters
    ----------
    python : pathlib.Path
        Interpreter inside the disposable environment.
    wheel_path : pathlib.Path
        Local wheel artifact to install without dependency resolution.

    Returns
    -------
    tuple[str, ...]
        Shell-free offline install command vector.
    """
    return (
        "uv",
        "pip",
        "install",
        "--python",
        str(python),
        "--no-index",
        "--no-deps",
        str(wheel_path),
    )


def scenarios(*, checkout: Path, target: Path) -> tuple[RehearsalScenario, ...]:
    """Return the supported standalone, selected, core, and local scenarios.

    Parameters
    ----------
    checkout : pathlib.Path
        Cloned Codira checkout rendered only in the local-checkout plan.
    target : pathlib.Path
        Explicit existing-environment target rendered in every plan.

    Returns
    -------
    tuple[RehearsalScenario, ...]
        Stable installer plan-export scenarios.
    """
    common = ("--target", "existing", "--environment", str(target))
    return (
        RehearsalScenario("standalone", common),
        RehearsalScenario(
            "selected-feature",
            (*common, "--package", "codira-analyzer-c"),
        ),
        RehearsalScenario("core-only", (*common, "--profile", "core-only")),
        RehearsalScenario(
            "local-checkout",
            (*common, "--source", "local-checkout", "--checkout", str(checkout)),
        ),
    )


def _wheel_path(wheel_dir: Path, distribution: str) -> Path:
    """Return the one expected local wheel for a normalized distribution name.

    Parameters
    ----------
    wheel_dir : pathlib.Path
        Directory containing freshly built wheel artifacts.
    distribution : str
        Normalized distribution project name.

    Returns
    -------
    pathlib.Path
        Matching wheel artifact.

    Raises
    ------
    FileNotFoundError
        If the requested distribution wheel was not built exactly once.
    """
    matches = tuple(sorted(wheel_dir.glob(f"{distribution.replace('-', '_')}-*.whl")))
    if len(matches) != 1:
        message = (
            f"expected one {distribution} wheel in {wheel_dir}, found {len(matches)}"
        )
        raise FileNotFoundError(message)
    return matches[0]


def _build_byproducts(package_path: Path) -> set[Path]:
    """Return local build directories that one wheel build may create.

    Parameters
    ----------
    package_path : pathlib.Path
        Source directory of the package being built.

    Returns
    -------
    set[pathlib.Path]
        Existing build and egg-info directories for the package.
    """
    candidates = {package_path / "build"}
    candidates.update(package_path.glob("*.egg-info"))
    candidates.update((package_path / "src").glob("*.egg-info"))
    return {path for path in candidates if path.exists()}


def _cleanup_new_byproducts(package_path: Path, *, before: set[Path]) -> None:
    """Remove only build by-products introduced by this rehearsal invocation.

    Parameters
    ----------
    package_path : pathlib.Path
        Source directory of the package that was built.
    before : set[pathlib.Path]
        Build paths that existed before the rehearsal began.

    Returns
    -------
    None
    """
    for path in sorted(_build_byproducts(package_path) - before):
        shutil.rmtree(path, ignore_errors=True)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse installer-release rehearsal options.

    Parameters
    ----------
    argv : list[str] | None, optional
        Optional command-line argument override.

    Returns
    -------
    argparse.Namespace
        Parsed rehearsal configuration.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument("--wheel-dir", type=Path, required=True)
    parser.add_argument("--venv-dir", type=Path, required=True)
    parser.add_argument("--plan-dir", type=Path, required=True)
    parser.add_argument("--checkout", type=Path, default=REPO_ROOT)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Build offline artifacts and export plans from an installed standalone wheel.

    Parameters
    ----------
    argv : list[str] | None, optional
        Optional command-line argument override.

    Returns
    -------
    int
        Zero after all artifact, metadata, and plan-export probes succeed.

    Raises
    ------
    FileNotFoundError
        If either expected wheel artifact is not built exactly once.
    OSError
        If the rehearsal output directories cannot be created or read.
    subprocess.CalledProcessError
        If an artifact build, offline installation, metadata probe, or plan
        export command fails.
    ValueError
        If an exported installer plan does not contain a fingerprint.
    """
    args = parse_args(argv)
    args.wheel_dir.mkdir(parents=True, exist_ok=True)
    args.plan_dir.mkdir(parents=True, exist_ok=True)
    commands = (
        build_wheel_argv(
            python=args.python, package_path=INSTALLER_PATH, wheel_dir=args.wheel_dir
        ),
        build_wheel_argv(
            python=args.python, package_path=BUNDLE_PATH, wheel_dir=args.wheel_dir
        ),
        build_venv_argv(python=args.python, venv_root=args.venv_dir),
    )
    for command in commands:
        print(" ".join(command))
    if args.dry_run:
        return 0
    for package_path, command in zip(
        (INSTALLER_PATH, BUNDLE_PATH), commands[:2], strict=True
    ):
        before = _build_byproducts(package_path)
        try:
            subprocess.run(command, cwd=REPO_ROOT, check=True)
        finally:
            _cleanup_new_byproducts(package_path, before=before)
    subprocess.run(commands[2], cwd=REPO_ROOT, check=True)
    python = venv_python(args.venv_dir)
    installer_wheel = _wheel_path(args.wheel_dir, "codira-installer")
    bundle_wheel = _wheel_path(args.wheel_dir, "codira-bundle-official")
    for wheel in (installer_wheel, bundle_wheel):
        command = build_offline_install_argv(python=python, wheel_path=wheel)
        print(" ".join(command))
        subprocess.run(command, check=True)
    metadata_probe = (
        str(python),
        "-c",
        "from importlib.metadata import version; print(version('codira-bundle-official'))",
    )
    subprocess.run(metadata_probe, check=True)
    for scenario in scenarios(checkout=args.checkout, target=args.venv_dir):
        plan_path = args.plan_dir / f"{scenario.name}.json"
        command = (
            str(python),
            "-m",
            "codira_installer.cli",
            *scenario.arguments,
            "--plan",
            str(plan_path),
        )
        print(" ".join(command))
        subprocess.run(command, check=True)
        payload = json.loads(plan_path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or "fingerprint" not in payload:
            message = f"invalid exported installer plan: {plan_path}"
            raise ValueError(message)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
