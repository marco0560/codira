"""Recognize source-proven loop prefixes while preserving written call evidence.

Parameters
----------
None

Returns
-------
None
    Coordinate-preserving grammar hints, without expanding replacement bodies.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass
from itertools import chain

from tree_sitter import Node, Parser

_IDENTIFIER = re.compile(rb"[A-Za-z_][A-Za-z_0-9]*\Z")
_TOKEN = re.compile(
    rb"(?P<space>\s+|/\*.*?\*/|//[^\n]*)"
    rb"|(?:u8|u|U|L)?(?:\"(?:[^\"\\\n]|\\[^\n])*\"|'(?:[^'\\\n]|\\[^\n])*')"
    rb"|[A-Za-z_][A-Za-z_0-9]*|##|[^\s]",
    re.DOTALL,
)


@dataclass(frozen=True)
class _LoopDefinition:
    """Retain a fixed-arity replacement and its source availability boundary.

    Parameters
    ----------
    parameters : tuple[bytes, ...]
        Fixed parameter names; variadic definitions are held.
    tokens : tuple[bytes, ...]
        Unexpanded replacement tokens, with comments and splices removed.
    available_after : int
        Original source boundary after which the definition can be used.

    Returns
    -------
    None
        Immutable source evidence, not an expanded declaration or expression.
    """

    parameters: tuple[bytes, ...]
    tokens: tuple[bytes, ...]
    available_after: int


def _nodes(root: Node) -> Iterator[Node]:
    """Visit syntax nodes in source order without recursive Python calls.

    Parameters
    ----------
    root : tree_sitter.Node
        Root to visit.

    Returns
    -------
    collections.abc.Iterator[tree_sitter.Node]
        Deterministic depth-first traversal.
    """
    pending = [root]
    while pending:
        node = pending.pop()
        yield node
        pending.extend(reversed(node.children))


def _tokens(source: bytes) -> tuple[bytes, ...]:
    """Read structural tokens without interpreting macro replacement semantics.

    Parameters
    ----------
    source : bytes
        Replacement or argument bytes.

    Returns
    -------
    tuple[bytes, ...]
        Tokens retaining quoted delimiters as indivisible literals.
    """
    source = re.sub(rb"\\\r?\n", b"", source)
    return tuple(
        match[0] for match in _TOKEN.finditer(source) if match.lastgroup != "space"
    )


def _closing(tokens: tuple[bytes, ...], opening: int) -> int | None:
    """Find a matching structural delimiter while rejecting crossed groups.

    Parameters
    ----------
    tokens : tuple[bytes, ...]
        Tokens to inspect.
    opening : int
        Opening delimiter position.

    Returns
    -------
    int or None
        Closing index, or None for an unbalanced group.
    """
    pairs = {b"(": b")", b"[": b"]", b"{": b"}"}
    stack: list[bytes] = []
    for index in range(opening, len(tokens)):
        token = tokens[index]
        if token in pairs:
            stack.append(pairs[token])
        elif token in pairs.values():
            if not stack or stack.pop() != token:
                return None
            if not stack:
                return index
    return None


def _arity(tokens: tuple[bytes, ...]) -> int | None:
    """Count fixed preprocessing arguments using parentheses, not C expressions.

    Parameters
    ----------
    tokens : tuple[bytes, ...]
        Entire parenthesized invocation argument list.

    Returns
    -------
    int or None
        Argument count; zero for an empty list, None for invalid parentheses.
    """
    if not tokens or tokens[0] != b"(" or tokens[-1] != b")":
        return None
    if len(tokens) == 2:
        return 0
    depth = 0
    count = 1
    for token in tokens[1:-1]:
        if token == b"(":
            depth += 1
        elif token == b")":
            depth -= 1
            if depth < 0:
                return None
        elif token == b"," and depth == 0:
            count += 1
    return count if depth == 0 else None


def _loop_headers(tokens: tuple[bytes, ...]) -> bool:
    """Require a complete sequence of literal for headers with no supplied body.

    Parameters
    ----------
    tokens : tuple[bytes, ...]
        Unexpanded replacement-list tokens.

    Returns
    -------
    bool
        Whether each prefix has balanced delimiters and two header separators.
        This proves a statement-prefix role, not type or expression correctness.
    """
    index = 0
    heads = 0
    while index < len(tokens):
        if tokens[index : index + 2] != (b"for", b"("):
            return False
        closing = _closing(tokens, index + 1)
        if closing is None:
            return False
        depth = 0
        separators = 0
        for token in tokens[index + 2 : closing]:
            if token in (b"(", b"[", b"{"):
                depth += 1
            elif token in (b")", b"]", b"}"):
                depth -= 1
            elif token == b";" and depth == 0:
                separators += 1
        if separators != 2:
            return False
        heads += 1
        if heads > 8:
            return False
        index = closing + 1
    return bool(heads)


def _definitions(
    source: bytes,
    root: Node,
    parser: Parser,
    included_sources: tuple[tuple[bytes, int], ...],
) -> tuple[dict[bytes, list[_LoopDefinition]], set[bytes]]:
    """Collect all observed alternatives without choosing compilation branches.

    Parameters
    ----------
    source : bytes
        Original-coordinate source buffer.
    root : tree_sitter.Node
        Tree for that buffer.
    parser : tree_sitter.Parser
        Parser for captured contained headers.
    included_sources : tuple[tuple[bytes, int], ...]
        Header bytes and original include availability boundaries.

    Returns
    -------
    tuple[dict[bytes, list[_LoopDefinition]], set[bytes]]
        Function alternatives and names invalidated by unsupported definitions
        or undefinitions. Keyword overrides invalidate the entire projection.
    """
    result: dict[bytes, list[_LoopDefinition]] = {}
    unsafe: set[bytes] = set()
    for content, boundary, tree in chain(
        ((source, -1, root),),
        (
            (raw, offset, parser.parse(raw).root_node)
            for raw, offset in included_sources
        ),
    ):
        for node in _nodes(tree):
            if node.type == "preproc_call":
                match = re.match(
                    rb"#\s*undef\s+([A-Za-z_][A-Za-z_0-9]*)",
                    content[node.start_byte : node.end_byte],
                )
                if match:
                    unsafe.add(match[1])
                continue
            if node.type not in {"preproc_def", "preproc_function_def"}:
                continue
            name_node = node.child_by_field_name("name")
            if name_node is None:
                continue
            name = content[name_node.start_byte : name_node.end_byte]
            if name in {b"for", b"while"} or node.type == "preproc_def":
                unsafe.add(name)
                continue
            parameters = node.child_by_field_name("parameters")
            value = node.child_by_field_name("value")
            if parameters is None:
                unsafe.add(name)
                continue
            raw_parameters = _tokens(
                content[parameters.start_byte : parameters.end_byte]
            )
            if (
                len(raw_parameters) < 2
                or raw_parameters[0] != b"("
                or raw_parameters[-1] != b")"
            ):
                unsafe.add(name)
                continue
            interior = raw_parameters[1:-1]
            names = interior[::2]
            if (
                any(
                    not _IDENTIFIER.fullmatch(token) or token in {b"for", b"while"}
                    for token in names
                )
                or len(names) != len(set(names))
                or interior[1::2] != (b",",) * max(0, len(names) - 1)
            ):
                unsafe.add(name)
                continue
            result.setdefault(name, []).append(
                _LoopDefinition(
                    names,
                    _tokens(content[value.start_byte : value.end_byte])
                    if value
                    else (),
                    node.end_byte if boundary < 0 else boundary,
                )
            )
    return result, unsafe


def _roles(
    definitions: dict[bytes, list[_LoopDefinition]], unsafe: set[bytes]
) -> dict[bytes, tuple[int, int]]:
    """Resolve compatible direct and forwarding statement-prefix alternatives.

    Parameters
    ----------
    definitions : dict[bytes, list[_LoopDefinition]]
        All captured function-macro alternatives.
    unsafe : set[bytes]
        Invalidated names.

    Returns
    -------
    dict[bytes, tuple[int, int]]
        Accepted macro names mapped to fixed arity and latest availability.
        Aliases unresolved after 64 passes remain held.
    """
    if unsafe & {b"for", b"while"}:
        return {}
    accepted: dict[bytes, tuple[int, int]] = {}
    for _ in range(64):
        changed = False
        for name, alternatives in definitions.items():
            if (
                name in accepted
                or name in unsafe
                or len({len(item.parameters) for item in alternatives}) != 1
            ):
                continue
            available = 0
            valid = True
            for item in alternatives:
                available = max(available, item.available_after)
                if _loop_headers(item.tokens):
                    continue
                tokens = item.tokens
                if (
                    len(tokens) < 3
                    or tokens[0] in item.parameters
                    or tokens[0] not in accepted
                    or tokens[1] != b"("
                    or _closing(tokens, 1) != len(tokens) - 1
                    or _arity(tokens[1:]) != accepted[tokens[0]][0]
                ):
                    valid = False
                    break
                available = max(available, accepted[tokens[0]][1])
            if valid:
                accepted[name] = (len(alternatives[0].parameters), available)
                changed = True
        if not changed:
            break
    return accepted


def statement_macro_source(
    source: bytes,
    root: Node,
    parser: Parser,
    included_sources: tuple[tuple[bytes, int], ...] = (),
) -> bytes:
    """Provide equal-width loop grammar hints for proven statement invocations.

    Parameters
    ----------
    source : bytes
        Original-coordinate grammar buffer.
    root : tree_sitter.Node
        Tree for exactly that buffer.
    parser : tree_sitter.Parser
        Parser used for contained definition evidence.
    included_sources : tuple[tuple[bytes, int], ...], optional
        Captured headers with original availability boundaries.

    Returns
    -------
    bytes
        Unchanged bytes or a same-coordinate parser view. Callers must require
        a fully clean final tree and preserve projected macro-call evidence.
        Names shorter than ``while`` remain held rather than shifting offsets.
        An orphan else misread by the provider as a type cannot become clean.
    """
    candidates: list[tuple[Node, Node, Node]] = []
    for node in _nodes(root):
        if node.type != "call_expression":
            continue
        parent = node.parent
        function = node.child_by_field_name("function")
        arguments = node.child_by_field_name("arguments")
        if (
            parent is not None
            and parent.type == "expression_statement"
            and len(parent.named_children) == 1
            and parent.named_children[0] == node
            and any(child.type == ";" and child.is_missing for child in parent.children)
            and function is not None
            and function.type == "identifier"
            and function.end_byte - function.start_byte >= 5
            and arguments is not None
            and not arguments.has_error
        ):
            candidates.append((node, function, arguments))
    if not candidates:
        return source
    definitions, unsafe = _definitions(source, root, parser, included_sources)
    roles = _roles(definitions, unsafe)
    projected = bytearray(source)
    for node, function, arguments in candidates:
        role = roles.get(source[function.start_byte : function.end_byte])
        if role is None or node.start_byte < role[1]:
            continue
        actual = _arity(_tokens(source[arguments.start_byte : arguments.end_byte]))
        if actual == 0 and role[0] == 1:
            actual = 1
        if actual != role[0]:
            continue
        projected[function.start_byte : function.end_byte] = b"while".ljust(
            function.end_byte - function.start_byte
        )
    view = bytes(projected)
    if view != source and any(
        node.type == "type_identifier" and node.text == b"else"
        for node in _nodes(parser.parse(view).root_node)
    ):
        return source
    return view


def projected_statement_macro_name(node: Node, source: bytes) -> str | None:
    """Recover the written callee from a proven loop grammar projection.

    Parameters
    ----------
    node : tree_sitter.Node
        Candidate projected while statement.
    source : bytes
        Original source, separate from the parser's equal-width view.

    Returns
    -------
    str or None
        Original macro name when the parsed keyword differs from source text.
    """
    if node.type != "while_statement" or not node.children:
        return None
    keyword = node.children[0]
    if keyword.type != "while" or keyword.text != b"while":
        return None
    match = re.match(rb"[A-Za-z_][A-Za-z_0-9]*", source[node.start_byte :])
    if match is None or match[0] == b"while":
        return None
    return match[0].decode("ascii")
