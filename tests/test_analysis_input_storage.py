"""Verify external input identity persistence against real structural backends.

Parameters
----------
None

Returns
-------
None
    Source hashes and external input identities remain independently queryable.
"""

from __future__ import annotations

import hashlib
from dataclasses import replace
from typing import TYPE_CHECKING, cast

import pytest
from codira_backend_duckdb import DuckDBIndexBackend
from codira_backend_sqlite import SQLiteIndexBackend

from codira.contracts import (
    AnalysisInputStateBackend,
    BackendPersistAnalysisRequest,
    BackendPersistFullIndexFile,
    BackendPersistFullIndexRequest,
    EmbeddingIndexingPolicy,
)
from codira.models import AnalysisResult, FileMetadataSnapshot, ModuleArtifact
from codira.semantic.embeddings import EmbeddingBackendSpec

if TYPE_CHECKING:
    from pathlib import Path


def _file_input(root: Path, name: str, fingerprint: str) -> BackendPersistFullIndexFile:
    """Create a source-bound snapshot with independently supplied external input.

    Parameters
    ----------
    root : pathlib.Path
        Disposable repository root.
    name : str
        Unique source and module name.
    fingerprint : str
        External input identity, including the empty source-only sentinel.

    Returns
    -------
    BackendPersistFullIndexFile
        File request with a real SHA-256 of the written source bytes.
    """
    path = root / f"{name}.cpp"
    source = b"int value;\n"
    path.write_bytes(source)
    metadata = FileMetadataSnapshot(
        path=path,
        sha256=hashlib.sha256(source).hexdigest(),
        mtime=path.stat().st_mtime,
        size=len(source),
        analyzer_name="cpp",
        analyzer_version="fixture",
        analysis_input_fingerprint=fingerprint,
    )
    analysis = AnalysisResult(
        source_path=path,
        module=ModuleArtifact(name, f"cpp:module:{name}", None, 0),
        classes=(),
        functions=(),
        declarations=(),
        imports=(),
    )
    return BackendPersistFullIndexFile(path, metadata, analysis)


@pytest.mark.parametrize("backend_name", ["sqlite", "duckdb"])
def test_external_input_identity_round_trips_without_replacing_source_hash(
    tmp_path: Path, backend_name: str
) -> None:
    """Persist external identities independently through incremental writes.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Disposable repository and backend storage root.
    backend_name : str
        First-party backend tested with its real database driver.

    Returns
    -------
    None
        External-input and source-only rows round-trip through owned/shared reads.
    """
    backend = SQLiteIndexBackend() if backend_name == "sqlite" else DuckDBIndexBackend()
    backend.initialize(tmp_path)
    assert isinstance(backend, AnalysisInputStateBackend)
    reader = cast("AnalysisInputStateBackend", backend)
    first = _file_input(tmp_path, "with_header", "header-content-before")
    second = _file_input(tmp_path, "without_header", "")
    policy = EmbeddingIndexingPolicy(object_types=frozenset())
    for item in (first, second):
        backend.persist_analysis(
            BackendPersistAnalysisRequest(
                root=tmp_path,
                file_metadata=item.file_metadata,
                analysis=item.analysis,
                embedding_backend=EmbeddingBackendSpec("fixture", "1", 3),
                embedding_indexing=policy,
                defer_embeddings=True,
            )
        )
    expected = {str(first.path): "header-content-before", str(second.path): ""}
    assert reader.load_existing_file_analysis_inputs(tmp_path) == expected
    assert backend.load_existing_file_hashes(tmp_path) == {
        str(item.path): hashlib.sha256(item.path.read_bytes()).hexdigest()
        for item in (first, second)
    }
    conn = backend.open_connection(tmp_path)
    try:
        assert (
            reader.load_existing_file_analysis_inputs(tmp_path, conn=conn) == expected
        )
        assert conn.execute("SELECT COUNT(*) FROM files").fetchone() == (2,)
    finally:
        conn.close()
    session = backend.begin_index_session(tmp_path)
    try:
        session.prepare(full=False, indexed_paths=[str(first.path)], deleted_paths=[])
        session.persist_analysis(
            BackendPersistAnalysisRequest(
                root=tmp_path,
                file_metadata=replace(
                    first.file_metadata,
                    analysis_input_fingerprint="header-content-after",
                ),
                analysis=first.analysis,
                embedding_backend=EmbeddingBackendSpec("fixture", "1", 3),
                embedding_indexing=policy,
                defer_embeddings=True,
            )
        )
        session.commit()
    except BaseException:
        session.abort()
        raise
    finally:
        session.close()
    assert reader.load_existing_file_analysis_inputs(tmp_path) == {
        str(first.path): "header-content-after",
        str(second.path): "",
    }
    assert backend.load_existing_file_hashes(tmp_path) == {
        str(item.path): hashlib.sha256(item.path.read_bytes()).hexdigest()
        for item in (first, second)
    }


def test_duckdb_full_bulk_preserves_external_input_identity(tmp_path: Path) -> None:
    """Exercise the Arrow full-index path with nonempty external identities.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Disposable repository and real DuckDB storage root.

    Returns
    -------
    None
        Full-index replacement keeps raw source hashes and supplied fingerprints.
    """
    backend = DuckDBIndexBackend()
    backend.initialize(tmp_path)
    first = _file_input(tmp_path, "first", "header-one")
    second = _file_input(tmp_path, "second", "header-two")
    backend.persist_full_index(
        BackendPersistFullIndexRequest(
            root=tmp_path,
            files=(first, second),
            embedding_backend=EmbeddingBackendSpec("fixture", "1", 3),
            embedding_indexing=EmbeddingIndexingPolicy(object_types=frozenset()),
            defer_embeddings=True,
            vector_store=None,
            vector_set_identity=None,
            vector_store_config={},
            coverage_complete=True,
            analyzers=(),
        )
    )
    assert backend.load_existing_file_analysis_inputs(tmp_path) == {
        str(first.path): "header-one",
        str(second.path): "header-two",
    }
    assert backend.load_existing_file_hashes(tmp_path) == {
        str(item.path): hashlib.sha256(item.path.read_bytes()).hexdigest()
        for item in (first, second)
    }
