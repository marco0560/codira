"""Tests for atomic workspace registry and CLI administration."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path  # noqa: TC003

import pytest

from codira.cli import main
from codira.path_resolution import resolve_runtime_paths
from codira.platform_paths import PlatformPaths
from codira.workspace import WorkspaceError
from codira.workspace_registry import WorkspaceRegistry


def _registry(tmp_path: Path) -> WorkspaceRegistry:
    """Build one isolated workspace registry.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary test root.

    Returns
    -------
    WorkspaceRegistry
        Isolated descriptor and state registry.
    """
    return WorkspaceRegistry(tmp_path / "config" / "workspaces", tmp_path / "state")


def test_registry_add_is_idempotent_and_rejects_name_and_root_conflicts(
    tmp_path: Path,
) -> None:
    """Persist equivalent registrations once and reject conflicts atomically.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository and registry roots.

    Returns
    -------
    None
        The test asserts name and canonical-root invariants.
    """
    registry = _registry(tmp_path)
    first_root = tmp_path / "first"
    first_root.mkdir()
    first = registry.with_defaults(name="first", repository_root=first_root)
    assert registry.add(first)[1] is True
    assert registry.add(first)[1] is False
    with pytest.raises(WorkspaceError, match="name is already registered"):
        registry.add(
            registry.with_defaults(name="first", repository_root=tmp_path / "other")
        )
    with pytest.raises(WorkspaceError, match="already registered by workspace: first"):
        registry.add(registry.with_defaults(name="second", repository_root=first_root))
    assert registry.list_definitions() == (first,)


def test_registry_update_validate_and_remove_preserve_target_data(
    tmp_path: Path,
) -> None:
    """Update and unregister descriptors without deleting owned external data.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository, state, and registry paths.

    Returns
    -------
    None
        The test asserts remove affects only the descriptor.
    """
    registry = _registry(tmp_path)
    repository = tmp_path / "repository"
    repository.mkdir()
    state = tmp_path / "external-state"
    state.mkdir()
    definition = registry.with_defaults(name="sample", repository_root=repository)
    registry.add(definition)
    replacement = registry.with_defaults(
        name="sample", repository_root=repository, state_root=state
    )
    assert registry.update(replacement) == replacement
    assert registry.validate("sample").state_root == state.resolve()
    assert registry.remove("sample") == replacement
    assert repository.exists()
    assert state.exists()
    assert not registry.descriptor_path("sample").exists()


def test_workspace_cli_emits_deterministic_json(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Exercise workspace add, list, validate, and remove JSON contracts.

    Parameters
    ----------
    monkeypatch : pytest.MonkeyPatch
        Fixture used to isolate platform paths and process arguments.
    tmp_path : pathlib.Path
        Temporary repository and platform roots.
    capsys : pytest.CaptureFixture[str]
        Fixture used to capture command output.

    Returns
    -------
    None
        The test asserts versioned deterministic workspace CLI payloads.
    """
    repository = tmp_path / "repository"
    repository.mkdir()
    paths = PlatformPaths(
        config_root=tmp_path / "config",
        data_root=tmp_path / "data",
        state_root=tmp_path / "state",
        cache_root=tmp_path / "cache",
        runtime_root=tmp_path / "runtime",
        managed_runtime_root=tmp_path / "data" / "runtimes",
        workspace_config_root=tmp_path / "config" / "workspaces",
        workspace_state_root=tmp_path / "state" / "workspaces",
        model_root=tmp_path / "cache" / "models",
    )
    monkeypatch.setattr("codira.workspace_registry.platform_paths", lambda: paths)
    monkeypatch.setattr(
        sys,
        "argv",
        ["codira", "workspace", "add", "sample", "--path", str(repository), "--json"],
    )
    assert main() == 0
    created = json.loads(capsys.readouterr().out)
    assert created["status"] == "created"
    assert created["workspace"]["name"] == "sample"
    monkeypatch.setattr(
        sys, "argv", ["codira", "workspace", "validate", "sample", "--json"]
    )
    assert main() == 0
    assert json.loads(capsys.readouterr().out)["status"] == "valid"
    monkeypatch.setattr(
        sys, "argv", ["codira", "workspace", "remove", "sample", "--json"]
    )
    assert main() == 0
    assert json.loads(capsys.readouterr().out)["status"] == "removed"


def test_workspace_routing_matches_direct_paths_and_rejects_mixing(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Resolve equivalent workspace and direct routing through one resolver.

    Parameters
    ----------
    monkeypatch : pytest.MonkeyPatch
        Fixture used to inject the isolated registry.
    tmp_path : pathlib.Path
        Temporary repository, state, and registry roots.

    Returns
    -------
    None
        The test asserts parity and pre-access conflict rejection.
    """
    registry = _registry(tmp_path)
    repository = tmp_path / "repository"
    repository.mkdir()
    state = tmp_path / "state-root"
    definition = registry.with_defaults(
        name="sample", repository_root=repository, state_root=state
    )
    registry.add(definition)
    monkeypatch.setattr(
        "codira.workspace_registry.WorkspaceRegistry.default", lambda: registry
    )
    parser = argparse.ArgumentParser()
    direct = resolve_runtime_paths(
        parser,
        argparse.Namespace(
            path=str(repository), output_dir=str(state), config_file=None
        ),
    )
    workspace = resolve_runtime_paths(
        parser,
        argparse.Namespace(
            path=None, output_dir=None, config_file=None, workspace="sample"
        ),
    )
    assert (
        workspace.target_root,
        workspace.output_root,
        workspace.repo_config_file,
    ) == (
        direct.target_root,
        direct.output_root,
        direct.repo_config_file,
    )
    assert (
        workspace.workspace_descriptor_fingerprint
        == hashlib.sha256(registry.descriptor_path("sample").read_bytes()).hexdigest()
    )
    with pytest.raises(SystemExit):
        resolve_runtime_paths(
            parser,
            argparse.Namespace(
                path=None,
                output_dir=None,
                config_file=None,
                workspace="sample",
                workspace_fingerprint="0" * 64,
            ),
        )
    with pytest.raises(SystemExit):
        resolve_runtime_paths(
            parser,
            argparse.Namespace(
                path=str(repository),
                output_dir=None,
                config_file=None,
                workspace="sample",
            ),
        )
