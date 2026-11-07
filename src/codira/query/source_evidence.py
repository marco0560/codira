"""Retrieve exact lexical source evidence from the persisted index.

Parameters
----------
None

Returns
-------
None
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, cast

from codira.query.context_models import SourceEvidence
from codira.source_evidence import written_identifiers

if TYPE_CHECKING:
    from codira.contracts import BackendQueryConnection

_IDENTIFIER_LIMIT = 32
_SOURCE_EVIDENCE_LIMIT = 50
_SOURCE_LINE_TEXT_LIMIT = 1000
SourceEvidenceRow = tuple[str, str, int, str, str, str | None]


def _line_excerpt(line_text: str, identifiers: tuple[str, ...]) -> str:
    """Return a bounded excerpt centered on a matched identifier.

    Parameters
    ----------
    line_text : str
        Complete indexed source line.
    identifiers : tuple[str, ...]
        Identifiers matched on the line.

    Returns
    -------
    str
        Complete line when short, otherwise a bounded window around a match.
    """
    if len(line_text) <= _SOURCE_LINE_TEXT_LIMIT:
        return line_text
    positions = [
        position
        for identifier in identifiers
        if (position := line_text.find(identifier)) >= 0
    ]
    start = max(0, (positions[0] if positions else 0) - 400)
    if start + _SOURCE_LINE_TEXT_LIMIT > len(line_text):
        start = len(line_text) - _SOURCE_LINE_TEXT_LIMIT
    return line_text[start : start + _SOURCE_LINE_TEXT_LIMIT]


_QUERY_STOPWORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "by",
        "can",
        "code",
        "comment",
        "comments",
        "declaration",
        "declarations",
        "definition",
        "definitions",
        "find",
        "for",
        "from",
        "how",
        "in",
        "include",
        "is",
        "it",
        "locate",
        "me",
        "of",
        "on",
        "or",
        "show",
        "source",
        "tell",
        "that",
        "the",
        "this",
        "to",
        "where",
        "which",
        "with",
    }
)


def query_source_evidence(
    conn: BackendQueryConnection,
    root: Path,
    query: str,
    prefix: str | None,
) -> tuple[list[SourceEvidence], bool]:
    """Find bounded, exact identifier occurrences in indexed source lines.

    Parameters
    ----------
    conn : codira.contracts.BackendQueryConnection
        Active read-only connection to the index generation.
    root : pathlib.Path
        Repository root used to resolve a path prefix.
    query : str
        Original user query from which Unicode identifiers are extracted.
    prefix : str or None
        Optional normalized repository-relative path prefix.

    Returns
    -------
    tuple[list[codira.query.context_models.SourceEvidence], bool]
        Exact source lines ordered by path and line number, plus whether the
        bounded result was truncated. Text comes from the indexed snapshot.
    """
    query_identifiers = list(written_identifiers(query))
    filtered_identifiers = [
        identifier
        for identifier in query_identifiers
        if identifier.casefold() not in _QUERY_STOPWORDS
    ]
    identifiers = (
        filtered_identifiers
        if len(query_identifiers) > 1 and filtered_identifiers
        else query_identifiers
    )
    identifiers_truncated = len(identifiers) > _IDENTIFIER_LIMIT
    identifiers = identifiers[:_IDENTIFIER_LIMIT]
    if not identifiers:
        return ([], False)

    placeholders = ", ".join("?" for _ in identifiers)
    parameters: list[object] = list(identifiers)
    prefix_clause = ""
    if prefix:
        prefix_path = str((root / prefix).resolve())
        directory_prefix = f"{prefix_path}/"
        prefix_clause = " AND (f.path = ? OR substr(f.path, 1, ?) = ?)"
        parameters.extend((prefix_path, len(directory_prefix), directory_prefix))
    parameters.append(_SOURCE_EVIDENCE_LIMIT + 1)

    rows = cast(
        "list[SourceEvidenceRow]",
        conn.execute(
            "SELECT t.identifier, f.path, t.lineno, l.line_text, f.hash, a.coverage_state "
            "FROM written_source_tokens AS t "
            "JOIN written_source_lines AS l "
            "ON l.file_id = t.file_id AND l.lineno = t.lineno "
            "JOIN files AS f ON f.id = t.file_id "
            "LEFT JOIN analysis_status AS a ON a.path = f.path "
            f"WHERE t.identifier IN ({placeholders}){prefix_clause} "
            "GROUP BY t.identifier, f.path, t.lineno, l.line_text, f.hash, a.coverage_state "
            "ORDER BY f.path, t.lineno, t.identifier "
            "LIMIT ?",
            parameters,
        ).fetchall(),
    )

    grouped: dict[tuple[str, int], tuple[set[str], str, str, str | None]] = {}
    for identifier, file_path, lineno, line_text, file_sha256, coverage_state in rows:
        absolute_path = Path(str(file_path))
        try:
            rel_path = absolute_path.resolve().relative_to(root.resolve())
        except ValueError:
            continue
        key = (rel_path.as_posix(), int(lineno))
        identifiers_for_line, _existing_text, _existing_hash, _existing_coverage = (
            grouped.setdefault(
                key,
                (set(), str(line_text), str(file_sha256), coverage_state),
            )
        )
        identifiers_for_line.add(str(identifier))
    evidence = [
        SourceEvidence(
            file,
            lineno,
            tuple(sorted(identifiers_for_line)),
            _line_excerpt(line_text, tuple(sorted(identifiers_for_line))),
            file_sha256,
            None if coverage_state is None else str(coverage_state),
            len(line_text) > _SOURCE_LINE_TEXT_LIMIT,
        )
        for (file, lineno), (
            identifiers_for_line,
            line_text,
            file_sha256,
            coverage_state,
        ) in sorted(grouped.items())[:_SOURCE_EVIDENCE_LIMIT]
    ]
    return (
        evidence,
        identifiers_truncated
        or len(rows) > _SOURCE_EVIDENCE_LIMIT
        or len(grouped) > _SOURCE_EVIDENCE_LIMIT
        or any(item.line_truncated for item in evidence),
    )
