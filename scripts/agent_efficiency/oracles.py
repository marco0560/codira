"""Evaluate deterministic benchmark oracles outside an agent environment.

The module accepts only declarative JSON-compatible specifications.  Patch
checks operate on a pristine temporary copy and custom evaluators are explicit
grader-side registrations, never model-visible or shell-evaluated input.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import tempfile
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import cast

from scripts.agent_efficiency.contracts import ContractError, canonical_fingerprint

type OracleDefinition = Mapping[str, object]
type CustomEvaluator = Callable[[Mapping[str, object], Path], bool]
_PRIMITIVES = frozenset(
    {
        "contains_symbols",
        "contains_paths",
        "command_passes",
        "patch_applies_and_tests_pass",
        "normalized_artifact",
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
        Stable diagnostics without protected fixture content.
    fingerprint : str
        Canonical fingerprint of the oracle definition.

    """

    passed: bool
    checks: tuple[str, ...]
    fingerprint: str


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


def _run_protected(command: object, root: Path) -> bool:
    """Run a validated argument-vector command in the protected fixture.

    Parameters
    ----------
    command : object
        Non-shell command argument array.
    root : pathlib.Path
        Protected working directory.

    Returns
    -------
    bool
        ``True`` only for zero exit status.

    Raises
    ------
    ContractError
        If the command is not a safe argument vector.
    """

    return (
        subprocess.run(
            _protected_command(command), cwd=root, check=False, capture_output=True
        ).returncode
        == 0
    )


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


def _validate_patch_paths(patch: Path) -> None:
    """Validate all file targets declared by an untrusted unified diff.

    Parameters
    ----------
    patch : pathlib.Path
        Agent-controlled patch file already confined to the result root.

    Returns
    -------
    None
        The patch is safe for ``git apply`` target resolution.

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
        elif line.startswith(("rename from ", "rename to ", "copy from ", "copy to ")):
            _validate_fixture_relative_patch_path(line.split(" ", maxsplit=2)[2])


def _patch_check(
    spec: Mapping[str, object], result_root: Path, protected_root: Path
) -> bool:
    """Apply an agent patch to a pristine copy and run protected tests.

    Parameters
    ----------
    spec : Mapping[str, object]
        Patch primitive configuration.
    result_root : pathlib.Path
        Agent result root containing the candidate patch.
    protected_root : pathlib.Path
        Pristine fixture source and protected tests.

    Returns
    -------
    bool
        ``True`` only when apply and protected tests both pass.
    """

    patch = result_root / _safe_path(spec.get("patch_path"), label="patch_path")
    if result_root not in patch.resolve().parents:
        detail = "patch_path escapes agent result root"
        raise ContractError.message(detail)
    if not patch.is_file():
        return False
    tests = _protected_command(spec.get("command"))
    _validate_patch_paths(patch)
    with tempfile.TemporaryDirectory(prefix="codira-agent-oracle-") as temporary:
        destination = Path(temporary) / "fixture"
        shutil.copytree(protected_root, destination, symlinks=False)
        if not _run_protected(["git", "apply", "--check", str(patch)], destination):
            return False
        if not _run_protected(["git", "apply", str(patch)], destination):
            return False
        return _run_protected(tests, destination)


def _evaluate(
    definition: OracleDefinition,
    result: Mapping[str, object],
    result_root: Path,
    protected_root: Path,
    evaluators: Mapping[str, ProtectedEvaluator],
) -> tuple[bool, str]:
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

    Returns
    -------
    tuple[bool, str]
        Decision and stable primitive label.

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
    if name == "contains_symbols":
        return _is_subset(payload, result.get("symbols", [])), name
    if name == "contains_paths":
        return _is_subset(payload, result.get("paths", [])), name
    if name == "normalized_artifact":
        return _is_subset(normalize(payload), normalize(result)), name
    if name == "command_passes":
        return _run_protected(payload, protected_root), name
    if name == "patch_applies_and_tests_pass":
        if not isinstance(payload, Mapping):
            detail = "patch primitive must be an object"
            raise ContractError.message(detail)
        return _patch_check(
            cast("Mapping[str, object]", payload), result_root, protected_root
        ), name
    if name in {"all_of", "any_of"}:
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
            )[0]
            for item in payload
        ]
        return (all(children) if name == "all_of" else any(children)), name
    return _custom_evaluator(payload, result, protected_root, evaluators), name


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


def evaluate_oracle(
    definition: OracleDefinition,
    *,
    result_root: Path,
    result_path: str = ".benchmark/result.json",
    protected_root: Path,
    evaluators: Mapping[str, ProtectedEvaluator] | None = None,
) -> OracleResult:
    """Evaluate a declarative oracle against one isolated agent result.

    Parameters
    ----------
    definition : OracleDefinition
        Declarative single-root DSL definition.
    result_root : pathlib.Path
        Agent-visible fixture result tree.
    result_path : str, optional
        Safe relative JSON result-artifact path.
    protected_root : pathlib.Path
        Pristine grader-only fixture tree.
    evaluators : Mapping[str, ProtectedEvaluator] | None, optional
        Registered deterministic evaluator functions and reviewed script bindings.

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
    passed, label = _evaluate(
        definition,
        _result_object(artifact),
        root,
        protected_root.resolve(),
        evaluators or {},
    )
    return OracleResult(
        passed=passed, checks=(label,), fingerprint=canonical_fingerprint(definition)
    )
