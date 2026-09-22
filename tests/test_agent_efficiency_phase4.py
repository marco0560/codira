"""Test paired scheduling, immutable persistence, and container JSONL adaptation."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import cast

import pytest

from scripts.agent_efficiency.campaign_state import (
    CampaignStateError,
    CampaignStore,
    build_paired_schedule,
    run_pending,
)
from scripts.agent_efficiency.environment import FixtureEnvironment
from scripts.agent_efficiency.runner import (
    ContainerAttemptRequest,
    ContainerExecution,
    EnvironmentPreparationRequest,
    IndexPreparationRequest,
    build_attempt_codex_config,
    build_container_argv,
    build_environment_preparation_argv,
    build_index_preparation_argv,
    capture_workspace_patch,
    execute_container_attempt,
    result_from_execution,
    write_attempt_codex_config,
    write_proxy_relay,
)
from scripts.agent_efficiency.runtime_admission import (
    RuntimeAdmissionError,
    _require_history_free_staged_fixture,
    admit_runtime,
)
from scripts.agent_efficiency.usage import UsageError, normalize_completed_turn

IMAGE = "example.invalid/codira-benchmark@sha256:" + "a" * 64
INTEGRATION_IMAGE_ENV = "CODIRA_AGENT_EFFICIENCY_INTEGRATION_IMAGE"


def test_runner_containerfile_installs_transcript_required_utilities() -> None:
    """Keep commands used by benchmark agents available in the runner image.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The image recipe retains the shell tools observed in pilot transcripts.
    """

    containerfile = Path("benchmarks/agent-efficiency/Containerfile.phase4")
    source = containerfile.read_text(encoding="utf-8")
    for package in ("git", "jq", "ripgrep"):
        assert package in source
    assert "packages/codira-backend-sqlite" in source
    assert "/opt/codira-backend-sqlite" in source
    assert "packages/codira-vector-store-sqlite" in source
    assert "packages/codira-embedding-onnx" in source
    assert "download_embedding_model.py" in source
    assert "bge-small-en-v1.5-onnx" in source
    assert '"tree-sitter==0.25.2"' in source
    for analyzer in ("python", "javascript", "json", "markdown", "bash", "text"):
        assert f"packages/codira-analyzer-{analyzer}" in source
    assert "runtime_admission.py" in source
    assert "benchmark-codira.toml" in source
    assert "codira-mcp-benchmark" in source
    profile = Path("scripts/agent_efficiency/benchmark-codira.toml").read_text(
        encoding="utf-8"
    )
    assert 'engine = "onnx"' in profile
    assert 'strategy = "off"' in profile
    assert "batch_size = 1" in profile


@pytest.mark.integration
def test_runtime_admission_executes_an_indexed_mcp_query(tmp_path: Path) -> None:
    """Require a real local index and MCP context response before admission.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Writable disposable fixture root.

    Returns
    -------
    None
        The installed stdio MCP endpoint returns a non-error context response.
    """

    if os.environ.get("CODIRA_AGENT_EFFICIENCY_RUNTIME_ADMISSION") != "1":
        pytest.skip("set CODIRA_AGENT_EFFICIENCY_RUNTIME_ADMISSION=1 to run")
    (tmp_path / "sample.py").write_text(
        "def helper() -> int:\n    return 42\n", encoding="utf-8"
    )
    admit_runtime(tmp_path, "helper")


def test_runtime_admission_requires_the_agent_fixture_git_representation(
    tmp_path: Path,
) -> None:
    """Reject source checkouts and empty synthetic indexes during admission.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary Git repository used to model admission representations.

    Returns
    -------
    None
        Only a staged repository without a commit is admitted.
    """

    subprocess.run(("git", "init", "--quiet"), cwd=tmp_path, check=True)
    (tmp_path / "sample.py").write_text("value = 1\n", encoding="utf-8")
    with pytest.raises(RuntimeAdmissionError, match="staged history-free"):
        _require_history_free_staged_fixture(tmp_path)
    subprocess.run(("git", "add", "--all"), cwd=tmp_path, check=True)
    assert _require_history_free_staged_fixture(tmp_path) == 1
    subprocess.run(
        (
            "git",
            "-c",
            "user.name=Fixture",
            "-c",
            "user.email=fixture@example.invalid",
            "commit",
            "--quiet",
            "-m",
            "fixture",
        ),
        cwd=tmp_path,
        check=True,
    )
    with pytest.raises(RuntimeAdmissionError, match="staged history-free"):
        _require_history_free_staged_fixture(tmp_path)


def test_environment_preparation_runs_offline_before_the_agent(tmp_path: Path) -> None:
    """Build a no-network command for a locked fixture environment.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary fixture directory mounted writable in the container.

    Returns
    -------
    None
        The command retains the hardened runtime controls and selected plan.
    """

    fixture = tmp_path / "fixture"
    fixture.mkdir()
    environment = FixtureEnvironment(
        "uv",
        ("/opt/codira/prepare-fixture-environment", "fixture-public", "uv"),
        "ready",
        "fixture-public",
    )

    argv = build_environment_preparation_argv(
        EnvironmentPreparationRequest("podman", IMAGE, fixture, 60, environment)
    )

    assert "--network=none" in argv
    assert "--read-only" in argv
    assert argv[-3:] == environment.prepare_argv


def _events(mode: str = "codira-mcp") -> list[dict[str, object]]:
    """Build a complete synthetic JSONL event stream for one variant.

    Parameters
    ----------
    mode : str, optional
        Scheduled assistance variant represented by the event stream.

    Returns
    -------
    list[dict[str, object]]
        Complete stream with command evidence and provider usage.
    """

    items: list[dict[str, object]] = [
        {"type": "item.completed", "item": {"type": "command_execution"}}
    ]
    if mode == "codira-mcp":
        items.insert(0, {"type": "item.completed", "item": {"type": "mcp_tool_call"}})
    return [
        {"type": "thread.started"},
        {"type": "turn.started"},
        *items,
        {
            "type": "turn.completed",
            "usage": {
                "input_tokens": 10,
                "cached_input_tokens": 4,
                "output_tokens": 3,
                "reasoning_output_tokens": 2,
            },
        },
    ]


def _store(tmp_path: Path) -> CampaignStore:
    """Create one deterministic two-task campaign store.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary ignored runtime root.

    Returns
    -------
    CampaignStore
        Initialized frozen campaign store.
    """

    return CampaignStore(
        tmp_path / "state",
        "pilot-001",
        {"image": IMAGE, "runner": "container-jsonl", "seed": 7},
        build_paired_schedule(("symbols-001", "patch-001"), 1, 7),
    )


def _result(
    store: CampaignStore, attempt_id: str
) -> tuple[dict[str, object], dict[str, object]]:
    """Build one valid synthetic result/evidence pair for a scheduled attempt.

    Parameters
    ----------
    store : CampaignStore
        Store containing the desired schedule member.
    attempt_id : str
        Stable scheduled attempt identity.

    Returns
    -------
    tuple[dict[str, object], dict[str, object]]
        Valid result and immutable evidence metadata.
    """

    attempt = next(item for item in store.schedule if item.attempt_id == attempt_id)
    return result_from_execution(
        store.campaign_id,
        attempt,
        ContainerExecution(
            0,
            "\n".join(json.dumps(item) for item in _events(attempt.assistance_mode)),
            "",
            0.2,
        ),
    )


def test_paired_schedule_randomizes_order_but_preserves_complete_pairs() -> None:
    """Produce one baseline and one MCP attempt for every frozen pair.

    Parameters
    ----------
    None

    Returns
    -------
    None
        Assertions cover reproducibility, randomization, and pair completeness.
    """

    first = build_paired_schedule(("symbols-001", "patch-001"), 3, 9)
    assert first == build_paired_schedule(("patch-001", "symbols-001"), 3, 9)
    assert len(first) == 12
    pairs: dict[str, set[str]] = {}
    for attempt in first:
        pairs.setdefault(attempt.pair_id, set()).add(attempt.assistance_mode)
    assert all(modes == {"baseline", "codira-mcp"} for modes in pairs.values())


def test_runner_captures_workspace_diff_without_agent_git_history(
    tmp_path: Path,
) -> None:
    """Capture a patch from a private snapshot and a history-free workspace.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary private baseline and agent workspace roots.

    Returns
    -------
    None
        The captured patch contains only changed source content.
    """

    baseline, workspace = tmp_path / "baseline", tmp_path / "workspace"
    baseline.mkdir()
    workspace.mkdir()
    (baseline / "module.py").write_text("VALUE = 'before'\n", encoding="utf-8")
    (workspace / "module.py").write_text("VALUE = 'after'\n", encoding="utf-8")
    (workspace / ".git").mkdir()
    (workspace / ".git" / "hidden").write_text("ignored", encoding="utf-8")

    patch = workspace / ".benchmark" / "fix.patch"
    capture_workspace_patch(baseline, workspace, patch)

    source = patch.read_text(encoding="utf-8")
    assert "a/module.py" in source
    assert "b/module.py" in source
    assert ".git" not in source


def test_index_preparation_precedes_mcp_with_hardened_runtime(
    tmp_path: Path,
) -> None:
    """Require a separate hardened ``codira index`` command before MCP use.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Disposable exported fixture root.

    Returns
    -------
    None
        The command never mounts Codex state or a provider transport.
    """

    fixture = tmp_path / "fixture"
    fixture.mkdir()
    argv = build_index_preparation_argv(
        IndexPreparationRequest(
            "podman", IMAGE, fixture, 60, "/opt/codira/benchmark-codira.toml"
        )
    )
    assert argv[-4:] == (
        "codira",
        "index",
        "--config-file",
        "/opt/codira/benchmark-codira.toml",
    )
    assert "--network=none" in argv
    assert "/codex-state" not in " ".join(argv)


def test_store_resumes_only_validated_immutable_records(tmp_path: Path) -> None:
    """Keep terminal failures and skip them during subsequent resume calls.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary runtime storage root.

    Returns
    -------
    None
        Assertions cover atomic persistence and no-success-only retry behavior.
    """

    store = _store(tmp_path)
    store.initialize()
    first = store.schedule[0]
    result, evidence = _result(store, first.attempt_id)
    result["outcome"] = "oracle_failure"
    result["failure_class"] = "deterministic-oracle"
    stored = store.store_result(first.attempt_id, result, evidence)
    assert stored.is_file()
    assert first.attempt_id not in {
        item.attempt_id for item in store.pending_attempts()
    }
    assert len(store.pending_attempts()) == len(store.schedule) - 1
    with pytest.raises(CampaignStateError, match="already exists"):
        store.store_result(first.attempt_id, result, evidence)


def test_store_retains_index_preparation_separately_from_timed_results(
    tmp_path: Path,
) -> None:
    """Keep assisted index preparation outside paired execution accounting.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary campaign runtime root.

    Returns
    -------
    None
        Assertions cover assisted-only immutable preparation evidence.
    """

    store = _store(tmp_path)
    store.initialize()
    assisted = next(
        item for item in store.schedule if item.assistance_mode == "codira-mcp"
    )
    preparation = {
        "elapsed_seconds": 1.2,
        "fixture_revision": "a" * 40,
        "index_fingerprint": "b" * 64,
        "tracked_file_count": 2,
        "indexed_file_count": 1,
        "generation": 1,
        "generation_state": "ready",
        "partial": False,
        "failed_file_count": 0,
    }
    path = store.store_index_preparation(
        assisted.attempt_id,
        preparation,
    )
    assert path.parent == store.preparation_root
    stored = json.loads(path.read_text(encoding="utf-8"))
    stored["preparation_fingerprint"] = "0" * 64
    path.write_text(json.dumps(stored), encoding="utf-8")
    with pytest.raises(CampaignStateError, match="preparation fingerprint"):
        store.validated_preparation()
    baseline = next(
        item for item in store.schedule if item.assistance_mode == "baseline"
    )
    with pytest.raises(CampaignStateError, match="only valid"):
        store.store_index_preparation(
            baseline.attempt_id,
            preparation,
        )


def test_resume_rejects_configuration_drift_tampering_and_partial_crash(
    tmp_path: Path,
) -> None:
    """Reject drifted evidence while ignoring an uninstalled temporary write.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary runtime storage root.

    Returns
    -------
    None
        Assertions cover crash-safe temp files and strict evidence validation.
    """

    store = _store(tmp_path)
    store.initialize()
    (store.records_root / ".interrupted.tmp").parent.mkdir(exist_ok=True)
    (store.records_root / ".interrupted.tmp").write_text("partial", encoding="utf-8")
    assert len(store.pending_attempts()) == len(store.schedule)
    result, evidence = _result(store, store.schedule[0].attempt_id)
    record_path = store.store_result(store.schedule[0].attempt_id, result, evidence)
    record = json.loads(record_path.read_text(encoding="utf-8"))
    record["configuration_fingerprint"] = "b" * 64
    record_path.write_text(json.dumps(record), encoding="utf-8")
    with pytest.raises(CampaignStateError, match="configuration drift"):
        store.pending_attempts()


def test_run_pending_recovers_after_interruption_without_duplicate_execution(
    tmp_path: Path,
) -> None:
    """Run every missing schedule member once and resume as an empty operation.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary runtime storage root.

    Returns
    -------
    None
        Assertions cover resumable execution and immutable result installation.
    """

    store = _store(tmp_path)
    calls: list[str] = []

    def execute(attempt: object) -> tuple[dict[str, object], dict[str, object]]:
        """Return one deterministic result while tracking the execution identity.

        Parameters
        ----------
        attempt : object
            Scheduled attempt passed by the resume loop.

        Returns
        -------
        tuple[dict[str, object], dict[str, object]]
            Schema-valid result and evidence metadata.
        """

        assert hasattr(attempt, "attempt_id")
        attempt_id = str(attempt.attempt_id)
        calls.append(attempt_id)
        return _result(store, attempt_id)

    assert len(run_pending(store, execute)) == len(store.schedule)
    assert len(calls) == len(store.schedule)
    assert run_pending(store, execute) == ()
    assert len(calls) == len(store.schedule)


def test_usage_normalization_rejects_duplicates_and_excludes_cached_input() -> None:
    """Preserve provider counters without double-counting cached input tokens.

    Parameters
    ----------
    None

    Returns
    -------
    None
        Assertions cover duplicate terminal evidence and token semantics.
    """

    normalized = normalize_completed_turn(_events())
    assert normalized.complete is True
    assert normalized.observed_total_tokens == 15
    with pytest.raises(UsageError, match="exactly one"):
        normalize_completed_turn(_events() + [_events()[-1]])
    invalid = _events()
    usage = cast("dict[str, object]", invalid[-1]["usage"])
    invalid[-1]["usage"] = {**usage, "cached_input_tokens": 11}
    with pytest.raises(UsageError, match="cannot exceed"):
        normalize_completed_turn(invalid)


def test_container_argv_and_adapter_preserve_isolation_and_incomplete_usage(
    tmp_path: Path,
) -> None:
    """Build a network-disabled container command and mark missing usage incomplete.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary fixture and fresh Codex-state directories.
    monkeypatch : pytest.MonkeyPatch
        Fixture used to model the mounted Unix-socket capability.

    Returns
    -------
    None
        Assertions cover container isolation, JSONL adaptation, and accounting.
    """

    fixture = tmp_path / "fixture"
    state = tmp_path / "state"
    fixture.mkdir()
    state.mkdir()
    argv = build_container_argv(
        ContainerAttemptRequest("podman", IMAGE, fixture, state, "do task", 10)
    )
    assert "--network=none" in argv
    assert "--read-only" in argv
    assert argv[argv.index("--sandbox") + 1] == "danger-full-access"
    assert not any("OPENROUTER" in item or "GH_TOKEN" in item for item in argv)
    attempt = build_paired_schedule(("symbols-001",), 1, 1)[0]
    events = _events(attempt.assistance_mode)
    events[-1].pop("usage")
    result, evidence = result_from_execution(
        "pilot-001",
        attempt,
        ContainerExecution(0, "\n".join(json.dumps(item) for item in events), "", 0.1),
    )
    assert result["usage_complete"] is False
    assert result["outcome"] == "infrastructure_failure"
    assert evidence["jsonl_event_count"] == len(events)


def test_failed_turn_preserves_rate_limit_evidence() -> None:
    """Classify a provider 429 terminal event without requiring completion usage.

    Parameters
    ----------
    None

    Returns
    -------
    None
        Assertions prove a failed paid response remains diagnosable evidence.
    """

    attempt = build_paired_schedule(("symbols-001",), 1, 1)[0]
    events = _events(attempt.assistance_mode)[:-1] + [
        {
            "type": "turn.failed",
            "error": {"message": "exceeded retry limit, last status: 429"},
        }
    ]

    result, evidence = result_from_execution(
        "pilot-001",
        attempt,
        ContainerExecution(1, "\n".join(json.dumps(item) for item in events), "", 0.1),
    )

    assert result["outcome"] == "infrastructure_failure"
    assert result["failure_class"] == "provider_rate_limited"
    assert result["usage_complete"] is False
    assert evidence["jsonl_event_count"] == len(events)


def test_container_timeout_is_recorded_as_cancellation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Turn a runner timeout into a cancellable terminal result.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary fixture and fresh Codex-state directories.
    monkeypatch : pytest.MonkeyPatch
        Replaces process execution with a deterministic timeout.

    Returns
    -------
    None
        Assertions cover timeout capture and terminal cancellation reporting.
    """

    fixture = tmp_path / "fixture"
    fixture.mkdir()
    state = tmp_path / "state"
    state.mkdir()

    (state / "container.cid").write_text("a" * 64, encoding="utf-8")
    calls: list[tuple[str, ...]] = []

    def timeout_or_cleanup(arguments: tuple[str, ...], **_kwargs: object) -> object:
        """Time out the launch then record force-removal of its CID."""

        calls.append(arguments)
        if arguments[1] == "run":
            raise subprocess.TimeoutExpired(("podman", "run"), 1, output="partial")
        return subprocess.CompletedProcess(arguments, 0, "", "")

    monkeypatch.setattr(
        "scripts.agent_efficiency.runner.subprocess.run", timeout_or_cleanup
    )
    execution = execute_container_attempt(
        ContainerAttemptRequest("podman", IMAGE, fixture, state, "do task", 1)
    )
    attempt = build_paired_schedule(("symbols-001",), 1, 1)[0]
    result, evidence = result_from_execution("pilot-001", attempt, execution)
    assert execution.timed_out is True
    assert result["outcome"] == "cancelled"
    assert result["failure_class"] == "timeout"
    assert evidence["timed_out"] is True
    assert calls[-1] == ("podman", "rm", "--force", "a" * 64)


def test_runner_marks_provider_usage_above_the_manifest_cap_invalid() -> None:
    """Reject a complete response whose measured usage exceeds its manifest cap.

    Parameters
    ----------
    None

    Returns
    -------
    None
        Over-cap provider usage becomes non-comparative infrastructure evidence.
    """

    attempt = build_paired_schedule(("symbols-001",), 1, 1)[0]
    execution = ContainerExecution(
        0,
        "\n".join(json.dumps(item) for item in _events(attempt.assistance_mode)),
        "",
        0.1,
    )

    result, _ = result_from_execution(
        "pilot-001", attempt, execution, max_total_tokens=18
    )

    assert result["usage_complete"] is True
    assert result["outcome"] == "infrastructure_failure"
    assert result["failure_class"] == "usage_cap_exceeded"


def test_variant_configuration_exposes_required_mcp_only_to_assisted_runs(
    tmp_path: Path,
) -> None:
    """Keep baseline runs free of MCP while requiring Codira for assistance.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary fresh Codex-state location.

    Returns
    -------
    None
        Assertions cover variant-specific MCP exposure and fresh state.
    """

    baseline = build_attempt_codex_config("baseline")
    assisted = build_attempt_codex_config("codira-mcp")
    assert "mcp_servers" not in baseline
    assert "[mcp_servers.codira]" in assisted
    assert "required = true" in assisted
    config_path = write_attempt_codex_config(tmp_path / "state", "baseline")
    assert config_path.read_text(encoding="utf-8") == baseline
    with pytest.raises(ValueError, match="absent"):
        write_attempt_codex_config(config_path.parent, "baseline")


def test_proxy_transport_keeps_container_network_disabled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Expose a provider only through a mounted Unix socket and loopback relay.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary fixture and fresh Codex-state directories.
    monkeypatch : pytest.MonkeyPatch
        Fixture used to model the mounted Unix-socket capability.

    Returns
    -------
    None
        Assertions cover the proxy capability boundary in the command vector.
    """

    fixture = tmp_path / "fixture"
    fixture.mkdir()
    state = tmp_path / "state"
    state.mkdir()
    socket_path = state / "provider.sock"
    monkeypatch.setattr(Path, "is_socket", lambda _path: True)
    relay = write_proxy_relay(state)
    argv = build_container_argv(
        ContainerAttemptRequest(
            "podman",
            IMAGE,
            fixture,
            state,
            "probe",
            10,
            proxy_socket=socket_path,
            proxy_client_token="ephemeral-client-token",
        )
    )
    assert relay.is_file()
    assert "--network=none" in argv
    assert "--env=CODIRA_PROXY_CLIENT_TOKEN" in argv
    assert "--sandbox danger-full-access" in next(
        item for item in argv if "/codex-state/provider_relay.py" in item
    )
    assert any("/codex-state/provider_relay.py" in item for item in argv)


@pytest.mark.integration
def test_container_adapter_captures_network_isolated_jsonl_baseline(
    tmp_path: Path,
) -> None:
    """Exercise the real container adapter with a credential-free JSONL shim.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Disposable fixture and state roots mounted into the probe container.

    Returns
    -------
    None
        Assertions cover a real runtime invocation, network containment, and
        JSONL-to-result conversion without claiming Codex/MCP availability.
    """

    image = os.environ.get(INTEGRATION_IMAGE_ENV)
    if image is None:
        pytest.skip(f"set {INTEGRATION_IMAGE_ENV} to run the container adapter probe")
    fixture = tmp_path / "fixture"
    fixture.mkdir()
    state = tmp_path / "state"
    write_attempt_codex_config(state, "baseline")
    shim = fixture / "jsonl-shim"
    shim.write_text(
        "#!/bin/sh\n"
        "printf '%s\\n' "
        '\'{"type":"thread.started"}\' '
        '\'{"type":"turn.started"}\' '
        '\'{"type":"item.completed","item":{"type":"command_execution"}}\' '
        '\'{"type":"turn.completed","usage":{"input_tokens":1,"cached_input_tokens":0,"output_tokens":1,"reasoning_output_tokens":0}}\'\n',
        encoding="utf-8",
    )
    shim.chmod(0o755)
    execution = execute_container_attempt(
        ContainerAttemptRequest(
            "podman", image, fixture, state, "probe", 20, "/workspace/jsonl-shim"
        )
    )
    attempt = next(
        item
        for item in build_paired_schedule(("symbols-001",), 1, 3)
        if item.assistance_mode == "baseline"
    )
    result, evidence = result_from_execution("probe-001", attempt, execution)
    assert execution.timed_out is False
    assert result["outcome"] == "success"
    assert result["usage_complete"] is True
    assert evidence["jsonl_event_count"] == 4
