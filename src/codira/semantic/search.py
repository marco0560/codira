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

from pathlib import Path  # noqa: TC003
from typing import TYPE_CHECKING, cast

from codira.config import with_effective_config_cache
from codira.contracts import (
    BackendDocumentationCandidatesRequest,
    BackendEmbeddingCandidatesRequest,
    BackendResolveDocumentationScoresRequest,
    BackendResolveEmbeddingScoresRequest,
    SimilarityIndexIdentity,
    SimilaritySearchRequest,
    VectorSimilarityScore,
)
from codira.registry import (
    active_index_backend,
    active_similarity_index,
    active_similarity_index_config,
    active_similarity_search_profile,
    with_active_plugin_instance_cache,
)
from codira.semantic.embeddings import embed_text, embeddings_enabled
from codira.vector_store import active_vector_store_context

if TYPE_CHECKING:
    from codira.types import ChannelResults, DocumentationChannelResults

EmbeddingCandidatesRequest = BackendEmbeddingCandidatesRequest
DocumentationCandidatesRequest = BackendDocumentationCandidatesRequest


def _similarity_candidates(  # noqa: PLR0913
    *,
    root: Path,
    vector_store_context: object,
    object_type: str,
    query_vector: list[float],
    min_score: float,
    limit: int,
    profile_name: str | None,
) -> tuple[list[VectorSimilarityScore], int]:
    """Search one durable snapshot through the configured similarity index.

    Parameters
    ----------
    root : pathlib.Path
        Repository root selecting all runtime plugins.
    vector_store_context : object
        Active vector-store context with authoritative snapshot access.
    object_type : str
        Persisted owner type to search.
    query_vector : list[float]
        Encoded query values.
    min_score : float
        Minimum accepted candidate score.
    limit : int
        Explicit requested result limit.
    profile_name : str | None
        Named configured profile, or ``None`` for ``default``.

    Returns
    -------
    tuple[list[object], int]
        Candidate scores and the validated effective result limit.
    """
    from codira.contracts import VectorSnapshotRequest
    from codira.vector_store import ActiveVectorStoreContext

    context = cast("ActiveVectorStoreContext", vector_store_context)
    profile = active_similarity_search_profile(root=root, name=profile_name)
    if limit > profile.max_result_limit:
        message = (
            f"Requested result limit {limit} exceeds profile maximum "
            f"{profile.max_result_limit}."
        )
        raise ValueError(message)
    effective_limit = limit if limit > 0 else profile.default_result_limit
    index_config = active_similarity_index_config(root=root)
    index = active_similarity_index(root=root)
    index.initialize(root, index_config)
    identity = SimilarityIndexIdentity(
        root.resolve(), context.identity, index.spec(index_config)
    )
    snapshot = context.store.vector_snapshot(
        VectorSnapshotRequest(root, context.identity, object_type, context.config)
    )
    scores = index.search(
        SimilaritySearchRequest(identity, snapshot, query_vector, profile, min_score)
    )
    return list(scores), effective_limit


@with_effective_config_cache
@with_active_plugin_instance_cache
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
    scores, effective_limit = _similarity_candidates(
        root=request.root,
        vector_store_context=vector_store_context,
        object_type="symbol",
        query_vector=query_vector,
        min_score=request.min_score,
        limit=request.limit,
        profile_name=request.search_profile,
    )
    backend = active_index_backend(root=request.root)
    return backend.resolve_embedding_scores(
        BackendResolveEmbeddingScoresRequest(
            root=request.root,
            scores=scores,
            limit=effective_limit,
            prefix=request.prefix,
            conn=request.conn,
        )
    )


@with_effective_config_cache
@with_active_plugin_instance_cache
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
    scores, effective_limit = _similarity_candidates(
        root=request.root,
        vector_store_context=vector_store_context,
        object_type="documentation",
        query_vector=query_vector,
        min_score=request.min_score,
        limit=request.limit,
        profile_name=request.search_profile,
    )
    backend = active_index_backend(root=request.root)
    return backend.resolve_documentation_scores(
        BackendResolveDocumentationScoresRequest(
            root=request.root,
            scores=scores,
            limit=effective_limit,
            prefix=request.prefix,
            conn=request.conn,
        )
    )
