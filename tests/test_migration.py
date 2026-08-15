"""Tests for explicit non-destructive workspace migration."""

from __future__ import annotations

import json
import sys
from typing import TYPE_CHECKING

import pytest

from codira.cli import main
from codira.migration import (
    ConfigMigrationMode,
    ModelImport,
    StateMigrationMode,
    apply_workspace_migration,
    migration_payload,
    preview_workspace_migration,
)
from codira.model_store import ModelIdentity, SharedModelStore
from codira.workspace import WorkspaceError
from codira.workspace_registry import WorkspaceRegistry

if TYPE_CHECKING:
    from pathlib import Path


def _registry(tmp_path: Path) -> WorkspaceRegistry:
    """Build an isolated registry with deterministic migration journals.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary root provided by pytest.

    Returns
    -------
    codira.workspace_registry.WorkspaceRegistry
        Registry isolated from user platform data.
    """
    return WorkspaceRegistry(tmp_path / "descriptors", tmp_path / "state")


def test_workspace_migration_copies_selected_data_and_is_idempotent(
    tmp_path: Path,
) -> None:
    """Copy selected state, config, and model data without altering originals.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary source and destination roots.

    Returns
    -------
    None
        The test asserts full-plan provenance, atomic targets, and no-op replay.
    """
    repository = tmp_path / "repository"
    repository.mkdir()
    config = repository / "codira.toml"
    config.write_text("[index]\nworkers = 1\n", encoding="utf-8")
    old_state = tmp_path / "old-state"
    old_state.mkdir()
    (old_state / "index.sqlite3").write_bytes(b"state")
    old_model = tmp_path / "model.onnx"
    old_model.write_bytes(b"model")
    registry = _registry(tmp_path)
    plan = preview_workspace_migration(
        registry,
        name="sample",
        repository_root=repository,
        state_root=tmp_path / "new-state",
        config_source=config,
        config_mode=ConfigMigrationMode.COPY,
        state_source=old_state,
        state_mode=StateMigrationMode.COPY,
        model_imports=(
            ModelImport(
                ModelIdentity("onnx", "example/model", "r1", "model.onnx"),
                old_model,
            ),
        ),
        model_root=tmp_path / "shared-models",
    )

    preview = migration_payload(plan)
    assert preview["retained_originals"] == [
        str(repository),
        str(config),
        str(old_state),
        str(old_model),
    ]
    actions = preview["large_data_actions"]
    assert isinstance(actions, list)
    state_action = actions[0]
    assert isinstance(state_action, dict)
    assert state_action["estimated_bytes"] == len(b"state")
    assert not plan.descriptor_path.exists()
    assert not plan.state_root.exists()
    assert not plan.recovery_record.exists()

    apply_workspace_migration(registry, plan)
    assert registry.validate("sample").config_file == plan.config_destination
    assert (plan.state_root / "index.sqlite3").read_bytes() == b"state"
    assert plan.config_destination is not None
    assert plan.config_destination.read_text(encoding="utf-8") == config.read_text(
        encoding="utf-8"
    )
    assert config.exists()
    assert (old_state / "index.sqlite3").read_bytes() == b"state"
    store = SharedModelStore(tmp_path / "shared-models")
    assert store.artifact_path(plan.model_imports[0].identity) is not None
    journal = json.loads(plan.recovery_record.read_text(encoding="utf-8"))
    assert journal["completed"] == [
        "complete",
        "config",
        "models",
        "state",
        "workspace",
    ]

    journal_before = plan.recovery_record.read_bytes()
    apply_workspace_migration(registry, plan)
    assert plan.recovery_record.read_bytes() == journal_before


def test_workspace_migration_resumes_after_interruption(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Resume from the durable journal without copying state twice.

    Parameters
    ----------
    monkeypatch : pytest.MonkeyPatch
        Fixture used to interrupt the configuration copy.
    tmp_path : pathlib.Path
        Temporary source and destination roots.

    Returns
    -------
    None
        The test asserts completed state is reused during resume.
    """
    repository = tmp_path / "repository"
    repository.mkdir()
    config = tmp_path / "config.toml"
    config.write_text("[index]\nworkers = 1\n", encoding="utf-8")
    old_state = tmp_path / "old-state"
    old_state.mkdir()
    (old_state / "payload").write_text("kept", encoding="utf-8")
    registry = _registry(tmp_path)
    plan = preview_workspace_migration(
        registry,
        name="sample",
        repository_root=repository,
        state_root=tmp_path / "new-state",
        config_source=config,
        config_mode=ConfigMigrationMode.COPY,
        state_source=old_state,
        state_mode=StateMigrationMode.COPY,
    )

    def interrupted_copy(source: Path, destination: Path) -> None:
        """Simulate an interruption after state publication.

        Parameters
        ----------
        source : pathlib.Path
            Source configuration file.
        destination : pathlib.Path
            Destination configuration file.

        Returns
        -------
        None
            The fixture always raises instead of copying.

        Raises
        ------
        WorkspaceError
            Always, to model a failed later migration action.
        """
        del source, destination
        message = "interrupted"
        raise WorkspaceError(message)

    monkeypatch.setattr("codira.migration._copy_file_atomically", interrupted_copy)
    with pytest.raises(WorkspaceError, match="interrupted"):
        apply_workspace_migration(registry, plan)
    assert (plan.state_root / "payload").read_text(encoding="utf-8") == "kept"
    assert json.loads(plan.recovery_record.read_text(encoding="utf-8"))[
        "completed"
    ] == ["state"]

    monkeypatch.undo()
    apply_workspace_migration(registry, plan)
    assert registry.validate("sample").state_root == plan.state_root
    assert (plan.state_root / "payload").read_text(encoding="utf-8") == "kept"


def test_workspace_migration_rejects_overlapping_copy_paths(tmp_path: Path) -> None:
    """Reject copy destinations that could overwrite their own sources.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository and source tree.

    Returns
    -------
    None
        The test asserts overlap is rejected before filesystem writes.
    """
    repository = tmp_path / "repository"
    repository.mkdir()
    old_state = tmp_path / "old-state"
    old_state.mkdir()

    with pytest.raises(WorkspaceError, match="Unsafe overlapping state copy"):
        preview_workspace_migration(
            _registry(tmp_path),
            name="sample",
            repository_root=repository,
            state_root=old_state / "nested",
            state_source=old_state,
            state_mode=StateMigrationMode.COPY,
        )


def test_workspace_migration_recovers_after_state_rename_before_journal(
    tmp_path: Path,
) -> None:
    """Recognize an atomically copied state tree that lacks its journal entry.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository and state roots.

    Returns
    -------
    None
        The test asserts a rename-before-journal interruption resumes safely.
    """
    repository = tmp_path / "repository"
    repository.mkdir()
    old_state = tmp_path / "old-state"
    old_state.mkdir()
    (old_state / "payload").write_bytes(b"kept")
    registry = _registry(tmp_path)
    plan = preview_workspace_migration(
        registry,
        name="sample",
        repository_root=repository,
        state_root=tmp_path / "new-state",
        state_source=old_state,
        state_mode=StateMigrationMode.COPY,
    )
    (tmp_path / "new-state").mkdir()
    (tmp_path / "new-state" / "payload").write_bytes(b"kept")

    apply_workspace_migration(registry, plan)

    assert registry.validate("sample").state_root == plan.state_root
    journal = json.loads(plan.recovery_record.read_text(encoding="utf-8"))
    assert journal["completed"] == ["complete", "state", "workspace"]


def test_workspace_migration_cli_previews_before_explicit_apply(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Expose the migration plan through dry-run and apply CLI modes.

    Parameters
    ----------
    monkeypatch : pytest.MonkeyPatch
        Fixture used to inject an isolated registry and arguments.
    tmp_path : pathlib.Path
        Temporary repository and registry roots.
    capsys : pytest.CaptureFixture[str]
        Fixture used to capture JSON output.

    Returns
    -------
    None
        The test asserts migration has no effect without ``--apply``.
    """
    repository = tmp_path / "repository"
    repository.mkdir()
    registry = _registry(tmp_path)
    monkeypatch.setattr(
        "codira.workspace_registry.WorkspaceRegistry.default", lambda: registry
    )
    arguments = [
        "codira",
        "workspace",
        "migrate",
        "sample",
        "--path",
        str(repository),
        "--json",
    ]
    monkeypatch.setattr(sys, "argv", arguments)
    assert main() == 0
    preview = json.loads(capsys.readouterr().out)
    assert preview["status"] == "preview"
    assert not registry.descriptor_path("sample").exists()

    monkeypatch.setattr(sys, "argv", [*arguments, "--apply"])
    assert main() == 0
    applied = json.loads(capsys.readouterr().out)
    assert applied["status"] == "applied"
    assert registry.validate("sample").repository_root == repository
