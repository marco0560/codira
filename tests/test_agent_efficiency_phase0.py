"""Test Phase 0 agent-runner and isolation conformance checks.

Responsibilities
----------------
- Verify prerequisite checks fail closed without external Codex or containers.
- Verify JSONL evidence validation requires MCP, tool, and complete usage data.

Design principles
-----------------
Tests use controlled subprocess results so they never create agent sessions or
pull container images.

Architectural role
------------------
This module belongs to the tooling verification layer for issue #53.
"""

from __future__ import annotations

import json
import subprocess
import tempfile
import tomllib
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from scripts.agent_efficiency import phase0, provider_proxy
from scripts.check_agent_efficiency_environment import build_parser
from scripts.run_agent_efficiency_phase0_escape_probes import blocked, probe_commands
from scripts.run_agent_efficiency_phase0_live_probe import (
    build_codex_argv,
    load_manifest,
    main as run_live_probe,
    prepare_disposable_fixture,
    resolve_executable,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from _pytest.monkeypatch import MonkeyPatch


IMAGE = "example.invalid/codira-benchmark@sha256:" + "a" * 64
REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def _successful_runner(arguments: Sequence[str]) -> subprocess.CompletedProcess[str]:
    """Return deterministic successful prerequisite subprocess results.

    Parameters
    ----------
    arguments : tuple[str, ...]
        Requested command vector.

    Returns
    -------
    subprocess.CompletedProcess[str]
        Successful version, help, or image-inspection result.
    """

    if arguments[-1] == "--version":
        return subprocess.CompletedProcess(arguments, 0, "version 1.2.3\n", "")
    if arguments[-2:] == ("exec", "--help"):
        return subprocess.CompletedProcess(
            arguments,
            0,
            " ".join(phase0.REQUIRED_CODEX_EXEC_FLAGS),
            "",
        )
    if arguments[1:3] == ("image", "inspect"):
        return subprocess.CompletedProcess(arguments, 0, "[]", "")
    raise AssertionError(arguments)


def _complete_events() -> tuple[dict[str, object], ...]:
    """Return one complete synthetic assisted-run event stream.

    Parameters
    ----------
    None

    Returns
    -------
    tuple[dict[str, object], ...]
        JSONL-equivalent events with MCP, command, and usage evidence.
    """

    return (
        {"type": "thread.started"},
        {"type": "turn.started"},
        {"type": "item.completed", "item": {"type": "mcp_tool_call"}},
        {"type": "item.completed", "item": {"type": "command_execution"}},
        {
            "type": "turn.completed",
            "usage": {
                "input_tokens": 10,
                "cached_input_tokens": 2,
                "output_tokens": 3,
                "reasoning_output_tokens": 4,
            },
        },
    )


def test_build_conformance_report_accepts_proven_prerequisites(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    """Accept a host only when every Phase 0 non-billed check succeeds.

    Parameters
    ----------
    monkeypatch : pytest.MonkeyPatch
        Fixture used to provide executable locations.
    tmp_path : pathlib.Path
        Temporary directory for the fresh state root and repository root.

    Returns
    -------
    None
        The test asserts a fully ready report.
    """

    monkeypatch.setattr("shutil.which", lambda value: f"/tools/{value}")
    report = phase0.build_conformance_report(
        request=phase0.HostConformanceRequest(
            codex="codex",
            runtime="docker",
            image=IMAGE,
            state_root=tmp_path / "isolated-state",
            repository_root=tmp_path / "repository",
        ),
        runner=_successful_runner,
    )
    assert report.ready is True
    assert [check.name for check in report.checks] == [
        "codex",
        "codex-exec-help",
        "docker",
        "container-image",
        "isolated-state",
        "isolated-config",
    ]


def test_build_conformance_report_rejects_missing_codex_and_image(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    """Reject a host that lacks Codex and an image available to the runtime.

    Parameters
    ----------
    monkeypatch : pytest.MonkeyPatch
        Fixture used to hide Codex while retaining Docker.
    tmp_path : pathlib.Path
        Temporary directory for isolated paths.

    Returns
    -------
    None
        The test asserts reported prerequisite failures.
    """

    monkeypatch.setattr(
        "shutil.which",
        lambda value: None if value == "codex" else "/tools/docker",
    )

    def unavailable_image(
        arguments: Sequence[str],
    ) -> subprocess.CompletedProcess[str]:
        """Return an unavailable-image result while keeping other calls valid.

        Parameters
        ----------
        arguments : tuple[str, ...]
            Requested command vector.

        Returns
        -------
        subprocess.CompletedProcess[str]
            Controlled subprocess result.
        """

        if arguments[1:3] == ("image", "inspect"):
            return subprocess.CompletedProcess(arguments, 1, "", "missing")
        return _successful_runner(arguments)

    report = phase0.build_conformance_report(
        request=phase0.HostConformanceRequest(
            codex="codex",
            runtime="docker",
            image=IMAGE,
            state_root=tmp_path / "isolated-state",
            repository_root=tmp_path / "repository",
        ),
        runner=unavailable_image,
    )
    assert report.ready is False
    assert report.checks[0].detail == "executable not found on PATH"
    assert report.checks[3].detail == "pinned image is unavailable locally"


def test_isolated_state_rejects_repository_and_reused_state(tmp_path: Path) -> None:
    """Reject state roots that can carry implementation or prior-run context.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository root.

    Returns
    -------
    None
        The test asserts both contamination-prone state roots fail.
    """

    repository = tmp_path / "repository"
    state_inside = repository / "state"
    assert phase0.empty_isolated_state_check(state_inside, repository).passed is False

    reused_state = tmp_path / "reused-state"
    reused_state.mkdir()
    (reused_state / "history.jsonl").write_text("prior state", encoding="utf-8")
    assert phase0.empty_isolated_state_check(reused_state, repository).passed is False


def test_isolated_environment_replaces_inherited_codex_state(tmp_path: Path) -> None:
    """Replace inherited Codex selectors with one fresh state directory.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary fresh state path.

    Returns
    -------
    None
        The test asserts inherited state selectors are absent.
    """

    environment = phase0.isolated_environment(
        {
            "CODEX_HOME": "/host/codex",
            "CODEX_CONFIG": "/host/config.toml",
            "CODEX_PROFILE": "personal",
            "GH_TOKEN": "not-forwarded",
            "OPENAI_API_KEY": "not-forwarded",
            "PATH": "/usr/bin",
        },
        tmp_path / "clean-state",
    )
    assert environment == {
        "PATH": "/usr/bin",
        "HOME": str(tmp_path / "clean-state" / "home"),
        "CODEX_HOME": str(tmp_path / "clean-state"),
    }
    assert phase0.isolated_environment_check(environment).passed is True


def test_isolated_environment_check_rejects_unexpected_credentials() -> None:
    """Reject a planned agent environment containing inherited credentials.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test asserts credential-bearing variables fail closed.
    """

    result = phase0.isolated_environment_check(
        {
            "PATH": "/usr/bin",
            "HOME": "/clean/home",
            "CODEX_HOME": "/clean",
            "GH_TOKEN": "credential",
        }
    )
    assert result.passed is False
    assert result.detail == "unexpected inherited variables: GH_TOKEN"


def test_container_probe_argv_has_no_network_or_sensitive_mounts(
    tmp_path: Path,
) -> None:
    """Build a deterministic containment probe with only the fixture mounted.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary fixture directory.

    Returns
    -------
    None
        The test asserts the container cannot receive host state or credentials.
    """

    fixture = tmp_path / "fixture"
    fixture.mkdir()
    argv = phase0.build_container_probe_argv(
        phase0.ContainerProbeRequest(
            runtime="docker",
            image=IMAGE,
            fixture_root=fixture,
            command="test ! -e /run/secrets/benchmark",
        )
    )
    assert "--network=none" in argv
    assert "--read-only" in argv
    assert "--cap-drop=ALL" in argv
    assert f"--mount=type=bind,src={fixture.resolve()},dst=/workspace" in argv
    assert not any("docker.sock" in item for item in argv)
    assert not any("secret" in item for item in argv[:-1])


def test_container_probe_argv_rejects_unpinned_image_and_missing_fixture(
    tmp_path: Path,
) -> None:
    """Reject probe definitions that cannot establish reproducible containment.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary path used for a deliberately absent fixture.

    Returns
    -------
    None
        The test asserts unsafe probe definitions do not produce commands.
    """

    request = phase0.ContainerProbeRequest(
        runtime="docker",
        image="example.invalid/codira-benchmark:latest",
        fixture_root=tmp_path / "missing",
        command="true",
    )
    try:
        phase0.build_container_probe_argv(request)
    except ValueError as error:
        assert str(error) == "image must use an exact sha256 digest"
    else:
        message = "expected unsafe probe definition to fail"
        raise AssertionError(message)


def test_contamination_fixture_separates_agent_and_protected_sentinels(
    tmp_path: Path,
) -> None:
    """Create public and protected fixture trees with no shared descendants.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary root for deterministic probe data.

    Returns
    -------
    None
        The test asserts protected data cannot be included in the agent mount.
    """

    fixture = phase0.create_contamination_fixture(tmp_path / "probe")
    assert (fixture.agent_root / "README.txt").is_file()
    assert fixture.host_memory_sentinel.is_file()
    assert fixture.hidden_oracle.is_file()
    assert fixture.agent_root not in fixture.host_memory_sentinel.parents
    assert fixture.agent_root not in fixture.hidden_oracle.parents


def test_contamination_fixture_rejects_reused_root(tmp_path: Path) -> None:
    """Reject a fixture root that could contain evidence from a prior probe.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary pre-populated fixture root.

    Returns
    -------
    None
        The test asserts fixture creation fails closed on reuse.
    """

    root = tmp_path / "probe"
    root.mkdir()
    (root / "prior-run.txt").write_text("contamination", encoding="utf-8")
    try:
        phase0.create_contamination_fixture(root)
    except ValueError as error:
        assert str(error) == "contamination fixture root must be empty"
    else:
        message = "expected reused fixture root to fail"
        raise AssertionError(message)


def test_build_isolated_codex_config_requires_only_codira_mcp() -> None:
    """Render a minimal configuration that fails if Codira MCP is unavailable.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test asserts the expected MCP root and required setting.
    """

    config = phase0.build_isolated_codex_config("/fixture")
    parsed = tomllib.loads(config)
    assert 'args = ["--root", "/fixture"]' in config
    assert "required = true" in config
    assert "plugin" not in config
    assert parsed["mcp_servers"]["codira"]["required"] is True
    assert parsed["features"] == {"memories": False, "multi_agent": False}
    assert parsed["sandbox_workspace_write"]["network_access"] is False
    assert parsed["shell_environment_policy"] == {
        "inherit": "core",
        "ignore_default_excludes": False,
    }
    assert phase0.isolated_config_check("/fixture").passed is True


def test_generated_proxy_config_uses_only_loopback_and_fresh_state(
    tmp_path: Path,
) -> None:
    """Generate provider-proxy configuration without exposing its credential.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary parent of the fresh Codex state root.

    Returns
    -------
    None
        The test asserts the proxy URL is loopback-only and the configuration
        exists only in the per-run state root.
    """

    state_root = tmp_path / "state"
    config_path = phase0.write_isolated_codex_config(
        state_root,
        "/fixture",
        "http://127.0.0.1:43123/v1",
        ("openai/gpt-5.6-terra", "medium"),
    )
    parsed = tomllib.loads(config_path.read_text(encoding="utf-8"))
    provider = parsed["model_providers"]["benchmark-openrouter-proxy"]
    assert parsed["model_provider"] == "benchmark-openrouter-proxy"
    assert provider == {
        "name": "Benchmark OpenRouter proxy",
        "base_url": "http://127.0.0.1:43123/v1",
        "env_key": "CODIRA_PROXY_CLIENT_TOKEN",
        "wire_api": "responses",
        "requires_openai_auth": False,
    }
    assert (
        phase0.isolated_config_check(
            "/fixture",
            "http://127.0.0.1:43123/v1",
            "openai/gpt-5.6-terra",
            "medium",
        ).passed
        is True
    )


def test_generated_proxy_config_rejects_non_loopback_url() -> None:
    """Reject provider proxies that could be reached outside the runner host.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test asserts arbitrary remote provider endpoints are not accepted.
    """

    try:
        phase0.build_isolated_codex_config(
            proxy_url="https://proxy.example",
            model="openai/gpt-5.6-terra",
            reasoning_effort="medium",
        )
    except ValueError as error:
        assert (
            str(error) == "provider proxy URL must use HTTP(S) loopback ending in /v1"
        )
    else:
        message = "expected non-loopback provider proxy URL to fail"
        raise AssertionError(message)


def test_jsonl_conformance_accepts_complete_assisted_evidence() -> None:
    """Accept JSONL with MCP, tool output, and every required usage field.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test asserts the evidence stream is admissible.
    """

    assert phase0.jsonl_conformance_check(_complete_events()).passed is True


def test_jsonl_conformance_rejects_missing_usage_and_mcp_event() -> None:
    """Reject a completed event stream that cannot support token attribution.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test asserts an incomplete event stream is rejected.
    """

    events = list(_complete_events())
    events[2] = {"type": "item.completed", "item": {"type": "file_change"}}
    result = phase0.jsonl_conformance_check(events)
    assert result.passed is False
    assert result.detail == "MCP tool event is absent"


def test_jsonl_conformance_rejects_mcp_for_baseline_and_accepts_clean_baseline() -> (
    None
):
    """Require baseline JSONL evidence to exclude all MCP tool exposure.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test asserts the intended difference between experiment variants.
    """

    assisted = _complete_events()
    result = phase0.jsonl_conformance_check(assisted, "baseline")
    assert result.passed is False
    assert result.detail == "baseline JSONL contains an MCP tool event"

    baseline = list(assisted)
    baseline[2] = {"type": "item.completed", "item": {"type": "file_change"}}
    assert phase0.jsonl_conformance_check(baseline, "baseline").passed is True


def test_jsonl_conformance_accepts_completed_file_change_as_artifact_evidence() -> None:
    """Accept the current Codex artifact event in place of shell execution.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The completed file-change item proves the agent wrote its requested
        artifact even when no command-execution item is emitted.
    """

    events = list(_complete_events())
    events[3] = {
        "type": "item.completed",
        "item": {"type": "file_change", "status": "completed", "changes": [{}]},
    }
    assert phase0.jsonl_conformance_check(events).passed is True


def test_cancellation_check_requires_a_prompt_cancellation_exit() -> None:
    """Reject normal exits and late termination from a cancellation probe.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test asserts cancellation evidence is bounded and explicit.
    """

    assert phase0.cancellation_check(-15, 0.1, 1.0).passed is True
    assert phase0.cancellation_check(0, 0.1, 1.0).passed is False
    assert phase0.cancellation_check(0, 0.1, 1.0, signal_sent=True).passed is True
    assert phase0.cancellation_check(1, 0.1, 1.0, signal_sent=True).passed is True
    assert phase0.cancellation_check(130, 1.1, 1.0).passed is False


def test_cancellation_event_check_requires_started_nonterminal_turn() -> None:
    """Accept cancellation only after a turn begins without a terminal event.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test asserts a provider failure is not misclassified as cancellation.
    """

    assert (
        phase0.cancellation_event_check(
            ({"type": "thread.started"}, {"type": "turn.started"})
        ).passed
        is True
    )
    failed = phase0.cancellation_event_check(
        ({"type": "turn.started"}, {"type": "turn.failed"})
    )
    assert failed.passed is False
    assert failed.detail == "terminal events: turn.failed"


def test_escape_probe_check_requires_all_probes_to_be_blocked() -> None:
    """Reject missing or successful contamination and escape attempts.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test asserts the mandatory probe set is fail closed.
    """

    blocked = {probe: True for probe in phase0.REQUIRED_ESCAPE_PROBES}
    assert phase0.escape_probe_check(blocked).passed is True
    blocked["oracle-read"] = False
    result = phase0.escape_probe_check(blocked)
    assert result.passed is False
    assert result.detail == "unblocked probes: oracle-read"


def test_environment_checker_accepts_explicit_baseline_evidence_mode() -> None:
    """Expose the baseline's no-MCP assertion through the command interface.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test asserts the CLI does not silently assume assisted evidence.
    """

    args = build_parser().parse_args(
        [
            "--image",
            IMAGE,
            "--state-root",
            "/tmp/clean-state",
            "--assistance-mode",
            "baseline",
        ]
    )
    assert args.assistance_mode == "baseline"


def test_phase0_host_preparation_help_is_available() -> None:
    """Expose a safe, self-documenting host-preparation entry point.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test asserts the helper is syntactically valid and documents its
        explicit host-changing options.
    """

    script = REPOSITORY_ROOT / "scripts" / "prepare_agent_efficiency_phase0_host.sh"
    syntax = subprocess.run(
        ["bash", "-n", str(script)], check=False, capture_output=True, text=True
    )
    assert syntax.returncode == 0, syntax.stderr
    help_result = subprocess.run(
        ["bash", str(script), "--help"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert help_result.returncode == 0
    assert "--install-codex" in help_result.stdout
    assert "--pull-image" in help_result.stdout


def test_approved_live_probe_manifest_is_bounded_and_conformance_only() -> None:
    """Keep the approved live-probe inputs explicit and non-comparative.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test asserts the approved provider identity, limits, and evidence
        contract stay reviewable without reading a credential.
    """

    manifest_path = (
        REPOSITORY_ROOT / "benchmarks" / "agent-efficiency" / "phase0-live-probe.toml"
    )
    manifest = tomllib.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["purpose"] == "runner-and-isolation-conformance"
    assert manifest["attempts"] == 1
    assert manifest["provider"] == {
        "name": "openrouter",
        "model": "openai/gpt-5.6-terra",
        "reasoning_effort": "medium",
        "wire_api": "responses",
        "credential_environment": "codira-tests-openrouter",
        "provider_key_daily_limit_usd": 0.25,
    }
    assert manifest["limits"] == {
        "timeout_seconds": 600,
        "max_output_tokens": 12000,
        "observed_total_tokens_ceiling": 80000,
        "max_attempts": 1,
    }
    assert manifest["admission"] == {
        "purpose": "conformance-only",
        "exclude_from_paired_savings_analysis": True,
        "reject_if_observed_total_tokens_exceed_ceiling": True,
        "reject_if_provider_key_limit_is_not_configured": True,
    }


def test_live_probe_dry_run_has_fixed_jsonl_command(tmp_path: Path) -> None:
    """Render the paid probe command without starting an agent or proxy.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary fixture and fresh state/evidence locations.

    Returns
    -------
    None
        The test asserts dry run is non-billed and retains required Codex flags.
    """

    fixture_root = tmp_path / "fixture"
    fixture_root.mkdir()
    events = tmp_path / "events.jsonl"
    state_root = tmp_path / "state"
    manifest = load_manifest(
        REPOSITORY_ROOT / "benchmarks" / "agent-efficiency" / "phase0-live-probe.toml"
    )
    assert manifest["provider"] == {
        "name": "openrouter",
        "model": "openai/gpt-5.6-terra",
        "reasoning_effort": "medium",
        "wire_api": "responses",
        "credential_environment": "codira-tests-openrouter",
        "provider_key_daily_limit_usd": 0.25,
    }
    assert (
        run_live_probe(
            [
                "--fixture-root",
                str(fixture_root),
                "--state-root",
                str(state_root),
                "--events",
                str(events),
            ]
        )
        == 0
    )
    argv = build_codex_argv("codex", fixture_root)
    assert "--json" in argv
    assert "--ephemeral" in argv
    assert "--ignore-rules" in argv
    assert "--skip-git-repo-check" in argv


def test_live_probe_parser_accepts_declared_cancellation_delay() -> None:
    """Expose cancellation only through an explicit positive CLI input.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test asserts the launcher parser retains the declared delay value.
    """

    from scripts.run_agent_efficiency_phase0_live_probe import build_parser

    args = build_parser().parse_args(
        [
            "--fixture-root",
            "/tmp/fixture",
            "--state-root",
            "/tmp/state",
            "--events",
            "/tmp/events.jsonl",
            "--cancel-after-seconds",
            "1.5",
        ]
    )
    assert args.cancel_after_seconds == 1.5


def test_live_probe_prepares_a_fresh_disposable_fixture(tmp_path: Path) -> None:
    """Create a small agent fixture only from an absent or empty path.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary parent for a disposable probe fixture.

    Returns
    -------
    None
        The test asserts fixture content is deterministic and non-reusable.
    """

    fixture_root = tmp_path / "fixture"
    prepare_disposable_fixture(fixture_root)
    assert (fixture_root / "README.md").is_file()
    assert (fixture_root / "sample.py").is_file()
    assert (fixture_root / ".benchmark").is_dir()
    try:
        prepare_disposable_fixture(fixture_root)
    except ValueError as error:
        assert str(error) == "fixture root must be absent or empty for a fresh probe"
    else:
        message = "expected non-empty fixture reuse to fail"
        raise AssertionError(message)


def test_live_probe_resolves_only_executable_mcp_paths(tmp_path: Path) -> None:
    """Reject a configured MCP binary that cannot be executed.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary directory for a candidate executable path.

    Returns
    -------
    None
        The test asserts explicit executable paths are verified before launch.
    """

    candidate = tmp_path / "codira-mcp"
    candidate.write_text("#!/bin/sh\n", encoding="utf-8")
    assert resolve_executable(str(candidate)) is None
    candidate.chmod(0o700)
    assert resolve_executable(str(candidate)) == str(candidate)


def test_escape_probe_commands_and_exit_semantics_cover_every_requirement() -> None:
    """Define deterministic blocked outcomes for every required escape attempt.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test asserts the runner covers the approved mandatory probe set.
    """

    commands = probe_commands()
    assert set(commands) == set(phase0.REQUIRED_ESCAPE_PROBES)
    assert blocked(0, True) is True
    assert blocked(1, True) is False
    assert blocked(1, False) is True
    assert blocked(0, False) is False


def test_provider_proxy_requires_two_distinct_runner_side_credentials() -> None:
    """Require separate local-client and upstream proxy credentials.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test asserts the proxy fails before binding without both settings.
    """

    environment = {
        provider_proxy.PROXY_CLIENT_TOKEN_ENV: "client-token",
        provider_proxy.UPSTREAM_TOKEN_ENV: "upstream-token",
    }
    settings = provider_proxy.parse_settings(environment, 43123)
    assert settings.port == 43123
    assert provider_proxy.is_authorized("Bearer client-token", settings.client_token)
    assert not provider_proxy.is_authorized(
        "Bearer upstream-token", settings.client_token
    )
    try:
        provider_proxy.parse_settings({}, 43123)
    except ValueError as error:
        assert str(error) == "proxy client and upstream credentials are both required"
    else:
        message = "expected incomplete proxy settings to fail"
        raise AssertionError(message)


def test_unix_provider_proxy_is_owner_only() -> None:
    """Bind the runner-side proxy to one owner-only Unix socket capability.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test asserts that the bound socket has owner-only permissions.
    """

    settings = provider_proxy.ProxySettings("client", "upstream", 0)
    with tempfile.TemporaryDirectory(dir="/tmp", prefix="phase4-") as directory:
        socket_path = Path(directory) / "provider.sock"
        server = provider_proxy.create_unix_server(settings, str(socket_path))
        try:
            assert socket_path.is_socket()
            assert socket_path.stat().st_mode & 0o777 == 0o600
        finally:
            server.server_close()


def test_provider_proxy_exposes_only_responses_api_paths() -> None:
    """Limit proxy routing to the documented minimal endpoint allowlist.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test asserts unrelated provider API endpoints are not proxied.
    """

    assert {"/v1/models", "/v1/responses"} == provider_proxy.ALLOWED_PATHS
    assert provider_proxy.upstream_path("/v1/responses") == "/api/v1/responses"
    assert (
        provider_proxy.upstream_path("/v1/models?limit=1") == "/api/v1/models?limit=1"
    )
    try:
        provider_proxy.upstream_path("/v1/files")
    except ValueError as error:
        assert str(error) == "request path is not allowlisted"
    else:
        message = "expected non-allowlisted provider path to fail"
        raise AssertionError(message)


def test_provider_proxy_clamps_responses_output_allowance() -> None:
    """Bound the provider-requested output allowance to the approved ceiling.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test asserts large allowances are reduced without retaining payloads.
    """

    bounded = provider_proxy.constrain_response_request(
        b'{"model":"openai/gpt-5.6-terra","max_output_tokens":65536}', 12000
    )
    assert json.loads(bounded) == {
        "model": "openai/gpt-5.6-terra",
        "max_output_tokens": 12000,
    }
    assert json.loads(provider_proxy.constrain_response_request(b"{}", 12000)) == {
        "max_output_tokens": 12000
    }


def test_provider_proxy_rejects_model_effort_substitution_and_sets_price_cap() -> None:
    """Reject unapproved model settings and constrain approved provider pricing.

    Parameters
    ----------
    None

    Returns
    -------
    None
        Assertions cover immutable Phase 6 model, effort, and price controls.
    """

    payload = json.dumps(
        {
            "model": "openai/gpt-5.6-terra",
            "reasoning": {"effort": "medium"},
            "max_output_tokens": 12000,
        }
    ).encode()
    constraints = provider_proxy.ResponseConstraints(
        "openai/gpt-5.6-terra", "medium", 2, 12
    )
    constrained = provider_proxy.constrain_response_request(payload, 12000, constraints)
    assert json.loads(constrained)["provider"] == {
        "allow_fallbacks": False,
        "max_price": {"prompt": 2, "completion": 12},
    }
    with pytest.raises(ValueError, match="approved model"):
        provider_proxy.constrain_response_request(
            payload,
            12000,
            provider_proxy.ResponseConstraints("openai/gpt-5.6-sol", "medium"),
        )
    with pytest.raises(ValueError, match="approved effort"):
        provider_proxy.constrain_response_request(
            payload,
            12000,
            provider_proxy.ResponseConstraints("openai/gpt-5.6-terra", "high"),
        )


def test_observed_total_token_check_excludes_cached_input_from_total() -> None:
    """Count cached input only once through the provider-reported input total.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test asserts over-budget completed evidence is rejected.
    """

    events = _complete_events()[:-1] + (
        {
            "type": "turn.completed",
            "usage": {
                "input_tokens": 12000,
                "cached_input_tokens": 11000,
                "output_tokens": 1,
                "reasoning_output_tokens": 0,
            },
        },
    )
    check = phase0.observed_total_token_check(events, 12000)
    assert check.passed is False
    assert check.detail == "observed total 12001 exceeds ceiling 12000"


def test_parse_jsonl_events_rejects_non_object_rows() -> None:
    """Reject malformed JSONL before it can be treated as benchmark evidence.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test asserts invalid rows raise a deterministic error.
    """

    try:
        phase0.parse_jsonl_events('{"type":"turn.started"}\n[]\n')
    except phase0.JsonlEvidenceError as error:
        assert str(error) == "JSONL line 2 is not an object"
    else:
        message = "expected malformed JSONL to be rejected"
        raise AssertionError(message)
