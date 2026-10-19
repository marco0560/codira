"""Project proven plain data-field macros in record bodies at original offsets.

Parameters
----------
None

Returns
-------
None
    Data fields are outside the C analyzer's emitted artifact categories. The
    original source still supplies signatures; nested types and calls are held.
"""

import re
from collections.abc import Mapping, Sequence

from tree_sitter import Node, Parser

_OPAQUE = frozenset(
    {
        "preproc_def",
        "preproc_function_def",
        "preproc_call",
        "preproc_include",
        "comment",
        "string_literal",
        "char_literal",
    }
)
_UNSAFE_FIELDS = frozenset(
    {
        "function_declarator",
        "call_expression",
        "attribute_specifier",
        "attribute_declaration",
        "type_qualifier",
        "array_declarator",
        "bitfield_clause",
        "init_declarator",
        "struct_specifier",
        "union_specifier",
        "enum_specifier",
        "preproc_def",
        "preproc_function_def",
        "preproc_call",
        "preproc_include",
    }
)


def _plain_fields(value: bytes, parser: Parser) -> bool:
    """Recognize only ordinary data fields preceding an unchanged sentinel.

    Parameters
    ----------
    value : bytes
        Exact captured object-macro replacement.
    parser : tree_sitter.Parser
        Package-owned C grammar parser.

    Returns
    -------
    bool
        Whether the replacement adds plain fields, without nested public types,
        qualified constants, functions, expressions, or additional declarations.
    """
    source = b"struct __codira_record_probe {\n" + value + b"\nint __sentinel;\n};"
    root = parser.parse(source).root_node
    declarations = [node for node in root.named_children if node.type != "comment"]
    if (
        root.has_error
        or len(declarations) != 1
        or declarations[0].type != "struct_specifier"
    ):
        return False
    body = declarations[0].child_by_field_name("body")
    fields = (
        [] if body is None else [n for n in body.named_children if n.type != "comment"]
    )
    if len(fields) < 2:
        return False
    sentinel = fields[-1].child_by_field_name("declarator")
    if sentinel is None or sentinel.text != b"__sentinel":
        return False
    for field in fields[:-1]:
        declared_type = field.child_by_field_name("type")
        if (
            field.type != "field_declaration"
            or declared_type is None
            or declared_type.type
            not in {
                "type_identifier",
                "primitive_type",
                "sized_type_specifier",
            }
        ):
            return False
        pending = [field]
        while pending:
            node = pending.pop()
            if node.type in _UNSAFE_FIELDS:
                return False
            pending.extend(node.named_children)
    return True


def record_prefix_definitions(
    replacements: Mapping[bytes, Sequence[bytes]],
    first_offsets: Mapping[bytes, int],
    unsafe: set[bytes],
    parser: Parser,
) -> dict[bytes, int]:
    """Accept identical plain-field alternatives without selecting a branch.

    Parameters
    ----------
    replacements : collections.abc.Mapping[bytes, collections.abc.Sequence[bytes]]
        Source and captured-header object replacement alternatives.
    first_offsets : collections.abc.Mapping[bytes, int]
        Earliest original-source availability for each definition.
    unsafe : set[bytes]
        Names invalidated by undefinitions or function-like definitions.
    parser : tree_sitter.Parser
        Package-owned C grammar parser.

    Returns
    -------
    dict[bytes, int]
        Proven field-prefix names and original availability boundaries. Aliases,
        conflicting alternatives and macro-dependent field types remain held.
    """
    accepted: dict[bytes, int] = {}
    for name, alternatives in replacements.items():
        if name in unsafe or len(set(alternatives)) != 1:
            continue
        value = alternatives[0]
        if not _plain_fields(value, parser):
            continue
        dependent = any(
            token in replacements or token in unsafe
            for token in re.findall(rb"[A-Za-z_][A-Za-z_0-9]*", value)
        )
        if not dependent:
            accepted[name] = first_offsets[name]
    return accepted


def record_prefix_source(
    source: bytes,
    root: Node,
    definitions: Mapping[bytes, int],
    protected: tuple[tuple[int, int], ...],
) -> bytes:
    """Blank only proven record prefixes in direct field-type positions.

    Parameters
    ----------
    source : bytes
        Original-coordinate source buffer.
    root : tree_sitter.Node
        Partial tree supplying field-type positions.
    definitions : collections.abc.Mapping[bytes, int]
        Proven prefix names and their earliest safe availability.
    protected : tuple[tuple[int, int], ...]
        Logical hash-line spans whose modification could invent a directive.

    Returns
    -------
    bytes
        Equal-width projection. Source signatures, line endings and following
        declarations retain their original bytes and coordinates.
    """
    projected = bytearray(source)
    pending = [root]
    while pending:
        node = pending.pop()
        if node.type in _OPAQUE:
            continue
        parent = node.parent
        token = source[node.start_byte : node.end_byte]
        if (
            node.type == "type_identifier"
            and token in definitions
            and node.start_byte >= definitions[token]
            and parent is not None
            and parent.type == "field_declaration"
            and parent.child_by_field_name("type") == node
            and parent.parent is not None
            and parent.parent.type == "field_declaration_list"
            and not any(start <= node.start_byte < end for start, end in protected)
        ):
            projected[node.start_byte : node.end_byte] = b" " * (
                node.end_byte - node.start_byte
            )
        pending.extend(node.children)
    return bytes(projected)
