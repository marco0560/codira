"""Tests for the future multirepo CI decomposition contract."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, cast

if TYPE_CHECKING:
    from scripts.future_repo_ci import FutureRepoCISpec


class _FutureRepoCIModule(Protocol):
    """Protocol for the standalone future-repo CI helper module."""

    def future_repo_ci_specs(self) -> tuple[FutureRepoCISpec, ...]:
        """
        Return the deterministic future repository CI specifications.

        Parameters
        ----------
        None

        Returns
        -------
        tuple[scripts.future_repo_ci.FutureRepoCISpec, ...]
            Future repository CI specifications in deterministic order.
        """


def _load_future_repo_ci_helper() -> _FutureRepoCIModule:
    """
    Load the standalone future-repo CI helper module from its repository path.

    Parameters
    ----------
    None

    Returns
    -------
    object
        Loaded module object for the future-repo CI helper script.
    """
    helper_path = Path(__file__).resolve().parents[1] / "scripts" / "future_repo_ci.py"
    sys.path.insert(0, str(helper_path.parent))
    spec = importlib.util.spec_from_file_location("future_repo_ci", helper_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return cast("_FutureRepoCIModule", module)


def test_future_repo_ci_specs_cover_the_accepted_repository_set() -> None:
    """
    Keep the future CI plan aligned to the accepted split repository set.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test asserts the CI specs cover every accepted future repository.
    """
    specs = _load_future_repo_ci_helper().future_repo_ci_specs()

    assert [spec.repository for spec in specs] == [
        "codira",
        "codira-analyzer-python",
        "codira-analyzer-json",
        "codira-analyzer-c",
        "codira-analyzer-bash",
        "codira-backend-sqlite",
        "codira-backend-duckdb",
        "codira-bundle-official",
    ]


def test_core_future_repo_ci_keeps_integration_validation_explicit() -> None:
    """
    Keep the core future-repo CI contract focused on integration validation.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test asserts the core CI spec keeps full repository validation.
    """
    core_spec = _load_future_repo_ci_helper().future_repo_ci_specs()[0]

    assert core_spec.install == (
        (
            "uv",
            "sync",
            "--frozen",
            "--extra",
            "dev",
            "--extra",
            "docs",
            "--extra",
            "semantic",
        ),
        (
            "uv",
            "run",
            "python",
            "scripts/install_first_party_packages.py",
            "--include-core",
            "--core-extra",
            "dev",
            "--core-extra",
            "docs",
            "--core-extra",
            "semantic",
        ),
    )
    assert core_spec.validate == (
        ("uv", "run", "pre_commit", "run", "--all-files"),
        ("uv", "run", "ruff", "check", "src", "scripts", "tests"),
        ("uv", "run", "ruff", "format", "--check", "src", "scripts", "tests"),
        ("uv", "run", "mypy", "src", "scripts", "tests"),
        ("uv", "run", "pytest", "-q"),
    )


def test_package_future_repo_ci_keeps_package_local_validation_uniform() -> None:
    """
    Keep first-party package repos on one package-local CI contract.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test asserts package CI specs share the same validation commands.
    """
    package_specs = _load_future_repo_ci_helper().future_repo_ci_specs()[1:7]

    assert all(
        spec.install == (("uv", "sync", "--frozen", "--extra", "test"),)
        for spec in package_specs
    )
    assert all(
        spec.validate
        == (
            ("uv", "run", "ruff", "check", "src", "tests"),
            ("uv", "run", "ruff", "format", "--check", "src", "tests"),
            ("uv", "run", "mypy", "src", "tests"),
            ("uv", "run", "pytest", "-q", "tests"),
        )
        for spec in package_specs
    )


def test_bundle_future_repo_ci_stays_test_only() -> None:
    """
    Keep the bundle repo CI focused on metadata and package-local tests.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test asserts the bundle CI spec stays test-only.
    """
    bundle_spec = _load_future_repo_ci_helper().future_repo_ci_specs()[-1]

    assert bundle_spec.install == (("uv", "sync", "--frozen", "--extra", "test"),)
    assert bundle_spec.validate == (
        ("uv", "run", "ruff", "check", "tests"),
        ("uv", "run", "ruff", "format", "--check", "tests"),
        ("uv", "run", "mypy", "tests"),
        ("uv", "run", "pytest", "-q", "tests"),
    )
