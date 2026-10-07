"""Check selective completion against a synthetic immutable parent campaign."""

from __future__ import annotations

import fcntl
import hashlib
import json
import shutil
from decimal import Decimal
from pathlib import Path
from typing import cast

import pytest

from scripts.agent_efficiency.campaign_factory import (
    build_campaign,
    write_campaign_artifacts,
)
from scripts.agent_efficiency.campaign_state import CampaignStore, ScheduledAttempt
from scripts.agent_efficiency.completion_campaign import validate_completion_plan
from scripts.agent_efficiency.contracts import canonical_fingerprint
from scripts.agent_efficiency.full_campaign import run_full_campaign
from scripts.launch_agent_efficiency_pilot import PilotLaunch, tmux_command
from scripts.run_agent_efficiency_phase6_pilot import execution_controls, execution_plan


def _result(
    campaign_id: str, attempt: ScheduledAttempt, *, failed: bool = False
) -> dict[str, object]:
    """Build one schema-valid synthetic parent result.

    Parameters
    ----------
    campaign_id : str
        Synthetic parent identity.
    attempt : ScheduledAttempt
        Source schedule member.
    failed : bool, optional
        Mark one attempted slot as an operational failure.

    Returns
    -------
    dict[str, object]
        Public result compatible with the run-result schema.
    """

    return {
        "schema_version": "1.0",
        "campaign_id": campaign_id,
        "task_id": attempt.task_id,
        "attempt_id": attempt.attempt_id,
        "assistance_mode": attempt.assistance_mode,
        "outcome": "infrastructure_failure" if failed else "success",
        "failure_class": "session_token_cap_exceeded" if failed else None,
        "usage_complete": not failed,
        "usage": {
            "input_tokens": 0,
            "output_tokens": 0,
            "cached_input_tokens": 0,
            "reasoning_output_tokens": 0,
        },
        "provenance": {"runner": "synthetic", "runner_version": "1.0"},
        "operational_calibration": {
            "status": "failed" if failed else "passed",
            "failure_class": "session_token_cap_exceeded" if failed else None,
        },
        "task_oracle": {
            "status": "not_evaluated" if failed else "passed",
            "failure_class": None,
            "fingerprint": None if failed else "a" * 64,
        },
    }


def _fixture(tmp_path: Path) -> tuple[dict[str, object], dict[str, object], Path]:
    """Create a source with 54 completed slots and one failed record.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Isolated root for parent and benchmark documents.

    Returns
    -------
    tuple[dict[str, object], dict[str, object], pathlib.Path]
        Completion specification, parent plan, and copied benchmark root.
    """

    repository = Path.cwd()
    root = tmp_path / "repository"
    benchmark_root = root / "benchmarks/agent-efficiency"
    for directory in ("tasks", "oracles", "fixtures"):
        (benchmark_root / directory).mkdir(parents=True)
        for file in (repository / "benchmarks/agent-efficiency" / directory).glob(
            "*.json"
        ):
            shutil.copyfile(file, benchmark_root / directory / file.name)
    parent_spec = json.loads(
        (
            repository
            / "benchmarks/agent-efficiency/campaign-specs/codira-efficacy-campaign-006.json"
        ).read_text()
    )
    from scripts.run_agent_efficiency_phase6_pilot import runtime_profile_fingerprint

    parent_spec["campaign_id"] = "synthetic-parent-001"
    parent_spec["runtime_profile_fingerprint"] = runtime_profile_fingerprint()
    parent_manifest, parent_plan = build_campaign(parent_spec, benchmark_root)
    campaign_dir = root / "source-campaign"
    write_campaign_artifacts(campaign_dir, parent_manifest, parent_plan)
    parent_attempts = cast("list[dict[str, object]]", parent_plan["attempts"])
    schedule = tuple(
        ScheduledAttempt(
            cast("str", item["task_id"]),
            cast("int", item["repetition"]),
            cast("str", item["assistance_mode"]),
            cast("str", item["attempt_id"]),
            cast("str", item["pair_id"]),
        )
        for item in parent_attempts
    )
    state_root = root / "source-state"
    store = CampaignStore(
        state_root, "synthetic-parent-001", {"frozen": True}, schedule
    )
    store.initialize()
    for attempt in schedule[:55]:
        store.store_result(
            attempt.attempt_id,
            _result("synthetic-parent-001", attempt, failed=attempt == schedule[54]),
            {},
        )
    completion_spec = json.loads(
        (
            repository
            / "benchmarks/agent-efficiency/campaign-specs/codira-efficacy-completion-007.json"
        ).read_text()
    )
    completion_spec["campaign_id"] = "synthetic-completion-001"
    completion_spec["runtime_profile_fingerprint"] = runtime_profile_fingerprint()
    completion_spec["completion_source"] = {
        "campaign_id": "synthetic-parent-001",
        "campaign_dir": "source-campaign",
        "state_root": "source-state",
        "seed": cast("int", parent_spec["seed"]),
        "attempt_ids": [item.attempt_id for item in schedule[54:]],
    }
    return completion_spec, parent_plan, benchmark_root


def test_completion_factory_selects_only_unfinished_parent_slots(
    tmp_path: Path,
) -> None:
    """Freeze the exact failed and missing slots with parent provenance.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Isolated parent campaign and generated completion artifacts.

    Returns
    -------
    None
        Assertions cover selection, digests, and shared-pool controls.
    """

    specification, parent_plan, benchmark_root = _fixture(tmp_path)
    manifest, plan = build_campaign(specification, benchmark_root)
    expected = cast("list[dict[str, object]]", parent_plan["attempts"])[54:]
    assert plan["attempts"] == expected
    assert plan["scheduled_attempt_count"] == 6
    snapshot = cast("dict[str, object]", plan["source_snapshot"])
    assert len(cast("dict[str, str]", snapshot["record_fingerprints"])) == 55
    schedule = validate_completion_plan(
        manifest, plan, benchmark_root.parents[1], cast("int", specification["seed"])
    )
    assert [item.__dict__ for item in schedule] == expected
    assert (
        execution_controls(
            manifest, scheduled_attempts=6, full_campaign=True
        ).max_pilot_spend
        == 2
    )


def test_completion_rejects_cherry_picking_and_source_drift(tmp_path: Path) -> None:
    """Reject omitted unfinished slots and changed parent evidence.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Isolated parent campaign with mutable synthetic evidence.

    Returns
    -------
    None
        Assertions cover incomplete selection and source-byte changes.
    """

    specification, _, benchmark_root = _fixture(tmp_path)
    source = specification["completion_source"]
    assert isinstance(source, dict)
    source["attempt_ids"] = source["attempt_ids"][1:]
    with pytest.raises(ValueError, match="exactly unfinished slots"):
        build_campaign(specification, benchmark_root)
    source["attempt_ids"] = [
        "patch-002-r05-codira-mcp",
        "patch-002-r05-baseline",
        "impact-001-r05-codira-mcp",
        "impact-001-r05-baseline",
        "architecture-001-r01-codira-mcp",
        "architecture-001-r01-baseline",
    ]
    manifest, plan = build_campaign(specification, benchmark_root)
    record = (
        benchmark_root.parents[1] / "source-state/records/patch-002-r05-codira-mcp.json"
    )
    record.write_text(record.read_text() + " ")
    with pytest.raises(ValueError, match="source evidence differs"):
        validate_completion_plan(
            manifest,
            plan,
            benchmark_root.parents[1],
            cast("int", specification["seed"]),
        )


def test_completion_runner_settles_only_its_six_slots(tmp_path: Path) -> None:
    """Run the six selected attempts without importing parent result records.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Isolated parent and completion state roots.

    Returns
    -------
    None
        Assertions cover six fresh settlements and no pending attempts.
    """

    specification, _, benchmark_root = _fixture(tmp_path)
    manifest, plan = build_campaign(specification, benchmark_root)
    schedule = validate_completion_plan(
        manifest, plan, benchmark_root.parents[1], cast("int", specification["seed"])
    )
    store = CampaignStore(
        tmp_path / "completion-state",
        cast("str", manifest["campaign_id"]),
        {"manifest": manifest, "plan": plan},
        schedule,
    )
    store.initialize()

    def execute(
        attempt: ScheduledAttempt, remaining: Decimal
    ) -> tuple[dict[str, object], dict[str, object]]:
        """Produce complete synthetic provider usage for one selected slot.

        Parameters
        ----------
        attempt : ScheduledAttempt
            Selected completion schedule member.
        remaining : decimal.Decimal
            Positive observed campaign allowance.

        Returns
        -------
        tuple[dict[str, object], dict[str, object]]
            Schema-valid result and complete provider observations.
        """

        assert remaining > 0
        return _result(cast("str", manifest["campaign_id"]), attempt), {
            "provider_responses": [
                {
                    "source": "upstream",
                    "status": 200,
                    "response_sha256": "b" * 64,
                    "provider_usage": {
                        "input_tokens": 1000,
                        "output_tokens": 0,
                        "total_tokens": 1000,
                    },
                }
            ]
        }

    report = run_full_campaign(
        store,
        execute,
        pool=Decimal("2"),
        attempt_estimate=Decimal("1.05"),
        prompt_price=Decimal("0.25"),
        completion_price=Decimal("0.75"),
    )
    assert report["status"] == "complete"
    assert report["pending_attempt_ids"] == []
    assert len(store.validated_records()) == 6


def test_completion_launcher_builds_three_task_paid_command(tmp_path: Path) -> None:
    """Keep the shared-pool flag while selecting three task identities.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Isolated source used to build a completion launch plan.

    Returns
    -------
    None
        Assertions cover the paid command's exact task cardinality.
    """

    specification, _, benchmark_root = _fixture(tmp_path)
    manifest, plan = build_campaign(specification, benchmark_root)
    launch = PilotLaunch(
        tmp_path / "campaign",
        tmp_path / "execution",
        {},
        "podman",
        cast("int", specification["seed"]),
        manifest,
        plan,
    )
    _, command = tmux_command(launch)
    assert "--full-campaign" in command
    assert command.count("--task-id") == 3
    assert "--task-id patch-002" in command


def _representative_fixture(
    tmp_path: Path,
    *,
    budget_stop: bool = False,
) -> tuple[dict[str, object], dict[str, object], Path]:
    """Create a representative parent stopped after one arm of its thirtieth pair.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Isolated parent evidence and copied panel definitions.
    budget_stop : bool, optional
        Whether the last started slot was cut short by the budget guard.

    Returns
    -------
    tuple[dict[str, object], dict[str, object], pathlib.Path]
        Continuation specification, parent plan and benchmark root.
    """
    from codira.runtime_identity import runtime_identity

    root = tmp_path / "repository"
    benchmark_root = root / "benchmarks/agent-efficiency"
    shutil.copytree(
        Path("benchmarks/agent-efficiency/panels"), benchmark_root / "panels"
    )
    shutil.copytree(
        Path("benchmarks/agent-efficiency/fixtures"), benchmark_root / "fixtures"
    )
    parent_spec = json.loads(
        Path(
            "benchmarks/agent-efficiency/campaign-specs/codira-efficacy-campaign-020.json"
        ).read_text()
    )
    parent_spec["runtime_source_fingerprint"] = runtime_identity()["source_sha256"]
    parent_spec["campaign_id"] = "representative-parent-test"
    manifest, plan = build_campaign(parent_spec, benchmark_root)
    write_campaign_artifacts(root / "source-campaign", manifest, plan)
    schedule = tuple(
        ScheduledAttempt(
            cast("str", item["task_id"]),
            cast("int", item["repetition"]),
            cast("str", item["assistance_mode"]),
            cast("str", item["attempt_id"]),
            cast("str", item["pair_id"]),
        )
        for item in cast("list[dict[str, object]]", plan["attempts"])
    )
    store = CampaignStore(
        root / "source-state", "representative-parent-test", {"frozen": True}, schedule
    )
    store.initialize()
    budget = store.root / "budget"
    budget.mkdir()
    (budget / "execution.lock").touch()
    identity = {
        "configuration_fingerprint": store.configuration_fingerprint,
        "pool_usd": "7",
    }
    (budget / "identity.json").write_text(json.dumps(identity))
    for attempt in schedule[:59]:
        responses = (
            store.root / "attempt-work" / attempt.attempt_id / "provider-responses"
        )
        responses.mkdir(parents=True)
        body = b'{"status":"completed","usage":{"input_tokens":100,"output_tokens":0,"total_tokens":100,"cost":0.001}}'
        (responses / "response-001.body").write_bytes(body)
        result = _result("representative-parent-test", attempt)
        if budget_stop and attempt == schedule[58]:
            result = _result("representative-parent-test", attempt, failed=True)
            result["failure_class"] = "campaign_spend_limit_reached"
            result["operational_calibration"] = {
                "status": "failed",
                "failure_class": "campaign_spend_limit_reached",
            }
            result["usage_complete"] = False
        store.store_result(
            attempt.attempt_id,
            result,
            {
                "provider_responses": [
                    {
                        "source": "upstream",
                        "status": 200,
                        "response_artifact": "response-001.body",
                        "response_sha256": hashlib.sha256(body).hexdigest(),
                        "provider_usage": {
                            "input_tokens": 100,
                            "output_tokens": 0,
                            "total_tokens": 100,
                        },
                    }
                ]
            },
        )
        record = json.loads(
            (store.root / "records" / f"{attempt.attempt_id}.json").read_text()
        )
        (budget / f"{attempt.attempt_id}.started.json").write_text(
            json.dumps({**identity, "attempt_id": attempt.attempt_id})
        )
        (budget / f"{attempt.attempt_id}.settled.json").write_text(
            json.dumps(
                {
                    **identity,
                    "attempt_id": attempt.attempt_id,
                    "record_fingerprint": canonical_fingerprint(record),
                    "charged_usd": "0.001",
                }
            )
        )
    spec = {
        **parent_spec,
        "campaign_id": "representative-continuation-test",
        "stage": "completion",
        "task_ids": sorted({item.task_id for item in schedule[59:]}),
        "completion_source": {
            "campaign_id": "representative-parent-test",
            "campaign_dir": "source-campaign",
            "state_root": "source-state",
            "seed": parent_spec["seed"],
            "attempt_ids": [
                item.attempt_id for item in schedule[58 if budget_stop else 59 :]
            ],
        },
    }
    return spec, plan, benchmark_root


def test_representative_completion_preserves_all_85_unfinished_slots(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Keep every unfinished arm and exclude all 59 settled parent attempts.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Isolated representative parent evidence.
    monkeypatch : pytest.MonkeyPatch
        Bind launcher asset lookup to the isolated parent repository.

    Returns
    -------
    None
        Arbitrary remaining counts and a straddling pair are factory-admitted.
    """
    specification, parent, benchmark = _representative_fixture(tmp_path)
    manifest, plan = build_campaign(specification, benchmark)
    attempts = cast("list[dict[str, object]]", parent["attempts"])
    assert plan["attempts"] == attempts[59:]
    assert plan["scheduled_attempt_count"] == 85
    assert attempts[58]["pair_id"] == attempts[59]["pair_id"]
    assert set(
        item["attempt_id"] for item in cast("list[dict[str, object]]", plan["attempts"])
    ).isdisjoint(item["attempt_id"] for item in attempts[:59])
    assert (
        execution_controls(
            manifest, scheduled_attempts=85, full_campaign=True
        ).max_pilot_spend
        == 7
    )
    assert (
        len(validate_completion_plan(manifest, plan, benchmark.parents[1], 261004))
        == 85
    )
    snapshot = cast("dict[str, object]", plan["source_snapshot"])
    assert len(cast("dict[str, str]", snapshot["record_fingerprints"])) == 59
    assert "budget_fingerprints" in snapshot
    assert snapshot["parent_reported_spend_usd"] == "0.059"
    from scripts import launch_agent_efficiency_pilot as launcher

    campaign = benchmark.parents[1] / "completion-campaign"
    write_campaign_artifacts(campaign, manifest, plan)
    monkeypatch.setattr(launcher, "BENCHMARK_ROOT", benchmark)
    monkeypatch.setattr(launcher, "validate_protected_task_assets", lambda *_: None)
    from scripts.agent_efficiency import completion_campaign

    fingerprint = plan["harness_fingerprint"]
    monkeypatch.setattr(completion_campaign, "harness_fingerprint", lambda: fingerprint)
    monkeypatch.chdir(benchmark.parents[1])
    bindings = cast("dict[str, str]", manifest["task_fixture_ids"])
    launch = launcher.load_launch(
        campaign,
        benchmark.parents[1] / "completion-execution",
        {fixture: benchmark for fixture in bindings.values()},
        "podman",
        261004,
    )
    _, selected = execution_plan(
        manifest,
        tuple(sorted(bindings)),
        261004,
        campaign / "launch-plan.json",
        full_campaign=True,
    )
    assert len(selected) == 85
    assert launch.plan["scheduled_attempt_count"] == 85


@pytest.mark.parametrize(
    "failure", ["started", "locked", "settlement", "omit", "repeat", "runtime", "body"]
)
def test_representative_completion_rejects_uncertain_or_duplicate_work(
    tmp_path: Path, failure: str
) -> None:
    """Block continuation when parent billing or exact selection is uncertain.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Isolated source evidence.
    failure : str
        Independent mutation of parent accounting or selected attempts.

    Returns
    -------
    None
        No uncertain source permits factory generation or paid work.
    """
    spec, parent, benchmark = _representative_fixture(tmp_path)
    root = benchmark.parents[1]
    source = cast("dict[str, object]", spec["completion_source"])
    selected = cast("list[str]", source["attempt_ids"])
    lock = None
    if failure == "started":
        (root / "source-state/budget/unfinished.started.json").write_text("{}")
    elif failure == "locked":
        lock = (root / "source-state/budget/execution.lock").open("r")
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    elif failure == "settlement":
        path = next((root / "source-state/budget").glob("*.settled.json"))
        path.write_text('{"record_fingerprint":"bad"}')
    elif failure == "omit":
        selected.pop()
    elif failure == "repeat":
        selected.append(
            cast("list[dict[str, str]]", parent["attempts"])[0]["attempt_id"]
        )
    elif failure == "body":
        path = next(
            (root / "source-state/attempt-work").glob("*/provider-responses/*.body")
        )
        path.write_bytes(path.read_bytes() + b" ")
    else:
        spec["runtime_source_fingerprint"] = "0" * 64
    try:
        with pytest.raises(ValueError):
            build_campaign(spec, benchmark)
    finally:
        if lock is not None:
            lock.close()


def test_budget_interrupted_slot_is_unfinished_with_complete_provider_billing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Retry only a known budget interruption whose charges remain accounted.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Isolated parent cut short after 59 starts.
    monkeypatch : pytest.MonkeyPatch
        Bind launcher asset lookup to the isolated parent repository.

    Returns
    -------
    None
        The incomplete last slot joins 85 unstarted slots; 58 results remain used.
    """
    spec, parent, benchmark = _representative_fixture(tmp_path, budget_stop=True)
    manifest, plan = build_campaign(spec, benchmark)
    assert plan["scheduled_attempt_count"] == 86
    assert plan["attempts"] == cast("list[dict[str, object]]", parent["attempts"])[58:]
    snapshot = cast("dict[str, object]", plan["source_snapshot"])
    assert snapshot["parent_reported_spend_usd"] == "0.059"
    from scripts import launch_agent_efficiency_pilot as launcher

    campaign = benchmark.parents[1] / "completion-campaign"
    write_campaign_artifacts(campaign, manifest, plan)
    monkeypatch.setattr(launcher, "BENCHMARK_ROOT", benchmark)
    monkeypatch.setattr(launcher, "validate_protected_task_assets", lambda *_: None)
    from scripts.agent_efficiency import completion_campaign

    fingerprint = plan["harness_fingerprint"]
    monkeypatch.setattr(completion_campaign, "harness_fingerprint", lambda: fingerprint)
    monkeypatch.chdir(benchmark.parents[1])
    bindings = cast("dict[str, str]", manifest["task_fixture_ids"])
    launch = launcher.load_launch(
        campaign,
        benchmark.parents[1] / "completion-execution",
        {fixture: benchmark for fixture in bindings.values()},
        "podman",
        261004,
    )
    _, selected = execution_plan(
        manifest,
        tuple(sorted(bindings)),
        261004,
        campaign / "launch-plan.json",
        full_campaign=True,
    )
    assert len(selected) == 86
    assert launch.plan["scheduled_attempt_count"] == 86
    assert (
        len(validate_completion_plan(manifest, plan, benchmark.parents[1], 261004))
        == 86
    )
