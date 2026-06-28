#!/usr/bin/env python3
"""Run ONNX embedding runtime parameter sweeps."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from time import perf_counter
from typing import cast

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.run_final_embedding_model_campaign import (
    ModelEntry,
    RepositoryEntry,
    read_models,
    read_repositories,
    render_model_config,
)
from scripts.scriptlib import RepoConfigRestore, resolve_codira, safe_slug

DEFAULT_SWEEP_MANIFEST = Path("benchmarks/onnx-parameter-sweep.json")
DEFAULT_MODEL_MANIFEST = Path("benchmarks/embedding-model-candidates.json")
DEFAULT_REPO_MANIFEST = Path("benchmarks/uv-backed-repos.local.json")
DEFAULT_ARTIFACT_ROOT = Path(".artifacts/onnx-parameter-sweep")
DEFAULT_BACKEND = "sqlite"
BACKENDS = ("sqlite", "duckdb")


@dataclass(frozen=True)
class OnnxVariant:
    """
    One ONNX runtime parameter variant.

    Parameters
    ----------
    variant_id : str
        Stable variant id.
    batch_size : int
        Core embedding batch size.
    max_tokens : int
        ONNX tokenizer/runtime token cap.
    intra_op_num_threads : int
        ONNX Runtime intra-op thread count.
    inter_op_num_threads : int
        ONNX Runtime inter-op thread count.
    max_text_chars : int
        Indexing text cap, or zero to disable the cap.
    """

    variant_id: str
    batch_size: int
    max_tokens: int
    intra_op_num_threads: int
    inter_op_num_threads: int
    max_text_chars: int = 0


@dataclass(frozen=True)
class OnnxSweep:
    """
    One ONNX model sweep.

    Parameters
    ----------
    sweep_id : str
        Stable sweep id.
    model_id : str
        ONNX model manifest id.
    queries : tuple[str, ...]
        Query texts to run after indexing.
    variants : tuple[OnnxVariant, ...]
        Runtime parameter variants.
    """

    sweep_id: str
    model_id: str
    queries: tuple[str, ...]
    variants: tuple[OnnxVariant, ...]


@dataclass(frozen=True)
class CommandResult:
    """
    Timed command result.

    Parameters
    ----------
    returncode : int
        Process return code.
    elapsed_seconds : float
        Wall-clock elapsed seconds.
    log_path : pathlib.Path
        Captured command log path.
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


def load_sweeps(path: Path) -> tuple[OnnxSweep, ...]:
    """
    Load ONNX parameter sweeps from a JSON manifest.

    Parameters
    ----------
    path : pathlib.Path
        Sweep manifest path.

    Returns
    -------
    tuple[OnnxSweep, ...]
        Parsed sweeps.
    """

    payload = json.loads(path.read_text(encoding="utf-8"))
    sweeps: list[OnnxSweep] = []
    for item in payload["sweeps"]:
        sweeps.append(
            OnnxSweep(
                sweep_id=str(item["id"]),
                model_id=str(item["model"]),
                queries=tuple(str(query) for query in item.get("queries", ())),
                variants=tuple(
                    OnnxVariant(
                        variant_id=str(variant["id"]),
                        batch_size=int(variant["batch_size"]),
                        max_tokens=int(variant.get("max_tokens", 512)),
                        intra_op_num_threads=int(
                            variant.get("intra_op_num_threads", 0)
                        ),
                        inter_op_num_threads=int(
                            variant.get("inter_op_num_threads", 0)
                        ),
                        max_text_chars=int(variant.get("max_text_chars", 0)),
                    )
                    for variant in item["variants"]
                ),
            )
        )
    return tuple(sweeps)


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


def model_for_variant(model: ModelEntry, variant: OnnxVariant) -> ModelEntry:
    """
    Return a model entry with variant runtime settings applied.

    Parameters
    ----------
    model : ModelEntry
        Base ONNX model entry.
    variant : OnnxVariant
        Runtime parameter variant.

    Returns
    -------
    ModelEntry
        Model entry with variant config overrides.
    """

    config = dict(model.config)
    config["max_tokens"] = variant.max_tokens
    config["intra_op_num_threads"] = variant.intra_op_num_threads
    config["inter_op_num_threads"] = variant.inter_op_num_threads
    return ModelEntry(
        id=f"{model.id}-{variant.variant_id}",
        engine=model.engine,
        model=model.model,
        version=model.version,
        dimension=model.dimension,
        precision=model.precision,
        config=config,
    )


def render_variant_config(model: ModelEntry, variant: OnnxVariant, backend: str) -> str:
    """
    Render Codira config for one ONNX variant.

    Parameters
    ----------
    model : ModelEntry
        Base model entry.
    variant : OnnxVariant
        Runtime parameter variant.
    backend : {"sqlite", "duckdb"}
        Active backend/vector-store.

    Returns
    -------
    str
        TOML configuration text.
    """

    rendered = render_model_config(model_for_variant(model, variant), backend)
    rendered = rendered.replace(
        f"batch_size = {8 if model.dimension < 768 else 1}",
        f"batch_size = {variant.batch_size}",
        1,
    )
    rendered = rendered.replace(
        "intra_op_num_threads = 0"
        if model.dimension < 768
        else "intra_op_num_threads = 4",
        f"intra_op_num_threads = {variant.intra_op_num_threads}",
        1,
    )
    rendered = rendered.replace(
        "inter_op_num_threads = 0"
        if model.dimension < 768
        else "inter_op_num_threads = 1",
        f"inter_op_num_threads = {variant.inter_op_num_threads}",
        1,
    )
    if variant.max_text_chars:
        rendered = rendered.replace(
            "max_text_chars = 0",
            f"max_text_chars = {variant.max_text_chars}",
            1,
        )
    return rendered


def timed_command(
    command: tuple[str, ...],
    *,
    cwd: Path,
    env: dict[str, str],
    log_path: Path,
) -> CommandResult:
    """
    Run one command and capture elapsed wall time.

    Parameters
    ----------
    command : tuple[str, ...]
        Command vector.
    cwd : pathlib.Path
        Working directory.
    env : dict[str, str]
        Child process environment.
    log_path : pathlib.Path
        Log path receiving stdout and stderr.

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


def result_row(**values: object) -> str:
    """
    Serialize one JSONL result row.

    Parameters
    ----------
    **values : object
        JSON-compatible row values.

    Returns
    -------
    str
        One JSON line.
    """

    return json.dumps(values, sort_keys=True) + "\n"


def build_parser() -> argparse.ArgumentParser:
    """
    Build the ONNX sweep parser.

    Parameters
    ----------
    None

    Returns
    -------
    argparse.ArgumentParser
        Parser for ONNX parameter sweep options.
    """

    parser = argparse.ArgumentParser(
        description="Run isolated Codira ONNX parameter sweep experiments.",
    )
    parser.add_argument("--sweep-manifest", type=Path, default=DEFAULT_SWEEP_MANIFEST)
    parser.add_argument("--model-manifest", type=Path, default=DEFAULT_MODEL_MANIFEST)
    parser.add_argument("--repo-manifest", type=Path, default=DEFAULT_REPO_MANIFEST)
    parser.add_argument("--backend", choices=BACKENDS, default=DEFAULT_BACKEND)
    parser.add_argument("--sweep-id", action="append", default=[])
    parser.add_argument("--variant-id", action="append", default=[])
    parser.add_argument("--artifact-root", type=Path, default=DEFAULT_ARTIFACT_ROOT)
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--no-full", action="store_true")
    return parser


def run_variant(  # noqa: PLR0913
    *,
    codira: str,
    repo: RepositoryEntry,
    sweep: OnnxSweep,
    model: ModelEntry,
    variant: OnnxVariant,
    backend: str,
    artifact_root: Path,
    env: dict[str, str],
    results_path: Path,
    limit: int,
    full: bool,
) -> int:
    """
    Run one repo/model/variant sweep phase.

    Parameters
    ----------
    codira : str
        Codira executable.
    repo : RepositoryEntry
        Repository entry.
    sweep : OnnxSweep
        Sweep metadata.
    model : ModelEntry
        Base ONNX model entry.
    variant : OnnxVariant
        Runtime parameter variant.
    backend : {"sqlite", "duckdb"}
        Active backend/vector-store.
    artifact_root : pathlib.Path
        Root artifact directory.
    env : dict[str, str]
        Child process environment.
    results_path : pathlib.Path
        JSONL result path.
    limit : int
        `codira emb` result limit.
    full : bool
        Whether to force full indexing.

    Returns
    -------
    int
        First non-zero phase status, or zero.
    """

    repo_slug = safe_slug(f"{repo.index}-{repo.label}")
    slug = safe_slug(f"{sweep.sweep_id}-{variant.variant_id}-{repo_slug}")
    output_dir = artifact_root / "outputs" / slug
    config_path = artifact_root / "configs" / f"{slug}.toml"
    log_root = artifact_root / "logs"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        render_variant_config(model, variant, backend),
        encoding="utf-8",
    )
    target_config = repo.path / ".codira" / "config.toml"
    target_config.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(config_path, target_config)

    status = 0
    index_command = (
        codira,
        "index",
        *(("--full",) if full else ()),
        "--path",
        str(repo.path),
        "--output-dir",
        str(output_dir),
        "--json",
    )
    index_result = timed_command(
        index_command,
        cwd=Path.cwd(),
        env=env,
        log_path=log_root / f"{slug}-index.log",
    )
    with results_path.open("a", encoding="utf-8") as results_file:
        results_file.write(
            result_row(
                sweep=sweep.sweep_id,
                variant=variant.variant_id,
                repo=repo.label,
                backend=backend,
                phase="index",
                batch_size=variant.batch_size,
                max_tokens=variant.max_tokens,
                intra_op_num_threads=variant.intra_op_num_threads,
                inter_op_num_threads=variant.inter_op_num_threads,
                max_text_chars=variant.max_text_chars,
                elapsed_seconds=index_result.elapsed_seconds,
                status=index_result.returncode,
                log=str(index_result.log_path),
            )
        )
    if index_result.returncode:
        return index_result.returncode

    for query_index, query in enumerate(sweep.queries, start=1):
        for command_name in ("emb", "ctx"):
            command: tuple[str, ...] = (
                codira,
                command_name,
                "--json",
                query,
                "--path",
                str(repo.path),
                "--output-dir",
                str(output_dir),
            )
            if command_name == "emb":
                command = (
                    codira,
                    "emb",
                    query,
                    "--json",
                    "--limit",
                    str(limit),
                    "--path",
                    str(repo.path),
                    "--output-dir",
                    str(output_dir),
                )
            result = timed_command(
                command,
                cwd=Path.cwd(),
                env=env,
                log_path=log_root / f"{slug}-{command_name}-{query_index}.log",
            )
            with results_path.open("a", encoding="utf-8") as results_file:
                results_file.write(
                    result_row(
                        sweep=sweep.sweep_id,
                        variant=variant.variant_id,
                        repo=repo.label,
                        backend=backend,
                        phase=command_name,
                        query=query,
                        elapsed_seconds=result.elapsed_seconds,
                        status=result.returncode,
                        log=str(result.log_path),
                    )
                )
            if result.returncode and not status:
                status = result.returncode
    return status


def main(argv: list[str] | None = None) -> int:
    """
    Run the ONNX parameter sweep.

    Parameters
    ----------
    argv : list[str] | None, optional
        Command-line arguments excluding the executable.

    Returns
    -------
    int
        Zero when all phases pass.
    """

    args = build_parser().parse_args(argv)
    codira = resolve_codira()
    stamp = local_stamp()
    artifact_root = args.artifact_root / stamp
    backup_root = artifact_root / "repo-config-backups"
    results_path = artifact_root / "results.jsonl"
    artifact_root.mkdir(parents=True, exist_ok=True)

    repos = read_repositories(args.repo_manifest)
    models = model_by_id(read_models(args.model_manifest))
    selected_sweeps = set(cast("list[str]", args.sweep_id))
    selected_variants = set(cast("list[str]", args.variant_id))
    sweeps = tuple(
        sweep
        for sweep in load_sweeps(args.sweep_manifest)
        if not selected_sweeps or sweep.sweep_id in selected_sweeps
    )
    if not sweeps:
        message = "No ONNX sweeps selected."
        raise SystemExit(message)

    env = dict(os.environ)
    status = 0
    with RepoConfigRestore(tuple(repo.path for repo in repos), backup_root):
        for sweep in sweeps:
            model = models[sweep.model_id]
            if model.engine != "onnx":
                message = f"Sweep model is not ONNX: {model.id}"
                raise SystemExit(message)
            variants = tuple(
                variant
                for variant in sweep.variants
                if not selected_variants or variant.variant_id in selected_variants
            )
            for variant in variants:
                for repo in repos:
                    rc = run_variant(
                        codira=codira,
                        repo=repo,
                        sweep=sweep,
                        model=model,
                        variant=variant,
                        backend=args.backend,
                        artifact_root=artifact_root,
                        env=env,
                        results_path=results_path,
                        limit=args.limit,
                        full=not args.no_full,
                    )
                    if rc and not status:
                        status = rc
    print(f"Artifacts: {artifact_root}")
    print(f"Results: {results_path}")
    return status


if __name__ == "__main__":
    raise SystemExit(main())
