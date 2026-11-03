"""Recover complex syntax, pragmas and annotations at original source coordinates.

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

from .c_record_prefixes import record_prefix_definitions, record_prefix_source
from .c_statement_macros import (
    statement_argument_macro_source,
    statement_macro_source,
    type_argument_macro_source,
)


_DECLARATION_SPECIFIERS = frozenset(
    {
        ("storage_class_specifier", b"inline"),
        ("storage_class_specifier", b"__inline"),
        ("storage_class_specifier", b"__inline__"),
        ("type_qualifier", b"_Noreturn"),
    }
)
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
        Captured header bytes and earliest original-source availability.

    Returns
    -------
    dict[bytes, int]
        Eligible macro names and the earliest safe use offset. Function macros,
        undefined names and conflicting replacements are excluded file-wide.
    """
    return _resolve_annotations(
        _input_definitions(source, root, parser, included_sources), parser
    )


def _input_definitions(
    source: bytes,
    root: Node,
    parser: Parser,
    included_sources: tuple[tuple[bytes, int], ...],
) -> _AnnotationDefinitions:
    """Collect source and captured header definitions at original availability.

    Parameters
    ----------
    source : bytes
        Original-coordinate translation unit.
    root : tree_sitter.Node
        Tree for the translation unit.
    parser : tree_sitter.Parser
        Package-local C parser.
    included_sources : tuple[tuple[bytes, int], ...]
        Exact contained header bytes and source availability offsets.

    Returns
    -------
    _AnnotationDefinitions
        Combined alternatives, availability and invalidating directives.
    """
    state = _AnnotationDefinitions()
    _collect_annotation_definitions(source, root, state)
    for header, boundary in included_sources:
        tree = parser.parse(header).root_node
        content = _c_language_source(header, tree)
        if content != header:
            tree = parser.parse(content).root_node
        _collect_annotation_definitions(content, tree, state, available_after=boundary)
    return state


def _resolve_annotations(
    state: _AnnotationDefinitions, parser: Parser
) -> dict[bytes, int]:
    """Resolve only compatible annotation and function-specifier alternatives.

    Parameters
    ----------
    state : _AnnotationDefinitions
        Captured source and header macro definitions.
    parser : tree_sitter.Parser
        C parser used to validate unchanged declaration type and identity.

    Returns
    -------
    dict[bytes, int]
        Accepted names and their earliest safe original-source availability.
    """
    definitions = state.replacements
    first_offsets = state.first_offsets
    unsafe = state.unsafe
    overridden = {
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
            expanded = [
                _IDENTIFIER.sub(
                    lambda match: (
                        b" " * len(match[0]) if match[0] in accepted else match[0]
                    ),
                    value,
                )
                for value in alternatives
            ]
            if any(
                overridden.intersection(_IDENTIFIER.findall(value))
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
            changed = True
    return accepted


def _collect_annotation_definitions(
    source: bytes,
    root: Node,
    definitions: _AnnotationDefinitions,
    *,
    available_after: int | None = None,
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

    available_after : int or None, optional
        Original-source include boundary, or the local definition end offset.

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
            offset = node.end_byte if available_after is None else available_after
            definitions.first_offsets[token] = min(
                definitions.first_offsets.get(token, offset), offset
            )
        elif node.type == "preproc_call":
            match = _UNDEF.match(source[node.start_byte : node.end_byte])
            if match is not None:
                definitions.unsafe.add(match[1])


def _c_language_source(source: bytes, root: Node) -> bytes:
    """Project C++ linkage wrappers without selecting a language branch.

    Parameters
    ----------
    source : bytes
        Original C source bytes.
    root : tree_sitter.Node
        Unmodified tree supplying opaque comment, literal and macro spans.

    Returns
    -------
    bytes
        Same-length source with only ``extern "C" {`` wrapper tokens blanked.
        Declarations inside positive ``__cplusplus`` branches remain visible.
    """
    opaque = [
        (node.start_byte, node.end_byte)
        for node in _nodes(root)
        if node.type in _OPAQUE_NODES and node.type != "string_literal"
    ]
    directives = tuple(
        re.finditer(
            rb"(?m)^[ \t]*#[ \t]*(ifdef|ifndef|if|elif|else|endif)\b([^\r\n]*)",
            source,
        )
    )
    projected = bytearray(source)
    for index, match in enumerate(directives):
        directive, condition = match[1], match[2].strip()
        positive = (directive == b"ifdef" and condition == b"__cplusplus") or (
            directive == b"if"
            and re.fullmatch(
                rb"defined\s*(?:\(\s*__cplusplus\s*\)|\s+__cplusplus)",
                condition,
            )
            is not None
        )
        if not positive or any(start < match.start() < end for start, end in opaque):
            continue
        depth = 1
        boundary = len(directives)
        for following in range(index + 1, len(directives)):
            kind = directives[following][1]
            if kind in {b"if", b"ifdef", b"ifndef"}:
                depth += 1
            elif kind == b"endif":
                depth -= 1
                if depth == 0:
                    boundary = following
                    break
            elif depth == 1 and kind in {b"else", b"elif"}:
                boundary = following
                break
        end = (
            directives[boundary].start() if boundary < len(directives) else len(source)
        )
        branch = source[match.end() : end]
        wrapper = re.search(rb"\bextern\s+\"C\"\s*\{", branch)
        if wrapper is not None:
            wrapper_start = match.end() + wrapper.start()
            wrapper_end = match.end() + wrapper.end()
            for offset in range(wrapper_start, wrapper_end):
                if projected[offset] not in (10, 13):
                    projected[offset] = 32
            close_source = branch[wrapper.end() :]
            close_offset = wrapper.end()
        else:
            close_source = branch
            close_offset = 0
        close = tuple(re.finditer(rb"(?m)^[ \t]*\}[ \t]*(?:\r?\n|$)", close_source))
        if close:
            selected = close[-1]
            close_start = match.end() + close_offset + selected.start()
            close_end = match.end() + close_offset + selected.end()
            for offset in range(close_start, close_end):
                if projected[offset] not in (10, 13):
                    projected[offset] = 32
    return bytes(projected)


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
    Unclosed operators and ambiguous preprocessing line splices are not
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


def _parse_c_source(
    source: bytes,
    parser: Parser,
    included_sources: tuple[tuple[bytes, int], ...] = (),
    parse_projection: bytes | None = None,
) -> Node:
    """Recover guards, pragmas, annotations and proven loop-prefix syntax.

    Parameters
    ----------
    source : bytes
        Original C source, retained for artifact spans and signatures.
    parser : tree_sitter.Parser
        Package-owned C grammar parser.

    included_sources : tuple[tuple[bytes, int], ...], optional
        Captured header definitions, available only after their source boundary.

    Returns
    -------
    tree_sitter.Node
        Original partial root unless an equal-width projection is wholly clean.
        Known reserved operators missing operands remain diagnosed even when the
        original provider treats their spelling as an ordinary identifier.
        Captured contained headers can prove macros; no compiler or build tool
        is invoked. Plain data-field prefixes affect no emitted field category.
        Loop-prefix views retain original coordinates; callers must preserve
        their written macro invocation when extracting source calls.
    """
    original = parser.parse(source).root_node
    if (
        original.has_error
        and parse_projection is not None
        and len(parse_projection) == len(source)
        and parse_projection != source
    ):
        projected_root = parser.parse(parse_projection).root_node
        if not projected_root.has_error or _projection_preserves_other_errors(
            source, original, parse_projection, projected_root
        ):
            return projected_root
    pragma_source = _pragma_source(source, original)
    pragma_root = (
        parser.parse(pragma_source).root_node if pragma_source != source else original
    )
    complex_view = _complex_source(pragma_source, pragma_root)
    complex_changed = complex_view != pragma_source
    pragma_source = complex_view
    if not original.has_error and pragma_source == source:
        type_view = type_argument_macro_source(
            source, original, parser, included_sources
        )
        if type_view == source:
            return original
        recovered = parser.parse(type_view).root_node
        return recovered if not recovered.has_error else original
    pragma_root = (
        parser.parse(pragma_source).root_node if pragma_source != source else original
    )
    working = _c_language_source(pragma_source, pragma_root)
    basis = parser.parse(working).root_node if working != source else original
    if not basis.has_error:
        type_view = type_argument_macro_source(working, basis, parser, included_sources)
        if type_view == working:
            return basis
        recovered = parser.parse(type_view).root_node
        return recovered if not recovered.has_error else basis
    fallback = basis if not original.has_error and complex_changed else original
    definitions = _input_definitions(working, basis, parser, included_sources)
    annotations = _resolve_annotations(definitions, parser)
    records = record_prefix_definitions(
        definitions.replacements, definitions.first_offsets, definitions.unsafe, parser
    )
    protected = _hash_lines(working, basis)
    projected = bytearray(record_prefix_source(working, basis, records, protected))
    pending = [basis]
    while pending:
        node = pending.pop()
        if node.type in _OPAQUE_NODES:
            continue
        if node.type in _IDENTIFIER_NODES:
            token = working[node.start_byte : node.end_byte]
            available = annotations.get(token)
            if (
                available is not None
                and node.start_byte >= available
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
    view = bytes(projected)
    loop_basis = basis if view == working else parser.parse(view).root_node
    view = type_argument_macro_source(view, loop_basis, parser, included_sources)
    loop_basis = parser.parse(view).root_node if view != working else loop_basis
    view = statement_argument_macro_source(view, loop_basis, parser, included_sources)
    loop_basis = parser.parse(view).root_node if view != working else loop_basis
    view = statement_macro_source(view, loop_basis, parser, included_sources)
    if view == working:
        return fallback
    recovered = parser.parse(view).root_node
    return fallback if recovered.has_error else recovered


def _projection_preserves_other_errors(
    source: bytes, original: Node, projected_source: bytes, projected: Node
) -> bool:
    """Allow a parse-only repair only when unrelated error nodes are unchanged.

    Parameters
    ----------
    source : bytes
        Original translation-unit bytes.
    original : tree_sitter.Node
        Original syntax tree.
    projected_source : bytes
        Equal-width parser-only projection.
    projected : tree_sitter.Node
        Syntax tree parsed from the projection.

    Returns
    -------
    bool
        Whether every error outside changed bytes remains at the same range.
    """
    changed = {
        index
        for index, (left, right) in enumerate(zip(source, projected_source))
        if left != right
    }

    def errors(root: Node) -> list[tuple[str, int, int, bool]]:
        result: list[tuple[str, int, int, bool]] = []
        pending = [root]
        while pending:
            node = pending.pop()
            if node.type == "ERROR" or node.is_missing:
                result.append(
                    (node.type, node.start_byte, node.end_byte, node.is_missing)
                )
            pending.extend(node.children)
        return result

    original_errors = errors(original)
    expected_empty_slots = {
        item
        for item in original_errors
        if item[0] == "identifier"
        and item[3]
        and any(item[1] in {offset, offset + 1} for offset in changed)
    }
    remaining_original = sorted(
        item for item in original_errors if item not in expected_empty_slots
    )
    projected_errors = sorted(errors(projected))
    return remaining_original == projected_errors


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
        standalone pragma prefixes. Siblings and comments bound the gap. A
        translation unit can omit leading projected whitespace from its span;
        that prefix is checked too, while an original UTF-8 BOM stays excluded.
    """
    parent = node.parent
    if parent is None:
        return node.start_byte
    previous = node.prev_sibling
    lower = (
        previous.end_byte
        if previous is not None
        else (0 if parent.type == "translation_unit" else parent.start_byte)
    )
    if lower == 0 and source.startswith(b"\xef\xbb\xbf"):
        lower = 3
    gap = source[lower : node.start_byte]
    if not gap.strip():
        return node.start_byte
    projected = parent.text
    if projected is None:
        return node.start_byte
    projected_gap = projected[
        max(0, lower - parent.start_byte) : node.start_byte - parent.start_byte
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
