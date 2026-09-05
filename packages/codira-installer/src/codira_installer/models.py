"""Immutable request, plan, result, and journal models for the installer."""
# ruff: noqa: TRY003, EM101, EM102

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path


class InstallSource(StrEnum):
    """Package source options.

    Parameters
    ----------
    None

    Returns
    -------
    None
    """

    PYPI = "pypi"
    LOCAL_CHECKOUT = "local-checkout"


class EnvironmentKind(StrEnum):
    """Supported environment target kinds.

    Parameters
    ----------
    None

    Returns
    -------
    None
    """

    CURRENT = "current"
    EXISTING = "existing"
    NEW = "new"


class RuntimeKind(StrEnum):
    """Supported Codira runtime destinations.

    Parameters
    ----------
    None

    Returns
    -------
    None
    """

    MANAGED = "managed"
    CURRENT = "current"
    EXISTING = "existing"
    NEW = "new"


class RuntimeOperation(StrEnum):
    """Explicit lifecycle operation for one Codira runtime.

    Parameters
    ----------
    None

    Returns
    -------
    None
    """

    INSTALL = "install"
    UPDATE = "update"
    REPAIR = "repair"
    MODIFY = "modify"


class PackageManager(StrEnum):
    """Bounded package-manager backends.

    Parameters
    ----------
    None

    Returns
    -------
    None
    """

    UV = "uv"
    PIP = "pip"


class InstallationProfile(StrEnum):
    """Catalog-derived package selection profiles.

    Parameters
    ----------
    None

    Returns
    -------
    None
    """

    CORE_ONLY = "core-only"
    RECOMMENDED = "recommended"
    FULL_OFFICIAL = "full-official"


@dataclass(frozen=True)
class EnvironmentTarget:
    """A target environment selected by the installer.

    Parameters
    ----------
    kind : EnvironmentKind
        Current process, explicit existing, or newly created environment.
    path : pathlib.Path | None
        Environment root for explicit existing and new targets.
    """

    kind: EnvironmentKind
    path: Path | None = None

    def __post_init__(self) -> None:
        """Validate target path cardinality.

        Parameters
        ----------
        None

        Returns
        -------
        None

        Raises
        ------
        ValueError
            If the target kind and path are incompatible.
        """
        if self.kind is EnvironmentKind.CURRENT and self.path is not None:
            raise ValueError("current target cannot contain an environment path")
        if self.kind is not EnvironmentKind.CURRENT and self.path is None:
            raise ValueError(f"{self.kind} target requires an environment path")


@dataclass(frozen=True)
class RuntimeTarget:
    """Select the independent destination that executes Codira.

    Parameters
    ----------
    kind : RuntimeKind
        Managed standalone, current, existing, or new runtime destination.
    path : pathlib.Path | None
        Runtime root for managed, existing, and new destinations.
    """

    kind: RuntimeKind = RuntimeKind.MANAGED
    path: Path | None = None

    def __post_init__(self) -> None:
        """Validate runtime-root cardinality.

        Parameters
        ----------
        None

        Returns
        -------
        None

        Raises
        ------
        ValueError
            If the runtime kind and path are incompatible.
        """
        if self.kind is RuntimeKind.CURRENT and self.path is not None:
            raise ValueError("current runtime cannot contain a runtime path")


@dataclass(frozen=True)
class WorkspaceRegistration:
    """Optionally register one analyzed repository after runtime installation.

    Parameters
    ----------
    name : str
        Stable workspace name.
    repository_root : pathlib.Path
        Analyzed repository selected independently of the runtime destination.
    state_root : pathlib.Path | None
        Optional external workspace state root.
    config_file : pathlib.Path | None
        Optional workspace configuration source.
    """

    name: str
    repository_root: Path
    state_root: Path | None = None
    config_file: Path | None = None

    def __post_init__(self) -> None:
        """Reject an empty workspace identity before planning.

        Parameters
        ----------
        None

        Returns
        -------
        None

        Raises
        ------
        ValueError
            If the workspace name is blank.
        """
        if not self.name.strip():
            raise ValueError("workspace registration requires a name")


@dataclass(frozen=True)
class InstallerRequest:
    """Declarative user choices before plan resolution.

    Parameters
    ----------
    target : EnvironmentTarget
        Selected installation target.
    source : InstallSource
        Coordinated PyPI release or cloned checkout source.
    checkout : pathlib.Path | None
        Cloned Codira root for local-checkout requests.
    manager : PackageManager
        Package-manager backend.
    profile : InstallationProfile
        Named package selection profile.
    packages : tuple[str, ...]
        Explicit Advanced package override.
    runtime_profile : str
        Existing runtime-tuning profile name.
    runtime : RuntimeTarget
        Independent Codira runtime destination; managed is the default.
    operation : RuntimeOperation
        Explicit install, update, repair, or modify lifecycle request.
    workspace : WorkspaceRegistration | None
        Optional analyzed repository registration, never an environment target.
    model_store : pathlib.Path | None
        Optional shared model-store location for the runtime.
    receipt_path : pathlib.Path | None
        Existing managed-runtime receipt required for non-install operations.
    """

    target: EnvironmentTarget
    source: InstallSource = InstallSource.PYPI
    checkout: Path | None = None
    manager: PackageManager = PackageManager.UV
    profile: InstallationProfile = InstallationProfile.RECOMMENDED
    packages: tuple[str, ...] = ()
    runtime_profile: str = "balanced"
    runtime: RuntimeTarget = field(default_factory=RuntimeTarget)
    operation: RuntimeOperation = RuntimeOperation.INSTALL
    workspace: WorkspaceRegistration | None = None
    model_store: Path | None = None
    receipt_path: Path | None = None


@dataclass(frozen=True)
class PlanStep:
    """One ordered shell-free execution step.

    Parameters
    ----------
    identifier : str
        Stable plan-step key.
    command : tuple[str, ...]
        Command argument vector.
    postcondition : str
        Idempotent completion predicate.
    """

    identifier: str
    command: tuple[str, ...]
    postcondition: str


@dataclass(frozen=True)
class InstallPlan:
    """A complete versioned plan suitable for JSON export and application.

    Parameters
    ----------
    schema_version : int
        JSON plan schema version.
    coordinated_version : str
        Required common distribution version.
    request : InstallerRequest
        Normalized installer choices.
    packages : tuple[str, ...]
        Ordered selected extensions.
    deselected_packages : tuple[str, ...]
        Retained installed extensions outside selection.
    steps : tuple[PlanStep, ...]
        Ordered preflight and apply operations.
    fingerprint : str
        Stable canonical-plan digest.
    """

    schema_version: int
    coordinated_version: str
    request: InstallerRequest
    packages: tuple[str, ...]
    deselected_packages: tuple[str, ...] = ()
    steps: tuple[PlanStep, ...] = ()
    fingerprint: str = ""

    def as_dict(self) -> dict[str, object]:
        """Return portable JSON-compatible plan content.

        Parameters
        ----------
        None

        Returns
        -------
        dict[str, object]
            Canonical plan payload.
        """
        payload = asdict(self)
        request = payload["request"]
        target = request["target"]
        if target["path"] is not None:
            target["path"] = str(target["path"])
        if request["checkout"] is not None:
            request["checkout"] = str(request["checkout"])
        runtime = request["runtime"]
        if runtime["path"] is not None:
            runtime["path"] = str(runtime["path"])
        workspace = request["workspace"]
        if workspace is not None:
            workspace["repository_root"] = str(workspace["repository_root"])
            if workspace["state_root"] is not None:
                workspace["state_root"] = str(workspace["state_root"])
            if workspace["config_file"] is not None:
                workspace["config_file"] = str(workspace["config_file"])
        if request["model_store"] is not None:
            request["model_store"] = str(request["model_store"])
        if request["receipt_path"] is not None:
            request["receipt_path"] = str(request["receipt_path"])
        return payload


@dataclass(frozen=True)
class StepResult:
    """Result of an execution step.

    Parameters
    ----------
    identifier : str
        Stable step key.
    completed : bool
        Whether the postcondition is satisfied.
    detail : str
        Safe result text.
    """

    identifier: str
    completed: bool
    detail: str


@dataclass(frozen=True)
class ExecutionJournal:
    """Credential-free resumable execution record.

    Parameters
    ----------
    fingerprint : str
        Applied plan digest.
    results : tuple[StepResult, ...]
        Successful results in plan order.
    """

    fingerprint: str
    results: tuple[StepResult, ...] = field(default_factory=tuple)

    def completed_identifiers(self) -> frozenset[str]:
        """Return steps already completed in this journal.

        Parameters
        ----------
        None

        Returns
        -------
        frozenset[str]
            Successful plan-step identifiers.
        """
        return frozenset(
            result.identifier for result in self.results if result.completed
        )
