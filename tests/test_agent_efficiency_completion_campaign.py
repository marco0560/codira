"""Check selective completion against a synthetic immutable parent campaign."""

from __future__ import annotations

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
from scripts.agent_efficiency.full_campaign import run_full_campaign
from scripts.run_agent_efficiency_phase6_pilot import execution_controls


def _result(
    campaign_id: str, attempt: ScheduledAttempt, *, failed: bool = False
) -> dict[str, object]:
    """Build one schema-valid synthetic parent result."""

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
    """Create a source with 54 completed slots and one failed record."""

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
    parent_spec["campaign_id"] = "synthetic-parent-001"
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
    """Freeze the exact failed and missing slots with parent provenance."""

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
    """Reject omitted unfinished slots and changed parent evidence."""

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
    """Run the six selected attempts without importing parent result records."""

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
        """Produce complete synthetic provider usage for one selected slot."""

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
