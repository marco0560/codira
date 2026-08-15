"""Plan optional model, calibration, and repository-scoped service operations."""
# ruff: noqa: TRY003, EM101

from __future__ import annotations

import os
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path


class ServiceKind(StrEnum):
    """Supported repository-scoped daemon service families.

    Parameters
    ----------
    None

    Returns
    -------
    None
    """

    INDEXING = "daemon"
    QUERY = "query-daemon"


@dataclass(frozen=True)
class ModelProvisionPlan:
    """Describe idempotent embedding-model provisioning in one environment.

    Parameters
    ----------
    python : pathlib.Path
        Target environment Python executable.
    command : tuple[str, ...]
        Shell-free provisioning command.
    postcondition : str
        State checked before a repeat provisioning attempt.
    model_root : pathlib.Path | None
        Optional shared model store selected for the target runtime.
    """

    python: Path
    command: tuple[str, ...]
    postcondition: str
    model_root: Path | None = None


@dataclass(frozen=True)
class HardwareRecommendation:
    """Provenance-rich recommendation produced without modifying configuration.

    Parameters
    ----------
    cpu_count : int
        Detected available CPU count.
    config_delta : dict[str, object]
        Proposed configuration-only change.
    reason : str
        Human-readable source of the recommendation.
    """

    cpu_count: int
    config_delta: dict[str, object]
    reason: str


@dataclass(frozen=True)
class CalibrationProposal:
    """A separately-confirmed configuration delta derived from a recommendation.

    Parameters
    ----------
    recommendation : HardwareRecommendation
        Read-only recommendation being proposed.
    config_delta : dict[str, object]
        Exact configuration delta requiring confirmation.
    """

    recommendation: HardwareRecommendation
    config_delta: dict[str, object]


@dataclass(frozen=True)
class ServicePlan:
    """Describe one explicit non-elevating service operation.

    Parameters
    ----------
    kind : ServiceKind
        Indexing or query daemon family.
    platform : str
        Target platform family.
    root : pathlib.Path
        Fixed repository root.
    output_root : pathlib.Path
        Fixed output root.
    action : str
        Explicit lifecycle operation.
    command : tuple[str, ...]
        Shell-free command vector.
    config_delta : dict[str, object]
        Configuration required before install or start.
    workspace_name : str | None
        Registered workspace selected for the service command, when applicable.
    """

    kind: ServiceKind
    platform: str
    root: Path
    output_root: Path
    action: str
    command: tuple[str, ...]
    config_delta: dict[str, object]
    workspace_name: str | None = None


@dataclass(frozen=True)
class ServicePlanOptions:
    """Select deterministic platform and workspace service-plan routing.

    Parameters
    ----------
    platform : str | None
        Explicit platform override for deterministic planning.
    workspace_name : str | None
        Registered workspace selected instead of direct path routing.
    """

    platform: str | None = None
    workspace_name: str | None = None


@dataclass(frozen=True)
class ServiceVerification:
    """Report isolated platform-service verification status.

    Parameters
    ----------
    plan : ServicePlan
        Service plan that was checked.
    healthy : bool
        Whether the platform status command succeeded.
    detail : str
        Safe diagnostic or remediation guidance.
    """

    plan: ServicePlan
    healthy: bool
    detail: str


CommandRunner = Callable[[tuple[str, ...]], None]
ReadinessProbe = Callable[[], bool]


def model_provision_plan(
    python: Path, *, model_root: Path | None = None
) -> ModelProvisionPlan:
    """Build a target-environment model provisioning plan.

    Parameters
    ----------
    python : pathlib.Path
        Target environment Python executable.
    model_root : pathlib.Path | None, optional
        Explicit user-owned shared store for the target runtime. ``None`` lets
        Codira resolve its configured, environment, or platform default root.

    Returns
    -------
    ModelProvisionPlan
        Idempotent provisioning command and postcondition.
    """
    script = (
        "from codira.semantic.embeddings import provision_embedding_model; "
        "provision_embedding_model(quiet=True)"
    )
    if model_root is not None:
        script = (
            "import os; "
            f"os.environ['CODIRA_MODEL_ROOT'] = {str(model_root)!r}; "
            f"{script}"
        )
    return ModelProvisionPlan(
        python=python,
        command=(str(python), "-c", script),
        postcondition="configured embedding artifacts are in the shared model store",
        model_root=model_root,
    )


def provision_model(
    plan: ModelProvisionPlan,
    *,
    is_ready: ReadinessProbe,
    runner: CommandRunner,
) -> bool:
    """Provision a model only when its target environment is not ready.

    Parameters
    ----------
    plan : ModelProvisionPlan
        Target-environment provisioning plan.
    is_ready : collections.abc.Callable[[], bool]
        Artifact readiness probe.
    runner : CommandRunner
        Provisioning command runner.

    Returns
    -------
    bool
        ``True`` when provisioning ran, otherwise ``False`` for an idempotent no-op.
    """
    if is_ready():
        return False
    runner(plan.command)
    return True


def recommend_hardware(cpu_count: int | None = None) -> HardwareRecommendation:
    """Produce a read-only CPU-based configuration recommendation.

    Parameters
    ----------
    cpu_count : int | None, optional
        Explicit CPU count for deterministic callers; ``None`` probes locally.

    Returns
    -------
    HardwareRecommendation
        Recommendation with provenance and no write side effect.
    """
    observed = os.cpu_count() if cpu_count is None else cpu_count
    detected = max(1, observed or 1)
    threads = min(detected, 8)
    return HardwareRecommendation(
        cpu_count=detected,
        config_delta={"embeddings": {"torch_num_threads": threads}},
        reason=f"detected {detected} logical CPU(s); bounded recommendation is {threads}",
    )


def calibration_proposal(recommendation: HardwareRecommendation) -> CalibrationProposal:
    """Create a separately-confirmed calibration proposal.

    Parameters
    ----------
    recommendation : HardwareRecommendation
        Recommendation to expose for confirmation.

    Returns
    -------
    CalibrationProposal
        Configuration delta with no write side effect.
    """
    return CalibrationProposal(recommendation, recommendation.config_delta.copy())


def apply_calibration(
    proposal: CalibrationProposal,
    *,
    confirmed: bool,
    apply: Callable[[Mapping[str, object]], None],
) -> None:
    """Apply a calibration proposal only after its second confirmation.

    Parameters
    ----------
    proposal : CalibrationProposal
        Proposed configuration delta.
    confirmed : bool
        Explicit second-confirmation state.
    apply : collections.abc.Callable[[collections.abc.Mapping[str, object]], None]
        Configuration write callback.

    Returns
    -------
    None

    Raises
    ------
    ValueError
        If the proposal lacks second confirmation.
    """
    if not confirmed:
        raise ValueError("calibration requires a second explicit confirmation")
    apply(proposal.config_delta)


def service_plan(
    kind: ServiceKind,
    root: Path,
    output_root: Path,
    action: str,
    *,
    options: ServicePlanOptions = ServicePlanOptions(),
) -> ServicePlan:
    """Build an explicit repository-scoped platform service command.

    Parameters
    ----------
    kind : ServiceKind
        Service family.
    root : pathlib.Path
        Repository root fixed by the service.
    output_root : pathlib.Path
        Output root fixed by the service.
    action : {"configure", "install", "start", "status"}
        Explicit lifecycle action.
    options : ServicePlanOptions, optional
        Platform override and optional registered workspace selection.

    Returns
    -------
    ServicePlan
        Non-elevating service command plan.

    Raises
    ------
    ValueError
        If the action or platform is unsupported.
    """
    resolved_platform = sys.platform if options.platform is None else options.platform
    if resolved_platform not in {"linux", "darwin", "win32"}:
        raise ValueError("services require Linux, macOS, or Windows")
    if action not in {"configure", "install", "start", "status"}:
        raise ValueError("service action must be configure, install, start, or status")
    config_key = "daemon" if kind is ServiceKind.INDEXING else "query_daemon"
    config_delta: dict[str, object] = {config_key: {"enabled": True}}
    routing = (
        ("--workspace", options.workspace_name)
        if options.workspace_name is not None
        else (
            "--path",
            str(root.resolve()),
            "--output-dir",
            str(output_root.resolve()),
        )
    )
    command = (
        ()
        if action == "configure"
        else (
            "codira",
            kind.value,
            action,
            *routing,
        )
    )
    return ServicePlan(
        kind=kind,
        platform=resolved_platform,
        root=root.resolve(),
        output_root=output_root.resolve(),
        action=action,
        command=command,
        config_delta=config_delta,
        workspace_name=options.workspace_name,
    )


def verify_service(plan: ServicePlan, runner: CommandRunner) -> ServiceVerification:
    """Verify a service in isolation and return remediation instead of raising.

    Parameters
    ----------
    plan : ServicePlan
        Service plan to verify.
    runner : CommandRunner
        Status command runner.

    Returns
    -------
    ServiceVerification
        Healthy status or platform-specific remediation guidance.
    """
    status_command = (*plan.command[:2], "status", *plan.command[3:])
    try:
        runner(status_command)
    except (OSError, RuntimeError) as error:
        return ServiceVerification(
            plan,
            False,
            f"service status unavailable: {error}; review the {plan.platform} user-service logs",
        )
    return ServiceVerification(plan, True, "service status verified")
