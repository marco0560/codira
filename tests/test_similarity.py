"""Focused tests for the core exact similarity-index contract."""

from __future__ import annotations

import struct
from typing import TYPE_CHECKING

import pytest

from codira.contracts import (
    EmbeddingEngineSpec,
    SimilarityIndexIdentity,
    SimilaritySearchProfile,
    SimilaritySearchRequest,
    StoredVectorRow,
    VectorSetIdentity,
    VectorSnapshot,
    VectorSnapshotMetadata,
    VectorStoreSpec,
)
from codira.similarity import ExactSimilarityIndex

if TYPE_CHECKING:
    from pathlib import Path


def _snapshot(root: Path) -> tuple[VectorSnapshot, SimilarityIndexIdentity]:
    """Return deterministic two-row snapshot and exact index identity.

    Parameters
    ----------
    root : pathlib.Path
        Root to bind into the derived identity.

    Returns
    -------
    tuple[VectorSnapshot, SimilarityIndexIdentity]
        Authoritative rows and selected exact identity.
    """

    vector_set = VectorSetIdentity(
        engine=EmbeddingEngineSpec("test", "1", "test", "1", 2),
        vector_store=VectorStoreSpec("test", "1", "1"),
    )
    index = ExactSimilarityIndex()
    identity = SimilarityIndexIdentity(root, vector_set, index.spec({}))
    rows = (
        StoredVectorRow("symbol", "alpha", "a", 2, struct.pack("<2f", 1.0, 0.0)),
        StoredVectorRow("symbol", "beta", "b", 2, struct.pack("<2f", 0.0, 1.0)),
    )
    return (
        VectorSnapshot(VectorSnapshotMetadata(vector_set, 3, "symbol", 2), rows),
        identity,
    )


def test_exact_similarity_orders_equal_scores_by_stable_id(tmp_path: Path) -> None:
    """Order exhaustive exact candidates by score then stable identity.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary root for a root-bound identity.

    Returns
    -------
    None
        The test verifies stable ties and profile candidate truncation.
    """

    snapshot, identity = _snapshot(tmp_path)
    profile = SimilaritySearchProfile("balanced", 8, 2, 1, 2)
    scores = ExactSimilarityIndex().search(
        SimilaritySearchRequest(identity, snapshot, (1.0, 1.0), profile)
    )
    assert [score.stable_id for score in scores] == ["alpha", "beta"]
    assert scores[0].score == pytest.approx(0.70710678)
    assert scores[1].score == pytest.approx(0.70710678)


@pytest.mark.parametrize(
    "profile",
    [
        ("", 1, 1, 1, 1),
        ("bad", 0, 1, 1, 1),
        ("bad", 1, 1, 2, 1),
        ("bad", 1, 1, 1, 2),
    ],
)
def test_similarity_profile_rejects_invalid_core_limits(
    profile: tuple[str, int, int, int, int],
) -> None:
    """Reject invalid generic profile constraints before plugin-specific checks.

    Parameters
    ----------
    profile : tuple[str, int, int, int, int]
        Candidate profile values.

    Returns
    -------
    None
        The test verifies every invalid profile raises ``ValueError``.
    """

    with pytest.raises(ValueError):
        SimilaritySearchProfile(*profile)
