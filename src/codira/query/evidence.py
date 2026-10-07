"""Expand generation-bound indexed identities into whole source evidence.

Parameters
----------
None

Returns
-------
None
    Read-only evidence helpers shared by CLI and MCP.
"""
# ruff: noqa: EM101, TRY003

from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path
from typing import TYPE_CHECKING, cast

from codira.index_generation import IndexGenerationStore
from codira.query.exact import (
    EdgeQueryRequest,
    find_call_edges,
    find_callable_refs,
    find_symbol,
    logical_symbol_name,
)
from codira.registry import active_index_backend

if TYPE_CHECKING:
    from collections.abc import Sequence

    from codira.contracts import BackendQueryConnection
    from codira.types import SymbolRow


def symbol_identity(root: Path, symbol: SymbolRow) -> str:
    """Encode one indexed symbol and generation without an absolute path.

    Parameters
    ----------
    root : pathlib.Path
        Trusted repository root.
    symbol : codira.types.SymbolRow
        Indexed symbol row.

    Returns
    -------
    str
        Opaque generation-bound identity.
    """
    record = IndexGenerationStore(root).read()
    row = [*symbol]
    row[3] = Path(symbol[3]).resolve().relative_to(root.resolve()).as_posix()
    payload = {
        "symbol": row,
        "generation": None if record is None else record.generation,
    }
    return (
        "sym:"
        + base64.urlsafe_b64encode(
            json.dumps(payload, sort_keys=True).encode()
        ).decode()
    )


def expand_symbol(root: Path, identity: str, *, limit: int = 10) -> dict[str, object]:
    """Return a complete indexed definition and bounded static relationships.

    Parameters
    ----------
    root : pathlib.Path
        Trusted repository root.
    identity : str
        Identity returned by indexed discovery.
    limit : int, optional
        Maximum complete relationship items; source is never clipped.

    Returns
    -------
    dict[str, object]
        Verified source range, hash, ownership and relation provenance.

    Raises
    ------
    ValueError
        If identity, generation, source hash or trusted containment fails.
    """
    if not 1 <= limit <= 100 or not identity.startswith("sym:"):
        raise ValueError("invalid symbol evidence request")
    try:
        data = json.loads(base64.b64decode(identity[4:], altchars=b"-_", validate=True))
        kind, module, name, relative, line = data["symbol"]
        record = IndexGenerationStore(root).read()
        if (
            record is None
            or record.state != "ready"
            or data["generation"] != record.generation
        ):
            raise ValueError("stale symbol identity; rediscover after indexing")
        path = (root / relative).resolve()
        path.relative_to(root.resolve())
        if (
            Path(relative).is_absolute()
            or not isinstance(line, int)
            or isinstance(line, bool)
            or line < 1
        ):
            raise ValueError("invalid symbol evidence identity")
    except (KeyError, TypeError, json.JSONDecodeError) as error:
        raise ValueError("invalid symbol evidence identity") from error
    row: SymbolRow = (kind, module, name, str(path), line)
    backend = active_index_backend(root=root)
    conn = cast("BackendQueryConnection", backend.open_connection(root))
    try:
        if row not in find_symbol(root, name, conn=conn):
            raise ValueError("symbol identity is not indexed")
        stored = cast(
            "tuple[object, ...] | None",
            conn.execute(
                "SELECT hash FROM files WHERE path = ?", (str(path),)
            ).fetchone(),
        )
        content = path.read_bytes()
        digest = hashlib.sha256(content).hexdigest()
        if stored is None or stored[0] != digest:
            raise ValueError("source changed since indexing; reindex before expansion")
        end_row = cast(
            "tuple[object, ...] | None",
            conn.execute(
                """SELECT end_lineno FROM functions fn JOIN modules m ON fn.module_id=m.id
               JOIN files f ON m.file_id=f.id WHERE f.path=? AND fn.lineno=?
               UNION ALL SELECT end_lineno FROM classes c JOIN modules m ON c.module_id=m.id
               JOIN files f ON m.file_id=f.id WHERE f.path=? AND c.lineno=?""",
                (str(path), line, str(path), line),
            ).fetchone(),
        )
        lines = content.decode("utf-8").splitlines()
        end = (
            int(str(end_row[0]))
            if end_row is not None and end_row[0] is not None
            else line
        )
        if kind == "module":
            end = len(lines)
        start = _definition_start(content, path, line)
        qualified = logical_symbol_name(root, row, conn=conn)
        relations: list[dict[str, object]] = []
        for relation_kind, lookup in (
            ("call", find_call_edges),
            ("reference", find_callable_refs),
        ):
            for incoming in (True, False):
                for relation in lookup(
                    EdgeQueryRequest(
                        root=root, name=qualified, incoming=incoming, conn=conn
                    )
                ):
                    relations.append(
                        {
                            "kind": relation_kind,
                            "direction": "incoming" if incoming else "outgoing",
                            "provenance": "static_analyzer",
                            "edge": list(relation),
                            "resolved": bool(relation[-1]),
                            "locations": _relation_locations(root, conn, relation),
                        }
                    )
        return {
            "identity": identity,
            "file": relative,
            "start_line": start,
            "end_line": end,
            "source_sha256": digest,
            "source": "\n".join(lines[start - 1 : end]),
            "qualified_name": qualified,
            "owner": qualified.rpartition(".")[0] or None,
            "relations": relations[:limit],
            "relation_total": len(relations),
            "tests": [
                item
                for item in relations[:limit]
                if any(
                    location["test_path_heuristic"]
                    for location in cast("list[dict[str, object]]", item["locations"])
                )
            ],
            "coverage": {
                "dynamic_complete": False,
                "unresolved_relations": sum(
                    not bool(item["resolved"]) for item in relations
                ),
                "test_provenance": "static relation plus test-path heuristic; no test execution implied",
                "relations_omitted": max(0, len(relations) - limit),
                "warning": "Static relations do not establish complete dynamic impact or test coverage.",
            },
        }
    finally:
        backend.close_connection(conn)


def _relation_locations(
    root: Path, conn: BackendQueryConnection, relation: Sequence[object]
) -> list[dict[str, object]]:
    """Attach indexed endpoint locations and explicitly heuristic test labels.

    Parameters
    ----------
    root : pathlib.Path
        Trusted source root.
    conn : codira.contracts.BackendQueryConnection
        Current logical query connection.
    relation : collections.abc.Sequence[object]
        Static edge with module/name endpoints.

    Returns
    -------
    list[dict[str, object]]
        Verified indexed locations; empty endpoints remain unresolved.
    """
    locations: list[dict[str, object]] = []
    for endpoint, module, name in (
        ("source", relation[0], relation[1]),
        ("target", relation[2], relation[3]),
    ):
        if module is None or name is None:
            continue
        for row in find_symbol(root, f"{module}.{name}", conn=conn):
            path = Path(row[3]).resolve().relative_to(root.resolve())
            locations.append(
                {
                    "endpoint": endpoint,
                    "file": path.as_posix(),
                    "line": row[4],
                    "test_path_heuristic": any(
                        part in {"test", "tests"} for part in path.parts
                    )
                    or path.name.startswith("test_"),
                }
            )
    return locations


def _definition_start(content: bytes, path: Path, line: int) -> int:
    """Include adjacent Python decorators without parsing target code in core.

    Parameters
    ----------
    content : bytes
        Hash-verified source buffer.
    path : pathlib.Path
        Trusted path identifying the source language.
    line : int
        Indexed declaration start.

    Returns
    -------
    int
        Earliest adjacent decorator line or the indexed declaration start.
    """
    if path.suffix != ".py":
        return line
    lines = content.decode("utf-8", errors="replace").splitlines()
    declaration = lines[line - 1]
    indentation = len(declaration) - len(declaration.lstrip())
    start = line
    for position in range(line - 2, -1, -1):
        preceding = lines[position]
        stripped = preceding.strip()
        if not stripped:
            break
        depth = len(preceding) - len(preceding.lstrip())
        if depth == indentation and stripped.startswith("@"):
            start = position + 1
        elif depth <= indentation and not stripped.startswith((")", "]", "}")):
            break
    return start
