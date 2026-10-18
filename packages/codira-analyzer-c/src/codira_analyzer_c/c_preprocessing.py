"""Recover source-local annotation macros without moving source coordinates.

Parameters
----------
None

Returns
-------
None
    Provides a conservative C syntax projection, not a build preprocessor.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass, field

from tree_sitter import Node, Parser


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
        Earliest source definition end offset.
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
        Package-local C parser.

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
    _collect_annotation_definitions(source, root, state)
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
    definitions: _AnnotationDefinitions,
) -> None:
    """Collect alternatives and invalidating directives from one source input.

    Parameters
    ----------
    source : bytes
        Original C source bytes.
    root : tree_sitter.Node
        Unmodified parse tree for these bytes.
    definitions : _AnnotationDefinitions
        Mutable alternatives, earliest offsets and unsafe names accumulated
        for this source input.

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
            offset = node.end_byte
            definitions.first_offsets[token] = min(
                definitions.first_offsets.get(token, offset), offset
            )
        elif node.type == "preproc_call":
            match = _UNDEF.match(source[node.start_byte : node.end_byte])
            if match is not None:
                definitions.unsafe.add(match[1])


def _c_language_source(source: bytes, root: Node) -> bytes:
    """Blank positive C++-only branches in a C translation unit.

    Parameters
    ----------
    source : bytes
        Original C source bytes.
    root : tree_sitter.Node
        Unmodified tree supplying opaque comment, literal and macro spans.

    Returns
    -------
    bytes
        Same-length C source with line endings and guard directives retained.
        Source definitions or undefinitions of __cplusplus prevent inference.
    """
    opaque: list[tuple[int, int]] = []
    for node in _nodes(root):
        if node.type in {"preproc_def", "preproc_function_def"}:
            name = node.child_by_field_name("name")
            if (
                name is not None
                and source[name.start_byte : name.end_byte] == b"__cplusplus"
            ):
                return source
        if node.type == "preproc_call" and re.match(
            rb"#\s*undef\s+__cplusplus\b", source[node.start_byte : node.end_byte]
        ):
            return source
        if node.type in _OPAQUE_NODES:
            opaque.append((node.start_byte, node.end_byte))
    projected = bytearray(source)
    stack: list[tuple[int, bool, bool]] = []
    masks: list[tuple[int, int]] = []
    for match in re.finditer(
        rb"(?m)^[ \t]*#[ \t]*(ifdef|ifndef|if|elif|else|endif)\b([^\r\n]*)", source
    ):
        offset = source.index(b"#", match.start(), match.end())
        if any(start < offset < end for start, end in opaque):
            continue
        directive, condition = match[1], match[2].strip()
        if directive in {b"ifdef", b"ifndef", b"if"}:
            positive = (directive == b"ifdef" and condition == b"__cplusplus") or (
                directive == b"if"
                and re.fullmatch(
                    rb"defined\s*(?:\(\s*__cplusplus\s*\)|\s+__cplusplus)", condition
                )
                is not None
            )
            stack.append((match.end(), positive, False))
        elif directive in {b"else", b"elif"} and stack:
            start, positive, done = stack[-1]
            if positive and not done:
                masks.append((start, match.start()))
                stack[-1] = (start, positive, True)
        elif directive == b"endif" and stack:
            start, positive, done = stack.pop()
            if positive and not done:
                masks.append((start, match.start()))
    for start, end in masks:
        for index in range(start, end):
            if projected[index] not in (10, 13):
                projected[index] = 32
    return bytes(projected)


def _parse_c_source(source: bytes, parser: Parser) -> Node:
    """Recover C language guards and source-local annotation macros.

    Parameters
    ----------
    source : bytes
        Original C source, retained for artifact spans and signatures.
    parser : tree_sitter.Parser
        Package-owned C grammar parser.

    Returns
    -------
    tree_sitter.Node
        Original root unless a coordinate-preserving projection is wholly clean.
        No header bytes, compiler flags or build commands are consulted.
    """
    original = parser.parse(source).root_node
    if not original.has_error:
        return original
    working = _c_language_source(source, original)
    basis = parser.parse(working).root_node if working != source else original
    if not basis.has_error:
        return basis
    annotations = _annotation_definitions(working, basis, parser)
    if not annotations:
        return original
    projected = bytearray(working)
    pending = [basis]
    while pending:
        node = pending.pop()
        if node.type in _OPAQUE_NODES:
            continue
        if node.type in _IDENTIFIER_NODES:
            token = working[node.start_byte : node.end_byte]
            available = annotations.get(token)
            if available is not None and node.start_byte >= available:
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
    if projected == working:
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
