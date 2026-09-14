#!/usr/bin/env python3
"""Run the bounded, resumable Issue #53 Phase 6 pilot.

The public manifest is validated before the runner reads its OpenRouter
credential. Agent containers receive only a fresh proxy token and an exported
fixture; protected graders receive a separate immutable checkout.
"""
# ruff: noqa: EM101, EM102, TRY003, TRY004, TRY301

from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import shutil
import subprocess
import sys
import threading
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import cast

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
from scripts.agent_efficiency.oracles import evaluate_oracle
from scripts.agent_efficiency.runner import (
    ContainerAttemptRequest,
    execute_container_attempt,
    result_from_execution,
    write_proxy_relay,
)

BENCHMARK_ROOT = Path("benchmarks/agent-efficiency")
PROTECTED_ASSET_ROOT = BENCHMARK_ROOT / "protected"


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


@dataclass(frozen=True)
class ExecutionControls:
    """Hold validated scalar execution controls from the approved manifest.

    Parameters
    ----------
    model, reasoning_effort : str
        Exact provider settings fixed for the pilot.
    max_prompt_price, max_completion_price : float
        Positive OpenRouter price ceilings per million tokens.
    max_output_tokens, timeout_seconds, max_response_requests : int
        Positive per-attempt output, time, and provider-request ceilings.

    Returns
    -------
    None
        Instances are typed immutable values safe to use after validation.
    """

    model: str
    reasoning_effort: str
    max_prompt_price: float
    max_completion_price: float
    max_output_tokens: int
    timeout_seconds: int
    max_response_requests: int


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
        The baseline prompt unchanged, or the protocol instruction followed by
        the same public task prompt for the assisted treatment.

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
    if (
        not isinstance(version, str)
        or not version
        or not isinstance(instruction, str)
        or not instruction.strip()
    ):
        raise PilotLauncherError("campaign treatment protocol is invalid")
    if assistance_mode == "baseline":
        return task_prompt
    if assistance_mode == "codira-mcp":
        return f"{instruction.strip()}\n\n{task_prompt}"
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
    execution_controls(manifest)
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
    manifest: Mapping[str, object],
) -> ExecutionControls:
    """Return complete typed execution controls before any attempt side effect.

    Parameters
    ----------
    manifest : Mapping[str, object]
        Approved campaign manifest.

    Returns
    -------
    ExecutionControls
        Typed provider, accounting, and budget ceilings.

    Raises
    ------
    PilotLauncherError
        If any required runtime control is absent or has an invalid type.
    """

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
    max_output_tokens = budgets.get("max_output_tokens")
    timeout_seconds = budgets.get("timeout_seconds")
    if (
        not isinstance(max_output_tokens, int)
        or isinstance(max_output_tokens, bool)
        or max_output_tokens < 1
        or not isinstance(timeout_seconds, int)
        or isinstance(timeout_seconds, bool)
        or timeout_seconds < 1
    ):
        raise PilotLauncherError("campaign budget controls are invalid")
    request_limit = accounting.get("max_response_requests_per_attempt")
    if (
        not isinstance(request_limit, int)
        or isinstance(request_limit, bool)
        or request_limit < 1
    ):
        raise PilotLauncherError("campaign response request control is invalid")
    return ExecutionControls(
        model,
        effort,
        float(prompt_price),
        float(completion_price),
        max_output_tokens,
        timeout_seconds,
        request_limit,
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
    """

    task = context.tasks[attempt.task_id]
    fixture_id = str(task["fixture_id"])
    fixture = context.fixtures[fixture_id]
    controls = execution_controls(context.manifest)
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
        "codira-mcp" if attempt.assistance_mode == "codira-mcp" else None,
    )
    write_proxy_relay(state_root)
    socket_path = state_root / "provider.sock"
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
    )
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
                ),
                controls.timeout_seconds,
                proxy_socket=socket_path,
                proxy_client_token=token,
            )
        )
    finally:
        server.shutdown()
        server.server_close()
    (attempt_root / "events.jsonl").write_text(execution.stdout, encoding="utf-8")
    result, evidence = result_from_execution(store.campaign_id, attempt, execution)
    oracle_passed, oracle_fingerprint = False, None
    if result["outcome"] == "success":
        try:
            definition = context.oracles[attempt.task_id]["definition"]
            if not isinstance(definition, Mapping):
                raise ContractError.message("oracle definition must be an object")
            outcome = evaluate_oracle(
                definition,
                result_root=agent_root,
                result_path=str(task["result_path"]),
                protected_root=protected_root,
            )
            oracle_passed, oracle_fingerprint = outcome.passed, outcome.fingerprint
            if not outcome.passed:
                result["outcome"], result["failure_class"] = (
                    "oracle_failure",
                    "deterministic_oracle",
                )
        except (ContractError, KeyError, TypeError):
            result["outcome"], result["failure_class"] = (
                "oracle_failure",
                "oracle_contract",
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
        execution_controls(manifest)
        validate_treatment_protocol(manifest)
        sources = parse_fixture_sources(args.fixture_source)
        tasks, oracles, fixtures = load_pilot_inputs(manifest, args.task_id, sources)
        upstream = os.environ.get(provider_proxy.UPSTREAM_TOKEN_ENV, "")
        if not upstream:
            raise PilotLauncherError("pilot OpenRouter credential is unavailable")
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
