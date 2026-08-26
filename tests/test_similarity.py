"""Focused tests for the core exact similarity-index contract."""

from __future__ import annotations

import struct
from typing import TYPE_CHECKING

import pytest

from codira.contracts import (
    EmbeddingEngineSpec,
    SimilarityCandidate,
    SimilarityIndexIdentity,
    SimilarityIndexIncompatibleError,
    SimilarityPurgeRequest,
    SimilarityQueryProvenance,
    SimilaritySearchProfile,
    SimilaritySearchRequest,
    SimilaritySearchResult,
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
    result = ExactSimilarityIndex().search(
        SimilaritySearchRequest(identity, snapshot, (1.0, 1.0), profile)
    )
    assert [candidate.stable_id for candidate in result.candidates] == ["alpha", "beta"]
    assert result.candidates[0].score == pytest.approx(0.70710678)
    assert result.candidates[1].score == pytest.approx(0.70710678)
    assert result.query.plugin_name == "exact"
    assert result.query.transport == "in_process"
    assert result.query.native_provenance == ()


def test_similarity_result_rejects_secret_or_misaligned_provenance() -> None:
    """Reject unsafe provenance and candidate envelopes before rendering.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test verifies result contracts fail closed on unsafe data.
    """

    with pytest.raises(ValueError, match="sensitive"):
        SimilarityCandidate(
            "symbol:alpha",
            1.0,
            native_provenance=(("api_key", "secret"),),
        )
    with pytest.raises(ValueError, match="opaque"):
        SimilarityQueryProvenance(
            "exact",
            "1",
            "symbol",
            3,
            "default",
            2,
            native_provenance=(("native", "https://remote.example"),),
        )
    provenance = SimilarityQueryProvenance("exact", "1", "symbol", 3, "default", 2)
    with pytest.raises(ValueError, match="ordered"):
        SimilaritySearchResult(
            provenance,
            (
                SimilarityCandidate("symbol:beta", 1.0),
                SimilarityCandidate("symbol:alpha", 1.0),
            ),
        )


def test_exact_purge_is_previewable_and_does_not_fabricate_artifacts(
    tmp_path: Path,
) -> None:
    """Preview and confirm exact cache cleanup without fake artifact IDs.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary root for the cache-bound identity.

    Returns
    -------
    None
        The test verifies the typed purge contract for an in-memory index.
    """

    snapshot, identity = _snapshot(tmp_path)
    index = ExactSimilarityIndex()
    index.rebuild(snapshot, identity)
    preview = index.purge(SimilarityPurgeRequest(tmp_path, identity))
    assert preview.preview
    assert preview.removed_artifact_hashes == ()
    confirmed = index.purge(SimilarityPurgeRequest(tmp_path, identity, preview=False))
    assert not confirmed.preview
    assert confirmed.removed_artifact_hashes == ()


def test_exact_reports_incompatible_vectors_with_typed_failure(tmp_path: Path) -> None:
    """Classify malformed authoritative vectors as typed index incompatibility.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary root for a deterministic derived identity.

    Returns
    -------
    None
        The test verifies malformed vectors do not raise an untyped error.
    """

    snapshot, identity = _snapshot(tmp_path)
    malformed = VectorSnapshot(
        snapshot.metadata,
        (
            StoredVectorRow("symbol", "alpha", "a", 2, b"bad"),
            snapshot.rows[1],
        ),
    )
    with pytest.raises(SimilarityIndexIncompatibleError):
        ExactSimilarityIndex().rebuild(malformed, identity)


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
