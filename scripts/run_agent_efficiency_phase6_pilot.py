#!/usr/bin/env python3
"""Plan the bounded Issue #53 Phase 6 pilot without executing agents.

The command accepts a schema-valid campaign manifest and emits the deterministic
six-attempt schedule for three one-repetition pairs.  It deliberately rejects
``--execute`` until the separately approved pilot-manifest and spending-control
implementation is complete.
"""
# ruff: noqa: EM101, TRY003, TRY004, TRY301

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.agent_efficiency.campaign_state import build_paired_schedule
from scripts.agent_efficiency.contracts import (
    ContractError,
    canonical_fingerprint,
    load_document,
)


class PilotLauncherError(ValueError):
    """Report a deterministic, non-secret pilot-launcher validation failure.

    Parameters
    ----------
    detail : str
        Public-safe failure detail.
    """


def build_pilot_plan(
    manifest: Mapping[str, object], task_ids: Sequence[str], seed: int
) -> dict[str, object]:
    """Build the fixed six-attempt Phase 6 pilot plan without side effects.

    Parameters
    ----------
    manifest : collections.abc.Mapping[str, object]
        Schema-valid public campaign manifest.
    task_ids : collections.abc.Sequence[str]
        Exactly three unique public task identities.
    seed : int
        Persisted schedule-order seed.

    Returns
    -------
    dict[str, object]
        Public deterministic pilot identity, budget, and schedule summary.

    Raises
    ------
    PilotLauncherError
        If the manifest or requested pilot cardinality is invalid.
    """

    if len(task_ids) != 3 or len(set(task_ids)) != 3:
        raise PilotLauncherError("Phase 6 pilot requires exactly three unique tasks")
    task_fingerprints = manifest.get("task_fingerprints")
    task_fixture_ids = manifest.get("task_fixture_ids")
    fixture_fingerprints = manifest.get("fixture_fingerprints")
    if not isinstance(task_fingerprints, Mapping):
        raise PilotLauncherError("campaign manifest lacks immutable task bindings")
    if not isinstance(task_fixture_ids, Mapping):
        raise PilotLauncherError("campaign manifest lacks immutable task bindings")
    if not isinstance(fixture_fingerprints, Mapping):
        raise PilotLauncherError("campaign manifest lacks immutable task bindings")
    requested_tasks = set(task_ids)
    if requested_tasks != set(task_fingerprints) or requested_tasks != set(
        task_fixture_ids
    ):
        raise PilotLauncherError("pilot tasks must exactly match manifest bindings")
    if not all(isinstance(value, str) for value in task_fixture_ids.values()):
        raise PilotLauncherError("pilot fixture bindings must be strings")
    bound_fixtures = {
        value for value in task_fixture_ids.values() if isinstance(value, str)
    }
    if len(bound_fixtures) != 3 or not bound_fixtures <= set(fixture_fingerprints):
        raise PilotLauncherError("pilot requires three bound immutable fixtures")
    try:
        schedule = build_paired_schedule(task_ids, 1, seed)
    except ValueError as error:
        raise PilotLauncherError(str(error)) from error
    budgets = manifest.get("budgets")
    campaign_id = manifest.get("campaign_id")
    if not isinstance(budgets, Mapping) or not isinstance(campaign_id, str):
        raise PilotLauncherError("campaign manifest lacks required pilot fields")
    return {
        "campaign_id": campaign_id,
        "manifest_fingerprint": canonical_fingerprint(manifest),
        "seed": seed,
        "task_ids": sorted(task_ids),
        "repetitions": 1,
        "scheduled_execution_count": len(schedule),
        "budgets": dict(budgets),
        "attempts": [attempt.__dict__ for attempt in schedule],
        "execution_authorized": False,
    }


def build_parser() -> argparse.ArgumentParser:
    """Build the non-billed Phase 6 pilot launcher parser.

    Parameters
    ----------
    None

    Returns
    -------
    argparse.ArgumentParser
        Parser requiring a public campaign manifest and three task IDs.
    """

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign-manifest", type=Path, required=True)
    parser.add_argument("--task-id", action="append", required=True)
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--execute", action="store_true")
    return parser


def main(arguments: list[str] | None = None) -> int:
    """Validate and print a non-billed bounded pilot plan.

    Parameters
    ----------
    arguments : list[str] or None, optional
        Command-line arguments excluding the executable name.

    Returns
    -------
    int
        Zero for a valid dry run and two for invalid or disallowed execution.

    Raises
    ------
    SystemExit
        If command-line arguments do not satisfy the parser contract.
    """

    args = build_parser().parse_args(arguments)
    if args.execute:
        print(
            "Phase 6 execution requires a separately approved pilot manifest",
            file=sys.stderr,
        )
        return 2
    try:
        manifest = load_document(args.campaign_manifest, "campaign")
        plan = build_pilot_plan(manifest, args.task_id, args.seed)
    except (ContractError, OSError, PilotLauncherError) as error:
        print(f"pilot launcher error: {error}", file=sys.stderr)
        return 2
    print(json.dumps(plan, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
