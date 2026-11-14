"""Regression coverage for streamed SQLite index vector-store atomicity.

Parameters
----------
None

Returns
-------
None
    A failed full index must leave its previously published vectors intact.
"""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING, Literal, cast
from unittest.mock import Mock

import codira_backend_sqlite.sqlite_support as sqlite_support
import pytest
from codira_backend_sqlite import sqlite_write_session
from codira_vector_store_sqlite import SQLiteVectorStore, SQLiteVectorStoreWriteSession

import codira.indexer as indexer_module
from codira.config import IndexConcurrencyConfig
from codira.contracts import (
    BackendPersistFullIndexResult,
    PreparedVectorRow,
    VectorSetIdentity,
    VectorSnapshot,
    VectorSnapshotRequest,
    VectorStore,
    VectorStoreError,
)
from codira.index_generation import IndexGenerationStore, transition_record
from codira.indexer import index_repo
from codira.registry import active_index_backend
from codira.semantic.embeddings import EMBEDDING_DIM
from codira.vector_store import active_vector_store_context

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from pathlib import Path

    from codira.contracts import LanguageAnalyzer
    from codira.index_stream_contracts import (
        BackendPersistFullIndexStreamRequest,
        FullIndexStreamingBulkBackend,
    )
    from codira.indexer import _AnalysisTask, _AnalysisTaskResult


def _published_symbol_vectors(root: Path) -> VectorSnapshot:
    """Read the active vector store's published symbol-vector state.

    Parameters
    ----------
    root : pathlib.Path
        Repository root that owns the SQLite vector store.

    Returns
    -------
    codira.contracts.VectorSnapshot
        Ordered vectors and publication revision for symbols.
    """
    context = active_vector_store_context(root)
    return context.store.vector_snapshot(
        VectorSnapshotRequest(
            root=root,
            identity=context.identity,
            object_type="symbol",
            config=context.config,
        )
    )


def test_streamed_full_index_analysis_failure_preserves_published_vectors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Preserve the vector-store publication after a later analysis failure.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Isolated source repository and index state.
    monkeypatch : pytest.MonkeyPatch
        Fixture for deterministic embeddings, batch flushing, and failure
        injection.

    Returns
    -------
    None
        The vector-store snapshot remains equal to its prior publication.

    Raises
    ------
    RuntimeError
        The injected second-file analysis failure is propagated by indexing.
    """
    (tmp_path / ".codira").mkdir()
    config = tmp_path / ".codira/config.toml"
    config.write_text(
        '[backend]\nname = "sqlite"\n'
        '[embeddings]\nenabled = true\nvector_store = "sqlite"\n'
        '[embeddings.indexing]\nobject_types = ["symbol"]\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("CODIRA_CONFIG_FILE", str(config))
    (tmp_path / "a.py").write_text("def before():\n    return 1\n", encoding="utf-8")
    (tmp_path / "b.py").write_text("def later():\n    return 2\n", encoding="utf-8")

    monkeypatch.setattr(
        sqlite_support,
        "embed_texts",
        lambda texts, *, root=None: [[1.0] * EMBEDDING_DIM for _text in texts],
    )
    active_index_backend(root=tmp_path).initialize(tmp_path)
    initial = index_repo(tmp_path, full=True)
    assert initial.failed == 0
    published_before_failure = _published_symbol_vectors(tmp_path)
    assert published_before_failure.rows

    (tmp_path / "a.py").write_text("def after():\n    return 3\n", encoding="utf-8")
    monkeypatch.setattr(
        sqlite_write_session, "embedding_work_batch_size", lambda *, root=None: 1
    )
    vector_store_writes = 0
    original_store_vectors = SQLiteVectorStoreWriteSession.store_vectors

    def record_store_vectors(
        store: SQLiteVectorStoreWriteSession,
        rows: Sequence[PreparedVectorRow],
    ) -> None:
        """Count materialized external writes while retaining real persistence.

        Parameters
        ----------
        store : codira_vector_store_sqlite.SQLiteVectorStoreWriteSession
            Real staged SQLite vector-store session.
        rows : collections.abc.Sequence[codira.contracts.PreparedVectorRow]
            Materialized vectors being published.

        Returns
        -------
        None
            The original store method persists the rows.
        """
        nonlocal vector_store_writes
        vector_store_writes += len(rows)
        original_store_vectors(store, rows)

    monkeypatch.setattr(
        SQLiteVectorStoreWriteSession, "store_vectors", record_store_vectors
    )
    original_analyze = indexer_module._analyze_index_task
    analysis_calls = 0

    def fail_on_second_file(
        task: _AnalysisTask,
        root: Path,
        analyzers: list[LanguageAnalyzer],
    ) -> _AnalysisTaskResult:
        """Raise on the later file after the first file has been persisted.

        Parameters
        ----------
        task : codira.indexer._AnalysisTask
            File analysis task in deterministic path order.
        root : pathlib.Path
            Repository root.
        analyzers : list[codira.contracts.LanguageAnalyzer]
            Configured source analyzers.

        Returns
        -------
        codira.indexer._AnalysisTaskResult
            First file's normal analysis result.

        Raises
        ------
        RuntimeError
            On the second source file.
        """
        nonlocal analysis_calls
        analysis_calls += 1
        if analysis_calls == 2:
            message = "injected later analysis failure"
            raise RuntimeError(message)
        return original_analyze(task, root, analyzers)

    monkeypatch.setattr(indexer_module, "_analyze_index_task", fail_on_second_file)
    with pytest.raises(RuntimeError, match="injected later analysis failure"):
        index_repo(tmp_path, full=True)

    assert analysis_calls == 2
    assert vector_store_writes > 0
    published_after_failure = _published_symbol_vectors(tmp_path)
    assert published_after_failure == published_before_failure, (
        "streamed full-index failure changed the published SQLite vectors after "
        f"{vector_store_writes} external vector writes: revision "
        f"{published_before_failure.metadata.revision} -> "
        f"{published_after_failure.metadata.revision}, row count "
        f"{published_before_failure.metadata.row_count} -> "
        f"{published_after_failure.metadata.row_count}, stable IDs "
        f"{[row.stable_id for row in published_before_failure.rows]} -> "
        f"{[row.stable_id for row in published_after_failure.rows]}"
    )


def test_vector_publication_failure_leaves_generation_unavailable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Keep a generation non-ready if its staged vector commit fails.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Isolated source and index root.
    monkeypatch : pytest.MonkeyPatch
        Provides deterministic embeddings and a failed vector commit.

    Returns
    -------
    None
        Failed publication cannot leave the generation marked ready.
    """
    (tmp_path / ".codira").mkdir()
    config = tmp_path / ".codira/config.toml"
    config.write_text(
        '[backend]\nname = "sqlite"\n'
        '[embeddings]\nenabled = true\nvector_store = "sqlite"\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("CODIRA_CONFIG_FILE", str(config))
    source = tmp_path / "sample.py"
    source.write_text("def before():\n    return 1\n", encoding="utf-8")
    monkeypatch.setattr(
        sqlite_support,
        "embed_texts",
        lambda texts, *, root=None: [[1.0] * EMBEDDING_DIM for _text in texts],
    )
    active_index_backend(root=tmp_path).initialize(tmp_path)
    index_repo(tmp_path, full=True)
    previous = _published_symbol_vectors(tmp_path)
    source.write_text("def after():\n    return 2\n", encoding="utf-8")

    def fail_commit(_session: SQLiteVectorStoreWriteSession) -> None:
        """Fail the staged vector-store commit for this test.

        Parameters
        ----------
        _session : codira_vector_store_sqlite.SQLiteVectorStoreWriteSession
            Session whose commit is rejected.

        Returns
        -------
        None
            This function always raises.

        Raises
        ------
        RuntimeError
            Always, to simulate a vector publication failure.
        """
        message = "injected vector commit failure"
        raise RuntimeError(message)

    monkeypatch.setattr(SQLiteVectorStoreWriteSession, "commit", fail_commit)
    with pytest.raises(
        VectorStoreError, match="vector-store session commit failed"
    ) as error:
        index_repo(tmp_path, full=True)
    assert str(error.value.__cause__) == "injected vector commit failure"
    generation = IndexGenerationStore(tmp_path).read()
    assert generation is not None and generation.state == "failed"
    assert _published_symbol_vectors(tmp_path) == previous


def test_vector_batch_failure_aborts_the_index_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Treat vector batch failures as fatal instead of publishing partial data.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Isolated source and index root.
    monkeypatch : pytest.MonkeyPatch
        Supplies deterministic vectors and an injected batch failure.

    Returns
    -------
    None
        The failed generation is unavailable and earlier vectors are unchanged.
    """
    (tmp_path / ".codira").mkdir()
    config = tmp_path / ".codira/config.toml"
    config.write_text(
        '[backend]\nname = "sqlite"\n'
        '[embeddings]\nenabled = true\nvector_store = "sqlite"\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("CODIRA_CONFIG_FILE", str(config))
    source = tmp_path / "sample.py"
    source.write_text("def before():\n    return 1\n", encoding="utf-8")
    monkeypatch.setattr(
        sqlite_support,
        "embed_texts",
        lambda texts, *, root=None: [[1.0] * EMBEDDING_DIM for _text in texts],
    )
    active_index_backend(root=tmp_path).initialize(tmp_path)
    index_repo(tmp_path, full=True)
    previous = _published_symbol_vectors(tmp_path)
    source.write_text("def after():\n    return 2\n", encoding="utf-8")
    monkeypatch.setattr(
        sqlite_write_session, "embedding_work_batch_size", lambda *, root=None: 1
    )

    def fail_batch(
        _session: SQLiteVectorStoreWriteSession, _rows: Sequence[PreparedVectorRow]
    ) -> None:
        """Reject a staged vector batch.

        Parameters
        ----------
        _session : codira_vector_store_sqlite.SQLiteVectorStoreWriteSession
            Active staged writer.
        _rows : collections.abc.Sequence[codira.contracts.PreparedVectorRow]
            Batch whose publication is rejected.

        Returns
        -------
        None
            This function always raises.

        Raises
        ------
        RuntimeError
            Always, to simulate a vector-store failure.
        """
        message = "injected vector batch failure"
        raise RuntimeError(message)

    monkeypatch.setattr(SQLiteVectorStoreWriteSession, "store_vectors", fail_batch)
    with pytest.raises(VectorStoreError, match="vector-store .* failed"):
        index_repo(tmp_path, full=True)
    generation = IndexGenerationStore(tmp_path).read()
    assert generation is not None and generation.state == "failed"
    assert _published_symbol_vectors(tmp_path) == previous


def test_streaming_only_backend_opens_one_transactional_vector_session(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Let a streaming backend own the only staged vector-store session.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Isolated source and index root.
    monkeypatch : pytest.MonkeyPatch
        Installs a streaming-only backend view and counts write sessions.

    Returns
    -------
    None
        Full indexing succeeds with exactly one transactional vector session.
    """
    (tmp_path / ".codira").mkdir()
    config = tmp_path / ".codira/config.toml"
    config.write_text(
        '[backend]\nname = "duckdb"\n'
        '[embeddings]\nenabled = true\nvector_store = "sqlite"\n'
        '[embeddings.indexing]\nobject_types = ["symbol"]\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("CODIRA_CONFIG_FILE", str(config))
    (tmp_path / "sample.py").write_text(
        "def sample():\n    return 1\n", encoding="utf-8"
    )
    monkeypatch.setattr(
        sqlite_support,
        "embed_texts",
        lambda texts, *, root=None: [[1.0] * EMBEDDING_DIM for _text in texts],
    )
    backend = active_index_backend(root=tmp_path)
    backend.initialize(tmp_path)

    class StreamingOnlyBackend:
        """Expose DuckDB streaming while hiding its legacy bulk capability."""

        def __init__(self, wrapped: object) -> None:
            self._wrapped = wrapped

        def __getattr__(self, name: str) -> object:
            if name == "persist_full_index":
                raise AttributeError(name)
            return getattr(self._wrapped, name)

        def persist_full_index_stream(
            self, request: BackendPersistFullIndexStreamRequest
        ) -> BackendPersistFullIndexResult:
            return cast(
                "FullIndexStreamingBulkBackend", self._wrapped
            ).persist_full_index_stream(request)

    streaming_backend = StreamingOnlyBackend(backend)
    monkeypatch.setattr(
        indexer_module,
        "active_index_backend",
        lambda *, root=None: streaming_backend,
    )

    vector_store = cast(
        "SQLiteVectorStore", active_vector_store_context(tmp_path).store
    )
    original_begin = SQLiteVectorStore.begin_write_session
    opened_sessions: list[Path] = []

    def count_write_sessions(
        store: SQLiteVectorStore,
        root: Path,
        identity: VectorSetIdentity,
        config: Mapping[str, object],
    ) -> SQLiteVectorStoreWriteSession:
        """Count and open each real SQLite write session.

        Parameters
        ----------
        store : object
            SQLite vector store receiving the session request.
        root : pathlib.Path
            Repository root owning the vector database.
        identity : object
            Vector-set identity for the session.
        config : object
            Vector-store configuration.

        Returns
        -------
        codira_vector_store_sqlite.SQLiteVectorStoreWriteSession
            Real transactional write session.
        """
        opened_sessions.append(root)
        return original_begin(store, root, identity, config)

    monkeypatch.setattr(type(vector_store), "begin_write_session", count_write_sessions)

    report = index_repo(tmp_path, full=True)

    assert report.publication_ready
    assert report.indexed == 1 and report.failed == 0
    assert opened_sessions == [tmp_path]
    assert _published_symbol_vectors(tmp_path).rows


def test_legacy_vector_store_keeps_eager_analysis_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Keep the old analysis order for stores without staged-write support.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Isolated source and index root.
    monkeypatch : pytest.MonkeyPatch
        Supplies a legacy store proxy and deterministic embeddings.

    Returns
    -------
    None
        The index completes using the existing eager collection path.
    """
    (tmp_path / ".codira").mkdir()
    config = tmp_path / ".codira/config.toml"
    config.write_text(
        '[backend]\nname = "sqlite"\n'
        '[embeddings]\nenabled = true\nvector_store = "sqlite"\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("CODIRA_CONFIG_FILE", str(config))
    (tmp_path / "sample.py").write_text("def sample():\n    return 1\n")
    monkeypatch.setattr(
        sqlite_support,
        "embed_texts",
        lambda texts, *, root=None: [[1.0] * EMBEDDING_DIM for _text in texts],
    )
    backend = active_index_backend(root=tmp_path)
    backend.initialize(tmp_path)
    context = active_vector_store_context(tmp_path)

    class LegacyStore:
        """Forward the old store surface without the optional session factory."""

        def __getattr__(self, name: str) -> object:
            """Forward legacy attributes while hiding the session capability.

            Parameters
            ----------
            name : str
                Requested plugin attribute.

            Returns
            -------
            object
                Attribute supplied by the underlying store.

            Raises
            ------
            AttributeError
                If the optional session factory is requested.
            """
            if name == "begin_write_session":
                raise AttributeError(name)
            return getattr(context.store, name)

    from typing import cast

    monkeypatch.setattr(
        indexer_module,
        "active_vector_store_context",
        lambda _root: replace(context, store=cast("VectorStore", LegacyStore())),
    )
    collect = Mock(wraps=indexer_module._collect_indexed_file_analyses)
    monkeypatch.setattr(indexer_module, "_collect_indexed_file_analyses", collect)
    report = index_repo(tmp_path, full=True)
    assert report.indexed == 1 and report.failed == 0
    collect.assert_called_once()


@pytest.mark.parametrize("strategy", ["thread", "process"])
def test_staged_vector_rebuild_preserves_cached_bindings(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    strategy: Literal["thread", "process"],
) -> None:
    """Reuse materialized vectors during a concurrent full rebuild.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Isolated source and index root.
    monkeypatch : pytest.MonkeyPatch
        Supplies deterministic embeddings.
    strategy : str
        Concurrent analysis scheduler.

    Returns
    -------
    None
        Existing cached bindings survive and are reused without inference.
    """
    (tmp_path / ".codira").mkdir()
    config = tmp_path / ".codira/config.toml"
    config.write_text(
        '[backend]\nname = "sqlite"\n'
        '[embeddings]\nenabled = true\nvector_store = "sqlite"\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("CODIRA_CONFIG_FILE", str(config))
    (tmp_path / "a.py").write_text("def first():\n    return 1\n")
    (tmp_path / "b.py").write_text("def second():\n    return 2\n")
    monkeypatch.setattr(
        sqlite_support,
        "embed_texts",
        lambda texts, *, root=None: [[1.0] * EMBEDDING_DIM for _text in texts],
    )
    active_index_backend(root=tmp_path).initialize(tmp_path)
    index_repo(tmp_path, full=True)
    before = _published_symbol_vectors(tmp_path)
    inference = Mock(side_effect=AssertionError("cached vectors must be reused"))
    monkeypatch.setattr(sqlite_support, "embed_texts", inference)
    report = index_repo(
        tmp_path,
        full=True,
        analysis_concurrency=IndexConcurrencyConfig(strategy=strategy, max_workers=2),
    )
    assert report.failed == 0 and report.embeddings_reused > 0
    assert _published_symbol_vectors(tmp_path) == before
    inference.assert_not_called()


def test_full_rebuild_from_updating_seed_reuses_vectors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Rebuild a synthetic interrupted generation without recomputing vectors.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Isolated source and index root.
    monkeypatch : pytest.MonkeyPatch
        Supplies deterministic embeddings.

    Returns
    -------
    None
        A full rebuild publishes a new ready generation with cached vectors.
    """
    (tmp_path / ".codira").mkdir()
    config = tmp_path / ".codira/config.toml"
    config.write_text(
        '[backend]\nname = "sqlite"\n'
        '[embeddings]\nenabled = true\nvector_store = "sqlite"\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("CODIRA_CONFIG_FILE", str(config))
    (tmp_path / "a.py").write_text("def first():\n    return 1\n")
    (tmp_path / "b.py").write_text("def second():\n    return 2\n")
    monkeypatch.setattr(
        sqlite_support,
        "embed_texts",
        lambda texts, *, root=None: [[1.0] * EMBEDDING_DIM for _text in texts],
    )
    active_index_backend(root=tmp_path).initialize(tmp_path)
    index_repo(tmp_path, full=True)
    previous_vectors = _published_symbol_vectors(tmp_path)
    generation_store = IndexGenerationStore(tmp_path)
    previous = generation_store.read()
    assert previous is not None and previous.state == "ready"
    generation_store.write(
        transition_record(
            generation=previous.generation + 1,
            state="updating",
            last_successful_generation=previous.generation,
            failed_files=previous.failed_files,
            analysis_fingerprint=previous.analysis_fingerprint,
        )
    )
    inference = Mock(side_effect=AssertionError("cached vectors must be reused"))
    monkeypatch.setattr(sqlite_support, "embed_texts", inference)
    report = index_repo(
        tmp_path,
        full=True,
        analysis_concurrency=IndexConcurrencyConfig(strategy="thread", max_workers=2),
    )
    current = generation_store.read()
    assert current is not None and current.state == "ready"
    assert current.generation == previous.generation + 2
    assert report.failed == 0 and report.embeddings_reused > 0
    assert _published_symbol_vectors(tmp_path) == previous_vectors
    inference.assert_not_called()
