"""Coherent rebuild coordination for configured derived similarity indexes.

This module runs only at mutation boundaries. Query hot paths consume the
published artifacts it creates and never perform lifecycle configuration work.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from codira.contracts import SimilarityIndexIdentity, VectorSnapshotRequest
from codira.registry import (
    active_similarity_index,
    active_similarity_index_config,
)
from codira.vector_store import active_vector_store_context

if TYPE_CHECKING:
    from pathlib import Path


@dataclass(frozen=True)
class SimilarityRebuildResult:
    """Observed result of rebuilding one configured similarity index.

    Parameters
    ----------
    index : str
        Active similarity-index plugin name.
    source_revisions : dict[str, int]
        Verified durable revisions by owner type.
    """

    index: str
    source_revisions: dict[str, int]


def rebuild_active_similarity_index(root: Path) -> SimilarityRebuildResult:
    """Build both authoritative object-type snapshots and verify their revisions.

    The caller must own the repository index maintenance lock. A failed build
    leaves the index plugin's prior published artifact untouched; a changed
    revision raises rather than publishing a stale result.

    Parameters
    ----------
    root : pathlib.Path
        Repository root owning durable vectors and derived artifacts.

    Returns
    -------
    SimilarityRebuildResult
        Active plugin name and revisions verified after each rebuild.

    Raises
    ------
    ValueError
        If a durable source revision changes during rebuilding.
    """

    context = active_vector_store_context(root)
    index = active_similarity_index(root=root)
    config = active_similarity_index_config(root=root)
    index.initialize(root, config)
    identity = SimilarityIndexIdentity(
        root.resolve(), context.identity, index.spec(config)
    )
    revisions: dict[str, int] = {}
    for object_type in ("symbol", "documentation"):
        snapshot = context.store.vector_snapshot(
            VectorSnapshotRequest(root, context.identity, object_type, context.config)
        )
        index.rebuild(snapshot, identity)
        refreshed = context.store.vector_snapshot(
            VectorSnapshotRequest(root, context.identity, object_type, context.config)
        )
        if refreshed.metadata.revision != snapshot.metadata.revision:
            msg = (
                "Embedding source changed during similarity-index rebuild. "
                "Retry `codira emb rebuild`."
            )
            raise ValueError(msg)
        revisions[object_type] = snapshot.metadata.revision
    return SimilarityRebuildResult(index.name, revisions)
