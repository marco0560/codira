"""Prepare neutral written-source occurrences for indexed retrieval."""

from __future__ import annotations

import hashlib


def written_identifiers(text: str) -> tuple[str, ...]:
    """Return distinct written identifiers in first-occurrence order.

    Parameters
    ----------
    text : str
        Source line or query text to tokenize.

    Returns
    -------
    tuple[str, ...]
        Identifiers using Unicode identifier start and continuation characters.
    """
    identifiers: dict[str, None] = {}
    start: int | None = None
    numeric_prefix = False
    for offset, char in enumerate(text):
        continuation = ("a" + char).isidentifier()
        if numeric_prefix:
            if continuation:
                continue
            numeric_prefix = False
        if start is None:
            if char == "_" or (char.isidentifier() and not char.isdecimal()):
                start = offset
            elif char.isdecimal():
                numeric_prefix = True
        elif not continuation:
            identifiers[text[start:offset]] = None
            start = (
                offset
                if char == "_" or (char.isidentifier() and not char.isdecimal())
                else None
            )
            numeric_prefix = char.isdecimal()
    if start is not None:
        identifiers[text[start:]] = None
    return tuple(identifiers)


def source_evidence_rows(
    source: bytes, expected_sha256: str
) -> tuple[list[tuple[int, str]], list[tuple[str, int]]]:
    """Prepare physical source lines and their distinct written identifiers.

    Parameters
    ----------
    source : bytes
        Exact source bytes captured by the analyzer.
    expected_sha256 : str
        Content digest recorded for the indexed file.

    Returns
    -------
    tuple[list[tuple[int, str]], list[tuple[str, int]]]
        Line number and display text, then identifier and line number pairs.
        Text is decoded as UTF-8 with replacement for invalid byte sequences.

    Raises
    ------
    ValueError
        The analyzer source differs from the scanned file snapshot.
    """
    if hashlib.sha256(source).hexdigest() != expected_sha256:
        message = "written source does not match indexed file digest"
        raise ValueError(message)

    text = source.decode("utf-8", errors="replace")
    physical_lines = text.split("\n")
    if physical_lines[-1] == "":
        physical_lines.pop()
    lines: list[tuple[int, str]] = []
    tokens: list[tuple[str, int]] = []
    for lineno, raw_line in enumerate(physical_lines, start=1):
        line = raw_line.removesuffix("\r")
        lines.append((lineno, line))
        tokens.extend(
            (identifier, lineno) for identifier in sorted(written_identifiers(line))
        )
    return lines, tokens
