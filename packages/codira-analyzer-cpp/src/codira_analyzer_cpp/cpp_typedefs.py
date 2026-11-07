"""Identify written typedef names without entering parameter or type subtrees.

Parameters
----------
None

Returns
-------
None
    Supplies declaration-name traversal for module and class typedefs.
"""

from __future__ import annotations

from collections.abc import Sequence

from .cpp_projection import SyntaxNode


def _typedef_name_nodes(node: SyntaxNode) -> tuple[SyntaxNode, ...]:
    """Follow each typedef declarator to its written alias identifier.

    Parameters
    ----------
    node : SyntaxNode
        Type-definition node with one or more declarator fields.

    Returns
    -------
    tuple[SyntaxNode, ...]
        Alias names in source order, excluding names in types or parameters.
    """
    names: list[SyntaxNode] = []
    children: Sequence[SyntaxNode] = node.children
    for index, child in enumerate(children):
        if node.field_name_for_child(index) != "declarator":
            continue
        current: SyntaxNode | None = child
        while current is not None:
            if current.type in {"type_identifier", "identifier", "field_identifier"}:
                names.append(current)
                break
            nested = current.child_by_field_name("declarator")
            if nested is None and current.type in {
                "parenthesized_declarator",
                "reference_declarator",
            }:
                nested = next(
                    (
                        item
                        for item in current.named_children
                        if item.type.endswith("_declarator")
                        or item.type
                        in {"type_identifier", "identifier", "field_identifier"}
                    ),
                    None,
                )
            current = nested
    return tuple(names)
