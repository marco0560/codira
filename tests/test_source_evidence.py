"""Verify neutral written-source tokenization and snapshot consistency."""

import hashlib

import pytest

from codira.source_evidence import source_evidence_rows


def test_source_evidence_keeps_written_lines_and_distinct_identifiers() -> None:
    """Keep comments, strings, conditional text, Unicode, and physical lines.

    Parameters
    ----------
    None

    Returns
    -------
    None
        Source evidence retains neutral lexical occurrences.
    """
    source = (
        '#if OTHER\r\n// ceil ceil\r\nconst char *x = "ceil";\n'
        "int café = 42; 123ceil\n#endif\n"
    ).encode()
    lines, tokens = source_evidence_rows(source, hashlib.sha256(source).hexdigest())
    assert lines[1] == (2, "// ceil ceil")
    assert ("ceil", 2) in tokens
    assert ("ceil", 3) in tokens
    assert ("ceil", 4) not in tokens
    assert ("café", 4) in tokens
    assert tokens.count(("ceil", 2)) == 1


def test_source_evidence_rejects_content_different_from_scanned_snapshot() -> None:
    """Never attach source evidence to a different indexed file digest.

    Parameters
    ----------
    None

    Returns
    -------
    None
        A mismatched digest is rejected.
    """
    with pytest.raises(ValueError, match="does not match"):
        source_evidence_rows(b"changed", hashlib.sha256(b"original").hexdigest())
