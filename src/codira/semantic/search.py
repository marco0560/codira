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

from codira.contracts import BackendEmbeddingCandidatesRequest
from codira.registry import active_index_backend

if TYPE_CHECKING:
    from codira.types import ChannelResults

EmbeddingCandidatesRequest = BackendEmbeddingCandidatesRequest


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
    return backend.embedding_candidates(request)
