"""Measure same-process semantic startup and steady-state embedding costs.

Responsibilities
----------------
- Separate import, cold query, warm query, and split model-load costs.
- Reuse the repository metadata/artifact helpers used by other benchmark tools.
- Keep startup diagnostics deterministic and isolated from user-facing CLI behavior.

Design principles
-----------------
The script runs one process-local benchmark pass, emits structured JSON, and
avoids mutating normal codira command behavior.

Architectural role
------------------
This module belongs to the **developer tooling layer** and provides
operator-facing semantic-startup diagnostics.
"""

from __future__ import annotations

import argparse
import json
from importlib import import_module
from pathlib import Path
from time import perf_counter
from typing import Protocol, cast

from benchmark_timing import (  # type: ignore[import-not-found]
    benchmark_metadata,
    write_json_artifact,
)


class _EmbeddingsModule(Protocol):
    """Protocol for the embedding helper module used by the benchmark script."""

    EMBEDDING_BACKEND: str
    EMBEDDING_DIM: int
    EMBEDDING_VERSION: str

    def _load_model(self) -> object:
        """
        Load the cached embedding model.

        Parameters
        ----------
        None

        Returns
        -------
        object
            Loaded embedding model object.
        """

    def embed_text(self, text: str) -> list[float]:
        """
        Embed one text payload.

        Parameters
        ----------
        text : str
            Text payload to embed.

        Returns
        -------
        list[float]
            Dense embedding vector.
        """

    def reset_embedding_runtime_caches(self) -> None:
        """
        Clear cached semantic startup state for the current process.

        Parameters
        ----------
        None

        Returns
        -------
        None
            Cached startup state is discarded.
        """


def _load_embeddings_module() -> _EmbeddingsModule:
    """
    Import the semantic embedding helper module.

    Parameters
    ----------
    None

    Returns
    -------
    _EmbeddingsModule
        Imported embedding helper module.
    """
    return cast(
        "_EmbeddingsModule",
        import_module("codira.semantic.embeddings"),
    )


def build_parser() -> argparse.ArgumentParser:
    """
    Build the semantic-startup benchmark CLI parser.

    Parameters
    ----------
    None

    Returns
    -------
    argparse.ArgumentParser
        Configured parser for one benchmark invocation.
    """
    parser = argparse.ArgumentParser(
        description=(
            "Measure same-process semantic import, cold query, and warm query "
            "costs for codira embeddings."
        ),
    )
    parser.add_argument(
        "--root",
        default=".",
        help="Repository root used for benchmark metadata.",
    )
    parser.add_argument(
        "--text",
        default="schema migration logic",
        help="Text payload used for the cold query measurement.",
    )
    parser.add_argument(
        "--second-text",
        default="docstring audit rules",
        help="Text payload used for the warm query measurement.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Write the benchmark JSON artifact to this path.",
    )
    return parser


def measure_embedding_startup(
    *,
    text: str,
    second_text: str,
) -> dict[str, object]:
    """
    Measure same-process embedding startup and warm-query costs.

    Parameters
    ----------
    text : str
        Text payload used for the cold query measurement.
    second_text : str
        Text payload used for the warm query measurement.

    Returns
    -------
    dict[str, object]
        Structured timing report for import, cold, and warm embedding paths.
    """
    import_start = perf_counter()
    embeddings_module = _load_embeddings_module()
    import_elapsed = perf_counter() - import_start

    embeddings_module.reset_embedding_runtime_caches()
    load_start = perf_counter()
    embeddings_module._load_model()
    model_load_elapsed = perf_counter() - load_start

    first_encode_start = perf_counter()
    first_vector = embeddings_module.embed_text(text)
    first_encode_elapsed = perf_counter() - first_encode_start

    second_encode_start = perf_counter()
    second_vector = embeddings_module.embed_text(second_text)
    second_encode_elapsed = perf_counter() - second_encode_start

    embeddings_module.reset_embedding_runtime_caches()
    cold_query_start = perf_counter()
    cold_vector = embeddings_module.embed_text(text)
    cold_query_elapsed = perf_counter() - cold_query_start

    warm_query_start = perf_counter()
    warm_vector = embeddings_module.embed_text(second_text)
    warm_query_elapsed = perf_counter() - warm_query_start

    return {
        "backend": {
            "name": embeddings_module.EMBEDDING_BACKEND,
            "version": embeddings_module.EMBEDDING_VERSION,
            "dim": embeddings_module.EMBEDDING_DIM,
        },
        "queries": {
            "cold_text": text,
            "warm_text": second_text,
        },
        "timings": {
            "module_import": round(import_elapsed, 6),
            "model_load": round(model_load_elapsed, 6),
            "first_encode_after_load": round(first_encode_elapsed, 6),
            "second_encode_after_load": round(second_encode_elapsed, 6),
            "cold_query": round(cold_query_elapsed, 6),
            "warm_query": round(warm_query_elapsed, 6),
        },
        "vectors": {
            "cold_query_dim": len(cold_vector),
            "warm_query_dim": len(warm_vector),
            "first_encode_dim": len(first_vector),
            "second_encode_dim": len(second_vector),
        },
    }


def main() -> int:
    """
    Run the semantic-startup benchmark and print one JSON report.

    Parameters
    ----------
    None

    Returns
    -------
    int
        Zero on success.
    """
    args = build_parser().parse_args()
    root = Path(args.root).resolve()
    report = measure_embedding_startup(
        text=args.text,
        second_text=args.second_text,
    )
    payload = {
        "metadata": benchmark_metadata(root),
        "root": str(root),
        **report,
    }
    if args.output is not None:
        write_json_artifact(args.output, payload)
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
