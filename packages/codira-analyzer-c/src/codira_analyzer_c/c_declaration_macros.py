"""Expand selected source backed C declaration macros within strict bounds.

Parameters
----------
None

Returns
-------
None
    Provides opt in declaration expansion with exact captured input evidence.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, replace
from pathlib import Path

from .c_include_context import IncludeContext
from .c_parser import _new_parser
from .c_preprocessing import _input_definitions, _resolve_annotations

_TOKEN = re.compile(
    rb"/\*.*?\*/|//[^\r\n]*|(?:u8|u|U|L)?\"(?:\\.|[^\"\\])*\"|"
    rb"(?:u8|u|U|L)?'(?:\\.|[^'\\])*'|"
    rb"[A-Za-z_][A-Za-z_0-9]*|[0-9][A-Za-z_0-9.]*|"
    rb"##|\.\.\.|->\*|->|\+\+|--|<<=|>>=|<=|>=|==|!=|&&|\|\||"
    rb"\+=|-=|\*=|/=|%=|&=|\^=|\|=|<<|>>|[^\s]",
    re.DOTALL,
)
_IDENTIFIER = re.compile(rb"[A-Za-z_][A-Za-z_0-9]*\Z")
_DIRECTIVE = re.compile(rb"(?m)^[ \t]*#[ \t]*([A-Za-z_][A-Za-z_0-9]*)\b([^\r\n]*)")
_DEFINE = re.compile(rb"^\s*([A-Za-z_][A-Za-z_0-9]*)(\((.*?)\))?[ \t]*(.*)$", re.DOTALL)
_MAX_EXPANSIONS = 128
_MAX_TOKENS = 16_384
_MAX_BYTES = 131_072


@dataclass(frozen=True)
class MacroToken:
    """Retain one preprocessing token and its original argument span.

    Parameters
    ----------
    spelling : bytes
        Token spelling without surrounding whitespace or comments.
    start : int
        Original translation unit start, when the token came from an argument.
    end : int
        Original translation unit end, when the token came from an argument.
    """

    spelling: bytes
    start: int | None = None
    end: int | None = None


@dataclass(frozen=True)
class MacroDefinition:
    """Bind a function like macro to its exact captured source replacement.

    Parameters
    ----------
    name : bytes
        Macro identifier.
    parameters : tuple[bytes, ...] or None
        Fixed parameter names; None identifies an object like macro.
    variadic : bool
        Whether additional arguments are accepted as ``__VA_ARGS__``.
    replacement : tuple[MacroToken, ...]
        Tokenized replacement list.
    source_path : str
        Repository relative defining source or header path.
    source_sha256 : str
        Digest of the exact captured source bytes.
    source_order : int
        Ordinal of the executed definition directive through nested includes.
    conditional : bool
        Whether an unresolved conditional controls this definition. Such a
        replacement is evidence only and cannot drive declaration expansion.
    span : tuple[int, int]
        Original directive range in the defining source.
    available_after : int
        Translation unit byte offset where a captured header becomes visible.

    Returns
    -------
    None
        Immutable definition and its captured directive identity.
    """

    name: bytes
    parameters: tuple[bytes, ...] | None
    variadic: bool
    replacement: tuple[MacroToken, ...]
    source_path: str
    source_sha256: str
    source_order: int
    conditional: bool
    replacement_sha256: str
    span: tuple[int, int]
    available_after: int


@dataclass(frozen=True)
class ExpandedDeclaration:
    """Describe one completely expanded file scope macro invocation.

    Parameters
    ----------
    start : int
        Original invocation start byte.
    end : int
        Original invocation end byte.
    name : str
        Selected outer macro identifier.
    source : bytes
        Isolated generated declaration source for the C parser.
    tokens : tuple[tuple[bytes, tuple[int, int] | None, tuple[int, int]], ...]
        Generated spelling, original argument span, and generated-buffer span.
    definitions : tuple[MacroDefinition, ...]
        Exact definition chain used to produce the expansion.
    """

    start: int
    end: int
    name: str
    source: bytes
    tokens: tuple[tuple[bytes, tuple[int, int] | None, tuple[int, int]], ...]
    definitions: tuple[MacroDefinition, ...]


class ExpansionRejected(ValueError):
    """Signal that expansion cannot be proven complete for this invocation."""


def _tokens(source: bytes, offset: int = 0) -> tuple[MacroToken, ...]:
    """Tokenize C preprocessing text while discarding comments and whitespace.

    Parameters
    ----------
    source : bytes
        Original or replacement-list bytes.
    offset : int, optional
        Translation unit offset for source invocation arguments.

    Returns
    -------
    tuple[MacroToken, ...]
        Bounded preprocessing tokens.
    """
    clean = bytearray()
    original_offsets: list[int] = []
    position = 0
    while position < len(source):
        if source[position : position + 2] == b"\\\n":
            position += 2
            continue
        if source[position : position + 3] == b"\\\r\n":
            position += 3
            continue
        clean.append(source[position])
        original_offsets.append(position)
        position += 1
    normalized = bytes(clean)
    result = tuple(
        MacroToken(
            match[0],
            None
            if re.search(
                rb"\\\r?\n",
                source[
                    original_offsets[match.start()] : original_offsets[match.end() - 1]
                    + 1
                ],
            )
            else offset + original_offsets[match.start()],
            None
            if re.search(
                rb"\\\r?\n",
                source[
                    original_offsets[match.start()] : original_offsets[match.end() - 1]
                    + 1
                ],
            )
            else offset + original_offsets[match.end() - 1] + 1,
        )
        for match in _TOKEN.finditer(normalized)
        if not match[0].startswith((b"/*", b"//"))
    )
    if len(result) > _MAX_TOKENS:
        raise ExpansionRejected("macro token bound exceeded")
    return result


def _mask_comments(source: bytes) -> bytes:
    """Replace comments with spaces while preserving C lexical positions.

    Parameters
    ----------
    source : bytes
        Captured source or header bytes.

    Returns
    -------
    bytes
        Same-length bytes with comment contents blanked.
    """
    output = bytearray(source)
    index = 0
    quote: int | None = None
    block_comment = False
    line_comment = False
    while index < len(source):
        byte = source[index]
        following = source[index + 1] if index + 1 < len(source) else -1
        if line_comment:
            spliced_newline = (
                (byte == 10 and index > 0 and source[index - 1] == 92)
                or (
                    byte == 13
                    and following == 10
                    and index > 0
                    and source[index - 1] == 92
                )
                or (
                    byte == 10
                    and index > 1
                    and source[index - 1] == 13
                    and source[index - 2] == 92
                )
            )
            if byte in (10, 13):
                if not spliced_newline:
                    line_comment = False
            else:
                output[index] = 32
        elif block_comment:
            if byte in (10, 13):
                pass
            else:
                output[index] = 32
            if byte == 42 and following == 47:
                output[index + 1] = 32
                block_comment = False
                index += 1
        elif quote is not None:
            if byte == 92:
                index += 1
            elif byte == quote:
                quote = None
        elif byte in (34, 39):
            quote = byte
        elif byte == 47 and following == 42:
            output[index] = output[index + 1] = 32
            block_comment = True
            index += 1
        elif byte == 47 and following == 47:
            output[index] = output[index + 1] = 32
            line_comment = True
            index += 1
        index += 1
    return bytes(output)


def _conditionals_balanced(source: bytes) -> bool:
    """Check that conditional directives form complete, ordered groups.

    Parameters
    ----------
    source : bytes
        Captured source or header bytes.

    Returns
    -------
    bool
        Whether all conditional groups have valid branch structure.
    """
    stack: list[bool] = []
    for _, _, kind, _ in _directive_rows(source):
        if kind in {b"if", b"ifdef", b"ifndef"}:
            stack.append(False)
        elif kind in {b"else", b"elif"}:
            if not stack or (kind == b"else" and stack[-1]):
                return False
            if kind == b"else":
                stack[-1] = True
            elif stack[-1]:
                return False
        elif kind == b"endif":
            if not stack:
                return False
            stack.pop()
    return not stack


def _directive_rows(source: bytes) -> tuple[tuple[int, int, bytes, bytes], ...]:
    """Read preprocessor directives, including continued replacement lines.

    Parameters
    ----------
    source : bytes
        Captured source or header bytes.

    Returns
    -------
    tuple[tuple[int, int, bytes, bytes], ...]
        Directive start, end, keyword and payload.
    """
    rows: list[tuple[int, int, bytes, bytes]] = []
    masked = _mask_comments(source)
    for match in _DIRECTIVE.finditer(masked):
        start = match.start()
        previous_line_end = source.rfind(b"\n", 0, start)
        previous_line = (
            source[source.rfind(b"\n", 0, previous_line_end) + 1 : previous_line_end]
            if previous_line_end >= 0
            else b""
        )
        if previous_line.rstrip(b"\r\t ").endswith(b"\\"):
            continue
        end = match.end()
        while source[start:end].rstrip(b"\r\n \t").endswith(b"\\") and end < len(
            source
        ):
            line_end = source.find(b"\n", end)
            if line_end < 0:
                line_end = len(source)
            end = min(len(source), line_end + 1)
        payload = masked[match.end(1) : end].strip()
        rows.append((start, end, match[1], payload))
    return tuple(rows)


def _include_guard(
    source: bytes, directives: tuple[tuple[int, int, bytes, bytes], ...]
) -> bytes | None:
    """Return a canonical whole file include guard, if structurally present.

    Parameters
    ----------
    source : bytes
        Header bytes containing the candidate guard.
    directives : tuple[tuple[int, int, bytes, bytes], ...]
        Scanned preprocessor directives.

    Returns
    -------
    bytes or None
        Guard macro name only when the first and last directives prove a wrapper.
    """
    if len(directives) < 3:
        return None
    first, second = directives[0], directives[1]
    if first[2] != b"ifndef" or second[2] != b"define":
        return None
    guard_parts = first[3].split()
    define_parts = second[3].split()
    guard = guard_parts[0] if len(guard_parts) == 1 else b""
    define = define_parts[0] if len(define_parts) == 1 else b""
    masked = _mask_comments(source)
    if (
        not guard
        or guard != define
        or masked[: first[0]].strip()
        or masked[first[1] : second[0]].strip()
    ):
        return None
    depth = 0
    closing_index: int | None = None
    for index, (_, _, kind, _) in enumerate(directives):
        if kind in {b"if", b"ifdef", b"ifndef"}:
            depth += 1
        elif kind == b"endif":
            depth -= 1
            if depth < 0:
                return None
            if depth == 0:
                closing_index = index
                break
        elif depth == 1 and kind in {b"else", b"elif"}:
            return None
    if closing_index != len(directives) - 1:
        return None
    last = directives[closing_index]
    if depth != 0 or last[3].strip() or masked[last[1] :].strip():
        return None
    return guard


def _definition_rows(
    source: bytes,
    source_path: str,
    source_sha256: str,
    available_after: int,
    source_order: int,
) -> tuple[
    tuple[MacroDefinition, ...],
    tuple[tuple[bytes, int, str, int, int], ...],
]:
    """Capture definitions and undefinitions outside unresolved conditions.

    Parameters
    ----------
    source : bytes
        Exact captured source or header bytes.
    source_path : str
        Repository relative path of the captured bytes.
    source_sha256 : str
        SHA-256 digest of those exact bytes.
    available_after : int
        Translation unit boundary at which a header becomes available.
    source_order : int
        Ordinal of the executed definition directive through nested includes.

    Returns
    -------
    tuple[
        tuple[MacroDefinition, ...],
        tuple[tuple[bytes, int, str, int, int], ...],
    ]
        Proven macro definitions and unsafe undef sites.
    """
    directives = _directive_rows(source)
    guard = _include_guard(source, directives)
    condition_stack: list[bytes | None] = []
    definitions: list[MacroDefinition] = []
    undefs: list[tuple[bytes, int, str, int, int]] = []
    for start, end, kind, payload in directives:
        if kind in {b"if", b"ifdef", b"ifndef"}:
            condition_stack.append(
                guard
                if kind == b"ifndef" and payload.split()[:1] == [guard] and guard
                else None
            )
            continue
        if kind in {b"elif", b"else"}:
            if condition_stack:
                condition_stack[-1] = None
            continue
        if kind == b"endif":
            if condition_stack:
                condition_stack.pop()
            continue
        if kind == b"undef":
            parts = payload.split()
            if parts:
                undef_boundary = start if source_path == "@source" else available_after
                undefs.append(
                    (parts[0], undef_boundary, source_path, start, source_order)
                )
            continue
        if kind != b"define":
            continue
        parsed = _DEFINE.match(payload)
        if parsed is None:
            continue
        name, parameter_text, _, replacement = parsed.groups()
        conditional = any(value is None for value in condition_stack)
        if conditional:
            unsafe_boundary = start if source_path == "@source" else available_after
            undefs.append((name, unsafe_boundary, source_path, start, source_order))
        parameters: tuple[bytes, ...] | None = None
        variadic = False
        if parameter_text is not None:
            parameter_body = parameter_text[1:-1]
            if parameter_body.strip():
                raw_parameters = [item.strip() for item in parameter_body.split(b",")]
                if raw_parameters and raw_parameters[-1] == b"...":
                    variadic = True
                    raw_parameters.pop()
                elif raw_parameters and raw_parameters[-1].endswith(b"..."):
                    variadic = True
                    raw_parameters[-1] = raw_parameters[-1][:-3].strip()
                if any(not _IDENTIFIER.fullmatch(item) for item in raw_parameters):
                    unsafe_boundary = (
                        start if source_path == "@source" else available_after
                    )
                    undefs.append(
                        (name, unsafe_boundary, source_path, start, source_order)
                    )
                    continue
                parameters = tuple(raw_parameters)
            else:
                parameters = ()
        try:
            replacement_tokens = _tokens(replacement)
        except ExpansionRejected:
            unsafe_boundary = start if source_path == "@source" else available_after
            undefs.append((name, unsafe_boundary, source_path, start, source_order))
            continue
        if any(token.spelling in {b"##", b"#"} for token in replacement_tokens):
            unsafe_boundary = start if source_path == "@source" else available_after
            undefs.append((name, unsafe_boundary, source_path, start, source_order))
            continue
        definition_start = start if source_path == "@source" else available_after
        definitions.append(
            MacroDefinition(
                name=name,
                parameters=parameters,
                variadic=variadic,
                replacement=replacement_tokens,
                source_path=source_path,
                source_sha256=source_sha256,
                source_order=source_order,
                conditional=conditional,
                replacement_sha256=hashlib.sha256(source[start:end]).hexdigest(),
                span=(start, end),
                available_after=definition_start,
            )
        )
    return tuple(definitions), tuple(undefs)


def _scan_invocations(
    source: bytes, names: frozenset[bytes]
) -> tuple[tuple[bytes, int, int, tuple[MacroToken, ...]], ...]:
    """Find balanced top level function-like macro invocations.

    Parameters
    ----------
    source : bytes
        Original translation unit.
    names : frozenset[bytes]
        Names with captured function-like definitions.

    Returns
    -------
    tuple[tuple[bytes, int, int, tuple[MacroToken, ...]], ...]
        Macro name, invocation span and argument tokens.
    """
    tokens = _tokens(source)
    protected = tuple((start, end) for start, end, _, _ in _directive_rows(source))
    braces = 0
    conditional_ranges: list[tuple[int, int]] = []
    condition_start: int | None = None
    condition_depth = 0
    for start, end, kind, _ in _directive_rows(source):
        if kind in {b"if", b"ifdef", b"ifndef"}:
            if condition_depth == 0:
                condition_start = end
            condition_depth += 1
        elif kind == b"endif" and condition_depth:
            condition_depth -= 1
            if condition_depth == 0 and condition_start is not None:
                conditional_ranges.append((condition_start, start))
                condition_start = None
    if condition_start is not None:
        conditional_ranges.append((condition_start, len(source)))
    result: list[tuple[bytes, int, int, tuple[MacroToken, ...]]] = []
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if token.start is None or token.end is None:
            index += 1
            continue
        if any(start <= token.start < end for start, end in protected) or any(
            start <= token.start < end for start, end in conditional_ranges
        ):
            index += 1
            continue
        if token.spelling == b"{":
            braces += 1
        elif token.spelling == b"}":
            braces = max(0, braces - 1)
        if (
            braces == 0
            and token.spelling in names
            and index + 1 < len(tokens)
            and tokens[index + 1].spelling == b"("
        ):
            depth = 0
            closing: int | None = None
            for position in range(index + 1, len(tokens)):
                spelling = tokens[position].spelling
                if spelling == b"(":
                    depth += 1
                elif spelling == b")":
                    depth -= 1
                    if depth == 0:
                        closing = position
                        break
            if closing is not None:
                opening = index + 1
                argument_tokens = tokens[opening + 1 : closing]
                result.append(
                    (
                        token.spelling,
                        token.start,
                        tokens[closing].end or token.end,
                        argument_tokens,
                    )
                )
                index = closing + 1
                continue
        index += 1
    return tuple(result)


def _split_arguments_with_commas(
    tokens: tuple[MacroToken, ...],
) -> tuple[tuple[tuple[MacroToken, ...], ...], tuple[MacroToken, ...]]:
    """Split invocation arguments at un-nested preprocessing commas.

    Parameters
    ----------
    tokens : tuple[MacroToken, ...]
        Tokens inside a macro invocation's outer parentheses.

    Returns
    -------
    tuple[tuple[tuple[MacroToken, ...], ...], tuple[MacroToken, ...]]
        Arguments and original comma tokens in source order.
    """
    if not tokens:
        return (), ()
    groups: list[list[MacroToken]] = [[]]
    commas: list[MacroToken] = []
    stack: list[bytes] = []
    pairs = {b"(": b")"}
    for token in tokens:
        spelling = token.spelling
        if spelling in pairs:
            stack.append(pairs[spelling])
        elif spelling == b")":
            if not stack or stack.pop() != spelling:
                raise ExpansionRejected("unbalanced macro argument delimiters")
        if spelling == b"," and not stack:
            commas.append(token)
            groups.append([])
        else:
            groups[-1].append(token)
    if stack:
        raise ExpansionRejected("unbalanced macro argument delimiters")
    return tuple(tuple(group) for group in groups), tuple(commas)


def _split_arguments(
    tokens: tuple[MacroToken, ...],
) -> tuple[tuple[MacroToken, ...], ...]:
    """Split preprocessing arguments using parenthesis nesting only.

    Parameters
    ----------
    tokens : tuple[MacroToken, ...]
        Tokens inside a macro invocation's outer parentheses.

    Returns
    -------
    tuple[tuple[MacroToken, ...], ...]
        Arguments in source order.
    """
    return _split_arguments_with_commas(tokens)[0]


class _Expander:
    """Resolve one translation unit's exact macro definitions and expansions."""

    def __init__(
        self,
        definitions: tuple[MacroDefinition, ...],
        undefs: tuple[tuple[bytes, int, str, int, int], ...],
        invocation: int,
        annotations: dict[bytes, int],
    ) -> None:
        """Initialize an invocation-local expansion environment.

        Parameters
        ----------
        definitions : tuple[MacroDefinition, ...]
            All proven definitions captured for this translation unit.
        undefs : tuple[tuple[bytes, int, str, int, int], ...]
            Unconditional undefinitions and their ordered source identities.
        invocation : int
            Original invocation byte offset.
        annotations : dict[bytes, int]
            Existing C parser annotation proofs and their availability offsets.

        Returns
        -------
        None
            Initializes the proven definitions and unresolved macro names.
        """
        self._definitions: dict[bytes, MacroDefinition] = {}
        self._used: dict[tuple[str, tuple[int, int]], MacroDefinition] = {}
        self._annotations = {
            name for name, available in annotations.items() if available <= invocation
        }
        self._annotation_inputs: dict[bytes, tuple[MacroDefinition, ...]] = {
            name: tuple(
                item
                for item in definitions
                if item.name == name
                and item.parameters is None
                and item.available_after <= invocation
            )
            for name in self._annotations
        }
        relevant = [
            item
            for item in definitions
            if item.available_after <= invocation and not item.conditional
        ]

        def definition_key(item: MacroDefinition) -> tuple[int, int, int]:
            """Order a definition by include boundary, header and directive."""
            return (item.available_after, item.source_order, item.span[0])

        invocation_key = (
            invocation,
            max((item.source_order for item in definitions), default=0),
            invocation,
        )
        by_name: dict[bytes, list[MacroDefinition]] = {}
        for definition in relevant:
            by_name.setdefault(definition.name, []).append(definition)
        for name, candidates in by_name.items():
            latest = max(definition_key(item) for item in candidates)
            selected = [item for item in candidates if definition_key(item) == latest]
            if len(selected) > 1:
                selected = [max(selected, key=lambda item: item.span[0])]
            fingerprints = {
                (
                    item.parameters,
                    item.variadic,
                    tuple(token.spelling for token in item.replacement),
                )
                for item in selected
            }
            if len(fingerprints) != 1:
                continue
            if any(
                undef_name == name
                and (undef_at, undef_order, undef_offset) <= invocation_key
                and (undef_at, undef_order, undef_offset) >= latest
                for undef_name, undef_at, _undef_path, undef_offset, undef_order in undefs
            ):
                continue
            self._definitions[name] = selected[-1]
        all_names = set(by_name) | {name for name, _, _, _, _ in undefs}
        self._unsafe_names: set[bytes] = set()
        for name in all_names:
            selected_definition = self._definitions.get(name)
            selected_key = (
                (-1, -1, -1)
                if selected_definition is None
                else definition_key(selected_definition)
            )
            if any(
                undef_name == name
                and (undef_at, undef_order, undef_offset) <= invocation_key
                and (
                    selected_definition is None
                    or (undef_at, undef_order, undef_offset) >= selected_key
                )
                for undef_name, undef_at, _, undef_offset, undef_order in undefs
            ):
                self._unsafe_names.add(name)
        self._annotations.difference_update(
            name
            for name, available, path_name, _, _ in undefs
            if path_name == "@unresolved"
            and available <= invocation
            and name not in self._definitions
        )

    def expand(
        self, tokens: tuple[MacroToken, ...], *, depth: int = 0
    ) -> tuple[MacroToken, ...]:
        """Expand every unambiguous object or function macro in the token list.

        Parameters
        ----------
        tokens : tuple[MacroToken, ...]
            Input preprocessing tokens.
        depth : int, optional
            Recursive expansion depth.

        Returns
        -------
        tuple[MacroToken, ...]
            Fully rescanned bounded output tokens.

        Raises
        ------
        ExpansionRejected
            If selection is ambiguous, cyclic, unsupported or over budget.
        """
        if depth > 32:
            raise ExpansionRejected("macro expansion depth exceeded")
        output: list[MacroToken] = []
        index = 0
        while index < len(tokens):
            token = tokens[index]
            definition = self._definitions.get(token.spelling)
            if definition is None:
                if token.spelling in self._unsafe_names:
                    if token.spelling not in self._annotations:
                        raise ExpansionRejected("nested macro state is unresolved")
                if token.spelling in self._annotations:
                    for annotation_input in self._annotation_inputs.get(
                        token.spelling, ()
                    ):
                        self._used[
                            (annotation_input.source_path, annotation_input.span)
                        ] = annotation_input
                output.append(token)
                index += 1
                continue
            arguments: tuple[tuple[MacroToken, ...], ...] = ()
            consumed = 1
            if definition.parameters is not None:
                if index + 1 >= len(tokens) or tokens[index + 1].spelling != b"(":
                    output.append(token)
                    index += 1
                    continue
                closing = _matching_paren(tokens, index + 1)
                if closing is None:
                    raise ExpansionRejected("unclosed nested macro invocation")
                arguments = _split_arguments(tokens[index + 2 : closing])
                consumed = closing - index + 1
                fixed = len(definition.parameters)
                if len(arguments) < fixed or (
                    not definition.variadic and len(arguments) != fixed
                ):
                    raise ExpansionRejected("macro argument count mismatch")
            self._used[(definition.source_path, definition.span)] = definition
            substitutions = (
                {}
                if definition.parameters is None
                else dict(zip(definition.parameters, arguments, strict=False))
            )
            if definition.variadic:
                fixed = len(definition.parameters or ())
                variadic = arguments[fixed:]
                _, commas = _split_arguments_with_commas(tokens[index + 2 : closing])
                substitutions[b"__VA_ARGS__"] = tuple(
                    item
                    for part_index, part in enumerate(variadic)
                    for item in (
                        (commas[fixed + part_index - 1],)
                        if part_index > 0 and fixed + part_index - 1 < len(commas)
                        else ()
                    )
                    + part
                )
            replacement: list[MacroToken] = []
            for part in definition.replacement:
                supplied = substitutions.get(part.spelling)
                if supplied is None:
                    replacement.append(MacroToken(part.spelling))
                else:
                    replacement.extend(supplied)
            expanded = self.expand(tuple(replacement), depth=depth + 1)
            output.extend(expanded)
            if (
                len(output) > _MAX_TOKENS
                or sum(len(item.spelling) for item in output) > _MAX_BYTES
            ):
                raise ExpansionRejected("macro expansion output bound exceeded")
            index += consumed
        return tuple(output)


def _matching_paren(tokens: tuple[MacroToken, ...], opening: int) -> int | None:
    """Find a matching right parenthesis by token nesting.

    Parameters
    ----------
    tokens : tuple[MacroToken, ...]
        Token stream containing the opening parenthesis.
    opening : int
        Index of its left parenthesis.

    Returns
    -------
    int or None
        Matching token index, or None when the group is incomplete.
    """
    depth = 0
    for index in range(opening, len(tokens)):
        if tokens[index].spelling == b"(":
            depth += 1
        elif tokens[index].spelling == b")":
            depth -= 1
            if depth == 0:
                return index
    return None


def _ordered_definition_rows(
    context: IncludeContext, root: Path, source_path: Path
) -> tuple[list[MacroDefinition], list[tuple[bytes, int, str, int, int]]]:
    """Replay captured include directives in preprocessing execution order.

    Parameters
    ----------
    context : IncludeContext
        Captured bytes and exact include lookup outcomes.
    root : pathlib.Path
        Containment boundary for captured header identities.
    source_path : pathlib.Path
        Original translation unit.

    Returns
    -------
    tuple[list[MacroDefinition], list[tuple[bytes, int, str, int, int]]]
        Definitions and unsafe events ordered through nested include sites.

    Raises
    ------
    ExpansionRejected
        If captured inputs cannot establish a bounded directive traversal.
    """
    root = root.resolve()
    source_name = source_path.resolve().relative_to(root).as_posix()
    sources = {
        item.path.relative_to(root).as_posix(): item.source for item in context.headers
    }
    sources[source_name] = context.source
    try:
        identity = json.loads(context.identity)
        lookups = {
            (owner, spelling, quoted): (status, target)
            for owner, spelling, quoted, status, target in identity["lookups"]
        }
        preincludes = identity["preinclude"]
    except (ValueError, KeyError, TypeError) as exc:
        raise ExpansionRejected("missing captured include execution inputs") from exc
    captured: dict[
        str,
        tuple[
            tuple[MacroDefinition, ...], tuple[tuple[bytes, int, str, int, int], ...]
        ],
    ] = {}
    names: set[bytes] = set()
    for owner, content in sources.items():
        if not _conditionals_balanced(content):
            raise ExpansionRejected("unbalanced captured directives")
        path_name = "@source" if owner == source_name else owner
        rows = _definition_rows(
            content, path_name, hashlib.sha256(content).hexdigest(), 0, 0
        )
        captured[owner] = rows
        names.update(item.name for item in rows[0])
        names.update(item[0] for item in rows[1])
    definitions: list[MacroDefinition] = []
    undefs: list[tuple[bytes, int, str, int, int]] = []
    states: dict[bytes, bool | None] = {}
    active: set[str] = set()
    once: set[str] = set()
    unknown_seen = False
    order = 0

    def walk(owner: str, boundary: int, uncertain: bool = False) -> None:
        """Replay one captured file with bounded nesting and guard state.

        Parameters
        ----------
        owner : str
            Captured repository relative file identity.
        boundary : int
            Translation unit include boundary, or minus one for the source.
        uncertain : bool, optional
            Whether an unresolved enclosing condition controls this traversal.

        Returns
        -------
        None
            Appends ordered definition and unsafe events.
        """
        nonlocal order, unknown_seen
        if owner not in sources or len(active) >= 64:
            raise ExpansionRejected("uncaptured or cyclic include traversal")
        if owner in once:
            return
        content = sources[owner]
        directives = _directive_rows(content)
        guard = _include_guard(content, directives) if boundary >= 0 else None
        if guard is not None:
            guard_state = states.get(guard, None if unknown_seen else False)
            if guard_state is True:
                return
            uncertain = uncertain or guard_state is None
        if owner in active:
            raise ExpansionRejected("unguarded include cycle")
        active.add(owner)
        by_offset = {item.span[0]: item for item in captured[owner][0]}
        unsafe_by_offset: dict[int, list[bytes]] = {}
        for name, _, _, offset, _ in captured[owner][1]:
            unsafe_by_offset.setdefault(offset, []).append(name)
        condition_stack: list[bool] = []
        for start, end, kind, payload in directives:
            order += 1
            if order > _MAX_TOKENS:
                raise ExpansionRejected("include directive traversal bound exceeded")
            available = start if boundary < 0 else boundary
            path_name = "@source" if boundary < 0 else owner
            if kind in {b"if", b"ifdef", b"ifndef"}:
                transparent = guard is not None and start == directives[0][0]
                condition_stack.append(not transparent)
                continue
            if kind in {b"else", b"elif"}:
                if condition_stack:
                    condition_stack[-1] = True
                continue
            if kind == b"endif":
                if condition_stack:
                    condition_stack.pop()
                continue
            conditional = uncertain or any(condition_stack)
            if kind in {b"include", b"include_next"}:
                raw = re.sub(rb"\\\r?\n", b"", payload).strip()
                quoted = raw.startswith(b'"') and raw.endswith(b'"')
                system = raw.startswith(b"<") and raw.endswith(b">")
                spelling = (raw[1:-1] if quoted or system else raw).decode(
                    "utf-8", "surrogateescape"
                )
                status, target = lookups.get(
                    (owner, spelling, True if quoted else False if system else None),
                    ("unknown", ""),
                )
                if status == "resolved" and target in sources:
                    walk(target, end if boundary < 0 else boundary, conditional)
                else:
                    # An uncaptured include can invalidate every known macro.
                    # Later proven definitions can restore individual names.
                    unknown_seen = True
                    for name in names:
                        states[name] = None
                        undefs.append((name, available, "@unresolved", start, order))
                continue
            if kind == b"pragma" and payload.strip() == b"once" and not conditional:
                once.add(owner)
            for name in unsafe_by_offset.get(start, ()):
                undefs.append((name, available, path_name, start, order))
                states[name] = None if conditional or kind != b"undef" else False
            item = by_offset.get(start)
            if item is not None:
                selected = replace(
                    item,
                    available_after=available,
                    source_order=order,
                    conditional=item.conditional or conditional,
                )
                definitions.append(selected)
                states[item.name] = None if selected.conditional else True
                if selected.conditional:
                    undefs.append((item.name, available, path_name, start, order))
        active.remove(owner)

    for owner in preincludes:
        walk(owner, 0)
    walk(source_name, -1)
    return definitions, undefs


def declaration_expansions(
    context: IncludeContext,
    root: Path,
    source_path: Path,
) -> tuple[ExpandedDeclaration, ...]:
    """Select and expand complete top-level declaration macro invocations.

    Parameters
    ----------
    context : IncludeContext
        Exact source and contained header snapshots for this translation unit.
    root : pathlib.Path
        Repository boundary used for provenance paths.
    source_path : pathlib.Path
        Source file whose byte coordinates anchor invocations.

    Returns
    -------
    tuple[ExpandedDeclaration, ...]
        Only invocations with complete bounded expansions; uncertain sites are
        omitted so callers preserve the original grammar diagnostic.
    """
    try:
        definitions, undefs = _ordered_definition_rows(context, root, source_path)
    except ExpansionRejected:
        return ()
    parser = _new_parser()
    annotation_inputs = _input_definitions(
        context.source,
        parser.parse(context.source).root_node,
        parser,
        tuple((header.source, header.available_after) for header in context.headers),
    )
    annotations = _resolve_annotations(annotation_inputs, parser)
    names = frozenset(
        {item.name for item in definitions if item.parameters is not None}
        | {name for name, _, _, _, _ in undefs}
    )
    candidates = _scan_invocations(context.source, names)
    if len(candidates) > _MAX_EXPANSIONS:
        return ()
    result: list[ExpandedDeclaration] = []
    for name, start, end, arguments_tokens in candidates:
        if start > end or end - start > _MAX_BYTES:
            continue
        try:
            expander = _Expander(tuple(definitions), tuple(undefs), start, annotations)
            outer = expander._definitions.get(name)
            if outer is not None and outer.parameters is None:
                outer = None
            if outer is None:
                continue
            invocation_args = _split_arguments(arguments_tokens)
            if any(
                token.start is None or token.end is None
                for argument in invocation_args
                for token in argument
            ):
                continue
            if len(invocation_args) < len(outer.parameters or ()) or (
                not outer.variadic
                and len(invocation_args) != len(outer.parameters or ())
            ):
                continue
            original_call = (
                MacroToken(name),
                MacroToken(b"("),
                *arguments_tokens,
                MacroToken(b")"),
            )
            expanded = expander.expand(tuple(original_call))
            rendered_parts: list[bytes] = []
            token_rows: list[tuple[bytes, tuple[int, int] | None, tuple[int, int]]] = []
            cursor = 0
            for token_index, token in enumerate(expanded):
                if token_index:
                    rendered_parts.append(b" ")
                    cursor += 1
                token_start = cursor
                rendered_parts.append(token.spelling)
                cursor += len(token.spelling)
                token_rows.append(
                    (
                        token.spelling,
                        (token.start, token.end)
                        if token.start is not None
                        and token.end is not None
                        and start <= token.start < token.end <= end
                        else None,
                        (token_start, cursor),
                    )
                )
            rendered = b"".join(rendered_parts)
            if not rendered or len(rendered) > _MAX_BYTES:
                continue
            following = context.source[end:]
            if following.lstrip().startswith(b";") and expanded[-1].spelling not in {
                b";",
                b"}",
            }:
                # The source terminator completes replacement declarations such
                # as a trailing extern object. It remains outside macro-token
                # provenance because it is not produced by the replacement.
                rendered += b" ;"
            chain = tuple(expander._used.values())
            if not chain or outer not in chain:
                continue
            result.append(
                ExpandedDeclaration(
                    start,
                    end,
                    name.decode("ascii"),
                    rendered,
                    tuple(token_rows),
                    chain,
                )
            )
        except (ExpansionRejected, UnicodeDecodeError, ValueError):
            continue
    return tuple(result)
