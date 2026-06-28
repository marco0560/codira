"""Tests for split embedding engine experiment helpers."""

from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING

from scripts import run_split_embedding_engine_experiment as split_experiment
from scripts.run_final_embedding_model_campaign import ModelEntry

if TYPE_CHECKING:
    from pathlib import Path


def _model(
    model_id: str,
    *,
    engine: str,
    model: str = "demo/model",
) -> ModelEntry:
    """
    Build a model entry fixture.

    Parameters
    ----------
    model_id : str
        Manifest id.
    engine : str
        Embedding engine name.
    model : str, optional
        Model identity.

    Returns
    -------
    scripts.run_final_embedding_model_campaign.ModelEntry
        Model fixture.
    """

    return ModelEntry(
        id=model_id,
        engine=engine,
        model=model,
        version="1",
        dimension=2,
        precision="float32",
        config={},
    )


def test_load_split_pairs_reads_manifest(tmp_path: Path) -> None:
    """
    Read split engine pairs from manifest JSON.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary directory.

    Returns
    -------
    None
        The test asserts manifest fields are preserved.
    """

    manifest = tmp_path / "pairs.json"
    manifest.write_text(
        """
        {
          "schema_version": 1,
          "pairs": [
            {
              "id": "demo",
              "index_model": "demo-st",
              "query_model": "demo-onnx",
              "threshold": 0.98,
              "queries": ["schema", "plugins"]
            }
          ]
        }
        """,
        encoding="utf-8",
    )

    pairs = split_experiment.load_split_pairs(manifest)

    assert pairs == (
        split_experiment.SplitPair(
            pair_id="demo",
            index_model="demo-st",
            query_model="demo-onnx",
            threshold=0.98,
            queries=("schema", "plugins"),
        ),
    )


def test_compatibility_entries_preserve_model_metadata() -> None:
    """
    Convert campaign model entries to compatibility helper entries.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test asserts identity fields are preserved for the gate helper.
    """

    entries = split_experiment.compatibility_entries(
        {"demo": _model("demo", engine="onnx")}
    )

    assert entries["demo"].model_id == "demo"
    assert entries["demo"].engine == "onnx"
    assert entries["demo"].model == "demo/model"
    assert entries["demo"].dimension == 2


def test_alias_sqlite_vector_set_duplicates_materialized_vectors(
    tmp_path: Path,
) -> None:
    """
    Alias SQLite materialized vectors from ST identity to ONNX identity.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary directory.

    Returns
    -------
    None
        The test asserts the query-time ONNX vector-set sees source vectors.
    """

    db_path = tmp_path / "embeddings.db"
    source = _model("demo-st", engine="sentence-transformers")
    target = _model("demo-onnx", engine="onnx")
    with sqlite3.connect(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE vector_sets (
                id INTEGER PRIMARY KEY,
                engine TEXT NOT NULL,
                engine_version TEXT NOT NULL,
                model TEXT NOT NULL,
                model_version TEXT NOT NULL,
                dimension INTEGER NOT NULL,
                precision TEXT NOT NULL,
                store TEXT NOT NULL,
                store_version TEXT NOT NULL,
                format_version TEXT NOT NULL,
                UNIQUE (
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
            );
            CREATE TABLE vectors (
                vector_set_id INTEGER NOT NULL,
                object_type TEXT NOT NULL,
                stable_id TEXT NOT NULL,
                content_hash TEXT NOT NULL,
                vector BLOB NOT NULL,
                PRIMARY KEY (vector_set_id, object_type, stable_id)
            );
            """
        )
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
            VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                source.engine,
                "1.0.1",
                source.model,
                source.version,
                source.dimension,
                source.precision,
                "sqlite",
                "1.0.1",
                "1",
            ),
        )
        conn.execute(
            """
            INSERT INTO vectors(
                vector_set_id,
                object_type,
                stable_id,
                content_hash,
                vector
            )
            VALUES (1, 'symbol', 'symbol:one', 'hash-one', ?)
            """,
            (b"vector",),
        )

    count = split_experiment.alias_sqlite_vector_set(
        db_path=db_path,
        source=source,
        target=target,
        backend="sqlite",
    )

    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT vs.engine, v.stable_id, v.vector
            FROM vector_sets vs
            JOIN vectors v ON v.vector_set_id = vs.id
            WHERE vs.engine = 'onnx'
            """
        ).fetchall()

    assert count == 1
    assert rows == [("onnx", "symbol:one", b"vector")]
