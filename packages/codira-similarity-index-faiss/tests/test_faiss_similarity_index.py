"""Contract tests for the first-party FAISS similarity-index plugin."""

from __future__ import annotations

import json
import struct
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING, cast

import faiss
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
from codira_similarity_index_faiss import FaissSimilarityIndex

if TYPE_CHECKING:
    from pathlib import Path


def _snapshot(root: Path, *, revision: int = 3) -> VectorSnapshot:
    """Return a deterministic three-vector source snapshot.

    Parameters
    ----------
    root : pathlib.Path
        Repository root bound to the derived index identity.
    revision : int, optional
        Durable vector-set revision.

    Returns
    -------
    codira.contracts.VectorSnapshot
        Deterministically ordered normalized-vector source rows.
    """

    del root
    identity = VectorSetIdentity(
        engine=EmbeddingEngineSpec("test", "1", "test", "1", 2),
        vector_store=VectorStoreSpec("test", "1", "1"),
    )
    rows = (
        StoredVectorRow("symbol", "alpha", "a", 2, struct.pack("<2f", 1.0, 0.0)),
        StoredVectorRow("symbol", "beta", "b", 2, struct.pack("<2f", 0.0, 1.0)),
        StoredVectorRow("symbol", "gamma", "c", 2, struct.pack("<2f", 1.0, 1.0)),
    )
    return VectorSnapshot(VectorSnapshotMetadata(identity, revision, "symbol", 3), rows)


def _identity(
    root: Path,
    index: FaissSimilarityIndex,
    config: dict[str, object],
) -> SimilarityIndexIdentity:
    """Return one selected FAISS identity for the deterministic snapshot.

    Parameters
    ----------
    root : pathlib.Path
        Repository root owning the artifact.
    index : codira_similarity_index_faiss.FaissSimilarityIndex
        Configured FAISS plugin instance.
    config : dict[str, object]
        Build-time FAISS settings.

    Returns
    -------
    codira.contracts.SimilarityIndexIdentity
        Selected FAISS identity.
    """

    return SimilarityIndexIdentity(
        root, _snapshot(root).metadata.identity, index.spec(config)
    )


def _request(
    root: Path,
    index: FaissSimilarityIndex,
    config: dict[str, object],
    *,
    revision: int = 3,
    ef_search: int = 8,
) -> SimilaritySearchRequest:
    """Return one deterministic FAISS search request.

    Parameters
    ----------
    root : pathlib.Path
        Repository root owning the artifact.
    index : codira_similarity_index_faiss.FaissSimilarityIndex
        Configured FAISS plugin instance.
    config : dict[str, object]
        Build-time FAISS settings.
    revision : int, optional
        Durable snapshot revision.
    ef_search : int, optional
        Per-query HNSW graph-exploration effort.

    Returns
    -------
    codira.contracts.SimilaritySearchRequest
        Search request against the current artifact identity.
    """

    snapshot = _snapshot(root, revision=revision)
    return SimilaritySearchRequest(
        _identity(root, index, config),
        snapshot,
        (1.0, 1.0),
        SimilaritySearchProfile("test", ef_search, 3, 3, 3),
    )


def test_flat_faiss_matches_exact_and_survives_cache_reset(tmp_path: Path) -> None:
    """Match core exact ordering after reload from a published FAISS artifact.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository root.

    Returns
    -------
    None
        The test asserts exact flat results and persisted warm reloads agree.
    """

    index = FaissSimilarityIndex()
    config: dict[str, object] = {}
    index.initialize(tmp_path, config)
    request = _request(tmp_path, index, config)
    index.rebuild(request.snapshot, request.identity)
    faiss_scores = index.search(request)
    exact_scores = ExactSimilarityIndex().search(request)
    assert [item.stable_id for item in faiss_scores] == [
        item.stable_id for item in exact_scores
    ]
    assert [item.score for item in faiss_scores] == pytest.approx(
        [item.score for item in exact_scores]
    )
    index.reset_runtime_caches()
    assert [item.stable_id for item in index.search(request)] == [
        "gamma",
        "alpha",
        "beta",
    ]


def test_hnsw_uses_per_query_effort_without_shared_mutation(tmp_path: Path) -> None:
    """Keep concurrent-profile effort out of the persisted HNSW state.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository root.

    Returns
    -------
    None
        The test verifies changing ``ef_search`` does not mutate warm index state.
    """

    index = FaissSimilarityIndex()
    config: dict[str, object] = {
        "index_type": "hnsw",
        "M": 8,
        "efConstruction": 32,
    }
    index.initialize(tmp_path, config)
    request = _request(tmp_path, index, config, ef_search=4)
    index.rebuild(request.snapshot, request.identity)
    assert index.search(request)
    loaded = cast("faiss.IndexHNSWFlat", next(iter(index._cache.values())).index)
    before = loaded.hnsw.efSearch
    requests = (
        _request(tmp_path, index, config, ef_search=4),
        _request(tmp_path, index, config, ef_search=12),
    )
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(index.search, requests))
    assert all(results)
    assert loaded.hnsw.efSearch == before


def test_missing_artifact_fails_closed_with_rebuild_guidance(tmp_path: Path) -> None:
    """Reject a selected FAISS index before any artifact has been published.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository root.

    Returns
    -------
    None
        The test asserts missing state never falls back to core exact search.
    """

    index = FaissSimilarityIndex()
    config: dict[str, object] = {}
    index.initialize(tmp_path, config)
    with pytest.raises(ValueError, match="codira emb rebuild"):
        index.search(_request(tmp_path, index, config))


def test_stale_or_corrupt_artifacts_fail_with_rebuild_command(tmp_path: Path) -> None:
    """Reject stale revisions and corrupt label maps instead of falling back.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository root.

    Returns
    -------
    None
        The test asserts repair guidance is deterministic and explicit.
    """

    index = FaissSimilarityIndex()
    config: dict[str, object] = {}
    index.initialize(tmp_path, config)
    request = _request(tmp_path, index, config)
    index.rebuild(request.snapshot, request.identity)
    with pytest.raises(ValueError, match="codira emb rebuild"):
        index.search(_request(tmp_path, index, config, revision=4))
    index.reset_runtime_caches()
    current = next(
        (tmp_path / ".codira" / "similarity-indexes" / "faiss").rglob("labels.json")
    )
    current.write_text("not-json", encoding="utf-8")
    with pytest.raises(ValueError, match="codira emb rebuild"):
        index.search(request)


def test_failed_rebuild_keeps_previously_published_pointer(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Preserve a working artifact when a subsequent FAISS build fails.

    Parameters
    ----------
    monkeypatch : pytest.MonkeyPatch
        Fixture used to force a FAISS write failure.
    tmp_path : pathlib.Path
        Temporary repository root.

    Returns
    -------
    None
        The test asserts current publication is not changed by a failed build.
    """

    index = FaissSimilarityIndex()
    config: dict[str, object] = {}
    index.initialize(tmp_path, config)
    request = _request(tmp_path, index, config)
    index.rebuild(request.snapshot, request.identity)
    pointer = next(
        (tmp_path / ".codira" / "similarity-indexes" / "faiss").rglob("current.json")
    )
    previous = json.loads(pointer.read_text(encoding="utf-8"))

    def fail_write(*args: object, **kwargs: object) -> None:
        """Raise the injected FAISS publication failure.

        Parameters
        ----------
        args : object
            Positional FAISS write arguments.
        kwargs : object
            Keyword FAISS write arguments.

        Returns
        -------
        None

        Raises
        ------
        RuntimeError
            Always raised to simulate a failed artifact build.
        """

        del args, kwargs
        raise RuntimeError("write failed")

    monkeypatch.setattr("codira_similarity_index_faiss.faiss.write_index", fail_write)
    with pytest.raises(RuntimeError, match="write failed"):
        index.rebuild(request.snapshot, request.identity)
    assert json.loads(pointer.read_text(encoding="utf-8")) == previous


@pytest.mark.parametrize(
    "config",
    [
        {"index_type": "unsupported"},
        {"M": 0},
        {"efConstruction": 0},
        {"candidate_limit": 5},
    ],
)
def test_faiss_rejects_invalid_build_config(config: dict[str, object]) -> None:
    """Reject unsupported build options without accepting legacy limits.

    Parameters
    ----------
    config : dict[str, object]
        Invalid plugin configuration mapping.

    Returns
    -------
    None
        The test asserts configuration fails before artifact work starts.
    """

    with pytest.raises(ValueError):
        FaissSimilarityIndex().configure(config)
