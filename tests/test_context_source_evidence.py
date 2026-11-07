"""Verify independent lexical source evidence in rendered context output.

Parameters
----------
None

Returns
-------
None
"""

from __future__ import annotations

import json
from importlib import import_module
from typing import TYPE_CHECKING

import pytest
from codira_backend_sqlite import SQLiteIndexBackend

from codira.query.context_models import ContextRenderRequest
from codira.query.context_render import _render_context
from codira.query.source_evidence import query_source_evidence

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.parametrize("backend_name", ["sqlite", "duckdb"])
@pytest.mark.parametrize("with_symbol", [False, True])
def test_source_evidence_is_separate_and_available_without_symbol_matches(
    tmp_path: Path,
    backend_name: str,
    with_symbol: bool,
) -> None:
    """Render indexed lexical evidence independently of ranked symbols.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary indexed repository root.
    backend_name : str
        First-party structural backend selected for the test.
    with_symbol : bool
        Whether the context page includes a ranked symbol.

    Returns
    -------
    None
        The public rendering keeps lexical evidence separate from symbols.
    """
    backend = (
        SQLiteIndexBackend()
        if backend_name == "sqlite"
        else import_module("codira_backend_duckdb").DuckDBIndexBackend()
    )
    backend.initialize(tmp_path)
    source_path = tmp_path / "src" / "math.c"
    source_path.parent.mkdir()
    source_path.write_text("// ceil is documented here\nint ceil(int value);\n")

    conn = backend.open_connection(tmp_path)
    try:
        conn.execute(
            "INSERT INTO files(path, hash, mtime, size, analyzer_name, analyzer_version) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (str(source_path), "snapshot", 0.0, 0, "c", "1"),
        )
        file_id = conn.execute(
            "SELECT id FROM files WHERE path = ?", (str(source_path),)
        ).fetchone()[0]
        conn.execute(
            "INSERT INTO written_source_lines(file_id, lineno, line_text) "
            "VALUES (?, ?, ?)",
            (file_id, 1, "// ceil is documented here"),
        )
        conn.execute(
            "INSERT INTO written_source_tokens(identifier, file_id, lineno) "
            "VALUES (?, ?, ?)",
            ("ceil", file_id, 1),
        )
        evidence, truncated = query_source_evidence(
            conn, tmp_path, "Where is ceil?", None
        )
    finally:
        conn.close()

    symbols = [("function", "math", "ceil", str(source_path), 2)] if with_symbol else []
    output = json.loads(
        _render_context(
            ContextRenderRequest(
                root=tmp_path,
                query="Where is ceil?",
                top_matches=symbols,
                doc_issues=[],
                expanded=[],
                unique_refs=[],
                source_evidence=evidence,
                source_evidence_truncated=truncated,
                as_json=True,
                result_total=len(symbols),
            )
        )
    )

    assert output["status"] == "ok"
    assert output["source_evidence"]["items"] == [
        {
            "file": "src/math.c",
            "lineno": 1,
            "identifiers": ["ceil"],
            "text": "// ceil is documented here",
            "file_sha256": "snapshot",
            "coverage_state": None,
            "line_truncated": False,
        }
    ]
    assert output["source_evidence"]["truncated"] is False
    assert (
        "comments, strings, or conditional code"
        in output["source_evidence"]["interpretation"]
    )


def test_source_evidence_query_keeps_exact_stopword_and_bounds_long_lines(
    tmp_path: Path,
) -> None:
    """Retain exact stopword matches and signal clipped indexed lines.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary indexed repository root.

    Returns
    -------
    None
        The query result identifies both line and result truncation.
    """
    backend = SQLiteIndexBackend()
    backend.initialize(tmp_path)
    conn = backend.open_connection(tmp_path)
    try:
        source_path = tmp_path / "module.py"
        conn.execute(
            "INSERT INTO files(path, hash, mtime, size, analyzer_name, analyzer_version) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (str(source_path), "snapshot", 0.0, 0, "python", "1"),
        )
        file_id = conn.execute(
            "SELECT id FROM files WHERE path = ?", (str(source_path),)
        ).fetchone()[0]
        line_text = ("x" * 1100) + " get"
        conn.execute(
            "INSERT INTO written_source_lines(file_id, lineno, line_text) "
            "VALUES (?, ?, ?)",
            (file_id, 1, line_text),
        )
        conn.execute(
            "INSERT INTO written_source_tokens(identifier, file_id, lineno) "
            "VALUES (?, ?, ?)",
            ("get", file_id, 1),
        )
        evidence, truncated = query_source_evidence(conn, tmp_path, "get", None)
    finally:
        conn.close()

    assert evidence[0].identifiers == ("get",)
    assert len(evidence[0].line_text) == 1000
    assert "get" in evidence[0].line_text
    assert evidence[0].line_truncated is True
    assert truncated is True
