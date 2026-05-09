"""Tests for third-party plugin discovery and reporting.

Responsibilities
----------------
- Simulate entry-point loading, plugin registration, and analyzer/backend discovery flows.
- Assert that the registry reports active analyzers and backends with deterministic metadata.
- Verify CLI plugin listing and failure handling for loader exceptions.

Design principles
-----------------
Tests use fake distribution and entry-point fixtures so plugin discovery remains deterministic and isolated.

Architectural role
------------------
This module belongs to the **registry verification layer** and safeguards plugin discovery/reporting expectations.
"""

from __future__ import annotations

import importlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, cast

import pytest
from codira_backend_sqlite import SQLiteIndexBackend

import codira.registry as registry
from codira.cli import main
from codira.contracts import IndexBackend, LanguageAnalyzer
from codira.models import AnalysisResult, ModuleArtifact

if TYPE_CHECKING:
    from collections.abc import Callable


def _root_build_artifact_paths(repo_root: Path) -> set[Path]:
    """
    Return transient root-package build artifacts created by wheel builds.

    Parameters
    ----------
    repo_root : pathlib.Path
        Repository root whose transient build artifacts should be tracked.

    Returns
    -------
    set[pathlib.Path]
        Build and egg-info paths currently present for the root package.
    """
    paths: set[Path] = set()
    build_dir = repo_root / "build"
    if build_dir.exists():
        paths.add(build_dir)
    for egg_info_dir in sorted((repo_root / "src").glob("*.egg-info")):
        paths.add(egg_info_dir)
    return paths


def _cleanup_root_build_artifacts(
    repo_root: Path,
    *,
    before_paths: set[Path],
) -> None:
    """
    Remove transient root-package build artifacts created during one test run.

    Parameters
    ----------
    repo_root : pathlib.Path
        Repository root whose transient build artifacts should be cleaned.
    before_paths : set[pathlib.Path]
        Artifact paths that existed before the test started.

    Returns
    -------
    None
        Newly created build artifacts are removed in place.
    """
    for path in sorted(_root_build_artifact_paths(repo_root) - before_paths):
        shutil.rmtree(path, ignore_errors=True)


@dataclass(frozen=True)
class _FakeDistribution:
    """Minimal distribution record for fake entry points."""

    name: str


@dataclass(frozen=True)
class _FakeEntryPoint:
    """
    Minimal entry-point stub used for registry tests.

    Parameters
    ----------
    name : str
        Entry-point name exposed by the fake distribution.
    value : str
        Raw entry-point target string.
    dist : _FakeDistribution
        Fake distribution metadata owning the entry point.
    loaded : object
        Object or exception returned when the entry point is loaded.
    """

    name: str
    value: str
    dist: _FakeDistribution
    loaded: object

    def load(self) -> object:
        """
        Return or raise the configured load target.

        Parameters
        ----------
        None

        Returns
        -------
        object
            Loaded plugin object for the fake entry point.

        Raises
        ------
        Exception
            Re-raises the configured failure when ``loaded`` is an exception.
        """
        if isinstance(self.loaded, Exception):
            raise self.loaded
        return self.loaded


class _DemoAnalyzer:
    """
    Small analyzer plugin stub.

    Parameters
    ----------
    None
    """

    name = "demo"
    version = "1"
    discovery_globs: tuple[str, ...] = ("*.demo",)

    def supports_path(self, path: Path) -> bool:
        """
        Return whether the fake analyzer accepts the supplied path.

        Parameters
        ----------
        path : pathlib.Path
            Candidate repository path.

        Returns
        -------
        bool
            ``True`` when the path uses the ``.demo`` suffix.
        """
        return path.suffix == ".demo"

    def analyze_file(self, path: Path, root: Path) -> AnalysisResult:
        """
        Return an empty deterministic analysis result.

        Parameters
        ----------
        path : pathlib.Path
            Source path supplied to the analyzer.
        root : pathlib.Path
            Repository root supplied to the analyzer.

        Returns
        -------
        codira.models.AnalysisResult
            Empty normalized analysis result for the fake plugin.
        """
        del path, root
        return AnalysisResult(
            source_path=Path("demo.demo"),
            module=ModuleArtifact(
                name="demo",
                stable_id="demo:module:demo",
                docstring=None,
                has_docstring=0,
            ),
            classes=(),
            functions=(),
            declarations=(),
            imports=(),
        )


def _build_optional_first_party_analyzer(name: str) -> LanguageAnalyzer:
    """
    Build a deterministic first-party optional analyzer stub.

    Parameters
    ----------
    name : str
        Stable analyzer name exposed through the fake first-party entry point.

    Returns
    -------
    codira.contracts.LanguageAnalyzer
        Minimal analyzer instance compatible with registry validation.
    """

    class _OptionalFirstPartyAnalyzer(_DemoAnalyzer):
        """Small analyzer stub carrying one first-party optional name."""

        version = "1"
        discovery_globs: tuple[str, ...] = (f"*.{name}",)

        def supports_path(self, path: Path) -> bool:
            """
            Report support for the analyzer-specific suffix.

            Parameters
            ----------
            path : pathlib.Path
                Candidate repository path.

            Returns
            -------
            bool
                ``True`` when the suffix matches the analyzer name.
            """
            return path.suffix == f".{name}"

    analyzer = _OptionalFirstPartyAnalyzer()
    analyzer.name = name
    return cast("LanguageAnalyzer", analyzer)


def _build_c_analyzer() -> LanguageAnalyzer:
    """
    Build one fake first-party C analyzer.

    Parameters
    ----------
    None

    Returns
    -------
    codira.contracts.LanguageAnalyzer
        Deterministic C analyzer stub for registry tests.
    """
    return _build_optional_first_party_analyzer("c")


def _build_bash_analyzer() -> LanguageAnalyzer:
    """
    Build one fake first-party Bash analyzer.

    Parameters
    ----------
    None

    Returns
    -------
    codira.contracts.LanguageAnalyzer
        Deterministic Bash analyzer stub for registry tests.
    """
    return _build_optional_first_party_analyzer("bash")


def _build_python_analyzer() -> LanguageAnalyzer:
    """
    Build one fake first-party Python analyzer.

    Parameters
    ----------
    None

    Returns
    -------
    codira.contracts.LanguageAnalyzer
        Deterministic Python analyzer stub for registry tests.
    """
    return _build_optional_first_party_analyzer("python")


def _build_json_analyzer() -> LanguageAnalyzer:
    """
    Build one fake first-party JSON analyzer.

    Parameters
    ----------
    None

    Returns
    -------
    codira.contracts.LanguageAnalyzer
        Deterministic JSON analyzer stub for registry tests.
    """
    return _build_optional_first_party_analyzer("json")


class _DemoBackend(SQLiteIndexBackend):
    """Small backend plugin stub."""

    name = "demo-backend"


class _DemoDuckDBBackend(SQLiteIndexBackend):
    """Small DuckDB-shaped backend stub used for registry-selection tests."""

    name = "duckdb"


def _patch_entry_points(
    monkeypatch: pytest.MonkeyPatch,
    *,
    analyzers: list[_FakeEntryPoint],
    backends: list[_FakeEntryPoint],
) -> None:
    """
    Patch registry entry-point discovery for one test.

    Parameters
    ----------
    monkeypatch : pytest.MonkeyPatch
        Pytest fixture used to override registry discovery hooks.
    analyzers : list[_FakeEntryPoint]
        Fake analyzer entry points exposed during the test.
    backends : list[_FakeEntryPoint]
        Fake backend entry points exposed during the test.

    Returns
    -------
    None
        Registry entry-point discovery is patched in place.
    """

    def fake_group_loader(group: str) -> list[_FakeEntryPoint]:
        if group == registry.ANALYZER_ENTRY_POINT_GROUP:
            return analyzers
        if group == registry.BACKEND_ENTRY_POINT_GROUP:
            return backends
        return []

    monkeypatch.setattr(registry, "_entry_points_for_group", fake_group_loader)


def test_plugin_registrations_report_loaded_skipped_and_duplicate_plugins(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Report deterministic plugin discovery diagnostics across families.

    Parameters
    ----------
    monkeypatch : pytest.MonkeyPatch
        Pytest fixture used to patch entry-point discovery.

    Returns
    -------
    None
        The test asserts loaded, skipped, and duplicate plugin statuses.
    """
    _patch_entry_points(
        monkeypatch,
        analyzers=[
            _FakeEntryPoint(
                name="demo-analyzer",
                value="demo:analyzer",
                dist=_FakeDistribution("demo-analyzer"),
                loaded=_DemoAnalyzer,
            ),
            _FakeEntryPoint(
                name="dup-json",
                value="demo:dup",
                dist=_FakeDistribution("dup-analyzer"),
                loaded=type(
                    "_DuplicateDemoAnalyzer",
                    (),
                    {
                        "name": "demo",
                        "version": "1",
                        "discovery_globs": ("*.demo",),
                        "supports_path": lambda self, path: False,
                        "analyze_file": lambda self, path, root: AnalysisResult(
                            source_path=path,
                            module=ModuleArtifact(
                                name="dup",
                                stable_id="dup:module:dup",
                                docstring=None,
                                has_docstring=0,
                            ),
                            classes=(),
                            functions=(),
                            declarations=(),
                            imports=(),
                        ),
                    },
                ),
            ),
            _FakeEntryPoint(
                name="broken-analyzer",
                value="demo:broken",
                dist=_FakeDistribution("broken-analyzer"),
                loaded=RuntimeError("boom"),
            ),
        ],
        backends=[
            _FakeEntryPoint(
                name="demo-backend",
                value="demo:backend",
                dist=_FakeDistribution("demo-backend"),
                loaded=_DemoBackend,
            ),
        ],
    )

    registrations = registry.plugin_registrations()

    assert any(
        record.family == "analyzer"
        and record.name == "demo"
        and record.provider == "demo-analyzer"
        and record.status == "loaded"
        and record.origin == "third_party"
        for record in registrations
    )
    assert any(
        record.family == "analyzer"
        and record.name == "demo"
        and record.provider == "dup-analyzer"
        and record.status == "duplicate"
        for record in registrations
    )
    assert any(
        record.family == "analyzer"
        and record.provider == "broken-analyzer"
        and record.status == "skipped"
        and record.detail is not None
        and "RuntimeError" in record.detail
        for record in registrations
    )
    assert any(
        record.family == "backend"
        and record.name == "demo-backend"
        and record.status == "loaded"
        for record in registrations
    )


def test_active_registry_uses_loaded_entry_point_plugins(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Activate loaded analyzer and backend plugins from entry points.

    Parameters
    ----------
    monkeypatch : pytest.MonkeyPatch
        Pytest fixture used to patch entry-point discovery and backend config.

    Returns
    -------
    None
        The test asserts entry-point plugins participate in the active
        registry.
    """
    _patch_entry_points(
        monkeypatch,
        analyzers=[
            _FakeEntryPoint(
                name="demo-analyzer",
                value="demo:analyzer",
                dist=_FakeDistribution("demo-analyzer"),
                loaded=_DemoAnalyzer,
            )
        ],
        backends=[
            _FakeEntryPoint(
                name="demo-backend",
                value="demo:backend",
                dist=_FakeDistribution("demo-backend"),
                loaded=_DemoBackend,
            )
        ],
    )
    monkeypatch.setenv(registry.INDEX_BACKEND_ENV_VAR, "demo-backend")

    analyzers = registry.active_language_analyzers()
    backend = registry.active_index_backend()

    assert isinstance(analyzers[0], LanguageAnalyzer)
    analyzer_names = [analyzer.name for analyzer in analyzers]
    assert analyzer_names[0] == "demo"
    assert "demo" in analyzer_names
    assert isinstance(backend, IndexBackend)
    assert backend.name == "demo-backend"


def test_disable_third_party_plugins_skips_untrusted_entry_points(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Avoid loading third-party entry points when the hardening switch is set.

    Parameters
    ----------
    monkeypatch : pytest.MonkeyPatch
        Pytest fixture used to patch entry-point discovery and environment.

    Returns
    -------
    None
        The test asserts third-party plugins are reported as skipped without
        executing their entry-point loader while first-party plugins still load.
    """

    _patch_entry_points(
        monkeypatch,
        analyzers=[
            _FakeEntryPoint(
                name="demo-analyzer",
                value="demo:analyzer",
                dist=_FakeDistribution("demo-analyzer"),
                loaded=AssertionError("third-party loader should not execute"),
            ),
            _FakeEntryPoint(
                name="python-analyzer",
                value="codira:python",
                dist=_FakeDistribution("codira-analyzer-python"),
                loaded=_build_python_analyzer,
            ),
        ],
        backends=[],
    )
    monkeypatch.setenv("CODIRA_DISABLE_THIRD_PARTY_PLUGINS", "1")

    registrations = registry.plugin_registrations()

    assert any(
        record.family == "analyzer"
        and record.provider == "demo-analyzer"
        and record.status == "skipped"
        and record.origin == "third_party"
        and record.detail
        == "third-party plugins are disabled by CODIRA_DISABLE_THIRD_PARTY_PLUGINS"
        for record in registrations
    )
    assert any(
        record.family == "analyzer"
        and record.name == "python"
        and record.provider == "codira-analyzer-python"
        and record.status == "loaded"
        and record.origin == "first_party"
        for record in registrations
    )


def test_active_default_backend_comes_from_first_party_sqlite_package() -> None:
    """
    Keep the default backend runtime type owned by the first-party package.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test asserts the active default backend instance comes from the
        extracted first-party SQLite package.
    """
    backend = registry.active_index_backend()

    assert backend.__class__.__name__ == "SQLiteIndexBackend"
    assert backend.__class__.__module__ == "codira_backend_sqlite"


def test_registry_can_select_first_party_duckdb_backend_entry_point(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Resolve the DuckDB backend through normal first-party entry-point discovery.

    Parameters
    ----------
    monkeypatch : pytest.MonkeyPatch
        Pytest fixture used to patch backend discovery and environment.

    Returns
    -------
    None
        The test asserts the registry can activate the configured DuckDB
        backend and reports it as a first-party plugin.
    """
    _patch_entry_points(
        monkeypatch,
        analyzers=[],
        backends=[
            _FakeEntryPoint(
                name="duckdb-backend",
                value="codira_backend_duckdb:build_backend",
                dist=_FakeDistribution("codira-backend-duckdb"),
                loaded=_DemoDuckDBBackend,
            )
        ],
    )
    monkeypatch.setenv(registry.INDEX_BACKEND_ENV_VAR, "duckdb")

    backend = registry.active_index_backend()
    registrations = registry.plugin_registrations()

    assert isinstance(backend, IndexBackend)
    assert backend.name == "duckdb"
    assert any(
        record.family == "backend"
        and record.name == "duckdb"
        and record.provider == "codira-backend-duckdb"
        and record.status == "loaded"
        and record.origin == "first_party"
        for record in registrations
    )


def test_plugins_cli_emits_json_registration_diagnostics(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """
    Emit plugin registrations through the dedicated CLI command.

    Parameters
    ----------
    monkeypatch : pytest.MonkeyPatch
        Pytest fixture used to patch entry-point discovery and argv.
    capsys : pytest.CaptureFixture[str]
        Pytest fixture used to capture CLI output.

    Returns
    -------
    None
        The test asserts the CLI JSON includes discovered plugin records.
    """
    _patch_entry_points(
        monkeypatch,
        analyzers=[
            _FakeEntryPoint(
                name="demo-analyzer",
                value="demo:analyzer",
                dist=_FakeDistribution("demo-analyzer"),
                loaded=_DemoAnalyzer,
            )
        ],
        backends=[],
    )
    monkeypatch.setattr(sys, "argv", ["codira", "plugins", "--json"])

    assert main() == 0
    payload = json.loads(capsys.readouterr().out)

    assert payload["command"] == "plugins"
    assert payload["status"] == "ok"
    assert any(
        row["family"] == "analyzer"
        and row["name"] == "demo"
        and row["provider"] == "demo-analyzer"
        and row["origin"] == "third_party"
        and row["status"] == "loaded"
        for row in payload["results"]
    )


def test_plugin_snapshot_cache_reuses_entry_point_discovery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Reuse one resolved registry snapshot within the current process.

    Parameters
    ----------
    monkeypatch : pytest.MonkeyPatch
        Pytest fixture used to patch entry-point discovery.

    Returns
    -------
    None
        The test asserts repeated registry reads do not rediscover entry points
        while the cache remains valid.
    """
    call_counts = {
        registry.ANALYZER_ENTRY_POINT_GROUP: 0,
        registry.BACKEND_ENTRY_POINT_GROUP: 0,
    }

    def fake_group_loader(group: str) -> list[_FakeEntryPoint]:
        call_counts[group] += 1
        if group == registry.ANALYZER_ENTRY_POINT_GROUP:
            return [
                _FakeEntryPoint(
                    name="demo-analyzer",
                    value="demo:analyzer",
                    dist=_FakeDistribution("demo-analyzer"),
                    loaded=_DemoAnalyzer,
                )
            ]
        if group == registry.BACKEND_ENTRY_POINT_GROUP:
            return [
                _FakeEntryPoint(
                    name="demo-backend",
                    value="demo:backend",
                    dist=_FakeDistribution("demo-backend"),
                    loaded=_DemoBackend,
                )
            ]
        return []

    registry.reset_plugin_registry_caches()
    monkeypatch.setattr(registry, "_entry_points_for_group", fake_group_loader)

    first = registry.plugin_registrations()
    second = registry.plugin_registrations()

    assert first == second
    assert call_counts == {
        registry.ANALYZER_ENTRY_POINT_GROUP: 1,
        registry.BACKEND_ENTRY_POINT_GROUP: 1,
    }


def test_plugin_snapshot_cache_respects_third_party_toggle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Rebuild the registry snapshot when third-party loading policy changes.

    Parameters
    ----------
    monkeypatch : pytest.MonkeyPatch
        Pytest fixture used to patch entry-point discovery and environment.

    Returns
    -------
    None
        The test asserts the disable-third-party toggle does not reuse a stale
        snapshot built under different policy.
    """
    _patch_entry_points(
        monkeypatch,
        analyzers=[
            _FakeEntryPoint(
                name="demo-analyzer",
                value="demo:analyzer",
                dist=_FakeDistribution("demo-analyzer"),
                loaded=_DemoAnalyzer,
            ),
            _FakeEntryPoint(
                name="python-analyzer",
                value="codira:python",
                dist=_FakeDistribution("codira-analyzer-python"),
                loaded=_build_python_analyzer,
            ),
        ],
        backends=[],
    )
    registry.reset_plugin_registry_caches()

    enabled = registry.plugin_registrations()

    monkeypatch.setenv(registry.DISABLE_THIRD_PARTY_PLUGINS_ENV_VAR, "1")
    disabled = registry.plugin_registrations()

    assert any(
        record.provider == "demo-analyzer" and record.status == "loaded"
        for record in enabled
    )
    assert any(
        record.provider == "demo-analyzer" and record.status == "skipped"
        for record in disabled
    )


def test_version_cli_groups_curated_bundle_plugins(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """
    Print core and curated first-party plugin versions through ``codira -V``.

    Parameters
    ----------
    monkeypatch : pytest.MonkeyPatch
        Pytest fixture used to patch CLI metadata lookups and argv.
    capsys : pytest.CaptureFixture[str]
        Pytest fixture used to capture CLI output.

    Returns
    -------
    None
        The test asserts the version report groups first-party plugins under
        the installed curated bundle marker.
    """
    monkeypatch.setattr("codira.cli.__version__", "9.9.9")
    monkeypatch.setattr(
        "codira.cli.installed_distribution_version",
        lambda name: "0.9.0" if name == "codira-bundle-official" else None,
    )
    monkeypatch.setattr(
        "codira.cli.plugin_registrations",
        lambda: [
            registry.PluginRegistration(
                family="analyzer",
                name="python",
                provider="codira-analyzer-python",
                source="entry_point",
                status="loaded",
                version="0.1.0",
                origin="first_party",
            ),
            registry.PluginRegistration(
                family="backend",
                name="sqlite",
                provider="codira-backend-sqlite",
                source="entry_point",
                status="loaded",
                version="0.1.0",
                origin="first_party",
            ),
        ],
    )
    monkeypatch.setattr(sys, "argv", ["codira", "-V"])

    assert main() == 0
    assert capsys.readouterr().out.splitlines() == [
        "codira 9.9.9",
        "bundle-official 0.9.0",
        "  analyzer python 0.1.0",
        "  backend sqlite 0.1.0",
    ]


def test_version_cli_lists_third_party_plugins_when_bundle_is_absent(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """
    Print third-party plugin versions when no curated bundle is installed.

    Parameters
    ----------
    monkeypatch : pytest.MonkeyPatch
        Pytest fixture used to patch CLI metadata lookups and argv.
    capsys : pytest.CaptureFixture[str]
        Pytest fixture used to capture CLI output.

    Returns
    -------
    None
        The test asserts the version report stays concise when only third-party
        plugins are loaded.
    """
    monkeypatch.setattr("codira.cli.__version__", "9.9.9")
    monkeypatch.setattr(
        "codira.cli.installed_distribution_version",
        lambda _name: None,
    )
    monkeypatch.setattr(
        "codira.cli.plugin_registrations",
        lambda: [
            registry.PluginRegistration(
                family="analyzer",
                name="demo",
                provider="demo-analyzer",
                source="entry_point",
                status="loaded",
                version="1",
                origin="third_party",
            )
        ],
    )
    monkeypatch.setattr(sys, "argv", ["codira", "--version"])

    assert main() == 0
    assert capsys.readouterr().out.splitlines() == [
        "codira 9.9.9",
        "third-party plugins:",
        "  analyzer demo 1",
    ]


def test_core_can_discover_installed_first_party_packages_from_built_wheels(
    tmp_path: Path,
) -> None:
    """
    Discover first-party plugins from installed wheel artifacts outside the repo.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary directory managed by pytest.

    Returns
    -------
    None
        The test asserts core plugin discovery works from installed wheel
        artifacts without relying on the repository checkout as `cwd`.
    """
    repo_root = Path(__file__).resolve().parents[1]
    wheel_dir = tmp_path / "wheels"
    install_dir = tmp_path / "site-packages"
    build_artifacts_before = _root_build_artifact_paths(repo_root)

    try:
        subprocess.run(
            [
                sys.executable,
                "scripts/build_first_party_packages.py",
                "--wheel-dir",
                str(wheel_dir),
            ],
            cwd=repo_root,
            check=True,
            capture_output=True,
            text=True,
        )
        subprocess.run(
            [
                sys.executable,
                "-m",
                "pip",
                "wheel",
                "--no-build-isolation",
                "--no-deps",
                "--wheel-dir",
                str(wheel_dir),
                str(repo_root),
            ],
            cwd=repo_root,
            check=True,
            capture_output=True,
            text=True,
        )
    finally:
        _cleanup_root_build_artifacts(repo_root, before_paths=build_artifacts_before)

    wheel_paths = sorted(str(path) for path in wheel_dir.glob("*.whl"))
    assert wheel_paths

    subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--no-deps",
            "--target",
            str(install_dir),
            *wheel_paths,
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    env = os.environ.copy()
    env["PYTHONPATH"] = str(install_dir)
    env["PYTHONNOUSERSITE"] = "1"
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import json, codira, codira.registry as registry; "
                "backend = registry.active_index_backend(); "
                "analyzers = registry.active_language_analyzers(); "
                "print(json.dumps({"
                "'codira_file': codira.__file__, "
                "'backend_module': type(backend).__module__, "
                "'analyzers': [analyzer.name for analyzer in analyzers]"
                "}))"
            ),
        ],
        cwd=tmp_path,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )

    payload = json.loads(result.stdout)

    assert Path(payload["codira_file"]).is_relative_to(install_dir)
    assert payload["backend_module"] == "codira_backend_sqlite"
    assert payload["analyzers"] == ["python", "json", "c", "bash"]


def test_registry_orders_first_party_analyzers_across_sources(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Keep analyzer order stable across built-in and entry-point sources.

    Parameters
    ----------
    monkeypatch : pytest.MonkeyPatch
        Fixture used to patch registry entry-point discovery.

    Returns
    -------
    None
        The test asserts Python, JSON, C, and Bash load as first-party
        entry-point plugins in the final routing order.
    """
    _patch_entry_points(
        monkeypatch,
        analyzers=[
            _FakeEntryPoint(
                name="python",
                value="codira_analyzer_python:build_analyzer",
                dist=_FakeDistribution("codira-analyzer-python"),
                loaded=_build_python_analyzer,
            ),
            _FakeEntryPoint(
                name="json",
                value="codira_analyzer_json:build_analyzer",
                dist=_FakeDistribution("codira-analyzer-json"),
                loaded=_build_json_analyzer,
            ),
            _FakeEntryPoint(
                name="c",
                value="codira_analyzer_c:build_analyzer",
                dist=_FakeDistribution("codira-analyzer-c"),
                loaded=_build_c_analyzer,
            ),
            _FakeEntryPoint(
                name="bash",
                value="codira_analyzer_bash:build_analyzer",
                dist=_FakeDistribution("codira-analyzer-bash"),
                loaded=_build_bash_analyzer,
            ),
        ],
        backends=[],
    )

    analyzer_names = [
        analyzer.name for analyzer in registry.active_language_analyzers()
    ]
    registrations = registry.plugin_registrations()

    assert analyzer_names == ["python", "json", "c", "bash"]
    assert any(
        record.family == "analyzer"
        and record.name == "python"
        and record.provider == "codira-analyzer-python"
        and record.source == "entry_point"
        and record.origin == "first_party"
        and record.status == "loaded"
        for record in registrations
    )
    assert any(
        record.family == "analyzer"
        and record.name == "json"
        and record.provider == "codira-analyzer-json"
        and record.source == "entry_point"
        and record.origin == "first_party"
        and record.status == "loaded"
        for record in registrations
    )
    assert any(
        record.family == "analyzer"
        and record.name == "c"
        and record.provider == "codira-analyzer-c"
        and record.source == "entry_point"
        and record.origin == "first_party"
        and record.status == "loaded"
        for record in registrations
    )
    assert any(
        record.family == "analyzer"
        and record.name == "bash"
        and record.provider == "codira-analyzer-bash"
        and record.source == "entry_point"
        and record.origin == "first_party"
        and record.status == "loaded"
        for record in registrations
    )


def test_compatibility_shims_do_not_fall_back_to_checkout_local_package_sources(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Keep analyzer compatibility imports limited to installed distributions.

    Parameters
    ----------
    monkeypatch : pytest.MonkeyPatch
        Fixture used to force shim imports to behave as if first-party packages
        are not installed.

    Returns
    -------
    None
        The test asserts the shims raise operator-facing install hints without
        probing monorepo-local `packages/.../src` paths.
    """
    repo_root = Path(__file__).resolve().parents[1]
    shim_cases = (
        (
            "src/codira/analyzers/python.py",
            "codira_analyzer_python",
            "codira-analyzer-python",
        ),
        (
            "src/codira/analyzers/json.py",
            "codira_analyzer_json",
            "codira-analyzer-json",
        ),
        (
            "src/codira/analyzers/c.py",
            "codira_analyzer_c",
            "codira-analyzer-c",
        ),
        (
            "src/codira/analyzers/bash.py",
            "codira_analyzer_bash",
            "codira-analyzer-bash",
        ),
    )

    for relative_path, package_module, package_distribution in shim_cases:
        source_path = repo_root / relative_path
        original_import_module = cast(
            "Callable[[str, str | None], object]",
            importlib.import_module,
        )

        def _reject_first_party_import(
            name: str,
            package: str | None = None,
            *,
            _package_module: str = package_module,
            _original_import_module: Callable[[str, str | None], object] = (
                original_import_module
            ),
        ) -> object:
            if name == _package_module:
                raise ModuleNotFoundError(name=name)
            return _original_import_module(name, package)

        monkeypatch.setattr(importlib, "import_module", _reject_first_party_import)
        spec = importlib.util.spec_from_file_location(
            f"test_{package_module}_shim",
            source_path,
        )
        assert spec is not None
        assert spec.loader is not None
        shim_module = importlib.util.module_from_spec(spec)

        with pytest.raises(ModuleNotFoundError) as exc_info:
            spec.loader.exec_module(shim_module)

        assert package_distribution in str(exc_info.value)
        assert (repo_root / "packages" / package_distribution / "src").is_dir()
        monkeypatch.undo()
