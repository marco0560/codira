"""Resolve analyzer-owned aliases through existing indexed import metadata.

Parameters
----------
None

Returns
-------
None
    Deterministic canonical declaration candidates, retaining ambiguity.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, cast

from codira.registry import active_index_backend

if TYPE_CHECKING:
    from codira.contracts import BackendQueryConnection
    from codira.types import SymbolRow


def alias_candidates(
    root: Path, name: str, *, prefix: str | None, conn: object | None
) -> list[SymbolRow]:
    """Follow bounded alias and re-export chains in the logical import schema.

    Parameters
    ----------
    root : pathlib.Path
        Indexed repository.
    name : str
        Case-sensitive requested name, optionally module qualified.
    prefix : str or None
        Optional path restriction.
    conn : object or None
        Existing backend connection.

    Returns
    -------
    list[codira.types.SymbolRow]
        All resolved declarations; unresolved targets remain absent.
    """
    backend = active_index_backend(root=root)
    owns = conn is None
    connection = cast(
        "BackendQueryConnection", backend.open_connection(root) if owns else conn
    )
    result: set[SymbolRow] = set()
    pending = [name]
    seen: set[str] = set()
    try:
        while pending and len(seen) < 64:
            requested = pending.pop(0)
            if requested in seen:
                continue
            seen.add(requested)
            short = requested.rsplit(".", 1)[-1]
            aliases = connection.execute(
                """SELECT m.name, i.name, i.alias, f.path FROM imports i
                   JOIN modules m ON i.module_id=m.id JOIN files f ON m.file_id=f.id
                   WHERE i.alias=? ORDER BY m.name,i.name,f.path""",
                (short,),
            ).fetchall()
            for module, target, alias, path in aliases:
                if requested not in {str(alias), f"{str(module)}.{str(alias)}"} or (
                    prefix is not None and not str(path).startswith(prefix)
                ):
                    continue
                target = str(target)
                pending.append(target)
                for row in backend.find_symbol(
                    root, target.rsplit(".", 1)[-1], prefix=prefix, conn=connection
                ):
                    logical = backend.logical_symbol_name(root, row, conn=connection)
                    if target == f"{row[1]}.{logical}":
                        result.add(row)
                # Qualified class constants have their owner in the stored name.
                for split in range(1, len(target.split("."))):
                    parts = target.split(".")
                    for row in backend.find_symbol(
                        root, ".".join(parts[split:]), prefix=prefix, conn=connection
                    ):
                        if row[1] == ".".join(parts[:split]):
                            result.add(row)
        return sorted(result)
    finally:
        if owns:
            backend.close_connection(connection)


def alias_evidence(
    root: Path, name: str, conn: BackendQueryConnection | None
) -> list[dict[str, object]]:
    """Expose bounded indexed alias and re-export provenance for exact lookup.

    Parameters
    ----------
    root : pathlib.Path
        Trusted repository root.
    name : str
        Requested exact identifier.
    conn : codira.contracts.BackendQueryConnection or None
        Existing logical query connection, or open a temporary connection.

    Returns
    -------
    list[dict[str, object]]
        Static alias edges with declaration location, target and relation kind.
        A bounded chain is not proof of complete runtime dispatch.
    """
    backend = active_index_backend(root=root)
    owns = conn is None
    connection = cast(
        "BackendQueryConnection", backend.open_connection(root) if owns else conn
    )
    assert connection is not None
    try:
        pending = [name]
        seen: set[str] = set()
        edges: list[dict[str, object]] = []
        while pending and len(seen) < 64:
            requested = pending.pop(0)
            if requested in seen:
                continue
            seen.add(requested)
            rows = connection.execute(
                "SELECT m.name,i.name,i.alias,i.kind,f.path,i.lineno FROM imports i JOIN modules m ON i.module_id=m.id JOIN files f ON m.file_id=f.id WHERE i.alias=? ORDER BY m.name,i.name,f.path",
                (requested.rsplit(".", 1)[-1],),
            ).fetchall()
            for module, target, alias, kind, path, line in rows:
                if requested not in {str(alias), f"{str(module)}.{str(alias)}"}:
                    continue
                relative = (
                    Path(str(path)).resolve().relative_to(root.resolve()).as_posix()
                )
                edges.append(
                    {
                        "alias": f"{str(module)}.{str(alias)}",
                        "target": str(target),
                        "kind": str(kind),
                        "file": relative,
                        "line": int(str(line)),
                        "provenance": "static_analyzer",
                    }
                )
                pending.append(str(target))
        return edges
    finally:
        if owns:
            backend.close_connection(connection)
