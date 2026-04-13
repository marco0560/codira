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
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, cast

if TYPE_CHECKING:
    from scripts.bootstrap_dev_environment import CommandSpec


class _InstallHelperModule(Protocol):
    """Protocol for the standalone first-party install helper module."""

    FIRST_PARTY_EDITABLE_PACKAGES: tuple[str, ...]

    def first_party_package_root(
        self,
        repo_root: Path,
        package_root: Path | None,
    ) -> Path:
        """Return the directory containing first-party package repositories."""

    def editable_core_requirement(
        self,
        repo_root: Path,
        *,
        extras: tuple[str, ...] = (),
    ) -> str:
        """Return the editable requirement string for the core package."""

    def editable_package_paths(
        self,
        repo_root: Path,
        *,
        package_root: Path | None = None,
    ) -> tuple[Path, ...]:
        """Return package paths in deterministic order."""

    def bundle_package_path(
        self,
        repo_root: Path,
        *,
        package_root: Path | None = None,
    ) -> Path:
        """Return the bundle package path."""

    def non_bundle_package_paths(
        self,
        repo_root: Path,
        *,
        package_root: Path | None = None,
    ) -> tuple[Path, ...]:
        """Return first-party package paths excluding the bundle package."""

    def build_install_commands(
        self,
        *,
        python: str,
        repo_root: Path,
        include_core: bool = False,
        core_extras: tuple[str, ...] = (),
        include_bundle: bool = False,
        package_root: Path | None = None,
    ) -> tuple[tuple[str, ...], ...]:
        """Build the editable-install command plan for first-party packages."""


class _PackageInventoryModule(Protocol):
    """Protocol for the shared first-party package inventory helper."""

    FIRST_PARTY_PACKAGE_DIRS: tuple[str, ...]

    def package_paths(self, repo_root: Path) -> tuple[Path, ...]:
        """Return package paths in deterministic order."""


class _BuildHelperModule(Protocol):
    """Protocol for the standalone first-party build helper module."""

    def build_build_argv(
        self,
        *,
        python: str,
        package_path: Path,
        wheel_dir: Path,
    ) -> tuple[str, ...]:
        """Build the wheel-validation argv for one package."""

    def build_all_argv(
        self,
        *,
        python: str,
        repo_root: Path,
        wheel_dir: Path,
    ) -> tuple[tuple[str, ...], ...]:
        """Build the complete wheel-validation command plan."""

    def cleanup_build_artifacts(self, package_path: Path) -> None:
        """Remove known package-local wheel-build artifacts."""


class _ReleaseInstallRehearsalModule(Protocol):
    """Protocol for the installed-wheel release rehearsal helper."""

    def build_first_party_wheels_argv(
        self,
        *,
        python: str,
        repo_root: Path,
        wheel_dir: Path,
    ) -> tuple[str, ...]:
        """Build the first-party wheel-rehearsal command."""

    def build_root_wheel_argv(
        self,
        *,
        python: str,
        repo_root: Path,
        wheel_dir: Path,
    ) -> tuple[str, ...]:
        """Build the core wheel-rehearsal command."""

    def discover_wheel_paths(self, wheel_dir: Path) -> tuple[Path, ...]:
        """Return built wheel paths in deterministic order."""

    def build_install_wheels_argv(
        self,
        *,
        python: str,
        install_dir: Path,
        wheel_paths: tuple[Path, ...],
    ) -> tuple[str, ...]:
        """Build the installed-wheel rehearsal install command."""

    def build_probe_argv(self, *, python: str) -> tuple[str, ...]:
        """Build the installed-wheel discovery probe command."""


class _ReleaseArtifactBuildModule(Protocol):
    """Protocol for the release-artifact build helper."""

    def release_package_paths(self, repo_root: Path) -> tuple[Path, ...]:
        """Return release package roots in deterministic order."""

    def build_artifact_argv(
        self,
        *,
        python: str,
        package_path: Path,
    ) -> tuple[str, ...]:
        """Build the release artifact command for one package root."""

    def artifact_check_argv(
        self,
        *,
        python: str,
        package_path: Path,
    ) -> tuple[str, ...]:
        """Build the twine-check command for one package root."""

    def build_release_plan(
        self,
        *,
        python: str,
        repo_root: Path,
    ) -> tuple[tuple[str, ...], ...]:
        """Build the ordered release-artifact plan."""


class _SplitRepoVerificationModule(Protocol):
    """Protocol for the exported split-repo verification helper."""

    def split_repo_names(self) -> tuple[str, ...]:
        """Return split repository names in deterministic validation order."""

    def build_repo_validation_commands(
        self,
        *,
        python: str,
        exported_repo_root: Path,
        core_repo_root: Path,
    ) -> tuple[tuple[str, ...], ...]:
        """Build the validation command plan for one exported split repository."""


class _BootstrapHelperModule(Protocol):
    """Protocol for the standalone bootstrap helper module."""

    def build_bootstrap_commands(
        self,
        *,
        repo_root: Path,
        python: str,
        skip_validation: bool,
    ) -> list[CommandSpec]:
        """Build the ordered bootstrap command plan."""


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


def test_editable_package_paths_follow_authoritative_first_party_order() -> None:
    """
    Resolve first-party package directories in deterministic install order.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test asserts the helper preserves the accepted first-party package list.
    """
    helper = _load_install_helper()
    repo_root = Path("/tmp/codira")

    assert helper.first_party_package_root(repo_root, None) == (repo_root / "packages")
    assert helper.editable_package_paths(repo_root) == (
        repo_root / "packages/codira-analyzer-python",
        repo_root / "packages/codira-analyzer-json",
        repo_root / "packages/codira-analyzer-c",
        repo_root / "packages/codira-analyzer-bash",
        repo_root / "packages/codira-backend-sqlite",
        repo_root / "packages/codira-bundle-official",
    )
    assert helper.FIRST_PARTY_EDITABLE_PACKAGES == (
        "packages/codira-analyzer-python",
        "packages/codira-analyzer-json",
        "packages/codira-analyzer-c",
        "packages/codira-analyzer-bash",
        "packages/codira-backend-sqlite",
        "packages/codira-bundle-official",
    )


def test_install_helper_can_target_exported_split_repositories() -> None:
    """
    Build editable-install commands against an external split-repository root.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test asserts local bootstrap can repair stale editable installs by
        targeting the actual split repository directory.
    """
    helper = _load_install_helper()
    repo_root = Path("/tmp/codira")
    package_root = Path("/tmp/codira-split-repos")

    assert helper.first_party_package_root(repo_root, package_root) == package_root
    assert helper.editable_package_paths(
        repo_root,
        package_root=package_root,
    ) == (
        package_root / "codira-analyzer-python",
        package_root / "codira-analyzer-json",
        package_root / "codira-analyzer-c",
        package_root / "codira-analyzer-bash",
        package_root / "codira-backend-sqlite",
        package_root / "codira-bundle-official",
    )
    assert helper.bundle_package_path(
        repo_root,
        package_root=package_root,
    ) == (package_root / "codira-bundle-official")
    assert helper.build_install_commands(
        python="/tmp/codira/.venv/bin/python",
        repo_root=repo_root,
        include_core=True,
        include_bundle=True,
        package_root=package_root,
    ) == (
        (
            "/tmp/codira/.venv/bin/python",
            "-m",
            "pip",
            "install",
            "-e",
            "/tmp/codira",
            "-e",
            "/tmp/codira-split-repos/codira-analyzer-python",
            "-e",
            "/tmp/codira-split-repos/codira-analyzer-json",
            "-e",
            "/tmp/codira-split-repos/codira-analyzer-c",
            "-e",
            "/tmp/codira-split-repos/codira-analyzer-bash",
            "-e",
            "/tmp/codira-split-repos/codira-backend-sqlite",
        ),
        (
            "/tmp/codira/.venv/bin/python",
            "-m",
            "pip",
            "install",
            "--no-deps",
            "-e",
            "/tmp/codira-split-repos/codira-bundle-official",
        ),
    )


def test_shared_first_party_package_inventory_stays_in_split_order() -> None:
    """
    Resolve the shared first-party package inventory in deterministic order.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test asserts the shared package inventory stays aligned with the
        accepted split/package order.
    """
    helper = _load_first_party_package_inventory()
    repo_root = Path("/tmp/codira")

    assert helper.package_paths(repo_root) == (
        repo_root / "packages/codira-analyzer-python",
        repo_root / "packages/codira-analyzer-json",
        repo_root / "packages/codira-analyzer-c",
        repo_root / "packages/codira-analyzer-bash",
        repo_root / "packages/codira-backend-sqlite",
        repo_root / "packages/codira-bundle-official",
    )
    assert helper.FIRST_PARTY_PACKAGE_DIRS == (
        "packages/codira-analyzer-python",
        "packages/codira-analyzer-json",
        "packages/codira-analyzer-c",
        "packages/codira-analyzer-bash",
        "packages/codira-backend-sqlite",
        "packages/codira-bundle-official",
    )


def test_build_install_argv_installs_each_first_party_package_editably() -> None:
    """
    Build the exact editable-install command for first-party packages.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test asserts the helper emits the expected pip command arguments
        without installing the curated bundle by default.
    """
    helper = _load_install_helper()
    repo_root = Path("/tmp/codira")

    assert helper.bundle_package_path(repo_root) == (
        repo_root / "packages/codira-bundle-official"
    )
    assert helper.non_bundle_package_paths(repo_root) == (
        repo_root / "packages/codira-analyzer-python",
        repo_root / "packages/codira-analyzer-json",
        repo_root / "packages/codira-analyzer-c",
        repo_root / "packages/codira-analyzer-bash",
        repo_root / "packages/codira-backend-sqlite",
    )
    assert helper.build_install_commands(
        python="/tmp/codira/.venv/bin/python",
        repo_root=repo_root,
    ) == (
        (
            "/tmp/codira/.venv/bin/python",
            "-m",
            "pip",
            "install",
            "-e",
            "/tmp/codira/packages/codira-analyzer-python",
            "-e",
            "/tmp/codira/packages/codira-analyzer-json",
            "-e",
            "/tmp/codira/packages/codira-analyzer-c",
            "-e",
            "/tmp/codira/packages/codira-analyzer-bash",
            "-e",
            "/tmp/codira/packages/codira-backend-sqlite",
        ),
    )


def test_install_helper_can_include_core_repo_with_requested_extras() -> None:
    """
    Build one source-tree install command for core plus first-party packages.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test asserts the helper can prepend the editable core requirement
        with requested extras ahead of the extracted package set.
    """
    helper = _load_install_helper()
    repo_root = Path("/tmp/codira")

    assert helper.editable_core_requirement(repo_root) == "/tmp/codira"
    assert (
        helper.editable_core_requirement(
            repo_root,
            extras=("semantic",),
        )
        == "/tmp/codira[semantic]"
    )
    assert helper.build_install_commands(
        python="/tmp/codira/.venv/bin/python",
        repo_root=repo_root,
        include_core=True,
        core_extras=("semantic",),
    ) == (
        (
            "/tmp/codira/.venv/bin/python",
            "-m",
            "pip",
            "install",
            "-e",
            "/tmp/codira[semantic]",
            "-e",
            "/tmp/codira/packages/codira-analyzer-python",
            "-e",
            "/tmp/codira/packages/codira-analyzer-json",
            "-e",
            "/tmp/codira/packages/codira-analyzer-c",
            "-e",
            "/tmp/codira/packages/codira-analyzer-bash",
            "-e",
            "/tmp/codira/packages/codira-backend-sqlite",
        ),
    )


def test_install_helper_can_opt_into_bundle_package() -> None:
    """
    Build the local install plan with an explicit curated bundle step.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test asserts the helper only adds the bundle meta-package when it
        is requested explicitly.
    """
    helper = _load_install_helper()
    repo_root = Path("/tmp/codira")

    assert helper.build_install_commands(
        python="/tmp/codira/.venv/bin/python",
        repo_root=repo_root,
        include_bundle=True,
    ) == (
        (
            "/tmp/codira/.venv/bin/python",
            "-m",
            "pip",
            "install",
            "-e",
            "/tmp/codira/packages/codira-analyzer-python",
            "-e",
            "/tmp/codira/packages/codira-analyzer-json",
            "-e",
            "/tmp/codira/packages/codira-analyzer-c",
            "-e",
            "/tmp/codira/packages/codira-analyzer-bash",
            "-e",
            "/tmp/codira/packages/codira-backend-sqlite",
        ),
        (
            "/tmp/codira/.venv/bin/python",
            "-m",
            "pip",
            "install",
            "--no-deps",
            "-e",
            "/tmp/codira/packages/codira-bundle-official",
        ),
    )


def test_build_helper_rehearses_each_first_party_package_boundary() -> None:
    """
    Build the split-readiness command plan for every first-party package.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test asserts the build helper emits one explicit wheel-build
        command per future package repository.
    """
    helper = _load_build_helper()
    repo_root = Path("/tmp/codira")
    wheel_dir = repo_root / ".artifacts" / "wheels"

    assert helper.build_all_argv(
        python="/tmp/codira/.venv/bin/python",
        repo_root=repo_root,
        wheel_dir=wheel_dir,
    ) == (
        (
            "/tmp/codira/.venv/bin/python",
            "-m",
            "pip",
            "wheel",
            "--no-deps",
            "--wheel-dir",
            "/tmp/codira/.artifacts/wheels",
            "/tmp/codira/packages/codira-analyzer-python",
        ),
        (
            "/tmp/codira/.venv/bin/python",
            "-m",
            "pip",
            "wheel",
            "--no-deps",
            "--wheel-dir",
            "/tmp/codira/.artifacts/wheels",
            "/tmp/codira/packages/codira-analyzer-json",
        ),
        (
            "/tmp/codira/.venv/bin/python",
            "-m",
            "pip",
            "wheel",
            "--no-deps",
            "--wheel-dir",
            "/tmp/codira/.artifacts/wheels",
            "/tmp/codira/packages/codira-analyzer-c",
        ),
        (
            "/tmp/codira/.venv/bin/python",
            "-m",
            "pip",
            "wheel",
            "--no-deps",
            "--wheel-dir",
            "/tmp/codira/.artifacts/wheels",
            "/tmp/codira/packages/codira-analyzer-bash",
        ),
        (
            "/tmp/codira/.venv/bin/python",
            "-m",
            "pip",
            "wheel",
            "--no-deps",
            "--wheel-dir",
            "/tmp/codira/.artifacts/wheels",
            "/tmp/codira/packages/codira-backend-sqlite",
        ),
        (
            "/tmp/codira/.venv/bin/python",
            "-m",
            "pip",
            "wheel",
            "--no-deps",
            "--wheel-dir",
            "/tmp/codira/.artifacts/wheels",
            "/tmp/codira/packages/codira-bundle-official",
        ),
    )


def test_build_helper_cleans_known_package_build_artifacts(tmp_path: Path) -> None:
    """
    Remove transient build artifacts created during local wheel validation.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary directory managed by pytest.

    Returns
    -------
    None
        The test asserts the helper removes `build/` and `*.egg-info` outputs.
    """
    helper = _load_build_helper()
    package_path = tmp_path / "packages" / "codira-analyzer-python"
    build_dir = package_path / "build"
    egg_info_dir = package_path / "src" / "codira_analyzer_python.egg-info"
    build_dir.mkdir(parents=True)
    egg_info_dir.mkdir(parents=True)

    helper.cleanup_build_artifacts(package_path)

    assert not build_dir.exists()
    assert not egg_info_dir.exists()


def test_release_install_rehearsal_builds_first_party_and_core_wheels() -> None:
    """
    Keep the release rehearsal explicit about first-party and core wheel builds.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test asserts the rehearsal builds the first-party package set before
        the core wheel.
    """
    helper = _load_release_install_rehearsal_helper()
    repo_root = Path("/tmp/codira")
    wheel_dir = Path("/tmp/codira-wheels")

    assert helper.build_first_party_wheels_argv(
        python="python",
        repo_root=repo_root,
        wheel_dir=wheel_dir,
    ) == (
        "python",
        str(repo_root / "scripts" / "build_first_party_packages.py"),
        "--wheel-dir",
        str(wheel_dir),
    )
    assert helper.build_root_wheel_argv(
        python="python",
        repo_root=repo_root,
        wheel_dir=wheel_dir,
    ) == (
        "python",
        "-m",
        "pip",
        "wheel",
        "--no-deps",
        "--wheel-dir",
        str(wheel_dir),
        str(repo_root),
    )


def test_release_install_rehearsal_installs_sorted_wheels_into_target_directory(
    tmp_path: Path,
) -> None:
    """
    Keep installed-wheel rehearsal deterministic across artifact build order.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary directory managed by pytest.

    Returns
    -------
    None
        The test asserts discovered wheels are sorted and installed into the
        requested target directory.
    """
    helper = _load_release_install_rehearsal_helper()
    wheel_dir = tmp_path / "wheels"
    install_dir = tmp_path / "site-packages"
    wheel_dir.mkdir()
    (wheel_dir / "codira_backend_sqlite-1.0.0-py3-none-any.whl").write_text(
        "",
        encoding="utf-8",
    )
    (wheel_dir / "codira-1.0.0-py3-none-any.whl").write_text("", encoding="utf-8")

    wheel_paths = helper.discover_wheel_paths(wheel_dir)

    assert wheel_paths == (
        wheel_dir / "codira-1.0.0-py3-none-any.whl",
        wheel_dir / "codira_backend_sqlite-1.0.0-py3-none-any.whl",
    )
    assert helper.build_install_wheels_argv(
        python="python",
        install_dir=install_dir,
        wheel_paths=wheel_paths,
    ) == (
        "python",
        "-m",
        "pip",
        "install",
        "--no-deps",
        "--target",
        str(install_dir),
        str(wheel_dir / "codira-1.0.0-py3-none-any.whl"),
        str(wheel_dir / "codira_backend_sqlite-1.0.0-py3-none-any.whl"),
    )


def test_release_install_rehearsal_probe_stays_focused_on_discovery_contract() -> None:
    """
    Keep the release rehearsal probe aligned to the plugin discovery contract.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test asserts the release probe inspects the installed codira
        location, backend module, and analyzer names.
    """
    helper = _load_release_install_rehearsal_helper()

    probe_argv = helper.build_probe_argv(python="python")

    assert probe_argv[0] == "python"
    assert probe_argv[1] == "-c"
    assert "'backend_module': type(backend).__module__" in probe_argv[2]
    assert "'analyzers': [analyzer.name for analyzer in analyzers]" in probe_argv[2]


def test_release_artifact_helper_covers_core_and_all_first_party_packages() -> None:
    """
    Keep the release build plan aligned to the accepted distribution set.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test asserts the release helper covers core plus every first-party
        distribution in deterministic order.
    """
    helper = _load_release_artifact_build_helper()
    repo_root = Path("/tmp/codira")

    assert helper.release_package_paths(repo_root) == (
        repo_root,
        repo_root / "packages/codira-analyzer-python",
        repo_root / "packages/codira-analyzer-json",
        repo_root / "packages/codira-analyzer-c",
        repo_root / "packages/codira-analyzer-bash",
        repo_root / "packages/codira-backend-sqlite",
        repo_root / "packages/codira-bundle-official",
    )


def test_release_artifact_helper_builds_build_and_twine_commands() -> None:
    """
    Keep release-artifact command construction explicit and deterministic.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test asserts build and twine-check commands use the expected tool
        surfaces and package order.
    """
    helper = _load_release_artifact_build_helper()
    repo_root = Path("/tmp/codira")

    assert helper.build_artifact_argv(
        python="python",
        package_path=repo_root / "packages/codira-backend-sqlite",
    ) == (
        "python",
        "-m",
        "build",
        "--wheel",
        "--sdist",
        "/tmp/codira/packages/codira-backend-sqlite",
    )
    assert helper.artifact_check_argv(
        python="python",
        package_path=repo_root / "packages/codira-backend-sqlite",
    ) == (
        "python",
        "-m",
        "twine",
        "check",
        "/tmp/codira/packages/codira-backend-sqlite/dist/*",
    )

    release_plan = helper.build_release_plan(python="python", repo_root=repo_root)

    assert release_plan[:2] == (
        ("python", "-m", "build", "--wheel", "--sdist", "/tmp/codira"),
        (
            "python",
            "-m",
            "build",
            "--wheel",
            "--sdist",
            "/tmp/codira/packages/codira-analyzer-python",
        ),
    )
    assert release_plan[-2:] == (
        (
            "python",
            "-m",
            "twine",
            "check",
            "/tmp/codira/packages/codira-backend-sqlite/dist/*",
        ),
        (
            "python",
            "-m",
            "twine",
            "check",
            "/tmp/codira/packages/codira-bundle-official/dist/*",
        ),
    )


def test_split_repo_verification_uses_local_core_checkout_before_package_install() -> (
    None
):
    """
    Keep split-repo rehearsal pinned to the local core checkout before publish.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test asserts exported package repos install the local core checkout
        before their own test extra.
    """
    helper = _load_split_repo_verification_helper()
    export_root = Path("/tmp/newrepos/split")
    repo_root = export_root / "codira-analyzer-python"
    core_root = Path("/tmp/codira")

    assert helper.split_repo_names() == (
        "codira-analyzer-python",
        "codira-analyzer-json",
        "codira-analyzer-c",
        "codira-analyzer-bash",
        "codira-backend-sqlite",
        "codira-bundle-official",
    )
    assert helper.build_repo_validation_commands(
        python="python",
        exported_repo_root=repo_root,
        core_repo_root=core_root,
    )[:3] == (
        ("python", "-m", "pip", "install", "--upgrade", "pip"),
        ("python", "-m", "pip", "install", "-e", "/tmp/codira[semantic]"),
        (
            "python",
            "-m",
            "pip",
            "install",
            "-e",
            "/tmp/newrepos/split/codira-analyzer-python[test]",
        ),
    )


def test_split_repo_verification_installs_local_first_party_packages_for_bundle() -> (
    None
):
    """
    Keep bundle split-repo rehearsal independent from unpublished package indexes.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test asserts exported bundle validation installs the local first-party
        package repos before validating the bundle repo itself.
    """
    helper = _load_split_repo_verification_helper()
    export_root = Path("/tmp/newrepos/split")
    bundle_root = export_root / "codira-bundle-official"
    core_root = Path("/tmp/codira")

    commands = helper.build_repo_validation_commands(
        python="python",
        exported_repo_root=bundle_root,
        core_repo_root=core_root,
    )

    assert commands[:8] == (
        ("python", "-m", "pip", "install", "--upgrade", "pip"),
        ("python", "-m", "pip", "install", "-e", "/tmp/codira[semantic]"),
        (
            "python",
            "-m",
            "pip",
            "install",
            "-e",
            "/tmp/newrepos/split/codira-analyzer-python",
        ),
        (
            "python",
            "-m",
            "pip",
            "install",
            "-e",
            "/tmp/newrepos/split/codira-analyzer-json",
        ),
        (
            "python",
            "-m",
            "pip",
            "install",
            "-e",
            "/tmp/newrepos/split/codira-analyzer-c",
        ),
        (
            "python",
            "-m",
            "pip",
            "install",
            "-e",
            "/tmp/newrepos/split/codira-analyzer-bash",
        ),
        (
            "python",
            "-m",
            "pip",
            "install",
            "-e",
            "/tmp/newrepos/split/codira-backend-sqlite",
        ),
        (
            "python",
            "-m",
            "pip",
            "install",
            "-e",
            "/tmp/newrepos/split/codira-bundle-official[test]",
        ),
    )


def test_build_bootstrap_commands_reuses_shared_first_party_install_command() -> None:
    """
    Reuse the shared first-party install helper inside bootstrap planning.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test asserts bootstrap no longer hard-codes a divergent package list.
    """
    bootstrap_helper = _load_bootstrap_helper()
    repo_root = Path("/tmp/codira")
    commands = bootstrap_helper.build_bootstrap_commands(
        repo_root=repo_root,
        python="/usr/bin/python3",
        skip_validation=True,
    )

    install_command = next(
        command
        for command in commands
        if command.description
        == "Install extracted first-party analyzer and backend packages"
    )

    assert install_command.argv == (
        str(repo_root / ".venv" / "bin" / "python"),
        "scripts/install_first_party_packages.py",
        "--include-core",
        "--core-extra",
        "dev",
        "--core-extra",
        "docs",
        "--core-extra",
        "semantic",
    )
