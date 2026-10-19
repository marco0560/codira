"""Recognize C++ template evidence inside incomplete header syntax.

Parameters
----------
None

Returns
-------
None
    Provides language hints without recovering or emitting source artifacts.
"""

from __future__ import annotations

from tree_sitter import Node

from .cpp_syntax import _new_parser

_OPAQUE = frozenset(
    {
        "comment",
        "string_literal",
        "raw_string_literal",
        "char_literal",
        "system_lib_string",
        "preproc_def",
        "preproc_function_def",
        "preproc_call",
        "preproc_include",
    }
)
_TYPE_PARAMETERS = frozenset(
    {
        "type_parameter_declaration",
        "optional_type_parameter_declaration",
        "variadic_type_parameter_declaration",
    }
)
_KEYWORDS = frozenset({b"template", b"class", b"typename"})


def has_named_template_parameters(source: bytes, root: Node) -> bool:
    """Recognize a complete named type parameter list despite a broken body.

    Parameters
    ----------
    source : bytes
        Original header bytes, also used for the supplied tree's coordinates.
    root : tree_sitter.Node
        Potentially incomplete C++ tree for the header.

    Returns
    -------
    bool
        Whether a source template prefix independently parses with a named type
        parameter. Opaque contents and locally redefined keywords are excluded.
        This is language evidence, not proof that the header parses or compiles.
    """
    if b"template" not in source:
        return False
    tokens: list[Node] = []
    pending = [root]
    while pending:
        node = pending.pop()
        if node.type in {"preproc_def", "preproc_function_def"}:
            name = node.child_by_field_name("name")
            if (
                name is not None
                and source[name.start_byte : name.end_byte] in _KEYWORDS
            ):
                return False
        if node.type in _OPAQUE:
            continue
        if node.children:
            pending.extend(reversed(node.children))
        else:
            tokens.append(node)
    for index, node in enumerate(tokens[:-1]):
        if node.type != "template" or tokens[index + 1].type != "<":
            continue
        angles = 0
        brackets: list[str] = []
        for token in tokens[index + 1 :]:
            kind = token.type
            if kind in {"(", "[", "{"}:
                brackets.append({"(": ")", "[": "]", "{": "}"}[kind])
            elif kind in {")", "]", "}"}:
                if not brackets or brackets.pop() != kind:
                    break
            elif not brackets:
                if kind == ";":
                    break
                if kind == "<":
                    angles += 1
                elif kind in {">", ">>"}:
                    angles -= len(kind)
                    if angles < 0:
                        break
                    if angles == 0:
                        prefix = source[node.start_byte : token.end_byte]
                        probe = (
                            _new_parser()
                            .parse(prefix + b"\nstruct __codira_header_probe;")
                            .root_node
                        )
                        if not probe.has_error:
                            candidates = [probe]
                            while candidates:
                                candidate = candidates.pop()
                                if candidate.type in _TYPE_PARAMETERS and any(
                                    child.type == "type_identifier"
                                    and not child.is_missing
                                    for child in candidate.named_children
                                ):
                                    return True
                                candidates.extend(candidate.named_children)
                        break
    return False
