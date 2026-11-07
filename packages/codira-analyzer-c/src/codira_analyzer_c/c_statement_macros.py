"""Recognize source-proven loop prefixes while preserving written call evidence.

Parameters
----------
None

Returns
-------
None
    Coordinate-preserving grammar hints, without expanding replacement bodies.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass
from functools import lru_cache
from itertools import chain

from tree_sitter import Language, Node, Parser

_IDENTIFIER = re.compile(rb"[A-Za-z_][A-Za-z_0-9]*\Z")
_TOKEN = re.compile(
    rb"(?P<space>\s+|/\*.*?\*/|//[^\n]*)"
    rb"|(?:u8|u|U|L)?(?:\"(?:[^\"\\\n]|\\[^\n])*\"|'(?:[^'\\\n]|\\[^\n])*')"
    rb"|[A-Za-z_][A-Za-z_0-9]*|##|[^\s]",
    re.DOTALL,
)
_C_TYPE_QUALIFIERS = frozenset({b"const", b"volatile", b"restrict", b"_Atomic"})
_C_TAG_KEYWORDS = frozenset({b"enum", b"struct", b"union"})
_C23_RESERVED_NON_TYPE_WORDS = frozenset(
    {
        b"_BitInt",
        b"alignas",
        b"alignof",
        b"constexpr",
        b"false",
        b"nullptr",
        b"static_assert",
        b"thread_local",
        b"true",
        b"typeof",
        b"typeof_unqual",
    }
)
_C_NON_TYPE_KEYWORDS = frozenset(
    {
        b"_Alignas",
        b"_Alignof",
        b"_Atomic",
        b"_Bool",
        b"_Complex",
        b"_Generic",
        b"_Imaginary",
        b"_Noreturn",
        b"_Static_assert",
        b"_Thread_local",
        b"auto",
        b"break",
        b"case",
        b"char",
        b"const",
        b"continue",
        b"default",
        b"do",
        b"double",
        b"else",
        b"enum",
        b"extern",
        b"float",
        b"for",
        b"goto",
        b"if",
        b"inline",
        b"int",
        b"long",
        b"register",
        b"restrict",
        b"return",
        b"short",
        b"signed",
        b"sizeof",
        b"static",
        b"struct",
        b"switch",
        b"typedef",
        b"union",
        b"unsigned",
        b"void",
        b"volatile",
        b"while",
    }
)
_C_BUILTIN_TYPE_SPELLINGS = frozenset(
    {
        (b"bool",),
        (b"_Bool",),
        (b"char",),
        (b"signed", b"char"),
        (b"unsigned", b"char"),
        (b"short",),
        (b"short", b"int"),
        (b"signed", b"short"),
        (b"signed", b"short", b"int"),
        (b"unsigned", b"short"),
        (b"unsigned", b"short", b"int"),
        (b"int",),
        (b"signed",),
        (b"signed", b"int"),
        (b"unsigned",),
        (b"unsigned", b"int"),
        (b"long",),
        (b"long", b"int"),
        (b"signed", b"long"),
        (b"signed", b"long", b"int"),
        (b"unsigned", b"long"),
        (b"unsigned", b"long", b"int"),
        (b"long", b"long"),
        (b"long", b"long", b"int"),
        (b"signed", b"long", b"long"),
        (b"signed", b"long", b"long", b"int"),
        (b"unsigned", b"long", b"long"),
        (b"unsigned", b"long", b"long", b"int"),
        (b"float",),
        (b"double",),
        (b"long", b"double"),
        (b"float", b"_Complex"),
        (b"double", b"_Complex"),
        (b"long", b"double", b"_Complex"),
        (b"void",),
    }
)
_C_BUILTIN_TYPE_KEYWORDS = frozenset(
    token for spelling in _C_BUILTIN_TYPE_SPELLINGS for token in spelling
)
_C_BUILTIN_TYPE_SPECIFIER_MULTISETS = frozenset(
    tuple(sorted(spelling)) for spelling in _C_BUILTIN_TYPE_SPELLINGS
)


@dataclass(frozen=True)
class _LoopDefinition:
    """Retain a fixed-arity replacement and its source availability boundary.

    Parameters
    ----------
    parameters : tuple[bytes, ...]
        Fixed parameter names; variadic definitions are held.
    tokens : tuple[bytes, ...]
        Unexpanded replacement tokens, with comments and splices removed.
    available_after : int
        Original source boundary after which the definition can be used.

    Returns
    -------
    None
        Immutable source evidence, not an expanded declaration or expression.
    """

    parameters: tuple[bytes, ...]
    tokens: tuple[bytes, ...]
    available_after: int


@dataclass(frozen=True)
class _FunctionDefinition:
    """Retain a bounded function-macro replacement for statement-role proof.

    Parameters
    ----------
    parameters : tuple[bytes, ...]
        Fixed parameter names in preprocessing order.
    tokens : tuple[bytes, ...]
        Replacement tokens with escaped newlines and comments removed.
    available_after : int
        Original source offset where a contained definition becomes visible.

    Returns
    -------
    None
        Immutable macro evidence used only for parser-view projection.
    """

    parameters: tuple[bytes, ...]
    tokens: tuple[bytes, ...]
    available_after: int
    direct_statement_arguments: frozenset[int]
    forwarded_statement_arguments: tuple[tuple[int, bytes, int], ...]
    direct_type_arguments: frozenset[int]
    forwarded_type_arguments: tuple[tuple[int, bytes, int], ...]


def _nodes(root: Node) -> Iterator[Node]:
    """Visit syntax nodes in source order without recursive Python calls.

    Parameters
    ----------
    root : tree_sitter.Node
        Root to visit.

    Returns
    -------
    collections.abc.Iterator[tree_sitter.Node]
        Deterministic depth-first traversal.
    """
    pending = [root]
    while pending:
        node = pending.pop()
        yield node
        pending.extend(reversed(node.children))


def _tokens(source: bytes) -> tuple[bytes, ...]:
    """Read structural tokens without interpreting macro replacement semantics.

    Parameters
    ----------
    source : bytes
        Replacement or argument bytes.

    Returns
    -------
    tuple[bytes, ...]
        Tokens retaining quoted delimiters as indivisible literals.
    """
    source = re.sub(rb"\\\r?\n", b"", source)
    return tuple(
        match[0] for match in _TOKEN.finditer(source) if match.lastgroup != "space"
    )


def _closing(tokens: tuple[bytes, ...], opening: int) -> int | None:
    """Find a matching structural delimiter while rejecting crossed groups.

    Parameters
    ----------
    tokens : tuple[bytes, ...]
        Tokens to inspect.
    opening : int
        Opening delimiter position.

    Returns
    -------
    int or None
        Closing index, or None for an unbalanced group.
    """
    pairs = {b"(": b")", b"[": b"]", b"{": b"}"}
    stack: list[bytes] = []
    for index in range(opening, len(tokens)):
        token = tokens[index]
        if token in pairs:
            stack.append(pairs[token])
        elif token in pairs.values():
            if not stack or stack.pop() != token:
                return None
            if not stack:
                return index
    return None


def _arity(tokens: tuple[bytes, ...]) -> int | None:
    """Count fixed preprocessing arguments using parentheses, not C expressions.

    Parameters
    ----------
    tokens : tuple[bytes, ...]
        Entire parenthesized invocation argument list.

    Returns
    -------
    int or None
        Argument count; zero for an empty list, None for invalid parentheses.
    """
    if not tokens or tokens[0] != b"(" or tokens[-1] != b")":
        return None
    if len(tokens) == 2:
        return 0
    depth = 0
    count = 1
    for token in tokens[1:-1]:
        if token == b"(":
            depth += 1
        elif token == b")":
            depth -= 1
            if depth < 0:
                return None
        elif token == b"," and depth == 0:
            count += 1
    return count if depth == 0 else None


def _loop_headers(tokens: tuple[bytes, ...]) -> bool:
    """Require a complete sequence of literal for headers with no supplied body.

    Parameters
    ----------
    tokens : tuple[bytes, ...]
        Unexpanded replacement-list tokens.

    Returns
    -------
    bool
        Whether each prefix has balanced delimiters and two header separators.
        This proves a statement-prefix role, not type or expression correctness.
    """
    index = 0
    heads = 0
    while index < len(tokens):
        if tokens[index : index + 2] != (b"for", b"("):
            return False
        closing = _closing(tokens, index + 1)
        if closing is None:
            return False
        depth = 0
        separators = 0
        for token in tokens[index + 2 : closing]:
            if token in (b"(", b"[", b"{"):
                depth += 1
            elif token in (b")", b"]", b"}"):
                depth -= 1
            elif token == b";" and depth == 0:
                separators += 1
        if separators != 2:
            return False
        heads += 1
        if heads > 8:
            return False
        index = closing + 1
    return bool(heads)


def _split_macro_arguments(
    tokens: tuple[bytes, ...],
) -> tuple[tuple[bytes, ...], ...] | None:
    """Split one preprocessing argument list using parenthesis nesting only.

    Parameters
    ----------
    tokens : tuple[bytes, ...]
        Tokens including the outer parentheses.

    Returns
    -------
    tuple[tuple[bytes, ...], ...] or None
        Exact fixed-arity arguments, or None for malformed parentheses.
    """
    if not tokens or tokens[0] != b"(" or tokens[-1] != b")":
        return None
    if len(tokens) == 2:
        return ()
    result: list[tuple[bytes, ...]] = []
    start = 1
    depth = 0
    for index, token in enumerate(tokens[1:-1], start=1):
        if token == b"(":
            depth += 1
        elif token == b")":
            depth -= 1
            if depth < 0:
                return None
        elif token == b"," and depth == 0:
            result.append(tokens[start:index])
            start = index + 1
    if depth != 0:
        return None
    result.append(tokens[start:-1])
    return tuple(result)


def _statement_role_proven(
    parameters: tuple[bytes, ...], tokens: tuple[bytes, ...], index: int, parser: Parser
) -> bool:
    """Check that substituting one parameter as a statement keeps C syntax.

    Parameters
    ----------
    parameters : tuple[bytes, ...]
        Fixed function-macro parameters.
    tokens : tuple[bytes, ...]
        Function-macro replacement tokens.
    index : int
        Candidate parameter position.
    parser : tree_sitter.Parser
        C parser used to validate the replacement shape.

    Returns
    -------
    bool
        Whether every occurrence of the candidate can occupy statement syntax.
    """
    if b"#" in tokens or b"##" in tokens or index >= len(parameters):
        return False
    target = parameters[index]
    occurrences = [position for position, token in enumerate(tokens) if token == target]
    if not occurrences:
        return False
    replacement: list[bytes] = []
    marker = b"if (1) return 0; else return 1;"
    for token in tokens:
        if token == target:
            replacement.append(marker)
        elif token in parameters:
            replacement.append(b"0")
        else:
            replacement.append(token)
    probe = b"void __codira_statement_probe(void) { " + b" ".join(replacement) + b" ; }"
    return not parser.parse(probe).root_node.has_error


def _forwarded_statement_arguments(
    parameters: tuple[bytes, ...], tokens: tuple[bytes, ...]
) -> tuple[tuple[int, bytes, int], ...]:
    """Find parameters forwarded unchanged to a nested function-like macro.

    Parameters
    ----------
    parameters : tuple[bytes, ...]
        Fixed parameters of the outer macro.
    tokens : tuple[bytes, ...]
        Replacement tokens of the outer macro.

    Returns
    -------
    tuple[tuple[int, bytes, int], ...]
        Outer parameter index, nested macro name and nested argument index.
    """
    result: list[tuple[int, bytes, int]] = []
    for position in range(len(tokens) - 1):
        name = tokens[position]
        if not _IDENTIFIER.fullmatch(name) or tokens[position + 1] != b"(":
            continue
        closing = _closing(tokens, position + 1)
        if closing is None:
            continue
        arguments = _split_macro_arguments(tokens[position + 1 : closing + 1])
        if arguments is None:
            continue
        for argument_index, argument in enumerate(arguments):
            if len(argument) == 1 and argument[0] in parameters:
                result.append((parameters.index(argument[0]), name, argument_index))
    return tuple(result)


def _direct_type_argument_positions(
    parameters: tuple[bytes, ...], tokens: tuple[bytes, ...]
) -> frozenset[int]:
    """Find parameters used only in explicit C type-name token positions.

    Parameters
    ----------
    parameters : tuple[bytes, ...]
        Fixed parameters of a function-like macro.
    tokens : tuple[bytes, ...]
        Replacement tokens of the macro.

    Returns
    -------
    frozenset[int]
        Parameter indexes whose every occurrence is in a cast or ``sizeof``
        type-name position. Other occurrences are left for forwarding proof.
    """
    direct: set[int] = set()
    for index, parameter in enumerate(parameters):
        positions = [
            token_index
            for token_index, token in enumerate(tokens)
            if token == parameter
        ]
        if not positions:
            continue
        valid = True
        has_cast_type = False
        for token_index in positions:
            cast_type = (
                token_index >= 1
                and token_index + 2 < len(tokens)
                and tokens[token_index - 1] == b"("
                and tokens[token_index + 1] == b"*"
                and tokens[token_index + 2] == b")"
            )
            has_cast_type = has_cast_type or cast_type
            sizeof_type = (
                token_index >= 2
                and token_index + 1 < len(tokens)
                and tokens[token_index - 2 : token_index] in ((b"sizeof", b"("),)
                and tokens[token_index + 1] == b")"
            )
            if not cast_type and not sizeof_type:
                valid = False
                break
        if valid and has_cast_type:
            direct.add(index)
    return frozenset(direct)


def _forwarded_type_arguments(
    parameters: tuple[bytes, ...], tokens: tuple[bytes, ...]
) -> tuple[tuple[int, bytes, int], ...]:
    """Find unchanged parameters forwarded to nested function-like macros.

    Parameters
    ----------
    parameters : tuple[bytes, ...]
        Fixed parameters of the outer macro.
    tokens : tuple[bytes, ...]
        Replacement tokens of the outer macro.

    Returns
    -------
    tuple[tuple[int, bytes, int], ...]
        Outer parameter index, nested macro name and nested argument index.
    """
    return tuple(
        item
        for item in _forwarded_statement_arguments(parameters, tokens)
        if item[1] not in {b"sizeof", b"_Alignof", b"_Generic"}
    )


def _type_argument_roles(
    definitions: dict[bytes, list[_FunctionDefinition]], unsafe: set[bytes]
) -> dict[bytes, tuple[int, ...]]:
    """Resolve type-valued argument positions across bounded macro forwarding.

    Parameters
    ----------
    definitions : dict[bytes, list[_FunctionDefinition]]
        Function-macro alternatives captured from source and included headers.
    unsafe : set[bytes]
        Macro names invalidated by undefinitions or unsupported definitions.

    Returns
    -------
    dict[bytes, tuple[int, ...]]
        Macro names and positions proven type-valued in every observed
        alternative. Unresolved cycles and mixed-use parameters are omitted.
    """
    accepted: dict[bytes, tuple[int, ...]] = {}
    for _ in range(64):
        changed = False
        for name, alternatives in definitions.items():
            if name in accepted or name in unsafe or not alternatives:
                continue
            arities = {len(item.parameters) for item in alternatives}
            if len(arities) != 1:
                continue
            valid_positions: list[int] = []
            for position in range(next(iter(arities))):
                valid = True
                for item in alternatives:
                    if position in item.direct_type_arguments:
                        continue
                    forwarded = [
                        (callee, callee_position)
                        for outer_position, callee, callee_position in item.forwarded_type_arguments
                        if outer_position == position
                    ]
                    occurrences = item.tokens.count(item.parameters[position])
                    direct_occurrences = sum(
                        1
                        for token_index, token in enumerate(item.tokens)
                        if token == item.parameters[position]
                        and (
                            (
                                token_index >= 1
                                and token_index + 2 < len(item.tokens)
                                and item.tokens[token_index - 1] == b"("
                                and item.tokens[token_index + 1] == b"*"
                                and item.tokens[token_index + 2] == b")"
                            )
                            or (
                                token_index >= 2
                                and token_index + 1 < len(item.tokens)
                                and item.tokens[token_index - 2 : token_index]
                                == (b"sizeof", b"(")
                                and item.tokens[token_index + 1] == b")"
                            )
                        )
                    )
                    cast_occurrences = sum(
                        1
                        for token_index, token in enumerate(item.tokens)
                        if token == item.parameters[position]
                        and token_index >= 1
                        and token_index + 2 < len(item.tokens)
                        and item.tokens[token_index - 1] == b"("
                        and item.tokens[token_index + 1] == b"*"
                        and item.tokens[token_index + 2] == b")"
                    )
                    if (
                        len(forwarded) + direct_occurrences != occurrences
                        or (not forwarded and not cast_occurrences)
                        or not all(
                            callee not in unsafe
                            and callee_position in accepted.get(callee, ())
                            for callee, callee_position in forwarded
                        )
                    ):
                        valid = False
                        break
                if valid:
                    valid_positions.append(position)
            if valid_positions:
                accepted[name] = tuple(valid_positions)
                changed = True
        if not changed:
            break
    return accepted


def _function_macro_definitions(
    source: bytes,
    root: Node,
    parser: Parser,
    included_sources: tuple[tuple[bytes, int], ...],
) -> tuple[dict[bytes, list[_FunctionDefinition]], set[bytes]]:
    """Capture fixed function-macro alternatives and invalidating directives.

    Parameters
    ----------
    source : bytes
        Source buffer in original coordinates.
    root : tree_sitter.Node
        Parse tree for the source buffer.
    parser : tree_sitter.Parser
        Parser used for captured header inputs and replacement validation.
    included_sources : tuple[tuple[bytes, int], ...]
        Contained header bytes and their source availability offsets.

    Returns
    -------
    tuple[dict[bytes, list[_FunctionDefinition]], set[bytes]]
        All observed alternatives and names invalidated by object definitions,
        undefinitions or unsupported parameter declarations.
    """
    definitions: dict[bytes, list[_FunctionDefinition]] = {}
    unsafe: set[bytes] = set()
    sources = ((source, -1, root),) + tuple(
        (header, boundary, parser.parse(header).root_node)
        for header, boundary in included_sources
    )
    for content, boundary, tree in sources:
        for node in _nodes(tree):
            if node.type == "preproc_call":
                match = re.match(
                    rb"#\s*undef\s+([A-Za-z_][A-Za-z_0-9]*)",
                    content[node.start_byte : node.end_byte],
                )
                if match:
                    unsafe.add(match[1])
                continue
            if node.type not in {"preproc_def", "preproc_function_def"}:
                continue
            name_node = node.child_by_field_name("name")
            if name_node is None:
                continue
            name = content[name_node.start_byte : name_node.end_byte]
            if node.type == "preproc_def":
                unsafe.add(name)
                continue
            parameter_node = node.child_by_field_name("parameters")
            value_node = node.child_by_field_name("value")
            if parameter_node is None:
                unsafe.add(name)
                continue
            parameter_tokens = _tokens(
                content[parameter_node.start_byte : parameter_node.end_byte]
            )
            if (
                len(parameter_tokens) < 2
                or parameter_tokens[0] != b"("
                or parameter_tokens[-1] != b")"
            ):
                unsafe.add(name)
                continue
            interior = parameter_tokens[1:-1]
            parameters = interior[::2]
            if (
                any(not _IDENTIFIER.fullmatch(token) for token in parameters)
                or len(parameters) != len(set(parameters))
                or interior[1::2] != (b",",) * max(0, len(parameters) - 1)
            ):
                unsafe.add(name)
                continue
            replacement_tokens = (
                _tokens(content[value_node.start_byte : value_node.end_byte])
                if value_node is not None
                else ()
            )
            definitions.setdefault(name, []).append(
                _FunctionDefinition(
                    parameters,
                    replacement_tokens,
                    node.end_byte if boundary < 0 else boundary,
                    frozenset(
                        index
                        for index in range(len(parameters))
                        if _statement_role_proven(
                            parameters, replacement_tokens, index, parser
                        )
                    ),
                    _forwarded_statement_arguments(parameters, replacement_tokens),
                    _direct_type_argument_positions(parameters, replacement_tokens),
                    _forwarded_type_arguments(parameters, replacement_tokens),
                )
            )
    return definitions, unsafe


def _statement_argument_roles(
    definitions: dict[bytes, list[_FunctionDefinition]], unsafe: set[bytes]
) -> dict[bytes, tuple[int, ...]]:
    """Resolve only argument positions proven as statements in every alternative.

    Parameters
    ----------
    definitions : dict[bytes, list[_FunctionDefinition]]
        Function-macro alternatives from source and contained headers.
    unsafe : set[bytes]
        Macro names with object definitions, undefinitions or unsupported forms.

    Returns
    -------
    dict[bytes, tuple[int, ...]]
        Macro names and statement-valued parameter indices shared by all
        alternatives. Unresolved forwarding cycles remain absent.
    """
    accepted: dict[bytes, tuple[int, ...]] = {}
    for _ in range(64):
        changed = False
        for name, alternatives in definitions.items():
            if name in accepted or name in unsafe or not alternatives:
                continue
            arities = {len(item.parameters) for item in alternatives}
            if len(arities) != 1:
                continue
            arity = next(iter(arities))
            valid_positions: list[int] = []
            for position in range(arity):
                valid = True
                for item in alternatives:
                    if position in item.direct_statement_arguments:
                        continue
                    forwarded = [
                        (callee, callee_position)
                        for outer_position, callee, callee_position in item.forwarded_statement_arguments
                        if outer_position == position
                    ]
                    occurrences = item.tokens.count(item.parameters[position])
                    if (
                        not forwarded
                        or len(forwarded) != occurrences
                        or not all(
                            callee not in unsafe
                            and callee_position in accepted.get(callee, ())
                            for callee, callee_position in forwarded
                        )
                    ):
                        valid = False
                        break
                if valid:
                    valid_positions.append(position)
            if valid_positions:
                accepted[name] = tuple(valid_positions)
                changed = True
        if not changed:
            break
    return accepted


def _skip_source_trivia(source: bytes, offset: int, end: int) -> int | None:
    """Skip whitespace and comments without crossing an escaped newline.

    Parameters
    ----------
    source : bytes
        Physical source buffer.
    offset : int
        First byte to inspect.
    end : int
        Exclusive bound for the current invocation or argument.

    Returns
    -------
    int or None
        First non-trivia byte, or None for an unterminated comment or splice.
    """
    while offset < end:
        if source[offset] in b" \t\r\n\f\v":
            offset += 1
        elif (
            source[offset : offset + 2] == b"\\\n"
            or source[offset : offset + 3] == b"\\\r\n"
        ):
            return None
        elif source[offset : offset + 2] == b"/*":
            closing = source.find(b"*/", offset + 2, end)
            if closing < 0:
                return None
            offset = closing + 2
        elif source[offset : offset + 2] == b"//":
            closing = source.find(b"\n", offset + 2, end)
            if closing < 0:
                return end
            offset = closing + 1
        else:
            return offset
    return offset


def _source_invocation_arguments(
    source: bytes, opening: int
) -> tuple[tuple[int, int], ...] | None:
    """Locate source argument spans with preprocessing comma rules.

    Parameters
    ----------
    source : bytes
        Physical source buffer.
    opening : int
        Offset of the invocation's opening parenthesis.

    Returns
    -------
    tuple[tuple[int, int], ...] or None
        Argument byte spans, or None for malformed or spliced invocations.
    """
    if opening >= len(source) or source[opening] != 40:
        return None
    result: list[tuple[int, int]] = []
    start = opening + 1
    depth = 0
    offset = start
    quote = 0
    while offset < len(source):
        byte = source[offset]
        if byte == 92 and source[offset : offset + 2] in {b"\\\n", b"\\\r"}:
            return None
        if quote:
            if byte == 92:
                offset += 2
                continue
            if byte == quote:
                quote = 0
        elif byte in (34, 39):
            quote = byte
        elif source[offset : offset + 2] == b"/*":
            closing = source.find(b"*/", offset + 2)
            if closing < 0:
                return None
            offset = closing + 2
            continue
        elif source[offset : offset + 2] == b"//":
            closing = source.find(b"\n", offset + 2)
            if closing < 0:
                return None
            offset = closing + 1
            continue
        elif byte == 40:
            depth += 1
        elif byte == 41:
            if depth == 0:
                if not result and not source[start:offset].strip():
                    return ()
                result.append((start, offset))
                return tuple(result)
            depth -= 1
        elif byte == 44 and depth == 0:
            result.append((start, offset))
            start = offset + 1
        offset += 1
    return None


def _has_preprocessing_identifier_left_boundary(source: bytes, offset: int) -> bool:
    """Check that an ASCII macro-name match starts a whole C identifier.

    Parameters
    ----------
    source : bytes
        Original source bytes, before phase-two line splicing.
    offset : int
        Start byte of the ASCII candidate identifier.

    Returns
    -------
    bool
        Whether the preceding preprocessing-token bytes prove a boundary.
        Non-ASCII bytes, dollar signs, universal-character-name prefixes and
        physical line splices are handled conservatively.
    """
    cursor = offset
    while cursor:
        if source[cursor - 1 : cursor] == b"\n":
            if cursor >= 2 and source[cursor - 2 : cursor] == b"\\\n":
                cursor -= 2
                continue
            if cursor >= 3 and source[cursor - 3 : cursor] == b"\\\r\n":
                cursor -= 3
                continue
        break
    if cursor == 0:
        return True
    previous = source[cursor - 1]
    return not (
        48 <= previous <= 57
        or 65 <= previous <= 90
        or 97 <= previous <= 122
        or previous in (36, 92, 95)
        or previous >= 0x80
    )


def statement_argument_macro_source(
    source: bytes,
    root: Node,
    parser: Parser,
    included_sources: tuple[tuple[bytes, int], ...] = (),
) -> bytes:
    """Blank only a leading return/goto keyword in a proven macro statement arg.

    Parameters
    ----------
    source : bytes
        Equal-width parser-view source in original coordinates.
    root : tree_sitter.Node
        Parse tree for exactly that source view.
    parser : tree_sitter.Parser
        Parser used for contained header and replacement-shape evidence.
    included_sources : tuple[tuple[bytes, int], ...], optional
        Captured headers with original availability boundaries.

    Returns
    -------
    bytes
        Same-length parser view preserving invocation and argument source bytes
        except for proven statement keywords. Callers must require a clean final
        tree before accepting the view.
    """
    definitions, unsafe = _function_macro_definitions(
        source, root, parser, included_sources
    )
    if not definitions:
        return source
    opaque = [
        (node.start_byte, node.end_byte)
        for node in _nodes(root)
        if node.type
        in {
            "comment",
            "string_literal",
            "raw_string_literal",
            "char_literal",
            "preproc_call",
            "preproc_def",
            "preproc_function_def",
            "preproc_include",
        }
    ]
    projected = bytearray(source)
    changed = False
    for match in re.finditer(rb"[A-Za-z_][A-Za-z_0-9]*", source):
        if not _has_preprocessing_identifier_left_boundary(source, match.start()):
            continue
        name = match[0]
        if name not in definitions or any(
            start <= match.start() < end for start, end in opaque
        ):
            continue
        opening = _skip_source_trivia(source, match.end(), len(source))
        if opening is None or opening >= len(source) or source[opening] != 40:
            continue
        eligible = {
            macro_name: [
                definition
                for definition in alternatives
                if definition.available_after <= match.start()
            ]
            for macro_name, alternatives in definitions.items()
        }
        eligible = {
            macro_name: alternatives
            for macro_name, alternatives in eligible.items()
            if alternatives
        }
        roles = _statement_argument_roles(eligible, unsafe)
        role_positions = roles.get(name)
        if not role_positions:
            continue
        arguments = _source_invocation_arguments(source, opening)
        if arguments is None or len(arguments) != len(eligible[name][0].parameters):
            continue
        for index in role_positions:
            if index >= len(arguments):
                continue
            argument_start, argument_end = arguments[index]
            token_start = _skip_source_trivia(source, argument_start, argument_end)
            if token_start is None or token_start >= argument_end:
                continue
            keyword = next(
                (
                    token
                    for token in (b"return", b"goto")
                    if source.startswith(token, token_start, argument_end)
                ),
                None,
            )
            if keyword is None:
                continue
            token_end = token_start + len(keyword)
            suffix = source[token_end : token_end + 1]
            if token_end >= argument_end or (
                suffix
                and (
                    suffix.isalnum()
                    or suffix == b"_"
                    or suffix == b"$"
                    or suffix[0] >= 0x80
                    or suffix == b"\\"
                )
            ):
                continue
            if _skip_source_trivia(source, token_end, argument_end) == argument_end:
                continue
            projected[token_start:token_end] = b" " * len(keyword)
            changed = True
    return bytes(projected) if changed else source


def _parser_accepts_type_name(tokens: tuple[bytes, ...], parser: Parser) -> bool:
    """Check tokens in the C parser's type-name grammar position.

    Parameters
    ----------
    tokens : tuple[bytes, ...]
        Candidate type-name tokens.
    parser : tree_sitter.Parser
        C parser used to validate syntax only.

    Returns
    -------
    bool
        Whether a synthetic typedef declaration parses without errors.
    """
    probe = b"typedef " + b" ".join(tokens) + b" __codira_type_probe;"
    return not parser.parse(probe).root_node.has_error


@lru_cache(maxsize=4)
def _parser_reserved_type_words(language: Language) -> frozenset[bytes]:
    """Derive reserved word spellings from the active C grammar inventory.

    Parameters
    ----------
    language : tree_sitter.Language
        Exact grammar language used by the C parser.

    Returns
    -------
    frozenset[bytes]
        Identifier-shaped visible grammar tokens that cannot occupy the type
        position of a synthetic typedef declaration.
    """
    grammar_parser = Parser(language)
    reserved: set[bytes] = set()
    for symbol_id in range(language.node_kind_count):
        spelling = language.node_kind_for_id(symbol_id)
        if (
            not language.node_kind_is_visible(symbol_id)
            or spelling is None
            or not _IDENTIFIER.fullmatch(spelling.encode())
        ):
            continue
        token = spelling.encode()
        tree = grammar_parser.parse(b"typedef " + token + b" __codira_keyword_probe;")
        definition = tree.root_node.named_children
        type_node = definition[0].child_by_field_name("type") if definition else None
        if (
            tree.root_node.has_error
            or type_node is None
            or type_node.type != "type_identifier"
        ):
            reserved.add(token)
    return frozenset(reserved)


def _safe_type_argument_tokens(
    source: bytes,
    definitions: dict[bytes, list[_FunctionDefinition]],
    unsafe: set[bytes],
    parser: Parser,
    parser_reserved_words: frozenset[bytes],
) -> bool:
    """Accept only a bounded, call-free C type-name spelling for projection.

    Parameters
    ----------
    source : bytes
        One physical macro argument span.
    definitions : dict[bytes, list[_FunctionDefinition]]
        Captured function-like macro names.
    unsafe : set[bytes]
        Names with object-like or otherwise unsupported definitions.
    parser : tree_sitter.Parser
        C parser used to check the spelling in a type-name grammar position.
    parser_reserved_words : frozenset[bytes]
        Reserved words derived from the parser's visible grammar inventory.

    Returns
    -------
    bool
        Whether the argument is a bounded C type-name spelling with no calls,
        declarators, operators, reserved non-type keywords or invalid built-in
        specifier sequence.
    """
    tokens = _tokens(source)
    if not tokens or any(
        not _IDENTIFIER.fullmatch(token) and token != b"*" for token in tokens
    ):
        return False
    if any(token in unsafe or token in definitions for token in tokens):
        return False
    reserved_words = (
        _C_NON_TYPE_KEYWORDS | _C23_RESERVED_NON_TYPE_WORDS | parser_reserved_words
    )
    if any(
        token in reserved_words
        and token not in _C_TYPE_QUALIFIERS
        and token not in _C_TAG_KEYWORDS
        and token not in _C_BUILTIN_TYPE_KEYWORDS
        for token in tokens
    ):
        return False
    if b"*" in tokens:
        first_pointer = tokens.index(b"*")
        base = tokens[:first_pointer]
        suffix = tokens[first_pointer:]
        if any(token != b"*" and token not in _C_TYPE_QUALIFIERS for token in suffix):
            return False
    else:
        base = tokens
    tag_positions = [
        index for index, token in enumerate(base) if token in _C_TAG_KEYWORDS
    ]
    if tag_positions:
        if len(tag_positions) != 1:
            return False
        tag_index = tag_positions[0]
        tag_prefix = base[:tag_index]
        tag_name_index = tag_index + 1
        if (
            any(token not in _C_TYPE_QUALIFIERS for token in tag_prefix)
            or tag_name_index >= len(base)
            or not _IDENTIFIER.fullmatch(base[tag_name_index])
            or base[tag_name_index] in reserved_words
            or any(
                token not in _C_TYPE_QUALIFIERS for token in base[tag_name_index + 1 :]
            )
        ):
            return False
        return _parser_accepts_type_name(tokens, parser)
    base = tuple(token for token in base if token not in _C_TYPE_QUALIFIERS)
    if not base:
        return False
    if tuple(sorted(base)) in _C_BUILTIN_TYPE_SPECIFIER_MULTISETS:
        return _parser_accepts_type_name(tokens, parser)
    if len(base) == 1:
        if base[0] in reserved_words and base[0] not in _C_BUILTIN_TYPE_KEYWORDS:
            return False
        return _parser_accepts_type_name(tokens, parser)
    return False


def type_argument_macro_source(
    source: bytes,
    root: Node,
    parser: Parser,
    included_sources: tuple[tuple[bytes, int], ...] = (),
) -> bytes:
    """Replace only proven simple type-name macro arguments in a parser view.

    Parameters
    ----------
    source : bytes
        Equal-width parser-view source in original coordinates.
    root : tree_sitter.Node
        Parse tree for exactly that source view.
    parser : tree_sitter.Parser
        Parser used for contained header and replacement-shape evidence.
    included_sources : tuple[tuple[bytes, int], ...], optional
        Captured headers with original availability boundaries.

    Returns
    -------
    bytes
        Same-length view with a proven type-only argument replaced by an
        expression placeholder. The macro invocation, other arguments and
        original source remain available to extraction.
    """
    definitions, unsafe = _function_macro_definitions(
        source, root, parser, included_sources
    )
    if not definitions:
        return source
    opaque = [
        (node.start_byte, node.end_byte)
        for node in _nodes(root)
        if node.type
        in {
            "comment",
            "string_literal",
            "raw_string_literal",
            "char_literal",
            "preproc_call",
            "preproc_def",
            "preproc_function_def",
            "preproc_include",
        }
    ]
    projected = bytearray(source)
    changed = False
    parser_reserved_words: frozenset[bytes] | None = None
    for match in re.finditer(rb"[A-Za-z_][A-Za-z_0-9]*", source):
        if not _has_preprocessing_identifier_left_boundary(source, match.start()):
            continue
        name = match[0]
        if name not in definitions or any(
            start <= match.start() < end for start, end in opaque
        ):
            continue
        opening = _skip_source_trivia(source, match.end(), len(source))
        if opening is None or opening >= len(source) or source[opening] != 40:
            continue
        eligible = {
            macro_name: [
                definition
                for definition in alternatives
                if definition.available_after <= match.start()
            ]
            for macro_name, alternatives in definitions.items()
        }
        eligible = {
            macro_name: alternatives
            for macro_name, alternatives in eligible.items()
            if alternatives
        }
        role_positions = _type_argument_roles(eligible, unsafe).get(name)
        if not role_positions:
            continue
        if parser_reserved_words is None:
            parser_reserved_words = _parser_reserved_type_words(parser.language)
        arguments = _source_invocation_arguments(source, opening)
        if arguments is None or len(arguments) != len(eligible[name][0].parameters):
            continue
        for index in role_positions:
            if index >= len(arguments):
                continue
            start, end = arguments[index]
            raw_argument = source[start:end]
            if not _safe_type_argument_tokens(
                raw_argument,
                eligible,
                unsafe,
                parser,
                parser_reserved_words,
            ):
                continue
            value = _skip_source_trivia(source, start, end)
            if value is None or value >= end:
                continue
            for position in range(start, end):
                if source[position] not in (10, 13):
                    projected[position] = 32
            projected[value] = 48
            changed = True
    return bytes(projected) if changed else source


def _definitions(
    source: bytes,
    root: Node,
    parser: Parser,
    included_sources: tuple[tuple[bytes, int], ...],
) -> tuple[dict[bytes, list[_LoopDefinition]], set[bytes]]:
    """Collect all observed alternatives without choosing compilation branches.

    Parameters
    ----------
    source : bytes
        Original-coordinate source buffer.
    root : tree_sitter.Node
        Tree for that buffer.
    parser : tree_sitter.Parser
        Parser for captured contained headers.
    included_sources : tuple[tuple[bytes, int], ...]
        Header bytes and original include availability boundaries.

    Returns
    -------
    tuple[dict[bytes, list[_LoopDefinition]], set[bytes]]
        Function alternatives and names invalidated by unsupported definitions
        or undefinitions. Keyword overrides invalidate the entire projection.
    """
    result: dict[bytes, list[_LoopDefinition]] = {}
    unsafe: set[bytes] = set()
    for content, boundary, tree in chain(
        ((source, -1, root),),
        (
            (raw, offset, parser.parse(raw).root_node)
            for raw, offset in included_sources
        ),
    ):
        for node in _nodes(tree):
            if node.type == "preproc_call":
                match = re.match(
                    rb"#\s*undef\s+([A-Za-z_][A-Za-z_0-9]*)",
                    content[node.start_byte : node.end_byte],
                )
                if match:
                    unsafe.add(match[1])
                continue
            if node.type not in {"preproc_def", "preproc_function_def"}:
                continue
            name_node = node.child_by_field_name("name")
            if name_node is None:
                continue
            name = content[name_node.start_byte : name_node.end_byte]
            if name in {b"for", b"while"} or node.type == "preproc_def":
                unsafe.add(name)
                continue
            parameters = node.child_by_field_name("parameters")
            value = node.child_by_field_name("value")
            if parameters is None:
                unsafe.add(name)
                continue
            raw_parameters = _tokens(
                content[parameters.start_byte : parameters.end_byte]
            )
            if (
                len(raw_parameters) < 2
                or raw_parameters[0] != b"("
                or raw_parameters[-1] != b")"
            ):
                unsafe.add(name)
                continue
            interior = raw_parameters[1:-1]
            names = interior[::2]
            if (
                any(
                    not _IDENTIFIER.fullmatch(token) or token in {b"for", b"while"}
                    for token in names
                )
                or len(names) != len(set(names))
                or interior[1::2] != (b",",) * max(0, len(names) - 1)
            ):
                unsafe.add(name)
                continue
            result.setdefault(name, []).append(
                _LoopDefinition(
                    names,
                    _tokens(content[value.start_byte : value.end_byte])
                    if value
                    else (),
                    node.end_byte if boundary < 0 else boundary,
                )
            )
    return result, unsafe


def _roles(
    definitions: dict[bytes, list[_LoopDefinition]], unsafe: set[bytes]
) -> dict[bytes, tuple[int, int]]:
    """Resolve compatible direct and forwarding statement-prefix alternatives.

    Parameters
    ----------
    definitions : dict[bytes, list[_LoopDefinition]]
        All captured function-macro alternatives.
    unsafe : set[bytes]
        Invalidated names.

    Returns
    -------
    dict[bytes, tuple[int, int]]
        Accepted macro names mapped to fixed arity and latest availability.
        Aliases unresolved after 64 passes remain held.
    """
    if unsafe & {b"for", b"while"}:
        return {}
    accepted: dict[bytes, tuple[int, int]] = {}
    for _ in range(64):
        changed = False
        for name, alternatives in definitions.items():
            if (
                name in accepted
                or name in unsafe
                or len({len(item.parameters) for item in alternatives}) != 1
            ):
                continue
            available = 0
            valid = True
            for item in alternatives:
                available = max(available, item.available_after)
                if _loop_headers(item.tokens):
                    continue
                tokens = item.tokens
                if (
                    len(tokens) < 3
                    or tokens[0] in item.parameters
                    or tokens[0] not in accepted
                    or tokens[1] != b"("
                    or _closing(tokens, 1) != len(tokens) - 1
                    or _arity(tokens[1:]) != accepted[tokens[0]][0]
                ):
                    valid = False
                    break
                available = max(available, accepted[tokens[0]][1])
            if valid:
                accepted[name] = (len(alternatives[0].parameters), available)
                changed = True
        if not changed:
            break
    return accepted


def statement_macro_source(
    source: bytes,
    root: Node,
    parser: Parser,
    included_sources: tuple[tuple[bytes, int], ...] = (),
) -> bytes:
    """Provide equal-width loop grammar hints for proven statement invocations.

    Parameters
    ----------
    source : bytes
        Original-coordinate grammar buffer.
    root : tree_sitter.Node
        Tree for exactly that buffer.
    parser : tree_sitter.Parser
        Parser used for contained definition evidence.
    included_sources : tuple[tuple[bytes, int], ...], optional
        Captured headers with original availability boundaries.

    Returns
    -------
    bytes
        Unchanged bytes or a same-coordinate parser view. Callers must require
        a fully clean final tree and preserve projected macro-call evidence.
        Names shorter than ``while`` remain held rather than shifting offsets.
        An orphan else misread by the provider as a type cannot become clean.
    """
    candidates: list[tuple[Node, Node, Node]] = []
    for node in _nodes(root):
        if node.type != "call_expression":
            continue
        parent = node.parent
        function = node.child_by_field_name("function")
        arguments = node.child_by_field_name("arguments")
        if (
            parent is not None
            and parent.type == "expression_statement"
            and len(parent.named_children) == 1
            and parent.named_children[0] == node
            and any(child.type == ";" and child.is_missing for child in parent.children)
            and function is not None
            and function.type == "identifier"
            and function.end_byte - function.start_byte >= 5
            and arguments is not None
            and not arguments.has_error
        ):
            candidates.append((node, function, arguments))
    if not candidates:
        return source
    definitions, unsafe = _definitions(source, root, parser, included_sources)
    roles = _roles(definitions, unsafe)
    projected = bytearray(source)
    for node, function, arguments in candidates:
        role = roles.get(source[function.start_byte : function.end_byte])
        if role is None or node.start_byte < role[1]:
            continue
        actual = _arity(_tokens(source[arguments.start_byte : arguments.end_byte]))
        if actual == 0 and role[0] == 1:
            actual = 1
        if actual != role[0]:
            continue
        projected[function.start_byte : function.end_byte] = b"while".ljust(
            function.end_byte - function.start_byte
        )
    view = bytes(projected)
    if view != source and any(
        node.type == "type_identifier" and node.text == b"else"
        for node in _nodes(parser.parse(view).root_node)
    ):
        return source
    return view


def projected_statement_macro_name(node: Node, source: bytes) -> str | None:
    """Recover the written callee from a proven loop grammar projection.

    Parameters
    ----------
    node : tree_sitter.Node
        Candidate projected while statement.
    source : bytes
        Original source, separate from the parser's equal-width view.

    Returns
    -------
    str or None
        Original macro name when the parsed keyword differs from source text.
    """
    if node.type != "while_statement" or not node.children:
        return None
    keyword = node.children[0]
    if keyword.type != "while" or keyword.text != b"while":
        return None
    match = re.match(rb"[A-Za-z_][A-Za-z_0-9]*", source[node.start_byte :])
    if match is None or match[0] == b"while":
        return None
    return match[0].decode("ascii")
