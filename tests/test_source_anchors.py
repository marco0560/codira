"""Backend-portable source-anchor range and query-cost regressions.

Parameters
----------
None

Returns
-------
None
    Matching source lines preserve enclosing-symbol evidence at bounded cost.
"""

from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING, cast

import pytest

from codira.indexer import index_repo
from codira.query.task_anchors import source_candidates
from codira.registry import active_index_backend

if TYPE_CHECKING:
    from pathlib import Path

    from codira.contracts import BackendQueryConnection
    from codira.types import SymbolRow


def _previous_candidates(conn: BackendQueryConnection, term: str) -> set[SymbolRow]:
    """Evaluate the pre-fix enclosing-range oracle on a small fixture.

    Parameters
    ----------
    conn : BackendQueryConnection
        Connection to the fixture's logical structural schema.
    term : str
        Source substring to search.

    Returns
    -------
    set of SymbolRow
        Previously emitted rows before independent anchor counting.
    """
    rows = conn.execute(
        """SELECT s.type, s.module_name, s.name, f.path, s.lineno
        FROM symbol_index s JOIN files f ON f.id=s.file_id
        JOIN reference_scan_lines r ON r.file_id=f.id
        WHERE LOWER(r.line_text) LIKE LOWER(?) AND r.lineno >= s.lineno
        AND r.lineno <= COALESCE(
          (SELECT MAX(c.end_lineno) FROM classes c JOIN modules m ON c.module_id=m.id
           WHERE m.file_id=f.id AND c.lineno=s.lineno AND s.type='class'),
          (SELECT MAX(fn.end_lineno) FROM functions fn JOIN modules m ON fn.module_id=m.id
           WHERE m.file_id=f.id AND fn.lineno=s.lineno), s.lineno)
        ORDER BY f.path, s.lineno LIMIT 128""",
        (f"%{term}%",),
    ).fetchall()
    return {
        (str(k), str(m), str(n), str(p), int(str(line))) for k, m, n, p, line in rows
    }


@pytest.mark.parametrize("backend_name", ["sqlite", "duckdb"])
def test_source_anchor_range_equivalence(tmp_path: Path, backend_name: str) -> None:
    """Preserve nested ranges, case-insensitive anchors and independent counts.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Disposable fixture source and index.
    backend_name : str
        Structural backend receiving the same logical SQL.

    Returns
    -------
    None
        Old and new results agree for classes, functions and repeated hits.
    """
    (tmp_path / ".codira").mkdir()
    (tmp_path / ".codira/config.toml").write_text(
        f'[embeddings]\nenabled = false\n[backend]\nname = "{backend_name}"\n'
    )
    (tmp_path / "nested.py").write_text(
        'class Box:\n    def run(self):\n        marker = "Marker Other"\n'
        '        return marker + "MARKER"\n\ndef outside():\n    return "Other"\n'
    )
    assert index_repo(tmp_path).failed == 0
    backend = active_index_backend(root=tmp_path)
    conn = cast("BackendQueryConnection", backend.open_connection(tmp_path))
    try:
        expected: dict[SymbolRow, int] = {}
        for term in ("Marker", "Other"):
            for row in _previous_candidates(conn, term):
                expected[row] = expected.get(row, 0) + 1
        assert source_candidates(conn, ("Marker", "Other"), None) == expected
        assert {row[2] for row in expected} >= {"Box", "run", "outside"}
    finally:
        backend.close_connection(conn)


def test_anchor_filter_precedes_limit_and_has_bounded_work(tmp_path: Path) -> None:
    """Apply literal path prefixes before limiting and avoid correlated scans.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Disposable index with hundreds of unrelated enclosing ranges.

    Returns
    -------
    None
        Restricted hits survive the cap and complete within a VM-step budget.
    """
    (tmp_path / ".codira").mkdir()
    (tmp_path / ".codira/config.toml").write_text("[embeddings]\nenabled = false\n")
    (tmp_path / "first.py").write_text(
        "\n".join(f'def fn{i}():\n    return "Marker"\n' for i in range(500))
    )
    selected = tmp_path / "z_%_é.py"
    selected.write_text('def selected():\n    return "Marker"\n')
    assert index_repo(tmp_path).failed == 0
    backend = active_index_backend(root=tmp_path)
    conn = backend.open_connection(tmp_path)
    assert isinstance(conn, sqlite3.Connection)
    statements: list[str] = []
    conn.set_trace_callback(statements.append)
    ticks = 0

    def bounded_progress() -> int:
        """Interrupt SQL that exceeds the regression's VM-step allowance.

        Parameters
        ----------
        None

        Returns
        -------
        int
            Nonzero once one million instructions have executed.
        """
        nonlocal ticks
        ticks += 1
        return int(ticks > 1000)

    conn.set_progress_handler(bounded_progress, 1000)
    try:
        rows = source_candidates(conn, ("Marker",), str(selected))
        assert rows and all(row[3] == str(selected) for row in rows)
        assert any(row[2] == "selected" for row in rows)
        query = statements[0]
        plan = conn.execute("EXPLAIN QUERY PLAN " + query).fetchall()
        assert not any("CORRELATED" in str(row) for row in plan)
        assert len(statements) == 1
    finally:
        backend.close_connection(conn)
