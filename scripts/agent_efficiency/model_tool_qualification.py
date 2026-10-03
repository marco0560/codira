"""Require a genuine unattended model-requested MCP call before readiness.

Parameters
----------
None

Returns
-------
None
    Qualification retains provider and native evidence before admission.
"""
# ruff: noqa: EM101, EM102, TRY003

from __future__ import annotations

import argparse
import json
import os
import tempfile
import threading
from pathlib import Path
from typing import TYPE_CHECKING, cast

from scripts.agent_efficiency import phase0
from scripts.agent_efficiency.campaign_state import CampaignStore, ScheduledAttempt
from scripts.agent_efficiency.codex_subscription import (
    SubscriptionTunnel,
    write_subscription_config,
)
from scripts.agent_efficiency.readiness import write_evidence
from scripts.agent_efficiency.runner import (
    PROJECT_TEMP_ROOT,
    ContainerAttemptRequest,
    execute_container_attempt,
    result_from_execution,
    write_proxy_relay,
)

if TYPE_CHECKING:
    from scripts.agent_efficiency.runner import ContainerExecution
    from scripts.launch_agent_efficiency_pilot import PilotLaunch

CANARY_PROMPT = (
    "Readiness qualification only. Call the codira MCP index_status tool and "
    "context_for_task with query 'Qualification probe helper' and limit 1. "
    "Require successful nonempty results from both tools. Then use the shell "
    "to write exactly ready to .benchmark/model-canary.txt. Do not modify source, "
    "install dependencies, delegate, or request approval. Stop immediately after "
    "these checks and report readiness. If any tool fails, stop and report failure."
)


def _openrouter_canary(
    launch: PilotLaunch, workspace: Path, directory: Path
) -> ContainerExecution:
    """Use the campaign proxy with SOPS-scoped credentials and durable bodies.

    Parameters
    ----------
    launch : PilotLaunch
        Validated OpenRouter campaign, without subscription bindings.
    workspace, directory : pathlib.Path
        Prepared tool workspace and fresh durable evidence root.

    Returns
    -------
    ContainerExecution
        Captured model process, also retained before accounting admission.

    Raises
    ------
    ValueError
        If credentials, route, response evidence or accounting are incomplete.
    """
    from scripts.run_agent_efficiency_phase6_pilot import (
        PilotExecutionContext,
        _execute_provider_attempt,
        execution_controls,
        preflight_openrouter_route,
    )

    token = os.environ.get("OPENROUTER_API_KEY")
    if (
        not token
        or launch.subscription_auth_source is not None
        or launch.subscription_codex is not None
    ):
        raise ValueError("OpenRouter qualification requires exclusive scoped API auth")
    schedule = tuple(
        ScheduledAttempt(
            cast("str", record["task_id"]),
            cast("int", record["repetition"]),
            cast("str", record["assistance_mode"]),
            cast("str", record["attempt_id"]),
            cast("str", record["pair_id"]),
        )
        for record in cast("list[dict[str, object]]", launch.plan["attempts"])
    )
    controls = execution_controls(
        launch.manifest, scheduled_attempts=len(schedule), full_campaign=True
    )
    route = preflight_openrouter_route(launch.manifest, controls, token)
    write_evidence(directory / "authenticated-route.json", route)
    public_route = cast("dict[str, object]", route["public_route"])
    context_length = cast("int", public_route["context_length"])
    manifest = dict(launch.manifest)
    manifest["budgets"] = {
        **cast("dict[str, int]", manifest["budgets"]),
        "timeout_seconds": min(120, controls.timeout_seconds),
    }
    context = PilotExecutionContext(
        {},
        {},
        {},
        {},
        str(manifest["runtime_image"]),
        launch.runtime,
        token,
        manifest,
        context_length,
        True,
    )
    attempt = ScheduledAttempt(
        "readiness", 1, "codira-mcp", "readiness-canary", "readiness-pair"
    )
    store = CampaignStore(directory, str(manifest["campaign_id"]), {}, schedule)
    execution, responses, requests, _, _ = _execute_provider_attempt(
        context,
        store,
        attempt,
        CANARY_PROMPT,
        (
            controls.max_total_tokens,
            controls.max_attempt_spend,
            controls.max_pilot_spend,
        ),
        workspace=workspace,
    )
    # Persist process evidence before rejecting an uncertain or incomplete charge.
    (directory / "native.events.jsonl").write_text(execution.stdout)
    (directory / "native.stderr").write_text(execution.stderr)
    (directory / "native.exit").write_text(str(execution.returncode) + "\n")
    write_evidence(
        directory / "provider-observations.json",
        {"responses": responses, "requests": requests},
    )
    upstream = [
        response for response in responses if response.get("source") == "upstream"
    ]
    if (
        not upstream
        or any(
            response.get("status") != 200
            or not isinstance(response.get("provider_usage"), dict)
            or not response.get("response_sha256")
            or response.get("usage_exceeded_frozen_response_limits")
            for response in upstream
        )
        or any(response.get("source") == "local" for response in responses)
    ):
        write_evidence(
            directory / "provider-admission.json",
            {"status": "failed", "reason": "incomplete_or_failed_accounting"},
        )
        raise ValueError(
            "OpenRouter canary response accounting is incomplete or failed"
        )
    accounting: dict[str, object] = {
        "accounting": "OpenRouter USD",
        "estimated_cost_usd_at_ceiling": sum(
            cast("float", response["estimated_cost_usd_at_ceiling"])
            for response in upstream
        ),
        "provider_total_tokens": sum(
            cast("dict[str, int]", response["provider_usage"])["total_tokens"]
            for response in upstream
        ),
        "campaign_attempts_consumed": 0,
    }
    write_evidence(directory / "accounting.json", accounting)
    if cast(
        "int", accounting["provider_total_tokens"]
    ) > controls.max_total_tokens or cast(
        "float", accounting["estimated_cost_usd_at_ceiling"]
    ) > min(controls.max_attempt_spend, controls.max_pilot_spend):
        raise ValueError("OpenRouter canary exceeded its frozen runaway guards")
    return execution


def main() -> int:
    """Run only the OpenRouter canary inside its approved SOPS child.

    Parameters
    ----------
    None

    Returns
    -------
    int
        Zero only after immutable bindings and complete canary admission.

    Raises
    ------
    ValueError
        If prepared controls changed or live canary qualification fails.
    """
    from scripts.agent_efficiency.readiness import readiness_identity
    from scripts.launch_agent_efficiency_pilot import (
        load_prepared_inputs,
        verify_prepared_launch,
    )

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execution-root", type=Path, required=True)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--directory", type=Path, required=True)
    args = parser.parse_args()
    launch = load_prepared_inputs(args.execution_root)
    verify_prepared_launch(launch)
    expected = json.loads(
        (
            launch.execution_root / "readiness/factory-inputs/check-result.json"
        ).read_text()
    )["identity"]
    provider = cast("dict[str, object]", launch.manifest["provider"])
    if readiness_identity(launch) != expected or provider["name"] != "openrouter":
        raise ValueError("model canary inputs or provider changed")
    qualify_model_tools(launch, args.workspace, args.directory)
    return 0


def qualify_model_tools(launch: PilotLaunch, workspace: Path, directory: Path) -> None:
    """Capture a bounded real model turn through the campaign executor.

    Parameters
    ----------
    launch : PilotLaunch
        Frozen provider model, image and exclusive authentication binding.
    workspace : pathlib.Path
        Indexed canary with the shared CLI profile and writable tool home.
    directory : pathlib.Path
        Fresh durable canary records, events, diagnostics and exit status.

    Returns
    -------
    None
        Only completed successful model-requested calls admit readiness.

    Raises
    ------
    ValueError
        If execution, native usage, tool calls or the shell marker fail.
    """
    provider = cast("dict[str, object]", launch.manifest["provider"])
    budgets = cast("dict[str, int]", launch.manifest["budgets"])
    subscription = provider["name"] == "codex-subscription"
    if provider["name"] not in {"codex-subscription", "openrouter"}:
        raise ValueError("unsupported model qualification route")
    if subscription and launch.subscription_auth_source is None:
        raise ValueError("subscription qualification requires managed login")
    directory.mkdir(parents=True)
    state = directory / "state"
    accounting = (
        "subscription quota; no dollar accounting"
        if subscription
        else "OpenRouter USD; preparation canary separate from campaign attempts"
    )
    if subscription:
        write_subscription_config(
            state,
            str(provider["model"]),
            str(provider["reasoning_effort"]),
            "/opt/codira/codira-mcp-benchmark",
        )
        write_proxy_relay(state)
    write_evidence(
        directory / "started.json",
        {
            "status": "started",
            "model": provider["model"],
            "reasoning_effort": provider["reasoning_effort"],
            "prompt": CANARY_PROMPT,
            "timeout_seconds": min(120, budgets["timeout_seconds"]),
            "accounting": accounting,
        },
    )
    if not subscription:
        execution = _openrouter_canary(launch, workspace, directory)
    else:
        execution = _subscription_canary(launch, workspace, state, budgets)
    _admit_canary(launch, workspace, directory, execution, accounting)


def _subscription_canary(
    launch: PilotLaunch, workspace: Path, state: Path, budgets: dict[str, int]
) -> ContainerExecution:
    """Execute the exclusive native subscription transport.

    Parameters
    ----------
    launch : PilotLaunch
        Frozen image and managed login.
    workspace, state : pathlib.Path
        Prepared source and native configuration.
    budgets : dict[str, int]
        Frozen token and time guards.

    Returns
    -------
    ContainerExecution
        Complete captured native process evidence.
    """
    with tempfile.TemporaryDirectory(
        prefix="ae-model-", dir=PROJECT_TEMP_ROOT
    ) as temporary:
        scratch = Path(temporary)
        socket_path = scratch / "p.sock"
        server = SubscriptionTunnel(str(socket_path))
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            execution = execute_container_attempt(
                ContainerAttemptRequest(
                    launch.runtime,
                    str(launch.manifest["runtime_image"]),
                    workspace,
                    state,
                    CANARY_PROMPT,
                    min(120, budgets["timeout_seconds"]),
                    proxy_socket=socket_path,
                    temporary_root=scratch,
                    provider_transport="codex-subscription",
                    subscription_auth=launch.subscription_auth_source,
                )
            )
        finally:
            server.shutdown()
            server.server_close()
            worker.join(timeout=5)
    return execution


def _admit_canary(
    launch: PilotLaunch,
    workspace: Path,
    directory: Path,
    execution: ContainerExecution,
    accounting: str,
) -> None:
    """Retain model events and require successful unattended tools and usage.

    Parameters
    ----------
    launch : PilotLaunch
        Frozen campaign controls.
    workspace, directory : pathlib.Path
        Tool marker and durable evidence roots.
    execution : ContainerExecution
        Captured model invocation.
    accounting : str
        Exclusive provider accounting description.

    Returns
    -------
    None
        A receipt exists only after complete successful evidence.

    Raises
    ------
    ValueError
        If the model fails the unattended tool contract.
    """
    budgets = cast("dict[str, int]", launch.manifest["budgets"])
    (directory / "native.events.jsonl").write_text(execution.stdout)
    (directory / "native.stderr").write_text(execution.stderr)
    (directory / "native.exit").write_text(str(execution.returncode) + "\n")
    attempt = ScheduledAttempt(
        "readiness", 1, "codira-mcp", "readiness-canary", "readiness-pair"
    )
    result, evidence = result_from_execution(
        str(launch.manifest["campaign_id"]),
        attempt,
        execution,
        max_total_tokens=budgets["max_total_tokens"],
        require_mcp=True,
    )
    write_evidence(directory / "result.json", {"result": result, "evidence": evidence})
    events = phase0.parse_jsonl_events(execution.stdout)
    tools: set[str] = set()
    for event in events:
        item = event.get("item")
        if (
            event.get("type") == "item.completed"
            and isinstance(item, dict)
            and item.get("type") == "mcp_tool_call"
            and item.get("status") == "completed"
            and not item.get("error")
        ):
            tool = item.get("tool")
            response = item.get("result")
            if (
                isinstance(tool, str)
                and item.get("server") == "codira"
                and isinstance(response, dict)
                and response.get("content")
                and response.get("isError") is not True
            ):
                tools.add(tool)
    marker = workspace / ".benchmark/model-canary.txt"
    if (
        result["outcome"] != "success"
        or result["usage_complete"] is not True
        or not {"index_status", "context_for_task"}.issubset(tools)
        or not marker.is_file()
        or marker.read_text() != "ready"
    ):
        raise ValueError("unattended model-requested MCP qualification failed")
    write_evidence(
        directory / "receipt.json",
        {
            "status": "passed",
            "usage": result["usage"],
            "successful_model_requested_tools": sorted(tools),
            "accounting": accounting,
        },
    )


if __name__ == "__main__":
    raise SystemExit(main())
