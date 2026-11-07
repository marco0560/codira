"""Recover explicitly named symbolic member operators in type expressions.

Parameters
----------
None

Returns
-------
None
    Defines a narrowly scoped, source-coordinate-preserving syntax adapter.
"""

from __future__ import annotations

from collections.abc import Iterator

from tree_sitter import Parser

from .cpp_projection import SyntaxNode as Node, _source_projection

_SYMBOLIC_OPERATORS = frozenset(
    {
        b"+",
        b"-",
        b"*",
        b"/",
        b"%",
        b"^",
        b"&",
        b"|",
        b"~",
        b"!",
        b"=",
        b"<",
        b">",
        b"+=",
        b"-=",
        b"*=",
        b"/=",
        b"%=",
        b"^=",
        b"&=",
        b"|=",
        b"<<=",
        b">>=",
        b"==",
        b"!=",
        b"<=",
        b">=",
        b"<=>",
        b"&&",
        b"||",
        b"++",
        b"--",
        b",",
        b"->*",
        b"->",
        b"()",
        b"[]",
    }
)


def _nodes(root: Node) -> Iterator[Node]:
    """Visit one syntax subtree in deterministic depth-first order.

    Parameters
    ----------
    root : SyntaxNode
        Root node whose descendants are visited.

    Returns
    -------
    collections.abc.Iterator[SyntaxNode]
        Root followed by its descendants in provider order.
    """
    pending = [root]
    while pending:
        node = pending.pop()
        yield node
        pending.extend(reversed(node.children))


def _inside_decltype(node: Node) -> bool:
    """Check whether a syntax node belongs to a decltype expression.

    Parameters
    ----------
    node : SyntaxNode
        Candidate diagnostic node.

    Returns
    -------
    bool
        Whether a decltype node encloses the candidate.
    """
    parent = node.parent
    while parent is not None:
        if parent.type == "decltype":
            return True
        parent = parent.parent
    return False


def _operator_replacements(source: bytes, root: Node) -> list[tuple[int, int, bytes]]:
    """Find complete member-operator diagnostics licensed for adaptation.

    Parameters
    ----------
    source : bytes
        Coordinate-aligned source parsed into root.
    root : SyntaxNode
        Provider tree containing the original diagnostics.

    Returns
    -------
    list[tuple[int, int, bytes]]
        Equal-width identifier replacements for recognized operator tokens.
        An empty list means the tree provides no supported, complete candidate.
    """
    replacements: list[tuple[int, int, bytes]] = []
    for error in _nodes(root):
        if not error.is_error or not _inside_decltype(error):
            continue
        parent = error.parent
        name_nodes = [
            child for child in error.named_children if child.type == "operator_name"
        ]
        if (
            parent is None
            or parent.type != "call_expression"
            or parent.child_by_field_name("function") is None
            or parent.child_by_field_name("arguments") is None
            or len(name_nodes) != 1
        ):
            continue
        name = name_nodes[0]
        spelling = source[name.start_byte : name.end_byte]
        if not spelling.startswith(b"operator"):
            continue
        operator = spelling[len(b"operator") :]
        if operator not in _SYMBOLIC_OPERATORS or name.end_byte != error.end_byte:
            continue
        prefix = source[error.start_byte : name.start_byte]
        if prefix not in {b".", b"->"}:
            continue
        start = name.end_byte - len(operator)
        replacements.append((start, name.end_byte, b"_" * len(operator)))
    return replacements


def _member_operator_syntax(
    source: bytes,
    root: Node,
    parser: Parser,
    *,
    keyword_overridden: bool,
) -> Node | None:
    """Parse only fully recoverable symbolic member operators in decltype.

    Parameters
    ----------
    source : bytes
        Coordinate-aligned parser input; its length and line endings are retained.
    root : SyntaxNode
        Original provider tree for source.
    parser : tree_sitter.Parser
        C++ parser used to validate the projected candidate.
    keyword_overridden : bool
        Whether source or captured headers define or undefine the operator
        keyword spelling, making the syntax adaptation ambiguous.

    Returns
    -------
    SyntaxNode or None
        Clean projected syntax with physical operator spellings and original
        coordinates, or None when any diagnostic remains or proof is absent.
    """
    if not root.has_error or keyword_overridden:
        return None
    replacements = _operator_replacements(source, root)
    if not replacements:
        return None
    projection = _source_projection(source, replacements)
    recovered = parser.parse(projection.expanded).root_node
    if recovered.has_error:
        return None
    return projection.tree(recovered)
