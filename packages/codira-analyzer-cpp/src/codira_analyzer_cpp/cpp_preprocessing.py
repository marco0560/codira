"""Recover complex syntax, pragmas and annotations at original source coordinates.

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

from tree_sitter import Parser

from .cpp_projection import SyntaxNode as Node, _source_projection

from .cpp_syntax import _new_parser

_IDENTIFIER = re.compile(rb"\b[A-Za-z_][A-Za-z_0-9]*\b")
_MS_PRAGMA_RAW_STRING = re.compile(rb'(?:u8|u|U|L)?R"([^ ()\\\t\r\n]{0,16})\(')
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
_DECLARATION_SPECIFIERS = frozenset(
    {("storage_class_specifier", b"inline"), ("type_qualifier", b"constexpr")}
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
    functions : dict[bytes, list[tuple[tuple[bytes, ...], bytes]]], optional
        Supported function replacement alternatives and their formal arguments.
    invalid_functions : set[bytes], optional
        Names with undefinitions or unsupported formal arguments.
    stringifiers : dict[bytes, tuple[int, int]] | None, optional
        Cached pure stringifier arity and availability, local to these inputs.
    pragma_overridden : bool, optional
        Whether captured declarations or directives override pragma spellings.

    Returns
    -------
    None
        Mutable collection state local to one parser call.
    """

    replacements: dict[bytes, list[bytes]] = field(default_factory=dict)
    first_offsets: dict[bytes, int] = field(default_factory=dict)
    unsafe: set[bytes] = field(default_factory=set)
    functions: dict[bytes, list[tuple[tuple[bytes, ...], bytes]]] = field(
        default_factory=dict
    )
    invalid_functions: set[bytes] = field(default_factory=set)
    stringifiers: dict[bytes, tuple[int, int]] | None = None
    pragma_overridden: bool = False


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
    """Accept attributes, inline or constexpr without changing a probe's type.

    Parameters
    ----------
    value : bytes
        Object macro replacement after known annotation aliases are blanked.
    parser : tree_sitter.Parser
        Package-local C++ parser.

    Returns
    -------
    bool
        Whether the replacement adds only attributes or supported declaration
        specifiers to an unchanged int probe. Type, linkage and declarator
        replacements remain unsupported.
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
        child == type_node
        or child == declarator
        or child.type in _ANNOTATION_NODES
        or (child.type, source[child.start_byte : child.end_byte])
        in _DECLARATION_SPECIFIERS
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
        Object annotation names and earliest safe use offsets. Compatible
        function replacements can license their object aliases. Function names,
        undefinitions and conflicting replacements remain excluded file-wide.
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
    overridden_specifiers = {
        token
        for _, token in _DECLARATION_SPECIFIERS
        if token in definitions or token in unsafe
    }
    accepted: dict[bytes, int] = {}
    changed = True
    while changed:
        changed = False
        for name, alternatives in definitions.items():
            if name in accepted or name in unsafe:
                continue
            function_views = [
                _function_annotation_source(value, state, accepted, parser)
                for value in alternatives
            ]
            expanded = [
                _IDENTIFIER.sub(
                    lambda match: (
                        b" " * len(match[0]) if match[0] in accepted else match[0]
                    ),
                    value,
                )
                for value, _, _ in function_views
            ]
            if any(
                overridden_specifiers.intersection(_IDENTIFIER.findall(value))
                for value in expanded
            ) or not all(_is_annotation(value, parser) for value in expanded):
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
            accepted[name] = max(
                accepted[name], *(boundary for _, boundary, _ in function_views)
            )
            changed = True
    return accepted


def _macro_call_arguments(source: bytes, arguments: Node) -> tuple[bytes, ...] | None:
    """Split macro arguments by preprocessing parentheses rather than templates.

    Parameters
    ----------
    source : bytes
        Replacement buffer containing the call.
    arguments : tree_sitter.Node
        Provider argument list with complete written parentheses.

    Returns
    -------
    tuple[bytes, ...] | None
        Raw arguments, or None for incomplete or unbalanced input.
    """
    return _macro_argument_span(
        source, arguments.start_byte, arguments.end_byte, tuple(_nodes(arguments))
    )


def _macro_argument_span(
    source: bytes, start: int, end: int, nodes: tuple[Node, ...]
) -> tuple[bytes, ...] | None:
    """Split a lexically bounded macro invocation even inside opaque pragma text.

    Parameters
    ----------
    source : bytes
        Buffer owning the invocation.
    start, end : int
        Original opening parenthesis and exclusive closing offset.
    nodes : tuple[tree_sitter.Node, ...]
        Provider nodes supplying literal and comment spans.

    Returns
    -------
    tuple[bytes, ...] | None
        Preprocessing arguments, or None for incomplete parentheses.
    """
    if source[start : start + 1] != b"(" or source[end - 1 : end] != b")":
        return None
    protected = {
        node.start_byte: node.end_byte for node in nodes if node.type in _OPAQUE_NODES
    }
    values: list[bytes] = []
    cursor = beginning = start + 1
    depth = 0
    while cursor < end - 1:
        if cursor in protected:
            cursor = protected[cursor]
            continue
        byte = source[cursor]
        if byte == 40:
            depth += 1
        elif byte == 41:
            depth -= 1
            if depth < 0:
                return None
        elif byte == 44 and depth == 0:
            values.append(source[beginning:cursor].strip())
            beginning = cursor + 1
        cursor += 1
    if depth:
        return None
    tail = source[beginning : end - 1].strip()
    tail_view = bytearray(source[beginning : end - 1])
    for node in nodes:
        if node.type == "comment" and beginning <= node.start_byte < end - 1:
            a, b = node.start_byte - beginning, node.end_byte - beginning
            tail_view[a:b] = b" " * (b - a)
    return tuple([*values, tail]) if values or bytes(tail_view).strip() else ()


def _stringifier_definitions(
    state: _AnnotationDefinitions, parser: Parser
) -> dict[bytes, tuple[int, int]]:
    """Prove only parameter stringification and single-stringifier wrappers.

    Parameters
    ----------
    state : _AnnotationDefinitions
        Complete captured alternatives and invalidations.
    parser : tree_sitter.Parser
        Parser for simple wrapper invocations.

    Returns
    -------
    dict[bytes, tuple[int, int]]
        String-only macro arities and latest dependency availability.
    """
    if state.stringifiers is not None:
        return state.stringifiers
    resolved: dict[bytes, tuple[int, int]] = {}
    changed = True
    while changed:
        changed = False
        for name, alternatives in state.functions.items():
            if (
                name in resolved
                or name in state.invalid_functions
                or name in state.replacements
            ):
                continue
            arities = {len(parameters) for parameters, _ in alternatives}
            if len(arities) != 1:
                continue
            latest = state.first_offsets[name]
            for parameters, body in alternatives:
                body = body.strip()
                sharp = re.fullmatch(rb"#\s*([A-Za-z_][A-Za-z_0-9]*)", body)
                if sharp and sharp[1] in parameters:
                    continue
                prefix = _IDENTIFIER.match(body)
                if prefix is None or prefix[0] not in resolved:
                    break
                call = next(
                    (
                        node
                        for node in _nodes(parser.parse(body).root_node)
                        if node.type == "call_expression"
                        and node.start_byte == 0
                        and node.end_byte == len(body)
                    ),
                    None,
                )
                arguments = call.child_by_field_name("arguments") if call else None
                actual = _macro_call_arguments(body, arguments) if arguments else None
                count, dependency = resolved[prefix[0]]
                if actual is None or not (
                    len(actual) == count or count == 1 and not actual
                ):
                    break
                latest = max(latest, dependency)
            else:
                resolved[name] = (next(iter(arities)), latest)
                changed = True
    state.stringifiers = resolved
    return resolved


def _pragma_annotation_source(
    value: bytes, state: _AnnotationDefinitions, parser: Parser
) -> tuple[bytes, int, bool]:
    """Hide complete pragma operators in replacement values with proven operands.

    Parameters
    ----------
    value : bytes
        Macro replacement bytes, not an executable source body.
    state : _AnnotationDefinitions
        Captured declarations, definitions and stringifier proof inputs.
    parser : tree_sitter.Parser
        Parser supplying protected literal and comment spans.

    Returns
    -------
    tuple[bytes, int, bool]
        Equal-width view, latest dependency boundary and pragma proof flag.
    """
    if state.pragma_overridden or (
        b"_Pragma" not in value and b"__pragma" not in value
    ):
        return value, 0, False
    nodes = tuple(_nodes(parser.parse(value).root_node))
    protected = [(n.start_byte, n.end_byte) for n in nodes if n.type in _OPAQUE_NODES]
    projected = bytearray(value)
    boundary = 0
    proven = False
    covered = 0
    for match in _IDENTIFIER.finditer(value):
        if (
            match[0] not in {b"_Pragma", b"__pragma"}
            or match.start() < covered
            or any(a <= match.start() < b for a, b in protected)
        ):
            continue
        end = _pragma_end(value, match.start())
        dependency = 0
        if end is None and match[0] == b"_Pragma":
            # The existing MS pragma lexer supplies balanced opaque parentheses;
            # only a separately proven stringifier licenses a standard operand.
            surrogate = b"__pragma" + value[match.end() :]
            balanced = _pragma_end(surrogate, 0)
            if balanced is None:
                continue
            candidate_end = match.start() + balanced - 1
            opening = match.end()
            while opening < len(value) and value[opening] in b" \t\r\n\f":
                opening += 1
            operand_start = opening + 1
            while (
                operand_start < candidate_end and value[operand_start] in b" \t\r\n\f"
            ):
                operand_start += 1
            operand = value[operand_start : candidate_end - 1].rstrip()
            name = _IDENTIFIER.match(operand)
            stringifiers = _stringifier_definitions(state, parser)
            if name is None or name[0] not in stringifiers:
                continue
            arity, dependency = stringifiers[name[0]]
            inner_end = _pragma_end(b"__pragma" + operand[name.end() :], 0)
            if inner_end is None or inner_end - 8 + name.end() != len(operand):
                continue
            parenthesis = name.end()
            while parenthesis < len(operand) and operand[parenthesis] in b" \t\r\n\f":
                parenthesis += 1
            actual = _macro_argument_span(
                operand,
                parenthesis,
                len(operand),
                tuple(_nodes(parser.parse(operand).root_node)),
            )
            if actual is None or not (
                len(actual) == arity or arity == 1 and not actual
            ):
                continue
            end = candidate_end
        if end is not None:
            for offset in range(match.start(), end):
                if projected[offset] not in {10, 13}:
                    projected[offset] = 32
            boundary = max(boundary, dependency)
            proven = True
            covered = end
    return bytes(projected), boundary, proven


def _function_annotation_source(
    value: bytes,
    state: _AnnotationDefinitions,
    accepted: dict[bytes, int],
    parser: Parser,
    active: frozenset[bytes] = frozenset(),
) -> tuple[bytes, int, bool]:
    """Blank only function replacements proven to preserve an annotation probe.

    Parameters
    ----------
    value : bytes
        Object or nested function replacement, never an executable source body.
    state : _AnnotationDefinitions
        Captured alternatives, availability and invalidations.
    accepted : dict[bytes, int]
        Already proven object annotation aliases.
    parser : tree_sitter.Parser
        Package-local C++ parser.
    active : frozenset[bytes], optional
        Current dependency chain, bounding recursion and rejecting cycles.

    Returns
    -------
    tuple[bytes, int, bool]
        Equal-width replacement, latest definition boundary and whether any
        nonempty compiler annotation was proven. Pure empty functions stay opaque.
    """
    if len(active) >= 32:
        return value, 0, False
    value, boundary, proven = _pragma_annotation_source(value, state, parser)
    if not state.functions.keys() & set(_IDENTIFIER.findall(value)):
        return value, boundary, proven
    root = parser.parse(value).root_node
    projected = bytearray(value)
    covered: list[tuple[int, int]] = []
    overridden = {
        token
        for _, token in _DECLARATION_SPECIFIERS
        if token in state.replacements or token in state.unsafe
    }
    for node in _nodes(root):
        if node.type not in {"call_expression", "init_declarator"} or any(
            a <= node.start_byte < b for a, b in covered
        ):
            continue
        function = node.child_by_field_name(
            "declarator" if node.type == "init_declarator" else "function"
        )
        arguments = node.child_by_field_name(
            "value" if node.type == "init_declarator" else "arguments"
        )
        if function is None or function.type != "identifier" or arguments is None:
            continue
        if arguments.type != "argument_list":
            continue
        name = value[function.start_byte : function.end_byte]
        alternatives = state.functions.get(name, [])
        if (
            not alternatives
            or name in active
            or name in state.invalid_functions
            or name in state.replacements
        ):
            continue
        actual = _macro_call_arguments(value, arguments)
        if actual is None:
            continue
        latest = state.first_offsets[name]
        positive = False
        for formals, body in alternatives:
            supplied = (b"",) if len(formals) == 1 and not actual else actual
            if len(formals) != len(supplied):
                break
            bindings = dict(zip(formals, supplied, strict=True))
            opaque = [
                (n.start_byte, n.end_byte)
                for n in _nodes(parser.parse(body).root_node)
                if n.type in _OPAQUE_NODES | {"user_defined_literal", "number_literal"}
            ]
            substituted = _IDENTIFIER.sub(
                lambda match: (
                    match[0]
                    if any(a <= match.start() < b for a, b in opaque)
                    else bindings.get(match[0], match[0])
                ),
                body,
            )
            if len(substituted) > 4096:
                break
            substituted, nested, nested_positive = _function_annotation_source(
                substituted, state, accepted, parser, active | {name}
            )
            dependencies = accepted.keys() & set(_IDENTIFIER.findall(substituted))
            latest = max(latest, nested, *(accepted[token] for token in dependencies))
            substituted = _IDENTIFIER.sub(
                lambda match: (
                    b" " * len(match[0]) if match[0] in accepted else match[0]
                ),
                substituted,
            )
            if overridden.intersection(
                _IDENTIFIER.findall(substituted)
            ) or not _is_annotation(substituted, parser):
                break
            positive = positive or nested_positive or bool(substituted.strip())
        else:
            if not positive:
                continue
            projected[node.start_byte : node.end_byte] = b" " * (
                node.end_byte - node.start_byte
            )
            covered.append((node.start_byte, node.end_byte))
            boundary = max(boundary, latest)
            proven = True
    return bytes(projected), boundary, proven


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
    definitions.stringifiers = None
    if not definitions.pragma_overridden and (
        b"_Pragma" in source or b"__pragma" in source
    ):
        definitions.pragma_overridden = _pragma_overridden(source, root)
    for node in _nodes(root):
        if node.type in {"preproc_def", "preproc_function_def"}:
            name_node = node.child_by_field_name("name")
            if name_node is None:
                continue
            token = source[name_node.start_byte : name_node.end_byte]
            offset = node.end_byte if boundary is None else boundary
            definitions.first_offsets[token] = min(
                definitions.first_offsets.get(token, offset), offset
            )
            value = node.child_by_field_name("value")
            replacement = source[value.start_byte : value.end_byte] if value else b""
            replacement = re.sub(rb"\\\r?\n", b" ", replacement)
            if node.type == "preproc_function_def":
                definitions.unsafe.add(token)
                parameters = node.child_by_field_name("parameters")
                text = (
                    source[parameters.start_byte : parameters.end_byte]
                    if parameters
                    else b""
                )
                if re.fullmatch(
                    rb"\(\s*(?:[A-Za-z_][A-Za-z_0-9]*(?:\s*,\s*[A-Za-z_][A-Za-z_0-9]*)*)?\s*\)",
                    text,
                ):
                    formals = tuple(_IDENTIFIER.findall(text))
                    if len(set(formals)) == len(formals):
                        definitions.functions.setdefault(token, []).append(
                            (formals, replacement)
                        )
                        continue
                definitions.invalid_functions.add(token)
                continue
            definitions.replacements.setdefault(token, []).append(replacement)
        elif node.type == "preproc_call":
            match = _UNDEF.match(source[node.start_byte : node.end_byte])
            if match is not None:
                definitions.unsafe.add(match[1])
                definitions.invalid_functions.add(match[1])


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


def _pragma_end(source: bytes, start: int) -> int | None:
    """Find the end of one lexically complete compiler pragma operator.

    Parameters
    ----------
    source : bytes
        Bytes owning the operator and its opaque payload.
    start : int
        Start offset of the reserved operator spelling.

    Returns
    -------
    int | None
        Exclusive closing offset, or ``None`` for unsafe/incomplete input.
    """
    operator = (
        b"__pragma"
        if source[start : start + 8] == b"__pragma"
        else b"_Pragma"
        if source[start : start + 7] == b"_Pragma"
        else None
    )
    if operator is None:
        return None
    standard = operator == b"_Pragma"
    literal = False
    cursor = start + len(operator)
    while cursor < len(source) and source[cursor] in b" \t\r\n\f":
        cursor += 1
    if cursor == len(source) or source[cursor] != 40:
        return None
    depth = 1
    cursor += 1
    while cursor < len(source):
        byte = source[cursor]
        if source[cursor : cursor + 2] == b"/*":
            end = source.find(b"*/", cursor + 2)
            if end < 0:
                return None
            cursor = end + 2
            continue
        if source[cursor : cursor + 2] == b"//":
            end = source.find(b"\n", cursor + 2)
            if end < 0:
                return None
            if (
                b"\\\n" in source[cursor : end + 1]
                or b"\\\r\n" in source[cursor : end + 1]
            ):
                return None
            cursor = end + 1
            continue
        if standard:
            if byte in b" \t\r\n\f":
                cursor += 1
                continue
            if literal:
                return cursor + 1 if byte == 41 else None
            if byte == 76 and source[cursor + 1 : cursor + 2] == b'"':
                cursor += 1
                byte = 34
            if byte != 34:
                return None
        raw = _MS_PRAGMA_RAW_STRING.match(source, cursor)
        if raw is not None:
            marker = b")" + raw[1] + b'"'
            end = source.find(marker, raw.end())
            if end < 0:
                return None
            cursor = end + len(marker)
            continue
        if byte in {34, 39}:
            quote = byte
            cursor += 1
            while cursor < len(source) and source[cursor] != quote:
                if source[cursor] == 92:
                    cursor += 2
                elif source[cursor] in {10, 13}:
                    return None
                else:
                    cursor += 1
            if cursor >= len(source):
                return None
            cursor += 1
            literal = True
            continue
        if (
            source[cursor : cursor + 2] == b"\\\n"
            or source[cursor : cursor + 3] == b"\\\r\n"
        ):
            return None
        if byte == 40:
            depth += 1
        elif byte == 41:
            depth -= 1
            if not depth:
                return cursor + 1
        cursor += 1
    return None


def _pragma_overridden(source: bytes, root: Node) -> bool:
    """Check source-proven declarations or preprocessing overrides of pragma names.

    Parameters
    ----------
    source : bytes
        Source input being checked.
    root : tree_sitter.Node
        Provider root for this input.

    Returns
    -------
    bool
        Whether an observed definition or undef prevents builtin interpretation.
    """
    if b"__pragma" not in source and b"_Pragma" not in source:
        return False
    for node in _nodes(root):
        if node.type in {"declaration", "function_definition"} and not node.has_error:
            declarator = node.child_by_field_name("declarator")
            while declarator is not None:
                if source[declarator.start_byte : declarator.end_byte] in {
                    b"__pragma",
                    b"_Pragma",
                }:
                    return True
                declarator = declarator.child_by_field_name("declarator")
        if node.type in {"preproc_def", "preproc_function_def"}:
            name = node.child_by_field_name("name")
            if name is not None and source[name.start_byte : name.end_byte] in {
                b"__pragma",
                b"_Pragma",
            }:
                return True
        if node.type == "preproc_call" and re.match(
            rb"#\s*undef\s+(?:__pragma|_Pragma)\b",
            source[node.start_byte : node.end_byte],
        ):
            return True
    return False


def _pragma_source(source: bytes, root: Node) -> bytes:
    """Hide complete compiler pragma operators from the executable grammar.

    Parameters
    ----------
    source : bytes
        Original or coordinate-preserving language-view source.
    root : tree_sitter.Node
        Provider root for the supplied source bytes.

    Returns
    -------
    bytes
        Equal-width view preserving newlines, literals and directives. Source
        definitions of the reserved spelling disable this interpretation.

    Notes
    -----
    Pragma payload semantics are left opaque, as for ordinary hash pragmas.
    Unclosed operators or payloads crossing statement/block delimiters are not
    recovered. The caller must require a wholly clean final parse.
    """
    if b"__pragma" not in source and b"_Pragma" not in source:
        return source
    if _pragma_overridden(source, root):
        return source
    candidates: list[Node] = []
    pending = [root]
    while pending:
        node = pending.pop()
        if node.type in _OPAQUE_NODES:
            continue
        if node.type in _IDENTIFIER_NODES and source[
            node.start_byte : node.end_byte
        ] in {b"__pragma", b"_Pragma"}:
            candidates.append(node)
        pending.extend(reversed(node.children))
    protected = _hash_lines(source, root)
    projected = bytearray(source)
    for node in candidates:
        if any(start <= node.start_byte < end for start, end in protected):
            continue
        cursor = _pragma_end(source, node.start_byte)
        if cursor is None or any(
            start < cursor and end > node.start_byte for start, end in protected
        ):
            continue
        for offset in range(node.start_byte, cursor):
            if projected[offset] not in {10, 13}:
                projected[offset] = 32
    for before, after in zip(source.split(b"\n"), bytes(projected).split(b"\n")):
        if after.lstrip(b" \t\r\f").startswith(b"#") and not before.lstrip(
            b" \t\r\f"
        ).startswith(b"#"):
            return source
    return bytes(projected)


_COMPLEX_TYPES = frozenset({b"_Complex", b"__complex", b"__complex__"})
_COMPLEX_OPERATORS = frozenset({b"__real", b"__real__", b"__imag", b"__imag__"})
_COMPLEX_KEYWORDS = _COMPLEX_TYPES | _COMPLEX_OPERATORS
_COMPLEX_WORD = re.compile(
    rb"\b(?:_Complex|__complex(?:__)?|__real(?:__)?|__imag(?:__)?)\b"
)
_COMPLEX_BASES = frozenset(
    word.encode()
    for word in (
        "char short int long float double signed unsigned __int128 "
        "_Float16 _Float32 _Float64 _Float128 __float128 __fp16 __bf16"
    ).split()
)
_COMPLEX_QUALIFIERS = frozenset(
    word.encode()
    for word in (
        "const volatile restrict __restrict __restrict__ _Atomic "
        "__const __const__ __volatile __volatile__"
    ).split()
)


def _complex_overrides(source: bytes, root: Node) -> frozenset[bytes]:
    """Find source-defined or undefined reserved complex keyword spellings.

    Parameters
    ----------
    source : bytes
        Source bytes corresponding to the provider tree.
    root : tree_sitter.Node
        Original provider root for this input.

    Returns
    -------
    frozenset[bytes]
        Spellings whose preprocessing contract must remain opaque.
    """
    if _COMPLEX_WORD.search(source) is None:
        return frozenset()
    overridden: set[bytes] = set()
    for node in _nodes(root):
        if node.type in {"preproc_def", "preproc_function_def"}:
            name = node.child_by_field_name("name")
            if name is not None:
                token = source[name.start_byte : name.end_byte]
                if token in _COMPLEX_KEYWORDS:
                    overridden.add(token)
        elif node.type == "preproc_call":
            match = re.match(
                rb"#\s*undef\s+(\w+)", source[node.start_byte : node.end_byte]
            )
            if match is not None and match[1] in _COMPLEX_KEYWORDS:
                overridden.add(match[1])
    return frozenset(overridden)


def _is_complex_operator_call(node: Node, source: bytes) -> bool:
    """Identify the non-call marker preserving a parenthesized operator operand.

    Parameters
    ----------
    node : tree_sitter.Node
        Provider call-expression node considered by artifact extraction.
    source : bytes
        Original source bytes.

    Returns
    -------
    bool
        Whether a numeric view callee covers an original reserved complex operator.
        Ordinary source calls and overridden macros cannot satisfy this marker.
    """
    function = node.child_by_field_name("function")
    if function is None or function.type != "number_literal" or function.text != b"0":
        return False
    match = _COMPLEX_WORD.match(source, function.start_byte)
    return match is not None and match[0] in _COMPLEX_OPERATORS


def _complex_source(
    source: bytes, root: Node, overridden: frozenset[bytes] = frozenset()
) -> bytes:
    """Represent complex types and real/imaginary operators in the provider grammar.

    Parameters
    ----------
    source : bytes
        Original source or an equal-width parse view.
    root : tree_sitter.Node
        Provider tree used to shield comments, literals and directives.
    overridden : frozenset[bytes], optional
        Reserved spellings overridden by captured header preprocessing inputs.

    Returns
    -------
    bytes
        Equal-width view, with original line endings. Complex modifiers use a
        provider type-qualifier placeholder. Real/imaginary operators use a unary
        placeholder, or a tagged non-call marker to keep nested operand calls out
        of the C grammar's cast ambiguity. Bare complex types retain their spans.
        Extractors
        must read text from original source, never interpret placeholder semantics.

    Notes
    -----
    This is structural grammar adaptation only; qualifier/attribute placeholders
    assert no volatility, nonreturning, alignment, unary-plus, ABI or evaluation
    semantics. Their byte widths exactly match the original complex keyword.
    Accepted duplicate specifiers retain their original source text. Recovery
    requires a wholly clean final provider tree.
    """
    if _COMPLEX_WORD.search(source) is None:
        return source
    blocked = overridden | _complex_overrides(source, root)
    call_operands: set[int] = set()
    for node in _nodes(root):
        if node.type != "call_expression":
            continue
        function = node.child_by_field_name("function")
        arguments = node.child_by_field_name("arguments")
        if (
            function is not None
            and arguments is not None
            and source[function.start_byte : function.end_byte] in _COMPLEX_OPERATORS
            and any(child.type == "call_expression" for child in _nodes(arguments))
        ):
            call_operands.add(function.start_byte)
    opaque: list[tuple[int, int]] = []
    lexical = bytearray(source)
    for node in _nodes(root):
        if node.type in _OPAQUE_NODES:
            opaque.append((node.start_byte, node.end_byte))
        if node.type == "comment":
            for offset in range(node.start_byte, node.end_byte):
                if lexical[offset] not in {10, 13}:
                    lexical[offset] = 32
    protected = _hash_lines(source, root)
    if not any(
        match[0] not in blocked
        and not any(
            start <= match.start() < end for start, end in (*opaque, *protected)
        )
        for match in _COMPLEX_WORD.finditer(source)
    ):
        return source
    for start, end in protected:
        for offset in range(start, end):
            if lexical[offset] not in {10, 13}:
                lexical[offset] = 32
        lexical[start] = 59
    tokens = tuple(re.finditer(rb"[A-Za-z_][A-Za-z_0-9]*|[^\s]", bytes(lexical)))
    group_words = _COMPLEX_TYPES | _COMPLEX_BASES | _COMPLEX_QUALIFIERS
    projected = bytearray(source)
    for index, match in enumerate(tokens):
        token = match[0]
        if token not in _COMPLEX_KEYWORDS or token in blocked:
            continue
        if any(start <= match.start() < end for start, end in (*opaque, *protected)):
            continue
        if token in _COMPLEX_OPERATORS:
            replacement = b"0" if match.start() in call_operands else b"+"
        else:
            first = index
            while first and tokens[first - 1][0] in group_words:
                first -= 1
            last = index + 1
            while last < len(tokens) and tokens[last][0] in group_words:
                last += 1
            group = [item[0] for item in tokens[first:last]]
            if not any(item in _COMPLEX_BASES for item in group):
                leading = next(
                    item for item in tokens[first:last] if item[0] in _COMPLEX_TYPES
                )
                if match.start() == leading.start():
                    continue
            replacement = {
                b"_Complex": b"volatile",
                b"__complex": b"_Noreturn",
                b"__complex__": b"alignas(00)",
            }[token]
        projected[match.start() : match.end()] = replacement.ljust(len(token), b" ")
    return bytes(projected)


def _namespace_source(
    source: bytes,
    root: Node,
    parser: Parser,
    included_sources: tuple[tuple[bytes, int], ...],
    namespace_bindings: tuple[tuple[bytes, bytes, int], ...] = (),
) -> Node | None:
    """Expand unambiguous object macros that open or close namespace scopes.

    Parameters
    ----------
    source : bytes
        Coordinate-aligned source after existing grammar adaptations.
    root : SyntaxNode
        Partial tree used to protect directives, comments and literals.
    parser : tree_sitter.Parser
        Package-local C++ parser.
    included_sources : tuple[tuple[bytes, int], ...]
        Captured headers and their earliest source include boundaries.
    namespace_bindings : tuple[tuple[bytes, bytes, int], ...], optional
        Validated namespace-only identifiers and their availability boundaries.

    Returns
    -------
    SyntaxNode or None
        Complete tree with original coordinates, or None if proof is incomplete.

    Notes
    -----
    Alternatives must resolve identically after namespace brace spacing is
    normalized. Undefs, function macros, cycles,
    unresolved uppercase namespace names and keyword redefinitions are held.
    Explicitly validated namespace binding values may use uppercase names.
    Expansions exceeding 4096 bytes are held to bound macro growth. Only complete
    scope-opening or scope-closing expansions are substituted in source code.
    """
    state = _AnnotationDefinitions()
    _collect_annotation_definitions(source, root, None, state)
    for content, boundary in included_sources:
        _collect_annotation_definitions(
            content, parser.parse(content).root_node, boundary, state
        )
    if any(
        token in state.replacements or token in state.unsafe
        for token in (b"namespace", b"inline")
    ):
        return None
    annotations = _annotation_definitions(source, root, parser, included_sources)
    resolved: dict[bytes, tuple[bytes, int]] = {
        name: (b"", boundary) for name, boundary in annotations.items()
    }
    resolved.update(
        {name: (value, boundary) for name, value, boundary in namespace_bindings}
    )
    openings = re.compile(
        rb"(?:(?:inline\s+)?namespace\s+"
        rb"[A-Za-z_][A-Za-z_0-9]*(?:::[A-Za-z_][A-Za-z_0-9]*)*\s*\{\s*)+"
    )
    changed = True
    while changed:
        changed = False
        for name, alternatives in state.replacements.items():
            if name in resolved or name in state.unsafe:
                continue
            values: set[bytes] = set()
            boundary = state.first_offsets[name]
            for value in alternatives:
                value, annotation_boundary, _ = _function_annotation_source(
                    value, state, annotations, parser
                )
                boundary = max(boundary, annotation_boundary)
                tokens = _IDENTIFIER.findall(value)
                if any(
                    token in state.unsafe
                    or (token in state.replacements and token not in resolved)
                    for token in tokens
                ):
                    break
                for token in tokens:
                    if token in resolved:
                        boundary = max(boundary, resolved[token][1])
                expanded = _IDENTIFIER.sub(
                    lambda match: resolved.get(match[0], (match[0], 0))[0], value
                )
                if len(expanded) > 4096:
                    break
                expanded = b" ".join(expanded.split())
                if openings.fullmatch(expanded) or re.fullmatch(
                    rb"(?:\}\s*)+", expanded
                ):
                    expanded = b" ".join(
                        re.sub(rb"\s*([{}])\s*", rb" \1 ", expanded).split()
                    )
                values.add(expanded)
            else:
                if len(values) == 1:
                    resolved[name] = (values.pop(), boundary)
                    changed = True
    bound_names = {value for _, value, _ in namespace_bindings}
    eligible = {
        name: (value, boundary)
        for name, (value, boundary) in resolved.items()
        if (openings.fullmatch(value) or re.fullmatch(rb"(?:\}\s*)+", value))
        and not any(
            token not in bound_names and re.fullmatch(rb"[A-Z_][A-Z_0-9]*", token)
            for token in _IDENTIFIER.findall(value)
        )
    }
    if not eligible and not namespace_bindings:
        return None
    protected = [*_hash_lines(source, root)]
    protected.extend(
        (node.start_byte, node.end_byte)
        for node in _nodes(root)
        if node.type in _OPAQUE_NODES
    )
    replacements = [
        (match.start(), match.end(), eligible[match[0]][0])
        for match in _IDENTIFIER.finditer(source)
        if match[0] in eligible
        and match.start() >= eligible[match[0]][1]
        and not any(start <= match.start() < end for start, end in protected)
    ]
    names = {name: (value, boundary) for name, value, boundary in namespace_bindings}
    for node in _nodes(root):
        if node.type != "namespace_definition":
            continue
        identifier = node.child_by_field_name("name")
        if identifier is None or identifier.type != "namespace_identifier":
            continue
        token = source[identifier.start_byte : identifier.end_byte]
        if token in names and identifier.start_byte >= names[token][1]:
            replacements.append(
                (identifier.start_byte, identifier.end_byte, names[token][0])
            )
    if not replacements:
        return None
    projection = _source_projection(source, sorted(replacements))
    recovered = parser.parse(projection.expanded).root_node
    return None if recovered.has_error else projection.tree(recovered)


def _parse_cpp_source(
    source: bytes,
    *,
    included_sources: tuple[tuple[bytes, int], ...] = (),
    namespace_bindings: tuple[tuple[bytes, bytes, int], ...] = (),
) -> Node:
    """Parse C++ with coordinate-preserving macro and compiler pragma recovery.

    Parameters
    ----------
    source : bytes
        Original C++ file bytes, also used later for artifact extraction.
    included_sources : tuple[tuple[bytes, int], ...], optional
        Captured header bytes and earliest source include-end offsets. Callers
        must bind these external analysis inputs to incremental reuse identity.
    namespace_bindings : tuple[tuple[bytes, bytes, int], ...], optional
        Validated namespace-only bindings used in the same scope projection.

    Returns
    -------
    SyntaxNode
        Original partial root unless grammar adaptation produces a wholly clean
        tree. Known reserved operators missing operands remain diagnosed even
        when originally accepted as identifiers. Directives/literals are retained.
    """
    parser = _new_parser()
    original = parser.parse(source).root_node
    override = (
        any(
            _pragma_overridden(content, parser.parse(content).root_node)
            for content, _ in included_sources
        )
        if b"__pragma" in source or b"_Pragma" in source
        else False
    )
    working = source if override else _pragma_source(source, original)
    complex_overrides = (
        frozenset(
            token
            for content, _ in included_sources
            for token in _complex_overrides(content, parser.parse(content).root_node)
        )
        if _COMPLEX_WORD.search(source) is not None
        else frozenset()
    )
    basis = parser.parse(working).root_node if working != source else original
    complex_view = _complex_source(working, basis, complex_overrides)
    complex_changed = complex_view != working
    working = complex_view
    if not original.has_error and working == source:
        return original
    basis = parser.parse(working).root_node if working != source else original
    if not basis.has_error:
        return basis
    fallback = basis if not original.has_error and complex_changed else original
    annotations = _annotation_definitions(working, basis, parser, included_sources)
    protected = _hash_lines(working, basis)
    projected = bytearray(working)
    pending = [basis]
    while pending:
        node = pending.pop()
        if node.type in _OPAQUE_NODES:
            continue
        if node.type in _IDENTIFIER_NODES:
            token = working[node.start_byte : node.end_byte]
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
    recovered = parser.parse(bytes(projected)).root_node
    if not recovered.has_error:
        return recovered
    namespace_root = _namespace_source(
        bytes(projected), recovered, parser, included_sources, namespace_bindings
    )
    return fallback if namespace_root is None else namespace_root


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
        Original declaration start, extended over blanked annotations while skipping
        standalone pragma prefixes. Siblings and comments bound the gap.
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
    cursor = len(gap) - len(gap.lstrip())
    while (
        gap[cursor : cursor + 8] == b"__pragma"
        or gap[cursor : cursor + 7] == b"_Pragma"
    ):
        end = _pragma_end(gap, cursor)
        if end is None:
            break
        cursor = end
        while cursor < len(gap) and gap[cursor] in b" \t\r\n\f":
            cursor += 1
    return lower + cursor
