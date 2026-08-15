"""Tests for versioned workspace and platform-path contracts."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from codira.platform_paths import platform_paths
from codira.workspace import (
    WORKSPACE_SCHEMA_VERSION,
    ResolvedWorkspace,
    WorkspaceDefinition,
    WorkspaceError,
    load_workspace_definition,
    resolve_workspace,
)


@dataclass(frozen=True)
class _PlatformModel:
    """
    Isolated platformdirs-compatible model used for platform path tests.

    Parameters
    ----------
    user_config_path : pathlib.Path
        Modelled user configuration root.
    user_data_path : pathlib.Path
        Modelled user data root.
    user_state_path : pathlib.Path
        Modelled user state root.
    user_cache_path : pathlib.Path
        Modelled user cache root.
    user_runtime_path : pathlib.Path
        Modelled user runtime root.
    """

    user_config_path: Path
    user_data_path: Path
    user_state_path: Path
    user_cache_path: Path
    user_runtime_path: Path


@pytest.mark.parametrize(
    ("name", "model"),
    [
        (
            "linux",
            _PlatformModel(
                Path("/home/alice/.config/codira"),
                Path("/home/alice/.local/share/codira"),
                Path("/home/alice/.local/state/codira"),
                Path("/home/alice/.cache/codira"),
                Path("/run/user/1000/codira"),
            ),
        ),
        (
            "macos",
            _PlatformModel(
                Path("/Users/alice/Library/Application Support/codira"),
                Path("/Users/alice/Library/Application Support/codira"),
                Path("/Users/alice/Library/Application Support/codira"),
                Path("/Users/alice/Library/Caches/codira"),
                Path("/Users/alice/Library/Caches/TemporaryItems/codira"),
            ),
        ),
        (
            "windows",
            _PlatformModel(
                Path("C:/Users/alice/AppData/Local/codira"),
                Path("C:/Users/alice/AppData/Local/codira"),
                Path("C:/Users/alice/AppData/Local/codira"),
                Path("C:/Users/alice/AppData/Local/codira/Cache"),
                Path("C:/Users/alice/AppData/Local/Temp/codira"),
            ),
        ),
    ],
)
def test_platform_paths_are_deterministic_for_each_platform_model(
    name: str,
    model: _PlatformModel,
) -> None:
    """
    Derive every owned path from an isolated platform model.

    Parameters
    ----------
    name : str
        Human-readable platform model name.
    model : _PlatformModel
        Isolated platform directory model.

    Returns
    -------
    None
        The test asserts each derived location stays within its owning root.
    """
    paths = platform_paths(dirs=model)

    assert name in {"linux", "macos", "windows"}
    assert paths.managed_runtime_root == model.user_data_path / "runtimes"
    assert paths.workspace_config_root == model.user_config_path / "workspaces"
    assert paths.workspace_state_root == model.user_state_path / "workspaces"
    assert paths.model_root == model.user_cache_path / "models"
    assert paths.runtime_root == model.user_runtime_path


def test_workspace_descriptor_round_trip_and_relative_resolution(
    tmp_path: Path,
) -> None:
    """
    Preserve a descriptor round trip and canonicalize relative paths.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary descriptor, repository, state, and config paths.

    Returns
    -------
    None
        The test asserts stable TOML serialization and resolved routing paths.
    """
    descriptor_dir = tmp_path / "config" / "workspaces" / "sample"
    descriptor_dir.mkdir(parents=True)
    repository = tmp_path / "repositories" / "sample"
    repository.mkdir(parents=True)
    config_file = descriptor_dir / "settings.toml"
    config_file.write_text("[backend]\nname = 'sqlite'\n", encoding="utf-8")
    state_root = tmp_path / "state" / "sample"
    definition = WorkspaceDefinition(
        name="sample",
        repository_root=Path("../../../repositories/sample"),
        state_root=Path("../../../state/sample"),
        config_file=Path("settings.toml"),
    )
    descriptor_path = descriptor_dir / "workspace.toml"
    descriptor_path.write_text(definition.to_toml(), encoding="utf-8")

    loaded = load_workspace_definition(descriptor_path)
    resolved = resolve_workspace(loaded, descriptor_path=descriptor_path)

    assert loaded == definition
    assert loaded.to_toml() == definition.to_toml()
    assert resolved == ResolvedWorkspace(
        name="sample",
        descriptor_path=descriptor_path.resolve(),
        repository_root=repository.resolve(),
        state_root=state_root.resolve(),
        config_file=config_file.resolve(),
    )


@pytest.mark.parametrize(
    ("content", "message"),
    [
        (
            "schema_version = 2\nname = 'sample'\nrepository_root = 'repo'\nstate_root = 'state'\n",
            "Unsupported workspace schema_version 2",
        ),
        (
            "schema_version = 1\nname = 'sample'\nrepository_root = 'repo'\nstate_root = 'state'\nunknown = true\n",
            "Unknown workspace descriptor key: unknown",
        ),
    ],
)
def test_workspace_descriptor_rejects_unknown_contracts(
    content: str,
    message: str,
) -> None:
    """
    Reject unsupported schema versions and unknown descriptor fields.

    Parameters
    ----------
    content : str
        Invalid workspace TOML content.
    message : str
        Expected stable error fragment.

    Returns
    -------
    None
        The test asserts descriptor validation is strict.
    """
    with pytest.raises(WorkspaceError, match=message):
        WorkspaceDefinition.from_toml(content)


def test_workspace_resolution_rejects_missing_roots_and_unsafe_overlap(
    tmp_path: Path,
) -> None:
    """
    Reject a missing repository root and state containing descriptor metadata.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary workspace descriptor root.

    Returns
    -------
    None
        The test asserts filesystem validation remains deterministic.
    """
    descriptor_dir = tmp_path / "workspaces" / "sample"
    descriptor_dir.mkdir(parents=True)
    descriptor_path = descriptor_dir / "workspace.toml"
    missing = WorkspaceDefinition(
        name="sample",
        repository_root=Path("missing"),
        state_root=Path("state"),
    )
    with pytest.raises(WorkspaceError, match="repository root does not exist"):
        resolve_workspace(missing, descriptor_path=descriptor_path)

    repository = tmp_path / "repository"
    repository.mkdir()
    overlapping = WorkspaceDefinition(
        name="sample",
        repository_root=repository,
        state_root=tmp_path / "workspaces",
    )
    with pytest.raises(WorkspaceError, match="must not contain its descriptor"):
        resolve_workspace(overlapping, descriptor_path=descriptor_path)


def test_workspace_resolution_canonicalizes_repository_symlinks(tmp_path: Path) -> None:
    """
    Canonicalize an existing repository symlink before exposing workspace paths.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary target repository and workspace descriptor paths.

    Returns
    -------
    None
        The test asserts resolved routing does not retain symlink aliases.
    """
    repository = tmp_path / "repository"
    repository.mkdir()
    repository_link = tmp_path / "repository-link"
    repository_link.symlink_to(repository, target_is_directory=True)
    descriptor_path = tmp_path / "workspace.toml"

    resolved = resolve_workspace(
        WorkspaceDefinition(
            name="sample",
            repository_root=repository_link,
            state_root=tmp_path / "state",
        ),
        descriptor_path=descriptor_path,
    )

    assert resolved.repository_root == repository.resolve()


def test_workspace_definition_reserves_stable_non_path_identity() -> None:
    """
    Reject workspace names that could become filesystem traversal paths.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test asserts workspace identity is not a path expression.
    """
    with pytest.raises(WorkspaceError, match="contain no path separators"):
        WorkspaceDefinition(
            name="nested/workspace",
            repository_root=Path("repository"),
            state_root=Path("state"),
            schema_version=WORKSPACE_SCHEMA_VERSION,
        )
