"""DuckDB reference-scan persistence helpers owned by the backend package."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from .duckdb_bulk_io import _temporary_csv_path_for_rows
from .profiling import DuckDBProfileRecorder

if TYPE_CHECKING:
    from codira.types import ReferenceSearchRow

    from .duckdb_support import _DuckDBPersistenceConnection


def _reference_scan_rows(path: Path) -> list[ReferenceSearchRow]:
    """
    Return deterministic non-import source lines for query-time reference scans.

    Parameters
    ----------
    path : pathlib.Path
        Source file whose text should be prepared for stored reference scans.

    Returns
    -------
    list[codira.types.ReferenceSearchRow]
        Stored rows as ``(file_path, lineno, line_text)``.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []

    file_path = str(path)
    return [
        (file_path, lineno, line)
        for lineno, line in enumerate(text.splitlines(), start=1)
        if not line.strip().startswith(("import ", "from "))
    ]


def _flush_reference_scan_rows(
    conn: _DuckDBPersistenceConnection,
    *,
    file_id: int,
    path: Path,
    pending_rows: list[tuple[int, int, str]] | None = None,
) -> None:
    """
    Persist the stored reference-search surface for one indexed file.

    Parameters
    ----------
    conn : _DuckDBPersistenceConnection
        Open database connection.
    file_id : int
        Owning indexed file identifier.
    path : pathlib.Path
        Source file whose text should be stored for later query-time scans.
    pending_rows : list[tuple[int, int, str]] | None, optional
        Session-level reference row buffer. When supplied, rows are appended to
        the buffer and flushed by the caller in one backend batch.

    Returns
    -------
    None
        Matching non-import lines are inserted in deterministic order.
    """
    reference_rows = _reference_scan_rows(path)
    if not reference_rows:
        return

    rows = [
        (file_id, lineno, line_text) for _file_path, lineno, line_text in reference_rows
    ]
    if pending_rows is not None:
        pending_rows.extend(rows)
        return

    _flush_pending_reference_scan_rows(conn, rows)


def _flush_pending_reference_scan_rows(
    conn: _DuckDBPersistenceConnection,
    rows: list[tuple[int, int, str]],
    *,
    profiler: DuckDBProfileRecorder | None = None,
) -> None:
    """
    Flush pending reference-search rows to DuckDB in one batch.

    Parameters
    ----------
    conn : _DuckDBPersistenceConnection
        Open database connection.
    rows : list[tuple[int, int, str]]
        Stored reference rows as ``(file_id, lineno, line_text)``.
    profiler : codira_backend_duckdb.profiling.DuckDBProfileRecorder | None, optional
        Optional recorder for CSV staging spans.

    Returns
    -------
    None
        Pending reference rows are inserted in place.
    """
    if not rows:
        return

    active_profiler = (
        DuckDBProfileRecorder(enabled=False) if profiler is None else profiler
    )
    with active_profiler.span("csv.write.reference_scan_lines", rows=len(rows)):
        csv_path = _temporary_csv_path_for_rows(rows)
    try:
        with active_profiler.span("csv.read_csv.reference_scan_lines", rows=len(rows)):
            conn.execute(
                """
                INSERT INTO reference_scan_lines(file_id, lineno, line_text)
                SELECT *
                FROM read_csv(
                    ?,
                    header=false,
                    nullstr='__CODIRA_NULL_SENTINEL__',
                    columns={
                        'file_id': 'INTEGER',
                        'lineno': 'INTEGER',
                        'line_text': 'VARCHAR'
                    }
                )
                """,
                (str(csv_path),),
            )
    finally:
        try:
            csv_path.unlink()
        except FileNotFoundError:
            pass
