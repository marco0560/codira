"""Coordinate-preserving views for specific Rust grammar omissions.

Parameters
----------
None

Returns
-------
None
    Defines syntax-only recovery helpers; original source owns all artifacts.
"""

from __future__ import annotations

from bisect import bisect_right

from tree_sitter import Node, Parser

_COMMENTS = frozenset({"line_comment", "block_comment"})
_TOKEN_TREES = frozenset({"token_tree", "token_tree_pattern"})


def _nodes(root: Node) -> list[Node]:
    """Collect provider nodes in source order.

    Parameters
    ----------
    root : tree_sitter.Node
        Root to traverse without retaining parser state.

    Returns
    -------
    list[tree_sitter.Node]
        Depth-first nodes including anonymous punctuation.
    """
    result: list[Node] = []
    pending = [root]
    while pending:
        node = pending.pop()
        result.append(node)
        pending.extend(reversed(node.children))
    return result


def _inside_token_tree(node: Node) -> bool:
    """Return whether a node belongs to an opaque Rust token tree.

    Parameters
    ----------
    node : tree_sitter.Node
        Candidate recovery node.

    Returns
    -------
    bool
        Whether a token-tree ancestor contains the candidate.
    """
    ancestor = node.parent
    while ancestor is not None:
        if ancestor.type in _TOKEN_TREES:
            return True
        ancestor = ancestor.parent
    return False


def _tokens(root: Node) -> list[Node]:
    """Collect non-comment tokens while keeping literals and token trees opaque.

    Parameters
    ----------
    root : tree_sitter.Node
        Original parse root or recovery subtree.

    Returns
    -------
    list[tree_sitter.Node]
        Source-ordered lexical leaves with opaque literal/token-tree units.
    """
    leaves: list[Node] = []
    pending = [root]
    while pending:
        node = pending.pop()
        if node.type in _COMMENTS or node.is_missing:
            continue
        if not node.children or node.type in (
            _TOKEN_TREES | {"string_literal", "raw_string_literal", "char_literal"}
        ):
            leaves.append(node)
        else:
            pending.extend(reversed(node.children))
    return leaves


def _attribute_ranges(
    parser: Parser, nodes: list[Node], source: bytes
) -> list[tuple[int, int]]:
    """Find complete outer attributes decorating delimited components.

    Parameters
    ----------
    parser : tree_sitter.Parser
        Parser used to validate complete standalone attribute syntax.
    nodes : list[tree_sitter.Node]
        Provider nodes from the original partial parse.
    source : bytes
        Original source owning all byte coordinates.

    Returns
    -------
    list[tuple[int, int]]
        Half-open attribute ranges following opening delimiters or commas.

    Notes
    -----
    Only complete, independently parsed outer attributes are eligible. Token
    trees, inner attributes, comments and attributes without a following
    component remain untouched. Attribute predicates are never evaluated.
    """
    leaves = _tokens(nodes[0])
    ranges: list[tuple[int, int]] = []
    accepted_ends: set[int] = set()
    for index, node in enumerate(leaves):
        if source[node.start_byte : node.end_byte] != b"#" or index == 0:
            continue
        if ranges and node.start_byte < ranges[-1][1]:
            continue
        if index + 1 == len(leaves):
            continue
        opening = leaves[index + 1]
        if source[opening.start_byte : opening.end_byte] != b"[":
            continue
        previous_node = leaves[index - 1]
        previous = source[previous_node.start_byte : previous_node.end_byte]
        if previous not in {b"(", b"{", b"[", b","} and (
            previous_node.end_byte not in accepted_ends
        ):
            continue
        depth = 0
        closing_index: int | None = None
        for following_index in range(index + 1, len(leaves)):
            token = leaves[following_index]
            text = source[token.start_byte : token.end_byte]
            if text == b"[":
                depth += 1
            elif text == b"]":
                depth -= 1
                if depth == 0:
                    closing_index = following_index
                    break
        if closing_index is None or closing_index + 1 == len(leaves):
            continue
        after = leaves[closing_index + 1]
        following = source[after.start_byte : after.end_byte]
        if following in {b")", b"}", b"]", b",", b";"}:
            continue
        end = leaves[closing_index].end_byte
        attribute = source[node.start_byte : end]
        probe = parser.parse(attribute + b"\nfn __codira_attribute_probe() {}")
        children = probe.root_node.named_children
        if (
            probe.root_node.has_error
            or len(children) != 2
            or children[0].type != "attribute_item"
            or children[0].end_byte != len(attribute)
            or children[1].type != "function_item"
        ):
            continue
        ranges.append((node.start_byte, end))
        accepted_ends.add(end)
    return ranges


def _closure_ranges(
    parser: Parser, nodes: list[Node], source: bytes
) -> list[tuple[int, int]]:
    """Find trailing closure commas using isolated parameter-list probes.

    Parameters
    ----------
    parser : tree_sitter.Parser
        Parser used for closure signature validation.
    nodes : list[tree_sitter.Node]
        Nodes of the original partial tree.
    source : bytes
        Original source owning the node coordinates.

    Returns
    -------
    list[tuple[int, int]]
        Trailing comma ranges whose removal leaves a complete closure header.
    """
    ranges: list[tuple[int, int]] = []
    errors: list[tuple[int, int]] = []
    for node in nodes:
        if not node.is_error:
            continue
        if errors and node.start_byte <= errors[-1][1]:
            errors[-1] = (errors[-1][0], max(errors[-1][1], node.end_byte))
        else:
            errors.append((node.start_byte, node.end_byte))
    error_starts = [start for start, _ in errors]
    tokens = _tokens(nodes[0])
    for index, (comma, closing) in enumerate(zip(tokens, tokens[1:])):
        if (
            source[comma.start_byte : comma.end_byte] != b","
            or source[closing.start_byte : closing.end_byte] != b"|"
        ):
            continue
        error_index = bisect_right(error_starts, closing.start_byte) - 1
        if error_index < 0 or closing.start_byte >= errors[error_index][1]:
            continue
        for opening_index in range(index - 1, -1, -1):
            opening = tokens[opening_index]
            if source[opening.start_byte : opening.end_byte] != b"|":
                continue
            if opening_index:
                before = tokens[opening_index - 1]
                prefix = source[before.start_byte : before.end_byte]
                if prefix not in {b"=", b"(", b",", b"{", b"move", b"async", b"return"}:
                    continue
            parameters = source[opening.start_byte : comma.start_byte] + b"|"
            probe = parser.parse(b"fn __probe(){let _=" + parameters + b"{};}")
            if not probe.root_node.has_error:
                ranges.append((comma.start_byte, comma.end_byte))
                break
    return ranges


def _turbofish_ranges(
    parser: Parser, nodes: list[Node], source: bytes
) -> list[tuple[int, int]]:
    """Recognize nested type-path separators inside a recovered type argument.

    Parameters
    ----------
    parser : tree_sitter.Parser
        Parser used for complete type-alias probes.
    nodes : list[tree_sitter.Node]
        Original provider nodes.
    source : bytes
        Original source owning every node coordinate.

    Returns
    -------
    list[tuple[int, int]]
        Inner optional path separators validated as one complete type.
    """
    ranges: list[tuple[int, int]] = []
    for node in nodes:
        text = source[node.start_byte : node.end_byte]
        if node.type == "type_arguments" and node.has_error:
            candidates = [
                (child.start_byte, child.start_byte + 2)
                for child in node.named_children
                if child.is_error
                and source[child.start_byte : child.end_byte].startswith(b"::<")
            ]
            if candidates:
                projected = bytearray(text)
                for start, end in candidates:
                    projected[start - node.start_byte : end - node.start_byte] = (
                        b" " * (end - start)
                    )
                probe = parser.parse(b"type __Probe=__Owner" + bytes(projected) + b";")
                if not probe.root_node.has_error:
                    ranges.extend(candidates)
        if not node.is_error or not text.startswith(b"::<"):
            continue
        tokens = _tokens(node)
        candidates = [
            (left.start_byte, left.end_byte)
            for left, right in zip(tokens, tokens[1:])
            if left.start_byte >= node.start_byte + 3
            and source[left.start_byte : left.end_byte] == b"::"
            and source[right.start_byte : right.end_byte] == b"<"
        ]
        if not candidates:
            continue
        projected = bytearray(text[3:])
        for start, end in candidates:
            projected[start - node.start_byte - 3 : end - node.start_byte - 3] = (
                b" " * (end - start)
            )
        probe = parser.parse(b"type __Probe=__Owner<" + bytes(projected) + b">;")
        children = probe.root_node.named_children
        if (
            not probe.root_node.has_error
            and len(children) == 1
            and children[0].type == "type_item"
        ):
            ranges.extend(candidates)
    return ranges


def rust_parse_root(parser: Parser, source: bytes) -> Node:
    """Parse Rust using conservative views for recognized grammar gaps.

    Parameters
    ----------
    parser : tree_sitter.Parser
        Isolated parser configured for Rust.
    source : bytes
        Original source; extraction must continue to read these bytes.

    Returns
    -------
    tree_sitter.Node
        Original root when clean or recovery fails; otherwise a clean view
        retaining every original byte and newline coordinate.

    Notes
    -----
    Tilde punctuation inside token trees is represented by accepted punctuation.
    Lifetime-first ``dyn`` bounds and negative integer const arguments retain
    their original artifact text. Complete outer attributes at delimited
    component boundaries become transparent. Closure trailing commas and inner
    type-path turbofish separators require complete isolated header/type probes.
    No macro expansion, conditional selection, type checking or compiler
    invocation is performed. All remaining errors discard the complete view.
    """
    original = parser.parse(source).root_node
    if not original.has_error:
        return original
    nodes = _nodes(original)
    projected = bytearray(source)
    ranges = _attribute_ranges(parser, nodes, source)
    ranges.extend(_closure_ranges(parser, nodes, source))
    ranges.extend(_turbofish_ranges(parser, nodes, source))
    for node in nodes:
        if (
            node.type == "dynamic_type"
            and node.has_error
            and node.parent is not None
            and node.parent.type == "bounded_type"
            and source[node.start_byte : node.start_byte + 3] == b"dyn"
        ):
            lifetime = source[node.start_byte + 3 : node.end_byte].strip()
            if lifetime.startswith(b"'"):
                probe = parser.parse(b"fn __probe<" + lifetime + b">(){}")
                if not probe.root_node.has_error:
                    ranges.append((node.start_byte, node.start_byte + 3))
        if not node.is_error:
            continue
        text = source[node.start_byte : node.end_byte]
        if b"~" in text and not text.strip(b"~ \t\r\n"):
            if _inside_token_tree(node):
                for offset in range(node.start_byte, node.end_byte):
                    if source[offset] == ord("~"):
                        projected[offset] = ord("!")
            continue
        parent = node.parent
        following = node.next_named_sibling
        if parent is None or parent.type != "type_arguments" or following is None:
            continue
        if text == b"-" and following.type == "integer_literal":
            ranges.append((node.start_byte, node.end_byte))
        elif (
            text == b"dyn"
            and following.type == "bounded_type"
            and not following.has_error
            and following.named_children
        ):
            first = following.named_children[0]
            while first.type == "bounded_type" and first.named_children:
                first = first.named_children[0]
            if first.type == "lifetime":
                ranges.append((node.start_byte, node.end_byte))
    for start, end in ranges:
        for offset in range(start, end):
            if source[offset] not in (ord("\n"), ord("\r")):
                projected[offset] = ord(" ")
    if projected == source:
        return original
    recovered = parser.parse(bytes(projected)).root_node
    return original if recovered.has_error else recovered
