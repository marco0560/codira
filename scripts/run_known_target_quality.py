"""Run resumable, automatically scored known-target retrieval campaigns.

Parameters
----------
None

Returns
-------
None
"""

from __future__ import annotations

import argparse
import contextlib
import fcntl
import io
import json
import math
import os
import platform
import re
import signal
import sqlite3
import subprocess
import sys
import tarfile
import time
from dataclasses import asdict, dataclass, field as dataclass_field, replace
from pathlib import Path
from statistics import mean, median
from typing import TYPE_CHECKING, cast

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from codira.config import CONFIG_VERSION
from scripts.build_known_target_dataset import git_bytes, repository_candidates
from scripts.known_target_quality import (
    Case,
    Target,
    canonical_json,
    case_payload,
    digest_bytes,
    invalid,
    load_cases,
    ranked_locations,
    score_ranking,
)
from scripts.run_final_embedding_model_campaign import (
    ModelEntry,
    read_models,
    read_repositories,
    render_model_config,
)
from scripts.scriptlib import resolve_codira, safe_slug

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence


@dataclass
class RunProgress:
    """Show operation progress and a heartbeat without exposing query text.

    Parameters
    ----------
    total : int
        Planned indexes, primary queries and context probes.
    enabled : bool, optional
        Whether to write progress to stderr.

    Returns
    -------
    None
    """

    total: int
    enabled: bool = True
    completed: int = 0
    reused: int = 0
    active: str = "preparing"
    started: float = dataclass_field(default_factory=time.monotonic)
    last_update: float = 0

    def render(self, *, force: bool = False) -> None:
        """Refresh the terminal bar or append a bounded-frequency log line.

        Parameters
        ----------
        force : bool, optional
            Emit an immediate operation transition.

        Returns
        -------
        None
        """
        now = time.monotonic()
        tty = sys.stderr.isatty()
        if not self.enabled or (
            not force and now - self.last_update < (1 if tty else 15)
        ):
            return
        self.last_update = now
        fraction = self.completed / self.total if self.total else 1
        filled = int(fraction * 20)
        bar = "#" * filled + "-" * (20 - filled)
        message = (
            f"[{bar}] {fraction:6.1%} {self.completed}/{self.total} "
            f"elapsed {now - self.started:.0f}s reused {self.reused} | {self.active}"
        )
        print(
            "\r" + message + "\033[K" if tty else message,
            end="" if tty else "\n",
            file=sys.stderr,
            flush=True,
        )

    def advance(self, *, reused: bool = False) -> None:
        """Record a finished or reused operation and show its completion.

        Parameters
        ----------
        reused : bool, optional
            Whether verified checkpoint evidence avoided execution.

        Returns
        -------
        None
        """
        self.completed += 1
        self.reused += int(reused)
        self.render(force=True)


def validate_index_inventory(state: Path) -> dict[str, int]:
    """Verify the pinned SQLite search bindings against structural metadata.

    Parameters
    ----------
    state : pathlib.Path
        Isolated model/repository output directory.

    Returns
    -------
    dict[str, int]
        Expected and searchable binding counts.

    Raises
    ------
    ValueError
        State is missing, ambiguous or has incomplete search bindings.
    """
    try:
        with (
            sqlite3.connect(
                f"file:{(state / '.codira/index.db').resolve()}?mode=ro", uri=True
            ) as graph,
            sqlite3.connect(
                f"file:{(state / '.codira/embeddings.db').resolve()}?mode=ro", uri=True
            ) as vectors,
        ):
            expected = set(
                graph.execute(
                    "SELECT 'symbol', s.stable_id, e.content_hash FROM embeddings e "
                    "JOIN symbol_index s ON e.object_id=s.id WHERE e.object_type='symbol' "
                    "UNION ALL SELECT 'documentation', d.stable_id, e.content_hash "
                    "FROM embeddings e JOIN documentation_artifacts d ON e.object_id=d.id "
                    "WHERE e.object_type='documentation'"
                ).fetchall()
            )
            if vectors.execute("SELECT count(*) FROM vector_sets").fetchone()[0] != 1:
                invalid("Index must contain one selected vector set")
            actual = set(
                vectors.execute(
                    "SELECT object_type, stable_id, content_hash FROM vector_bindings"
                ).fetchall()
            )
            payloads = {
                row[0]
                for row in vectors.execute("SELECT content_hash FROM vector_payloads")
            }
        if (
            not expected
            or actual != expected
            or any(row[2] not in payloads for row in actual)
        ):
            invalid(
                f"Incomplete searchable vector inventory: {len(actual)}/{len(expected)} bindings"
            )
        return {"expected_bindings": len(expected), "searchable_bindings": len(actual)}
    except sqlite3.Error as exc:
        message = "Unreadable SQLite vector inventory"
        raise ValueError(message) from exc


@contextlib.contextmanager
def campaign_lock(root: Path) -> Iterator[None]:
    """Reject concurrent execution or rescoring of one campaign identity.

    Parameters
    ----------
    root : pathlib.Path
        Campaign output directory.

    Yields
    ------
    collections.abc.Iterator[None]
        Context holding an exclusive advisory lock.

    Raises
    ------
    BlockingIOError
        Another process is using the same campaign.
    """
    root.parent.mkdir(parents=True, exist_ok=True)
    with (root.parent / f".{root.name}.lock").open("a") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield


def write_json(path: Path, value: object) -> None:
    """Atomically publish derived state with a sibling staging file.

    Parameters
    ----------
    path : pathlib.Path
        Destination.
    value : object
        JSON-compatible data.

    Returns
    -------
    None
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    stage = path.with_suffix(path.suffix + ".pending")
    stage.write_text(canonical_json(value) + "\n", encoding="utf-8")
    stage.replace(path)


def process_tree_rss(pid: int) -> int | None:
    """Sample Linux resident memory for a process and its live descendants.

    Parameters
    ----------
    pid : int
        Root process identifier.

    Returns
    -------
    int | None
        Sum of sampled resident KiB, or None when /proc is unavailable.
    """
    if not Path("/proc").is_dir():
        return None
    total = 0
    pending = [pid]
    seen: set[int] = set()
    while pending:
        current = pending.pop()
        if current in seen:
            continue
        seen.add(current)
        try:
            status = Path(f"/proc/{current}/status").read_text()
            for line in status.splitlines():
                if line.startswith("VmRSS:"):
                    total += int(line.split()[1])
            children = Path(f"/proc/{current}/task/{current}/children").read_text()
            pending.extend(int(child) for child in children.split())
        except (OSError, ValueError):
            continue
    return total


def measure(
    command: Sequence[str],
    root: Path,
    evidence: Path,
    timeout: float,
    progress: RunProgress | None = None,
) -> dict[str, object]:
    """Retain exact command output and sampled resource measurements.

    Parameters
    ----------
    command : collections.abc.Sequence[str]
        Argument vector, never a shell command.
    root : pathlib.Path
        Working directory.
    evidence : pathlib.Path
        New attempt directory.
    timeout : float
        Maximum command duration in seconds.
    progress : RunProgress | None, optional
        Operation heartbeat reporter.

    Returns
    -------
    dict[str, object]
        Exit status, wall time, sampled RSS and raw-output digests.
    """
    evidence.mkdir(parents=True, exist_ok=False)
    write_json(
        evidence / "command.json",
        {"command": list(command), "timeout_seconds": timeout},
    )
    started = time.monotonic()
    peak: int | None = None
    timed_out = False
    with (
        (evidence / "stdout").open("wb") as stdout,
        (evidence / "stderr").open("wb") as stderr,
    ):
        process = subprocess.Popen(
            command, cwd=root, stdout=stdout, stderr=stderr, start_new_session=True
        )
        while process.poll() is None:
            if progress is not None:
                progress.render()
            rss = process_tree_rss(process.pid)
            if rss is not None:
                peak = max(peak or 0, rss)
            if time.monotonic() - started > timeout:
                timed_out = True
                os.killpg(process.pid, signal.SIGTERM)
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait()
                break
            time.sleep(0.05)
        status = process.wait()
    result: dict[str, object] = {
        "command": list(command),
        "exit_code": status,
        "timed_out": timed_out,
        "elapsed_seconds": time.monotonic() - started,
        "sampled_peak_rss_kib": peak,
        "rss_method": "Linux /proc process-tree sum sampled every 50ms; lower bound on peak",
        "stdout_sha256": digest_bytes((evidence / "stdout").read_bytes()),
        "stderr_sha256": digest_bytes((evidence / "stderr").read_bytes()),
        "evidence": str(evidence),
    }
    write_json(evidence / "measurement.json", result)
    return result


def validate_sources(cases: tuple[Case, ...], repositories: dict[str, Path]) -> None:
    """Regenerate source witnesses before accepting automatic labels.

    Parameters
    ----------
    cases : tuple[Case, ...]
        Dataset controls.
    repositories : dict[str, pathlib.Path]
        Local Git locators.

    Returns
    -------
    None

    Raises
    ------
    ValueError
        Repositories, commits, labels, queries or evidence do not match source.
    """
    for repo in sorted({case.repo for case in cases}):
        if repo not in repositories:
            invalid(f"Unknown repository: {repo}")
        commits = {case.commit for case in cases if case.repo == repo}
        if len(commits) != 1:
            invalid(f"Mixed revisions for {repo}")
        candidates = {
            case.id: case_payload(case)
            for case in repository_candidates(
                repositories[repo],
                repo,
                next(iter(commits)),
            )
        }
        for case in cases:
            if case.repo == repo and candidates.get(case.id) != case_payload(case):
                invalid(f"Case is not source-verifiable: {case.id}")


def verify_snapshot(snapshot: Path, archive: bytes) -> None:
    """Check every frozen file and link against the exact Git archive.

    Parameters
    ----------
    snapshot : pathlib.Path
        Extracted immutable source tree.
    archive : bytes
        Original Git archive.

    Returns
    -------
    None

    Raises
    ------
    ValueError
        Any archived location was changed or an extra file was introduced.
    """
    expected: set[str] = set()
    with tarfile.open(fileobj=io.BytesIO(archive)) as tree:
        for member in tree.getmembers():
            if member.isdir():
                continue
            expected.add(member.name)
            path = snapshot / member.name
            if member.issym():
                if not path.is_symlink() or str(path.readlink()) != member.linkname:
                    invalid("Frozen source link was modified")
            elif member.isfile():
                stream = tree.extractfile(member)
                if (
                    stream is None
                    or path.is_symlink()
                    or path.read_bytes() != stream.read()
                ):
                    invalid("Frozen source was modified")
            else:
                invalid("Unsupported frozen source entry")
    actual = {
        path.relative_to(snapshot).as_posix()
        for path in snapshot.rglob("*")
        if ".git" not in path.relative_to(snapshot).parts
        and (path.is_symlink() or path.is_file())
    }
    if actual != expected:
        invalid("Frozen source file inventory was modified")


def operation_payload(result: dict[str, object]) -> dict[str, object]:
    """Validate successful raw evidence before interpreting a response.

    Parameters
    ----------
    result : dict[str, object]
        Retained subprocess measurement.

    Returns
    -------
    dict[str, object]
        Exact parsed stdout object.

    Raises
    ------
    ValueError
        The command, digest or response is invalid.
    """
    if result.get("exit_code") != 0 or result.get("timed_out"):
        invalid("Command failed or timed out")
    evidence = Path(str(result["evidence"]))
    for stream in ("stdout", "stderr"):
        if digest_bytes((evidence / stream).read_bytes()) != result[f"{stream}_sha256"]:
            invalid("Operation evidence drift")
    payload = json.loads((evidence / "stdout").read_text())
    if not isinstance(payload, dict):
        invalid("Invalid operation response")
    body = payload.get("result", payload)
    if not isinstance(body, dict) or body.get("status") not in {"ok", "no_matches"}:
        invalid("Invalid operation response")
    return cast("dict[str, object]", payload)


def render_known_target_config(model: ModelEntry) -> str:
    """Adapt the historical renderer to current fixed retrieval controls.

    Parameters
    ----------
    model : scripts.run_final_embedding_model_campaign.ModelEntry
        Model with resolved local asset paths.

    Returns
    -------
    str
        SQLite configuration with exact search, fixed text limits and no daemons.
    """
    config = (
        render_model_config(model, "sqlite")
        .replace(
            "config_version = 1",
            f"config_version = {CONFIG_VERSION}",
            1,
        )
        .replace(
            'vector_store = "sqlite"',
            'vector_store = "sqlite"\nsimilarity_index = "exact"',
            1,
        )
    )
    config = re.sub(r"(?m)^max_text_chars = \d+$", "max_text_chars = 4000", config)
    return config + "\n[daemon]\nenabled = false\n[query_daemon]\nenabled = false\n"


def campaign_configs(args: argparse.Namespace) -> tuple[dict[str, str], dict[str, str]]:
    """Resolve selected models and fingerprint available local model assets.

    Parameters
    ----------
    args : argparse.Namespace
        Model selection controls.

    Returns
    -------
    tuple[dict[str, str], dict[str, str]]
        Rendered fixed-chunk configurations and model asset digests.

    Raises
    ------
    ValueError
        Models are unknown, ambiguous, or reference missing local assets.
    """
    models = read_models(args.model_manifest)
    requested = set(cast("list[str]", args.model_id))
    available = {model.id for model in models}
    if len({safe_slug(model.id) for model in models}) != len(models):
        invalid("Model IDs collide after path normalization")
    if requested - available or len(available) != len(models):
        invalid("Unknown or duplicate model IDs")
    model_evidence: dict[str, str] = {}
    normalized_models = []
    for model in models:
        if requested and model.id not in requested:
            continue
        config = dict(model.config)
        for key in ("model_path", "tokenizer_path"):
            value = config.get(key)
            if value:
                asset = Path(str(value)).resolve()
                if not asset.is_file():
                    invalid(f"Missing model asset: {model.id} {key}")
                model_evidence[f"{model.id}:{key}"] = digest_bytes(asset.read_bytes())
                config[key] = str(asset)
        normalized_models.append(replace(model, config=config))
    configs = {
        model.id: render_known_target_config(model) for model in normalized_models
    }
    if not configs:
        invalid("No models selected")
    return configs, model_evidence


def prepare_campaign(
    args: argparse.Namespace,
) -> tuple[dict[str, object], tuple[Case, ...], str]:
    """Bind a run to datasets, model configurations, source and runtime.

    Parameters
    ----------
    args : argparse.Namespace
        Parsed execution controls.

    Returns
    -------
    tuple[dict[str, object], tuple[Case, ...], str]
        Immutable identity, cases, and Codira executable.

    Raises
    ------
    ValueError
        Models are unknown or controls differ from an existing campaign.
    """
    cases = load_cases(args.dataset)
    repositories = {
        repo.label: repo.path for repo in read_repositories(args.repo_manifest)
    }
    validate_sources(cases, repositories)
    configs, model_evidence = campaign_configs(args)
    if args.baseline and args.baseline not in configs:
        invalid("Baseline must be one of the selected model IDs")
    if len({safe_slug(case.repo) for case in cases}) != len(
        {case.repo for case in cases}
    ):
        invalid("Repository IDs collide after path normalization")
    codira = resolve_codira()
    runtime = subprocess.run(
        [codira, "caps", "--json"], capture_output=True, check=True
    ).stdout
    identity: dict[str, object] = {
        "schema_version": "known-target-campaign-v1",
        "dataset_sha256": digest_bytes(args.dataset.read_bytes()),
        "model_manifest_sha256": digest_bytes(args.model_manifest.read_bytes()),
        "cases": [case_payload(case) for case in cases],
        "configs": configs,
        "model_assets_sha256": model_evidence,
        "codira_executable_sha256": digest_bytes(Path(codira).read_bytes()),
        "backend": "sqlite",
        "max_text_chars": 4000,
        "cutoffs": args.k,
        "query_timeout": args.query_timeout,
        "index_timeout": args.index_timeout,
        "harness_sha256": {
            name: digest_bytes((Path(__file__).parent / name).read_bytes())
            for name in (
                "known_target_quality.py",
                "build_known_target_dataset.py",
                "run_known_target_quality.py",
            )
        },
        "runtime_sha256": digest_bytes(runtime),
        "runtime": json.loads(runtime),
        "python": sys.version,
        "platform": platform.platform(),
        "machine": platform.machine(),
        "cpu_count": os.cpu_count(),
        "memory_budget_mib": args.memory_budget_mib,
        "max_index_seconds": args.max_index_seconds,
        "baseline": args.baseline,
        "codira_executable": codira,
    }
    args.output = args.output.resolve()
    identity_path = args.output / "campaign.json"
    if args.resume:
        if not identity_path.is_file() or canonical_json(
            json.loads(identity_path.read_text())
        ) != canonical_json(identity):
            invalid("Resume controls or runtime differ; create a new run identity")
    else:
        args.output.mkdir(parents=True, exist_ok=False)
        write_json(identity_path, identity)
        (args.output / "cases.jsonl").write_bytes(args.dataset.read_bytes())
    for repo in sorted({case.repo for case in cases}):
        snapshot = args.output / "repositories" / safe_slug(repo)
        receipt = args.output / "repositories" / f"{safe_slug(repo)}.json"
        commit = next(case.commit for case in cases if case.repo == repo)
        archive = git_bytes(repositories[repo], "archive", "--format=tar", commit)
        expected = {"commit": commit, "archive_sha256": digest_bytes(archive)}
        if receipt.is_file():
            if json.loads(receipt.read_text()) != expected:
                invalid("Frozen source archive differs")
            verify_snapshot(snapshot, archive)
            git_bytes(snapshot, "init")
            git_bytes(snapshot, "add", "--force", "--all")
            continue
        snapshot.mkdir(parents=True, exist_ok=True)
        with tarfile.open(fileobj=io.BytesIO(archive)) as tree:
            tree.extractall(snapshot, filter="data")
        verify_snapshot(snapshot, archive)
        git_bytes(snapshot, "init")
        git_bytes(snapshot, "add", "--force", "--all")
        write_json(receipt, expected)
    for model, config in configs.items():
        config_path = args.output / "configs" / f"{safe_slug(model)}.toml"
        config_path.parent.mkdir(parents=True, exist_ok=True)
        if config_path.exists() and config_path.read_text() != config:
            invalid("Frozen model config differs")
        config_path.write_text(config, encoding="utf-8")
    return identity, cases, codira


def execute_operation(
    command: Sequence[str],
    root: Path,
    operation: Path,
    timeout: float,
    progress: RunProgress | None = None,
) -> dict[str, object]:
    """Reuse a verified success or create a new retained attempt.

    Parameters
    ----------
    command : collections.abc.Sequence[str]
        Effective command.
    root : pathlib.Path
        Command working directory.
    operation : pathlib.Path
        Checkpoint directory.
    timeout : float
        Command timeout.
    progress : RunProgress | None, optional
        Reporter updated for execution and checkpoint reuse.

    Returns
    -------
    dict[str, object]
        Operation measurement; prior failures are retained on retry.

    Raises
    ------
    ValueError
        A saved successful operation has changed evidence or command controls.
    """
    checkpoint = operation / "result.json"
    if checkpoint.is_file():
        saved = json.loads(checkpoint.read_text())
        if saved.get("command") != list(command):
            invalid("Checkpoint command drift")
        if (
            saved.get("exit_code") == 0
            and not saved.get("timed_out")
            and saved.get("valid_response", True)
        ):
            evidence = Path(saved["evidence"])
            for stream in ("stdout", "stderr"):
                if (
                    digest_bytes((evidence / stream).read_bytes())
                    != saved[f"{stream}_sha256"]
                ):
                    invalid("Checkpoint evidence drift")
            if progress is not None:
                progress.advance(reused=True)
            return cast("dict[str, object]", saved)
    operation.mkdir(parents=True, exist_ok=True)
    number = len(tuple(operation.glob("attempt-*"))) + 1
    result = measure(
        command, root, operation / f"attempt-{number:04d}", timeout, progress
    )
    write_json(checkpoint, result)
    if progress is not None:
        progress.advance()
    return result


def collect_rankings(
    args: argparse.Namespace,
    identity: dict[str, object],
    cases: tuple[Case, ...],
    codira: str,
) -> int:
    """Execute model/repository groups and save every case result.

    Parameters
    ----------
    args : argparse.Namespace
        Execution controls.
    identity : dict[str, object]
        Bound campaign identity.
    cases : tuple[Case, ...]
        Validated case bank.
    codira : str
        Host executable.

    Returns
    -------
    int
        One if any index, query or response fails; zero otherwise.
    """
    status = 0
    configs = cast("dict[str, str]", identity["configs"])
    progress = RunProgress(
        len(configs) * (len({case.repo for case in cases}) + 2 * len(cases)),
        enabled=not args.quiet_progress,
    )
    for model in sorted(configs):
        for repo in sorted({case.repo for case in cases}):
            snapshot = args.output / "repositories" / safe_slug(repo)
            group = args.output / "operations" / safe_slug(model) / safe_slug(repo)
            common = [
                "--path",
                str(snapshot),
                "--output-dir",
                str(group / "index-state"),
                "--config-file",
                str(args.output / "configs" / f"{safe_slug(model)}.toml"),
            ]
            progress.active = f"{model}/{repo} | indexing"
            progress.render(force=True)
            index = execute_operation(
                [codira, "index", "--full", "--json", *common],
                args.output,
                group / "index",
                args.index_timeout,
                progress,
            )
            try:
                index_payload = operation_payload(index)
                index_summary = index_payload.get("summary")
                if (
                    index_payload.get("command") != "index"
                    or not isinstance(index_summary, dict)
                    or index_summary.get("failed") != 0
                    or index_summary.get("embedding_complete") is not True
                    or index_summary.get("embeddings_pending") != 0
                    or int(index_summary.get("indexed", 0))
                    + int(index_summary.get("reused", 0))
                    == 0
                ):
                    invalid("Index did not complete successfully")
                if not (group / "index-state").is_dir():
                    invalid("Index state is missing")
                index["inventory"] = validate_index_inventory(group / "index-state")
                index["valid_response"] = True
            except (ValueError, TypeError, AttributeError) as exc:
                index["validation_error"] = str(exc)
                index["valid_response"] = False
                status = 1
            write_json(group / "index" / "result.json", index)
            if not index["valid_response"]:
                progress.active = (
                    f"{model}/{repo} | index rejected: {index.get('validation_error')}"
                )
                progress.render(force=True)
                continue
            for case in cases:
                if case.repo != repo:
                    continue
                operation = group / case.id
                progress.active = f"{model}/{repo} | {case.channel} {case.intent}"
                progress.render(force=True)
                result = execute_operation(
                    [
                        codira,
                        case.channel,
                        case.query,
                        "--json",
                        "--limit",
                        str(max(args.k)),
                        *common,
                    ],
                    args.output,
                    operation,
                    args.query_timeout,
                    progress,
                )
                row = {
                    **result,
                    "model": model,
                    "repo": repo,
                    "case_id": case.id,
                    "intent": case.intent,
                    "channel": case.channel,
                    "ranking": [],
                    "error": None,
                }
                try:
                    payload = operation_payload(result)
                    if payload.get("command") != case.channel:
                        invalid("Wrong retrieval command in response")
                    row["ranking"] = [
                        asdict(target) for target in ranked_locations(payload, snapshot)
                    ]
                except (ValueError, TypeError, AttributeError) as exc:
                    row["error"] = str(exc)
                    status = 1
                result["valid_response"] = row["error"] is None
                write_json(operation / "result.json", result)
                write_json(operation / "ranking.json", row)
                progress.active = f"{model}/{repo} | ctx {case.intent}"
                progress.render(force=True)
                ctx = execute_operation(
                    [
                        codira,
                        "ctx",
                        case.query,
                        "--json",
                        "--max-results",
                        str(max(args.k)),
                        *common,
                    ],
                    args.output,
                    operation / "ctx",
                    args.query_timeout,
                    progress,
                )
                try:
                    ranked_locations(operation_payload(ctx), snapshot)
                    ctx["valid_response"] = True
                except (ValueError, TypeError, AttributeError):
                    ctx["valid_response"] = False
                    status = 1
                write_json(operation / "ctx" / "result.json", ctx)
    progress.active = "finished with failures" if status else "finished"
    progress.render(force=True)
    if progress.enabled and sys.stderr.isatty():
        print(file=sys.stderr, flush=True)
    return status


def compare_models(
    models: dict[str, dict[str, object]], identity: dict[str, object]
) -> None:
    """Attach quality-versus-cost diagnostics to automatic model summaries.

    Parameters
    ----------
    models : dict[str, dict[str, object]]
        Model summaries updated in place.
    identity : dict[str, object]
        Bound baseline and optional resource budgets.

    Returns
    -------
    None
        No installed model defaults are changed.
    """
    baseline_name = identity.get("baseline")
    if not baseline_name:
        for result in models.values():
            result["decision_reason"] = "No baseline selected"
        return
    baseline = models[str(baseline_name)]
    base_metrics = cast("dict[str, dict[str, float]]", baseline["macro"])
    base_latency = cast("dict[str, float | None]", baseline["median_latency_seconds"])
    for model, result in models.items():
        metrics = cast("dict[str, dict[str, float]]", result["macro"])
        latency = cast("dict[str, float | None]", result["median_latency_seconds"])
        gain_recall = metrics["5"]["recall"] - base_metrics["5"]["recall"]
        gain_mrr = metrics["10"]["mrr"] - base_metrics["10"]["mrr"]
        ratios: dict[str, float | None] = {}
        for channel in ("emb", "ctx"):
            base_value = base_latency.get(channel)
            value = latency.get(channel)
            ratios[channel] = (
                value / base_value if value is not None and base_value else None
            )
        result["comparison"] = {
            "baseline": baseline_name,
            "macro_recall_at_5_delta": gain_recall,
            "macro_mrr_at_10_delta": gain_mrr,
            "median_latency_ratios": ratios,
            "material_known_target_gain": gain_recall >= 0.05 or gain_mrr >= 0.05,
        }
        if model == baseline_name:
            reason = "Reference model; installed defaults are unchanged"
        elif (
            result["failures"]
            or result["ctx_failures"]
            or baseline["failures"]
            or baseline["ctx_failures"]
        ):
            reason = "Incomplete paired coverage"
        elif gain_recall < 0.05 and gain_mrr < 0.05:
            result["decision"] = "rejected"
            reason = "No material known-target gain at the declared thresholds"
        else:
            result["decision"] = "quality_profile_candidate"
            reason = "Known-target gain merits further evaluation; semantic usefulness and hard peak memory compliance remain unproven"
        result["decision_reason"] = reason
        memory_budget = identity.get("memory_budget_mib")
        rss = result["sampled_peak_rss_kib"]
        index_budget = identity.get("max_index_seconds")
        result["cost_gates"] = {
            "latency_within_1_25x": all(
                value is not None and value <= 1.25 for value in ratios.values()
            ),
            "sampled_memory_exceeds_budget": float(cast("int", rss))
            > float(cast("float", memory_budget)) * 1024
            if rss is not None and memory_budget is not None
            else None,
            "index_within_budget": float(cast("float", result["index_seconds"]))
            <= float(cast("float", index_budget))
            if index_budget is not None
            else None,
            "hard_peak_memory_compliance": "unverified: RSS is sampled",
        }


def summarize_run(root: Path) -> dict[str, object]:
    """Rescore retained rankings and account for every planned slot.

    Parameters
    ----------
    root : pathlib.Path
        Existing campaign directory.

    Returns
    -------
    dict[str, object]
        Per-case, per-repository, per-intent, macro and micro results.
    """
    identity = json.loads((root / "campaign.json").read_text())
    cases = load_cases(root / "cases.jsonl")
    if digest_bytes((root / "cases.jsonl").read_bytes()) != identity["dataset_sha256"]:
        invalid("Retained dataset digest differs")
    cutoffs = identity["cutoffs"]
    models: dict[str, dict[str, object]] = {}
    for model in sorted(identity["configs"]):
        records: list[dict[str, object]] = []
        index_cost = 0.0
        rss_values: list[int] = []
        for repo in sorted({case.repo for case in cases}):
            index_file = (
                root
                / "operations"
                / safe_slug(model)
                / safe_slug(repo)
                / "index"
                / "result.json"
            )
            if index_file.is_file():
                index = json.loads(index_file.read_text())
                index_cost += float(index["elapsed_seconds"])
                if isinstance(index["sampled_peak_rss_kib"], int):
                    rss_values.append(index["sampled_peak_rss_kib"])
        for case in cases:
            ranking_file = (
                root
                / "operations"
                / safe_slug(model)
                / safe_slug(case.repo)
                / case.id
                / "ranking.json"
            )
            raw = (
                json.loads(ranking_file.read_text())
                if ranking_file.is_file()
                else {"error": "missing"}
            )
            ranking: tuple[Target, ...] = ()
            if raw.get("error") is None:
                ranking = ranked_locations(
                    operation_payload(raw), root / "repositories" / safe_slug(case.repo)
                )
                if [asdict(target) for target in ranking] != raw.get("ranking"):
                    invalid("Derived ranking differs from raw evidence")
            ctx_file = ranking_file.parent / "ctx" / "result.json"
            ctx = json.loads(ctx_file.read_text()) if ctx_file.is_file() else {}
            ctx_ok = ctx.get("valid_response", False)
            if ctx_ok:
                operation_payload(ctx)
            scores = {str(k): score_ranking(case, ranking, k) for k in cutoffs}
            if isinstance(raw.get("sampled_peak_rss_kib"), int):
                rss_values.append(int(raw["sampled_peak_rss_kib"]))
            records.append(
                {
                    "case_id": case.id,
                    "repo": case.repo,
                    "intent": case.intent,
                    "channel": case.channel,
                    "error": raw.get("error"),
                    "scores": scores,
                    "elapsed_seconds": raw.get("elapsed_seconds"),
                    "empty": not ranking,
                    "ctx_elapsed_seconds": ctx.get("elapsed_seconds")
                    if ctx_ok
                    else None,
                    "ctx_error": not ctx_ok,
                }
            )
        grouped: dict[str, dict[str, dict[str, float]]] = {}
        for field in ("repo", "intent"):
            for value in sorted({str(record[field]) for record in records}):
                group_records = [record for record in records if record[field] == value]
                grouped[f"{field}:{value}"] = average_scores(group_records, cutoffs)
        per_repo = [
            scores for key, scores in grouped.items() if key.startswith("repo:")
        ]
        macro = {
            str(k): {
                metric: mean(score[str(k)][metric] for score in per_repo)
                for metric in ("hit", "recall", "mrr")
            }
            for k in cutoffs
        }
        timings: dict[str, float | None] = {}
        for channel in ("emb", "docs"):
            values = [
                float(cast("float", record["elapsed_seconds"]))
                for record in records
                if record["channel"] == channel and record["error"] is None
            ]
            timings[channel] = median(values) if values else None
        ctx_times = [
            float(cast("float", record["ctx_elapsed_seconds"]))
            for record in records
            if record["ctx_elapsed_seconds"] is not None
        ]
        timings["ctx"] = median(ctx_times) if ctx_times else None
        models[model] = {
            "macro": macro,
            "micro": average_scores(records, cutoffs),
            "groups": grouped,
            "cases": records,
            "planned_cases": len(cases),
            "failures": sum(record["error"] is not None for record in records),
            "ctx_failures": sum(bool(record["ctx_error"]) for record in records),
            "empty_rankings": sum(bool(record["empty"]) for record in records),
            "median_latency_seconds": timings,
            "index_seconds": index_cost,
            "sampled_peak_rss_kib": max(rss_values) if rss_values else None,
            "decision": "needs_more_data",
        }
    compare_models(models, identity)
    return {
        "schema_version": "known-target-summary-v1",
        "identity": identity,
        "models": models,
        "interpretation": "Known-target retrieval only; labels are non-exhaustive. No manual or LLM grading.",
        "rss_limit": "Sampled /proc process-tree RSS is a lower bound, not proof of compliance with a hard peak limit.",
    }


def average_scores(
    records: list[dict[str, object]], cutoffs: list[int]
) -> dict[str, dict[str, float]]:
    """Average each query metric, retaining failed and missing slots as zero.

    Parameters
    ----------
    records : list[dict[str, object]]
        Case records.
    cutoffs : list[int]
        Retrieval cutoffs.

    Returns
    -------
    dict[str, dict[str, float]]
        Equal-query metric averages.
    """
    return {
        str(k): {
            metric: mean(
                cast("dict[str, dict[str, float]]", row["scores"])[str(k)][metric]
                for row in records
            )
            for metric in ("hit", "recall", "mrr")
        }
        for k in cutoffs
    }


def write_reports(root: Path) -> None:
    """Write deterministic derived reports without rerunning retrieval.

    Parameters
    ----------
    root : pathlib.Path
        Campaign directory.

    Returns
    -------
    None
    """
    summary = summarize_run(root)
    write_json(root / "quality-summary.json", summary)
    lines = [
        "# Automatic known-target retrieval quality",
        "",
        str(summary["interpretation"]),
        "",
        str(summary["rss_limit"]),
        "",
        "Failures and missing slots remain in metric denominators.",
        "",
        "| Model | Group | K | Hit@K | Known Recall@K | MRR@K |",
        "| --- | --- | ---: | ---: | ---: | ---: |",
    ]
    models = cast("dict[str, dict[str, object]]", summary["models"])
    for model, result in models.items():
        groups = {
            "macro": result["macro"],
            "micro": result["micro"],
            **cast("dict[str, object]", result["groups"]),
        }
        for group, metrics in groups.items():
            for k, scores in cast("dict[str, dict[str, float]]", metrics).items():
                lines.append(
                    f"| {model} | {group} | {k} | {scores['hit']:.4f} | {scores['recall']:.4f} | {scores['mrr']:.4f} |"
                )
        lines.extend(
            [
                "",
                f"{model}: {result['failures']} failures; {result['empty_rankings']} empty rankings; "
                f"index wall time {result['index_seconds']}s; median query times {result['median_latency_seconds']}; "
                f"sampled peak RSS {result['sampled_peak_rss_kib']} KiB; decision {result['decision']}.",
                "",
            ]
        )
        lines.extend(
            [
                f"Decision rationale: {result.get('decision_reason')}",
                f"Comparison: {result.get('comparison')}",
                f"Cost gates: {result.get('cost_gates')}",
                "",
            ]
        )
    (root / "quality-summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    """Execute or rescore a known-target campaign.

    Parameters
    ----------
    argv : list[str] | None, optional
        CLI arguments.

    Returns
    -------
    int
        Nonzero if any planned operation fails.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path)
    parser.add_argument("--repo-manifest", type=Path)
    parser.add_argument(
        "--model-manifest",
        type=Path,
        default=Path("benchmarks/embedding/model-candidates.json"),
    )
    parser.add_argument("--model-id", action="append", default=[])
    parser.add_argument("--baseline")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--k", type=int, nargs="+", default=[1, 5, 10])
    parser.add_argument("--query-timeout", type=float, default=900)
    parser.add_argument("--index-timeout", type=float, default=3600)
    parser.add_argument("--memory-budget-mib", type=float)
    parser.add_argument("--max-index-seconds", type=float)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--rescore", action="store_true")
    parser.add_argument("--quiet-progress", action="store_true")
    args = parser.parse_args(argv)
    if args.rescore:
        with campaign_lock(args.output.resolve()):
            write_reports(args.output.resolve())
            result = summarize_run(args.output.resolve())
            return int(
                any(
                    model["failures"] or model["ctx_failures"]
                    for model in cast(
                        "dict[str, dict[str, object]]", result["models"]
                    ).values()
                )
            )
    if args.dataset is None or args.repo_manifest is None:
        parser.error("Execution requires --dataset and --repo-manifest")
    args.k = sorted(set(args.k) | {1, 5, 10})
    budgets = [
        args.query_timeout,
        args.index_timeout,
        *[
            value
            for value in (args.memory_budget_mib, args.max_index_seconds)
            if value is not None
        ],
    ]
    if not all(math.isfinite(value) and value > 0 for value in budgets):
        parser.error("Timeouts and optional budgets must be finite and positive")
    if (
        min(args.k) < 1
        or max(args.k) > 100
        or min(args.query_timeout, args.index_timeout) <= 0
    ):
        parser.error("K must be 1..100; timeouts must be positive")
    with campaign_lock(args.output.resolve()):
        if not args.quiet_progress:
            print(
                "Preparing frozen sources and model controls...",
                file=sys.stderr,
                flush=True,
            )
        identity, cases, codira = prepare_campaign(args)
        status = collect_rankings(args, identity, cases, codira)
        write_reports(args.output)
    print(f"Known-target results: {args.output}")
    return status


if __name__ == "__main__":
    raise SystemExit(main())
