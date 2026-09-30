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
from scripts.run_agent_efficiency_phase6_pilot import (
    parse_fixture_sources,
    validate_protected_task_assets,
)

FACTORY_VERSION = "1.0"
SOPS_ENVIRONMENT = (
    "/home/marco/.config/personal-secrets/secrets/"
    "openrouter_codira_agent_efficiency_pilot.env"
)
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
    """

    campaign_directory: Path
    execution_root: Path
    fixture_sources: dict[str, Path]
    runtime: str
    seed: int
    manifest: dict[str, object]
    plan: dict[str, object]


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
        If the pilot task mapping is malformed.
    """

    fingerprints = manifest.get("task_fingerprints")
    if not isinstance(fingerprints, dict) or len(fingerprints) != (
        6 if full_campaign else 3
    ):
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
    stage = plan.get("stage")
    full_campaign = stage == "full-campaign"
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
                task_ids, 5 if full_campaign else 1, seed
            )
        ]
    )
    if (
        plan.get("factory_version") != FACTORY_VERSION
        or plan.get("stage") not in {"pilot", "full-campaign", "completion"}
        or plan.get("campaign_id") != manifest.get("campaign_id")
        or plan.get("manifest_fingerprint") != canonical_fingerprint(manifest)
        or plan.get("scheduled_attempt_count") != (60 if full_campaign else 6)
        or plan.get("attempts") != expected_attempts
    ):
        raise PilotLaunchError("factory launch plan differs from manifest or seed")
    task_fingerprints = manifest.get("task_fingerprints")
    if not isinstance(task_fingerprints, dict):
        raise PilotLaunchError("pilot task fingerprints are invalid")
    for task_id in task_ids:
        try:
            task = load_document(BENCHMARK_ROOT / "tasks" / f"{task_id}.json", "task")
            oracle = load_document(
                BENCHMARK_ROOT / "oracles" / f"{task['oracle_id']}.json", "oracle"
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
            BENCHMARK_ROOT / "fixtures" / f"{fixture_id}.json", "fixture"
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
        "manifest_fingerprint": canonical_fingerprint(launch.manifest),
        "manifest_sha256": _sha256(launch.campaign_directory / "campaign.json"),
        "launch_plan_sha256": _sha256(launch.campaign_directory / "launch-plan.json"),
        "fixture_sources": reports,
        "runtime": launch.runtime,
        "seed": launch.seed,
        "state_root": str(runtime_state_root(launch)),
        "log_path": str(launch.execution_root / "logs" / "pilot.log"),
        "exit_path": str(launch.execution_root / "pilot.exit"),
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


def tmux_command(launch: PilotLaunch, *, invocation: int = 0) -> tuple[str, str]:
    """Build the fixed credential-scoped shell command after preparation.

    Parameters
    ----------
    launch : PilotLaunch
        Validated and prepared paired-pilot launch.
    invocation : int, optional
        Zero for initial launch; positive resume ordinal preserves earlier logs.

    Returns
    -------
    tuple[str, str]
        Deterministic tmux session name and shell command.
    """

    runner = [
        "uv",
        "--directory",
        str(Path.cwd()),
        "run",
        "python",
        "scripts/run_agent_efficiency_phase6_pilot.py",
        "--execute",
        "--campaign-manifest",
        str(launch.campaign_directory / "campaign.json"),
    ]
    full_campaign = launch.plan.get("stage") in {"full-campaign", "completion"}
    if full_campaign:
        runner.extend(
            (
                "--full-campaign",
                "--launch-plan",
                str(launch.campaign_directory / "launch-plan.json"),
            )
        )
    for task_id in _task_ids(launch.manifest, full_campaign=full_campaign):
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
    command = ["sops", "exec-env", SOPS_ENVIRONMENT, shlex.join(runner)]
    stem = "pilot" if invocation == 0 else f"resume-{invocation:03d}"
    log = launch.execution_root / "logs" / f"{stem}.log"
    exit_path = launch.execution_root / f"{stem}.exit"
    shell = (
        f"export TMPDIR={shlex.quote(str(PROJECT_TEMP_ROOT))} "
        f"TMP={shlex.quote(str(PROJECT_TEMP_ROOT))} "
        f"TEMP={shlex.quote(str(PROJECT_TEMP_ROOT))}; "
        f"{shlex.join(command)} > {shlex.quote(str(log))} 2>&1; "
        f"code=$?; printf '%s\\n' \"$code\" > {shlex.quote(str(exit_path))}"
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
    if resume:
        if launch.plan.get("stage") not in {"full-campaign", "completion"}:
            raise PilotLaunchError("resume is qualified only for full campaigns")
        journal = runtime_state_root(launch) / "budget"
        starts = {
            path.stem.removesuffix(".started")
            for path in journal.glob("*.started.json")
        }
        settlements = {
            path.stem.removesuffix(".settled")
            for path in journal.glob("*.settled.json")
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
    elif (launch.execution_root / "logs" / "pilot.log").exists() or (
        launch.execution_root / "pilot.exit"
    ).exists():
        raise PilotLaunchError("initial launch evidence exists; use explicit resume")
    session, command = tmux_command(launch, invocation=invocation)
    completed = subprocess.run(
        ("tmux", "new-session", "-d", "-s", session, "bash", "-lc", command),
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        raise PilotLaunchError("tmux launch failed")
    return session


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
    parser.add_argument("--campaign-dir", type=Path, required=True)
    parser.add_argument("--execution-root", type=Path, required=True)
    parser.add_argument("--fixture-source", action="append", required=True)
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--runtime", default="podman")
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
    """

    args = build_parser().parse_args(arguments)
    try:
        launch = load_launch(
            args.campaign_dir,
            args.execution_root,
            parse_fixture_sources(args.fixture_source),
            args.runtime,
            args.seed,
            allow_prepared_root=args.launch or args.resume,
        )
        receipt = (
            verify_prepared_launch(launch)
            if args.launch or args.resume
            else prepare_launch(launch)
        )
        session = (
            start_tmux(launch, resume=args.resume)
            if args.launch or args.resume
            else None
        )
    except (OSError, PilotLaunchError, ValueError) as error:
        print(f"pilot executor error: {error}", file=sys.stderr)
        return 2
    print(json.dumps({"launch_receipt": str(receipt), "tmux_session": session}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
