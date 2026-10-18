"""Recover source-local annotation macros without moving source coordinates.

Parameters
----------
None

Returns
-------
None
    Provides a conservative C++ syntax projection, not a build preprocessor.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass, field

from tree_sitter import Node, Parser

from .cpp_syntax import _new_parser

_IDENTIFIER = re.compile(rb"\b[A-Za-z_][A-Za-z_0-9]*\b")
_UNDEF = re.compile(rb"#\s*undef\s+([A-Za-z_][A-Za-z_0-9]*)")
_OPAQUE_NODES = frozenset(
    {
        "preproc_def",
        "preproc_function_def",
        "preproc_call",
        "preproc_include",
        "comment",
        "string_literal",
        "raw_string_literal",
        "char_literal",
    }
)
_ANNOTATION_NODES = frozenset(
    {"attribute_declaration", "attribute_specifier", "ms_declspec_modifier"}
)
_IDENTIFIER_NODES = frozenset(
    {
        "identifier",
        "type_identifier",
        "namespace_identifier",
        "field_identifier",
        "statement_identifier",
    }
)


@dataclass
class _AnnotationDefinitions:
    """Accumulate replacements, availability and invalidating directives.

    Parameters
    ----------
    replacements : dict[bytes, list[bytes]], optional
        All observed object replacement alternatives by macro name.
    first_offsets : dict[bytes, int], optional
        Earliest source definition or reaching include boundary.
    unsafe : set[bytes], optional
        Names with function-like definitions or undef directives.

    Returns
    -------
    None
        Mutable collection state local to one parser call.
    """

    replacements: dict[bytes, list[bytes]] = field(default_factory=dict)
    first_offsets: dict[bytes, int] = field(default_factory=dict)
    unsafe: set[bytes] = field(default_factory=set)


def _nodes(root: Node) -> Iterator[Node]:
    """Visit a tree without Python recursion limits.

    Parameters
    ----------
    root : tree_sitter.Node
        Root of the subtree to visit.

    Returns
    -------
    collections.abc.Iterator[tree_sitter.Node]
        Nodes in deterministic depth-first order.
    """
    pending = [root]
    while pending:
        node = pending.pop()
        yield node
        pending.extend(reversed(node.children))


def _is_annotation(value: bytes, parser: Parser) -> bool:
    """Accept an empty replacement or parsed attributes before a probe.

    Parameters
    ----------
    value : bytes
        Object macro replacement after known annotation aliases are blanked.
    parser : tree_sitter.Parser
        Package-local C++ parser.

    Returns
    -------
    bool
        Whether the replacement adds only attributes to an unchanged int probe.
    """
    source = value + b" int __codira_annotation_probe();"
    root = parser.parse(source).root_node
    if root.has_error or len(root.named_children) != 1:
        return False
    declaration = root.named_children[0]
    if declaration.type != "declaration":
        return False
    type_node = declaration.child_by_field_name("type")
    declarator = declaration.child_by_field_name("declarator")
    if (
        type_node is None
        or type_node.type != "primitive_type"
        or type_node.start_byte != len(value) + 1
        or declarator is None
        or declarator.type != "function_declarator"
    ):
        return False
    return all(
        child == type_node or child == declarator or child.type in _ANNOTATION_NODES
        for child in declaration.named_children
    )


def _annotation_definitions(
    source: bytes,
    root: Node,
    parser: Parser,
    included_sources: tuple[tuple[bytes, int], ...] = (),
) -> dict[bytes, int]:
    """Resolve source-backed object macros with compatible replacements.

    Parameters
    ----------
    source : bytes
        Original file bytes.
    root : tree_sitter.Node
        Unmodified parse tree.
    parser : tree_sitter.Parser
        Parser used to validate replacement syntax.
    included_sources : tuple[tuple[bytes, int], ...], optional
        Captured header bytes and earliest source include-end offsets. Their
        definitions cannot license annotation uses preceding the include.

    Returns
    -------
    dict[bytes, int]
        Eligible macro names and the earliest safe use offset. Function macros,
        undefined names and conflicting replacements are excluded file-wide.
    """
    state = _AnnotationDefinitions()
    definitions = state.replacements
    first_offsets = state.first_offsets
    unsafe = state.unsafe
    inputs = [(source, root, None)] + [
        (content, parser.parse(content).root_node, boundary)
        for content, boundary in included_sources
    ]
    for content, tree, boundary in inputs:
        _collect_annotation_definitions(content, tree, boundary, state)
    accepted: dict[bytes, int] = {}
    changed = True
    while changed:
        changed = False
        for name, alternatives in definitions.items():
            if name in accepted or name in unsafe:
                continue
            expanded = [
                _IDENTIFIER.sub(
                    lambda match: (
                        b" " * len(match[0]) if match[0] in accepted else match[0]
                    ),
                    value,
                )
                for value in alternatives
            ]
            if not all(_is_annotation(value, parser) for value in expanded):
                continue
            dependencies = {
                token
                for value in alternatives
                for token in _IDENTIFIER.findall(value)
                if token in accepted
            }
            accepted[name] = (
                max(
                    first_offsets[name],
                    *(accepted[token] for token in dependencies),
                )
                if dependencies
                else first_offsets[name]
            )
            changed = True
    return accepted


def _collect_annotation_definitions(
    source: bytes,
    root: Node,
    boundary: int | None,
    definitions: _AnnotationDefinitions,
) -> None:
    """Collect alternatives and invalidating directives from one source input.

    Parameters
    ----------
    source : bytes
        Captured source or header bytes.
    root : tree_sitter.Node
        Unmodified parse tree for these bytes.
    boundary : int | None
        Source include-end offset for a header, or None for the source itself.
    definitions : _AnnotationDefinitions
        Mutable alternatives, earliest offsets and unsafe names accumulated
        across all source inputs.

    Returns
    -------
    None
        Updates the supplied collections without expanding declarations.
    """
    for node in _nodes(root):
        if node.type in {"preproc_def", "preproc_function_def"}:
            name_node = node.child_by_field_name("name")
            if name_node is None:
                continue
            token = source[name_node.start_byte : name_node.end_byte]
            if node.type == "preproc_function_def":
                definitions.unsafe.add(token)
                continue
            value = node.child_by_field_name("value")
            replacement = source[value.start_byte : value.end_byte] if value else b""
            replacement = re.sub(rb"\\\r?\n", b" ", replacement)
            definitions.replacements.setdefault(token, []).append(replacement)
            offset = node.end_byte if boundary is None else boundary
            definitions.first_offsets[token] = min(
                definitions.first_offsets.get(token, offset), offset
            )
        elif node.type == "preproc_call":
            match = _UNDEF.match(source[node.start_byte : node.end_byte])
            if match is not None:
                definitions.unsafe.add(match[1])


def _hash_lines(source: bytes, root: Node) -> tuple[tuple[int, int], ...]:
    """Protect logical lines containing real preprocessing hash tokens.

    Parameters
    ----------
    source : bytes
        Source before annotation replacement.
    root : tree_sitter.Node
        Tree supplying literal and comment spans.

    Returns
    -------
    tuple[tuple[int, int], ...]
        Logical line ranges where deleting an identifier could invent a directive.
        Escaped newlines join physical lines; hashes in literals/comments do not.
    """
    opaque = [
        (node.start_byte, node.end_byte)
        for node in _nodes(root)
        if node.type
        in {"comment", "string_literal", "raw_string_literal", "char_literal"}
    ]
    protected: set[tuple[int, int]] = set()
    for match in re.finditer(rb"#", source):
        offset = match.start()
        if any(start <= offset < end for start, end in opaque):
            continue
        start = source.rfind(b"\n", 0, offset) + 1
        while start:
            tail = start - 2
            if tail >= 0 and source[tail] == 13:
                tail -= 1
            if tail < 0 or source[tail] != 92:
                break
            start = source.rfind(b"\n", 0, tail) + 1
        end = source.find(b"\n", offset)
        while end >= 0:
            tail = end - 1
            if tail >= 0 and source[tail] == 13:
                tail -= 1
            if tail < 0 or source[tail] != 92:
                break
            end = source.find(b"\n", end + 1)
        protected.add((start, len(source) if end < 0 else end))
    return tuple(sorted(protected))


def _parse_cpp_source(
    source: bytes, *, included_sources: tuple[tuple[bytes, int], ...] = ()
) -> Node:
    """Parse C++ with a coordinate-preserving source-backed annotation recovery.

    Parameters
    ----------
    source : bytes
        Original C++ file bytes, also used later for artifact extraction.
    included_sources : tuple[tuple[bytes, int], ...], optional
        Captured header bytes and earliest source include-end offsets. Callers
        must bind these external analysis inputs to incremental reuse identity.

    Returns
    -------
    tree_sitter.Node
        Original root unless replacing known annotation uses produces a wholly
        clean tree. Definitions, directives, comments and literals are retained.
    """
    parser = _new_parser()
    original = parser.parse(source).root_node
    if not original.has_error:
        return original
    annotations = _annotation_definitions(source, original, parser, included_sources)
    if not annotations:
        return original
    protected = _hash_lines(source, original)
    projected = bytearray(source)
    pending = [original]
    while pending:
        node = pending.pop()
        if node.type in _OPAQUE_NODES:
            continue
        if node.type in _IDENTIFIER_NODES:
            token = source[node.start_byte : node.end_byte]
            after_definition = annotations.get(token)
            if (
                after_definition is not None
                and node.start_byte >= after_definition
                and not any(start <= node.start_byte < end for start, end in protected)
            ):
                projected[node.start_byte : node.end_byte] = b" " * len(token)
        condition = (
            node.child_by_field_name("condition")
            if node.type.startswith("preproc_")
            else None
        )
        name = (
            node.child_by_field_name("name")
            if node.type.startswith("preproc_")
            else None
        )
        pending.extend(
            child for child in node.children if child != condition and child != name
        )
    if projected == source:
        return original
    recovered = parser.parse(bytes(projected)).root_node
    return original if recovered.has_error else recovered


def _original_declaration_start(node: Node, source: bytes) -> int:
    """Recover a leading annotation omitted from a projected node's span.

    Parameters
    ----------
    node : tree_sitter.Node
        Declaration or enclosing template whose start may follow blanked macros.
    source : bytes
        Original source used for signatures and line coordinates.

    Returns
    -------
    int
        Original declaration start, extended only over a gap that the recovered
        tree treats entirely as whitespace. Siblings and comments bound the gap.
    """
    parent = node.parent
    if parent is None:
        return node.start_byte
    previous = node.prev_sibling
    lower = previous.end_byte if previous is not None else parent.start_byte
    gap = source[lower : node.start_byte]
    if not gap.strip():
        return node.start_byte
    projected = parent.text
    if projected is None:
        return node.start_byte
    projected_gap = projected[
        lower - parent.start_byte : node.start_byte - parent.start_byte
    ]
    if projected_gap.strip():
        return node.start_byte
    return lower + len(gap) - len(gap.lstrip())
