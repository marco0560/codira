"""Prepare a complete campaign in one non-executing qualification pass.

Parameters
----------
None

Returns
-------
None
    Failed preparation retains evidence but never produces a ready receipt.
"""
# ruff: noqa: EM101, EM102, TRY003

from __future__ import annotations

import hashlib
import json
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import TYPE_CHECKING, cast

from scripts.agent_efficiency.readiness import (
    evidence_check,
    publish_readiness,
    qualify_host_context,
    readiness_identity,
    write_evidence,
)
from scripts.agent_efficiency.runner import (
    PROJECT_TEMP_ROOT,
    IndexPreparationRequest,
    execute_index_preparation,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from scripts.launch_agent_efficiency_pilot import PilotLaunch


def _command_evidence(
    command: list[str], directory: Path, *, timeout: int = 120
) -> None:
    """Run one bounded non-model check and retain its stdout, stderr and exit.

    Parameters
    ----------
    command : list[str]
        Repository-owned non-executing qualification command.
    directory : pathlib.Path
        Fresh durable check output directory.
    timeout : int, optional
        Host command guard, including authentication around a bounded canary.

    Returns
    -------
    None
        Nonzero status rejects preparation without a retry.

    Raises
    ------
    ValueError
        If the required preparation boundary fails.
    """
    directory.mkdir(parents=True)
    with (
        (directory / "stdout.log").open("x") as stdout,
        (directory / "stderr.log").open("x") as stderr,
    ):
        completed = subprocess.run(
            command, stdout=stdout, stderr=stderr, check=False, timeout=timeout
        )
    (directory / "exit").write_text(str(completed.returncode) + "\n")
    if completed.returncode != 0:
        raise ValueError(f"preparation check failed: {directory.name}")


def _repository_gate(directory: Path) -> None:
    """Run, examine and report the full gate before cleaning successful logs.

    Parameters
    ----------
    directory : pathlib.Path
        Readiness directory retaining the index check and gate result receipt.

    Returns
    -------
    None
        Successful temporary gate files and session are removed after reporting.
        Failed or unfinished gates retain their full evidence.

    Raises
    ------
    ValueError
        If the required preparation boundary fails.
    """
    directory.mkdir(parents=True)
    from scripts.launch_agent_efficiency_pilot import child_environment

    _command_evidence(
        [sys.executable, "-m", "codira", "index"], directory / "index-refresh"
    )
    session = f"ae-ready-{time.time_ns()}"
    gate_root = Path.cwd() / ".artifacts/validation/repo-gates" / session
    gate_root.mkdir(parents=True)
    log, status = gate_root / "validation.log", gate_root / "validation.exit"
    command = (
        f"cd {shlex.quote(str(Path.cwd()))}; "
        f"{child_environment()} "
        f"{shlex.join([sys.executable, 'scripts/validate_repo.py'])} > {shlex.quote(str(log))} 2>&1; "
        f'gate_status=$?; printf "%s\\n" "$gate_status" > {shlex.quote(str(status))}; exit "$gate_status"'
    )
    subprocess.run(
        [
            shutil.which("tmux") or "/usr/bin/tmux",
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
        ],
        check=True,
        capture_output=True,
    )
    (gate_root / "session.txt").write_text(session + "\n")
    time.sleep(240)
    deadline = time.monotonic() + 6 * 60 * 60
    while not status.is_file():
        if time.monotonic() > deadline:
            raise ValueError(
                "repository gate has no terminal status; inspect retained session"
            )
        time.sleep(60)
    exit_status = status.read_text().strip()
    receipt: dict[str, object] = {
        "status": "passed" if exit_status == "0" else "failed",
        "exit_status": exit_status,
        "session": session,
        "gate_directory": str(gate_root),
        "log_sha256": hashlib.sha256(log.read_bytes()).hexdigest(),
        "log_tail": log.read_text(errors="replace").splitlines()[-20:],
        "evidence_retained": exit_status != "0",
    }
    write_evidence(directory / "gate-result.json", receipt)
    print(json.dumps({"repository_gate": receipt}), flush=True)
    if exit_status != "0":
        raise ValueError("full repository gate failed; inspect retained log")
    subprocess.run(
        [shutil.which("tmux") or "/usr/bin/tmux", "kill-session", "-t", session],
        check=True,
        capture_output=True,
    )
    shutil.rmtree(gate_root)


def _tool_dispatch(
    launch: PilotLaunch, directory: Path, *, model_canary: bool = False
) -> None:
    """Qualify baseline shell and assisted native MCP dispatch without inference.

    Parameters
    ----------
    launch : PilotLaunch
        Factory-frozen image and provider configuration.
    directory : pathlib.Path
        Fresh durable tool qualification directory.
    model_canary : bool, optional
        Require a genuine subscription model turn after authenticated admission.

    Returns
    -------
    None
        Both arms must support their intended tool contract.

    Raises
    ------
    ValueError
        If the required preparation boundary fails.
    """
    from scripts.agent_efficiency.native_tool_qualification import qualify_native_tools

    directory.mkdir(parents=True)
    provider = cast("dict[str, object]", launch.manifest["provider"])
    transport = (
        "codex-subscription"
        if provider["name"] == "codex-subscription"
        else "openrouter-proxy"
    )
    with tempfile.TemporaryDirectory(
        prefix="ae-tools-", dir=PROJECT_TEMP_ROOT
    ) as temporary:
        scratch = Path(temporary)
        workspace = scratch / "workspace"
        workspace.mkdir()
        (workspace / "qualification.py").write_text(
            "class Qualification:\n    def probe(self):\n        return 42\n\ndef helper():\n    return Qualification().probe()\n"
        )
        subprocess.run(
            [shutil.which("git") or "/usr/bin/git", "init", "--quiet", str(workspace)],
            check=True,
            capture_output=True,
        )
        subprocess.run(
            [
                shutil.which("git") or "/usr/bin/git",
                "-C",
                str(workspace),
                "add",
                "--all",
            ],
            check=True,
            capture_output=True,
        )
        profile = workspace / ".codira/config.toml"
        profile.parent.mkdir()
        shutil.copyfile("scripts/agent_efficiency/benchmark-codira.toml", profile)
        (workspace / ".benchmark/home").mkdir(parents=True)
        temporary_root = scratch / "temporary"
        temporary_root.mkdir()
        indexed = execute_index_preparation(
            IndexPreparationRequest(
                launch.runtime,
                str(launch.manifest["runtime_image"]),
                workspace,
                180,
                "/workspace/.codira/config.toml",
                temporary_root,
            )
        )
        (directory / "index.stdout").write_text(indexed.stdout)
        (directory / "index.stderr").write_text(indexed.stderr)
        if indexed.returncode != 0 or indexed.timed_out:
            raise ValueError("tool canary index preparation failed")
        if model_canary:
            from scripts.agent_efficiency.model_tool_qualification import (
                qualify_model_tools,
            )

            if transport == "openrouter-proxy":
                from scripts.launch_agent_efficiency_pilot import (
                    CANARY_SOPS_ENVIRONMENTS,
                )

                command = [
                    sys.executable,
                    "-m",
                    "scripts.agent_efficiency.model_tool_qualification",
                    "--execution-root",
                    str(launch.execution_root),
                    "--workspace",
                    str(workspace),
                    "--directory",
                    str(directory / "model-canary"),
                ]
                _command_evidence(
                    [
                        "sops",
                        "exec-env",
                        CANARY_SOPS_ENVIRONMENTS[launch.canary_key],
                        shlex.join(command),
                    ],
                    directory / "scoped-child",
                    timeout=300,
                )
            else:
                qualify_model_tools(launch, workspace, directory / "model-canary")
            return
        for mode in ("baseline", "codira-mcp"):
            qualify_native_tools(
                launch.runtime,
                str(launch.manifest["runtime_image"]),
                workspace,
                directory / mode,
                str(provider["model"]),
                str(provider["reasoning_effort"]),
                require_mcp=mode == "codira-mcp",
                provider_transport=transport,
            )


def _authenticated_check(launch: PilotLaunch, directory: Path) -> None:
    """Run the registered read-only authenticated preflight in the exact route.

    Parameters
    ----------
    launch : PilotLaunch
        Frozen provider and managed credential binding.
    directory : pathlib.Path
        Fresh durable sanitized preflight output directory.

    Returns
    -------
    None
        No model turn is requested; crossed provider authentication is rejected.

    Raises
    ------
    ValueError
        If the required preparation boundary fails.
    """
    from scripts.launch_agent_efficiency_pilot import SOPS_ENVIRONMENT, runner_argv

    command = runner_argv(launch, execute=False)
    command[command.index("--state-root") + 1] = str(directory / "state")
    if launch.subscription_codex is None:
        command = ["sops", "exec-env", SOPS_ENVIRONMENT, shlex.join(command)]
    _command_evidence(command, directory)
    receipt = json.loads((directory / "stdout.log").read_text())
    if not isinstance(receipt, dict) or not receipt:
        raise ValueError("authenticated route receipt is missing")


def prepare_readiness(launch: PilotLaunch) -> Path:
    """Qualify every mandatory boundary and publish one immutable ready receipt.

    Parameters
    ----------
    launch : PilotLaunch
        Validated factory inputs whose fresh local launch paths were claimed.

    Returns
    -------
    pathlib.Path
        Machine-validated readiness receipt; absent after any failed check.

    Raises
    ------
    ValueError
        If qualification fails, evidence is incomplete, or inputs change.
    """
    from scripts.agent_efficiency.panel_patch_calibration import qualify_patch_cases
    from scripts.agent_efficiency.runtime_qualification import (
        qualify_image,
        qualify_panel_freshness,
    )

    if launch.manifest.get("stage") != "representative-campaign" and not (
        launch.manifest.get("stage") == "completion"
        and launch.manifest.get("panel_id") == "representative-v1"
    ):
        raise ValueError(
            "complete pipeline calibration is required for this task inventory"
        )
    provider = cast("dict[str, object]", launch.manifest["provider"])
    if provider.get("name") not in {"codex-subscription", "openrouter"}:
        raise ValueError("complete readiness requires a qualified provider route")
    root = launch.execution_root / "readiness"
    root.mkdir(exist_ok=False)
    identity = readiness_identity(launch)
    checks: dict[str, object] = {}
    authenticated_at = 0.0

    def check(name: str, action: Callable[[Path], object]) -> None:
        """Retain the terminal state of each required preparation boundary.

        Parameters
        ----------
        name : str
            Required check identity.
        action : collections.abc.Callable
            Non-executing checker producing durable evidence.

        Returns
        -------
        None
            Failure is recorded and propagated; no retry occurs.

        Raises
        ------
        ValueError
            If the required preparation boundary fails.
        """
        directory = root / name
        print(json.dumps({"preparation_check": name, "status": "running"}), flush=True)
        try:
            if identity != readiness_identity(launch):
                raise ValueError("preparation inputs changed before qualification")  # noqa: TRY301 - record changed controls before any model work
            result = action(directory)
            if isinstance(result, dict):
                directory.mkdir(parents=True, exist_ok=True)
                write_evidence(directory / "check-result.json", result)
                if result.get("status") != "passed":
                    raise ValueError(f"preparation check did not pass: {name}")  # noqa: TRY301 - record checker rejection
            checks[name] = evidence_check(launch.execution_root, directory)
        except Exception as error:
            write_evidence(
                root / f"{name}-failed.json",
                {
                    "status": "failed",
                    "error_class": type(error).__name__,
                    "check": name,
                },
            )
            raise
        print(json.dumps({"preparation_check": name, "status": "passed"}), flush=True)

    check("host-context", lambda _: qualify_host_context(launch.runtime))
    check("factory-inputs", lambda _: {"status": "passed", "identity": identity})
    check(
        "image-runtime",
        lambda path: qualify_image(
            launch.runtime, str(launch.manifest["runtime_image"]), path
        ),
    )
    check("native-tool-dispatch", lambda path: _tool_dispatch(launch, path))
    check(
        "fixture-freshness",
        lambda path: qualify_panel_freshness(
            launch.runtime, str(launch.manifest["runtime_image"]), path
        ),
    )
    check(
        "rubric-calibration",
        lambda path: _command_evidence(
            [sys.executable, "scripts/calibrate_agent_efficiency_panel.py", "--check"],
            path,
        ),
    )
    check(
        "complete-patch-pipeline",
        lambda path: qualify_patch_cases(
            launch.runtime,
            str(launch.manifest["runtime_image"]),
            path,
            launch.fixture_sources,
        ),
    )
    check("repository-gate", _repository_gate)
    check("authenticated-route", lambda path: _authenticated_check(launch, path))
    authenticated_at = time.time()
    check(
        "model-requested-mcp",
        lambda path: _tool_dispatch(launch, path, model_canary=True),
    )
    check(
        "authenticated-route-after-canary",
        lambda path: _authenticated_check(launch, path),
    )
    authenticated_at = time.time()
    write_evidence(root / "checks.json", {"checks": checks})
    return publish_readiness(
        launch, identity, checks, authenticated_at=authenticated_at
    )
