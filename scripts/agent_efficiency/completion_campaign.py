"""Bind a selective completion campaign to immutable parent evidence."""
# ruff: noqa: C901, EM101, EM102, TRY003, TRY004

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
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
    harness_fingerprint,
)


def _repository_path(root: Path, value: object) -> Path:
    """Resolve one repository-relative evidence path.

    Parameters
    ----------
    root : pathlib.Path
        Trusted repository root.
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
    expected = [
        item.__dict__
        for item in build_paired_schedule(tuple(parent_tasks), 5, parent_seed)
    ]
    if (
        parent_plan.get("stage") != "full-campaign"
        or parent_plan.get("campaign_id") != source_manifest.get("campaign_id")
        or parent_plan.get("manifest_fingerprint")
        != canonical_fingerprint(source_manifest)
        or parent_plan.get("seed") != source.get("seed")
        or parent_plan.get("repetitions") != 5
        or parent_plan.get("scheduled_attempt_count") != 60
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
        or len(unfinished) != 6
        or any(
            sum(candidate.pair_id == item.pair_id for candidate in unfinished) != 2
            for item in unfinished
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
        Exact six source-ordered attempts admitted for completion.

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
            root / f"benchmarks/agent-efficiency/tasks/{task_id}.json", "task"
        )
        oracle = load_document(
            root / f"benchmarks/agent-efficiency/oracles/{task['oracle_id']}.json",
            "oracle",
        )
        if (
            canonical_fingerprint(task) != task_hashes[task_id]
            or oracle.get("task_id") != task_id
            or canonical_fingerprint(oracle) != oracle_hashes[task_id]
        ):
            raise ValueError("completion task or oracle identity differs")
    return schedule
