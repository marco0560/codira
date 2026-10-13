"""Exercise durable pending-queue recovery using real backend databases.

Parameters
----------
None

Returns
-------
None
    Inference is simulated; database transactions and queue processing are real.
"""

from __future__ import annotations

import importlib
import json
from typing import TYPE_CHECKING

import pytest

from codira.semantic.embeddings import EmbeddingBackendSpec

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.parametrize("backend_name", ["sqlite", "duckdb"])
@pytest.mark.parametrize("borrowed", [False, True])
def test_interrupted_pending_batch_preserves_transaction_ownership(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    backend_name: str,
    borrowed: bool,
) -> None:
    """Resume completed batches or leave rollback to the borrowing caller.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Owned repository fixture with native database files.
    monkeypatch : pytest.MonkeyPatch
        Supplies deterministic embeddings and a two-row work segment.
    backend_name : str
        Native structural backend under test.
    borrowed : bool
        Whether the caller supplies and controls an explicit transaction.

    Returns
    -------
    None
        Failed rows survive, completed owned batches persist and retry is exact.
    """
    module = importlib.import_module(f"codira_backend_{backend_name}")
    support = importlib.import_module(
        f"codira_backend_{backend_name}.{backend_name}_support"
    )
    backend_type = (
        "SQLiteIndexBackend" if backend_name == "sqlite" else "DuckDBIndexBackend"
    )
    backend = getattr(module, backend_type)()
    monkeypatch.setenv("CODIRA_EMBEDDING_PROFILE_DIR", str(tmp_path / "profiles"))
    backend.initialize(tmp_path)
    monkeypatch.setattr(module, "embedding_work_batch_size", lambda **kwargs: 2)
    spec = EmbeddingBackendSpec(name="test", version="1", dim=3)
    conn = backend.open_connection(tmp_path)
    conn.executemany(
        "INSERT INTO pending_embeddings "
        "(object_type, object_id, stable_id, backend, version, content_hash, dim, text) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        [
            ("symbol", i, f"id-{i}", "test", "1", f"hash-{i}", 3, f"text-{i}")
            for i in range(4)
        ],
    )
    conn.commit()
    calls: list[list[str]] = []

    def encode(texts: list[str], *, root: Path | None = None) -> list[list[float]]:
        """Interrupt the second real queue batch at the inference boundary.

        Parameters
        ----------
        texts : list[str]
            Selected batch text.
        root : pathlib.Path | None, optional
            Unused repository context.

        Returns
        -------
        list[list[float]]
            Deterministic unit vectors.

        Raises
        ------
        KeyboardInterrupt
            The second batch simulates operator interruption.
        """
        calls.append(texts)
        if len(calls) == 2:
            raise KeyboardInterrupt
        return [[1.0, 0.0, 0.0] for _ in texts]

    monkeypatch.setattr(support, "embed_texts", encode)
    if borrowed:
        conn.execute("BEGIN TRANSACTION")
    with pytest.raises(KeyboardInterrupt):
        backend.process_pending_embeddings(
            tmp_path, embedding_backend=spec, conn=conn if borrowed else None
        )
    if borrowed:
        conn.execute("ROLLBACK")
    pending = conn.execute(
        "SELECT object_id FROM pending_embeddings ORDER BY object_id"
    ).fetchall()
    assert pending == ([(0,), (1,), (2,), (3,)] if borrowed else [(2,), (3,)])
    receipts = [
        json.loads(line)
        for path in (tmp_path / "profiles").glob("*.jsonl")
        for line in path.read_text().splitlines()
    ]
    assert any(
        item["phase"] == "inference" and item["status"] == "KeyboardInterrupt"
        for item in receipts
    )
    assert any(
        item["phase"] == "persistence" and item["rows"] == 2 for item in receipts
    )
    assert (
        any(item["phase"] == "checkpoint.commit" for item in receipts) is not borrowed
    )
    assert all("text-" not in json.dumps(item) for item in receipts)
    calls.clear()
    monkeypatch.setattr(
        support, "embed_texts", lambda texts, **kwargs: [[1.0, 0.0, 0.0] for _ in texts]
    )
    assert backend.process_pending_embeddings(tmp_path, embedding_backend=spec) == (
        (4, 0) if borrowed else (2, 0)
    )
    assert conn.execute("SELECT COUNT(*) FROM pending_embeddings").fetchone() == (0,)
    assert conn.execute("SELECT COUNT(*) FROM embeddings").fetchone() == (4,)
    assert backend.process_pending_embeddings(tmp_path, embedding_backend=spec) == (
        0,
        0,
    )
    conn.close()
