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

from codira.contracts import (
    BackendDocumentationCandidatesRequest,
    BackendEmbeddingCandidatesRequest,
    BackendResolveDocumentationScoresRequest,
    BackendResolveEmbeddingScoresRequest,
    VectorSimilarityRequest,
)
from codira.registry import active_index_backend
from codira.semantic.embeddings import embed_text, embeddings_enabled
from codira.vector_store import active_vector_store_context

if TYPE_CHECKING:
    from codira.types import ChannelResults, DocumentationChannelResults

EmbeddingCandidatesRequest = BackendEmbeddingCandidatesRequest
DocumentationCandidatesRequest = BackendDocumentationCandidatesRequest


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
    if not embeddings_enabled(root=request.root):
        return []
    query_vector = embed_text(request.query, root=request.root)
    if not any(query_vector):
        return []
    vector_store_context = active_vector_store_context(request.root)
    scores = vector_store_context.store.similarity_scores(
        VectorSimilarityRequest(
            root=request.root,
            identity=vector_store_context.identity,
            object_type="symbol",
            query_vector=query_vector,
            min_score=request.min_score,
            config=vector_store_context.config,
        )
    )
    backend = active_index_backend(root=request.root)
    return backend.resolve_embedding_scores(
        BackendResolveEmbeddingScoresRequest(
            root=request.root,
            scores=scores,
            limit=request.limit,
            prefix=request.prefix,
            conn=request.conn,
        )
    )


def documentation_candidates(
    request: DocumentationCandidatesRequest,
) -> DocumentationChannelResults:
    """
    Return ranked documentation candidates using stored embedding similarity.

    Parameters
    ----------
    request : DocumentationCandidatesRequest
        Documentation candidate request carrying query and filtering options.

    Returns
    -------
    codira.types.DocumentationChannelResults
        Ranked documentation candidates ordered by descending similarity and
        stable documentation identity.
    """
    if not embeddings_enabled(root=request.root):
        return []
    query_vector = embed_text(request.query, root=request.root)
    if not any(query_vector):
        return []
    vector_store_context = active_vector_store_context(request.root)
    scores = vector_store_context.store.similarity_scores(
        VectorSimilarityRequest(
            root=request.root,
            identity=vector_store_context.identity,
            object_type="documentation",
            query_vector=query_vector,
            min_score=request.min_score,
            config=vector_store_context.config,
        )
    )
    backend = active_index_backend(root=request.root)
    return backend.resolve_documentation_scores(
        BackendResolveDocumentationScoresRequest(
            root=request.root,
            scores=scores,
            limit=request.limit,
            prefix=request.prefix,
            conn=request.conn,
        )
    )
