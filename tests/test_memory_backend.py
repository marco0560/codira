"""Contract tests for the test-only in-memory backend."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from codira_backend_sqlite import SQLiteIndexBackend
from memory_backend import MemoryIndexBackend, build_backend

import codira.indexer as indexer_module
import codira.registry as registry_module
from codira.contracts import BackendRelationQueryRequest, IndexBackend
from codira.indexer import index_repo
from codira.semantic.embeddings import EMBEDDING_DIM

if TYPE_CHECKING:
    from typing import Protocol

    import pytest

    from codira.types import DocstringIssueRow, SymbolRow

    class _ObservableBackend(Protocol):
        """Backend query surface used by comparison helpers."""

        def find_symbol(self, root: Path, name: str) -> list[SymbolRow]: ...

        def find_logical_symbols(
            self,
            root: Path,
            module_name: str,
            logical_name: str,
        ) -> list[SymbolRow]: ...

        def find_call_edges(
            self,
            request: BackendRelationQueryRequest,
        ) -> list[tuple[str, str, str | None, str | None, int]]: ...

        def find_callable_refs(
            self,
            request: BackendRelationQueryRequest,
        ) -> list[tuple[str, str, str | None, str | None, int]]: ...

        def docstring_issues(self, root: Path) -> list[DocstringIssueRow]: ...

        def embedding_inventory(
            self, root: Path
        ) -> list[tuple[str, str, int, int]]: ...

else:
    _ObservableBackend = object


class _FakeDist:
    """Entry-point distribution stub used by registry tests."""

    def __init__(self, name: str) -> None:
        """
        Store a package name for metadata lookup.

        Parameters
        ----------
        name : str
            Distribution package name.

        Returns
        -------
        None
            The stub keeps the name in memory.
        """
        self._name = name

    @property
    def metadata(self) -> dict[str, str]:
        """
        Return distribution metadata.

        Parameters
        ----------
        None

        Returns
        -------
        dict[str, str]
            Metadata containing the distribution ``Name``.
        """
        return {"Name": self._name}


class _FakeEntryPoint:
    """Entry-point stub that returns the memory backend factory."""

    name = "memory"
    dist = _FakeDist("codira-backend-memory")

    def load(self) -> object:
        """
        Return the fake entry-point target.

        Parameters
        ----------
        None

        Returns
        -------
        object
            Backend factory used by the registry.
        """
        return build_backend


def _write_fixture(root: Path) -> None:
    """
    Write a small Python package used by backend comparison tests.

    Parameters
    ----------
    root : pathlib.Path
        Temporary repository root to populate.

    Returns
    -------
    None
        Files are written below ``root``.
    """
    pkg = root / "pkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text('"""Fixture package."""\n', encoding="utf-8")
    (pkg / "helpers.py").write_text(
        '"""Helper module."""\n'
        "\n"
        "def imported_helper():\n"
        '    """Return an imported value."""\n'
        "    return 1\n",
        encoding="utf-8",
    )
    (pkg / "sample.py").write_text(
        '"""Sample module."""\n'
        "\n"
        "from pkg.helpers import imported_helper as external\n"
        "\n"
        "\n"
        "def helper():\n"
        '    """Return a local value."""\n'
        "    return 1\n"
        "\n"
        "\n"
        "def caller():\n"
        '    """Call local and imported helpers."""\n'
        "    helper()\n"
        "    external()\n"
        "    return helper\n"
        "\n"
        "\n"
        "class Demo:\n"
        '    """Demo class."""\n'
        "\n"
        "    def method(self):\n"
        '        """Call a local helper."""\n'
        "        return helper()\n",
        encoding="utf-8",
    )


def _normalize_symbols(
    root: Path, rows: list[tuple[str, str, str, str, int]]
) -> list[tuple[str, str, str, str, int]]:
    """
    Normalize absolute file paths in symbol rows.

    Parameters
    ----------
    root : pathlib.Path
        Fixture root.
    rows : list[tuple[str, str, str, str, int]]
        Backend symbol rows.

    Returns
    -------
    list[tuple[str, str, str, str, int]]
        Rows with repo-relative paths.
    """
    return [
        (typ, module, name, Path(path).relative_to(root).as_posix(), lineno)
        for typ, module, name, path, lineno in rows
    ]


def _normalize_issues(
    root: Path,
    rows: list[tuple[str, str, str, str, str, str, str, int, int | None]],
) -> list[tuple[str, str, str, str, str, str, str, int, int | None]]:
    """
    Normalize absolute file paths in docstring issue rows.

    Parameters
    ----------
    root : pathlib.Path
        Fixture root.
    rows : list[tuple[str, str, str, str, str, str, str, int, int | None]]
        Backend docstring issue rows.

    Returns
    -------
    list[tuple[str, str, str, str, str, str, str, int, int | None]]
        Rows with repo-relative paths.
    """
    return [
        (
            issue_type,
            message,
            stable_id,
            symbol_type,
            module,
            symbol,
            Path(path).relative_to(root).as_posix(),
            lineno,
            end_lineno,
        )
        for (
            issue_type,
            message,
            stable_id,
            symbol_type,
            module,
            symbol,
            path,
            lineno,
            end_lineno,
        ) in rows
    ]


def _fake_embed_texts(texts: list[str]) -> list[list[float]]:
    """
    Return deterministic vectors without loading external model artifacts.

    Parameters
    ----------
    texts : list[str]
        Text payloads to encode.

    Returns
    -------
    list[list[float]]
        One vector per text.
    """
    return [[float(index + 1)] * EMBEDDING_DIM for index, _text in enumerate(texts)]


def _index_with_backend(
    monkeypatch: pytest.MonkeyPatch,
    root: Path,
    backend: object,
) -> None:
    """
    Run the real indexer with a supplied backend.

    Parameters
    ----------
    monkeypatch : pytest.MonkeyPatch
        Fixture used to patch backend selection.
    root : pathlib.Path
        Repository root to index.
    backend : codira.contracts.IndexBackend
        Backend under test.

    Returns
    -------
    None
        The repository is indexed through ``backend``.
    """
    monkeypatch.setattr(indexer_module, "active_index_backend", lambda: backend)
    monkeypatch.setattr("codira.sqlite_backend_support.embed_texts", _fake_embed_texts)
    report = index_repo(root)
    assert report.failed == 0
    assert report.indexed == 3


def _backend_observations(
    root: Path,
    backend: _ObservableBackend,
) -> dict[str, object]:
    """
    Collect observable backend query results for comparison.

    Parameters
    ----------
    root : pathlib.Path
        Indexed fixture root.
    backend : codira.contracts.IndexBackend
        Backend under test.

    Returns
    -------
    dict[str, object]
        Normalized query observations.
    """
    return {
        "helper_symbols": _normalize_symbols(root, backend.find_symbol(root, "helper")),
        "demo_symbols": _normalize_symbols(root, backend.find_symbol(root, "Demo")),
        "logical_method": _normalize_symbols(
            root,
            backend.find_logical_symbols(root, "pkg.sample", "Demo.method"),
        ),
        "caller_edges": backend.find_call_edges(
            BackendRelationQueryRequest(
                root=root,
                name="caller",
                module="pkg.sample",
            )
        ),
        "incoming_imported": backend.find_call_edges(
            BackendRelationQueryRequest(
                root=root,
                name="imported_helper",
                module="pkg.helpers",
                incoming=True,
            )
        ),
        "caller_refs": backend.find_callable_refs(
            BackendRelationQueryRequest(
                root=root,
                name="caller",
                module="pkg.sample",
            )
        ),
        "issues": _normalize_issues(root, backend.docstring_issues(root)),
        "embedding_counts": sorted(row[3] for row in backend.embedding_inventory(root)),
    }


def test_memory_backend_implements_full_contract_without_sql_dependency() -> None:
    """
    Keep the memory backend aligned to the complete backend contract.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test asserts protocol conformance and SQL independence.
    """
    backend = build_backend()

    assert isinstance(backend, IndexBackend)
    backend_source = (
        Path(__file__).with_name("memory_backend.py").read_text(encoding="utf-8")
    )
    assert "sqlite3" not in backend_source
    assert "sqlite_backend_support" not in backend_source


def test_registry_can_select_memory_backend_entry_point(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Verify backend selection works through the standard entry-point registry.

    Parameters
    ----------
    monkeypatch : pytest.MonkeyPatch
        Fixture used to isolate registry discovery and environment.

    Returns
    -------
    None
        The test asserts the active backend is the memory plugin.
    """

    def fake_entry_points(group: str) -> list[_FakeEntryPoint]:
        if group == registry_module.BACKEND_ENTRY_POINT_GROUP:
            return [_FakeEntryPoint()]
        return []

    monkeypatch.setenv(registry_module.INDEX_BACKEND_ENV_VAR, "memory")
    monkeypatch.setattr(registry_module, "_entry_points_for_group", fake_entry_points)

    backend = registry_module.active_index_backend()

    assert isinstance(backend, MemoryIndexBackend)
    assert backend.name == "memory"


def test_memory_backend_matches_sqlite_for_indexing_contract(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Compare memory and SQLite observable behavior through the real indexer.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Pytest temporary root.
    monkeypatch : pytest.MonkeyPatch
        Fixture used to patch backend selection and embeddings.

    Returns
    -------
    None
        The test asserts both backends expose identical contract observations.
    """
    sqlite_root = tmp_path / "sqlite"
    memory_root = tmp_path / "memory"
    sqlite_root.mkdir()
    memory_root.mkdir()
    _write_fixture(sqlite_root)
    _write_fixture(memory_root)
    sqlite_backend = SQLiteIndexBackend()
    memory_backend = MemoryIndexBackend()

    _index_with_backend(monkeypatch, sqlite_root, sqlite_backend)
    sqlite_observations = _backend_observations(sqlite_root, sqlite_backend)
    _index_with_backend(monkeypatch, memory_root, memory_backend)
    memory_observations = _backend_observations(memory_root, memory_backend)

    assert memory_observations == sqlite_observations
    assert memory_backend.load_runtime_inventory(memory_root) == ("memory", "1", 1)


def test_memory_backend_supports_incremental_reuse_and_deletion(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Verify the memory backend supports indexing lifecycle operations.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository root.
    monkeypatch : pytest.MonkeyPatch
        Fixture used to patch backend selection.

    Returns
    -------
    None
        The test asserts reuse and deletion behavior across index runs.
    """
    _write_fixture(tmp_path)
    backend = MemoryIndexBackend()
    monkeypatch.setattr(indexer_module, "active_index_backend", lambda: backend)

    first = index_repo(tmp_path)
    second = index_repo(tmp_path)
    (tmp_path / "pkg" / "sample.py").unlink()
    third = index_repo(tmp_path)

    assert first.indexed == 3
    assert second.indexed == 0
    assert second.reused == 3
    assert second.embeddings_reused > 0
    assert third.deleted == 1
    assert backend.find_symbol(tmp_path, "caller") == []
