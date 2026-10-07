"""Bind unfinished campaign slots and actual charges to immutable parent evidence.

Parameters
----------
None

Returns
-------
None
    Completion admission never rewrites parent records or repeats finished slots.
"""
# ruff: noqa: C901, EM101, EM102, TRY003, TRY004

from __future__ import annotations

import fcntl
import hashlib
import json
import shutil
import subprocess
from collections.abc import Mapping
from decimal import Decimal
from pathlib import Path
from typing import cast

from scripts.agent_efficiency.campaign_state import (
    ScheduledAttempt,
    build_paired_schedule,
)
from scripts.agent_efficiency.contracts import (
    canonical_fingerprint,
    load_document,
    validate_document,
)
from scripts.agent_efficiency.full_campaign import (
    CHECKPOINT_SECONDS,
    evidence_cost,
    harness_fingerprint,
)
from scripts.agent_efficiency.panels import panel_document_path
from scripts.agent_efficiency.provider_billing import response_cost


def _repository_path(root: Path, value: object) -> Path:
    """Resolve one repository-relative evidence path.

    Parameters
    ----------
    root : pathlib.Path
        Trusted checkout; Git worktrees may read their shared repository root.
    value : object
        Requested repository-relative path.

    Returns
    -------
    pathlib.Path
        Resolved path within the trusted root.

    Raises
    ------
    ValueError
        If the path is absolute or escapes the repository.
    """

    if not isinstance(value, str) or not value or Path(value).is_absolute():
        raise ValueError("completion source path must be repository-relative")
    path = (root / value).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError("completion source path escapes the repository")
    if not path.exists():
        result = subprocess.run(
            [shutil.which("git") or "/usr/bin/git", "rev-parse", "--git-common-dir"],
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode == 0:
            shared_root = (root / result.stdout.strip()).resolve().parent
            shared = (shared_root / value).resolve()
            if shared.is_relative_to(shared_root) and shared.exists():
                return shared
    return path


def _sha256(path: Path) -> str:
    """Return the exact byte digest of one immutable source artifact.

    Parameters
    ----------
    path : pathlib.Path
        Existing artifact to digest.

    Returns
    -------
    str
        Lowercase SHA-256 digest.
    """

    return hashlib.sha256(path.read_bytes()).hexdigest()


def source_snapshot(
    source: Mapping[str, object], manifest: Mapping[str, object], root: Path
) -> tuple[tuple[ScheduledAttempt, ...], dict[str, object]]:
    """Verify the parent schedule and return exactly its unfinished slots.

    Parameters
    ----------
    source : Mapping[str, object]
        Repository-relative parent artifacts and selected attempt IDs.
    manifest : Mapping[str, object]
        New campaign manifest whose shared task and provider controls are checked.
    root : pathlib.Path
        Trusted repository root.

    Returns
    -------
    tuple[tuple[ScheduledAttempt, ...], dict[str, object]]
        Parent-ordered unfinished attempts and a digest-only evidence snapshot.

    Raises
    ------
    ValueError
        If the parent evidence is inconsistent or selection is incomplete.
    """

    campaign_dir = _repository_path(root, source.get("campaign_dir"))
    state_root = _repository_path(root, source.get("state_root"))
    source_manifest = load_document(campaign_dir / "campaign.json", "campaign")
    parent_plan = json.loads((campaign_dir / "launch-plan.json").read_text())
    parent_state = json.loads((state_root / "campaign-state.json").read_text())
    if not isinstance(parent_plan, dict) or not isinstance(parent_state, dict):
        raise ValueError("completion source plan or state is malformed")
    attempts = parent_plan.get("attempts")
    parent_tasks = source_manifest.get("task_fingerprints")
    parent_seed = source.get("seed")
    if not isinstance(parent_tasks, Mapping) or not isinstance(parent_seed, int):
        raise ValueError("completion source task or seed identity is invalid")
    representative = parent_plan.get("stage") == "representative-campaign"
    repetitions = parent_plan.get("repetitions") if representative else 5
    if not isinstance(repetitions, int) or not 1 <= repetitions <= 5:
        raise ValueError("completion parent repetition control is invalid")
    expected = [
        item.__dict__
        for item in build_paired_schedule(tuple(parent_tasks), repetitions, parent_seed)
    ]
    if (
        parent_plan.get("stage") not in {"full-campaign", "representative-campaign"}
        or parent_plan.get("campaign_id") != source_manifest.get("campaign_id")
        or parent_plan.get("manifest_fingerprint")
        != canonical_fingerprint(source_manifest)
        or parent_plan.get("seed") != source.get("seed")
        or parent_plan.get("repetitions") != repetitions
        or parent_plan.get("scheduled_attempt_count")
        != len(parent_tasks) * repetitions * 2
        or not isinstance(attempts, list)
        or attempts != expected
        or parent_state.get("campaign_id") != source_manifest.get("campaign_id")
        or parent_state.get("schedule") != attempts
        or source_manifest.get("campaign_id") != source.get("campaign_id")
    ):
        raise ValueError("completion source identity or schedule differs")
    for key in (
        "provider",
        "resource_controls",
        "runtime_image",
        "runtime_profile_fingerprint",
        "treatment_protocol",
    ):
        if source_manifest.get(key) != manifest.get(key):
            raise ValueError(f"completion source {key} differs")
    if representative and any(
        source_manifest.get(key) != manifest.get(key)
        for key in ("panel_id", "budgets", "runtime_source_fingerprint")
    ):
        raise ValueError("representative completion controls differ")
    source_tasks = cast("Mapping[str, object]", source_manifest["task_fingerprints"])
    source_fixtures = cast(
        "Mapping[str, object]", source_manifest["fixture_fingerprints"]
    )
    new_tasks = cast("Mapping[str, object]", manifest["task_fingerprints"])
    new_fixtures = cast("Mapping[str, object]", manifest["fixture_fingerprints"])
    if any(
        source_tasks.get(task) != digest for task, digest in new_tasks.items()
    ) or any(
        source_fixtures.get(fixture) != digest
        for fixture, digest in new_fixtures.items()
    ):
        raise ValueError("completion source task or fixture differs")
    schedule = tuple(ScheduledAttempt(**item) for item in attempts)
    ids = {item.attempt_id for item in schedule}
    if len(ids) != len(schedule):
        raise ValueError("completion source has duplicate attempts")
    record_fingerprints: dict[str, str] = {}
    unfinished: list[ScheduledAttempt] = []
    for item in schedule:
        record_path = state_root / "records" / f"{item.attempt_id}.json"
        if not record_path.exists():
            unfinished.append(item)
            continue
        record = json.loads(record_path.read_text())
        if (
            not isinstance(record, dict)
            or record.get("state_version") != "1.0"
            or record.get("attempt") != item.__dict__
            or record.get("configuration_fingerprint")
            != parent_state.get("configuration_fingerprint")
        ):
            raise ValueError("completion source record identity differs")
        result = record.get("result")
        if not isinstance(result, dict):
            raise ValueError("completion source result is malformed")
        validate_document("run-result", result)
        if (
            result.get("campaign_id") != source_manifest["campaign_id"]
            or result.get("attempt_id") != item.attempt_id
        ):
            raise ValueError("completion source result identity differs")
        record_fingerprints[item.attempt_id] = _sha256(record_path)
        operational = result.get("operational_calibration")
        if (
            not isinstance(operational, Mapping)
            or operational.get("status") != "passed"
            or result.get("usage_complete") is not True
        ):
            unfinished.append(item)
    if set(state_root.joinpath("records").glob("*.json")) != {
        state_root / "records" / f"{attempt_id}.json"
        for attempt_id in record_fingerprints
    }:
        raise ValueError("completion source contains unknown records")
    selected = source.get("attempt_ids")
    if (
        not isinstance(selected, list)
        or not all(isinstance(item, str) for item in selected)
        or len(selected) != len(set(selected))
        or set(selected) != {item.attempt_id for item in unfinished}
        or not unfinished
        or (
            not representative
            and (
                len(unfinished) != 6
                or any(
                    sum(candidate.pair_id == item.pair_id for candidate in unfinished)
                    != 2
                    for item in unfinished
                )
            )
        )
    ):
        raise ValueError("completion selection must cover exactly unfinished slots")
    snapshot: dict[str, object] = {
        "campaign_id": source_manifest["campaign_id"],
        "manifest_fingerprint": _sha256(campaign_dir / "campaign.json"),
        "plan_fingerprint": _sha256(campaign_dir / "launch-plan.json"),
        "state_fingerprint": _sha256(state_root / "campaign-state.json"),
        "record_fingerprints": record_fingerprints,
    }
    if representative:
        snapshot["budget_fingerprints"] = _settled_parent_budget(
            state_root, record_fingerprints
        )
        snapshot["parent_reported_spend_usd"] = str(
            _parent_reported_spend(state_root, record_fingerprints)
        )
    return tuple(unfinished), snapshot


def validate_completion_plan(
    manifest: Mapping[str, object], plan: Mapping[str, object], root: Path, seed: int
) -> tuple[ScheduledAttempt, ...]:
    """Recheck a generated completion plan and its parent evidence.

    Parameters
    ----------
    manifest : Mapping[str, object]
        New campaign manifest with frozen task and provider controls.
    plan : Mapping[str, object]
        Factory-generated completion schedule and source snapshot.
    root : pathlib.Path
        Repository root containing the saved parent evidence and task assets.
    seed : int
        Requested seed matching the frozen parent schedule.

    Returns
    -------
    tuple[ScheduledAttempt, ...]
        Exact source-ordered unfinished attempts, including an unpaired arm.

    Raises
    ------
    ValueError
        If the plan, parent evidence, task, oracle, or harness has changed.
    """

    source = plan.get("completion_source")
    if not isinstance(source, Mapping):
        raise ValueError("completion plan lacks its source")
    schedule, snapshot = source_snapshot(source, manifest, root)
    if (
        plan.get("factory_version") != "1.0"
        or plan.get("stage") != "completion"
        or plan.get("campaign_id") != manifest.get("campaign_id")
        or plan.get("manifest_fingerprint") != canonical_fingerprint(manifest)
        or plan.get("seed") != seed
        or source.get("seed") != seed
        or plan.get("repetitions")
        != (
            json.loads(
                (
                    _repository_path(root, source.get("campaign_dir"))
                    / "launch-plan.json"
                ).read_text()
            )["repetitions"]
        )
        or plan.get("scheduled_attempt_count") != len(schedule)
        or plan.get("attempts") != [item.__dict__ for item in schedule]
        or plan.get("source_snapshot") != snapshot
        or plan.get("harness_fingerprint") != harness_fingerprint()
        or plan.get("checkpoint_seconds") != CHECKPOINT_SECONDS
    ):
        raise ValueError("completion plan or source evidence differs")
    oracle_hashes = plan.get("oracle_fingerprints")
    task_hashes = cast("Mapping[str, object]", manifest["task_fingerprints"])
    if not isinstance(oracle_hashes, Mapping) or set(oracle_hashes) != set(task_hashes):
        raise ValueError("completion oracle identities are incomplete")
    for task_id in task_hashes:
        task = load_document(
            panel_document_path(root / "benchmarks/agent-efficiency", "tasks", task_id),
            "task",
        )
        oracle = load_document(
            panel_document_path(
                root / "benchmarks/agent-efficiency", "oracles", str(task["oracle_id"])
            ),
            "oracle",
        )
        if (
            canonical_fingerprint(task) != task_hashes[task_id]
            or oracle.get("task_id") != task_id
            or canonical_fingerprint(oracle) != oracle_hashes[task_id]
        ):
            raise ValueError("completion task or oracle identity differs")
    return schedule


def _settled_parent_budget(
    state_root: Path, record_fingerprints: Mapping[str, str]
) -> dict[str, str]:
    """Freeze a stopped parent's billing journal without admitting uncertain starts.

    Parameters
    ----------
    state_root : pathlib.Path
        Parent campaign state directory.
    record_fingerprints : collections.abc.Mapping[str, str]
        Completed parent record identities.

    Returns
    -------
    dict[str, str]
        Exact journal digests preserved in the continuation plan.

    Raises
    ------
    ValueError
        If the parent is running or its starts and settlements are incomplete.
    """
    budget = state_root / "budget"
    if (
        not (budget / "execution.lock").exists()
        or not (budget / "identity.json").exists()
    ):
        raise ValueError("parent billing journal is unavailable")
    with (budget / "execution.lock").open("r") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_SH | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise ValueError("parent campaign is still running") from error
        starts = {
            p.name.removesuffix(".started.json") for p in budget.glob("*.started.json")
        }
        settled = {
            p.name.removesuffix(".settled.json") for p in budget.glob("*.settled.json")
        }
        if (
            starts != settled
            or starts != set(record_fingerprints)
            or any(budget.glob("*.reserved.json"))
        ):
            raise ValueError("unfinished parent billing blocks continuation")
        for attempt_id in starts:
            record = json.loads(
                (state_root / "records" / f"{attempt_id}.json").read_text()
            )
            settlement = json.loads((budget / f"{attempt_id}.settled.json").read_text())
            result = record.get("result", {})
            budget_stop = (
                result.get("failure_class") == "campaign_spend_limit_reached"
                and result.get("operational_calibration", {}).get("failure_class")
                == "campaign_spend_limit_reached"
            )
            if settlement.get("record_fingerprint") != canonical_fingerprint(
                record
            ) or (
                not budget_stop
                and (
                    result.get("usage_complete") is not True
                    or result.get("operational_calibration", {}).get("status")
                    != "passed"
                )
            ):
                raise ValueError("parent terminal evidence blocks continuation")
        return {p.name: _sha256(p) for p in sorted(budget.glob("*.json"))}


def _parent_reported_spend(state_root: Path, records: Mapping[str, str]) -> Decimal:
    """Reconcile parent charges from hash-verified retained provider bodies.

    Parameters
    ----------
    state_root : pathlib.Path
        Parent state with attempt evidence and exact response bodies.
    records : collections.abc.Mapping[str, str]
        Settled record identities selected by the parent snapshot.

    Returns
    -------
    decimal.Decimal
        Exact reported USD spending carried into the remaining campaign pool.

    Raises
    ------
    ValueError
        If any billed response is missing, altered or lacks terminal cost.
    """
    total = Decimal(0)
    for attempt_id in records:
        record = json.loads((state_root / "records" / f"{attempt_id}.json").read_text())
        evidence = record.get("evidence", {})
        observations = evidence.get("provider_responses")
        if not isinstance(observations, list) or not observations:
            raise ValueError("parent response billing evidence is absent")
        upstream = 0
        billed_observations: list[dict[str, object]] = []
        for observation in observations:
            if not isinstance(observation, Mapping):
                raise ValueError("parent billing observation is malformed")
            if observation.get("source") == "local":
                continue
            name = observation.get("response_artifact")
            if (
                observation.get("source") != "upstream"
                or observation.get("status") != 200
                or not isinstance(name, str)
                or Path(name).name != name
            ):
                raise ValueError("parent billing response identity is invalid")
            path = (
                state_root / "attempt-work" / attempt_id / "provider-responses" / name
            )
            if not path.exists() or _sha256(path) != observation.get("response_sha256"):
                raise ValueError("parent provider response digest differs")
            cost = response_cost(path.read_bytes())
            if cost is None:
                raise ValueError("parent reported charge is unavailable")
            billed_observations.append({**observation, "provider_cost_usd": str(cost)})
            upstream += 1
        if upstream == 0:
            raise ValueError("parent has no received provider charge")
        total += evidence_cost(
            {"provider_responses": billed_observations},
            Decimal(0),
            Decimal(0),
            "provider-reported",
        )
    return total
