"""Tests for ADR-004 Phase 3 contract and normalization models.

Responsibilities
----------------
- Verify analyzer and backend contracts using fake implementations that hook into the existing registry.
- Ensure normalization from parser output produces the expected AnalysisResult artifacts and deterministic module data.
- Validate registry discovery, analyzer selection, and backend initialization invariants.

Design principles
-----------------
Tests rely on stub analyzers/backends and explicit fixtures so contract violations surface as deterministic failures.

Architectural role
------------------
This module belongs to the **contract verification layer** and enforces the ADR-004 Phase 3 language analyzer and backend APIs.
"""

from __future__ import annotations

import json
import sqlite3
import subprocess
import tomllib
from pathlib import Path
from typing import TYPE_CHECKING

from codira_backend_sqlite import SQLiteIndexBackend

import codira.indexer as indexer_module
import codira.registry as registry_module
from codira.analyzers import BashAnalyzer, CAnalyzer, JsonAnalyzer, PythonAnalyzer
from codira.analyzers.c import _disambiguate_function_stable_ids
from codira.cli import _run_symbol
from codira.contracts import (
    KNOWN_RETRIEVAL_CAPABILITIES,
    BackendEmbeddingCandidatesRequest,
    BackendPersistAnalysisRequest,
    BackendRelationQueryRequest,
    BackendRuntimeInventoryRequest,
    BackendSymbolInventoryItem,
    IndexBackend,
    LanguageAnalyzer,
    RetrievalProducer,
    RetrievalProducerInfo,
    split_declared_retrieval_capabilities,
)
from codira.indexer import (
    _collect_indexed_file_analyses,
    _select_language_analyzer,
    index_repo,
)
from codira.models import (
    AnalysisResult,
    CallSite,
    EnumMemberArtifact,
    FileMetadataSnapshot,
    FunctionArtifact,
    ModuleArtifact,
)
from codira.normalization import analysis_result_from_parsed
from codira.parser_ast import parse_file
from codira.query.producers import (
    CALL_GRAPH_RETRIEVAL_PRODUCER,
    EMBEDDING_RETRIEVAL_PRODUCER,
    INCLUDE_GRAPH_RETRIEVAL_PRODUCER,
    REFERENCE_RETRIEVAL_PRODUCER,
)
from codira.registry import (
    _instantiate_language_analyzers,
    active_index_backend,
    active_language_analyzers,
    missing_language_analyzer_hint,
)
from codira.scanner import (
    discovery_file_globs,
    iter_canonical_project_files,
    iter_project_files,
)
from codira.semantic.embeddings import (
    EMBEDDING_BACKEND,
    EMBEDDING_DIM,
    EMBEDDING_VERSION,
)
from codira.storage import get_db_path

if TYPE_CHECKING:
    from pytest import CaptureFixture, MonkeyPatch


class _FakeAnalyzer:
    """Small analyzer stub used to validate the protocol surface."""

    name = "fake-python"
    version = "1"
    discovery_globs: tuple[str, ...] = ("*.py",)

    def supports_path(self, path: Path) -> bool:
        """
        Report support for Python files.

        Parameters
        ----------
        path : pathlib.Path
            Candidate source path.

        Returns
        -------
        bool
            ``True`` for Python files.
        """
        return path.suffix == ".py"

    def analyze_file(self, path: Path, root: Path) -> AnalysisResult:
        """
        Analyze one file through the existing Python parser path.

        Parameters
        ----------
        path : pathlib.Path
            Source file to analyze.
        root : pathlib.Path
            Repository root used for module resolution.

        Returns
        -------
        codira.models.AnalysisResult
            Normalized analysis result for the file.
        """
        parsed = parse_file(path, root)
        return analysis_result_from_parsed(path, parsed)


class _FakeBackend:
    """Small backend stub used to validate the protocol surface."""

    name = "fake-backend"
    version = "1"

    def open_connection(self, root: Path) -> sqlite3.Connection:
        """
        Open an in-memory SQLite connection for protocol validation.

        Parameters
        ----------
        root : pathlib.Path
            Repository root.

        Returns
        -------
        sqlite3.Connection
            In-memory SQLite connection handle.
        """
        del root
        return sqlite3.connect(":memory:")

    def load_runtime_inventory(
        self,
        root: Path,
        *,
        conn: sqlite3.Connection | None = None,
    ) -> tuple[str, str, int] | None:
        """
        Return no persisted runtime inventory for the fake backend.

        Parameters
        ----------
        root : pathlib.Path
            Repository root.
        conn : sqlite3.Connection | None, optional
            Optional SQLite connection.

        Returns
        -------
        tuple[str, str, int] | None
            ``None`` for protocol validation.
        """
        del root, conn
        return None

    def load_analyzer_inventory(
        self,
        root: Path,
        *,
        conn: sqlite3.Connection | None = None,
    ) -> list[tuple[str, str, str]]:
        """
        Return no persisted analyzer inventory for the fake backend.

        Parameters
        ----------
        root : pathlib.Path
            Repository root.
        conn : sqlite3.Connection | None, optional
            Optional SQLite connection.

        Returns
        -------
        list[tuple[str, str, str]]
            Empty analyzer inventory for protocol validation.
        """
        del root, conn
        return []

    def initialize(self, root: Path) -> None:
        """
        Perform no-op initialization for the fake backend.

        Parameters
        ----------
        root : pathlib.Path
            Repository root.

        Returns
        -------
        None
            This fake backend keeps no state.
        """
        return

    def load_existing_file_hashes(
        self,
        root: Path,
        *,
        conn: sqlite3.Connection | None = None,
    ) -> dict[str, str]:
        """
        Return an empty file-hash mapping.

        Parameters
        ----------
        root : pathlib.Path
            Repository root.
        conn : sqlite3.Connection | None, optional
            Optional SQLite connection.

        Returns
        -------
        dict[str, str]
            Empty mapping for protocol validation.
        """
        del conn
        return {}

    def load_existing_file_ownership(
        self,
        root: Path,
        *,
        conn: sqlite3.Connection | None = None,
    ) -> dict[str, tuple[str, str]]:
        """
        Return an empty analyzer-ownership mapping.

        Parameters
        ----------
        root : pathlib.Path
            Repository root.
        conn : sqlite3.Connection | None, optional
            Optional SQLite connection.

        Returns
        -------
        dict[str, tuple[str, str]]
            Empty ownership mapping for protocol validation.
        """
        del root, conn
        return {}

    def delete_paths(
        self,
        root: Path,
        *,
        paths: list[str],
        conn: sqlite3.Connection | None = None,
    ) -> None:
        """
        Perform no-op path deletion for the fake backend.

        Parameters
        ----------
        root : pathlib.Path
            Repository root.
        paths : list[str]
            Paths that would be deleted.
        conn : sqlite3.Connection | None, optional
            Optional SQLite connection.

        Returns
        -------
        None
            This fake backend keeps no state.
        """
        del conn
        return

    def clear_index(
        self,
        root: Path,
        *,
        conn: object | None = None,
    ) -> None:
        """
        Perform no-op index clearing for the fake backend.

        Parameters
        ----------
        root : pathlib.Path
            Repository root.
        conn : object | None, optional
            Optional backend connection.

        Returns
        -------
        None
            This fake backend keeps no state.
        """
        del root, conn
        return

    def purge_skipped_docstring_issues(
        self,
        root: Path,
        *,
        conn: object | None = None,
    ) -> None:
        """
        Perform no-op skipped-docstring cleanup for the fake backend.

        Parameters
        ----------
        root : pathlib.Path
            Repository root.
        conn : object | None, optional
            Optional backend connection.

        Returns
        -------
        None
            This fake backend keeps no state.
        """
        del root, conn
        return

    def load_previous_embeddings_by_path(
        self,
        root: Path,
        *,
        paths: list[str],
        embedding_backend: object,
        conn: object | None = None,
    ) -> dict[str, dict[str, object]]:
        """
        Return no reusable semantic artifacts for the fake backend.

        Parameters
        ----------
        root : pathlib.Path
            Repository root.
        paths : list[str]
            Paths selected for replacement.
        embedding_backend : object
            Active embedding backend placeholder.
        conn : object | None, optional
            Optional backend connection.

        Returns
        -------
        dict[str, dict[str, object]]
            Empty reusable-artifact mapping.
        """
        del root, paths, embedding_backend, conn
        return {}

    def persist_analysis(
        self,
        request: BackendPersistAnalysisRequest,
    ) -> tuple[int, int]:
        """
        Count normalized functions as a stand-in for persisted artifacts.

        Parameters
        ----------
        request : BackendPersistAnalysisRequest
            Persistence request carrying metadata, normalized analysis, and
            optional backend state placeholders.

        Returns
        -------
        tuple[int, int]
            Recomputed and reused semantic-artifact counts.
        """
        return (len(request.analysis.iter_functions()), 0)

    def count_reusable_embeddings(
        self,
        root: Path,
        *,
        paths: list[str],
        conn: sqlite3.Connection | None = None,
    ) -> int:
        """
        Count supplied paths as a stand-in reusable-artifact metric.

        Parameters
        ----------
        root : pathlib.Path
            Repository root.
        paths : list[str]
            Reusable paths.
        conn : sqlite3.Connection | None, optional
            Optional SQLite connection.

        Returns
        -------
        int
            Number of reusable paths.
        """
        del root, conn
        return len(paths)

    def rebuild_derived_indexes(
        self,
        root: Path,
        *,
        conn: sqlite3.Connection | None = None,
    ) -> None:
        """
        Perform no-op derived-index rebuilding.

        Parameters
        ----------
        root : pathlib.Path
            Repository root.
        conn : sqlite3.Connection | None, optional
            Optional SQLite connection.

        Returns
        -------
        None
            This fake backend keeps no state.
        """
        del conn
        return

    def list_symbols_in_module(
        self,
        root: Path,
        module: str,
        *,
        prefix: str | None = None,
        limit: int = 20,
        conn: sqlite3.Connection | None = None,
    ) -> list[tuple[str, str, str, str, int]]:
        """
        Return no symbol rows for protocol validation.

        Parameters
        ----------
        root : pathlib.Path
            Repository root.
        module : str
            Dotted module name.
        prefix : str | None, optional
            Optional path filter.
        limit : int, optional
            Maximum result count.
        conn : sqlite3.Connection | None, optional
            Optional SQLite connection.

        Returns
        -------
        list[tuple[str, str, str, str, int]]
            Empty symbol rows for protocol validation.
        """
        del root, module, prefix, limit, conn
        return []

    def find_symbol(
        self,
        root: Path,
        name: str,
        *,
        prefix: str | None = None,
        conn: sqlite3.Connection | None = None,
    ) -> list[tuple[str, str, str, str, int]]:
        """
        Return no symbol matches for protocol validation.

        Parameters
        ----------
        root : pathlib.Path
            Repository root.
        name : str
            Exact symbol name.
        prefix : str | None, optional
            Optional path filter.
        conn : sqlite3.Connection | None, optional
            Optional SQLite connection.

        Returns
        -------
        list[tuple[str, str, str, str, int]]
            Empty symbol rows for protocol validation.
        """
        del root, name, prefix, conn
        return []

    def symbol_inventory(
        self,
        root: Path,
        *,
        prefix: str | None = None,
        include_tests: bool = False,
        limit: int = 1000,
        conn: sqlite3.Connection | None = None,
    ) -> list[BackendSymbolInventoryItem]:
        """
        Return no inventory rows for protocol validation.

        Parameters
        ----------
        root : pathlib.Path
            Repository root.
        prefix : str | None, optional
            Optional path filter.
        include_tests : bool, optional
            Whether test modules are included.
        limit : int, optional
            Maximum result count.
        conn : sqlite3.Connection | None, optional
            Optional SQLite connection.

        Returns
        -------
        list[codira.contracts.BackendSymbolInventoryItem]
            Empty symbol inventory rows for protocol validation.
        """
        del root, prefix, include_tests, limit, conn
        return []

    def find_symbol_overloads(
        self,
        root: Path,
        symbol: tuple[str, str, str, str, int],
        *,
        conn: sqlite3.Connection | None = None,
    ) -> list[tuple[str, str, int, str, int, int | None, str | None]]:
        """
        Return no overload metadata for protocol validation.

        Parameters
        ----------
        root : pathlib.Path
            Repository root.
        symbol : tuple[str, str, str, str, int]
            Canonical symbol row.
        conn : sqlite3.Connection | None, optional
            Optional SQLite connection.

        Returns
        -------
        list[tuple[str, str, int, str, int, int | None, str | None]]
            Empty overload rows for protocol validation.
        """
        del root, symbol, conn
        return []

    def find_symbol_enum_members(
        self,
        root: Path,
        symbol: tuple[str, str, str, str, int],
        *,
        conn: sqlite3.Connection | None = None,
    ) -> list[tuple[str, str, int, str, str, int]]:
        """
        Return no enum-member metadata for protocol validation.

        Parameters
        ----------
        root : pathlib.Path
            Repository root.
        symbol : tuple[str, str, str, str, int]
            Canonical symbol row.
        conn : sqlite3.Connection | None, optional
            Optional SQLite connection.

        Returns
        -------
        list[tuple[str, str, int, str, str, int]]
            Empty enum-member rows for protocol validation.
        """
        del root, symbol, conn
        return []

    def docstring_issues(
        self,
        root: Path,
        *,
        prefix: str | None = None,
        conn: sqlite3.Connection | None = None,
    ) -> list[tuple[str, str, str, str, str, str, str, int, int | None]]:
        """
        Return no docstring issues for protocol validation.

        Parameters
        ----------
        root : pathlib.Path
            Repository root.
        prefix : str | None, optional
            Optional path filter.
        conn : sqlite3.Connection | None, optional
            Optional SQLite connection.

        Returns
        -------
        list[tuple[str, str, str, str, str, str, str, int, int | None]]
            Empty docstring issue rows for protocol validation.
        """
        del root, prefix, conn
        return []

    def find_call_edges(
        self,
        request: BackendRelationQueryRequest,
    ) -> list[tuple[str, str, str | None, str | None, int]]:
        """
        Return no call edges for protocol validation.

        Parameters
        ----------
        request : BackendRelationQueryRequest
            Exact relation lookup request.

        Returns
        -------
        list[tuple[str, str, str | None, str | None, int]]
            Empty call-edge rows for protocol validation.
        """
        del request
        return []

    def find_callable_refs(
        self,
        request: BackendRelationQueryRequest,
    ) -> list[tuple[str, str, str | None, str | None, int]]:
        """
        Return no callable references for protocol validation.

        Parameters
        ----------
        request : BackendRelationQueryRequest
            Exact relation lookup request.

        Returns
        -------
        list[tuple[str, str, str | None, str | None, int]]
            Empty callable-reference rows for protocol validation.
        """
        del request
        return []

    def find_include_edges(
        self,
        request: BackendRelationQueryRequest,
    ) -> list[tuple[str, str, str, int]]:
        """
        Return no include edges for protocol validation.

        Parameters
        ----------
        request : BackendRelationQueryRequest
            Exact relation lookup request.

        Returns
        -------
        list[tuple[str, str, str, int]]
            Empty include-edge rows for protocol validation.
        """
        del request
        return []

    def find_logical_symbols(
        self,
        root: Path,
        module_name: str,
        logical_name: str,
        *,
        prefix: str | None = None,
        conn: sqlite3.Connection | None = None,
    ) -> list[tuple[str, str, str, str, int]]:
        """
        Return no logical-symbol rows for protocol validation.

        Parameters
        ----------
        root : pathlib.Path
            Repository root.
        module_name : str
            Owning module name.
        logical_name : str
            Logical callable name.
        prefix : str | None, optional
            Optional path filter.
        conn : sqlite3.Connection | None, optional
            Optional SQLite connection.

        Returns
        -------
        list[tuple[str, str, str, str, int]]
            Empty symbol rows for protocol validation.
        """
        del root, module_name, logical_name, prefix, conn
        return []

    def logical_symbol_name(
        self,
        root: Path,
        symbol: tuple[str, str, str, str, int],
        *,
        conn: sqlite3.Connection | None = None,
    ) -> str:
        """
        Return the symbol name as a stand-in logical identity.

        Parameters
        ----------
        root : pathlib.Path
            Repository root.
        symbol : tuple[str, str, str, str, int]
            Indexed symbol row.
        conn : sqlite3.Connection | None, optional
            Optional SQLite connection.

        Returns
        -------
        str
            Symbol name extracted from the supplied row.
        """
        del root, conn
        return symbol[2]

    def embedding_inventory(
        self,
        root: Path,
        *,
        conn: sqlite3.Connection | None = None,
    ) -> list[tuple[str, str, int, int]]:
        """
        Return no embedding inventory rows for protocol validation.

        Parameters
        ----------
        root : pathlib.Path
            Repository root.
        conn : sqlite3.Connection | None, optional
            Optional SQLite connection.

        Returns
        -------
        list[tuple[str, str, int, int]]
            Empty inventory rows for protocol validation.
        """
        del root, conn
        return []

    def embedding_candidates(
        self,
        request: BackendEmbeddingCandidatesRequest,
    ) -> list[tuple[float, tuple[str, str, str, str, int]]]:
        """
        Return no embedding candidates for protocol validation.

        Parameters
        ----------
        request : BackendEmbeddingCandidatesRequest
            Embedding candidate lookup request.

        Returns
        -------
        list[tuple[float, tuple[str, str, str, str, int]]]
            Empty candidate rows for protocol validation.
        """
        del request
        return []

    def prune_orphaned_embeddings(
        self,
        root: Path,
        *,
        conn: sqlite3.Connection | None = None,
    ) -> None:
        """
        Perform no-op orphaned-embedding cleanup for protocol validation.

        Parameters
        ----------
        root : pathlib.Path
            Repository root.
        conn : sqlite3.Connection | None, optional
            Optional SQLite connection.

        Returns
        -------
        None
            This fake backend keeps no state.
        """
        del root, conn
        return

    def persist_runtime_inventory(
        self,
        request: BackendRuntimeInventoryRequest,
    ) -> None:
        """
        Perform no-op runtime inventory persistence for the fake backend.

        Parameters
        ----------
        request : BackendRuntimeInventoryRequest
            Runtime inventory persistence request.

        Returns
        -------
        None
            This fake backend keeps no state.
        """
        del request
        return

    def commit(self, root: Path, *, conn: object) -> None:
        """
        Perform no-op commit for the fake backend.

        Parameters
        ----------
        root : pathlib.Path
            Repository root.
        conn : object
            Backend connection placeholder.

        Returns
        -------
        None
            This fake backend keeps no state.
        """
        del root, conn
        return

    def close_connection(self, conn: object) -> None:
        """
        Perform no-op connection close for the fake backend.

        Parameters
        ----------
        conn : object
            Backend connection placeholder.

        Returns
        -------
        None
            This fake backend keeps no state.
        """
        del conn
        return

    def current_embedding_state_matches(
        self,
        root: Path,
        *,
        embedding_backend: object,
        conn: sqlite3.Connection | None = None,
    ) -> bool:
        """
        Report a matching embedding state for protocol validation.

        Parameters
        ----------
        root : pathlib.Path
            Repository root.
        embedding_backend : object
            Backend metadata placeholder.
        conn : sqlite3.Connection | None, optional
            Optional SQLite connection.

        Returns
        -------
        bool
            Always ``True`` for protocol validation.
        """
        del root, embedding_backend, conn
        return True


class _FakeRetrievalProducer:
    """Small retrieval-producer stub used to validate the protocol surface."""

    def retrieval_producer_info(self) -> RetrievalProducerInfo:
        """
        Return deterministic producer identity metadata.

        Parameters
        ----------
        None

        Returns
        -------
        codira.contracts.RetrievalProducerInfo
            Producer and capability-version metadata.
        """
        return RetrievalProducerInfo(
            producer_name="fake-producer",
            producer_version="1",
            capability_version="1",
        )

    def retrieval_capabilities(self) -> tuple[str, ...]:
        """
        Return deterministic capability declarations.

        Parameters
        ----------
        None

        Returns
        -------
        tuple[str, ...]
            Declared capability names.
        """
        return ("symbol_lookup", "graph_relations", "future_extension")


def test_analysis_result_from_parsed_normalizes_python_artifacts(
    tmp_path: Path,
) -> None:
    """
    Normalize current parser output into the ADR-004 artifact model.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary directory provided by pytest.

    Returns
    -------
    None
        The test asserts normalized module, function, method, call, and import
        artifacts.
    """
    module = tmp_path / "pkg" / "sample.py"
    module.parent.mkdir()
    module.write_text(
        '"""Fixture module."""\n'
        "\n"
        "from pkg.helpers import helper as external\n"
        "\n"
        "@pytest.fixture\n"
        "def sample_fixture():\n"
        '    """Build the sample payload."""\n'
        "    return 1\n"
        "\n"
        "def top_level(value):\n"
        '    """Return the direct helper call."""\n'
        "    return external(value)\n"
        "\n"
        "class Demo:\n"
        "    def method(self):\n"
        '        """Return the imported helper."""\n'
        "        assert external is not None\n"
        '        return {"helper": external}\n',
        encoding="utf-8",
    )

    parsed = parse_file(module, tmp_path)
    result = analysis_result_from_parsed(module, parsed)

    assert result.module.name == "pkg.sample"
    assert tuple(import_row.name for import_row in result.imports) == (
        "pkg.helpers.helper",
    )
    assert tuple(function.name for function in result.functions) == (
        "sample_fixture",
        "top_level",
    )
    assert result.functions[0].decorators == ("pytest.fixture",)
    assert result.functions[0].has_asserts == 0
    assert tuple(class_row.name for class_row in result.classes) == ("Demo",)
    assert result.classes[0].methods[0].logical_name(class_name="Demo") == "Demo.method"
    assert result.classes[0].methods[0].has_asserts == 1
    assert tuple(call.target for call in result.iter_call_sites()) == ("external",)
    assert tuple(ref.target for ref in result.iter_callable_references()) == (
        "external",
    )


def test_analysis_result_from_parsed_ignores_python_overload_stubs(
    tmp_path: Path,
) -> None:
    """
    Ignore typing overload stubs when normalizing runtime callables.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary directory provided by pytest.

    Returns
    -------
    None
        The test asserts overload declarations do not create duplicate runtime
        function or method artifacts.
    """
    module = tmp_path / "pkg" / "sample.py"
    module.parent.mkdir()
    module.write_text(
        "import typing\n"
        "from typing import overload\n"
        "\n"
        "@overload\n"
        "def build(value: int) -> int: ...\n"
        "\n"
        "@typing.overload\n"
        "def build(value: str) -> str: ...\n"
        "\n"
        "def build(value):\n"
        "    return value\n"
        "\n"
        "class Demo:\n"
        "    @overload\n"
        "    def load(self, value: int) -> int: ...\n"
        "\n"
        "    def load(self, value):\n"
        "        return value\n",
        encoding="utf-8",
    )

    parsed = parse_file(module, tmp_path)
    result = analysis_result_from_parsed(module, parsed)

    assert [(function.name, function.lineno) for function in result.functions] == [
        ("build", 10)
    ]
    assert [(method.name, method.lineno) for method in result.classes[0].methods] == [
        ("load", 17)
    ]
    assert tuple(function.stable_id for function in result.functions) == (
        "python:function:pkg.sample:build",
    )
    assert tuple(method.stable_id for method in result.classes[0].methods) == (
        "python:method:pkg.sample:Demo.load",
    )
    assert tuple(overload.stable_id for overload in result.functions[0].overloads) == (
        "python:overload:pkg.sample:build:1",
        "python:overload:pkg.sample:build:2",
    )
    assert tuple(
        overload.parent_stable_id for overload in result.functions[0].overloads
    ) == (
        "python:function:pkg.sample:build",
        "python:function:pkg.sample:build",
    )
    assert tuple(overload.ordinal for overload in result.functions[0].overloads) == (
        1,
        2,
    )
    assert tuple(overload.signature for overload in result.functions[0].overloads) == (
        "build(value)",
        "build(value)",
    )
    assert tuple(
        overload.stable_id for overload in result.classes[0].methods[0].overloads
    ) == ("python:overload:pkg.sample:Demo.load:1",)
    assert tuple(
        overload.parent_stable_id for overload in result.classes[0].methods[0].overloads
    ) == ("python:method:pkg.sample:Demo.load",)


def test_analysis_result_from_parsed_extracts_python_type_alias_declarations(
    tmp_path: Path,
) -> None:
    """
    Normalize explicit top-level Python type aliases as declarations.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary directory provided by pytest.

    Returns
    -------
    None
        The test asserts only explicit top-level type aliases become
        declaration artifacts.
    """
    module = tmp_path / "pkg" / "sample.py"
    module.parent.mkdir()
    module.write_text(
        "import typing\n"
        "from typing import Final, TypeAlias\n"
        "\n"
        "type UserId = int\n"
        "Slug: TypeAlias = str\n"
        "Metadata: typing.TypeAlias = dict[str, int]\n"
        "VALUE = 1\n"
        "TIMEOUT = (1, 2, 3)\n"
        "PORT: int = 8080\n"
        'NAME: Final[str] = "codira"\n'
        "ALIAS = VALUE + 1\n"
        "_PRIVATE = 2\n"
        "\n"
        "class Demo:\n"
        "    Alias: TypeAlias = str\n",
        encoding="utf-8",
    )

    parsed = parse_file(module, tmp_path)
    result = analysis_result_from_parsed(module, parsed)

    assert [(decl.kind, decl.name, decl.lineno) for decl in result.declarations] == [
        ("type_alias", "UserId", 4),
        ("type_alias", "Slug", 5),
        ("type_alias", "Metadata", 6),
        ("constant", "VALUE", 7),
        ("constant", "TIMEOUT", 8),
        ("constant", "PORT", 9),
        ("constant", "NAME", 10),
    ]
    assert [(decl.name, decl.signature) for decl in result.declarations] == [
        ("UserId", "type UserId = int"),
        ("Slug", "Slug: TypeAlias = str"),
        ("Metadata", "Metadata: typing.TypeAlias = dict[str, int]"),
        ("VALUE", "VALUE = 1"),
        ("TIMEOUT", "TIMEOUT = (1, 2, 3)"),
        ("PORT", "PORT: int = 8080"),
        ("NAME", 'NAME: Final[str] = "codira"'),
    ]
    assert tuple(decl.stable_id for decl in result.declarations) == (
        "python:type_alias:pkg.sample:UserId",
        "python:type_alias:pkg.sample:Slug",
        "python:type_alias:pkg.sample:Metadata",
        "python:constant:pkg.sample:VALUE",
        "python:constant:pkg.sample:TIMEOUT",
        "python:constant:pkg.sample:PORT",
        "python:constant:pkg.sample:NAME",
    )


def test_sqlite_backend_persists_python_overload_metadata(
    tmp_path: Path,
) -> None:
    """
    Persist overload metadata as child rows under canonical callables.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary directory provided by pytest.

    Returns
    -------
    None
        The test asserts overload rows round-trip through the SQLite backend.
    """
    module = tmp_path / "pkg" / "sample.py"
    module.parent.mkdir()
    module.write_text(
        "from typing import overload\n"
        "\n"
        "@overload\n"
        "def build(value: int) -> int: ...\n"
        "\n"
        "@overload\n"
        "def build(value: str) -> str: ...\n"
        "\n"
        "def build(value):\n"
        "    return value\n",
        encoding="utf-8",
    )

    backend = SQLiteIndexBackend()
    backend.initialize(tmp_path)

    parsed = parse_file(module, tmp_path)
    analysis = analysis_result_from_parsed(module, parsed)
    snapshot = FileMetadataSnapshot(
        path=module,
        sha256="overload123",
        mtime=1.0,
        size=module.stat().st_size,
    )

    backend.persist_analysis(
        BackendPersistAnalysisRequest(
            root=tmp_path,
            file_metadata=snapshot,
            analysis=analysis,
        )
    )

    symbol = backend.find_symbol(tmp_path, "build")[0]
    assert backend.find_symbol_overloads(tmp_path, symbol) == [
        (
            "python:overload:pkg.sample:build:1",
            "python:function:pkg.sample:build",
            1,
            "build(value)",
            4,
            4,
            None,
        ),
        (
            "python:overload:pkg.sample:build:2",
            "python:function:pkg.sample:build",
            2,
            "build(value)",
            7,
            7,
            None,
        ),
    ]


def test_run_symbol_json_includes_overload_metadata(
    tmp_path: Path,
    capsys: CaptureFixture[str],
) -> None:
    """
    Render overload metadata only in JSON symbol output.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary directory provided by pytest.
    capsys : pytest.CaptureFixture[str]
        Captured output fixture.

    Returns
    -------
    None
        The test asserts the JSON payload carries overload detail.
    """
    module = tmp_path / "pkg" / "sample.py"
    module.parent.mkdir()
    module.write_text(
        "from typing import overload\n"
        "\n"
        "@overload\n"
        "def build(value: int) -> int: ...\n"
        "\n"
        "def build(value):\n"
        "    return value\n",
        encoding="utf-8",
    )

    backend = SQLiteIndexBackend()
    backend.initialize(tmp_path)
    parsed = parse_file(module, tmp_path)
    analysis = analysis_result_from_parsed(module, parsed)
    snapshot = FileMetadataSnapshot(
        path=module,
        sha256="json-overload",
        mtime=1.0,
        size=module.stat().st_size,
    )
    backend.persist_analysis(
        BackendPersistAnalysisRequest(
            root=tmp_path,
            file_metadata=snapshot,
            analysis=analysis,
        )
    )

    assert _run_symbol(tmp_path, "build", as_json=True) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["results"] == [
        {
            "type": "function",
            "module": "pkg.sample",
            "name": "build",
            "file": str(module),
            "lineno": 6,
            "overloads": [
                {
                    "kind": "overload",
                    "stable_id": "python:overload:pkg.sample:build:1",
                    "parent_stable_id": "python:function:pkg.sample:build",
                    "ordinal": 1,
                    "signature": "build(value)",
                    "lineno": 4,
                    "end_lineno": 4,
                    "docstring": None,
                }
            ],
        }
    ]


def test_run_symbol_json_includes_enum_member_metadata(
    tmp_path: Path,
    capsys: CaptureFixture[str],
) -> None:
    """
    Render enum-member metadata only in JSON symbol output.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary directory provided by pytest.
    capsys : pytest.CaptureFixture[str]
        Captured output fixture.

    Returns
    -------
    None
        The test asserts the JSON payload carries enum-member detail.
    """
    source = tmp_path / "native" / "types.h"
    source.parent.mkdir()
    source.write_text(
        "enum Color { RED, GREEN = 3, BLUE };\n",
        encoding="utf-8",
    )

    backend = SQLiteIndexBackend()
    backend.initialize(tmp_path)
    analysis = CAnalyzer().analyze_file(source, tmp_path)
    snapshot = FileMetadataSnapshot(
        path=source,
        sha256="json-enum-members",
        mtime=1.0,
        size=source.stat().st_size,
    )
    backend.persist_analysis(
        BackendPersistAnalysisRequest(
            root=tmp_path,
            file_metadata=snapshot,
            analysis=analysis,
        )
    )

    assert _run_symbol(tmp_path, "Color", as_json=True) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["results"] == [
        {
            "type": "enum",
            "module": "native.types",
            "name": "Color",
            "file": str(source),
            "lineno": 1,
            "enum_members": [
                {
                    "kind": "enum_member",
                    "stable_id": "c:enum_member:native/types.h:Color:1",
                    "parent_stable_id": "c:enum:native/types.h:Color",
                    "ordinal": 1,
                    "name": "RED",
                    "signature": "RED",
                    "lineno": 1,
                },
                {
                    "kind": "enum_member",
                    "stable_id": "c:enum_member:native/types.h:Color:2",
                    "parent_stable_id": "c:enum:native/types.h:Color",
                    "ordinal": 2,
                    "name": "GREEN",
                    "signature": "GREEN = 3",
                    "lineno": 1,
                },
                {
                    "kind": "enum_member",
                    "stable_id": "c:enum_member:native/types.h:Color:3",
                    "parent_stable_id": "c:enum:native/types.h:Color",
                    "ordinal": 3,
                    "name": "BLUE",
                    "signature": "BLUE",
                    "lineno": 1,
                },
            ],
        }
    ]


def test_run_symbol_json_includes_python_constant_detail(
    tmp_path: Path,
    capsys: CaptureFixture[str],
) -> None:
    """
    Render Python constant detail only in JSON symbol output.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary directory provided by pytest.
    capsys : pytest.CaptureFixture[str]
        Captured output fixture.

    Returns
    -------
    None
        The test asserts the JSON payload carries constant detail.
    """
    module = tmp_path / "pkg" / "sample.py"
    module.parent.mkdir()
    module.write_text(
        'NAME: str = "codira"\n',
        encoding="utf-8",
    )

    backend = SQLiteIndexBackend()
    backend.initialize(tmp_path)
    analysis = PythonAnalyzer().analyze_file(module, tmp_path)
    snapshot = FileMetadataSnapshot(
        path=module,
        sha256="json-constant",
        mtime=1.0,
        size=module.stat().st_size,
        analyzer_name="python",
        analyzer_version=PythonAnalyzer().version,
    )
    backend.persist_analysis(
        BackendPersistAnalysisRequest(
            root=tmp_path,
            file_metadata=snapshot,
            analysis=analysis,
        )
    )

    assert _run_symbol(tmp_path, "NAME", as_json=True) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["results"] == [
        {
            "type": "constant",
            "module": "pkg.sample",
            "name": "NAME",
            "file": str(module),
            "lineno": 1,
            "constant_detail": {
                "kind": "constant_detail",
                "annotation": "str",
                "value": '"codira"',
            },
        }
    ]


def test_analysis_result_from_parsed_disambiguates_property_accessors(
    tmp_path: Path,
) -> None:
    """
    Assign distinct stable IDs to Python property accessors.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary directory provided by pytest.

    Returns
    -------
    None
        The test asserts getter and setter methods do not collide.
    """
    module = tmp_path / "pkg" / "sample.py"
    module.parent.mkdir()
    module.write_text(
        "class Demo:\n"
        "    @property\n"
        "    def value(self):\n"
        "        return 1\n"
        "\n"
        "    @value.setter\n"
        "    def value(self, new_value):\n"
        "        self._value = new_value\n",
        encoding="utf-8",
    )

    parsed = parse_file(module, tmp_path)
    result = analysis_result_from_parsed(module, parsed)

    methods = result.classes[0].methods
    assert tuple(method.name for method in methods) == ("value", "value")
    assert tuple(method.stable_id for method in methods) == (
        "python:method:pkg.sample:Demo.value",
        "python:method:pkg.sample:Demo.value:setter",
    )


def test_parse_file_excludes_nested_helper_control_flow_from_outer_metadata(
    tmp_path: Path,
) -> None:
    """
    Keep nested helper control flow out of outer callable metadata.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary directory provided by pytest.

    Returns
    -------
    None
        The test asserts nested helper ``return``, ``yield``, and ``raise``
        statements do not affect the outer function flags.
    """
    module = tmp_path / "pkg" / "sample.py"
    module.parent.mkdir()
    module.write_text(
        "import contextlib\n"
        "\n"
        "def outer() -> None:\n"
        '    """Exercise nested helpers."""\n'
        "    @contextlib.contextmanager\n"
        "    def locked():\n"
        "        yield\n"
        "\n"
        "    def compute() -> int:\n"
        "        return 1\n"
        "\n"
        "    def fail() -> None:\n"
        '        raise RuntimeError("boom")\n'
        "\n"
        "    with locked():\n"
        "        pass\n",
        encoding="utf-8",
    )

    parsed = parse_file(module, tmp_path)
    function = parsed["functions"][0]

    assert function["name"] == "outer"
    assert function["returns_value"] == 0
    assert function["yields_value"] == 0
    assert function["raises"] == 0


def test_language_analyzer_index_backend_and_retrieval_protocols_are_runtime_checkable() -> (
    None
):
    """
    Ensure the Phase 3 protocol types accept conforming implementations.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test asserts runtime protocol compatibility for analyzer, backend,
        and retrieval-producer stubs.
    """
    assert isinstance(PythonAnalyzer(), LanguageAnalyzer)
    assert isinstance(CAnalyzer(), LanguageAnalyzer)
    assert isinstance(_FakeAnalyzer(), LanguageAnalyzer)
    assert isinstance(_FakeBackend(), IndexBackend)
    assert isinstance(_FakeRetrievalProducer(), RetrievalProducer)
    assert isinstance(EMBEDDING_RETRIEVAL_PRODUCER, RetrievalProducer)
    assert isinstance(CALL_GRAPH_RETRIEVAL_PRODUCER, RetrievalProducer)
    assert isinstance(REFERENCE_RETRIEVAL_PRODUCER, RetrievalProducer)
    assert isinstance(INCLUDE_GRAPH_RETRIEVAL_PRODUCER, RetrievalProducer)


def test_split_declared_retrieval_capabilities_partitions_known_and_unknown() -> None:
    """
    Partition declared retrieval capabilities deterministically.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test asserts known capabilities remain ordered and unknown
        extensions are retained for diagnostics.
    """
    known, unknown = split_declared_retrieval_capabilities(
        (
            "symbol_lookup",
            "graph_relations",
            "symbol_lookup",
            "future_extension",
            " ",
            "embedding_similarity",
        )
    )

    assert known == (
        "symbol_lookup",
        "graph_relations",
        "embedding_similarity",
    )
    assert unknown == ("future_extension",)
    assert "symbol_lookup" in KNOWN_RETRIEVAL_CAPABILITIES


def test_root_optional_dependencies_support_monorepo_bundle_install() -> None:
    """
    Keep root extras compatible with editable installs in the current monorepo.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test asserts the root package keeps the curated bundle aligned to
        the first-party distribution set and preserves the canonical docs extra,
        including documentation navigation plugins.
    """
    with Path("pyproject.toml").open("rb") as pyproject_file:
        pyproject = tomllib.load(pyproject_file)
    project = pyproject["project"]

    optional_dependencies = project["optional-dependencies"]

    assert optional_dependencies["docs"] == [
        "mkdocs>=1.6,<2.0",
        "mkdocs-material>=9.7,<10.0",
        "mkdocs-awesome-pages-plugin>=2.10,<3.0",
        "mkdocstrings[python]>=1.0,<2.0",
    ]
    assert optional_dependencies["bundle-official"] == [
        "sentence-transformers>=5.4,<6.0",
        "codira-analyzer-python==1.5.2",
        "codira-analyzer-json==1.5.0",
        "codira-analyzer-c==1.5.5",
        "codira-analyzer-bash==1.5.0",
        "codira-backend-sqlite==1.5.2",
    ]
    assert pyproject.get("tool", {}).get("poetry") is None


def test_active_phase_8_registries_expose_default_backend_and_analyzers() -> None:
    """
    Keep the Phase 8 registry defaults explicit and runtime-checkable.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test asserts the default backend and analyzer registry instances.
    """
    backend = active_index_backend()
    analyzers = active_language_analyzers()

    assert isinstance(backend, IndexBackend)
    assert isinstance(backend, SQLiteIndexBackend)
    assert [analyzer.name for analyzer in analyzers] == ["python", "json", "c", "bash"]


def test_indexer_sqlite_backend_symbol_reexports_package_backend() -> None:
    """
    Keep the historical indexer backend symbol as a package-backed re-export.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test asserts core no longer owns a separate SQLite backend class.
    """
    assert indexer_module.SQLiteIndexBackend is SQLiteIndexBackend


def test_registered_index_backends_keep_core_scope_narrow() -> None:
    """
    Keep the built-in backend factory list limited to core-owned implementations.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test asserts the default SQLite backend now loads through the
        first-party backend package rather than a core factory list.
    """
    backends = registry_module._registered_index_backends()

    assert backends == {}


def test_registered_language_analyzer_factories_keep_core_scope_narrow() -> None:
    """
    Keep the built-in analyzer factory list limited to core-owned analyzers.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test asserts optional first-party analyzers are not hard-wired into
        the core factory list.
    """
    factories = registry_module._registered_language_analyzer_factories()

    assert [factory().name for factory in factories] == []


def test_active_language_analyzers_skip_optional_c_when_dependencies_missing(
    monkeypatch: MonkeyPatch,
) -> None:
    """
    Skip the optional C analyzer when its plugin package is unavailable.

    Parameters
    ----------
    monkeypatch : pytest.MonkeyPatch
        Pytest fixture used to patch entry-point discovery.

    Returns
    -------
    None
        The test asserts the registry keeps Python active and omits C.
    """
    monkeypatch.setattr(
        registry_module,
        "_entry_points_for_group",
        lambda group: [],
    )

    try:
        active_language_analyzers()
    except ValueError as exc:
        message = str(exc)
    else:
        msg = "expected ValueError when no analyzers are registered"
        raise AssertionError(msg)

    assert message == "No language analyzers are registered for codira"


def test_json_analyzer_extracts_module_metadata_from_json_schema(
    tmp_path: Path,
) -> None:
    """
    Analyze one JSON Schema document into a module-only artifact.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository root for the fixture.

    Returns
    -------
    None
        The test asserts schema documents become stable module artifacts.
    """
    source = tmp_path / "src" / "codira" / "schema" / "context.schema.json"
    source.parent.mkdir(parents=True)
    source.write_text(
        json.dumps(
            {
                "$schema": "http://json-schema.org/draft-07/schema#",
                "title": "codira context output",
                "description": "Validate ctx JSON output.",
                "type": "object",
            }
        ),
        encoding="utf-8",
    )

    result = JsonAnalyzer().analyze_file(source, tmp_path)

    assert result.module.name == "src.codira.schema.context_schema"
    assert (
        result.module.stable_id == "json:module:src/codira/schema/context.schema.json"
    )
    assert (
        result.module.docstring
        == "JSON Schema: codira context output. Validate ctx JSON output."
    )
    assert result.classes == ()
    assert result.functions == ()
    assert result.declarations == ()
    assert result.imports == ()


def test_json_analyzer_rejects_unclassified_json_documents(tmp_path: Path) -> None:
    """
    Leave generic JSON blobs unclaimed by the JSON analyzer.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository root for the fixture.

    Returns
    -------
    None
        The test asserts unsupported JSON files remain outside analyzer scope.
    """
    source = tmp_path / "scripts" / "build.json"
    source.parent.mkdir(parents=True)
    source.write_text('{"task": "build"}\n', encoding="utf-8")

    assert JsonAnalyzer().supports_path(source) is False


def test_json_analyzer_extracts_schema_properties_and_definitions(
    tmp_path: Path,
) -> None:
    """
    Extract deterministic definition and property symbols from JSON Schema.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository root for the fixture.

    Returns
    -------
    None
        The test asserts the JSON analyzer emits schema-specific declarations.
    """
    source = tmp_path / "src" / "codira" / "schema" / "example.schema.json"
    source.parent.mkdir(parents=True)
    source.write_text(
        json.dumps(
            {
                "$schema": "http://json-schema.org/draft-07/schema#",
                "type": "object",
                "$defs": {
                    "Channel": {
                        "type": "string",
                        "description": "One retrieval channel.",
                    }
                },
                "properties": {
                    "status": {
                        "type": "string",
                        "description": "Rendered query status.",
                    },
                    "explain": {
                        "type": "object",
                        "properties": {
                            "planner": {"type": "object"},
                        },
                    },
                },
            }
        ),
        encoding="utf-8",
    )

    result = JsonAnalyzer().analyze_file(source, tmp_path)
    declaration_rows = [
        (decl.kind, decl.name, decl.signature, decl.docstring)
        for decl in result.declarations
    ]

    assert (
        "json_schema_definition",
        "Channel",
        "definition Channel type=string",
        "One retrieval channel.",
    ) in declaration_rows
    assert (
        "json_schema_property",
        "status",
        "property path=status type=string",
        "Rendered query status.",
    ) in declaration_rows
    assert (
        "json_schema_property",
        "explain.planner",
        "property path=explain.planner type=object",
        None,
    ) in declaration_rows


def test_json_analyzer_extracts_package_manifest_symbols(tmp_path: Path) -> None:
    """
    Extract stable manifest symbols from one ``package.json`` file.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository root for the fixture.

    Returns
    -------
    None
        The test asserts package, script, and dependency symbols are emitted.
    """
    source = tmp_path / "package.json"
    source.write_text(
        json.dumps(
            {
                "name": "codira-release",
                "version": "1.2.3",
                "scripts": {"release": "semantic-release"},
                "devDependencies": {"semantic-release": "^23.0.0"},
            }
        ),
        encoding="utf-8",
    )

    result = JsonAnalyzer().analyze_file(source, tmp_path)
    declaration_rows = [
        (decl.kind, decl.name, decl.signature) for decl in result.declarations
    ]

    assert (
        "json_manifest_name",
        "codira-release",
        "package name=codira-release version=1.2.3",
    ) in declaration_rows
    assert (
        "json_manifest_script",
        "release",
        "package script release: semantic-release",
    ) in declaration_rows
    assert (
        "json_manifest_dependency",
        "semantic-release",
        "package dependency section=devDependencies name=semantic-release version=^23.0.0",
    ) in declaration_rows


def test_json_analyzer_extracts_semantic_release_symbols(tmp_path: Path) -> None:
    """
    Extract stable branch and plugin symbols from semantic-release config.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository root for the fixture.

    Returns
    -------
    None
        The test asserts semantic-release symbols are emitted deterministically.
    """
    source = tmp_path / ".releaserc.json"
    source.write_text(
        json.dumps(
            {
                "branches": ["main", {"name": "next"}],
                "plugins": [
                    "@semantic-release/commit-analyzer",
                    ["@semantic-release/git", {"assets": ["CHANGELOG.md"]}],
                ],
            }
        ),
        encoding="utf-8",
    )

    result = JsonAnalyzer().analyze_file(source, tmp_path)
    declaration_rows = [
        (decl.kind, decl.name, decl.signature) for decl in result.declarations
    ]

    assert (
        "json_release_branch",
        "main",
        "semantic-release branch main",
    ) in declaration_rows
    assert (
        "json_release_branch",
        "next",
        "semantic-release branch next",
    ) in declaration_rows
    assert (
        "json_release_plugin",
        "@semantic-release/commit-analyzer",
        "semantic-release plugin @semantic-release/commit-analyzer",
    ) in declaration_rows
    assert (
        "json_release_plugin",
        "@semantic-release/git",
        "semantic-release plugin @semantic-release/git",
    ) in declaration_rows


def test_select_language_analyzer_reports_optional_extra_hint(
    monkeypatch: MonkeyPatch,
) -> None:
    """
    Report the package install hint when a C-family file has no available analyzer.

    Parameters
    ----------
    monkeypatch : pytest.MonkeyPatch
        Pytest fixture used to patch entry-point discovery.

    Returns
    -------
    None
        The test asserts the failure message includes the C package hint.

    Notes
    -----
    The test captures the ``ValueError`` internally, so it does not expose a
    ``Raises`` contract to callers.
    """
    monkeypatch.setattr(
        registry_module,
        "_entry_points_for_group",
        lambda group: [],
    )

    analyzers: list[LanguageAnalyzer] = []

    try:
        _select_language_analyzer(Path("native/sample.c"), analyzers)
    except ValueError as exc:
        message = str(exc)
    else:
        msg = "expected ValueError for missing optional C analyzer"
        raise AssertionError(msg)

    assert "No language analyzer registered for path: native/sample.c" in message
    assert "codira-analyzer-c" in message
    assert missing_language_analyzer_hint(Path("native/sample.c")) is not None


def test_select_language_analyzer_reports_python_package_hint(
    monkeypatch: MonkeyPatch,
) -> None:
    """
    Report the package install hint when a Python file has no available analyzer.

    Parameters
    ----------
    monkeypatch : pytest.MonkeyPatch
        Pytest fixture used to patch entry-point discovery.

    Returns
    -------
    None
        The test asserts the failure message includes the Python package hint.

    Notes
    -----
    The test captures the ``ValueError`` internally, so it does not expose a
    ``Raises`` contract to callers.
    """
    monkeypatch.setattr(
        registry_module,
        "_entry_points_for_group",
        lambda group: [],
    )

    analyzers: list[LanguageAnalyzer] = []

    try:
        _select_language_analyzer(Path("pkg/sample.py"), analyzers)
    except ValueError as exc:
        message = str(exc)
    else:
        msg = "expected ValueError for missing Python analyzer"
        raise AssertionError(msg)

    assert "No language analyzer registered for path: pkg/sample.py" in message
    assert "codira-analyzer-python" in message
    assert missing_language_analyzer_hint(Path("pkg/sample.py")) is not None


def test_select_language_analyzer_reports_json_package_hint(
    monkeypatch: MonkeyPatch,
) -> None:
    """
    Report the package install hint when a supported JSON file has no analyzer.

    Parameters
    ----------
    monkeypatch : pytest.MonkeyPatch
        Pytest fixture used to patch entry-point discovery.

    Returns
    -------
    None
        The test asserts the failure message includes the JSON package hint.

    Notes
    -----
    The test captures the ``ValueError`` internally, so it does not expose a
    ``Raises`` contract to callers.
    """
    monkeypatch.setattr(
        registry_module,
        "_entry_points_for_group",
        lambda group: [],
    )

    analyzers: list[LanguageAnalyzer] = []

    try:
        _select_language_analyzer(Path("package.json"), analyzers)
    except ValueError as exc:
        message = str(exc)
    else:
        msg = "expected ValueError for missing JSON analyzer"
        raise AssertionError(msg)

    assert "No language analyzer registered for path: package.json" in message
    assert "codira-analyzer-json" in message
    assert missing_language_analyzer_hint(Path("package.json")) is not None


def test_c_analyzer_normalizes_functions_and_includes(tmp_path: Path) -> None:
    """
    Validate the Phase 9 C analyzer proof against normalized artifacts.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary directory provided by pytest.

    Returns
    -------
    None
        The test asserts deterministic module, include, and function output.
    """
    source = tmp_path / "pkg" / "sample.c"
    source.parent.mkdir()
    source.write_text(
        '#include "pkg/sample.h"\n'
        "#include <stdio.h>\n"
        "\n"
        "static int helper(int value) {\n"
        "    return value;\n"
        "}\n"
        "\n"
        "int public_api(void) {\n"
        "    return helper(1);\n"
        "}\n",
        encoding="utf-8",
    )

    result = CAnalyzer().analyze_file(source, tmp_path)

    assert result.module.name == "pkg.sample"
    assert tuple(import_row.name for import_row in result.imports) == (
        "pkg/sample.h",
        "stdio.h",
    )
    assert tuple(import_row.kind for import_row in result.imports) == (
        "include_local",
        "include_system",
    )
    assert tuple(function.name for function in result.functions) == (
        "helper",
        "public_api",
    )
    assert result.functions[0].parameters == ("value",)
    assert result.functions[0].is_public == 0
    assert result.functions[1].parameters == ()
    assert result.functions[1].is_public == 1


def test_c_analyzer_extracts_top_level_declarations(tmp_path: Path) -> None:
    """
    Normalize top-level C type declarations into module-level symbols.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary directory provided by pytest.

    Returns
    -------
    None
        The test asserts deterministic constant, macro, struct, union, enum,
        and typedef extraction.
    """
    source = tmp_path / "native" / "types.h"
    source.parent.mkdir()
    source.write_text(
        "/* Stable internal constants. */\n"
        "static const int LIMIT = 3;\n"
        'static const char *NAME2 = "codira";\n'
        "const int LIMIT2 = 3;\n"
        "extern const int SIZE = 3;\n"
        "static const int A = 1, B = 2;\n"
        "static const int VALUE = 1 + 2;\n"
        "static const int VALUES[] = {1, 2};\n"
        "const int DECL_ONLY;\n"
        "extern const int DECL_EXT;\n"
        "const int fn(void);\n"
        "const int (*fp)(void);\n"
        "\n"
        "/* Stable exported macros. */\n"
        "#define PORT 8080\n"
        '#define NAME "codira"\n'
        "#define CALL(x) ((x) + 1)\n"
        "\n"
        "/* Node representation for graph edges. */\n"
        "typedef struct Node { int value; } Node;\n"
        "\n"
        "// Available palette values.\n"
        "enum Color { RED, BLUE };\n"
        "\n"
        "union Value { int i; float f; };\n"
        "\n"
        "struct Pair { int left; int right; };\n"
        "\n"
        "/* Stable integer alias. */\n"
        "typedef unsigned long size_t;\n",
        encoding="utf-8",
    )

    result = CAnalyzer().analyze_file(source, tmp_path)

    assert [
        (declaration.kind, declaration.name, declaration.lineno)
        for declaration in result.declarations
    ] == [
        ("constant", "LIMIT", 2),
        ("constant", "NAME2", 3),
        ("constant", "LIMIT2", 4),
        ("constant", "SIZE", 5),
        ("constant", "A", 6),
        ("constant", "B", 6),
        ("constant", "VALUE", 7),
        ("constant", "VALUES", 8),
        ("constant", "DECL_ONLY", 9),
        ("constant", "DECL_EXT", 10),
        ("macro", "PORT", 15),
        ("macro", "NAME", 16),
        ("macro", "CALL", 17),
        ("struct", "Node", 20),
        ("typedef", "Node", 20),
        ("enum", "Color", 23),
        ("union", "Value", 25),
        ("struct", "Pair", 27),
        ("typedef", "size_t", 30),
    ]
    assert result.declarations[0].signature == "static const int LIMIT = 3;"
    assert result.declarations[1].signature == 'static const char *NAME2 = "codira";'
    assert result.declarations[2].signature == "const int LIMIT2 = 3;"
    assert result.declarations[3].signature == "extern const int SIZE = 3;"
    assert result.declarations[4].signature == "static const int A = 1, B = 2;"
    assert result.declarations[5].signature == "static const int A = 1, B = 2;"
    assert result.declarations[6].signature == "static const int VALUE = 1 + 2;"
    assert result.declarations[0].docstring == "Stable internal constants."
    assert result.declarations[1].docstring is None
    assert result.declarations[2].docstring is None
    assert result.declarations[3].docstring is None
    assert result.declarations[4].docstring is None
    assert result.declarations[5].docstring is None
    assert result.declarations[6].docstring is None
    assert result.declarations[7].docstring is None
    assert result.declarations[8].docstring is None
    assert result.declarations[9].docstring is None
    assert result.declarations[10].docstring == "Stable exported macros."
    assert result.declarations[11].docstring is None
    assert result.declarations[12].docstring is None
    assert result.declarations[13].docstring == "Node representation for graph edges."
    assert result.declarations[14].docstring == "Node representation for graph edges."
    assert result.declarations[15].docstring == "Available palette values."
    assert result.declarations[16].docstring is None
    assert result.declarations[17].docstring is None
    assert result.declarations[18].docstring == "Stable integer alias."
    assert result.declarations[15].enum_members == (
        EnumMemberArtifact(
            stable_id="c:enum_member:native/types.h:Color:1",
            parent_stable_id="c:enum:native/types.h:Color",
            ordinal=1,
            name="RED",
            signature="RED",
            lineno=23,
        ),
        EnumMemberArtifact(
            stable_id="c:enum_member:native/types.h:Color:2",
            parent_stable_id="c:enum:native/types.h:Color",
            ordinal=2,
            name="BLUE",
            signature="BLUE",
            lineno=23,
        ),
    )
    assert result.declarations[16].signature == "union Value { int i; float f; }"
    assert result.declarations[16].stable_id == "c:union:native/types.h:Value"


def test_c_analyzer_preserves_suffix_in_declaration_stable_ids(
    tmp_path: Path,
) -> None:
    """
    Keep declaration stable IDs distinct across sibling source suffixes.
    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary directory provided by pytest.

    Returns
    -------
    None
        The test asserts `.c` and `.h` siblings do not collide.
    """
    include = tmp_path / "native" / "common.h"
    implementation = tmp_path / "native" / "common.c"
    include.parent.mkdir()
    include.write_text("struct name_info { int value; };\n", encoding="utf-8")
    implementation.write_text("struct name_info { int value; };\n", encoding="utf-8")

    include_result = CAnalyzer().analyze_file(include, tmp_path)
    implementation_result = CAnalyzer().analyze_file(implementation, tmp_path)

    assert include_result.declarations[0].stable_id == (
        "c:struct:native/common.h:name_info"
    )
    assert implementation_result.declarations[0].stable_id == (
        "c:struct:native/common.c:name_info"
    )


def test_c_analyzer_extracts_typedef_wrapped_union_declarations(tmp_path: Path) -> None:
    """
    Normalize typedef-wrapped C unions into explicit declaration artifacts.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary directory provided by pytest.

    Returns
    -------
    None
        The test asserts typedef-wrapped unions emit both union and typedef
        declarations deterministically.
    """
    source = tmp_path / "native" / "token.h"
    source.parent.mkdir()
    source.write_text(
        "typedef union Token { int kind; char c; } Token;\n",
        encoding="utf-8",
    )

    result = CAnalyzer().analyze_file(source, tmp_path)

    assert [
        (declaration.kind, declaration.name, declaration.lineno)
        for declaration in result.declarations
    ] == [
        ("union", "Token", 1),
        ("typedef", "Token", 1),
    ]
    assert result.declarations[0].signature == "union Token { int kind; char c; }"
    assert (
        result.declarations[1].signature
        == "typedef union Token { int kind; char c; } Token;"
    )
    assert result.declarations[0].stable_id == "c:union:native/token.h:Token"
    assert result.declarations[1].stable_id == "c:typedef:native/token.h:Token"


def test_c_analyzer_keeps_last_duplicate_named_declaration(tmp_path: Path) -> None:
    """
    Keep the last duplicate named C declaration when analysis sees both forms.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository root for the fixture.

    Returns
    -------
    None
        The test asserts only the final declaration variant is retained.
    """
    source = tmp_path / "native" / "types.h"
    source.parent.mkdir()
    source.write_text(
        "struct Foo;\nstruct Foo { int value; };\n",
        encoding="utf-8",
    )

    result = CAnalyzer().analyze_file(source, tmp_path)

    assert [
        (declaration.kind, declaration.name, declaration.lineno)
        for declaration in result.declarations
    ] == [("struct", "Foo", 2)]
    assert result.declarations[0].signature == "struct Foo { int value; }"


def test_c_analyzer_uses_real_name_for_annotated_functions(tmp_path: Path) -> None:
    """
    Recover real C function names from annotation-prefixed declarations.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository root for the fixture.

    Returns
    -------
    None
        The test asserts annotation wrappers do not replace function names.
    """
    source = tmp_path / "native" / "annotated.c"
    source.parent.mkdir()
    source.write_text(
        "typedef struct cairo_xml cairo_xml_t;\n"
        "static void CAIRO_PRINTF_FORMAT (2, 3)\n"
        "_cairo_xml_printf(cairo_xml_t *xml, const char *fmt, ...)\n"
        "{\n"
        "}\n"
        "\n"
        "static void CAIRO_PRINTF_FORMAT (2, 3)\n"
        "_cairo_xml_printf_start(cairo_xml_t *xml, const char *fmt, ...)\n"
        "{\n"
        "}\n",
        encoding="utf-8",
    )

    result = CAnalyzer().analyze_file(source, tmp_path)

    assert [(function.name, function.lineno) for function in result.functions] == [
        ("_cairo_xml_printf", 2),
        ("_cairo_xml_printf_start", 7),
    ]


def test_index_repo_handles_duplicate_c_declaration_redefinitions(
    tmp_path: Path,
) -> None:
    """
    Index duplicate C declarations without surfacing a failure.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository root for the fixture.

    Returns
    -------
    None
        The test asserts the repository indexes successfully.
    """
    source = tmp_path / "native" / "types.h"
    source.parent.mkdir()
    source.write_text(
        "struct Foo;\nstruct Foo { int value; };\n",
        encoding="utf-8",
    )

    report = index_repo(tmp_path)

    assert report.failed == 0
    assert report.indexed == 1


def test_index_repo_handles_annotated_c_functions(tmp_path: Path) -> None:
    """
    Index annotated C functions without tripping the fallback parser path.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository root for the fixture.

    Returns
    -------
    None
        The test asserts indexing completes without failures.
    """
    source = tmp_path / "native" / "annotated.c"
    source.parent.mkdir()
    source.write_text(
        "typedef struct cairo_xml cairo_xml_t;\n"
        "static void CAIRO_PRINTF_FORMAT (2, 3)\n"
        "_cairo_xml_printf(cairo_xml_t *xml, const char *fmt, ...)\n"
        "{\n"
        "}\n"
        "\n"
        "static void CAIRO_PRINTF_FORMAT (2, 3)\n"
        "_cairo_xml_printf_start(cairo_xml_t *xml, const char *fmt, ...)\n"
        "{\n"
        "}\n",
        encoding="utf-8",
    )

    report = index_repo(tmp_path)

    assert report.failed == 0
    assert report.indexed == 1


def test_c_analyzer_uses_real_name_for_macro_wrapped_functions(
    tmp_path: Path,
) -> None:
    """
    Recover real names from macro-wrapped C function declarations.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository root for the fixture.

    Returns
    -------
    None
        The test asserts wrapper macros do not leak into function names.
    """
    source = tmp_path / "native" / "compat.c"
    source.parent.mkdir()
    source.write_text(
        "typedef unsigned long mp_limb_t;\n"
        "typedef unsigned long mp_size_t;\n"
        "typedef unsigned long *mp_ptr;\n"
        "typedef const unsigned long *mp_srcptr;\n"
        "mp_limb_t\n"
        "__MPN (divexact_by3) (mp_ptr dst, mp_srcptr src, mp_size_t size)\n"
        "{\n"
        "    return 0;\n"
        "}\n"
        "\n"
        "mp_limb_t\n"
        "__MPN (divmod_1) (mp_ptr dst, mp_srcptr src, mp_size_t size)\n"
        "{\n"
        "    return 0;\n"
        "}\n",
        encoding="utf-8",
    )

    result = CAnalyzer().analyze_file(source, tmp_path)

    assert [(function.name, function.lineno) for function in result.functions] == [
        ("divexact_by3", 5),
        ("divmod_1", 11),
    ]


def test_index_repo_handles_macro_wrapped_c_functions(tmp_path: Path) -> None:
    """
    Index macro-wrapped C functions without reporting analyzer failures.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository root for the fixture.

    Returns
    -------
    None
        The test asserts one file is indexed successfully.
    """
    source = tmp_path / "native" / "compat.c"
    source.parent.mkdir()
    source.write_text(
        "typedef unsigned long mp_limb_t;\n"
        "typedef unsigned long mp_size_t;\n"
        "typedef unsigned long *mp_ptr;\n"
        "typedef const unsigned long *mp_srcptr;\n"
        "mp_limb_t\n"
        "__MPN (divexact_by3) (mp_ptr dst, mp_srcptr src, mp_size_t size)\n"
        "{\n"
        "    return 0;\n"
        "}\n"
        "\n"
        "mp_limb_t\n"
        "__MPN (divmod_1) (mp_ptr dst, mp_srcptr src, mp_size_t size)\n"
        "{\n"
        "    return 0;\n"
        "}\n",
        encoding="utf-8",
    )

    report = index_repo(tmp_path)

    assert report.failed == 0
    assert report.indexed == 1


def test_c_analyzer_handles_latin1_encoded_source(tmp_path: Path) -> None:
    """
    Decode latin-1 C source deterministically during analysis.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository root for the fixture.

    Returns
    -------
    None
        The test asserts module comment recovery and function extraction.
    """
    source = tmp_path / "native" / "legacy.c"
    source.parent.mkdir()
    source.write_bytes(
        (
            "/* Cr\xe8me legacy comment. */\nint helper(void)\n{\n    return 1;\n}\n"
        ).encode("latin-1")
    )

    result = CAnalyzer().analyze_file(source, tmp_path)

    assert result.module.docstring == "Cr\xe8me legacy comment."
    assert [(function.name, function.lineno) for function in result.functions] == [
        ("helper", 2)
    ]


def test_index_repo_handles_latin1_encoded_c_source(tmp_path: Path) -> None:
    """
    Index latin-1 encoded C source without surfacing a failure.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository root for the fixture.

    Returns
    -------
    None
        The test asserts the file indexes successfully.
    """
    source = tmp_path / "native" / "legacy.c"
    source.parent.mkdir()
    source.write_bytes(
        (
            "/* Cr\xe8me legacy comment. */\nint helper(void)\n{\n    return 1;\n}\n"
        ).encode("latin-1")
    )

    report = index_repo(tmp_path)

    assert report.failed == 0
    assert report.indexed == 1


def test_c_analyzer_uses_error_recovered_name_for_export_macros(
    tmp_path: Path,
) -> None:
    """
    Recover exported function names when macros disrupt the first parse pass.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository root for the fixture.

    Returns
    -------
    None
        The test asserts the recovered names match the declarations.
    """
    source = tmp_path / "native" / "exported.c"
    source.parent.mkdir()
    source.write_text(
        "typedef struct TestNode TestNode;\n"
        "void T_CTEST_EXPORT2\n"
        "showTests (const TestNode *root)\n"
        "{\n"
        "}\n"
        "\n"
        "void T_CTEST_EXPORT2\n"
        "runTests (const TestNode *root)\n"
        "{\n"
        "}\n",
        encoding="utf-8",
    )

    result = CAnalyzer().analyze_file(source, tmp_path)

    assert [(function.name, function.lineno) for function in result.functions] == [
        ("showTests", 2),
        ("runTests", 7),
    ]


def test_c_analyzer_ignores_throw_exception_specifier_as_function_name(
    tmp_path: Path,
) -> None:
    """
    Ignore ``throw()`` syntax when recovering the function name.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository root for the fixture.

    Returns
    -------
    None
        The test asserts the function name remains ``logger``.
    """
    source = tmp_path / "native" / "face.h"
    source.parent.mkdir()
    source.write_text(
        "class Face { public: json * logger() const throw(); };\n"
        "inline\n"
        "json * Face::logger() const throw()\n"
        "{\n"
        "  return 0;\n"
        "}\n",
        encoding="utf-8",
    )

    result = CAnalyzer().analyze_file(source, tmp_path)

    assert [(function.name, function.lineno) for function in result.functions] == [
        ("logger", 2)
    ]


def test_c_analyzer_uses_error_recovered_name_for_type_like_prefix(
    tmp_path: Path,
) -> None:
    """
    Recover names when type-like prefixes precede C declarations.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository root for the fixture.

    Returns
    -------
    None
        The test asserts both names are recovered correctly.
    """
    source = tmp_path / "native" / "float_funcs.c"
    source.parent.mkdir()
    source.write_text(
        "static force_inline float\n"
        "minf (float a, float b)\n"
        "{\n"
        "  return a;\n"
        "}\n"
        "\n"
        "static force_inline float\n"
        "maxf (float a, float b)\n"
        "{\n"
        "  return a;\n"
        "}\n",
        encoding="utf-8",
    )

    result = CAnalyzer().analyze_file(source, tmp_path)

    assert [(function.name, function.lineno) for function in result.functions] == [
        ("minf", 1),
        ("maxf", 7),
    ]


def test_c_function_stable_ids_are_disambiguated_when_names_repeat() -> None:
    """
    Disambiguate repeated C function stable IDs with deterministic suffixes.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test asserts repeated names do not collide.
    """
    functions = (
        FunctionArtifact(
            name="assign",
            stable_id="c:function:native.sample:assign",
            lineno=10,
            end_lineno=12,
            signature="assign(size_t n, const T& u)",
            docstring=None,
            has_docstring=0,
            is_method=0,
            is_public=1,
            parameters=(),
            returns_value=0,
            yields_value=0,
            raises=0,
            has_asserts=0,
            decorators=(),
            calls=(),
            callable_refs=(),
        ),
        FunctionArtifact(
            name="assign",
            stable_id="c:function:native.sample:assign",
            lineno=13,
            end_lineno=15,
            signature="assign(const_iterator first, const_iterator last)",
            docstring=None,
            has_docstring=0,
            is_method=0,
            is_public=1,
            parameters=(),
            returns_value=0,
            yields_value=0,
            raises=0,
            has_asserts=0,
            decorators=(),
            calls=(),
            callable_refs=(),
        ),
    )

    disambiguated = _disambiguate_function_stable_ids(functions)

    assert len({function.stable_id for function in disambiguated}) == 2
    assert all(
        function.stable_id.startswith("c:function:native.sample:assign")
        for function in disambiguated
    )


def test_discovery_file_globs_follow_analyzer_registration_order() -> None:
    """
    Derive deterministic scanner globs from analyzer metadata.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test asserts analyzer-registration order is preserved while
        duplicate globs are removed.
    """
    analyzers = [PythonAnalyzer(), CAnalyzer(), _FakeAnalyzer()]

    assert discovery_file_globs(analyzers) == ("*.py", "*.c", "*.h")


def test_iter_project_files_uses_analyzer_declared_globs(tmp_path: Path) -> None:
    """
    Discover files through analyzer-declared globs outside Git repositories.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary directory provided by pytest.

    Returns
    -------
    None
        The test asserts scanner discovery is not limited to the former
        hard-coded core glob tuple.
    """

    class _DemoAnalyzer:
        name = "demo"
        version = "1"
        discovery_globs: tuple[str, ...] = ("*.demo",)

        def supports_path(self, path: Path) -> bool:
            return path.suffix == ".demo"

        def analyze_file(self, path: Path, root: Path) -> AnalysisResult:
            del root
            return AnalysisResult(
                source_path=path,
                module=ModuleArtifact(
                    name=path.stem,
                    stable_id=f"demo:module:{path.stem}",
                    docstring=None,
                    has_docstring=0,
                ),
                classes=(),
                functions=(),
                declarations=(),
                imports=(),
            )

    demo_file = tmp_path / "src" / "sample.demo"
    ignored_file = tmp_path / "src" / "sample.py"
    demo_file.parent.mkdir()
    demo_file.write_text("demo\n", encoding="utf-8")
    ignored_file.write_text("print('ignored')\n", encoding="utf-8")

    discovered = list(iter_project_files(tmp_path, analyzers=[_DemoAnalyzer()]))

    assert discovered == [demo_file]


def test_iter_project_files_uses_analyzer_globs_with_git(tmp_path: Path) -> None:
    """
    Discover tracked files through analyzer-declared globs inside Git repos.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary directory provided by pytest.

    Returns
    -------
    None
        The test asserts Git-backed discovery follows analyzer metadata.
    """

    class _DemoAnalyzer:
        name = "demo"
        version = "1"
        discovery_globs: tuple[str, ...] = ("*.demo",)

        def supports_path(self, path: Path) -> bool:
            return path.suffix == ".demo"

        def analyze_file(self, path: Path, root: Path) -> AnalysisResult:
            del root
            return AnalysisResult(
                source_path=path,
                module=ModuleArtifact(
                    name=path.stem,
                    stable_id=f"demo:module:{path.stem}",
                    docstring=None,
                    has_docstring=0,
                ),
                classes=(),
                functions=(),
                declarations=(),
                imports=(),
            )

    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    demo_file = tmp_path / "src" / "sample.demo"
    other_file = tmp_path / "src" / "sample.py"
    demo_file.parent.mkdir()
    demo_file.write_text("demo\n", encoding="utf-8")
    other_file.write_text("print('ignored')\n", encoding="utf-8")
    subprocess.run(
        ["git", "add", "src/sample.demo", "src/sample.py"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )

    discovered = list(iter_project_files(tmp_path, analyzers=[_DemoAnalyzer()]))

    assert discovered == [demo_file]


def test_iter_project_files_filters_broad_globs_by_supports_path(
    tmp_path: Path,
) -> None:
    """
    Filter broad discovery globs through analyzer ownership checks.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary directory provided by pytest.

    Returns
    -------
    None
        The test asserts broad globs do not force unsupported files into the
        indexing set.
    """

    class _SelectiveJsonAnalyzer:
        name = "selective-json"
        version = "1"
        discovery_globs: tuple[str, ...] = ("*.json",)

        def supports_path(self, path: Path) -> bool:
            return path.name == "package.json"

        def analyze_file(self, path: Path, root: Path) -> AnalysisResult:
            del root
            return AnalysisResult(
                source_path=path,
                module=ModuleArtifact(
                    name=path.stem,
                    stable_id=f"json:module:{path.name}",
                    docstring=None,
                    has_docstring=0,
                ),
                classes=(),
                functions=(),
                declarations=(),
                imports=(),
            )

    package_file = tmp_path / "package.json"
    lockfile = tmp_path / "package-lock.json"
    package_file.write_text('{"name": "demo"}\n', encoding="utf-8")
    lockfile.write_text('{"name": "demo"}\n', encoding="utf-8")

    discovered = list(
        iter_project_files(tmp_path, analyzers=[_SelectiveJsonAnalyzer()])
    )

    assert discovered == [package_file]


def test_iter_canonical_project_files_uses_git_tracked_directories(
    tmp_path: Path,
) -> None:
    """
    Discover tracked files under canonical directories through Git.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary directory provided by pytest.

    Returns
    -------
    None
        The test asserts canonical-directory discovery does not depend on the
        active analyzer set.
    """
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    src_file = tmp_path / "src" / "main.rs"
    test_file = tmp_path / "tests" / "test_main.py"
    docs_file = tmp_path / "docs" / "notes.md"
    src_file.parent.mkdir()
    test_file.parent.mkdir()
    docs_file.parent.mkdir()
    src_file.write_text("fn main() {}\n", encoding="utf-8")
    test_file.write_text("def test_demo():\n    pass\n", encoding="utf-8")
    docs_file.write_text("# ignored\n", encoding="utf-8")
    subprocess.run(
        ["git", "add", "src/main.rs", "tests/test_main.py", "docs/notes.md"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )

    discovered = list(iter_canonical_project_files(tmp_path))

    assert discovered == [src_file, test_file]


def test_c_analyzer_extracts_calls_returns_and_module_comment(tmp_path: Path) -> None:
    """
    Preserve Phase 11 C semantic-parity artifacts within the current model.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary directory provided by pytest.

    Returns
    -------
    None
        The test asserts call extraction, return detection, and module comment
        capture for C sources.
    """
    source = tmp_path / "native" / "flow.c"
    source.parent.mkdir()
    source.write_text(
        "/* Vector reduction helpers. */\n"
        "\n"
        "static int helper(int value) {\n"
        "    return obj->normalize(value);\n"
        "}\n"
        "\n"
        "int public_api(int input) {\n"
        '    trace("value");\n'
        "    return helper(input);\n"
        "}\n",
        encoding="utf-8",
    )

    result = CAnalyzer().analyze_file(source, tmp_path)

    assert result.module.docstring == "Vector reduction helpers."
    assert result.module.has_docstring == 1
    assert tuple(function.name for function in result.functions) == (
        "helper",
        "public_api",
    )
    assert result.functions[0].returns_value == 1
    assert result.functions[0].calls == (
        CallSite(
            kind="attribute",
            target="normalize",
            lineno=4,
            col_offset=16,
            base="obj",
        ),
    )
    assert result.functions[1].returns_value == 1
    assert tuple(call.target for call in result.functions[1].calls) == (
        "trace",
        "helper",
    )


def test_c_analyzer_ignores_macro_blocks_misparsed_as_functions(
    tmp_path: Path,
) -> None:
    """
    Skip malformed macro blocks that tree-sitter exposes as functions.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary directory provided by pytest.

    Returns
    -------
    None
        The test asserts only real function definitions are normalized.
    """
    source = tmp_path / "native" / "macro_noise.c"
    source.parent.mkdir()
    source.write_text(
        "#define CTL_PROTO(x) x\n"
        "#define MUTEX_STATS_CTL_PROTO_GEN(n) \\\n"
        "CTL_PROTO(stats_##n##_num_ops) \\\n"
        "CTL_PROTO(stats_##n##_num_wait)\n"
        "\n"
        "typedef int ctl_named_node_t;\n"
        "#define OP(mtx) MUTEX_STATS_CTL_PROTO_GEN(mutexes_##mtx)\n"
        "static const ctl_named_node_t stats_node[] = {\n"
        "    OP(background_thread),\n"
        "};\n"
        "#undef OP\n"
        "\n"
        "int real(void) {\n"
        "    return 1;\n"
        "}\n",
        encoding="utf-8",
    )

    result = CAnalyzer().analyze_file(source, tmp_path)

    assert tuple(function.name for function in result.functions) == ("real",)
    assert result.functions[0].signature == "int real(void)"


def test_c_import_kinds_persist_through_sqlite_backend(tmp_path: Path) -> None:
    """
    Persist C include-kind metadata through the current SQLite backend.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary directory provided by pytest.

    Returns
    -------
    None
        The test asserts stored local and system include kinds.
    """
    source = tmp_path / "native" / "sample.c"
    source.parent.mkdir()
    source.write_text(
        '#include "native/sample.h"\n'
        "#include <stdio.h>\n"
        "\n"
        "int demo(void) {\n"
        "    return 1;\n"
        "}\n",
        encoding="utf-8",
    )

    backend = SQLiteIndexBackend()
    backend.initialize(tmp_path)
    analysis = CAnalyzer().analyze_file(source, tmp_path)
    snapshot = FileMetadataSnapshot(
        path=source,
        sha256="abc123",
        mtime=1.0,
        size=source.stat().st_size,
    )
    backend.persist_analysis(
        BackendPersistAnalysisRequest(
            root=tmp_path,
            file_metadata=snapshot,
            analysis=analysis,
        )
    )

    conn = sqlite3.connect(get_db_path(tmp_path))
    try:
        rows = conn.execute("""
            SELECT i.name, i.kind
            FROM imports i
            JOIN modules m
              ON i.module_id = m.id
            ORDER BY i.lineno, i.name
            """).fetchall()
    finally:
        conn.close()

    assert rows == [
        ("native/sample.h", "include_local"),
        ("stdio.h", "include_system"),
    ]


def test_c_declarations_persist_as_exact_symbols(tmp_path: Path) -> None:
    """
    Persist C declaration artifacts into the existing exact-symbol index.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary directory provided by pytest.

    Returns
    -------
    None
        The test asserts exact symbol lookup for persisted C declarations.
    """
    source = tmp_path / "native" / "types.h"
    source.parent.mkdir()
    source.write_text(
        "#define PORT 8080\n"
        '#define NAME "codira"\n'
        "static const int LIMIT = 3;\n"
        'static const char *NAME2 = "codira";\n'
        "const int LIMIT2 = 3;\n"
        "extern const int SIZE = 3;\n"
        "static const int A = 1, B = 2;\n"
        "static const int VALUE = 1 + 2;\n"
        "static const int VALUES[] = {1, 2};\n"
        "const int DECL_ONLY;\n"
        "extern const int DECL_EXT;\n"
        "const int fn(void);\n"
        "const int (*fp)(void);\n"
        "#define CALL(x) ((x) + 1)\n"
        "typedef struct Node { int value; } Node;\n"
        "enum Color { RED, BLUE };\n"
        "union Value { int i; float f; };\n"
        "struct Pair { int left; int right; };\n"
        "typedef unsigned long size_t;\n",
        encoding="utf-8",
    )

    backend = SQLiteIndexBackend()
    backend.initialize(tmp_path)
    analysis = CAnalyzer().analyze_file(source, tmp_path)
    snapshot = FileMetadataSnapshot(
        path=source,
        sha256="abc123",
        mtime=1.0,
        size=source.stat().st_size,
    )
    backend.persist_analysis(
        BackendPersistAnalysisRequest(
            root=tmp_path,
            file_metadata=snapshot,
            analysis=analysis,
        )
    )

    assert backend.find_symbol(tmp_path, "LIMIT") == [
        ("constant", "native.types", "LIMIT", str(source), 3),
    ]
    assert backend.find_symbol(tmp_path, "NAME2") == [
        ("constant", "native.types", "NAME2", str(source), 4),
    ]
    assert backend.find_symbol(tmp_path, "LIMIT2") == [
        ("constant", "native.types", "LIMIT2", str(source), 5),
    ]
    assert backend.find_symbol(tmp_path, "SIZE") == [
        ("constant", "native.types", "SIZE", str(source), 6),
    ]
    assert backend.find_symbol(tmp_path, "A") == [
        ("constant", "native.types", "A", str(source), 7),
    ]
    assert backend.find_symbol(tmp_path, "B") == [
        ("constant", "native.types", "B", str(source), 7),
    ]
    assert backend.find_symbol(tmp_path, "VALUE") == [
        ("constant", "native.types", "VALUE", str(source), 8),
    ]
    assert backend.find_symbol(tmp_path, "VALUES") == [
        ("constant", "native.types", "VALUES", str(source), 9),
    ]
    assert backend.find_symbol(tmp_path, "DECL_ONLY") == [
        ("constant", "native.types", "DECL_ONLY", str(source), 10),
    ]
    assert backend.find_symbol(tmp_path, "DECL_EXT") == [
        ("constant", "native.types", "DECL_EXT", str(source), 11),
    ]
    assert backend.find_symbol(tmp_path, "Node") == [
        ("struct", "native.types", "Node", str(source), 15),
        ("typedef", "native.types", "Node", str(source), 15),
    ]
    assert backend.find_symbol(tmp_path, "PORT") == [
        ("macro", "native.types", "PORT", str(source), 1),
    ]
    assert backend.find_symbol(tmp_path, "NAME") == [
        ("macro", "native.types", "NAME", str(source), 2),
    ]
    assert backend.find_symbol(tmp_path, "CALL") == [
        ("macro", "native.types", "CALL", str(source), 14),
    ]
    assert backend.find_symbol(tmp_path, "fn") == []
    assert backend.find_symbol(tmp_path, "fp") == []
    assert backend.find_symbol(tmp_path, "Color") == [
        ("enum", "native.types", "Color", str(source), 16),
    ]
    assert backend.find_symbol(tmp_path, "Value") == [
        ("union", "native.types", "Value", str(source), 17),
    ]
    assert backend.find_symbol(tmp_path, "size_t") == [
        ("typedef", "native.types", "size_t", str(source), 19),
    ]

    enum_symbol = backend.find_symbol(tmp_path, "Color")[0]
    assert backend.find_symbol_enum_members(tmp_path, enum_symbol) == [
        (
            "c:enum_member:native/types.h:Color:1",
            "c:enum:native/types.h:Color",
            1,
            "RED",
            "RED",
            16,
        ),
        (
            "c:enum_member:native/types.h:Color:2",
            "c:enum:native/types.h:Color",
            2,
            "BLUE",
            "BLUE",
            16,
        ),
    ]


def test_python_type_aliases_persist_as_exact_symbols(tmp_path: Path) -> None:
    """
    Persist explicit Python type aliases into the exact-symbol index.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary directory provided by pytest.

    Returns
    -------
    None
        The test asserts explicit Python type aliases become queryable
        declaration symbols.
    """
    source = tmp_path / "pkg" / "sample.py"
    source.parent.mkdir()
    source.write_text(
        "from typing import TypeAlias\n"
        "\n"
        "type UserId = int\n"
        "Slug: TypeAlias = str\n",
        encoding="utf-8",
    )

    backend = SQLiteIndexBackend()
    backend.initialize(tmp_path)
    analysis = PythonAnalyzer().analyze_file(source, tmp_path)
    snapshot = FileMetadataSnapshot(
        path=source,
        sha256="abc123",
        mtime=1.0,
        size=source.stat().st_size,
        analyzer_name="python",
        analyzer_version=PythonAnalyzer().version,
    )
    backend.persist_analysis(
        BackendPersistAnalysisRequest(
            root=tmp_path,
            file_metadata=snapshot,
            analysis=analysis,
        )
    )

    assert backend.find_symbol(tmp_path, "UserId") == [
        ("type_alias", "pkg.sample", "UserId", str(source), 3),
    ]
    assert backend.find_symbol(tmp_path, "Slug") == [
        ("type_alias", "pkg.sample", "Slug", str(source), 4),
    ]


def test_python_constants_persist_as_exact_symbols(tmp_path: Path) -> None:
    """
    Persist bounded Python constants into the exact-symbol index.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary directory provided by pytest.

    Returns
    -------
    None
        The test asserts module-level constant declarations become queryable
        exact symbols while non-constant assignments remain excluded.
    """
    source = tmp_path / "pkg" / "sample.py"
    source.parent.mkdir()
    source.write_text(
        "VALUE = 1\n"
        "TIMEOUT = (1, 2, 3)\n"
        "PORT: int = 8080\n"
        'NAME: str = "codira"\n'
        "ALIAS = VALUE + 1\n"
        "_PRIVATE = 2\n",
        encoding="utf-8",
    )

    backend = SQLiteIndexBackend()
    backend.initialize(tmp_path)
    analysis = PythonAnalyzer().analyze_file(source, tmp_path)
    snapshot = FileMetadataSnapshot(
        path=source,
        sha256="constants123",
        mtime=1.0,
        size=source.stat().st_size,
        analyzer_name="python",
        analyzer_version=PythonAnalyzer().version,
    )
    backend.persist_analysis(
        BackendPersistAnalysisRequest(
            root=tmp_path,
            file_metadata=snapshot,
            analysis=analysis,
        )
    )

    assert backend.find_symbol(tmp_path, "VALUE") == [
        ("constant", "pkg.sample", "VALUE", str(source), 1),
    ]
    assert backend.find_symbol(tmp_path, "TIMEOUT") == [
        ("constant", "pkg.sample", "TIMEOUT", str(source), 2),
    ]
    assert backend.find_symbol(tmp_path, "PORT") == [
        ("constant", "pkg.sample", "PORT", str(source), 3),
    ]
    assert backend.find_symbol(tmp_path, "NAME") == [
        ("constant", "pkg.sample", "NAME", str(source), 4),
    ]
    assert backend.find_symbol(tmp_path, "ALIAS") == []
    assert backend.find_symbol(tmp_path, "_PRIVATE") == []


def test_c_declaration_comments_contribute_to_embedding_candidates(
    tmp_path: Path,
) -> None:
    """
    Include leading declaration comments in C semantic symbol retrieval.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary directory provided by pytest.

    Returns
    -------
    None
        The test asserts embedding retrieval can match declaration comments.
    """
    source = tmp_path / "native" / "types.h"
    source.parent.mkdir()
    source.write_text(
        "/* Palette lookup for UI themes. */\nenum Color { RED, BLUE };\n",
        encoding="utf-8",
    )

    backend = SQLiteIndexBackend()
    backend.initialize(tmp_path)
    analysis = CAnalyzer().analyze_file(source, tmp_path)
    snapshot = FileMetadataSnapshot(
        path=source,
        sha256="abc123",
        mtime=1.0,
        size=source.stat().st_size,
    )
    backend.persist_analysis(
        BackendPersistAnalysisRequest(
            root=tmp_path,
            file_metadata=snapshot,
            analysis=analysis,
        )
    )

    results = backend.embedding_candidates(
        BackendEmbeddingCandidatesRequest(
            root=tmp_path,
            query="palette lookup themes",
            limit=5,
            min_score=0.0,
        )
    )

    assert results
    assert ("enum", "native.types", "Color", str(source), 2) in {
        symbol for _score, symbol in results
    }


def test_active_index_backend_rejects_unknown_configured_backend(
    monkeypatch: MonkeyPatch,
) -> None:
    """
    Reject unsupported backend configuration deterministically.

    Parameters
    ----------
    monkeypatch : pytest.MonkeyPatch
        Pytest fixture used to set process-local environment variables.

    Returns
    -------
    None
        The test asserts an informative failure for unsupported backend names.

    Raises
    ------
    ValueError
        Raised when the configured backend name is not registered.
    """
    monkeypatch.setenv("CODIRA_INDEX_BACKEND", "unknown")

    try:
        active_index_backend()
    except ValueError as exc:
        message = str(exc)
    else:
        msg = "expected ValueError for unsupported backend"
        raise AssertionError(msg)

    assert "Unsupported codira backend 'unknown'" in message
    assert "sqlite" in message


def test_active_index_backend_mentions_first_party_sqlite_package_when_missing(
    monkeypatch: MonkeyPatch,
) -> None:
    """
    Mention the extracted SQLite backend package when no backend is available.

    Parameters
    ----------
    monkeypatch : pytest.MonkeyPatch
        Fixture used to remove backend entry-point discovery.

    Returns
    -------
    None
        The test asserts the default backend error includes the installation
        hint for the first-party SQLite package.
    """
    monkeypatch.setenv(registry_module.INDEX_BACKEND_ENV_VAR, "sqlite")
    monkeypatch.setattr(
        registry_module,
        "_entry_points_for_group",
        lambda group: [],
    )

    try:
        active_index_backend()
    except ValueError as exc:
        message = str(exc)
    else:
        msg = "expected ValueError when no backend plugins are registered"
        raise AssertionError(msg)

    assert "codira-backend-sqlite" in message
    assert "codira-bundle-official" in message


def test_instantiating_language_analyzers_requires_a_non_empty_registry() -> None:
    """
    Reject empty analyzer registries with an explicit deterministic error.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test asserts the registry failure path used by Phase 8.

    Raises
    ------
    ValueError
        Raised when analyzer instantiation is attempted with an empty
        registry.
    """
    try:
        _instantiate_language_analyzers(())
    except ValueError as exc:
        assert str(exc) == "No language analyzers are registered for codira"
    else:
        msg = "expected ValueError for empty analyzer registry"
        raise AssertionError(msg)


def test_sqlite_index_backend_persists_and_deletes_normalized_analysis(
    tmp_path: Path,
) -> None:
    """
    Exercise the concrete SQLite backend through the Phase 3 contract surface.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary directory provided by pytest.

    Returns
    -------
    None
        The test asserts normalized persistence, reusable embedding counting,
        and deletion through `SQLiteIndexBackend`.
    """
    module = tmp_path / "pkg" / "sample.py"
    module.parent.mkdir()
    module.write_text(
        'def demo(value):\n    """Return the supplied value."""\n    return value\n',
        encoding="utf-8",
    )

    backend = SQLiteIndexBackend()
    backend.initialize(tmp_path)

    parsed = parse_file(module, tmp_path)
    analysis = analysis_result_from_parsed(module, parsed)
    snapshot = FileMetadataSnapshot(
        path=module,
        sha256="abc123",
        mtime=1.0,
        size=module.stat().st_size,
    )

    assert isinstance(backend, IndexBackend)
    recomputed, reused = backend.persist_analysis(
        BackendPersistAnalysisRequest(
            root=tmp_path,
            file_metadata=snapshot,
            analysis=analysis,
        )
    )
    backend.rebuild_derived_indexes(tmp_path)

    conn = sqlite3.connect(get_db_path(tmp_path))
    try:
        file_hashes = backend.load_existing_file_hashes(tmp_path, conn=conn)
        symbol_rows = conn.execute(
            "SELECT name, type FROM symbol_index ORDER BY name, type"
        ).fetchall()
    finally:
        conn.close()

    assert recomputed == 2
    assert reused == 0
    assert file_hashes == {str(module): "abc123"}
    assert symbol_rows == [
        ("demo", "function"),
        ("pkg.sample", "module"),
    ]
    assert backend.find_symbol(tmp_path, "demo") == [
        (
            "function",
            "pkg.sample",
            "demo",
            str(module),
            1,
        )
    ]
    assert backend.embedding_inventory(tmp_path) == [
        (EMBEDDING_BACKEND, EMBEDDING_VERSION, EMBEDDING_DIM, 2)
    ]
    assert backend.embedding_candidates(
        BackendEmbeddingCandidatesRequest(
            root=tmp_path,
            query="return supplied value",
            limit=5,
            min_score=0.0,
        )
    )
    assert backend.count_reusable_embeddings(tmp_path, paths=[str(module)]) == 2

    backend.delete_paths(tmp_path, paths=[str(module)])
    assert backend.load_existing_file_hashes(tmp_path) == {}


def test_select_language_analyzer_uses_first_supporting_analyzer(
    tmp_path: Path,
) -> None:
    """
    Preserve deterministic analyzer routing order in the Phase 5 orchestrator.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary directory provided by pytest.

    Returns
    -------
    None
        The test asserts first-match routing for a supported path.

    Raises
    ------
    AssertionError
        Raised if the rejecting analyzer is called despite not supporting the
        path.
    """

    class _RejectingAnalyzer:
        name = "reject"
        version = "1"
        discovery_globs: tuple[str, ...] = ("*.py",)

        def supports_path(self, path: Path) -> bool:
            return False

        def analyze_file(self, path: Path, root: Path) -> AnalysisResult:
            msg = "should not be called"
            raise AssertionError(msg)

    analyzer = _select_language_analyzer(
        tmp_path / "sample.py",
        [_RejectingAnalyzer(), _FakeAnalyzer()],
    )

    assert analyzer is not None
    assert analyzer.name == "fake-python"


def test_collect_indexed_file_analyses_routes_paths_to_analyzers(
    tmp_path: Path,
) -> None:
    """
    Collect normalized analyses through the Phase 5 analyzer-routing helper.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary directory provided by pytest.

    Returns
    -------
    None
        The test asserts snapshot conversion and analyzer-produced artifacts.
    """
    module = tmp_path / "pkg" / "sample.py"
    module.parent.mkdir()
    module.write_text(
        'def demo():\n    """Return a constant."""\n    return 1\n',
        encoding="utf-8",
    )

    rows, failures, collected_warnings = _collect_indexed_file_analyses(
        tmp_path,
        [str(module)],
        {
            str(module): {
                "path": str(module),
                "hash": "abc123",
                "mtime": 1.0,
                "size": module.stat().st_size,
            }
        },
        [_FakeAnalyzer()],
    )

    assert failures == []
    assert collected_warnings == []
    assert len(rows) == 1
    path, snapshot, analysis = rows[0]
    assert path == module
    assert snapshot == FileMetadataSnapshot(
        path=module,
        sha256="abc123",
        mtime=1.0,
        size=module.stat().st_size,
        analyzer_name="fake-python",
        analyzer_version="1",
    )
    assert analysis.module.name == "pkg.sample"


def test_sqlite_backend_persists_file_analyzer_ownership(tmp_path: Path) -> None:
    """
    Persist analyzer ownership metadata on file rows.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary directory provided by pytest.

    Returns
    -------
    None
        The test asserts persisted file rows record analyzer name and version.
    """
    backend = SQLiteIndexBackend()
    backend.initialize(tmp_path)
    module = tmp_path / "pkg" / "sample.py"
    module.parent.mkdir()
    module.write_text(
        'def demo():\n    """Return a constant."""\n    return 1\n',
        encoding="utf-8",
    )
    snapshot = FileMetadataSnapshot(
        path=module,
        sha256="hash-v1",
        mtime=1.0,
        size=module.stat().st_size,
        analyzer_name="python",
        analyzer_version=PythonAnalyzer().version,
    )
    analysis = PythonAnalyzer().analyze_file(module, tmp_path)

    backend.persist_analysis(
        BackendPersistAnalysisRequest(
            root=tmp_path,
            file_metadata=snapshot,
            analysis=analysis,
        )
    )

    conn = sqlite3.connect(get_db_path(tmp_path))
    try:
        row = conn.execute(
            """
            SELECT analyzer_name, analyzer_version
            FROM files
            WHERE path = ?
            """,
            (str(module),),
        ).fetchone()
    finally:
        conn.close()

    assert row == ("python", PythonAnalyzer().version)


def test_sqlite_backend_persists_runtime_inventory(tmp_path: Path) -> None:
    """
    Persist runtime backend and analyzer inventory for one index run.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary directory provided by pytest.

    Returns
    -------
    None
        The test asserts backend runtime metadata and analyzer inventory are
        stored in the SQLite database.
    """
    module = tmp_path / "pkg" / "sample.py"
    module.parent.mkdir()
    module.write_text(
        'def demo():\n    """Return a constant."""\n    return 1\n',
        encoding="utf-8",
    )

    index_repo(tmp_path)

    backend = SQLiteIndexBackend()
    assert backend.load_runtime_inventory(tmp_path) == ("sqlite", "13", 1)
    assert backend.load_analyzer_inventory(tmp_path) == [
        (
            analyzer.name,
            analyzer.version,
            json.dumps(tuple(analyzer.discovery_globs)),
        )
        for analyzer in sorted(active_language_analyzers(), key=lambda item: item.name)
    ]


def test_bash_analyzer_extracts_simple_calls(tmp_path: Path) -> None:
    """
    Extract plain shell command calls from one Bash function body.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository root for the fixture.

    Returns
    -------
    None
        The test asserts simple sequential calls are recorded in order.
    """
    source = tmp_path / "scripts" / "build.sh"
    source.parent.mkdir()
    source.write_text(
        "build() {\n    echo hello\n    make all\n}\n",
        encoding="utf-8",
    )

    result = BashAnalyzer().analyze_file(source, tmp_path)

    assert tuple(call.target for call in result.functions[0].calls) == (
        "echo",
        "make",
    )


def test_bash_analyzer_extracts_pipeline_calls(tmp_path: Path) -> None:
    """
    Extract every command participating in one shell pipeline.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository root for the fixture.

    Returns
    -------
    None
        The test asserts pipeline commands are recorded left to right.
    """
    source = tmp_path / "scripts" / "build.sh"
    source.parent.mkdir()
    source.write_text(
        "build() {\n    cat input.txt | grep foo | sort\n}\n",
        encoding="utf-8",
    )

    result = BashAnalyzer().analyze_file(source, tmp_path)

    assert tuple(call.target for call in result.functions[0].calls) == (
        "cat",
        "grep",
        "sort",
    )


def test_bash_analyzer_extracts_subshell_and_substitution_calls(tmp_path: Path) -> None:
    """
    Extract calls nested in subshells and command substitutions.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository root for the fixture.

    Returns
    -------
    None
        The test asserts nested calls are still collected in order.
    """
    source = tmp_path / "scripts" / "build.sh"
    source.parent.mkdir()
    source.write_text(
        'build() {\n    (echo hello; make all)\n    value="$(git rev-parse HEAD)"\n}\n',
        encoding="utf-8",
    )

    result = BashAnalyzer().analyze_file(source, tmp_path)

    assert tuple(call.target for call in result.functions[0].calls) == (
        "echo",
        "make",
        "git",
    )


def test_bash_analyzer_ignores_plain_assignments(tmp_path: Path) -> None:
    """
    Ignore bare variable assignments that do not execute shell commands.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository root for the fixture.

    Returns
    -------
    None
        The test asserts no calls are collected for plain assignments.
    """
    source = tmp_path / "scripts" / "build.sh"
    source.parent.mkdir()
    source.write_text(
        "build() {\n    value=hello\n    PATH=/tmp/bin\n}\n",
        encoding="utf-8",
    )

    result = BashAnalyzer().analyze_file(source, tmp_path)

    assert result.functions[0].calls == ()


def test_bash_analyzer_extracts_env_prefixed_command(tmp_path: Path) -> None:
    """
    Keep the executed command when an environment assignment prefixes it.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository root for the fixture.

    Returns
    -------
    None
        The test asserts the prefixed command is still recorded.
    """
    source = tmp_path / "scripts" / "build.sh"
    source.parent.mkdir()
    source.write_text(
        "build() {\n    PATH=/tmp/bin make all\n}\n",
        encoding="utf-8",
    )

    result = BashAnalyzer().analyze_file(source, tmp_path)

    assert tuple(call.target for call in result.functions[0].calls) == ("make",)


def test_bash_analyzer_keeps_last_duplicate_function_definition(
    tmp_path: Path,
) -> None:
    """
    Keep only the last duplicate Bash function definition during analysis.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository root for the fixture.

    Returns
    -------
    None
        The test asserts the final definition and its calls survive.
    """
    source = tmp_path / "scripts" / "build.sh"
    source.parent.mkdir()
    source.write_text(
        "build() {\n    echo one\n}\n\nbuild() {\n    make all\n}\n",
        encoding="utf-8",
    )

    result = BashAnalyzer().analyze_file(source, tmp_path)

    assert [(fn.name, fn.lineno) for fn in result.functions] == [("build", 5)]
    assert tuple(call.target for call in result.functions[0].calls) == ("make",)


def test_index_repo_handles_duplicate_bash_function_redefinitions(
    tmp_path: Path,
) -> None:
    """
    Index duplicate Bash function redefinitions without surfacing a failure.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository root for the fixture.

    Returns
    -------
    None
        The test asserts the file indexes successfully.
    """
    source = tmp_path / "scripts" / "build.sh"
    source.parent.mkdir()
    source.write_text(
        "build() {\n    echo one\n}\n\nbuild() {\n    make all\n}\n",
        encoding="utf-8",
    )

    report = index_repo(tmp_path)

    assert report.failed == 0
    assert report.indexed == 1
