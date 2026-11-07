"""Check token rendering and separate physical/generated projection coordinates.

Parameters
----------
None

Returns
-------
None
    Projection controls do not qualify original benchmark files.
"""

from __future__ import annotations

import pytest

from codira_analyzer_cpp.cpp_macro_expansion import (
    _MacroDefinition,
    _MacroToken,
    _expand_macro_tokens,
    _macro_tokens,
)
from codira_analyzer_cpp.cpp_macro_projection import (
    MacroReplacement,
    _render_macro_tokens,
    project_macro_replacements,
)
from codira_analyzer_cpp.cpp_syntax import _new_parser
from codira_analyzer_cpp.cpp_preprocessing import _original_declaration_start
from codira_analyzer_cpp.cpp_projection import _source_projection


@pytest.mark.parametrize("mask_generated", [False, True])
def test_source_layout_preserves_annotation_padding_without_generated_spelling(
    mask_generated: bool,
) -> None:
    """Carry provider blanks through physical and repeated source projections.

    Parameters
    ----------
    mask_generated : bool
        Whether the parsed view also blanks a generated replacement keyword.

    Returns
    -------
    None
        Annotation padding survives while original invocation bytes remain intact.
    """
    source = "// café\r\nMARK bool entry() { TOKEN(); return true; }\r\n".encode()
    first = source.index(b"TOKEN()")
    mapping = _source_projection(
        source, [(first, first + len(b"TOKEN()"), b"static_assert(true)")]
    )
    view = mapping.expanded.replace(b"MARK", b"    ")
    if mask_generated:
        view = view.replace(b"static_assert", b" " * len(b"static_assert"))
    root = _new_parser().parse(view).root_node
    assert not root.has_error
    projected = mapping.tree(root)
    expected = source.replace(b"MARK", b"    ")
    assert projected.text == expected
    assert mapping.source == source
    assert b"TOKEN()" in projected.text
    function = next(
        n for n in projected.named_children if n.type == "function_definition"
    )
    assert _original_declaration_start(function, source) == source.index(b"MARK")
    repeated = _source_projection(source, []).tree(projected)
    assert repeated.text == expected
    function = next(
        n for n in repeated.named_children if n.type == "function_definition"
    )
    assert _original_declaration_start(function, source) == source.index(b"MARK")


@pytest.mark.parametrize(
    "spellings",
    [
        (b"+", b"+"),
        (b"-", b">"),
        (b"/", b"*"),
        (b"/", b"/"),
        (b"<", b":"),
        (b"%", b":"),
        (b">", b">"),
        (b"#", b"#"),
        (b".", b".", b"."),
        (b"1", b"e", b"+", b"2"),
        (b"1", b"'x'"),
        (b'"x"', b"suffix"),
        (b"u8", b'"x"'),
        (b"left", b"right"),
        (b"[", b"[", b"gnu", b"::", b"alias", b"(", b'"x"', b")", b"]", b"]"),
    ],
)
def test_renderer_preserves_preprocessing_tokens(spellings: tuple[bytes, ...]) -> None:
    """Avoid accidental operators, comments, literals, suffixes and digit merging.

    Parameters
    ----------
    spellings : tuple[bytes, ...]
        Separate preprocessing tokens without inherited whitespace.

    Returns
    -------
    None
        Re-tokenization and every recorded rendered range preserve identity.
    """
    tokens = tuple(_MacroToken(value, 0, 1) for value in spellings)
    source, spans = _render_macro_tokens(tokens)
    assert tuple(token.spelling for token in _macro_tokens(source)) == spellings
    assert tuple(source[start:end] for start, end in spans) == spellings


def test_native_shaped_attribute_adjacency_remains_parseable() -> None:
    """Preserve paired attribute brackets in a public-packaging-shaped expansion.

    Parameters
    ----------
    None

    Returns
    -------
    None
        Native-shaped generated declarations parse without whitespace artifacts.
    """
    raw = b'decltype(ns::f) impl asm("f"); decltype(ns::f) f [[gnu::alias("f")]]; double impl(double x)'
    rendered, _ = _render_macro_tokens(_macro_tokens(raw))
    assert b"[[" in rendered and b"]]" in rendered
    assert not _new_parser().parse(rendered + b" { return x; }").root_node.has_error


def test_projection_maps_unchanged_body_and_separates_generated_spelling() -> None:
    """Map UTF-8/CRLF body bytes after a differently sized multiline invocation.

    Parameters
    ----------
    None

    Returns
    -------
    None
        Body calls remain physical while template/paste/stringify bytes do not.
    """
    source = "// café\r\n".encode() + b"WRAP(\r\nvalue) { return math::f(value); }\r\n"
    start = source.index(b"WRAP")
    end = source.index(b")", start) + 1
    definitions = {
        b"WRAP": _MacroDefinition(
            (b"x",), b"const char * name_##x = #x; double x(double a)"
        )
    }
    tokens = _expand_macro_tokens(source[start:end], definitions, offset=start)
    projection = project_macro_replacements(
        source, (MacroReplacement((start, end), tokens),)
    )
    call = projection.source.index(b"math::f")
    original_call = source.index(b"math::f")
    assert projection.physical_span(call, call + 7) == (
        original_call,
        original_call + 7,
    )
    assert projection.original == source
    for projected in projection.generated_tokens:
        first, last = projected.projected_span
        assert projection.source[first:last] == projected.token.spelling
        assert projection.physical_span(first, last) is None
        if projected.token.spelling in (b"name_value", b'"value"', b"double"):
            assert projected.physical_spelling_span is None
        if projected.token.spelling == b"value":
            assert projected.physical_spelling_span == (
                source.index(b"value"),
                source.index(b"value") + 5,
            )
    assert projection.physical_span(0, len(projection.source)) is None
    assert projection.physical_span(-1, 1) is None
    assert projection.physical_span(1, 1) is None


def test_spliced_argument_retains_its_exact_physical_span() -> None:
    """Keep a logical token's spliced source range without inventing byte identity.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The physical span contains the original splice while spelling is logical.
    """
    source = b"ID(na\\\nme)"
    tokens = _expand_macro_tokens(source, {b"ID": _MacroDefinition((b"x",), b"x")})
    result = project_macro_replacements(
        source, (MacroReplacement((0, len(source)), tokens),)
    )
    assert result.generated_tokens[0].token.spelling == b"name"
    assert result.generated_tokens[0].physical_spelling_span == (3, 9)


def test_multiple_replacements_and_empty_expansion_keep_source_segments() -> None:
    """Map original bytes after multiple replacements and a removed invocation.

    Parameters
    ----------
    None

    Returns
    -------
    None
        Empty expansions have no generated tokens and cannot merge neighbors.
    """
    source = b"left EMPTY()right;\nF() { return 1; }"
    first = (source.index(b"EMPTY"), source.index(b")") + 1)
    second = (source.index(b"F()"), source.index(b"F()") + 3)
    tokens = _expand_macro_tokens(
        b"F()", {b"F": _MacroDefinition((), b"int function()")}, offset=second[0]
    )
    result = project_macro_replacements(
        source, (MacroReplacement(first, ()), MacroReplacement(second, tokens))
    )
    assert tuple(token.spelling for token in _macro_tokens(result.source))[:2] == (
        b"left",
        b"right",
    )
    body = result.source.index(b"{ return")
    assert result.physical_span(body, len(result.source)) == (
        source.index(b"{ return"),
        len(source),
    )
    original = project_macro_replacements(source, ())
    assert original.source == source and original.physical_span(0, len(source)) == (
        0,
        len(source),
    )


@pytest.mark.parametrize("span", [(-1, 1), (0, 0), (1, 0), (0, 4)])
def test_invalid_invocation_ranges_are_rejected(span: tuple[int, int]) -> None:
    """Reject empty, reversed and out-of-source invocation ranges.

    Parameters
    ----------
    span : tuple[int, int]
        Invalid original range.

    Returns
    -------
    None
        No misleading projection is produced.
    """
    with pytest.raises(ValueError, match="invocation span"):
        project_macro_replacements(b"F()", (MacroReplacement(span, ()),))


def test_overlaps_and_forged_physical_spellings_are_rejected() -> None:
    """Validate original anchors and physical argument evidence before mapping.

    Parameters
    ----------
    None

    Returns
    -------
    None
        Generated bytes cannot masquerade as unchanged physical spellings.
    """
    with pytest.raises(ValueError, match="overlapping"):
        project_macro_replacements(
            b"F()", (MacroReplacement((0, 3), ()), MacroReplacement((0, 3), ()))
        )
    with pytest.raises(ValueError, match="anchor escapes"):
        project_macro_replacements(
            b"F()", (MacroReplacement((0, 3), (_MacroToken(b"x", 0, 4),)),)
        )
    with pytest.raises(ValueError, match="spelling does not match"):
        project_macro_replacements(
            b"F()",
            (MacroReplacement((0, 3), (_MacroToken(b"x", 0, 1, argument=True),)),),
        )


@pytest.mark.parametrize("spelling", [b"", b"x y", b"/*", b"a\0"])
def test_invalid_token_spellings_are_rejected(spelling: bytes) -> None:
    """Reject malformed or compound spellings supplied as one generated token.

    Parameters
    ----------
    spelling : bytes
        Unsupported token bytes.

    Returns
    -------
    None
        The renderer never silently changes the supplied token sequence.
    """
    with pytest.raises(ValueError):
        _render_macro_tokens((_MacroToken(spelling, 0, 1),))


def test_projection_bounds_are_enforced() -> None:
    """Bound source size, invocation count, expanded tokens and rendered bytes.

    Parameters
    ----------
    None

    Returns
    -------
    None
        Excessive work is rejected explicitly.
    """
    with pytest.raises(ValueError, match="source or invocation limit"):
        project_macro_replacements(b"x" * (8 * 1024 * 1024 + 1), ())
    with pytest.raises(ValueError, match="source or invocation limit"):
        project_macro_replacements(b"F", (MacroReplacement((0, 1), ()),) * 257)
    with pytest.raises(ValueError, match="token limit"):
        _render_macro_tokens((_MacroToken(b"x", 0, 1),) * 32769)
    with pytest.raises(ValueError, match="replacement byte limit"):
        _render_macro_tokens(
            (_MacroToken(b"x" * 262144, 0, 1), _MacroToken(b"y", 0, 1))
        )
