#!/usr/bin/env python3
"""Run Codira retrieval-quality benchmarks over labeled examples."""

from __future__ import annotations

import argparse
import json
import math
import os
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from time import perf_counter
from typing import TYPE_CHECKING, cast

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.run_final_embedding_model_campaign import (
    CONCRETE_BACKENDS,
    ModelEntry,
    RepositoryEntry,
    read_models,
    read_repositories,
    render_model_config,
)
from scripts.scriptlib import resolve_codira, safe_slug

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

DEFAULT_DATASET = Path(".artifacts/retrieval-quality/dataset.jsonl")
DEFAULT_MODEL_MANIFEST = Path("benchmarks/embedding-model-candidates.json")
DEFAULT_REPO_MANIFEST = Path("benchmarks/retrieval-quality-repos.local.json")
DEFAULT_ARTIFACT_ROOT = Path(".artifacts/retrieval-quality")
BACKENDS = (*CONCRETE_BACKENDS, "both")
PATH_KEYS = frozenset({"file", "path", "file_path"})


@dataclass(frozen=True)
class QualityExample:
    """
    One labeled retrieval-quality example.

    Parameters
    ----------
    example_id : str
        Stable dataset example id.
    repo : str
        Repository label.
    source : str
        Dataset source label.
    query : str
        Natural-language query.
    expected_paths : tuple[str, ...]
        Repo-relative relevant file paths.

    Returns
    -------
    None
    """

    example_id: str
    repo: str
    source: str
    query: str
    expected_paths: tuple[str, ...]


@dataclass(frozen=True)
class Score:
    """
    Ranking-quality metrics for one query.

    Parameters
    ----------
    recall : float
        Recall over expected paths.
    mrr : float
        Reciprocal rank of the first relevant result.
    ndcg : float
        Normalized discounted cumulative gain.
    hit_any : bool
        Whether any expected path was retrieved.
    hits : int
        Number of distinct expected paths retrieved.

    Returns
    -------
    None
    """

    recall: float
    mrr: float
    ndcg: float
    hit_any: bool
    hits: int


@dataclass(frozen=True)
class CommandResult:
    """
    Timed subprocess result.

    Parameters
    ----------
    returncode : int
        Process return code.
    elapsed_seconds : float
        Wall-clock elapsed seconds.
    log_path : pathlib.Path
        Captured stdout/stderr log.

    Returns
    -------
    None
    """

    returncode: int
    elapsed_seconds: float
    log_path: Path


def local_stamp() -> str:
    """
    Return a local timestamp for artifact directories.

    Parameters
    ----------
    None

    Returns
    -------
    str
        Timestamp with timezone offset.
    """

    return datetime.now().strftime("%Y%m%dT%H%M%S%z")


def positive_int(value: str) -> int:
    """
    Parse a positive integer CLI value.

    Parameters
    ----------
    value : str
        Raw command-line value.

    Returns
    -------
    int
        Parsed positive integer.

    Raises
    ------
    argparse.ArgumentTypeError
        Raised when the value is not a positive integer.
    """

    try:
        parsed = int(value)
    except ValueError as exc:
        msg = "value must be an integer"
        raise argparse.ArgumentTypeError(msg) from exc
    if parsed < 1:
        msg = "value must be >= 1"
        raise argparse.ArgumentTypeError(msg)
    return parsed


def normalize_path(path: str) -> str:
    """
    Normalize a repository-relative result path.

    Parameters
    ----------
    path : str
        Raw path.

    Returns
    -------
    str
        Normalized path.
    """

    normalized = path.replace("\\", "/").strip()
    while normalized.startswith("./"):
        normalized = normalized[2:]
    return normalized.strip("/")


def load_dataset(path: Path) -> tuple[QualityExample, ...]:
    """
    Load retrieval-quality examples from JSON Lines.

    Parameters
    ----------
    path : pathlib.Path
        Dataset path.

    Returns
    -------
    tuple[QualityExample, ...]
        Parsed examples.

    Raises
    ------
    TypeError
        Raised when a dataset row has an invalid shape.
    """

    examples: list[QualityExample] = []
    for line_number, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(), 1
    ):
        if not line.strip():
            continue
        payload = json.loads(line)
        if not isinstance(payload, dict):
            msg = f"dataset row {line_number} must be an object"
            raise TypeError(msg)
        expected = payload.get("expected_paths")
        if not isinstance(expected, list):
            msg = f"dataset row {line_number} missing expected_paths list"
            raise TypeError(msg)
        examples.append(
            QualityExample(
                example_id=str(payload["id"]),
                repo=str(payload["repo"]),
                source=str(payload["source"]),
                query=str(payload["query"]),
                expected_paths=tuple(
                    normalized
                    for raw in expected
                    if (normalized := normalize_path(str(raw)))
                ),
            )
        )
    return tuple(examples)


def model_by_id(models: tuple[ModelEntry, ...]) -> dict[str, ModelEntry]:
    """
    Index model entries by manifest id.

    Parameters
    ----------
    models : tuple[ModelEntry, ...]
        Parsed model manifest entries.

    Returns
    -------
    dict[str, ModelEntry]
        Model entries keyed by id.
    """

    return {model.id: model for model in models}


def repo_by_label(repos: tuple[RepositoryEntry, ...]) -> dict[str, RepositoryEntry]:
    """
    Index repository entries by label.

    Parameters
    ----------
    repos : tuple[RepositoryEntry, ...]
        Parsed repository entries.

    Returns
    -------
    dict[str, RepositoryEntry]
        Repository entries keyed by label.
    """

    return {repo.label: repo for repo in repos}


def concrete_backends(backend: str) -> tuple[str, ...]:
    """
    Expand a backend mode to concrete backend names.

    Parameters
    ----------
    backend : str
        Backend mode.

    Returns
    -------
    tuple[str, ...]
        Concrete backend names.

    Raises
    ------
    ValueError
        Raised when ``backend`` is unknown.
    """

    if backend == "both":
        return CONCRETE_BACKENDS
    if backend in CONCRETE_BACKENDS:
        return (backend,)
    msg = f"unknown backend: {backend}"
    raise ValueError(msg)


def timed_command(
    command: Sequence[str],
    *,
    cwd: Path,
    env: dict[str, str],
    log_path: Path,
) -> CommandResult:
    """
    Run a command and capture elapsed wall time.

    Parameters
    ----------
    command : collections.abc.Sequence[str]
        Command vector.
    cwd : pathlib.Path
        Working directory.
    env : dict[str, str]
        Child environment.
    log_path : pathlib.Path
        Log path for stdout and stderr.

    Returns
    -------
    CommandResult
        Timed command metadata.
    """

    log_path.parent.mkdir(parents=True, exist_ok=True)
    started = perf_counter()
    with log_path.open("w", encoding="utf-8") as log_file:
        returncode = subprocess.call(
            list(command),
            cwd=cwd,
            env=env,
            stdout=log_file,
            stderr=subprocess.STDOUT,
        )
    return CommandResult(
        returncode=returncode,
        elapsed_seconds=perf_counter() - started,
        log_path=log_path,
    )


def decode_json_from_log(path: Path) -> dict[str, object]:
    """
    Decode the first JSON object from a command log.

    Parameters
    ----------
    path : pathlib.Path
        Command log path.

    Returns
    -------
    dict[str, object]
        Decoded JSON object, or an empty object when none is found.
    """

    text = path.read_text(encoding="utf-8")
    decoder = json.JSONDecoder()
    for index, char in enumerate(text):
        if char != "{":
            continue
        try:
            payload, _end = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            return cast("dict[str, object]", payload)
    return {}


def extract_paths(value: object) -> tuple[str, ...]:
    """
    Extract result paths from a nested JSON payload.

    Parameters
    ----------
    value : object
        JSON-compatible value.

    Returns
    -------
    tuple[str, ...]
        Deduplicated normalized paths in traversal order.
    """

    paths: list[str] = []

    def visit(item: object) -> None:
        if isinstance(item, dict):
            for key, nested in item.items():
                if key in PATH_KEYS and isinstance(nested, str):
                    if path := normalize_path(nested):
                        paths.append(path)
                else:
                    visit(nested)
        elif isinstance(item, list):
            for nested in item:
                visit(nested)

    visit(value)
    return tuple(dict.fromkeys(paths))


def score_paths(
    expected_paths: Iterable[str], retrieved_paths: Iterable[str], *, k: int
) -> Score:
    """
    Score retrieved paths against expected paths.

    Parameters
    ----------
    expected_paths : collections.abc.Iterable[str]
        Relevant paths.
    retrieved_paths : collections.abc.Iterable[str]
        Ranked retrieved paths.
    k : int
        Ranking cutoff.

    Returns
    -------
    Score
        Retrieval quality metrics.
    """

    expected = tuple(
        dict.fromkeys(
            normalize_path(path) for path in expected_paths if normalize_path(path)
        )
    )
    ranked = tuple(
        dict.fromkeys(
            normalize_path(path) for path in retrieved_paths if normalize_path(path)
        )
    )[:k]
    if not expected:
        return Score(recall=0.0, mrr=0.0, ndcg=0.0, hit_any=False, hits=0)

    def matches_expected(path: str) -> bool:
        """
        Return whether a retrieved path matches an expected repository path.

        Parameters
        ----------
        path : str
            Normalized retrieved path.

        Returns
        -------
        bool
            ``True`` when ``path`` is equal to or ends with an expected
            repo-relative path.
        """
        return any(
            path == expected_path or path.endswith(f"/{expected_path}")
            for expected_path in expected
        )

    hits = 0
    dcg = 0.0
    first_rank = 0
    for rank, path in enumerate(ranked, start=1):
        if not matches_expected(path):
            continue
        hits += 1
        if not first_rank:
            first_rank = rank
        dcg += 1.0 / math.log2(rank + 1)

    ideal_hits = min(len(expected), k)
    ideal_dcg = sum(1.0 / math.log2(rank + 1) for rank in range(1, ideal_hits + 1))
    return Score(
        recall=hits / len(expected),
        mrr=0.0 if not first_rank else 1.0 / first_rank,
        ndcg=0.0 if ideal_dcg == 0.0 else dcg / ideal_dcg,
        hit_any=hits > 0,
        hits=hits,
    )


def result_row(**values: object) -> str:
    """
    Serialize one JSONL row.

    Parameters
    ----------
    **values : object
        JSON-compatible values.

    Returns
    -------
    str
        JSON line.
    """

    return json.dumps(values, sort_keys=True) + "\n"


def write_config(path: Path, model: ModelEntry, backend: str) -> None:
    """
    Write one generated Codira config.

    Parameters
    ----------
    path : pathlib.Path
        Output config path.
    model : ModelEntry
        Model entry.
    backend : str
        Backend name.

    Returns
    -------
    None
        Config is written.
    """

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_model_config(model, backend), encoding="utf-8")


def append_index_row(
    results_path: Path,
    *,
    repo: RepositoryEntry,
    model: ModelEntry,
    backend: str,
    result: CommandResult,
) -> None:
    """
    Append one index result row.

    Parameters
    ----------
    results_path : pathlib.Path
        JSONL results path.
    repo : RepositoryEntry
        Repository entry.
    model : ModelEntry
        Model entry.
    backend : str
        Backend name.
    result : CommandResult
        Timed command result.

    Returns
    -------
    None
        Row is appended.
    """

    with results_path.open("a", encoding="utf-8") as output:
        output.write(
            result_row(
                phase="index",
                repo=repo.label,
                model=model.id,
                engine=model.engine,
                dimension=model.dimension,
                backend=backend,
                elapsed_seconds=result.elapsed_seconds,
                status=result.returncode,
                log=str(result.log_path),
            )
        )


def append_query_row(  # noqa: PLR0913
    results_path: Path,
    *,
    example: QualityExample,
    repo: RepositoryEntry,
    model: ModelEntry,
    backend: str,
    channel: str,
    result: CommandResult,
    retrieved_paths: tuple[str, ...],
    score: Score,
) -> None:
    """
    Append one query result row.

    Parameters
    ----------
    results_path : pathlib.Path
        JSONL results path.
    example : QualityExample
        Dataset example.
    repo : RepositoryEntry
        Repository entry.
    model : ModelEntry
        Model entry.
    backend : str
        Backend name.
    channel : str
        Retrieval channel command.
    result : CommandResult
        Timed command result.
    retrieved_paths : tuple[str, ...]
        Ranked result paths.
    score : Score
        Retrieval metrics.

    Returns
    -------
    None
        Row is appended.
    """

    with results_path.open("a", encoding="utf-8") as output:
        output.write(
            result_row(
                phase=channel,
                example_id=example.example_id,
                repo=repo.label,
                source=example.source,
                model=model.id,
                engine=model.engine,
                dimension=model.dimension,
                backend=backend,
                query=example.query,
                expected_paths=list(example.expected_paths),
                retrieved_paths=list(retrieved_paths),
                elapsed_seconds=result.elapsed_seconds,
                status=result.returncode,
                recall=score.recall,
                mrr=score.mrr,
                ndcg=score.ndcg,
                hit_any=score.hit_any,
                hits=score.hits,
                log=str(result.log_path),
            )
        )


def summarize_results(results_path: Path) -> dict[str, object]:
    """
    Summarize query rows by backend/model/repo/source/channel.

    Parameters
    ----------
    results_path : pathlib.Path
        JSONL result path.

    Returns
    -------
    dict[str, object]
        Summary payload.
    """

    groups: dict[tuple[str, str, str, str, str], list[dict[str, object]]] = {}
    index_seconds: dict[tuple[str, str, str], float] = {}
    for line in results_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if not isinstance(row, dict):
            continue
        phase = str(row.get("phase") or "")
        if phase == "index":
            index_key = (
                str(row.get("backend") or ""),
                str(row.get("model") or ""),
                str(row.get("repo") or ""),
            )
            index_seconds[index_key] = _float_field(row, "elapsed_seconds")
            continue
        if phase not in {"emb", "ctx"}:
            continue
        group_key = (
            str(row.get("backend") or ""),
            str(row.get("model") or ""),
            str(row.get("repo") or ""),
            str(row.get("source") or ""),
            phase,
        )
        groups.setdefault(group_key, []).append(cast("dict[str, object]", row))

    summaries: list[dict[str, object]] = []
    for (backend, model, repo, source, channel), rows in sorted(groups.items()):
        count = len(rows)
        index_elapsed = index_seconds.get((backend, model, repo), 0.0)
        scores = tuple(_score_result_row(row) for row in rows)
        summaries.append(
            {
                "backend": backend,
                "model": model,
                "repo": repo,
                "source": source,
                "channel": channel,
                "examples": count,
                "index_seconds": index_elapsed,
                "mean_query_seconds": sum(
                    _float_field(row, "elapsed_seconds") for row in rows
                )
                / count,
                "mean_recall": sum(score.recall for score in scores) / count,
                "mean_mrr": sum(score.mrr for score in scores) / count,
                "mean_ndcg": sum(score.ndcg for score in scores) / count,
                "hit_any_rate": sum(1 for score in scores if score.hit_any) / count,
            }
        )
    return {"schema_version": 1, "groups": summaries}


def _score_result_row(row: dict[str, object]) -> Score:
    """
    Recompute one stored query row score from path lists.

    Parameters
    ----------
    row : dict[str, object]
        Stored query result row.

    Returns
    -------
    Score
        Recomputed score using the current path-normalization logic.
    """
    expected_raw = row.get("expected_paths")
    retrieved_raw = row.get("retrieved_paths")
    expected = (
        [str(value) for value in expected_raw] if isinstance(expected_raw, list) else []
    )
    retrieved = (
        [str(value) for value in retrieved_raw]
        if isinstance(retrieved_raw, list)
        else []
    )
    return score_paths(expected, retrieved, k=len(retrieved) or 1)


def _float_field(row: dict[str, object], key: str) -> float:
    """
    Return one numeric row field as ``float``.

    Parameters
    ----------
    row : dict[str, object]
        Result row.
    key : str
        Field name.

    Returns
    -------
    float
        Numeric value, or ``0.0`` for missing and non-numeric values.
    """

    value = row.get(key)
    if isinstance(value, int | float | str):
        return float(value)
    return 0.0


def write_report(path: Path, summary: dict[str, object]) -> None:
    """
    Write a Markdown summary report.

    Parameters
    ----------
    path : pathlib.Path
        Report path.
    summary : dict[str, object]
        Summary payload.

    Returns
    -------
    None
        Report is written.
    """

    groups = summary.get("groups")
    rows = groups if isinstance(groups, list) else []
    lines = [
        "# Retrieval Quality Benchmark",
        "",
        "| Backend | Model | Repo | Source | Channel | Examples | Recall | MRR | nDCG | Hit@10 | Index s | Query s |",
        "|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in rows:
        if not isinstance(row, dict):
            continue
        lines.append(
            "| {backend} | {model} | {repo} | {source} | {channel} | {examples} | "
            "{recall:.4f} | {mrr:.4f} | {ndcg:.4f} | {hit:.4f} | "
            "{index:.3f} | {query:.3f} |".format(
                backend=row["backend"],
                model=row["model"],
                repo=row["repo"],
                source=row["source"],
                channel=row["channel"],
                examples=int(row["examples"]),
                recall=float(row["mean_recall"]),
                mrr=float(row["mean_mrr"]),
                ndcg=float(row["mean_ndcg"]),
                hit=float(row["hit_any_rate"]),
                index=float(row["index_seconds"]),
                query=float(row["mean_query_seconds"]),
            )
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_summary_artifacts(results_path: Path) -> tuple[Path, Path]:
    """
    Write summary artifacts for an existing result file.

    Parameters
    ----------
    results_path : pathlib.Path
        JSON Lines result file.

    Returns
    -------
    tuple[pathlib.Path, pathlib.Path]
        Written ``summary.json`` and ``report.md`` paths.
    """

    summary = summarize_results(results_path)
    summary_path = results_path.parent / "summary.json"
    report_path = results_path.parent / "report.md"
    summary_path.write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    write_report(report_path, summary)
    return summary_path, report_path


def build_parser() -> argparse.ArgumentParser:
    """
    Build the retrieval-quality benchmark parser.

    Parameters
    ----------
    None

    Returns
    -------
    argparse.ArgumentParser
        Configured parser.
    """

    parser = argparse.ArgumentParser(
        description="Run Codira retrieval-quality benchmarks from a labeled dataset."
    )
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--model-manifest", type=Path, default=DEFAULT_MODEL_MANIFEST)
    parser.add_argument("--repo-manifest", type=Path, default=DEFAULT_REPO_MANIFEST)
    parser.add_argument("--backend", choices=BACKENDS, default="sqlite")
    parser.add_argument("--model-id", action="append", default=[])
    parser.add_argument("--artifact-root", type=Path, default=DEFAULT_ARTIFACT_ROOT)
    parser.add_argument("--top-k", type=positive_int, default=10)
    parser.add_argument("--include-ctx", action="store_true")
    parser.add_argument("--no-full", action="store_true")
    parser.add_argument(
        "--rescore-results",
        type=Path,
        help="Regenerate summary.json and report.md beside an existing results.jsonl.",
    )
    return parser


def run_group(  # noqa: PLR0913
    *,
    codira: str,
    repo: RepositoryEntry,
    model: ModelEntry,
    backend: str,
    examples: Sequence[QualityExample],
    artifact_root: Path,
    results_path: Path,
    env: dict[str, str],
    top_k: int,
    include_ctx: bool,
    full: bool,
) -> int:
    """
    Run one repo/model/backend benchmark group.

    Parameters
    ----------
    codira : str
        Codira executable.
    repo : RepositoryEntry
        Repository entry.
    model : ModelEntry
        Model entry.
    backend : str
        Backend name.
    examples : collections.abc.Sequence[QualityExample]
        Examples for this repository.
    artifact_root : pathlib.Path
        Artifact directory.
    results_path : pathlib.Path
        JSONL result path.
    env : dict[str, str]
        Child process environment.
    top_k : int
        Retrieval cutoff.
    include_ctx : bool
        Whether to also run ``codira ctx``.
    full : bool
        Whether to force full indexing.

    Returns
    -------
    int
        First non-zero command status, or zero.
    """

    slug = safe_slug(f"{backend}-{model.id}-{repo.index}-{repo.label}")
    config_path = artifact_root / "configs" / f"{slug}.toml"
    output_dir = artifact_root / "outputs" / slug
    log_root = artifact_root / "logs"
    write_config(config_path, model, backend)

    index_command = (
        codira,
        "index",
        *(("--full",) if full else ()),
        "--path",
        str(repo.path),
        "--output-dir",
        str(output_dir),
        "--config-file",
        str(config_path),
        "--json",
    )
    index_result = timed_command(
        index_command,
        cwd=Path.cwd(),
        env=env,
        log_path=log_root / f"{slug}-index.log",
    )
    append_index_row(
        results_path,
        repo=repo,
        model=model,
        backend=backend,
        result=index_result,
    )
    if index_result.returncode:
        return index_result.returncode

    status = 0
    channels = ("emb", "ctx") if include_ctx else ("emb",)
    for example in examples:
        for channel in channels:
            command: tuple[str, ...]
            if channel == "emb":
                command = (
                    codira,
                    "emb",
                    example.query,
                    "--json",
                    "--limit",
                    str(top_k),
                    "--path",
                    str(repo.path),
                    "--output-dir",
                    str(output_dir),
                    "--config-file",
                    str(config_path),
                )
            else:
                command = (
                    codira,
                    "ctx",
                    "--json",
                    example.query,
                    "--path",
                    str(repo.path),
                    "--output-dir",
                    str(output_dir),
                    "--config-file",
                    str(config_path),
                )
            result = timed_command(
                command,
                cwd=Path.cwd(),
                env=env,
                log_path=log_root
                / f"{slug}-{channel}-{safe_slug(example.example_id)}.log",
            )
            payload = decode_json_from_log(result.log_path)
            retrieved = extract_paths(payload)[:top_k]
            score = score_paths(example.expected_paths, retrieved, k=top_k)
            append_query_row(
                results_path,
                example=example,
                repo=repo,
                model=model,
                backend=backend,
                channel=channel,
                result=result,
                retrieved_paths=retrieved,
                score=score,
            )
            if result.returncode and not status:
                status = result.returncode
    return status


def main(argv: list[str] | None = None) -> int:
    """
    Run the retrieval-quality benchmark.

    Parameters
    ----------
    argv : list[str] | None, optional
        Command-line arguments excluding the executable.

    Returns
    -------
    int
        Zero when all selected groups complete successfully.

    Raises
    ------
    ValueError
        Raised when manifests or datasets are malformed.
    OSError
        Propagated when artifacts cannot be written.
    """

    args = build_parser().parse_args(argv)
    if args.rescore_results is not None:
        summary_path, report_path = write_summary_artifacts(args.rescore_results)
        print(f"Results: {args.rescore_results}")
        print(f"Summary: {summary_path}")
        print(f"Report: {report_path}")
        return 0

    codira = resolve_codira()
    stamp = local_stamp()
    artifact_root = args.artifact_root / stamp
    results_path = artifact_root / "results.jsonl"
    summary_path = artifact_root / "summary.json"
    report_path = artifact_root / "report.md"
    artifact_root.mkdir(parents=True, exist_ok=True)

    examples = load_dataset(args.dataset)
    repos = repo_by_label(read_repositories(args.repo_manifest))
    models = model_by_id(read_models(args.model_manifest))
    selected_model_ids = set(cast("list[str]", args.model_id))
    selected_models = tuple(
        model
        for model in models.values()
        if not selected_model_ids or model.id in selected_model_ids
    )
    if not selected_models:
        msg = "No models selected."
        raise SystemExit(msg)

    examples_by_repo: dict[str, list[QualityExample]] = {}
    for example in examples:
        examples_by_repo.setdefault(example.repo, []).append(example)

    env = dict(os.environ)
    env["CODIRA"] = codira
    status = 0
    for backend in concrete_backends(args.backend):
        for model in selected_models:
            for repo_label, repo_examples in sorted(examples_by_repo.items()):
                repo = repos.get(repo_label)
                if repo is None:
                    continue
                rc = run_group(
                    codira=codira,
                    repo=repo,
                    model=model,
                    backend=backend,
                    examples=repo_examples,
                    artifact_root=artifact_root,
                    results_path=results_path,
                    env=env,
                    top_k=args.top_k,
                    include_ctx=args.include_ctx,
                    full=not args.no_full,
                )
                if rc and not status:
                    status = rc

    summary_path, report_path = write_summary_artifacts(results_path)
    print(f"Artifacts: {artifact_root}")
    print(f"Results: {results_path}")
    print(f"Summary: {summary_path}")
    print(f"Report: {report_path}")
    return status


if __name__ == "__main__":
    raise SystemExit(main())
