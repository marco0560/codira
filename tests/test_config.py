"""Tests for Codira persistent runtime configuration.

Responsibilities
----------------
- Validate deterministic config hierarchy and origin tracking.
- Exercise config CLI commands without touching host user config.
- Guard runtime integration for registry and embedding toggles.

Design principles
-----------------
Tests keep config paths under temporary directories and avoid relying on the
operator's real platform config locations.

Architectural role
------------------
This module belongs to the **runtime configuration verification layer**.
"""

from __future__ import annotations

import json
import sys
from typing import TYPE_CHECKING, cast

import pytest

from codira import config as config_module
from codira.cli import main
from codira.config import (
    ConfigError,
    config_to_mapping,
    load_effective_config,
    profile_config,
    render_config_toml,
    validate_config_mapping,
    write_config_file,
)
from codira.contracts import BackendEmbeddingCandidatesRequest
from codira.registry import reset_plugin_registry_caches
from codira.semantic import embeddings as embeddings_module
from codira.semantic.search import embedding_candidates

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path


def _isolate_config_paths(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> tuple[Path, Path]:
    """
    Redirect platform config paths into a temporary directory.

    Parameters
    ----------
    monkeypatch : pytest.MonkeyPatch
        Fixture used to patch path providers.
    tmp_path : pathlib.Path
        Temporary directory for test-owned config files.

    Returns
    -------
    tuple[pathlib.Path, pathlib.Path]
        User and system config directories.
    """

    user_dir = tmp_path / "user-config"
    system_dir = tmp_path / "system-config"
    monkeypatch.setattr(
        config_module,
        "user_config_path",
        lambda: user_dir / "config.toml",
    )
    monkeypatch.setattr(
        config_module,
        "system_config_path",
        lambda: system_dir / "config.toml",
    )
    return user_dir, system_dir


def test_effective_config_merges_with_env_precedence(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """
    Merge system, user, repo, and environment config deterministically.

    Parameters
    ----------
    monkeypatch : pytest.MonkeyPatch
        Fixture used to isolate config paths.
    tmp_path : pathlib.Path
        Temporary repository root and config directory.

    Returns
    -------
    None
        The test asserts highest-precedence values and origins win.
    """

    user_dir, system_dir = _isolate_config_paths(monkeypatch, tmp_path)
    root = tmp_path / "repo"
    root.mkdir()
    system_path = system_dir / "config.toml"
    user_path = user_dir / "config.toml"
    repo_path = root / ".codira" / "config.toml"
    system_path.parent.mkdir(parents=True)
    user_path.parent.mkdir(parents=True)
    repo_path.parent.mkdir(parents=True)
    system_path.write_text('[backend]\nname = "sqlite"\n', encoding="utf-8")
    user_path.write_text("[embeddings]\nbatch_size = 16\n", encoding="utf-8")
    repo_path.write_text('[plugins]\ndisabled_analyzers = ["json"]\n', encoding="utf-8")

    config = load_effective_config(
        root=root,
        env={
            "CODIRA_INDEX_BACKEND": "duckdb",
            "CODIRA_EMBED_BATCH_SIZE": "7",
        },
    )

    assert config.backend.name == "duckdb"
    assert config.embeddings.batch_size == 7
    assert config.plugins.disabled_analyzers == ("json",)
    assert config.origins["backend.name"].level == "environment"
    assert config.origins["plugins.disabled_analyzers"].path == repo_path


def test_config_validation_rejects_unknown_keys() -> None:
    """
    Reject unknown config keys during strict validation.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test asserts unknown keys fail deterministically.
    """

    with pytest.raises(ConfigError, match="Unknown configuration key"):
        validate_config_mapping({"embeddings": {"unknown": True}})


def test_config_validation_accepts_namespaced_plugin_tables(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """
    Accept dynamic plugin configuration tables under the plugins section.

    Parameters
    ----------
    monkeypatch : pytest.MonkeyPatch
        Fixture used to isolate config paths.
    tmp_path : pathlib.Path
        Temporary config directory.

    Returns
    -------
    None
        The test asserts plugin-specific tables are preserved.
    """

    user_dir, _system_dir = _isolate_config_paths(monkeypatch, tmp_path)
    user_path = user_dir / "config.toml"
    user_path.parent.mkdir(parents=True)
    user_path.write_text(
        """
[plugins.analyzer-python]
enabled = true
include_paths = ["src"]

[plugins.backend-sqlite]
enabled = true
""".strip(),
        encoding="utf-8",
    )

    config = load_effective_config(
        env={},
        root=None,
    )
    mapping = config_to_mapping(config)
    plugins = cast("Mapping[str, object]", mapping["plugins"])

    assert plugins["analyzer-python"] == {
        "enabled": True,
        "include_paths": ["src"],
    }
    assert plugins["backend-sqlite"] == {"enabled": True}


def test_config_validation_rejects_invalid_plugin_table_names() -> None:
    """
    Reject plugin tables without analyzer or backend namespace prefixes.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test asserts invalid table names fail deterministically.
    """

    with pytest.raises(ConfigError, match="Plugin configuration tables"):
        validate_config_mapping({"plugins": {"python": {"enabled": True}}})


def test_profile_rendering_includes_gpu_profile_values() -> None:
    """
    Render generated profile TOML with deterministic values.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test asserts profile overrides are present in rendered TOML.
    """

    rendered = render_config_toml(profile_config("gpu"))

    assert "config_version = 1" in rendered
    assert 'device = "cuda"' in rendered
    assert "batch_size = 64" in rendered
    assert "[embeddings.gpu]" in rendered
    assert "device_id = 0" in rendered


def test_config_cli_init_and_dump_json(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """
    Create and dump a user config through the CLI.

    Parameters
    ----------
    monkeypatch : pytest.MonkeyPatch
        Fixture used to isolate config paths and argv.
    tmp_path : pathlib.Path
        Temporary config directory.
    capsys : pytest.CaptureFixture[str]
        Fixture used to capture command output.

    Returns
    -------
    None
        The test asserts config CLI init and JSON dump output.
    """

    _isolate_config_paths(monkeypatch, tmp_path)
    monkeypatch.setattr(
        sys, "argv", ["codira", "config", "init", "--profile", "low-memory"]
    )

    assert main() == 0

    monkeypatch.setattr(
        sys,
        "argv",
        ["codira", "config", "dump", "--level", "user", "--json"],
    )
    assert main() == 0

    captured = capsys.readouterr()
    payload = json.loads(captured.out[captured.out.index("{") :])
    assert payload["status"] == "ok"
    assert payload["results"]["embeddings"]["batch_size"] == 8


def test_config_cli_explain_reports_environment_origin(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """
    Explain one effective config key and report its origin.

    Parameters
    ----------
    monkeypatch : pytest.MonkeyPatch
        Fixture used to isolate config paths, environment, and argv.
    tmp_path : pathlib.Path
        Temporary config directory.
    capsys : pytest.CaptureFixture[str]
        Fixture used to capture command output.

    Returns
    -------
    None
        The test asserts environment-origin explanation output.
    """

    _isolate_config_paths(monkeypatch, tmp_path)
    monkeypatch.setenv("CODIRA_EMBED_BATCH_SIZE", "12")
    monkeypatch.setattr(
        sys,
        "argv",
        ["codira", "config", "explain", "embeddings.batch_size", "--json"],
    )

    assert main() == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["value"] == 12
    assert payload["origin"]["level"] == "environment"


def test_registry_filters_config_disabled_analyzers(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """
    Remove config-disabled analyzers from the active registry snapshot.

    Parameters
    ----------
    monkeypatch : pytest.MonkeyPatch
        Fixture used to isolate config paths and reset registry caches.
    tmp_path : pathlib.Path
        Temporary config directory.

    Returns
    -------
    None
        The test asserts disabled analyzers are reported as skipped.
    """

    user_dir, _system_dir = _isolate_config_paths(monkeypatch, tmp_path)
    write_config_file(user_dir / "config.toml")
    (user_dir / "config.toml").write_text(
        '[plugins]\ndisabled_analyzers = ["json"]\n',
        encoding="utf-8",
    )
    reset_plugin_registry_caches()

    from codira import registry

    analyzers = registry.active_language_analyzers()
    registrations = registry.plugin_registrations()

    assert "json" not in {analyzer.name for analyzer in analyzers}
    assert any(
        registration.name == "json"
        and registration.status == "skipped"
        and registration.detail == "analyzer is disabled by configuration"
        for registration in registrations
    )


def test_embedding_candidates_are_hidden_when_embeddings_are_disabled(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """
    Hide stored embedding candidates when config disables embeddings.

    Parameters
    ----------
    monkeypatch : pytest.MonkeyPatch
        Fixture used to isolate config paths and patch backend access.
    tmp_path : pathlib.Path
        Temporary config directory.

    Returns
    -------
    None
        The test asserts the backend is not queried when embeddings are
        disabled.
    """

    user_dir, _system_dir = _isolate_config_paths(monkeypatch, tmp_path)
    (user_dir).mkdir(parents=True)
    (user_dir / "config.toml").write_text(
        "[embeddings]\nenabled = false\n",
        encoding="utf-8",
    )

    def _unexpected_backend() -> object:
        msg = "backend should not be queried when embeddings are disabled"
        raise AssertionError(msg)

    monkeypatch.setattr(
        "codira.semantic.search.active_index_backend",
        _unexpected_backend,
    )

    assert embeddings_module.embeddings_enabled() is False
    assert (
        embedding_candidates(
            BackendEmbeddingCandidatesRequest(
                root=tmp_path,
                query="schema",
                limit=1,
                min_score=0.0,
            )
        )
        == []
    )


def test_config_to_mapping_round_trips_defaults(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """
    Convert default effective config into the public mapping shape.

    Parameters
    ----------
    monkeypatch : pytest.MonkeyPatch
        Fixture used to isolate config paths.
    tmp_path : pathlib.Path
        Temporary config directory.

    Returns
    -------
    None
        The test asserts the default mapping exposes public sections.
    """

    _isolate_config_paths(monkeypatch, tmp_path)

    mapping = config_to_mapping(load_effective_config(env={}))

    backend = mapping["backend"]
    embeddings = mapping["embeddings"]
    assert isinstance(backend, dict)
    assert isinstance(embeddings, dict)
    assert backend == {"name": "sqlite"}
    assert embeddings["enabled"] is True
    assert embeddings["gpu"] == {"device_id": 0, "memory_limit_mb": 0}


def test_config_validation_rejects_negative_gpu_memory_limit() -> None:
    """
    Reject invalid GPU calibration metadata values.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test asserts GPU memory limits are non-negative.
    """

    with pytest.raises(ConfigError, match="embeddings.gpu.memory_limit_mb"):
        validate_config_mapping(
            {"embeddings": {"gpu": {"memory_limit_mb": -1}}},
        )
