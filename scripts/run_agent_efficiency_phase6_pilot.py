#!/usr/bin/env python3
"""Run the bounded, resumable Issue #53 Phase 6 pilot.

The public manifest is validated before the runner reads its OpenRouter
credential. Agent containers receive only a fresh proxy token and an exported
fixture; protected graders receive a separate immutable checkout.
"""
# ruff: noqa: C901, EM101, EM102, TRY003, TRY004, TRY301

from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import shutil
import subprocess
import sys
import tempfile
import threading
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import cast
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.agent_efficiency import phase0, provider_proxy
from scripts.agent_efficiency.campaign_state import (
    CampaignStore,
    ScheduledAttempt,
    build_paired_schedule,
    run_pending,
)
from scripts.agent_efficiency.contracts import (
    ContractError,
    canonical_fingerprint,
    load_document,
)
from scripts.agent_efficiency.corpus import export_fixture, verify_fixture
from scripts.agent_efficiency.environment import (
    EnvironmentPreparationError,
    fixture_environment,
)
from scripts.agent_efficiency.oracles import evaluate_oracle
from scripts.agent_efficiency.runner import (
    ContainerAttemptRequest,
    EnvironmentPreparationRequest,
    IndexPreparationRequest,
    capture_workspace_patch,
    execute_container_attempt,
    execute_environment_preparation,
    execute_index_preparation,
    result_from_execution,
    write_proxy_relay,
)

BENCHMARK_ROOT = Path("benchmarks/agent-efficiency")
PROJECT_TEMP_ROOT = Path("/home/marco/Personalia/Progetti/.Temp")
PROTECTED_ASSET_ROOT = BENCHMARK_ROOT / "protected"
BENCHMARK_CODIRA_CONFIG = "/opt/codira/benchmark-codira.toml"
BENCHMARK_MCP_COMMAND = "/opt/codira/codira-mcp-benchmark"
BENCHMARK_CODIRA_PROFILE = Path("scripts/agent_efficiency/benchmark-codira.toml")
OPENROUTER_MODELS_URL = "https://openrouter.ai/api/v1/models"
OPENROUTER_USER_MODELS_URL = "https://openrouter.ai/api/v1/models/user"
OPENROUTER_KEY_URL = "https://openrouter.ai/api/v1/key"
GIT_EXECUTABLE = shutil.which("git")


def runtime_profile_fingerprint() -> str:
    """Return the identity of the Codira profile used by assisted attempts.

    Parameters
    ----------
    None

    Returns
    -------
    str
        SHA-256 digest of the exact profile copied into every assisted fixture.
    """

    return hashlib.sha256(BENCHMARK_CODIRA_PROFILE.read_bytes()).hexdigest()


def validate_prepared_index(root: Path) -> dict[str, object]:
    """Validate one assisted fixture index before provider setup.

    Parameters
    ----------
    root : pathlib.Path
        History-free staged fixture containing a completed Codira index.

    Returns
    -------
    dict[str, object]
        Public-safe tracked-file and index-generation evidence.

    Raises
    ------
    PilotLauncherError
        If Git has no staged baseline or the Codira index is empty, partial,
        failed, implausibly large, or internally inconsistent.
    """

    if GIT_EXECUTABLE is None:
        raise PilotLauncherError("Git is unavailable for index validation")
    try:
        tracked = subprocess.run(
            (GIT_EXECUTABLE, "ls-files", "--cached", "-z"),
            cwd=root,
            check=True,
            capture_output=True,
        ).stdout
        tracked_file_count = len([item for item in tracked.split(b"\0") if item])
        metadata = json.loads(
            (root / ".codira" / "metadata.json").read_text(encoding="utf-8")
        )
        generation = json.loads(
            (root / ".codira" / "index-generation.json").read_text(encoding="utf-8")
        )
        indexed_file_count = int(metadata["indexed_file_count"])
        generation_indexed_file_count = int(generation["indexed_file_count"])
    except (
        KeyError,
        OSError,
        TypeError,
        ValueError,
        json.JSONDecodeError,
        subprocess.CalledProcessError,
    ) as error:
        raise PilotLauncherError(
            "Codira index preparation evidence is invalid"
        ) from error
    if (
        tracked_file_count < 1
        or indexed_file_count < 1
        or indexed_file_count > tracked_file_count
        or generation_indexed_file_count != indexed_file_count
        or generation.get("state") != "ready"
        or generation.get("partial") is not False
        or generation.get("failed_file_count") != 0
    ):
        raise PilotLauncherError("Codira index preparation is not usable")
    return {
        "tracked_file_count": tracked_file_count,
        "indexed_file_count": indexed_file_count,
        "generation": generation.get("generation"),
        "generation_state": generation.get("state"),
        "partial": generation.get("partial"),
        "failed_file_count": generation.get("failed_file_count"),
    }


class PilotLauncherError(ValueError):
    """Report a deterministic, non-secret Phase 6 pilot failure.

    Parameters
    ----------
    detail : str
        Public-safe validation or execution failure.

    Returns
    -------
    None
        The exception carries the stable failure detail.
    """


@dataclass(frozen=True)
class PilotExecutionContext:
    """Collect immutable dependencies needed to execute one pilot attempt.

    Parameters
    ----------
    tasks, oracles, fixtures : Mapping[str, Mapping[str, object]]
        Validated public records bound to the approved manifest.
    sources : Mapping[str, pathlib.Path]
        Verified local immutable fixture checkouts.
    image : str
        Digest-pinned benchmark image.
    runtime : str
        Supported container runtime.
    upstream_token : str
        Runner-only provider credential, never persisted.
    manifest : Mapping[str, object]
        Approved execution controls.
    provider_context_length : int or None, optional
        Context size from the immediately preceding authenticated route
        preflight; absent only in deterministic unit-test contexts.

    Returns
    -------
    None
        Instances are immutable per-process runner dependencies.
    """

    tasks: Mapping[str, Mapping[str, object]]
    oracles: Mapping[str, Mapping[str, object]]
    fixtures: Mapping[str, Mapping[str, object]]
    sources: Mapping[str, Path]
    image: str
    runtime: str
    upstream_token: str
    manifest: Mapping[str, object]
    provider_context_length: int | None = None


@dataclass(frozen=True)
class ExecutionControls:
    """Hold validated scalar execution controls from the approved manifest.

    Parameters
    ----------
    model, reasoning_effort : str
        Exact provider settings fixed for the pilot.
    max_prompt_price, max_completion_price : float
        Positive OpenRouter price ceilings per million tokens.
    max_total_tokens : int
        Positive token ceiling with scope declared by
        ``max_total_tokens_scope``.
    max_total_tokens_scope : str
        Whether the total-token ceiling covers the whole agent session or each
        logical continuation for conservative legacy accounting.
    max_output_tokens, timeout_seconds, max_response_requests : int
        Positive output, time, and provider-request ceilings.
    max_daily_spend, max_attempt_spend, max_pilot_spend : float
        Positive bounded accounting controls in USD.

    Returns
    -------
    None
        Instances are typed immutable values safe to use after validation.
    """

    model: str
    reasoning_effort: str
    max_prompt_price: float
    max_completion_price: float
    max_total_tokens: int
    max_total_tokens_scope: str
    max_output_tokens: int
    timeout_seconds: int
    max_response_requests: int
    max_transport_attempts_per_response: int
    max_daily_spend: float
    max_attempt_spend: float
    max_pilot_spend: float


def _openrouter_json(request: Request, detail: str) -> Mapping[str, object]:
    """Fetch a JSON object from the fixed OpenRouter admission endpoints.

    Parameters
    ----------
    request : urllib.request.Request
        Fixed public or authenticated metadata request without a request body.
    detail : str
        Public-safe failure category for transport or JSON decoding errors.

    Returns
    -------
    collections.abc.Mapping[str, object]
        Parsed OpenRouter response object.

    Raises
    ------
    PilotLauncherError
        If the endpoint fails, emits invalid JSON, or returns a non-object.
    """

    try:
        with urlopen(request, timeout=30) as response:
            document = json.loads(response.read())
    except HTTPError as error:
        raise PilotLauncherError(f"{detail}: HTTP {error.code}") from error
    except (OSError, URLError, json.JSONDecodeError) as error:
        raise PilotLauncherError(detail) from error
    if not isinstance(document, Mapping):
        raise PilotLauncherError(f"{detail}: malformed response")
    return document


def _model_catalog(
    document: Mapping[str, object],
) -> Mapping[str, Mapping[str, object]]:
    """Return the model-ID mapping from one OpenRouter catalog document.

    Parameters
    ----------
    document : collections.abc.Mapping[str, object]
        Parsed public or authenticated OpenRouter catalog object.

    Returns
    -------
    collections.abc.Mapping[str, collections.abc.Mapping[str, object]]
        Exact model IDs mapped to their public-safe metadata.

    Raises
    ------
    PilotLauncherError
        If the catalog does not expose a model list.
    """

    entries = document.get("data")
    if not isinstance(entries, list):
        raise PilotLauncherError("OpenRouter model catalog is malformed")
    return {
        identifier: entry
        for entry in entries
        if isinstance(entry, Mapping)
        and isinstance((identifier := entry.get("id")), str)
    }


def _active_pricing(
    pricing: Mapping[str, object], now_utc: datetime | None = None
) -> tuple[Mapping[str, object], dict[str, object]]:
    """Return the one published UTC pricing window active at admission time.

    Parameters
    ----------
    pricing : collections.abc.Mapping[str, object]
        OpenRouter model pricing with optional UTC weekday overrides.
    now_utc : datetime.datetime or None, optional
        UTC instant used for deterministic window selection. ``None`` uses the
        current UTC time.

    Returns
    -------
    tuple[collections.abc.Mapping[str, object], dict[str, object]]
        Active pricing mapping and a public-safe selected-window record.

    Raises
    ------
    PilotLauncherError
        If pricing overrides are malformed, overlap, or cannot be interpreted.
    """

    overrides = pricing.get("overrides", [])
    if not isinstance(overrides, list):
        raise PilotLauncherError("OpenRouter model pricing overrides are malformed")
    instant = now_utc or datetime.now(UTC)
    if instant.tzinfo is None or instant.utcoffset() != UTC.utcoffset(instant):
        raise PilotLauncherError("OpenRouter pricing instant must be UTC")
    minute = instant.hour * 60 + instant.minute
    weekday = instant.strftime("%A").lower()
    selected: list[Mapping[str, object]] = []
    for override in overrides:
        if not isinstance(override, Mapping):
            raise PilotLauncherError("OpenRouter model pricing overrides are malformed")
        raw_days = override.get("utc_days")
        raw_start = override.get("utc_start")
        raw_end = override.get("utc_end")
        if not isinstance(raw_days, list) or not all(
            isinstance(day, str) for day in raw_days
        ):
            raise PilotLauncherError("OpenRouter model pricing overrides are malformed")
        days = tuple(day.lower() for day in raw_days)
        if raw_start is None and raw_end is None:
            in_window = True
        elif (
            isinstance(raw_start, int)
            and not isinstance(raw_start, bool)
            and isinstance(raw_end, int)
            and not isinstance(raw_end, bool)
        ):
            start = _utc_hhmm_minutes(raw_start)
            end = _utc_hhmm_minutes(raw_end)
            in_window = (
                start <= minute < end
                if start < end
                else minute >= start or minute < end
            )
        else:
            raise PilotLauncherError("OpenRouter model pricing overrides are malformed")
        if weekday in days and in_window:
            selected.append(override)
    if len(selected) > 1:
        raise PilotLauncherError("OpenRouter model pricing windows overlap")
    if not selected:
        return pricing, {"kind": "base"}
    override = selected[0]
    window: dict[str, object] = {
        "kind": "override",
        "utc_days": list(cast("list[str]", override["utc_days"])),
    }
    if "utc_start" in override:
        window["utc_start"] = cast("int", override["utc_start"])
        window["utc_end"] = cast("int", override["utc_end"])
    return override, window


def _utc_hhmm_minutes(value: int) -> int:
    """Convert an OpenRouter integer UTC ``HHMM`` value to minutes after midnight.

    Parameters
    ----------
    value : int
        Integer UTC clock value without a colon.

    Returns
    -------
    int
        Minute offset in the inclusive range zero through 1,439.

    Raises
    ------
    PilotLauncherError
        If the value is not a valid UTC ``HHMM`` clock value.
    """

    hour, minute = divmod(value, 100)
    if value < 0 or hour > 23 or minute > 59:
        raise PilotLauncherError("OpenRouter pricing window is malformed")
    return hour * 60 + minute


def _token_price(pricing: Mapping[str, object], field: str) -> float:
    """Return one positive per-token price from the active OpenRouter window.

    Parameters
    ----------
    pricing : collections.abc.Mapping[str, object]
        Active base or override price mapping.
    field : str
        Required ``prompt`` or ``completion`` price field.

    Returns
    -------
    float
        Positive per-token price before conversion to per-million units.

    Raises
    ------
    PilotLauncherError
        If the selected window omits or corrupts a required price.
    """

    value = pricing.get(field)
    if not isinstance(value, str | int | float) or isinstance(value, bool):
        raise PilotLauncherError("OpenRouter model price is unavailable")
    try:
        result = float(value)
    except ValueError as error:
        raise PilotLauncherError("OpenRouter model price is malformed") from error
    if result <= 0:
        raise PilotLauncherError("OpenRouter model price is unavailable")
    return result


def preflight_openrouter_route(
    manifest: Mapping[str, object],
    controls: ExecutionControls,
    token: str,
    *,
    now_utc: datetime | None = None,
) -> dict[str, object]:
    """Verify the exact agent route and scoped key without a completion request.

    Parameters
    ----------
    manifest : collections.abc.Mapping[str, object]
        Frozen pilot manifest whose fingerprint is persisted in the result.
    controls : ExecutionControls
        Validated model, price, token, and accounting ceilings.
    token : str
        Scoped OpenRouter key supplied only through the approved SOPS child.
    now_utc : datetime.datetime or None, optional
        UTC instant used for deterministic pricing-window admission in tests.

    Returns
    -------
    dict[str, object]
        Public-safe model and key-budget admission record.

    Raises
    ------
    PilotLauncherError
        If the public route, key-visible route, price, capability, or budget
        differs from the frozen manifest.
    """

    public_catalog = _model_catalog(
        _openrouter_json(
            Request(OPENROUTER_MODELS_URL, method="GET"),
            "cannot fetch public OpenRouter catalog",
        )
    )
    public_model = public_catalog.get(controls.model)
    if not isinstance(public_model, Mapping):
        raise PilotLauncherError("frozen OpenRouter model is unavailable")
    pricing = public_model.get("pricing")
    parameters = public_model.get("supported_parameters")
    top_provider = public_model.get("top_provider")
    context_length = public_model.get("context_length")
    max_completion_tokens = (
        top_provider.get("max_completion_tokens")
        if isinstance(top_provider, Mapping)
        else None
    )
    if (
        not isinstance(pricing, Mapping)
        or not isinstance(parameters, list)
        or not {"tools", "reasoning"}.issubset(parameters)
        or not isinstance(top_provider, Mapping)
        or not isinstance(context_length, int)
        or context_length < controls.max_output_tokens
        or not isinstance(max_completion_tokens, int)
        or max_completion_tokens < controls.max_output_tokens
    ):
        raise PilotLauncherError("public OpenRouter model contract is incomplete")
    active_pricing, pricing_window = _active_pricing(pricing, now_utc)
    prompt_price = _token_price(active_pricing, "prompt") * 1_000_000
    completion_price = _token_price(active_pricing, "completion") * 1_000_000
    if (
        prompt_price > controls.max_prompt_price
        or completion_price > controls.max_completion_price
    ):
        raise PilotLauncherError("OpenRouter model price exceeds the frozen ceiling")

    authenticated_catalog = _model_catalog(
        _openrouter_json(
            Request(
                OPENROUTER_USER_MODELS_URL,
                headers={"Authorization": f"Bearer {token}"},
                method="GET",
            ),
            "cannot fetch authenticated OpenRouter catalog",
        )
    )
    authenticated_model = authenticated_catalog.get(controls.model)
    authenticated_parameters = (
        authenticated_model.get("supported_parameters")
        if isinstance(authenticated_model, Mapping)
        else None
    )
    if not isinstance(authenticated_parameters, list) or not {
        "tools",
        "reasoning",
    }.issubset(authenticated_parameters):
        raise PilotLauncherError("scoped key cannot admit the frozen model route")

    budget_payload = _openrouter_json(
        Request(
            OPENROUTER_KEY_URL,
            headers={"Authorization": f"Bearer {token}"},
            method="GET",
        ),
        "cannot fetch scoped OpenRouter key budget",
    )
    budget = budget_payload.get("data")
    if not isinstance(budget, Mapping):
        raise PilotLauncherError("scoped OpenRouter key budget is malformed")
    limit = budget.get("limit")
    remaining = budget.get("limit_remaining")
    daily_usage = budget.get("usage_daily")
    reset = budget.get("limit_reset")
    if (
        not isinstance(limit, int | float)
        or not isinstance(remaining, int | float)
        or not isinstance(daily_usage, int | float)
        or isinstance(limit, bool)
        or isinstance(remaining, bool)
        or isinstance(daily_usage, bool)
        or limit > controls.max_daily_spend
        or remaining < controls.max_pilot_spend
        or (reset is not None and not isinstance(reset, str))
    ):
        raise PilotLauncherError("scoped OpenRouter key budget is insufficient")
    return {
        "campaign_id": manifest["campaign_id"],
        "manifest_fingerprint": canonical_fingerprint(manifest),
        "model": controls.model,
        "reasoning_effort": controls.reasoning_effort,
        "accounting": {
            "max_total_tokens": controls.max_total_tokens,
            "max_total_tokens_scope": controls.max_total_tokens_scope,
            "max_response_requests_per_attempt": controls.max_response_requests,
            "max_transport_attempts_per_response": (
                controls.max_transport_attempts_per_response
            ),
            "max_estimated_attempt_spend_usd": controls.max_attempt_spend,
            "max_estimated_pilot_spend_usd": controls.max_pilot_spend,
            "max_daily_spend_usd": controls.max_daily_spend,
        },
        "public_route": {
            "context_length": context_length,
            "max_completion_tokens": top_provider.get("max_completion_tokens"),
            "max_prompt_usd_per_million": prompt_price,
            "max_completion_usd_per_million": completion_price,
            "pricing_window": pricing_window,
            "supported_parameters": sorted(str(value) for value in parameters),
        },
        "authenticated_route": {
            "supported_parameters": sorted(
                str(value) for value in authenticated_parameters
            )
        },
        "key_budget": {
            "limit_usd": float(limit),
            "limit_remaining_usd": float(remaining),
            "limit_reset": reset,
            "usage_daily_usd": float(daily_usage),
        },
    }


def prompt_for_attempt(
    task_prompt: str, assistance_mode: str, manifest: Mapping[str, object]
) -> str:
    """Bind the approved treatment instruction to an agent invocation.

    Parameters
    ----------
    task_prompt : str
        Frozen public task prompt shared by both variants.
    assistance_mode : str
        Scheduled treatment identity.
    manifest : collections.abc.Mapping[str, object]
        Approved campaign manifest containing the treatment protocol.

    Returns
    -------
    str
        Common protocol guidance plus the public task prompt, with the
        assisted-only Codira instruction prepended for the treatment arm.

    Raises
    ------
    PilotLauncherError
        If the manifest lacks a valid treatment protocol.
    """

    protocol = manifest.get("treatment_protocol")
    if not isinstance(protocol, Mapping):
        raise PilotLauncherError("campaign treatment protocol is invalid")
    version = protocol.get("version")
    instruction = protocol.get("codira_mcp_instruction")
    common_instruction = protocol.get("agent_instruction")
    if (
        not isinstance(version, str)
        or not version
        or not isinstance(instruction, str)
        or not instruction.strip()
    ):
        raise PilotLauncherError("campaign treatment protocol is invalid")
    if common_instruction is not None and (
        not isinstance(common_instruction, str) or not common_instruction.strip()
    ):
        raise PilotLauncherError("campaign treatment protocol is invalid")
    if version == "mcp-required-v2" and not isinstance(common_instruction, str):
        raise PilotLauncherError("campaign treatment protocol is invalid")
    task = task_prompt
    if isinstance(common_instruction, str):
        task = f"{common_instruction.strip()}\n\n{task}"
    if assistance_mode == "baseline":
        return task
    if assistance_mode == "codira-mcp":
        return f"{instruction.strip()}\n\n{task}"
    raise PilotLauncherError("scheduled assistance mode is invalid")


def validate_treatment_protocol(manifest: Mapping[str, object]) -> None:
    """Reject paid execution without both approved treatment prompts.

    Parameters
    ----------
    manifest : collections.abc.Mapping[str, object]
        Approved campaign manifest.

    Returns
    -------
    None
        Successful return means both scheduled treatment identities have an
        unambiguous prompt construction.
    """

    for assistance_mode in ("baseline", "codira-mcp"):
        prompt_for_attempt("", assistance_mode, manifest)


def build_pilot_plan(
    manifest: Mapping[str, object], task_ids: Sequence[str], seed: int
) -> dict[str, object]:
    """Build the fixed six-attempt Phase 6 plan without side effects.

    Parameters
    ----------
    manifest : Mapping[str, object]
        Approved campaign manifest.
    task_ids : Sequence[str]
        Exactly three selected task identities.
    seed : int
        Persisted paired-schedule seed.

    Returns
    -------
    dict[str, object]
        Public deterministic plan summary.

    Raises
    ------
    PilotLauncherError
        If manifest bindings or pilot cardinality are invalid.
    """

    if len(task_ids) != 3 or len(set(task_ids)) != 3:
        raise PilotLauncherError("Phase 6 pilot requires exactly three unique tasks")
    raw_tasks = manifest.get("task_fingerprints")
    raw_bindings = manifest.get("task_fixture_ids")
    raw_fixtures = manifest.get("fixture_fingerprints")
    if not all(
        isinstance(item, Mapping) for item in (raw_tasks, raw_bindings, raw_fixtures)
    ):
        raise PilotLauncherError("campaign manifest lacks immutable task bindings")
    tasks = cast("Mapping[str, object]", raw_tasks)
    bindings = cast("Mapping[str, object]", raw_bindings)
    fixtures = cast("Mapping[str, object]", raw_fixtures)
    requested_task_ids = set(task_ids)
    if not requested_task_ids <= set(tasks) or not requested_task_ids <= set(bindings):
        raise PilotLauncherError("pilot task is absent from manifest bindings")
    if requested_task_ids != set(tasks) or requested_task_ids != set(bindings):
        raise PilotLauncherError("pilot tasks must exactly match manifest bindings")
    bound = set(bindings.values())
    if (
        len(bound) != 3
        or not all(isinstance(item, str) for item in bound)
        or not bound <= set(fixtures)
    ):
        raise PilotLauncherError("pilot requires three bound immutable fixtures")
    budgets, accounting, campaign_id = (
        manifest.get("budgets"),
        manifest.get("accounting"),
        manifest.get("campaign_id"),
    )
    if (
        not isinstance(budgets, Mapping)
        or not isinstance(accounting, Mapping)
        or not isinstance(campaign_id, str)
    ):
        raise PilotLauncherError("campaign manifest lacks required pilot fields")
    runtime_image = manifest.get("runtime_image")
    if runtime_image is not None and (
        not isinstance(runtime_image, str)
        or phase0.IMAGE_DIGEST_PATTERN.fullmatch(runtime_image) is None
    ):
        raise PilotLauncherError("campaign manifest has an invalid runtime image")
    runtime_profile = manifest.get("runtime_profile_fingerprint")
    if runtime_profile is not None and (
        not isinstance(runtime_profile, str)
        or len(runtime_profile) != 64
        or any(character not in "0123456789abcdef" for character in runtime_profile)
    ):
        raise PilotLauncherError("campaign manifest has an invalid runtime profile")
    try:
        schedule = build_paired_schedule(task_ids, 1, seed)
    except ValueError as error:
        raise PilotLauncherError("pilot schedule cannot be constructed") from error
    return {
        "campaign_id": campaign_id,
        "manifest_fingerprint": canonical_fingerprint(manifest),
        "seed": seed,
        "task_ids": sorted(task_ids),
        "task_fingerprints": {task_id: tasks[task_id] for task_id in sorted(task_ids)},
        "task_fixture_ids": {
            task_id: bindings[task_id] for task_id in sorted(task_ids)
        },
        "fixture_fingerprints": {
            fixture_id: fixtures[fixture_id] for fixture_id in sorted(map(str, bound))
        },
        "repetitions": 1,
        "scheduled_execution_count": len(schedule),
        "budgets": dict(budgets),
        "accounting": dict(accounting),
        "runtime_image": runtime_image,
        "runtime_profile_fingerprint": runtime_profile,
        "attempts": [item.__dict__ for item in schedule],
        "execution_authorized": False,
    }


def parse_fixture_sources(values: Sequence[str]) -> dict[str, Path]:
    """Parse unique ``fixture_id=/absolute/source`` bindings.

    Parameters
    ----------
    values : Sequence[str]
        Command-line fixture source bindings.

    Returns
    -------
    dict[str, pathlib.Path]
        Fixture IDs mapped to absolute source checkouts.

    Raises
    ------
    PilotLauncherError
        If a binding is relative, malformed, or duplicated.
    """

    sources: dict[str, Path] = {}
    for value in values:
        fixture_id, separator, raw_path = value.partition("=")
        path = Path(raw_path)
        if (
            not separator
            or not fixture_id
            or not path.is_absolute()
            or fixture_id in sources
        ):
            raise PilotLauncherError(
                "fixture sources must be unique fixture_id=/absolute/path bindings"
            )
        sources[fixture_id] = path
    return sources


def load_pilot_inputs(
    manifest: Mapping[str, object], task_ids: Sequence[str], sources: Mapping[str, Path]
) -> tuple[
    dict[str, Mapping[str, object]],
    dict[str, Mapping[str, object]],
    dict[str, Mapping[str, object]],
]:
    """Load public task, oracle, and fixture records bound to the manifest.

    Parameters
    ----------
    manifest : Mapping[str, object]
        Approved campaign manifest.
    task_ids : Sequence[str]
        Selected frozen public task IDs.
    sources : Mapping[str, pathlib.Path]
        Local source checkouts for each required fixture.

    Returns
    -------
    tuple[dict[str, Mapping[str, object]], dict[str, Mapping[str, object]], dict[str, Mapping[str, object]]]
        Validated task, oracle, and fixture lookup mappings.

    Raises
    ------
    PilotLauncherError
        If public inputs or their immutable bindings drift.
    """

    bindings = manifest.get("task_fixture_ids")
    task_hashes = manifest.get("task_fingerprints")
    fixture_hashes = manifest.get("fixture_fingerprints")
    if not (
        isinstance(bindings, Mapping)
        and isinstance(task_hashes, Mapping)
        and isinstance(fixture_hashes, Mapping)
    ):
        raise PilotLauncherError("campaign manifest lacks immutable task bindings")
    tasks: dict[str, Mapping[str, object]] = {}
    oracles: dict[str, Mapping[str, object]] = {}
    fixtures: dict[str, Mapping[str, object]] = {}
    for task_id in task_ids:
        task = load_document(BENCHMARK_ROOT / "tasks" / f"{task_id}.json", "task")
        oracle = load_document(
            BENCHMARK_ROOT / "oracles" / f"{task['oracle_id']}.json", "oracle"
        )
        fixture_id = task.get("fixture_id")
        if (
            task.get("task_id") != task_id
            or task.get("oracle_id") != oracle.get("oracle_id")
            or fixture_id != bindings.get(task_id)
        ):
            raise PilotLauncherError(
                "public task bindings differ from the approved manifest"
            )
        if canonical_fingerprint(task) != task_hashes.get(task_id) or not isinstance(
            fixture_id, str
        ):
            raise PilotLauncherError(
                "public task fingerprint differs from the approved manifest"
            )
        fixture = load_document(
            BENCHMARK_ROOT / "fixtures" / f"{fixture_id}.json", "fixture"
        )
        if (
            canonical_fingerprint(fixture) != fixture_hashes.get(fixture_id)
            or fixture_id not in sources
        ):
            raise PilotLauncherError(
                "public fixture identity differs from the approved manifest"
            )
        verify_fixture(fixture, sources[fixture_id])
        tasks[task_id], oracles[task_id], fixtures[fixture_id] = task, oracle, fixture
    if set(sources) != set(fixtures):
        raise PilotLauncherError(
            "fixture sources must exactly match the approved pilot fixtures"
        )
    return tasks, oracles, fixtures


def install_protected_asset(
    task_id: str, protected_root: Path
) -> dict[str, object] | None:
    """Copy a reviewed protected grader asset after verifying its identity.

    Parameters
    ----------
    task_id : str
        Task whose grader may require a protected asset.
    protected_root : pathlib.Path
        Fresh grader-only fixture checkout.

    Returns
    -------
    dict[str, object] or None
        Provenance summary, or ``None`` for tasks with no asset.

    Raises
    ------
    PilotLauncherError
        If protected asset provenance or content is invalid.
    """

    asset_root = PROTECTED_ASSET_ROOT / task_id
    provenance_path = asset_root / "provenance.json"
    if not provenance_path.exists():
        return None
    provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
    if not isinstance(provenance, dict):
        raise PilotLauncherError("protected asset provenance must be an object")
    asset_path, expected = provenance.get("asset_path"), provenance.get("asset_sha256")
    if not isinstance(asset_path, str) or not isinstance(expected, str):
        raise PilotLauncherError("protected asset provenance is incomplete")
    relative = PurePosixPath(asset_path)
    if (
        relative.is_absolute()
        or "." in relative.parts
        or ".." in relative.parts
        or "\\" in asset_path
    ):
        raise PilotLauncherError(
            "protected asset path must remain beneath its asset root"
        )
    source = asset_root.joinpath(*relative.parts)
    actual = hashlib.sha256(source.read_bytes()).hexdigest() if source.is_file() else ""
    if actual != expected:
        raise PilotLauncherError("protected asset identity does not match provenance")
    destination = protected_root.joinpath(*relative.parts)
    if not source.is_relative_to(asset_root) or not destination.is_relative_to(
        protected_root
    ):
        raise PilotLauncherError(
            "protected asset path must remain beneath its asset root"
        )
    if destination.exists():
        raise PilotLauncherError("protected asset conflicts with frozen fixture")
    shutil.copy2(source, destination)
    return {
        "asset_path": asset_path,
        "asset_sha256": actual,
        "source_commit": provenance.get("source_commit"),
    }


def prepare_protected_fixture(
    source: Path, revision: str, destination: Path, task_id: str
) -> dict[str, object] | None:
    """Create a pristine Git checkout for protected patch grading.

    Parameters
    ----------
    source : pathlib.Path
        Verified local source checkout holding the frozen revision.
    revision : str
        Frozen fixture commit SHA.
    destination : pathlib.Path
        Absent grader-only checkout destination.
    task_id : str
        Task selecting any reviewed protected asset.

    Returns
    -------
    dict[str, object] or None
        Installed protected-asset provenance, if applicable.

    Raises
    ------
    PilotLauncherError
        If Git cannot create the exact protected checkout.
    """

    git = shutil.which("git")
    if git is None:
        raise PilotLauncherError("Git is unavailable for protected fixture preparation")
    clone = subprocess.run(
        (git, "clone", "--no-checkout", "--no-local", str(source), str(destination)),
        check=False,
        text=True,
        capture_output=True,
    )
    checkout = (
        subprocess.run(
            (git, "-C", str(destination), "checkout", "--detach", revision),
            check=False,
            text=True,
            capture_output=True,
        )
        if clone.returncode == 0
        else None
    )
    if clone.returncode != 0 or checkout is None or checkout.returncode != 0:
        raise PilotLauncherError("cannot create protected immutable fixture checkout")
    return install_protected_asset(task_id, destination)


def execution_controls(
    manifest: Mapping[str, object], *, scheduled_attempts: int = 6
) -> ExecutionControls:
    """Return complete typed execution controls before any attempt side effect.

    Parameters
    ----------
    manifest : Mapping[str, object]
        Approved campaign manifest.
    scheduled_attempts : int, optional
        Number of frozen provider attempts whose aggregate cap must fit the
        declared pilot spending ceiling. The paired pilot defaults to six;
        the dedicated route calibration supplies one.

    Returns
    -------
    ExecutionControls
        Typed provider, accounting, and budget ceilings.

    Raises
    ------
    PilotLauncherError
        If any required runtime control is absent or has an invalid type.
    """

    if scheduled_attempts < 1:
        raise PilotLauncherError("scheduled attempt count must be positive")
    provider = manifest.get("provider")
    accounting = manifest.get("accounting")
    budgets = manifest.get("budgets")
    if not all(isinstance(item, Mapping) for item in (provider, accounting, budgets)):
        raise PilotLauncherError("campaign manifest has invalid execution controls")
    provider = cast("Mapping[str, object]", provider)
    accounting = cast("Mapping[str, object]", accounting)
    budgets = cast("Mapping[str, object]", budgets)
    model = provider.get("model")
    effort = provider.get("reasoning_effort")
    prompt_price = provider.get("max_prompt_usd_per_million")
    completion_price = provider.get("max_completion_usd_per_million")
    if (
        not isinstance(model, str)
        or not model
        or not isinstance(effort, str)
        or not effort
    ):
        raise PilotLauncherError("campaign provider controls are invalid")
    if (
        not isinstance(prompt_price, (int, float))
        or isinstance(prompt_price, bool)
        or prompt_price <= 0
        or not isinstance(completion_price, (int, float))
        or isinstance(completion_price, bool)
        or completion_price <= 0
    ):
        raise PilotLauncherError("campaign provider controls are invalid")
    max_total_tokens = budgets.get("max_total_tokens")
    max_output_tokens = budgets.get("max_output_tokens")
    timeout_seconds = budgets.get("timeout_seconds")
    if (
        not isinstance(max_total_tokens, int)
        or isinstance(max_total_tokens, bool)
        or max_total_tokens < 1
        or not isinstance(max_output_tokens, int)
        or isinstance(max_output_tokens, bool)
        or max_output_tokens < 1
        or max_total_tokens < max_output_tokens
        or not isinstance(timeout_seconds, int)
        or isinstance(timeout_seconds, bool)
        or timeout_seconds < 1
    ):
        raise PilotLauncherError("campaign budget controls are invalid")
    daily_spend = accounting.get("max_daily_spend_usd")
    attempt_spend = accounting.get("max_estimated_attempt_spend_usd")
    pilot_spend = accounting.get("max_estimated_pilot_spend_usd")
    request_limit = accounting.get("max_response_requests_per_attempt")
    transport_limit = accounting.get("max_transport_attempts_per_response", 1)
    token_scope = accounting.get("max_total_tokens_scope", "per-continuation")
    daily_spend_value = cast("int | float", daily_spend)
    attempt_spend_value = cast("int | float", attempt_spend)
    pilot_spend_value = cast("int | float", pilot_spend)
    request_limit_value = cast("int", request_limit)
    transport_limit_value = cast("int", transport_limit)
    if not (
        all(
            isinstance(value, (int, float)) and not isinstance(value, bool)
            for value in (daily_spend, attempt_spend, pilot_spend)
        )
        and isinstance(request_limit, int)
        and not isinstance(request_limit, bool)
        and request_limit >= 1
        and isinstance(transport_limit, int)
        and not isinstance(transport_limit, bool)
        and transport_limit >= 1
        and token_scope in {"whole-session", "per-continuation"}
    ):
        raise PilotLauncherError("campaign accounting controls are invalid")
    token_scope_value = token_scope
    reservation_multiplier = (
        1
        if token_scope_value == "whole-session"
        else request_limit_value * transport_limit_value
    )
    if (
        float(daily_spend_value) <= 0
        or float(attempt_spend_value) <= 0
        or float(pilot_spend_value) <= 0
        or float(pilot_spend_value) > float(daily_spend_value)
        or float(pilot_spend_value) < float(attempt_spend_value) * scheduled_attempts
        or float(attempt_spend_value)
        < reservation_multiplier
        * max_total_tokens
        * max(float(prompt_price), float(completion_price))
        / 1_000_000
    ):
        raise PilotLauncherError("campaign accounting controls are invalid")
    return ExecutionControls(
        model,
        effort,
        float(prompt_price),
        float(completion_price),
        max_total_tokens,
        token_scope_value,
        max_output_tokens,
        timeout_seconds,
        request_limit_value,
        transport_limit_value,
        float(daily_spend_value),
        float(attempt_spend_value),
        float(pilot_spend_value),
    )


def execute_pilot_attempt(
    store: CampaignStore,
    attempt: ScheduledAttempt,
    context: PilotExecutionContext,
) -> tuple[dict[str, object], dict[str, object]]:
    """Run one bounded paid attempt and retain only non-secret evidence facts.

    Parameters
    ----------
    store : CampaignStore
        Frozen resumable campaign state.
    attempt : ScheduledAttempt
        One pending paired execution.
    context : PilotExecutionContext
        Immutable validated execution dependencies.

    Returns
    -------
    tuple[dict[str, object], dict[str, object]]
        Schema-valid result and credential-free evidence metadata.

    Raises
    ------
    PilotLauncherError
        If a fresh attempt cannot be safely prepared or graded.

    Notes
    -----
    The host proxy socket lives in the designated short-lived project
    temporary directory, keeping it below the Unix-domain path limit even
    when the durable attempt path and identifier are long. It is removed when
    the container attempt finishes; response evidence remains under the
    durable campaign state root.
    """

    task = context.tasks[attempt.task_id]
    fixture_id = str(task["fixture_id"])
    fixture = context.fixtures[fixture_id]
    controls = execution_controls(
        context.manifest, scheduled_attempts=len(store.schedule)
    )
    attempt_root = store.root / "attempt-work" / attempt.attempt_id
    if attempt_root.exists():
        raise PilotLauncherError(
            "unfinished attempt work exists; do not risk duplicate billing"
        )
    agent_root, protected_root, state_root = (
        attempt_root / "agent",
        attempt_root / "protected",
        attempt_root / "state",
    )
    attempt_root.mkdir(parents=True)
    export_fixture(context.sources[fixture_id], str(fixture["revision"]), agent_root)
    try:
        environment = fixture_environment(agent_root, fixture_id)
    except EnvironmentPreparationError as error:
        raise PilotLauncherError(str(error)) from error
    environment_preparation = execute_environment_preparation(
        EnvironmentPreparationRequest(
            context.runtime,
            context.image,
            agent_root,
            controls.timeout_seconds,
            environment,
        )
    )
    if environment_preparation.timed_out or environment_preparation.returncode != 0:
        raise PilotLauncherError(
            "fixture environment preparation failed before provider setup"
        )
    if attempt.assistance_mode == "codira-mcp":
        if not BENCHMARK_CODIRA_PROFILE.is_file():
            raise PilotLauncherError("benchmark Codira profile is unavailable")
        profile_target = agent_root / ".codira" / "config.toml"
        profile_target.parent.mkdir(exist_ok=True)
        shutil.copyfile(BENCHMARK_CODIRA_PROFILE, profile_target)
        profile_fingerprint = runtime_profile_fingerprint()
        preparation = execute_index_preparation(
            IndexPreparationRequest(
                context.runtime,
                context.image,
                agent_root,
                controls.timeout_seconds,
                BENCHMARK_CODIRA_CONFIG,
            )
        )
        if preparation.timed_out or preparation.returncode != 0:
            raise PilotLauncherError(
                "codira index preparation failed before MCP startup"
            )
        index_admission = validate_prepared_index(agent_root)
        index_root = agent_root / ".codira"
        index_fingerprint = canonical_fingerprint(
            {
                str(path.relative_to(index_root)): hashlib.sha256(
                    path.read_bytes()
                ).hexdigest()
                for path in sorted(index_root.rglob("*"))
                if path.is_file()
            }
        )
        store.store_index_preparation(
            attempt.attempt_id,
            {
                "elapsed_seconds": preparation.elapsed_seconds,
                "fixture_revision": str(fixture["revision"]),
                "profile_fingerprint": profile_fingerprint,
                "index_fingerprint": index_fingerprint,
                "returncode": preparation.returncode,
                "timed_out": preparation.timed_out,
                "stdout_fingerprint": hashlib.sha256(
                    preparation.stdout.encode("utf-8")
                ).hexdigest(),
                "stderr_fingerprint": hashlib.sha256(
                    preparation.stderr.encode("utf-8")
                ).hexdigest(),
                **index_admission,
            },
        )
    result_format = str(task.get("result_format", "json"))
    snapshot_root = attempt_root / "workspace-before"
    if result_format == "workspace-diff":
        shutil.copytree(
            agent_root,
            snapshot_root,
            ignore=shutil.ignore_patterns(".benchmark", ".git", ".venv", "__pycache__"),
        )
    protected_asset = prepare_protected_fixture(
        context.sources[fixture_id],
        str(fixture["revision"]),
        protected_root,
        attempt.task_id,
    )
    token = secrets.token_urlsafe(32)
    phase0.write_isolated_codex_config(
        state_root,
        "/workspace",
        "http://127.0.0.1:43123/v1",
        (controls.model, controls.reasoning_effort),
        BENCHMARK_MCP_COMMAND if attempt.assistance_mode == "codira-mcp" else None,
    )
    write_proxy_relay(state_root)
    constraints = provider_proxy.ResponseConstraints(
        controls.model,
        controls.reasoning_effort,
        controls.max_prompt_price,
        controls.max_completion_price,
    )
    settings = provider_proxy.ProxySettings(
        token,
        context.upstream_token,
        0,
        controls.max_output_tokens,
        constraints,
        controls.max_response_requests,
        controls.max_transport_attempts_per_response,
        max_total_tokens=controls.max_total_tokens,
        max_context_tokens=context.provider_context_length,
        max_prompt_usd_per_million=controls.max_prompt_price,
        max_completion_usd_per_million=controls.max_completion_price,
        max_attempt_spend_usd=controls.max_attempt_spend,
        response_artifact_root=attempt_root / "provider-responses",
    )
    with tempfile.TemporaryDirectory(prefix="ae-", dir=PROJECT_TEMP_ROOT) as socket_dir:
        socket_path = Path(socket_dir) / "p.sock"
        server = provider_proxy.create_unix_server(settings, str(socket_path))
        try:
            threading.Thread(target=server.serve_forever, daemon=True).start()
            execution = execute_container_attempt(
                ContainerAttemptRequest(
                    context.runtime,
                    context.image,
                    agent_root,
                    state_root,
                    prompt_for_attempt(
                        str(task["prompt"]), attempt.assistance_mode, context.manifest
                    )
                    + "\n\n"
                    + environment.directive,
                    controls.timeout_seconds,
                    proxy_socket=socket_path,
                    proxy_client_token=token,
                )
            )
        finally:
            server.shutdown()
            server.server_close()
    capture_error: str | None = None
    if result_format == "workspace-diff":
        try:
            capture_workspace_patch(
                snapshot_root, agent_root, agent_root / str(task["result_path"])
            )
        except ValueError as error:
            capture_error = str(error)
    (attempt_root / "events.jsonl").write_text(execution.stdout, encoding="utf-8")
    result, evidence = result_from_execution(
        store.campaign_id,
        attempt,
        execution,
        max_total_tokens=controls.max_total_tokens,
    )
    evidence["provider_responses"] = list(settings.response_observations)
    evidence["environment_preparation"] = {
        "ecosystem": environment.ecosystem,
        "elapsed_seconds": environment_preparation.elapsed_seconds,
        "returncode": environment_preparation.returncode,
    }
    observations = settings.response_observations
    if (
        observations
        and observations[-1].get("source") == "local"
        and result["failure_class"] == "provider_rate_limited"
    ):
        local_reason = observations[-1].get("reason")
        result["failure_class"] = {
            "session_token_budget_exhausted": "session_token_cap_exceeded",
            "provider_usage_unavailable": "provider_usage_unavailable",
            "attempt_spend_budget_exhausted": "attempt_spend_cap_exceeded",
            "attempt_spend_cap_reservation_exceeded": "attempt_spend_cap_exceeded",
        }.get(str(local_reason), "local_request_cap_exceeded")
    operational_status = "passed" if result["outcome"] == "success" else "failed"
    operational_failure = (
        None if operational_status == "passed" else result["failure_class"]
    )
    oracle_passed, oracle_fingerprint = False, None
    task_oracle_status = "not_evaluated"
    task_oracle_failure: str | None = None
    if result["outcome"] == "success" and capture_error is not None:
        result["outcome"], result["failure_class"] = (
            "oracle_failure",
            "workspace_capture",
        )
        task_oracle_status = "failed"
        task_oracle_failure = "workspace_capture"
    elif result["outcome"] == "success":
        try:
            definition = context.oracles[attempt.task_id]["definition"]
            if not isinstance(definition, Mapping):
                raise ContractError.message("oracle definition must be an object")
            outcome = evaluate_oracle(
                definition,
                result_root=agent_root,
                result_path=str(task["result_path"]),
                result_format=result_format,
                protected_root=protected_root,
            )
            oracle_passed, oracle_fingerprint = outcome.passed, outcome.fingerprint
            task_oracle_status = "passed" if outcome.passed else "failed"
            if not outcome.passed:
                result["outcome"], result["failure_class"] = (
                    "oracle_failure",
                    "deterministic_oracle",
                )
                task_oracle_failure = "deterministic_oracle"
        except (ContractError, KeyError, TypeError):
            result["outcome"], result["failure_class"] = (
                "oracle_failure",
                "oracle_contract",
            )
            task_oracle_status = "failed"
            task_oracle_failure = "oracle_contract"
    result.update(
        {
            "operational_calibration": {
                "status": operational_status,
                "failure_class": operational_failure,
            },
            "task_oracle": {
                "status": task_oracle_status,
                "failure_class": task_oracle_failure,
                "fingerprint": oracle_fingerprint,
            },
        }
    )
    evidence.update(
        {
            "oracle_passed": oracle_passed,
            "oracle_fingerprint": oracle_fingerprint,
            "protected_asset": protected_asset,
            "response_request_count": settings.limiter.count,
        }
    )
    return result, evidence


def build_parser() -> argparse.ArgumentParser:
    """Build the explicit Phase 6 pilot parser.

    Parameters
    ----------
    None

    Returns
    -------
    argparse.ArgumentParser
        Parser for dry-run planning or explicit paid execution.
    """

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign-manifest", type=Path, required=True)
    parser.add_argument("--task-id", action="append", required=True)
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--state-root", type=Path)
    parser.add_argument("--fixture-source", action="append", default=[])
    parser.add_argument("--image")
    parser.add_argument("--runtime", default="podman")
    parser.add_argument("--preflight", action="store_true")
    parser.add_argument("--execute", action="store_true")
    return parser


def main(arguments: list[str] | None = None) -> int:
    """Print a dry-run plan or execute only the approved bounded pilot.

    Parameters
    ----------
    arguments : list[str] or None, optional
        Command-line arguments excluding the executable name.

    Returns
    -------
    int
        Zero for a completed operation and two for safe rejection.

    Raises
    ------
    SystemExit
        If command-line arguments violate the parser contract.
    """

    args = build_parser().parse_args(arguments)
    try:
        manifest = load_document(args.campaign_manifest, "campaign")
        plan = build_pilot_plan(manifest, args.task_id, args.seed)
        if args.preflight and args.execute:
            raise PilotLauncherError("preflight and paid execution are separate stages")
        if args.preflight:
            controls = execution_controls(manifest)
            upstream = os.environ.get(provider_proxy.UPSTREAM_TOKEN_ENV, "")
            if not upstream:
                raise PilotLauncherError("pilot OpenRouter credential is unavailable")
            print(
                json.dumps(
                    preflight_openrouter_route(manifest, controls, upstream),
                    sort_keys=True,
                )
            )
            return 0
        if not args.execute:
            print(json.dumps(plan, sort_keys=True))
            return 0
        if args.state_root is None or not args.image:
            raise PilotLauncherError("paid execution requires --state-root and --image")
        runtime_image = manifest.get("runtime_image")
        if (
            not isinstance(runtime_image, str)
            or phase0.IMAGE_DIGEST_PATTERN.fullmatch(runtime_image) is None
        ):
            raise PilotLauncherError(
                "paid execution requires a digest-pinned manifest runtime image"
            )
        if args.image != runtime_image:
            raise PilotLauncherError("paid execution image differs from manifest")
        runtime_profile = manifest.get("runtime_profile_fingerprint")
        if not isinstance(runtime_profile, str):
            raise PilotLauncherError(
                "paid execution requires a runtime profile fingerprint"
            )
        if runtime_profile != runtime_profile_fingerprint():
            raise PilotLauncherError(
                "local Codira profile differs from manifest fingerprint"
            )
        controls = execution_controls(manifest)
        validate_treatment_protocol(manifest)
        sources = parse_fixture_sources(args.fixture_source)
        tasks, oracles, fixtures = load_pilot_inputs(manifest, args.task_id, sources)
        upstream = os.environ.get(provider_proxy.UPSTREAM_TOKEN_ENV, "")
        if not upstream:
            raise PilotLauncherError("pilot OpenRouter credential is unavailable")
        route_preflight = preflight_openrouter_route(manifest, controls, upstream)
        public_route = route_preflight.get("public_route")
        provider_context_length = (
            public_route.get("context_length")
            if isinstance(public_route, Mapping)
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
                "seed": args.seed,
            },
            build_paired_schedule(args.task_id, 1, args.seed),
        )
        store.initialize()
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
        written = run_pending(
            store, lambda attempt: execute_pilot_attempt(store, attempt, context)
        )
    except (ContractError, OSError, PilotLauncherError, ValueError) as error:
        print(f"pilot launcher error: {error}", file=sys.stderr)
        return 2
    print(
        json.dumps(
            {
                "campaign_id": manifest["campaign_id"],
                "new_record_paths": [str(path) for path in written],
                "pending_attempt_ids": [
                    item.attempt_id for item in store.pending_attempts()
                ],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
