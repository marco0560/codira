"""Run one benchmark attempt in a constrained container and retain JSONL facts."""
# ruff: noqa: EM101, TRY003

from __future__ import annotations

import difflib
import json
import os
import re
import subprocess
import time
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING

from scripts.agent_efficiency import phase0
from scripts.agent_efficiency.contracts import CONTRACT_VERSION
from scripts.agent_efficiency.usage import UsageError, normalize_completed_turn

_CONTAINER_ID_PATTERN = re.compile(r"^[0-9a-f]{64}$")
PROJECT_TEMP_ROOT = Path("/home/marco/Personalia/Progetti/.Temp")

if TYPE_CHECKING:
    from scripts.agent_efficiency.campaign_state import ScheduledAttempt
    from scripts.agent_efficiency.environment import FixtureEnvironment

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
    temporary_root : pathlib.Path, optional
        Operation-scoped host scratch directory mounted at ``/temporary``.

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
    temporary_root: Path | None = None


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


@dataclass(frozen=True)
class IndexPreparationRequest:
    """Describe a pre-timer Codira index preparation container.

    Parameters
    ----------
    runtime : str
        Supported container runtime executable.
    image : str
        Digest-pinned reviewed benchmark image.
    fixture_root : pathlib.Path
        Disposable writable exported fixture to index before MCP startup.
    timeout_seconds : int
        Positive wall-clock limit for the non-agent preparation step.
    codira_config_path : str
        Absolute container-visible profile used by both index and MCP startup.
    temporary_root : pathlib.Path, optional
        Operation-scoped host scratch directory mounted at ``/temporary``.
    """

    runtime: str
    image: str
    fixture_root: Path
    timeout_seconds: int
    codira_config_path: str
    temporary_root: Path | None = None


@dataclass(frozen=True)
class EnvironmentPreparationRequest:
    """Describe one offline fixture-environment preparation container.

    Parameters
    ----------
    runtime : str
        Supported container runtime executable.
    image : str
        Digest-pinned reviewed benchmark image.
    fixture_root : pathlib.Path
        Exported writable fixture whose environment is prepared before a turn.
    timeout_seconds : int
        Positive wall-clock limit for pre-agent preparation.
    environment : scripts.agent_efficiency.environment.FixtureEnvironment
        Deterministically selected locked package-manager plan.
    temporary_root : pathlib.Path, optional
        Operation-scoped host scratch directory mounted at ``/temporary``.

    Returns
    -------
    None
        Instances bind the no-network preparation command to one fixture.
    """

    runtime: str
    image: str
    fixture_root: Path
    timeout_seconds: int
    environment: FixtureEnvironment
    temporary_root: Path | None = None


def _temporary_mount_options(temporary_root: Path | None) -> tuple[str, ...]:
    """Build container temp mount and environment options.

    Parameters
    ----------
    temporary_root : pathlib.Path or None
        Existing operation-scoped host scratch directory.

    Returns
    -------
        tuple[str, ...]
        A project-scratch bind mount plus temp variables, or an isolated tmpfs
        fallback when no host scratch directory is provided.

    Raises
    ------
    ValueError
        If the requested host scratch directory is unavailable.
    """

    if temporary_root is None:
        return ("--tmpfs=/tmp:rw,nosuid,nodev,noexec,size=128m",)
    root = temporary_root.resolve()
    if not root.is_dir():
        raise ValueError("container temporary root must be an existing directory")
    return (
        f"--mount=type=bind,src={root},dst=/temporary,rw",
        "--tmpfs=/tmp:rw,nosuid,nodev,noexec,size=128m",
        "--env=TMPDIR=/temporary",
        "--env=TMP=/temporary",
        "--env=TEMP=/temporary",
        "--env=UV_CACHE_DIR=/temporary/uv-cache",
        "--env=UV_PYTHON_INSTALL_DIR=/temporary/uv-python",
    )


@lru_cache(maxsize=8)
def codex_model_base_instructions(runtime: str, image: str) -> str:
    """Read the native Codex instruction template from a pinned image.

    Parameters
    ----------
    runtime : str
        Supported container runtime executable.
    image : str
        Digest-pinned benchmark image containing the Codex CLI.

    Returns
    -------
    str
        Exact base instructions from the image's bundled Codex catalog.

    Raises
    ------
    TypeError
        If the bundled model catalog has an unexpected shape.
    ValueError
        If the runtime image or its bundled model catalog is unavailable.
    """

    if (
        runtime not in phase0.SUPPORTED_CONTAINER_RUNTIMES
        or phase0.IMAGE_DIGEST_PATTERN.fullmatch(image) is None
    ):
        raise ValueError("Codex instruction source must use the pinned runtime image")
    completed = subprocess.run(
        (
            runtime,
            "run",
            "--rm",
            "--network=none",
            "--read-only",
            "--cap-drop=ALL",
            "--security-opt=no-new-privileges",
            "--pids-limit=64",
            "--tmpfs=/tmp:rw,nosuid,nodev,noexec,size=64m",
            "--env=CODEX_HOME=/tmp/codex-state",
            "--env=HOME=/tmp/codex-home",
            "--workdir=/workspace",
            image,
            "/bin/sh",
            "-c",
            "mkdir -p /tmp/codex-state /tmp/codex-home && codex debug models --bundled",
        ),
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )
    if completed.returncode != 0:
        raise ValueError("cannot read the bundled Codex model catalog")
    try:
        document = json.loads(completed.stdout)
    except ValueError as error:
        raise ValueError("bundled Codex model catalog is malformed") from error
    models = document.get("models") if isinstance(document, dict) else None
    if not isinstance(models, list):
        raise TypeError("bundled Codex model catalog is malformed")
    preferred = next(
        (
            item
            for item in models
            if isinstance(item, dict) and item.get("slug") == "gpt-5.6-sol"
        ),
        None,
    )
    candidates = ([preferred] if preferred is not None else []) + models
    instructions = next(
        (
            item.get("base_instructions")
            for item in candidates
            if isinstance(item, dict)
            and isinstance(item.get("base_instructions"), str)
            and item["base_instructions"].strip()
        ),
        None,
    )
    if not isinstance(instructions, str):
        raise TypeError("bundled Codex catalog has no base instructions")
    return instructions


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
        Runtime command without host-home, credential, or grader mounts; an
        enabled provider proxy socket is mounted at its stable container path.

    Raises
    ------
    ValueError
        If isolation inputs are unsafe or incomplete.

    Notes
    -----
    The container has no network route.  When provider proxying is enabled,
    only its Unix socket is mounted separately at ``/codex-state/provider.sock``.
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
    proxy_mount: tuple[str, ...] = ()
    if request.proxy_socket is not None:
        proxy_mount = (
            f"--mount=type=bind,src={request.proxy_socket.resolve()},"
            "dst=/codex-state/provider.sock",
        )
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
        *_temporary_mount_options(request.temporary_root),
        f"--cidfile={state_root / 'container.cid'}",
        f"--mount=type=bind,src={fixture_root},dst=/workspace,rw",
        f"--mount=type=bind,src={state_root},dst=/codex-state,rw",
        *proxy_mount,
        "--env=HOME=/codex-state/home",
        "--env=CODEX_HOME=/codex-state",
        *(("--env=CODIRA_PROXY_CLIENT_TOKEN",) if proxy_enabled else ()),
        "--workdir=/workspace",
        request.image,
        *command,
    )


def build_index_preparation_argv(request: IndexPreparationRequest) -> tuple[str, ...]:
    """Build the isolated command that indexes before Codira MCP can start.

    Parameters
    ----------
    request : IndexPreparationRequest
        Frozen runtime, image, fixture, and bounded preparation controls.

    Returns
    -------
    tuple[str, ...]
        Shell-free hardened container invocation ending with ``codira index``.

    Raises
    ------
    ValueError
        If the runtime, image, fixture, or timeout is unsafe.
    """

    if request.runtime not in phase0.SUPPORTED_CONTAINER_RUNTIMES:
        raise ValueError("container runtime is unsupported")
    if phase0.IMAGE_DIGEST_PATTERN.fullmatch(request.image) is None:
        raise ValueError("container image must use an exact sha256 digest")
    if request.timeout_seconds < 1 or not request.codira_config_path.startswith("/"):
        raise ValueError("index preparation timeout must be positive")
    fixture_root = request.fixture_root.resolve()
    if not fixture_root.is_dir():
        raise ValueError("index preparation fixture root must exist")
    return (
        request.runtime,
        "run",
        "--rm",
        "--network=none",
        "--read-only",
        "--cap-drop=ALL",
        "--security-opt=no-new-privileges",
        "--pids-limit=512",
        *_temporary_mount_options(request.temporary_root),
        f"--mount=type=bind,src={fixture_root},dst=/workspace,rw",
        "--workdir=/workspace",
        request.image,
        "codira",
        "index",
        "--config-file",
        request.codira_config_path,
    )


def execute_index_preparation(request: IndexPreparationRequest) -> ContainerExecution:
    """Run required pre-MCP ``codira index`` outside agent timing.

    Parameters
    ----------
    request : IndexPreparationRequest
        Validated isolated pre-timer preparation request.

    Returns
    -------
    ContainerExecution
        Captured non-secret facts; a timeout is represented explicitly.
    """

    started = time.monotonic()
    try:
        completed = subprocess.run(
            build_index_preparation_argv(request),
            check=False,
            text=True,
            capture_output=True,
            timeout=request.timeout_seconds,
        )
    except subprocess.TimeoutExpired as error:
        stdout = (
            error.stdout.decode() if isinstance(error.stdout, bytes) else error.stdout
        )
        stderr = (
            error.stderr.decode() if isinstance(error.stderr, bytes) else error.stderr
        )
        return ContainerExecution(
            124,
            stdout or "",
            stderr or "",
            time.monotonic() - started,
            timed_out=True,
        )
    return ContainerExecution(
        completed.returncode,
        completed.stdout,
        completed.stderr,
        time.monotonic() - started,
    )


def build_environment_preparation_argv(
    request: EnvironmentPreparationRequest,
) -> tuple[str, ...]:
    """Build the hardened offline command that prepares one fixture environment.

    Parameters
    ----------
    request : EnvironmentPreparationRequest
        Runtime, immutable image, fixture, and selected environment plan.

    Returns
    -------
    tuple[str, ...]
        Shell-free no-network container invocation ending in the plan command.

    Raises
    ------
    ValueError
        If runtime, image, fixture, or timeout inputs are unsafe.
    """

    if request.runtime not in phase0.SUPPORTED_CONTAINER_RUNTIMES:
        raise ValueError("container runtime is unsupported")
    if phase0.IMAGE_DIGEST_PATTERN.fullmatch(request.image) is None:
        raise ValueError("container image must use an exact sha256 digest")
    if request.timeout_seconds < 1 or not request.fixture_root.resolve().is_dir():
        raise ValueError("environment preparation inputs are invalid")
    return (
        request.runtime,
        "run",
        "--rm",
        "--network=none",
        "--read-only",
        "--cap-drop=ALL",
        "--security-opt=no-new-privileges",
        "--pids-limit=512",
        *_temporary_mount_options(request.temporary_root),
        f"--mount=type=bind,src={request.fixture_root.resolve()},dst=/workspace,rw",
        "--workdir=/workspace",
        request.image,
        *request.environment.prepare_argv,
    )


def execute_environment_preparation(
    request: EnvironmentPreparationRequest,
) -> ContainerExecution:
    """Prepare a locked fixture environment before the agent timer begins.

    Parameters
    ----------
    request : EnvironmentPreparationRequest
        Immutable no-network preparation container request.

    Returns
    -------
    ContainerExecution
        Captured pre-agent execution facts, including timeout state.
    """

    started = time.monotonic()
    try:
        completed = subprocess.run(
            build_environment_preparation_argv(request),
            check=False,
            text=True,
            capture_output=True,
            timeout=request.timeout_seconds,
        )
    except subprocess.TimeoutExpired as error:
        stdout = (
            error.stdout.decode() if isinstance(error.stdout, bytes) else error.stdout
        )
        stderr = (
            error.stderr.decode() if isinstance(error.stderr, bytes) else error.stderr
        )
        return ContainerExecution(
            124, stdout or "", stderr or "", time.monotonic() - started, True
        )
    return ContainerExecution(
        completed.returncode,
        completed.stdout,
        completed.stderr,
        time.monotonic() - started,
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


def capture_workspace_patch(
    baseline_root: Path, workspace_root: Path, patch_path: Path
) -> None:
    """Capture agent workspace edits as a treatment-neutral unified patch.

    The exported fixture deliberately has no Git history, so the runner keeps
    a private pre-agent snapshot and produces the patch after the turn.  The
    snapshot is never mounted into the agent container.

    Parameters
    ----------
    baseline_root : pathlib.Path
        Private pre-agent fixture snapshot.
    workspace_root : pathlib.Path
        Agent-visible workspace after completion.
    patch_path : pathlib.Path
        Safe workspace-relative destination for the captured patch.

    Returns
    -------
    None
        The patch is written only to ``patch_path``.

    Raises
    ------
    ValueError
        If a candidate workspace contains a symlink or non-text changed file.
    """

    ignored = {".benchmark", ".git", ".venv", "__pycache__"}

    def files(root: Path) -> set[Path]:
        """Return safe regular workspace files excluding runner metadata."""

        discovered: set[Path] = set()
        for candidate in root.rglob("*"):
            relative = candidate.relative_to(root)
            if ignored.intersection(relative.parts):
                continue
            if candidate.is_symlink():
                raise ValueError("workspace patch capture rejects symlinks")
            if candidate.is_file():
                discovered.add(relative)
        return discovered

    lines: list[str] = []
    for relative in sorted(files(baseline_root) | files(workspace_root)):
        before, after = baseline_root / relative, workspace_root / relative
        before_bytes = before.read_bytes() if before.is_file() else None
        after_bytes = after.read_bytes() if after.is_file() else None
        if before_bytes == after_bytes:
            continue
        if any(
            value is not None and b"\0" in value
            for value in (before_bytes, after_bytes)
        ):
            raise ValueError("workspace patch capture rejects binary changes")
        label = relative.as_posix()
        lines.append(f"diff --git a/{label} b/{label}")
        if before_bytes is None:
            assert after_bytes is not None
            lines.append("new file mode 100644")
            diff = difflib.unified_diff(
                [],
                after_bytes.decode("utf-8").splitlines(),
                fromfile="/dev/null",
                tofile=f"b/{label}",
                lineterm="",
            )
        elif after_bytes is None:
            assert before_bytes is not None
            lines.append("deleted file mode 100644")
            diff = difflib.unified_diff(
                before_bytes.decode("utf-8").splitlines(),
                [],
                fromfile=f"a/{label}",
                tofile="/dev/null",
                lineterm="",
            )
        else:
            assert before_bytes is not None
            diff = difflib.unified_diff(
                before_bytes.decode("utf-8").splitlines(),
                after_bytes.decode("utf-8").splitlines(),
                fromfile=f"a/{label}",
                tofile=f"b/{label}",
                lineterm="",
            )
        lines.extend(diff)
    patch_path.parent.mkdir(parents=True, exist_ok=True)
    patch_path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


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
    *,
    max_total_tokens: int | None = None,
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
    max_total_tokens : int or None, optional
        Manifest-bound total provider-token ceiling. ``None`` retains the
        generic runner behavior used by non-pilot callers.

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
            terminal_failure = _terminal_failure_class(events)
            if terminal_failure is not None:
                failure_class = terminal_failure
            else:
                check = phase0.jsonl_conformance_check(events, attempt.assistance_mode)
                normalized = normalize_completed_turn(events)
                usage_complete = normalized.complete
                usage = normalized.as_document()
                total_tokens = normalized.observed_total_tokens
                if (
                    max_total_tokens is not None
                    and total_tokens is not None
                    and total_tokens > max_total_tokens
                ):
                    failure_class = "usage_cap_exceeded"
                elif execution.returncode == 0 and check.passed:
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


def _terminal_failure_class(events: tuple[dict[str, object], ...]) -> str | None:
    """Classify a failed Codex terminal event without losing its evidence.

    Parameters
    ----------
    events : tuple[dict[str, object], ...]
        Parsed JSONL events captured from one Codex invocation.

    Returns
    -------
    str or None
        Stable public-safe failure class for one failed terminal event, or
        ``None`` when usage normalization should process a completed turn.
    """

    completed = [event for event in events if event.get("type") == "turn.completed"]
    failed = [event for event in events if event.get("type") == "turn.failed"]
    if completed or len(failed) != 1:
        return None
    error = failed[0].get("error")
    message = error.get("message", "") if isinstance(error, dict) else ""
    if isinstance(message, str) and "429" in message:
        return "provider_rate_limited"
    return "turn_failed"


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
