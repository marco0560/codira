"""Validate agent-runner and container isolation prerequisites.

Responsibilities
----------------
- Inspect the pinned Codex CLI and a supported container runtime.
- Generate a minimal, required-Codira-MCP configuration for clean runs.
- Validate Codex JSONL evidence before measured benchmark results are admitted.

Design principles
-----------------
The verifier treats unavailable tools and incomplete evidence as failures. It
does not execute a paid agent turn; a separately approved live probe supplies
the JSONL transcript for validation.

Architectural role
------------------
This module belongs to the developer tooling layer for issue #53 Phase 0.
"""

from __future__ import annotations

import json
import re
import shutil
import signal
import subprocess
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.parse import urlparse

SUPPORTED_CONTAINER_RUNTIMES = ("docker", "podman")
ASSISTANCE_MODES = ("baseline", "codira-mcp")
REQUIRED_CODEX_EXEC_FLAGS = (
    "--json",
    "--ephemeral",
    "--sandbox",
    "--ignore-rules",
)
REQUIRED_USAGE_FIELDS = (
    "input_tokens",
    "cached_input_tokens",
    "output_tokens",
    "reasoning_output_tokens",
)
IMAGE_DIGEST_PATTERN = re.compile(r"^.+@sha256:[0-9a-f]{64}$")
RunCommand = Callable[[Sequence[str]], subprocess.CompletedProcess[str]]
REQUIRED_ESCAPE_PROBES = (
    "host-memory-read",
    "oracle-read",
    "outside-fixture-write",
    "direct-network",
    "host-docker-socket",
)
SAFE_ENVIRONMENT_KEYS = ("LANG", "LC_ALL", "PATH", "SSL_CERT_FILE", "TZ")


@dataclass(frozen=True)
class CheckResult:
    """Describe one deterministic Phase 0 prerequisite check.

    Parameters
    ----------
    name : str
        Stable check identifier.
    passed : bool
        Whether the prerequisite was demonstrated.
    detail : str
        Human-readable result without secrets.

    Returns
    -------
    None
        Instances are immutable evidence records.
    """

    name: str
    passed: bool
    detail: str


class JsonlEvidenceError(ValueError):
    """Raised when a Codex JSONL transcript is malformed or incomplete.

    Parameters
    ----------
    detail : str
        Specific transcript-validation failure.

    Returns
    -------
    None
        The exception reports deterministic evidence rejection.
    """

    def __init__(self, detail: str) -> None:
        """Initialize a JSONL evidence validation failure.

        Parameters
        ----------
        detail : str
            Specific transcript-validation failure.

        Returns
        -------
        None
            The exception is initialized with a stable detail message.
        """

        super().__init__(detail)


@dataclass(frozen=True)
class ConformanceReport:
    """Collect Phase 0 checks and produce a serializable result.

    Parameters
    ----------
    checks : tuple[CheckResult, ...]
        Ordered prerequisite results.

    Returns
    -------
    None
        Instances expose the aggregate readiness state.
    """

    checks: tuple[CheckResult, ...]

    @property
    def ready(self) -> bool:
        """Return whether every conformance prerequisite passed.

        Parameters
        ----------
        None

        Returns
        -------
        bool
            ``True`` only when every check passed.
        """

        return all(check.passed for check in self.checks)

    def as_dict(self) -> dict[str, object]:
        """Render the report into deterministic JSON-compatible data.

        Parameters
        ----------
        None

        Returns
        -------
        dict[str, object]
            Aggregate readiness and ordered check rows.
        """

        return {
            "schema_version": "1.0",
            "phase": "runner-and-isolation-conformance",
            "ready": self.ready,
            "checks": [asdict(check) for check in self.checks],
        }


@dataclass(frozen=True)
class HostConformanceRequest:
    """Identify the host resources required for one Phase 0 inspection.

    Parameters
    ----------
    codex : str
        Codex executable name or absolute path.
    runtime : str
        Container runtime executable.
    image : str
        Exact digest-pinned benchmark image reference.
    state_root : pathlib.Path
        Empty per-run Codex state root.
    repository_root : pathlib.Path
        Implementation checkout root.

    Returns
    -------
    None
        Instances provide one immutable prerequisite request.
    """

    codex: str
    runtime: str
    image: str
    state_root: Path
    repository_root: Path


@dataclass(frozen=True)
class ContainerProbeRequest:
    """Identify the constrained container used for a non-agent isolation probe.

    Parameters
    ----------
    runtime : str
        Supported container runtime executable.
    image : str
        Exact digest-pinned image used for the probe.
    fixture_root : pathlib.Path
        Disposable fixture visible to the probe container.
    command : str
        Deterministic shell command that tests one containment property.

    Returns
    -------
    None
        Instances define a reproducible container probe without credentials,
        host state, or hidden grading data.
    """

    runtime: str
    image: str
    fixture_root: Path
    command: str


@dataclass(frozen=True)
class ContaminationFixture:
    """Locate deterministic public and protected data for an isolation probe.

    Parameters
    ----------
    agent_root : pathlib.Path
        Tree mounted at ``/workspace`` for the probe container.
    host_memory_sentinel : pathlib.Path
        Host-only file representing a personal-memory contamination attempt.
    hidden_oracle : pathlib.Path
        Host-only file representing grader data that agents must not read.

    Returns
    -------
    None
        Instances identify the three deterministic fixture targets.
    """

    agent_root: Path
    host_memory_sentinel: Path
    hidden_oracle: Path


def create_contamination_fixture(root: Path) -> ContaminationFixture:
    """Create deterministic public and protected sentinel files for Phase 0.

    Parameters
    ----------
    root : pathlib.Path
        Empty or newly created root outside the benchmark agent's writable
        fixture mount.

    Returns
    -------
    ContaminationFixture
        Paths for the agent-visible fixture and the two protected sentinels.

    Raises
    ------
    ValueError
        If a pre-existing root contains files that could contaminate a probe.
    """

    if root.exists() and any(root.iterdir()):
        message = "contamination fixture root must be empty"
        raise ValueError(message)
    agent_root = root / "agent-fixture"
    protected_root = root / "protected"
    agent_root.mkdir(parents=True, exist_ok=False)
    protected_root.mkdir()
    (agent_root / "README.txt").write_text(
        "Public benchmark fixture. Protected sentinels are not mounted.\n",
        encoding="utf-8",
    )
    host_memory_sentinel = protected_root / "host-memory-sentinel.txt"
    host_memory_sentinel.write_text(
        "personal-memory-must-not-be-visible\n", encoding="utf-8"
    )
    hidden_oracle = protected_root / "hidden-oracle.txt"
    hidden_oracle.write_text("grader-data-must-not-be-visible\n", encoding="utf-8")
    return ContaminationFixture(agent_root, host_memory_sentinel, hidden_oracle)


def build_container_probe_argv(request: ContainerProbeRequest) -> tuple[str, ...]:
    """Build a credential-free, network-disabled containment probe command.

    Parameters
    ----------
    request : ContainerProbeRequest
        Exact runtime, image, fixture, and deterministic probe command.

    Returns
    -------
    tuple[str, ...]
        Shell-free container-runtime argument vector. It has no credential,
        host-state, grading, or Docker-socket mount.

    Raises
    ------
    ValueError
        If the runtime, image, fixture root, or probe command is unsafe.
    """

    if request.runtime not in SUPPORTED_CONTAINER_RUNTIMES:
        supported = ", ".join(SUPPORTED_CONTAINER_RUNTIMES)
        message = f"runtime must be one of: {supported}"
        raise ValueError(message)
    if IMAGE_DIGEST_PATTERN.fullmatch(request.image) is None:
        message = "image must use an exact sha256 digest"
        raise ValueError(message)
    fixture_root = request.fixture_root.resolve()
    if not fixture_root.is_dir():
        message = "fixture root must be an existing directory"
        raise ValueError(message)
    if not request.command.strip():
        message = "probe command must not be empty"
        raise ValueError(message)
    return (
        request.runtime,
        "run",
        "--rm",
        "--network=none",
        "--read-only",
        "--cap-drop=ALL",
        "--security-opt=no-new-privileges",
        "--pids-limit=256",
        "--tmpfs=/tmp:rw,nosuid,nodev,noexec,size=64m",
        f"--mount=type=bind,src={fixture_root},dst=/workspace",
        "--workdir=/workspace",
        request.image,
        "/bin/sh",
        "-lc",
        request.command,
    )


def isolated_config_check(
    codira_root: str = "/workspace/fixture",
    proxy_url: str | None = None,
    model: str | None = None,
    reasoning_effort: str | None = None,
) -> CheckResult:
    """Validate the benchmark-only Codex configuration before a live probe.

    Parameters
    ----------
    codira_root : str, optional
        Container-visible fixture root passed to the Codira MCP server.
    proxy_url : str or None, optional
        Loopback OpenRouter proxy URL for the fresh Codex configuration.
    model : str or None, optional
        Provider model selected by the approved execution manifest.
    reasoning_effort : str or None, optional
        Provider reasoning effort selected by that manifest.

    Returns
    -------
    CheckResult
        Passing result only when the configuration is parseable and declares
        exactly one required MCP server.
    """

    try:
        import tomllib

        parsed = tomllib.loads(
            build_isolated_codex_config(codira_root, proxy_url, model, reasoning_effort)
        )
    except (TypeError, ValueError) as error:
        return CheckResult("isolated-config", False, f"invalid TOML: {error}")
    mcp_servers = parsed.get("mcp_servers")
    if not isinstance(mcp_servers, dict) or set(mcp_servers) != {"codira"}:
        return CheckResult(
            "isolated-config", False, "configuration must declare only Codira MCP"
        )
    codira = mcp_servers["codira"]
    if not isinstance(codira, dict) or codira.get("required") is not True:
        return CheckResult("isolated-config", False, "Codira MCP must be required")
    if parsed.get("sandbox_mode") != "workspace-write":
        return CheckResult("isolated-config", False, "workspace-write sandbox required")
    workspace_write = parsed.get("sandbox_workspace_write")
    if (
        not isinstance(workspace_write, dict)
        or workspace_write.get("network_access") is not False
    ):
        return CheckResult("isolated-config", False, "task network must be disabled")
    features = parsed.get("features")
    if not isinstance(features, dict) or features.get("memories") is not False:
        return CheckResult("isolated-config", False, "Codex memories must be disabled")
    if features.get("multi_agent") is not False:
        return CheckResult(
            "isolated-config", False, "multi-agent delegation must be disabled"
        )
    shell_policy = parsed.get("shell_environment_policy")
    if not isinstance(shell_policy, dict) or shell_policy.get("inherit") != "core":
        return CheckResult(
            "isolated-config", False, "core-only shell environment is required"
        )
    if shell_policy.get("ignore_default_excludes") is not False:
        return CheckResult(
            "isolated-config", False, "default secret exclusions must remain active"
        )
    if proxy_url is not None:
        model_providers = parsed.get("model_providers")
        provider = (
            model_providers.get("benchmark-openrouter-proxy")
            if isinstance(model_providers, dict)
            else None
        )
        if not isinstance(provider, dict) or provider.get("base_url") != proxy_url:
            return CheckResult(
                "isolated-config", False, "OpenRouter proxy URL is missing"
            )
        if (
            parsed.get("model_provider") != "benchmark-openrouter-proxy"
            or parsed.get("model") != model
            or parsed.get("model_reasoning_effort") != reasoning_effort
            or provider.get("env_key") != "CODIRA_PROXY_CLIENT_TOKEN"
            or provider.get("wire_api") != "responses"
            or provider.get("requires_openai_auth") is not False
        ):
            return CheckResult(
                "isolated-config", False, "OpenRouter provider contract is invalid"
            )
    return CheckResult("isolated-config", True, "only required Codira MCP configured")


def run_command(arguments: Sequence[str]) -> subprocess.CompletedProcess[str]:
    """Run a non-interactive prerequisite command with captured text output.

    Parameters
    ----------
    arguments : collections.abc.Sequence[str]
        Command vector to execute without shell interpolation.

    Returns
    -------
    subprocess.CompletedProcess[str]
        Completed process result. Missing executables are represented by a
        return code of 127.
    """

    try:
        return subprocess.run(
            list(arguments),
            check=False,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        return subprocess.CompletedProcess(list(arguments), 127, "", "not found")


def executable_check(executable: str, runner: RunCommand = run_command) -> CheckResult:
    """Check that one executable exists and returns a non-empty version.

    Parameters
    ----------
    executable : str
        Executable name or absolute path.
    runner : collections.abc.Callable, optional
        Collaborator used to execute the version command.

    Returns
    -------
    CheckResult
        Passing result with a trimmed version string, or a failure detail.
    """

    resolved = (
        shutil.which(executable) if Path(executable).name == executable else executable
    )
    if resolved is None:
        return CheckResult(executable, False, "executable not found on PATH")
    completed = runner((resolved, "--version"))
    version = (completed.stdout or completed.stderr).strip().splitlines()
    if completed.returncode != 0 or not version:
        return CheckResult(executable, False, "version command did not succeed")
    return CheckResult(executable, True, version[0])


def codex_help_check(codex: str, runner: RunCommand = run_command) -> CheckResult:
    """Check that the Codex executable advertises required exec options.

    Parameters
    ----------
    codex : str
        Codex executable name or absolute path.
    runner : collections.abc.Callable, optional
        Collaborator used to execute the help command.

    Returns
    -------
    CheckResult
        Passing result only when all required isolation and JSONL flags appear.
    """

    completed = runner((codex, "exec", "--help"))
    text = f"{completed.stdout}\n{completed.stderr}"
    missing = tuple(flag for flag in REQUIRED_CODEX_EXEC_FLAGS if flag not in text)
    if completed.returncode != 0:
        return CheckResult("codex-exec-help", False, "codex exec --help failed")
    if missing:
        return CheckResult(
            "codex-exec-help",
            False,
            f"missing required flags: {', '.join(missing)}",
        )
    return CheckResult(
        "codex-exec-help", True, "required JSONL and isolation flags present"
    )


def container_image_check(
    runtime: str,
    image: str,
    runner: RunCommand = run_command,
) -> CheckResult:
    """Check a supported runtime and an exact available container image digest.

    Parameters
    ----------
    runtime : str
        Supported container runtime executable.
    image : str
        Image reference pinned with a SHA-256 digest.
    runner : collections.abc.Callable, optional
        Collaborator used to inspect the local image store.

    Returns
    -------
    CheckResult
        Passing result only when the image is digest-pinned and locally present.
    """

    if runtime not in SUPPORTED_CONTAINER_RUNTIMES:
        supported = ", ".join(SUPPORTED_CONTAINER_RUNTIMES)
        return CheckResult(
            "container-image", False, f"runtime must be one of: {supported}"
        )
    if IMAGE_DIGEST_PATTERN.fullmatch(image) is None:
        return CheckResult(
            "container-image", False, "image must use an exact sha256 digest"
        )
    completed = runner((runtime, "image", "inspect", image))
    if completed.returncode != 0:
        return CheckResult(
            "container-image", False, "pinned image is unavailable locally"
        )
    return CheckResult("container-image", True, image)


def empty_isolated_state_check(state_root: Path, repository_root: Path) -> CheckResult:
    """Verify a fresh state root exists outside the implementation checkout.

    Parameters
    ----------
    state_root : pathlib.Path
        Intended fresh Codex state directory for one benchmark execution.
    repository_root : pathlib.Path
        Implementation checkout that must not contain benchmark state.

    Returns
    -------
    CheckResult
        Passing result only for an empty state directory outside the checkout.
    """

    resolved_state = state_root.resolve()
    resolved_repository = repository_root.resolve()
    if (
        resolved_state == resolved_repository
        or resolved_repository in resolved_state.parents
    ):
        return CheckResult(
            "isolated-state", False, "state root is inside implementation checkout"
        )
    if state_root.exists() and any(state_root.iterdir()):
        return CheckResult(
            "isolated-state", False, "state root must be empty for a fresh run"
        )
    return CheckResult("isolated-state", True, str(resolved_state))


def build_isolated_codex_config(
    codira_root: str = "/workspace/fixture",
    proxy_url: str | None = None,
    model: str | None = None,
    reasoning_effort: str | None = None,
    mcp_command: str | None = "codira-mcp",
) -> str:
    """Build the minimal benchmark Codex configuration with required MCP.

    Parameters
    ----------
    codira_root : str, optional
        Container-visible fixture root bound to the Codira MCP server.
    proxy_url : str or None, optional
        Loopback URL of the runner-side OpenRouter proxy. The URL is not a
        credential and may be omitted for non-agent containment probes.
    model : str or None, optional
        Pinned provider model selected by an approved execution manifest.
    reasoning_effort : str or None, optional
        Provider reasoning effort selected by that manifest.
    mcp_command : str or None, optional
        Resolved host-visible Codira MCP executable, or ``None`` to expose no
        MCP server to the baseline condition.

    Returns
    -------
    str
        TOML configuration for a fresh ``CODEX_HOME``. It disables memories,
        delegation, task-network access, and inherited secret variables while
        declaring only the required Codira MCP server.

    Raises
    ------
    ValueError
        If provider settings are incomplete or ``proxy_url`` is not a loopback
        HTTP(S) URL ending in ``/v1``.
    """

    root_configuration = 'approval_policy = "never"\nsandbox_mode = "workspace-write"\n'
    escaped_root = codira_root.replace("\\", "\\\\").replace('"', '\\"')
    configuration = (
        root_configuration + "\n"
        "[sandbox_workspace_write]\n"
        "network_access = false\n\n"
        "[shell_environment_policy]\n"
        'inherit = "core"\n'
        "ignore_default_excludes = false\n\n"
        "[features]\n"
        "memories = false\n"
        "multi_agent = false\n"
    )
    if mcp_command is not None:
        escaped_mcp_command = mcp_command.replace("\\", "\\\\").replace('"', '\\"')
        configuration += (
            "\n[mcp_servers.codira]\n"
            f'command = "{escaped_mcp_command}"\n'
            f'args = ["--root", "{escaped_root}"]\n'
            "required = true\n"
        )
    if proxy_url is None:
        if model is not None or reasoning_effort is not None:
            message = "model settings require a provider proxy URL"
            raise ValueError(message)
        return configuration
    if not model or not reasoning_effort:
        message = "provider proxy configuration requires model and reasoning effort"
        raise ValueError(message)
    parsed_url = urlparse(proxy_url)
    if (
        parsed_url.scheme not in {"http", "https"}
        or parsed_url.hostname not in {"127.0.0.1", "localhost"}
        or parsed_url.path != "/v1"
        or parsed_url.params
        or parsed_url.query
        or parsed_url.fragment
        or parsed_url.username is not None
        or parsed_url.password is not None
    ):
        message = "provider proxy URL must use HTTP(S) loopback ending in /v1"
        raise ValueError(message)
    escaped_proxy = proxy_url.replace("\\", "\\\\").replace('"', '\\"')
    escaped_model = model.replace("\\", "\\\\").replace('"', '\\"')
    escaped_effort = reasoning_effort.replace("\\", "\\\\").replace('"', '\\"')
    provider_configuration = (
        f'model = "{escaped_model}"\n'
        f'model_reasoning_effort = "{escaped_effort}"\n'
        'model_provider = "benchmark-openrouter-proxy"\n\n'
        "[model_providers.benchmark-openrouter-proxy]\n"
        'name = "Benchmark OpenRouter proxy"\n'
        f'base_url = "{escaped_proxy}"\n'
        'env_key = "CODIRA_PROXY_CLIENT_TOKEN"\n'
        'wire_api = "responses"\n'
        "requires_openai_auth = false\n\n"
    )
    return (
        root_configuration
        + "\n"
        + provider_configuration
        + configuration.removeprefix(root_configuration)
    )


def write_isolated_codex_config(
    state_root: Path,
    codira_root: str = "/workspace/fixture",
    proxy_url: str | None = None,
    provider_settings: tuple[str, str] | None = None,
    mcp_command: str | None = "codira-mcp",
) -> Path:
    """Write the only user-level Codex configuration for one benchmark run.

    Parameters
    ----------
    state_root : pathlib.Path
        Fresh per-run ``CODEX_HOME`` outside the fixture and implementation
        checkout.
    codira_root : str, optional
        Container-visible fixture root passed to the Codira MCP server.
    proxy_url : str or None, optional
        Loopback URL of the runner-side OpenRouter proxy.
    provider_settings : tuple[str, str] or None, optional
        Provider model and reasoning effort selected by the approved execution
        manifest.
    mcp_command : str or None, optional
        Resolved host-visible Codira MCP executable, or ``None`` for a
        baseline configuration without MCP access.

    Returns
    -------
    pathlib.Path
        Generated ``config.toml`` path beneath the fresh state root.
    """

    state_root.mkdir(parents=True, exist_ok=False)
    model, reasoning_effort = provider_settings or (None, None)
    config_path = state_root / "config.toml"
    config_path.write_text(
        build_isolated_codex_config(
            codira_root, proxy_url, model, reasoning_effort, mcp_command
        ),
        encoding="utf-8",
    )
    return config_path


def isolated_environment(
    base_environment: Mapping[str, str], state_root: Path
) -> dict[str, str]:
    """Build a child environment that replaces inherited Codex state.

    Parameters
    ----------
    base_environment : collections.abc.Mapping[str, str]
        Parent environment used only for non-Codex process necessities.
    state_root : pathlib.Path
        Empty per-run state root mounted inside the isolated execution boundary.

    Returns
    -------
    dict[str, str]
        Curated environment containing only safe runtime settings, a fresh
        home directory, and a fresh ``CODEX_HOME``. Credentials are excluded.
    """

    environment = {
        key: base_environment[key]
        for key in SAFE_ENVIRONMENT_KEYS
        if key in base_environment
    }
    environment["HOME"] = str(state_root / "home")
    environment["CODEX_HOME"] = str(state_root)
    return environment


def isolated_environment_check(environment: Mapping[str, str]) -> CheckResult:
    """Reject inherited credentials and non-isolated Codex state selectors.

    Parameters
    ----------
    environment : collections.abc.Mapping[str, str]
        Exact environment planned for the benchmark-agent process.

    Returns
    -------
    CheckResult
        Passing result only for the curated environment emitted by
        :func:`isolated_environment`.
    """

    allowed = set(SAFE_ENVIRONMENT_KEYS) | {"CODEX_HOME", "HOME"}
    unexpected = sorted(set(environment) - allowed)
    if unexpected:
        return CheckResult(
            "isolated-environment",
            False,
            f"unexpected inherited variables: {', '.join(unexpected)}",
        )
    if not environment.get("CODEX_HOME") or not environment.get("HOME"):
        return CheckResult(
            "isolated-environment", False, "fresh CODEX_HOME and HOME are required"
        )
    return CheckResult(
        "isolated-environment", True, "environment excludes credentials and host state"
    )


def parse_jsonl_events(text: str) -> tuple[dict[str, object], ...]:
    """Parse non-empty Codex JSONL output into event objects.

    Parameters
    ----------
    text : str
        Complete JSON Lines transcript captured from Codex standard output.

    Returns
    -------
    tuple[dict[str, object], ...]
        Parsed events in stream order.

    Raises
    ------
    ValueError
        If a line is invalid JSON or does not contain an object.
    """

    events: list[dict[str, object]] = []
    for number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError as error:
            detail = f"JSONL line {number} is invalid"
            raise JsonlEvidenceError(detail) from error
        if not isinstance(event, dict):
            detail = f"JSONL line {number} is not an object"
            raise JsonlEvidenceError(detail)
        events.append(event)
    if not events:
        detail = "JSONL transcript is empty"
        raise JsonlEvidenceError(detail)
    return tuple(events)


def jsonl_conformance_check(
    events: Sequence[Mapping[str, object]],
    assistance_mode: str = "codira-mcp",
) -> CheckResult:
    """Validate the minimum evidence needed to admit one assisted run.

    Parameters
    ----------
    events : collections.abc.Sequence[collections.abc.Mapping[str, object]]
        Parsed Codex JSONL events for one completed assisted execution.
    assistance_mode : str, optional
        ``"codira-mcp"`` requires a Codira MCP event; ``"baseline"`` rejects
        all MCP events to prevent alternate retrieval access.

    Returns
    -------
    CheckResult
        Passing result only for a completed run with the expected MCP exposure,
        tool evidence, and complete non-negative usage fields.
    """

    if assistance_mode not in ASSISTANCE_MODES:
        modes = ", ".join(ASSISTANCE_MODES)
        return CheckResult(
            "jsonl-evidence", False, f"assistance mode must be one of: {modes}"
        )
    types = [event.get("type") for event in events]
    required_events = ("thread.started", "turn.started", "turn.completed")
    missing = [name for name in required_events if name not in types]
    if missing:
        return CheckResult(
            "jsonl-evidence", False, f"missing events: {', '.join(missing)}"
        )
    item_types = [
        item.get("type")
        for event in events
        if event.get("type") == "item.completed"
        for item in [event.get("item")]
        if isinstance(item, Mapping)
    ]
    has_mcp_event = any(
        isinstance(item_type, str) and "mcp" in item_type for item_type in item_types
    )
    if assistance_mode == "codira-mcp" and not has_mcp_event:
        return CheckResult("jsonl-evidence", False, "MCP tool event is absent")
    if assistance_mode == "baseline" and has_mcp_event:
        return CheckResult(
            "jsonl-evidence", False, "baseline JSONL contains an MCP tool event"
        )
    file_changes = [
        item
        for event in events
        if event.get("type") == "item.completed"
        for item in [event.get("item")]
        if isinstance(item, Mapping) and item.get("type") == "file_change"
    ]
    has_artifact = any(
        item.get("status") == "completed"
        and isinstance(item.get("changes"), list)
        and bool(item["changes"])
        for item in file_changes
    )
    if (
        not any(item_type == "command_execution" for item_type in item_types)
        and not has_artifact
    ):
        return CheckResult(
            "jsonl-evidence", False, "tool-output capture event is absent"
        )
    completed = next(
        event for event in reversed(events) if event.get("type") == "turn.completed"
    )
    usage = completed.get("usage")
    if not isinstance(usage, Mapping):
        return CheckResult("jsonl-evidence", False, "turn completion lacks usage")
    invalid = [
        field
        for field in REQUIRED_USAGE_FIELDS
        if not isinstance(usage.get(field), int)
        or isinstance(usage.get(field), bool)
        or usage.get(field, 0) < 0
    ]
    if invalid:
        return CheckResult(
            "jsonl-evidence",
            False,
            f"missing or invalid usage fields: {', '.join(invalid)}",
        )
    return CheckResult(
        "jsonl-evidence",
        True,
        "JSONL has expected MCP exposure, tool output, and complete usage evidence",
    )


def observed_total_token_check(
    events: Sequence[Mapping[str, object]], ceiling: int
) -> CheckResult:
    """Reject a completed run whose provider-reported token total exceeds a cap.

    Parameters
    ----------
    events : collections.abc.Sequence[collections.abc.Mapping[str, object]]
        Parsed Codex JSONL events containing one completed turn.
    ceiling : int
        Maximum admitted total of input, output, and reasoning-output tokens.

    Returns
    -------
    CheckResult
        Passing result only when complete usage is present and the observed
        total is within the approved ceiling.

    Notes
    -----
    Cached input tokens are a subset of input tokens and are therefore not
    added separately.
    """

    if ceiling < 1:
        return CheckResult("observed-total-tokens", False, "ceiling must be positive")
    completed = next(
        (event for event in reversed(events) if event.get("type") == "turn.completed"),
        None,
    )
    if not isinstance(completed, Mapping):
        return CheckResult("observed-total-tokens", False, "turn completion is absent")
    usage = completed.get("usage")
    if not isinstance(usage, Mapping):
        return CheckResult(
            "observed-total-tokens", False, "turn completion lacks usage"
        )
    input_tokens = usage.get("input_tokens")
    output_tokens = usage.get("output_tokens")
    reasoning_output_tokens = usage.get("reasoning_output_tokens")
    values = (input_tokens, output_tokens, reasoning_output_tokens)
    if any(
        not isinstance(value, int) or isinstance(value, bool) or value < 0
        for value in values
    ):
        return CheckResult("observed-total-tokens", False, "usage fields are invalid")
    assert isinstance(input_tokens, int)
    assert isinstance(output_tokens, int)
    assert isinstance(reasoning_output_tokens, int)
    total = input_tokens + output_tokens + reasoning_output_tokens
    if total > ceiling:
        return CheckResult(
            "observed-total-tokens",
            False,
            f"observed total {total} exceeds ceiling {ceiling}",
        )
    return CheckResult(
        "observed-total-tokens",
        True,
        f"observed total {total} is within ceiling {ceiling}",
    )


def cancellation_check(
    returncode: int,
    elapsed_seconds: float,
    limit_seconds: float,
    signal_sent: bool = False,
) -> CheckResult:
    """Validate evidence that a deliberately interrupted probe stopped promptly.

    Parameters
    ----------
    returncode : int
        Process exit status after the runner sends its termination signal.
    elapsed_seconds : float
        Measured elapsed duration from the cancellation request to process exit.
    limit_seconds : float
        Predeclared maximum acceptable cancellation duration.
    signal_sent : bool, optional
        Whether the runner recorded delivery of the cancellation signal.

    Returns
    -------
    CheckResult
        Passing result only when the process exits through a cancellation status
        within the predeclared limit.
    """

    if limit_seconds <= 0 or elapsed_seconds < 0:
        return CheckResult(
            "cancellation", False, "cancellation durations must be non-negative"
        )
    cancellation_codes = {-signal.SIGINT, -signal.SIGTERM, 130, 143}
    if signal_sent:
        cancellation_codes.update({0, 1})
    if returncode not in cancellation_codes:
        return CheckResult(
            "cancellation", False, "process did not exit through cancellation"
        )
    if elapsed_seconds > limit_seconds:
        return CheckResult("cancellation", False, "cancellation exceeded time limit")
    return CheckResult("cancellation", True, "cancellation completed within limit")


def cancellation_event_check(events: Sequence[Mapping[str, object]]) -> CheckResult:
    """Validate that an interrupted turn started but reached no terminal event.

    Parameters
    ----------
    events : collections.abc.Sequence[collections.abc.Mapping[str, object]]
        Parsed JSONL events captured before the runner cancellation signal.

    Returns
    -------
    CheckResult
        Passing result only for a started turn without completed or failed
        terminal evidence.
    """

    types = {event.get("type") for event in events}
    if "turn.started" not in types:
        return CheckResult("cancellation-events", False, "turn did not start")
    terminal = {"turn.completed", "turn.failed"} & types
    if terminal:
        names = ", ".join(sorted(str(name) for name in terminal))
        return CheckResult("cancellation-events", False, f"terminal events: {names}")
    return CheckResult(
        "cancellation-events", True, "started turn has no terminal event after signal"
    )


def escape_probe_check(outcomes: Mapping[str, bool]) -> CheckResult:
    """Require every mandatory contamination and escape probe to be blocked.

    Parameters
    ----------
    outcomes : collections.abc.Mapping[str, bool]
        Probe identifiers mapped to whether their attempted escape was blocked.

    Returns
    -------
    CheckResult
        Passing result only when all mandatory probes are present and blocked.
    """

    missing = [probe for probe in REQUIRED_ESCAPE_PROBES if probe not in outcomes]
    failed = [probe for probe in REQUIRED_ESCAPE_PROBES if outcomes.get(probe) is False]
    if missing or failed:
        details: list[str] = []
        if missing:
            details.append(f"missing probes: {', '.join(missing)}")
        if failed:
            details.append(f"unblocked probes: {', '.join(failed)}")
        return CheckResult("escape-probes", False, "; ".join(details))
    return CheckResult(
        "escape-probes", True, "all required contamination and escape probes blocked"
    )


def build_conformance_report(
    *,
    request: HostConformanceRequest,
    runner: RunCommand = run_command,
) -> ConformanceReport:
    """Inspect all non-billed Phase 0 host and isolation prerequisites.

    Parameters
    ----------
    request : HostConformanceRequest
        Immutable host resources and paths to inspect.
    runner : collections.abc.Callable, optional
        Collaborator used for executable and image inspection.

    Returns
    -------
    ConformanceReport
        Complete non-billed prerequisite report.
    """

    return ConformanceReport(
        (
            executable_check(request.codex, runner),
            codex_help_check(request.codex, runner),
            executable_check(request.runtime, runner),
            container_image_check(request.runtime, request.image, runner),
            empty_isolated_state_check(request.state_root, request.repository_root),
            isolated_config_check(),
        )
    )
