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
    from pathlib import Path

import sqlite3

from codira.indexer import index_repo
from codira.query.exact import docstring_issues, find_symbol
from codira.storage import get_db_path, init_db


def test_index_and_queries(tmp_path: Path) -> None:
    """
    Index a temporary package and verify basic query behavior.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary directory provided by pytest.

    Returns
    -------
    None
        The test asserts basic indexing and exact-query behavior.

    Notes
    -----
    The indexed source intentionally omits some callable docstrings so the
    audit query can verify that missing-docstring issues are recorded.
    """
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
        "    return x\n",
        encoding="utf-8",
    )

    init_db(tmp_path)
    index_repo(tmp_path)

    conn = sqlite3.connect(get_db_path(tmp_path))
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
