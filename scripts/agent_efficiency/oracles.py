"""Evaluate deterministic benchmark oracles outside an agent environment.

The module accepts only declarative JSON-compatible specifications.  Patch
checks operate on a pristine temporary copy and custom evaluators are explicit
grader-side registrations, never model-visible or shell-evaluated input.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import tempfile
from collections.abc import Callable, Mapping, Sequence
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import cast

from scripts.agent_efficiency.contracts import ContractError, canonical_fingerprint

type CommandExecutor = Callable[
    [Sequence[str], Path], subprocess.CompletedProcess[bytes]
]
_COMMAND_EXECUTOR: ContextVar[CommandExecutor | None] = ContextVar(
    "oracle_command_executor", default=None
)

type OracleDefinition = Mapping[str, object]
type CustomEvaluator = Callable[[Mapping[str, object], Path], bool]
_PRIMITIVES = frozenset(
    {
        "contains_symbols",
        "contains_paths",
        "command_passes",
        "patch_applies_and_tests_pass",
        "normalized_artifact",
        "text_contains",
        "quality_rubric",
        "all_of",
        "any_of",
        "custom_evaluator",
    }
)


@dataclass(frozen=True)
class OracleResult:
    """Record one deterministic oracle decision.

    Parameters
    ----------
    passed : bool
        Whether every required condition held.
    checks : tuple[str, ...]
        Stable, content-safe diagnostics for each evaluated oracle component.
    fingerprint : str
        Canonical fingerprint of the oracle definition.
    trace_manifest_sha256 : str or None
        Digest of the private protected-command trace manifest, when enabled.
    trace_command_count : int
        Number of protected commands captured in the private trace.

    """

    passed: bool
    checks: tuple[str, ...]
    fingerprint: str
    trace_manifest_sha256: str | None = None
    trace_command_count: int = 0


@dataclass(frozen=True)
class ProtectedCommandResult:
    """Summarize a protected command while optionally retaining its output.

    Parameters
    ----------
    returncode : int or None
        Process status, or ``None`` when the command could not be started.
    stdout_sha256, stderr_sha256 : str
        Digests of captured output bytes.
    stdout_size_bytes, stderr_size_bytes : int
        Captured output sizes.
    exception_class : str or None
        Exception class parsed from a traceback, without its message.
    failure_location : str or None
        Basename and line number parsed from the final traceback frame.

    Returns
    -------
    None
        Instances contain public-safe command metadata; raw output is retained
        separately in the private attempt trace when enabled.
    """

    returncode: int | None
    stdout_sha256: str
    stderr_sha256: str
    stdout_size_bytes: int
    stderr_size_bytes: int
    exception_class: str | None = None
    failure_location: str | None = None

    @property
    def passed(self) -> bool:
        """Return whether the protected command exited successfully.

        Parameters
        ----------
        None

        Returns
        -------
        bool
            ``True`` only for exit status zero.
        """

        return self.returncode == 0


class _ProtectedTrace:
    """Persist private stdout and stderr for each protected command.

    Parameters
    ----------
    root : pathlib.Path
        New private artifact directory for one attempt.

    """

    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, mode=0o700, exist_ok=False)
        self.root.chmod(0o700)
        self.commands: list[dict[str, object]] = []
        self.status = "in_progress"
        self._write_manifest()

    def record(  # noqa: PLR0913
        self,
        stage: str,
        command: Sequence[str],
        stdout: bytes,
        stderr: bytes,
        returncode: int | None,
        exception_class: str | None,
        exception_message: str | None,
    ) -> None:
        """Write one protected process result and update the manifest.

        Parameters
        ----------
        stage : str
            Oracle DSL path and protected command stage.
        command : collections.abc.Sequence[str]
            Exact argument vector passed to the process runner.
        stdout : bytes
            Complete captured standard output stream.
        stderr : bytes
            Complete captured standard error stream.
        returncode : int or None
            Process status, or ``None`` if process startup failed.
        exception_class : str or None
            Startup exception class, if any.
        exception_message : str or None
            Private startup exception message, if any.

        Returns
        -------
        None
            Artifacts and the updated manifest are durable on return.
        """

        index = len(self.commands) + 1
        outputs: dict[str, object] = {}
        for stream, content in (("stdout", stdout), ("stderr", stderr)):
            filename = f"command-{index:03d}.{stream}.bin"
            path = self.root / filename
            with path.open("xb") as artifact:
                artifact.write(content)
            path.chmod(0o600)
            outputs[stream] = {
                "path": filename,
                "sha256": hashlib.sha256(content).hexdigest(),
                "size_bytes": len(content),
            }
        self.commands.append(
            {
                "stage": stage,
                "argv": list(command),
                "returncode": returncode,
                "exception_class": exception_class,
                "exception_message": exception_message,
                "outputs": outputs,
            }
        )
        self._write_manifest()

    def finalize(self, status: str) -> tuple[str, int]:
        """Mark the oracle trace terminal and return its digest and count.

        Parameters
        ----------
        status : str
            ``complete`` after evaluation or ``error`` when evaluation raises.

        Returns
        -------
        tuple[str, int]
            Manifest SHA-256 and number of captured protected commands.
        """

        self.status = status
        self._write_manifest()
        digest = hashlib.sha256((self.root / "manifest.json").read_bytes()).hexdigest()
        return digest, len(self.commands)

    def _write_manifest(self) -> None:
        payload = {
            "schema_version": 1,
            "status": self.status,
            "commands": self.commands,
        }
        target = self.root / "manifest.json"
        temporary = self.root / "manifest.json.tmp"
        temporary.write_text(
            json.dumps(payload, sort_keys=True, indent=2) + "\n", encoding="utf-8"
        )
        temporary.chmod(0o600)
        temporary.replace(target)


@dataclass(frozen=True)
class ProtectedEvaluator:
    """Bind one grader callable to its reviewed protected script identity.

    Parameters
    ----------
    evaluator : CustomEvaluator
        Deterministic callable retained only by the protected grader.
    script_path : str
        POSIX-relative path of the reviewed protected evaluator script.
    script_sha256 : str
        SHA-256 of the reviewed protected evaluator script.

    """

    evaluator: CustomEvaluator
    script_path: str
    script_sha256: str


def _safe_path(raw: object, *, label: str) -> PurePosixPath:
    """Validate a grader-relative path.

    Parameters
    ----------
    raw : object
        Candidate POSIX path.
    label : str
        Field name for deterministic errors.

    Returns
    -------
    pathlib.PurePosixPath
        Safe relative path.

    Raises
    ------
    ContractError
        If the path is absolute, empty, or escapes its root.
    """

    if not isinstance(raw, str) or not raw or "\\" in raw:
        detail = f"{label} must be a non-empty POSIX-relative path"
        raise ContractError.message(detail)
    path = PurePosixPath(raw)
    if path.is_absolute() or ".." in path.parts or "." in path.parts:
        detail = f"{label} escapes its protected root"
        raise ContractError.message(detail)
    return path


def normalize(value: object) -> object:
    """Normalize JSON values for deterministic subset comparison.

    Parameters
    ----------
    value : object
        JSON-compatible result value.

    Returns
    -------
    object
        Whitespace-normalized recursively ordered representation.
    """

    if isinstance(value, str):
        return " ".join(value.split())
    if isinstance(value, Mapping):
        return {str(key): normalize(item) for key, item in sorted(value.items())}
    if isinstance(value, list):
        return [normalize(item) for item in value]
    return value


def _is_subset(expected: object, actual: object) -> bool:
    """Return whether a normalized expected value occurs in an actual value.

    Parameters
    ----------
    expected : object
        Required normalized structure.
    actual : object
        Candidate normalized structure.

    Returns
    -------
    bool
        ``True`` when every expected mapping/list leaf is present.
    """

    if isinstance(expected, Mapping):
        return isinstance(actual, Mapping) and all(
            key in actual and _is_subset(value, actual[key])
            for key, value in expected.items()
        )
    if isinstance(expected, list):
        return isinstance(actual, list) and all(
            any(_is_subset(item, candidate) for candidate in actual)
            for item in expected
        )
    return expected == actual


def _result_object(result_path: Path) -> Mapping[str, object]:
    """Load one agent result artifact without accepting malformed JSON.

    Parameters
    ----------
    result_path : pathlib.Path
        Result file copied from the agent fixture.

    Returns
    -------
    Mapping[str, object]
        Parsed result object.

    Raises
    ------
    ContractError
        If the artifact is missing, malformed, or not an object.
    """

    try:
        parsed = json.loads(result_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        detail = f"result artifact is missing or malformed: {error}"
        raise ContractError.message(detail) from error
    if not isinstance(parsed, Mapping):
        detail = "result artifact must be a JSON object"
        raise ContractError.message(detail)
    return cast("Mapping[str, object]", parsed)


def _result_artifact(result_path: Path, result_format: str) -> object:
    """Load one declared natural task artifact for deterministic grading.

    Parameters
    ----------
    result_path : pathlib.Path
        Safe agent-visible artifact path.
    result_format : str
        Declared task-artifact representation.

    Returns
    -------
    object
        A JSON object or UTF-8 text, including the runner-captured patch.

    Raises
    ------
    ContractError
        If the declared artifact is unavailable or malformed.
    """

    if result_format == "json":
        return _result_object(result_path)
    if result_format == "text":
        try:
            return result_path.read_text(encoding="utf-8")
        except OSError as error:
            detail = f"text artifact is missing or unreadable: {error}"
            raise ContractError.message(detail) from error
    if result_format == "workspace-diff":
        if not result_path.is_file():
            detail = "runner-captured patch is missing"
            raise ContractError.message(detail)
        return result_path.read_text(encoding="utf-8")
    detail = "task result format is unsupported"
    raise ContractError.message(detail)


def _protected_command(command: object) -> Sequence[str]:
    """Validate one non-shell protected command argument vector.

    Parameters
    ----------
    command : object
        Non-empty command argument array.

    Returns
    -------
    collections.abc.Sequence[str]
        Validated argument vector.

    Raises
    ------
    ContractError
        If the command is not a safe argument vector.
    """

    if (
        not isinstance(command, list)
        or not command
        or not all(isinstance(part, str) and part for part in command)
    ):
        detail = "protected command must be a non-empty argument array"
        raise ContractError.message(detail)
    shell_names = {"sh", "bash", "zsh", "dash", "ksh", "fish"}
    if (
        Path(command[0]).name in shell_names
        or "-c" in command
        or "--command" in command
    ):
        detail = "protected command cannot invoke a shell"
        raise ContractError.message(detail)
    return cast("Sequence[str]", command)


def _run_protected(
    command: object,
    root: Path,
    *,
    trace: _ProtectedTrace | None = None,
    stage: str,
) -> ProtectedCommandResult:
    """Run a protected command and retain safe output diagnostics.

    Parameters
    ----------
    command : object
        Non-shell command argument array.
    root : pathlib.Path
        Protected working directory.
    trace : _ProtectedTrace or None, optional
        Private trace collector for this attempt.
    stage : str
        Stable oracle stage label used in the private manifest.

    Returns
    -------
    ProtectedCommandResult
        Exit status and output digests without raw command output.

    Raises
    ------
    ContractError
        If the command is not a safe argument vector.
    """

    try:
        argv = _protected_command(command)
        executor = _COMMAND_EXECUTOR.get()
        completed = (
            executor(argv, root)
            if executor is not None
            else subprocess.run(argv, cwd=root, check=False, capture_output=True)
        )
    except OSError as error:
        argv = _protected_command(command)
        if trace is not None:
            trace.record(stage, argv, b"", b"", None, type(error).__name__, str(error))
        return ProtectedCommandResult(
            returncode=None,
            stdout_sha256=hashlib.sha256(b"").hexdigest(),
            stderr_sha256=hashlib.sha256(b"").hexdigest(),
            stdout_size_bytes=0,
            stderr_size_bytes=0,
            exception_class=type(error).__name__,
        )
    stdout = completed.stdout if isinstance(completed.stdout, bytes) else b""
    stderr = completed.stderr if isinstance(completed.stderr, bytes) else b""
    if trace is not None:
        trace.record(
            stage,
            cast("Sequence[str]", completed.args),
            stdout,
            stderr,
            completed.returncode,
            None,
            None,
        )
    diagnostic_text = stderr.decode("utf-8", errors="replace")
    exception_class: str | None = None
    failure_location: str | None = None
    if "Traceback (most recent call last):" in diagnostic_text:
        lines = [line.strip() for line in diagnostic_text.splitlines() if line.strip()]
        if lines:
            match = re.match(r"([A-Za-z_][A-Za-z0-9_.]*)(?::|$)", lines[-1])
            if match is not None:
                exception_class = match.group(1)
        locations = re.findall(
            r'File "[^"/]+/([^"/]+)", line ([0-9]+)', diagnostic_text
        )
        if locations:
            filename, line_number = locations[-1]
            failure_location = f"{filename}:{line_number}"
    return ProtectedCommandResult(
        returncode=completed.returncode,
        stdout_sha256=hashlib.sha256(stdout).hexdigest(),
        stderr_sha256=hashlib.sha256(stderr).hexdigest(),
        stdout_size_bytes=len(stdout),
        stderr_size_bytes=len(stderr),
        exception_class=exception_class,
        failure_location=failure_location,
    )


def _command_checks(label: str, result: ProtectedCommandResult) -> tuple[str, ...]:
    """Convert command execution facts into content-safe check strings.

    Parameters
    ----------
    label : str
        Stable oracle-stage identifier.
    result : ProtectedCommandResult
        Captured protected command metadata.

    Returns
    -------
    tuple[str, ...]
        Stable status and digest checks suitable for immutable attempt records.
    """

    checks = [
        f"{label}:{'passed' if result.passed else 'failed'}",
        f"{label}.exit_code:{result.returncode}",
        f"{label}.stdout_sha256:{result.stdout_sha256}",
        f"{label}.stdout_size_bytes:{result.stdout_size_bytes}",
        f"{label}.stderr_sha256:{result.stderr_sha256}",
        f"{label}.stderr_size_bytes:{result.stderr_size_bytes}",
    ]
    if result.exception_class is not None:
        checks.append(f"{label}.exception_class:{result.exception_class}")
    if result.failure_location is not None:
        checks.append(f"{label}.failure_location:{result.failure_location}")
    return tuple(checks)


def _validate_fixture_relative_patch_path(raw: str) -> None:
    """Reject one unprefixed patch target outside the pristine fixture copy.

    Parameters
    ----------
    raw : str
        Relative patch target, as used by rename and copy directives.

    Returns
    -------
    None
        Valid paths need no transformation.

    Raises
    ------
    ContractError
        If the path is malformed or can escape the fixture root.
    """

    path = PurePosixPath(raw)
    if not path.parts or path.is_absolute() or "." in path.parts or ".." in path.parts:
        detail = "patch header path escapes protected fixture"
        raise ContractError.message(detail)


def _validate_patch_path(raw: str) -> None:
    """Reject one standard patch header path outside the fixture copy.

    Parameters
    ----------
    raw : str
        Header path in standard ``a/`` or ``b/`` form.

    Returns
    -------
    None
        Valid paths need no transformation.

    Raises
    ------
    ContractError
        If the path is malformed or can escape the fixture root.
    """

    if raw == "/dev/null":
        return
    if not raw.startswith(("a/", "b/")):
        detail = "patch header path must use an a/ or b/ prefix"
        raise ContractError.message(detail)
    _validate_fixture_relative_patch_path(raw[2:])


def _validate_patch_paths(patch: Path) -> tuple[str, ...]:
    """Validate all file targets declared by an untrusted unified diff.

    Parameters
    ----------
    patch : pathlib.Path
        Agent-controlled patch file already confined to the result root.

    Returns
    -------
    tuple[str, ...]
        Sorted unique fixture-relative paths changed by the patch.

    Raises
    ------
    ContractError
        If a patch header is malformed or names a path outside the fixture.
    """

    try:
        lines = patch.read_text(encoding="utf-8").splitlines()
    except OSError as error:
        detail = f"patch cannot be read: {error}"
        raise ContractError.message(detail) from error
    changed_paths: set[str] = set()
    for line in lines:
        if line.startswith(("--- ", "+++ ")):
            _validate_patch_path(line[4:].split("\t", maxsplit=1)[0])
        elif line.startswith("diff --git "):
            targets = line.removeprefix("diff --git ").split()
            if len(targets) != 2:
                detail = "patch diff header must contain exactly two paths"
                raise ContractError.message(detail)
            for target in targets:
                _validate_patch_path(target)
                if target != "/dev/null":
                    changed_paths.add(target[2:])
        elif line.startswith(("rename from ", "rename to ", "copy from ", "copy to ")):
            _validate_fixture_relative_patch_path(line.split(" ", maxsplit=2)[2])
    return tuple(sorted(changed_paths))


def _patch_check(
    spec: Mapping[str, object],
    result_root: Path,
    protected_root: Path,
    *,
    trace: _ProtectedTrace | None,
    stage_prefix: str,
) -> tuple[bool, tuple[str, ...]]:
    """Apply an agent patch to a pristine copy and run protected tests.

    Parameters
    ----------
    spec : Mapping[str, object]
        Patch primitive configuration.
    result_root : pathlib.Path
        Agent result root containing the candidate patch.
    protected_root : pathlib.Path
        Pristine fixture source and protected tests.
    trace : _ProtectedTrace or None
        Private protected-command trace collector.
    stage_prefix : str
        Composite DSL path prefix for this patch primitive.

    Returns
    -------
    tuple[bool, tuple[str, ...]]
        Combined decision and the result of each patch validation stage.
    """

    patch = result_root / _safe_path(spec.get("patch_path"), label="patch_path")
    if result_root not in patch.resolve().parents:
        detail = "patch_path escapes agent result root"
        raise ContractError.message(detail)
    if not patch.is_file():
        return False, ("patch.file:missing",)
    checks = ["patch.file:present"]
    tests = _protected_command(spec.get("command"))
    changed_paths = _validate_patch_paths(patch)
    checks.append("patch.path_validation:passed")
    required_changed_paths = spec.get("required_changed_paths", [])
    if not isinstance(required_changed_paths, list) or not all(
        isinstance(path, str) and path for path in required_changed_paths
    ):
        detail = "required_changed_paths must be a list of non-empty paths"
        raise ContractError.message(detail)
    allowed_changed_paths = spec.get("allowed_changed_paths")
    allowed_paths: set[str] | None = None
    if allowed_changed_paths is not None:
        if (
            not isinstance(allowed_changed_paths, list)
            or not allowed_changed_paths
            or not all(isinstance(path, str) and path for path in allowed_changed_paths)
            or len(set(allowed_changed_paths)) != len(allowed_changed_paths)
        ):
            detail = "allowed_changed_paths must be a unique list of non-empty paths"
            raise ContractError.message(detail)
        allowed_paths = {
            _safe_path(path, label="allowed_changed_paths").as_posix()
            for path in allowed_changed_paths
        }
        required_paths = {
            _safe_path(path, label="required_changed_paths").as_posix()
            for path in required_changed_paths
        }
        if not required_paths <= allowed_paths:
            detail = "required_changed_paths must be included in allowed_changed_paths"
            raise ContractError.message(detail)
        if set(changed_paths) - allowed_paths:
            checks.append("patch.allowed_changed_paths:unexpected")
            return False, tuple(checks)
        checks.append("patch.allowed_changed_paths:passed")
    patch_text = patch.read_text(encoding="utf-8")
    required_paths_passed = True
    for index, raw_path in enumerate(required_changed_paths):
        changed_path = _safe_path(raw_path, label="required_changed_paths")
        header = f"diff --git a/{changed_path} b/{changed_path}"
        present = header in patch_text
        required_paths_passed = required_paths_passed and present
        checks.append(
            f"patch.required_changed_path[{index}]:{'present' if present else 'missing'}"
        )
    if not required_paths_passed:
        return False, tuple(checks)
    with tempfile.TemporaryDirectory(
        prefix="codira-agent-oracle-", dir="/home/marco/Personalia/Progetti/.Temp"
    ) as temporary:
        destination = Path(temporary) / "fixture"
        shutil.copytree(protected_root, destination, symlinks=False)
        apply_check = _run_protected(
            ["git", "apply", "--check", str(patch)],
            destination,
            trace=trace,
            stage=f"{stage_prefix}patch.apply_check",
        )
        checks.extend(_command_checks("patch.apply_check", apply_check))
        if not apply_check.passed:
            return False, tuple(checks)
        applied = _run_protected(
            ["git", "apply", str(patch)],
            destination,
            trace=trace,
            stage=f"{stage_prefix}patch.apply",
        )
        checks.extend(_command_checks("patch.apply", applied))
        if not applied.passed:
            return False, tuple(checks)
        protected_result = _run_protected(
            tests,
            destination,
            trace=trace,
            stage=f"{stage_prefix}patch.protected_command",
        )
        checks.extend(_command_checks("patch.protected_command", protected_result))
        return protected_result.passed, tuple(checks)


def _quality_check(
    payload: object, result: object, trace: _ProtectedTrace | None
) -> tuple[bool, tuple[str, ...]]:
    """Evaluate a rubric and retain complete blinded evidence.

    Parameters
    ----------
    payload : object
        Explicit task-specific quality rubric.
    result : object
        Complete answer artifact.
    trace : _ProtectedTrace or None
        Durable private attempt trace.

    Returns
    -------
    tuple[bool, tuple[str, ...]]
        Quality decision and stable per-criterion statuses.
    """
    from scripts.agent_efficiency.quality import grade_quality, write_blinded_packet

    if not isinstance(payload, Mapping) or not isinstance(result, str):
        detail = "quality_rubric requires a rubric object and text artifact"
        raise ContractError.message(detail)
    report = grade_quality(result, payload)
    if trace is not None:
        path = trace.root / f"quality-{canonical_fingerprint(payload)}.json"
        if not path.exists():
            write_blinded_packet(result, payload, path)
        grade_path = trace.root / f"quality-{canonical_fingerprint(payload)}-grade.json"
        with grade_path.open("x", encoding="utf-8") as stream:
            stream.write(json.dumps(report, sort_keys=True, indent=2))
    findings = cast("list[dict[str, object]]", report["criteria"])
    return report["status"] == "passed", tuple(
        f"quality[{item['id']}]:{item['status']}" for item in findings
    )


def _evaluate(  # noqa: PLR0913
    definition: OracleDefinition,
    result: object,
    result_root: Path,
    protected_root: Path,
    evaluators: Mapping[str, ProtectedEvaluator],
    *,
    trace: _ProtectedTrace | None,
    stage_prefix: str = "",
) -> tuple[bool, tuple[str, ...]]:
    """Evaluate one DSL node recursively.

    Parameters
    ----------
    definition : OracleDefinition
        Single-key DSL node.
    result : Mapping[str, object]
        Parsed agent result artifact.
    result_root : pathlib.Path
        Agent result root.
    protected_root : pathlib.Path
        Protected grader fixture root.
    evaluators : Mapping[str, ProtectedEvaluator]
        Explicit grader-side custom evaluator registry and script bindings.
    trace : _ProtectedTrace or None
        Private protected-command trace collector.
    stage_prefix : str
        Composite DSL path prefix for this node.

    Returns
    -------
    tuple[bool, tuple[str, ...]]
        Decision and content-safe check results for the oracle node.

    Raises
    ------
    ContractError
        If the DSL node is malformed or uses an unregistered custom evaluator.
    """

    if len(definition) != 1:
        detail = "oracle node must contain exactly one primitive"
        raise ContractError.message(detail)
    name, payload = next(iter(definition.items()))
    if name not in _PRIMITIVES:
        detail = f"unsupported oracle primitive: {name}"
        raise ContractError.message(detail)
    if name in {"all_of", "any_of"}:
        return _evaluate_composite(
            definition,
            result,
            result_root,
            protected_root,
            evaluators,
            trace=trace,
            stage_prefix=stage_prefix,
        )
    if name == "contains_symbols":
        passed = _is_subset(
            payload, result.get("symbols", []) if isinstance(result, Mapping) else []
        )
        return passed, (f"contains_symbols:{'passed' if passed else 'failed'}",)
    if name == "contains_paths":
        passed = _is_subset(
            payload, result.get("paths", []) if isinstance(result, Mapping) else []
        )
        return passed, (f"contains_paths:{'passed' if passed else 'failed'}",)
    if name == "normalized_artifact":
        passed = _is_subset(normalize(payload), normalize(result))
        return passed, (f"normalized_artifact:{'passed' if passed else 'failed'}",)
    if name == "text_contains":
        if not isinstance(payload, list) or not all(
            isinstance(item, str) and item for item in payload
        ):
            detail = "text_contains requires non-empty strings"
            raise ContractError.message(detail)
        if not isinstance(result, str):
            return False, ("text_contains:artifact_not_text",)
        checks = tuple(
            f"text_contains[{index}]:{'passed' if item in result else 'missing'}"
            for index, item in enumerate(payload)
        )
        return all(item in result for item in payload), checks
    if name == "quality_rubric":
        return _quality_check(payload, result, trace)
    if name == "command_passes":
        result = _run_protected(
            payload,
            protected_root,
            trace=trace,
            stage=f"{stage_prefix}command_passes",
        )
        return result.passed, _command_checks("command_passes", result)
    if name == "patch_applies_and_tests_pass":
        if not isinstance(payload, Mapping):
            detail = "patch primitive must be an object"
            raise ContractError.message(detail)
        return _patch_check(
            cast("Mapping[str, object]", payload),
            result_root,
            protected_root,
            trace=trace,
            stage_prefix=stage_prefix,
        )
    if not isinstance(result, Mapping):
        detail = "custom evaluator requires a JSON object artifact"
        raise ContractError.message(detail)
    passed = _custom_evaluator(payload, result, protected_root, evaluators)
    return passed, (f"custom_evaluator:{'passed' if passed else 'failed'}",)


def _evaluate_composite(  # noqa: PLR0913
    definition: OracleDefinition,
    result: object,
    result_root: Path,
    protected_root: Path,
    evaluators: Mapping[str, ProtectedEvaluator],
    *,
    trace: _ProtectedTrace | None,
    stage_prefix: str,
) -> tuple[bool, tuple[str, ...]]:
    """Evaluate and trace one recursive ``all_of`` or ``any_of`` node.

    Parameters
    ----------
    name : str
        Composite operator name.
    payload : object
        Candidate child definitions.
    result : object
        Parsed task result passed to each child.
    result_root : pathlib.Path
        Agent artifact root.
    protected_root : pathlib.Path
        Protected grader fixture root.
    evaluators : collections.abc.Mapping[str, ProtectedEvaluator]
        Explicit custom evaluator registry.
    trace : _ProtectedTrace or None
        Private protected-command trace collector.
    stage_prefix : str
        Parent composite path prefix.

    Returns
    -------
    tuple[bool, tuple[str, ...]]
        Composite decision and path-qualified child diagnostics.

    Raises
    ------
    ContractError
        If children are absent or malformed.
    """

    name, payload = next(iter(definition.items()))
    if not isinstance(payload, list) or not payload:
        detail = f"{name} requires a non-empty list"
        raise ContractError.message(detail)
    if not all(isinstance(item, Mapping) for item in payload):
        detail = f"{name} children must be objects"
        raise ContractError.message(detail)
    children = [
        _evaluate(
            cast("OracleDefinition", item),
            result,
            result_root,
            protected_root,
            evaluators,
            trace=trace,
            stage_prefix=f"{stage_prefix}{name}[{index}].",
        )
        for index, item in enumerate(payload)
    ]
    child_checks = tuple(
        f"{name}[{index}].{check}"
        for index, (_, checks) in enumerate(children)
        for check in checks
    )
    passed = (
        all(child_passed for child_passed, _ in children)
        if name == "all_of"
        else any(child_passed for child_passed, _ in children)
    )
    return passed, (f"{name}:{'passed' if passed else 'failed'}", *child_checks)


def _custom_evaluator(
    payload: object,
    result: Mapping[str, object],
    protected_root: Path,
    evaluators: Mapping[str, ProtectedEvaluator],
) -> bool:
    """Run a registered evaluator after verifying its protected script identity.

    Parameters
    ----------
    payload : object
        Custom-evaluator specification.
    result : Mapping[str, object]
        Agent result artifact.
    protected_root : pathlib.Path
        Grader-only root holding the versioned evaluator script.
    evaluators : Mapping[str, ProtectedEvaluator]
        Protected callable registry with reviewed script bindings.

    Returns
    -------
    bool
        Registered evaluator decision.

    Raises
    ------
    ContractError
        If isolation declarations, script identity, or registration are invalid.
    """

    if not isinstance(payload, Mapping):
        detail = "custom evaluator primitive must be an object"
        raise ContractError.message(detail)
    evaluator_id = payload.get("evaluator_id")
    rationale = payload.get("rationale")
    script_path = payload.get("script_path")
    script_sha256 = payload.get("script_sha256")
    if payload.get("no_llm") is not True:
        detail = "custom evaluator must prohibit LLM use"
        raise ContractError.message(detail)
    if payload.get("variant_identity_access") is not False:
        detail = "custom evaluator must prohibit variant identity access"
        raise ContractError.message(detail)
    if (
        not isinstance(rationale, str)
        or not rationale.strip()
        or not isinstance(script_sha256, str)
        or len(script_sha256) != 64
    ):
        detail = (
            "custom evaluator must declare isolation, rationale, and script SHA-256"
        )
        raise ContractError.message(detail)
    script = protected_root / _safe_path(script_path, label="script_path")
    if (
        not script.is_file()
        or hashlib.sha256(script.read_bytes()).hexdigest() != script_sha256
    ):
        detail = "custom evaluator script identity does not match its protected SHA-256"
        raise ContractError.message(detail)
    if not isinstance(evaluator_id, str) or evaluator_id not in evaluators:
        detail = "custom evaluator is not registered by the protected grader"
        raise ContractError.message(detail)
    registered = evaluators[evaluator_id]
    if (
        registered.script_path != script_path
        or registered.script_sha256 != script_sha256
    ):
        detail = "custom evaluator registry binding does not match the reviewed script"
        raise ContractError.message(detail)
    return registered.evaluator(result, protected_root)


def evaluate_oracle(  # noqa: PLR0913
    definition: OracleDefinition,
    *,
    result_root: Path,
    result_path: str = ".benchmark/result.json",
    result_format: str = "json",
    protected_root: Path,
    evaluators: Mapping[str, ProtectedEvaluator] | None = None,
    trace_root: Path | None = None,
    command_executor: CommandExecutor | None = None,
) -> OracleResult:
    """Evaluate a declarative oracle against one isolated agent result.

    Parameters
    ----------
    definition : OracleDefinition
        Declarative single-root DSL definition.
    result_root : pathlib.Path
        Agent-visible fixture result tree.
    result_path : str, optional
        Safe relative task-artifact path.
    result_format : str, optional
        Declared JSON, text, or runner-captured workspace-diff representation.
    protected_root : pathlib.Path
        Pristine grader-only fixture tree.
    evaluators : Mapping[str, ProtectedEvaluator] | None, optional
        Registered deterministic evaluator functions and reviewed script bindings.
    trace_root : pathlib.Path or None, optional
        New private directory for complete protected command output artifacts.

    command_executor : CommandExecutor or None, optional
        Image-bound behavioral runner; isolated host execution for unit tests.

    Returns
    -------
    OracleResult
        Decision, diagnostic primitive, and oracle fingerprint.

    Raises
    ------
    ContractError
        If the result artifact or oracle definition violates the protected
        grading contract.
    """

    root = result_root.resolve()
    artifact = root / _safe_path(result_path, label="result_path")
    if root not in artifact.resolve().parents:
        detail = "result_path escapes agent result root"
        raise ContractError.message(detail)
    trace = _ProtectedTrace(trace_root) if trace_root is not None else None
    token = _COMMAND_EXECUTOR.set(command_executor)
    try:
        passed, checks = _evaluate(
            definition,
            _result_artifact(artifact, result_format),
            root,
            protected_root.resolve(),
            evaluators or {},
            trace=trace,
        )
    except BaseException:
        if trace is not None:
            trace.finalize("error")
        raise
    finally:
        _COMMAND_EXECUTOR.reset(token)
    trace_digest: str | None = None
    trace_count = 0
    if trace is not None:
        trace_digest, trace_count = trace.finalize("complete")
    return OracleResult(
        passed=passed,
        checks=checks,
        fingerprint=canonical_fingerprint(definition),
        trace_manifest_sha256=trace_digest,
        trace_command_count=trace_count,
    )
