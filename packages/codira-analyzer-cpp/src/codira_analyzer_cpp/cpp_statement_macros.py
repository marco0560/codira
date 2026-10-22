"""Discover source-backed assertion macros without selecting preprocessing branches.

Parameters
----------
None

Returns
-------
None
    Candidate discovery only; ordered context selection still licenses expansion.
"""

from collections.abc import Mapping

from .cpp_macro_context import _definition, _directives
from .cpp_macro_expansion import _MacroToken, _macro_tokens
from .cpp_macro_projection import _render_macro_tokens
from .cpp_syntax import _new_parser


def statement_invocations(
    source: bytes, captures: Mapping[str, bytes]
) -> tuple[tuple[int, int, bytes], ...]:
    """Locate complete invocations of captured function-like assertion macros.

    Parameters
    ----------
    source : bytes
        Original translation unit, including physical invocation positions.
    captures : Mapping[str, bytes]
        Source and literal include snapshots used by ordered context selection.

    Returns
    -------
    tuple[tuple[int, int, bytes], ...]
        Nonoverlapping start/end/name candidates outside directives and literals.

    Raises
    ------
    ValueError
        If an invocation is unclosed or the existing lexical bounds are exceeded.
    """
    names = set()
    for content in captures.values():
        if b"static_assert" not in content:
            continue
        for _, _, kind, payload in _directives(content):
            if kind != b"define":
                continue
            name, definition = _definition(payload)
            if definition is None or definition.parameters is None:
                continue
            tokens = _macro_tokens(definition.replacement)
            if tokens and tokens[0].spelling == b"static_assert":
                names.add(name)
    if not names or not any(name in source for name in names):
        return ()
    protected = [(a, b) for a, b, _, _ in _directives(source)]
    tokens = _macro_tokens(source)
    result = []
    covered = -1
    for index, token in enumerate(tokens[:-1]):
        if (
            index <= covered
            or token.spelling not in names
            or tokens[index + 1].spelling != b"("
            or any(a <= token.start < b for a, b in protected)
        ):
            continue
        depth = 0
        for closing in range(index + 1, len(tokens)):
            spelling = tokens[closing].spelling
            depth += int(spelling == b"(") - int(spelling == b")")
            if depth == 0:
                result.append((token.start, tokens[closing].end, token.spelling))
                covered = closing
                break
        else:
            raise ValueError("unclosed statement macro invocation")
    return tuple(result)


def declaration_invocations(
    source: bytes, captures: Mapping[str, bytes]
) -> tuple[tuple[int, int, bytes], ...]:
    """Locate complete invocations of captured variadic declaration forwarders.

    Parameters
    ----------
    source : bytes
        Original translation unit with physical invocation positions.
    captures : Mapping[str, bytes]
        Exact source and literal include snapshots used by ordered selection.

    Returns
    -------
    tuple[tuple[int, int, bytes], ...]
        Complete declaration-forwarder candidates outside directives and literals.

    Raises
    ------
    ValueError
        If a candidate invocation is unclosed or exceeds the bounded count.

    Notes
    -----
    Discovery accepts only a variadic definition whose entire replacement is
    ``__VA_ARGS__``. The ordered context walk still decides which definition
    reaches each invocation, and generated syntax is validated after expansion.
    """
    names = set()
    for content in captures.values():
        for _, _, kind, payload in _directives(content):
            if kind != b"define":
                continue
            name, definition = _definition(payload)
            if (
                definition is not None
                and definition.parameters is not None
                and definition.variadic
                and tuple(t.spelling for t in _macro_tokens(definition.replacement))
                == (b"__VA_ARGS__",)
            ):
                names.add(name)
    if not names or not any(name in source for name in names):
        return ()
    protected = [(a, b) for a, b, _, _ in _directives(source)]
    tokens = _macro_tokens(source)
    result = []
    covered = -1
    for index, token in enumerate(tokens[:-1]):
        if (
            index <= covered
            or token.spelling not in names
            or tokens[index + 1].spelling != b"("
            or any(a <= token.start < b for a, b in protected)
        ):
            continue
        depth = 0
        for closing in range(index + 1, len(tokens)):
            spelling = tokens[closing].spelling
            depth += int(spelling == b"(") - int(spelling == b")")
            if depth == 0:
                previous = None if index == 0 else tokens[index - 1].spelling
                if (
                    closing + 1 < len(tokens)
                    and tokens[closing + 1].spelling == b";"
                    and previous in {None, b"{", b";", b"}"}
                ):
                    result.append((token.start, tokens[closing].end, token.spelling))
                    covered = closing
                break
        else:
            raise ValueError("unclosed declaration macro invocation")
    if len(result) > 256:
        raise ValueError("declaration statement macro candidate limit exceeded")
    return tuple(result)


def is_declaration_statement(tokens: tuple[_MacroToken, ...]) -> bool:
    """Check that expanded tokens form exactly one declaration statement.

    Parameters
    ----------
    tokens : tuple[_MacroToken, ...]
        Rescanned tokens from one selected declaration-forwarder invocation.

    Returns
    -------
    bool
        Whether the expansion is empty or parses as one declaration.

    Raises
    ------
    ValueError
        If the bounded replacement cannot be rendered or parsed.
    """
    if not tokens:
        return True
    rendered, _ = _render_macro_tokens(tokens)
    tree = _new_parser().parse(b"void codira_probe() { " + rendered + b"; }").root_node
    function = next(
        (node for node in tree.named_children if node.type == "function_definition"),
        None,
    )
    body = None if function is None else function.child_by_field_name("body")
    statements = () if body is None else body.named_children
    return (
        not tree.has_error
        and len(statements) == 1
        and statements[0].type == "declaration"
    )


def has_lexical_calls(source: bytes, first: int, last: int) -> bool | None:
    """Detect calls inside one written macro argument without erasing their syntax.

    Parameters
    ----------
    source : bytes
        Original translation unit with physical invocation coordinates.
    first, last : int
        Complete invocation byte boundaries.

    Returns
    -------
    bool or None
        Whether the argument parses as one statement containing a call; ``None``
        means its syntax is unsupported and must remain unprojected.
    """
    tokens = _macro_tokens(source[first:last], offset=first)
    if len(tokens) < 3 or tokens[1].spelling != b"(":
        return None
    argument_start = tokens[1].end
    argument_end = tokens[-1].start
    arguments = source[argument_start:argument_end]
    candidate = b"void codira_probe() { " + arguments + b"; }"
    tree = _new_parser().parse(candidate).root_node
    if tree.has_error:
        return None
    function = next(
        (node for node in tree.named_children if node.type == "function_definition"),
        None,
    )
    body = None if function is None else function.child_by_field_name("body")
    if body is None:
        return None
    pending = [body]
    while pending:
        node = pending.pop()
        if node.type == "call_expression":
            return True
        pending.extend(node.named_children)
    return False
