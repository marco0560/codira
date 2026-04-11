"""Deterministic search helpers for stored semantic embeddings.

Responsibilities
----------------
- Generate ranked embedding candidates for user queries using the active backend.
- Support candidate filtering by score, limit, and minimum threshold.
- Integrate embedding helper data into retrieval plans and CLI context output.

Design principles
-----------------
Search helpers operate deterministically, rely on stored embedding metadata, and emit consistent result ordering.

Architectural role
------------------
This module belongs to the **semantic retrieval layer** that supplies embedding candidates to the context builder.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from codira.registry import active_index_backend

if TYPE_CHECKING:
    import sqlite3
    from pathlib import Path

    from codira.types import ChannelResults


def embedding_candidates(
    root: Path,
    query: str,
    *,
    limit: int,
    min_score: float,
    prefix: str | None = None,
    conn: sqlite3.Connection | None = None,
) -> ChannelResults:
    """
    Return ranked symbol candidates using stored embedding similarity.

    Parameters
    ----------
    root : pathlib.Path
        Repository root containing the index database.
    query : str
        User query string.
    limit : int
        Maximum number of ranked results to return.
    min_score : float
        Minimum similarity threshold for emitted results.
    prefix : str | None, optional
        Repo-root-relative path prefix used to restrict matched symbol files.
    conn : sqlite3.Connection | None, optional
        Existing database connection to reuse. When omitted, the function
        opens and closes its own connection.

    Returns
    -------
    codira.types.ChannelResults
        Ranked symbol candidates ordered by descending similarity and stable
        symbol identity.
    """
    backend = active_index_backend()
    return backend.embedding_candidates(
        root,
        query,
        limit=limit,
        min_score=min_score,
        prefix=prefix,
        conn=conn,
    )
