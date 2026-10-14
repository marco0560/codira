#!/usr/bin/env python3
"""Verify selected local embedding assets without indexing repository sources.

Parameters
----------
None

Returns
-------
None
    CLI output is an admission receipt, never a benchmark measurement.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import logging
import math
import os
from pathlib import Path
from typing import TYPE_CHECKING

from codira.config import load_effective_config
from codira.semantic.embeddings import (
    _sentence_transformer_location,
    embed_texts,
    embedding_engine_config,
    get_embedding_backend,
)

if TYPE_CHECKING:
    from collections.abc import Sequence


def artifact_record(path: Path) -> dict[str, object]:
    """Fingerprint an actual resolved file rather than only its configuration.

    Parameters
    ----------
    path : pathlib.Path
        Required local artifact file.

    Returns
    -------
    dict[str, object]
        Resolved path, content digest and size.

    Raises
    ------
    OSError
        Artifact is missing or cannot be read.
    """
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return {
        "path": str(path.resolve()),
        "sha256": digest.hexdigest(),
        "size": path.stat().st_size,
    }


def selected_artifacts(root: Path) -> tuple[list[Path], str | None]:
    """Resolve files through the same engine settings used during population.

    Parameters
    ----------
    root : pathlib.Path
        Context selecting the supplied campaign configuration.

    Returns
    -------
    tuple[list[pathlib.Path], str | None]
        Selected artifact files and local snapshot revision, if applicable.

    Raises
    ------
    ValueError
        The engine is unsupported by this local suite or lacks model files.
    """
    config = load_effective_config(root=root)
    engine = config.embeddings.engine
    if engine == "onnx":
        module = importlib.import_module("codira_embedding_onnx")
        settings = module._engine_config(embedding_engine_config(root=root))
        paths = [settings.model_path, settings.tokenizer_path]
        # Include adjacent external tensor files when the exported graph uses them.
        paths.extend(
            sorted(settings.model_path.parent.glob(settings.model_path.name + ".*"))
        )
        return list(dict.fromkeys(paths)), None
    if engine == "sentence-transformers":
        source, cache = _sentence_transformer_location(root)
        if Path(source).is_dir():
            snapshot = Path(source)
        else:
            hub = importlib.import_module("huggingface_hub")
            snapshot = Path(
                hub.snapshot_download(
                    repo_id=source, cache_dir=str(cache), local_files_only=True
                )
            )
        paths = sorted(
            path
            for path in snapshot.rglob("*")
            if path.is_file()
            and not {"onnx", "openvino"}.intersection(path.relative_to(snapshot).parts)
            and path.suffix in {".json", ".safetensors", ".bin", ".txt", ".model"}
        )
        if not paths or not any(
            path.suffix in {".safetensors", ".bin"} for path in paths
        ):
            message = "The selected Sentence Transformers snapshot lacks PyTorch checkpoint artifacts; an ONNX export alone is insufficient."
            raise ValueError(message)
        return paths, snapshot.name
    message = f"Unsupported local benchmark embedding engine: {engine}"
    raise ValueError(message)


def check_readiness(root: Path) -> dict[str, object]:
    """Verify immutable assets and one native finite, dimension-correct encoding.

    Parameters
    ----------
    root : pathlib.Path
        Configuration context; no structural backend or source index is opened.

    Returns
    -------
    dict[str, object]
        Stable asset and engine provenance, without vectors or timing comparisons.

    Raises
    ------
    ValueError
        Configuration, dimensions or artifact stability cannot be verified.
    """
    config = load_effective_config(root=root)
    if not config.embeddings.enabled:
        message = "Selected embedding profile has embeddings disabled."
        raise ValueError(message)
    files, revision = selected_artifacts(root)
    before = [artifact_record(path) for path in files]
    backend = get_embedding_backend(root=root)
    vectors = embed_texts(["Codira offline model readiness."], root=root)
    if (
        len(vectors) != 1
        or len(vectors[0]) != backend.dim
        or not all(math.isfinite(value) for value in vectors[0])
    ):
        message = (
            "Embedding readiness returned invalid dimensions or non-finite values."
        )
        raise ValueError(message)
    if [artifact_record(path) for path in files] != before:
        message = "Embedding artifacts changed during readiness verification."
        raise ValueError(message)
    return {
        "status": "ready",
        "engine": config.embeddings.engine,
        "logical_model": backend.name,
        "model_version": backend.version,
        "dimension": backend.dim,
        "snapshot_revision": revision,
        "assets": before,
    }


def main(argv: Sequence[str] | None = None) -> int:
    """Emit retained offline prerequisite success or an explicit admission error.

    Parameters
    ----------
    argv : collections.abc.Sequence[str] | None, optional
        Explicit arguments or the invoking process arguments.

    Returns
    -------
    int
        Zero when ready, one for an unavailable prerequisite.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config", type=Path)
    parser.add_argument("--root", type=Path, required=True)
    args = parser.parse_args(argv)
    os.environ["CODIRA_CONFIG_FILE"] = str(args.config.resolve())
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    try:
        result = check_readiness(args.root.resolve())
    except Exception as error:
        logging.getLogger(__name__).exception("Embedding prerequisite unavailable")
        print(
            json.dumps(
                {
                    "status": "unavailable",
                    "error_type": type(error).__name__,
                    "reason": str(error),
                }
            )
        )
        return 1
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
