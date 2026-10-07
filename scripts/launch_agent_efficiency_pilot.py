#!/usr/bin/env python3
"""Prepare or launch a factory-generated paired pilot with durable evidence."""
# ruff: noqa: EM101, EM102, PLR0913, S607, TRY003

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shlex
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.agent_efficiency.campaign_state import build_paired_schedule
from scripts.agent_efficiency.contracts import canonical_fingerprint, load_document
from scripts.agent_efficiency.corpus import verify_fixture
from scripts.agent_efficiency.panels import panel_document_path
from scripts.run_agent_efficiency_phase6_pilot import (
    PilotLauncherError,
    parse_fixture_sources,
    validate_campaign_image_reference,
    validate_protected_task_assets,
)

FACTORY_VERSION = "1.0"
SOPS_ENVIRONMENT = (
    "/home/marco/.config/personal-secrets/secrets/"
    "openrouter_codira_agent_efficiency_pilot.env"
)
CANARY_SOPS_ENVIRONMENTS = {
    "campaign": SOPS_ENVIRONMENT,
    "codira-tests": (
        "/home/marco/.config/personal-secrets/secrets/openrouter_codira_tests.env"
    ),
}
BENCHMARK_ROOT = Path("benchmarks/agent-efficiency")
PROJECT_TEMP_ROOT = Path("/home/marco/Personalia/Progetti/.Temp")


class PilotLaunchError(ValueError):
    """Report a public-safe paired-pilot launch-contract failure.

    Parameters
    ----------
    detail : str
        Stable non-secret reason for rejecting the launch.
    """


@dataclass(frozen=True)
class PilotLaunch:
    """Hold validated factory artifacts and deterministic runtime paths.

    Parameters
    ----------
    campaign_directory : pathlib.Path
        Immutable factory output containing the manifest and launch plan.
    execution_root : pathlib.Path
        Absent directory atomically claimed for this launch.
    fixture_sources : dict[str, pathlib.Path]
        Exact admitted source checkout for each fixture identity.
    runtime : str
        Container runtime passed to the pilot runner.
    seed : int
        Seed whose schedule must exactly reproduce the factory launch plan.
    manifest, plan : dict[str, object]
        Validated generated campaign artifacts.
    subscription_codex, subscription_auth_source : pathlib.Path or None
        Explicit native CLI and managed login bindings for a subscription route.
    canary_key : str, optional
        Registered OpenRouter credential environment for preparation only.
    canary_budget_usd : float or None, optional
        Separate frozen canary allowance; None retains campaign guards.
    canary_max_total_tokens : int or None, optional
        Separate preparation token guard; None retains the campaign guard.

    Returns
    -------
    None
        Instances retain immutable preparation bindings.
    """

    campaign_directory: Path
    execution_root: Path
    fixture_sources: dict[str, Path]
    runtime: str
    seed: int
    manifest: dict[str, object]
    plan: dict[str, object]
    subscription_codex: Path | None = None
    subscription_auth_source: Path | None = None
    canary_key: str = "campaign"
    canary_budget_usd: float | None = None
    canary_max_total_tokens: int | None = None


def _sha256(path: Path) -> str:
    """Return the SHA-256 digest of one immutable artifact.

    Parameters
    ----------
    path : pathlib.Path
        Existing artifact to digest.

    Returns
    -------
    str
        Lowercase hexadecimal SHA-256 digest.
    """

    return hashlib.sha256(path.read_bytes()).hexdigest()


def _task_ids(
    manifest: dict[str, object], *, full_campaign: bool = False
) -> tuple[str, ...]:
    """Return the manifest's sorted task identities.

    Parameters
    ----------
    manifest : dict[str, object]
        Validated generated campaign manifest.
    full_campaign : bool, optional
        Require six task identities for the qualified full campaign.

    Returns
    -------
    tuple[str, ...]
        Deterministic pilot or full-campaign task identities.

    Raises
    ------
    PilotLaunchError
        If the task mapping or full-campaign image reference is inadmissible.
    """

    if full_campaign or manifest.get("stage") == "completion":
        try:
            validate_campaign_image_reference(manifest.get("runtime_image"))
        except PilotLauncherError as error:
            raise PilotLaunchError(str(error)) from error
    fingerprints = manifest.get("task_fingerprints")
    expected_count = (
        len(fingerprints)
        if isinstance(fingerprints, dict)
        and manifest.get("stage") == "completion"
        and manifest.get("panel_id") == "representative-v1"
        and 1 <= len(fingerprints) <= 24
        else (
            (24 if manifest.get("stage") == "representative-campaign" else 6)
            if full_campaign
            else 3
        )
    )
    if not isinstance(fingerprints, dict) or len(fingerprints) != expected_count:
        raise PilotLaunchError("pilot task fingerprints are invalid")
    task_ids = tuple(sorted(fingerprints))
    if not all(isinstance(item, str) and item for item in task_ids):
        raise PilotLaunchError("pilot task identities are invalid")
    return task_ids


def load_launch(
    campaign_directory: Path,
    execution_root: Path,
    fixture_sources: dict[str, Path],
    runtime: str,
    seed: int,
    *,
    allow_prepared_root: bool = False,
    subscription_codex: Path | None = None,
    subscription_auth_source: Path | None = None,
    canary_key: str = "campaign",
    canary_budget_usd: float | None = None,
    canary_max_total_tokens: int | None = None,
) -> PilotLaunch:
    """Validate generated artifacts before any directory or tmux side effect.

    Parameters
    ----------
    campaign_directory : pathlib.Path
        Factory output containing immutable JSON artifacts.
    execution_root : pathlib.Path
        Required absent root for this launch's state and logs.
    fixture_sources : dict[str, pathlib.Path]
        Exact admitted source checkouts keyed by fixture identity.
    runtime : str
        Non-empty container runtime command.
    seed : int
        Candidate schedule seed checked against the factory plan.
    allow_prepared_root : bool, optional
        Permit an existing root only for receipt-verified launch mode.
    subscription_codex : pathlib.Path or None, optional
        Existing native CLI when that route is frozen.
    subscription_auth_source : pathlib.Path or None, optional
        Existing managed login binding for the native route.
    canary_key : str, optional
        Registered OpenRouter key alias used only by the preparation canary.
    canary_budget_usd : float or None, optional
        Positive finite preparation-only dollar allowance.
    canary_max_total_tokens : int or None, optional
        Preparation token guard bounded by the campaign's output and token limits.

    Returns
    -------
    PilotLaunch
        Fully validated paired-pilot launch inputs.

    Raises
    ------
    PilotLaunchError
        If artifacts, schedule, paths, sources, or runtime are invalid.
    """

    campaign_directory = campaign_directory.resolve()
    execution_root = execution_root.resolve()
    subscription_codex = (
        subscription_codex.resolve() if subscription_codex is not None else None
    )
    subscription_auth_source = (
        subscription_auth_source.resolve()
        if subscription_auth_source is not None
        else None
    )
    sources = {key: value.resolve() for key, value in fixture_sources.items()}
    if execution_root.exists() and not allow_prepared_root:
        raise PilotLaunchError("execution root already exists")
    if not runtime or any(not path.is_dir() for path in sources.values()):
        raise PilotLaunchError("fixture source or runtime is invalid")
    try:
        manifest = load_document(campaign_directory / "campaign.json", "campaign")
        plan = json.loads(
            (campaign_directory / "launch-plan.json").read_text(encoding="utf-8")
        )
    except (OSError, ValueError) as error:
        raise PilotLaunchError("factory artifacts are unavailable") from error
    if not isinstance(plan, dict):
        raise PilotLaunchError("factory launch plan is malformed")
    _validate_subscription_inputs(
        manifest, subscription_codex, subscription_auth_source
    )
    _validate_canary_inputs(
        manifest, canary_key, canary_budget_usd, canary_max_total_tokens
    )
    stage = plan.get("stage")
    full_campaign = stage in {"full-campaign", "representative-campaign"}
    completion = stage == "completion"
    task_ids = _task_ids(manifest, full_campaign=full_campaign)
    if full_campaign:
        from scripts.agent_efficiency.full_campaign import validate_full_plan

        validate_full_plan(manifest, plan, seed)
    elif completion:
        from scripts.agent_efficiency.completion_campaign import (
            validate_completion_plan,
        )

        validate_completion_plan(manifest, plan, Path.cwd(), seed)
    bindings = manifest.get("task_fixture_ids")
    if not isinstance(bindings, dict):
        raise PilotLaunchError("pilot fixture bindings are invalid")
    fixture_ids = set(bindings.values())
    if (
        not all(isinstance(item, str) for item in fixture_ids)
        or set(sources) != fixture_ids
    ):
        raise PilotLaunchError("fixture sources differ from manifest bindings")
    expected_attempts = (
        plan.get("attempts")
        if completion
        else [
            attempt.__dict__
            for attempt in build_paired_schedule(
                task_ids, int(plan.get("repetitions", 5)) if full_campaign else 1, seed
            )
        ]
    )
    if (
        plan.get("factory_version")
        != (
            "1.1"
            if manifest.get("stage") == "representative-campaign"
            else FACTORY_VERSION
        )
        or plan.get("stage")
        not in {"pilot", "full-campaign", "completion", "representative-campaign"}
        or plan.get("campaign_id") != manifest.get("campaign_id")
        or plan.get("manifest_fingerprint") != canonical_fingerprint(manifest)
        or plan.get("scheduled_attempt_count")
        != (
            len(expected_attempts)
            if completion and isinstance(expected_attempts, list)
            else len(task_ids) * int(plan.get("repetitions", 5)) * 2
            if full_campaign
            else 6
        )
        or plan.get("attempts") != expected_attempts
    ):
        raise PilotLaunchError("factory launch plan differs from manifest or seed")
    task_fingerprints = manifest.get("task_fingerprints")
    if not isinstance(task_fingerprints, dict):
        raise PilotLaunchError("pilot task fingerprints are invalid")
    for task_id in task_ids:
        try:
            task = load_document(
                panel_document_path(BENCHMARK_ROOT, "tasks", task_id), "task"
            )
            oracle = load_document(
                panel_document_path(BENCHMARK_ROOT, "oracles", str(task["oracle_id"])),
                "oracle",
            )
            fixture_id = bindings.get(task_id)
        except (KeyError, TypeError, ValueError) as error:
            raise PilotLaunchError("campaign task assets are unavailable") from error
        if not isinstance(fixture_id, str) or fixture_id not in sources:
            raise PilotLaunchError("campaign fixture binding is invalid")
        fixture_source = sources[fixture_id]
        if (
            task.get("task_id") != task_id
            or canonical_fingerprint(task) != task_fingerprints.get(task_id)
            or task.get("oracle_id") != oracle.get("oracle_id")
        ):
            raise PilotLaunchError("campaign task differs from its frozen identity")
        validate_protected_task_assets(task_id, oracle, fixture_source)
    return PilotLaunch(
        campaign_directory,
        execution_root,
        sources,
        runtime,
        seed,
        manifest,
        plan,
        subscription_codex,
        subscription_auth_source,
        canary_key,
        canary_budget_usd,
        canary_max_total_tokens,
    )


def _validate_canary_inputs(
    manifest: dict[str, object],
    key: str,
    budget: float | None,
    tokens: int | None = None,
) -> None:
    """Reject unregistered or crossed preparation credential bindings.

    Parameters
    ----------
    manifest : dict[str, object]
        Frozen provider and campaign accounting controls.
    key : str
        Registered preparation key alias.
    budget : float or None
        Separate canary allowance; None retains campaign guards.
    tokens : int or None, optional
        Separate token guard constrained by the campaign's frozen token limits.

    Returns
    -------
    None
        Only supported exclusive authentication bindings are admitted.

    Raises
    ------
    PilotLaunchError
        If the key, allowance or provider combination is invalid.
    """
    import math

    if key not in CANARY_SOPS_ENVIRONMENTS:
        raise PilotLaunchError("canary key is not registered")
    if budget is not None and (
        isinstance(budget, bool)
        or not isinstance(budget, (int, float))
        or not math.isfinite(budget)
        or budget <= 0
    ):
        raise PilotLaunchError("canary budget must be positive and finite")
    provider = manifest.get("provider")
    if not isinstance(provider, dict) or (
        provider.get("name") != "openrouter"
        and (key != "campaign" or budget is not None or tokens is not None)
    ):
        raise PilotLaunchError("canary key and dollar controls require OpenRouter")
    if key != "campaign" and budget is None:
        raise PilotLaunchError("separate canary key requires a frozen allowance")
    if tokens is not None:
        limits = manifest.get("budgets")
        if (
            isinstance(tokens, bool)
            or not isinstance(tokens, int)
            or not isinstance(limits, dict)
            or not isinstance(limits.get("max_output_tokens"), int)
            or not isinstance(limits.get("max_total_tokens"), int)
            or not limits["max_output_tokens"] <= tokens <= limits["max_total_tokens"]
        ):
            raise PilotLaunchError("canary tokens must fit the frozen campaign limits")


def _validate_subscription_inputs(
    manifest: dict[str, object], codex: Path | None, auth_source: Path | None
) -> None:
    """Validate native login bindings before a launcher side effect.

    Parameters
    ----------
    manifest : dict[str, object]
        Frozen provider selection.
    codex, auth_source : pathlib.Path or None
        Existing binary and managed login file, without reading tokens.

    Raises
    ------
    PilotLaunchError
        If native bindings are missing or supplied to another provider.
    """
    provider = manifest.get("provider")
    subscription = (
        isinstance(provider, dict) and provider.get("name") == "codex-subscription"
    )
    if subscription:
        if (
            codex is None
            or not codex.is_file()
            or auth_source is None
            or not auth_source.is_file()
        ):
            raise PilotLaunchError(
                "subscription requires the native Codex binary and managed login"
            )
    elif codex is not None or auth_source is not None:
        raise PilotLaunchError(
            "OpenRouter launch cannot accept subscription credentials"
        )


def _atomic_json(path: Path, document: dict[str, object]) -> None:
    """Write one absent JSON evidence artifact atomically.

    Parameters
    ----------
    path : pathlib.Path
        Absent output path beneath a prepared execution root.
    document : dict[str, object]
        Public-safe JSON document to persist.

    Raises
    ------
    PilotLaunchError
        If the immutable evidence artifact cannot be written.
    """

    if path.exists():
        raise PilotLaunchError(f"immutable launch artifact exists: {path.name}")
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with temporary.open("x", encoding="utf-8") as handle:
            json.dump(document, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(path)
    except OSError as error:
        raise PilotLaunchError("cannot persist launch evidence") from error
    finally:
        if temporary.exists():
            temporary.unlink()


def runtime_state_root(launch: PilotLaunch) -> Path:
    """Return the durable runtime state directory beneath the execution root.

    Parameters
    ----------
    launch : PilotLaunch
        Validated generated campaign inputs.

    Returns
    -------
    pathlib.Path
        Persistent campaign directory safe for Unix-domain socket descendants
        when the caller selects a short execution-root name.
    """

    return launch.execution_root / "state"


def _receipt(launch: PilotLaunch) -> dict[str, object]:
    """Build the public-safe receipt and reverify every fixture source.

    Parameters
    ----------
    launch : PilotLaunch
        Validated paired-pilot launch.

    Returns
    -------
    dict[str, object]
        Complete receipt without its self-fingerprint.
    """

    reports: dict[str, object] = {}
    for fixture_id, source in sorted(launch.fixture_sources.items()):
        fixture = load_document(
            panel_document_path(BENCHMARK_ROOT, "fixtures", fixture_id), "fixture"
        )
        try:
            report = verify_fixture(fixture, source)
        except ValueError as error:
            raise PilotLaunchError(
                f"fixture source fails admission: {fixture_id}"
            ) from error
        reports[fixture_id] = {
            "source": str(source),
            "revision": report.revision,
            "tree_sha": report.tree_sha,
        }
    return {
        "campaign_id": launch.manifest["campaign_id"],
        "campaign_directory": str(launch.campaign_directory),
        "manifest_fingerprint": canonical_fingerprint(launch.manifest),
        "manifest_sha256": _sha256(launch.campaign_directory / "campaign.json"),
        "launch_plan_sha256": _sha256(launch.campaign_directory / "launch-plan.json"),
        "fixture_sources": reports,
        "runtime": launch.runtime,
        "seed": launch.seed,
        "state_root": str(runtime_state_root(launch)),
        "log_path": str(launch.execution_root / "logs" / "pilot.log"),
        "exit_path": str(launch.execution_root / "pilot.exit"),
        "canary_key": launch.canary_key,
        "canary_budget_usd": launch.canary_budget_usd,
        "canary_max_total_tokens": launch.canary_max_total_tokens,
        **(
            {
                "subscription_codex_sha256": _sha256(launch.subscription_codex),
                "subscription_codex": str(launch.subscription_codex.resolve()),
                "subscription_auth_source": str(
                    launch.subscription_auth_source.resolve()
                )
                if launch.subscription_auth_source is not None
                else None,
            }
            if launch.subscription_codex is not None
            else {}
        ),
    }


def prepare_launch(launch: PilotLaunch) -> Path:
    """Claim fresh runtime paths and persist launch evidence before tmux.

    Parameters
    ----------
    launch : PilotLaunch
        Validated immutable campaign and runtime inputs.

    Returns
    -------
    pathlib.Path
        Immutable launch receipt path.

    Raises
    ------
    PilotLaunchError
        If fresh paths cannot be claimed or inputs fail revalidation.
    """

    try:
        launch.execution_root.mkdir(parents=True)
        (launch.execution_root / "logs").mkdir()
        runtime_state_root(launch).mkdir()
    except OSError as error:
        raise PilotLaunchError("cannot create fresh execution paths") from error
    receipt = _receipt(launch)
    receipt["receipt_fingerprint"] = canonical_fingerprint(receipt)
    path = launch.execution_root / "launch-receipt.json"
    _atomic_json(path, receipt)
    return path


def verify_prepared_launch(launch: PilotLaunch) -> Path:
    """Verify the immutable receipt and required paths before tmux launch.

    Parameters
    ----------
    launch : PilotLaunch
        Launch whose execution root was prepared earlier.

    Returns
    -------
    pathlib.Path
        Existing immutable receipt path.

    Raises
    ------
    PilotLaunchError
        If preparation is absent, altered, or incomplete.
    """

    path = launch.execution_root / "launch-receipt.json"
    try:
        receipt = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise PilotLaunchError("prepared launch receipt is unavailable") from error
    if not isinstance(receipt, dict):
        raise PilotLaunchError("prepared launch receipt is malformed")
    fingerprint = receipt.pop("receipt_fingerprint", None)
    expected = _receipt(launch)
    if fingerprint != canonical_fingerprint(expected) or receipt != expected:
        raise PilotLaunchError("prepared launch receipt differs from inputs")
    if (
        not runtime_state_root(launch).is_dir()
        or not (launch.execution_root / "logs").is_dir()
    ):
        raise PilotLaunchError("prepared launch paths are unavailable")
    return path


def runner_argv(launch: PilotLaunch, *, execute: bool = True) -> list[str]:
    """Build one shared runner command for preparation and execution.

    Parameters
    ----------
    launch : PilotLaunch
        Validated and prepared paired-pilot launch.
    execute : bool, optional
        Select paid execution or read-only authenticated admission.

    Returns
    -------
    list[str]
        Exact absolute interpreter and resolved factory bindings.
    """

    runner = [
        str(Path(sys.executable).absolute()),
        "scripts/run_agent_efficiency_phase6_pilot.py",
        "--execute" if execute else "--preflight",
        "--campaign-manifest",
        str(launch.campaign_directory / "campaign.json"),
    ]
    full_campaign = launch.plan.get("stage") in {
        "full-campaign",
        "completion",
        "representative-campaign",
    }
    if full_campaign:
        runner.extend(
            (
                "--full-campaign",
                "--launch-plan",
                str(launch.campaign_directory / "launch-plan.json"),
            )
        )
    for task_id in _task_ids(
        launch.manifest,
        full_campaign=launch.plan.get("stage")
        in {"full-campaign", "representative-campaign"},
    ):
        runner.extend(("--task-id", task_id))
    runner.extend(
        ("--seed", str(launch.seed), "--state-root", str(runtime_state_root(launch)))
    )
    for fixture_id, source in sorted(launch.fixture_sources.items()):
        runner.extend(("--fixture-source", f"{fixture_id}={source}"))
    runner.extend(
        (
            "--image",
            str(launch.manifest["runtime_image"]),
            "--runtime",
            launch.runtime,
        )
    )
    if launch.subscription_codex is not None:
        assert launch.subscription_auth_source is not None
        runner.extend(
            (
                "--subscription-codex",
                str(launch.subscription_codex),
                "--subscription-auth-source",
                str(launch.subscription_auth_source),
            )
        )
    if execute:
        runner.extend(
            (
                "--readiness-receipt",
                str(launch.execution_root / "readiness-receipt.json"),
            )
        )
    return runner


def child_environment() -> str:
    """Bind the verified child environment without modifying the tmux server.

    Parameters
    ----------
    None

    Returns
    -------
    str
        Shell assignments preserving present and absent qualification bindings.
    """
    return " ".join(
        f"export {name}={shlex.quote(os.environ[name])};"
        if name in os.environ
        else f"unset {name};"
        for name in ("PYTHONPATH", "PATH", "XDG_RUNTIME_DIR")
    )


def tmux_command(launch: PilotLaunch, *, invocation: int = 0) -> tuple[str, str]:
    """Build a fixed child environment without changing tmux global state.

    Parameters
    ----------
    launch : PilotLaunch
        Prepared immutable execution bindings.
    invocation : int, optional
        Separate initial or resume log identity.

    Returns
    -------
    tuple[str, str]
        Named session and exact credential-scoped command.
    """
    runner = runner_argv(launch)
    command = (
        runner
        if launch.subscription_codex is not None
        else ["sops", "exec-env", SOPS_ENVIRONMENT, shlex.join(runner)]
    )
    stem = "pilot" if invocation == 0 else f"resume-{invocation:03d}"
    log = launch.execution_root / "logs" / f"{stem}.log"
    exit_path = launch.execution_root / f"{stem}.exit"
    shell = (
        f"cd {shlex.quote(str(Path.cwd()))}; "
        f"{child_environment()} "
        f"export TMPDIR={shlex.quote(str(PROJECT_TEMP_ROOT))} "
        f"TMP={shlex.quote(str(PROJECT_TEMP_ROOT))} "
        f"TEMP={shlex.quote(str(PROJECT_TEMP_ROOT))}; "
        f"{shlex.join(command)} > {shlex.quote(str(log))} 2>&1; "
        f'code=$?; printf \'%s\\n\' "$code" > {shlex.quote(str(exit_path))}; exit "$code"'
    )
    suffix = "" if invocation == 0 else f"-resume-{invocation:03d}"
    return f"agent-efficiency-{launch.manifest['campaign_id']}{suffix}", shell


def start_tmux(launch: PilotLaunch, *, resume: bool = False) -> str:
    """Start the prepared paid pilot without exposing its credential.

    Parameters
    ----------
    launch : PilotLaunch
        Receipt-verified paired-pilot launch.
    resume : bool, optional
        Resume a full campaign under a separate immutable invocation receipt.

    Returns
    -------
    str
        Started deterministic tmux session name.

    Raises
    ------
    PilotLaunchError
        If tmux cannot start the prepared command.
    """

    invocation = 0
    from scripts.agent_efficiency.readiness import verify_readiness

    verify_readiness(launch)
    if resume:
        if launch.plan.get("stage") not in {
            "full-campaign",
            "completion",
            "representative-campaign",
        }:
            raise PilotLaunchError("resume is qualified only for full campaigns")
        if launch.subscription_codex is not None:
            state = runtime_state_root(launch)
            starts = state / "subscription-starts"
            if any(
                not (state / "records" / f"{path.stem}.json").is_file()
                for path in starts.glob("*.json")
            ):
                raise PilotLaunchError("unfinished subscription attempt blocks resume")
            invocation = 1 + len(
                tuple(launch.execution_root.glob("resume-*-receipt.json"))
            )
            _atomic_json(
                launch.execution_root / f"resume-{invocation:03d}-receipt.json",
                {
                    "launch_receipt_sha256": _sha256(
                        launch.execution_root / "launch-receipt.json"
                    ),
                    "invocation": invocation,
                    "launch_plan_sha256": _sha256(
                        launch.campaign_directory / "launch-plan.json"
                    ),
                },
            )
        else:
            invocation = _openrouter_resume_invocation(launch)
    elif (launch.execution_root / "logs" / "pilot.log").exists() or (
        launch.execution_root / "pilot.exit"
    ).exists():
        raise PilotLaunchError("initial launch evidence exists; use explicit resume")
    session, command = tmux_command(launch, invocation=invocation)
    completed = subprocess.run(
        (
            "tmux",
            "new-session",
            "-d",
            "-s",
            session,
            "bash",
            "-c",
            command,
            ";",
            "set-option",
            "-t",
            session,
            "remain-on-exit",
            "on",
        ),
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        raise PilotLaunchError("tmux launch failed")
    return session


def _openrouter_resume_invocation(launch: PilotLaunch) -> int:
    """Verify paid proxy settlement before selecting a new resume receipt.

    Parameters
    ----------
    launch : PilotLaunch
        Prepared OpenRouter campaign.

    Returns
    -------
    int
        New immutable invocation number.
    """
    journal = runtime_state_root(launch) / "budget"
    starts = {
        path.stem.removesuffix(".started") for path in journal.glob("*.started.json")
    }
    settlements = {
        path.stem.removesuffix(".settled") for path in journal.glob("*.settled.json")
    }
    state = runtime_state_root(launch)
    clean_admission_stop = (
        not (journal / "identity.json").exists()
        and not any(state.iterdir())
        and (launch.execution_root / "pilot.exit").is_file()
    )
    if starts != settlements or (
        not (journal / "identity.json").is_file() and not clean_admission_stop
    ):
        raise PilotLaunchError("unfinished budget evidence blocks resume")
    invocation = 1 + len(tuple(launch.execution_root.glob("resume-*-receipt.json")))
    _atomic_json(
        launch.execution_root / f"resume-{invocation:03d}-receipt.json",
        {
            "launch_receipt_sha256": _sha256(
                launch.execution_root / "launch-receipt.json"
            ),
            "invocation": invocation,
            "launch_plan_sha256": _sha256(
                launch.campaign_directory / "launch-plan.json"
            ),
        },
    )
    return invocation


def load_prepared_inputs(execution_root: Path) -> PilotLaunch:
    """Load mechanical launch bindings from the original prepared receipt.

    Parameters
    ----------
    execution_root : pathlib.Path
        Prepared execution identity.

    Returns
    -------
    PilotLaunch
        Re-admitted bindings without re-entering paths or credentials.
    """
    receipt = json.loads((execution_root / "launch-receipt.json").read_text())
    sources = {
        name: Path(row["source"]) for name, row in receipt["fixture_sources"].items()
    }
    native = receipt.get("subscription_codex")
    auth = receipt.get("subscription_auth_source")
    return load_launch(
        Path(receipt["campaign_directory"]),
        execution_root,
        sources,
        receipt["runtime"],
        receipt["seed"],
        allow_prepared_root=True,
        subscription_codex=Path(native) if native else None,
        subscription_auth_source=Path(auth) if auth else None,
        canary_key=receipt.get("canary_key", "campaign"),
        canary_budget_usd=receipt.get("canary_budget_usd"),
        canary_max_total_tokens=receipt.get("canary_max_total_tokens"),
    )


def build_parser() -> argparse.ArgumentParser:
    """Build the deterministic paired-pilot executor parser.

    Parameters
    ----------
    None

    Returns
    -------
    argparse.ArgumentParser
        Parser for prepare-only and explicit tmux-launch stages.
    """

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign-dir", type=Path)
    parser.add_argument("--execution-root", type=Path, required=True)
    parser.add_argument("--fixture-source", action="append")
    parser.add_argument("--seed", type=int)
    parser.add_argument("--runtime")
    parser.add_argument("--subscription-codex", type=Path)
    parser.add_argument("--subscription-auth-source", type=Path)
    parser.add_argument("--canary-key", choices=tuple(CANARY_SOPS_ENVIRONMENTS))
    parser.add_argument("--canary-budget-usd", type=float)
    parser.add_argument("--canary-max-total-tokens", type=int)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--prepare", action="store_true")
    mode.add_argument("--launch", action="store_true")
    mode.add_argument("--resume", action="store_true")
    return parser


def main(arguments: list[str] | None = None) -> int:
    """Prepare evidence or launch one factory-generated pilot in tmux.

    Parameters
    ----------
    arguments : list[str] or None, optional
        CLI arguments excluding the executable name.

    Returns
    -------
    int
        Zero on successful preparation or launch; two on safe rejection.

    Raises
    ------
    SystemExit
        If CLI arguments violate the parser contract.
    """

    args = build_parser().parse_args(arguments)
    try:
        if (args.launch or args.resume) and args.campaign_dir is None:
            if (
                args.fixture_source
                or args.seed is not None
                or args.subscription_codex
                or args.subscription_auth_source
                or args.runtime is not None
                or args.canary_key is not None
                or args.canary_budget_usd is not None
                or args.canary_max_total_tokens is not None
            ):
                raise PilotLaunchError(  # noqa: TRY301 - CLI validation boundary
                    "receipt-based launch cannot accept replacement bindings"
                )
            launch = load_prepared_inputs(args.execution_root)
        else:
            if (
                args.campaign_dir is None
                or args.seed is None
                or not args.fixture_source
            ):
                raise PilotLaunchError(  # noqa: TRY301 - CLI validation boundary
                    "preparation requires campaign, seed and all fixture sources"
                )
            launch = load_launch(
                args.campaign_dir,
                args.execution_root,
                parse_fixture_sources(args.fixture_source),
                args.runtime or "podman",
                args.seed,
                allow_prepared_root=args.launch or args.resume,
                subscription_codex=args.subscription_codex,
                subscription_auth_source=args.subscription_auth_source,
                canary_key=args.canary_key or "campaign",
                canary_budget_usd=args.canary_budget_usd,
                canary_max_total_tokens=args.canary_max_total_tokens,
            )
        receipt = (
            verify_prepared_launch(launch)
            if args.launch or args.resume
            else prepare_launch(launch)
        )
        from scripts.agent_efficiency.preparation import prepare_readiness
        from scripts.agent_efficiency.readiness import verify_readiness

        readiness = (
            verify_readiness(launch)
            if args.launch or args.resume
            else prepare_readiness(launch)
        )
        session = (
            start_tmux(launch, resume=args.resume)
            if args.launch or args.resume
            else None
        )
    except (OSError, PilotLaunchError, ValueError, TypeError, KeyError) as error:
        print(f"pilot executor error: {error}", file=sys.stderr)
        return 2
    print(
        json.dumps(
            {
                "launch_receipt": str(receipt),
                "readiness_receipt": str(readiness),
                "tmux_session": session,
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
