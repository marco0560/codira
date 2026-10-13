#!/usr/bin/env python3
"""Execute an operator-launched local corpus benchmark with durable checkpoints.

This shared developer launcher supports analyzer-style and local stress manifests. Without
--run it validates inputs and prints the plan; it never indexes the corpus.

Parameters
----------
None

Returns
-------
None
    Command-line entry points retain measured stages only when explicitly run.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import hashlib
import importlib
import importlib.metadata
import json
import logging
import os
import platform
import re
import shutil
import signal
import subprocess
import sys
import time
import tomllib
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any, NoReturn

import tomlkit

from codira.runtime_identity import runtime_identity

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

LOGGER = logging.getLogger(__name__)

SUCCESS_STATUSES = frozenset({"passed", "empty"})
PARTIAL_STATUSES = frozenset({"partial", "partial_empty"})
QUERYABLE_STATUSES = SUCCESS_STATUSES | PARTIAL_STATUSES
READ_COMMANDS = frozenset(
    {
        "cov",
        "audit",
        "symlist",
        "sym",
        "calls",
        "refs",
        "ctx",
        "arch",
        "emb",
        "docs",
        "evidence",
    }
)


def command_failure(
    reason: str, exit_code: int, stderr: str, error: object = None
) -> dict[str, Any]:
    """Preserve the underlying diagnosis alongside command/output failures.

    Parameters
    ----------
    reason : str
        Operational or output-contract failure.
    exit_code : int
        Actual child status.
    stderr : str
        Original retained diagnostics.
    error : object, optional
        Structured CLI error detail when supplied.

    Returns
    -------
    dict
        Failed measurement with a compact diagnosis and original exit status.
    """
    lines = [line.strip() for line in stderr.splitlines() if line.strip()]
    diagnoses = [
        line
        for line in lines
        if line.startswith("[codira]") or re.match(r"\w+(?:Error|Exception):", line)
    ]
    return {
        "status": "failed",
        "reason": reason,
        "timing_valid": False,
        "exit_code": exit_code,
        "error": error,
        "stderr_diagnostic": (
            diagnoses[-1] if diagnoses else lines[-1] if lines else ""
        )[:1024],
    }


def measurement_capabilities() -> dict[str, str]:
    """Declare per-command RSS collection availability and its interpretation.

    Parameters
    ----------
    None

    Returns
    -------
    dict of str to str
        Collector, unit and scope binding measurement comparisons to controls.
    """
    collector = (
        "wait4"
        if callable(getattr(os, "wait4", None))
        and platform.system() in {"Linux", "Darwin"}
        else "gnu-time"
        if platform.system() == "Linux" and Path("/usr/bin/time").exists()
        else "unavailable"
    )
    return {
        "collector": collector,
        "unit": "KiB",
        "scope": "maximum lifetime process RSS, including pre-exec startup and waited descendants; not simultaneous process-tree RSS",
        "wall_clock": "time.perf_counter",
    }


def wait_for_resources(process: subprocess.Popen[str], timeout: float) -> int | None:
    """Wait for one exact child and collect its independent resource usage.

    Parameters
    ----------
    process : subprocess.Popen
        Owned command whose status has not been reaped by another waiter.
    timeout : float
        Deadline in seconds; zero permits an unbounded wait.

    Returns
    -------
    int or None
        Per-command peak RSS in KiB, or unavailable resource accounting.

    Raises
    ------
    subprocess.TimeoutExpired
        If the command remains live after its deadline.
    """
    pid = getattr(process, "pid", None)
    if measurement_capabilities()["collector"] != "wait4" or not isinstance(pid, int):
        process.wait(timeout=timeout or None)
        return None
    deadline = time.monotonic() + timeout if timeout else None
    while True:
        waited_pid, status, usage = os.wait4(pid, os.WNOHANG)
        if waited_pid:
            process.returncode = os.waitstatus_to_exitcode(status)
            rss = int(usage.ru_maxrss)
            return (rss + 1023) // 1024 if platform.system() == "Darwin" else rss
        if deadline is not None and time.monotonic() >= deadline:
            raise subprocess.TimeoutExpired(process.args, timeout)
        time.sleep(0.01)


def version_provenance() -> dict[str, object]:
    """Retain installed and generated versions and reject known disagreements.

    Parameters
    ----------
    None

    Returns
    -------
    dict of str to object
        Distribution/build versions with explicit consistency state.

    Raises
    ------
    ValueError
        If generated and installed versions disagree before a new campaign.
    """
    installed = importlib.metadata.version("codira")
    try:
        generated = getattr(importlib.import_module("codira._version"), "version", None)
    except ModuleNotFoundError as error:
        if error.name != "codira._version":
            raise
        generated = None
    if isinstance(generated, str) and generated != installed:
        message = "Installed and generated Codira versions differ; run uv sync --offline before creating a campaign."
        raise ValueError(message)
    return {
        "distribution": installed,
        "generated": generated,
        "consistent": generated == installed if generated is not None else None,
    }


def native_acceleration_identity() -> dict[str, object]:
    """Capture optional FAISS acceleration from the native library itself.

    Parameters
    ----------
    None

    Returns
    -------
    dict[str, object]
        Actual SIMD configuration, or an explicit missing optional dependency.

    Raises
    ------
    ModuleNotFoundError
        An unrelated dependency of the optional plugin cannot be imported.
    """
    try:
        module = importlib.import_module("codira_similarity_index_faiss")
    except ModuleNotFoundError as error:
        if error.name not in {"codira_similarity_index_faiss", "faiss"}:
            raise
        return {"faiss": {"available": False, "reason": str(error)}}
    return {"faiss": module.runtime_diagnostics()}


def coverage_is_partial(coverage: Mapping[str, object]) -> bool:
    """Recognize incomplete usable coverage in CLI or generation metadata.

    Parameters
    ----------
    coverage : collections.abc.Mapping[str, object]
        Coverage envelope or ready generation record. ``partial`` counts failed
        selected files; ``complete`` also accounts for unsupported/recovered input.

    Returns
    -------
    bool
        Whether known coverage gaps prevent complete-index comparisons.
    """
    if coverage.get("usable") is False:
        return False
    complete = coverage.get("complete", coverage.get("coverage_complete"))
    return bool(coverage.get("partial") or complete is False)


def classify_mcp_outcome(
    responses: list[dict[str, Any]], coverage: dict[str, Any]
) -> dict[str, Any]:
    """Classify protocol success separately from source coverage and usability.

    Parameters
    ----------
    responses : list of dict
        Retained MCP tool results and explicit prerequisite exclusions.
    coverage : dict
        Last reported generation coverage; all response coverage is also checked.

    Returns
    -------
    dict
        Operational status, comparison cohort and timing eligibility. Tool errors
        retain precedence over incomplete coverage.
    """
    payloads = [response.get("response") or {} for response in responses]
    envelopes = [
        coverage,
        *(
            payload.get("provenance", {}).get("index_coverage", {})
            for payload in payloads
        ),
    ]
    partial = any(coverage_is_partial(item) for item in envelopes) or any(
        payload.get("result", {}).get("status") == "partial" for payload in payloads
    )
    unusable = any(item.get("usable") is False for item in envelopes)
    status = (
        "failed"
        if any(response.get("is_error") for response in responses)
        else "unusable"
        if unusable
        else "partial"
        if partial
        else "passed"
    )
    return {
        "status": status,
        "usable": not unusable,
        "index_coverage": coverage,
        "comparison_group": "unusable_index"
        if unusable
        else "partial_coverage"
        if partial
        else "complete_index",
        "timing_valid": status == "passed",
        "partial_timing_valid": status == "partial",
    }


def mcp_error_details(responses: list[dict[str, Any]]) -> dict[str, str]:
    """Name actual tool errors without interpreting routine diagnostic prose.

    Parameters
    ----------
    responses : list of dict
        Retained tool responses carrying their protocol error flags.

    Returns
    -------
    dict[str, str]
        Failure reason when tool errors exist, otherwise an empty mapping.
    """
    names = [str(item["tool"]) for item in responses if item.get("is_error")]
    return {"reason": "MCP tool errors: " + ", ".join(names)} if names else {}


def classify_sample(
    argv: list[str], stdout: str, stderr: str, exit_code: int
) -> dict[str, Any]:
    """Classify process output without promoting partial or empty data to success.

    Parameters
    ----------
    argv : list of str
        Exact invocation before the timing wrapper.
    stdout : str
        Retained standard output.
    stderr : str
        Retained diagnostics.
    exit_code : int
        Actual process exit status.

    Returns
    -------
    dict
        Operational outcome and timing eligibility, with analysis failures.
    """
    operation = argv[1] if len(argv) > 1 else ""
    payload = {}
    if "--json" in argv:
        try:
            payload = json.loads(stdout)
            if not isinstance(payload, dict):
                failure = command_failure(
                    "process exited unsuccessfully"
                    if exit_code
                    else "invalid JSON envelope",
                    exit_code,
                    stderr,
                )
                failure["output_error"] = "invalid JSON envelope"
                return failure
        except ValueError:
            failure = command_failure(
                "process exited unsuccessfully"
                if exit_code
                else "malformed JSON output",
                exit_code,
                stderr,
            )
            failure["output_error"] = "malformed JSON output"
            return failure
    # These counts describe the current command's reported coverage scope.
    issues = (
        payload.get("results")
        if operation == "cov"
        else payload.get("coverage_issues")
        if operation == "index" and "--embeddings-only" not in argv
        else None
    )
    if isinstance(issues, list) and isinstance(payload.get("index_coverage"), dict):
        payload["index_coverage"] = {
            **payload["index_coverage"],
            "issue_count": len(issues),
        }
    if payload.get("status") in {"error", "failed", "invalid"}:
        return command_failure(
            "command reported an error", exit_code, stderr, payload.get("error")
        )
    if operation == "index":
        outcome = classify_index(payload, exit_code)
        if outcome is not None:
            return outcome
    empty = operation in READ_COMMANDS and (
        payload.get("status") == "no_matches"
        or (
            operation in {"calls", "refs"}
            and stdout.startswith(
                ("No call edges found", "No callable references found")
            )
        )
    )
    if exit_code not in ({0, 1} if empty else {0}):
        return command_failure("process exited unsuccessfully", exit_code, stderr)

    if operation in READ_COMMANDS and re.search(
        r"\[codira\] (?:Index (?:stale|missing|outdated|schema changed|not found)|Failed source or analysis configuration changed)",
        stderr,
    ):
        return {
            "status": "invalid_measurement",
            "reason": "query triggered automatic indexing",
            "timing_valid": False,
        }
    coverage = payload.get(
        "index_coverage", payload.get("provenance", {}).get("index_coverage", {})
    )
    if coverage.get("usable") is False:
        return {
            "status": "unusable",
            "usable": False,
            "timing_valid": False,
            "partial_timing_valid": False,
            "comparison_group": "unusable_index",
            "index_coverage": coverage,
        }
    partial = bool(
        coverage_is_partial(coverage)
        or "[codira] Partial index:" in stderr
        or payload.get("result", {}).get("status") == "partial"
    )
    if partial:
        return {
            "status": "partial_empty" if empty else "partial",
            "usable": coverage.get("usable", True),
            "index_coverage": coverage,
            "timing_valid": False,
            "partial_timing_valid": True,
            "comparison_group": "partial_coverage",
            "embedding_complete": payload.get("summary", {}).get(
                "embedding_complete", False
            ),
        }
    return {
        "status": "empty" if empty else "passed",
        "timing_valid": True,
        "comparison_group": "complete_index",
        "usable": True,
        "index_coverage": coverage,
        "embedding_complete": payload.get("summary", {}).get(
            "embedding_complete", False
        ),
    }


def has_analysis_failures(indexed: dict[str, Any]) -> bool:
    """Identify failed source attempts independently of coverage gaps.

    Parameters
    ----------
    indexed : dict
        Structural stage result with retained coverage and failure diagnostics.

    Returns
    -------
    bool
        Whether explicit indexing would retry a recorded source failure.
    """
    coverage = indexed.get("index_coverage", {})
    return bool(
        coverage.get("partial")
        or coverage.get("failed_file_count")
        or coverage.get("failed_paths")
        or indexed.get("analysis_failures")
        or indexed.get("failed_files")
    )


def classify_index(payload: dict[str, Any], exit_code: int) -> dict[str, Any] | None:
    """Separate queryable analysis failure from unusable structural state.

    Parameters
    ----------
    payload : dict
        Original indexing response.
    exit_code : int
        Original process exit status.

    Returns
    -------
    dict or None
        Partial, failed or unusable outcome; otherwise continue classification.
    """
    summary = payload.get("summary", {})
    if "summary" not in payload:
        return {
            "status": "failed",
            "reason": "missing index summary",
            "timing_valid": False,
        }
    coverage = payload.get("index_coverage", {})
    failures = payload.get("failures", [])
    usable = bool(
        coverage.get("usable", summary.get("indexed", 0) + summary.get("reused", 0) > 0)
    )
    if summary.get("failed", 0) or failures:
        return {
            "status": "failed" if exit_code else "partial" if usable else "unusable",
            "reason": "index skipped failed files" if usable else "index is unusable",
            "analysis_failures": failures,
            "failed_files": summary.get("failed", len(failures)),
            "usable": usable,
            "index_coverage": coverage
            or {"partial": True, "complete": False, "usable": usable},
            "embedding_complete": summary.get("embedding_complete", False),
            "comparison_group": "partial_coverage",
            "timing_valid": False,
            "partial_timing_valid": usable and exit_code == 0,
        }
    if coverage and not usable:
        return {
            "status": "unusable",
            "usable": False,
            "index_coverage": coverage,
            "timing_valid": False,
        }
    return None


def memory_summary(results: list[dict[str, Any]]) -> dict[str, object]:
    """Expose unavailable RSS samples separately from command success.

    Parameters
    ----------
    results : list of dict
        Retained stage receipts, including partial and failed measurements.

    Returns
    -------
    dict of str to object
        Availability counts and reasons; missing RSS is never a zero value.
    """
    samples = [
        (result["key"], number, sample)
        for result in results
        for number, sample in enumerate(result.get("samples", []))
    ]
    unavailable = [
        {
            "key": key,
            "sample": number,
            "reason": sample.get("memory_measurement", {}).get("reason")
            or "resource metadata absent",
        }
        for key, number, sample in samples
        if sample.get("peak_rss_kib") is None
    ]
    return {
        "capabilities": measurement_capabilities(),
        "sample_count": len(samples),
        "available_sample_count": len(samples) - len(unavailable),
        "unavailable_samples": unavailable,
    }


def aggregate_status(samples: list[dict[str, Any]]) -> str:
    """Reduce sample outcomes while preserving partial and invalid measurements.

    Parameters
    ----------
    samples : list of dict
        Classified process measurements.

    Returns
    -------
    str
        Worst recorded outcome, or empty when every invocation has no matches.
    """
    for status in (
        "interrupted",
        "timeout",
        "failed",
        "unusable",
        "invalid_measurement",
        "partial",
        "partial_empty",
    ):
        if any(sample["status"] == status for sample in samples):
            return status
    return (
        "empty" if all(sample["status"] == "empty" for sample in samples) else "passed"
    )


def terminate_group(process: subprocess.Popen[str]) -> None:
    """Stop an owned subprocess group, including graph render descendants.

    Parameters
    ----------
    process : subprocess.Popen
        Child launched with its own session.

    Returns
    -------
    None
        Children receive termination and remaining group members are killed.
    """
    with contextlib.suppress(ProcessLookupError):
        os.killpg(process.pid, signal.SIGTERM)
    with contextlib.suppress(subprocess.TimeoutExpired):
        process.wait(timeout=5)
    with contextlib.suppress(ProcessLookupError):
        os.killpg(process.pid, signal.SIGKILL)
    process.wait()


def digest(path: Path) -> str:
    """Hash one immutable input.

    Parameters
    ----------
    path : pathlib.Path
        Input file.

    Returns
    -------
    str
        SHA-256 digest.
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path: Path, value: object) -> None:
    """Atomically retain a JSON record.

    Parameters
    ----------
    path : pathlib.Path
        Destination.
    value : object
        JSON-serializable record.

    Returns
    -------
    None
        The record is replaced atomically.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    temporary.replace(path)


def items(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Read result items from inspected CLI and MCP envelopes.

    Parameters
    ----------
    payload : dict
        Decoded result.

    Returns
    -------
    list of dict
        Complete returned items.
    """
    value = payload.get("result", payload)
    return list(value.get("items", value.get("symbols", value.get("results", []))))


def planned_stage_keys(spec: dict[str, Any]) -> set[str]:
    """Enumerate potential measurements without executing the local corpus.

    Parameters
    ----------
    spec : dict
        Parsed analyzer-style or stress manifest.

    Returns
    -------
    set of str
        Stage identities, including conditional tests pruned during execution.
        Repeated samples belong to one stage.
    """
    keys = {"capabilities", "plugins"}
    profiles = spec.get("profiles", [])
    for profile in profiles:
        for repo in spec.get("repositories", []):
            prefix = f"{profile['id']}/{repo['label']}"
            stages = {
                "workspace",
                "config",
                "index-full",
                "index-incremental",
                "symlist",
                "cov",
                "audit",
                "ctx",
                "ctx-prompt",
                "ctx-explain",
                "arch",
                "sym",
                "calls",
                "calls-tree",
                "refs",
                "refs-incoming",
            }
            if profile.get("embeddings"):
                stages.update(
                    {"index-embeddings", "emb", "docs", "emb-rebuild", "emb-purge"}
                )
            if spec.get("extended"):
                stages.update(
                    {
                        "config-dump",
                        "config-explain",
                        "workspace-show",
                        "workspace-validate",
                        "mcp",
                        "mcp/cli-evidence",
                    }
                )
                if profile["id"] == profiles[0]["id"]:
                    stages.update({"index-process", "index-thread"})
            keys.update(f"{prefix}/{stage}" for stage in stages)
    if spec.get("extended"):
        keys.update(
            f"family/{stage}"
            for stage in (
                "index",
                "status",
                "validate",
                "ctx",
                "sym",
                "refs",
                "mcp",
                "mcp/cli-evidence",
            )
        )
        daemon_repository = spec.get("daemon_repository")
        if daemon_repository is not None:
            keys.update(
                f"daemons/{daemon_repository}/{stage}"
                for stage in (
                    "workspace",
                    "index",
                    "warm-query",
                    "foreground",
                    "restore-index",
                    "purge-owned-vectors",
                    "reset-owned-semantic-state",
                )
            )
        keys.update({"calibration", "installer"})
    return keys


def retains_checkpoint(status: str, retry_failed: bool) -> bool:
    """Decide whether an existing stage needs another attempt.

    Parameters
    ----------
    status : str
        Retained outcome.
    retry_failed : bool
        Explicit operator request to retry failed stages.

    Returns
    -------
    bool
        Whether execution reuses the checkpoint, including usable partial results.
    """
    return status in QUERYABLE_STATUSES or (
        not retry_failed and status != "interrupted"
    )


def outcome_description(status: str, result: Mapping[str, object] | None = None) -> str:
    """Explain terminal outcomes without changing stored machine statuses.

    Parameters
    ----------
    status : str
        Operational classification or explicit exclusion text.
    result : collections.abc.Mapping[str, object] | None, optional
        Retained coverage, failure and optional-artifact evidence.

    Returns
    -------
    str
        Compact description distinguishing coverage gaps, empty data and errors.
    """
    if result is None:
        return status
    details: list[str] = []
    coverage = result.get("index_coverage")
    if not isinstance(coverage, dict):
        coverage = {}
    if status in PARTIAL_STATUSES:
        if status == "partial_empty":
            details.append("no matches")
        failed = coverage.get("failed_file_count", result.get("failed_files"))
        if failed is not None:
            details.append(f"failed files={failed}")
        gaps = result.get("coverage_issue_count", coverage.get("issue_count"))
        if gaps is not None:
            details.append(f"coverage issues={gaps}")
        if coverage.get("complete") is False:
            details.append("coverage incomplete")
        elif not coverage.get("partial"):
            details.append("analysis limited")
    elif status == "empty":
        details.append("no matches")
    elif status == "unusable":
        details.append("index unavailable for dependent queries")
    elif status in {"failed", "timeout", "invalid_measurement", "excluded"}:
        reason = (
            result.get("stderr_diagnostic")
            or result.get("reason")
            or result.get("error")
        )
        if reason:
            details.append(" ".join(str(reason).split())[:160])
    optional = result.get("optional_artifacts")
    if isinstance(optional, dict):
        svg = optional.get("svg")
        if isinstance(svg, dict) and svg.get("available") is False:
            details.append(str(svg.get("warning", "optional SVG unavailable")))
    return status + (" (" + "; ".join(details) + ")" if details else "")


class StageProgress:
    """Track measurements pending in this invocation, excluding checkpoints.

    Parameters
    ----------
    keys : set of str
        Potential stage identities selected by the manifest.
    root : pathlib.Path
        Durable campaign root containing any resume checkpoints.
    retry_failed : bool
        Whether failed stages are eligible for another attempt.

    Returns
    -------
    None
        Counters are terminal-only and do not modify measurement receipts.
    """

    def __init__(self, keys: set[str], root: Path, retry_failed: bool) -> None:
        """Remove retained checkpoints from the initial pending inventory.

        Parameters
        ----------
        keys : set of str
            Potential measurement identities.
        root : pathlib.Path
            Campaign evidence root.
        retry_failed : bool
            Explicit retry control.

        Returns
        -------
        None
            Numbering starts at one for newly measured stages on every launch.
        """
        self.pending = keys.copy()
        self.completed = 0
        for key in keys:
            record = root / "stages" / key / "result.json"
            if record.exists() and retains_checkpoint(
                json.loads(record.read_text())["status"], retry_failed
            ):
                self.omit(key, retained=True)

    def omit(
        self,
        prefix: str,
        reason: str = "conditional prerequisite unavailable",
        *,
        retained: bool = False,
    ) -> None:
        """Explain newly omitted tests or silently prune retained checkpoints.

        Parameters
        ----------
        prefix : str
            Exact stage or slash-delimited group identity.
        reason : str, optional
            Prerequisite preventing these conditional measurements.
        retained : bool, optional
            Existing checkpoint reuse, which produces no new skip outcome.

        Returns
        -------
        None
            Each newly omitted test decrements pending once without an ordinal.
        """
        keys = sorted(
            key for key in self.pending if key == prefix or key.startswith(prefix + "/")
        )
        if retained:
            self.pending.difference_update(keys)
        else:
            for key in keys:
                self.report(key, "excluded: " + reason, measured=False)

    def report(
        self,
        key: str,
        status: str,
        *,
        measured: bool = True,
        result: Mapping[str, object] | None = None,
    ) -> None:
        """Prefix an outcome with its ordinal, pending count and local timestamp.

        Parameters
        ----------
        key : str
            Test name printed after the progress prefix.
        status : str
            Existing outcome text or exclusion reason.
        measured : bool, optional
            Whether a test was attempted rather than excluded.
        result : collections.abc.Mapping[str, object] | None, optional
            Retained evidence used to explain coverage and operational outcomes.

        Returns
        -------
        None
            Remaining tests exclude this outcome and retained checkpoints.
            The timestamp records this outcome in local time with its UTC offset.
        """
        if not measured and key not in self.pending:
            return
        self.pending.discard(key)
        if measured:
            self.completed += 1
        ordinal = str(self.completed) if measured else "skip"
        timestamp = (
            datetime.now(UTC).astimezone().isoformat(sep=" ", timespec="seconds")
        )
        print(
            f"[{ordinal}; {len(self.pending)}; {timestamp}]",
            key,
            outcome_description(status, result),
            flush=True,
        )

    def omit_unavailable(
        self, prefix: str, stages: tuple[str, ...], *, available: bool
    ) -> None:
        """Drop conditional tests whose discovery prerequisite is unavailable.

        Parameters
        ----------
        prefix : str
            Repository/profile identity.
        stages : tuple of str
            Stage suffixes sharing the prerequisite.
        available : bool
            Whether the prerequisite permits these measurements.

        Returns
        -------
        None
            Only unavailable tests are removed from the pending inventory.
        """
        if not available:
            for stage in stages:
                self.omit(prefix + "/" + stage, "no symbol identity discovered")


class Campaign:
    """Own one immutable run and its isolated state.

    Parameters
    ----------
    manifest : pathlib.Path
        Local suite definition.
    root : pathlib.Path
        Durable run directory.
    retry_failed : bool
        Whether failed stages may be attempted again.
    architecture_timeout_seconds : float, optional
        Outer architecture-command deadline, or zero for no outer limit.
    svg_timeout_seconds : float, optional
        Graphviz layout deadline passed explicitly to Codira; zero is unbounded.

    Returns
    -------
    None
        Owns stage checkpoints, isolated execution and terminal progress.
    """

    def __init__(
        self,
        manifest: Path,
        root: Path,
        retry_failed: bool,
        architecture_timeout_seconds: float = 300,
        svg_timeout_seconds: float = 180,
    ) -> None:
        """Configure isolated state and per-render limits for one local run.

        Parameters
        ----------
        manifest : pathlib.Path
            Operator-selected JSON suite.
        root : pathlib.Path
            Durable run directory.
        retry_failed : bool
            Whether unsuccessful completed stages may be retried.
        architecture_timeout_seconds : float, optional
            Outer architecture-command deadline, or zero to disable it.
        svg_timeout_seconds : float, optional
            Graphviz layout deadline; zero disables only the inner limit.

        Returns
        -------
        None
            The campaign is initialized without launching a workload.
        """
        self.manifest = manifest.resolve()
        self.spec = json.loads(manifest.read_text())
        self.root = root.resolve()
        self.retry_failed = retry_failed
        self.progress = StageProgress(
            planned_stage_keys(self.spec), self.root, retry_failed
        )
        validate_timeout(architecture_timeout_seconds)
        validate_timeout(svg_timeout_seconds, name="SVG timeout")
        self.architecture_timeout_seconds = architecture_timeout_seconds
        self.svg_timeout_seconds = svg_timeout_seconds
        self.env = dict(os.environ)
        for name in tuple(self.env):
            if not name.startswith("CODIRA_"):
                continue
            self.env.pop(name, None)
        self.env.update(
            XDG_CONFIG_HOME=str(self.root / "registry"),
            TMPDIR=self.spec["temporary_root"],
            HF_HUB_OFFLINE="1",
            TRANSFORMERS_OFFLINE="1",
            CODIRA_DISABLE_THIRD_PARTY_PLUGINS="1",
            UV_OFFLINE="1",
            PIP_NO_INDEX="1",
            LC_ALL="C",
        )
        self.codira = str(Path(sys.executable).with_name("codira"))
        self.results: list[dict[str, Any]] = []
        self.member_coverage: dict[str, dict[str, Any]] = {}
        self.embedding_ready: dict[str, bool] = {}
        self.requires_embeddings: dict[str, bool] = {}

    def environment_for_stage(self, key: str) -> dict[str, str]:
        """Select the profile registry used by a CLI, MCP or daemon stage.

        Parameters
        ----------
        key : str
            Stage identity whose first component may name a configured profile.

        Returns
        -------
        dict of str to str
            Independent environment with a profile-specific registry. Shared
            family and daemon stages use the primary profile's registry.
        """
        environment = self.env.copy()
        profiles = self.spec.get("profiles", [])
        if profiles:
            profile_ids = {profile["id"] for profile in profiles}
            candidate = key.split("/", 1)[0]
            profile_id = candidate if candidate in profile_ids else profiles[0]["id"]
            environment["XDG_CONFIG_HOME"] = str(self.root / "registry" / profile_id)
        return environment

    def command(self, key: str, argv: list[str], *, repeats: int = 1) -> dict[str, Any]:
        """Run a stage, preserving failures, timings and output per attempt.

        Parameters
        ----------
        key : str
            Unique stage key.
        argv : list of str
            Exact argument vector, without shell interpretation.
        repeats : int, optional
            Number of measured invocations.

        Returns
        -------
        dict
            Stage result, including every process exit status.

        Raises
        ------
        KeyboardInterrupt
            If interrupted, after the attempt evidence has been retained.
        OSError
            If the process cannot be started or its evidence cannot be written.
        """
        destination = self.root / "stages" / key
        record = destination / "result.json"
        if record.exists():
            old: dict[str, Any] = json.loads(record.read_text())
            if retains_checkpoint(old["status"], self.retry_failed):
                self.results.append(old)
                return old
        attempts = (
            destination / f"attempt-{len(list(destination.glob('attempt-*'))) + 1}"
        )
        attempts.mkdir(parents=True)
        samples = []
        interrupted = False
        for number in range(repeats):
            start = time.perf_counter()
            with (
                (attempts / f"{number}.stdout").open("w") as out,
                (attempts / f"{number}.stderr").open("w") as err,
            ):
                measured = (
                    ["/usr/bin/time", "-v", *argv]
                    if measurement_capabilities()["collector"] == "gnu-time"
                    else argv
                )
                process = subprocess.Popen(
                    measured,
                    env=self.environment_for_stage(key),
                    stdout=out,
                    stderr=err,
                    text=True,
                    start_new_session=True,
                )
                timed_out = False
                limit = (
                    self.architecture_timeout_seconds
                    if len(argv) > 1 and argv[1] == "arch"
                    else 0
                )
                peak_rss = None
                try:
                    peak_rss = wait_for_resources(process, limit)
                except subprocess.TimeoutExpired:
                    timed_out = True
                    terminate_group(process)
                except KeyboardInterrupt:
                    interrupted = True
                    terminate_group(process)
            memory = (
                re.search(
                    r"Maximum resident set size \(kbytes\):\s*(\d+)",
                    (attempts / f"{number}.stderr").read_text(),
                )
                if measurement_capabilities()["collector"] == "gnu-time"
                else None
            )
            samples.append(
                {
                    "seconds": time.perf_counter() - start,
                    "exit_code": process.returncode,
                    "peak_rss_kib": peak_rss
                    if peak_rss is not None
                    else int(memory.group(1))
                    if memory
                    else None,
                    "memory_measurement": {
                        **measurement_capabilities(),
                        "available": peak_rss is not None or memory is not None,
                        "reason": None
                        if peak_rss is not None or memory is not None
                        else "resource usage unavailable after interruption"
                        if timed_out or interrupted
                        else "resource collector unavailable for child",
                    },
                    "stdout": str(attempts / f"{number}.stdout"),
                    "stderr": str(attempts / f"{number}.stderr"),
                    **classify_sample(
                        argv,
                        (attempts / f"{number}.stdout").read_text(),
                        (attempts / f"{number}.stderr").read_text(),
                        process.returncode,
                    ),
                }
            )
            if not timed_out and not interrupted and process.returncode == 0:
                artifacts = architecture_artifacts(argv)
                if artifacts:
                    write(attempts / f"{number}.architecture-manifest.json", artifacts)
                    samples[-1].update(
                        optional_artifacts={"svg": artifacts.get("svg", {})},
                        architecture_artifacts=artifacts,
                    )
            if timed_out or interrupted:
                samples[-1].update(
                    status="interrupted" if interrupted else "timeout",
                    reason="operator interrupted stage"
                    if interrupted
                    else "architecture command exceeded limit",
                    timing_valid=False,
                    timeout_seconds=limit,
                )
            if samples[-1]["status"] not in QUERYABLE_STATUSES:
                break
        result: dict[str, Any] = {
            "key": key,
            "argv": argv,
            "samples": samples,
            "status": aggregate_status(samples),
            "stdout": str(attempts / "0.stdout"),
            "stderr": str(attempts / "0.stderr"),
        }
        result["attempt_history"] = (
            [
                str(path / "result.json")
                for path in sorted(destination.glob("attempt-*"))
            ]
            if "samples" in result
            else result.get("attempt_history", [])
        )
        if "samples" in result:
            result.update(
                {
                    key: samples[-1][key]
                    for key in (
                        "usable",
                        "index_coverage",
                        "embedding_complete",
                        "comparison_group",
                        "optional_artifacts",
                        "architecture_artifacts",
                    )
                    if key in samples[-1]
                }
            )
            write(attempts / "result.json", result)
        write(record, result)
        if len(argv) > 1 and argv[1] != "index" and "--workspace" in argv:
            position = argv.index("--workspace") + 1
            if position < len(argv):
                self.apply_coverage(
                    result, self.member_coverage.get(argv[position], {})
                )
        self.results.append(result)
        self.progress.report(key, result["status"], result=result)
        if interrupted:
            raise KeyboardInterrupt
        return result

    def exclude_queries(self, prefix: str, reason: str) -> None:
        """Record withheld query measurements without changing corpus or state.

        Parameters
        ----------
        prefix : str
            Repository/profile stage prefix.
        reason : str
            Prerequisite that did not pass.

        Returns
        -------
        None
            The durable exclusion remains visible in the summary.
        """
        self.progress.omit(prefix, reason)
        self.exclude_stage(prefix + "/queries", reason)

    def exclude_stage(self, key: str, reason: str) -> None:
        """Record a withheld stage without labelling it as a query group.

        Parameters
        ----------
        key : str
            Exact stage identifier.
        reason : str
            Prerequisite preventing execution.

        Returns
        -------
        None
            The summary and terminal output identify the withheld stage.
        """
        result = {"key": key, "status": "excluded", "reason": reason}
        write(self.root / "stages" / key / "result.json", result)
        self.results.append(result)
        self.progress.omit(key, reason)

    def cli(
        self, key: str, workspace: str, argv: list[str], *, repeats: int = 1
    ) -> dict[str, Any]:
        """Invoke the real CLI against a registered isolated workspace.

        Parameters
        ----------
        key : str
            Stage key.
        workspace : str
            Registered member.
        argv : list of str
            CLI arguments.
        repeats : int, optional
            Measured invocation count.

        Returns
        -------
        dict
            Persisted process result.
        """
        if argv[0] == "arch" and "--svg-timeout-seconds" not in argv:
            argv = [*argv, "--svg-timeout-seconds", str(self.svg_timeout_seconds)]
        result = self.command(
            key,
            [self.codira, argv[0], "--workspace", workspace, *argv[1:]],
            repeats=repeats,
        )
        return (
            result
            if argv[0] == "index"
            else self.apply_coverage(result, self.member_coverage.get(workspace, {}))
        )

    def apply_coverage(
        self, result: dict[str, Any], coverage: dict[str, Any]
    ) -> dict[str, Any]:
        """Annotate structural and warm measurements with their actual coverage.

        Parameters
        ----------
        result : dict
            Persisted measured stage.
        coverage : dict
            Structural generation metadata.

        Returns
        -------
        dict
            Same operational outcome with explicit measurement cohort.
        """
        partial = coverage_is_partial(coverage)
        unusable = coverage.get("usable") is False or result.get("usable") is False
        if partial or unusable:
            group = "unusable_index" if unusable else "partial_coverage"
            result["index_coverage"] = coverage
            result["comparison_group"] = group
            result["usable"] = not unusable
            if result["status"] in QUERYABLE_STATUSES:
                result["status"] = (
                    "unusable"
                    if unusable
                    else "partial_empty"
                    if result["status"] in {"empty", "partial_empty"}
                    else "partial"
                )
            result["timing_valid"] = False
            result["partial_timing_valid"] = result["status"] in PARTIAL_STATUSES
            for sample in result.get("samples", []):
                if sample["status"] in QUERYABLE_STATUSES:
                    sample["status"] = (
                        "unusable"
                        if unusable
                        else "partial_empty"
                        if sample["status"] in {"empty", "partial_empty"}
                        else "partial"
                    )
                sample.update(
                    index_coverage=coverage,
                    usable=not unusable,
                    timing_valid=False,
                    partial_timing_valid=sample["status"] in PARTIAL_STATUSES,
                    comparison_group=group,
                )
            write(self.root / "stages" / result["key"] / "result.json", result)
            history = result.get("attempt_history", [])
            if history:
                write(Path(history[-1]), result)
        return result

    def prepare_workspace(
        self, prefix: str, name: str, repository: str, state: Path, config: Path
    ) -> bool:
        """Register a workspace before validating its dependent configuration.

        Parameters
        ----------
        prefix, name : str
            Stage prefix and profile-specific workspace name.
        repository : str
            Canonical corpus root.
        state, config : pathlib.Path
            Isolated index state and explicit configuration file.

        Returns
        -------
        bool
            Whether both prerequisites passed; failure evidence is retained.
        """
        registered = self.command(
            prefix + "/workspace",
            [
                self.codira,
                "workspace",
                "add",
                name,
                "--path",
                repository,
                "--state-root",
                str(state),
                "--config-file",
                str(config),
            ],
        )
        if registered["status"] != "passed":
            self.exclude_stage(prefix + "/config", "workspace registration failed")
            self.exclude_queries(prefix, "workspace registration failed")
            return False
        configured = self.cli(
            prefix + "/config", name, ["config", "validate", "--json"]
        )
        if configured["status"] != "passed":
            self.exclude_queries(prefix, "configuration failed")
            return False
        return True

    def repository(
        self, repo: dict[str, Any], profile: dict[str, Any]
    ) -> dict[str, Any] | None:
        """Measure indexing and applicable CLI reads for one member/profile.

        Parameters
        ----------
        repo : dict
            Pinned repository and documentation witnesses.
        profile : dict
            Explicit local backend/embedding configuration.

        Returns
        -------
        dict or None
            Member selection for later MCP/family probes, or unavailable state.
        """
        name = f"{profile['id']}-{repo['label']}".lower()
        prefix = f"{profile['id']}/{repo['label']}"
        config = self.manifest.parent / repo["configs"][profile["id"]]
        state = self.root / "indexes" / name
        if not self.prepare_workspace(prefix, name, repo["path"], state, config):
            return None
        if self.spec["extended"]:
            self.cli(prefix + "/config-dump", name, ["config", "dump", "--json"])
            self.cli(
                prefix + "/config-explain",
                name,
                ["config", "explain", "embeddings.engine", "--json"],
            )
            self.command(
                prefix + "/workspace-show",
                [self.codira, "workspace", "show", name, "--json"],
            )
            self.command(
                prefix + "/workspace-validate",
                [self.codira, "workspace", "validate", name, "--json"],
            )
        args = ["index", "--full", "--json"]
        if profile["embeddings"]:
            args.append("--defer-embeddings")
        indexed = self.cli(prefix + "/index-full", name, args)
        if indexed["status"] not in QUERYABLE_STATUSES or not indexed.get(
            "usable", indexed["status"] in SUCCESS_STATUSES
        ):
            self.exclude_queries(prefix, "full index is " + indexed["status"])
            return None
        self.member_coverage[name] = indexed.get(
            "index_coverage", {"partial": indexed["status"] in PARTIAL_STATUSES}
        )
        self.requires_embeddings[name] = bool(profile["embeddings"])
        embeddings = None
        if profile["embeddings"]:
            embeddings = self.cli(
                prefix + "/index-embeddings",
                name,
                ["index", "--embeddings-only", "--json"],
            )
        indexed = self.measure_concurrency(prefix, name, profile, indexed)
        if indexed["status"] not in QUERYABLE_STATUSES or not indexed.get(
            "usable", indexed["status"] in SUCCESS_STATUSES
        ):
            self.exclude_queries(prefix, "latest structural index is unusable")
            return None
        self.member_coverage[name] = indexed.get(
            "index_coverage", self.member_coverage[name]
        )
        repetitions = repo["repetitions"]
        if has_analysis_failures(indexed):
            self.exclude_stage(
                prefix + "/index-incremental",
                "unchanged deterministic failures are not automatically retried",
            )
        else:
            incremental = self.cli(
                prefix + "/index-incremental",
                name,
                ["index", "--json"],
                repeats=repetitions,
            )
            if incremental["status"] not in QUERYABLE_STATUSES or not incremental.get(
                "usable", incremental["status"] in SUCCESS_STATUSES
            ):
                self.exclude_queries(prefix, "incremental index is unusable")
                return None
            self.member_coverage[name] = incremental.get(
                "index_coverage", self.member_coverage[name]
            )
        self.embedding_ready[name] = bool(
            embeddings
            and embeddings["status"] in QUERYABLE_STATUSES
            and embeddings.get("embedding_complete")
        )
        inventory = self.cli(
            prefix + "/symlist",
            name,
            ["symlist", "--json", "--include-tests", "--limit", "100"],
        )
        data = (
            json.loads(Path(inventory["stdout"]).read_text())
            if inventory["status"] in QUERYABLE_STATUSES
            else {}
        )
        symbols = items(data)
        symbol = next(
            (s for s in symbols if s.get("type") in ("function", "method")),
            symbols[0] if symbols else None,
        )
        self.progress.omit_unavailable(
            prefix,
            ("sym", "calls", "calls-tree", "refs", "refs-incoming"),
            available=symbol is not None,
        )
        query = symbol["name"].replace("_", " ") if symbol else repo["query"]
        for operation in (
            ["cov", "--json"],
            ["audit", "--json"],
            ["ctx", query, "--json"],
            ["ctx", query, "--prompt"],
            ["ctx", query, "--explain"],
            ["arch", "--output", str(self.root / "architecture" / name)],
        ):
            mode = operation[0] + (
                "-prompt"
                if "--prompt" in operation
                else "-explain"
                if "--explain" in operation
                else ""
            )
            if (
                operation[0] == "ctx"
                and profile["embeddings"]
                and not self.embedding_ready[name]
            ):
                self.exclude_queries(
                    prefix + "/" + mode, "embedding population did not complete"
                )
                continue
            self.cli(prefix + "/" + mode, name, operation, repeats=repetitions)
        if symbol:
            for operation in (
                ["sym", symbol["name"], "--json"],
                ["calls", symbol["name"], "--json"],
                ["calls", symbol["name"], "--tree", "--dot"],
                ["refs", symbol["name"], "--json"],
                ["refs", symbol["name"], "--incoming", "--tree", "--dot"],
            ):
                key = operation[0] + (
                    "-incoming"
                    if "--incoming" in operation
                    else "-tree"
                    if "--tree" in operation
                    else ""
                )
                self.cli(prefix + "/" + key, name, operation, repeats=repetitions)
        if profile["embeddings"] and self.embedding_ready[name]:
            for operation in (
                ["emb", query, "--json", "--limit", "10"],
                ["docs", repo["query"], "--json"],
                ["emb", "rebuild", "--json"],
                ["emb", "purge", "--stale", "--dry-run", "--json"],
            ):
                self.cli(
                    prefix
                    + "/"
                    + (
                        "emb-" + operation[1]
                        if operation[0] == "emb"
                        and operation[1] in ("rebuild", "purge")
                        else operation[0]
                    ),
                    name,
                    operation,
                    repeats=repetitions,
                )
        self.record_embedding_exclusion(prefix, name)
        return {
            "workspace": name,
            "repo": repo,
            "profile": profile,
            "symbol": symbol,
            "query": query,
            "index_coverage": self.member_coverage[name],
            "embedding_ready": self.embedding_ready[name],
        }

    def record_embedding_exclusion(self, prefix: str, name: str) -> None:
        """Expose missing population prerequisites without blocking structural reads.

        Parameters
        ----------
        prefix : str
            Stage prefix.
        name : str
            Workspace name.

        Returns
        -------
        None
            Required but unready embedding stages are visibly excluded.
        """
        if self.requires_embeddings[name] and not self.embedding_ready[name]:
            for stage in ("emb", "docs", "emb-rebuild", "emb-purge"):
                self.progress.omit(
                    prefix + "/" + stage, "embedding population did not complete"
                )
            self.exclude_queries(
                prefix + "/semantic", "embedding population did not complete"
            )

    def measure_concurrency(
        self, prefix: str, name: str, profile: dict[str, Any], indexed: dict[str, Any]
    ) -> dict[str, Any]:
        """Measure optional schedulers when selected sources have no failures.

        Parameters
        ----------
        prefix : str
            Stage prefix.
        name : str
            Workspace name.
        profile : dict
            Backend profile.
        indexed : dict
            Structural outcome.

        Returns
        -------
        dict
            Latest structural outcome; partial failures are never retried.
        """
        if (
            indexed["status"] in QUERYABLE_STATUSES
            and indexed.get("usable", True)
            and not has_analysis_failures(indexed)
            and self.spec["extended"]
            and profile["id"] == self.spec["profiles"][0]["id"]
        ):
            for strategy in ("process", "thread"):
                result = self.cli(
                    prefix + "/index-" + strategy,
                    name,
                    [
                        "index",
                        "--full",
                        "--concurrency",
                        strategy,
                        "--jobs",
                        "2",
                        "--json",
                    ],
                )
                indexed = result
                if (
                    result["status"] not in QUERYABLE_STATUSES
                    or not result.get("usable", True)
                    or has_analysis_failures(result)
                ):
                    self.progress.omit(
                        prefix + "/index-thread",
                        "preceding concurrency index was unusable or had analysis failures",
                    )
                    return result
        else:
            self.progress.omit(
                prefix + "/index-process",
                "concurrency indexing prerequisites unavailable",
            )
            self.progress.omit(
                prefix + "/index-thread",
                "concurrency indexing prerequisites unavailable",
            )

        return indexed

    async def mcp(self, key: str, args: list[str], query: str) -> dict[str, Any]:
        """Exercise advertised tools through an actual stdio MCP client.

        Parameters
        ----------
        key : str
            Durable probe key.
        args : list of str
            Fixed server startup selection.
        query : str
            Context and semantic query.

        Returns
        -------
        dict
            Tool responses and explicit unsupported-data exclusions.
        """
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        record = self.root / "stages" / key / "result.json"
        if record.exists():
            previous: dict[str, Any] = json.loads(record.read_text())
            if retains_checkpoint(previous["status"], self.retry_failed):
                self.progress.omit(key + "/cli-evidence", retained=True)
                self.results.append(previous)
                return previous
        destination = record.parent
        attempts = (
            destination / f"attempt-{len(list(destination.glob('attempt-*'))) + 1}"
        )
        attempts.mkdir(parents=True)
        server = StdioServerParameters(
            command=str(Path(sys.executable).with_name("codira-mcp")),
            args=args,
            env=self.environment_for_stage(key),
        )
        responses: list[dict[str, Any]] = []
        result: dict[str, Any]
        symbol = None
        workspace = args[1] if "--workspace" in args else None
        coverage = self.member_coverage.get(workspace or "", {})
        semantic_ready = self.embedding_ready.get(workspace or "", False)
        start = time.perf_counter()
        try:
            with (attempts / "mcp.stderr").open("w") as errlog:
                async with (
                    stdio_client(server, errlog=errlog) as (read, output),
                    ClientSession(
                        read, output, read_timeout_seconds=timedelta(seconds=3600)
                    ) as session,
                ):
                    await session.initialize()
                    available = {
                        tool.name for tool in (await session.list_tools()).tools
                    }
                    names = [
                        "capabilities",
                        "index_status",
                        "symbols",
                        "context_for_task",
                        "symbol",
                        "symbol_evidence",
                        "references",
                        "callers",
                        "callees",
                        "impact_analysis",
                        "repository_map",
                        "arch",
                        "emb",
                        "docs",
                    ]
                    for tool in names:
                        if tool not in available:
                            continue
                        if (
                            tool in {"emb", "docs"}
                            or tool == "context_for_task"
                            and self.requires_embeddings.get(workspace or "", False)
                        ) and not semantic_ready:
                            responses.append(
                                {
                                    "tool": tool,
                                    "excluded": "embedding prerequisites unavailable",
                                }
                            )
                            continue
                        arguments = tool_arguments(tool, query, symbol)
                        if (
                            arguments is not None
                            and "--family" in args
                            and tool in {"context_for_task", "symbol", "references"}
                        ):
                            arguments["allow_partial"] = True
                        if arguments is None:
                            responses.append(
                                {
                                    "tool": tool,
                                    "excluded": "no discovered symbol identity",
                                }
                            )
                            continue
                        tool_result = await session.call_tool(tool, arguments)
                        payload = tool_result.structuredContent
                        if payload is None:
                            payload = json.loads(
                                next(
                                    block.text
                                    for block in tool_result.content
                                    if block.type == "text"
                                )
                            )
                        coverage = payload.get("provenance", {}).get(
                            "index_coverage", coverage
                        )
                        responses.append(
                            {
                                "tool": tool,
                                "arguments": arguments,
                                "is_error": tool_result.isError,
                                "response": payload,
                            }
                        )
                        if tool in ("symbols", "context_for_task") and symbol is None:
                            symbol = next(
                                (x for x in items(payload) if x.get("identity")), None
                            )
                        cursor = payload.get("page", {}).get("next_cursor")
                        if cursor and tool in ("symbols", "context_for_task"):
                            next_page = await session.call_tool(
                                tool, {**arguments, "cursor": cursor}
                            )
                            responses.append(
                                {
                                    "tool": tool + "/continuation",
                                    "is_error": next_page.isError,
                                    "response": next_page.structuredContent,
                                }
                            )
                    if "--family" in args and symbol:
                        linked = await session.call_tool(
                            "references",
                            {
                                "name": symbol["name"],
                                "direction": "outgoing",
                                "limit": 10,
                                "allow_partial": True,
                            },
                        )
                        responses.append(
                            {
                                "tool": "references/explicit-links",
                                "is_error": linked.isError,
                                "response": linked.structuredContent,
                            }
                        )
            result = {
                "key": key,
                **classify_mcp_outcome(responses, coverage),
                "seconds": time.perf_counter() - start,
                "transport": "real_stdio",
                "responses": responses,
            }
            if symbol and "identity" in symbol:
                if "--family" in args:
                    self.command(
                        key + "/cli-evidence",
                        [
                            self.codira,
                            "family",
                            "evidence",
                            args[1],
                            symbol["identity"],
                            "--json",
                        ],
                    )
                else:
                    self.cli(
                        key + "/cli-evidence", args[1], ["evidence", symbol["identity"]]
                    )
        except Exception as error:
            LOGGER.exception("Benchmark stage failed; retaining checkpoint")
            result = {
                "key": key,
                "status": "failed",
                "error": str(error),
                "responses": responses,
            }
        result["stderr"] = str(attempts / "mcp.stderr")
        result.update(mcp_error_details(responses))
        result["attempt_history"] = [
            str(path / "result.json") for path in sorted(destination.glob("attempt-*"))
        ]
        write(attempts / "result.json", result)
        write(record, result)
        self.results.append(result)
        self.progress.omit(
            key + "/cli-evidence",
            "MCP probe failed before CLI evidence could run"
            if result["status"] == "failed"
            else "no MCP symbol identity discovered",
        )
        self.progress.report(key, result["status"], result=result)
        return result

    def daemons(self, member: dict[str, Any]) -> None:
        """Measure real warm reads and a foreground source-change reconciliation.

        Parameters
        ----------
        member : dict
            Selected indexed repository/profile.

        Returns
        -------
        None
            Clone, timings and restoration evidence remain in this run only.
        """
        repo, profile = member["repo"], member["profile"]
        key = "daemons/" + repo["label"]
        clone = self.root / "daemon-clone" / repo["label"]
        if not clone.exists():
            self.command(
                key + "/clone", ["git", "clone", "--shared", repo["path"], str(clone)]
            )
        config = self.manifest.parent / repo["configs"][profile["id"]]
        name = "daemon-" + repo["label"]
        self.command(
            key + "/workspace",
            [
                self.codira,
                "workspace",
                "add",
                name,
                "--path",
                str(clone),
                "--state-root",
                str(clone),
                "--config-file",
                str(config),
            ],
        )
        self.cli(key + "/index", name, ["index", "--full", "--json"])
        saved_env = self.env.copy()
        self.env["CODIRA_CONFIG_FILE"] = str(config)
        warm = self.command(
            key + "/warm-query",
            [
                sys.executable,
                str(
                    Path(self.spec["codira_root"]) / "scripts/benchmark_query_daemon.py"
                ),
                "--root",
                str(clone),
                "--runs",
                str(repo["repetitions"]),
                "--query",
                member["query"],
                "--output",
                str(self.root / "daemon-warm.json"),
            ],
        )
        self.apply_coverage(warm, member.get("index_coverage", {}))
        self.env = saved_env
        result_path = self.root / "stages" / key / "foreground" / "result.json"
        if result_path.exists():
            previous = json.loads(result_path.read_text())
            if retains_checkpoint(previous["status"], self.retry_failed):
                self.results.append(previous)
                if previous["status"] in QUERYABLE_STATUSES:
                    self.finish_daemon(key, name)
                return
        # Only this disposable clone is changed. Restore even on errors/signals.
        source = clone / repo["daemon_witness"]
        original = source.read_bytes()
        generation_path = clone / ".codira/index-generation.json"
        start = time.perf_counter()
        result = {"key": key + "/foreground", "status": "failed"}
        initial = json.loads(generation_path.read_text())["generation"]
        with (self.root / "daemon-foreground.log").open("w") as log:
            process = subprocess.Popen(
                [self.codira, "daemon", "--workspace", name, "run"],
                env=self.environment_for_stage(key),
                stdout=log,
                stderr=log,
            )
            try:
                deadline = (
                    time.monotonic()
                    + self.spec["daemon_reconciliation_timeout_seconds"]
                )
                while time.monotonic() < deadline and process.poll() is None:
                    state = json.loads(generation_path.read_text())
                    status_path = clone / ".codira/daemon-status.json"
                    reconciled = (
                        json.loads(status_path.read_text())
                        if status_path.exists()
                        else {}
                    )
                    if (
                        state["generation"] >= initial
                        and state["state"] == "ready"
                        and reconciled.get("last_success_at")
                    ):
                        break
                    time.sleep(1)
                else:
                    reject("foreground daemon did not finish initial reconciliation")
                before = json.loads(generation_path.read_text())["generation"]
                source.write_bytes(original + b"\n")
                deadline = (
                    time.monotonic()
                    + self.spec["daemon_reconciliation_timeout_seconds"]
                )
                while time.monotonic() < deadline and process.poll() is None:
                    state = json.loads(generation_path.read_text())
                    if state["generation"] > before and state["state"] == "ready":
                        result.update(
                            status="partial"
                            if coverage_is_partial(state)
                            else "passed",
                            comparison_group="partial_coverage"
                            if coverage_is_partial(state)
                            else "complete_index",
                            index_coverage={
                                "usable": True,
                                "partial": state.get("partial", False),
                                "complete": state.get("coverage_complete", True),
                                "failed_file_count": state.get("failed_file_count", 0),
                                "attempted_file_count": state.get(
                                    "attempted_file_count"
                                ),
                                "indexed_file_count": state.get("indexed_file_count"),
                            },
                            timing_valid=not coverage_is_partial(state),
                            partial_timing_valid=coverage_is_partial(state),
                            before=before,
                            after=state["generation"],
                            seconds=time.perf_counter() - start,
                        )
                        break
                    time.sleep(1)
            except Exception as error:
                LOGGER.exception("Benchmark stage failed; retaining checkpoint")
                result["error"] = str(error)
            finally:
                process.send_signal(signal.SIGINT)
                try:
                    process.wait(timeout=30)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
                source.write_bytes(original)
        write(result_path, result)
        self.results.append(result)
        self.progress.report(result["key"], result["status"], result=result)
        self.finish_daemon(key, name)

    def finish_daemon(self, key: str, name: str) -> None:
        """Restore the clone index and exercise owned semantic cleanup.

        Parameters
        ----------
        key : str
            Durable stage prefix.
        name : str
            Clone workspace.

        Returns
        -------
        None
            All command results are retained or resumed.
        """
        self.cli(key + "/restore-index", name, ["index", "--json"])
        self.cli(
            key + "/purge-owned-vectors",
            name,
            ["emb", "purge", "--all", "--yes", "--json"],
        )
        self.cli(
            key + "/reset-owned-semantic-state",
            name,
            ["emb", "reset", "--yes", "--json"],
        )

    def family(self, members: list[dict[str, Any]]) -> None:
        """Run federation against explicitly linked, independently indexed members.

        Parameters
        ----------
        members : list of dict
            Successfully indexed members in the primary profile.

        Returns
        -------
        None
            Family CLI and MCP evidence is retained.
        """
        usable = [m for m in members if m["symbol"]]
        if len(usable) < 2:
            self.results.append(
                {
                    "key": "family",
                    "status": "failed",
                    "error": "two members with symbols required",
                }
            )
            return
        path = self.root / "family.toml"
        lines = ["schema_version = 1", 'name = "stress-family"']
        for m in members:
            lines += [
                "[[members]]",
                "workspace = " + json.dumps(m["workspace"]),
                'role = "benchmark-member"',
            ]
        lines += ["[[links]]"]
        for side, member in zip(("source", "target"), usable[:2], strict=True):
            symbol = member["symbol"]
            file = Path(symbol["file"])
            if file.is_absolute():
                file = file.relative_to(member["repo"]["path"])
            lines += [
                f"[links.{side}]",
                "workspace = " + json.dumps(member["workspace"]),
                "name = " + json.dumps(symbol["name"]),
                "file = " + json.dumps(file.as_posix()),
                "lineno = " + str(symbol.get("line", symbol.get("lineno"))),
            ]
        path.write_text("\n".join(lines) + "\n")
        for operation in ("index", "status", "validate"):
            if operation in {"index", "validate"} and any(
                m.get("index_coverage", {}).get("partial") for m in members
            ):
                self.exclude_queries(
                    "family/" + operation,
                    "partial members retained; no automatic retry or strict validation",
                )
                continue
            self.command(
                "family/" + operation,
                [self.codira, "family", operation, str(path), "--json"],
            )
        for operation, query in (
            ("ctx", usable[0]["query"]),
            ("sym", usable[0]["symbol"]["name"]),
            ("refs", usable[0]["symbol"]["name"]),
        ):
            self.command(
                "family/" + operation,
                [
                    self.codira,
                    "family",
                    operation,
                    str(path),
                    query,
                    "--json",
                    "--allow-partial",
                ],
            )
        asyncio.run(self.mcp("family/mcp", ["--family", str(path)], usable[0]["query"]))


def reject(message: str) -> NoReturn:
    """Reject an invalid plan or unavailable prerequisite.

    Parameters
    ----------
    message : str
        Diagnostic to retain.

    Returns
    -------
    None
        The function always raises.

    Raises
    ------
    ValueError
        Always, with the supplied diagnostic.
    """
    raise ValueError(message)


def tool_arguments(
    tool: str, query: str, symbol: dict[str, Any] | None
) -> dict[str, Any] | None:
    """Select bounded arguments for a discovered MCP tool.

    Parameters
    ----------
    tool : str
        Advertised tool name.
    query : str
        Workload query.
    symbol : dict or None
        Discovered symbol identity.

    Returns
    -------
    dict or None
        Arguments, or an explicit unsupported-data exclusion.
    """
    if tool in ("context_for_task", "emb", "docs"):
        return {"query": query, "limit": 10}
    if tool == "symbols":
        return {"limit": 10}
    if tool in ("symbol", "references", "callers", "callees", "impact_analysis"):
        return {"name": symbol["name"], "limit": 10} if symbol else None
    if tool == "symbol_evidence":
        return (
            {"identity": symbol["identity"], "limit": 10}
            if symbol and "identity" in symbol
            else None
        )
    return {}


def validate_plan(manifest: Path, spec: dict[str, Any]) -> None:
    """Validate input paths and syntax without executing the workload.

    Parameters
    ----------
    manifest : pathlib.Path
        Suite definition.
    spec : dict
        Parsed suite.

    Returns
    -------
    None
        Input problems raise a diagnostic exception.
    """
    if spec["schema_version"] != 1:
        reject("unsupported local suite schema")
    for repo in spec["repositories"]:
        if not Path(repo["path"]).is_dir():
            reject("missing repository: " + repo["path"])
        for config in repo["configs"].values():
            tomllib.loads((manifest.parent / config).read_text())


def verify_revisions(spec: dict[str, Any]) -> None:
    """Reject corpus drift before running any index.

    Parameters
    ----------
    spec : dict
        Pinned suite definition.

    Returns
    -------
    None
        Mismatched or dirty repositories raise a diagnostic exception.
    """
    # Check all revisions and tracked modifications before running any index.
    for repo in spec["repositories"]:
        head = subprocess.check_output(
            [
                shutil.which("git") or "/usr/bin/git",
                "-C",
                repo["path"],
                "rev-parse",
                "HEAD",
            ],
            text=True,
        ).strip()
        if head != repo["revision"]:
            reject("revision drift: " + repo["label"])
        subprocess.run(
            [
                shutil.which("git") or "/usr/bin/git",
                "-C",
                repo["path"],
                "diff",
                "--quiet",
                "HEAD",
            ],
            check=True,
        )


def execute_extension(operation: Callable[[], object]) -> None:
    """Invoke one selected extension after validating that it is callable.

    Parameters
    ----------
    operation : collections.abc.Callable
        Bound benchmark extension.

    Returns
    -------
    None
        The extension retains its own outcomes.
    """
    operation()


def architecture_artifacts(argv: list[str]) -> dict[str, Any]:
    """Read the renderer's reported outcome rather than infer SVG success.

    Parameters
    ----------
    argv : list of str
        Completed architecture invocation with an explicit output directory.

    Returns
    -------
    dict
        Mandatory-artifact and optional-SVG manifest, or no evidence when absent.
    """
    if len(argv) < 2 or argv[1] != "arch" or "--output" not in argv:
        return {}
    position = argv.index("--output") + 1
    if position >= len(argv):
        return {}
    manifest = Path(argv[position]) / "manifest.json"
    if not manifest.exists():
        return {}
    payload = json.loads(manifest.read_text())
    if not isinstance(payload, dict):
        reject("architecture manifest must be an object")
    return payload


def validate_timeout(value: float, *, name: str = "architecture timeout") -> None:
    """Reject invalid architecture rendering limits.

    Parameters
    ----------
    value : float
        Seconds per invocation, or zero for an unbounded limit.
    name : str, optional
        Diagnostic label distinguishing inner rendering and outer command limits.

    Returns
    -------
    None
        Invalid limits raise a diagnostic exception.
    """
    if value < 0 or not value < float("inf"):
        reject(f"{name} must be finite and nonnegative")


def snapshot_failure_evidence(
    original_run: Path, destination: Path
) -> list[dict[str, Any]]:
    """Copy failure receipts and raw output without mutating the source run.

    Parameters
    ----------
    original_run : pathlib.Path
        Retained benchmark identity.
    destination : pathlib.Path
        New recovery directory.

    Returns
    -------
    list[dict[str, Any]]
        Digest-linked evidence copies.
    """
    evidence_rows: list[dict[str, Any]] = []
    for number, stage in enumerate(
        sorted((original_run / "stages").rglob("result.json"))
    ):
        result = json.loads(stage.read_text())
        if result.get("status") in SUCCESS_STATUSES:
            continue
        retained = destination / "source-evidence" / str(number)
        write(retained / "result.json", result)
        evidence: dict[str, Any] = {
            "original": str(stage),
            "sha256": digest(stage),
            "snapshot": str(retained / "result.json"),
            "outputs": [],
        }
        for sample_number, sample in enumerate(result.get("samples", [])):
            for channel in ("stdout", "stderr"):
                source = Path(sample[channel])
                if source.is_file():
                    target = retained / f"{sample_number}.{channel}"
                    shutil.copyfile(source, target)
                    evidence["outputs"].append(
                        {
                            "original": str(source),
                            "sha256": digest(source),
                            "snapshot": str(target),
                        }
                    )
        evidence_rows.append(evidence)
    return evidence_rows


def prepare_recovery(
    manifest: Path, original_run: Path | None, destination: Path, exclusions: list[str]
) -> Path:
    """Freeze a new operator-selected plan while preserving original evidence.

    Parameters
    ----------
    manifest : pathlib.Path
        Original immutable suite input.
    original_run : pathlib.Path | None
        Existing identity and stage evidence, or no prior run for a baseline.
    destination : pathlib.Path
        New durable directory; must not already exist.
    exclusions : list[str]
        Explicit repository:analyzer:relative-path exclusions.

    Returns
    -------
    pathlib.Path
        Prepared manifest; no workload is launched.
    """
    if original_run is None and exclusions:
        reject("exclusions require an original run for evidence-linked recovery")
    original_spec = json.loads(manifest.read_text())
    identity_path = None if original_run is None else original_run / "identity.json"
    identity: dict[str, Any] = (
        json.loads(identity_path.read_text())
        if identity_path is not None
        else {
            "manifest_sha256": digest(manifest),
            "configs": {
                relative: digest(manifest.parent / relative)
                for repo in original_spec["repositories"]
                for relative in repo["configs"].values()
            },
        }
    )
    if identity["manifest_sha256"] != digest(manifest):
        reject("original manifest differs from retained run identity")
    if destination.exists():
        reject("recovery directory exists; choose a fresh identity")
    spec = json.loads(manifest.read_text())
    selected: dict[str, dict[str, list[str]]] = {}
    labels = {repo["label"] for repo in spec["repositories"]}
    for exclusion in exclusions:
        parts = exclusion.split(":", 2)
        if len(parts) != 3:
            reject("exclusions must be repository:analyzer:relative-path")
        label, analyzer, relative = parts
        if (
            label not in labels
            or not analyzer
            or not relative
            or Path(relative).is_absolute()
            or ".." in Path(relative).parts
        ):
            reject(
                "exclusion must identify a declared repository and a safe relative path"
            )
        selected.setdefault(label, {}).setdefault(analyzer, []).append(relative)
    configs: dict[str, str] = {}
    documents: dict[str, str] = {}
    for repo in spec["repositories"]:
        for profile, relative in repo["configs"].items():
            source = (manifest.parent / relative).resolve()
            if identity.get("configs", {}).get(relative) != digest(source):
                reject(
                    "original configuration differs from retained identity: " + relative
                )
            document = tomlkit.parse(source.read_text())
            for analyzer, paths in selected.get(repo["label"], {}).items():
                plugins = document.setdefault("plugins", tomlkit.table())
                table = plugins.setdefault("analyzer-" + analyzer, tomlkit.table())
                existing = list(table.get("exclude_paths", []))
                table["exclude_paths"] = sorted(set(existing + paths))
            target = f"configs/{profile}-{repo['label']}.toml"
            documents[target] = tomlkit.dumps(document)
            configs[str(source)] = digest(source)
            repo["configs"][profile] = target
    provenance: dict[str, Any] = {
        "original_run": None if original_run is None else str(original_run.resolve()),
        "original_identity": identity,
        "original_identity_sha256": None
        if identity_path is None
        else digest(identity_path),
        "original_manifest_sha256": digest(manifest),
        "original_config_digests": configs,
        "operator_exclusions": selected,
        "failure_evidence": [],
    }
    destination.mkdir(parents=True)
    for relative, content in documents.items():
        path = destination / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    provenance["failure_evidence"] = (
        []
        if original_run is None
        else snapshot_failure_evidence(original_run, destination)
    )
    spec["codira_root"] = str(Path(__file__).resolve().parents[1])
    spec["artifact_root"] = str(destination.resolve() / "runs")
    spec["recovery"] = provenance
    prepared = destination / "manifest.json"
    write(prepared, spec)
    write(destination / "recovery-provenance.json", provenance)
    return prepared


def prepare_operator_recovery(args: argparse.Namespace) -> Path | None:
    """Validate recovery options and prepare the operator's immutable plan.

    Parameters
    ----------
    args : argparse.Namespace
        Parsed launcher options.

    Returns
    -------
    pathlib.Path | None
        Prepared manifest or no recovery request.
    """
    if args.prepare_recovery or args.prepare_plan:
        if (
            args.run
            or not args.recovery_dir
            or (args.prepare_plan and args.prepare_recovery)
        ):
            reject("recovery preparation requires --recovery-dir and cannot use --run")
        return prepare_recovery(
            args.manifest.resolve(),
            None if args.prepare_recovery is None else args.prepare_recovery.resolve(),
            args.recovery_dir.resolve(),
            args.exclude_file,
        )
    if args.exclude_file or args.recovery_dir:
        reject("exclusions and recovery directory require --prepare-recovery")
    return None


def campaign_exit_status(results: list[dict[str, Any]]) -> int:
    """Keep partial coverage distinct from complete execution and failure.

    Parameters
    ----------
    results : list[dict[str, Any]]
        Retained stage outcomes, including resumed checkpoints.

    Returns
    -------
    int
        One for command failures, two for partial coverage, otherwise zero.
    """
    if any(
        r["status"] not in QUERYABLE_STATUSES and r["status"] != "excluded"
        for r in results
    ):
        return 1
    return 2 if any(r["status"] in PARTIAL_STATUSES for r in results) else 0


def resolve_run_root(spec: dict[str, Any], run_id: str | None, resume: bool) -> Path:
    """Require a fresh durable identity or explicit unchanged resume.

    Parameters
    ----------
    spec : dict
        Suite artifact routing.
    run_id : str | None
        Operator-selected safe identifier.
    resume : bool
        Permit an existing identity.

    Returns
    -------
    pathlib.Path
        Validated durable run location.
    """
    if not run_id:
        reject("--run-id is required for immutable artifact identity")
    if Path(run_id).name != run_id or run_id in (".", ".."):
        reject("run-id must be one safe path component")
    root = (Path(spec["artifact_root"]) / run_id).resolve()
    if root.exists() and not resume:
        reject("run exists; choose a fresh identity or explicitly --resume")
    return root


def main() -> int:
    """Validate a plan or execute it only with explicit --run.

    Parameters
    ----------
    None

    Returns
    -------
    int
        Nonzero for invalid inputs, failed stages or incomplete required coverage.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--run-id")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--retry-failed", action="store_true")
    parser.add_argument("--prepare-recovery", type=Path, metavar="ORIGINAL_RUN")
    parser.add_argument("--prepare-plan", action="store_true")
    parser.add_argument("--recovery-dir", type=Path)
    parser.add_argument(
        "--exclude-file", action="append", default=[], metavar="REPO:ANALYZER:PATH"
    )
    parser.add_argument(
        "--architecture-timeout-seconds",
        type=float,
        default=300,
        help="Outer architecture-command deadline; default 300 seconds, 0 disables",
    )
    parser.add_argument(
        "--svg-timeout-seconds",
        type=float,
        default=180,
        help="Inner Graphviz layout deadline; default 180 seconds, 0 disables",
    )
    args = parser.parse_args()
    prepared = prepare_operator_recovery(args)
    if prepared is not None:
        print(
            json.dumps(
                {
                    "prepared_manifest": str(prepared),
                    "run_command": [
                        sys.executable,
                        str(Path(__file__).resolve()),
                        str(prepared),
                        "--run",
                        "--run-id",
                        "recovery-r1",
                    ],
                },
                indent=2,
            )
        )
        return 0
    validate_timeout(args.architecture_timeout_seconds)
    validate_timeout(args.svg_timeout_seconds, name="SVG timeout")
    spec = json.loads(args.manifest.read_text())
    validate_plan(args.manifest, spec)
    plan = {
        "suite": spec["name"],
        "repositories": len(spec["repositories"]),
        "profiles": spec["profiles"],
        "scope": spec["capabilities"],
        "size_gaps": spec["coverage_gaps"],
        "execute": args.run,
        "architecture_timeout_seconds": args.architecture_timeout_seconds,
        "svg_timeout_seconds": args.svg_timeout_seconds,
    }
    print(json.dumps(plan, indent=2), flush=True)
    if not args.run:
        return 0
    root = resolve_run_root(spec, args.run_id, args.resume)
    identity = {
        "manifest_sha256": digest(args.manifest),
        "launcher_sha256": digest(Path(__file__)),
        "runtime": runtime_identity(),
        "version_provenance": version_provenance(),
        "measurement_capabilities": measurement_capabilities(),
        "native_acceleration": native_acceleration_identity(),
        "architecture_timeout_seconds": args.architecture_timeout_seconds,
        "svg_timeout_seconds": args.svg_timeout_seconds,
        "configs": {
            p: digest(args.manifest.parent / p)
            for r in spec["repositories"]
            for p in r["configs"].values()
        },
        "codira_commit": subprocess.check_output(
            [
                shutil.which("git") or "/usr/bin/git",
                "-C",
                spec["codira_root"],
                "rev-parse",
                "HEAD",
            ],
            text=True,
        ).strip(),
        "python": sys.version,
        "host": platform.platform(),
        "cpu_count": os.cpu_count(),
        "packages": {
            d.metadata["Name"]: d.version
            for d in importlib.metadata.distributions()
            if (d.metadata["Name"] or "").startswith("codira")
        },
    }
    receipt = root / "identity.json"
    if receipt.exists() and json.loads(receipt.read_text()) != identity:
        reject("resume identity differs; retain this run and choose a new run-id")
    write(receipt, identity)
    write(root / "manifest.json", spec)
    verify_revisions(spec)
    campaign = Campaign(
        args.manifest,
        root,
        args.retry_failed,
        args.architecture_timeout_seconds,
        args.svg_timeout_seconds,
    )
    campaign.command("capabilities", [campaign.codira, "caps", "--json"])
    campaign.command("plugins", [campaign.codira, "plugins", "--json"])
    all_members = []
    for profile in spec["profiles"]:
        for repo in spec["repositories"]:
            try:
                member = campaign.repository(repo, profile)
                if member:
                    all_members.append(member)
                    if spec["extended"]:
                        asyncio.run(
                            campaign.mcp(
                                profile["id"] + "/" + repo["label"] + "/mcp",
                                ["--workspace", member["workspace"]],
                                member["query"],
                            )
                        )
            except Exception as error:
                LOGGER.exception("Benchmark stage failed; retaining checkpoint")
                result = {
                    "key": profile["id"] + "/" + repo["label"] + "/exception",
                    "status": "failed",
                    "error": str(error),
                }
                campaign.results.append(result)
                write(root / "stages" / result["key"] / "result.json", result)
            finally:
                campaign.progress.omit(
                    profile["id"] + "/" + repo["label"],
                    "repository orchestration ended before this conditional stage",
                )
            write(
                root / "summary.json", {"results": campaign.results, "complete": False}
            )
    if spec["extended"]:
        primary = [
            m for m in all_members if m["profile"]["id"] == spec["profiles"][0]["id"]
        ]
        daemon = next(
            (m for m in primary if m["repo"]["label"] == spec["daemon_repository"]),
            None,
        )
        for key, operation in [
            ("family", lambda: campaign.family(primary)),
            ("daemons", lambda: campaign.daemons(daemon) if daemon else None),
        ]:
            try:
                if key == "daemons" and daemon is None:
                    reject("required daemon member did not index successfully")
                execute_extension(operation)
            except Exception as error:
                LOGGER.exception("Benchmark stage failed; retaining checkpoint")
                result = {
                    "key": key + "/exception",
                    "status": "failed",
                    "error": str(error),
                }
                campaign.results.append(result)
                write(root / "stages" / result["key"] / "result.json", result)
            finally:
                campaign.progress.omit(
                    key, "extension prerequisites unavailable or orchestration failed"
                )
            write(
                root / "summary.json", {"results": campaign.results, "complete": False}
            )
        campaign.command(
            "calibration",
            [
                campaign.codira,
                "calibrate",
                "embeddings",
                "--output",
                str(root / "calibrated.toml"),
            ],
        )
        campaign.command(
            "installer",
            [
                sys.executable,
                str(
                    Path(spec["codira_root"]) / "scripts/rehearse_installer_installs.py"
                ),
                "--wheel-dir",
                str(root / "installer-wheels"),
                "--venv-dir",
                str(root / "installer-venv"),
                "--plan-dir",
                str(root / "installer-plans"),
            ],
        )
    failures = [
        r["key"]
        for r in campaign.results
        if r["status"] not in QUERYABLE_STATUSES and r["status"] != "excluded"
    ]
    write(
        root / "summary.json",
        {
            "results": campaign.results,
            "complete": campaign_exit_status(campaign.results) == 0
            and not any(r["status"] == "excluded" for r in campaign.results),
            "execution_complete": True,
            "partial_stages": [
                r["key"] for r in campaign.results if r["status"] in PARTIAL_STATUSES
            ],
            "comparison_groups": {
                group: [
                    r["key"]
                    for r in campaign.results
                    if r.get("comparison_group") == group
                ]
                for group in ("complete_index", "partial_coverage")
            },
            "failed_stages": failures,
            "empty_stages": [
                r["key"] for r in campaign.results if r["status"] == "empty"
            ],
            "excluded_stages": [
                r for r in campaign.results if r["status"] == "excluded"
            ],
            "coverage_complete": not failures
            and not any(
                r["status"] in PARTIAL_STATUSES or r["status"] == "excluded"
                for r in campaign.results
            ),
            "memory_measurement": memory_summary(campaign.results),
            "limitations": spec["limitations"],
        },
    )
    return campaign_exit_status(campaign.results)


if __name__ == "__main__":
    raise SystemExit(main())
