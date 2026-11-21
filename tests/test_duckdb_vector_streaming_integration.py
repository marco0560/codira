"""Check streamed indexing with the DuckDB structural and vector stores."""

from __future__ import annotations

from typing import TYPE_CHECKING

import codira_backend_duckdb.duckdb_support as duckdb_support
import codira_backend_sqlite.sqlite_support as sqlite_support
import pytest

import codira.indexer as indexer
from codira.index_generation import IndexGenerationStore
from codira.registry import active_index_backend
from codira.semantic.embeddings import EMBEDDING_DIM

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.parametrize("backend", ["sqlite", "duckdb"])
@pytest.mark.parametrize("mode", ["deferred", "immediate"])
def test_duckdb_vector_full_index_streams_without_eager_collection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, backend: str, mode: str
) -> None:
    """Stream full indexing with DuckDB vectors and either structural backend.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Isolated repository and index state.
    monkeypatch : pytest.MonkeyPatch
        Selects the plugins and rejects eager analysis collection.
    backend : str
        SQLite or DuckDB structural backend.
    mode : str
        Deferred or immediate embedding population.

    Returns
    -------
    None
        A ready structural index and its expected embedding state are published.
    """
    pytest.importorskip("duckdb")
    (tmp_path / ".codira").mkdir()
    config = tmp_path / ".codira/config.toml"
    config.write_text(
        f'[backend]\nname = "{backend}"\n'
        '[embeddings]\nenabled = true\nvector_store = "duckdb"\n'
        '[embeddings.indexing]\nobject_types = ["symbol"]\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("CODIRA_CONFIG_FILE", str(config))
    (tmp_path / "sample.py").write_text("def sample():\n    return 1\n")
    active_index_backend(root=tmp_path).initialize(tmp_path)

    def embed(texts: list[str], *, root: Path | None = None) -> list[list[float]]:
        """Return deterministic vectors for the test's immediate mode.

        Parameters
        ----------
        texts : list of str
            Texts requiring embeddings.
        root : pathlib.Path or None, optional
            Repository root supplied by the backend.

        Returns
        -------
        list of list of float
            One deterministic vector per text.
        """
        del root
        return [[1.0] * EMBEDDING_DIM for _ in texts]

    monkeypatch.setattr(sqlite_support, "embed_texts", embed)
    monkeypatch.setattr(duckdb_support, "embed_texts", embed)

    def reject_eager(*args: object, **kwargs: object) -> None:
        """Fail when the legacy all-files collector is selected.

        Parameters
        ----------
        *args, **kwargs : object
            Unused arguments supplied by the collector call.

        Returns
        -------
        None
            This function always raises.

        Raises
        ------
        AssertionError
            The indexer selected the legacy collector.
        """
        message = "eager analysis collection was selected"
        raise AssertionError(message)

    monkeypatch.setattr(indexer, "_collect_indexed_file_analyses", reject_eager)
    result = indexer.index_repo(tmp_path, full=True, embedding_index_mode=mode)
    assert result.publication_ready and result.failed == 0 and result.indexed == 1
    if mode == "deferred":
        assert result.embeddings_pending > 0 and not result.embedding_complete
    else:
        assert result.embeddings_recomputed > 0 and result.embedding_complete
    generation = IndexGenerationStore(tmp_path).read()
    assert generation is not None and generation.state == "ready"
