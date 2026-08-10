"""Deterministically resolve, render, validate, and fingerprint installer plans."""
# ruff: noqa: TRY003, TRY004, TRY301, EM101, EM102

from __future__ import annotations

import hashlib
import json
import sys
from dataclasses import replace
from importlib.metadata import distributions
from pathlib import Path
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence

from codira_installer.catalog import load_catalog
from codira_installer.models import (
    EnvironmentKind,
    EnvironmentTarget,
    InstallationProfile,
    InstallerRequest,
    InstallPlan,
    InstallSource,
    PackageManager,
    PlanStep,
)

PLAN_SCHEMA_VERSION = 1
CORE_DISTRIBUTION = "codira"
RECOMMENDED_PACKAGES = ("codira-analyzer-python", "codira-backend-sqlite")


def _catalog_rows(catalog: Mapping[str, object]) -> tuple[Mapping[str, object], ...]:
    """Return generated catalog package rows.

    Parameters
    ----------
    catalog : collections.abc.Mapping[str, object]
        Generated installer catalog.

    Returns
    -------
    tuple[collections.abc.Mapping[str, object], ...]
        Catalog package rows.

    Raises
    ------
    ValueError
        If the catalog is structurally invalid.
    """
    rows = catalog.get("packages")
    if not isinstance(rows, list):
        raise TypeError("catalog packages must be a list")
    return tuple(cast("Mapping[str, object]", row) for row in rows)


def validate_request(request: InstallerRequest) -> None:
    """Validate source and backend constraints before host resolution.

    Parameters
    ----------
    request : InstallerRequest
        User request to validate.

    Returns
    -------
    None

    Raises
    ------
    ValueError
        If the request exceeds bounded installer support.
    """
    if request.source is InstallSource.LOCAL_CHECKOUT and request.checkout is None:
        raise ValueError("local-checkout source requires the cloned Codira root")
    if request.manager is PackageManager.PIP:
        if request.target.kind is EnvironmentKind.NEW:
            raise ValueError("pip cannot create environments")
        if request.source is InstallSource.LOCAL_CHECKOUT:
            raise ValueError("pip cannot install from local checkouts")


def _selected_packages(
    request: InstallerRequest, catalog: Mapping[str, object]
) -> tuple[str, ...]:
    """Resolve profile and Advanced overrides into stable package names.

    Parameters
    ----------
    request : InstallerRequest
        Validated installer request.
    catalog : collections.abc.Mapping[str, object]
        Generated installer catalog.

    Returns
    -------
    tuple[str, ...]
        Alphabetically ordered selected extension packages.
    """
    selectable = tuple(
        str(row["name"]) for row in _catalog_rows(catalog) if row["selectable"]
    )
    if request.packages:
        unknown = sorted(set(request.packages) - set(selectable))
        if unknown:
            raise ValueError(f"unknown selectable packages: {', '.join(unknown)}")
        return tuple(sorted(set(request.packages)))
    if request.profile is InstallationProfile.CORE_ONLY:
        return ()
    if request.profile is InstallationProfile.FULL_OFFICIAL:
        return tuple(sorted(selectable))
    return RECOMMENDED_PACKAGES


def _installed_distributions() -> frozenset[str]:
    """Return installed distribution names without retaining environment metadata.

    Parameters
    ----------
    None

    Returns
    -------
    frozenset[str]
        Normalized installed distribution names.
    """
    return frozenset(
        distribution.metadata["Name"].lower()
        for distribution in distributions()
        if distribution.metadata.get("Name")
    )


def _target_python(request: InstallerRequest) -> str:
    """Resolve the Python executable argument for a target environment.

    Parameters
    ----------
    request : InstallerRequest
        Validated installer request.

    Returns
    -------
    str
        Python executable path or current interpreter.
    """
    if request.target.kind is EnvironmentKind.CURRENT:
        return sys.executable
    assert request.target.path is not None
    executable = "Scripts/python.exe" if sys.platform == "win32" else "bin/python"
    return str(request.target.path / executable)


def _install_command(
    request: InstallerRequest,
    packages: Sequence[str],
    version: str,
    catalog: Mapping[str, object],
) -> tuple[str, ...]:
    """Build one shell-free package-install command.

    Parameters
    ----------
    request : InstallerRequest
        Validated installer request.
    packages : collections.abc.Sequence[str]
        Selected extensions.
    version : str
        Required coordinated version.
    catalog : collections.abc.Mapping[str, object]
        Generated catalog supplying local package paths.

    Returns
    -------
    tuple[str, ...]
        Command argument vector.
    """
    if request.source is InstallSource.LOCAL_CHECKOUT:
        assert request.checkout is not None
        paths = {str(row["name"]): str(row["path"]) for row in _catalog_rows(catalog)}
        local_projects = (
            str(request.checkout),
            *(str(request.checkout / paths[name]) for name in packages),
        )
        return (
            "uv",
            "pip",
            "install",
            "--python",
            _target_python(request),
            *local_projects,
        )
    requirements = tuple(
        f"{name}=={version}" for name in (CORE_DISTRIBUTION, *packages)
    )
    if request.manager is PackageManager.PIP:
        return (sys.executable, "-m", "pip", "install", *requirements)
    return ("uv", "pip", "install", "--python", _target_python(request), *requirements)


def _steps(
    request: InstallerRequest,
    packages: tuple[str, ...],
    version: str,
    catalog: Mapping[str, object],
) -> tuple[PlanStep, ...]:
    """Build ordered idempotent preflight and apply steps.

    Parameters
    ----------
    request : InstallerRequest
        Validated installer request.
    packages : tuple[str, ...]
        Selected extensions.
    version : str
        Required coordinated version.
    catalog : collections.abc.Mapping[str, object]
        Generated catalog supplying local package paths.

    Returns
    -------
    tuple[PlanStep, ...]
        Stable sequence of plan steps.
    """
    steps = [PlanStep("preflight", (), "selected environment is compatible")]
    if request.target.kind is EnvironmentKind.NEW:
        assert request.target.path is not None
        steps.append(
            PlanStep(
                "create-environment",
                ("uv", "venv", str(request.target.path)),
                "target environment exists",
            )
        )
    steps.append(
        PlanStep(
            "install-packages",
            _install_command(request, packages, version, catalog),
            "selected distributions match the plan version",
        )
    )
    return tuple(steps)


def fingerprint_plan_payload(payload: Mapping[str, object]) -> str:
    """Return the SHA-256 fingerprint of canonical JSON plan content.

    Parameters
    ----------
    payload : collections.abc.Mapping[str, object]
        Plan payload without its fingerprint.

    Returns
    -------
    str
        Lowercase hexadecimal digest.
    """
    data = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def resolve_plan(
    request: InstallerRequest,
    *,
    catalog: Mapping[str, object] | None = None,
    installed_packages: Iterable[str] | None = None,
) -> InstallPlan:
    """Resolve a request into a stable, validated, versioned plan.

    Parameters
    ----------
    request : InstallerRequest
        User-selected installer request.
    catalog : collections.abc.Mapping[str, object] | None, optional
        Data-only catalog override for deterministic callers.
    installed_packages : collections.abc.Iterable[str] | None, optional
        Normalized installed names used to report retained deselections.

    Returns
    -------
    InstallPlan
        Fully resolved installation plan.

    Raises
    ------
    TypeError
        If the generated catalog has an invalid structural field.
    ValueError
        If the request violates installer constraints or selects unknown packages.
    """
    validate_request(request)
    active_catalog = load_catalog() if catalog is None else catalog
    version = active_catalog.get("coordinated_version")
    if not isinstance(version, str):
        raise TypeError("catalog coordinated_version must be a string")
    packages = _selected_packages(request, active_catalog)
    selectable = {
        str(row["name"]) for row in _catalog_rows(active_catalog) if row["selectable"]
    }
    installed = (
        _installed_distributions()
        if installed_packages is None
        else frozenset(installed_packages)
    )
    deselected = tuple(sorted((selectable & installed) - set(packages)))
    plan = InstallPlan(
        schema_version=PLAN_SCHEMA_VERSION,
        coordinated_version=version,
        request=request,
        packages=packages,
        deselected_packages=deselected,
        steps=_steps(request, packages, version, active_catalog),
    )
    payload = plan.as_dict()
    payload.pop("fingerprint")
    return replace(plan, fingerprint=fingerprint_plan_payload(payload))


def render_plan(plan: InstallPlan) -> str:
    """Render a plan as newline-terminated canonical JSON.

    Parameters
    ----------
    plan : InstallPlan
        Plan to render.

    Returns
    -------
    str
        Deterministically formatted JSON plan.
    """
    return json.dumps(plan.as_dict(), sort_keys=True, indent=2) + "\n"


def load_plan(payload: Mapping[str, object]) -> InstallPlan:
    """Construct and validate an exported JSON installation plan.

    Parameters
    ----------
    payload : collections.abc.Mapping[str, object]
        Decoded canonical plan JSON.

    Returns
    -------
    InstallPlan
        Typed validated plan.

    Raises
    ------
    ValueError
        If JSON fields are absent or violate the versioned plan contract.
    """
    try:
        request_payload = cast("Mapping[str, object]", payload["request"])
        target_payload = cast("Mapping[str, object]", request_payload["target"])
        target_path = target_payload["path"]
        checkout = request_payload["checkout"]
        request = InstallerRequest(
            target=EnvironmentTarget(
                EnvironmentKind(str(target_payload["kind"])),
                None if target_path is None else Path(str(target_path)),
            ),
            source=InstallSource(str(request_payload["source"])),
            checkout=None if checkout is None else Path(str(checkout)),
            manager=PackageManager(str(request_payload["manager"])),
            profile=InstallationProfile(str(request_payload["profile"])),
            packages=tuple(
                str(item)
                for item in cast("Sequence[object]", request_payload["packages"])
            ),
            runtime_profile=str(request_payload["runtime_profile"]),
        )
        steps = tuple(
            PlanStep(
                identifier=str(row["identifier"]),
                command=tuple(
                    str(item) for item in cast("Sequence[object]", row["command"])
                ),
                postcondition=str(row["postcondition"]),
            )
            for row in cast("Sequence[Mapping[str, object]]", payload["steps"])
        )
        schema_version = payload["schema_version"]
        if not isinstance(schema_version, int):
            raise TypeError("plan schema version must be an integer")
        plan = InstallPlan(
            schema_version=schema_version,
            coordinated_version=str(payload["coordinated_version"]),
            request=request,
            packages=tuple(
                str(item) for item in cast("Sequence[object]", payload["packages"])
            ),
            deselected_packages=tuple(
                str(item)
                for item in cast("Sequence[object]", payload["deselected_packages"])
            ),
            steps=steps,
            fingerprint=str(payload["fingerprint"]),
        )
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError("invalid installer plan JSON") from error
    validate_plan(plan)
    return plan


def validate_plan(plan: InstallPlan) -> None:
    """Validate canonical ordering, constraints, and fingerprint integrity.

    Parameters
    ----------
    plan : InstallPlan
        Plan to validate.

    Returns
    -------
    None

    Raises
    ------
    ValueError
        If any plan invariant is violated.
    """
    validate_request(plan.request)
    if plan.schema_version != PLAN_SCHEMA_VERSION:
        raise ValueError("unsupported plan schema version")
    if plan.packages != tuple(sorted(set(plan.packages))):
        raise ValueError("plan packages must be sorted and unique")
    identifiers = tuple(step.identifier for step in plan.steps)
    if identifiers != tuple(dict.fromkeys(identifiers)):
        raise ValueError("plan step identifiers must be unique")
    payload = plan.as_dict()
    fingerprint = payload.pop("fingerprint")
    if fingerprint != fingerprint_plan_payload(payload):
        raise ValueError("plan fingerprint does not match canonical payload")
