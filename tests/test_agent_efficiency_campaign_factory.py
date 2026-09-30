"""Test deterministic, credential-free campaign construction."""

from __future__ import annotations

import hashlib
import json
import shutil
from collections import Counter
from pathlib import Path

import pytest

from scripts.agent_efficiency.campaign_factory import (
    CampaignFactoryError,
    build_campaign,
    validate_campaign_artifacts,
    write_campaign_artifacts,
)
from scripts.generate_agent_efficiency_campaign import main


def _spec(stage: str, task_ids: list[str]) -> dict[str, object]:
    """Build one valid factory specification for frozen public fixtures."""

    result: dict[str, object] = {
        "schema_version": "1.0",
        "campaign_id": f"factory-{stage}-001",
        "stage": stage,
        "task_ids": task_ids,
        "budgets": {
            "max_total_tokens": 200000,
            "max_output_tokens": 32000,
            "timeout_seconds": 900,
        },
        "provider": {
            "name": "openrouter",
            "model": "deepseek/deepseek-v4.1-flash",
            "reasoning_effort": "none",
            "wire_api": "responses",
            "max_prompt_usd_per_million": 0.15,
            "max_completion_usd_per_million": 0.6,
        },
        "accounting": {
            "max_daily_spend_usd": 6,
            "max_estimated_attempt_spend_usd": 0.15,
            "max_estimated_pilot_spend_usd": 0.15 if stage == "calibration" else 0.9,
            "max_response_requests_per_attempt": 1,
        },
        "resource_controls": {
            "network": "none",
            "read_only_rootfs": True,
            "pids_limit": 512,
            "tmpfs_size_mib": 128,
        },
        "visibility": "public",
    }
    if stage == "pilot":
        result["seed"] = 20260919
    return result


def test_factory_builds_one_assisted_calibration_attempt() -> None:
    """Generate frozen calibration bindings and exactly one request.

    Parameters
    ----------
    None

    Returns
    -------
    None
        Assertions cover calibration identity, bindings, and cardinality.
    """

    manifest, plan = build_campaign(
        _spec("calibration", ["symbols-001"]), Path("benchmarks/agent-efficiency")
    )

    task_fingerprints = manifest["task_fingerprints"]
    assert isinstance(task_fingerprints, dict)
    assert set(task_fingerprints) == {"symbols-001"}
    assert plan["scheduled_attempt_count"] == 1
    assert plan["attempts"] == [
        {
            "task_id": "symbols-001",
            "repetition": 1,
            "assistance_mode": "codira-mcp",
            "attempt_id": "symbols-001-calibration-codira-mcp",
            "pair_id": "symbols-001-calibration",
        }
    ]


def test_factory_builds_a_deterministic_six_request_pilot() -> None:
    """Require exactly three tasks and preserve paired schedule determinism.

    Parameters
    ----------
    None

    Returns
    -------
    None
        Assertions cover deterministic paired pilot construction.
    """

    specification = _spec("pilot", ["symbols-001", "patch-001", "documentation-001"])
    first = build_campaign(specification, Path("benchmarks/agent-efficiency"))
    second = build_campaign(specification, Path("benchmarks/agent-efficiency"))

    assert first == second
    assert first[1]["scheduled_attempt_count"] == 6


def _full_spec() -> dict[str, object]:
    """Build the six-category, five-repetition campaign specification.

    Parameters
    ----------
    None

    Returns
    -------
    dict[str, object]
        Specification with a measured full-campaign pool.
    """

    specification = _spec(
        "full-campaign",
        [
            "context-page-001",
            "impact-001",
            "localize-001",
            "patch-002",
            "architecture-001",
            "documentation-001",
        ],
    )
    specification.update(
        seed=20260929,
        repetitions=5,
        runtime_image="localhost/factory-test@sha256:" + "1" * 64,
        runtime_profile_fingerprint=hashlib.sha256(
            Path("scripts/agent_efficiency/benchmark-codira.toml").read_bytes()
        ).hexdigest(),
    )
    accounting = specification["accounting"]
    assert isinstance(accounting, dict)
    accounting.update(
        max_daily_spend_usd=10,
        max_estimated_pilot_spend_usd=9,
        budget_reservation_mode="shared-pool",
    )
    return specification


def test_full_campaign_freezes_sixty_paired_attempts_and_oracles() -> None:
    """Freeze every pair, oracle identity, and unpaid launch prerequisite.

    Parameters
    ----------
    None

    Returns
    -------
    None
        Assertions cover deterministic schedules and oracle evidence.
    """

    root = Path("benchmarks/agent-efficiency")
    specification = _full_spec()
    manifest, plan = build_campaign(specification, root)
    assert (manifest, plan) == build_campaign(specification, root)
    assert plan["scheduled_attempt_count"] == 60
    attempts = plan["attempts"]
    assert isinstance(attempts, list)
    counts = Counter(
        (attempt["task_id"], attempt["repetition"], attempt["assistance_mode"])
        for attempt in attempts
    )
    assert len(counts) == 60 and set(counts.values()) == {1}
    assert {attempt["repetition"] for attempt in attempts} == {1, 2, 3, 4, 5}
    assert len({attempt["attempt_id"] for attempt in attempts}) == 60
    assert len({attempt["pair_id"] for attempt in attempts}) == 30
    oracle_fingerprints = plan["oracle_fingerprints"]
    assert isinstance(oracle_fingerprints, dict)
    assert len(oracle_fingerprints) == 6
    assert all(len(value) == 64 for value in oracle_fingerprints.values())
    gates = plan["execution"]
    assert isinstance(gates, dict)
    assert gates["credential_free_generation_only"] is True
    assert gates["requires_full_campaign_executor_qualification"] is True
    assert gates["requires_registry_image_admission"] is True


@pytest.mark.parametrize("repetitions", [1, 4, 6])
def test_full_campaign_rejects_an_unapproved_repetition_count(repetitions: int) -> None:
    """Prevent expansion or reduction of the approved sixty-run matrix.

    Parameters
    ----------
    repetitions : int
        Unapproved number of pairs per task.

    Returns
    -------
    None
        The factory rejects every count other than five.
    """

    specification = _full_spec()
    specification["repetitions"] = repetitions
    with pytest.raises(CampaignFactoryError, match="exactly 5 repetitions"):
        build_campaign(specification, Path("benchmarks/agent-efficiency"))


def test_full_campaign_rejects_a_pool_above_its_daily_limit() -> None:
    """Keep the observed pool within the declared daily account allowance.

    Parameters
    ----------
    None

    Returns
    -------
    None
        A pool above its daily ceiling cannot produce a campaign.
    """

    specification = _full_spec()
    accounting = specification["accounting"]
    assert isinstance(accounting, dict)
    accounting["max_estimated_pilot_spend_usd"] = 10.1
    with pytest.raises(CampaignFactoryError, match="does not bound its schedule"):
        build_campaign(specification, Path("benchmarks/agent-efficiency"))


def test_full_campaign_requires_observed_shared_pool() -> None:
    """Reject reserve-based accounting for the measured full executor.

    Parameters
    ----------
    None

    Returns
    -------
    None
        A full campaign cannot silently use incompatible budget semantics.
    """

    specification = _full_spec()
    accounting = specification["accounting"]
    assert isinstance(accounting, dict)
    accounting["budget_reservation_mode"] = "sum-attempt-ceilings"
    with pytest.raises(CampaignFactoryError, match="observed shared-pool"):
        build_campaign(specification, Path("benchmarks/agent-efficiency"))


def test_shared_campaign_pool_requires_a_qualified_budget_executor() -> None:
    """Admit measured spend without reserving any attempt maximum.

    Parameters
    ----------
    None

    Returns
    -------
    None
        A smaller pool retains an explicit full-executor launch gate.
    """

    specification = _full_spec()
    accounting = specification["accounting"]
    assert isinstance(accounting, dict)
    accounting.update(
        budget_reservation_mode="shared-pool", max_estimated_pilot_spend_usd=1
    )
    manifest, plan = build_campaign(specification, Path("benchmarks/agent-efficiency"))
    assert manifest["accounting"] == accounting
    assert plan["scheduled_attempt_count"] == 60
    gates = plan["execution"]
    assert isinstance(gates, dict)
    assert gates["requires_shared_campaign_budget_enforcement"] is True
    accounting["max_estimated_pilot_spend_usd"] = 0.14
    accounting["max_estimated_attempt_spend_usd"] = 0.001
    build_campaign(specification, Path("benchmarks/agent-efficiency"))
    accounting["max_daily_spend_usd"] = 0.13
    with pytest.raises(CampaignFactoryError, match="does not bound its schedule"):
        build_campaign(specification, Path("benchmarks/agent-efficiency"))


def test_pilot_factory_rejects_shared_campaign_pool_mode() -> None:
    """Prevent admitting pooled accounting into the existing pilot executor.

    Parameters
    ----------
    None

    Returns
    -------
    None
        Pilot generation remains compatible with its aggregate reservations.
    """

    specification = _spec("pilot", ["symbols-001", "patch-001", "documentation-001"])
    accounting = specification["accounting"]
    assert isinstance(accounting, dict)
    accounting["budget_reservation_mode"] = "shared-pool"
    with pytest.raises(CampaignFactoryError, match="require the full-campaign stage"):
        build_campaign(specification, Path("benchmarks/agent-efficiency"))


@pytest.mark.parametrize("control", ["seed", "cardinality", "fixtures"])
def test_full_campaign_rejects_incomplete_matrix_controls(control: str) -> None:
    """Reject absent seeds and matrices that omit tasks or public fixtures.

    Parameters
    ----------
    control : str
        Required matrix control deliberately invalidated.

    Returns
    -------
    None
        Invalid full-campaign specifications never reach persistence.
    """

    specification = _full_spec()
    if control == "seed":
        specification.pop("seed")
    elif control == "cardinality":
        specification["task_ids"] = [
            "context-page-001",
            "patch-002",
            "documentation-001",
        ]
    else:
        specification["task_ids"] = [
            "context-page-001",
            "symbols-001",
            "impact-001",
            "patch-001",
            "patch-002",
            "localize-001",
        ]
    with pytest.raises(CampaignFactoryError):
        build_campaign(specification, Path("benchmarks/agent-efficiency"))


def test_factory_check_rejects_oracle_drift_without_rewriting(tmp_path: Path) -> None:
    """Detect changed grader inputs and mismatched task/oracle identities.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Disposable copied benchmark inputs and generated output.

    Returns
    -------
    None
        Oracle changes invalidate the immutable plan without altering it.
    """

    root = tmp_path / "inputs"
    for directory in ("tasks", "fixtures", "oracles"):
        shutil.copytree(
            Path("benchmarks/agent-efficiency") / directory, root / directory
        )
    specification = _full_spec()
    manifest, plan = build_campaign(specification, root)
    output = tmp_path / "output"
    _, plan_path = write_campaign_artifacts(output, manifest, plan)
    before = plan_path.read_bytes()
    validate_campaign_artifacts(output, manifest, plan)
    assert plan_path.read_bytes() == before
    oracle_path = root / "oracles" / "localize-001.json"
    oracle = json.loads(oracle_path.read_text())
    oracle["definition"]["text_contains"].append("new grader requirement")
    oracle_path.write_text(json.dumps(oracle))
    new_manifest, new_plan = build_campaign(specification, root)
    assert new_manifest == manifest
    with pytest.raises(CampaignFactoryError, match="differs from frozen inputs"):
        validate_campaign_artifacts(output, new_manifest, new_plan)
    assert plan_path.read_bytes() == before
    oracle["task_id"] = "symbols-001"
    oracle_path.write_text(json.dumps(oracle))
    with pytest.raises(CampaignFactoryError, match="oracle binding is invalid"):
        build_campaign(specification, root)


def test_factory_cli_check_preserves_artifacts_and_rejects_tampering(
    tmp_path: Path,
) -> None:
    """Exercise credential-free generation and read-only CLI validation.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Disposable specification and generated campaign directory.

    Returns
    -------
    None
        CLI validation passes unchanged output and rejects malformed plans.
    """

    spec_path = tmp_path / "spec.json"
    spec_path.write_text(json.dumps(_full_spec()))
    output = tmp_path / "output"
    arguments = ["--spec", str(spec_path), "--output-dir", str(output)]
    assert main(arguments) == 0
    plan_path = output / "launch-plan.json"
    before = plan_path.read_bytes()
    assert main([*arguments, "--check"]) == 0
    assert plan_path.read_bytes() == before
    plan_path.write_text("{")
    assert main([*arguments, "--check"]) == 2
    tampered = json.loads(before)
    first_repetition = next(
        attempt for attempt in tampered["attempts"] if attempt["repetition"] == 1
    )
    first_repetition["repetition"] = True
    plan_path.write_text(json.dumps(tampered))
    assert main([*arguments, "--check"]) == 2


def test_factory_accounts_whole_session_tokens_once_per_attempt() -> None:
    """Bound a multi-continuation pilot by its whole-session token ceiling.

    Parameters
    ----------
    None

    Returns
    -------
    None
        Assertions distinguish session accounting from legacy multiplication.
    """

    specification = _spec("pilot", ["symbols-001", "patch-001", "documentation-001"])
    budgets = specification["budgets"]
    accounting = specification["accounting"]
    assert isinstance(budgets, dict)
    assert isinstance(accounting, dict)
    budgets["max_total_tokens"] = 240000
    accounting.update(
        {
            "max_total_tokens_scope": "whole-session",
            "max_response_requests_per_attempt": 10,
            "max_transport_attempts_per_response": 2,
            "max_estimated_attempt_spend_usd": 0.18,
            "max_estimated_pilot_spend_usd": 1.08,
        }
    )

    manifest, plan = build_campaign(specification, Path("benchmarks/agent-efficiency"))

    assert manifest["accounting"] == accounting
    assert plan["scheduled_attempt_count"] == 6


def test_factory_rejects_an_invalid_stage_cardinality() -> None:
    """Prevent a calibration from becoming an unreviewed campaign.

    Parameters
    ----------
    None

    Returns
    -------
    None
        Assertions cover fail-closed calibration cardinality.
    """

    with pytest.raises(CampaignFactoryError, match="calibration requires exactly 1"):
        build_campaign(
            _spec("calibration", ["symbols-001", "patch-001"]),
            Path("benchmarks/agent-efficiency"),
        )


def test_factory_rejects_a_fingerprint_for_the_wrong_runtime_profile() -> None:
    """Reject the image fingerprint when the campaign field means Codira profile.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The factory must fail before producing paid-stage artifacts.
    """

    specification = _spec("pilot", ["symbols-001", "patch-001", "documentation-001"])
    image_profile = "0" * 64
    codira_profile = hashlib.sha256(
        Path("scripts/agent_efficiency/benchmark-codira.toml").read_bytes()
    ).hexdigest()
    assert image_profile != codira_profile
    specification["runtime_profile_fingerprint"] = image_profile

    with pytest.raises(
        CampaignFactoryError,
        match="does not match the benchmark Codira profile",
    ):
        build_campaign(specification, Path("benchmarks/agent-efficiency"))

    specification["runtime_profile_fingerprint"] = codira_profile
    manifest, _ = build_campaign(specification, Path("benchmarks/agent-efficiency"))
    assert manifest["runtime_profile_fingerprint"] == codira_profile


def test_factory_refuses_to_overwrite_artifacts(tmp_path: Path) -> None:
    """Keep generated campaign evidence immutable after first creation.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary destination for generated campaign artifacts.

    Returns
    -------
    None
        Assertions cover first-write success and overwrite rejection.
    """

    manifest, plan = build_campaign(
        _spec("calibration", ["symbols-001"]), Path("benchmarks/agent-efficiency")
    )
    output = tmp_path / "factory-calibration-001"

    manifest_path, plan_path = write_campaign_artifacts(output, manifest, plan)

    assert manifest_path.is_file()
    assert plan_path.is_file()
    with pytest.raises(CampaignFactoryError, match="already exists"):
        write_campaign_artifacts(output, manifest, plan)
