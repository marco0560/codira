"""Regressions for deterministic call and reference CSV bulk transport."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

import duckdb
import pytest

from codira_backend_duckdb.duckdb_artifact_persistence import (
    _flush_call_record_rows,
    _flush_callable_ref_record_rows,
)
from codira_backend_duckdb.schema import DDL

if TYPE_CHECKING:
    from codira_backend_duckdb.duckdb_support import (
        CallRow,
        RefRow,
        _DuckDBPersistenceConnection,
    )


@pytest.mark.parametrize("reference", [False, True])
def test_bulk_csv_preserves_late_quoted_fields(reference: bool) -> None:
    """Retain dialect-sensitive fields after a long plain-text prefix.

    Parameters
    ----------
    reference : bool
        Whether to exercise callable references instead of calls.

    Returns
    -------
    None
        Real DuckDB inserts preserve commas, quotes, Unicode and newlines.
    """
    with duckdb.connect(":memory:") as raw:
        for statement in DDL:
            raw.execute(statement)
        conn = cast("_DuckDBPersistenceConnection", raw)
        plain: CallRow = (
            1,
            "module",
            "owner",
            "attribute",
            "plain",
            "map",
            "",
            "",
            23,
            17,
        )
        special: list[CallRow] = [
            (2, "module", "owner", "attribute", base, "map", "", "", 408, 27)
            for base in (
                "opcodes.split(',')",
                'quoted "value", café',
                "",
                "first\nsecond",
                "first\r\nsecond",
            )
        ]
        calls = [plain] * 25_000 + special
        if reference:
            refs: list[RefRow] = [(*row[:4], "callback", *row[4:]) for row in calls]
            _flush_callable_ref_record_rows(conn, refs)
            actual = raw.execute(
                "SELECT * FROM callable_ref_records ORDER BY rowid"
            ).fetchall()
            assert actual == refs
        else:
            _flush_call_record_rows(conn, calls)
            actual = raw.execute("SELECT * FROM call_records ORDER BY rowid").fetchall()
            assert actual == calls


@pytest.mark.parametrize("reference", [False, True])
def test_bulk_csv_distinguishes_null_empty_and_literal_null_tokens(
    reference: bool,
) -> None:
    """Preserve NULL, empty text, and token-like strings through bulk CSV.

    Parameters
    ----------
    reference : bool
        Whether to exercise callable-reference rows instead of calls.

    Returns
    -------
    None
        The test asserts null encoding stays distinct from empty and literal
        values for both nullable record tables.
    """
    literal_tokens = (
        "__CODIRA_NULL_SENTINEL__",
        "__CODIRA_NULL_SENTINEL___",
        "__CODIRA_NULL_SENTINEL____",
    )
    with duckdb.connect(":memory:") as raw:
        for statement in DDL:
            raw.execute(statement)
        conn = cast("_DuckDBPersistenceConnection", raw)
        if reference:
            ref_rows: list[RefRow] = [
                (
                    1,
                    "module",
                    "owner",
                    "callable",
                    "callback",
                    "",
                    "target",
                    None,
                    None,
                    1,
                    0,
                ),
                (
                    1,
                    "module",
                    "owner",
                    "callable",
                    "callback",
                    "",
                    "target",
                    "",
                    "",
                    2,
                    0,
                ),
                (
                    1,
                    "module",
                    "owner",
                    "callable",
                    "callback",
                    "",
                    "target",
                    literal_tokens[0],
                    literal_tokens[1],
                    3,
                    0,
                ),
                (
                    1,
                    "module",
                    "owner",
                    "callable",
                    "callback",
                    "",
                    "target",
                    literal_tokens[2],
                    None,
                    4,
                    0,
                ),
            ]
            _flush_callable_ref_record_rows(conn, ref_rows)
            actual = raw.execute(
                "SELECT * FROM callable_ref_records ORDER BY lineno"
            ).fetchall()
            assert actual == ref_rows
        else:
            call_rows: list[CallRow] = [
                (1, "module", "owner", "name", "", "target", None, None, 1, 0),
                (1, "module", "owner", "name", "", "target", "", "", 2, 0),
                (
                    1,
                    "module",
                    "owner",
                    "name",
                    "",
                    "target",
                    literal_tokens[0],
                    literal_tokens[1],
                    3,
                    0,
                ),
                (
                    1,
                    "module",
                    "owner",
                    "name",
                    "",
                    "target",
                    literal_tokens[2],
                    None,
                    4,
                    0,
                ),
            ]
            _flush_call_record_rows(conn, call_rows)
            actual = raw.execute(
                "SELECT * FROM call_records ORDER BY lineno"
            ).fetchall()
            assert actual == call_rows
