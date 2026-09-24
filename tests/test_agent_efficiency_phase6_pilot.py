"""Test the non-billed Phase 6 pilot launcher contract."""

from __future__ import annotations

import json
import shutil
import subprocess
from datetime import UTC, datetime
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
    preflight_openrouter_route,
    prepare_protected_fixture,
    prompt_for_attempt,
    validate_prepared_index,
    validate_treatment_protocol,
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
            "max_completion_usd_per_million": 3,
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
        "runtime_image": "localhost/pilot@sha256:" + "a" * 64,
        "runtime_profile_fingerprint": "b" * 64,
        "treatment_protocol": {
            "version": "mcp-required-v1",
            "codira_mcp_instruction": (
                "Before completing this task, call the configured Codira MCP "
                "server at least once."
            ),
        },
        "visibility": "public",
    }


def test_prompt_for_attempt_requires_the_manifest_bound_mcp_instruction() -> None:
    """Expose Codira MCP only through the assisted treatment prompt.

    Parameters
    ----------
    None

    Returns
    -------
    None
        Assertions distinguish the baseline and assisted prompt constructions.
    """

    manifest = _manifest()
    task_prompt = "Write the required artifact."
    assert prompt_for_attempt(task_prompt, "baseline", manifest) == task_prompt
    assisted = prompt_for_attempt(task_prompt, "codira-mcp", manifest)
    assert assisted.endswith(task_prompt)
    assert "call the configured Codira MCP server" in assisted


def test_prompt_for_attempt_applies_common_verification_directives_to_both_arms() -> (
    None
):
    """Keep source-verification guidance identical across the paired arms.

    Parameters
    ----------
    None

    Returns
    -------
    None
        Both prompts carry the common instruction while MCP guidance remains
        confined to the assisted arm.
    """

    manifest = _manifest()
    protocol = manifest["treatment_protocol"]
    assert isinstance(protocol, dict)
    protocol.update(
        {
            "version": "mcp-required-v2",
            "agent_instruction": "Verify exact case-sensitive names from source.",
        }
    )
    baseline = prompt_for_attempt("Do the task.", "baseline", manifest)
    assisted = prompt_for_attempt("Do the task.", "codira-mcp", manifest)
    assert baseline.startswith("Verify exact case-sensitive names from source.")
    assert assisted.startswith(
        "Before completing this task, call the configured Codira MCP server"
    )
    assert "Verify exact case-sensitive names from source." in assisted
    protocol.pop("agent_instruction")
    with pytest.raises(PilotLauncherError, match="treatment protocol"):
        validate_treatment_protocol(manifest)


def test_treatment_protocol_rejects_a_missing_assisted_instruction() -> None:
    """Fail before paid execution when the treatment is not reproducible.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The missing treatment protocol raises a deterministic launcher error.
    """

    manifest = _manifest()
    manifest.pop("treatment_protocol")
    with pytest.raises(PilotLauncherError, match="treatment protocol"):
        validate_treatment_protocol(manifest)


def test_validate_prepared_index_rejects_empty_and_inconsistent_indexes(
    tmp_path: Path,
) -> None:
    """Reject the zero-file treatment defect before any provider setup.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary staged fixture and synthetic Codira metadata root.

    Returns
    -------
    None
        Only a non-empty consistent ready generation is admitted.
    """

    subprocess.run(("git", "init", "--quiet"), cwd=tmp_path, check=True)
    (tmp_path / "sample.py").write_text("value = 1\n", encoding="utf-8")
    subprocess.run(("git", "add", "--all"), cwd=tmp_path, check=True)
    state = tmp_path / ".codira"
    state.mkdir()
    (state / "metadata.json").write_text(
        json.dumps({"indexed_file_count": "0"}), encoding="utf-8"
    )
    generation = {
        "generation": 1,
        "state": "ready",
        "indexed_file_count": 0,
        "partial": False,
        "failed_file_count": 0,
    }
    (state / "index-generation.json").write_text(
        json.dumps(generation), encoding="utf-8"
    )
    with pytest.raises(PilotLauncherError, match="not usable"):
        validate_prepared_index(tmp_path)

    (state / "metadata.json").write_text(
        json.dumps({"indexed_file_count": "1"}), encoding="utf-8"
    )
    generation["indexed_file_count"] = 1
    (state / "index-generation.json").write_text(
        json.dumps(generation), encoding="utf-8"
    )
    assert validate_prepared_index(tmp_path) == {
        "tracked_file_count": 1,
        "indexed_file_count": 1,
        "generation": 1,
        "generation_state": "ready",
        "partial": False,
        "failed_file_count": 0,
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


def test_build_pilot_plan_rejects_a_task_outside_manifest_bindings() -> None:
    """Fail closed instead of indexing an unknown requested task identity.

    Parameters
    ----------
    None

    Returns
    -------
    None
        Assertions cover the public launcher error for task-selection drift.
    """

    with pytest.raises(PilotLauncherError, match="absent from manifest bindings"):
        build_pilot_plan(_manifest(), ("symbols-001", "patch-001", "unknown-001"), 7)


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
        Path("benchmarks/agent-efficiency/phase6-pilot-018.json"), "campaign"
    )
    plan = build_pilot_plan(
        manifest, ("symbols-001", "patch-001", "documentation-001"), 7
    )
    assert plan["scheduled_execution_count"] == 6
    assert plan["task_ids"] == ["documentation-001", "patch-001", "symbols-001"]
    assert plan["accounting"] == manifest["accounting"]
    assert plan["runtime_image"] == manifest["runtime_image"]
    assert plan["runtime_profile_fingerprint"] is None
    assert plan["fixture_fingerprints"] == manifest["fixture_fingerprints"]
    assert plan["task_fingerprints"] == manifest["task_fingerprints"]
    assert plan["task_fixture_ids"] == manifest["task_fixture_ids"]


def test_new_efficacy_pilot_manifest_binds_admitted_runtime_and_budget() -> None:
    """Require the renewed pilot to retain its exact runtime and cost controls.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The public manifest creates exactly three baseline/MCP pairs without
        authorizing an execution.
    """

    manifest = load_document(
        Path("benchmarks/agent-efficiency/codira-efficacy-pilot-001.json"),
        "campaign",
    )
    plan = build_pilot_plan(
        manifest, ("symbols-001", "patch-001", "documentation-001"), 20260919
    )

    assert plan["scheduled_execution_count"] == 6
    assert plan["execution_authorized"] is False
    assert manifest["runtime_profile_fingerprint"] == (
        "505d9aa2d761657199fa63de526dea33c1e4aacef030c2f45e3216526643f680"
    )
    assert manifest["provider"] == {
        "name": "openrouter",
        "model": "deepseek/deepseek-v4.1-flash-20260910",
        "reasoning_effort": "none",
        "wire_api": "responses",
        "max_prompt_usd_per_million": 0.15,
        "max_completion_usd_per_million": 0.6,
    }


def test_pilot_plan_rejects_an_invalid_runtime_image() -> None:
    """Reject a public plan that supplies an invalid runtime input.

    Parameters
    ----------
    None

    Returns
    -------
    None
        A malformed runtime image fails before the launcher can execute an attempt.
    """

    manifest = _manifest()
    manifest["runtime_image"] = "mutable-tag"
    with pytest.raises(PilotLauncherError, match="invalid runtime image"):
        build_pilot_plan(manifest, ("symbols-001", "patch-001", "documentation-001"), 7)


def test_pilot_plan_rejects_an_invalid_runtime_profile() -> None:
    """Reject a malformed profile identity before a paid execution is planned.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The malformed profile fingerprint is rejected by planning.
    """

    manifest = _manifest()
    manifest["runtime_profile_fingerprint"] = "not-a-sha256"

    with pytest.raises(PilotLauncherError, match="invalid runtime profile"):
        build_pilot_plan(manifest, ("symbols-001", "patch-001", "documentation-001"), 7)


def test_pilot_launcher_rejects_an_image_that_differs_from_the_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Fail before input preparation when the supplied runtime image drifts.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Disposable manifest and campaign state locations.
    monkeypatch : pytest.MonkeyPatch
        Fixture asserting that no paid-input preparation occurs.

    Returns
    -------
    None
        The launcher returns its deterministic mismatch status.
    """

    manifest = tmp_path / "pilot.json"
    manifest.write_text(json.dumps(_manifest()), encoding="utf-8")
    monkeypatch.setattr(
        pilot,
        "parse_fixture_sources",
        lambda values: pytest.fail("image mismatch must precede input preparation"),
    )
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
                "--state-root",
                str(tmp_path / "state"),
                "--image",
                "localhost/other@sha256:" + "b" * 64,
                "--execute",
            ]
        )
        == 2
    )


def test_pilot_launcher_requires_a_manifest_runtime_image(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Reject historical manifests before fixture preparation or credential access.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Disposable manifest and campaign state locations.
    monkeypatch : pytest.MonkeyPatch
        Fixture asserting that no paid-input preparation occurs.

    Returns
    -------
    None
        Paid execution cannot use a manifest without a bound runtime image.
    """

    manifest_data = _manifest()
    manifest_data.pop("runtime_image")
    manifest = tmp_path / "pilot.json"
    manifest.write_text(json.dumps(manifest_data), encoding="utf-8")
    monkeypatch.setattr(
        pilot,
        "parse_fixture_sources",
        lambda values: pytest.fail("missing image must precede input preparation"),
    )
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
                "--state-root",
                str(tmp_path / "state"),
                "--image",
                "localhost/pilot@sha256:" + "a" * 64,
                "--execute",
            ]
        )
        == 2
    )


def test_pilot_launcher_rejects_an_invalid_manifest_runtime_image(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Reject a malformed runtime image before paid-input preparation.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Disposable manifest and campaign state locations.
    monkeypatch : pytest.MonkeyPatch
        Fixture asserting that no paid-input preparation occurs.

    Returns
    -------
    None
        Paid execution cannot use a mutable or malformed image reference.
    """

    manifest_data = _manifest()
    manifest_data["runtime_image"] = "mutable-tag"
    manifest = tmp_path / "pilot.json"
    manifest.write_text(json.dumps(manifest_data), encoding="utf-8")
    monkeypatch.setattr(
        pilot,
        "parse_fixture_sources",
        lambda values: pytest.fail("invalid image must precede input preparation"),
    )
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
                "--state-root",
                str(tmp_path / "state"),
                "--image",
                "mutable-tag",
                "--execute",
            ]
        )
        == 2
    )


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


def test_execution_controls_reject_an_unfunded_token_ceiling() -> None:
    """Reject accounting that cannot cover the configured maximum token spend.

    Parameters
    ----------
    None

    Returns
    -------
    None
        Price and token ceilings must fit within both attempt and pilot budgets.
    """

    manifest = _manifest()
    accounting = manifest["accounting"]
    assert isinstance(accounting, dict)
    accounting["max_estimated_attempt_spend_usd"] = 0.1

    with pytest.raises(PilotLauncherError, match="accounting"):
        execution_controls(manifest)


def test_execution_controls_account_whole_session_tokens_once() -> None:
    """Admit the approved whole-session ceiling with continuation headroom.

    Parameters
    ----------
    None

    Returns
    -------
    None
        Assertions cover the approved token scope, limits, and spend caps.
    """

    manifest = _manifest()
    provider = manifest["provider"]
    budgets = manifest["budgets"]
    accounting = manifest["accounting"]
    assert isinstance(provider, dict)
    assert isinstance(budgets, dict)
    assert isinstance(accounting, dict)
    provider.update(
        {
            "max_prompt_usd_per_million": 0.15,
            "max_completion_usd_per_million": 0.6,
        }
    )
    budgets["max_total_tokens"] = 240000
    accounting.update(
        {
            "max_total_tokens_scope": "whole-session",
            "max_response_requests_per_attempt": 10,
            "max_transport_attempts_per_response": 2,
            "max_daily_spend_usd": 6,
            "max_estimated_attempt_spend_usd": 0.18,
            "max_estimated_pilot_spend_usd": 1.08,
        }
    )

    controls = execution_controls(manifest)

    assert controls.max_total_tokens == 240000
    assert controls.max_total_tokens_scope == "whole-session"
    assert controls.max_response_requests == 10
    assert controls.max_transport_attempts_per_response == 2
    accounting.pop("max_total_tokens_scope")
    with pytest.raises(PilotLauncherError, match="accounting"):
        execution_controls(manifest)


def test_preflight_admits_only_the_exact_route_and_scoped_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Record public and authenticated route admission without a completion.

    Parameters
    ----------
    monkeypatch : pytest.MonkeyPatch
        Replaces the three fixed OpenRouter metadata endpoints.

    Returns
    -------
    None
        The public-safe record retains route capabilities and budget only.
    """

    manifest = _manifest()
    provider = manifest["provider"]
    budgets = manifest["budgets"]
    accounting = manifest["accounting"]
    assert isinstance(provider, dict)
    assert isinstance(budgets, dict)
    assert isinstance(accounting, dict)
    provider.update(
        {
            "model": "deepseek/deepseek-v4.1-flash-20260910",
            "reasoning_effort": "none",
            "max_prompt_usd_per_million": 0.15,
            "max_completion_usd_per_million": 0.6,
        }
    )
    budgets.update({"max_total_tokens": 500000, "max_output_tokens": 32000})
    accounting.update(
        {
            "max_daily_spend_usd": 6,
            "max_estimated_attempt_spend_usd": 0.3,
            "max_estimated_pilot_spend_usd": 1.8,
        }
    )
    model = {
        "id": provider["model"],
        "pricing": {
            "prompt": "0.00000015",
            "completion": "0.0000006",
            "overrides": [
                {
                    "utc_days": ["saturday", "sunday"],
                    "prompt": "0.00000015",
                    "completion": "0.0000006",
                },
                {
                    "utc_days": [
                        "monday",
                        "tuesday",
                        "wednesday",
                        "thursday",
                        "friday",
                    ],
                    "utc_start": 100,
                    "utc_end": 400,
                    "prompt": "0.0000003",
                    "completion": "0.0000012",
                },
            ],
        },
        "supported_parameters": ["tools", "reasoning"],
        "top_provider": {"max_completion_tokens": 393216},
        "context_length": 204800,
    }

    class Response:
        """Return one deterministic JSON body through the HTTP context API.

        Parameters
        ----------
        document : dict[str, object]
            Synthetic OpenRouter response body.
        """

        def __init__(self, document: dict[str, object]) -> None:
            self.document = document

        def __enter__(self) -> Response:
            return self

        def __exit__(self, *arguments: object) -> None:
            return None

        def read(self) -> bytes:
            return json.dumps(self.document).encode("utf-8")

    responses = [
        Response({"data": [model]}),
        Response({"data": [model]}),
        Response(
            {
                "data": {
                    "limit": 6,
                    "limit_remaining": 5.75,
                    "usage_daily": 0.25,
                    "limit_reset": "2026-09-20T00:00:00Z",
                }
            }
        ),
    ]
    monkeypatch.setattr(pilot, "urlopen", lambda *arguments, **kwargs: responses.pop(0))

    record = preflight_openrouter_route(
        manifest,
        execution_controls(manifest),
        "scoped-token",
        now_utc=datetime(2026, 9, 20, 12, tzinfo=UTC),
    )

    assert record["model"] == provider["model"]
    assert record["accounting"] == {
        "max_total_tokens": 500000,
        "max_total_tokens_scope": "per-continuation",
        "max_response_requests_per_attempt": 1,
        "max_transport_attempts_per_response": 1,
        "max_estimated_attempt_spend_usd": 0.3,
        "max_estimated_pilot_spend_usd": 1.8,
        "max_daily_spend_usd": 6.0,
    }
    assert record["public_route"] == {
        "context_length": 204800,
        "max_completion_tokens": 393216,
        "max_prompt_usd_per_million": 0.15,
        "max_completion_usd_per_million": 0.6,
        "pricing_window": {
            "kind": "override",
            "utc_days": ["saturday", "sunday"],
        },
        "supported_parameters": ["reasoning", "tools"],
    }
    assert record["key_budget"] == {
        "limit_usd": 6.0,
        "limit_remaining_usd": 5.75,
        "limit_reset": "2026-09-20T00:00:00Z",
        "usage_daily_usd": 0.25,
    }


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


def test_baseline_configuration_excludes_codira_mcp(tmp_path: Path) -> None:
    """Expose the provider proxy without MCP access to the baseline variant.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Fresh per-attempt Codex state directory.

    Returns
    -------
    None
        Baseline TOML has the fixed provider but no MCP-server declaration.
    """

    state = tmp_path / "state"
    phase0.write_isolated_codex_config(
        state,
        "/workspace",
        "http://127.0.0.1:43123/v1",
        ("openai/gpt-5.6-terra", "medium"),
        None,
    )
    configuration = (state / "config.toml").read_text(encoding="utf-8")
    assert 'base_url = "http://127.0.0.1:43123/v1"' in configuration
    assert "[mcp_servers.codira]" not in configuration


@pytest.mark.parametrize(
    ("assistance_mode", "expected_mcp_command"),
    (("baseline", None), ("codira-mcp", pilot.BENCHMARK_MCP_COMMAND)),
)
def test_execute_attempt_records_an_oracle_contract_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    assistance_mode: str,
    expected_mcp_command: str | None,
) -> None:
    """Convert grader contract failure into one terminal immutable-safe result.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary campaign and disposable attempt roots.
    monkeypatch : pytest.MonkeyPatch
        Fixture replacing container, proxy, and fixture side effects.
    assistance_mode : str
        Parametrized baseline or Codira MCP treatment identity.
    expected_mcp_command : str or None
        Expected configured MCP executable for the selected treatment.

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
        build_paired_schedule(("documentation-001",), 1, 1),
    )
    attempt = next(
        item for item in store.schedule if item.assistance_mode == assistance_mode
    )
    fixture = {"revision": "a" * 40}
    temp_root = tmp_path
    monkeypatch.setattr(pilot, "PROJECT_TEMP_ROOT", temp_root)
    proxy_paths: list[Path] = []

    task = {
        "fixture_id": "click-public",
        "prompt": "test",
        "result_path": ".benchmark/result.json",
        "result_format": "workspace-diff",
    }
    context = PilotExecutionContext(
        {"documentation-001": task},
        {"documentation-001": {"definition": {}}},
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

    def export_fixture(source: Path, revision: str, root: Path) -> None:
        """Create a fixture with a dangling prepared-environment interpreter."""

        del source, revision
        interpreter = root / ".venv" / "bin" / "python"
        interpreter.parent.mkdir(parents=True)
        interpreter.symlink_to("/nonexistent-python")

    monkeypatch.setattr(pilot, "export_fixture", export_fixture)
    monkeypatch.setattr(
        pilot,
        "fixture_environment",
        lambda root, fixture_id: SimpleNamespace(
            ecosystem="uv", directive="environment ready"
        ),
    )
    monkeypatch.setattr(
        pilot,
        "execute_environment_preparation",
        lambda request: SimpleNamespace(
            elapsed_seconds=0.1, returncode=0, timed_out=False
        ),
    )
    monkeypatch.setattr(
        pilot,
        "fixture_environment",
        lambda root, fixture_id: SimpleNamespace(
            ecosystem="uv", directive="environment ready"
        ),
    )
    monkeypatch.setattr(
        pilot,
        "execute_environment_preparation",
        lambda request: SimpleNamespace(
            elapsed_seconds=0.1, returncode=0, timed_out=False
        ),
    )
    monkeypatch.setattr(
        pilot,
        "prepare_protected_fixture",
        lambda source, revision, root, task_id: (root.mkdir(), None)[1],
    )
    monkeypatch.setattr(
        pilot,
        "execute_index_preparation",
        lambda request: SimpleNamespace(
            elapsed_seconds=0.1,
            returncode=0,
            timed_out=False,
            stdout="Indexed: 1",
            stderr="",
        ),
    )
    monkeypatch.setattr(
        pilot,
        "validate_prepared_index",
        lambda root: {
            "tracked_file_count": 1,
            "indexed_file_count": 1,
            "generation": 1,
            "generation_state": "ready",
            "partial": False,
            "failed_file_count": 0,
        },
    )
    mcp_commands: list[str | None] = []

    def write_config(root: Path, *arguments: object) -> Path:
        """Record the MCP selection without writing a real configuration.

        Parameters
        ----------
        root : pathlib.Path
            Synthetic per-attempt state root.
        arguments : object
            Positional configuration controls passed by the pilot runner.

        Returns
        -------
        pathlib.Path
            Synthetic configuration path.
        """

        command = arguments[-1] if arguments else None
        assert command is None or isinstance(command, str)
        mcp_commands.append(command)
        root.mkdir()
        return root / "config.toml"

    monkeypatch.setattr(phase0, "write_isolated_codex_config", write_config)
    monkeypatch.setattr(pilot, "write_proxy_relay", lambda root: root / "relay.py")

    def create_server(
        settings: provider_proxy.ProxySettings, socket_path: str
    ) -> Server:
        """Capture the disposable socket path used for this attempt.

        Parameters
        ----------
        settings : provider_proxy.ProxySettings
            Validated proxy settings supplied by the pilot.
        socket_path : str
            Host Unix socket path supplied to the proxy server.

        Returns
        -------
        Server
            Synthetic proxy server used by the test.
        """

        del settings
        proxy_paths.append(Path(socket_path))
        return Server()

    monkeypatch.setattr(provider_proxy, "create_unix_server", create_server)
    monkeypatch.setattr(
        pilot, "execute_container_attempt", lambda request: SimpleNamespace(stdout="")
    )
    monkeypatch.setattr(
        pilot,
        "result_from_execution",
        lambda campaign_id, scheduled, execution, **_kwargs: (
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
    monkeypatch.setattr(pilot, "capture_workspace_patch", lambda *args: None)
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
    assert result["operational_calibration"] == {
        "status": "passed",
        "failure_class": None,
    }
    assert result["task_oracle"] == {
        "status": "failed",
        "failure_class": "oracle_contract",
        "fingerprint": None,
    }
    assert evidence["oracle_passed"] is False
    assert mcp_commands == [expected_mcp_command]
    assert len(proxy_paths) == 1
    assert proxy_paths[0].parent.parent == temp_root
    assert proxy_paths[0].name == "p.sock"
    assert not proxy_paths[0].parent.exists()
    assert (
        store.root / "attempt-work" / attempt.attempt_id / "provider-responses"
    ).is_dir()
    assert not (
        store.root / "attempt-work" / attempt.attempt_id / "workspace-before" / ".venv"
    ).exists()
