#!/usr/bin/env python3
"""Prepare or launch a factory-generated calibration with durable evidence.

Parameters
----------
None

Returns
-------
None
    Command-line entry point only.
"""
# ruff: noqa: EM101, EM102, S607, TRY003

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.agent_efficiency.contracts import canonical_fingerprint, load_document
from scripts.agent_efficiency.corpus import verify_fixture
from scripts.run_agent_efficiency_phase6_calibration import calibration_attempt
from scripts.run_agent_efficiency_phase6_pilot import PROJECT_TEMP_ROOT

FACTORY_VERSION = "1.0"
SOPS_ENVIRONMENT = (
    "/home/marco/.config/personal-secrets/secrets/"
    "openrouter_codira_agent_efficiency_pilot.env"
)


class CalibrationLaunchError(ValueError):
    """Report a public-safe calibration launch-contract failure.

    Parameters
    ----------
    detail : str
        Stable non-secret reason for rejecting the launch.

    Returns
    -------
    None
        Instances carry the deterministic failure detail.
    """


@dataclass(frozen=True)
class CalibrationLaunch:
    """Hold validated factory artifacts and deterministic runtime paths.

    Parameters
    ----------
    campaign_directory : pathlib.Path
        Immutable factory output containing the manifest and launch plan.
    execution_root : pathlib.Path
        Absent directory atomically claimed for this one launch.
    fixture_source : pathlib.Path
        Local checkout containing the frozen Codira fixture revision.
    runtime : str
        Container runtime passed to the calibration runner.
    manifest : dict[str, object]
        Validated generated campaign manifest.
    plan : dict[str, object]
        Validated generated factory launch plan.

    Returns
    -------
    None
        Immutable launch inputs.
    """

    campaign_directory: Path
    execution_root: Path
    fixture_source: Path
    runtime: str
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


def load_launch(
    campaign_directory: Path,
    execution_root: Path,
    fixture_source: Path,
    runtime: str,
    *,
    allow_prepared_root: bool = False,
) -> CalibrationLaunch:
    """Validate generated artifacts before any directory or tmux side effect.

    Parameters
    ----------
    campaign_directory : pathlib.Path
        Factory output directory containing immutable JSON artifacts.
    execution_root : pathlib.Path
        Required absent root for this launch's state and logs.
    fixture_source : pathlib.Path
        Existing local source checkout for the frozen fixture.
    runtime : str
        Non-empty container runtime command.
    allow_prepared_root : bool, optional
        Permit an existing root only when the caller will verify its immutable
        preparation receipt before tmux launch.

    Returns
    -------
    CalibrationLaunch
        Fully validated launch inputs.

    Raises
    ------
    CalibrationLaunchError
        If artifacts, stage, schedule, paths, or runtime are invalid.
    """

    campaign_directory = campaign_directory.resolve()
    execution_root = execution_root.resolve()
    fixture_source = fixture_source.resolve()
    manifest_path = campaign_directory / "campaign.json"
    plan_path = campaign_directory / "launch-plan.json"
    if execution_root.exists() and not allow_prepared_root:
        raise CalibrationLaunchError("execution root already exists")
    if not fixture_source.is_dir() or not runtime:
        raise CalibrationLaunchError("fixture source or runtime is invalid")
    try:
        manifest = load_document(manifest_path, "campaign")
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise CalibrationLaunchError("factory artifacts are unavailable") from error
    if not isinstance(plan, dict):
        raise CalibrationLaunchError("factory launch plan is malformed")
    expected_attempt = calibration_attempt(manifest).__dict__
    if (
        plan.get("factory_version") != FACTORY_VERSION
        or plan.get("stage") != "calibration"
        or plan.get("campaign_id") != manifest.get("campaign_id")
        or plan.get("manifest_fingerprint") != canonical_fingerprint(manifest)
        or plan.get("scheduled_attempt_count") != 1
        or plan.get("attempts") != [expected_attempt]
    ):
        raise CalibrationLaunchError("factory launch plan differs from manifest")
    return CalibrationLaunch(
        campaign_directory, execution_root, fixture_source, runtime, manifest, plan
    )


def _atomic_json(path: Path, document: dict[str, object]) -> None:
    """Write one absent JSON evidence artifact atomically.

    Parameters
    ----------
    path : pathlib.Path
        Absent output path beneath a prepared execution root.
    document : dict[str, object]
        Public-safe JSON document to persist.

    Returns
    -------
    None

    Raises
    ------
    CalibrationLaunchError
        If an evidence artifact exists or cannot be written.
    """

    if path.exists():
        raise CalibrationLaunchError(f"immutable launch artifact exists: {path.name}")
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with temporary.open("x", encoding="utf-8") as handle:
            json.dump(document, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(path)
    except OSError as error:
        raise CalibrationLaunchError("cannot persist launch evidence") from error
    finally:
        if temporary.exists():
            temporary.unlink()


def runtime_state_root(launch: CalibrationLaunch) -> Path:
    """Return the durable state directory beneath this execution's root.

    Parameters
    ----------
    launch : CalibrationLaunch
        Validated generated campaign inputs.

    Returns
    -------
        pathlib.Path
        Persistent path for campaign state and provider response evidence.
    """

    return launch.execution_root / "state"


def prepare_launch(launch: CalibrationLaunch) -> Path:
    """Claim an execution root and persist all paths before tmux can start.

    Parameters
    ----------
    launch : CalibrationLaunch
        Validated immutable campaign and runtime inputs.

    Returns
    -------
    pathlib.Path
        Immutable launch receipt path.

    Raises
    ------
    CalibrationLaunchError
        If the fresh root cannot be atomically created.
    """

    try:
        launch.execution_root.mkdir(parents=True)
        (launch.execution_root / "logs").mkdir()
        runtime_state_root(launch).mkdir()
    except OSError as error:
        raise CalibrationLaunchError("cannot create fresh execution root") from error
    bindings = launch.manifest.get("task_fixture_ids")
    if not isinstance(bindings, dict) or len(bindings) != 1:
        raise CalibrationLaunchError("calibration fixture binding is invalid")
    fixture_id = next(iter(bindings.values()))
    if not isinstance(fixture_id, str):
        raise CalibrationLaunchError("calibration fixture binding is invalid")
    fixture = load_document(
        Path("benchmarks/agent-efficiency/fixtures") / f"{fixture_id}.json", "fixture"
    )
    revision = fixture.get("revision")
    git = shutil.which("git")
    checkout = launch.execution_root / "fixture"
    if not isinstance(revision, str) or git is None:
        raise CalibrationLaunchError("calibration fixture preparation is unavailable")
    with tempfile.TemporaryDirectory(prefix="aef-", dir=PROJECT_TEMP_ROOT) as temp:
        temp_checkout = Path(temp) / "fixture"
        clone = subprocess.run(
            (
                git,
                "clone",
                "--no-checkout",
                "--no-local",
                str(launch.fixture_source),
                str(temp_checkout),
            ),
            check=False,
            capture_output=True,
            text=True,
        )
        if clone.returncode != 0:
            raise CalibrationLaunchError(
                f"cannot clone frozen calibration fixture (exit {clone.returncode})"
            )
        pinned_head = subprocess.run(
            (
                git,
                "-C",
                str(temp_checkout),
                "update-ref",
                "--no-deref",
                "HEAD",
                revision,
            ),
            check=False,
            capture_output=True,
            text=True,
        )
        if pinned_head.returncode != 0:
            detail = (
                pinned_head.stderr.splitlines()[0][:180]
                if pinned_head.stderr
                else "no diagnostic"
            )
            raise CalibrationLaunchError(
                "cannot pin frozen calibration fixture "
                f"(exit {pinned_head.returncode}: {detail})"
            )
        detached = subprocess.run(
            (git, "-C", str(temp_checkout), "checkout", "--detach", revision),
            check=False,
            capture_output=True,
            text=True,
        )
        if detached.returncode != 0:
            detail = (
                detached.stderr.splitlines()[0][:180]
                if detached.stderr
                else "no diagnostic"
            )
            raise CalibrationLaunchError(
                "cannot check out frozen calibration fixture "
                f"(exit {detached.returncode}: {detail})"
            )
        try:
            report = verify_fixture(fixture, temp_checkout)
        except ValueError as error:
            raise CalibrationLaunchError(
                "frozen calibration fixture fails admission"
            ) from error
        try:
            shutil.copytree(temp_checkout, checkout)
        except OSError as error:
            raise CalibrationLaunchError(
                "cannot persist the admitted calibration fixture"
            ) from error
    try:
        report = verify_fixture(fixture, checkout)
    except ValueError as error:
        raise CalibrationLaunchError(
            "persisted calibration fixture fails admission"
        ) from error
    receipt = {
        "campaign_id": launch.manifest["campaign_id"],
        "manifest_fingerprint": canonical_fingerprint(launch.manifest),
        "manifest_sha256": _sha256(launch.campaign_directory / "campaign.json"),
        "launch_plan_sha256": _sha256(launch.campaign_directory / "launch-plan.json"),
        "fixture_source": str(launch.fixture_source),
        "fixture_checkout": str(checkout),
        "fixture_revision": report.revision,
        "fixture_tree_sha": report.tree_sha,
        "runtime": launch.runtime,
        "state_root": str(runtime_state_root(launch)),
        "log_path": str(launch.execution_root / "logs" / "calibration.log"),
        "exit_path": str(launch.execution_root / "calibration.exit"),
    }
    receipt["receipt_fingerprint"] = canonical_fingerprint(receipt)
    path = launch.execution_root / "launch-receipt.json"
    _atomic_json(path, receipt)
    return path


def verify_prepared_launch(launch: CalibrationLaunch) -> Path:
    """Verify the immutable receipt and required paths before tmux launch.

    Parameters
    ----------
    launch : CalibrationLaunch
        Validated launch whose execution root was prepared earlier.

    Returns
    -------
    pathlib.Path
        Existing immutable receipt path.

    Raises
    ------
    CalibrationLaunchError
        If preparation is absent, altered, or lacks durable output paths.
    """

    receipt_path = launch.execution_root / "launch-receipt.json"
    try:
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise CalibrationLaunchError(
            "prepared launch receipt is unavailable"
        ) from error
    if not isinstance(receipt, dict):
        raise CalibrationLaunchError("prepared launch receipt is malformed")
    fingerprint = receipt.pop("receipt_fingerprint", None)
    bindings = launch.manifest.get("task_fixture_ids")
    if not isinstance(bindings, dict) or len(bindings) != 1:
        raise CalibrationLaunchError("calibration fixture binding is invalid")
    fixture_id = next(iter(bindings.values()))
    if not isinstance(fixture_id, str):
        raise CalibrationLaunchError("calibration fixture binding is invalid")
    try:
        fixture = load_document(
            Path("benchmarks/agent-efficiency/fixtures") / f"{fixture_id}.json",
            "fixture",
        )
        report = verify_fixture(fixture, launch.execution_root / "fixture")
    except (OSError, ValueError) as error:
        raise CalibrationLaunchError(
            "prepared calibration fixture fails admission"
        ) from error
    required = {
        "campaign_id": launch.manifest["campaign_id"],
        "manifest_fingerprint": canonical_fingerprint(launch.manifest),
        "manifest_sha256": _sha256(launch.campaign_directory / "campaign.json"),
        "launch_plan_sha256": _sha256(launch.campaign_directory / "launch-plan.json"),
        "fixture_source": str(launch.fixture_source),
        "fixture_checkout": str(launch.execution_root / "fixture"),
        "fixture_revision": report.revision,
        "fixture_tree_sha": report.tree_sha,
        "runtime": launch.runtime,
        "state_root": str(runtime_state_root(launch)),
        "log_path": str(launch.execution_root / "logs" / "calibration.log"),
        "exit_path": str(launch.execution_root / "calibration.exit"),
    }
    if fingerprint != canonical_fingerprint(required) or receipt != required:
        raise CalibrationLaunchError("prepared launch receipt differs from inputs")
    if (
        not runtime_state_root(launch).is_dir()
        or not (launch.execution_root / "logs").is_dir()
    ):
        raise CalibrationLaunchError("prepared launch paths are unavailable")
    return receipt_path


def tmux_command(launch: CalibrationLaunch) -> tuple[str, str]:
    """Build the fixed shell command and tmux session name after preparation.

    Parameters
    ----------
    launch : CalibrationLaunch
        Validated and prepared launch inputs.

    Returns
    -------
    tuple[str, str]
        Session name and shell command with pre-created durable paths.

    Raises
    ------
    CalibrationLaunchError
        If the manifest has no valid fixture binding for the attempt.
    """

    campaign_id = str(launch.manifest["campaign_id"])
    manifest = launch.campaign_directory / "campaign.json"
    state = runtime_state_root(launch)
    log = launch.execution_root / "logs" / "calibration.log"
    exit_path = launch.execution_root / "calibration.exit"
    image = str(launch.manifest["runtime_image"])
    attempt = calibration_attempt(launch.manifest)
    bindings = launch.manifest.get("task_fixture_ids")
    fixture_id = bindings.get(attempt.task_id) if isinstance(bindings, dict) else None
    if not isinstance(fixture_id, str):
        raise CalibrationLaunchError("calibration fixture binding is invalid")
    runner = [
        "uv",
        "--directory",
        str(Path.cwd()),
        "run",
        "python",
        "scripts/run_agent_efficiency_phase6_calibration.py",
        "--execute",
        "--campaign-manifest",
        str(manifest),
        "--state-root",
        str(state),
        "--fixture-source",
        f"{fixture_id}={launch.execution_root / 'fixture'}",
        "--image",
        image,
        "--runtime",
        launch.runtime,
    ]
    command = ["sops", "exec-env", SOPS_ENVIRONMENT, shlex.join(runner)]
    shell = (
        f"{shlex.join(command)} > {shlex.quote(str(log))} 2>&1; "
        f"code=$?; printf '%s\\n' \"$code\" > {shlex.quote(str(exit_path))}"
    )
    return f"agent-efficiency-{campaign_id}", shell


def start_tmux(launch: CalibrationLaunch) -> str:
    """Start the prepared calibration in tmux without exposing credentials.

    Parameters
    ----------
    launch : CalibrationLaunch
        Launch whose execution root and receipt already exist.

    Returns
    -------
    str
        Started deterministic tmux session name.

    Raises
    ------
    CalibrationLaunchError
        If tmux cannot start the prepared command.
    """

    session, command = tmux_command(launch)
    completed = subprocess.run(
        ("tmux", "new-session", "-d", "-s", session, "bash", "-lc", command),
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        raise CalibrationLaunchError("tmux launch failed")
    return session


def build_parser() -> argparse.ArgumentParser:
    """Build the deterministic calibration-executor command parser.

    Parameters
    ----------
    None

    Returns
    -------
    argparse.ArgumentParser
        Parser for a prepare-only or explicit tmux launch stage.
    """

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign-dir", type=Path, required=True)
    parser.add_argument("--execution-root", type=Path, required=True)
    parser.add_argument("--fixture-source", type=Path, required=True)
    parser.add_argument("--runtime", default="podman")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--prepare", action="store_true")
    mode.add_argument("--launch", action="store_true")
    return parser


def main(arguments: list[str] | None = None) -> int:
    """Prepare evidence or launch one factory-generated calibration in tmux.

    Parameters
    ----------
    arguments : list[str] or None, optional
        Command-line arguments excluding the executable name.

    Returns
    -------
    int
        Zero on prepared or started launch, two on safe rejection.
    """

    args = build_parser().parse_args(arguments)
    try:
        launch = load_launch(
            args.campaign_dir,
            args.execution_root,
            args.fixture_source,
            args.runtime,
            allow_prepared_root=args.launch,
        )
        receipt = (
            verify_prepared_launch(launch) if args.launch else prepare_launch(launch)
        )
        session = start_tmux(launch) if args.launch else None
    except CalibrationLaunchError as error:
        print(f"calibration executor error: {error}", file=sys.stderr)
        return 2
    print(json.dumps({"launch_receipt": str(receipt), "tmux_session": session}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
