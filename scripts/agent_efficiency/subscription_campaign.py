"""Run factory-frozen attempts against native Codex quota with durable starts."""
# ruff: noqa: EM101, EM102, TRY003

from __future__ import annotations

import fcntl
import json
import time
from typing import TYPE_CHECKING, cast

from scripts.agent_efficiency.codex_subscription import (
    SubscriptionQuotaError,
    subscription_quota_exhausted,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    from scripts.agent_efficiency.campaign_state import CampaignStore, ScheduledAttempt


def run_subscription_campaign(
    store: CampaignStore,
    execute: Callable[
        [ScheduledAttempt], tuple[Mapping[str, object], Mapping[str, object]]
    ],
    *,
    check_quota: Callable[[], Mapping[str, object]],
) -> dict[str, object]:
    """Execute pending attempts until the authenticated quota or checkpoint.

    Parameters
    ----------
    store : CampaignStore
        Initialized factory-frozen campaign state.
    execute : Callable
        One-attempt executor retaining its full private event trace.
    check_quota : Callable
        Read-only admission through the same frozen image and managed login.

    Returns
    -------
    dict[str, object]
        Public-safe completed count and stop reason.

    Raises
    ------
    ValueError
        If an unfinished start, quota failure, or concurrent executor is found.
    """
    start_root = store.root / "subscription-starts"
    start_root.mkdir(parents=True, exist_ok=True)
    with (store.root / "subscription.lock").open("a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        completed = store.validated_records()
        for start in start_root.glob("*.json"):
            if start.stem not in completed:
                raise ValueError(
                    "unfinished subscription attempt requires adjudication"
                )
        written = 0
        started = time.monotonic()
        for attempt in store.pending_attempts():
            if time.monotonic() - started >= 6 * 60 * 60:
                return {
                    "status": "checkpoint",
                    "reason": "elapsed_time",
                    "new_attempt_count": written,
                    "pending_attempt_count": len(store.pending_attempts()),
                }
            try:
                receipt = check_quota()
            except SubscriptionQuotaError:
                return {
                    "status": "checkpoint",
                    "reason": "subscription_quota_exhausted",
                    "new_attempt_count": written,
                    "pending_attempt_count": len(store.pending_attempts()),
                }
            if subscription_quota_exhausted(receipt):
                return {
                    "status": "checkpoint",
                    "reason": "subscription_quota_exhausted",
                    "new_attempt_count": written,
                    "pending_attempt_count": len(store.pending_attempts()),
                }
            with (start_root / f"{attempt.attempt_id}.json").open(
                "x", encoding="utf-8"
            ) as handle:
                json.dump(
                    {"attempt_id": attempt.attempt_id, "route_preflight": receipt},
                    handle,
                    sort_keys=True,
                    indent=2,
                )
                handle.write("\n")
            result, evidence = execute(attempt)
            store.store_result(attempt.attempt_id, result, evidence)
            written += 1
            if (
                cast(
                    "Mapping[str, object]", result.get("operational_calibration", {})
                ).get("status")
                != "passed"
            ):
                return {
                    "status": "checkpoint",
                    "reason": "operational_failure",
                    "new_attempt_count": written,
                    "pending_attempt_count": len(store.pending_attempts()),
                }
        return {
            "status": "complete",
            "new_attempt_count": written,
            "pending_attempt_count": 0,
        }
