#!/usr/bin/env python3
"""Inspect Codira embedding model campaign manifests."""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import cast

DEFAULT_MANIFEST = Path("benchmarks/embedding-model-candidates.json")
SUPPORTED_ENGINES = frozenset({"sentence-transformers", "onnx"})


@dataclass(frozen=True)
class EmbeddingModelEntry:
    """
    One embedding model campaign entry.

    Parameters
    ----------
    identifier : str
        Stable manifest entry identifier.
    engine : str
        Embedding engine plugin name.
    model : str
        Model identifier.
    version : str
        Operator-controlled model version label.
    dimension : int
        Expected vector dimension.
    precision : str
        Precision or quantization label.
    config : dict[str, object]
        Engine-specific plugin configuration values.
    """

    identifier: str
    engine: str
    model: str
    version: str
    dimension: int
    precision: str
    config: dict[str, object]


def _require_string(row: dict[str, object], key: str) -> str:
    """
    Return a required string field from a manifest row.

    Parameters
    ----------
    row : dict[str, object]
        Manifest row.
    key : str
        Field name.

    Returns
    -------
    str
        Non-empty string value.

    Raises
    ------
    ValueError
        If the field is absent or invalid.
    """
    value = row.get(key)
    if not isinstance(value, str) or not value.strip():
        msg = f"manifest model entry requires non-empty string field {key!r}"
        raise ValueError(msg)
    return value.strip()


def _require_dimension(row: dict[str, object]) -> int:
    """
    Return a required positive vector dimension.

    Parameters
    ----------
    row : dict[str, object]
        Manifest row.

    Returns
    -------
    int
        Positive vector dimension.

    Raises
    ------
    ValueError
        If the field is absent or invalid.
    """
    value = row.get("dimension")
    if not isinstance(value, int) or value <= 0:
        msg = "manifest model entry requires positive integer field 'dimension'"
        raise ValueError(msg)
    return value


def load_manifest(path: Path = DEFAULT_MANIFEST) -> tuple[EmbeddingModelEntry, ...]:
    """
    Load and validate an embedding model manifest.

    Parameters
    ----------
    path : pathlib.Path, optional
        Manifest JSON path.

    Returns
    -------
    tuple[EmbeddingModelEntry, ...]
        Validated manifest entries in file order.

    Raises
    ------
    ValueError
        If the manifest shape is invalid.
    """
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("schema_version") != 1:
        msg = "embedding model manifest requires schema_version = 1"
        raise ValueError(msg)
    rows = payload.get("models")
    if not isinstance(rows, list) or not rows:
        msg = "embedding model manifest requires a non-empty 'models' list"
        raise ValueError(msg)

    entries: list[EmbeddingModelEntry] = []
    seen_ids: set[str] = set()
    for raw_row in rows:
        if not isinstance(raw_row, dict):
            msg = "embedding model manifest entries must be objects"
            raise TypeError(msg)
        row = cast("dict[str, object]", raw_row)
        identifier = _require_string(row, "id")
        if identifier in seen_ids:
            msg = f"duplicate embedding model manifest id: {identifier}"
            raise ValueError(msg)
        seen_ids.add(identifier)
        engine = _require_string(row, "engine")
        if engine not in SUPPORTED_ENGINES:
            msg = f"unsupported embedding engine in manifest: {engine}"
            raise ValueError(msg)
        config = row.get("config", {})
        if not isinstance(config, dict):
            msg = f"manifest entry {identifier!r} requires object field 'config'"
            raise TypeError(msg)
        entries.append(
            EmbeddingModelEntry(
                identifier=identifier,
                engine=engine,
                model=_require_string(row, "model"),
                version=_require_string(row, "version"),
                dimension=_require_dimension(row),
                precision=_require_string(row, "precision"),
                config=cast("dict[str, object]", config),
            )
        )
    return tuple(entries)


def entry_by_id(
    entries: tuple[EmbeddingModelEntry, ...],
    identifier: str,
) -> EmbeddingModelEntry:
    """
    Return one manifest entry by identifier.

    Parameters
    ----------
    entries : tuple[EmbeddingModelEntry, ...]
        Loaded manifest entries.
    identifier : str
        Entry identifier to select.

    Returns
    -------
    EmbeddingModelEntry
        Matching entry.

    Raises
    ------
    ValueError
        If no entry has the requested identifier.
    """
    for entry in entries:
        if entry.identifier == identifier:
            return entry
    available = ", ".join(entry.identifier for entry in entries)
    msg = f"unknown embedding model id {identifier!r}; available: {available}"
    raise ValueError(msg)


def render_config(entry: EmbeddingModelEntry) -> str:
    """
    Render a TOML configuration snippet for one manifest entry.

    Parameters
    ----------
    entry : EmbeddingModelEntry
        Manifest entry to render.

    Returns
    -------
    str
        TOML snippet for repository configuration.
    """
    lines = [
        "[embeddings]",
        f"engine = {json.dumps(entry.engine)}",
        f"model = {json.dumps(entry.model)}",
        f"version = {json.dumps(entry.version)}",
        f"dimension = {entry.dimension}",
        "",
        f"[plugins.embedding-{entry.engine}]",
        "enabled = true",
        f"precision = {json.dumps(entry.precision)}",
    ]
    for key, value in sorted(entry.config.items()):
        if isinstance(value, bool):
            rendered = "true" if value else "false"
        elif isinstance(value, int):
            rendered = str(value)
        elif isinstance(value, str):
            rendered = json.dumps(value)
        else:
            msg = f"unsupported config value for {key!r}: {value!r}"
            raise TypeError(msg)
        lines.append(f"{key} = {rendered}")
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    """
    Build the manifest utility parser.

    Parameters
    ----------
    None

    Returns
    -------
    argparse.ArgumentParser
        Configured parser.
    """
    parser = argparse.ArgumentParser(
        description="Inspect Codira embedding model campaign manifests.",
    )
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--list", action="store_true", help="List manifest entries.")
    parser.add_argument("--id", help="Select one manifest entry.")
    parser.add_argument(
        "--print-config",
        action="store_true",
        help="Print a TOML config snippet for --id.",
    )
    return parser


def main() -> int:
    """
    Run the manifest utility.

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
        entries = load_manifest(args.manifest)
        if args.print_config:
            if not args.id:
                parser.error("--print-config requires --id")
            print(render_config(entry_by_id(entries, args.id)))
            return 0
        if args.list or not args.id:
            for entry in entries:
                print(
                    f"{entry.identifier}\t{entry.engine}\t"
                    f"{entry.model}\tdim={entry.dimension}"
                )
            return 0
        entry = entry_by_id(entries, args.id)
    except ValueError as exc:
        print(f"[codira] {exc}")
        return 2
    print(f"{entry.identifier}\t{entry.engine}\t{entry.model}\tdim={entry.dimension}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
