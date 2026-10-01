"""Retrieve causal vocabulary from persisted source evidence.

Parameters
----------
None

Returns
-------
None
    Repository independent lexical support for the symbol channel.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from codira.query.signals import RetrievalSignal
from codira.version import package_version

if TYPE_CHECKING:
    from codira.contracts import BackendQueryConnection
    from codira.types import SymbolRow


def symptom_terms(query: str) -> tuple[str, ...]:
    """Expand diagnostic terms without promoting generic task vocabulary.

    Parameters
    ----------
    query : str
        Original task description.

    Returns
    -------
    tuple[str, ...]
        Sorted source anchors, including explicit case-sensitive identifiers.
    """
    terms = set(re.findall(r"\b(?:[A-Z][A-Za-z0-9_]*|\w+_\w+)\b", query))
    terms.difference_update(
        {
            "Diagnose",
            "Identify",
            "Find",
            "Explain",
            "Fix",
            "The",
            "An",
            "Which",
            "Why",
            "Where",
            "Write",
            "Select",
            "Trace",
            "Add",
        }
    )
    groups = (
        (
            ("pickle", "pickling", "unpickle", "serialization"),
            ("pickle", "reduce", "Enum"),
        ),
        (("copy", "copying", "deepcopy"), ("copy", "deepcopy")),
        (("unset", "sentinel"), ("unset", "sentinel")),
        (("callback", "callbacks"), ("callback",)),
    )
    lowered = query.lower()
    for cues, anchors in groups:
        if any(cue in lowered for cue in cues):
            terms.update(anchors)
    return tuple(sorted(terms))


def source_candidates(
    conn: BackendQueryConnection, terms: tuple[str, ...], prefix: str | None
) -> dict[SymbolRow, int]:
    """Associate persisted source anchor hits with enclosing declarations.

    Parameters
    ----------
    conn : codira.contracts.BackendQueryConnection
        Open structural connection using the logical schema.
    terms : tuple[str, ...]
        Specific task anchors.
    prefix : str or None
        Optional normalized path restriction.

    Returns
    -------
    dict[codira.types.SymbolRow, int]
        Candidate rows with independent anchor counts, capped deterministically.
    """
    result: dict[SymbolRow, int] = {}
    for term in terms:
        rows = conn.execute(
            """SELECT s.type, s.module_name, s.name, f.path, s.lineno
               FROM symbol_index s JOIN files f ON f.id = s.file_id
               JOIN reference_scan_lines r ON r.file_id = f.id
               WHERE LOWER(r.line_text) LIKE LOWER(?) AND r.lineno >= s.lineno
               AND r.lineno <= COALESCE(
                   (SELECT MAX(c.end_lineno) FROM classes c JOIN modules m ON c.module_id=m.id
                    WHERE m.file_id=f.id AND c.lineno=s.lineno AND s.type='class'),
                   (SELECT MAX(fn.end_lineno) FROM functions fn JOIN modules m ON fn.module_id=m.id
                    WHERE m.file_id=f.id AND fn.lineno=s.lineno), s.lineno)
               ORDER BY f.path, s.lineno LIMIT 128""",
            (f"%{term}%",),
        ).fetchall()
        seen: set[SymbolRow] = set()
        for kind, module, name, path, line in rows:
            if prefix is not None and not str(path).startswith(prefix):
                continue
            row = (str(kind), str(module), str(name), str(path), int(str(line)))
            if row not in seen:
                result[row] = result.get(row, 0) + 1
                seen.add(row)
    return result


def source_signals(
    conn: BackendQueryConnection, query: str, prefix: str | None
) -> list[RetrievalSignal]:
    """Retain source-anchor support through rank fusion and explain output.

    Parameters
    ----------
    conn : codira.contracts.BackendQueryConnection
        Structural connection.
    query : str
        Original task.
    prefix : str or None
        Normalized path restriction.

    Returns
    -------
    list[codira.query.signals.RetrievalSignal]
        Independent task evidence with reproducible anchor counts.
    """
    candidates = source_candidates(conn, symptom_terms(query), prefix)
    return [
        RetrievalSignal(
            kind="text_match",
            family="task",
            target=symbol,
            producer_name="codira.indexed-source-anchors",
            producer_version=package_version(),
            capability_name="semantic_text",
            capability_version="1",
            channel_name="symbol",
            evidence_detail="source_anchors",
            rank=rank,
            strength=float(count),
        )
        for rank, (symbol, count) in enumerate(
            sorted(candidates.items(), key=lambda item: (-item[1], item[0])), 1
        )
    ]
