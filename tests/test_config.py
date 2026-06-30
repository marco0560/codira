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
    effective_config_cache,
    full_profile_config,
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


def test_effective_config_cache_reuses_file_backed_loads(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """
    Reuse merged file-backed config within one command-scoped cache.

    Parameters
    ----------
    monkeypatch : pytest.MonkeyPatch
        Fixture used to isolate config paths and count file reads.
    tmp_path : pathlib.Path
        Temporary repository and config root.

    Returns
    -------
    None
        The test asserts repeated default-environment loads read TOML once.
    """

    user_dir, _system_dir = _isolate_config_paths(monkeypatch, tmp_path)
    root = tmp_path / "repo"
    root.mkdir()
    user_path = user_dir / "config.toml"
    user_path.parent.mkdir(parents=True)
    user_path.write_text("[embeddings]\nbatch_size = 16\n", encoding="utf-8")

    original_read_config_file = config_module._read_config_file
    read_paths: list[Path] = []

    def counting_read_config_file(path: Path) -> dict[str, object]:
        read_paths.append(path)
        return original_read_config_file(path)

    monkeypatch.setattr(
        config_module,
        "_read_config_file",
        counting_read_config_file,
    )

    with effective_config_cache():
        first = load_effective_config(root=root)
        second = load_effective_config(root=root)

    assert first is second
    assert first.embeddings.batch_size == 16
    assert read_paths == [user_path]


def test_effective_config_cache_does_not_cache_explicit_env(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """
    Keep explicit environment mappings outside the command-scoped cache.

    Parameters
    ----------
    monkeypatch : pytest.MonkeyPatch
        Fixture used to isolate config paths.
    tmp_path : pathlib.Path
        Temporary repository and config root.

    Returns
    -------
    None
        The test asserts explicit ``env`` values are evaluated independently.
    """

    _isolate_config_paths(monkeypatch, tmp_path)
    root = tmp_path / "repo"
    root.mkdir()

    with effective_config_cache():
        first = load_effective_config(
            root=root,
            env={"CODIRA_EMBED_BATCH_SIZE": "3"},
        )
        second = load_effective_config(
            root=root,
            env={"CODIRA_EMBED_BATCH_SIZE": "7"},
        )

    assert first.embeddings.batch_size == 3
    assert second.embeddings.batch_size == 7
    assert first is not second


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

[plugins.embedding-sentence-transformers]
enabled = true

[plugins.vector-store-sqlite]
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
    assert plugins["embedding-sentence-transformers"] == {"enabled": True}
    assert plugins["vector-store-sqlite"] == {"enabled": True}


def test_config_validation_rejects_invalid_plugin_table_names() -> None:
    """
    Reject plugin tables without supported namespace prefixes.

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
    assert "[embeddings.indexing]" in rendered
    assert 'mode = "immediate"' in rendered
    assert 'object_types = ["symbol", "documentation"]' in rendered


def test_full_profile_rendering_includes_first_party_plugin_defaults() -> None:
    """
    Render a full generated profile with all first-party plugin defaults.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test asserts the full template exposes all default plugin options.
    """

    rendered = render_config_toml(full_profile_config("default"))
    section_order = [line for line in rendered.splitlines() if line.startswith("[")]

    assert section_order == [
        "[backend]",
        "[plugins]",
        "[embeddings]",
        "[embeddings.gpu]",
        "[embeddings.indexing]",
        "[plugins.backend-sqlite]",
        "[plugins.backend-duckdb]",
        "[plugins.embedding-sentence-transformers]",
        "[plugins.embedding-onnx]",
        "[plugins.vector-store-sqlite]",
        "[plugins.vector-store-duckdb]",
        "[plugins.analyzer-python]",
        "[plugins.analyzer-json]",
        "[plugins.analyzer-c]",
        "[plugins.analyzer-cpp]",
        "[plugins.analyzer-bash]",
        "[plugins.analyzer-markdown]",
        "[plugins.analyzer-text]",
    ]
    assert "[plugins.analyzer-python]" in rendered
    assert "emit_module_documentation = true" in rendered
    assert "[plugins.analyzer-json]" in rendered
    assert 'enabled_families = ["schema", "package", "release"]' in rendered
    assert "[plugins.analyzer-c]" in rendered
    assert "emit_macros = true" in rendered
    assert "[plugins.analyzer-cpp]" in rendered
    assert "emit_namespaces = true" in rendered
    assert "[plugins.backend-sqlite]" in rendered
    assert "[plugins.backend-duckdb]" in rendered
    assert "profiling_enabled = false" in rendered
    assert "[plugins.embedding-sentence-transformers]" in rendered
    assert "[plugins.embedding-onnx]" in rendered
    assert "max_tokens = 512" in rendered
    assert "[plugins.vector-store-sqlite]" in rendered
    assert "[plugins.vector-store-duckdb]" in rendered


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
        sys,
        "argv",
        ["codira", "config", "init", "--level", "user", "--profile", "low-memory"],
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
    rendered = config_module.user_config_path().read_text(encoding="utf-8")
    assert "# config_version = 1" in rendered
    assert "# enabled = true" in rendered
    assert "batch_size = 8" in rendered
    assert "# batch_size = 32" not in rendered


def test_config_cli_init_defaults_to_repo_config(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """
    Create a repository config by default through the CLI.

    Parameters
    ----------
    monkeypatch : pytest.MonkeyPatch
        Fixture used to isolate config paths and argv.
    tmp_path : pathlib.Path
        Temporary repository root.

    Returns
    -------
    None
        The test asserts the default init target is repo-local.
    """

    _isolate_config_paths(monkeypatch, tmp_path)
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    monkeypatch.chdir(repo_root)
    monkeypatch.setattr(sys, "argv", ["codira", "config", "init"])

    assert main() == 0

    repo_config = repo_root / ".codira" / "config.toml"
    assert repo_config.exists()
    assert not config_module.user_config_path().exists()
    assert "# config_version = 1" in repo_config.read_text(encoding="utf-8")


def test_config_cli_config_file_overrides_repo_config(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """
    Use an explicit repo-level config file for effective config resolution.

    Parameters
    ----------
    monkeypatch : pytest.MonkeyPatch
        Fixture used to isolate config paths and argv.
    tmp_path : pathlib.Path
        Temporary repository root.
    capsys : pytest.CaptureFixture[str]
        Fixture used to capture CLI output.

    Returns
    -------
    None
        The test asserts ``--config-file`` replaces the default repo config
        path without changing the output directory.
    """

    _isolate_config_paths(monkeypatch, tmp_path)
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    default_repo_config = repo_root / ".codira" / "config.toml"
    default_repo_config.parent.mkdir()
    default_repo_config.write_text("[embeddings]\nbatch_size = 5\n", encoding="utf-8")
    override_config = tmp_path / "override.toml"
    override_config.write_text("[embeddings]\nbatch_size = 7\n", encoding="utf-8")
    monkeypatch.chdir(repo_root)
    monkeypatch.setattr(
        sys,
        "argv",
        ["codira", "config", "dump", "--config-file", str(override_config), "--json"],
    )

    assert main() == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "ok"
    assert payload["results"]["embeddings"]["batch_size"] == 7


def test_config_cli_init_config_file_writes_requested_target(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """
    Write an explicit repository config file through ``config init``.

    Parameters
    ----------
    monkeypatch : pytest.MonkeyPatch
        Fixture used to isolate config paths and argv.
    tmp_path : pathlib.Path
        Temporary repository root.

    Returns
    -------
    None
        The test asserts ``--config-file`` changes only the repo config target.
    """

    _isolate_config_paths(monkeypatch, tmp_path)
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    override_config = tmp_path / "configs" / "repo.toml"
    monkeypatch.chdir(repo_root)
    monkeypatch.setattr(
        sys,
        "argv",
        ["codira", "config", "init", "--config-file", str(override_config)],
    )

    assert main() == 0

    assert override_config.exists()
    assert not (repo_root / ".codira" / "config.toml").exists()


def test_config_cli_init_full_writes_plugin_defaults(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """
    Create a full user config through the CLI.

    Parameters
    ----------
    monkeypatch : pytest.MonkeyPatch
        Fixture used to isolate config paths and argv.
    tmp_path : pathlib.Path
        Temporary config directory.

    Returns
    -------
    None
        The test asserts ``config init --full`` writes plugin default tables.
    """

    _isolate_config_paths(monkeypatch, tmp_path)
    monkeypatch.setattr(
        sys,
        "argv",
        ["codira", "config", "init", "--level", "user", "--full"],
    )

    assert main() == 0

    rendered = config_module.user_config_path().read_text(encoding="utf-8")
    assert "[plugins.analyzer-cpp]" in rendered
    assert "# emit_macros = true" in rendered
    assert "# include_paths = []" in rendered
    assert "[plugins.backend-sqlite]" in rendered


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


def test_config_cli_explain_reports_embedding_indexing_origin(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """
    Explain a default embedding indexing config key.

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
        The test asserts nested embedding indexing defaults are explainable.
    """

    _isolate_config_paths(monkeypatch, tmp_path)
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    monkeypatch.chdir(repo_root)
    monkeypatch.setattr(
        sys,
        "argv",
        ["codira", "config", "explain", "embeddings.indexing.mode", "--json"],
    )

    assert main() == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["value"] == "immediate"
    assert payload["origin"]["level"] == "defaults"


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

    def _unexpected_backend(*, root: Path | None = None) -> object:
        del root
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
    assert embeddings["indexing"] == {
        "mode": "immediate",
        "object_types": ["symbol", "documentation"],
        "max_text_chars": 0,
        "include_paths": [],
        "exclude_paths": [],
    }


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


def test_config_validation_rejects_invalid_embedding_indexing_values() -> None:
    """
    Reject unsupported embedding indexing controls.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test asserts mode, object type, text length, and path validation.
    """

    with pytest.raises(ConfigError, match="embeddings.indexing.mode"):
        validate_config_mapping({"embeddings": {"indexing": {"mode": "later"}}})
    with pytest.raises(ConfigError, match="embeddings.indexing.object_types"):
        validate_config_mapping(
            {"embeddings": {"indexing": {"object_types": ["symbol", "symbol"]}}},
        )
    with pytest.raises(ConfigError, match="embeddings.indexing.object_types"):
        validate_config_mapping(
            {"embeddings": {"indexing": {"object_types": ["unknown"]}}},
        )
    with pytest.raises(ConfigError, match="embeddings.indexing.max_text_chars"):
        validate_config_mapping(
            {"embeddings": {"indexing": {"max_text_chars": -1}}},
        )
    with pytest.raises(ConfigError, match="embeddings.indexing.exclude_paths"):
        validate_config_mapping(
            {"embeddings": {"indexing": {"exclude_paths": [""]}}},
        )
