"""Reject incomplete campaign admission and qualify shared tool boundaries.

Parameters
----------
None

Returns
-------
None
    Definitions are consumed by the local MCP or qualification workflow.
"""

from __future__ import annotations

import json
import time
import tomllib
from types import SimpleNamespace
from typing import TYPE_CHECKING, cast
from unittest.mock import MagicMock

import pytest

from scripts.agent_efficiency import readiness
from scripts.agent_efficiency.codex_subscription import write_subscription_config
from scripts.agent_efficiency.phase0 import build_isolated_codex_config
from scripts.agent_efficiency.runner import capture_workspace_patch, snapshot_workspace

if TYPE_CHECKING:
    from pathlib import Path

    from scripts.launch_agent_efficiency_pilot import PilotLaunch


@pytest.mark.parametrize("proxy", [False, True])
@pytest.mark.parametrize("exit_code", [0, 1])
def test_native_shell_probe_matches_transport_and_retains_failures(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    proxy: bool,
    exit_code: int,
) -> None:
    """Match container execution policy and preserve rejected shell evidence.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Disposable evidence directory.
    monkeypatch : pytest.MonkeyPatch
        Credential-free native process and RPC fixtures.
    proxy : bool
        Whether the measured transport uses the outer container sandbox.
    exit_code : int
        Successful or rejected native shell response.

    Returns
    -------
    None
        Failed shell checks remain blocking for both transport policies.
    """
    from scripts.agent_efficiency import native_tool_qualification as native

    process = MagicMock()
    process.__enter__.return_value = process
    monkeypatch.setattr(
        "scripts.agent_efficiency.native_tool_qualification.subprocess.Popen",
        MagicMock(return_value=process),
    )
    shell = {
        "exitCode": exit_code,
        "stdout": json.dumps({"shell_git_uv_cli": "passed"}),
        "stderr": "nested namespace denied" if exit_code else "",
    }
    rpc = MagicMock(side_effect=[{}, {"config": {"approval_policy": "never"}}, shell])
    monkeypatch.setattr(native, "_request", rpc)
    diagnostics = tmp_path / "native.stderr"
    if exit_code:
        with pytest.raises(ValueError, match="native tool shell contract failed"):
            native.probe_native_client(
                ("isolated-native",),
                require_mcp=False,
                diagnostic_path=diagnostics,
                openrouter_proxy=proxy,
            )
    else:
        result = native.probe_native_client(
            ("isolated-native",),
            require_mcp=False,
            diagnostic_path=diagnostics,
            openrouter_proxy=proxy,
        )
        assert result["shell_policy"] == ("dangerFullAccess" if proxy else "configured")
    arguments = rpc.call_args_list[2].args[3]
    assert arguments.get("sandboxPolicy") == (
        {"type": "dangerFullAccess"} if proxy else None
    )
    assert json.loads(diagnostics.with_suffix(".shell.json").read_text()) == shell


def _admission(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[PilotLaunch, dict[str, object], dict[str, object]]:
    """Build non-model admission evidence with a stable dependency identity.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Disposable execution root.
    monkeypatch : pytest.MonkeyPatch
        Controlled identity provider.

    Returns
    -------
    tuple
        Launch, frozen identity and required evidence map.
    """
    launch = cast("PilotLaunch", SimpleNamespace(execution_root=tmp_path))
    identity: dict[str, object] = {
        "harness": "qualified",
        "environment": {"PYTHONPATH": "frozen"},
    }
    monkeypatch.setattr(readiness, "readiness_identity", lambda _: identity.copy())
    checks: dict[str, object] = {}
    for name in readiness.REQUIRED_CHECKS:
        evidence = tmp_path / name / "receipt.json"
        evidence.parent.mkdir()
        readiness.write_evidence(evidence, {"status": "passed"})
        checks[name] = readiness.evidence_check(tmp_path, evidence.parent)
    return launch, identity, checks


@pytest.mark.parametrize(
    "fault", ["missing", "failed", "empty", "stale", "future", "changed"]
)
def test_readiness_rejects_invalid_admission(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    """Never publish readiness with an incomplete or invalid required check.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Disposable evidence root.
    monkeypatch : pytest.MonkeyPatch
        Controlled dependency identity.
    fault : str
        Independent admission violation.

    Returns
    -------
    None
        Rejection leaves no ready receipt.
    """
    launch, identity, checks = _admission(tmp_path, monkeypatch)
    authenticated_at = time.time()
    if fault == "missing":
        checks.pop("native-tool-dispatch")
    elif fault == "failed":
        checks["native-tool-dispatch"] = {"status": "failed"}
    elif fault == "empty":
        checks["native-tool-dispatch"] = {"status": "passed", "evidence": {}}
    elif fault == "stale":
        authenticated_at -= readiness.MAX_READINESS_AGE_SECONDS + 1
    elif fault == "future":
        authenticated_at += 60
    else:
        (tmp_path / "native-tool-dispatch/receipt.json").write_text("altered")
    with pytest.raises(ValueError):
        readiness.publish_readiness(
            launch, identity, checks, authenticated_at=authenticated_at
        )
    assert not (tmp_path / "readiness-receipt.json").exists()


@pytest.mark.parametrize("fault", ["evidence", "identity", "receipt", "age"])
def test_launch_rechecks_readiness(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    """Reject changes occurring after preparation, including authentication expiry.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Disposable execution root.
    monkeypatch : pytest.MonkeyPatch
        Controlled identity and clock.
    fault : str
        Post-preparation change.

    Returns
    -------
    None
        An unchanged receipt passes and each changed boundary rejects.
    """
    launch, identity, checks = _admission(tmp_path, monkeypatch)
    path = readiness.publish_readiness(
        launch, identity, checks, authenticated_at=time.time()
    )
    assert readiness.verify_readiness(launch) == path
    if fault == "evidence":
        (tmp_path / "repository-gate/receipt.json").write_text("altered")
    elif fault == "identity":
        identity["harness"] = "changed"
    elif fault == "receipt":
        document = json.loads(path.read_text())
        document["status"] = "failed"
        path.write_text(json.dumps(document))
    else:
        current = time.time()
        monkeypatch.setattr(
            "scripts.agent_efficiency.readiness.time.time", lambda: current + 901
        )
    with pytest.raises(ValueError):
        readiness.verify_readiness(launch)


def test_both_native_config_builders_preapprove_codira(tmp_path: Path) -> None:
    """Require unattended MCP policy on native and proxy configurations.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Disposable native state root.

    Returns
    -------
    None
        Both generated server configurations explicitly approve tools.
    """
    native = write_subscription_config(
        tmp_path / "native", "gpt-6-luna", "high", "/opt/codira/codira-mcp-benchmark"
    ).read_text()
    proxy = build_isolated_codex_config(
        codira_root="/workspace", mcp_command="/opt/codira/codira-mcp-benchmark"
    )
    for configuration in (native, proxy):
        assert (
            tomllib.loads(configuration)["mcp_servers"]["codira"][
                "default_tools_approval_mode"
            ]
            == "approve"
        )


def test_capture_ignores_dependencies_and_includes_new_tests(tmp_path: Path) -> None:
    """Apply one snapshot policy while retaining source symlink rejection.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Disposable workspace and snapshot roots.

    Returns
    -------
    None
        Dependency links are ignored and actual source/test edits are captured.
    """
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "app.py").write_text("value = 1\n")
    dependencies = workspace / "node_modules/.bin"
    dependencies.mkdir(parents=True)
    (dependencies / "tool").symlink_to("../tool/bin.js")
    baseline = tmp_path / "before"
    snapshot_workspace(workspace, baseline)
    assert not (baseline / "node_modules").exists()
    (workspace / "app.py").write_text("value = 2\n")
    (workspace / "test_new.py").write_text("assert value == 2\n")
    artifact = workspace / ".benchmark/fix.patch"
    artifact.parent.mkdir()
    capture_workspace_patch(baseline, workspace, artifact)
    patch = artifact.read_text()
    assert "+value = 2" in patch and "test_new.py" in patch
    assert "node_modules" not in patch
    (workspace / "escape.py").symlink_to(tmp_path / "outside.py")
    with pytest.raises(ValueError, match="symlinks"):
        capture_workspace_patch(baseline, workspace, artifact)


@pytest.mark.parametrize("failure", [None, "image", "native", "identity"])
def test_preparation_runs_each_boundary_once_and_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str | None
) -> None:
    """Assemble readiness in one pass and stop at a rejected boundary.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Disposable execution identity.
    monkeypatch : pytest.MonkeyPatch
        Non-model qualification implementations.
    failure : str or None
        Injected checker failure or concurrent input change.

    Returns
    -------
    None
        Only a complete stable pass produces the launch receipt.
    """
    from scripts.agent_efficiency import (
        panel_patch_calibration,
        preparation,
        runtime_qualification,
    )

    launch = cast(
        "PilotLaunch",
        SimpleNamespace(
            execution_root=tmp_path,
            runtime="podman",
            fixture_sources={},
            manifest={
                "stage": "representative-campaign",
                "runtime_image": "frozen",
                "provider": {"name": "codex-subscription"},
            },
        ),
    )
    identity: dict[str, object] = {"harness": "frozen"}
    monkeypatch.setattr(readiness, "readiness_identity", lambda _: identity.copy())
    monkeypatch.setattr(preparation, "readiness_identity", lambda _: identity.copy())
    calls: list[str] = []

    def qualify(name: str, directory: Path) -> dict[str, object]:
        """Write one terminal qualification result without external processes.

        Parameters
        ----------
        name : str
            Checker identity.
        directory : pathlib.Path
            Evidence destination.

        Returns
        -------
        dict
            Explicit passed or failed verdict.
        """
        calls.append(name)
        directory.mkdir(parents=True)
        readiness.write_evidence(directory / "evidence.json", {"status": "passed"})
        if failure == name:
            return {"status": "failed"}
        if failure == "identity" and name == "auth":
            identity["harness"] = "changed"
        return {"status": "passed"}

    monkeypatch.setattr(
        preparation, "qualify_host_context", lambda _: {"status": "passed"}
    )
    monkeypatch.setattr(
        runtime_qualification,
        "qualify_image",
        lambda _runtime, _image, directory: qualify("image", directory),
    )
    monkeypatch.setattr(
        preparation,
        "_tool_dispatch",
        lambda _launch, directory, **options: qualify(
            "model" if options.get("model_canary") else "native", directory
        ),
    )
    monkeypatch.setattr(
        runtime_qualification,
        "qualify_panel_freshness",
        lambda _runtime, _image, directory: qualify("freshness", directory),
    )
    monkeypatch.setattr(
        preparation,
        "_command_evidence",
        lambda _command, directory: qualify("rubric", directory),
    )
    monkeypatch.setattr(
        panel_patch_calibration,
        "qualify_patch_cases",
        lambda _runtime, _image, directory, _sources: qualify("patch", directory),
    )
    monkeypatch.setattr(
        preparation, "_repository_gate", lambda directory: qualify("gate", directory)
    )
    monkeypatch.setattr(
        preparation,
        "_authenticated_check",
        lambda _launch, directory: qualify(
            "auth-after"
            if directory.name == "authenticated-route-after-canary"
            else "auth",
            directory,
        ),
    )
    if failure is None:
        path = preparation.prepare_readiness(launch)
        assert readiness.verify_readiness(launch) == path
    else:
        with pytest.raises(ValueError):
            preparation.prepare_readiness(launch)
        assert not (tmp_path / "readiness-receipt.json").exists()
    assert len(calls) == len(set(calls))
    if failure == "image":
        assert calls == ["image"]
    elif failure == "native":
        assert calls == ["image", "native"]
    else:
        assert calls == [
            "image",
            "native",
            "freshness",
            "rubric",
            "patch",
            "gate",
            "auth",
            *(["model", "auth-after"] if failure is None else []),
        ]


def test_composite_patch_preserves_behavior_and_semantic_pending(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Feed captured patch text into the complete oracle without claiming semantics.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Disposable artifact root.
    monkeypatch : pytest.MonkeyPatch
        Deterministic protected behavior result.

    Returns
    -------
    None
        Behavioral evidence and pending quality survive the full composite.
    """
    from scripts.agent_efficiency import oracles

    artifact = tmp_path / "fix.patch"
    artifact.write_text("--- a/app.py\n+++ b/app.py\n@@ -1 +1 @@\n-old\n+new\n")
    monkeypatch.setattr(
        oracles, "_patch_check", lambda *args, **kwargs: (True, ("patch_tests:passed",))
    )
    definition = {
        "all_of": [
            {"patch_applies_and_tests_pass": {}},
            {
                "quality_rubric": {
                    "criteria": [
                        {
                            "id": "substance",
                            "dimension": "correctness",
                            "semantic": True,
                        },
                    ]
                }
            },
        ]
    }
    outcome = oracles.evaluate_oracle(
        definition,
        result_root=tmp_path,
        protected_root=tmp_path,
        result_path="fix.patch",
        result_format="workspace-diff",
    )
    assert not outcome.passed
    assert "all_of[0].patch_tests:passed" in outcome.checks
    assert "all_of[1].quality[substance]:review_required" in outcome.checks


@pytest.mark.parametrize(
    "message", ["requires approval", "source changed; reindex required"]
)
def test_mcp_denial_is_distinct_from_expected_tool_rejection(message: str) -> None:
    """Reject denied MCP execution while retaining native usage accounting.

    Parameters
    ----------
    message : str
        Public native tool error, including an expected freshness rejection.

    Returns
    -------
    None
        Optional use cannot turn an attempted denial into success.
    """
    from scripts.agent_efficiency.campaign_state import ScheduledAttempt
    from scripts.agent_efficiency.runner import (
        ContainerExecution,
        result_from_execution,
    )

    events = [
        {"type": "thread.started"},
        {"type": "turn.started"},
        {
            "type": "item.completed",
            "item": {
                "type": "mcp_tool_call",
                "status": "failed",
                "error": {"message": message},
            },
        },
        {"type": "item.completed", "item": {"type": "command_execution"}},
        {
            "type": "turn.completed",
            "usage": {
                "input_tokens": 10,
                "cached_input_tokens": 0,
                "output_tokens": 3,
                "reasoning_output_tokens": 0,
            },
        },
    ]
    attempt = ScheduledAttempt("panel-x", 1, "codira-mcp", "attempt-001", "pair-001")
    result, evidence = result_from_execution(
        "campaign",
        attempt,
        ContainerExecution(0, "\n".join(json.dumps(item) for item in events), "", 1.0),
        require_mcp=False,
    )
    denied = message == "requires approval"
    assert result["outcome"] == ("infrastructure_failure" if denied else "success")
    assert result["failure_class"] == ("mcp_approval_denied" if denied else None)
    trajectory = cast("dict[str, object]", evidence["trajectory"])
    assert trajectory["mcp_failed_call_count"] == 1
    assert trajectory["mcp_denied_call_count"] == int(denied)
    assert result["usage_complete"] is True
    assert evidence["returncode"] == 0


@pytest.mark.parametrize(
    "failure",
    [
        None,
        "denied",
        "missing-marker",
        "empty-response",
        "missing-usage",
        "provider-error",
        "missing-provider-usage",
        "tool-error-then-success",
    ],
)
@pytest.mark.parametrize(
    ("route", "canary_tokens"),
    [("codex-subscription", None), ("openrouter", None), ("openrouter", 200000)],
)
@pytest.mark.parametrize("canary_budget", [None, 0.25])
def test_model_canary_requires_real_completed_tool_events(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure: str | None,
    route: str,
    canary_budget: float | None,
    canary_tokens: int | None,
) -> None:
    """Require native model tool evidence and retain failures without a retry.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Disposable canary state and fixture roots.
    monkeypatch : pytest.MonkeyPatch
        Recorded native executor and local tunnel fixture.
    failure : str or None
        Independent native completion failure.
    route : str
        Exclusive subscription or OpenRouter credential boundary.
    canary_budget : float or None
        Separate OpenRouter allowance or historical campaign guards.
    canary_tokens : int or None
        Separate OpenRouter token guard or the inherited campaign guard.

    Returns
    -------
    None
        Readiness requires successful tool calls, usage and the shell marker.
    """
    from scripts.agent_efficiency import model_tool_qualification as qualification
    from scripts.agent_efficiency.runner import (
        ContainerAttemptRequest,
        ContainerExecution,
    )

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / ".benchmark").mkdir()
    auth = tmp_path / "public-managed-login.json"
    auth.write_text('{"canary":"public"}')
    launch = cast(
        "PilotLaunch",
        SimpleNamespace(
            subscription_auth_source=auth if route == "codex-subscription" else None,
            subscription_codex=None,
            canary_key="codira-tests" if canary_budget is not None else "campaign",
            canary_budget_usd=canary_budget,
            canary_max_total_tokens=canary_tokens,
            runtime="podman",
            manifest={
                "campaign_id": "qualification",
                "runtime_image": "frozen",
                "stage": "representative-campaign",
                "provider": {
                    "name": route,
                    "model": "gpt-6-luna",
                    "reasoning_effort": "high",
                    "max_prompt_usd_per_million": 0.25,
                    "max_completion_usd_per_million": 0.75,
                },
                "budgets": {
                    "timeout_seconds": 900,
                    "max_total_tokens": 1000000,
                    "max_output_tokens": 32000,
                },
                "accounting": {
                    "budget_reservation_mode": "shared-pool",
                    "max_total_tokens_scope": "whole-session",
                    "max_daily_spend_usd": 10,
                    "max_estimated_attempt_spend_usd": 1,
                    "max_estimated_pilot_spend_usd": 10,
                    "max_response_requests_per_attempt": 30,
                },
            },
            plan={
                "attempts": [
                    {
                        "task_id": "panel-x",
                        "repetition": 1,
                        "assistance_mode": "codira-mcp",
                        "attempt_id": f"attempt-{index}",
                        "pair_id": f"pair-{index}",
                    }
                    for index in range(48)
                ]
            },
        ),
    )
    calls = []
    from scripts import run_agent_efficiency_phase6_pilot as pilot
    from scripts.agent_efficiency import provider_proxy

    proxy_settings: list[provider_proxy.ProxySettings] = []
    preflight_manifests = []
    create_server = provider_proxy.create_unix_server

    def create_proxy(
        settings: provider_proxy.ProxySettings, socket_path: str
    ) -> object:
        """Capture the real local proxy settings without exposing credentials.

        Parameters
        ----------
        settings : ProxySettings
            Frozen controls and private response root.
        socket_path : str
            Short local capability socket.

        Returns
        -------
        object
            Actual unstarted local proxy server.
        """
        proxy_settings.append(settings)
        return create_server(settings, socket_path)

    monkeypatch.setenv("OPENROUTER_API_KEY", "public-test-key")
    monkeypatch.setattr(provider_proxy, "create_unix_server", create_proxy)

    def preflight(manifest: dict[str, object], *_: object) -> dict[str, object]:
        """Record derived canary controls without authenticating.

        Parameters
        ----------
        manifest : dict[str, object]
            Campaign or separately bounded canary manifest.
        *_ : object
            Unused execution controls and public fake credential.

        Returns
        -------
        dict[str, object]
            Public route context fixture.
        """
        preflight_manifests.append(manifest)
        return {"public_route": {"context_length": 1000000}}

    monkeypatch.setattr(
        pilot,
        "preflight_openrouter_route",
        preflight,
    )
    monkeypatch.setattr(
        pilot,
        "codex_model_base_instructions",
        lambda *_: "Public qualification instructions",
    )

    def execute(request: ContainerAttemptRequest) -> ContainerExecution:
        """Replay native events while verifying exclusive subscription binding.

        Parameters
        ----------
        request : ContainerAttemptRequest
            Real qualification request assembled by the shared runner.

        Returns
        -------
        ContainerExecution
            Captured public native fixture events.
        """
        calls.append(request)
        assert request.subscription_auth == (
            auth if route == "codex-subscription" else None
        )
        assert request.provider_transport == (
            "codex-subscription"
            if route == "codex-subscription"
            else "openrouter-proxy"
        )
        assert request.timeout_seconds == 120
        assert (request.proxy_client_token is None) == (route == "codex-subscription")
        if route == "openrouter":
            settings = proxy_settings[0]
            assert settings.constraints.expected_model == "gpt-6-luna"
            assert settings.max_response_requests == 30
            assert settings.max_total_tokens == (
                canary_tokens if canary_tokens is not None else 1000000
            )
            if canary_tokens == 200000 and canary_budget == 0.25:
                assert settings.local_token_cap_reason(42383) is None
            assert settings.max_attempt_spend_usd == (
                canary_budget if canary_budget is not None else 1
            )
            settings.record_response(
                429 if failure == "provider-error" else 200,
                [],
                body=json.dumps(
                    {
                        "output": [
                            {"type": "function_call", "name": tool, "arguments": "{}"}
                            for tool in ("index_status", "context_for_task")
                        ],
                        "usage": {}
                        if failure == "missing-provider-usage"
                        else {
                            "input_tokens": 10,
                            "output_tokens": 3,
                            "total_tokens": 13,
                        },
                    }
                ).encode(),
            )
        if failure != "missing-marker":
            (workspace / ".benchmark/model-canary.txt").write_text("ready")
        events: list[dict[str, object]] = [
            {"type": "thread.started"},
            {"type": "turn.started"},
        ]
        for tool in ("index_status", "context_for_task"):
            events.append(
                {
                    "type": "item.started",
                    "item": {
                        "type": "mcp_tool_call",
                        "server": "codira",
                        "tool": tool,
                        "arguments": {},
                    },
                }
            )
            if failure == "tool-error-then-success":
                events.append(
                    {
                        "type": "item.completed",
                        "item": {"type": "mcp_tool_call", "status": "failed"},
                    }
                )
            events.append(
                {
                    "type": "item.completed",
                    "item": {
                        "type": "mcp_tool_call",
                        "tool": tool,
                        "server": "codira",
                        "status": "failed" if failure == "denied" else "completed",
                        "error": {"message": "requires approval"}
                        if failure == "denied"
                        else None,
                        "result": {
                            "content": []
                            if failure == "empty-response"
                            else [{"type": "text", "text": "public canary evidence"}]
                        },
                    },
                }
            )
        events.append({"type": "item.completed", "item": {"type": "command_execution"}})
        events.append(
            {
                "type": "turn.completed",
                "usage": {}
                if failure in {"missing-usage", "missing-provider-usage"}
                else {
                    "input_tokens": 10,
                    "cached_input_tokens": 0,
                    "output_tokens": 3,
                    "reasoning_output_tokens": 0,
                },
            }
        )
        return ContainerExecution(
            1 if failure == "provider-error" else 0,
            "\n".join(json.dumps(event) for event in events),
            "public diagnostic",
            1.0,
        )

    monkeypatch.setattr(qualification, "execute_container_attempt", execute)
    monkeypatch.setattr(pilot, "execute_container_attempt", execute)
    monkeypatch.setattr(
        qualification,
        "SubscriptionTunnel",
        lambda _: SimpleNamespace(
            serve_forever=lambda: None,
            shutdown=lambda: None,
            server_close=lambda: None,
        ),
    )
    directory = tmp_path / "model-check"
    if failure is None:
        qualification.qualify_model_tools(launch, workspace, directory)
        assert (
            json.loads((directory / "receipt.json").read_text())["status"] == "passed"
        )
    else:
        with pytest.raises(ValueError):
            qualification.qualify_model_tools(launch, workspace, directory)
        assert not (directory / "receipt.json").exists()
    assert len(calls) == 1
    assert (directory / "started.json").is_file()
    assert (directory / "result.json").is_file() or (
        directory / "provider-admission.json"
    ).is_file()
    assert (directory / "native.events.jsonl").is_file()
    assert (directory / "native.stderr").read_text() == "public diagnostic"
    assert (directory / "native.exit").read_text().strip() == (
        "1" if failure == "provider-error" else "0"
    )
    if route == "openrouter":
        campaign_budgets = cast("dict[str, int]", launch.manifest["budgets"])
        derived_budgets = cast("dict[str, int]", preflight_manifests[0]["budgets"])
        assert campaign_budgets["max_total_tokens"] == 1000000
        assert derived_budgets["max_total_tokens"] == (
            canary_tokens if canary_tokens is not None else 1000000
        )
        campaign_accounting = cast("dict[str, object]", launch.manifest["accounting"])
        assert campaign_accounting["max_estimated_pilot_spend_usd"] == 10
        canary_accounting = cast(
            "dict[str, object]", preflight_manifests[0]["accounting"]
        )
        assert canary_accounting["max_estimated_pilot_spend_usd"] == (
            canary_budget if canary_budget is not None else 10
        )
        assert (
            directory
            / "attempt-work/readiness-canary/provider-responses/response-001.body"
        ).is_file()
        if failure in {"provider-error", "missing-provider-usage"}:
            assert not (directory / "accounting.json").exists()
            return
        accounting = json.loads((directory / "accounting.json").read_text())
        assert accounting["provider_total_tokens"] == 13
        assert accounting["estimated_cost_usd_at_ceiling"] > 0
        assert accounting["campaign_attempts_consumed"] == 0


def test_openrouter_canary_rejects_changed_bindings_before_authentication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Reject changed source bindings inside the SOPS child before model work.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Disposable prepared receipt root.
    monkeypatch : pytest.MonkeyPatch
        Frozen receipt and changed identity fixtures.

    Returns
    -------
    None
        The credentialed worker stops before any model qualification.
    """
    import sys

    from scripts import launch_agent_efficiency_pilot as launcher
    from scripts.agent_efficiency import model_tool_qualification as qualification

    launch = SimpleNamespace(
        execution_root=tmp_path, manifest={"provider": {"name": "openrouter"}}
    )
    expected = tmp_path / "readiness/factory-inputs/check-result.json"
    expected.parent.mkdir(parents=True)
    expected.write_text(json.dumps({"identity": {"harness": "original"}}))
    monkeypatch.setattr(launcher, "load_prepared_inputs", lambda _: launch)
    monkeypatch.setattr(launcher, "verify_prepared_launch", lambda _: None)
    monkeypatch.setattr(
        readiness, "readiness_identity", lambda _: {"harness": "changed"}
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "worker",
            "--execution-root",
            str(tmp_path),
            "--workspace",
            str(tmp_path / "workspace"),
            "--directory",
            str(tmp_path / "canary"),
        ],
    )
    with pytest.raises(ValueError, match="inputs or provider changed"):
        qualification.main()
    assert not (tmp_path / "canary").exists()


@pytest.mark.parametrize("key", ["campaign", "codira-tests"])
def test_openrouter_dispatch_scopes_credentials_to_canary_child(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, key: str
) -> None:
    """Require the SOPS child rather than running provider inference in parent.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Disposable tool evidence root.
    monkeypatch : pytest.MonkeyPatch
        Offline index execution and child command recorder.
    key : str
        Registered canary credential alias.

    Returns
    -------
    None
        Only the scoped child receives the model qualification command.
    """
    from scripts.agent_efficiency import preparation
    from scripts.agent_efficiency.runner import ContainerExecution
    from scripts.launch_agent_efficiency_pilot import CANARY_SOPS_ENVIRONMENTS

    launch = cast(
        "PilotLaunch",
        SimpleNamespace(
            runtime="podman",
            execution_root=tmp_path,
            canary_key=key,
            manifest={"runtime_image": "frozen", "provider": {"name": "openrouter"}},
        ),
    )
    monkeypatch.setattr(
        preparation,
        "execute_index_preparation",
        lambda _: ContainerExecution(0, "indexed", "", 0.1),
    )
    commands = []
    monkeypatch.setattr(
        preparation,
        "_command_evidence",
        lambda command, directory, **options: commands.append(
            (command, directory, options)
        ),
    )
    preparation._tool_dispatch(launch, tmp_path / "dispatch", model_canary=True)
    assert len(commands) == 1
    command, directory, options = commands[0]
    assert command[:3] == ["sops", "exec-env", CANARY_SOPS_ENVIRONMENTS[key]]
    assert "scripts.agent_efficiency.model_tool_qualification" in command[3]
    assert "--execution-root" in command[3]
    assert directory.name == "scoped-child"
    assert options == {"timeout": 300}


@pytest.mark.parametrize(
    ("provider", "key", "budget", "accepted"),
    [
        ("openrouter", "campaign", None, True),
        ("openrouter", "codira-tests", 0.25, True),
        ("openrouter", "codira-tests", None, False),
        ("openrouter", "unregistered", 0.25, False),
        ("openrouter", "campaign", float("nan"), False),
        ("openrouter", "campaign", float("inf"), False),
        ("openrouter", "campaign", 0, False),
        ("codex-subscription", "codira-tests", 0.25, False),
        ("codex-subscription", "campaign", 0.25, False),
    ],
)
def test_canary_rejects_crossed_credentials_and_invalid_allowances(
    provider: str, key: str, budget: float | None, accepted: bool
) -> None:
    """Admit only registered, bounded and provider-compatible canary controls.

    Parameters
    ----------
    provider : str
        Candidate provider.
    key : str
        Registered environment alias.
    budget : float or None
        Separate preparation-only allowance.
    accepted : bool
        Expected admission decision.

    Returns
    -------
    None
        Rejections happen without authentication or inference.
    """
    from scripts.launch_agent_efficiency_pilot import (
        PilotLaunchError,
        _validate_canary_inputs,
    )

    manifest: dict[str, object] = {"provider": {"name": provider}}
    if accepted:
        _validate_canary_inputs(manifest, key, budget)
    else:
        with pytest.raises(PilotLaunchError):
            _validate_canary_inputs(manifest, key, budget)


@pytest.mark.parametrize(
    ("provider", "tokens", "accepted"),
    [
        ("openrouter", 200000, True),
        ("openrouter", 64000, True),
        ("openrouter", 2500000, True),
        ("openrouter", 2500001, False),
        ("openrouter", 63999, False),
        ("openrouter", 0, False),
        ("openrouter", True, False),
        ("codex-subscription", 200000, False),
    ],
)
def test_canary_token_guard_rejects_invalid_or_crossed_limits(
    provider: str, tokens: int, accepted: bool
) -> None:
    """Bound preparation tokens without relaxing main or native controls.

    Parameters
    ----------
    provider : str
        Candidate provider route.
    tokens : int
        Candidate separate guard, including invalid boolean values.
    accepted : bool
        Expected admission decision.

    Returns
    -------
    None
        Invalid or crossed controls fail before model work.
    """
    from scripts.launch_agent_efficiency_pilot import (
        PilotLaunchError,
        _validate_canary_inputs,
    )

    manifest: dict[str, object] = {
        "provider": {"name": provider},
        "budgets": {"max_output_tokens": 64000, "max_total_tokens": 2500000},
    }
    if accepted:
        _validate_canary_inputs(manifest, "campaign", None, tokens)
    else:
        with pytest.raises(PilotLaunchError):
            _validate_canary_inputs(manifest, "campaign", None, tokens)


def test_tests_key_canary_does_not_change_main_campaign_authentication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Keep the tests key out of the main runner and bind it in the receipt.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Disposable factory and execution paths.
    monkeypatch : pytest.MonkeyPatch
        Replaces the runner argv without credential or runtime access.

    Returns
    -------
    None
        Preparation selection does not grant main execution the tests key.
    """
    from scripts import launch_agent_efficiency_pilot as launcher

    campaign = tmp_path / "campaign"
    campaign.mkdir()
    for name in ("campaign.json", "launch-plan.json"):
        (campaign / name).write_text("{}")
    launch = launcher.PilotLaunch(
        campaign,
        tmp_path / "execution",
        {},
        "podman",
        261004,
        {"campaign_id": "test-key-boundary"},
        {},
        canary_key="codira-tests",
        canary_budget_usd=0.25,
        canary_max_total_tokens=200000,
    )
    monkeypatch.setattr(launcher, "runner_argv", lambda _: ["python", "main-runner"])
    _, command = launcher.tmux_command(launch)
    assert launcher.SOPS_ENVIRONMENT in command
    assert launcher.CANARY_SOPS_ENVIRONMENTS["codira-tests"] not in command
    receipt = launcher._receipt(launch)
    assert receipt["canary_key"] == "codira-tests"
    assert receipt["canary_budget_usd"] == 0.25
    assert receipt["canary_max_total_tokens"] == 200000


@pytest.mark.parametrize("exit_status", ["0", "2"])
def test_repository_gate_reports_before_success_cleanup_and_retains_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    exit_status: str,
) -> None:
    """Verify gate timing, location, reporting and failure evidence retention.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Isolated repository and evidence root.
    monkeypatch : pytest.MonkeyPatch
        Replace the terminal and clock with deterministic local boundaries.
    capsys : pytest.CaptureFixture[str]
        Capture the published terminal result before cleanup.
    exit_status : str
        Successful or failed terminal result.

    Returns
    -------
    None
        Success is cleaned only after reporting; failures retain their logs.
    """
    from scripts.agent_efficiency import preparation

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "scripts.agent_efficiency.preparation.time.time_ns", lambda: 123
    )
    sleeps: list[int] = []
    monkeypatch.setattr(
        "scripts.agent_efficiency.preparation.time.sleep", sleeps.append
    )
    monkeypatch.setattr(preparation, "_command_evidence", MagicMock())
    gate_root = tmp_path / ".artifacts/validation/repo-gates/ae-ready-123"
    directory = tmp_path / "readiness/repository-gate"

    def terminal(command: list[str], *, check: bool, capture_output: bool) -> None:
        """Complete the fake terminal or verify cleanup follows reporting.

        Parameters
        ----------
        command : list[str]
            Requested terminal action.
        check : bool
            Required subprocess success enforcement.
        capture_output : bool
            Required bounded subprocess output.

        Returns
        -------
        None
            Writes a terminal result or checks report-before-cleanup ordering.
        """
        assert check and capture_output
        if "new-session" in command:
            (gate_root / "validation.log").write_text("validation passed\n")
            (gate_root / "validation.exit").write_text(exit_status + "\n")
        else:
            assert "kill-session" in command
            assert (directory / "gate-result.json").is_file()
            assert '"repository_gate"' in capsys.readouterr().out

    monkeypatch.setattr("scripts.agent_efficiency.preparation.subprocess.run", terminal)
    if exit_status == "0":
        preparation._repository_gate(directory)
    else:
        with pytest.raises(ValueError, match="full repository gate failed"):
            preparation._repository_gate(directory)
    receipt = json.loads((directory / "gate-result.json").read_text())
    assert sleeps == [240]
    assert receipt["exit_status"] == exit_status
    assert receipt["log_sha256"]
    assert receipt["log_tail"] == ["validation passed"]
    assert gate_root.exists() is (exit_status != "0")
