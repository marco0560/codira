"""Tests for deterministic exact and FAISS HNSW characterization evidence."""

from __future__ import annotations

from scripts.characterize_similarity_indexes import run_characterization


def test_characterization_reports_exact_reference_and_hnsw_recall() -> None:
    """Emit stable corpus metadata and valid exact/HNSW result evidence.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test asserts deterministic ranking semantics and measured fields.
    """
    report = run_characterization(
        seed=20,
        vector_count=32,
        dimension=8,
        query_count=4,
        top_k=5,
        repeats=1,
    )

    assert report["schema_version"] == 1
    assert report["corpus"] == {
        "seed": 20,
        "vector_count": 32,
        "dimension": 8,
        "query_count": 4,
        "top_k": 5,
        "timing_repeats": 1,
    }
    exact_reference = report["exact_reference"]
    modes = report["modes"]
    assert isinstance(exact_reference, dict)
    assert isinstance(modes, dict)
    assert modes["flat"]["first_query_top_k"] == exact_reference["first_query_top_k"]
    assert modes["flat"]["recall_at_k"] == 1.0
    assert 0.0 <= modes["hnsw"]["recall_at_k"] <= 1.0
    for mode in modes.values():
        assert mode["build_latency_ns_median"] >= 0
        assert mode["cold_query_latency_ns_median"] >= 0
        assert mode["warm_query_latency_ns_median"] >= 0
        assert mode["artifact_size_bytes"] > 0
