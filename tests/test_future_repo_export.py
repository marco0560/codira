"""Tests for the future multirepo export helper."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Protocol, cast


class _FutureRepoExportEntry(Protocol):
    """Protocol for one export-plan entry returned by the standalone helper."""

    target_relative: Path


class _FutureRepoExportModule(Protocol):
    """Protocol for the standalone future-repo export helper module."""

    def build_future_repo_export_plan(
        self,
        repo_root: Path,
        repository: str,
    ) -> tuple[_FutureRepoExportEntry, ...]:
        """
        Return the deterministic export plan for one future repository.

        Parameters
        ----------
        repo_root : pathlib.Path
            Repository root containing the source monorepo.
        repository : str
            Future repository name to export.

        Returns
        -------
        tuple[_FutureRepoExportEntry, ...]
            Export plan entries for the requested repository.
        """

    def materialize_future_repo(
        self,
        repo_root: Path,
        repository: str,
        destination_root: Path,
    ) -> Path:
        """
        Materialize one future repository into a destination directory.

        Parameters
        ----------
        repo_root : pathlib.Path
            Repository root containing the source monorepo.
        repository : str
            Future repository name to materialize.
        destination_root : pathlib.Path
            Parent directory receiving the materialized repository.

        Returns
        -------
        pathlib.Path
            Path to the materialized future repository.
        """

    def _ignore_generated_export_artifacts(
        self,
        directory: str,
        names: list[str],
    ) -> set[str]:
        """
        Return generated artifacts ignored during export copies.

        Parameters
        ----------
        directory : str
            Directory being copied.
        names : list[str]
            Candidate child names.

        Returns
        -------
        set[str]
            Names that should be ignored.
        """


def _load_future_repo_export_helper() -> _FutureRepoExportModule:
    """
    Load the standalone future-repo export helper module from disk.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Pytest fixture providing an isolated temporary directory.

    Returns
    -------
    object
        Loaded module object for the future-repo export helper script.
    """
    helper_path = (
        Path(__file__).resolve().parents[1] / "scripts" / "future_repo_export.py"
    )
    sys.path.insert(0, str(helper_path.parent))
    spec = importlib.util.spec_from_file_location("future_repo_export", helper_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return cast("_FutureRepoExportModule", module)


def test_package_export_plan_flattens_owned_paths_to_repository_root() -> None:
    """
    Keep package-repository exports rooted at the future repository top level.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Pytest fixture providing an isolated temporary directory.

    Returns
    -------
    None
        The test asserts package-owned monorepo paths are rewritten relative to
        the future repository root.
    """
    helper = _load_future_repo_export_helper()
    repo_root = Path(__file__).resolve().parents[1]

    plan = helper.build_future_repo_export_plan(
        repo_root=repo_root,
        repository="codira-analyzer-json",
    )

    assert [str(entry.target_relative) for entry in plan] == [
        "README.md",
        "pyproject.toml",
        "src",
        "tests",
    ]


def test_core_export_plan_preserves_repository_relative_paths() -> None:
    """
    Keep the future core export plan aligned to the current repository layout.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Pytest fixture providing an isolated temporary directory.

    Returns
    -------
    None
        The test asserts core export targets remain repository-relative.
    """
    helper = _load_future_repo_export_helper()
    repo_root = Path(__file__).resolve().parents[1]

    plan = helper.build_future_repo_export_plan(
        repo_root=repo_root,
        repository="codira",
    )

    target_paths = [str(entry.target_relative) for entry in plan]

    assert target_paths[1:5] == [
        ".github/workflows/ci.yml",
        ".github/workflows/commit-message-check.yml",
        ".github/workflows/docs.yml",
        ".github/workflows/release.yml",
    ]
    assert {
        ".gitignore",
        ".pre-commit-config.yaml",
        ".releaserc.json",
        "CHANGELOG.md",
        "LICENSE",
        "README.md",
        "mkdocs.yml",
        "package-lock.json",
        "package.json",
        "pyproject.toml",
    }.issubset(set(target_paths))


def test_materialize_future_repo_copies_owned_paths_into_empty_destination(
    tmp_path: Path,
) -> None:
    """
    Keep the export helper limited to manifest-owned paths in an empty target.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Pytest fixture providing an isolated temporary directory.

    Returns
    -------
    None
        The test asserts the export helper copies the expected package files
        into a newly created repository directory.
    """
    helper = _load_future_repo_export_helper()
    repo_root = Path(__file__).resolve().parents[1]
    destination_root = tmp_path / "future-repo-export-test"

    export_dir = helper.materialize_future_repo(
        repo_root=repo_root,
        repository="codira-analyzer-python",
        destination_root=destination_root,
    )

    assert export_dir == destination_root / "codira-analyzer-python"
    assert (export_dir / "README.md").is_file()
    assert (export_dir / "pyproject.toml").is_file()
    assert (export_dir / "src" / "codira_analyzer_python" / "__init__.py").is_file()
    assert (export_dir / "tests" / "test_python_package.py").is_file()


def test_future_repo_export_ignores_generated_python_artifacts() -> None:
    """
    Keep generated bytecode artifacts out of materialized split repositories.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test asserts generated Python cache entries are excluded while
        source files remain eligible for export.
    """
    helper = _load_future_repo_export_helper()

    assert helper._ignore_generated_export_artifacts(
        "tests",
        [
            "__pycache__",
            "module.py",
            "module.pyc",
            "module.pyo",
            "README.md",
        ],
    ) == {"__pycache__", "module.pyc", "module.pyo"}


def test_materialize_future_repo_rejects_non_empty_destination(tmp_path: Path) -> None:
    """
    Keep export rehearsal non-destructive when the target repository already exists.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Pytest fixture providing an isolated temporary directory.

    Returns
    -------
    None
        The test asserts non-empty destination repositories are rejected.
    """
    helper = _load_future_repo_export_helper()
    repo_root = Path(__file__).resolve().parents[1]
    destination_root = tmp_path / "future-repo-export-non-empty"
    export_dir = destination_root / "codira-bundle-official"
    export_dir.mkdir(parents=True, exist_ok=True)
    marker = export_dir / "KEEP.txt"
    marker.write_text("occupied\n", encoding="utf-8")

    try:
        helper.materialize_future_repo(
            repo_root=repo_root,
            repository="codira-bundle-official",
            destination_root=destination_root,
        )
    except ValueError as exc:
        assert "not empty" in str(exc)
    else:
        message = "Expected materialize_future_repo() to reject non-empty target"
        raise AssertionError(message)
