"""Derive deterministic pre-agent environments from frozen fixture metadata."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path


class EnvironmentPreparationError(ValueError):
    """Report a fixture environment that cannot be prepared offline.

    Parameters
    ----------
    detail : str
        Stable public-safe rejection reason.

    Returns
    -------
    None
        Instances carry the deterministic rejection detail.
    """


@dataclass(frozen=True)
class FixtureEnvironment:
    """Describe one reproducible project environment before an agent starts.

    Parameters
    ----------
    ecosystem : str
        Package-management ecosystem selected from frozen project metadata.
    prepare_argv : tuple[str, ...]
        Offline command that creates the environment beneath the fixture root.
    directive : str
        Model-visible statement of the already-prepared environment.
    fixture_id : str
        Immutable fixture identity used to select baked offline material.

    Returns
    -------
    None
        The immutable plan is safe to persist with non-secret attempt evidence.
    """

    ecosystem: str
    prepare_argv: tuple[str, ...]
    directive: str
    fixture_id: str


def fixture_environment(root: Path, fixture_id: str) -> FixtureEnvironment:
    """Select an offline preparation plan from one exported fixture.

    Parameters
    ----------
    root : pathlib.Path
        Exported, writable fixture root inspected before provider setup.
    fixture_id : str
        Immutable public fixture identity bound to the scheduled task.

    Returns
    -------
    FixtureEnvironment
        Exact ecosystem command and shared model directive.

    Raises
    ------
    EnvironmentPreparationError
        If no locked ecosystem can be selected without mutable resolution.
    """

    if not root.is_dir() or not fixture_id:
        detail = "fixture environment root is unavailable"
        raise EnvironmentPreparationError(detail)
    if (root / "pyproject.toml").is_file() and (root / "uv.lock").is_file():
        return FixtureEnvironment(
            "uv",
            ("/opt/codira/prepare-fixture-environment", fixture_id, "uv"),
            "This fixture's locked uv environment and development dependencies are "
            "already prepared offline in .venv. Use its installed tools; do not run "
            "uv sync, install dependencies, or attempt network access.",
            fixture_id,
        )
    if (root / "package.json").is_file() and (root / "package-lock.json").is_file():
        return FixtureEnvironment(
            "npm",
            ("/opt/codira/prepare-fixture-environment", fixture_id, "npm"),
            "This fixture's locked npm environment and development dependencies are "
            "already prepared offline in node_modules. Use its installed tools; do "
            "not run npm install or attempt network access.",
            fixture_id,
        )
    if (root / "package.json").is_file():
        return FixtureEnvironment(
            "npm",
            ("/opt/codira/prepare-fixture-environment", fixture_id, "npm"),
            "This fixture's npm environment and development dependencies are already "
            "prepared offline in node_modules from the image-bound generated lockfile. "
            "Use its installed tools; do not run npm install or attempt network access.",
            fixture_id,
        )
    requirements = root / "requirements.txt"
    if requirements.is_file() and _requirements_are_pinned(requirements):
        return FixtureEnvironment(
            "pip",
            ("/opt/codira/prepare-fixture-environment", fixture_id, "pip"),
            "This fixture's pinned pip environment is already prepared offline in "
            ".venv. Use .venv/bin/python and its installed tools; do not install "
            "dependencies or attempt network access.",
            fixture_id,
        )
    detail = "fixture has no supported locked environment"
    raise EnvironmentPreparationError(detail)


def _requirements_are_pinned(path: Path) -> bool:
    """Require every active requirements entry to use an exact version.

    Parameters
    ----------
    path : pathlib.Path
        Requirements file to validate before an offline installation.

    Returns
    -------
    bool
        ``True`` only when every non-comment requirement uses ``==``.
    """

    entries = [
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    return bool(entries) and all("==" in entry for entry in entries)
