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

from dataclasses import dataclass
from typing import TYPE_CHECKING

from codira.registry import active_index_backend

if TYPE_CHECKING:
    import sqlite3
    from pathlib import Path

    from codira.types import ChannelResults


@dataclass(frozen=True)
class EmbeddingCandidatesRequest:
    """
    Request parameters for semantic embedding candidate retrieval.

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
    prefix : str | None
        Repo-root-relative path prefix used to restrict matched symbol files.
    conn : sqlite3.Connection | None
        Existing database connection to reuse.
    """

    root: Path
    query: str
    limit: int
    min_score: float
    prefix: str | None = None
    conn: sqlite3.Connection | None = None


def embedding_candidates(
    request: EmbeddingCandidatesRequest,
) -> ChannelResults:
    """
    Return ranked symbol candidates using stored embedding similarity.

    Parameters
    ----------
    request : EmbeddingCandidatesRequest
        Embedding candidate request carrying query and filtering options.

    Returns
    -------
    codira.types.ChannelResults
        Ranked symbol candidates ordered by descending similarity and stable
        symbol identity.
    """
    backend = active_index_backend()
    return backend.embedding_candidates(
        request.root,
        request.query,
        limit=request.limit,
        min_score=request.min_score,
        prefix=request.prefix,
        conn=request.conn,
    )
