#!/usr/bin/env python3
"""Generate immutable, credential-free agent-efficiency campaign artifacts."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.agent_efficiency.campaign_factory import (
    CampaignFactoryError,
    build_campaign,
    validate_campaign_artifacts,
    write_campaign_artifacts,
)
from scripts.agent_efficiency.contracts import ContractError, load_document


def build_parser() -> argparse.ArgumentParser:
    """Build the credential-free campaign-factory parser.

    Parameters
    ----------
    None

    Returns
    -------
    argparse.ArgumentParser
        Parser requiring a specification and output directory for generation or checks.
    """

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Validate existing immutable artifacts without rewriting them.",
    )
    return parser


def main(arguments: list[str] | None = None) -> int:
    """Generate or check immutable artifacts from a versioned specification.

    Parameters
    ----------
    arguments : list[str] or None, optional
        Command-line arguments excluding the executable name.

    Returns
    -------
    int
        Zero after generation; two when validation or persistence fails.
    """

    args = build_parser().parse_args(arguments)
    try:
        specification = load_document(args.spec, "campaign-spec")
        manifest, plan = build_campaign(
            specification, Path("benchmarks") / "agent-efficiency"
        )
        if args.check:
            validate_campaign_artifacts(args.output_dir, manifest, plan)
            manifest_path = args.output_dir / "campaign.json"
            plan_path = args.output_dir / "launch-plan.json"
        else:
            manifest_path, plan_path = write_campaign_artifacts(
                args.output_dir, manifest, plan
            )
    except (CampaignFactoryError, ContractError, OSError) as error:
        print(f"campaign factory error: {error}", file=sys.stderr)
        return 2
    print(
        json.dumps(
            {
                "campaign_manifest": str(manifest_path),
                "launch_plan": str(plan_path),
                "manifest_fingerprint": plan["manifest_fingerprint"],
                "scheduled_attempt_count": plan["scheduled_attempt_count"],
                "validation": "passed" if args.check else "generated",
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
