#!/usr/bin/env python3
"""Inspect a frozen Issue #53 Phase 4 campaign schedule and resume state.

The command intentionally has no paid-execution switch.  It creates or checks
the immutable campaign state, then prints pending schedule members.  A bounded
pilot manifest and approved provider transport are required before a live
runner is connected in Phase 6.
"""
# ruff: noqa: EM101, TRY003, TRY004, TRY301

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.agent_efficiency.campaign_state import CampaignStore, build_paired_schedule


def build_parser() -> argparse.ArgumentParser:
    """Build the no-paid-execution Phase 4 state inspection parser.

    Parameters
    ----------
    None

    Returns
    -------
    argparse.ArgumentParser
        Parser for immutable schedule/state inspection inputs.
    """

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-root", type=Path, required=True)
    parser.add_argument("--campaign-id", required=True)
    parser.add_argument("--task-id", action="append", required=True)
    parser.add_argument("--repetitions", type=int, default=5)
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--configuration-json", type=Path, required=True)
    return parser


def main(arguments: list[str] | None = None) -> int:
    """Create or inspect resumable state without executing benchmark agents.

    Parameters
    ----------
    arguments : list[str] or None, optional
        Command-line arguments excluding the executable name.

    Returns
    -------
    int
        Zero when state is valid; two when frozen inputs are invalid.

    Raises
    ------
    SystemExit
        If command-line arguments do not satisfy the parser contract.
    """

    args = build_parser().parse_args(arguments)
    try:
        configuration = json.loads(args.configuration_json.read_text(encoding="utf-8"))
        if not isinstance(configuration, dict):
            raise ValueError("configuration JSON must be an object")
        store = CampaignStore(
            args.state_root,
            args.campaign_id,
            configuration,
            build_paired_schedule(args.task_id, args.repetitions, args.seed),
        )
        store.initialize()
        pending = store.pending_attempts()
    except (OSError, ValueError) as error:
        print(f"benchmark configuration error: {error}", file=sys.stderr)
        return 2
    print(
        json.dumps(
            {
                "campaign_id": args.campaign_id,
                "pending_attempt_ids": [attempt.attempt_id for attempt in pending],
                "scheduled_execution_count": len(store.schedule),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
