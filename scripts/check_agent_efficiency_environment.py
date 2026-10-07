#!/usr/bin/env python3
"""Inspect non-billed prerequisites for agent-efficiency benchmark runs.

Responsibilities
----------------
- Validate pinned Codex and container prerequisites without starting an agent.
- Emit a secret-free JSON report suitable for Phase 0 ledger evidence.

Design principles
-----------------
The command reports not-ready hosts with a non-zero exit status and never
silently treats a missing runtime or image as a usable benchmark environment.

Architectural role
------------------
This script is the Phase 0 host conformance entry point for issue #53.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.agent_efficiency.phase0 import (
    ASSISTANCE_MODES,
    CheckResult,
    HostConformanceRequest,
    build_conformance_report,
    jsonl_conformance_check,
    parse_jsonl_events,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def build_parser() -> argparse.ArgumentParser:
    """Build the host-conformance command-line parser.

    Parameters
    ----------
    None

    Returns
    -------
    argparse.ArgumentParser
        Configured parser for non-billed prerequisite inspection.
    """

    parser = argparse.ArgumentParser(
        description="Check Phase 0 prerequisites without starting a Codex turn."
    )
    parser.add_argument("--codex", default="codex", help="Codex executable.")
    parser.add_argument(
        "--container-runtime",
        default="docker",
        choices=("docker", "podman"),
        help="Supported container runtime.",
    )
    parser.add_argument(
        "--image",
        required=True,
        help="Locally available benchmark image pinned by sha256 digest.",
    )
    parser.add_argument(
        "--state-root",
        type=Path,
        required=True,
        help="Empty per-run Codex state directory outside this checkout.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Optional path for the JSON conformance report.",
    )
    parser.add_argument(
        "--events",
        type=Path,
        help="JSONL from a separately approved, completed live probe.",
    )
    parser.add_argument(
        "--assistance-mode",
        choices=ASSISTANCE_MODES,
        default="codira-mcp",
        help="Expected MCP exposure for --events; baseline rejects MCP events.",
    )
    return parser


def main(arguments: list[str] | None = None) -> int:
    """Run non-billed agent-efficiency host conformance inspection.

    Parameters
    ----------
    arguments : list[str] or None, optional
        CLI arguments excluding the program name. Defaults to process arguments.

    Returns
    -------
    int
        Zero only when every Phase 0 prerequisite is demonstrated.
    """

    args = build_parser().parse_args(arguments)
    report = build_conformance_report(
        request=HostConformanceRequest(
            codex=args.codex,
            runtime=args.container_runtime,
            image=args.image,
            state_root=args.state_root,
            repository_root=REPOSITORY_ROOT,
        ),
    )
    checks = report.checks
    if args.events is not None:
        try:
            events = parse_jsonl_events(args.events.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            checks += (CheckResult("jsonl-evidence", False, str(error)),)
        else:
            checks += (jsonl_conformance_check(events, args.assistance_mode),)
    payload = (
        json.dumps(type(report)(checks).as_dict(), indent=2, sort_keys=True) + "\n"
    )
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
    print(payload, end="")
    return 0 if all(check.passed for check in checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())
