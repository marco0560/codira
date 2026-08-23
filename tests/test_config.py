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
from codira.daemon import DaemonState, DaemonStatus, DaemonStatusStore
from codira.registry import reset_plugin_registry_caches
from codira.semantic import embeddings as embeddings_module
from codira.semantic.search import embedding_candidates

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

    from codira.config import DaemonConfig


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


def test_daemon_config_round_trips_and_tracks_repo_origin(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Load daemon controls from the repository configuration level.

    Parameters
    ----------
    monkeypatch : pytest.MonkeyPatch
        Fixture used to isolate platform config paths.
    tmp_path : pathlib.Path
        Temporary repository root and configuration directory.

    Returns
    -------
    None
        The test asserts typed daemon settings and their origins round-trip.
    """

    _isolate_config_paths(monkeypatch, tmp_path)
    root = tmp_path / "repo"
    config_path = root / ".codira" / "config.toml"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(
        """
[daemon]
enabled = true
debounce_ms = 500
include_paths = ["src"]
exclude_paths = ["tests/fixtures"]
""",
        encoding="utf-8",
    )

    config = load_effective_config(root=root)

    assert config.daemon.enabled is True
    assert config.daemon.debounce_ms == 500
    assert config.daemon.include_paths == ("src",)
    assert config.daemon.exclude_paths == ("tests/fixtures",)
    assert config.origins["daemon.debounce_ms"].path == config_path
    assert config_to_mapping(config)["daemon"] == {
        "enabled": True,
        "debounce_ms": 500,
        "include_paths": ["src"],
        "exclude_paths": ["tests/fixtures"],
    }


@pytest.mark.parametrize(
    ("value", "message"),
    [
        ({"debounce_ms": 0}, "daemon.debounce_ms"),
        ({"include_paths": ["../outside"]}, "repo-relative"),
        ({"exclude_paths": ["/absolute"]}, "repo-relative"),
    ],
)
def test_daemon_config_rejects_unsafe_values(
    value: dict[str, object],
    message: str,
) -> None:
    """Reject invalid daemon configuration controls.

    Parameters
    ----------
    value : dict[str, object]
        Invalid daemon table supplied to validation.
    message : str
        Required stable diagnostic fragment.

    Returns
    -------
    None
        The test asserts invalid daemon controls fail deterministically.
    """

    with pytest.raises(ConfigError, match=message):
        validate_config_mapping({"daemon": value})


def test_query_daemon_config_defaults_disabled_and_tracks_repo_origin(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Load query-daemon enablement from repository configuration.

    Parameters
    ----------
    monkeypatch : pytest.MonkeyPatch
        Fixture used to isolate platform config paths.
    tmp_path : pathlib.Path
        Temporary repository root and configuration directory.

    Returns
    -------
    None
        The test asserts the initial query-daemon contract is disabled unless
        explicitly enabled by the repository configuration.
    """
    _isolate_config_paths(monkeypatch, tmp_path)
    root = tmp_path / "repo"
    config_path = root / ".codira" / "config.toml"
    config_path.parent.mkdir(parents=True)
    config_path.write_text("[query_daemon]\nenabled = true\n", encoding="utf-8")

    config = load_effective_config(root=root)

    assert config.query_daemon.enabled is True
    assert config.origins["query_daemon.enabled"].path == config_path
    assert config_to_mapping(config)["query_daemon"] == {"enabled": True}


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


def test_config_validation_accepts_documentation_audit_routes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """
    Accept ordered documentation audit routing rules under plugin globals.

    Parameters
    ----------
    monkeypatch : pytest.MonkeyPatch
        Fixture used to isolate config paths.
    tmp_path : pathlib.Path
        Temporary config directory.

    Returns
    -------
    None
        The test asserts route tables survive effective config loading.
    """

    user_dir, _system_dir = _isolate_config_paths(monkeypatch, tmp_path)
    user_path = user_dir / "config.toml"
    user_path.parent.mkdir(parents=True)
    user_path.write_text(
        """
[plugins]
documentation_audit_routes = [
  { language = "python", convention = "numpy", plugin = "numpy", include_paths = ["src/**"], exclude_paths = ["tests/**"] },
  { language = "python", convention = "google", plugin = "google" },
]

[plugins.documentation-audit-numpy]
enabled = true
""".strip(),
        encoding="utf-8",
    )

    config = load_effective_config(env={}, root=None)
    mapping = config_to_mapping(config)
    plugins = cast("Mapping[str, object]", mapping["plugins"])

    assert plugins["documentation_audit_routes"] == [
        {
            "language": "python",
            "convention": "numpy",
            "plugin": "numpy",
            "include_paths": ["src/**"],
            "exclude_paths": ["tests/**"],
        },
        {
            "language": "python",
            "convention": "google",
            "plugin": "google",
            "include_paths": [],
            "exclude_paths": [],
        },
    ]
    assert plugins["documentation-audit-numpy"] == {"enabled": True}
    assert config.plugins.documentation_audit_routes[0].plugin == "numpy"


def test_config_validation_rejects_invalid_documentation_audit_routes() -> None:
    """
    Reject malformed documentation audit routing rules.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test asserts missing required route fields fail deterministically.
    """

    with pytest.raises(
        ConfigError,
        match=r"plugins.documentation_audit_routes\[0\].plugin",
    ):
        validate_config_mapping(
            {
                "plugins": {
                    "documentation_audit_routes": [
                        {"language": "python", "convention": "numpy"}
                    ]
                }
            }
        )


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
    assert "work_batch_multiplier = 256" in rendered


def test_embedding_work_batch_multiplier_validation() -> None:
    """
    Validate the embedding indexing work-batch multiplier bounds.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test asserts the public multiplier rejects invalid values.
    """

    validate_config_mapping({"embeddings": {"indexing": {"work_batch_multiplier": 1}}})
    validate_config_mapping(
        {"embeddings": {"indexing": {"work_batch_multiplier": 4096}}}
    )

    with pytest.raises(
        ConfigError,
        match="embeddings.indexing.work_batch_multiplier",
    ):
        validate_config_mapping(
            {"embeddings": {"indexing": {"work_batch_multiplier": 0}}}
        )

    with pytest.raises(
        ConfigError,
        match="less than or equal to 4096",
    ):
        validate_config_mapping(
            {"embeddings": {"indexing": {"work_batch_multiplier": 4097}}}
        )


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
        "[index.concurrency]",
        "[index.coverage]",
        "[daemon]",
        "[query_daemon]",
        "[plugins.backend-sqlite]",
        "[plugins.backend-duckdb]",
        "[plugins.embedding-sentence-transformers]",
        "[plugins.embedding-onnx]",
        "[plugins.vector-store-sqlite]",
        "[plugins.vector-store-duckdb]",
        "[plugins.documentation-audit-numpy]",
        "[plugins.documentation-audit-google]",
        "[plugins.documentation-audit-doxygen]",
        "[plugins.documentation-audit-rustdoc]",
        "[plugins.analyzer-python]",
        "[plugins.analyzer-json]",
        "[plugins.analyzer-c]",
        "[plugins.analyzer-cpp]",
        "[plugins.analyzer-rust]",
        "[plugins.analyzer-bash]",
        "[plugins.analyzer-markdown]",
        "[plugins.analyzer-text]",
    ]
    assert "exclude_suffixes = []" in rendered
    assert "[plugins.analyzer-python]" in rendered
    assert "emit_module_documentation = true" in rendered
    assert "[plugins.analyzer-json]" in rendered
    assert 'enabled_families = ["schema", "package", "release"]' in rendered
    assert "[plugins.analyzer-c]" in rendered
    assert "emit_macros = true" in rendered
    assert "[plugins.analyzer-cpp]" in rendered
    assert "emit_namespaces = true" in rendered
    assert "[plugins.analyzer-rust]" in rendered
    assert "emit_macros = true" in rendered
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


def test_daemon_cli_reports_windows_scm_dependency_boundary(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Report that Windows service commands require the SCM dependency.

    Parameters
    ----------
    monkeypatch : pytest.MonkeyPatch
        Fixture used to isolate config paths, current directory, and argv.
    tmp_path : pathlib.Path
        Temporary repository root.
    capsys : pytest.CaptureFixture[str]
        Fixture used to capture the contract diagnostic.

    Returns
    -------
    None
        The test asserts Windows routing reports its missing optional dependency.
    """

    _isolate_config_paths(monkeypatch, tmp_path)
    root = tmp_path / "repo"
    root.mkdir()
    monkeypatch.chdir(root)
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(sys, "argv", ["codira", "daemon", "status"])

    assert main() == 2

    assert (
        "Windows daemon services require the pywin32 dependency"
        in capsys.readouterr().err
    )


def test_daemon_status_reports_durable_reconciliation_record(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Render repository-local reconciliation status with service activity.

    Parameters
    ----------
    monkeypatch : pytest.MonkeyPatch
        Fixture used to isolate platform routing and the systemd boundary.
    tmp_path : pathlib.Path
        Temporary repository root.
    capsys : pytest.CaptureFixture[str]
        Fixture used to capture the daemon status report.

    Returns
    -------
    None
        The test asserts service and durable reconciliation state are visible.
    """
    _isolate_config_paths(monkeypatch, tmp_path)
    root = tmp_path / "repo"
    root.mkdir()
    DaemonStatusStore(root).record(
        DaemonStatus(
            state=DaemonState.WATCHING,
            last_reconciled_commit="abc123",
        )
    )

    class Service:
        """Provide the minimal systemd status boundary for this CLI test.

        Parameters
        ----------
        root : pathlib.Path
            Repository root accepted by the service adapter boundary.

        Returns
        -------
        None
            The fixture does not retain state.
        """

        identifier = "codira-daemon-test.service"

        def __init__(self, root: Path) -> None:
            """Accept the repository root used by CLI platform routing.

            Parameters
            ----------
            root : pathlib.Path
                Repository root supplied by the CLI.

            Returns
            -------
            None
                The fixture has no mutable service state.
            """
            del root

        def status(self) -> object:
            """Return an active status compatible with the service contract.

            Parameters
            ----------
            None

            Returns
            -------
            object
                Minimal status object with an ``active`` attribute.
            """
            return type("Status", (), {"active": True})()

    monkeypatch.chdir(root)
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(sys, "argv", ["codira", "daemon", "status"])
    monkeypatch.setattr("codira.cli.SystemdUserService", Service)

    assert main() == 0

    output = capsys.readouterr().out
    assert "Systemd user unit codira-daemon-test.service: active" in output
    assert "Daemon reconciliation: watching; pending=False; commit=abc123" in output


def test_daemon_help_describes_available_lifecycle_commands(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Describe implemented daemon lifecycle operations in CLI help.

    Parameters
    ----------
    monkeypatch : pytest.MonkeyPatch
        Fixture used to set the CLI help arguments.
    capsys : pytest.CaptureFixture[str]
        Fixture used to capture rendered help output.

    Returns
    -------
    None
        The test asserts help does not label supported operations as planned.
    """
    monkeypatch.setattr(sys, "argv", ["codira", "daemon", "--help"])

    with pytest.raises(SystemExit, match="0"):
        main()

    output = capsys.readouterr().out
    assert "Lifecycle commands:" in output
    assert "Planned lifecycle commands" not in output
    assert "Windows SCM services" in output


def test_daemon_run_requires_explicit_enablement(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Reject foreground daemon mode until repository configuration enables it.

    Parameters
    ----------
    monkeypatch : pytest.MonkeyPatch
        Fixture used to isolate config paths, current directory, and argv.
    tmp_path : pathlib.Path
        Temporary repository root.
    capsys : pytest.CaptureFixture[str]
        Fixture used to capture the enablement diagnostic.

    Returns
    -------
    None
        The test asserts disabled-by-default daemon mode cannot start a watcher.
    """
    _isolate_config_paths(monkeypatch, tmp_path)
    root = tmp_path / "repo"
    root.mkdir()
    monkeypatch.chdir(root)
    monkeypatch.setattr(sys, "argv", ["codira", "daemon", "run"])

    assert main() == 2

    assert "daemon run requires daemon.enabled = true" in capsys.readouterr().err


def test_daemon_run_starts_foreground_runtime_when_enabled(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Dispatch enabled foreground daemon mode through the CLI.

    Parameters
    ----------
    monkeypatch : pytest.MonkeyPatch
        Fixture used to isolate config paths, current directory, argv, and the
        runtime boundary.
    tmp_path : pathlib.Path
        Temporary repository root.

    Returns
    -------
    None
        The test asserts the CLI passes the effective daemon configuration to
        foreground runtime without starting a watcher.
    """
    _isolate_config_paths(monkeypatch, tmp_path)
    root = tmp_path / "repo"
    root.mkdir()
    daemon_config_path = root / ".codira" / "config.toml"
    daemon_config_path.parent.mkdir()
    daemon_config_path.write_text("[daemon]\nenabled = true\n", encoding="utf-8")
    started: list[tuple[Path, object]] = []

    def start_runtime(runtime_root: Path, daemon_config: object) -> None:
        """Record CLI dispatch without starting watchfiles.

        Parameters
        ----------
        runtime_root : pathlib.Path
            Repository root supplied by the CLI.
        daemon_config : object
            Effective daemon configuration supplied by the CLI.

        Returns
        -------
        None
            The runtime invocation is recorded for assertions.
        """
        started.append((runtime_root, daemon_config))

    monkeypatch.chdir(root)
    monkeypatch.setattr(sys, "argv", ["codira", "daemon", "run"])
    monkeypatch.setattr("codira.cli.run_foreground_daemon", start_runtime)

    assert main() == 0

    assert started[0][0] == root
    assert cast("DaemonConfig", started[0][1]).enabled is True


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
    assert "[plugins.analyzer-rust]" in rendered
    assert "# emit_macros = true" in rendered
    assert "# include_paths = []" in rendered
    assert "[plugins.backend-sqlite]" in rendered
    assert "[plugins.documentation-audit-numpy]" in rendered


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
        "work_batch_multiplier": 256,
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


@pytest.mark.parametrize(
    ("roots", "accepted"),
    [
        ([], True),
        (["-"], True),
        (["src/**", "tests/**"], True),
        (["-", "src/**"], False),
        (["../src/**"], False),
    ],
)
def test_config_validation_handles_coverage_roots(
    roots: list[str], accepted: bool
) -> None:
    """Validate coverage-root fallback, opt-out, and path safety.

    Parameters
    ----------
    roots : list[str]
        Candidate coverage-root configuration.
    accepted : bool
        Whether validation should accept the candidate.

    Returns
    -------
    None
        The assertions verify the configured acceptance result.
    """

    payload = {"index": {"coverage": {"roots": roots}}}
    if accepted:
        validate_config_mapping(payload)
    else:
        with pytest.raises(ConfigError):
            validate_config_mapping(payload)


@pytest.mark.parametrize(
    ("exclude_suffixes", "accepted"),
    [
        ([], True),
        ([".yml", ".svg", "<no-suffix>"], True),
        (["YML"], False),
        (["."], False),
        (["docs/*.svg"], False),
        ([""], False),
    ],
)
def test_config_validation_handles_coverage_exclude_suffixes(
    exclude_suffixes: list[str], accepted: bool
) -> None:
    """Validate coverage suffix exclusions.

    Parameters
    ----------
    exclude_suffixes : list[str]
        Candidate suffix exclusion configuration.
    accepted : bool
        Whether validation should accept the candidate.

    Returns
    -------
    None
        The assertions verify accepted suffix syntax.
    """

    payload = {"index": {"coverage": {"exclude_suffixes": exclude_suffixes}}}
    if accepted:
        validate_config_mapping(payload)
    else:
        with pytest.raises(ConfigError):
            validate_config_mapping(payload)
