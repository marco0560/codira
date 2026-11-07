"""Expand explicitly selected declaration macros with source-token provenance.

Parameters
----------
None

Returns
-------
None
    Bounded token substitution; selecting active definitions remains the caller's
    responsibility. This module does not infer compiler flags or include order.
"""

from __future__ import annotations

import re
from typing import Literal
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace

_IDENTIFIER = re.compile(rb"[A-Za-z_][A-Za-z_0-9]*\Z")
_LEXEME = re.compile(
    rb"(?P<space>\s+|/\*.*?\*/|//[^\n]*)"
    rb"|(?P<literal>(?:u8|u|U|L)?(?:\"(?:[^\"\\\n]|\\[^\n])*\""
    rb"|'(?:[^'\\\n]|\\[^\n])*')(?:[A-Za-z_][A-Za-z_0-9]*)?)"
    rb"|(?P<number>(?:[0-9]|\.[0-9])(?:[eEpP][+-]|[A-Za-z_0-9.]|'[A-Za-z_0-9])*)"
    rb"|(?P<identifier>[A-Za-z_][A-Za-z_0-9]*)"
    rb"|(?P<punct>##|\.\.\.|<=>|<<=|>>=|->\*|::|->|\.\*|\+\+|--|&&|\|\||<<|>>"
    rb"|<=|>=|==|!=|[+*/%&|^!-]=|[{}\[\]().,;:?~!+*/%&|^<>=#-])",
    re.DOTALL,
)
_MAX_TOKENS = 32768
_MAX_STEPS = 4096
_MAX_DEPTH = 64
_MAX_SOURCE_BYTES = 262144
_RAW_STRING = re.compile(rb'(?:u8|u|U|L)?R"')


@dataclass(frozen=True)
class _MacroToken:
    """Carry a preprocessing token and its original translation-unit span.

    Parameters
    ----------
    spelling : bytes
        Semantic token spelling, possibly produced by stringification or paste.
    start : int
        Inclusive original byte offset.
    end : int
        Exclusive original byte offset.
    space_before : bool, optional
        Whether whitespace preceded this token, used by stringification.
    argument : bool, optional
        Whether the token carries an argument span rather than a template span.
    synthetic : bool, optional
        Whether the spelling was supplied or changed by macro replacement.
    unavailable : frozenset[bytes], optional
        Macro names suppressed during subsequent rescanning.
    operation : {'source', 'replacement', 'paste', 'stringify'}, optional
        Final derivation, separate from the original invocation/argument anchor.

    Returns
    -------
    None
        Immutable spelling and source provenance.
    """

    spelling: bytes
    start: int
    end: int
    space_before: bool = False
    argument: bool = False
    synthetic: bool = False
    unavailable: frozenset[bytes] = frozenset()
    operation: Literal["source", "replacement", "paste", "stringify"] = "source"


@dataclass(frozen=True)
class _MacroDefinition:
    """Describe one already selected object or function macro replacement.

    Parameters
    ----------
    parameters : tuple[bytes, ...] or None
        Fixed parameters, or None for an object macro.
    replacement : bytes
        Replacement-list bytes from the selected source definition.
    variadic : bool, optional
        Whether a function macro accepts a trailing ``__VA_ARGS__`` argument.
    opaque : bool, optional
        Whether only definedness is known. Such a macro cannot be expanded;
        parameters and replacement are not interpreted as a selected template.

    Returns
    -------
    None
        Definition independent of conditional selection and header discovery.
    """

    parameters: tuple[bytes, ...] | None
    replacement: bytes
    variadic: bool = False
    opaque: bool = False


def _macro_tokens(source: bytes, *, offset: int = 0) -> tuple[_MacroToken, ...]:
    """Tokenize a supported replacement or invocation without losing offsets.

    Parameters
    ----------
    source : bytes
        Original invocation or replacement-list bytes.
    offset : int, optional
        Original source offset of the supplied buffer.

    Returns
    -------
    tuple[_MacroToken, ...]
        Tokens with comments treated as whitespace and line splices removed.

    Raises
    ------
    ValueError
        If input contains unsupported lexical forms or exceeds the token bound.
    """
    if len(source) > _MAX_SOURCE_BYTES:
        raise ValueError("macro source byte limit exceeded")
    positions: list[int] = []
    unspliced = bytearray()
    cursor = 0
    while cursor < len(source):
        splice = re.match(rb"\\\r?\n", source[cursor : cursor + 3])
        if splice:
            cursor += splice.end()
            continue
        positions.append(cursor + offset)
        unspliced.append(source[cursor])
        cursor += 1
    logical = bytes(unspliced)
    result: list[_MacroToken] = []
    cursor = 0
    spaced = False
    while cursor < len(logical):
        if _RAW_STRING.match(logical, cursor):
            raise ValueError("raw string macro tokens are not supported")
        if logical[cursor : cursor + 2] in (b"<:", b":>", b"<%", b"%>", b"%:"):
            raise ValueError("digraph macro tokens are not supported")
        match = _LEXEME.match(logical, cursor)
        if (
            match is None
            or logical[cursor : cursor + 2] in (b"/*", b"//")
            and match.lastgroup != "space"
        ):
            raise ValueError("unsupported or unterminated macro token")
        if match.lastgroup == "space":
            spaced = True
        else:
            result.append(
                _MacroToken(
                    match[0],
                    positions[cursor],
                    positions[match.end() - 1] + 1,
                    space_before=spaced,
                )
            )
            spaced = False
            if len(result) > _MAX_TOKENS:
                raise ValueError("macro token limit exceeded")
        cursor = match.end()
    return tuple(result)


def _macro_arguments(
    tokens: list[_MacroToken], opening: int
) -> tuple[list[tuple[_MacroToken, ...]], int, tuple[_MacroToken, ...]]:
    """Split invocation arguments using preprocessing parentheses only.

    Parameters
    ----------
    tokens : list[_MacroToken]
        Token stream containing an invocation.
    opening : int
        Index of its opening parenthesis.

    Returns
    -------
    tuple[list[tuple[_MacroToken, ...]], int, tuple[_MacroToken, ...]]
        Raw arguments, closing-parenthesis index and original separator tokens.

    Raises
    ------
    ValueError
        If the invocation is not terminated.
    """
    result: list[tuple[_MacroToken, ...]] = []
    separators: list[_MacroToken] = []
    start = opening + 1
    depth = 0
    for index in range(start, len(tokens)):
        spelling = tokens[index].spelling
        if spelling == b"(":
            depth += 1
        elif spelling == b")":
            if depth == 0:
                result.append(tuple(tokens[start:index]))
                return result, index, tuple(separators)
            depth -= 1
        elif spelling == b"," and depth == 0:
            result.append(tuple(tokens[start:index]))
            separators.append(tokens[index])
            start = index + 1
    raise ValueError("unterminated macro invocation")


def _stringify(tokens: tuple[_MacroToken, ...]) -> bytes:
    """Stringify raw argument tokens with preprocessing whitespace rules.

    Parameters
    ----------
    tokens : tuple[_MacroToken, ...]
        Unexpanded argument tokens.

    Returns
    -------
    bytes
        Quoted string token with escaped literal quotes and backslashes.
    """
    result = bytearray(b'"')
    for index, token in enumerate(tokens):
        if index and token.space_before:
            result.extend(b" ")
        spelling = token.spelling
        if b'"' in spelling or b"'" in spelling:
            spelling = spelling.replace(b"\\", b"\\\\").replace(b'"', b'\\"')
        result.extend(spelling)
    result.extend(b'"')
    return bytes(result)


def _paste_tokens(left: _MacroToken, right: _MacroToken) -> _MacroToken:
    """Paste two tokens, including empty argument placemarkers.

    Parameters
    ----------
    left : _MacroToken
        Left operand, possibly an empty placemarker.
    right : _MacroToken
        Right operand, possibly an empty placemarker.

    Returns
    -------
    _MacroToken
        Single validated token, anchored to argument spans when available.

    Raises
    ------
    ValueError
        If concatenation does not produce exactly one supported token.
    """
    spelling = left.spelling + right.spelling
    if spelling:
        parsed = _macro_tokens(spelling)
        if len(parsed) != 1 or parsed[0].spelling != spelling:
            raise ValueError("macro paste does not form one preprocessing token")
    origins = [token for token in (left, right) if token.argument and token.spelling]
    if not origins:
        origins = [left, right]
    return _MacroToken(
        spelling,
        min(token.start for token in origins),
        max(token.end for token in origins),
        space_before=left.space_before,
        argument=bool(left.argument or right.argument),
        synthetic=True,
        unavailable=left.unavailable & right.unavailable,
        operation="paste",
    )


OpaqueMacroResolver = Callable[
    [tuple[_MacroToken, ...]], tuple[_MacroToken, ...] | None
]


class _MacroExpander:
    """Bound expansion work across rescanning and nested argument prescans.

    Parameters
    ----------
    definitions : Mapping[bytes, _MacroDefinition]
        Unambiguous active macro definitions selected by the caller.
    opaque_resolver : OpaqueMacroResolver or None, optional
        Explicit intrinsic answers during conditional expansion only.

    Returns
    -------
    None
        One expansion budget shared by recursive argument processing.
    """

    def __init__(
        self,
        definitions: Mapping[bytes, _MacroDefinition],
        *,
        opaque_resolver: OpaqueMacroResolver | None = None,
    ) -> None:
        """Snapshot definitions and initialize the shared substitution budget.

        Parameters
        ----------
        definitions : Mapping[bytes, _MacroDefinition]
            Selected object and function definitions.
        opaque_resolver : OpaqueMacroResolver or None, optional
            Source/profile-licensed scalar answers after ordinary macro rescan.

        Returns
        -------
        None
            Initializes independent expansion state.

        Raises
        ------
        ValueError
            If names, parameters or replacement operators are unsupported.
        """
        self.definitions = dict(definitions)
        self.opaque_resolver = opaque_resolver
        self.templates: dict[bytes, tuple[_MacroToken, ...]] = {}
        self.steps = 0
        self.used: set[bytes] = set()
        for name, definition in self.definitions.items():
            parameters = definition.parameters
            if not _IDENTIFIER.fullmatch(name) or name == b"__VA_ARGS__":
                raise ValueError("invalid macro name")
            if definition.opaque:
                continue
            if definition.variadic and parameters is None:
                raise ValueError("an object macro cannot be variadic")
            if parameters is not None and (
                len(set(parameters)) != len(parameters)
                or any(not _IDENTIFIER.fullmatch(parameter) for parameter in parameters)
                or b"__VA_ARGS__" in parameters
            ):
                raise ValueError("invalid macro parameters")
            template = _macro_tokens(definition.replacement)
            names = set(parameters or ())
            if definition.variadic:
                names.add(b"__VA_ARGS__")
            for index, token in enumerate(template):
                if token.spelling == b"__VA_OPT__":
                    raise ValueError(
                        "__VA_OPT__ requires unsupported dialect semantics"
                    )
                if token.spelling == b"__VA_ARGS__" and not definition.variadic:
                    raise ValueError("variadic token outside a variadic macro")
                if token.spelling == b"##" and index in (0, len(template) - 1):
                    raise ValueError("paste operator at replacement boundary")
                if (
                    token.spelling == b"#"
                    and parameters is not None
                    and (
                        index + 1 == len(template)
                        or template[index + 1].spelling not in names
                    )
                ):
                    raise ValueError("stringification requires a macro parameter")
                if (
                    token.spelling == b"##"
                    and index
                    and template[index - 1].spelling == b"##"
                ):
                    raise ValueError("adjacent paste operators")
                if (
                    token.spelling == b"##"
                    and index
                    and template[index - 1].spelling == b","
                    and index + 1 < len(template)
                    and template[index + 1].spelling == b"__VA_ARGS__"
                ):
                    raise ValueError("GNU comma elision is not supported")
            self.templates[name] = template

    def expand(
        self, tokens: tuple[_MacroToken, ...], depth: int = 0
    ) -> tuple[_MacroToken, ...]:
        """Expand and rescan tokens under the shared deterministic work bounds.

        Parameters
        ----------
        tokens : tuple[_MacroToken, ...]
            Original tokens or argument tokens to prescan.
        depth : int, optional
            Current argument-prescan nesting depth.

        Returns
        -------
        tuple[_MacroToken, ...]
            Expanded tokens retaining original spans and suppression sets.

        Raises
        ------
        ValueError
            If arity, token syntax or a configured work bound is violated.
        """
        if depth > _MAX_DEPTH or len(tokens) > _MAX_TOKENS:
            raise ValueError("macro expansion nesting or token limit exceeded")
        work = list(tokens)
        index = 0
        while index < len(work):
            token = work[index]
            name = token.spelling
            definition = self.definitions.get(name)
            if definition is None or name in token.unavailable:
                index += 1
                continue
            if definition.opaque:
                if (
                    self.opaque_resolver is not None
                    and index + 1 < len(work)
                    and work[index + 1].spelling == b"("
                ):
                    _, closing, _ = _macro_arguments(work, index + 1)
                    answer = self.opaque_resolver(tuple(work[index : closing + 1]))
                    if answer is not None:
                        self.steps += 1
                        self.used.add(name)
                        if self.steps > _MAX_STEPS:
                            raise ValueError(
                                "macro expansion substitution limit exceeded"
                            )
                        work[index : closing + 1] = answer
                        if len(work) > _MAX_TOKENS:
                            raise ValueError("macro expansion token limit exceeded")
                        continue
                raise ValueError("macro replacement is unavailable")
            end = index
            arguments: list[tuple[_MacroToken, ...]] = []
            separators: tuple[_MacroToken, ...] = ()
            if definition.parameters is not None:
                if index + 1 == len(work) or work[index + 1].spelling != b"(":
                    index += 1
                    continue
                arguments, end, separators = _macro_arguments(work, index + 1)
            self.steps += 1
            self.used.add(name)
            if self.steps > _MAX_STEPS:
                raise ValueError("macro expansion substitution limit exceeded")
            hidden = token.unavailable
            if definition.parameters is not None:
                hidden &= work[end].unavailable
            hidden |= {name}
            replacement = self._substitute(
                name, arguments, separators, token, work[end], depth
            )
            replacement = tuple(
                replace(item, unavailable=item.unavailable | hidden)
                for item in replacement
            )
            if replacement:
                replacement = (
                    replace(replacement[0], space_before=token.space_before),
                    *replacement[1:],
                )
            elif end + 1 < len(work) and token.space_before:
                work[end + 1] = replace(work[end + 1], space_before=True)
            work[index : end + 1] = replacement
            if len(work) > _MAX_TOKENS:
                raise ValueError("macro expansion token limit exceeded")
        return tuple(work)

    def _substitute(
        self,
        name: bytes,
        arguments: list[tuple[_MacroToken, ...]],
        separators: tuple[_MacroToken, ...],
        invocation: _MacroToken,
        closing: _MacroToken,
        depth: int,
    ) -> tuple[_MacroToken, ...]:
        """Substitute arguments before paste and rescan a selected template.

        Parameters
        ----------
        name : bytes
            Selected macro name.
        arguments : list[tuple[_MacroToken, ...]]
            Unexpanded arguments; empty for object macros.
        separators : tuple[_MacroToken, ...]
            Original top-level comma tokens, retained for variadic provenance.
        invocation : _MacroToken
            Macro name token carrying invocation provenance.
        closing : _MacroToken
            Closing parenthesis or object macro token.
        depth : int
            Current prescan nesting depth.

        Returns
        -------
        tuple[_MacroToken, ...]
            Replacement with paste completed and placemarkers removed.

        Raises
        ------
        ValueError
            If argument arity or token pasting is invalid.
        """
        definition = self.definitions[name]
        parameters = definition.parameters
        actual: dict[bytes, tuple[_MacroToken, ...]] = {}
        if parameters is not None:
            if not parameters and arguments == [()] and not definition.variadic:
                arguments = []
            if len(arguments) < len(parameters) or (
                not definition.variadic and len(arguments) != len(parameters)
            ):
                raise ValueError("macro argument arity mismatch")
            actual.update(zip(parameters, arguments, strict=False))
            if definition.variadic:
                variadic: list[_MacroToken] = []
                for ordinal, argument in enumerate(arguments[len(parameters) :]):
                    if ordinal:
                        variadic.append(separators[len(parameters) + ordinal - 1])
                    variadic.extend(argument)
                actual[b"__VA_ARGS__"] = tuple(variadic)
        template = self.templates[name]
        expanded: dict[bytes, tuple[_MacroToken, ...]] = {}
        pieces: list[tuple[bool, tuple[_MacroToken, ...]]] = []
        index = 0
        while index < len(template):
            token = template[index]
            spelling = token.spelling
            if spelling == b"##":
                pieces.append((True, ()))
                index += 1
                continue
            if spelling == b"#" and parameters is not None:
                index += 1
                raw = actual[template[index].spelling]
                value = _MacroToken(
                    _stringify(raw),
                    raw[0].start if raw else invocation.start,
                    raw[-1].end if raw else closing.end,
                    space_before=token.space_before,
                    argument=bool(raw),
                    synthetic=True,
                    operation="stringify",
                )
                pieces.append((False, (value,)))
            elif spelling in actual:
                pasted = (index > 0 and template[index - 1].spelling == b"##") or (
                    index + 1 < len(template) and template[index + 1].spelling == b"##"
                )
                if not pasted and spelling not in expanded:
                    expanded[spelling] = self.expand(actual[spelling], depth + 1)
                values = actual[spelling] if pasted else expanded[spelling]
                values = tuple(replace(item, argument=True) for item in values)
                if values:
                    values = (
                        replace(values[0], space_before=token.space_before),
                        *values[1:],
                    )
                else:
                    values = (
                        _MacroToken(
                            b"",
                            invocation.start,
                            closing.end,
                            space_before=token.space_before,
                        ),
                    )
                pieces.append((False, values))
            else:
                pieces.append(
                    (
                        False,
                        (
                            _MacroToken(
                                spelling,
                                invocation.start,
                                closing.end,
                                space_before=token.space_before,
                                synthetic=True,
                                operation="replacement",
                            ),
                        ),
                    )
                )
            index += 1
        result: list[_MacroToken] = []
        paste = False
        for operator, values in pieces:
            if operator:
                paste = True
            elif paste:
                left = result.pop()
                result.append(_paste_tokens(left, values[0]))
                result.extend(values[1:])
                paste = False
            else:
                result.extend(values)
        nonempty: list[_MacroToken] = []
        spaced = False
        for token in result:
            spaced |= token.space_before
            if token.spelling:
                nonempty.append(replace(token, space_before=spaced))
                spaced = False
        return tuple(nonempty)


def _expand_macro_tokens(
    source: bytes, definitions: Mapping[bytes, _MacroDefinition], *, offset: int = 0
) -> tuple[_MacroToken, ...]:
    """Expand source tokens using explicitly selected macro definitions.

    Parameters
    ----------
    source : bytes
        Invocation bytes, without preprocessor directives.
    definitions : Mapping[bytes, _MacroDefinition]
        Active definitions; unknown identifiers remain unchanged.
    offset : int, optional
        Original translation-unit offset of the invocation buffer.

    Returns
    -------
    tuple[_MacroToken, ...]
        Fully rescanned supported tokens retaining original byte provenance.

    Raises
    ------
    ValueError
        If expansion encounters unsupported syntax or exceeds bounded work.
    """
    return _MacroExpander(definitions).expand(_macro_tokens(source, offset=offset))
