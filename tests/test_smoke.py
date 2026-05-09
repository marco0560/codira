"""Smoke tests for codira CLI and retrieval workflows.

Responsibilities
----------------
- Run the `codira` CLI to ensure indexing, context, and docstring diagnostics succeed end-to-end.
- Validate deterministic outputs from exact, semantic, and embedding channels using a minimal fixture repository.
- Confirm regression coverage for default CLI behaviors such as `ctx` and docstring reporting.

Design principles
-----------------
Smoke coverage targets broad entrypoints with minimal fixtures so failures report high-level regressions with little setup.

Architectural role
------------------
This module belongs to the **test harness layer** and protects the high-level CLI and retrieval experience.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Callable
    from pathlib import Path

from typing import cast

import pytest

from codira.indexer import index_repo
from codira.query.context import ContextRequest, context_for
from codira.query.exact import docstring_issues, find_symbol
from codira.registry import active_index_backend
from codira.storage import init_db


@pytest.mark.parametrize("backend_name", ["sqlite", "duckdb"])
def test_index_and_queries(
    tmp_path: Path,
    set_index_backend: Callable[[str | None], None],
    backend_name: str,
) -> None:
    """
    Index a temporary package and verify basic query behavior across backends.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary directory provided by pytest.
    set_index_backend : collections.abc.Callable[[str | None], None]
        Helper used to select the backend under test.
    backend_name : str
        Backend name exercised by the current parametrized test case.

    Returns
    -------
    None
        The test asserts basic indexing and exact-query behavior for the
        selected backend.

    Notes
    -----
    The indexed source intentionally omits some callable docstrings so the
    audit query can verify that missing-docstring issues are recorded, and it
    includes one unresolved call so derived graph rebuilds exercise nullable
    edge targets.
    """
    set_index_backend(backend_name)
    pkg = tmp_path / "pkg"
    pkg.mkdir()

    source = pkg / "sample.py"
    source.write_text(
        '"""Module doc."""\n'
        "\n"
        "class Demo:\n"
        "    def method(self):\n"
        "        return 1\n"
        "\n"
        "def public_func(x):\n"
        '    """Do work."""\n'
        "    missing_runtime_hook(x)\n"
        "    return x\n",
        encoding="utf-8",
    )

    init_db(tmp_path)
    index_repo(tmp_path)

    backend = active_index_backend()
    conn = cast("sqlite3.Connection", backend.open_connection(tmp_path))
    try:
        function_count = conn.execute("SELECT COUNT(*) FROM functions").fetchone()[0]
        class_count = conn.execute("SELECT COUNT(*) FROM classes").fetchone()[0]
    finally:
        conn.close()

    assert function_count == 2
    assert class_count == 1

    demo_rows = find_symbol(tmp_path, "Demo")
    assert len(demo_rows) == 1

    issues = docstring_issues(tmp_path)
    messages = [issue[1] for issue in issues]
    assert any(
        message == "Method Demo.method: Missing docstring" for message in messages
    )


@pytest.mark.parametrize("backend_name", ["sqlite", "duckdb"])
def test_context_query_works_across_backends(
    tmp_path: Path,
    set_index_backend: Callable[[str | None], None],
    backend_name: str,
) -> None:
    """
    Run one context query through each supported backend.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary directory provided by pytest.
    set_index_backend : collections.abc.Callable[[str | None], None]
        Helper used to select the backend under test.
    backend_name : str
        Backend name exercised by the current parametrized test case.

    Returns
    -------
    None
        The test asserts context rendering succeeds for both SQLite and
        DuckDB-backed indexes.
    """
    set_index_backend(backend_name)
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "sample.py").write_text(
        '"""Module doc."""\n\ndef public_func(x):\n    """Do work."""\n    return x\n',
        encoding="utf-8",
    )

    init_db(tmp_path)
    index_repo(tmp_path)

    output = context_for(
        ContextRequest(root=tmp_path, query="public_func", as_json=True)
    )

    assert "public_func" in output
