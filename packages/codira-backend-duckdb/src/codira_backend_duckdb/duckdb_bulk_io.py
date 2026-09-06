"""DuckDB bulk-import transport helpers owned by the backend package."""

from __future__ import annotations

from collections.abc import Sequence
import csv
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .duckdb_support import _DuckDBPersistenceConnection


def _temporary_csv_path_for_rows(rows: Sequence[Sequence[object]]) -> Path:
    """
    Write rows to a temporary CSV file for DuckDB bulk import.

    Parameters
    ----------
    rows : collections.abc.Sequence[collections.abc.Sequence[object]]
        Row values to serialize.

    Returns
    -------
    pathlib.Path
        Temporary CSV path owned by the caller.
    """
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        newline="",
        prefix="codira-duckdb-bulk-",
        suffix=".csv",
        delete=False,
    ) as handle:
        csv_path = Path(handle.name)
        csv.writer(handle).writerows(rows)
    return csv_path


def _flush_registered_arrow_table(
    conn: _DuckDBPersistenceConnection,
    *,
    view_name: str,
    table: object,
    insert_sql: str,
) -> None:
    """
    Insert one Arrow table through a temporary DuckDB replacement scan.

    Parameters
    ----------
    conn : _DuckDBPersistenceConnection
        Open database connection.
    view_name : str
        Temporary replacement-scan name.
    table : object
        Arrow table accepted by DuckDB's Python replacement-scan API.
    insert_sql : str
        ``INSERT ... SELECT`` statement reading from ``view_name``.

    Returns
    -------
    None
        Rows are inserted in place and the replacement scan is unregistered.
    """
    conn.register(view_name, table)
    try:
        conn.execute(insert_sql)
    finally:
        conn.unregister(view_name)
