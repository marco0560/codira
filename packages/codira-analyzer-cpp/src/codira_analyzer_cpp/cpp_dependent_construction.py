"""Adapt dependent construction expressions without rewriting type declarations.

Parameters
----------
None

Returns
-------
None
    Supplies equal-width syntax views for a provider grammar gap.
"""

from __future__ import annotations

import re
from collections.abc import Iterator, Sequence

from tree_sitter import Parser

from .cpp_projection import SyntaxNode as Node


def _nodes(root: Node) -> Iterator[Node]:
    """Visit provider nodes without recursion.

    Parameters
    ----------
    root : SyntaxNode
        Root of the syntax view.

    Returns
    -------
    collections.abc.Iterator[SyntaxNode]
        Nodes in provider order.
    """
    pending = [root]
    while pending:
        node = pending.pop()
        yield node
        pending.extend(reversed(node.children))


def _type_context(node: Node, offset: int, *, proposed: bool) -> bool:
    """Protect declarations and unevaluated type contexts from expression repair.

    Parameters
    ----------
    node : SyntaxNode
        Node containing the keyword or proposed construction.
    offset : int
        Original source position.
    proposed : bool
        Whether the node comes from the candidate expression tree.

    Returns
    -------
    bool
        Whether the position must retain its original type spelling.
    """
    in_value = False
    current: Node | None = node
    while current is not None:
        if current.type in {
            "init_declarator",
            "optional_parameter_declaration",
            "field_declaration",
        }:
            for field in ("value", "default_value"):
                value = current.child_by_field_name(field)
                if value is not None and value.start_byte <= offset < value.end_byte:
                    in_value = True
        if current.type in {
            "sizeof_expression",
            "alignof_expression",
            "decltype",
            "type_descriptor",
            "template_argument_list",
            "alias_declaration",
            "type_definition",
        }:
            return True
        if not in_value and current.type in {"declaration", "field_declaration"}:
            return True
        if (
            proposed
            and not in_value
            and current.type
            in {"parameter_declaration", "optional_parameter_declaration"}
        ):
            return True
        current = current.parent
    return False


def _dependent_construction_source(
    source: bytes,
    root: Node,
    parser: Parser,
    *,
    protected_ranges: Sequence[tuple[int, int]] = (),
    keyword_overridden: bool = False,
) -> bytes:
    """Mask only typename tokens proven to belong to dependent constructions.

    Parameters
    ----------
    source : bytes
        Coordinate-aligned source bytes.
    root : SyntaxNode
        Partial provider tree supplying protected syntax contexts.
    parser : tree_sitter.Parser
        Package-local C++ parser.
    protected_ranges : collections.abc.Sequence[tuple[int, int]], optional
        Additional directive or literal spans that cannot be rewritten.
    keyword_overridden : bool, optional
        Whether captured directives redefine or undefine the keyword.

    Returns
    -------
    bytes
        Equal-width expression view with declarations and type contexts intact.
    """
    if keyword_overridden or b"typename" not in source or not root.has_error:
        return source
    nodes = tuple(_nodes(root))
    protected = [*protected_ranges]
    protected.extend(
        (node.start_byte, node.end_byte)
        for node in nodes
        if node.type
        in {
            "comment",
            "string_literal",
            "raw_string_literal",
            "char_literal",
            "preproc_def",
            "preproc_function_def",
            "preproc_call",
            "preproc_include",
        }
    )
    candidates: dict[int, tuple[int, int]] = {}
    for match in re.finditer(rb"\btypename\b", source):
        if any(a <= match.start() < b for a, b in protected):
            continue
        owner = min(
            (n for n in nodes if n.start_byte <= match.start() < n.end_byte),
            key=lambda n: n.end_byte - n.start_byte,
        )
        if _type_context(owner, match.start(), proposed=False):
            continue
        after = match.end()
        while after < len(source):
            if source[after] in b" \t\r\n\f":
                after += 1
                continue
            comment_end = next(
                (
                    n.end_byte
                    for n in nodes
                    if n.type == "comment" and n.start_byte == after
                ),
                None,
            )
            if comment_end is None:
                break
            after = comment_end
        candidates[after] = (match.start(), match.end())
    if not candidates:
        return source
    trial = bytearray(source)
    for a, b in candidates.values():
        trial[a:b] = b" " * (b - a)
    selected: set[tuple[int, int]] = set()
    for node in _nodes(parser.parse(bytes(trial)).root_node):
        if node.type not in {"call_expression", "compound_literal_expression"}:
            continue
        target = node.child_by_field_name(
            "function" if node.type == "call_expression" else "type"
        )
        if target is None or target.type != "qualified_identifier":
            continue
        candidate = candidates.get(target.start_byte)
        if candidate is not None and not _type_context(
            node, target.start_byte, proposed=True
        ):
            selected.add(candidate)
    projected = bytearray(source)
    for a, b in selected:
        projected[a:b] = b" " * (b - a)
    return bytes(projected)
