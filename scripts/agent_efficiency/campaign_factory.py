"""Build immutable, non-executing agent-efficiency campaign artifacts."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import TYPE_CHECKING, cast

from scripts.agent_efficiency.campaign_state import build_paired_schedule
from scripts.agent_efficiency.contracts import (
    ContractError,
    canonical_fingerprint,
    load_document,
    validate_document,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

FACTORY_VERSION = "1.0"


class CampaignFactoryError(ValueError):
    """Report a deterministic campaign-factory contract failure."""

    @classmethod
    def stage_cardinality(cls, stage: str, required_count: int) -> CampaignFactoryError:
        """Build the fixed-cardinality failure for one execution stage.

        Parameters
        ----------
        stage : str
            Campaign stage with invalid task cardinality.
        required_count : int
            Exact number of unique tasks required by the stage.

        Returns
        -------
        CampaignFactoryError
            Stable stage-cardinality failure.
        """

        return cls(f"{stage} requires exactly {required_count} unique task IDs")

    @classmethod
    def message(cls, detail: str) -> CampaignFactoryError:
        """Build one stable public-safe factory error.

        Parameters
        ----------
        detail : str
            Public-safe failure detail.

        Returns
        -------
        CampaignFactoryError
            Factory error carrying the supplied detail.
        """

        return cls(detail)

    @classmethod
    def missing_seed(cls) -> CampaignFactoryError:
        """Build the pilot seed requirement error.

        Parameters
        ----------
        None

        Returns
        -------
        CampaignFactoryError
            Stable missing-seed failure.
        """

        return cls("pilot requires a deterministic schedule seed")

    @classmethod
    def invalid_fixture_binding(cls) -> CampaignFactoryError:
        """Build the invalid task-fixture binding error.

        Parameters
        ----------
        None

        Returns
        -------
        CampaignFactoryError
            Stable invalid-binding failure.
        """

        return cls("task fixture binding is invalid")

    @classmethod
    def unbounded_accounting(cls) -> CampaignFactoryError:
        """Build the accounting-cap failure.

        Parameters
        ----------
        None

        Returns
        -------
        CampaignFactoryError
            Stable unbounded-accounting failure.
        """

        return cls("campaign accounting does not bound its schedule")

    @classmethod
    def runtime_profile_mismatch(cls) -> CampaignFactoryError:
        """Build the wrong-runtime-profile failure.

        Parameters
        ----------
        None

        Returns
        -------
        CampaignFactoryError
            Stable profile mismatch failure.
        """

        return cls(
            "runtime profile fingerprint does not match the benchmark Codira profile"
        )

    @classmethod
    def existing_output_directory(cls) -> CampaignFactoryError:
        """Build the immutable output-directory collision error.

        Parameters
        ----------
        None

        Returns
        -------
        CampaignFactoryError
            Stable output-directory collision failure.
        """

        return cls("campaign output directory already exists")


def build_campaign(
    specification: Mapping[str, object], benchmark_root: Path
) -> tuple[dict[str, object], dict[str, object]]:
    """Build one campaign manifest and launch plan without side effects.

    Parameters
    ----------
    specification : collections.abc.Mapping[str, object]
        Validated public campaign specification.
    benchmark_root : pathlib.Path
        Root containing the frozen task and fixture documents.

    Returns
    -------
    tuple[dict[str, object], dict[str, object]]
        Immutable campaign manifest and separate non-executing launch plan.

    Raises
    ------
    CampaignFactoryError
        If stage policy, bindings, or accounting are not deterministic.
    """

    try:
        validate_document("campaign-spec", specification)
    except ContractError as error:
        raise CampaignFactoryError(str(error)) from error
    runtime_profile = specification.get("runtime_profile_fingerprint")
    if runtime_profile is not None:
        profile_path = (
            Path(__file__).resolve().parents[2]
            / "scripts/agent_efficiency/benchmark-codira.toml"
        )
        expected_profile = hashlib.sha256(profile_path.read_bytes()).hexdigest()
        if runtime_profile != expected_profile:
            raise CampaignFactoryError.runtime_profile_mismatch()
    stage = cast("str", specification["stage"])
    task_ids = tuple(cast("list[str]", specification["task_ids"]))
    required_count = 1 if stage == "calibration" else 3
    if len(task_ids) != required_count:
        raise CampaignFactoryError.stage_cardinality(stage, required_count)
    if stage == "pilot" and "seed" not in specification:
        raise CampaignFactoryError.missing_seed()
    tasks: dict[str, Mapping[str, object]] = {}
    fixtures: dict[str, Mapping[str, object]] = {}
    for task_id in task_ids:
        task = load_document(benchmark_root / "tasks" / f"{task_id}.json", "task")
        fixture_id = task.get("fixture_id")
        if not isinstance(fixture_id, str):
            raise CampaignFactoryError.invalid_fixture_binding()
        tasks[task_id] = task
        fixtures[fixture_id] = load_document(
            benchmark_root / "fixtures" / f"{fixture_id}.json", "fixture"
        )
    manifest = {
        "schema_version": specification["schema_version"],
        "campaign_id": specification["campaign_id"],
        "fixture_fingerprints": {
            fixture_id: canonical_fingerprint(fixture)
            for fixture_id, fixture in sorted(fixtures.items())
        },
        "task_fingerprints": {
            task_id: canonical_fingerprint(task)
            for task_id, task in sorted(tasks.items())
        },
        "task_fixture_ids": {
            task_id: tasks[task_id]["fixture_id"] for task_id in sorted(tasks)
        },
        "budgets": specification["budgets"],
        "provider": specification["provider"],
        "accounting": specification["accounting"],
        "resource_controls": specification["resource_controls"],
        "runtime_image": specification.get("runtime_image"),
        "runtime_profile_fingerprint": specification.get("runtime_profile_fingerprint"),
        "treatment_protocol": specification.get("treatment_protocol"),
        "visibility": specification["visibility"],
    }
    manifest = {key: value for key, value in manifest.items() if value is not None}
    try:
        validate_document("campaign", manifest)
    except ContractError as error:
        raise CampaignFactoryError(str(error)) from error
    schedule = _schedule(stage, task_ids, specification)
    _validate_accounting(manifest, len(schedule))
    plan = {
        "factory_version": FACTORY_VERSION,
        "stage": stage,
        "campaign_id": manifest["campaign_id"],
        "manifest_fingerprint": canonical_fingerprint(manifest),
        "specification_fingerprint": canonical_fingerprint(specification),
        "scheduled_attempt_count": len(schedule),
        "attempts": schedule,
        "execution": {
            "credential_free_generation_only": True,
            "requires_offline_validation": True,
            "requires_authenticated_preflight": True,
            "requires_explicit_paid_authorization": True,
            "requires_fresh_state_root": True,
            "requires_tmux_durable_log_and_exit_status": True,
        },
    }
    return manifest, plan


def _schedule(
    stage: str, task_ids: tuple[str, ...], specification: Mapping[str, object]
) -> list[dict[str, object]]:
    """Return the stage-constrained deterministic attempt schedule."""

    if stage == "calibration":
        task_id = task_ids[0]
        return [
            {
                "task_id": task_id,
                "repetition": 1,
                "assistance_mode": "codira-mcp",
                "attempt_id": f"{task_id}-calibration-codira-mcp",
                "pair_id": f"{task_id}-calibration",
            }
        ]
    seed = cast("int", specification["seed"])
    return [item.__dict__ for item in build_paired_schedule(task_ids, 1, seed)]


def _validate_accounting(manifest: Mapping[str, object], attempts: int) -> None:
    """Reject spending ceilings that cannot bound the frozen schedule."""

    accounting = cast("Mapping[str, object]", manifest["accounting"])
    budgets = cast("Mapping[str, object]", manifest["budgets"])
    provider = cast("Mapping[str, object]", manifest["provider"])
    daily = float(cast("int | float", accounting["max_daily_spend_usd"]))
    per_attempt = float(
        cast("int | float", accounting["max_estimated_attempt_spend_usd"])
    )
    total = float(cast("int | float", accounting["max_estimated_pilot_spend_usd"]))
    token_scope = str(accounting.get("max_total_tokens_scope", "per-continuation"))
    reservation_multiplier = (
        1
        if token_scope == "whole-session"
        else int(cast("int", accounting.get("max_transport_attempts_per_response", 1)))
        * int(cast("int", accounting["max_response_requests_per_attempt"]))
    )
    token_bound = (
        int(cast("int", budgets["max_total_tokens"]))
        * reservation_multiplier
        * max(
            float(cast("int | float", provider["max_prompt_usd_per_million"])),
            float(cast("int | float", provider["max_completion_usd_per_million"])),
        )
        / 1_000_000
    )
    if total > daily or total < per_attempt * attempts or per_attempt < token_bound:
        raise CampaignFactoryError.unbounded_accounting()


def write_campaign_artifacts(
    output_directory: Path, manifest: Mapping[str, object], plan: Mapping[str, object]
) -> tuple[Path, Path]:
    """Atomically create one fresh artifact directory without overwrite.

    Parameters
    ----------
    output_directory : pathlib.Path
        Fresh destination for the immutable generated artifacts.
    manifest : collections.abc.Mapping[str, object]
        Validated campaign manifest to persist.
    plan : collections.abc.Mapping[str, object]
        Non-executing launch plan to persist.

    Returns
    -------
    tuple[pathlib.Path, pathlib.Path]
        Paths to the campaign manifest and launch plan.

    Raises
    ------
    CampaignFactoryError
        If the destination already exists.
    """

    if output_directory.exists():
        raise CampaignFactoryError.existing_output_directory()
    output_directory.mkdir(parents=True)
    manifest_path = output_directory / "campaign.json"
    plan_path = output_directory / "launch-plan.json"
    _atomic_json(manifest_path, manifest)
    _atomic_json(plan_path, plan)
    return manifest_path, plan_path


def _atomic_json(path: Path, document: Mapping[str, object]) -> None:
    """Write one public JSON artifact atomically."""

    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with temporary.open("x", encoding="utf-8") as handle:
            json.dump(document, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(path)
    finally:
        if temporary.exists():
            temporary.unlink()
