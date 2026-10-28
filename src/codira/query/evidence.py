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

from codira.analysis_inputs import analysis_input_fingerprint_matches
from codira.index_generation import IndexGenerationStore
from codira.query.exact import (
    EdgeQueryRequest,
    find_call_edges,
    find_callable_refs,
    find_symbol,
    logical_symbol_name,
)
from codira.registry import active_index_backend, active_language_analyzers

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
        generated, generated_declarations = _generated_evidence(
            root, path, conn, row, digest
        )
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
        if (
            generated is not None
            and generated.get("variant") != "compiler_observed_declaration"
            and generated["role"] == "definition"
        ):
            definition_rows = conn.execute(
                """SELECT fn.end_lineno FROM functions fn JOIN modules m ON fn.module_id=m.id
                   JOIN files f ON m.file_id=f.id WHERE f.path=? AND fn.name=? AND fn.lineno=?""",
                (str(path), name, line),
            ).fetchall()
            if len(definition_rows) != 1:
                raise ValueError("generated definition source ownership is ambiguous")
            end_row = tuple(definition_rows[0])
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
        result: dict[str, object] = {
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
        if generated is not None:
            _attach_generated_evidence(
                result, generated, generated_declarations, content
            )
        return result
    finally:
        backend.close_connection(conn)


def _generated_evidence(
    root: Path,
    path: Path,
    conn: BackendQueryConnection,
    row: SymbolRow,
    digest: str,
) -> tuple[dict[str, object] | None, list[dict[str, object]]]:
    """Load stable generated evidence and verify current analyzer inputs.

    Parameters
    ----------
    root, path : pathlib.Path
        Trusted repository and original source file.
    conn : BackendQueryConnection
        Active logical query connection.
    row : SymbolRow
        Exact indexed symbol identity.
    digest : str
        Verified original source digest.

    Returns
    -------
    tuple[dict[str, object] | None, list[dict[str, object]]]
        Canonical generated declaration and attached generated prototypes.

    Raises
    ------
    ValueError
        If identity, schema, source or context freshness checks fail.
    """
    kind, module, name, _, line = row
    generated_rows = conn.execute(
        """SELECT p.payload, p.stable_id, f.analysis_input_fingerprint,
                  f.analyzer_name, f.analyzer_version
           FROM artifact_provenance p JOIN symbol_index s
             ON p.file_id=s.file_id AND p.stable_id=s.stable_id
           JOIN files f ON f.id=p.file_id
           WHERE f.path=? AND s.type=? AND s.module_name=? AND s.name=? AND s.lineno=?""",
        (str(path), kind, module, name, line),
    ).fetchall()
    if len(generated_rows) > 1:
        raise ValueError(
            "generated symbol identity is ambiguous; rediscover after indexing"
        )
    generated: dict[str, object] | None = None
    generated_declarations: list[dict[str, object]] = []
    if generated_rows:
        from codira.generated import generated_provenance_payload

        payload, stable_id, expected_inputs, analyzer_name, analyzer_version = (
            generated_rows[0]
        )
        generated = generated_provenance_payload(str(payload))
        if (
            generated.get("variant") == "compiler_observed_declaration"
            and generated["declaration_kind"] != kind
        ):
            raise ValueError(
                "compiler-observed declaration kind does not match indexed symbol"
            )
        if (
            generated["source_sha256"] != digest
            or generated["context_identity"] != expected_inputs
        ):
            raise ValueError("generated provenance does not match indexed inputs")
        _verify_observed_invocation(root, path, generated)
        analyzer = next(
            (
                item
                for item in active_language_analyzers(root=root)
                if item.name == analyzer_name and item.version == analyzer_version
            ),
            None,
        )
        if analyzer is None or not analysis_input_fingerprint_matches(
            analyzer, path, root, str(expected_inputs)
        ):
            raise ValueError(
                "generated analysis inputs changed; reindex before expansion"
            )
        for (row_payload,) in conn.execute(
            """SELECT p.payload FROM artifact_provenance p
               JOIN overloads o ON o.stable_id=p.stable_id
               JOIN files f ON f.id=p.file_id
               WHERE f.path=? AND o.parent_stable_id=? ORDER BY o.ordinal""",
            (str(path), str(stable_id)),
        ).fetchall():
            overload = generated_provenance_payload(str(row_payload))
            if (
                overload["source_sha256"] != digest
                or overload["context_identity"] != expected_inputs
            ):
                raise ValueError("generated overload does not match indexed inputs")
            _verify_observed_invocation(root, path, overload)
            generated_declarations.append(overload)
    return generated, generated_declarations


def _attach_generated_evidence(
    result: dict[str, object],
    generated: dict[str, object],
    generated_declarations: list[dict[str, object]],
    content: bytes,
) -> None:
    """Attach truthful generated provenance fields to symbol evidence.

    Parameters
    ----------
    result : dict[str, object]
        Symbol evidence response being assembled.
    generated : dict[str, object]
        Validated generated provenance payload.
    generated_declarations : list[dict[str, object]]
        Validated generated overload evidence.
    content : bytes
        Verified source bytes for macro-invocation evidence.

    Returns
    -------
    None
        Evidence uses representation-appropriate source labels and ranges.
    """
    result["generated_provenance"] = generated
    result["generated_declarations"] = generated_declarations
    if generated.get("variant") in {
        "compiler_observed",
        "compiler_observed_declaration",
    }:
        result["source_kind"] = "compiler_generated"
        if generated["invocation"] is not None:
            result["compiler_observed_invocation"] = generated["invocation"]
        if generated.get("variant") == "compiler_observed_declaration":
            result["compiler_observed_declaration"] = {
                "origin": generated["origin"],
                "declaration_kind": generated["declaration_kind"],
                "spelling_location": generated["spelling_location"],
                "expansion_location": generated["expansion_location"],
            }
            invocation = generated["invocation"]
            if isinstance(invocation, dict) and invocation["path"] == result.get(
                "file"
            ):
                first, last = cast("list[int]", invocation["byte_range"])
                invocation_text = cast("str", invocation["text"])
                observed = invocation_text.encode("utf-8")
                if (
                    0 <= first < last <= len(content)
                    and content[first:last] == observed
                ):
                    result["start_line"] = content.count(b"\n", 0, first) + 1
                    result["end_line"] = content.count(b"\n", 0, last - 1) + 1
                    result["source"] = invocation_text
            return
        if generated.get("format_version") == 3 and generated.get("role") == "alias":
            result["compiler_observed_alias"] = {
                "target_identity": generated["alias_target_identity"],
                "linkage_name": generated["linkage_name"],
            }
            invocation = generated["invocation"]
            if isinstance(invocation, dict) and invocation["path"] == result.get(
                "file"
            ):
                first, last = cast("list[int]", invocation["byte_range"])
                invocation_text = cast("str", invocation["text"])
                observed = invocation_text.encode("utf-8")
                if (
                    0 <= first < last <= len(content)
                    and content[first:last] == observed
                ):
                    result["start_line"] = content.count(b"\n", 0, first) + 1
                    result["end_line"] = content.count(b"\n", 0, last - 1) + 1
                    result["source"] = invocation_text
                    return
            result.pop("start_line", None)
            result.pop("end_line", None)
            result.pop("source", None)
        return
    first, last = cast("list[int]", generated["invocation_span"])
    result.update(
        source_kind="macro_invocation",
        invocation_source=content[first:last].decode("utf-8"),
    )
    # V1 aliases and prototypes have an invocation, never an implementation body.
    if generated["role"] != "definition":
        result["start_line"] = content.count(b"\n", 0, first) + 1
        result["end_line"] = content.count(b"\n", 0, last - 1) + 1
        result["source"] = content[first:last].decode("utf-8")


def _verify_observed_invocation(
    root: Path,
    indexed_path: Path,
    payload: dict[str, object],
) -> None:
    """Match an observed preprocessor event to available source bytes.

    Parameters
    ----------
    root : pathlib.Path
        Trusted repository root.
    indexed_path : pathlib.Path
        Indexed translation unit owning the callable.
    payload : dict[str, object]
        Validated provenance payload.

    Returns
    -------
    None
        Any available invocation source agrees with the captured observation.

    Raises
    ------
    ValueError
        If the invocation escapes the repository or disagrees with source bytes.
    """
    if payload.get("variant") not in {
        "compiler_observed",
        "compiler_observed_declaration",
    }:
        return
    invocation = payload["invocation"]
    if invocation is None:
        return
    record = cast("dict[str, object]", invocation)
    relative = cast("str", record["path"])
    source_path = (root / relative).resolve()
    try:
        source_path.relative_to(root.resolve())
    except ValueError as error:
        raise ValueError("observed invocation path escapes repository") from error
    if not source_path.is_file():
        return
    source = source_path.read_bytes()
    if (
        source_path == indexed_path.resolve()
        and hashlib.sha256(source).hexdigest() != payload["source_sha256"]
    ):
        raise ValueError("source changed while verifying compiler observation")
    start, end = cast("list[int]", record["byte_range"])
    observed_text = cast("str", record["text"]).encode("utf-8")
    if end > len(source) or source[start:end] != observed_text:
        raise ValueError("observed preprocessor event does not match source bytes")


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
