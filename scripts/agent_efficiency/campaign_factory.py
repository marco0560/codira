"""Build immutable, non-executing agent-efficiency campaign artifacts."""
# ruff: noqa: C901, PLR0912

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
from scripts.agent_efficiency.panels import panel_document_path

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
    def missing_seed(cls, stage: str = "pilot") -> CampaignFactoryError:
        """Build the paired-stage seed requirement error.

        Parameters
        ----------
        stage : str, optional
            Paired execution stage requiring a deterministic seed.

        Returns
        -------
        CampaignFactoryError
            Stable missing-seed failure.
        """

        return cls(f"{stage} requires a deterministic schedule seed")

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
    accounting = cast("Mapping[str, object]", specification["accounting"])
    shared_pool = _uses_shared_campaign_pool(stage, accounting)
    provider = cast("Mapping[str, object]", specification["provider"])
    if (
        provider.get("name") == "codex-subscription"
        and stage != "representative-campaign"
    ):
        detail = "Codex subscription is admitted only for the representative stage"
        raise CampaignFactoryError.message(detail)
    task_ids = tuple(cast("list[str]", specification["task_ids"]))
    required_count = {
        "calibration": 1,
        "pilot": 3,
        "full-campaign": 6,
        "completion": 3,
        "representative-campaign": 24,
    }[stage]
    if len(task_ids) != required_count:
        raise CampaignFactoryError.stage_cardinality(stage, required_count)
    if stage != "calibration" and "seed" not in specification:
        raise CampaignFactoryError.missing_seed(stage)
    required_repetitions = (
        int(str(specification.get("repetitions", 1)))
        if stage == "representative-campaign"
        else 5
        if stage in {"full-campaign", "completion", "representative-campaign"}
        else 1
    )
    if not 1 <= required_repetitions <= 5:
        detail = "representative repetitions must be between one and five"
        raise CampaignFactoryError.message(detail)
    if specification.get("repetitions", 1) != required_repetitions:
        detail = f"{stage} requires exactly {required_repetitions} repetitions"
        raise CampaignFactoryError.message(detail)
    tasks: dict[str, Mapping[str, object]] = {}
    fixtures: dict[str, Mapping[str, object]] = {}
    oracle_fingerprints: dict[str, str] = {}
    for task_id in task_ids:
        task = load_document(
            panel_document_path(benchmark_root, "tasks", str(task_id)), "task"
        )
        fixture_id = task.get("fixture_id")
        if not isinstance(fixture_id, str):
            raise CampaignFactoryError.invalid_fixture_binding()
        tasks[task_id] = task
        fixtures[fixture_id] = load_document(
            panel_document_path(benchmark_root, "fixtures", str(fixture_id)), "fixture"
        )
        if stage in {"full-campaign", "completion", "representative-campaign"}:
            oracle_id = task["oracle_id"]
            oracle = load_document(
                panel_document_path(benchmark_root, "oracles", str(oracle_id)), "oracle"
            )
            if (
                task["task_id"] != task_id
                or oracle["task_id"] != task_id
                or oracle["oracle_id"] != oracle_id
            ):
                detail = "task oracle binding is invalid"
                raise CampaignFactoryError.message(detail)
            oracle_fingerprints[task_id] = canonical_fingerprint(oracle)
    if stage in {"full-campaign", "completion", "representative-campaign"} and len(
        fixtures
    ) != (6 if stage == "representative-campaign" else 3):
        detail = f"{stage} requires exactly {6 if stage == 'representative-campaign' else 3} immutable fixtures"
        raise CampaignFactoryError.message(detail)
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
        "panel_id": specification.get("panel_id"),
        "runtime_source_fingerprint": specification.get("runtime_source_fingerprint"),
        "visibility": specification["visibility"],
    }
    if stage == "representative-campaign":
        from scripts.agent_efficiency.panels import validate_panel_tasks

        validate_panel_tasks(tasks, specification)
    manifest = {key: value for key, value in manifest.items() if value is not None}
    if stage in {"completion", "representative-campaign"}:
        manifest["stage"] = stage
    try:
        validate_document("campaign", manifest)
    except ContractError as error:
        raise CampaignFactoryError(str(error)) from error
    completion_snapshot: dict[str, object] | None = None
    if stage == "completion":
        from scripts.agent_efficiency.completion_campaign import source_snapshot

        source = cast("Mapping[str, object]", specification["completion_source"])
        selected, completion_snapshot = source_snapshot(
            source, manifest, benchmark_root.resolve().parents[1]
        )
        schedule = [item.__dict__ for item in selected]
        if {item.task_id for item in selected} != set(task_ids):
            detail = "completion tasks differ from selection"
            raise CampaignFactoryError.message(detail)
    else:
        schedule = _schedule(stage, task_ids, specification)
    _validate_accounting(manifest, len(schedule))
    plan: dict[str, object] = {
        "factory_version": "1.1"
        if stage == "representative-campaign"
        else FACTORY_VERSION,
        "stage": stage,
        "campaign_id": manifest["campaign_id"],
        "manifest_fingerprint": canonical_fingerprint(manifest),
        "specification_fingerprint": canonical_fingerprint(specification),
        "scheduled_attempt_count": len(schedule),
        "attempts": schedule,
        "execution": {
            "credential_free_generation_only": True,
            "requires_offline_validation": True,
            "requires_machine_validated_readiness": True,
            "requires_authenticated_preflight": True,
            "requires_explicit_paid_authorization": True,
            "requires_fresh_state_root": True,
            "requires_tmux_durable_log_and_exit_status": True,
        },
    }
    if stage in {"full-campaign", "completion", "representative-campaign"}:
        from scripts.agent_efficiency.full_campaign import (
            CHECKPOINT_SECONDS,
            harness_fingerprint,
        )

        plan.update(
            seed=specification["seed"],
            repetitions=required_repetitions,
            oracle_fingerprints=oracle_fingerprints,
            harness_fingerprint=harness_fingerprint(),
            checkpoint_seconds=CHECKPOINT_SECONDS,
        )
        if stage == "completion":
            plan["completion_source"] = specification["completion_source"]
            plan["source_snapshot"] = completion_snapshot
        cast("dict[str, object]", plan["execution"]).update(
            requires_full_campaign_executor_qualification=True,
            requires_registry_image_admission=True,
        )
        if shared_pool:
            cast("dict[str, object]", plan["execution"])[
                "requires_shared_campaign_budget_enforcement"
            ] = True
        if provider.get("name") == "codex-subscription":
            cast("dict[str, object]", plan["execution"])[
                "requires_subscription_quota_enforcement"
            ] = True
    return manifest, plan


def _uses_shared_campaign_pool(stage: str, accounting: Mapping[str, object]) -> bool:
    """Admit pooled accounting only for a full-campaign specification.

    Parameters
    ----------
    stage : str
        Validated factory stage.
    accounting : collections.abc.Mapping[str, object]
        Validated accounting controls.

    Returns
    -------
    bool
        Whether the declared reservation mode uses a shared pool.

    Raises
    ------
    CampaignFactoryError
        If an existing pilot or calibration requests pooled accounting.
    """

    mode = accounting.get("budget_reservation_mode")
    shared_pool = mode == "shared-pool"
    subscription = mode == "subscription-quota"
    if subscription and stage != "representative-campaign":
        detail = "subscription quota requires the representative stage"
        raise CampaignFactoryError.message(detail)
    if shared_pool and stage not in {
        "full-campaign",
        "completion",
        "representative-campaign",
    }:
        detail = "shared campaign budgets require the full-campaign stage"
        raise CampaignFactoryError.message(detail)
    if stage in {"full-campaign", "completion", "representative-campaign"} and not (
        shared_pool or subscription
    ):
        detail = "full campaigns require observed shared-pool accounting"
        raise CampaignFactoryError.message(detail)
    return shared_pool


def _schedule(
    stage: str, task_ids: tuple[str, ...], specification: Mapping[str, object]
) -> list[dict[str, object]]:
    """Return the stage-constrained deterministic attempt schedule.

    Parameters
    ----------
    stage : str
        Calibration, pilot, or full-campaign stage.
    task_ids : tuple[str, ...]
        Validated unique task identities.
    specification : collections.abc.Mapping[str, object]
        Validated specification containing the paired-stage seed.

    Returns
    -------
    list[dict[str, object]]
        Frozen schedule with one, six, or sixty attempts.
    """

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
    repetitions = (
        int(str(specification.get("repetitions", 1)))
        if stage == "representative-campaign"
        else 5
        if stage == "full-campaign"
        else 1
    )
    return [
        item.__dict__ for item in build_paired_schedule(task_ids, repetitions, seed)
    ]


def _validate_accounting(manifest: Mapping[str, object], attempts: int) -> None:
    """Validate attempt reserves and the declared aggregate reservation mode.

    Parameters
    ----------
    manifest : collections.abc.Mapping[str, object]
        Validated campaign with explicit price and spending controls.
    attempts : int
        Number of scheduled executions.

    Returns
    -------
    None
        Sum mode funds every ceiling; shared mode records its observed pool.

    Raises
    ------
    CampaignFactoryError
        If the applicable aggregate or daily controls are invalid.

    Notes
    -----
    A shared pool requires a qualified executor that persists aggregate usage
    and stops new paid work once observed charges reach its threshold. Factory
    validation alone does not enforce that pool during execution.
    """

    accounting = cast("Mapping[str, object]", manifest["accounting"])
    budgets = cast("Mapping[str, object]", manifest["budgets"])
    provider = cast("Mapping[str, object]", manifest["provider"])
    subscription = provider.get("name") == "codex-subscription"
    if subscription:
        if (
            provider.get("wire_api") != "codex-cli"
            or accounting.get("budget_reservation_mode") != "subscription-quota"
            or any(
                provider.get(key) != 0
                for key in (
                    "max_prompt_usd_per_million",
                    "max_completion_usd_per_million",
                )
            )
            or any(
                accounting.get(key) != 0
                for key in (
                    "max_daily_spend_usd",
                    "max_estimated_attempt_spend_usd",
                    "max_estimated_pilot_spend_usd",
                )
            )
        ):
            detail = "subscription accounting route is invalid"
            raise CampaignFactoryError.message(detail)
        return
    if provider.get("name") != "openrouter" or provider.get("wire_api") != "responses":
        detail = "OpenRouter provider route is invalid"
        raise CampaignFactoryError.message(detail)
    if (
        accounting.get("budget_reservation_mode", "sum-attempt-ceilings")
        == "subscription-quota"
    ):
        detail = "OpenRouter cannot use subscription quota"
        raise CampaignFactoryError.message(detail)
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
    output_reserve = (
        int(cast("int", budgets["max_output_tokens"]))
        * float(cast("int | float", provider["max_completion_usd_per_million"]))
        / 1_000_000
    )
    shared_pool = accounting.get("budget_reservation_mode") == "shared-pool"
    required_total = per_attempt * attempts
    if (
        min(daily, per_attempt, total) <= 0
        or min(
            float(cast("int | float", provider["max_prompt_usd_per_million"])),
            float(cast("int | float", provider["max_completion_usd_per_million"])),
        )
        <= 0
        or total > daily
        or (not shared_pool and total + 1e-12 < required_total)
        or (not shared_pool and per_attempt < token_bound + output_reserve)
    ):
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


def validate_campaign_artifacts(
    output_directory: Path, manifest: Mapping[str, object], plan: Mapping[str, object]
) -> None:
    """Check existing factory artifacts against the current frozen inputs.

    Parameters
    ----------
    output_directory : pathlib.Path
        Existing immutable campaign directory.
    manifest : collections.abc.Mapping[str, object]
        Expected manifest rebuilt from the validated specification.
    plan : collections.abc.Mapping[str, object]
        Expected launch plan including schedule and oracle fingerprints.

    Returns
    -------
    None
        Successful validation leaves both artifacts unchanged.

    Raises
    ------
    CampaignFactoryError
        If artifacts are malformed or differ from the frozen inputs.
    OSError
        If an artifact cannot be read.
    """

    for filename, expected in (("campaign.json", manifest), ("launch-plan.json", plan)):
        try:
            actual = json.loads(
                (output_directory / filename).read_text(encoding="utf-8")
            )
        except json.JSONDecodeError as error:
            detail = "generated campaign artifact is malformed"
            raise CampaignFactoryError.message(detail) from error
        if not isinstance(actual, dict) or canonical_fingerprint(
            actual
        ) != canonical_fingerprint(expected):
            detail = "generated campaign artifact differs from frozen inputs"
            raise CampaignFactoryError.message(detail)


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
