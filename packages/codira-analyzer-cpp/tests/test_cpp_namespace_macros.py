"""Verify namespace macro ownership and original artifact positions.

Parameters
----------
None

Returns
-------
None
    Defines expansion and conservative-fallback regression tests.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from codira_analyzer_cpp import CppAnalyzer
from codira_analyzer_cpp.cpp_preprocessing import _parse_cpp_source
from codira_analyzer_cpp.cpp_projection import _source_projection


def test_nested_namespace_macros_preserve_artifacts(tmp_path: Path) -> None:
    """Keep inline scopes, UTF-8 byte columns, CRLF lines and following globals.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Isolated source directory.

    Returns
    -------
    None
        Definitions, calls, signatures and namespace ownership remain exact.
    """
    source = (
        "#define O namespace outer { inline namespace abi_v3 {\r\n"
        "#define C } }\r\n"
        "#define API [[nodiscard]]\r\n"
        "O\r\n"
        "// café\r\n"
        "API int run(int x) { /* café */ return callee(x); }\r\n"
        "C\r\n"
        "int after() { return 0; }\r\n"
    ).encode()
    path = tmp_path / "scopes.cpp"
    path.write_bytes(source)
    result = CppAnalyzer().analyze_file(path, tmp_path)
    assert result.index_symbols
    functions = {item.name: item for item in result.functions}
    assert set(functions) == {"outer::abi_v3::run", "after"}
    function = functions["outer::abi_v3::run"]
    assert (function.lineno, function.end_lineno) == (6, 6)
    assert function.signature == "API int run(int x)"
    assert function.parameters == ("x",)
    assert function.calls[0].target == "callee"
    assert function.calls[0].lineno == 6
    assert function.calls[0].col_offset == len(
        "API int run(int x) { /* café */ return ".encode()
    )
    assert functions["after"].lineno == 8
    assert {item.name for item in result.declarations if item.kind == "namespace"} == {
        "outer",
        "outer::abi_v3",
    }


def test_header_aliases_and_compatible_alternatives() -> None:
    """Expand source-proven aliases only after their reaching include.

    Parameters
    ----------
    None

    Returns
    -------
    None
        Nested header scopes recover without substituting protected text.
    """
    header = (
        b"#define ABI __v3\n"
        b"#if BUILD\n#define OPEN namespace outer {\n"
        b"#else\n#define OPEN namespace outer {\n#endif\n"
        b"#define O OPEN inline namespace ABI {\n#define C } }\n"
    )
    source = (
        b'#include "scopes.h"\n'
        b'// O C\nO\nconst char* text = "O C";\n'
        b"int run() { return 0; }\nC\n"
    )
    root = _parse_cpp_source(
        source, included_sources=((header, source.index(b"\n") + 1),)
    )
    assert not root.has_error
    assert root.text == source
    assert root.named_children[-1].type == "namespace_definition"


@pytest.mark.parametrize(
    "definitions",
    [
        b"#define O namespace outer {\n#define C }\n#undef O\n",
        b"#define O namespace outer {\n#define C }\n#undef C\n",
        b"#define O(x) namespace x {\n#define C }\n",
        b"#define O namespace ABI {\n#define C }\n",
        b"#define O LOOP\n#define LOOP O\n#define C }\n",
        b"#if BUILD\n#define O namespace one {\n#else\n#define O namespace two {\n#endif\n#define C }\n",
        b"#define namespace widget\n#define O namespace outer {\n#define C }\n",
        b"#define inline widget\n#define O namespace outer {\n#define C }\n",
    ],
)
def test_ambiguous_namespace_macros_remain_diagnosed(definitions: bytes) -> None:
    """Hold unknown ABI scopes, conflicting branches and invalidating directives.

    Parameters
    ----------
    definitions : bytes
        Definitions without a unique supported namespace expansion.

    Returns
    -------
    None
        No complete tree is claimed from an unproven expansion.
    """
    assert _parse_cpp_source(definitions + b"O\nint run() {}\nC\n").has_error


def test_namespace_macros_do_not_hide_errors_or_late_definitions() -> None:
    """Preserve malformed bodies and uses preceding a reaching definition.

    Parameters
    ----------
    None

    Returns
    -------
    None
        Failed whole-file recovery retains a diagnostic tree.
    """
    definitions = b"#define O namespace outer {\n#define C }\n"
    assert _parse_cpp_source(definitions + b"O\nint broken( {\nC\n").has_error
    assert _parse_cpp_source(b"O\nint run() {}\nC\n" + definitions).has_error
    source = b'O\n#include "scopes.h"\nint run() {}\nC\n'
    boundary = source.index(b"\n", source.index(b"#include")) + 1
    assert _parse_cpp_source(
        source, included_sources=((definitions, boundary),)
    ).has_error


def test_projection_boundaries_and_invalid_ranges() -> None:
    """Map invocation interiors and EOF while rejecting overlapping edits.

    Parameters
    ----------
    None

    Returns
    -------
    None
        Expansion size cannot shift original positions or accept invalid edits.
    """
    projection = _source_projection(
        b"O\r\nx\nC", [(0, 1, b"namespace n {"), (5, 6, b"} }")]
    )
    assert projection.offset(4) == 0
    assert projection.offset(4, end=True) == 1
    assert projection.offset(len(projection.expanded), end=True) == 6
    assert projection.point(4) == (1, 1)
    with pytest.raises(ValueError, match="Invalid source projection"):
        _source_projection(b"abc", [(0, 2, b"n"), (1, 3, b"x")])
