"""DuckDB derived graph-table rebuild owned by the backend package."""

from __future__ import annotations

from typing import cast

from .duckdb_bulk_io import _flush_registered_arrow_table
from .duckdb_call_resolution import _resolve_call_record, _unresolved_identity
from .duckdb_graph_lookup import (
    _caller_class_from_owner,
    _load_class_methods,
    _load_import_aliases,
    _load_module_functions,
)
from .duckdb_support import (
    CallResolutionRequest,
    CallRecord,
    _CALL_EDGES_REBUILD_TABLE_DDL,
    _CALLABLE_REFS_REBUILD_TABLE_DDL,
    _DERIVED_GRAPH_INDEX_DDL,
    _DERIVED_GRAPH_INDEX_DROP_DDL,
    _DuckDBPersistenceConnection,
    _duckdb_int,
)


def _rebuild_graph_indexes(conn: _DuckDBPersistenceConnection) -> None:
    """
    Rebuild derived call and callable-reference edges from stored raw records.

    Parameters
    ----------
    conn : _DuckDBPersistenceConnection
        Open database connection.

    Returns
    -------
    None
        The derived edge tables are replaced in place.
    """
    module_functions = _load_module_functions(conn)
    class_methods = _load_class_methods(conn)
    import_aliases_by_module = _load_import_aliases(conn)

    conn.execute("DROP TABLE IF EXISTS temp_call_edges_rebuild")
    conn.execute("DROP TABLE IF EXISTS temp_callable_refs_rebuild")
    conn.execute("""
        CREATE TEMP TABLE temp_call_edges_rebuild (
            caller_file_id INTEGER NOT NULL,
            caller_module TEXT NOT NULL,
            caller_name TEXT NOT NULL,
            callee_module TEXT,
            callee_name TEXT,
            unresolved_identity TEXT NOT NULL,
            external_target_kind TEXT,
            external_target_name TEXT,
            resolved INTEGER NOT NULL
        )
        """)
    conn.execute("""
        CREATE TEMP TABLE temp_callable_refs_rebuild (
            owner_file_id INTEGER NOT NULL,
            owner_module TEXT NOT NULL,
            owner_name TEXT NOT NULL,
            target_module TEXT,
            target_name TEXT,
            unresolved_identity TEXT NOT NULL,
            external_target_kind TEXT,
            external_target_name TEXT,
            resolved INTEGER NOT NULL
        )
        """)

    edges: set[
        tuple[
            int,
            str,
            str,
            str | None,
            str | None,
            str,
            str | None,
            str | None,
            int,
        ]
    ] = set()
    refs: set[
        tuple[
            int,
            str,
            str,
            str | None,
            str | None,
            str,
            str | None,
            str | None,
            int,
        ]
    ] = set()

    call_rows = conn.execute("""
        SELECT
            file_id,
            owner_module,
            owner_name,
            kind,
            base,
            target,
            external_target_kind,
            external_target_name,
            lineno,
            col_offset
        FROM call_records
        ORDER BY
            file_id,
            owner_module,
            owner_name,
            lineno,
            col_offset,
            kind,
            base,
            target
        """).fetchall()
    for (
        file_id,
        owner_module,
        owner_name,
        kind,
        base,
        target,
        external_target_kind,
        external_target_name,
        _lineno,
        _col_offset,
    ) in call_rows:
        record = cast(
            "CallRecord",
            {
                "kind": str(kind),
                "base": str(base),
                "target": str(target),
            },
        )
        caller_module = str(owner_module)
        caller_name = str(owner_name)
        callee_module, callee_name, resolved = _resolve_call_record(
            CallResolutionRequest(
                call=record,
                caller_module=caller_module,
                caller_class=_caller_class_from_owner(caller_name),
                import_aliases=import_aliases_by_module.get(caller_module, {}),
                module_functions=module_functions,
                class_methods=class_methods,
            )
        )
        edge_external_target_kind = (
            None
            if resolved or external_target_kind is None
            else str(external_target_kind)
        )
        edge_external_target_name = (
            None
            if resolved or external_target_name is None
            else str(external_target_name)
        )
        edges.add(
            (
                _duckdb_int(file_id),
                caller_module,
                caller_name,
                callee_module,
                callee_name,
                _unresolved_identity(record, resolved=resolved),
                edge_external_target_kind,
                edge_external_target_name,
                resolved,
            )
        )

    ref_rows = conn.execute("""
        SELECT
            file_id,
            owner_module,
            owner_name,
            kind,
            base,
            target,
            external_target_kind,
            external_target_name,
            lineno,
            col_offset
        FROM callable_ref_records
        ORDER BY
            file_id,
            owner_module,
            owner_name,
            lineno,
            col_offset,
            kind,
            base,
            target
        """).fetchall()
    for (
        file_id,
        owner_module,
        owner_name,
        kind,
        base,
        target,
        external_target_kind,
        external_target_name,
        _lineno,
        _col_offset,
    ) in ref_rows:
        record = cast(
            "CallRecord",
            {
                "kind": str(kind),
                "base": str(base),
                "target": str(target),
            },
        )
        caller_module = str(owner_module)
        caller_name = str(owner_name)
        target_module, target_name, resolved = _resolve_call_record(
            CallResolutionRequest(
                call=record,
                caller_module=caller_module,
                caller_class=_caller_class_from_owner(caller_name),
                import_aliases=import_aliases_by_module.get(caller_module, {}),
                module_functions=module_functions,
                class_methods=class_methods,
            )
        )
        ref_external_target_kind = (
            None
            if resolved or external_target_kind is None
            else str(external_target_kind)
        )
        ref_external_target_name = (
            None
            if resolved or external_target_name is None
            else str(external_target_name)
        )
        refs.add(
            (
                _duckdb_int(file_id),
                caller_module,
                caller_name,
                target_module,
                target_name,
                _unresolved_identity(record, resolved=resolved),
                ref_external_target_kind,
                ref_external_target_name,
                resolved,
            )
        )

    sorted_edges = sorted(
        edges,
        key=lambda item: (
            item[0],
            item[1],
            item[2],
            item[3] or "",
            item[4] or "",
            item[5],
            item[6] or "",
            item[7] or "",
            item[8],
        ),
    )
    if sorted_edges:
        import pyarrow as pa

        table = pa.table(
            {
                "caller_file_id": pa.array(
                    [row[0] for row in sorted_edges],
                    type=pa.int64(),
                ),
                "caller_module": pa.array(
                    [row[1] for row in sorted_edges],
                    type=pa.string(),
                ),
                "caller_name": pa.array(
                    [row[2] for row in sorted_edges],
                    type=pa.string(),
                ),
                "callee_module": pa.array(
                    [row[3] for row in sorted_edges],
                    type=pa.string(),
                ),
                "callee_name": pa.array(
                    [row[4] for row in sorted_edges],
                    type=pa.string(),
                ),
                "unresolved_identity": pa.array(
                    [row[5] for row in sorted_edges],
                    type=pa.string(),
                ),
                "external_target_kind": pa.array(
                    [row[6] for row in sorted_edges],
                    type=pa.string(),
                ),
                "external_target_name": pa.array(
                    [row[7] for row in sorted_edges],
                    type=pa.string(),
                ),
                "resolved": pa.array([row[8] for row in sorted_edges], type=pa.int64()),
            }
        )
        _flush_registered_arrow_table(
            conn,
            view_name="__codira_temp_call_edge_rows",
            table=table,
            insert_sql="""
                INSERT INTO temp_call_edges_rebuild(
                    caller_file_id,
                    caller_module,
                    caller_name,
                    callee_module,
                    callee_name,
                    unresolved_identity,
                    external_target_kind,
                    external_target_name,
                    resolved
                )
                SELECT
                    caller_file_id,
                    caller_module,
                    caller_name,
                    callee_module,
                    callee_name,
                    unresolved_identity,
                    external_target_kind,
                    external_target_name,
                    resolved
                FROM __codira_temp_call_edge_rows
                """,
        )

    sorted_refs = sorted(
        refs,
        key=lambda item: (
            item[0],
            item[1],
            item[2],
            item[3] or "",
            item[4] or "",
            item[5],
            item[6] or "",
            item[7] or "",
            item[8],
        ),
    )
    if sorted_refs:
        import pyarrow as pa

        table = pa.table(
            {
                "owner_file_id": pa.array(
                    [row[0] for row in sorted_refs],
                    type=pa.int64(),
                ),
                "owner_module": pa.array(
                    [row[1] for row in sorted_refs],
                    type=pa.string(),
                ),
                "owner_name": pa.array(
                    [row[2] for row in sorted_refs],
                    type=pa.string(),
                ),
                "target_module": pa.array(
                    [row[3] for row in sorted_refs],
                    type=pa.string(),
                ),
                "target_name": pa.array(
                    [row[4] for row in sorted_refs],
                    type=pa.string(),
                ),
                "unresolved_identity": pa.array(
                    [row[5] for row in sorted_refs],
                    type=pa.string(),
                ),
                "external_target_kind": pa.array(
                    [row[6] for row in sorted_refs],
                    type=pa.string(),
                ),
                "external_target_name": pa.array(
                    [row[7] for row in sorted_refs],
                    type=pa.string(),
                ),
                "resolved": pa.array([row[8] for row in sorted_refs], type=pa.int64()),
            }
        )
        _flush_registered_arrow_table(
            conn,
            view_name="__codira_temp_callable_ref_rows",
            table=table,
            insert_sql="""
                INSERT INTO temp_callable_refs_rebuild(
                    owner_file_id,
                    owner_module,
                    owner_name,
                    target_module,
                    target_name,
                    unresolved_identity,
                    external_target_kind,
                    external_target_name,
                    resolved
                )
                SELECT
                    owner_file_id,
                    owner_module,
                    owner_name,
                    target_module,
                    target_name,
                    unresolved_identity,
                    external_target_kind,
                    external_target_name,
                    resolved
                FROM __codira_temp_callable_ref_rows
                """,
        )

    for statement in _DERIVED_GRAPH_INDEX_DROP_DDL:
        conn.execute(statement)
    conn.execute("DROP TABLE call_edges")
    conn.execute("DROP TABLE callable_refs")
    conn.execute(_CALL_EDGES_REBUILD_TABLE_DDL)
    conn.execute(_CALLABLE_REFS_REBUILD_TABLE_DDL)
    conn.execute("""
        INSERT INTO call_edges(
            caller_file_id,
            caller_module,
            caller_name,
            callee_module,
            callee_name,
            unresolved_identity,
            external_target_kind,
            external_target_name,
            resolved
        )
        SELECT
            caller_file_id,
            caller_module,
            caller_name,
            callee_module,
            callee_name,
            unresolved_identity,
            external_target_kind,
            external_target_name,
            resolved
        FROM temp_call_edges_rebuild
        """)
    conn.execute("""
        INSERT INTO callable_refs(
            owner_file_id,
            owner_module,
            owner_name,
            target_module,
            target_name,
            unresolved_identity,
            external_target_kind,
            external_target_name,
            resolved
        )
        SELECT
            owner_file_id,
            owner_module,
            owner_name,
            target_module,
            target_name,
            unresolved_identity,
            external_target_kind,
            external_target_name,
            resolved
        FROM temp_callable_refs_rebuild
        """)
    for statement in _DERIVED_GRAPH_INDEX_DDL:
        conn.execute(statement)
    conn.execute("DROP TABLE temp_call_edges_rebuild")
    conn.execute("DROP TABLE temp_callable_refs_rebuild")
    conn.execute("DELETE FROM duckdb_symbol_lookup")
    conn.execute(
        """
        INSERT INTO duckdb_symbol_lookup(
            name,
            stable_id,
            type,
            module_name,
            file_id,
            path,
            lineno
        )
        SELECT
            s.name,
            s.stable_id,
            s.type,
            s.module_name,
            s.file_id,
            f.path,
            s.lineno
        FROM symbol_index s
        JOIN files f ON f.id = s.file_id
        """
    )
    conn.execute("DELETE FROM duckdb_documentation_lookup")
    conn.execute(
        """
        INSERT INTO duckdb_documentation_lookup(
            stable_id,
            kind,
            source_format,
            file_id,
            path,
            lineno,
            end_lineno,
            title,
            heading_path,
            text,
            owner_stable_id,
            owner_kind,
            attachment_confidence
        )
        SELECT
            d.stable_id,
            d.kind,
            d.source_format,
            d.file_id,
            f.path,
            d.lineno,
            d.end_lineno,
            d.title,
            d.heading_path,
            d.text,
            d.owner_stable_id,
            d.owner_kind,
            d.attachment_confidence
        FROM documentation_artifacts d
        JOIN files f ON f.id = d.file_id
        """
    )
