"""Download and smoke-test Codira embedding model artifacts."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import cast

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

if any(arg in {"-h", "--help"} for arg in sys.argv[1:]):
    print(
        "Usage: python scripts/download_embedding_model.py [options]\n\n"
        "Download and smoke-test Codira embedding model artifacts.\n"
        "Use `uv run python scripts/download_embedding_model.py --help` for "
        "the environment-backed full option list."
    )
    raise SystemExit(0)

from codira.contracts import EmbeddingEngineError

DEFAULT_MANIFEST = Path("benchmarks/embedding-model-candidates.json")
DEFAULT_TOKEN_FILE = Path.home() / ".hf_token"
DEFAULT_INSTALL_ROOT = Path(".codira/models")
DEFAULT_ONNX_MODEL_FILENAME = "onnx/model.onnx"
DEFAULT_TOKENIZER_FILENAME = "tokenizer.json"
SMOKE_TEXTS = [
    "schema migration constraints",
    "embedding retrieval for source code",
]


@dataclass(frozen=True)
class ModelEntry:
    """
    One embedding model manifest entry.

    Parameters
    ----------
    model_id : str
        Stable benchmark model identifier.
    engine : str
        Embedding engine name.
    model : str
        Hugging Face model repository.
    dimension : int
        Expected embedding vector dimension.
    config : dict[str, object]
        Engine-specific benchmark configuration.
    """

    model_id: str
    engine: str
    model: str
    dimension: int
    config: dict[str, object]


def read_hf_token(token_file: Path = DEFAULT_TOKEN_FILE) -> str:
    """
    Read the Hugging Face token from a shell-style token file.

    Parameters
    ----------
    token_file : pathlib.Path, optional
        File containing an ``HF_TOKEN`` or ``export HF_TOKEN=...`` assignment.

    Returns
    -------
    str
        Hugging Face access token.

    Raises
    ------
    FileNotFoundError
        Raised when the token file does not exist.
    ValueError
        Raised when no usable token is present.
    """
    if token_file.exists():
        completed = subprocess.run(
            [
                "/usr/bin/env",
                "bash",
                "-c",
                'source "$1"; printf "%s" "${HF_TOKEN:-}"',
                "codira-hf-token",
                str(token_file),
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        if completed.returncode != 0:
            detail = completed.stderr.strip() or f"exit status {completed.returncode}"
            msg = f"Failed to source Hugging Face token file {token_file}: {detail}"
            raise ValueError(msg)
        token = completed.stdout.strip()
        if token:
            return token
    env_token = os.environ.get("HF_TOKEN", "").strip()
    if env_token:
        return env_token
    msg = f"No HF_TOKEN assignment found in {token_file}"
    raise ValueError(msg)


def load_manifest_entries(manifest: Path) -> list[ModelEntry]:
    """
    Load model entries from the benchmark manifest.

    Parameters
    ----------
    manifest : pathlib.Path
        JSON model manifest path.

    Returns
    -------
    list[ModelEntry]
        Parsed model entries in manifest order.
    """
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    return [
        ModelEntry(
            model_id=str(entry["id"]),
            engine=str(entry["engine"]),
            model=str(entry["model"]),
            dimension=int(entry["dimension"]),
            config=dict(cast("dict[str, object]", entry.get("config", {}))),
        )
        for entry in payload["models"]
    ]


def _entry_destination(entry: ModelEntry, install_root: Path) -> Path:
    """
    Return the local artifact directory for one manifest entry.

    Parameters
    ----------
    entry : ModelEntry
        Manifest entry to install.
    install_root : pathlib.Path
        Root directory for local model artifacts.

    Returns
    -------
    pathlib.Path
        Local model artifact directory.
    """
    model_path = entry.config.get("model_path")
    if isinstance(model_path, str) and model_path:
        return Path(model_path).parent
    return install_root / entry.model.rsplit("/", 1)[-1]


def _file_sha256(path: Path) -> str:
    """
    Return the SHA-256 digest for one file.

    Parameters
    ----------
    path : pathlib.Path
        File to hash.

    Returns
    -------
    str
        Hex-encoded SHA-256 digest.
    """

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _install_artifact(source: Path, target: Path) -> None:
    """
    Install one artifact unless the target already has the same hash.

    Parameters
    ----------
    source : pathlib.Path
        Downloaded source artifact.
    target : pathlib.Path
        Runtime artifact path configured in the model manifest.

    Returns
    -------
    None
        The target file exists and matches the source hash.
    """

    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and _file_sha256(source) == _file_sha256(target):
        return
    target.write_bytes(source.read_bytes())


def _download_onnx_entry(entry: ModelEntry, token: str, install_root: Path) -> None:
    """
    Download ONNX artifacts for one manifest entry.

    Parameters
    ----------
    entry : ModelEntry
        ONNX manifest entry to download.
    token : str
        Hugging Face access token.
    install_root : pathlib.Path
        Root directory for model artifacts.

    Returns
    -------
    None
        ONNX model and tokenizer files are installed locally.
    """
    from huggingface_hub import hf_hub_download

    destination = _entry_destination(entry, install_root)
    destination.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=f"codira-{entry.model_id}-") as temp_root:
        download_root = Path(temp_root)
        hf_hub_download(
            repo_id=entry.model,
            filename=str(
                entry.config.get("hf_onnx_model_file", DEFAULT_ONNX_MODEL_FILENAME)
            ),
            token=token,
            local_dir=download_root,
        )
        model_source = download_root / DEFAULT_ONNX_MODEL_FILENAME
        model_target = Path(str(entry.config["model_path"]))
        _install_artifact(model_source, model_target)
        hf_hub_download(
            repo_id=entry.model,
            filename=str(
                entry.config.get("hf_tokenizer_file", DEFAULT_TOKENIZER_FILENAME)
            ),
            token=token,
            local_dir=download_root,
        )
        tokenizer_source = download_root / DEFAULT_TOKENIZER_FILENAME
        tokenizer_target = Path(str(entry.config["tokenizer_path"]))
        _install_artifact(tokenizer_source, tokenizer_target)


def _download_sentence_transformers_entry(entry: ModelEntry, token: str) -> None:
    """
    Download SentenceTransformers artifacts for one manifest entry.

    Parameters
    ----------
    entry : ModelEntry
        SentenceTransformers manifest entry to download.
    token : str
        Hugging Face access token.

    Returns
    -------
    None
        The model snapshot is present in the Hugging Face cache.
    """
    from huggingface_hub import snapshot_download

    snapshot_download(
        repo_id=entry.model,
        token=token,
        ignore_patterns=["*.safetensors.index.json"],
    )


def download_entry(entry: ModelEntry, token: str, install_root: Path) -> None:
    """
    Download model artifacts for one manifest entry.

    Parameters
    ----------
    entry : ModelEntry
        Manifest entry to download.
    token : str
        Hugging Face access token.
    install_root : pathlib.Path
        Root directory for local ONNX artifacts.

    Returns
    -------
    None
        Required model files are available locally.

    Raises
    ------
    ValueError
        Raised when the manifest entry uses an unsupported embedding engine.
    """
    if entry.engine == "onnx":
        _download_onnx_entry(entry, token, install_root)
        return
    if entry.engine == "sentence-transformers":
        _download_sentence_transformers_entry(entry, token)
        return
    msg = f"Unsupported embedding engine in manifest: {entry.engine}"
    raise ValueError(msg)


def smoke_test_entry(entry: ModelEntry) -> None:
    """
    Run a small embedding smoke test for one manifest entry.

    Parameters
    ----------
    entry : ModelEntry
        Manifest entry to smoke-test.

    Returns
    -------
    None
        Raises when the model cannot produce vectors with the expected
        dimension.

    Raises
    ------
    ValueError
        Raised when the manifest entry uses an unsupported embedding engine.
    codira.contracts.EmbeddingEngineError
        Raised when the smoke test output shape is invalid.
    """
    if entry.engine == "onnx":
        from codira_embedding_onnx import OnnxEmbeddingEngine

        engine = OnnxEmbeddingEngine()
        engine.provision(entry.config, quiet=True)
        vectors = engine.embed_texts(SMOKE_TEXTS, entry.config)
    elif entry.engine == "sentence-transformers":
        from sentence_transformers import SentenceTransformer

        model = SentenceTransformer(
            entry.model,
            device="cpu",
            trust_remote_code=bool(entry.config.get("trust_remote_code", False)),
            local_files_only=True,
        )
        vectors_array = model.encode(
            SMOKE_TEXTS,
            convert_to_numpy=True,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        vectors = cast("list[list[float]]", vectors_array.tolist())
    else:
        msg = f"Unsupported embedding engine in manifest: {entry.engine}"
        raise ValueError(msg)
    if len(vectors) != len(SMOKE_TEXTS):
        msg = f"{entry.model_id} returned {len(vectors)} vectors."
        raise EmbeddingEngineError(msg)
    bad_dimensions = [
        len(vector) for vector in vectors if len(vector) != entry.dimension
    ]
    if bad_dimensions:
        msg = (
            f"{entry.model_id} returned vector dimensions {bad_dimensions}; "
            f"expected {entry.dimension}."
        )
        raise EmbeddingEngineError(msg)


def _selected_entries(
    entries: list[ModelEntry], selected_ids: set[str]
) -> list[ModelEntry]:
    """
    Filter manifest entries by selected identifiers.

    Parameters
    ----------
    entries : list[ModelEntry]
        Manifest entries.
    selected_ids : set[str]
        Requested model identifiers.

    Returns
    -------
    list[ModelEntry]
        Selected entries in manifest order.

    Raises
    ------
    SystemExit
        Raised when one or more requested model identifiers are absent from
        the manifest.
    """
    if not selected_ids:
        return entries
    known_ids = {entry.model_id for entry in entries}
    missing = sorted(selected_ids.difference(known_ids))
    if missing:
        msg = f"Unknown model ids: {', '.join(missing)}"
        raise ValueError(msg)
    return [entry for entry in entries if entry.model_id in selected_ids]


def build_parser() -> argparse.ArgumentParser:
    """
    Build the command-line parser.

    Parameters
    ----------
    None

    Returns
    -------
    argparse.ArgumentParser
        Parser for the model download script.
    """
    parser = argparse.ArgumentParser(
        description="Download and smoke-test Codira embedding model artifacts.",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=DEFAULT_MANIFEST,
        help=f"Model manifest path. Default: {DEFAULT_MANIFEST}",
    )
    parser.add_argument(
        "--model-id",
        action="append",
        default=[],
        help="Model id to download. Repeat to select multiple ids. Default: all.",
    )
    parser.add_argument(
        "--token-file",
        type=Path,
        default=DEFAULT_TOKEN_FILE,
        help=f"Hugging Face token file. Default: {DEFAULT_TOKEN_FILE}",
    )
    parser.add_argument(
        "--install-root",
        type=Path,
        default=DEFAULT_INSTALL_ROOT,
        help=f"Local ONNX artifact root. Default: {DEFAULT_INSTALL_ROOT}",
    )
    parser.add_argument(
        "--skip-smoke",
        action="store_true",
        help="Download artifacts without running embedding smoke tests.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """
    Run the model download command.

    Parameters
    ----------
    argv : list[str] | None, optional
        Command-line arguments excluding the executable name.

    Returns
    -------
    int
        Process exit status.
    """
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        token = read_hf_token(args.token_file)
        os.environ["HF_TOKEN"] = token
        entries = _selected_entries(
            load_manifest_entries(args.manifest),
            set(args.model_id),
        )
        for entry in entries:
            print(f"[codira] downloading {entry.model_id}", file=sys.stderr)
            download_entry(entry, token, args.install_root)
            if not args.skip_smoke:
                print(f"[codira] smoke testing {entry.model_id}", file=sys.stderr)
                smoke_test_entry(entry)
    except (
        EmbeddingEngineError,
        FileNotFoundError,
        ImportError,
        OSError,
        ValueError,
    ) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
