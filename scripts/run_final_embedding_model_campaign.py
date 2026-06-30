#!/usr/bin/env python3
"""Run the final embedding model benchmark campaign."""

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

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.scriptlib import (
    resolve_codira,
    resolve_python,
    safe_slug,
)

DEFAULT_RUNS = 5
DEFAULT_WARMUP = 1
BACKEND_MODES = ("duckdb", "sqlite", "both")
CONCRETE_BACKENDS = ("sqlite", "duckdb")


@dataclass(frozen=True)
class RepositoryEntry:
    """Repository row from the campaign manifest."""

    index: int
    label: str
    path: Path


@dataclass(frozen=True)
class ModelEntry:
    """Model row from the embedding candidate manifest."""

    id: str
    engine: str
    model: str
    version: str
    dimension: int
    precision: str
    config: dict[str, object]


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


def local_stamp() -> str:
    """
    Return the local campaign timestamp.

    Parameters
    ----------
    None

    Returns
    -------
    str
        Timestamp with timezone offset.
    """

    return datetime.now().strftime("%Y%m%dT%H%M%S%z")


def log(message: str) -> None:
    """
    Print one timestamped campaign message.

    Parameters
    ----------
    message : str
        Message body.

    Returns
    -------
    None
        The message is printed.
    """

    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S %z')}] {message}")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """
    Parse command-line arguments.

    Parameters
    ----------
    argv : list[str] | None, optional
        Command-line arguments.

    Returns
    -------
    argparse.Namespace
        Parsed arguments.
    """

    parser = argparse.ArgumentParser(
        description="Run the final embedding model campaign."
    )
    parser.add_argument("--baseline", default="")
    parser.add_argument("--manifest", default="benchmarks/uv-backed-repos.local.json")
    parser.add_argument(
        "--model-manifest", default="benchmarks/embedding-model-candidates.json"
    )
    parser.add_argument(
        "--backend",
        choices=BACKEND_MODES,
        default=os.environ.get("BACKEND_MODE", "duckdb"),
    )
    parser.add_argument(
        "--runs",
        type=positive_int,
        default=DEFAULT_RUNS,
        help="Measured Hyperfine runs per command.",
    )
    parser.add_argument(
        "--warmup",
        type=positive_int,
        default=DEFAULT_WARMUP,
        help="Hyperfine warmup runs per command.",
    )
    parser.add_argument("--preflight-only", action="store_true")
    parser.add_argument("--restart-from", default=os.environ.get("RESTART_FROM", ""))
    return parser.parse_args(argv)


def read_repositories(manifest_path: Path) -> tuple[RepositoryEntry, ...]:
    """
    Read repository entries from a manifest.

    Parameters
    ----------
    manifest_path : pathlib.Path
        Repository benchmark manifest.

    Returns
    -------
    tuple[RepositoryEntry, ...]
        Repository entries.
    """

    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    entries: list[RepositoryEntry] = []
    for index, row in enumerate(payload["repositories"], start=1):
        path = Path(row["path"]).expanduser().resolve()
        entries.append(RepositoryEntry(index, row.get("label") or path.name, path))
    return tuple(entries)


def read_models(model_manifest_path: Path) -> tuple[ModelEntry, ...]:
    """
    Read model entries from a manifest.

    Parameters
    ----------
    model_manifest_path : pathlib.Path
        Model manifest path.

    Returns
    -------
    tuple[ModelEntry, ...]
        Model entries.
    """

    payload = json.loads(model_manifest_path.read_text(encoding="utf-8"))
    return tuple(
        ModelEntry(
            id=entry["id"],
            engine=entry["engine"],
            model=entry["model"],
            version=entry["version"],
            dimension=int(entry["dimension"]),
            precision=entry.get("precision", "float32"),
            config=dict(entry.get("config", {})),
        )
        for entry in payload["models"]
    )


def safe_embedding_batch_size(model: ModelEntry) -> int:
    """
    Return the campaign batch size for one model.

    Parameters
    ----------
    model : ModelEntry
        Model entry.

    Returns
    -------
    int
        Batch size used for campaign runs.
    """

    if model.dimension >= 768:
        return 1
    if model.engine == "onnx":
        return 8
    return 32


def safe_max_text_chars(model: ModelEntry) -> int:
    """
    Return max text chars for one model.

    Parameters
    ----------
    model : ModelEntry
        Model entry.

    Returns
    -------
    int
        Max text chars, or zero for uncapped text.
    """

    return 2000 if model.dimension >= 768 else 0


def safe_onnx_threads(model: ModelEntry) -> tuple[int, int]:
    """
    Return ONNX Runtime thread limits for one model.

    Parameters
    ----------
    model : ModelEntry
        Model entry.

    Returns
    -------
    tuple[int, int]
        Intra-op and inter-op thread counts.
    """

    if model.dimension >= 768:
        return (4, 1)
    return (0, 0)


def concrete_backends(backend_mode: str) -> tuple[str, ...]:
    """
    Return concrete backend phases for a requested backend mode.

    Parameters
    ----------
    backend_mode : str
        Requested backend mode.

    Returns
    -------
    tuple[str, ...]
        Concrete backend names to run.

    Raises
    ------
    ValueError
        Raised when the backend mode is unknown.
    """

    if backend_mode == "both":
        return CONCRETE_BACKENDS
    if backend_mode in CONCRETE_BACKENDS:
        return (backend_mode,)
    msg = f"unknown backend mode: {backend_mode}"
    raise ValueError(msg)


def render_model_config(model: ModelEntry, backend_mode: str) -> str:
    """
    Render one model-specific Codira config.

    Parameters
    ----------
    model : ModelEntry
        Model entry.
    backend_mode : str
        Backend mode requested for the campaign.

    Returns
    -------
    str
        TOML configuration text.
    """

    backend_name = backend_mode
    vector_store_name = backend_name
    trust_remote_code = str(model.config.get("trust_remote_code", False)).lower()
    max_tokens = model.config.get("max_tokens", 512)
    if not isinstance(max_tokens, int):
        max_tokens = 512
    intra_op, inter_op = safe_onnx_threads(model)
    return "\n".join(
        [
            "config_version = 1",
            "",
            "[backend]",
            f'name = "{backend_name}"',
            "",
            "[plugins]",
            "disable_third_party = false",
            "disabled_analyzers = []",
            "",
            "[plugins.backend-duckdb]",
            "enabled = true",
            "profiling_enabled = true"
            if backend_name == "duckdb"
            else "profiling_enabled = false",
            "",
            "[embeddings]",
            "enabled = true",
            f'engine = "{model.engine}"',
            f'vector_store = "{vector_store_name}"',
            f'model = "{model.model}"',
            f'version = "{model.version}"',
            f"dimension = {model.dimension}",
            'device = "cpu"',
            f"batch_size = {safe_embedding_batch_size(model)}",
            "torch_num_threads = 4"
            if model.dimension >= 768
            else "torch_num_threads = 0",
            "torch_num_interop_threads = 1"
            if model.dimension >= 768
            else "torch_num_interop_threads = 0",
            "",
            "[embeddings.gpu]",
            "device_id = 0",
            "memory_limit_mb = 0",
            "",
            "[embeddings.indexing]",
            'mode = "immediate"',
            'object_types = ["symbol", "documentation"]',
            f"max_text_chars = {safe_max_text_chars(model)}",
            "include_paths = []",
            "exclude_paths = []",
            "",
            "[plugins.embedding-sentence-transformers]",
            "enabled = true",
            f"trust_remote_code = {trust_remote_code}",
            "",
            "[plugins.embedding-onnx]",
            "enabled = true",
            f'precision = "{model.precision}"',
            f'model_path = "{model.config.get("model_path", "")}"',
            f'tokenizer_path = "{model.config.get("tokenizer_path", "")}"',
            f'provider = "{model.config.get("provider", "CPUExecutionProvider")}"',
            "normalize = true",
            f"max_tokens = {max_tokens}",
            f"intra_op_num_threads = {intra_op}",
            f"inter_op_num_threads = {inter_op}",
            "",
            "[plugins.vector-store-sqlite]",
            "enabled = true",
            "",
            "[plugins.vector-store-duckdb]",
            "enabled = true",
            "",
        ]
    )


def write_run_metadata(  # noqa: PLR0913
    *,
    metadata_root: Path,
    manifest_path: Path,
    model_manifest_path: Path,
    baseline_path: str,
    backend_mode: str,
    stamp: str,
    matrix_root: Path,
    python: str,
    codira: str,
    runs: int,
    warmup: int,
) -> None:
    """
    Write campaign metadata files.

    Parameters
    ----------
    metadata_root : pathlib.Path
        Metadata directory.
    manifest_path : pathlib.Path
        Repository manifest.
    model_manifest_path : pathlib.Path
        Model manifest.
    baseline_path : str
        Optional baseline path.
    backend_mode : str
        Backend mode.
    stamp : str
        Campaign stamp.
    matrix_root : pathlib.Path
        Matrix artifact root.
    python : str
        Python executable.
    codira : str
        Codira executable.
    runs : int
        Measured Hyperfine runs per command.
    warmup : int
        Hyperfine warmup runs per command.

    Returns
    -------
    None
        Metadata files are written.
    """

    metadata_root.mkdir(parents=True, exist_ok=True)
    baseline_label = (
        str(Path(baseline_path).resolve()) if baseline_path else "not provided"
    )
    (metadata_root / "baseline-path.txt").write_text(
        f"{baseline_label}\n", encoding="utf-8"
    )
    shutil.copy2(manifest_path, metadata_root / "repository-manifest.json")
    shutil.copy2(model_manifest_path, metadata_root / "model-manifest.json")
    (metadata_root / "environment.txt").write_text(
        "\n".join(
            [
                f"BACKEND_MODE={backend_mode}",
                f"CODIRA={codira}",
                f"CODIRA_EMBED_BATCH_SIZE={os.environ.get('CODIRA_EMBED_BATCH_SIZE', '')}",
                f"PYTHON={python}",
                f"RUNS={runs}",
                f"STAMP={stamp}",
                f"WARMUP={warmup}",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (metadata_root / "run-state.env").write_text(
        "\n".join(
            [
                f"BASELINE_PATH={baseline_label}",
                f"MANIFEST_PATH={manifest_path.resolve()}",
                f"MODEL_MANIFEST_PATH={model_manifest_path.resolve()}",
                f"BACKEND_MODE={backend_mode}",
                f"STAMP={stamp}",
                f"ARTIFACT_ROOT={matrix_root.parent.resolve()}",
                f"PYTHON={python}",
                f"CODIRA={codira}",
                f"RUNS={runs}",
                f"WARMUP={warmup}",
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def write_single_repo_manifest(
    source: Path, repo: RepositoryEntry, output_path: Path
) -> None:
    """
    Write a single-repository manifest.

    Parameters
    ----------
    source : pathlib.Path
        Source manifest.
    repo : RepositoryEntry
        Repository entry to select.
    output_path : pathlib.Path
        Output manifest path.

    Returns
    -------
    None
        Manifest is written.
    """

    payload = json.loads(source.read_text(encoding="utf-8"))
    payload["repositories"] = [payload["repositories"][repo.index - 1]]
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def find_checkpoint_root(label: str, search_root: Path) -> Path | None:
    """
    Find the campaign root containing a checkpoint label.

    Parameters
    ----------
    label : str
        Checkpoint label.
    search_root : pathlib.Path
        Root to search.

    Returns
    -------
    pathlib.Path | None
        Campaign root, when found.
    """

    for index_path in sorted(search_root.glob("*/checkpoints/index.tsv"), reverse=True):
        for line in index_path.read_text(encoding="utf-8").splitlines()[1:]:
            if line.split("\t", 1)[0] == label:
                return index_path.parents[1]
    return None


def append_checkpoint(  # noqa: PLR0913
    index_path: Path,
    labels_path: Path,
    *,
    label: str,
    model: ModelEntry,
    backend_mode: str,
    repo: RepositoryEntry,
    status: int,
    log_path: Path,
) -> None:
    """
    Append a successful checkpoint.

    Parameters
    ----------
    index_path : pathlib.Path
        Checkpoint index path.
    labels_path : pathlib.Path
        Checkpoint labels path.
    label : str
        Checkpoint label.
    model : ModelEntry
        Completed model.
    backend_mode : str
        Backend mode.
    repo : RepositoryEntry
        Completed repository.
    status : int
        Completed status.
    log_path : pathlib.Path
        Log path.

    Returns
    -------
    None
        Checkpoint files are appended.
    """

    labels_path.write_text(
        labels_path.read_text(encoding="utf-8") + f"{label}\n"
        if labels_path.exists()
        else f"{label}\n",
        encoding="utf-8",
    )
    with index_path.open("a", encoding="utf-8") as index_file:
        index_file.write(
            "\t".join(
                [
                    label,
                    datetime.now().strftime("%Y-%m-%d %H:%M:%S %z"),
                    model.id,
                    backend_mode,
                    str(repo.index),
                    repo.label,
                    str(repo.path),
                    str(status),
                    str(log_path),
                ]
            )
            + "\n"
        )
    log(f"Checkpoint written: {label}")


def run_repo_campaign(  # noqa: PLR0913
    *,
    model: ModelEntry,
    repo: RepositoryEntry,
    backend: str,
    config_root: Path,
    metadata_root: Path,
    campaign_root: Path,
    log_root: Path,
    stamp: str,
    manifest_path: Path,
    python: str,
    codira: str,
    labels_path: Path,
    checkpoint_index: Path,
    restart_from: str,
    restart_seen: bool,
    runs: int,
    warmup: int,
) -> tuple[int, bool]:
    """
    Run one model/repository campaign phase.

    Parameters
    ----------
    model : ModelEntry
        Model entry.
    repo : RepositoryEntry
        Repository entry.
    backend : str
        Concrete backend name.
    config_root : pathlib.Path
        Generated config root.
    metadata_root : pathlib.Path
        Metadata root.
    campaign_root : pathlib.Path
        Campaign artifact root.
    log_root : pathlib.Path
        Log root.
    stamp : str
        Campaign stamp.
    manifest_path : pathlib.Path
        Repository manifest.
    python : str
        Python executable.
    codira : str
        Codira executable.
    labels_path : pathlib.Path
        Checkpoint labels path.
    checkpoint_index : pathlib.Path
        Checkpoint index path.
    restart_from : str
        Restart label.
    restart_seen : bool
        Whether the restart point has been reached.
    runs : int
        Measured Hyperfine runs per command.
    warmup : int
        Hyperfine warmup runs per command.

    Returns
    -------
    tuple[int, bool]
        Phase status and updated restart flag.
    """

    repo_slug = safe_slug(f"{repo.index}-{repo.label}")
    model_slug = safe_slug(model.id)
    label = f"ckpt_{stamp}_{model_slug}_{backend}_{repo_slug}"
    if restart_from and not restart_seen:
        if label == restart_from:
            log(f"Restart point reached; skipping completed checkpoint: {label}")
            return (0, True)
        log(f"Skipping before restart point: model={model.id} repo={repo.label}")
        return (0, False)
    checkpoint_rows = checkpoint_index.read_text(encoding="utf-8").splitlines()
    if any(row.split("\t", 1)[0] == label for row in checkpoint_rows[1:]):
        log(f"Skipping already checkpointed phase: {label}")
        return (0, restart_seen)

    config_file = config_root / f"{model.id}-{backend}.toml"
    repo_manifest = metadata_root / "single-repo-manifests" / f"{repo_slug}.json"
    write_single_repo_manifest(manifest_path, repo, repo_manifest)
    log_path = log_root / f"{model_slug}-{backend}-{repo_slug}.log"
    repo_stamp = f"{stamp}-{model_slug}-{backend}-{repo_slug}"
    backend_args = {
        "duckdb": ["--duckdb-only"],
        "sqlite": ["--sqlite-only"],
    }[backend]
    env = dict(os.environ)
    env.update(
        {
            "ARTIFACT_ROOT": str(campaign_root),
            "STAMP": repo_stamp,
            "PYTHON": python,
            "CODIRA": codira,
            "CODIRA_EMBED_BATCH_SIZE": str(safe_embedding_batch_size(model)),
            "CODIRA_TORCH_NUM_THREADS": "4"
            if model.dimension >= 768
            else os.environ.get("CODIRA_TORCH_NUM_THREADS", "10"),
            "CODIRA_TORCH_NUM_INTEROP_THREADS": "1"
            if model.dimension >= 768
            else os.environ.get("CODIRA_TORCH_NUM_INTEROP_THREADS", "1"),
        }
    )
    log(
        f"Phase started: model={model.id} backend={backend} repo={repo.label} path={repo.path}"
    )
    with log_path.open("w", encoding="utf-8") as log_file:
        status = subprocess.call(
            [
                python,
                "-m",
                "scripts.run_manifest_baseline",
                *backend_args,
                "--runs",
                str(runs),
                "--warmup",
                str(warmup),
                str(repo_manifest),
                "--config-file",
                str(config_file),
            ],
            stdout=log_file,
            stderr=subprocess.STDOUT,
            env=env,
        )
    (metadata_root / f"{model_slug}-{backend}-{repo_slug}.status").write_text(
        f"{status}\n", encoding="utf-8"
    )
    log(
        f"Phase completed: model={model.id} backend={backend} repo={repo.label} status={status}; log={log_path}"
    )
    if status == 0:
        append_checkpoint(
            checkpoint_index,
            labels_path,
            label=label,
            model=model,
            backend_mode=backend,
            repo=repo,
            status=status,
            log_path=log_path,
        )
    else:
        log(
            f"No checkpoint written for failed phase: model={model.id} backend={backend} repo={repo.label} status={status}"
        )
    return (status, restart_seen)


def write_readme(  # noqa: PLR0913
    *,
    matrix_root: Path,
    metadata_root: Path,
    labels_path: Path,
    checkpoint_index: Path,
    manifest_path: Path,
    model_manifest_path: Path,
    backend_mode: str,
    runs: int,
    warmup: int,
) -> None:
    """
    Write campaign README.

    Parameters
    ----------
    matrix_root : pathlib.Path
        Campaign root.
    metadata_root : pathlib.Path
        Metadata root.
    labels_path : pathlib.Path
        Checkpoint labels path.
    checkpoint_index : pathlib.Path
        Checkpoint index path.
    manifest_path : pathlib.Path
        Repository manifest.
    model_manifest_path : pathlib.Path
        Model manifest.
    backend_mode : str
        Backend mode.
    runs : int
        Measured Hyperfine runs per command.
    warmup : int
        Hyperfine warmup runs per command.

    Returns
    -------
    None
        README is written.
    """

    last_label = labels_path.read_text(encoding="utf-8").splitlines()[-1:] or [""]
    lines = [
        "# Final embedding model campaign",
        "",
        f"- Baseline: {metadata_root.joinpath('baseline-path.txt').read_text(encoding='utf-8').strip()}",
        f"- Repository manifest: {manifest_path}",
        f"- Model manifest: {model_manifest_path}",
        f"- Backend mode: {backend_mode}",
        f"- Concrete backends: {', '.join(concrete_backends(backend_mode))}",
        f"- Runs: {runs}",
        f"- Warmup: {warmup}",
        f"- Checkpoint labels: {labels_path}",
        f"- Checkpoint metadata: {checkpoint_index}",
        "",
        f"Artifacts are under `{matrix_root}`.",
        "",
        "Restart from the last completed phase with:",
        "",
        "```bash",
        f"uv run python -m scripts.run_final_embedding_model_campaign --restart-from '{last_label[0]}'",
        "```",
    ]
    (matrix_root / "README.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:  # noqa: C901, PLR0912
    """
    Run the final embedding model campaign.

    Parameters
    ----------
    argv : list[str] | None, optional
        Command-line arguments.

    Returns
    -------
    int
        Process exit status.

    Raises
    ------
    SystemExit
        Raised when required manifest paths or restart metadata are invalid.
    """

    args = parse_args(argv)
    python = resolve_python()
    codira = resolve_codira()
    artifact_root = Path(
        os.environ.get("ARTIFACT_ROOT", ".artifacts/final-embedding-model-campaign")
    )
    restart_from = args.restart_from

    if restart_from:
        matrix_root = find_checkpoint_root(restart_from, artifact_root)
        if matrix_root is None:
            message = (
                f"ERROR: checkpoint label not found under {artifact_root}: "
                f"{restart_from}"
            )
            raise SystemExit(message)
        run_state = {
            key: value
            for key, value in (
                line.split("=", 1)
                for line in (matrix_root / "metadata" / "run-state.env")
                .read_text(encoding="utf-8")
                .splitlines()
                if "=" in line
            )
        }
        manifest_path = Path(run_state["MANIFEST_PATH"])
        model_manifest_path = Path(run_state["MODEL_MANIFEST_PATH"])
        backend_mode = run_state["BACKEND_MODE"]
        stamp = run_state["STAMP"]
        runs = int(run_state["RUNS"])
        warmup = int(run_state["WARMUP"])
        log(f"Restart requested from checkpoint label: {restart_from}")
        log(f"Restart artifacts: {matrix_root}")
    else:
        manifest_path = Path(args.manifest)
        model_manifest_path = Path(args.model_manifest)
        backend_mode = args.backend
        runs = args.runs
        warmup = args.warmup
        stamp = os.environ.get("STAMP", local_stamp())
        matrix_root = artifact_root / stamp

    config_root = matrix_root / "configs"
    metadata_root = matrix_root / "metadata"
    campaign_root = matrix_root / "campaigns"
    log_root = matrix_root / "logs"
    checkpoint_root = matrix_root / "checkpoints"
    for path in (
        config_root,
        metadata_root,
        campaign_root,
        log_root,
        checkpoint_root,
    ):
        path.mkdir(parents=True, exist_ok=True)

    if not manifest_path.is_file():
        message = f"ERROR: repository manifest not found: {manifest_path}"
        raise SystemExit(message)
    if not model_manifest_path.is_file():
        message = f"ERROR: model manifest not found: {model_manifest_path}"
        raise SystemExit(message)
    if args.baseline and not Path(args.baseline).exists():
        message = f"ERROR: baseline path does not exist: {args.baseline}"
        raise SystemExit(message)

    labels_path = checkpoint_root / "labels.txt"
    checkpoint_index = checkpoint_root / "index.tsv"
    if not checkpoint_index.exists():
        checkpoint_index.write_text(
            "label\tcompleted_at_local\tmodel_id\tbackend\trepo_index\trepo_label\trepo_path\tstatus\tlog_path\n",
            encoding="utf-8",
        )
    labels_path.touch()

    if not restart_from:
        write_run_metadata(
            metadata_root=metadata_root,
            manifest_path=manifest_path,
            model_manifest_path=model_manifest_path,
            baseline_path=args.baseline,
            backend_mode=backend_mode,
            stamp=stamp,
            matrix_root=matrix_root,
            python=python,
            codira=codira,
            runs=runs,
            warmup=warmup,
        )

    log(f"Campaign artifacts: {matrix_root}")
    log(f"Checkpoint labels: {labels_path}")
    log(f"Checkpoint metadata: {checkpoint_index}")

    if not restart_from:
        log("Preflight started: download and smoke-test embedding models")
        with (log_root / "model-download-preflight.log").open(
            "w", encoding="utf-8"
        ) as log_file:
            preflight_status = subprocess.call(
                [
                    python,
                    "scripts/download_embedding_model.py",
                    "--manifest",
                    str(model_manifest_path),
                ],
                stdout=log_file,
                stderr=subprocess.STDOUT,
            )
        log(
            f"Preflight completed status={preflight_status}; log={log_root / 'model-download-preflight.log'}"
        )
        if preflight_status:
            return preflight_status
    else:
        log("Preflight skipped on restart")

    if args.preflight_only:
        log(f"Preflight artifacts: {matrix_root}")
        return 0

    repos = read_repositories(manifest_path)
    models = read_models(model_manifest_path)
    (metadata_root / "manifest-repositories.tsv").write_text(
        "".join(f"{repo.index}\t{repo.label}\t{repo.path}\n" for repo in repos),
        encoding="utf-8",
    )
    (metadata_root / "manifest-repositories.txt").write_text(
        "".join(f"{repo.path}\n" for repo in repos),
        encoding="utf-8",
    )
    (metadata_root / "model-ids.txt").write_text(
        "".join(f"{model.id}\n" for model in models),
        encoding="utf-8",
    )
    for model in models:
        for backend in concrete_backends(backend_mode):
            (config_root / f"{model.id}-{backend}.toml").write_text(
                render_model_config(model, backend),
                encoding="utf-8",
            )

    status = 0
    restart_seen = not bool(restart_from)
    for model in models:
        log(f"Model campaign started: {model.id} backend={backend_mode}")
        for backend in concrete_backends(backend_mode):
            log(f"Backend campaign started: model={model.id} backend={backend}")
            for repo in repos:
                rc, restart_seen = run_repo_campaign(
                    model=model,
                    repo=repo,
                    backend=backend,
                    config_root=config_root,
                    metadata_root=metadata_root,
                    campaign_root=campaign_root,
                    log_root=log_root,
                    stamp=stamp,
                    manifest_path=manifest_path,
                    python=python,
                    codira=codira,
                    labels_path=labels_path,
                    checkpoint_index=checkpoint_index,
                    restart_from=restart_from,
                    restart_seen=restart_seen,
                    runs=runs,
                    warmup=warmup,
                )
                if rc and not status:
                    status = rc
            log(
                f"Backend campaign completed: model={model.id} backend={backend} current_status={status}"
            )
        log(f"Model campaign completed: {model.id} current_status={status}")

    if restart_from and not restart_seen:
        message = (
            f"ERROR: restart label was not reached during traversal: {restart_from}"
        )
        raise SystemExit(message)

    write_readme(
        matrix_root=matrix_root,
        metadata_root=metadata_root,
        labels_path=labels_path,
        checkpoint_index=checkpoint_index,
        manifest_path=manifest_path,
        model_manifest_path=model_manifest_path,
        backend_mode=backend_mode,
        runs=runs,
        warmup=warmup,
    )
    log(f"Final campaign artifacts: {matrix_root}")
    log(f"Checkpoint labels: {labels_path}")
    return status


if __name__ == "__main__":
    raise SystemExit(main())
