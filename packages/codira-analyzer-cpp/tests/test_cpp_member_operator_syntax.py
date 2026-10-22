"""Verify narrow recovery of explicit symbolic member operators.

Parameters
----------
None

Returns
-------
None
    Defines syntax-preservation and diagnostic-control tests.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from codira_analyzer_cpp import CppAnalyzer, _call_site_from_expression
from codira_analyzer_cpp.cpp_member_operator_syntax import _SYMBOLIC_OPERATORS
from codira_analyzer_cpp.cpp_preprocessing import _nodes, _parse_cpp_source
from codira_analyzer_cpp.cpp_projection import SyntaxNode as Node
from codira_analyzer_cpp.cpp_syntax import _new_parser


def _is_member_call(node: Node) -> bool:
    """Check whether a syntax node is a call through an explicit member.

    Parameters
    ----------
    node : SyntaxNode
        Candidate syntax node.

    Returns
    -------
    bool
        Whether the call's function is a member field expression.
    """
    if node.type != "call_expression":
        return False
    function = node.child_by_field_name("function")
    return function is not None and function.type == "field_expression"


def _operator_source(operator: bytes, receiver: bytes = b"object") -> bytes:
    """Build one complete type-context member-operator expression.

    Parameters
    ----------
    operator : bytes
        Symbolic operator spelling, without the operator keyword.
    receiver : bytes, optional
        Source expression used as the member receiver.

    Returns
    -------
    bytes
        One template declaration with a decltype operand call.
    """
    arguments = b"" if operator in {b"!", b"~", b"++", b"--", b"->"} else b"nested(0)"
    return (
        b"template<class T, class = decltype("
        + receiver
        + b".operator"
        + operator
        + b"("
        + arguments
        + b"))> void probe();\n"
    )


@pytest.mark.parametrize("operator", sorted(_SYMBOLIC_OPERATORS))
def test_symbolic_member_operator_names_recover_with_source_identity(
    operator: bytes,
) -> None:
    """Recover each supported symbolic spelling without changing its identity.

    Parameters
    ----------
    operator : bytes
        One symbolic C++ member operator name.

    Returns
    -------
    None
        Receiver, operator spelling, arguments, and physical coordinates survive.
    """
    source = _operator_source(operator)
    original = _new_parser().parse(source).root_node
    assert original.has_error

    recovered = _parse_cpp_source(source)
    assert not recovered.has_error
    assert recovered.text == source
    calls = [node for node in _nodes(recovered) if _is_member_call(node)]
    assert len(calls) == 1
    call = calls[0]
    function = call.child_by_field_name("function")
    assert function is not None
    receiver = function.child_by_field_name("argument")
    field = function.child_by_field_name("field")
    arguments = call.child_by_field_name("arguments")
    assert receiver is not None and field is not None and arguments is not None
    assert source[receiver.start_byte : receiver.end_byte] == b"object"
    assert source[field.start_byte : field.end_byte] == b"operator" + operator
    assert source[arguments.start_byte : arguments.end_byte] == (
        b"()" if operator in {b"!", b"~", b"++", b"--", b"->"} else b"(nested(0))"
    )
    call_site = _call_site_from_expression(call, source)
    assert call_site is not None
    assert call_site.target == "operator" + operator.decode()
    assert call_site.base == "object"


@pytest.mark.parametrize("operator", [b"/=", b"+="])
def test_libcxx_candidate_declaration_shape_is_recovered(operator: bytes) -> None:
    """Recover the exact decltype shape used by selected libcxx sources.

    Parameters
    ----------
    operator : bytes
        Explicit member operator spelling in the original declaration.

    Returns
    -------
    None
        The original receiver, operator, nested argument, and overload set survive.
    """
    source = (
        b"template <class It, class = decltype(fs::path{}.operator"
        + operator
        + b"(std::declval<It>()))>\n"
        + b"constexpr bool has_op(int) { return true; }\n"
        + b"template <class It>\n"
        + b"constexpr bool has_op(long) { return false; }\n"
    )
    original = _new_parser().parse(source).root_node
    assert original.has_error
    errors = [
        source[node.start_byte : node.end_byte]
        for node in _nodes(original)
        if node.is_error
    ]
    assert errors == [b".operator" + operator]
    recovered = _parse_cpp_source(source)
    assert not recovered.has_error
    assert recovered.text == source
    calls = [node for node in _nodes(recovered) if _is_member_call(node)]
    assert len(calls) == 1
    function = calls[0].child_by_field_name("function")
    assert function is not None
    receiver = function.child_by_field_name("argument")
    field = function.child_by_field_name("field")
    assert receiver is not None and field is not None
    assert source[receiver.start_byte : receiver.end_byte] == b"fs::path{}"
    assert source[field.start_byte : field.end_byte] == b"operator" + operator


@pytest.mark.parametrize(
    "receiver",
    [
        b"object",
        b"pointer",
        b"ns::Object{}",
        b"(ns::Object{})",
        b"factory<ns::Object>()",
    ],
)
def test_qualified_and_nested_receivers_keep_original_coordinates(
    receiver: bytes,
) -> None:
    """Project explicit operators for qualified and nested receiver forms.

    Parameters
    ----------
    receiver : bytes
        Bare, qualified, parenthesized, or nested source receiver expression.

    Returns
    -------
    None
        UTF-8 and CRLF coordinates remain physical-source coordinates.
    """
    source = b"// caf\xc3\xa9\r\n" + _operator_source(b"+=", receiver).replace(
        b"\n", b"\r\n"
    )
    recovered = _parse_cpp_source(source)
    assert not recovered.has_error
    assert recovered.text == source
    call = next(node for node in _nodes(recovered) if _is_member_call(node))
    function = call.child_by_field_name("function")
    assert function is not None
    field = function.child_by_field_name("field")
    assert field is not None
    offset = source.index(b"operator+=")
    assert field.start_byte == offset
    assert (field.start_point.row, field.start_point.column) == (
        1,
        offset - source.rfind(b"\n", 0, offset) - 1,
    )


def test_conversion_operator_declarations_and_standard_type_calls_are_unchanged() -> (
    None
):
    """Leave supported conversion declarations and type expressions untouched.

    Parameters
    ----------
    None

    Returns
    -------
    None
        Conversion declarations parse without a symbolic-name rewrite.
    """
    source = (
        b"struct Convertible { explicit operator bool() const; };\n"
        b"template<class T> using Truth = decltype(static_cast<bool>(T{}));\n"
    )
    original = _new_parser().parse(source).root_node
    recovered = _parse_cpp_source(source)
    assert not original.has_error
    assert not recovered.has_error
    assert str(recovered) == str(original)
    assert recovered.text == source


def test_member_operator_recovery_preserves_other_signatures_and_calls(
    tmp_path: Path,
) -> None:
    """Keep ordinary declarations and body calls intact beside an adapted type.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary source root used by the analyzer.

    Returns
    -------
    None
        The file remains analyzable with the original signature and call order.
    """
    source = (
        b"struct Receiver {};\n"
        b"int nested(int);\n"
        b"template<class T, class = decltype(Receiver{}.operator+=(nested(0)) )>\n"
        b"struct Probe {};\n"
        b"int keep(int value) { return nested(value); }\n"
    )
    path = tmp_path / "operator.cpp"
    path.write_bytes(source)
    result = CppAnalyzer().analyze_file(path, tmp_path)
    assert result.status is None
    keep = next(function for function in result.functions if function.name == "keep")
    assert keep.signature == "int keep(int value)"
    assert [call.target for call in keep.calls] == ["nested"]
    assert path.read_bytes() == source


@pytest.mark.parametrize(
    "source",
    [
        b"void f() { object.operator/=(nested(0)); }\n",
        b"template<class T, class = decltype(object.operator/=(nested(0)) + )> void f();\n",
        b"template<class T, class = decltype(object.operator??(nested(0)))> void f();\n",
        (
            b"#define operator replacement\n"
            b"template<class T, class = decltype(object.operator/=(nested(0)))> void f();\n"
        ),
    ],
)
def test_non_type_unknown_and_malformed_operator_syntax_stays_diagnostic(
    source: bytes,
) -> None:
    """Keep unsupported syntax and unrelated errors visible to callers.

    Parameters
    ----------
    source : bytes
        Non-type-context, malformed, unknown, or keyword-overridden source.

    Returns
    -------
    None
        The adapter does not convert ambiguous syntax into a clean tree.
    """
    original = _new_parser().parse(source).root_node
    assert original.has_error
    recovered = _parse_cpp_source(source)
    assert recovered.has_error
    assert recovered.text == source


def test_captured_operator_keyword_override_prevents_recovery() -> None:
    """Treat a captured header keyword override as ambiguous syntax.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The original diagnostic remains when a captured header redefines operator.
    """
    source = _operator_source(b"/=")
    header = b"#define operator replacement\n"
    recovered = _parse_cpp_source(source, included_sources=((header, 0),))
    assert recovered.has_error
    assert recovered.text == source
