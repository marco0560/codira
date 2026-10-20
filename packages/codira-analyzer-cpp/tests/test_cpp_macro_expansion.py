"""Check bounded macro substitution independently of conditional selection.

Parameters
----------
None

Returns
-------
None
    Token, provenance, recursion and failure controls for declaration expansion.
"""

from __future__ import annotations

import pytest

from codira_analyzer_cpp.cpp_macro_expansion import (
    _expand_macro_tokens,
    _MacroDefinition,
    _macro_tokens,
)


@pytest.mark.parametrize(
    ("source", "definitions", "expected"),
    [
        (
            b"A",
            {b"A": _MacroDefinition(None, b"B"), b"B": _MacroDefinition(None, b"int")},
            b"int",
        ),
        (b"ID(ID(7))", {b"ID": _MacroDefinition((b"x",), b"x")}, b"7"),
        (b"F(2)", {b"F": _MacroDefinition((b"x",), b"F(x)")}, b"F ( 2 )"),
        (
            b"A A",
            {b"A": _MacroDefinition(None, b"B"), b"B": _MacroDefinition(None, b"A")},
            b"A A",
        ),
        (
            b"F(3)",
            {b"F": _MacroDefinition(None, b"G"), b"G": _MacroDefinition((b"x",), b"x")},
            b"3",
        ),
        (
            b"F()(3)",
            {b"F": _MacroDefinition((), b"G"), b"G": _MacroDefinition((b"x",), b"x")},
            b"3",
        ),
        (b"F", {b"F": _MacroDefinition((b"x",), b"x")}, b"F"),
        (
            b"F(ignored(1,2))",
            {
                b"F": _MacroDefinition((b"x",), b"9"),
                b"ignored": _MacroDefinition((), b"broken"),
            },
            b"9",
        ),
        (b"F()", {b"F": _MacroDefinition((b"x",), b"x")}, b""),
        (
            b"CAT(,x) CAT(x,) CAT(,)",
            {b"CAT": _MacroDefinition((b"a", b"b"), b"a ## b")},
            b"x x",
        ),
        (
            b"CAT(A,B)",
            {
                b"CAT": _MacroDefinition((b"a", b"b"), b"a ## b"),
                b"A": _MacroDefinition(None, b"wrong"),
                b"AB": _MacroDefinition(None, b"right"),
            },
            b"right",
        ),
        (b"PASTE(+,=)", {b"PASTE": _MacroDefinition((b"a", b"b"), b"a ## b")}, b"+="),
        (b"F(a,(b,c))", {b"F": _MacroDefinition((b"x", b"y"), b"y x")}, b"( b , c ) a"),
        (
            b"F(1,2,3)",
            {b"F": _MacroDefinition((b"x",), b"x __VA_ARGS__", True)},
            b"1 2 , 3",
        ),
        (
            b"F(1,,x,)",
            {b"F": _MacroDefinition((b"x",), b"__VA_ARGS__", True)},
            b", x ,",
        ),
        (b"F(1)", {b"F": _MacroDefinition((b"x",), b"x __VA_ARGS__", True)}, b"1"),
        (
            b"STR( A +  B )",
            {
                b"STR": _MacroDefinition((b"x",), b"#x"),
                b"A": _MacroDefinition(None, b"wrong"),
            },
            b'"A + B"',
        ),
        (b"STR(a/**/+b)", {b"STR": _MacroDefinition((b"x",), b"#x")}, b'"a +b"'),
        (
            b'STR("a\\\\b")',
            {b"STR": _MacroDefinition((b"x",), b"#x")},
            b'"\\"a\\\\\\\\b\\""',
        ),
        (b"STR()", {b"STR": _MacroDefinition((b"x",), b"#x")}, b'""'),
        (
            b"S(1,,x,)",
            {b"S": _MacroDefinition((b"x",), b"#__VA_ARGS__", True)},
            b'",x,"',
        ),
        (b"P(1.0e,+2)", {b"P": _MacroDefinition((b"a", b"b"), b"a ## b")}, b"1.0e+ 2"),
        (b'P("a",_tag)', {b"P": _MacroDefinition((b"a", b"b"), b"a ## b")}, b'"a"_tag'),
        (b'P(L,"a")', {b"P": _MacroDefinition((b"a", b"b"), b"a ## b")}, b'L"a"'),
        (
            b"F(a EMPTY+b)",
            {
                b"F": _MacroDefinition((b"x",), b"S(x)"),
                b"S": _MacroDefinition((b"x",), b"#x"),
                b"EMPTY": _MacroDefinition(None, b""),
            },
            b'"a +b"',
        ),
        (
            b"F()",
            {
                b"F": _MacroDefinition((b"x",), b"S(a x+b)"),
                b"S": _MacroDefinition((b"x",), b"#x"),
            },
            b'"a +b"',
        ),
        (
            b"F(A)",
            {
                b"F": _MacroDefinition((b"x",), b"x #x"),
                b"A": _MacroDefinition(None, b"42"),
            },
            b'42 "A"',
        ),
        (
            b"JOIN(foo,bar,baz)",
            {b"JOIN": _MacroDefinition((b"a", b"b", b"c"), b"a ## b ## c")},
            b"foobarbaz",
        ),
        (b"F(F(1))", {b"F": _MacroDefinition((b"x",), b"x x")}, b"1 1 1 1"),
        (
            b"A",
            {
                b"A": _MacroDefinition(None, b"F(A)"),
                b"F": _MacroDefinition((b"x",), b"x"),
            },
            b"A",
        ),
    ],
)
def test_expansion_semantics(
    source: bytes, definitions: dict[bytes, _MacroDefinition], expected: bytes
) -> None:
    """Match token semantics for dispatch, raw arguments and recursive rescan.

    Parameters
    ----------
    source : bytes
        Invocation source.
    definitions : dict[bytes, _MacroDefinition]
        Selected macro environment.
    expected : bytes
        Independently specified expected tokens.

    Returns
    -------
    None
        Asserts exact token spelling.
    """
    assert (
        b" ".join(token.spelling for token in _expand_macro_tokens(source, definitions))
        == expected
    )


@pytest.mark.parametrize("public", [False, True])
@pytest.mark.parametrize("explicit_alias", [False, True])
@pytest.mark.parametrize("weak_attribute", [False, True])
def test_libc_function_dispatch(
    public: bool, explicit_alias: bool, weak_attribute: bool
) -> None:
    """Expand LLVM libc's actual dispatch and declaration templates in both modes.

    Parameters
    ----------
    public : bool
        Select the source branch generating an implementation and alias.
    explicit_alias : bool
        Supply the supported fourth argument instead of stringifying the name.
    weak_attribute : bool
        Expand the source-described function-specific attribute override.

    Returns
    -------
    None
        Checks real declaration identities and argument-owned name provenance.
    """
    definitions = {
        b"LLVM_LIBC_EMPTY": _MacroDefinition(None, b""),
        b"GET_NOTHING": _MacroDefinition((), b"0", True),
        b"GET_SECOND": _MacroDefinition((b"first", b"second"), b"second", True),
        b"GET_FIFTH": _MacroDefinition(
            (b"first", b"second", b"third", b"fourth", b"fifth"), b"fifth", True
        ),
        b"EXPAND_THEN_SECOND": _MacroDefinition(
            (b"name",), b"GET_SECOND(name, LLVM_LIBC_EMPTY)"
        ),
        b"LLVM_LIBC_ATTR": _MacroDefinition(
            (b"name",), b"EXPAND_THEN_SECOND(LLVM_LIBC_FUNCTION_ATTR_##name)"
        ),
        b"LLVM_LIBC_FUNCTION_ATTR": _MacroDefinition(None, b""),
        b"LIBC_NAMESPACE": _MacroDefinition(None, b"__llvm_libc"),
        b"LLVM_LIBC_FUNCTION_IMPL_3": _MacroDefinition(
            (b"type", b"name", b"arglist"),
            b"LLVM_LIBC_FUNCTION_IMPL_4(type, name, arglist, #name)",
        ),
        b"LLVM_LIBC_FUNCTION": _MacroDefinition(
            (),
            b"GET_FIFTH(__VA_ARGS__, LLVM_LIBC_FUNCTION_IMPL_4, LLVM_LIBC_FUNCTION_IMPL_3, GET_NOTHING)(__VA_ARGS__)",
            True,
        ),
        b"LLVM_LIBC_FUNCTION_IMPL_4": _MacroDefinition(
            (b"type", b"name", b"arglist", b"c_alias"),
            b"LLVM_LIBC_ATTR(name) LLVM_LIBC_FUNCTION_ATTR decltype(LIBC_NAMESPACE::name) __##name##_impl__ asm(c_alias); decltype(LIBC_NAMESPACE::name) name [[gnu::alias(c_alias)]]; type __##name##_impl__ arglist"
            if public
            else b"type name arglist",
        ),
    }
    if weak_attribute:
        definitions[b"LLVM_LIBC_FUNCTION_ATTR_ceil"] = _MacroDefinition(
            None, b"LLVM_LIBC_EMPTY, [[gnu::weak]]"
        )
    source = (
        b"LLVM_LIBC_FUNCTION(double, ceil, (double x)"
        + (b', "ceil_export"' if explicit_alias else b"")
        + b")"
    )
    tokens = _expand_macro_tokens(source, definitions, offset=100)
    alias = b'"ceil_export"' if explicit_alias else b'"ceil"'
    expected = (
        b"decltype ( __llvm_libc :: ceil ) __ceil_impl__ asm ( "
        + alias
        + b" ) ; decltype ( __llvm_libc :: ceil ) ceil [ [ gnu :: alias ( "
        + alias
        + b" ) ] ] ; double __ceil_impl__ ( double x )"
        if public
        else b"double ceil ( double x )"
    )
    if weak_attribute and public:
        expected = b"[ [ gnu :: weak ] ] " + expected
    assert b" ".join(token.spelling for token in tokens) == expected
    function_tokens = [
        token for token in tokens if token.spelling in (b"ceil", b"__ceil_impl__")
    ]
    assert function_tokens
    for token in function_tokens:
        assert source[token.start - 100 : token.end - 100] == b"ceil"
        assert token.argument
        assert token.synthetic == (token.spelling == b"__ceil_impl__")
    parameter = next(token for token in tokens if token.spelling == b"x")
    assert source[parameter.start - 100 : parameter.end - 100] == b"x"


@pytest.mark.parametrize(
    ("source", "definitions"),
    [
        (b"F(1,2)", {b"F": _MacroDefinition((b"x",), b"x")}),
        (b"F(1", {b"F": _MacroDefinition((b"x",), b"x")}),
        (b"F(+,*)", {b"F": _MacroDefinition((b"x", b"y"), b"x ## y")}),
        (b"F(1)", {b"F": _MacroDefinition((b"x",), b"## x")}),
        (b"F(1)", {b"F": _MacroDefinition((b"x",), b"x ##")}),
        (b"F(1)", {b"F": _MacroDefinition((b"x",), b"# other")}),
        (b"F(1)", {b"F": _MacroDefinition((b"x", b"x"), b"x")}),
        (b"F(1)", {b"F": _MacroDefinition(None, b"x", True)}),
        (b"F(1)", {b"F": _MacroDefinition((), b"__VA_OPT__(x)", True)}),
        (b"F(1)", {b"F": _MacroDefinition((), b", ## __VA_ARGS__", True)}),
        (b"F(1)", {b"F": _MacroDefinition((), b"__VA_ARGS__")}),
        (b"F(1)", {b"F": _MacroDefinition((b"x",), b"x ## ## x")}),
        (b'R"(raw)"', {}),
        (b'"unterminated', {}),
        (b"/* unterminated", {}),
        (b"\xff", {}),
        (b"<%", {}),
        (b"%:%:", {}),
    ],
)
def test_unsupported_expansions_hold(
    source: bytes, definitions: dict[bytes, _MacroDefinition]
) -> None:
    """Reject unsupported inputs without returning partially fabricated tokens.

    Parameters
    ----------
    source : bytes
        Invalid or unsupported invocation.
    definitions : dict[bytes, _MacroDefinition]
        Selected macro environment.

    Returns
    -------
    None
        Asserts explicit failure.
    """
    with pytest.raises(ValueError):
        _expand_macro_tokens(source, definitions)


def test_token_splices_and_comments_keep_original_offsets() -> None:
    """Remove preprocessing splices before lexing and retain physical spans.

    Parameters
    ----------
    None

    Returns
    -------
    None
        Checks line-spliced identifiers, comments and string contents.
    """
    source = b'ab\\\ncd /* comment */ "/* literal */" // comment\\\ncontinued\n last'
    tokens = _macro_tokens(source, offset=20)
    assert [token.spelling for token in tokens] == [
        b"abcd",
        b'"/* literal */"',
        b"last",
    ]
    assert (tokens[0].start, tokens[0].end) == (20, 26)
    assert source[tokens[-1].start - 20 : tokens[-1].end - 20] == b"last"


def test_expansion_work_is_bounded() -> None:
    """Reject exponential replacement growth and excessive argument nesting.

    Parameters
    ----------
    None

    Returns
    -------
    None
        Checks finite failure for otherwise syntactically valid expansion.
    """
    definitions = {
        f"A{index}".encode(): _MacroDefinition(
            None, f"A{index + 1} A{index + 1}".encode()
        )
        for index in range(20)
    }
    with pytest.raises(ValueError, match="limit exceeded"):
        _expand_macro_tokens(b"A0", definitions)
    with pytest.raises(ValueError, match="nesting"):
        _expand_macro_tokens(
            b"F(" * 70 + b"1" + b")" * 70, {b"F": _MacroDefinition((b"x",), b"x")}
        )
    with pytest.raises(ValueError, match="source byte limit"):
        _expand_macro_tokens(b" " * 262145, {})
