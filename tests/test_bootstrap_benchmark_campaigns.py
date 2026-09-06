"""Tests for repository bootstrap and package-install helper scripts.

Responsibilities
----------------
- Verify the authoritative first-party editable package list stays deterministic.
- Ensure bootstrap command generation uses the shared package-install helper contract.
- Keep bootstrap and CI package-boundary assumptions aligned to one repository-owned source of truth.

Design principles
-----------------
The tests validate command construction rather than executing package installs,
so packaging drift is caught quickly without network or environment noise.

Architectural role
------------------
This module belongs to the **tooling verification layer** guarding repository-local bootstrap workflows.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, cast

import pytest
from bootstrap_package_expectations import (
    EXPECTED_FIRST_PARTY_PACKAGE_DIRS,
    EXPECTED_NON_BUNDLE_PACKAGE_DIRS,
    _editable_args,
    _expected_monorepo_package_paths,
    _expected_split_package_paths,
)

if TYPE_CHECKING:
    import argparse
    from collections.abc import Mapping, Sequence
    from types import ModuleType

    from scripts.bootstrap_dev_environment import CommandSpec
    from scripts.install_first_party_packages import (
        InstallCommandRequest as InstallCommandRequestType,
    )


class _InstallHelperModule(Protocol):
    """Protocol for the standalone first-party install helper module."""

    FIRST_PARTY_EDITABLE_PACKAGES: tuple[str, ...]
    InstallCommandRequest: type[InstallCommandRequestType]

    def first_party_package_root(
        self,
        repo_root: Path,
        package_root: Path | None,
    ) -> Path:
        """
        Return the directory containing first-party package repositories.

        Parameters
        ----------
        repo_root : pathlib.Path
            Repository root used when no package root override is supplied.
        package_root : pathlib.Path | None
            Optional explicit package root.

        Returns
        -------
        pathlib.Path
            Directory containing first-party package repositories.
        """
        ...

    def editable_core_requirement(
        self,
        repo_root: Path,
        *,
        extras: tuple[str, ...] = (),
    ) -> str:
        """
        Return the editable requirement string for the core package.

        Parameters
        ----------
        repo_root : pathlib.Path
            Repository root for the editable core package.
        extras : tuple[str, ...], optional
            Optional extras to include in the requirement string.

        Returns
        -------
        str
            Editable requirement string for the core package.
        """
        ...

    def editable_package_paths(
        self,
        repo_root: Path,
        *,
        package_root: Path | None = None,
    ) -> tuple[Path, ...]:
        """
        Return package paths in deterministic order.

        Parameters
        ----------
        repo_root : pathlib.Path
            Repository root used to resolve package paths.
        package_root : pathlib.Path | None, optional
            Optional package directory override.

        Returns
        -------
        tuple[pathlib.Path, ...]
            Editable package paths in deterministic order.
        """
        ...

    def bundle_package_path(
        self,
        repo_root: Path,
        *,
        package_root: Path | None = None,
    ) -> Path:
        """
        Return the bundle package path.

        Parameters
        ----------
        repo_root : pathlib.Path
            Repository root used to resolve the package path.
        package_root : pathlib.Path | None, optional
            Optional package directory override.

        Returns
        -------
        pathlib.Path
            Bundle package path.
        """
        ...

    def non_bundle_package_paths(
        self,
        repo_root: Path,
        *,
        package_root: Path | None = None,
    ) -> tuple[Path, ...]:
        """
        Return first-party package paths excluding the bundle package.

        Parameters
        ----------
        repo_root : pathlib.Path
            Repository root used to resolve package paths.
        package_root : pathlib.Path | None, optional
            Optional package directory override.

        Returns
        -------
        tuple[pathlib.Path, ...]
            First-party package paths excluding the bundle package.
        """
        ...

    def build_install_commands(
        self,
        request: InstallCommandRequestType,
    ) -> tuple[tuple[str, ...], ...]:
        """
        Build the editable-install command plan for first-party packages.

        Parameters
        ----------
        request : scripts.install_first_party_packages.InstallCommandRequest
            Command construction request.

        Returns
        -------
        tuple[tuple[str, ...], ...]
            Editable-install command plan.
        """
        ...


class _PackageInventoryModule(Protocol):
    """Protocol for the shared first-party package inventory helper."""

    FIRST_PARTY_PACKAGE_DIRS: tuple[str, ...]

    def package_paths(self, repo_root: Path) -> tuple[Path, ...]:
        """
        Return package paths in deterministic order.

        Parameters
        ----------
        repo_root : pathlib.Path
            Repository root used to resolve package paths.

        Returns
        -------
        tuple[pathlib.Path, ...]
            Package paths in deterministic order.
        """
        ...


class _GitConfigInstallModule(Protocol):
    """Protocol for the standalone repo Git configuration installer."""

    def git_alias_entries(self) -> list[tuple[str, str]]:
        """
        Return repo-local Git config entries to install.

        Parameters
        ----------
        None

        Returns
        -------
        list[tuple[str, str]]
            Git config key-value entries to install.
        """
        ...


class _GithubSnapshotModule(Protocol):
    """Protocol for the GitHub planning snapshot generator."""

    OWNER: str
    REPOSITORY: str


class _BuildHelperModule(Protocol):
    """Protocol for the standalone first-party build helper module."""

    def build_build_argv(
        self,
        *,
        python: str,
        package_path: Path,
        wheel_dir: Path,
    ) -> tuple[str, ...]:
        """
        Build the wheel-validation argv for one package.

        Parameters
        ----------
        python : str
            Python executable used in the command.
        package_path : pathlib.Path
            Package root being built.
        wheel_dir : pathlib.Path
            Directory receiving wheel artifacts.

        Returns
        -------
        tuple[str, ...]
            Wheel-validation command arguments.
        """
        ...

    def build_all_argv(
        self,
        *,
        python: str,
        repo_root: Path,
        wheel_dir: Path,
    ) -> tuple[tuple[str, ...], ...]:
        """
        Build the complete wheel-validation command plan.

        Parameters
        ----------
        python : str
            Python executable used in generated commands.
        repo_root : pathlib.Path
            Repository root used to discover packages.
        wheel_dir : pathlib.Path
            Directory receiving wheel artifacts.

        Returns
        -------
        tuple[tuple[str, ...], ...]
            Complete wheel-validation command plan.
        """
        ...

    def cleanup_build_artifacts(self, package_path: Path) -> None:
        """
        Remove known package-local wheel-build artifacts.

        Parameters
        ----------
        package_path : pathlib.Path
            Package root whose build artifacts should be removed.

        Returns
        -------
        None
            Matching package-local artifacts are removed in place.
        """
        ...


class _ReleaseInstallRehearsalModule(Protocol):
    """Protocol for the installed-wheel release rehearsal helper."""

    def build_first_party_wheels_argv(
        self,
        *,
        python: str,
        repo_root: Path,
        wheel_dir: Path,
    ) -> tuple[str, ...]:
        """
        Build the first-party wheel-rehearsal command.

        Parameters
        ----------
        python : str
            Python executable used in the command.
        repo_root : pathlib.Path
            Repository root containing first-party packages.
        wheel_dir : pathlib.Path
            Directory receiving wheel artifacts.

        Returns
        -------
        tuple[str, ...]
            First-party wheel-rehearsal command arguments.
        """
        ...

    def build_root_wheel_argv(
        self,
        *,
        python: str,
        repo_root: Path,
        wheel_dir: Path,
    ) -> tuple[str, ...]:
        """
        Build the core wheel-rehearsal command.

        Parameters
        ----------
        python : str
            Python executable used in the command.
        repo_root : pathlib.Path
            Repository root for the core package.
        wheel_dir : pathlib.Path
            Directory receiving wheel artifacts.

        Returns
        -------
        tuple[str, ...]
            Core wheel-rehearsal command arguments.
        """
        ...

    def discover_wheel_paths(self, wheel_dir: Path) -> tuple[Path, ...]:
        """
        Return built wheel paths in deterministic order.

        Parameters
        ----------
        wheel_dir : pathlib.Path
            Directory containing built wheel artifacts.

        Returns
        -------
        tuple[pathlib.Path, ...]
            Built wheel paths in deterministic order.
        """
        ...

    def build_install_wheels_argv(
        self,
        *,
        python: str,
        install_dir: Path,
        wheel_paths: tuple[Path, ...],
    ) -> tuple[str, ...]:
        """
        Build the installed-wheel rehearsal install command.

        Parameters
        ----------
        python : str
            Python executable used in the command.
        install_dir : pathlib.Path
            Target directory for installed wheel contents.
        wheel_paths : tuple[pathlib.Path, ...]
            Wheel artifacts to install.

        Returns
        -------
        tuple[str, ...]
            Installed-wheel rehearsal install command arguments.
        """
        ...

    def build_probe_argv(self, *, python: str) -> tuple[str, ...]:
        """
        Build the installed-wheel discovery probe command.

        Parameters
        ----------
        python : str
            Python executable used in the command.

        Returns
        -------
        tuple[str, ...]
            Installed-wheel discovery probe command arguments.
        """
        ...


class _ReleaseArtifactBuildModule(Protocol):
    """Protocol for the release-artifact build helper."""

    def release_package_paths(self, repo_root: Path) -> tuple[Path, ...]:
        """
        Return release package roots in deterministic order.

        Parameters
        ----------
        repo_root : pathlib.Path
            Repository root used to discover release packages.

        Returns
        -------
        tuple[pathlib.Path, ...]
            Release package roots in deterministic order.
        """
        ...

    def build_artifact_argv(
        self,
        *,
        python: str,
        package_path: Path,
    ) -> tuple[str, ...]:
        """
        Build the release artifact command for one package root.

        Parameters
        ----------
        python : str
            Python executable used in the command.
        package_path : pathlib.Path
            Package root for the release artifact.

        Returns
        -------
        tuple[str, ...]
            Release artifact command arguments.
        """
        ...

    def artifact_check_argv(
        self,
        *,
        python: str,
        package_path: Path,
    ) -> tuple[str, ...]:
        """
        Build the twine-check command for one package root.

        Parameters
        ----------
        python : str
            Python executable used in the command.
        package_path : pathlib.Path
            Package root whose artifact should be checked.

        Returns
        -------
        tuple[str, ...]
            Twine-check command arguments.
        """
        ...

    def build_release_plan(
        self,
        *,
        python: str,
        repo_root: Path,
    ) -> tuple[tuple[str, ...], ...]:
        """
        Build the ordered release-artifact plan.

        Parameters
        ----------
        python : str
            Python executable used in generated commands.
        repo_root : pathlib.Path
            Repository root used to discover release packages.

        Returns
        -------
        tuple[tuple[str, ...], ...]
            Ordered release-artifact command plan.
        """
        ...


class _BenchmarkConfigFactory(Protocol):
    """Protocol for constructing release benchmark configuration objects."""

    def __call__(
        self,
        *,
        hyperfine: str,
        codira: str,
        output: Path,
        runs: int,
        warmup: int,
        query: str,
    ) -> object:
        """
        Build one benchmark configuration object.

        Parameters
        ----------
        hyperfine : str
            Hyperfine executable to invoke.
        codira : str
            Codira executable to benchmark.
        output : pathlib.Path
            JSON output path.
        runs : int
            Measured Hyperfine runs per command.
        warmup : int
            Warmup runs per command.
        query : str
            Query text used for the context benchmark.

        Returns
        -------
        object
            Benchmark configuration accepted by the helper module.
        """
        ...


class _ReleaseBenchmarkModule(Protocol):
    """Protocol for the release Hyperfine benchmark helper."""

    DEFAULT_OUTPUT: Path
    BenchmarkConfig: _BenchmarkConfigFactory

    def benchmark_command_strings(self, *, codira: str, query: str) -> tuple[str, ...]:
        """
        Return shell-quoted Codira commands measured by Hyperfine.

        Parameters
        ----------
        codira : str
            Codira executable to benchmark.
        query : str
            Query text used for the context benchmark.

        Returns
        -------
        tuple[str, ...]
            Command strings passed to Hyperfine.
        """
        ...

    def build_hyperfine_argv(self, config: object) -> tuple[str, ...]:
        """
        Build the Hyperfine release benchmark argv.

        Parameters
        ----------
        config : BenchmarkConfig
            Benchmark configuration.

        Returns
        -------
        tuple[str, ...]
            Complete Hyperfine argv.
        """
        ...

    def resolve_output_path(self, root: Path, output: Path) -> Path:
        """
        Resolve the Hyperfine JSON output path.

        Parameters
        ----------
        root : pathlib.Path
            Repository root used for relative output paths.
        output : pathlib.Path
            Configured output path.

        Returns
        -------
        pathlib.Path
            Absolute output path.
        """
        ...


class _BenchmarkTimingModule(Protocol):
    """Protocol for the shared benchmark timing helper."""

    FIRST_PARTY_PLUGIN_PROVIDERS: tuple[str, ...]

    def first_party_plugin_providers(self) -> tuple[str, ...]:
        """
        Return first-party plugin providers expected in benchmark metadata.

        Parameters
        ----------
        None

        Returns
        -------
        tuple[str, ...]
            First-party analyzer and backend distribution names.
        """
        ...

    def benchmark_metadata(
        self,
        root: Path,
        *,
        manifest: Path | None = None,
        hyperfine: str = "hyperfine",
    ) -> dict[str, object]:
        """
        Build common benchmark artifact metadata.

        Parameters
        ----------
        root : pathlib.Path
            Repository root associated with the benchmark run.
        manifest : pathlib.Path | None, optional
            Campaign manifest path.
        hyperfine : str, optional
            Hyperfine executable checked for availability.

        Returns
        -------
        dict[str, object]
            JSON-serializable benchmark metadata.
        """
        ...


class _BenchmarkCampaignModule(Protocol):
    """Protocol for the benchmark campaign helper."""

    CampaignConfig: type
    RepositoryBenchmark: type
    ResolvedRepositoryBenchmark: type
    subprocess: object

    def build_parser(self) -> argparse.ArgumentParser:
        """
        Build the benchmark campaign parser.

        Parameters
        ----------
        None

        Returns
        -------
        object
            Configured parser object.
        """
        ...

    def load_manifest(self, path: Path) -> tuple[object, ...]:
        """
        Load benchmark repositories from a manifest.

        Parameters
        ----------
        path : pathlib.Path
            Manifest path to read.

        Returns
        -------
        tuple[object, ...]
            Repository benchmark targets.
        """
        ...

    MANIFEST_BENCHMARK_SUBCOMMANDS: frozenset[str]

    def run_directory(self, config: object) -> Path:
        """
        Return the campaign run directory.

        Parameters
        ----------
        config : object
            Campaign configuration.

        Returns
        -------
        pathlib.Path
            Run artifact directory.
        """
        ...

    def utility_summary_path(self, repo: object, config: object) -> Path:
        """
        Return the utility-summary artifact path.

        Parameters
        ----------
        repo : object
            Resolved repository benchmark target.
        config : object
            Campaign configuration.

        Returns
        -------
        pathlib.Path
            Utility-summary artifact path.
        """
        ...

    def index_output_dir(self, repo: object, config: object) -> Path:
        """
        Return the repository benchmark index directory.

        Parameters
        ----------
        repo : object
            Resolved repository benchmark target.
        config : object
            Campaign configuration.

        Returns
        -------
        pathlib.Path
            Repository-local benchmark index directory.
        """
        ...

    def summarize_profile(
        self,
        profile: Path,
        *,
        limit: int = 20,
    ) -> list[dict[str, object]]:
        """
        Summarize one cProfile artifact.

        Parameters
        ----------
        profile : pathlib.Path
            Profile artifact to read.
        limit : int, optional
            Maximum number of rows to report.

        Returns
        -------
        list[dict[str, object]]
            Profile summary or unreadable-profile diagnostic rows.
        """
        ...

    def write_utility_summary(self, repo: object, config: object) -> None:
        """
        Write one utility-summary artifact.

        Parameters
        ----------
        repo : object
            Resolved repository benchmark target.
        config : object
            Campaign configuration.

        Returns
        -------
        None
            The summary is written when Hyperfine data is present.
        """
        ...

    def command_plan(
        self,
        repositories: tuple[object, ...],
        config: object,
    ) -> list[dict[str, object]]:
        """
        Build benchmark campaign command rows.

        Parameters
        ----------
        repositories : tuple[object, ...]
            Repository benchmark targets.
        config : object
            Campaign configuration.

        Returns
        -------
        list[dict[str, object]]
            JSON-serializable command plan rows.
        """
        ...

    def resolve_repositories(
        self,
        repositories: tuple[object, ...],
        config: object,
    ) -> tuple[object, ...]:
        """
        Resolve adaptive benchmark selections for all repositories.

        Parameters
        ----------
        repositories : tuple[object, ...]
            Repository benchmark targets.
        config : object
            Campaign configuration.

        Returns
        -------
        tuple[object, ...]
            Resolved repository benchmark targets.
        """
        ...

    def _run_command(self, command: tuple[str, ...], *, output_log: Path) -> int:
        """
        Execute one benchmark campaign command.

        Parameters
        ----------
        command : tuple[str, ...]
            Command vector to execute.
        output_log : pathlib.Path
            File that receives combined command output.

        Returns
        -------
        int
            Process exit status.
        """
        ...

    def main(self) -> int:
        """
        Run the benchmark campaign entry point.

        Parameters
        ----------
        None

        Returns
        -------
        int
            Process exit status.
        """
        ...


class _ManifestBaselineModule(Protocol):
    """Protocol for the paired backend benchmark baseline helper."""

    def build_parser(self) -> argparse.ArgumentParser:
        """
        Build the manifest baseline parser.

        Parameters
        ----------
        None

        Returns
        -------
        argparse.ArgumentParser
            Parser for baseline campaign options.
        """
        ...


class _FinalEmbeddingCampaignModule(Protocol):
    """Protocol for the final embedding model campaign helper."""

    def parse_args(self, argv: list[str] | None = None) -> argparse.Namespace:
        """
        Parse final campaign arguments.

        Parameters
        ----------
        argv : list[str] | None, optional
            Explicit command-line arguments.

        Returns
        -------
        argparse.Namespace
            Parsed campaign arguments.
        """
        ...

    def concrete_backends(self, backend_mode: str) -> tuple[str, ...]:
        """
        Return concrete backend phases for a requested backend mode.

        Parameters
        ----------
        backend_mode : str
            Requested backend mode.

        Returns
        -------
        tuple[str, ...]
            Concrete backend names.
        """
        ...

    def read_models(self, model_manifest_path: Path) -> tuple[object, ...]:
        """
        Read model entries from a manifest.

        Parameters
        ----------
        model_manifest_path : pathlib.Path
            Model manifest path.

        Returns
        -------
        tuple[object, ...]
            Model entries.
        """
        ...

    def render_model_config(self, model: object, backend_mode: str) -> str:
        """
        Render one model-specific Codira config.

        Parameters
        ----------
        model : object
            Model entry.
        backend_mode : str
            Concrete backend name.

        Returns
        -------
        str
            TOML configuration text.
        """
        ...


class _ResolvedBenchmarkRepository(Protocol):
    """Protocol for one adaptively resolved benchmark repository."""

    query: str
    commands: tuple[tuple[str, ...], ...]
    skipped_commands: tuple[tuple[str, ...], ...]


class _SplitRepoVerificationModule(Protocol):
    """Protocol for the exported split-repo verification helper."""

    def split_repo_names(self) -> tuple[str, ...]:
        """
        Return split repository names in deterministic validation order.

        Parameters
        ----------
        None

        Returns
        -------
        tuple[str, ...]
            Split repository names in deterministic validation order.
        """
        ...

    def build_repo_validation_commands(
        self,
        *,
        python: str,
        exported_repo_root: Path,
        core_repo_root: Path,
    ) -> tuple[tuple[str, ...], ...]:
        """
        Build the validation command plan for one exported split repository.

        Parameters
        ----------
        python : str
            Python executable used in generated commands.
        exported_repo_root : pathlib.Path
            Exported split repository root to validate.
        core_repo_root : pathlib.Path
            Core repository root used for shared context.

        Returns
        -------
        tuple[tuple[str, ...], ...]
            Validation command plan for one exported split repository.
        """
        ...


class _BootstrapHelperModule(Protocol):
    """Protocol for the standalone bootstrap helper module."""

    def build_bootstrap_commands(
        self,
        *,
        repo_root: Path,
        python: str,
        skip_validation: bool,
    ) -> list[CommandSpec]:
        """
        Build the ordered bootstrap command plan.

        Parameters
        ----------
        repo_root : pathlib.Path
            Repository root to bootstrap.
        python : str
            Python executable used in generated commands.
        skip_validation : bool
            Whether validation commands should be omitted.

        Returns
        -------
        list[scripts.bootstrap_dev_environment.CommandSpec]
            Ordered bootstrap command plan.
        """
        ...


class _RepoToolRunnerModule(Protocol):
    """Protocol for the repository tool runner helper."""

    subprocess: object

    def tool_state_root(
        self, repo_root: Path, *, temp_root: Path | None = None
    ) -> Path:
        """
        Return the per-checkout tool-state root.

        Parameters
        ----------
        repo_root : pathlib.Path
            Repository root for the current checkout.
        temp_root : pathlib.Path | None, optional
            Temporary root override.

        Returns
        -------
        pathlib.Path
            Tool-state root outside the repository.
        """
        ...

    def tool_environment(
        self,
        base_env: Mapping[str, str],
        *,
        state_root: Path,
    ) -> dict[str, str]:
        """
        Build the redirected tool environment.

        Parameters
        ----------
        base_env : collections.abc.Mapping[str, str]
            Baseline process environment.
        state_root : pathlib.Path
            Non-repository state root.

        Returns
        -------
        dict[str, str]
            Child process environment.
        """
        ...

    def create_pytest_basetemp(self, state_root: Path) -> Path:
        """
        Reserve a unique pytest base temporary directory path.

        Parameters
        ----------
        state_root : pathlib.Path
            Non-repository state root.

        Returns
        -------
        pathlib.Path
            Unique pytest base temporary directory path.
        """
        ...

    def build_tool_argv(
        self,
        tool: str,
        tool_args: tuple[str, ...],
        *,
        state_root: Path,
        python: str,
        pytest_basetemp: Path | None = None,
    ) -> tuple[str, ...]:
        """
        Build the redirected tool argument vector.

        Parameters
        ----------
        tool : str
            Supported tool name.
        tool_args : tuple[str, ...]
            Tool arguments.
        state_root : pathlib.Path
            Non-repository state root.
        python : str
            Python executable.
        pytest_basetemp : pathlib.Path | None, optional
            Explicit pytest base temporary directory.

        Returns
        -------
        tuple[str, ...]
            Complete command argument vector.
        """
        ...

    def split_black_serial_args(
        self,
        tool_args: tuple[str, ...],
    ) -> tuple[tuple[str, ...], list[str]]:
        """
        Split black arguments into options and path targets.

        Parameters
        ----------
        tool_args : tuple[str, ...]
            Arguments passed after ``black-serial``.

        Returns
        -------
        tuple[tuple[str, ...], list[str]]
            Black options and path targets.
        """
        ...

    def run_black_serial(
        self,
        tool_args: tuple[str, ...],
        *,
        env: Mapping[str, str],
        python: str,
    ) -> int:
        """
        Run Black one target at a time.

        Parameters
        ----------
        tool_args : tuple[str, ...]
            Black arguments supplied to ``black-serial``.
        env : collections.abc.Mapping[str, str]
            Environment for Black child processes.
        python : str
            Python executable used to invoke Black.

        Returns
        -------
        int
            Exit status from the serial Black run.
        """
        ...


class _ValidationHelperModule(Protocol):
    """Protocol for the repository validation helper."""

    REPO_ROOT: Path
    RUN_REPO_TOOL: Path
    COMPLETE_SEMGREP_ARTIFACT_ROOT: Path
    PERSONAL_SECRETS_DIR: Path
    subprocess: ModuleType

    def first_party_package_typecheck_paths(
        self,
        root: Path = ...,
    ) -> tuple[str, ...]:
        """
        Return deterministic first-party package source and test roots.

        Parameters
        ----------
        root : pathlib.Path
            Repository root containing first-party packages.

        Returns
        -------
        tuple[str, ...]
            Repository-relative source and test paths for mypy.
        """
        ...

    def build_parser(self) -> argparse.ArgumentParser:
        """
        Build the validator command-line parser.

        Parameters
        ----------
        None

        Returns
        -------
        argparse.ArgumentParser
            Parser for validator command-line options.
        """
        ...

    def build_validation_steps(
        self,
        *,
        include_semgrep_complete: bool = False,
    ) -> tuple[object, ...]:
        """
        Build the ordered validation steps for one invocation.

        Parameters
        ----------
        include_semgrep_complete : bool, optional
            Whether to append the broader Semgrep registry scan.

        Returns
        -------
        tuple[object, ...]
            Ordered validator step objects.
        """
        ...

    def complete_semgrep_output_path(self, *, now: object | None = None) -> Path:
        """
        Build the timestamped complete-Semgrep artifact path.

        Parameters
        ----------
        now : object | None, optional
            Explicit timestamp override used by tests.

        Returns
        -------
        pathlib.Path
            Timestamped JSON artifact path under the analysis artifact root.
        """
        ...

    def relative_report_path(self, path: Path) -> str:
        """
        Return the repository-relative label for one report path.

        Parameters
        ----------
        path : pathlib.Path
            Saved report path.

        Returns
        -------
        str
            Repository-relative label when possible.
        """
        ...

    def build_validation_commands(
        self,
        *,
        python: str = sys.executable,
        include_semgrep_complete: bool = False,
    ) -> tuple[tuple[str, ...], ...]:
        """
        Build validation command vectors.

        Parameters
        ----------
        python : str, optional
            Python executable used to invoke the tool runner.
        include_semgrep_complete : bool, optional
            Whether to append the broader Semgrep registry scan.

        Returns
        -------
        tuple[tuple[str, ...], ...]
            Ordered validation command vectors.
        """
        ...

    def run_validation(
        self,
        commands: tuple[tuple[str, ...], ...] | None = None,
    ) -> int:
        """
        Execute validation command vectors.

        Parameters
        ----------
        commands : tuple[tuple[str, ...], ...] | None, optional
            Explicit command vectors to execute.

        Returns
        -------
        int
            Validation exit status.
        """
        ...

    def render_validation_commands(
        self,
        commands: tuple[tuple[str, ...], ...],
    ) -> str:
        """
        Render validation commands for dry-run output.

        Parameters
        ----------
        commands : tuple[tuple[str, ...], ...]
            Command vectors that would be executed.

        Returns
        -------
        str
            Shell-quoted dry-run output.
        """
        ...

    def main(self, argv: Sequence[str] | None = None) -> int:
        """
        Run the validator entry point with explicit arguments.

        Parameters
        ----------
        argv : collections.abc.Sequence[str] | None, optional
            Explicit command-line arguments.

        Returns
        -------
        int
            Process exit status.
        """
        ...


def _load_first_party_package_inventory() -> _PackageInventoryModule:
    """
    Load the shared first-party package inventory helper.

    Parameters
    ----------
    None

    Returns
    -------
    object
        Loaded module object for the shared package inventory helper.
    """
    helper_path = (
        Path(__file__).resolve().parents[1] / "scripts" / "first_party_packages.py"
    )
    spec = importlib.util.spec_from_file_location("first_party_packages", helper_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return cast("_PackageInventoryModule", module)


def _load_install_helper() -> _InstallHelperModule:
    """
    Load the standalone install helper module from its repository path.

    Parameters
    ----------
    None

    Returns
    -------
    object
        Loaded module object for the install helper script.
    """
    helper_path = (
        Path(__file__).resolve().parents[1]
        / "scripts"
        / "install_first_party_packages.py"
    )
    sys.path.insert(0, str(helper_path.parent))
    spec = importlib.util.spec_from_file_location(
        "install_first_party_packages", helper_path
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return cast("_InstallHelperModule", module)


def _load_git_config_install_helper() -> _GitConfigInstallModule:
    """
    Load the repo Git configuration installer from its repository path.

    Parameters
    ----------
    None

    Returns
    -------
    object
        Loaded module object for the Git configuration installer.
    """
    helper_path = (
        Path(__file__).resolve().parents[1] / "scripts" / "install_repo_git_config.py"
    )
    spec = importlib.util.spec_from_file_location(
        "install_repo_git_config", helper_path
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return cast("_GitConfigInstallModule", module)


def _load_github_snapshot_helper() -> _GithubSnapshotModule:
    """
    Load the GitHub planning snapshot helper from its repository path.

    Parameters
    ----------
    None

    Returns
    -------
    object
        Loaded module object for the snapshot generator script.
    """
    helper_path = (
        Path(__file__).resolve().parents[1] / "scripts" / "generate_github_snapshot.py"
    )
    spec = importlib.util.spec_from_file_location(
        "generate_github_snapshot",
        helper_path,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return cast("_GithubSnapshotModule", module)


def _load_build_helper() -> _BuildHelperModule:
    """
    Load the standalone build helper module from its repository path.

    Parameters
    ----------
    None

    Returns
    -------
    object
        Loaded module object for the build helper script.
    """
    helper_path = (
        Path(__file__).resolve().parents[1]
        / "scripts"
        / "build_first_party_packages.py"
    )
    sys.path.insert(0, str(helper_path.parent))
    spec = importlib.util.spec_from_file_location(
        "build_first_party_packages",
        helper_path,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return cast("_BuildHelperModule", module)


def _load_bootstrap_helper() -> _BootstrapHelperModule:
    """
    Load the standalone bootstrap helper module from its repository path.

    Parameters
    ----------
    None

    Returns
    -------
    object
        Loaded module object for the bootstrap script.
    """
    helper_path = (
        Path(__file__).resolve().parents[1] / "scripts" / "bootstrap_dev_environment.py"
    )
    spec = importlib.util.spec_from_file_location(
        "bootstrap_dev_environment",
        helper_path,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return cast("_BootstrapHelperModule", module)


def _load_repo_tool_runner() -> _RepoToolRunnerModule:
    """
    Load the repository tool runner helper from its repository path.

    Parameters
    ----------
    None

    Returns
    -------
    object
        Loaded module object for the tool runner script.
    """
    helper_path = Path(__file__).resolve().parents[1] / "scripts" / "run_repo_tool.py"
    spec = importlib.util.spec_from_file_location("run_repo_tool", helper_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return cast("_RepoToolRunnerModule", module)


def _load_validation_helper() -> _ValidationHelperModule:
    """
    Load the repository validation helper from its repository path.

    Parameters
    ----------
    None

    Returns
    -------
    object
        Loaded module object for the validation helper script.
    """
    helper_path = Path(__file__).resolve().parents[1] / "scripts" / "validate_repo.py"
    spec = importlib.util.spec_from_file_location("validate_repo", helper_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return cast("_ValidationHelperModule", module)


def _load_release_install_rehearsal_helper() -> _ReleaseInstallRehearsalModule:
    """
    Load the installed-wheel release rehearsal helper from its repository path.

    Parameters
    ----------
    None

    Returns
    -------
    object
        Loaded module object for the installed-wheel rehearsal helper script.
    """
    helper_path = (
        Path(__file__).resolve().parents[1] / "scripts" / "rehearse_release_installs.py"
    )
    spec = importlib.util.spec_from_file_location(
        "rehearse_release_installs",
        helper_path,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return cast("_ReleaseInstallRehearsalModule", module)


def _load_release_artifact_build_helper() -> _ReleaseArtifactBuildModule:
    """
    Load the release-artifact build helper from its repository path.

    Parameters
    ----------
    None

    Returns
    -------
    object
        Loaded module object for the release-artifact build helper script.
    """
    helper_path = (
        Path(__file__).resolve().parents[1] / "scripts" / "build_release_artifacts.py"
    )
    spec = importlib.util.spec_from_file_location(
        "build_release_artifacts",
        helper_path,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return cast("_ReleaseArtifactBuildModule", module)


def _load_release_benchmark_helper() -> _ReleaseBenchmarkModule:
    """
    Load the release Hyperfine benchmark helper from its repository path.

    Parameters
    ----------
    None

    Returns
    -------
    object
        Loaded module object for the release benchmark helper script.
    """
    helper_path = (
        Path(__file__).resolve().parents[1] / "scripts" / "benchmark_release.py"
    )
    spec = importlib.util.spec_from_file_location(
        "benchmark_release",
        helper_path,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return cast("_ReleaseBenchmarkModule", module)


def _load_benchmark_timing_helper() -> _BenchmarkTimingModule:
    """
    Load the shared benchmark timing helper from its repository path.

    Parameters
    ----------
    None

    Returns
    -------
    object
        Loaded module object for the benchmark timing helper script.
    """
    helper_path = (
        Path(__file__).resolve().parents[1] / "scripts" / "benchmark_timing.py"
    )
    spec = importlib.util.spec_from_file_location("benchmark_timing", helper_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return cast("_BenchmarkTimingModule", module)


class _EmbeddingStartupBenchmarkModule(Protocol):
    """Protocol for the standalone embedding-startup benchmark helper."""

    def measure_embedding_startup(
        self,
        *,
        text: str,
        second_text: str,
    ) -> dict[str, object]:
        """
        Measure same-process semantic startup and warm-query costs.

        Parameters
        ----------
        text : str
            Text payload used for the cold query measurement.
        second_text : str
            Text payload used for the warm query measurement.

        Returns
        -------
        dict[str, object]
            Structured timing report.
        """
        ...


class _BenchmarkIndexModule(Protocol):
    """Protocol for the standalone index phase benchmark helper."""

    def active_backend_class(self, root: Path) -> type[object]:
        """
        Return the active backend class selected for the benchmark run.

        Parameters
        ----------
        root : pathlib.Path
            Repository root whose repo-local config selects the backend.

        Returns
        -------
        type[object]
            Concrete backend class selected for the current process.
        """
        ...

    def active_backend_support_module(self, root: Path) -> ModuleType:
        """
        Return the support module selected for benchmark instrumentation.

        Parameters
        ----------
        root : pathlib.Path
            Repository root whose repo-local config selects the backend.

        Returns
        -------
        types.ModuleType
            Imported backend-owned helper module for the current backend.
        """
        ...


def _load_benchmark_campaign_helper() -> _BenchmarkCampaignModule:
    """
    Load the benchmark campaign helper from its repository path.

    Parameters
    ----------
    None

    Returns
    -------
    object
        Loaded module object for the benchmark campaign helper script.
    """
    helper_path = (
        Path(__file__).resolve().parents[1] / "scripts" / "benchmark_campaign.py"
    )
    sys.path.insert(0, str(helper_path.parent))
    spec = importlib.util.spec_from_file_location("benchmark_campaign", helper_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return cast("_BenchmarkCampaignModule", module)


def _load_manifest_baseline_helper() -> _ManifestBaselineModule:
    """
    Load the paired backend baseline helper from its repository path.

    Parameters
    ----------
    None

    Returns
    -------
    object
        Loaded module object for the paired backend baseline helper.
    """
    helper_path = (
        Path(__file__).resolve().parents[1] / "scripts" / "run_manifest_baseline.py"
    )
    sys.path.insert(0, str(helper_path.parent))
    spec = importlib.util.spec_from_file_location("run_manifest_baseline", helper_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return cast("_ManifestBaselineModule", module)


def _load_final_embedding_campaign_helper() -> _FinalEmbeddingCampaignModule:
    """
    Load the final embedding model campaign helper from its repository path.

    Parameters
    ----------
    None

    Returns
    -------
    object
        Loaded module object for the final embedding campaign helper.
    """
    helper_path = (
        Path(__file__).resolve().parents[1]
        / "scripts"
        / "run_final_embedding_model_campaign.py"
    )
    sys.path.insert(0, str(helper_path.parent))
    spec = importlib.util.spec_from_file_location(
        "run_final_embedding_model_campaign",
        helper_path,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return cast("_FinalEmbeddingCampaignModule", module)


def _load_embedding_startup_benchmark_helper() -> _EmbeddingStartupBenchmarkModule:
    """
    Load the embedding-startup benchmark helper from its repository path.

    Parameters
    ----------
    None

    Returns
    -------
    object
        Loaded module object for the embedding-startup benchmark helper script.
    """
    helper_path = (
        Path(__file__).resolve().parents[1]
        / "scripts"
        / "benchmark_embedding_startup.py"
    )
    sys.path.insert(0, str(helper_path.parent))
    spec = importlib.util.spec_from_file_location(
        "benchmark_embedding_startup",
        helper_path,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return cast("_EmbeddingStartupBenchmarkModule", module)


def _load_benchmark_index_helper() -> _BenchmarkIndexModule:
    """
    Load the index phase benchmark helper from its repository path.

    Parameters
    ----------
    None

    Returns
    -------
    object
        Loaded module object for the index phase benchmark helper script.
    """
    helper_path = Path(__file__).resolve().parents[1] / "scripts" / "benchmark_index.py"
    sys.path.insert(0, str(helper_path.parent))
    spec = importlib.util.spec_from_file_location("benchmark_index", helper_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return cast("_BenchmarkIndexModule", module)


def _load_split_repo_verification_helper() -> _SplitRepoVerificationModule:
    """
    Load the exported split-repo verification helper from its repository path.

    Parameters
    ----------
    None

    Returns
    -------
    object
        Loaded module object for the split-repo verification helper script.
    """
    helper_path = (
        Path(__file__).resolve().parents[1]
        / "scripts"
        / "verify_exported_split_repos.py"
    )
    spec = importlib.util.spec_from_file_location(
        "verify_exported_split_repos",
        helper_path,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return cast("_SplitRepoVerificationModule", module)


def test_benchmark_campaign_helper_builds_dry_run_plan(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Keep performance campaign command construction reproducible.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary directory for manifest and target repositories.
    monkeypatch : pytest.MonkeyPatch
        Fixture used to patch subprocess execution for deterministic planning.

    Returns
    -------
    None
        The test asserts the campaign helper loads all repository categories
        and emits a dry-run command plan with Hyperfine and profiler commands
        after the phase index is used for adaptive calibration.
    """
    helper = _load_benchmark_campaign_helper()
    small = tmp_path / "codira"
    medium = tmp_path / "fontshow"
    large = tmp_path / "texlive"
    for path in (small, medium, large):
        path.mkdir()
    manifest = tmp_path / "benchmarks.json"
    manifest.write_text(
        json.dumps(
            {
                "repositories": [
                    {
                        "label": "codira",
                        "category": "small",
                        "path": str(small),
                    },
                    {
                        "label": "fontshow",
                        "category": "medium",
                        "path": str(medium),
                        "query": "plugin registry",
                    },
                    {
                        "label": "texlive",
                        "category": "large",
                        "path": str(large),
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    config = helper.CampaignConfig(
        manifest=manifest,
        artifact_root=tmp_path / ".artifacts" / "benchmarks",
        run_id="20260430T120000Z",
        codira="/tmp/codira/.venv/bin/codira",
        hyperfine="hyperfine",
        python="python",
        runs=3,
        warmup=1,
        dry_run=True,
    )

    def fake_run(
        command: Sequence[str],
        *,
        text: bool | None = None,
        capture_output: bool | None = None,
        check: bool | None = None,
    ) -> subprocess.CompletedProcess[str]:
        argv = tuple(str(part) for part in command)
        if "index" in argv:
            return subprocess.CompletedProcess(argv, 0, "", "")
        if "symlist" in argv and "--json" in argv:
            return subprocess.CompletedProcess(
                argv,
                0,
                json.dumps(
                    {
                        "status": "ok",
                        "symbols": [
                            {
                                "type": "function",
                                "name": "build_parser",
                                "module": "codira.cli",
                                "file": str(
                                    (small / "src" / "codira" / "cli.py").resolve()
                                ),
                                "calls_out": {"total": 4},
                                "calls_in": {"total": 2},
                                "refs_out": {"total": 1},
                                "refs_in": {"total": 1},
                            }
                        ],
                    }
                ),
                "",
            )
        if "emb" in argv and "--json" in argv:
            return subprocess.CompletedProcess(
                argv,
                0,
                json.dumps(
                    {
                        "status": "ok",
                        "results": [{"score": 0.9}],
                    }
                ),
                "",
            )
        return subprocess.CompletedProcess(
            argv,
            0,
            json.dumps({"status": "ok", "results": [{"name": "build_parser"}]}),
            "",
        )

    monkeypatch.setattr(helper.subprocess, "run", fake_run)
    repositories = helper.load_manifest(manifest)
    plan = helper.command_plan(repositories, config)
    help_text = helper.build_parser().format_help()
    parsed_zero_warmup = helper.build_parser().parse_args(
        [str(manifest), "--warmup", "0"]
    )

    assert [row["category"] for row in plan] == ["small", "medium", "large"]
    assert parsed_zero_warmup.warmup == 0
    assert "--dry-run" in help_text
    assert "Examples:" in help_text
    assert plan[0]["modes"] == ["cold", "warm", "partial_change"]
    display_commands = cast("list[str]", plan[0]["display_commands"])
    assert not any("benchmark_index.py" in command for command in display_commands)
    assert any("hyperfine" in command for command in display_commands)
    assert any("cProfile" in command for command in display_commands)
    assert all("--output-dir" in command for command in display_commands)
    assert any(
        ".artifacts/benchmarks/20260430T120000Z/indexes/small-codira" in command
        for command in display_commands
    )


def test_benchmark_campaign_helper_expands_manifest_commands(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Keep manifest-defined Codira commands reproducible and path-aware.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary directory for manifest and target repository fixtures.
    monkeypatch : pytest.MonkeyPatch
        Fixture used to patch subprocess execution for deterministic planning.

    Returns
    -------
    None
        The test asserts custom commands expand placeholders, gain repository
        path isolation where required, and deduplicate built-in default
        commands.
    """
    helper = _load_benchmark_campaign_helper()
    repo_path = tmp_path / "codira"
    repo_path.mkdir()
    manifest = tmp_path / "benchmarks.json"
    manifest.write_text(
        json.dumps(
            {
                "repositories": [
                    {
                        "label": "codira",
                        "category": "small",
                        "path": str(repo_path),
                        "query": "schema migration logic",
                        "commands": [
                            ["help"],
                            ["cov", "--json"],
                            ["index", "--full"],
                            ["sym", "build_parser", "--json"],
                            ["ctx", "--json", "{query}"],
                            ["caps", "--json"],
                        ],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    config_file = tmp_path / "generated-config.toml"
    config_file.write_text("config_version = 1\n", encoding="utf-8")
    config = helper.CampaignConfig(
        manifest=manifest,
        artifact_root=tmp_path / ".artifacts" / "benchmarks",
        run_id="20260501T120000Z",
        codira="/tmp/codira/.venv/bin/codira",
        hyperfine="hyperfine",
        python="python",
        runs=3,
        warmup=1,
        dry_run=True,
        config_file=config_file,
    )

    def fake_run(
        command: Sequence[str],
        *,
        text: bool | None = None,
        capture_output: bool | None = None,
        check: bool | None = None,
    ) -> subprocess.CompletedProcess[str]:
        argv = tuple(str(part) for part in command)
        if "index" in argv:
            return subprocess.CompletedProcess(argv, 0, "", "")
        if "symlist" in argv and "--json" in argv:
            return subprocess.CompletedProcess(
                argv,
                0,
                json.dumps(
                    {
                        "status": "ok",
                        "symbols": [
                            {
                                "type": "function",
                                "name": "build_parser",
                                "module": "codira.cli",
                                "file": str(
                                    (repo_path / "src" / "codira" / "cli.py").resolve()
                                ),
                                "calls_out": {"total": 4},
                                "calls_in": {"total": 2},
                                "refs_out": {"total": 1},
                                "refs_in": {"total": 1},
                            }
                        ],
                    }
                ),
                "",
            )
        if "emb" in argv and "--json" in argv:
            return subprocess.CompletedProcess(
                argv,
                0,
                json.dumps(
                    {
                        "status": "ok",
                        "results": [{"score": 0.9}],
                    }
                ),
                "",
            )
        return subprocess.CompletedProcess(
            argv,
            0,
            json.dumps({"status": "ok", "results": [{"name": "build_parser"}]}),
            "",
        )

    monkeypatch.setattr(helper.subprocess, "run", fake_run)
    repositories = helper.load_manifest(manifest)
    plan = helper.command_plan(repositories, config)
    row = plan[0]
    display_commands = cast("list[str]", row["display_commands"])
    commands = cast("list[list[str]]", row["commands"])
    hyperfine_commands = commands[0][8:]

    assert any("codira help" in command for command in display_commands)
    assert "--show-output" not in commands[0]
    assert "--ignore-failure" in commands[0]
    assert row["output_logs"] == [
        str(
            config.artifact_root
            / "20260501T120000Z"
            / "logs"
            / f"small-codira-command-{index}.log"
        )
        for index in range(1, len(commands) + 1)
    ]
    assert any(
        "cov --json --path " in command and "--output-dir " in command
        for command in display_commands
    )
    assert any(
        "cov --json --path " in command and f"--config-file {config_file}" in command
        for command in display_commands
    )
    assert any(
        "sym build_parser --json --path " in command and "--output-dir " in command
        for command in display_commands
    )
    assert any(
        "ctx --json 'schema migration logic' --path " in command
        and "--output-dir " in command
        for command in display_commands
    )
    assert any("caps --json" in command for command in display_commands)
    assert not any(
        "caps --json" in command and "--config-file" in command
        for command in hyperfine_commands
    )
    assert not any("codira index --full" in command for command in hyperfine_commands)
    assert any("codira index --path " in command for command in hyperfine_commands)


def test_benchmark_campaign_writes_utility_summary(tmp_path: Path) -> None:
    """
    Persist workflow-weighted utility scores from Hyperfine exports.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary artifact root.

    Returns
    -------
    None
        The test asserts query command inclusion and score weights stay
        aligned with the benchmark utility contract.
    """
    helper = _load_benchmark_campaign_helper()
    manifest = tmp_path / "manifest.json"
    config = helper.CampaignConfig(
        manifest=manifest,
        artifact_root=tmp_path / ".artifacts" / "benchmarks",
        run_id="20260501T120000Z",
        codira="/tmp/codira/.venv/bin/codira",
        hyperfine="hyperfine",
        python="python",
        runs=3,
        warmup=1,
        dry_run=False,
    )
    repo = helper.ResolvedRepositoryBenchmark(
        label="codira",
        category="small",
        path=tmp_path,
        query="schema migration",
        requested_query="schema migration",
        modes=("benchmark",),
        commands=(),
        requested_commands=(),
        skipped_commands=(),
        selection={},
    )
    hyperfine_path = helper.run_directory(config) / "small-codira-hyperfine.json"
    hyperfine_path.parent.mkdir(parents=True)
    phase_path = helper.run_directory(config) / "small-codira-index-phases.json"
    phase_path.write_text(
        json.dumps({"timings": {"total": 10.0}}),
        encoding="utf-8",
    )
    hyperfine_path.write_text(
        json.dumps(
            {
                "results": [
                    {
                        "command": "/tmp/codira/.venv/bin/codira index",
                        "mean": 2.0,
                    },
                    {
                        "command": "/tmp/codira/.venv/bin/codira ctx --json query",
                        "mean": 1.0,
                    },
                    {
                        "command": "/tmp/codira/.venv/bin/codira audit --json",
                        "mean": 3.0,
                    },
                    {
                        "command": "/tmp/codira/.venv/bin/codira help",
                        "mean": 100.0,
                    },
                    {
                        "command": "/tmp/codira/.venv/bin/codira caps --json",
                        "mean": 100.0,
                    },
                ]
            }
        ),
        encoding="utf-8",
    )

    helper.write_utility_summary(repo, config)

    payload = json.loads(
        helper.utility_summary_path(repo, config).read_text(encoding="utf-8")
    )
    assert payload["query_mean_seconds"] == 2.0
    assert payload["utility_score"] == 56.0
    assert [row["subcommand"] for row in payload["query_results"]] == [
        "ctx",
        "audit",
    ]


def test_benchmark_campaign_adaptive_resolution_picks_richer_candidates(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Resolve benchmark targets toward richer repo-specific command outputs.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary directory for manifest and target repository fixtures.
    monkeypatch : pytest.MonkeyPatch
        Fixture used to replace subprocess execution.

    Returns
    -------
    None
        The test asserts adaptive resolution replaces weak literal targets with
        richer symbol and query candidates and records selector provenance.
    """
    helper = _load_benchmark_campaign_helper()
    repo_path = tmp_path / "codira"
    repo_path.mkdir()
    manifest = tmp_path / "benchmarks.json"
    manifest.write_text(
        json.dumps(
            {
                "repositories": [
                    {
                        "label": "codira",
                        "category": "small",
                        "path": str(repo_path),
                        "query": "schema migration logic",
                        "commands": [
                            ["sym", "missing_symbol", "--json"],
                            ["refs", "missing_symbol", "--incoming", "--json"],
                            ["emb", "{query}", "--json", "--limit", "5"],
                        ],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    config = helper.CampaignConfig(
        manifest=manifest,
        artifact_root=tmp_path / ".artifacts" / "benchmarks",
        run_id="20260502T120000Z",
        codira="codira",
        hyperfine="hyperfine",
        python="python",
        runs=3,
        warmup=1,
        dry_run=True,
    )

    def fake_run(
        command: Sequence[str],
        *,
        text: bool | None = None,
        capture_output: bool | None = None,
        check: bool | None = None,
    ) -> subprocess.CompletedProcess[str]:
        argv = tuple(str(part) for part in command)
        if "index" in argv:
            return subprocess.CompletedProcess(argv, 0, "", "")
        if "symlist" in argv and "--json" in argv:
            return subprocess.CompletedProcess(
                argv,
                0,
                json.dumps(
                    {
                        "status": "ok",
                        "symbols": [
                            {
                                "type": "function",
                                "name": "alpha_edge",
                                "module": "codira.alpha",
                                "file": str(
                                    (
                                        repo_path / "src" / "codira" / "alpha.py"
                                    ).resolve()
                                ),
                                "calls_out": {"total": 2},
                                "calls_in": {"total": 1},
                                "refs_out": {"total": 0},
                                "refs_in": {"total": 0},
                            },
                            {
                                "type": "function",
                                "name": "beta_edge",
                                "module": "codira.beta",
                                "file": str(
                                    (repo_path / "src" / "codira" / "beta.py").resolve()
                                ),
                                "calls_out": {"total": 5},
                                "calls_in": {"total": 3},
                                "refs_out": {"total": 2},
                                "refs_in": {"total": 2},
                            },
                        ],
                    }
                ),
                "",
            )
        if "emb" in argv and "--json" in argv:
            query = argv[argv.index("emb") + 1]
            if query == "beta edge":
                payload = {
                    "status": "ok",
                    "results": [{"score": 0.95}, {"score": 0.91}],
                }
            elif query == "alpha edge":
                payload = {"status": "ok", "results": [{"score": 0.4}]}
            else:
                payload = {"status": "ok", "results": []}
            return subprocess.CompletedProcess(argv, 0, json.dumps(payload), "")
        if "sym" in argv and "--json" in argv:
            name = argv[argv.index("sym") + 1]
            payload = (
                {"status": "ok", "results": [{"name": name}, {"name": f"{name}.alt"}]}
                if name == "beta_edge"
                else {"status": "ok", "results": [{"name": name}]}
            )
            return subprocess.CompletedProcess(argv, 0, json.dumps(payload), "")
        if "refs" in argv and "--json" in argv:
            name = argv[argv.index("refs") + 1]
            if name == "beta_edge":
                payload = {
                    "status": "ok",
                    "results": [{"name": "one"}, {"name": "two"}],
                }
                return subprocess.CompletedProcess(argv, 0, json.dumps(payload), "")
            payload = {"status": "no_matches", "results": []}
            return subprocess.CompletedProcess(argv, 1, json.dumps(payload), "")
        return subprocess.CompletedProcess(argv, 0, json.dumps({"status": "ok"}), "")

    monkeypatch.setattr(helper.subprocess, "run", fake_run)

    repositories = helper.load_manifest(manifest)
    resolved = helper.resolve_repositories(repositories, config)
    plan = helper.command_plan(resolved, config)
    resolved_repo = cast("_ResolvedBenchmarkRepository", resolved[0])

    assert resolved_repo.query == "beta edge"
    assert resolved_repo.commands == (
        ("sym", "beta_edge", "--json"),
        ("refs", "beta_edge", "--incoming", "--json"),
        ("emb", "beta edge", "--json", "--limit", "5"),
    )
    row = plan[0]
    assert row["requested_query"] == "schema migration logic"
    assert row["query"] == "beta edge"
    assert row["skipped_commands"] == []


def test_benchmark_campaign_prints_repo_label_before_phase_discovery(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """
    Print the manifest label before the per-repository phase discovery run.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary directory for manifest and target repository fixtures.
    monkeypatch : pytest.MonkeyPatch
        Fixture used to replace subprocess execution.
    capsys : pytest.CaptureFixture[str]
        Fixture used to capture user-facing banner output.

    Returns
    -------
    None
        The test asserts repository discovery prints the uppercased label
        banner before the phase index command output.
    """
    helper = _load_benchmark_campaign_helper()
    repo_path = tmp_path / "fontshow"
    repo_path.mkdir()
    manifest = tmp_path / "benchmarks.json"
    manifest.write_text(
        json.dumps(
            {
                "repositories": [
                    {
                        "label": "fontshow",
                        "category": "small",
                        "path": str(repo_path),
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    config_file = tmp_path / "generated-config.toml"
    config_file.write_text("config_version = 1\n", encoding="utf-8")
    config = helper.CampaignConfig(
        manifest=manifest,
        artifact_root=tmp_path / ".artifacts" / "benchmarks",
        run_id="20260502T150000Z",
        codira="codira",
        hyperfine="hyperfine",
        python="python",
        runs=3,
        warmup=1,
        dry_run=True,
        config_file=config_file,
    )
    captured_commands: list[tuple[str, ...]] = []

    def fake_run(
        command: Sequence[str],
        *,
        text: bool | None = None,
        capture_output: bool | None = None,
        check: bool | None = None,
    ) -> subprocess.CompletedProcess[str]:
        argv = tuple(str(part) for part in command)
        captured_commands.append(argv)
        if "index" in argv:
            return subprocess.CompletedProcess(argv, 0, "", "")
        if "symlist" in argv and "--json" in argv:
            return subprocess.CompletedProcess(
                argv,
                0,
                json.dumps(
                    {
                        "status": "ok",
                        "symbols": [
                            {
                                "type": "function",
                                "name": "show_fonts",
                                "module": "fontshow.main",
                                "file": str(
                                    (
                                        repo_path / "src" / "fontshow" / "main.py"
                                    ).resolve()
                                ),
                                "calls_out": {"total": 1},
                                "calls_in": {"total": 1},
                                "refs_out": {"total": 0},
                                "refs_in": {"total": 0},
                            }
                        ],
                    }
                ),
                "",
            )
        if "emb" in argv and "--json" in argv:
            return subprocess.CompletedProcess(
                argv,
                0,
                json.dumps({"status": "ok", "results": [{"score": 0.8}]}),
                "",
            )
        return subprocess.CompletedProcess(argv, 0, json.dumps({"status": "ok"}), "")

    monkeypatch.setattr(helper.subprocess, "run", fake_run)

    repositories = helper.load_manifest(manifest)
    helper.resolve_repositories(repositories, config)
    captured = capsys.readouterr()

    assert captured.err == ""
    assert captured.out.startswith("--- FONTSHOW ---\n")
    discovery_index = next(
        argv for argv in captured_commands if "benchmark_index.py" in argv[1]
    )
    assert "--config-file" in discovery_index
    assert str(config_file) in discovery_index
    discovery_symlist = next(
        argv for argv in captured_commands if argv[:2] == ("codira", "symlist")
    )
    assert "--config-file" in discovery_symlist
    assert str(config_file) in discovery_symlist


def test_benchmark_campaign_skips_unresolved_adaptive_commands(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Skip adaptive commands that cannot produce meaningful output.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary directory for manifest and target repository fixtures.
    monkeypatch : pytest.MonkeyPatch
        Fixture used to replace subprocess execution.

    Returns
    -------
    None
        The test asserts unresolved adaptive commands are excluded from the
        resolved Hyperfine command matrix and persisted as skipped commands.
    """
    helper = _load_benchmark_campaign_helper()
    repo_path = tmp_path / "codira"
    repo_path.mkdir()
    manifest = tmp_path / "benchmarks.json"
    manifest.write_text(
        json.dumps(
            {
                "repositories": [
                    {
                        "label": "codira",
                        "category": "small",
                        "path": str(repo_path),
                        "commands": [
                            ["refs", "missing_symbol", "--incoming", "--json"]
                        ],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    config = helper.CampaignConfig(
        manifest=manifest,
        artifact_root=tmp_path / ".artifacts" / "benchmarks",
        run_id="20260502T130000Z",
        codira="codira",
        hyperfine="hyperfine",
        python="python",
        runs=3,
        warmup=1,
        dry_run=True,
    )

    def fake_run(
        command: Sequence[str],
        *,
        text: bool | None = None,
        capture_output: bool | None = None,
        check: bool | None = None,
    ) -> subprocess.CompletedProcess[str]:
        argv = tuple(str(part) for part in command)
        if "index" in argv:
            return subprocess.CompletedProcess(argv, 0, "", "")
        if "symlist" in argv and "--json" in argv:
            return subprocess.CompletedProcess(
                argv,
                0,
                json.dumps(
                    {
                        "status": "ok",
                        "symbols": [
                            {
                                "type": "function",
                                "name": "alpha_edge",
                                "module": "codira.alpha",
                                "file": str(
                                    (
                                        repo_path / "src" / "codira" / "alpha.py"
                                    ).resolve()
                                ),
                                "calls_out": {"total": 2},
                                "calls_in": {"total": 1},
                                "refs_out": {"total": 0},
                                "refs_in": {"total": 0},
                            }
                        ],
                    }
                ),
                "",
            )
        if "emb" in argv and "--json" in argv:
            return subprocess.CompletedProcess(
                argv,
                0,
                json.dumps({"status": "ok", "results": [{"score": 0.8}]}),
                "",
            )
        if "refs" in argv and "--json" in argv:
            return subprocess.CompletedProcess(
                argv,
                1,
                json.dumps({"status": "no_matches", "results": []}),
                "",
            )
        return subprocess.CompletedProcess(argv, 0, json.dumps({"status": "ok"}), "")

    monkeypatch.setattr(helper.subprocess, "run", fake_run)

    repositories = helper.load_manifest(manifest)
    resolved = helper.resolve_repositories(repositories, config)
    plan = helper.command_plan(resolved, config)
    resolved_repo = cast("_ResolvedBenchmarkRepository", resolved[0])

    assert resolved_repo.commands == ()
    assert resolved_repo.skipped_commands == (
        ("refs", "missing_symbol", "--incoming", "--json"),
    )
    assert plan[0]["skipped_commands"] == [
        ["refs", "missing_symbol", "--incoming", "--json"]
    ]


def test_benchmark_campaign_rejects_duplicate_labels(tmp_path: Path) -> None:
    """
    Keep benchmark manifest identities unique before campaign execution.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary workspace used for manifest fixtures.

    Returns
    -------
    None
        The test asserts duplicate labels are rejected before command planning.
    """
    helper = _load_benchmark_campaign_helper()
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    manifest = tmp_path / "benchmarks.json"
    manifest.write_text(
        json.dumps(
            {
                "repositories": [
                    {"label": "dup", "category": "small", "path": str(first)},
                    {"label": "dup", "category": "medium", "path": str(second)},
                ]
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="duplicate label"):
        helper.load_manifest(manifest)


def test_benchmark_campaign_main_creates_artifact_root_and_reports_missing_manifest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """
    Keep campaign startup failures concise and artifact roots reproducible.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary workspace used for CLI fixtures.
    monkeypatch : pytest.MonkeyPatch
        Fixture used to replace process arguments.
    capsys : pytest.CaptureFixture[str]
        Fixture used to inspect user-facing stderr output.

    Returns
    -------
    None
        The test asserts missing manifests return a short error and still create
        the configured artifact root directory.
    """
    helper = _load_benchmark_campaign_helper()
    artifact_root = tmp_path / "missing-artifacts-root"
    missing_manifest = tmp_path / "missing-benchmarks.json"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "benchmark_campaign.py",
            str(missing_manifest),
            "--artifact-root",
            str(artifact_root),
        ],
    )

    assert helper.main() == 2
    captured = capsys.readouterr()

    assert artifact_root.is_dir()
    assert captured.out == ""
    assert "Error: manifest file not found:" in captured.err


def test_benchmark_campaign_main_prints_timestamp_after_each_repo_step(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """
    Print a timestamp after each repository command group completes.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary workspace used for manifest fixtures.
    monkeypatch : pytest.MonkeyPatch
        Fixture used to replace process arguments and command execution.
    capsys : pytest.CaptureFixture[str]
        Fixture used to inspect terminal output.

    Returns
    -------
    None
        The test asserts one timestamp line is emitted per repository step.
    """
    helper = _load_benchmark_campaign_helper()
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    manifest = tmp_path / "benchmarks.json"
    manifest.write_text(
        json.dumps(
            {
                "repositories": [
                    {"label": "first", "category": "small", "path": str(first)},
                    {"label": "second", "category": "medium", "path": str(second)},
                ]
            }
        ),
        encoding="utf-8",
    )
    artifact_root = tmp_path / ".artifacts" / "benchmarks"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "benchmark_campaign.py",
            str(manifest),
            "--artifact-root",
            str(artifact_root),
        ],
    )
    monkeypatch.setattr(helper, "utc_run_timestamp", lambda: "2026-05-20T10:15:30Z")

    def fake_resolve_repositories(
        repositories: Sequence[object],
        config: object,
    ) -> Sequence[object]:
        return repositories

    def fake_command_plan(
        repositories: Sequence[object],
        config: object,
    ) -> list[dict[str, object]]:
        del repositories, config
        return [
            {
                "label": "first",
                "commands": [["true"]],
                "output_logs": [str(artifact_root / "run" / "logs" / "first.log")],
            },
            {
                "label": "second",
                "commands": [["true"]],
                "output_logs": [str(artifact_root / "run" / "logs" / "second.log")],
            },
        ]

    monkeypatch.setattr(helper, "resolve_repositories", fake_resolve_repositories)
    monkeypatch.setattr(helper, "command_plan", fake_command_plan)

    def fake_run_command(command: tuple[str, ...], *, output_log: Path) -> int:
        del command, output_log
        return 0

    monkeypatch.setattr(helper, "_run_command", fake_run_command)

    assert helper.main() == 0
    captured = capsys.readouterr()

    assert captured.err == ""
    assert "first: 2026-05-20T10:15:30Z\n" in captured.out
    assert "second: 2026-05-20T10:15:30Z\n" in captured.out


def test_benchmark_campaign_continue_on_error_records_all_failures(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Keep torture campaigns running after command failures.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary workspace used for manifest and artifact fixtures.
    monkeypatch : pytest.MonkeyPatch
        Fixture used to replace process arguments and command execution.

    Returns
    -------
    None
        The test asserts failed commands are summarized while later commands
        still execute.
    """
    helper = _load_benchmark_campaign_helper()
    target = tmp_path / "target"
    target.mkdir()
    manifest = tmp_path / "benchmarks.json"
    manifest.write_text(
        json.dumps(
            {
                "repositories": [
                    {"label": "target", "category": "small", "path": str(target)}
                ]
            }
        ),
        encoding="utf-8",
    )
    artifact_root = tmp_path / ".artifacts"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "benchmark_campaign.py",
            str(manifest),
            "--artifact-root",
            str(artifact_root),
            "--run-id",
            "torture",
            "--continue-on-error",
        ],
    )
    monkeypatch.setattr(helper, "utc_run_timestamp", lambda: "2026-05-20T10:15:30Z")

    def fake_resolve_repositories(
        repositories: Sequence[object],
        config: object,
    ) -> Sequence[object]:
        del config
        return repositories

    def fake_command_plan(
        repositories: Sequence[object],
        config: object,
    ) -> list[dict[str, object]]:
        del repositories, config
        return [
            {
                "label": "target",
                "category": "small",
                "commands": [["false"], ["true"]],
                "output_logs": [
                    str(artifact_root / "torture" / "logs" / "false.log"),
                    str(artifact_root / "torture" / "logs" / "true.log"),
                ],
            }
        ]

    executed: list[tuple[str, ...]] = []

    def fake_run_command(command: tuple[str, ...], *, output_log: Path) -> int:
        executed.append(command)
        output_log.parent.mkdir(parents=True, exist_ok=True)
        output_log.write_text("log\n", encoding="utf-8")
        return 1 if command == ("false",) else 0

    monkeypatch.setattr(helper, "resolve_repositories", fake_resolve_repositories)
    monkeypatch.setattr(helper, "command_plan", fake_command_plan)
    monkeypatch.setattr(helper, "_run_command", fake_run_command)

    assert helper.main() == 1

    assert executed == [("false",), ("true",)]
    summary = json.loads(
        (artifact_root / "torture" / "failure-summary.json").read_text(encoding="utf-8")
    )
    assert summary["failure_count"] == 1
    assert summary["continue_on_error"] is True
    assert summary["failures"][0]["label"] == "target"
    assert summary["failures"][0]["return_code"] == 1
    assert summary["failures"][0]["output_log"].endswith("false.log")


def test_benchmark_campaign_summarizes_unreadable_profiles(
    tmp_path: Path,
) -> None:
    """
    Report corrupt profile artifacts without failing the campaign.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary workspace used for the profile fixture.

    Returns
    -------
    None
        The test asserts malformed cProfile output is represented as
        diagnostic metadata.
    """
    helper = _load_benchmark_campaign_helper()
    profile = tmp_path / "broken.prof"
    profile.write_bytes(b"")

    summary = helper.summarize_profile(profile)

    assert summary == [
        {
            "status": "unreadable",
            "error_type": "EOFError",
            "error": "EOF read where object expected",
        }
    ]


def test_benchmark_campaign_removes_index_artifacts_after_repository(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Drop bulky per-repository indexes after durable results are written.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary workspace used for manifest and artifact fixtures.
    monkeypatch : pytest.MonkeyPatch
        Fixture used to replace process arguments and command execution.

    Returns
    -------
    None
        The test asserts the default retention policy removes benchmark index
        directories after a repository row completes.
    """
    helper = _load_benchmark_campaign_helper()
    target = tmp_path / "target"
    target.mkdir()
    manifest = tmp_path / "benchmarks.json"
    manifest.write_text(
        json.dumps(
            {
                "repositories": [
                    {"label": "target", "category": "small", "path": str(target)}
                ]
            }
        ),
        encoding="utf-8",
    )
    artifact_root = tmp_path / ".artifacts"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "benchmark_campaign.py",
            str(manifest),
            "--artifact-root",
            str(artifact_root),
            "--run-id",
            "cleanup",
        ],
    )
    monkeypatch.setattr(helper, "utc_run_timestamp", lambda: "2026-05-20T10:15:30Z")

    def fake_resolve_repositories(
        repositories: Sequence[object],
        config: object,
    ) -> Sequence[object]:
        del config
        return repositories

    index_dir_holder: dict[str, Path] = {}

    def fake_command_plan(
        repositories: Sequence[object],
        config: object,
    ) -> list[dict[str, object]]:
        index_dir = helper.index_output_dir(repositories[0], config)
        index_dir.mkdir(parents=True)
        (index_dir / "index.db").write_text("temporary index\n", encoding="utf-8")
        index_dir_holder["path"] = index_dir
        return [
            {
                "label": "target",
                "category": "small",
                "commands": [["true"]],
                "output_logs": [str(artifact_root / "cleanup" / "logs" / "true.log")],
            }
        ]

    def fake_run_command(command: tuple[str, ...], *, output_log: Path) -> int:
        del command
        output_log.parent.mkdir(parents=True, exist_ok=True)
        output_log.write_text("log\n", encoding="utf-8")
        return 0

    monkeypatch.setattr(helper, "resolve_repositories", fake_resolve_repositories)
    monkeypatch.setattr(helper, "command_plan", fake_command_plan)
    monkeypatch.setattr(helper, "_run_command", fake_run_command)

    assert helper.main() == 0

    assert not index_dir_holder["path"].exists()


def test_benchmark_campaign_run_command_writes_combined_output_log(
    tmp_path: Path,
) -> None:
    """
    Persist stdout and stderr from one benchmark campaign command.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary workspace used for the output log.

    Returns
    -------
    None
        The test asserts command output is captured in a durable log file.
    """
    helper = _load_benchmark_campaign_helper()
    output_log = tmp_path / "logs" / "command.log"

    return_code = helper._run_command(
        (
            sys.executable,
            "-c",
            "import sys; print('out', flush=True); print('err', file=sys.stderr)",
        ),
        output_log=output_log,
    )

    assert return_code == 0
    lines = output_log.read_text(encoding="utf-8").splitlines()
    assert lines[0].startswith(f"$ {sys.executable} -c ")
    assert lines[-2:] == ["out", "err"]


__all__ = [
    "EXPECTED_FIRST_PARTY_PACKAGE_DIRS",
    "EXPECTED_NON_BUNDLE_PACKAGE_DIRS",
    "Path",
    "Protocol",
    "TYPE_CHECKING",
    "_editable_args",
    "_expected_monorepo_package_paths",
    "_expected_split_package_paths",
    "cast",
    "importlib",
    "json",
    "pytest",
    "subprocess",
    "sys",
]
