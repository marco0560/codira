"""Exercise full campaigns without containers, credentials, or paid requests.

Parameters
----------
None

Returns
-------
None
    Deterministic tests qualify scheduling, budgeting, and safe resumption.
"""

from __future__ import annotations

import fcntl
import json
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

from scripts.agent_efficiency.campaign_factory import (
    build_campaign,
    write_campaign_artifacts,
)
from scripts.agent_efficiency.campaign_state import (
    CampaignStore,
    ScheduledAttempt,
    build_paired_schedule,
)
from scripts.agent_efficiency.full_campaign import (
    CHECKPOINT_SECONDS,
    evidence_cost,
    run_full_campaign,
    validate_full_plan,
)
from scripts.launch_agent_efficiency_pilot import (
    PilotLaunchError,
    load_launch,
    tmux_command,
)
from scripts.run_agent_efficiency_phase6_pilot import execution_controls


def _store(root: Path) -> CampaignStore:
    """Create a frozen sixty-attempt synthetic campaign.

    Parameters
    ----------
    root : pathlib.Path
        Isolated test state root.

    Returns
    -------
    CampaignStore
        Initialized schedule and durable state.
    """

    store = CampaignStore(
        root,
        "full-test-001",
        {"frozen": True},
        build_paired_schedule([f"task-{index:03d}" for index in range(6)], 5, 7),
    )
    store.initialize()
    return store


def _execute(
    attempt: ScheduledAttempt,
) -> tuple[Mapping[str, object], Mapping[str, object]]:
    """Return a scored task failure with complete billing evidence.

    Parameters
    ----------
    attempt : ScheduledAttempt
        Frozen schedule member.

    Returns
    -------
    tuple[Mapping[str, object], Mapping[str, object]]
        Schema-valid result and a conservative ten-cent charge.
    """

    return {
        "schema_version": "1.0",
        "campaign_id": "full-test-001",
        "task_id": attempt.task_id,
        "attempt_id": attempt.attempt_id,
        "assistance_mode": attempt.assistance_mode,
        "outcome": "oracle_failure",
        "failure_class": "deterministic_oracle",
        "usage_complete": True,
        "usage": {
            "input_tokens": 100000,
            "output_tokens": 0,
            "cached_input_tokens": 0,
            "reasoning_output_tokens": 0,
        },
        "provenance": {"runner": "synthetic", "runner_version": "1.0"},
        "operational_calibration": {"status": "passed", "failure_class": None},
        "task_oracle": {
            "status": "failed",
            "failure_class": "deterministic_oracle",
            "fingerprint": "a" * 64,
        },
    }, {
        "provider_responses": [
            {
                "source": "upstream",
                "status": 200,
                "response_sha256": "b" * 64,
                "provider_usage": {
                    "input_tokens": 100000,
                    "output_tokens": 0,
                    "total_tokens": 100000,
                },
            }
        ]
    }


def _run(
    store: CampaignStore,
    execute: Callable[
        [ScheduledAttempt], tuple[Mapping[str, object], Mapping[str, object]]
    ] = _execute,
    *,
    pool: str = "10",
    clock: Callable[[], float] = lambda: 0.0,
) -> dict[str, object]:
    """Run a synthetic campaign with a one-dollar attempt reserve.

    Parameters
    ----------
    store : CampaignStore
        Frozen test state.
    execute : Callable, optional
        Injectable result producer.
    pool : str, optional
        Decimal campaign ceiling.
    clock : Callable, optional
        Injectable checkpoint clock.

    Returns
    -------
    dict[str, object]
        Durable execution report.
    """

    return run_full_campaign(
        store,
        execute,
        pool=Decimal(pool),
        reserve=Decimal(1),
        prompt_price=Decimal(1),
        completion_price=Decimal(1),
        clock=clock,
    )


def test_full_matrix_continues_after_scored_failures_and_is_idempotent(
    tmp_path: Path,
) -> None:
    """Complete sixty attempts, retaining every task failure without retry.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary state root.

    Returns
    -------
    None
        Assertions qualify schedule completion and a no-op second invocation.
    """

    store = _store(tmp_path)
    assert _run(store)["status"] == "complete"
    assert len(store.validated_records()) == 60
    assert _run(store)["new_attempt_ids"] == []


def test_checkpoint_preserves_complete_pairs_and_resumes(tmp_path: Path) -> None:
    """Checkpoint after one complete pair and resume only pending work.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary state root.

    Returns
    -------
    None
        Assertions qualify pair boundaries and journal-based resumption.
    """

    store = _store(tmp_path)
    ticks = iter([0.0, 0.0, float(CHECKPOINT_SECONDS), float(CHECKPOINT_SECONDS)])
    report = _run(store, clock=lambda: next(ticks))
    assert report["status"] == "checkpoint"
    assert len(store.validated_records()) == 2
    assert _run(store)["charged_usd"] == "6.0"


def test_campaign_pool_stops_before_unaffordable_pair_and_survives_resume(
    tmp_path: Path,
) -> None:
    """Preserve aggregate spending across restarts with the same ceiling.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary state root.

    Returns
    -------
    None
        Budget exhaustion cannot be erased by restarting or changing the pool.
    """

    store = _store(tmp_path)
    first = _run(store, pool="2")
    assert first["status"] == "budget_exhausted"
    assert first["charged_usd"] == "0.2"
    assert _run(store, pool="2")["new_attempt_ids"] == []
    with pytest.raises(ValueError, match="identity differs"):
        _run(store, pool="10")


def test_interrupted_attempt_keeps_reservation_and_blocks_retry(tmp_path: Path) -> None:
    """Keep evidence of an interrupted execution and reject automatic retry.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary state root.

    Returns
    -------
    None
        An interruption never releases the reserved allowance.
    """

    store = _store(tmp_path)
    with pytest.raises(StopIteration):
        _run(store, execute=lambda _: next(iter(())))
    assert len(list((tmp_path / "budget").glob("*.reserved.json"))) == 1
    with pytest.raises(ValueError, match="unfinished"):
        _run(store)


@pytest.mark.parametrize(
    "mutation", ["missing_usage", "bad_total", "transport_error", "overspend"]
)
def test_uncertain_or_excess_usage_blocks_release_and_resume(
    tmp_path: Path, mutation: str
) -> None:
    """Preserve a terminal record and reservation when billing is uncertain.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary state root.
    mutation : str
        Injected usage or transport defect.

    Returns
    -------
    None
        Every defect stops the campaign without a settlement or retry.
    """

    store = _store(tmp_path)
    result, evidence = _execute(store.schedule[0])
    mutable = json.loads(json.dumps(evidence))
    observation = mutable["provider_responses"][0]
    if mutation == "missing_usage":
        del observation["provider_usage"]
    elif mutation == "bad_total":
        observation["provider_usage"]["total_tokens"] = 1
    elif mutation == "transport_error":
        observation["status"] = 504
    else:
        observation["provider_usage"] = {
            "input_tokens": 2000000,
            "output_tokens": 0,
            "total_tokens": 2000000,
        }
    with pytest.raises(ValueError):
        _run(store, execute=lambda _: (result, mutable))
    assert len(store.validated_records()) == 1
    assert not list((tmp_path / "budget").glob("*.settled.json"))
    with pytest.raises(ValueError, match="unfinished"):
        _run(store)


def test_settlement_tampering_and_operational_failure_block_resume(
    tmp_path: Path,
) -> None:
    """Reject a changed settlement before paying for another attempt.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary state root.

    Returns
    -------
    None
        Charge and immutable record fingerprints are reconciled on resume.
    """

    store = _store(tmp_path)
    _run(store, pool="2")
    path = next((tmp_path / "budget").glob("*.settled.json"))
    settlement = json.loads(path.read_text())
    settlement["charged_usd"] = "0"
    path.write_text(json.dumps(settlement))
    with pytest.raises(ValueError, match="settlement differs"):
        _run(store, pool="2")


@pytest.mark.parametrize(
    "field",
    ["harness_fingerprint", "oracle_fingerprints", "attempts", "checkpoint_seconds"],
)
def test_full_plan_detects_frozen_control_drift(field: str) -> None:
    """Reject changes to the generated full-campaign execution identity.

    Parameters
    ----------
    field : str
        Frozen launch-plan field to corrupt.

    Returns
    -------
    None
        Plan verification accepts the generated matrix and rejects drift.
    """

    spec = json.loads(
        Path(
            "benchmarks/agent-efficiency/campaign-specs/codira-efficacy-campaign-002.json"
        ).read_text()
    )
    manifest, plan = build_campaign(spec, Path("benchmarks/agent-efficiency"))
    assert len(validate_full_plan(manifest, plan, int(spec["seed"]))) == 60
    plan[field] = None
    with pytest.raises(ValueError):
        validate_full_plan(manifest, plan, int(spec["seed"]))


def test_usage_subsets_are_not_double_counted() -> None:
    """Count input and output once, independently of cache and reasoning subsets.

    Parameters
    ----------
    None

    Returns
    -------
    None
        Cost derives from the two inclusive provider token totals.
    """

    _, evidence = _execute(
        ScheduledAttempt("task-001", 1, "baseline", "attempt-001", "pair-001")
    )
    assert evidence_cost(evidence, Decimal(1), Decimal(1)) == Decimal("0.1")


def test_operational_failure_stops_after_one_record(tmp_path: Path) -> None:
    """Retain a failed execution and require diagnosis before resumption.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary state root.

    Returns
    -------
    None
        No later attempt executes after an operational failure.
    """

    store = _store(tmp_path)
    result, evidence = _execute(store.schedule[0])
    mutable = dict(result)
    mutable["outcome"] = "infrastructure_failure"
    mutable["failure_class"] = "provider_error"
    mutable["operational_calibration"] = {
        "status": "failed",
        "failure_class": "provider_error",
    }
    assert (
        _run(store, execute=lambda _: (mutable, evidence))["status"]
        == "execution_failed"
    )
    assert len(store.validated_records()) == 1
    with pytest.raises(ValueError, match="terminal execution failure"):
        _run(store)


def test_full_executor_admits_shared_pool_but_pilot_does_not() -> None:
    """Require the full runner and sixty scheduled attempts for pooled controls.

    Parameters
    ----------
    None

    Returns
    -------
    None
        Existing pilot admission cannot accidentally consume a shared pool.
    """

    spec = json.loads(
        Path(
            "benchmarks/agent-efficiency/campaign-specs/codira-efficacy-campaign-002.json"
        ).read_text()
    )
    manifest, _ = build_campaign(spec, Path("benchmarks/agent-efficiency"))
    assert (
        execution_controls(
            manifest, scheduled_attempts=60, full_campaign=True
        ).max_pilot_spend
        == 10
    )
    with pytest.raises(ValueError, match="qualified full-campaign"):
        execution_controls(manifest, scheduled_attempts=60)
    with pytest.raises(ValueError, match="qualified full-campaign"):
        execution_controls(manifest, scheduled_attempts=6, full_campaign=True)


def test_exclusive_lock_rejects_concurrent_execution(tmp_path: Path) -> None:
    """Reject another executor before any reservation or paid side effect.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary state root.

    Returns
    -------
    None
        A held lock excludes a second invocation.
    """

    store = _store(tmp_path)
    journal = tmp_path / "budget"
    journal.mkdir()
    with (journal / "execution.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(ValueError, match="another campaign executor"):
            _run(store)
    assert not list(journal.glob("*.reserved.json"))


def test_factory_executor_builds_full_and_resume_commands(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Bind sixty attempts and preserve separate logs on explicit resumption.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary factory and source roots.
    monkeypatch : pytest.MonkeyPatch
        Replace protected source admission for this command-only test.

    Returns
    -------
    None
        The credential consumer remains the already registered pilot runner.
    """

    specification = json.loads(
        Path(
            "benchmarks/agent-efficiency/campaign-specs/codira-efficacy-campaign-002.json"
        ).read_text()
    )
    manifest, plan = build_campaign(specification, Path("benchmarks/agent-efficiency"))
    campaign = tmp_path / "campaign"
    write_campaign_artifacts(campaign, manifest, plan)
    sources = {}
    for fixture_id in ("click-public", "codira-public", "picomatch-public"):
        source = tmp_path / fixture_id
        source.mkdir()
        sources[fixture_id] = source
    monkeypatch.setattr(
        "scripts.launch_agent_efficiency_pilot.validate_protected_task_assets",
        lambda *args: None,
    )
    launch = load_launch(
        campaign, tmp_path / "execution", sources, "podman", int(specification["seed"])
    )
    session, initial = tmux_command(launch)
    resume_session, resumed = tmux_command(launch, invocation=1)
    assert "--full-campaign --launch-plan" in initial
    assert initial.count("--task-id") == 6
    assert "scripts/run_agent_efficiency_phase6_pilot.py" in initial
    assert session != resume_session
    assert "resume-001.log" in resumed and "resume-001.exit" in resumed
    plan["oracle_fingerprints"] = {}
    (campaign / "launch-plan.json").write_text(json.dumps(plan))
    with pytest.raises((ValueError, PilotLaunchError), match="oracle identities"):
        load_launch(
            campaign,
            tmp_path / "execution",
            sources,
            "podman",
            int(specification["seed"]),
        )
