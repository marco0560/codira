#!/usr/bin/env python3
"""Run experimental SentenceTransformers-index and ONNX-query checks."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from time import perf_counter
from typing import cast

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts import compare_embedding_engines
from scripts.run_final_embedding_model_campaign import (
    ModelEntry,
    read_models,
    read_repositories,
    render_model_config,
)
from scripts.scriptlib import RepoConfigRestore, resolve_codira, safe_slug

DEFAULT_PAIR_MANIFEST = Path("benchmarks/split-embedding-engine-pairs.json")
DEFAULT_MODEL_MANIFEST = Path("benchmarks/embedding-model-candidates.json")
DEFAULT_REPO_MANIFEST = Path("benchmarks/uv-backed-repos.local.json")
DEFAULT_ARTIFACT_ROOT = Path(".artifacts/split-embedding-engine-experiment")
DEFAULT_BACKEND = "sqlite"
BACKENDS = ("sqlite", "duckdb")


@dataclass(frozen=True)
class SplitPair:
    """
    Experimental split-engine pair.

    Parameters
    ----------
    pair_id : str
        Stable experiment identifier.
    index_model : str
        Manifest id for the SentenceTransformers indexing model.
    query_model : str
        Manifest id for the ONNX query model.
    threshold : float
        Minimum compatibility-gate cosine similarity.
    queries : tuple[str, ...]
        Query texts to run after indexing.
    """

    pair_id: str
    index_model: str
    query_model: str
    threshold: float
    queries: tuple[str, ...]


@dataclass(frozen=True)
class CommandResult:
    """
    Timed command result.

    Parameters
    ----------
    command : tuple[str, ...]
        Command vector.
    returncode : int
        Process return code.
    elapsed_seconds : float
        Wall-clock elapsed seconds.
    log_path : pathlib.Path
        Captured command log path.
    """

    command: tuple[str, ...]
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


def load_split_pairs(path: Path) -> tuple[SplitPair, ...]:
    """
    Load split-engine pairs from a JSON manifest.

    Parameters
    ----------
    path : pathlib.Path
        Pair manifest path.

    Returns
    -------
    tuple[SplitPair, ...]
        Parsed split-engine pairs.
    """

    payload = json.loads(path.read_text(encoding="utf-8"))
    return tuple(
        SplitPair(
            pair_id=str(item["id"]),
            index_model=str(item["index_model"]),
            query_model=str(item["query_model"]),
            threshold=float(item.get("threshold", 0.99)),
            queries=tuple(str(query) for query in item.get("queries", ())),
        )
        for item in payload["pairs"]
    )


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


def compatibility_entries(
    models: dict[str, ModelEntry],
) -> dict[str, compare_embedding_engines.ModelEntry]:
    """
    Convert campaign model entries to compatibility-gate entries.

    Parameters
    ----------
    models : dict[str, scripts.run_final_embedding_model_campaign.ModelEntry]
        Campaign model entries keyed by id.

    Returns
    -------
    dict[str, scripts.compare_embedding_engines.ModelEntry]
        Compatibility manifest entries keyed by id.
    """

    return {
        model_id: compare_embedding_engines.ModelEntry(
            model_id=model.id,
            engine=model.engine,
            model=model.model,
            version=model.version,
            dimension=model.dimension,
            precision=model.precision,
            config=dict(model.config),
        )
        for model_id, model in models.items()
    }


def render_result_row(**values: object) -> str:
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
        command=command,
        returncode=returncode,
        elapsed_seconds=perf_counter() - started,
        log_path=log_path,
    )


def vector_store_path(output_dir: Path, backend: str) -> Path:
    """
    Return the separated vector-store path for one backend.

    Parameters
    ----------
    output_dir : pathlib.Path
        Experiment output directory used as Codira output root.
    backend : {"sqlite", "duckdb"}
        Active backend/vector-store name.

    Returns
    -------
    pathlib.Path
        Backend-specific vector-store database path.
    """

    suffix = {"sqlite": "embeddings.db", "duckdb": "embeddings.duckdb"}[backend]
    return output_dir / ".codira" / suffix


def alias_sqlite_vector_set(
    *,
    db_path: Path,
    source: ModelEntry,
    target: ModelEntry,
    backend: str,
) -> int:
    """
    Alias materialized SQLite vectors from source identity to target identity.

    Parameters
    ----------
    db_path : pathlib.Path
        SQLite vector-store path.
    source : ModelEntry
        Indexed SentenceTransformers model.
    target : ModelEntry
        Query-time ONNX model.
    backend : str
        Vector-store backend name.

    Returns
    -------
    int
        Number of materialized vector rows aliased.

    Raises
    ------
    RuntimeError
        Raised when the source vector set does not exist.
    """

    from codira_embedding_onnx import PACKAGE_VERSION as onnx_version

    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            """
            SELECT id, store_version, format_version
            FROM vector_sets
            WHERE engine = ?
              AND model = ?
              AND model_version = ?
              AND dimension = ?
              AND precision = ?
              AND store = ?
            """,
            (
                source.engine,
                source.model,
                source.version,
                source.dimension,
                source.precision,
                backend,
            ),
        ).fetchone()
        if row is None:
            msg = f"Source vector set not found in {db_path}: {source.id}"
            raise RuntimeError(msg)
        source_id = int(row[0])
        conn.execute(
            """
            INSERT OR IGNORE INTO vector_sets(
                engine,
                engine_version,
                model,
                model_version,
                dimension,
                precision,
                store,
                store_version,
                format_version
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                target.engine,
                onnx_version,
                target.model,
                target.version,
                target.dimension,
                target.precision,
                backend,
                str(row[1]),
                str(row[2]),
            ),
        )
        target_row = conn.execute(
            """
            SELECT id
            FROM vector_sets
            WHERE engine = ?
              AND model = ?
              AND model_version = ?
              AND dimension = ?
              AND precision = ?
              AND store = ?
            """,
            (
                target.engine,
                target.model,
                target.version,
                target.dimension,
                target.precision,
                backend,
            ),
        ).fetchone()
        assert target_row is not None
        target_id = int(target_row[0])
        conn.execute(
            """
            INSERT OR REPLACE INTO vectors(
                vector_set_id,
                object_type,
                stable_id,
                content_hash,
                vector
            )
            SELECT ?, object_type, stable_id, content_hash, vector
            FROM vectors
            WHERE vector_set_id = ?
            """,
            (target_id, source_id),
        )
        count = conn.execute(
            "SELECT COUNT(*) FROM vectors WHERE vector_set_id = ?",
            (target_id,),
        ).fetchone()
    return int(count[0]) if count is not None else 0


def alias_duckdb_vector_set(
    *,
    db_path: Path,
    source: ModelEntry,
    target: ModelEntry,
    backend: str,
) -> int:
    """
    Alias materialized DuckDB vectors from source identity to target identity.

    Parameters
    ----------
    db_path : pathlib.Path
        DuckDB vector-store path.
    source : ModelEntry
        Indexed SentenceTransformers model.
    target : ModelEntry
        Query-time ONNX model.
    backend : str
        Vector-store backend name.

    Returns
    -------
    int
        Number of materialized vector rows aliased.

    Raises
    ------
    RuntimeError
        Raised when the source vector set does not exist.
    """

    import duckdb
    from codira_embedding_onnx import PACKAGE_VERSION as onnx_version

    with duckdb.connect(str(db_path)) as conn:
        row = conn.execute(
            """
            SELECT id, store_version, format_version
            FROM vector_sets
            WHERE engine = ?
              AND model = ?
              AND model_version = ?
              AND dimension = ?
              AND precision = ?
              AND store = ?
            """,
            (
                source.engine,
                source.model,
                source.version,
                source.dimension,
                source.precision,
                backend,
            ),
        ).fetchone()
        if row is None:
            msg = f"Source vector set not found in {db_path}: {source.id}"
            raise RuntimeError(msg)
        source_id = int(row[0])
        target_row = conn.execute(
            """
            SELECT id
            FROM vector_sets
            WHERE engine = ?
              AND model = ?
              AND model_version = ?
              AND dimension = ?
              AND precision = ?
              AND store = ?
            """,
            (
                target.engine,
                target.model,
                target.version,
                target.dimension,
                target.precision,
                backend,
            ),
        ).fetchone()
        if target_row is None:
            conn.execute(
                """
                INSERT INTO vector_sets(
                    id,
                    engine,
                    engine_version,
                    model,
                    model_version,
                    dimension,
                    precision,
                    store,
                    store_version,
                    format_version
                )
                VALUES (
                    nextval('vector_sets_id_seq'),
                    ?, ?, ?, ?, ?, ?, ?, ?, ?
                )
                """,
                (
                    target.engine,
                    onnx_version,
                    target.model,
                    target.version,
                    target.dimension,
                    target.precision,
                    backend,
                    str(row[1]),
                    str(row[2]),
                ),
            )
            target_row = conn.execute(
                """
                SELECT id
                FROM vector_sets
                WHERE engine = ?
                  AND model = ?
                  AND model_version = ?
                  AND dimension = ?
                  AND precision = ?
                  AND store = ?
                """,
                (
                    target.engine,
                    target.model,
                    target.version,
                    target.dimension,
                    target.precision,
                    backend,
                ),
            ).fetchone()
        assert target_row is not None
        target_id = int(target_row[0])
        conn.execute(
            """
            INSERT OR REPLACE INTO vectors(
                vector_set_id,
                object_type,
                stable_id,
                content_hash,
                vector,
                vector_values
            )
            SELECT ?, object_type, stable_id, content_hash, vector, vector_values
            FROM vectors
            WHERE vector_set_id = ?
            """,
            (target_id, source_id),
        )
        count = conn.execute(
            "SELECT COUNT(*) FROM vectors WHERE vector_set_id = ?",
            (target_id,),
        ).fetchone()
    return int(count[0]) if count is not None else 0


def alias_vector_set(
    *,
    output_dir: Path,
    backend: str,
    source: ModelEntry,
    target: ModelEntry,
) -> int:
    """
    Alias source vectors to the ONNX query vector-set identity.

    Parameters
    ----------
    output_dir : pathlib.Path
        Codira output directory.
    backend : {"sqlite", "duckdb"}
        Active vector-store backend.
    source : ModelEntry
        Indexed SentenceTransformers model.
    target : ModelEntry
        Query-time ONNX model.

    Returns
    -------
    int
        Number of materialized vector rows available under the ONNX identity.
    """

    db_path = vector_store_path(output_dir, backend)
    if backend == "sqlite":
        return alias_sqlite_vector_set(
            db_path=db_path,
            source=source,
            target=target,
            backend=backend,
        )
    return alias_duckdb_vector_set(
        db_path=db_path,
        source=source,
        target=target,
        backend=backend,
    )


def write_config(path: Path, model: ModelEntry, backend: str) -> None:
    """
    Write one generated Codira config.

    Parameters
    ----------
    path : pathlib.Path
        Output config path.
    model : ModelEntry
        Model entry rendered into config.
    backend : {"sqlite", "duckdb"}
        Active backend/vector-store.

    Returns
    -------
    None
        Config text is written.
    """

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_model_config(model, backend), encoding="utf-8")


def run_gate(
    *,
    pair: SplitPair,
    entries: dict[str, compare_embedding_engines.ModelEntry],
    artifact_root: Path,
) -> compare_embedding_engines.ComparisonResult:
    """
    Run the split pair compatibility gate.

    Parameters
    ----------
    pair : SplitPair
        Split pair to validate.
    entries : dict[str, scripts.compare_embedding_engines.ModelEntry]
        Compatibility entries keyed by model id.
    artifact_root : pathlib.Path
        Artifact directory receiving the gate JSON.

    Returns
    -------
    scripts.compare_embedding_engines.ComparisonResult
        Compatibility result.
    """

    left = entries[pair.index_model]
    right = entries[pair.query_model]
    corpus = list(compare_embedding_engines.DEFAULT_CORPUS)
    result = compare_embedding_engines.compare_vectors(
        left,
        right,
        compare_embedding_engines.embed_manifest_entry(left, corpus),
        compare_embedding_engines.embed_manifest_entry(right, corpus),
        threshold=pair.threshold,
    )
    gate_path = artifact_root / "gates" / f"{safe_slug(pair.pair_id)}.json"
    gate_path.parent.mkdir(parents=True, exist_ok=True)
    gate_path.write_text(
        json.dumps(
            compare_embedding_engines.result_payload(result),
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return result


def build_parser() -> argparse.ArgumentParser:
    """
    Build the split experiment parser.

    Parameters
    ----------
    None

    Returns
    -------
    argparse.ArgumentParser
        Parser for split-engine experiment options.
    """

    parser = argparse.ArgumentParser(
        description=(
            "Experimentally index with SentenceTransformers and query with "
            "ONNX after a compatibility gate."
        )
    )
    parser.add_argument("--pair-manifest", type=Path, default=DEFAULT_PAIR_MANIFEST)
    parser.add_argument("--model-manifest", type=Path, default=DEFAULT_MODEL_MANIFEST)
    parser.add_argument("--repo-manifest", type=Path, default=DEFAULT_REPO_MANIFEST)
    parser.add_argument("--backend", choices=BACKENDS, default=DEFAULT_BACKEND)
    parser.add_argument("--pair-id", action="append", default=[])
    parser.add_argument("--artifact-root", type=Path, default=DEFAULT_ARTIFACT_ROOT)
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--no-full", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    """
    Run the split-engine experiment.

    Parameters
    ----------
    argv : list[str] | None, optional
        Command-line arguments excluding the executable.

    Returns
    -------
    int
        Zero when all experiment phases pass.

    Raises
    ------
    OSError
        Propagates filesystem failures while writing artifacts or configs.
    ValueError
        Propagates invalid manifest, model, or backend values.
    """

    args = build_parser().parse_args(argv)
    codira = resolve_codira()
    stamp = local_stamp()
    artifact_root = args.artifact_root / stamp
    config_root = artifact_root / "configs"
    output_root = artifact_root / "outputs"
    log_root = artifact_root / "logs"
    backup_root = artifact_root / "repo-config-backups"
    results_path = artifact_root / "results.jsonl"
    artifact_root.mkdir(parents=True, exist_ok=True)

    repos = read_repositories(args.repo_manifest)
    models = model_by_id(read_models(args.model_manifest))
    compat_entries = compatibility_entries(models)
    selected_pair_ids = set(cast("list[str]", args.pair_id))
    pairs = tuple(
        pair
        for pair in load_split_pairs(args.pair_manifest)
        if not selected_pair_ids or pair.pair_id in selected_pair_ids
    )
    if not pairs:
        message = "No split pairs selected."
        raise SystemExit(message)

    env = dict(os.environ)
    env["CODIRA"] = codira
    status = 0
    with RepoConfigRestore(tuple(repo.path for repo in repos), backup_root):
        for pair in pairs:
            gate = run_gate(
                pair=pair,
                entries=compat_entries,
                artifact_root=artifact_root,
            )
            if not gate.passed:
                results_path.write_text(
                    render_result_row(
                        pair_id=pair.pair_id,
                        phase="gate",
                        passed=False,
                        min_cosine=gate.min_cosine,
                        threshold=gate.threshold,
                    ),
                    encoding="utf-8",
                )
                return 1
            index_model = models[pair.index_model]
            query_model = models[pair.query_model]
            index_config = config_root / f"{pair.pair_id}-index.toml"
            query_config = config_root / f"{pair.pair_id}-query.toml"
            write_config(index_config, index_model, args.backend)
            write_config(query_config, query_model, args.backend)
            for repo in repos:
                repo_slug = safe_slug(f"{repo.index}-{repo.label}")
                output_dir = output_root / safe_slug(pair.pair_id) / repo_slug
                target_config = repo.path / ".codira" / "config.toml"
                target_config.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(index_config, target_config)
                index_command = (
                    codira,
                    "index",
                    *(("--full",) if not args.no_full else ()),
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
                    log_path=log_root
                    / f"{safe_slug(pair.pair_id)}-{repo_slug}-index.log",
                )
                with results_path.open("a", encoding="utf-8") as results_file:
                    results_file.write(
                        render_result_row(
                            pair_id=pair.pair_id,
                            repo=repo.label,
                            backend=args.backend,
                            phase="index",
                            engine=index_model.engine,
                            elapsed_seconds=index_result.elapsed_seconds,
                            status=index_result.returncode,
                            log=str(index_result.log_path),
                        )
                    )
                if index_result.returncode:
                    status = index_result.returncode
                    continue
                aliased_rows = alias_vector_set(
                    output_dir=output_dir,
                    backend=args.backend,
                    source=index_model,
                    target=query_model,
                )
                shutil.copy2(query_config, target_config)
                with results_path.open("a", encoding="utf-8") as results_file:
                    results_file.write(
                        render_result_row(
                            pair_id=pair.pair_id,
                            repo=repo.label,
                            backend=args.backend,
                            phase="alias",
                            rows=aliased_rows,
                            source_engine=index_model.engine,
                            query_engine=query_model.engine,
                        )
                    )
                for query_index, query in enumerate(pair.queries, start=1):
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
                                str(args.limit),
                                "--path",
                                str(repo.path),
                                "--output-dir",
                                str(output_dir),
                            )
                        result = timed_command(
                            command,
                            cwd=Path.cwd(),
                            env=env,
                            log_path=log_root
                            / (
                                f"{safe_slug(pair.pair_id)}-{repo_slug}-"
                                f"{command_name}-{query_index}.log"
                            ),
                        )
                        with results_path.open("a", encoding="utf-8") as results_file:
                            results_file.write(
                                render_result_row(
                                    pair_id=pair.pair_id,
                                    repo=repo.label,
                                    backend=args.backend,
                                    phase=command_name,
                                    engine=query_model.engine,
                                    query=query,
                                    elapsed_seconds=result.elapsed_seconds,
                                    status=result.returncode,
                                    log=str(result.log_path),
                                )
                            )
                        if result.returncode and not status:
                            status = result.returncode
    print(f"Artifacts: {artifact_root}")
    print(f"Results: {results_path}")
    return status


if __name__ == "__main__":
    raise SystemExit(main())
