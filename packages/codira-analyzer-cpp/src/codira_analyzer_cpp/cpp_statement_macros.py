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
from .cpp_macro_expansion import _MacroToken, _macro_arguments, _macro_tokens
from .cpp_macro_projection import _render_macro_tokens
from .cpp_syntax import _new_parser


def statement_invocations(
    source: bytes, captures: Mapping[str, bytes]
) -> tuple[tuple[int, int, bytes], ...]:
    """Locate complete standalone invocations of captured statement macros.

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
        for _, _, kind, payload in _directives(content):
            if kind != b"define":
                continue
            name, definition = _definition(payload)
            if definition is None or definition.parameters is None:
                continue
            tokens = _macro_tokens(definition.replacement)
            forwards_argument = any(
                token.spelling in definition.parameters
                or definition.variadic
                and token.spelling == b"__VA_ARGS__"
                for token in tokens
            )
            if (tokens and tokens[0].spelling == b"static_assert") or (
                forwards_argument
                and (
                    is_statement_macro_replacement(tokens)
                    or is_statement_macro_replacement(
                        _statement_template_shape(tokens, definition.parameters)
                    )
                )
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
                    previous in {None, b"{", b";", b"}"}
                    and closing + 1 < len(tokens)
                    and tokens[closing + 1].spelling == b";"
                ):
                    result.append((token.start, tokens[closing].end, token.spelling))
                    covered = closing
                break
        else:
            raise ValueError("unclosed statement macro invocation")
    return tuple(result)


def is_statement_macro_replacement(tokens: tuple[_MacroToken, ...]) -> bool:
    """Check whether captured replacement syntax is one standalone statement.

    Parameters
    ----------
    tokens : tuple[_MacroToken, ...]
        Unexpanded replacement tokens from a captured function-like definition.

    Returns
    -------
    bool
        Whether the replacement parses as one C++ statement or declaration.
    """
    if not tokens:
        return False
    rendered, _ = _render_macro_tokens(tokens)
    tree = _new_parser().parse(b"void codira_probe() { " + rendered + b"; }").root_node
    function = next(
        (node for node in tree.named_children if node.type == "function_definition"),
        None,
    )
    body = None if function is None else function.child_by_field_name("body")
    statements = () if body is None else body.named_children
    return not tree.has_error and len(statements) == 1


def _statement_template_shape(
    tokens: tuple[_MacroToken, ...], parameters: tuple[bytes, ...] | None
) -> tuple[_MacroToken, ...]:
    """Replace valid preprocessing operators with parser-safe operand tokens.

    Parameters
    ----------
    tokens : tuple[_MacroToken, ...]
        Unexpanded function-like replacement tokens.
    parameters : tuple[bytes, ...] or None
        Parameters accepted by the selected definition.

    Returns
    -------
    tuple[_MacroToken, ...]
        Shape-only tokens for candidate discovery; these are never expanded.
    """
    if parameters is None:
        return tokens
    result: list[_MacroToken] = []
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if (
            token.spelling == b"#"
            and index + 1 < len(tokens)
            and tokens[index + 1].spelling in parameters
        ):
            result.append(tokens[index + 1])
            index += 2
            continue
        if token.spelling == b"##" and result and index + 1 < len(tokens):
            index += 2
            continue
        result.append(token)
        index += 1
    return tuple(result)


def is_empty_statement_replacement(tokens: tuple[_MacroToken, ...]) -> bool:
    """Recognize an explicitly empty do-while replacement statement.

    Parameters
    ----------
    tokens : tuple[_MacroToken, ...]
        Fully expanded replacement tokens.

    Returns
    -------
    bool
        Whether the sole statement has an empty compound body.
    """
    if not is_statement_macro_replacement(tokens):
        return False
    rendered, _ = _render_macro_tokens(tokens)
    tree = _new_parser().parse(b"void codira_probe() { " + rendered + b"; }").root_node
    function = next(
        (node for node in tree.named_children if node.type == "function_definition"),
        None,
    )
    body = None if function is None else function.child_by_field_name("body")
    statement = (
        None if body is None or not body.named_children else body.named_children[0]
    )
    if statement is None or statement.type != "do_statement":
        return False
    contents = next(
        (
            child
            for child in statement.named_children
            if child.type == "compound_statement"
        ),
        None,
    )
    return contents is not None and not contents.named_children


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


def has_transformed_call_arguments(
    source: bytes,
    first: int,
    last: int,
    expanded: tuple[_MacroToken, ...],
) -> bool:
    """Detect call-shaped argument spelling erased by stringification or paste.

    Parameters
    ----------
    source : bytes
        Original translation unit containing the complete macro invocation.
    first, last : int
        Physical byte boundaries of the invocation.
    expanded : tuple[_MacroToken, ...]
        Fully rescanned replacement tokens with argument provenance.

    Returns
    -------
    bool
        Whether call-shaped source argument tokens were transformed or lost.
    """
    invocation = _macro_tokens(source[first:last], offset=first)
    arguments, _, _ = _macro_arguments(list(invocation), 1)
    if not any(token.spelling == b"(" for argument in arguments for token in argument):
        return False
    preserved = {
        (token.start, token.end)
        for token in expanded
        if token.argument and not token.synthetic
    }
    transformed = any(
        token.argument or token.operation in {"paste", "stringify"}
        for token in expanded
    )
    if not transformed:
        return False

    call_spans = _source_call_token_spans(source, first, arguments)
    if not call_spans:
        return transformed and any(
            token.spelling != b"," and (token.start, token.end) not in preserved
            for argument in arguments
            for token in argument
        )
    return transformed and any(
        (token.start, token.end) not in preserved
        for span in call_spans
        for token in span
    )


def has_unpreserved_call_arguments(
    source: bytes,
    first: int,
    last: int,
    expanded: tuple[_MacroToken, ...],
) -> bool:
    """Check whether expansion lost tokens belonging to a written call.

    Parameters
    ----------
    source : bytes
        Original translation unit containing the complete macro invocation.
    first, last : int
        Physical byte boundaries of the invocation.
    expanded : tuple[_MacroToken, ...]
        Fully rescanned replacement tokens with argument provenance.

    Returns
    -------
    bool
        Whether a source call token needs recovery from the original syntax.
    """
    invocation = _macro_tokens(source[first:last], offset=first)
    arguments, _, _ = _macro_arguments(list(invocation), 1)
    call_spans = _source_call_token_spans(source, first, arguments)
    preserved = {
        (token.start, token.end)
        for token in expanded
        if token.argument and not token.synthetic
    }
    return any(
        (token.start, token.end) not in preserved
        for span in call_spans
        for token in span
    )


def _source_call_token_spans(
    source: bytes,
    first: int,
    arguments: list[tuple[_MacroToken, ...]],
) -> tuple[tuple[_MacroToken, ...], ...]:
    """Return lexical token groups belonging to parsed source call expressions.

    Parameters
    ----------
    source : bytes
        Original translation unit.
    first : int
        Physical start of the macro invocation.
    arguments : list[tuple[_MacroToken, ...]]
        Preprocessor arguments extracted from the invocation.

    Returns
    -------
    tuple[tuple[_MacroToken, ...], ...]
        Source token groups for each parsed call expression.
    """
    result: list[tuple[_MacroToken, ...]] = []
    prefix = b"void codira_probe() { "
    for argument in arguments:
        if not any(token.spelling == b"(" for token in argument):
            continue
        if not argument:
            continue
        start, end = argument[0].start, argument[-1].end
        tree = _new_parser().parse(prefix + source[start:end] + b"; }").root_node
        calls = []
        pending = [tree]
        while pending:
            node = pending.pop()
            if node.type == "call_expression":
                calls.append(node)
            pending.extend(node.named_children)
        for call in calls:
            call_start = call.start_byte - len(prefix)
            call_end = call.end_byte - len(prefix)
            result.append(
                tuple(
                    token
                    for token in argument
                    if call_start <= token.start - start
                    and token.end - start <= call_end
                )
            )
    return tuple(result)
