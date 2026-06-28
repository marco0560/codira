"""Compare embedding engine vector compatibility for manifest entries."""

from __future__ import annotations

import argparse
import json
import math
import sys
from dataclasses import dataclass
from importlib import import_module
from pathlib import Path
from typing import Any, cast

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

DEFAULT_MANIFEST = Path("benchmarks/embedding-model-candidates.json")
DEFAULT_CORPUS = (
    "schema migration constraints",
    "embedding retrieval for source code",
    "numpy docstring validation",
    "duckdb vector persistence",
    "configuration precedence and plugin loading",
)
DEFAULT_THRESHOLD = 0.99


@dataclass(frozen=True)
class ModelEntry:
    """
    Embedding model manifest entry used for compatibility checks.

    Parameters
    ----------
    model_id : str
        Stable manifest identifier.
    engine : str
        Engine name, such as ``"onnx"`` or ``"sentence-transformers"``.
    model : str
        Model repository or local model identifier.
    version : str
        Operator-managed model version.
    dimension : int
        Expected vector dimension.
    precision : str
        Expected vector precision label.
    config : dict[str, object]
        Engine-specific configuration.
    """

    model_id: str
    engine: str
    model: str
    version: str
    dimension: int
    precision: str
    config: dict[str, object]


@dataclass(frozen=True)
class ComparisonResult:
    """
    Vector compatibility comparison result.

    Parameters
    ----------
    left : ModelEntry
        Left manifest entry.
    right : ModelEntry
        Right manifest entry.
    corpus_size : int
        Number of compared texts.
    threshold : float
        Minimum acceptable cosine similarity.
    dimensions_match : bool
        Whether manifest dimensions and produced vector dimensions match.
    identity_matches : bool
        Whether model identity fields match.
    min_cosine : float
        Minimum pairwise cosine similarity.
    mean_cosine : float
        Mean pairwise cosine similarity.
    passed : bool
        Whether every compatibility gate passed.
    """

    left: ModelEntry
    right: ModelEntry
    corpus_size: int
    threshold: float
    dimensions_match: bool
    identity_matches: bool
    min_cosine: float
    mean_cosine: float
    passed: bool


def load_manifest_entries(path: Path) -> dict[str, ModelEntry]:
    """
    Load embedding model entries from a benchmark manifest.

    Parameters
    ----------
    path : pathlib.Path
        JSON manifest path.

    Returns
    -------
    dict[str, ModelEntry]
        Manifest entries keyed by model id.
    """

    payload = json.loads(path.read_text(encoding="utf-8"))
    entries: dict[str, ModelEntry] = {}
    for item in payload["models"]:
        entry = ModelEntry(
            model_id=str(item["id"]),
            engine=str(item["engine"]),
            model=str(item["model"]),
            version=str(item.get("version", "1")),
            dimension=int(item["dimension"]),
            precision=str(item.get("precision", "float32")),
            config=dict(cast("dict[str, object]", item.get("config", {}))),
        )
        entries[entry.model_id] = entry
    return entries


def load_corpus(path: Path | None) -> list[str]:
    """
    Load comparison texts from a file or return the default fixed corpus.

    Parameters
    ----------
    path : pathlib.Path | None
        Optional UTF-8 text file with one comparison text per non-blank line.

    Returns
    -------
    list[str]
        Non-empty comparison texts.

    Raises
    ------
    ValueError
        Raised when a supplied corpus file contains no non-blank lines.
    """

    if path is None:
        return list(DEFAULT_CORPUS)
    lines = [
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if not lines:
        msg = f"Corpus file is empty: {path}"
        raise ValueError(msg)
    return lines


def cosine_similarity(left: list[float], right: list[float]) -> float:
    """
    Return cosine similarity for two vectors.

    Parameters
    ----------
    left : list[float]
        Left vector.
    right : list[float]
        Right vector.

    Returns
    -------
    float
        Cosine similarity, or ``0.0`` when either vector has zero norm.
    """

    if len(left) != len(right):
        return 0.0
    dot = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if left_norm == 0.0 or right_norm == 0.0:
        return 0.0
    return dot / (left_norm * right_norm)


def _engine_config(entry: ModelEntry) -> dict[str, object]:
    """
    Build engine config with core identity metadata injected.

    Parameters
    ----------
    entry : ModelEntry
        Manifest entry.

    Returns
    -------
    dict[str, object]
        Engine configuration passed to plugin-compatible engines.
    """

    config = dict(entry.config)
    config["_codira_model"] = entry.model
    config["_codira_model_version"] = entry.version
    config["_codira_dimension"] = entry.dimension
    config.setdefault("_codira_batch_size", 1)
    return config


def embed_manifest_entry(entry: ModelEntry, texts: list[str]) -> list[list[float]]:
    """
    Embed comparison texts for one manifest entry.

    Parameters
    ----------
    entry : ModelEntry
        Manifest entry selecting an embedding engine and model.
    texts : list[str]
        Comparison corpus.

    Returns
    -------
    list[list[float]]
        One vector per text.

    Raises
    ------
    ValueError
        Raised for unsupported engines.
    """

    if entry.engine == "onnx":
        from codira_embedding_onnx import OnnxEmbeddingEngine

        engine = OnnxEmbeddingEngine()
        config = _engine_config(entry)
        engine.provision(config, quiet=True)
        return engine.embed_texts(texts, config)
    if entry.engine == "sentence-transformers":
        SentenceTransformer = import_module("sentence_transformers").SentenceTransformer
        model = SentenceTransformer(
            entry.model,
            device="cpu",
            trust_remote_code=bool(entry.config.get("trust_remote_code", False)),
            local_files_only=True,
        )
        vectors = model.encode(
            texts,
            convert_to_numpy=True,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        return cast("list[list[float]]", vectors.tolist())
    msg = f"Unsupported embedding engine: {entry.engine}"
    raise ValueError(msg)


def compare_vectors(
    left: ModelEntry,
    right: ModelEntry,
    left_vectors: list[list[float]],
    right_vectors: list[list[float]],
    *,
    threshold: float,
) -> ComparisonResult:
    """
    Compare two vector sets for compatibility.

    Parameters
    ----------
    left : ModelEntry
        Left manifest entry.
    right : ModelEntry
        Right manifest entry.
    left_vectors : list[list[float]]
        Vectors produced by the left engine.
    right_vectors : list[list[float]]
        Vectors produced by the right engine.
    threshold : float
        Minimum accepted cosine similarity for every pair.

    Returns
    -------
    ComparisonResult
        Structured compatibility result.

    Raises
    ------
    ValueError
        Raised when vector counts do not match.
    """

    if len(left_vectors) != len(right_vectors):
        msg = "Engine outputs contain different vector counts."
        raise ValueError(msg)
    dimensions_match = (
        left.dimension == right.dimension
        and all(len(vector) == left.dimension for vector in left_vectors)
        and all(len(vector) == right.dimension for vector in right_vectors)
    )
    identity_matches = (
        left.model == right.model
        and left.version == right.version
        and left.precision == right.precision
    )
    cosines = [
        cosine_similarity(left_vector, right_vector)
        for left_vector, right_vector in zip(left_vectors, right_vectors, strict=True)
    ]
    min_cosine = min(cosines) if cosines else 0.0
    mean_cosine = sum(cosines) / len(cosines) if cosines else 0.0
    passed = bool(
        dimensions_match and identity_matches and cosines and min_cosine >= threshold
    )
    return ComparisonResult(
        left=left,
        right=right,
        corpus_size=len(cosines),
        threshold=threshold,
        dimensions_match=dimensions_match,
        identity_matches=identity_matches,
        min_cosine=min_cosine,
        mean_cosine=mean_cosine,
        passed=passed,
    )


def result_payload(result: ComparisonResult) -> dict[str, Any]:
    """
    Convert a comparison result to JSON-compatible data.

    Parameters
    ----------
    result : ComparisonResult
        Comparison result.

    Returns
    -------
    dict[str, typing.Any]
        JSON-compatible result payload.
    """

    return {
        "left": {
            "id": result.left.model_id,
            "engine": result.left.engine,
            "model": result.left.model,
            "version": result.left.version,
            "dimension": result.left.dimension,
            "precision": result.left.precision,
        },
        "right": {
            "id": result.right.model_id,
            "engine": result.right.engine,
            "model": result.right.model,
            "version": result.right.version,
            "dimension": result.right.dimension,
            "precision": result.right.precision,
        },
        "corpus_size": result.corpus_size,
        "threshold": result.threshold,
        "dimensions_match": result.dimensions_match,
        "identity_matches": result.identity_matches,
        "min_cosine": result.min_cosine,
        "mean_cosine": result.mean_cosine,
        "passed": result.passed,
    }


def render_summary(result: ComparisonResult) -> str:
    """
    Render a concise human-readable comparison summary.

    Parameters
    ----------
    result : ComparisonResult
        Comparison result.

    Returns
    -------
    str
        Summary text.
    """

    status = "PASS" if result.passed else "FAIL"
    return "\n".join(
        [
            f"Compatibility: {status}",
            f"left: {result.left.model_id} ({result.left.engine})",
            f"right: {result.right.model_id} ({result.right.engine})",
            f"corpus_size: {result.corpus_size}",
            f"dimensions_match: {result.dimensions_match}",
            f"identity_matches: {result.identity_matches}",
            f"min_cosine: {result.min_cosine:.6f}",
            f"mean_cosine: {result.mean_cosine:.6f}",
            f"threshold: {result.threshold:.6f}",
        ]
    )


def build_parser() -> argparse.ArgumentParser:
    """
    Build the command-line parser.

    Parameters
    ----------
    None

    Returns
    -------
    argparse.ArgumentParser
        Parser for embedding compatibility comparisons.
    """

    parser = argparse.ArgumentParser(
        description="Compare embedding vector compatibility between two manifest entries.",
    )
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--left", required=True, help="Left model manifest id.")
    parser.add_argument("--right", required=True, help="Right model manifest id.")
    parser.add_argument("--corpus", type=Path, default=None)
    parser.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD)
    parser.add_argument("--json", action="store_true", help="Print JSON only.")
    return parser


def main(argv: list[str] | None = None) -> int:
    """
    Run the embedding engine compatibility comparison.

    Parameters
    ----------
    argv : list[str] | None, optional
        Command-line arguments excluding the executable name.

    Returns
    -------
    int
        ``0`` when vectors are compatible, otherwise ``1``.
    """

    parser = build_parser()
    args = parser.parse_args(argv)
    entries = load_manifest_entries(args.manifest)
    try:
        left = entries[args.left]
        right = entries[args.right]
    except KeyError as exc:
        parser.error(f"Unknown model id: {exc.args[0]}")
    corpus = load_corpus(args.corpus)
    result = compare_vectors(
        left,
        right,
        embed_manifest_entry(left, corpus),
        embed_manifest_entry(right, corpus),
        threshold=args.threshold,
    )
    payload = result_payload(result)
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(render_summary(result))
        print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if result.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
