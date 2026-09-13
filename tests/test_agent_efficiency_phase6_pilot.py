"""Test the non-billed Phase 6 pilot launcher contract."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

import scripts.run_agent_efficiency_phase6_pilot as pilot
from scripts.agent_efficiency import phase0, provider_proxy
from scripts.agent_efficiency.campaign_state import CampaignStore, build_paired_schedule
from scripts.agent_efficiency.contracts import ContractError, load_document
from scripts.agent_efficiency.runner import write_proxy_relay
from scripts.run_agent_efficiency_phase6_pilot import (
    PilotExecutionContext,
    PilotLauncherError,
    build_pilot_plan,
    execution_controls,
    install_protected_asset,
    main,
    parse_fixture_sources,
    prepare_protected_fixture,
)


def _manifest() -> dict[str, object]:
    """Build one schema-valid public campaign manifest.

    Parameters
    ----------
    None

    Returns
    -------
    dict[str, object]
        Minimal campaign identity and enforceable execution ceilings.
    """

    return {
        "schema_version": "1.0",
        "campaign_id": "pilot-001",
        "fixture_fingerprints": {
            "codira-public": "a" * 64,
            "click-public": "b" * 64,
            "picomatch-public": "c" * 64,
        },
        "task_fingerprints": {
            "symbols-001": "d" * 64,
            "patch-001": "e" * 64,
            "documentation-001": "f" * 64,
        },
        "task_fixture_ids": {
            "symbols-001": "codira-public",
            "patch-001": "click-public",
            "documentation-001": "picomatch-public",
        },
        "budgets": {
            "max_total_tokens": 80000,
            "max_output_tokens": 12000,
            "timeout_seconds": 600,
        },
        "provider": {
            "name": "openrouter",
            "model": "openai/gpt-5.6-terra",
            "reasoning_effort": "medium",
            "wire_api": "responses",
            "max_prompt_usd_per_million": 2,
            "max_completion_usd_per_million": 12,
        },
        "accounting": {
            "max_daily_spend_usd": 2,
            "max_estimated_attempt_spend_usd": 0.3,
            "max_estimated_pilot_spend_usd": 1.8,
            "max_response_requests_per_attempt": 1,
        },
        "resource_controls": {
            "network": "none",
            "read_only_rootfs": True,
            "pids_limit": 512,
            "tmpfs_size_mib": 128,
        },
        "visibility": "public",
    }


def test_build_pilot_plan_has_three_complete_pairs() -> None:
    """Produce six deterministic attempts for the approved pilot cardinality.

    Parameters
    ----------
    None

    Returns
    -------
    None
        Assertions cover pair completeness and no execution authorization.
    """

    plan = build_pilot_plan(
        _manifest(), ("symbols-001", "patch-001", "documentation-001"), 7
    )
    assert plan["scheduled_execution_count"] == 6
    assert plan["execution_authorized"] is False
    attempts = plan["attempts"]
    assert isinstance(attempts, list)
    assert len(attempts) == 6


def test_checked_in_pilot_manifest_has_three_frozen_fixture_bindings() -> None:
    """Load the approved pilot manifest and verify its complete dry-run plan.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The checked-in public manifest produces the six planned executions.
    """

    manifest = load_document(
        Path("benchmarks/agent-efficiency/phase6-pilot.json"), "campaign"
    )
    plan = build_pilot_plan(
        manifest, ("symbols-001", "patch-001", "documentation-001"), 7
    )
    assert plan["scheduled_execution_count"] == 6


def test_pilot_launcher_rejects_execution_before_manifest_approval(
    tmp_path: Path,
) -> None:
    """Fail closed when an operator attempts paid execution prematurely.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary public manifest location.

    Returns
    -------
    None
        The launcher returns its deterministic disallowed-execution status.
    """

    manifest = tmp_path / "pilot.json"
    manifest.write_text(json.dumps(_manifest()), encoding="utf-8")
    assert (
        main(
            [
                "--campaign-manifest",
                str(manifest),
                "--task-id",
                "symbols-001",
                "--task-id",
                "patch-001",
                "--task-id",
                "documentation-001",
                "--seed",
                "7",
                "--execute",
            ]
        )
        == 2
    )


def test_pilot_launcher_rejects_wrong_task_cardinality(tmp_path: Path) -> None:
    """Reject any requested pilot other than three independent pairs.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary public manifest location.

    Returns
    -------
    None
        The launcher returns its deterministic invalid-plan status.
    """

    manifest = tmp_path / "pilot.json"
    manifest.write_text(json.dumps(_manifest()), encoding="utf-8")
    assert (
        main(
            [
                "--campaign-manifest",
                str(manifest),
                "--task-id",
                "symbols-001",
                "--task-id",
                "patch-001",
                "--seed",
                "7",
            ]
        )
        == 2
    )


def test_pilot_launcher_rejects_tasks_that_drift_from_manifest(tmp_path: Path) -> None:
    """Reject a three-task pilot whose identities differ from the manifest.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary public manifest location.

    Returns
    -------
    None
        The launcher returns its deterministic invalid-plan status.
    """

    manifest = tmp_path / "pilot.json"
    manifest.write_text(json.dumps(_manifest()), encoding="utf-8")
    assert (
        main(
            [
                "--campaign-manifest",
                str(manifest),
                "--task-id",
                "symbols-001",
                "--task-id",
                "patch-001",
                "--task-id",
                "architecture-001",
                "--seed",
                "7",
            ]
        )
        == 2
    )


def test_protected_patch_asset_has_verified_upstream_provenance(tmp_path: Path) -> None:
    """Install only the hash-verified grader-only Sentinel regression probe.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Fresh protected fixture destination.

    Returns
    -------
    None
        The installed asset records its upstream source without agent exposure.
    """

    protected = tmp_path / "protected"
    protected.mkdir()
    installed = install_protected_asset("patch-001", protected)
    assert installed is not None
    assert installed["source_commit"] == "f58ca3e81424a35626c8a475eb59ab95589008ce"
    assert (protected / "protected_sentinel_probe.py").is_file()


def test_fixture_sources_require_unique_absolute_bindings() -> None:
    """Reject ambiguous or relative host fixture source bindings.

    Parameters
    ----------
    None

    Returns
    -------
    None
        Invalid runner inputs fail before any provider interaction.
    """

    assert parse_fixture_sources(["click-public=/tmp/click"])["click-public"] == Path(
        "/tmp/click"
    )
    with pytest.raises(PilotLauncherError, match="unique"):
        parse_fixture_sources(["click-public=relative"])


def test_protected_asset_rejects_a_provenance_path_escape(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Reject a malformed protected-asset path before copying it.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary protected asset and destination roots.
    monkeypatch : pytest.MonkeyPatch
        Fixture replacing the reviewed protected asset root.

    Returns
    -------
    None
        Traversal metadata cannot write outside the protected fixture.
    """

    asset_root = tmp_path / "assets" / "patch-001"
    asset_root.mkdir(parents=True)
    (asset_root / "provenance.json").write_text(
        json.dumps({"asset_path": "../escape.py", "asset_sha256": "0" * 64}),
        encoding="utf-8",
    )
    monkeypatch.setattr(pilot, "PROTECTED_ASSET_ROOT", tmp_path / "assets")
    protected = tmp_path / "protected"
    protected.mkdir()
    with pytest.raises(PilotLauncherError, match="beneath"):
        install_protected_asset("patch-001", protected)


def test_execution_controls_reject_drift_before_attempt_side_effects() -> None:
    """Reject incomplete runtime controls without constructing an attempt.

    Parameters
    ----------
    None

    Returns
    -------
    None
        Required provider controls retain typed fail-closed validation.
    """

    manifest = _manifest()
    manifest["budgets"] = {"timeout_seconds": 600}
    with pytest.raises(PilotLauncherError, match="budget"):
        execution_controls(manifest)


def test_prepare_protected_fixture_rejects_git_clone_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Fail before grading when immutable protected checkout creation fails.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary source and destination paths.
    monkeypatch : pytest.MonkeyPatch
        Fixture replacing the Git subprocess result.

    Returns
    -------
    None
        Git preparation failure is a public-safe launcher error.
    """

    monkeypatch.setattr(shutil, "which", lambda _: "/usr/bin/git")
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 1, "", ""),
    )
    with pytest.raises(PilotLauncherError, match="immutable"):
        prepare_protected_fixture(tmp_path / "source", "a" * 40, tmp_path / "dest", "x")


def test_proxy_relay_configuration_binds_loopback_to_the_unix_socket(
    tmp_path: Path,
) -> None:
    """Keep credentialed provider forwarding on the mounted socket capability.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Fresh container state directory.

    Returns
    -------
    None
        The Codex provider URL and relay target form the reviewed bridge.
    """

    state = tmp_path / "state"
    phase0.write_isolated_codex_config(
        state,
        "/workspace",
        "http://127.0.0.1:43123/v1",
        ("openai/gpt-5.6-terra", "medium"),
        "codira-mcp",
    )
    relay = write_proxy_relay(state)
    assert 'base_url = "http://127.0.0.1:43123/v1"' in (
        state / "config.toml"
    ).read_text(encoding="utf-8")
    assert 'upstream.connect("/codex-state/provider.sock")' in relay.read_text(
        encoding="utf-8"
    )


def test_execute_attempt_records_an_oracle_contract_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Convert grader contract failure into one terminal immutable-safe result.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary campaign and disposable attempt roots.
    monkeypatch : pytest.MonkeyPatch
        Fixture replacing container, proxy, and fixture side effects.

    Returns
    -------
    None
        A malformed protected oracle becomes ``oracle_failure`` rather than an
        unhandled post-container exception.
    """

    store = CampaignStore(
        tmp_path / "campaign",
        "pilot-001",
        {"runner": "test"},
        build_paired_schedule(("patch-001",), 1, 1),
    )
    attempt = store.schedule[0]
    fixture = {"revision": "a" * 40}
    task = {
        "fixture_id": "click-public",
        "prompt": "test",
        "result_path": ".benchmark/result.json",
    }
    context = PilotExecutionContext(
        {"patch-001": task},
        {"patch-001": {"definition": {}}},
        {"click-public": fixture},
        {"click-public": tmp_path},
        "image@sha256:" + "a" * 64,
        "podman",
        "runner-only-token",
        _manifest(),
    )

    class Server:
        """Minimal disposable proxy server substitute.

        Parameters
        ----------
        None

        Returns
        -------
        None
            Methods model the proxy lifecycle without opening a socket.
        """

        def serve_forever(self) -> None:
            """Accept no requests in the synthetic execution.

            Parameters
            ----------
            None

            Returns
            -------
            None
            """

        def shutdown(self) -> None:
            """Model a clean proxy shutdown.

            Parameters
            ----------
            None

            Returns
            -------
            None
            """

        def server_close(self) -> None:
            """Model release of the synthetic proxy resource.

            Parameters
            ----------
            None

            Returns
            -------
            None
            """

    monkeypatch.setattr(
        pilot, "export_fixture", lambda source, revision, root: root.mkdir(parents=True)
    )
    monkeypatch.setattr(
        pilot,
        "prepare_protected_fixture",
        lambda source, revision, root, task_id: (root.mkdir(), None)[1],
    )
    monkeypatch.setattr(
        phase0,
        "write_isolated_codex_config",
        lambda root, *args: (root.mkdir(), root / "config.toml")[1],
    )
    monkeypatch.setattr(pilot, "write_proxy_relay", lambda root: root / "relay.py")
    monkeypatch.setattr(provider_proxy, "create_unix_server", lambda *args: Server())
    monkeypatch.setattr(
        pilot, "execute_container_attempt", lambda request: SimpleNamespace(stdout="")
    )
    monkeypatch.setattr(
        pilot,
        "result_from_execution",
        lambda campaign_id, scheduled, execution: (
            {
                "schema_version": "1.0",
                "campaign_id": campaign_id,
                "task_id": scheduled.task_id,
                "attempt_id": scheduled.attempt_id,
                "assistance_mode": scheduled.assistance_mode,
                "outcome": "success",
                "failure_class": None,
                "usage_complete": True,
                "usage": {
                    "input_tokens": 0,
                    "cached_input_tokens": 0,
                    "output_tokens": 0,
                    "reasoning_output_tokens": 0,
                },
                "provenance": {"runner": "test", "runner_version": "1.0"},
            },
            {},
        ),
    )
    monkeypatch.setattr(
        pilot,
        "evaluate_oracle",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            ContractError.message("malformed oracle")
        ),
    )

    result, evidence = pilot.execute_pilot_attempt(store, attempt, context)

    assert result["outcome"] == "oracle_failure"
    assert result["failure_class"] == "oracle_contract"
    assert evidence["oracle_passed"] is False
