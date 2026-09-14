"""Run one benchmark attempt in a constrained container and retain JSONL facts."""
# ruff: noqa: EM101, TRY003

from __future__ import annotations

import os
import re
import subprocess
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

from scripts.agent_efficiency import phase0
from scripts.agent_efficiency.contracts import CONTRACT_VERSION
from scripts.agent_efficiency.usage import UsageError, normalize_completed_turn

_CONTAINER_ID_PATTERN = re.compile(r"^[0-9a-f]{64}$")

if TYPE_CHECKING:
    from pathlib import Path

    from scripts.agent_efficiency.campaign_state import ScheduledAttempt

_PROXY_RELAY_BOOTSTRAP = (
    "python /codex-state/provider_relay.py & relay_pid=$!; "
    '"$2" exec --json --ephemeral --sandbox danger-full-access --ignore-rules '
    '--skip-git-repo-check "$1"; status=$?; kill $relay_pid; wait $relay_pid 2>/dev/null; '
    "exit $status"
)

_PROXY_RELAY_SOURCE = """import socket
import threading

LISTENER = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
LISTENER.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
LISTENER.bind(("127.0.0.1", 43123))
LISTENER.listen()

def copy(source, target):
    try:
        while data := source.recv(65536):
            target.sendall(data)
    finally:
        target.close()

while True:
    client, _ = LISTENER.accept()
    upstream = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    upstream.connect("/codex-state/provider.sock")
    threading.Thread(target=copy, args=(client, upstream), daemon=True).start()
    threading.Thread(target=copy, args=(upstream, client), daemon=True).start()
"""


@dataclass(frozen=True)
class ContainerAttemptRequest:
    """Describe the isolated resources and frozen prompt for one attempt.

    Parameters
    ----------
    runtime : str
        Supported container runtime executable.
    image : str
        Digest-pinned reviewed benchmark image.
    fixture_root : pathlib.Path
        Disposable writable exported fixture.
    state_root : pathlib.Path
        Fresh writable Codex state containing the generated configuration.
    prompt : str
        Frozen public task prompt.
    timeout_seconds : int
        Positive wall-clock timeout.
    codex_command : str, optional
        Container-visible Codex executable.

    Returns
    -------
    None
        Instances carry no credentials or protected oracle material.
    """

    runtime: str
    image: str
    fixture_root: Path
    state_root: Path
    prompt: str
    timeout_seconds: int
    codex_command: str = "codex"
    proxy_socket: Path | None = None
    proxy_port: int = 43123
    proxy_client_token: str | None = None


@dataclass(frozen=True)
class ContainerExecution:
    """Hold captured non-secret process facts for one container execution.

    Parameters
    ----------
    returncode : int
        Container process return code.
    stdout : str
        Captured Codex JSONL output.
    stderr : str
        Captured diagnostic output retained outside public reports.
    elapsed_seconds : float
        Measured wall-clock execution duration.
    timed_out : bool
        Whether the runner delivered timeout cancellation.

    Returns
    -------
    None
        Instances are converted into schema-valid result records.
    """

    returncode: int
    stdout: str
    stderr: str
    elapsed_seconds: float
    timed_out: bool = False


def build_attempt_codex_config(assistance_mode: str) -> str:
    """Build a fresh benchmark-only Codex configuration for one variant.

    Parameters
    ----------
    assistance_mode : str
        ``"baseline"`` or ``"codira-mcp"`` scheduled variant.

    Returns
    -------
    str
        TOML that disables memory/delegation and exposes MCP only to the
        assisted variant.

    Raises
    ------
    ValueError
        If the assistance mode is not part of the paired experiment.
    """

    if assistance_mode == "codira-mcp":
        return phase0.build_isolated_codex_config(codira_root="/workspace")
    if assistance_mode != "baseline":
        message = "assistance mode is unsupported"
        raise ValueError(message)
    return (
        'approval_policy = "never"\n'
        'sandbox_mode = "workspace-write"\n\n'
        "[sandbox_workspace_write]\n"
        "network_access = false\n\n"
        "[shell_environment_policy]\n"
        'inherit = "core"\n'
        "ignore_default_excludes = false\n\n"
        "[features]\n"
        "memories = false\n"
        "multi_agent = false\n"
    )


def write_attempt_codex_config(state_root: Path, assistance_mode: str) -> Path:
    """Create fresh container-visible Codex state for one scheduled variant.

    Parameters
    ----------
    state_root : pathlib.Path
        Absent directory mounted writable at ``/codex-state``.
    assistance_mode : str
        Variant determining whether the required Codira MCP is exposed.

    Returns
    -------
    pathlib.Path
        Written isolated ``config.toml`` path.

    Raises
    ------
    ValueError
        If state already exists or the variant is invalid.
    """

    if state_root.exists():
        message = "attempt state root must be absent"
        raise ValueError(message)
    state_root.mkdir(parents=True)
    config_path = state_root / "config.toml"
    config_path.write_text(
        build_attempt_codex_config(assistance_mode), encoding="utf-8"
    )
    return config_path


def write_proxy_relay(state_root: Path) -> Path:
    """Write the fixed loopback-to-Unix-socket relay for a provider probe.

    Parameters
    ----------
    state_root : pathlib.Path
        Fresh Codex state already mounted at ``/codex-state``.

    Returns
    -------
    pathlib.Path
        Non-secret relay script reachable only in the isolated container.

    Raises
    ------
    ValueError
        If the state root is not a fresh directory.
    """

    path = state_root / "provider_relay.py"
    if not state_root.is_dir() or path.exists():
        raise ValueError("fresh state root must contain no provider relay")
    path.write_text(_PROXY_RELAY_SOURCE, encoding="utf-8")
    return path


def build_container_argv(request: ContainerAttemptRequest) -> tuple[str, ...]:
    """Build the shell-free isolated container command for one Codex attempt.

    Parameters
    ----------
    request : ContainerAttemptRequest
        Frozen container, state, fixture, and prompt configuration.

    Returns
    -------
    tuple[str, ...]
        Runtime command with no host home, socket, credential, or grader mount.

    Raises
    ------
    ValueError
        If isolation inputs are unsafe or incomplete.

    Notes
    -----
    The container has no network route.  A future paid execution must first
    replace this command only through a separately reviewed provider-proxy
    transport; Phase 4 does not silently weaken this containment boundary.
    """

    if request.runtime not in phase0.SUPPORTED_CONTAINER_RUNTIMES:
        raise ValueError("container runtime is unsupported")
    if phase0.IMAGE_DIGEST_PATTERN.fullmatch(request.image) is None:
        raise ValueError("container image must use an exact sha256 digest")
    if request.timeout_seconds < 1 or not request.prompt.strip():
        raise ValueError("timeout and prompt must be non-empty")
    fixture_root = request.fixture_root.resolve()
    state_root = request.state_root.resolve()
    if not fixture_root.is_dir() or not state_root.is_dir():
        raise ValueError("fixture and fresh state roots must exist")
    proxy_enabled = request.proxy_socket is not None
    if proxy_enabled != (request.proxy_client_token is not None):
        raise ValueError("proxy socket and client token must be supplied together")
    if proxy_enabled:
        assert request.proxy_socket is not None
        if not request.proxy_socket.is_socket() or not 1 <= request.proxy_port <= 65535:
            raise ValueError("provider proxy socket and port are invalid")
    command = (
        (
            "/bin/sh",
            "-c",
            _PROXY_RELAY_BOOTSTRAP,
            "phase4-proxy-runner",
            request.prompt,
            request.codex_command,
        )
        if proxy_enabled
        else (
            request.codex_command,
            "exec",
            "--json",
            "--ephemeral",
            "--sandbox",
            "danger-full-access",
            "--ignore-rules",
            "--skip-git-repo-check",
            request.prompt,
        )
    )
    return (
        request.runtime,
        "run",
        "--rm",
        "--network=none",
        "--read-only",
        "--cap-drop=ALL",
        "--security-opt=no-new-privileges",
        "--pids-limit=512",
        "--tmpfs=/tmp:rw,nosuid,nodev,noexec,size=128m",
        f"--cidfile={state_root / 'container.cid'}",
        f"--mount=type=bind,src={fixture_root},dst=/workspace,rw",
        f"--mount=type=bind,src={state_root},dst=/codex-state,rw",
        "--env=HOME=/codex-state/home",
        "--env=CODEX_HOME=/codex-state",
        *(("--env=CODIRA_PROXY_CLIENT_TOKEN",) if proxy_enabled else ()),
        "--workdir=/workspace",
        request.image,
        *command,
    )


def remove_timed_out_container(request: ContainerAttemptRequest) -> None:
    """Force-remove the one container identified by a timed-out attempt.

    Parameters
    ----------
    request : ContainerAttemptRequest
        Attempt whose runtime command was cancelled by the wall-clock limit.

    Returns
    -------
    None
        Cleanup is best-effort: timeout evidence is retained even if the
        runtime has already removed the container or its CID file is absent.
    """

    cidfile = request.state_root.resolve() / "container.cid"
    try:
        container_id = cidfile.read_text(encoding="utf-8").strip()
    except OSError:
        return
    if _CONTAINER_ID_PATTERN.fullmatch(container_id) is None:
        return
    try:
        subprocess.run(
            (request.runtime, "rm", "--force", container_id),
            check=False,
            text=True,
            capture_output=True,
        )
    except OSError:
        return


def execute_container_attempt(request: ContainerAttemptRequest) -> ContainerExecution:
    """Execute a bounded container attempt and capture its JSONL stream.

    Parameters
    ----------
    request : ContainerAttemptRequest
        Frozen isolated execution request.

    Returns
    -------
    ContainerExecution
        Captured terminal process evidence, including timeout cancellation.
    """

    started = time.monotonic()
    try:
        environment = None
        if request.proxy_client_token is not None:
            environment = {
                **os.environ,
                "CODIRA_PROXY_CLIENT_TOKEN": request.proxy_client_token,
            }
        completed = subprocess.run(
            build_container_argv(request),
            check=False,
            text=True,
            capture_output=True,
            timeout=request.timeout_seconds,
            env=environment,
        )
        return ContainerExecution(
            completed.returncode,
            completed.stdout,
            completed.stderr,
            time.monotonic() - started,
        )
    except subprocess.TimeoutExpired as error:
        remove_timed_out_container(request)
        stdout = error.stdout if isinstance(error.stdout, str) else ""
        stderr = error.stderr if isinstance(error.stderr, str) else ""
        return ContainerExecution(
            124, stdout, stderr, time.monotonic() - started, timed_out=True
        )


def result_from_execution(
    campaign_id: str,
    attempt: ScheduledAttempt,
    execution: ContainerExecution,
) -> tuple[dict[str, object], dict[str, object]]:
    """Convert captured execution facts into a schema-valid run-result record.

    Parameters
    ----------
    campaign_id : str
        Frozen campaign identity.
    attempt : ScheduledAttempt
        Frozen schedule identity for the container execution.
    execution : ContainerExecution
        Captured process and JSONL evidence.

    Returns
    -------
    tuple[dict[str, object], dict[str, object]]
        Public run result and private-runtime-safe evidence metadata.
    """

    usage_complete = False
    usage: dict[str, int] = {
        "input_tokens": 0,
        "cached_input_tokens": 0,
        "output_tokens": 0,
        "reasoning_output_tokens": 0,
    }
    failure_class: str | None = None
    outcome = "infrastructure_failure"
    event_count = 0
    if execution.timed_out:
        outcome = "cancelled"
        failure_class = "timeout"
    else:
        try:
            events = phase0.parse_jsonl_events(execution.stdout)
            event_count = len(events)
            check = phase0.jsonl_conformance_check(events, attempt.assistance_mode)
            normalized = normalize_completed_turn(events)
            usage_complete = normalized.complete
            usage = normalized.as_document()
            if execution.returncode == 0 and check.passed:
                outcome = "success"
            else:
                failure_class = check.detail if not check.passed else "nonzero_exit"
        except (phase0.JsonlEvidenceError, UsageError) as error:
            failure_class = str(error)
    result: dict[str, object] = {
        "schema_version": CONTRACT_VERSION,
        "campaign_id": campaign_id,
        "task_id": attempt.task_id,
        "attempt_id": attempt.attempt_id,
        "assistance_mode": attempt.assistance_mode,
        "outcome": outcome,
        "failure_class": failure_class,
        "usage_complete": usage_complete,
        "usage": usage,
        "provenance": {"runner": "container-jsonl", "runner_version": CONTRACT_VERSION},
    }
    evidence: dict[str, object] = {
        "returncode": execution.returncode,
        "elapsed_seconds": round(execution.elapsed_seconds, 6),
        "timed_out": execution.timed_out,
        "jsonl_event_count": event_count,
        "stdout_sha256": _text_sha256(execution.stdout),
        "stderr_sha256": _text_sha256(execution.stderr),
    }
    return result, evidence


def _text_sha256(value: str) -> str:
    """Return a SHA-256 digest without embedding raw diagnostic text.

    Parameters
    ----------
    value : str
        Captured process output.

    Returns
    -------
    str
        Lowercase hexadecimal SHA-256 digest.
    """

    import hashlib

    return hashlib.sha256(value.encode("utf-8")).hexdigest()
