#!/usr/bin/env python3
"""Build deterministic embedding engine matrix run plans."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import cast

try:
    from scripts.embedding_model_manifest import (
        DEFAULT_MANIFEST,
        EmbeddingModelEntry,
        load_manifest,
        render_config,
    )
except ModuleNotFoundError:
    from embedding_model_manifest import (  # type: ignore[import-not-found,no-redef]
        DEFAULT_MANIFEST,
        EmbeddingModelEntry,
        load_manifest,
        render_config,
    )

DEFAULT_MATRIX = Path("benchmarks/embedding-engine-matrix.json")


def _load_matrix_manifest(path: Path) -> dict[str, object]:
    """
    Load and validate the matrix manifest.

    Parameters
    ----------
    path : pathlib.Path
        Matrix manifest path.

    Returns
    -------
    dict[str, object]
        Parsed manifest payload.

    Raises
    ------
    ValueError
        If the manifest shape is invalid.
    """
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("schema_version") != 1:
        msg = "embedding engine matrix manifest requires schema_version = 1"
        raise ValueError(msg)
    return cast("dict[str, object]", payload)


def _string_field(payload: dict[str, object], key: str, default: str) -> str:
    """
    Return one string field from the matrix manifest.

    Parameters
    ----------
    payload : dict[str, object]
        Matrix manifest payload.
    key : str
        Field name.
    default : str
        Default value when absent.

    Returns
    -------
    str
        Non-empty string value.

    Raises
    ------
    ValueError
        If the field exists with an invalid value.
    """
    value = payload.get(key, default)
    if not isinstance(value, str) or not value.strip():
        msg = f"matrix manifest requires non-empty string field {key!r}"
        raise ValueError(msg)
    return value.strip()


def build_matrix_plan(
    *,
    matrix_manifest: Path = DEFAULT_MATRIX,
    model_manifest: Path | None = None,
    repository_manifest: Path | None = None,
) -> dict[str, object]:
    """
    Build a deterministic embedding matrix run plan.

    Parameters
    ----------
    matrix_manifest : pathlib.Path, optional
        Matrix manifest path.
    model_manifest : pathlib.Path | None, optional
        Override model manifest path.
    repository_manifest : pathlib.Path | None, optional
        Override repository benchmark manifest path.

    Returns
    -------
    dict[str, object]
        JSON-serializable dry-run plan.
    """
    payload = _load_matrix_manifest(matrix_manifest)
    selected_model_manifest = model_manifest or Path(
        _string_field(payload, "model_manifest", str(DEFAULT_MANIFEST))
    )
    selected_repository_manifest = repository_manifest or Path(
        _string_field(
            payload, "repository_manifest", "benchmarks/uv-backed-repos.local.json"
        )
    )
    entries = load_manifest(selected_model_manifest)
    runs = [_run_plan(entry, selected_repository_manifest) for entry in entries]
    return {
        "schema_version": 1,
        "matrix_manifest": str(matrix_manifest),
        "model_manifest": str(selected_model_manifest),
        "repository_manifest": str(selected_repository_manifest),
        "runs": runs,
    }


def _run_plan(
    entry: EmbeddingModelEntry,
    repository_manifest: Path,
) -> dict[str, object]:
    """
    Build one run-plan row.

    Parameters
    ----------
    entry : scripts.embedding_model_manifest.EmbeddingModelEntry
        Model manifest entry.
    repository_manifest : pathlib.Path
        Repository benchmark manifest used by the long campaign.

    Returns
    -------
    dict[str, object]
        JSON-compatible plan row.
    """
    return {
        "model_id": entry.identifier,
        "engine": entry.engine,
        "model": entry.model,
        "dimension": entry.dimension,
        "repository_manifest": str(repository_manifest),
        "config_toml": render_config(entry),
    }


def build_parser() -> argparse.ArgumentParser:
    """
    Build the matrix-plan parser.

    Parameters
    ----------
    None

    Returns
    -------
    argparse.ArgumentParser
        Configured parser.
    """
    parser = argparse.ArgumentParser(
        description="Build a dry-run embedding engine matrix plan.",
    )
    parser.add_argument("--matrix", type=Path, default=DEFAULT_MATRIX)
    parser.add_argument("--model-manifest", type=Path)
    parser.add_argument("--repository-manifest", type=Path)
    return parser


def main() -> int:
    """
    Print the matrix run plan as JSON.

    Parameters
    ----------
    None

    Returns
    -------
    int
        Process exit code.
    """
    parser = build_parser()
    args = parser.parse_args()
    try:
        plan = build_matrix_plan(
            matrix_manifest=args.matrix,
            model_manifest=args.model_manifest,
            repository_manifest=args.repository_manifest,
        )
    except ValueError as exc:
        print(f"[codira] {exc}")
        return 2
    print(json.dumps(plan, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
