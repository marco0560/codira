#!/usr/bin/env python3
"""Run exactly one bounded, persisted Phase 6 route calibration."""
# ruff: noqa: EM101, EM102, TRY003, TRY004, TRY301

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.agent_efficiency import provider_proxy
from scripts.agent_efficiency.campaign_state import CampaignStore, ScheduledAttempt
from scripts.agent_efficiency.contracts import (
    ContractError,
    canonical_fingerprint,
    load_document,
)
from scripts.run_agent_efficiency_phase6_pilot import (
    PilotExecutionContext,
    PilotLauncherError,
    execute_pilot_attempt,
    execution_controls,
    load_pilot_inputs,
    parse_fixture_sources,
    preflight_openrouter_route,
    runtime_profile_fingerprint,
    validate_treatment_protocol,
)


def calibration_attempt(manifest: dict[str, object]) -> ScheduledAttempt:
    """Return the sole assisted attempt after validating calibration bindings.

    Parameters
    ----------
    manifest : dict[str, object]
        Frozen one-task calibration manifest.

    Returns
    -------
    scripts.agent_efficiency.campaign_state.ScheduledAttempt
        One Codira-MCP calibration attempt.

    Raises
    ------
    PilotLauncherError
        If the manifest does not bind exactly one task and fixture.
    """

    task_hashes = manifest.get("task_fingerprints")
    bindings = manifest.get("task_fixture_ids")
    fixture_hashes = manifest.get("fixture_fingerprints")
    if not isinstance(task_hashes, dict):
        raise PilotLauncherError("calibration manifest lacks immutable bindings")
    if not isinstance(bindings, dict):
        raise PilotLauncherError("calibration manifest lacks immutable bindings")
    if not isinstance(fixture_hashes, dict):
        raise PilotLauncherError("calibration manifest lacks immutable bindings")
    if len(task_hashes) != 1 or set(task_hashes) != set(bindings):
        raise PilotLauncherError("calibration requires exactly one bound task")
    task_id = next(iter(task_hashes))
    fixture_id = bindings[task_id]
    if not isinstance(task_id, str) or not isinstance(fixture_id, str):
        raise PilotLauncherError("calibration manifest bindings are invalid")
    if set(fixture_hashes) != {fixture_id}:
        raise PilotLauncherError("calibration requires exactly one bound fixture")
    return ScheduledAttempt(
        task_id=task_id,
        repetition=1,
        assistance_mode="codira-mcp",
        attempt_id=f"{task_id}-calibration-codira-mcp",
        pair_id=f"{task_id}-calibration",
    )


def build_parser() -> argparse.ArgumentParser:
    """Build the explicit one-request calibration command parser.

    Parameters
    ----------
    None

    Returns
    -------
    argparse.ArgumentParser
    Parser requiring a frozen manifest and one explicit offline-preflight or
    paid-execution stage.
    """

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign-manifest", type=Path, required=True)
    parser.add_argument("--state-root", type=Path, required=True)
    parser.add_argument("--fixture-source", action="append", required=True)
    parser.add_argument("--image", required=True)
    parser.add_argument("--runtime", default="podman")
    stage = parser.add_mutually_exclusive_group(required=True)
    stage.add_argument("--preflight", action="store_true")
    stage.add_argument("--execute", action="store_true")
    return parser


def main(arguments: list[str] | None = None) -> int:
    """Validate and execute the authorized single calibration request.

    Parameters
    ----------
    arguments : list[str] or None, optional
        Command-line arguments excluding the executable name.

    Returns
    -------
    int
        Zero for an admitted calibration record; two for safe rejection.

    Raises
    ------
    SystemExit
        If command-line arguments violate the parser contract.
    """

    args = build_parser().parse_args(arguments)
    try:
        manifest = load_document(args.campaign_manifest, "campaign")
        attempt = calibration_attempt(manifest)
        controls = execution_controls(manifest, scheduled_attempts=1)
        upstream = os.environ.get(provider_proxy.UPSTREAM_TOKEN_ENV, "")
        if not upstream:
            raise PilotLauncherError("calibration OpenRouter credential is unavailable")
        if args.preflight:
            print(
                json.dumps(
                    preflight_openrouter_route(manifest, controls, upstream),
                    sort_keys=True,
                )
            )
            return 0
        runtime_image = manifest.get("runtime_image")
        if not isinstance(runtime_image, str) or args.image != runtime_image:
            raise PilotLauncherError("calibration image differs from manifest")
        runtime_profile = manifest.get("runtime_profile_fingerprint")
        if (
            not isinstance(runtime_profile, str)
            or runtime_profile != runtime_profile_fingerprint()
        ):
            raise PilotLauncherError("local Codira profile differs from manifest")
        validate_treatment_protocol(manifest)
        sources = parse_fixture_sources(args.fixture_source)
        tasks, oracles, fixtures = load_pilot_inputs(
            manifest, (attempt.task_id,), sources
        )
        route_preflight = preflight_openrouter_route(manifest, controls, upstream)
        public_route = route_preflight.get("public_route")
        provider_context_length = (
            public_route.get("context_length")
            if isinstance(public_route, dict)
            else None
        )
        if not isinstance(provider_context_length, int):
            raise PilotLauncherError("authenticated route context is unavailable")
        store = CampaignStore(
            args.state_root,
            str(manifest["campaign_id"]),
            {
                "manifest": manifest,
                "image": args.image,
                "runtime": args.runtime,
                "stage": "calibration",
            },
            (attempt,),
        )
        store.initialize()
        if store.validated_records():
            raise PilotLauncherError(
                "calibration already has an immutable terminal record"
            )
        context = PilotExecutionContext(
            tasks,
            oracles,
            fixtures,
            sources,
            args.image,
            args.runtime,
            upstream,
            manifest,
            provider_context_length,
        )
        result, evidence = execute_pilot_attempt(store, attempt, context)
        record = store.store_result(attempt.attempt_id, result, evidence)
    except (ContractError, OSError, PilotLauncherError, ValueError) as error:
        print(f"calibration launcher error: {error}", file=sys.stderr)
        return 2
    print(
        json.dumps(
            {
                "campaign_id": manifest["campaign_id"],
                "configuration_fingerprint": canonical_fingerprint(
                    {
                        "manifest": manifest,
                        "image": args.image,
                        "runtime": args.runtime,
                        "stage": "calibration",
                    }
                ),
                "record_path": str(record),
                "outcome": result["outcome"],
                "failure_class": result["failure_class"],
                "response_request_count": evidence["response_request_count"],
                "max_total_tokens": controls.max_total_tokens,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
