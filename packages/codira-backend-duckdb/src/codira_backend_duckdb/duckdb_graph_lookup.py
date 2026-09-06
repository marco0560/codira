"""DuckDB graph-rebuild lookup helpers owned by the backend package."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .duckdb_call_resolution import _import_alias_map

if TYPE_CHECKING:
    from .duckdb_support import _DuckDBPersistenceConnection


def _load_module_functions(conn: _DuckDBPersistenceConnection) -> dict[str, set[str]]:
    """Load indexed top-level function names keyed by module.

    Parameters
    ----------
    conn : _DuckDBPersistenceConnection
        Open database connection.

    Returns
    -------
    dict[str, set[str]]
        Top-level function names keyed by module name.
    """
    rows = conn.execute("""
        SELECT m.name, f.name FROM functions f JOIN modules m ON f.module_id = m.id
        WHERE f.class_id IS NULL ORDER BY m.name, f.name
        """).fetchall()
    result: dict[str, set[str]] = {}
    for module_name, function_name in rows:
        result.setdefault(str(module_name), set()).add(str(function_name))
    return result


def _load_class_methods(
    conn: _DuckDBPersistenceConnection,
) -> dict[tuple[str, str], set[str]]:
    """Load indexed method names keyed by module and class.

    Parameters
    ----------
    conn : _DuckDBPersistenceConnection
        Open database connection.

    Returns
    -------
    dict[tuple[str, str], set[str]]
        Method names keyed by ``(module_name, class_name)``.
    """
    rows = conn.execute("""
        SELECT m.name, c.name, f.name FROM functions f JOIN classes c ON f.class_id = c.id
        JOIN modules m ON f.module_id = m.id ORDER BY m.name, c.name, f.name
        """).fetchall()
    result: dict[tuple[str, str], set[str]] = {}
    for module_name, class_name, method_name in rows:
        result.setdefault((str(module_name), str(class_name)), set()).add(
            str(method_name)
        )
    return result


def _load_import_aliases(
    conn: _DuckDBPersistenceConnection,
) -> dict[str, dict[str, str]]:
    """Load import alias maps keyed by owning module.

    Parameters
    ----------
    conn : _DuckDBPersistenceConnection
        Open database connection.

    Returns
    -------
    dict[str, dict[str, str]]
        Alias maps keyed by owning module name.
    """
    rows = conn.execute("""
        SELECT m.name, i.name, i.alias FROM imports i JOIN modules m ON i.module_id = m.id
        WHERE i.kind = 'import' ORDER BY m.name, i.lineno, i.name, COALESCE(i.alias, '')
        """).fetchall()
    imports: dict[str, list[dict[str, object]]] = {}
    for module_name, import_name, alias in rows:
        imports.setdefault(str(module_name), []).append(
            {"name": str(import_name), "alias": None if alias is None else str(alias)}
        )
    return {
        module_name: _import_alias_map(values)
        for module_name, values in imports.items()
    }


def _caller_class_from_owner(owner_name: str) -> str | None:
    """Return the class component of a logical callable owner name.

    Parameters
    ----------
    owner_name : str
        Logical callable owner name.

    Returns
    -------
    str | None
        Owning class name, or ``None`` for a top-level callable.
    """
    if "." not in owner_name:
        return None
    return owner_name.rsplit(".", 1)[0]
