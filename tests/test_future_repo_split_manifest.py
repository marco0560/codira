"""Tests for the future multirepo split file manifest."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, cast

if TYPE_CHECKING:
    from scripts.future_repo_split_manifest import FutureRepoSplitManifest


class _FutureRepoSplitManifestModule(Protocol):
    """Protocol for the standalone future split manifest helper."""

    def future_repo_split_manifests(self) -> tuple[FutureRepoSplitManifest, ...]:
        """Return the deterministic future repository split manifests."""


def _load_future_repo_split_manifest_helper() -> _FutureRepoSplitManifestModule:
    """
    Load the standalone future split manifest helper module from disk.

    Parameters
    ----------
    None

    Returns
    -------
    object
        Loaded module object for the future split manifest helper script.
    """
    helper_path = (
        Path(__file__).resolve().parents[1]
        / "scripts"
        / "future_repo_split_manifest.py"
    )
    sys.path.insert(0, str(helper_path.parent))
    spec = importlib.util.spec_from_file_location(
        "future_repo_split_manifest",
        helper_path,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return cast("_FutureRepoSplitManifestModule", module)


def test_future_repo_split_manifests_cover_the_accepted_repository_set() -> None:
    """
    Keep the split manifest aligned to the accepted repository topology.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test asserts the split manifests cover every accepted future repository.
    """
    manifests = _load_future_repo_split_manifest_helper().future_repo_split_manifests()

    assert [manifest.repository for manifest in manifests] == [
        "codira",
        "codira-analyzer-python",
        "codira-analyzer-json",
        "codira-analyzer-c",
        "codira-analyzer-bash",
        "codira-backend-sqlite",
        "codira-bundle-official",
    ]


def test_core_manifest_keeps_shared_repository_paths_in_core() -> None:
    """
    Keep shared project infrastructure assigned to the future core repository.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test asserts the core manifest retains shared project paths.
    """
    core_manifest = (
        _load_future_repo_split_manifest_helper().future_repo_split_manifests()[0]
    )

    assert core_manifest.owned_paths == (
        ".gitignore",
        ".github/workflows/ci.yml",
        ".github/workflows/commit-message-check.yml",
        ".github/workflows/docs.yml",
        ".github/workflows/release.yml",
        ".pre-commit-config.yaml",
        ".releaserc.json",
        "CHANGELOG.md",
        "LICENSE",
        "README.md",
        "docs/",
        "examples/",
        "mkdocs.yml",
        "package-lock.json",
        "package.json",
        "pyproject.toml",
        "scripts/",
        "src/codira/",
        "tests/",
    )
    assert core_manifest.stays_in_core == ()


def test_core_manifest_keeps_root_files_needed_by_retained_workflows() -> None:
    """
    Keep exported core repositories operational after the split rehearsal.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test asserts the core manifest retains the root files required by
        the CI, docs, and release workflows that stay in the exported core
        repository.
    """
    core_manifest = (
        _load_future_repo_split_manifest_helper().future_repo_split_manifests()[0]
    )

    required_paths = {
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
    }

    assert required_paths.issubset(set(core_manifest.owned_paths))


def test_package_manifests_keep_package_paths_and_compatibility_surfaces_explicit() -> (
    None
):
    """
    Keep package-owned files and residual core compatibility paths explicit.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test asserts each non-core manifest owns package-local paths and
        records the remaining core-side compatibility surfaces that matter after split.
    """
    manifests = _load_future_repo_split_manifest_helper().future_repo_split_manifests()[
        1:
    ]

    assert all(
        any(path.endswith("/pyproject.toml") for path in manifest.owned_paths)
        for manifest in manifests
    )
    assert all(
        any(path.endswith("/tests/") for path in manifest.owned_paths)
        for manifest in manifests
    )
    assert any(
        manifest.repository == "codira-backend-sqlite"
        and "src/codira/indexer.py" in manifest.stays_in_core
        and "src/codira/sqlite_backend_support.py" in manifest.stays_in_core
        for manifest in manifests
    )
