"""Regressions for template evidence obscured by unknown header macros.

Parameters
----------
None

Returns
-------
None
    Exercises language selection separately from extraction qualification.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

    from codira.contracts import LanguageAnalyzer

import pytest
from codira_analyzer_c import CAnalyzer
from codira_analyzer_cpp import CppAnalyzer
from codira_analyzer_cpp.cpp_headers import has_named_template_parameters
from codira_analyzer_cpp.cpp_preprocessing import _parse_cpp_source

from codira.indexer import _select_language_analyzer


@pytest.mark.parametrize(
    "parameters",
    [
        "class T",
        "typename T",
        "class... Ts",
        "typename... Ts",
        "class T = int",
        "int N, typename T",
        "class T, class U = Box<T>",
        "class T, class U = Box<Box<T>>",
        "class /* type */ T",
        "class T, bool B = (2 > 1)",
        "class T, char C = '>'",
    ],
)
def test_partial_template_header_selects_cpp(tmp_path: Path, parameters: str) -> None:
    """Select C++ using an isolated prefix despite external annotation macros.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Owned source repository.
    parameters : str
        Complete type and value parameter list with at least one named type.

    Returns
    -------
    None
        Both registration orders select C++ without claiming clean extraction.
    """
    source = (
        '// UTF-8: π\r\n#include "config.h"\r\nBEGIN\r\n'
        f"template<{parameters}>\r\nANNOT inline bool predicate(int x) "
        "{ return x != 0; }\r\nEND\r\n"
    ).encode()
    root = _parse_cpp_source(source)
    assert root.has_error
    assert has_named_template_parameters(source, root)
    path = tmp_path / "sample.h"
    path.write_bytes(source)
    orders: tuple[list[LanguageAnalyzer], list[LanguageAnalyzer]] = (
        [CAnalyzer(), CppAnalyzer()],
        [CppAnalyzer(), CAnalyzer()],
    )
    for analyzers in orders:
        assert _select_language_analyzer(path, analyzers, tmp_path).name == "cpp"


@pytest.mark.parametrize(
    "source",
    [
        b"int template, class, x; void f(void) { (template < class) > x; }",
        b"int template, class, x; void f(void) { template < class > x; }",
        b"// template<class T>\nint value;",
        b'const char *s = "template<class T>";',
        b'const char *s = R"(template<class T>)";',
        b"#define HINT template<class T>\nint value;",
        b"#define HINT(x) template<class T>\nint value;",
        b"#pragma hint template<class T>\nint value;",
        b"#include <template/class T>\nint value;",
        b"#define class\nint template, x; void f(void) { template < class x; }",
        b"#define template\nBEGIN template<class T> ANNOT int f(); END",
        b"#define class\nBEGIN template<class T> ANNOT int f(); END",
        b"#define typename\nBEGIN template<typename T> ANNOT int f(); END",
        b"BEGIN template<class> ANNOT int f(); END",
        b"BEGIN template<int N> ANNOT int f(); END",
        b"BEGIN template<class T ANNOT int f(); END",
        b"BEGIN template<class T,> ANNOT int f(); END",
        b"BEGIN template<class T); ANNOT int f(); END",
    ],
)
def test_template_hint_rejects_opaque_ambiguous_or_incomplete_prefix(
    source: bytes,
) -> None:
    """Keep C expressions, opaque text and unproven prefixes out of the hint.

    Parameters
    ----------
    source : bytes
        C source or a prefix insufficient to establish a named type parameter.

    Returns
    -------
    None
        The fallback provides no C++ language evidence for the input.
    """
    assert not has_named_template_parameters(source, _parse_cpp_source(source))
