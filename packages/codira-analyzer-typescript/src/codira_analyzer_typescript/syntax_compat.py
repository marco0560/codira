"""Project narrowly identified grammar gaps without changing source coordinates.

Parameters
----------
None

Returns
-------
None
    Defines parser-only projections; artifact text always uses original bytes.
"""

from __future__ import annotations

import re

from tree_sitter import Node, Parser


def _generic_import_query(node: Node, source: bytes) -> bool:
    """Recognize an import query misread as a generic-call comparison.

    Parameters
    ----------
    node : tree_sitter.Node
        Candidate import keyword.
    source : bytes
        Original source buffer.

    Returns
    -------
    bool
        Whether a typeof-import operand lies between a generic opening angle
        and the closing angle and argument list of a call.
    """
    call = node.parent
    if call is None or call.type != "call_expression":
        return False
    query = call.parent
    if query is None or query.type != "unary_expression":
        return False
    operator = query.child_by_field_name("operator")
    comparison = query.parent
    if (
        operator is None
        or operator.type != "typeof"
        or comparison is None
        or comparison.type != "binary_expression"
        or comparison.child_by_field_name("right") != query
    ):
        return False
    angle = comparison.child_by_field_name("operator")
    return (
        angle is not None
        and angle.type == "<"
        and re.match(rb"\s*>\s*\(", source[query.end_byte :]) is not None
    )


def _qualified_import_type(node: Node) -> bool:
    """Recognize a qualified literal-module import inside an erroneous type.

    Parameters
    ----------
    node : tree_sitter.Node
        Candidate import keyword.

    Returns
    -------
    bool
        Whether a single clean string argument is qualified by member names
        inside a type-annotation error, rather than a runtime import.
    """
    call = node.parent
    if call is None or call.type != "call_expression":
        return False
    arguments = call.child_by_field_name("arguments")
    if arguments is None:
        return False
    values = [child for child in arguments.named_children if child.type != "comment"]
    if len(values) != 1 or values[0].type != "string" or values[0].has_error:
        return False
    ancestor = call.parent
    qualified = False
    while ancestor is not None and ancestor.type == "member_expression":
        qualified = True
        ancestor = ancestor.parent
    return (
        qualified
        and ancestor is not None
        and ancestor.is_error
        and ancestor.parent is not None
        and ancestor.parent.type == "type_annotation"
    )


def _parenthesis_pairs(root: Node) -> dict[int, int]:
    """Match actual parenthesis tokens without reading strings as code.

    Parameters
    ----------
    root : tree_sitter.Node
        Original source root.

    Returns
    -------
    dict[int, int]
        Opening byte offsets mapped to closing token end offsets. Missing
        recovery tokens are excluded.
    """
    pending = [root]
    tokens: list[Node] = []
    while pending:
        node = pending.pop()
        pending.extend(node.children)
        if node.type in {"(", ")"} and not node.is_missing:
            tokens.append(node)
    openings: list[int] = []
    pairs: dict[int, int] = {}
    for token in sorted(tokens, key=lambda item: item.start_byte):
        if token.type == "(":
            openings.append(token.start_byte)
        elif openings:
            pairs[openings.pop()] = token.end_byte
    return pairs


def _project_decorator(
    node: Node,
    source: bytes,
    candidate: bytearray,
    parser: Parser,
    pairs: dict[int, int],
) -> None:
    """Project a separately validated empty-argument decorator IIFE.

    Parameters
    ----------
    node : tree_sitter.Node
        Erroneous decorator node.
    source : bytes
        Original source buffer.
    candidate : bytearray
        Parser buffer receiving same-width edits.
    parser : tree_sitter.Parser
        File-appropriate parser used to validate the ordinary expression.
    pairs : dict[int, int]
        Actual parenthesis token pairs.

    Returns
    -------
    None
        An IIFE is represented as a decorator call with its original function
        expression as argument. Call extraction restores the original callee.
    """
    prefix = re.match(rb"@\s*(\()\s*(\()", source[node.start_byte :])
    if prefix is None:
        return
    first = node.start_byte + prefix.start(1)
    second = node.start_byte + prefix.start(2)
    end = pairs.get(first)
    middle = pairs.get(second)
    if (
        end is None
        or middle is None
        or middle >= end
        or source[middle : end - 1].strip() != b"()"
    ):
        return
    probe = parser.parse(b"const _Decorator = " + source[first:end] + b";\n")
    if probe.root_node.has_error or has_argument_holes(probe.root_node):
        return
    candidate[first] = ord("_")
    for offset in range(middle, end):
        if candidate[offset] not in (ord("\n"), ord("\r")):
            candidate[offset] = ord(" ")


def project_known_syntax(root: Node, source: bytes, parser: Parser) -> bytes:
    """Project supported syntax only at observed grammar-error structures.

    Parameters
    ----------
    root : tree_sitter.Node
        Original parsed root containing unresolved errors.
    source : bytes
        Original UTF-8 source buffer.
    parser : tree_sitter.Parser
        File-appropriate parser for validating decorator expressions.

    Returns
    -------
    bytes
        Same-length parser buffer. The caller must retain the original tree
        unless the complete candidate has no unresolved errors.

    Notes
    -----
    JSX text ampersands and optional property names receive same-width token
    aliases. The unsupported override modifier ordering is normalized without
    changing any declaration name. Generic typeof-import queries use a neutral
    callee spelling to select the type-query grammar branch. These aliases must
    never be used to render artifacts or resolve runtime import calls.
    Qualified literal-module import types use an opaque namespace projection;
    original module text remains in source-based type signatures.
    Parenthesized decorator IIFEs preserve the complete function expression;
    their synthetic wrapper is decoded back to the original callee and position.
    """
    candidate = bytearray(source)
    pairs: dict[int, int] | None = None
    pending = [root]
    while pending:
        node = pending.pop()
        pending.extend(node.children)
        parent = node.parent
        if node.type == "decorator" and node.has_error:
            if pairs is None:
                pairs = _parenthesis_pairs(root)
            _project_decorator(node, source, candidate, parser, pairs)
        elif node.is_error and parent is not None and parent.type == "jsx_element":
            for child in node.children:
                if (
                    child.type == "&"
                    and source[child.start_byte : child.end_byte] == b"&"
                ):
                    candidate[child.start_byte] = ord("_")
        elif node.is_error and parent is not None and parent.type == "union_type":
            children = node.children
            if (
                len(children) >= 4
                and children[0].type == "identifier"
                and children[1].type == "?"
                and children[2].type == ":"
                and source[children[0].start_byte : children[0].end_byte].startswith(
                    b"in"
                )
            ):
                candidate[children[0].start_byte] = ord("_")
        elif (
            node.type == "override_modifier"
            and node.prev_sibling is not None
            and node.prev_sibling.type == "abstract"
            and re.match(rb"\s+readonly\b", source[node.end_byte :]) is not None
        ):
            candidate[node.start_byte : node.end_byte] = b" " * (
                node.end_byte - node.start_byte
            )
        elif node.type == "import" and _generic_import_query(node, source):
            candidate[node.start_byte : node.end_byte] = b"_mport"
        elif node.type == "import" and _qualified_import_type(node):
            candidate[node.start_byte : node.end_byte] = b"_mport"
            call = node.parent
            assert call is not None
            for offset in range(node.end_byte, call.end_byte):
                if candidate[offset] not in (ord("\n"), ord("\r")):
                    candidate[offset] = ord(" ")
    return bytes(candidate)


def has_argument_holes(root: Node) -> bool:
    """Reject empty argument slots tolerated by the bundled grammar.

    Parameters
    ----------
    root : tree_sitter.Node
        Candidate projected syntax tree.

    Returns
    -------
    bool
        Whether a call argument list starts with a comma or contains adjacent
        commas. A trailing comma after a real argument remains permitted.
    """
    pending = [root]
    while pending:
        node = pending.pop()
        pending.extend(node.named_children)
        if node.type != "arguments":
            continue
        needs_argument = True
        for child in node.children:
            if child.type in {"(", ")", "comment"}:
                continue
            if child.type == ",":
                if needs_argument:
                    return True
                needs_argument = True
            else:
                needs_argument = False
    return False
