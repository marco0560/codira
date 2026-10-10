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
from datetime import timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any, NoReturn

import tomlkit

from codira.runtime_identity import runtime_identity

if TYPE_CHECKING:
    from collections.abc import Callable

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
                return {
                    "status": "failed",
                    "reason": "invalid JSON envelope",
                    "timing_valid": False,
                }
        except ValueError:
            return {
                "status": "failed",
                "reason": "malformed JSON output",
                "timing_valid": False,
            }
    if operation == "index":
        outcome = classify_index(payload, exit_code)
        if outcome is not None:
            return outcome
    if payload.get("status") in {"error", "failed", "invalid"}:
        return {
            "status": "failed",
            "reason": "command reported an error",
            "timing_valid": False,
        }
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
        return {
            "status": "failed",
            "reason": "process exited unsuccessfully",
            "timing_valid": False,
        }
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
    partial = bool(
        (coverage.get("usable") and coverage.get("complete") is False)
        or coverage.get("partial")
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
    if operation == "index" and coverage and not coverage.get("usable"):
        return {
            "status": "unusable",
            "usable": False,
            "timing_valid": False,
            "index_coverage": coverage,
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
        Rendering limit per invocation, or zero for unlimited rendering.
    """

    def __init__(
        self,
        manifest: Path,
        root: Path,
        retry_failed: bool,
        architecture_timeout_seconds: float = 300,
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
            Per-render limit, or zero to disable the limit.

        Returns
        -------
        None
            The campaign is initialized without launching a workload.
        """
        self.manifest = manifest.resolve()
        self.spec = json.loads(manifest.read_text())
        self.root = root.resolve()
        self.retry_failed = retry_failed
        self.architecture_timeout_seconds = architecture_timeout_seconds
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
        """
        destination = self.root / "stages" / key
        record = destination / "result.json"
        if record.exists():
            old: dict[str, Any] = json.loads(record.read_text())
            if old["status"] in QUERYABLE_STATUSES or (
                not self.retry_failed and old["status"] != "interrupted"
            ):
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
                    if Path("/usr/bin/time").exists()
                    else argv
                )
                process = subprocess.Popen(
                    measured,
                    env=self.env,
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
                try:
                    process.wait(timeout=limit or None)
                except subprocess.TimeoutExpired:
                    timed_out = True
                    terminate_group(process)
                except KeyboardInterrupt:
                    interrupted = True
                    terminate_group(process)
            memory = re.search(
                r"Maximum resident set size \(kbytes\):\s*(\d+)",
                (attempts / f"{number}.stderr").read_text(),
            )
            samples.append(
                {
                    "seconds": time.perf_counter() - start,
                    "exit_code": process.returncode,
                    "peak_rss_kib": int(memory.group(1)) if memory else None,
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
            if timed_out or interrupted:
                samples[-1].update(
                    status="interrupted" if interrupted else "timeout",
                    reason="operator interrupted stage"
                    if interrupted
                    else "architecture rendering exceeded limit",
                    timing_valid=False,
                    timeout_seconds=limit,
                )
            if samples[-1]["status"] not in QUERYABLE_STATUSES:
                break
        result = {
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
                    )
                    if key in samples[-1]
                }
            )
            write(attempts / "result.json", result)
        write(record, result)
        self.results.append(result)
        print(key, result["status"], flush=True)
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
        result = {"key": prefix + "/queries", "status": "excluded", "reason": reason}
        write(self.root / "stages" / result["key"] / "result.json", result)
        self.results.append(result)
        print(result["key"], "excluded:", reason, flush=True)

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
        partial = bool(
            coverage.get("partial")
            or coverage.get("usable")
            and coverage.get("complete") is False
        )
        if partial:
            result["index_coverage"] = coverage
            result["comparison_group"] = "partial_coverage"
            if result["status"] in SUCCESS_STATUSES:
                result["status"] = (
                    "partial_empty" if result["status"] == "empty" else "partial"
                )
            result["timing_valid"] = False
            for sample in result.get("samples", []):
                if sample["status"] in SUCCESS_STATUSES:
                    sample["status"] = (
                        "partial_empty" if sample["status"] == "empty" else "partial"
                    )
                sample.update(
                    index_coverage=coverage,
                    timing_valid=False,
                    partial_timing_valid=sample["status"] in PARTIAL_STATUSES,
                    comparison_group="partial_coverage",
                )
            write(self.root / "stages" / result["key"] / "result.json", result)
            history = result.get("attempt_history", [])
            if history:
                write(Path(history[-1]), result)
        return result

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
        registered = self.command(
            prefix + "/workspace",
            [
                self.codira,
                "workspace",
                "add",
                name,
                "--path",
                repo["path"],
                "--state-root",
                str(state),
                "--config-file",
                str(config),
            ],
        )
        configured = self.cli(
            prefix + "/config", name, ["config", "validate", "--json"]
        )
        if registered["status"] != "passed" or configured["status"] != "passed":
            self.exclude_queries(prefix, "workspace or configuration failed")
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
        if indexed["status"] in PARTIAL_STATUSES:
            self.exclude_queries(
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
            self.exclude_queries(
                prefix + "/semantic", "embedding population did not complete"
            )

    def measure_concurrency(
        self, prefix: str, name: str, profile: dict[str, Any], indexed: dict[str, Any]
    ) -> dict[str, Any]:
        """Measure optional schedulers after complete structural indexing.

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
            indexed["status"] in SUCCESS_STATUSES
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
                if result["status"] not in SUCCESS_STATUSES:
                    return result

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
            if previous["status"] in QUERYABLE_STATUSES or (
                not self.retry_failed and previous["status"] != "interrupted"
            ):
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
            env=self.env,
        )
        responses: list[dict[str, Any]] = []
        result: dict[str, Any]
        symbol = None
        workspace = args[1] if "--workspace" in args else None
        coverage = self.member_coverage.get(workspace or "", {})
        semantic_ready = self.embedding_ready.get(workspace or "", False)
        start = time.perf_counter()
        try:
            async with (
                stdio_client(server) as (read, output),
                ClientSession(
                    read, output, read_timeout_seconds=timedelta(seconds=3600)
                ) as session,
            ):
                await session.initialize()
                available = {tool.name for tool in (await session.list_tools()).tools}
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
                            {"tool": tool, "excluded": "no discovered symbol identity"}
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
                "status": "failed"
                if any(x.get("is_error") for x in responses)
                else "partial"
                if coverage.get("partial")
                or any(
                    x.get("response", {}).get("result", {}).get("status") == "partial"
                    for x in responses
                )
                else "passed",
                "index_coverage": coverage,
                "comparison_group": "partial_coverage"
                if coverage.get("partial")
                or any(
                    x.get("response", {}).get("result", {}).get("status") == "partial"
                    for x in responses
                )
                else "complete_index",
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
        result["attempt_history"] = [
            str(path / "result.json") for path in sorted(destination.glob("attempt-*"))
        ]
        write(attempts / "result.json", result)
        write(record, result)
        self.results.append(result)
        print(key, result["status"], flush=True)
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
            if previous["status"] in QUERYABLE_STATUSES or (
                not self.retry_failed and previous["status"] != "interrupted"
            ):
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
                env=self.env,
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
                            status="partial" if state["partial"] else "passed",
                            comparison_group="partial_coverage"
                            if state["partial"]
                            else "complete_index",
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


def validate_timeout(value: float) -> None:
    """Reject invalid architecture rendering limits.

    Parameters
    ----------
    value : float
        Seconds per invocation, or zero for unlimited rendering.

    Returns
    -------
    None
        Invalid limits raise a diagnostic exception.
    """
    if value < 0 or not value < float("inf"):
        reject("architecture timeout must be finite and nonnegative")


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
        help="Architecture rendering limit per invocation; default 300 seconds, 0 disables",
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
    spec = json.loads(args.manifest.read_text())
    validate_plan(args.manifest, spec)
    plan = {
        "suite": spec["name"],
        "repositories": len(spec["repositories"]),
        "profiles": spec["profiles"],
        "scope": spec["capabilities"],
        "size_gaps": spec["coverage_gaps"],
        "execute": args.run,
    }
    print(json.dumps(plan, indent=2), flush=True)
    if not args.run:
        return 0
    root = resolve_run_root(spec, args.run_id, args.resume)
    identity = {
        "manifest_sha256": digest(args.manifest),
        "launcher_sha256": digest(Path(__file__)),
        "runtime": runtime_identity(),
        "architecture_timeout_seconds": args.architecture_timeout_seconds,
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
        args.manifest, root, args.retry_failed, args.architecture_timeout_seconds
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
            "limitations": spec["limitations"],
        },
    )
    return campaign_exit_status(campaign.results)


if __name__ == "__main__":
    raise SystemExit(main())
