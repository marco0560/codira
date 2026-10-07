#!/usr/bin/env python3
"""Evaluate immutable Issue #53 records and render public-safe reports.

This command never executes an agent or reads raw JSONL.  It reconstructs the
frozen campaign identity, validates installed records, and emits a canonical
JSON report plus Markdown derived solely from that JSON document.
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
from scripts.agent_efficiency.reporting import ReportError, write_report


def build_parser() -> argparse.ArgumentParser:
    """Build the deterministic public-report command parser.

    Parameters
    ----------
    None

    Returns
    -------
    argparse.ArgumentParser
        Parser requiring the frozen campaign identity and public output path.
    """

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--campaign-id", required=True)
    parser.add_argument("--task-id", action="append", required=True)
    parser.add_argument("--repetitions", type=int, default=5)
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--configuration-json", type=Path, required=True)
    return parser


def main(arguments: list[str] | None = None) -> int:
    """Validate stored evidence and render its public-safe report artifacts.

    Parameters
    ----------
    arguments : list[str] or None, optional
        Command-line arguments excluding the executable name.

    Returns
    -------
    int
        Zero after successful rendering and two for invalid frozen inputs.

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
        artifacts = write_report(store, args.output_dir)
    except (OSError, ReportError, ValueError) as error:
        print(f"benchmark reporting error: {error}", file=sys.stderr)
        return 2
    print(
        json.dumps(
            {
                "campaign_id": args.campaign_id,
                "json_report": str(artifacts.json_path),
                "markdown_report": str(artifacts.markdown_path),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
