"""Verify complex type spelling and real/imaginary operand call preservation.

Parameters
----------
None

Returns
-------
None
"""

from pathlib import Path

import pytest

from codira_analyzer_cpp import CppAnalyzer

COMPLEX_TYPES = [
    "_Complex double",
    "double _Complex",
    "long _Complex double",
    "double long _Complex",
    "__complex__ float",
    "float __complex__",
    "__complex int",
    "unsigned __complex__ int",
    "__complex__ long long",
    "_Complex",
    "const _Complex",
    "_Complex const",
    "_Complex _Float16",
    "_Complex _Complex double",
    "_Complex _Complex",
    "__complex__ _Complex",
]
OPERATORS = ["__real", "__real__", "__imag", "__imag__"]


@pytest.mark.parametrize("type_spelling", COMPLEX_TYPES)
def test_complex_type_keeps_original_signature_and_parameter_name(
    tmp_path: Path, type_spelling: str
) -> None:
    """Retain original declaration bounds and names for all supported spellings.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Isolated source directory.
    type_spelling : str
        Complex type spelling under test.

    Returns
    -------
    None
    """
    signature = f"{type_spelling} identity({type_spelling} value)"
    path = tmp_path / "complex.cpp"
    path.write_text(signature + " { return value; }\n")
    result = CppAnalyzer().analyze_file(path, tmp_path)
    assert result.index_symbols
    assert len(result.functions) == 1
    function = result.functions[0]
    assert function.name == "identity"
    assert function.parameters == ("value",)
    assert function.signature == signature
    assert function.lineno == 1
    assert function.end_lineno == 1
    assert function.calls == ()


@pytest.mark.parametrize("operator", OPERATORS)
@pytest.mark.parametrize("operand", ["get()", "(get())", "((get()))", "get() + x"])
def test_complex_operators_preserve_nested_call_coordinates(
    tmp_path: Path, operator: str, operand: str
) -> None:
    """Exclude the operator pseudo-call while retaining its actual operand call.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Isolated source directory.
    operator : str
        Reserved real or imaginary operator spelling.
    operand : str
        Parenthesized or compound operand containing a source call.

    Returns
    -------
    None
    """
    line = f"  return {operator}({operand}) + __imag__ x;"
    source = (
        "double get(void);\ndouble evaluate(double _Complex x) {\n" + line + "\n}\n"
    )
    path = tmp_path / "operators.cpp"
    path.write_text(source)
    result = CppAnalyzer().analyze_file(path, tmp_path)
    assert result.index_symbols
    function = next(f for f in result.functions if f.name == "evaluate")
    assert [
        (call.kind, call.target, call.lineno, call.col_offset)
        for call in function.calls
    ] == [("name", "get", 3, line.index("get"))]


def test_complex_unnamed_parameters_keep_full_source_type_binding(
    tmp_path: Path,
) -> None:
    """Keep unnamed parameters unnamed even with a trailing complex modifier.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Isolated source directory.

    Returns
    -------
    None
    """
    path = tmp_path / "unnamed.cpp"
    path.write_text("void f(double _Complex, double __complex__, int __complex) {}\n")
    result = CppAnalyzer().analyze_file(path, tmp_path)
    assert result.index_symbols
    function = result.functions[0]
    assert function.parameters == ()
    assert (
        function.signature
        == "void f(double _Complex, double __complex__, int __complex)"
    )


def test_complex_directives_literals_comments_and_macro_overrides_remain_opaque(
    tmp_path: Path,
) -> None:
    """Do not project source spellings used by preprocessing or literals.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Isolated source directory.

    Returns
    -------
    None
    """
    path = tmp_path / "opaque.cpp"
    path.write_text("""#define KEEP _Complex
/* __real__(hidden()) */
const char *text = "_Complex __imag__(hidden())";
_Complex double f(_Complex double x) { return x; }
""")
    result = CppAnalyzer().analyze_file(path, tmp_path)
    assert result.index_symbols
    assert [(f.name, f.calls) for f in result.functions] == [("f", ())]
    path.write_text("#define _Complex signed\n_Complex int f(void) { return 0; }\n")
    assert not CppAnalyzer().analyze_file(path, tmp_path).index_symbols


@pytest.mark.parametrize(
    "source",
    [
        "_Complex double f(void) { return __real__(; }",
        "_Complex void f(void) {}",
        "double f(void) { return __real__; }",
        "double f(void) { return __imag__(; }",
    ],
)
def test_malformed_complex_syntax_keeps_diagnostics(
    tmp_path: Path, source: str
) -> None:
    """Refuse incomplete operators and invalid type spellings.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Isolated source directory.
    source : str
        Intentionally malformed input.

    Returns
    -------
    None
    """
    path = tmp_path / "bad.cpp"
    path.write_text(source)
    assert not CppAnalyzer().analyze_file(path, tmp_path).index_symbols


def test_complex_views_keep_crlf_and_utf8_call_positions(tmp_path: Path) -> None:
    """Retain original byte positions across UTF-8 comments and CRLF endings.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Isolated source directory.

    Returns
    -------
    None
    """
    line = "  /* café */ return __real__(get()) + __imag__ value;"
    source = (
        "double get(void);\r\ndouble f(double __complex__ value) {\r\n"
        + line
        + "\r\n}\r\n"
    )
    path = tmp_path / "coords.cpp"
    path.write_bytes(source.encode())
    result = CppAnalyzer().analyze_file(path, tmp_path)
    assert result.index_symbols
    function = next(f for f in result.functions if f.name == "f")
    assert function.lineno == 2 and function.end_lineno == 4
    assert [(c.target, c.lineno, c.col_offset) for c in function.calls] == [
        ("get", 3, line.encode().index(b"get"))
    ]


def test_defined_complex_operator_remains_a_macro_call(tmp_path: Path) -> None:
    """Retain the previous opaque macro-call contract for a source override.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Isolated source directory.

    Returns
    -------
    None
    """
    path = tmp_path / "macro.cpp"
    path.write_text(
        "#define __real__(value) value\ndouble get(void);\ndouble f(void) { return __real__(get()); }\n"
    )
    result = CppAnalyzer().analyze_file(path, tmp_path)
    assert result.index_symbols
    function = next(f for f in result.functions if f.name == "f")
    assert [c.target for c in function.calls] == ["__real__", "get"]


def test_captured_header_complex_type_override_disables_builtin_projection(
    tmp_path: Path,
) -> None:
    """Respect an actual captured header redefining the reserved type spelling.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Isolated source and header directory.

    Returns
    -------
    None
    """
    (tmp_path / "type.h").write_text("#define _Complex signed\n")
    path = tmp_path / "source.cpp"
    path.write_text('#include "type.h"\n_Complex int f() { return 0; }\n')
    assert not CppAnalyzer().analyze_file(path, tmp_path).index_symbols


def test_complex_overloads_keep_distinct_original_type_signatures(
    tmp_path: Path,
) -> None:
    """Keep source type identities for unnamed complex overload parameters.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Isolated source directory.

    Returns
    -------
    None
    """
    path = tmp_path / "overloads.cpp"
    path.write_text("void f(double __complex__) {}\nvoid f(float __complex__) {}\n")
    result = CppAnalyzer().analyze_file(path, tmp_path)
    assert result.index_symbols
    assert len(result.functions) == 2
    assert len({f.stable_id for f in result.functions}) == 2
    assert {f.signature for f in result.functions} == {
        "void f(double __complex__)",
        "void f(float __complex__)",
    }
    assert all(f.parameters == () for f in result.functions)
