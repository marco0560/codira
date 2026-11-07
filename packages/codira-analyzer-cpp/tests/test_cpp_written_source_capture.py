"""Check exact written-source transport from the C++ analyzer.

Parameters
----------
None

Returns
-------
None
    Captured evidence remains byte-exact for complete and partial analyses.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from codira_analyzer_cpp import CppAnalyzer

if TYPE_CHECKING:
    from pathlib import Path


def test_cpp_analysis_retains_exact_written_source_with_partial_coverage(
    tmp_path: Path,
) -> None:
    """Capture original bytes despite recovery and conditional projections.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary source directory.

    Returns
    -------
    None
        Original CRLF bytes and partial diagnostics are both retained.
    """
    source = (
        b"#if FEATURE\r\nint first() { return 1; }\r\n#else\r\n"
        b"int second() { return 2; }\r\n#endif\r\nint broken( {\r\n"
    )
    path = tmp_path / "partial.cpp"
    path.write_bytes(source)

    result = CppAnalyzer().analyze_file(path, tmp_path)

    assert result.written_source == source
    assert result.status is not None
    assert result.status.coverage_state.value == "partial"
    assert {function.name for function in result.functions} >= {"first", "second"}
