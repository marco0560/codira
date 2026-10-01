"""Validate and execute frozen paired campaigns with a durable shared budget.

Parameters
----------
None

Returns
-------
None
    This module provides offline admission and injectable execution helpers.
"""
# ruff: noqa: EM101, EM102, TRY003, TRY004, PLR0913

from __future__ import annotations

import fcntl
import hashlib
import json
import time
from collections.abc import Callable, Mapping
from decimal import Decimal
from pathlib import Path
from typing import cast

from scripts.agent_efficiency.campaign_state import (
    CampaignStore,
    ScheduledAttempt,
    _atomic_write,
    build_paired_schedule,
)
from scripts.agent_efficiency.contracts import canonical_fingerprint, load_document
from scripts.agent_efficiency.panels import panel_document_path

CHECKPOINT_SECONDS = 6 * 60 * 60
FULL_ATTEMPTS = 60


def harness_fingerprint() -> str:
    """Fingerprint the host harness and container build inputs.

    Parameters
    ----------
    None

    Returns
    -------
    str
        Identity of repository-relative execution sources and assets.
    """

    paths = set(Path("scripts/agent_efficiency").rglob("*"))
    paths.update(Path("scripts").glob("*agent_efficiency*.py"))
    return canonical_fingerprint(
        {
            path.as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(paths)
            if path.is_file() and "__pycache__" not in path.parts
        }
    )


def validate_full_plan(
    manifest: Mapping[str, object],
    plan: Mapping[str, object],
    seed: int,
) -> tuple[ScheduledAttempt, ...]:
    """Verify the complete schedule, harness, and oracle identities.

    Parameters
    ----------
    manifest : Mapping[str, object]
        Factory-generated frozen campaign manifest.
    plan : Mapping[str, object]
        Factory-generated frozen launch plan.
    seed : int
        Requested schedule seed.

    Returns
    -------
    tuple[ScheduledAttempt, ...]
        The exact sixty admitted attempts.

    Raises
    ------
    ValueError
        If schedule, harness, task, or oracle identity differs.
    """

    hashes = manifest.get("task_fingerprints")
    representative = manifest.get("stage") == "representative-campaign"
    expected_count = 24 if representative else 6
    repetitions = int(str(plan.get("repetitions", 1))) if representative else 5
    if not isinstance(hashes, Mapping) or len(hashes) != expected_count:
        raise ValueError("full campaign requires six frozen tasks")
    task_ids = tuple(str(task_id) for task_id in hashes)
    schedule = build_paired_schedule(task_ids, repetitions, seed)
    if (
        plan.get("factory_version") != ("1.1" if representative else "1.0")
        or plan.get("stage")
        != ("representative-campaign" if representative else "full-campaign")
        or plan.get("campaign_id") != manifest.get("campaign_id")
        or plan.get("manifest_fingerprint") != canonical_fingerprint(manifest)
        or plan.get("seed") != seed
        or plan.get("repetitions") != repetitions
        or plan.get("scheduled_attempt_count") != expected_count * repetitions * 2
        or canonical_fingerprint({"attempts": plan.get("attempts")})
        != canonical_fingerprint({"attempts": [item.__dict__ for item in schedule]})
        or plan.get("harness_fingerprint") != harness_fingerprint()
        or plan.get("checkpoint_seconds") != CHECKPOINT_SECONDS
    ):
        raise ValueError("full campaign plan or harness identity differs")
    oracle_hashes = plan.get("oracle_fingerprints")
    if not isinstance(oracle_hashes, Mapping) or set(oracle_hashes) != set(task_ids):
        raise ValueError("full campaign oracle identities are incomplete")
    for task_id in task_ids:
        task = load_document(
            panel_document_path(Path("benchmarks/agent-efficiency"), "tasks", task_id),
            "task",
        )
        oracle = load_document(
            panel_document_path(
                Path("benchmarks/agent-efficiency"), "oracles", str(task["oracle_id"])
            ),
            "oracle",
        )
        if (
            canonical_fingerprint(task) != hashes[task_id]
            or oracle.get("task_id") != task_id
            or canonical_fingerprint(oracle) != oracle_hashes[task_id]
        ):
            raise ValueError("full campaign task or oracle identity differs")
    return schedule


def evidence_cost(
    evidence: Mapping[str, object],
    prompt_price: Decimal,
    completion_price: Decimal,
) -> Decimal:
    """Price every received response from complete provider usage evidence.

    Parameters
    ----------
    evidence : Mapping[str, object]
        Persisted attempt evidence with provider response observations.
    prompt_price : decimal.Decimal
        Frozen input-token ceiling per million tokens.
    completion_price : decimal.Decimal
        Frozen output-token ceiling per million tokens.

    Returns
    -------
    decimal.Decimal
        Conservative cost; uncertain transport or usage raises an error.

    Raises
    ------
    ValueError
        If received responses lack trustworthy complete usage evidence.
    """

    observations = evidence.get("provider_responses")
    if not isinstance(observations, list) or not observations:
        raise ValueError("complete provider billing evidence is unavailable")
    cost = Decimal(0)
    upstream_count = 0
    for observation in observations:
        if not isinstance(observation, Mapping):
            raise ValueError("provider observation is invalid")
        if observation.get("source") == "local":
            continue
        upstream_count += 1
        usage = observation.get("provider_usage")
        if (
            observation.get("source") != "upstream"
            or observation.get("status") != 200
            or not isinstance(usage, Mapping)
            or not isinstance(observation.get("response_sha256"), str)
            or observation.get("usage_exceeded_frozen_response_limits")
        ):
            raise ValueError("provider billing evidence is uncertain")
        tokens = [
            usage.get(name)
            for name in ("input_tokens", "output_tokens", "total_tokens")
        ]
        if any(
            not isinstance(value, int) or isinstance(value, bool) or value < 0
            for value in tokens
        ):
            raise ValueError("provider usage is incomplete")
        input_tokens, output_tokens, total_tokens = cast("list[int]", tokens)
        if input_tokens + output_tokens != total_tokens:
            raise ValueError("provider usage totals differ")
        cost += (
            Decimal(input_tokens) * prompt_price
            + Decimal(output_tokens) * completion_price
        ) / Decimal(1_000_000)
    if upstream_count == 0:
        raise ValueError("provider billing evidence has no received completion")
    return cost


def run_full_campaign(
    store: CampaignStore,
    execute: Callable[
        [ScheduledAttempt, Decimal],
        tuple[Mapping[str, object], Mapping[str, object]],
    ],
    *,
    pool: Decimal,
    attempt_estimate: Decimal,
    prompt_price: Decimal,
    completion_price: Decimal,
    clock: Callable[[], float] = time.monotonic,
) -> dict[str, object]:
    """Execute pending pairs under an exclusive lock and immutable budget journal.

    Parameters
    ----------
    store : CampaignStore
        Frozen sixty-attempt state.
    execute : Callable
        Qualified attempt executor receiving the remaining campaign allowance
        and returning result and response evidence.
    pool : decimal.Decimal
        Fixed aggregate campaign ceiling.
    attempt_estimate : decimal.Decimal
        Informational per-attempt price estimate frozen in the journal.
    prompt_price : decimal.Decimal
        Frozen input-token price per million tokens.
    completion_price : decimal.Decimal
        Frozen output-token price per million tokens.
    clock : Callable, optional
        Monotonic clock for checkpoints between complete pairs.

    Returns
    -------
    dict[str, object]
        Completion, budget stop, checkpoint, or terminal execution stop.

    Raises
    ------
    ValueError
        If the budget journal, usage, or resume state cannot be admitted.

    Notes
    -----
    Start markers precede all attempt side effects. Interrupted starts, failed
    operational records, and uncertain billing prohibit resumption. The soft
    pool stops new attempts when observed charges reach its threshold; the
    final received response may cross it. Settlements reference immutable
    result evidence and survive daily resets.
    """

    if not store.schedule or pool <= 0 or attempt_estimate <= 0:
        raise ValueError("full campaign schedule or budget is invalid")
    journal = store.root / "budget"
    journal.mkdir(exist_ok=True)
    with (journal / "execution.lock").open("a", encoding="utf-8") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise ValueError(
                "another campaign executor holds the budget lock"
            ) from error
        store.initialize()
        identity = {
            "configuration_fingerprint": store.configuration_fingerprint,
            "pool_usd": str(pool),
            "attempt_estimate_usd": str(attempt_estimate),
            "prompt_price": str(prompt_price),
            "completion_price": str(completion_price),
        }
        if any(journal.glob("*.reserved.json")):
            raise ValueError("legacy reservation journal cannot use observed spending")
        identity_path = journal / "identity.json"
        if identity_path.exists():
            if json.loads(identity_path.read_text()) != identity:
                raise ValueError("shared budget identity differs")
        else:
            _atomic_write(identity_path, identity)
        records = store.validated_records()
        starts = {
            path.stem.removesuffix(".started")
            for path in journal.glob("*.started.json")
        }
        settlements = {
            path.stem.removesuffix(".settled")
            for path in journal.glob("*.settled.json")
        }
        if starts != settlements or starts != set(records):
            raise ValueError("unfinished or inconsistent budget evidence blocks resume")
        spent = Decimal(0)
        for attempt_id, record in records.items():
            start = json.loads((journal / f"{attempt_id}.started.json").read_text())
            settlement = json.loads(
                (journal / f"{attempt_id}.settled.json").read_text()
            )
            expected = {**identity, "attempt_id": attempt_id}
            charge = evidence_cost(
                cast("Mapping[str, object]", record["evidence"]),
                prompt_price,
                completion_price,
            )
            if start != expected or settlement != {
                **expected,
                "charged_usd": str(charge),
                "record_fingerprint": canonical_fingerprint(record),
            }:
                raise ValueError(
                    "shared budget settlement differs from immutable evidence"
                )
            if _requires_stop(cast("Mapping[str, object]", record["result"])):
                raise ValueError("terminal execution failure blocks automatic resume")
            spent += charge
        started = clock()
        written: list[str] = []
        status = "complete"
        previous_pair: str | None = None
        for attempt in store.pending_attempts():
            if spent >= pool:
                status = "budget_exhausted"
                break
            if (
                attempt.pair_id != previous_pair
                and clock() - started >= CHECKPOINT_SECONDS
            ):
                status = "checkpoint"
                break
            expected = {**identity, "attempt_id": attempt.attempt_id}
            _atomic_write(journal / f"{attempt.attempt_id}.started.json", expected)
            result, evidence = execute(attempt, pool - spent)
            path = store.store_result(attempt.attempt_id, result, evidence)
            charge = evidence_cost(evidence, prompt_price, completion_price)
            record = json.loads(path.read_text())
            _atomic_write(
                journal / f"{attempt.attempt_id}.settled.json",
                {
                    **expected,
                    "charged_usd": str(charge),
                    "record_fingerprint": canonical_fingerprint(record),
                },
            )
            spent += charge
            written.append(attempt.attempt_id)
            previous_pair = attempt.pair_id
            if _requires_stop(result):
                status = (
                    "budget_exhausted"
                    if result.get("failure_class") == "campaign_spend_limit_reached"
                    else "execution_failed"
                )
                break
        report: dict[str, object] = {
            "status": status,
            "charged_usd": str(spent),
            "new_attempt_ids": written,
            "pending_attempt_ids": [
                item.attempt_id for item in store.pending_attempts()
            ],
        }
        _atomic_write(
            journal
            / f"checkpoint-{len(tuple(journal.glob('checkpoint-*.json'))):03d}.json",
            report,
        )
        return report


def _requires_stop(result: Mapping[str, object]) -> bool:
    """Distinguish a scored task failure from an execution or grading defect.

    Parameters
    ----------
    result : Mapping[str, object]
        One schema-valid attempt result.

    Returns
    -------
    bool
        Whether operator diagnosis is required before more paid attempts.
    """

    operational = result.get("operational_calibration")
    return (
        not isinstance(operational, Mapping)
        or operational.get("status") != "passed"
        or result.get("usage_complete") is not True
        or result.get("failure_class") in {"oracle_contract", "workspace_capture"}
    )
