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


def test_release_benchmark_helper_builds_hyperfine_plan() -> None:
    """
    Keep release benchmarks explicit and reproducible.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test asserts the Hyperfine helper covers index, ctx, and audit with
        stable run counts and JSON output.
    """
    helper = _load_release_benchmark_helper()
    repo_root = Path("/tmp/codira")
    output = repo_root / ".artifacts" / "benchmarks" / "release-hyperfine.json"
    config = helper.BenchmarkConfig(
        hyperfine="hyperfine",
        codira="/tmp/codira/.venv/bin/codira",
        output=output,
        runs=7,
        warmup=2,
        query="plugin registry",
    )

    assert helper.resolve_output_path(repo_root, helper.DEFAULT_OUTPUT) == output
    assert helper.benchmark_command_strings(
        codira="/tmp/codira/.venv/bin/codira",
        query="plugin registry",
    ) == (
        "/tmp/codira/.venv/bin/codira index --full",
        "/tmp/codira/.venv/bin/codira ctx --json 'plugin registry'",
        "/tmp/codira/.venv/bin/codira audit --json",
    )
    assert helper.build_hyperfine_argv(config) == (
        "hyperfine",
        "--warmup",
        "2",
        "--runs",
        "7",
        "--export-json",
        "/tmp/codira/.artifacts/benchmarks/release-hyperfine.json",
        "/tmp/codira/.venv/bin/codira index --full",
        "/tmp/codira/.venv/bin/codira ctx --json 'plugin registry'",
        "/tmp/codira/.venv/bin/codira audit --json",
    )


def test_manifest_baseline_uses_explicit_runs_and_warmup_cli(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Keep paired backend baseline measurement counts on the CLI surface.

    Parameters
    ----------
    monkeypatch : pytest.MonkeyPatch
        Fixture used to prove old environment variables are ignored.

    Returns
    -------
    None
        The test asserts explicit flags and parser defaults drive run counts.
    """
    helper = _load_manifest_baseline_helper()
    parser = helper.build_parser()

    monkeypatch.setenv("RUNS", "99")
    monkeypatch.setenv("WARMUP", "99")

    explicit = parser.parse_args(["--runs", "7", "--warmup", "0"])
    defaults = parser.parse_args([])

    assert explicit.runs == 7
    assert explicit.warmup == 0
    assert defaults.runs == 5
    assert defaults.warmup == 1


def test_final_embedding_campaign_uses_explicit_runs_and_warmup_cli(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Keep final embedding campaign measurement counts on the CLI surface.

    Parameters
    ----------
    monkeypatch : pytest.MonkeyPatch
        Fixture used to prove old environment variables are ignored.

    Returns
    -------
    None
        The test asserts explicit flags and parser defaults drive run counts.
    """
    helper = _load_final_embedding_campaign_helper()

    monkeypatch.setenv("RUNS", "99")
    monkeypatch.setenv("WARMUP", "99")

    explicit = helper.parse_args(["--runs", "7", "--warmup", "0"])
    defaults = helper.parse_args([])

    assert explicit.runs == 7
    assert explicit.warmup == 0
    assert defaults.runs == 5
    assert defaults.warmup == 1


def test_final_embedding_campaign_expands_both_to_concrete_backend_configs(
    tmp_path: Path,
) -> None:
    """
    Expand ``--backend both`` into visible backend-specific campaign phases.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary directory used for the model manifest fixture.

    Returns
    -------
    None
        The test asserts both mode has concrete backend order and matching
        generated backend/vector-store config.
    """
    helper = _load_final_embedding_campaign_helper()
    model_manifest = tmp_path / "models.json"
    model_manifest.write_text(
        json.dumps(
            {
                "models": [
                    {
                        "id": "example-model",
                        "engine": "sentence-transformers",
                        "model": "sentence-transformers/all-MiniLM-L6-v2",
                        "version": "1",
                        "dimension": 384,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    model = helper.read_models(model_manifest)[0]

    assert helper.concrete_backends("both") == ("sqlite", "duckdb")
    assert helper.concrete_backends("sqlite") == ("sqlite",)
    assert helper.concrete_backends("duckdb") == ("duckdb",)

    sqlite_config = helper.render_model_config(model, "sqlite")
    duckdb_config = helper.render_model_config(model, "duckdb")

    assert 'name = "sqlite"' in sqlite_config
    assert 'vector_store = "sqlite"' in sqlite_config
    assert "[plugins.backend-duckdb]" in sqlite_config
    assert "profiling_enabled = false" in sqlite_config
    assert 'name = "duckdb"' in duckdb_config
    assert 'vector_store = "duckdb"' in duckdb_config
    assert "[plugins.backend-duckdb]" in duckdb_config
    assert "profiling_enabled = true" in duckdb_config


@pytest.mark.parametrize(
    ("script_name", "argv"),
    (
        ("baseline", ["--runs", "0"]),
        ("baseline", ["--warmup", "-1"]),
        ("final", ["--runs", "0"]),
        ("final", ["--warmup", "-1"]),
    ),
)
def test_campaign_wrappers_reject_non_positive_run_counts(
    script_name: str,
    argv: list[str],
) -> None:
    """
    Reject invalid benchmark run counts before launching campaigns.

    Parameters
    ----------
    script_name : str
        Script helper under test.
    argv : list[str]
        Invalid command-line arguments.

    Returns
    -------
    None
        The test asserts argparse rejects non-positive values.
    """
    if script_name == "baseline":
        parser = _load_manifest_baseline_helper().build_parser()
        with pytest.raises(SystemExit):
            parser.parse_args(argv)
    else:
        helper = _load_final_embedding_campaign_helper()
        with pytest.raises(SystemExit):
            helper.parse_args(argv)


def test_benchmark_index_helper_uses_the_active_backend_class(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """
    Resolve phase benchmark instrumentation against the configured backend class.

    Parameters
    ----------
    monkeypatch : pytest.MonkeyPatch
        Fixture used to override backend selection deterministically.
    tmp_path : pathlib.Path
        Temporary repository root supplied to the helper.

    Returns
    -------
    None
        The test asserts the benchmark helper does not hard-code the SQLite
        backend class when selecting the rebuild hook target.
    """
    helper = _load_benchmark_index_helper()

    class _FakeDuckBackend:
        def rebuild_derived_indexes(
            self,
            root: Path,
            *,
            conn: object | None = None,
        ) -> None:
            del root, conn

    monkeypatch.setattr(
        helper,
        "active_index_backend",
        lambda *, root=None: _FakeDuckBackend(),
    )

    assert helper.active_backend_class(tmp_path) is _FakeDuckBackend


def test_benchmark_index_helper_uses_the_active_backend_support_module(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """
    Resolve benchmark helper patching against the active backend support module.

    Parameters
    ----------
    monkeypatch : pytest.MonkeyPatch
        Fixture used to override backend selection deterministically.
    tmp_path : pathlib.Path
        Temporary repository root supplied to the helper.

    Returns
    -------
    None
        The test asserts the benchmark helper selects the package-local support
        module for both first-party backends instead of hard-coding SQLite.
    """
    helper = _load_benchmark_index_helper()

    class _FakeBackend:
        def __init__(self, name: str) -> None:
            self.name = name

    monkeypatch.setattr(
        helper,
        "active_index_backend",
        lambda *, root=None: _FakeBackend("sqlite"),
    )
    sqlite_support = helper.active_backend_support_module(tmp_path)
    assert sqlite_support.__name__ == "codira_backend_sqlite.sqlite_support"

    monkeypatch.setattr(
        helper,
        "active_index_backend",
        lambda *, root=None: _FakeBackend("duckdb"),
    )
    duckdb_support = helper.active_backend_support_module(tmp_path)
    assert duckdb_support.__name__ == "codira_backend_duckdb.duckdb_support"


def test_embedding_startup_benchmark_helper_separates_cold_and_warm_costs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Keep semantic-startup timing splits deterministic in one process.

    Parameters
    ----------
    monkeypatch : pytest.MonkeyPatch
        Fixture used to control module loading and timer values.

    Returns
    -------
    None
        The test asserts the helper reports import, split load/encode, and
        cold-versus-warm query timings deterministically.
    """
    helper = _load_embedding_startup_benchmark_helper()

    class _FakeEmbeddingsModule:
        EMBEDDING_BACKEND = "demo-backend"
        EMBEDDING_VERSION = "9"
        EMBEDDING_DIM = 3

        def __init__(self) -> None:
            self.reset_calls = 0
            self.load_calls = 0
            self.embed_calls: list[str] = []

        def _load_model(self) -> object:
            self.load_calls += 1
            return object()

        def embed_text(self, text: str) -> list[float]:
            self.embed_calls.append(text)
            return [1.0, 2.0, 3.0]

        def reset_embedding_runtime_caches(self) -> None:
            self.reset_calls += 1

    fake_module = _FakeEmbeddingsModule()
    ticks = iter((0.0, 1.0, 2.0, 5.0, 7.0, 11.0, 13.0, 18.0, 20.0, 27.0, 30.0, 32.0))

    monkeypatch.setattr(helper, "_load_embeddings_module", lambda: fake_module)
    monkeypatch.setattr(helper, "perf_counter", lambda: next(ticks))

    payload = helper.measure_embedding_startup(
        text="schema migration logic",
        second_text="docstring audit rules",
    )

    assert cast("dict[str, object]", payload["backend"]) == {
        "name": "demo-backend",
        "version": "9",
        "dim": 3,
    }
    assert cast("dict[str, object]", payload["queries"]) == {
        "cold_text": "schema migration logic",
        "warm_text": "docstring audit rules",
    }
    assert cast("dict[str, object]", payload["timings"]) == {
        "module_import": 1.0,
        "model_load": 3.0,
        "first_encode_after_load": 4.0,
        "second_encode_after_load": 5.0,
        "cold_query": 7.0,
        "warm_query": 2.0,
    }
    assert cast("dict[str, object]", payload["vectors"]) == {
        "cold_query_dim": 3,
        "warm_query_dim": 3,
        "first_encode_dim": 3,
        "second_encode_dim": 3,
    }
    assert fake_module.reset_calls == 2
    assert fake_module.load_calls == 1
    assert fake_module.embed_calls == [
        "schema migration logic",
        "docstring audit rules",
        "schema migration logic",
        "docstring audit rules",
    ]


def test_benchmark_metadata_includes_first_party_plugins(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Keep benchmark artifacts tied to the first-party plugin set.

    Parameters
    ----------
    monkeypatch : pytest.MonkeyPatch
        Fixture used to set embedding runtime environment variables.

    Returns
    -------
    None
        The test asserts benchmark metadata exposes Codira identity, Git
        revision, tool availability, and all first-party analyzer/backend
        providers.
    """
    helper = _load_benchmark_timing_helper()
    monkeypatch.setenv("CODIRA_EMBED_BATCH_SIZE", "64")
    monkeypatch.setenv("CODIRA_EMBED_DEVICE", "cpu")
    monkeypatch.setenv("CODIRA_TORCH_NUM_THREADS", "4")
    monkeypatch.setenv("CODIRA_TORCH_NUM_INTEROP_THREADS", "1")
    expected_providers = tuple(
        relative.removeprefix("packages/")
        for relative in EXPECTED_NON_BUNDLE_PACKAGE_DIRS
    )

    metadata = helper.benchmark_metadata(
        Path(__file__).resolve().parents[1],
        hyperfine="definitely-missing-hyperfine",
    )
    plugins = cast("list[dict[str, object]]", metadata["plugins"])
    tools = cast("dict[str, object]", metadata["tools"])
    embedding_runtime = cast("dict[str, object]", metadata["embedding_runtime"])
    embedding_env = cast("dict[str, object]", embedding_runtime["env"])
    embedding_effective = cast("dict[str, object]", embedding_runtime["effective"])
    providers = {
        str(plugin["provider"])
        for plugin in plugins
        if plugin.get("origin") == "first_party"
    }

    assert helper.first_party_plugin_providers() == expected_providers
    assert metadata["run_at"]
    assert metadata["codira_version"]
    assert metadata["git_commit"]
    assert {
        "codira-analyzer-python",
        "codira-analyzer-json",
        "codira-analyzer-c",
        "codira-analyzer-cpp",
        "codira-analyzer-bash",
        "codira-analyzer-markdown",
        "codira-analyzer-text",
        "codira-backend-sqlite",
    } <= providers
    assert tools["hyperfine"] is False
    assert "pyinstrument" in tools
    assert "snakeviz" in tools
    assert embedding_env == {
        "CODIRA_EMBED_BATCH_SIZE": "64",
        "CODIRA_EMBED_DEVICE": "cpu",
        "CODIRA_TORCH_NUM_THREADS": "4",
        "CODIRA_TORCH_NUM_INTEROP_THREADS": "1",
    }
    assert embedding_effective["embedding_batch_size"] == 64
    assert embedding_effective["embedding_device"] == "cpu"
    assert "torch_available" in embedding_effective
    assert "torch_num_threads" in embedding_effective
    assert "torch_num_interop_threads" in embedding_effective


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
